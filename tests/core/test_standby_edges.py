from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.app import create_app
from nowa.core import booking, flows
from nowa.db import write_tx
from tests.core.support import DAY, move
from tests.core.test_standby import cancel, full, join, offer_code, rows
from tests.web.support import ORIGIN, fields


def test_offer_taken_after_booking_cutoff_is_refused(engine):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    move(clock, 10 * 60 + 50)  # 22:50, nine minutes before the admission cutoff.
    cancel(engine, clock, ids[0])
    code = offer_code(engine, a.standby_id)
    clock.advance(minutes=10)
    with write_tx(engine) as conn:
        assert standby.take_in_tx(conn, clock, code).reason == "booking_closed"
    assert [r["state"] for r in rows(engine)] == ["expired", "waiting"]


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_expired_link_renders_next_day_without_booking(engine, lang):
    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    cancel(engine, clock, ids[0])
    code = offer_code(engine, a.standby_id)
    with TestClient(create_app(engine, clock=clock)) as client:
        page = client.get(f"/s/{code}/take?lang={lang}")
        data = fields(page, "/take") | {"action": "take"}
        clock.advance(minutes=20)
        late = client.get(f"/s/{code}/take?lang={lang}")
        assert late.status_code == 200 and "?day=" in late.text
        assert 'name="action"' not in late.text
        assert rows(engine)[0]["state"] == "offered"  # GET never mutates.
        client.post(f"/s/{code}/take", data=data, headers=ORIGIN)
        assert [r["state"] for r in rows(engine)] == ["expired", "offered"]


def test_change_day_frees_original_day(engine):
    cid, eid, clock, ids = full(engine)
    join(engine, clock, cid)
    with engine.connect() as conn:
        phone = conn.execute(
            select(s.contacts.c.phone_e164).join(s.bookings).where(s.bookings.c.id == ids[0])
        ).scalar_one()
    result = flows.change_day(
        engine, clock, booking.link_code_for(ids[0]), phone[-4:], DAY + timedelta(days=2), "change"
    )
    assert isinstance(result, booking.ChangeDayResult)
    assert rows(engine)[0]["state"] == "offered"


def test_offer_enqueue_failure_rolls_back_cancellation(engine, monkeypatch):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    join(engine, clock, cid)

    def broken(*args, **kwargs):
        raise RuntimeError("fictional enqueue failure")

    monkeypatch.setattr(standby, "enqueue_message", broken)
    with pytest.raises(RuntimeError, match="fictional"):
        cancel(engine, clock, ids[0])
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.bookings.c.state).where(s.bookings.c.id == ids[0])).scalar_one()
            == "booked"
        )
    assert rows(engine)[0]["state"] == "waiting"


def test_worker_will_not_send_ended_offer(engine):
    from nowa.core.timers import TimerContext
    from nowa.messaging.pipeline import send_retry

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    cancel(engine, clock, ids[0])
    clock.advance(minutes=20)
    with write_tx(engine) as conn:
        oid = conn.execute(
            select(s.outbox.c.id).where(s.outbox.c.standby_id == a.standby_id)
        ).scalar_one()
        ctx = TimerContext(conn, clock, cid, 1, "send_retry", clock.now(cid), 1, clock.now(cid))
        send_retry(ctx, {"outbox_id": oid, "attempt": 1})
        assert not ctx.after_commit
        assert (
            conn.execute(select(s.outbox.c.status).where(s.outbox.c.id == oid)).scalar_one()
            == "failed"
        )


def test_standby_migration_single_head_and_postgres_ddl():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    from nowa.__main__ import migration_config

    assert ScriptDirectory.from_config(migration_config()).get_heads() == ["31"]
    path = Path(__file__).resolve().parents[2] / "migrations/versions/29_standbys.py"
    spec = importlib.util.spec_from_file_location("standby_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    ctx = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    module.op = Operations(ctx)
    module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE standbys" in sql and "REFERENCES standbys" in sql
    assert "standby_expire" in sql and "standby_contact" in sql


def test_failed_standby_delivery_uses_shared_doctor_alert_once(engine):
    from nowa.messaging.outbox import alert_failure

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    cancel(engine, clock, ids[0])
    with write_tx(engine) as conn:
        row = (
            conn.execute(select(s.outbox).where(s.outbox.c.standby_id == a.standby_id))
            .mappings()
            .one()
        )
        alert_failure(conn, clock, row)
        alert_failure(conn, clock, row)
        alerts = (
            conn.execute(
                select(s.outbox).where(
                    s.outbox.c.idempotency_key == row["idempotency_key"] + ":alert:doctor"
                )
            )
            .mappings()
            .all()
        )
        assert len(alerts) == 1
        assert "انتظار 1" in alerts[0]["body"]
        assert alerts[0]["audience"] == "doctor"
