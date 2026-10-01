import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, StatementError

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, FrozenClock
from nowa.config import get_settings
from nowa.core.ratelimit import hit
from nowa.core.timers import TimerContext, cancel_timer, schedule_timer
from nowa.db import write_tx
from nowa.web.request import client_ip
from nowa.web.templates import environment


def test_clock_and_live_offsets(engine, clinic_id, frozen_clock, offset_clock):
    base = frozen_clock.now(clinic_id)
    assert base.tzinfo == CAIRO
    frozen_clock.advance(minutes=7.5)
    assert frozen_clock.now(clinic_id) == base + timedelta(minutes=7.5)
    for offset in (60, 120):
        with write_tx(engine) as conn:
            conn.execute(
                s.clinics.update()
                .where(s.clinics.c.id == clinic_id)
                .values(is_sandbox=True, clock_offset_s=offset)
            )
        assert offset_clock.now(clinic_id) == frozen_clock.now(clinic_id) + timedelta(
            seconds=offset
        )
        assert offset_clock.base_now() == frozen_clock.base_now()
    with pytest.raises(NoResultFound):
        offset_clock.now(99999)
    with pytest.raises(ValueError, match="aware"):
        FrozenClock(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "stamp",
    [
        datetime(2026, 4, 23, 23, 30, tzinfo=CAIRO),
        datetime(2026, 4, 24, 1, 30, tzinfo=CAIRO),
        datetime(2026, 10, 29, 23, 30, tzinfo=CAIRO, fold=0),
        datetime(2026, 10, 29, 23, 30, tzinfo=CAIRO, fold=1),
    ],
)
def test_utc_roundtrip(engine, clinic_id, stamp):
    with write_tx(engine) as conn:
        conn.execute(
            s.pending_signups.insert().values(
                mobile_e164="+201000000099", created_at=stamp, expires_at=stamp
            )
        )
    with engine.connect() as conn:
        actual = conn.execute(select(s.pending_signups.c.created_at)).scalar_one()
        assert actual == stamp.astimezone(UTC)
        assert actual.tzinfo == UTC
        raw = conn.exec_driver_sql("SELECT created_at FROM pending_signups").scalar_one()
        assert raw.startswith(stamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    with pytest.raises(StatementError), write_tx(engine) as conn:
        conn.execute(
            s.pending_signups.insert().values(
                mobile_e164="+201000000098", created_at=stamp.replace(tzinfo=None), expires_at=stamp
            )
        )


def test_timers_idempotency_cancel_and_rollback(engine, clinic_id, frozen_clock):
    due = frozen_clock.now(clinic_id)
    with write_tx(engine) as conn:
        first = schedule_timer(conn, clinic_id, "leave_now_check", due, {"booking_id": 1}, "timer1")
        second = schedule_timer(
            conn, clinic_id, "silent_check", due + timedelta(hours=2), {"booking_id": 2}, "timer1"
        )
        assert first == second
        assert (
            schedule_timer(conn, clinic_id, "unknown", due, {"invalid": "text"}, "timer1") == first
        )
        row = conn.execute(select(s.timers)).mappings().one()
        assert row["due_at"] == due
        assert row["payload_json"] == {"booking_id": 1}
        assert row["kind"] == "leave_now_check"
        assert row["status"] == "pending" and row["attempts"] == 0
        assert cancel_timer(conn, "timer1")
        assert not cancel_timer(conn, "timer1")
        assert not cancel_timer(conn, "unknown")
        for status in ("running", "done", "failed"):
            conn.execute(s.timers.update().where(s.timers.c.id == first).values(status=status))
            assert not cancel_timer(conn, "timer1")
            assert conn.execute(select(s.timers.c.status)).scalar_one() == status
        a = TimerContext(conn, frozen_clock, clinic_id, first, "silent_check", due, 1, due)
        b = TimerContext(conn, frozen_clock, clinic_id, first, "silent_check", due, 1, due)
        a.after_commit.append(lambda: None)
        assert b.after_commit == []
    with pytest.raises(RuntimeError), write_tx(engine) as conn:
        schedule_timer(conn, clinic_id, "send_retry", due, {"outbox_id": 2}, "rollback")
        raise RuntimeError("rollback")
    with engine.connect() as conn:
        assert len(conn.execute(select(s.timers)).all()) == 1


@pytest.mark.parametrize(
    "value",
    ["patient text", "+201000000000", {"name": "patient"}, [1], float("nan"), float("inf"), True],
)
def test_timer_rejects_non_numeric_payload(engine, clinic_id, frozen_clock, value):
    with pytest.raises(ValueError), write_tx(engine) as conn:
        schedule_timer(
            conn, clinic_id, "silent_check", frozen_clock.now(clinic_id), {"data": value}, "bad"
        )


def check_ratelimit(engine, clock):
    raw = "192.0.2.9"
    with write_tx(engine) as conn:
        assert hit(conn, clock, "login", raw, 60, 2)
        assert hit(conn, clock, "login", raw, 60, 2)
        assert not hit(conn, clock, "login", raw, 60, 2)
        assert hit(conn, clock, "reset", raw, 60, 2)
        rows = conn.execute(select(s.rate_counters)).mappings().all()
        assert raw not in str(rows)
        row = next(row for row in rows if row["scope"] == "login")
        assert row["count"] == 3
        assert (
            row["key_hash"]
            == hmac.new(
                get_settings().server_secret.encode(), f"login|{raw}".encode(), hashlib.sha256
            ).hexdigest()
        )
        clock.advance(minutes=1)
        assert hit(conn, clock, "login", raw, 60, 2)
        assert len(conn.execute(select(s.rate_counters)).all()) == 3
        clock.advance(minutes=24 * 60)
        # At exactly 24h after the first window ends, that row is retained.
        hit(conn, clock, "login", raw, 60, 2)
        assert (
            len(
                conn.execute(
                    select(s.rate_counters).where(s.rate_counters.c.scope == "login")
                ).all()
            )
            == 3
        )
        clock.advance(minutes=1)
        hit(conn, clock, "login", raw, 60, 2)
        starts = (
            conn.execute(
                select(s.rate_counters.c.window_start).where(s.rate_counters.c.scope == "login")
            )
            .scalars()
            .all()
        )
        assert row["window_start"] not in starts
        assert (
            len(
                conn.execute(
                    select(s.rate_counters).where(s.rate_counters.c.scope == "reset")
                ).all()
            )
            == 1
        )


def test_ratelimit(engine, frozen_clock):
    check_ratelimit(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_ratelimit(postgres_engine, frozen_clock):
    check_ratelimit(postgres_engine, frozen_clock)


def test_ratelimit_uses_row_window_length(engine, frozen_clock):
    with write_tx(engine) as conn:
        hit(conn, frozen_clock, "mixed", "long", 3600, 1)
        hit(conn, frozen_clock, "mixed", "short", 60, 1)
        frozen_clock.advance(minutes=24 * 60 + 2)
        hit(conn, frozen_clock, "mixed", "new", 60, 1)
        rows = conn.execute(select(s.rate_counters)).mappings().all()
        assert sorted(row["window_s"] for row in rows) == [60, 3600]


def test_ratelimit_rollback(engine, frozen_clock):
    with pytest.raises(RuntimeError), write_tx(engine) as conn:
        hit(conn, frozen_clock, "rollback", "test", 60, 1)
        raise RuntimeError("rollback")
    with write_tx(engine) as conn:
        assert hit(conn, frozen_clock, "rollback", "test", 60, 1)


@pytest.mark.parametrize(
    "hops, header, expected",
    [
        (0, "1.1.1.1", "192.0.2.10"),
        (1, "1.1.1.1, 2.2.2.2", "2.2.2.2"),
        (1, None, "192.0.2.10"),
        (2, "1.1.1.1, 2.2.2.2, 3.3.3.3", "2.2.2.2"),
        (2, "1.1.1.1, 2.2.2.2", "1.1.1.1"),
        (2, "1.1.1.1", "192.0.2.10"),
        (1, " 1.1.1.1 ", "1.1.1.1"),
    ],
)
def test_client_ip(monkeypatch, hops, header, expected):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", str(hops))
    request = Request(
        {
            "type": "http",
            "client": ("192.0.2.10", 1234),
            "headers": [(b"x-forwarded-for", header.encode())] if header else [],
        }
    )
    assert client_ip(request) == expected


def test_template_escaping():
    assert environment.autoescape is True
    assert environment.from_string("{{ text }}").render(text="<script>") == "&lt;script&gt;"


def test_records_clock_commit_model_and_usage(
    engine, clinic_id, frozen_clock, offset_clock, monkeypatch
):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "test-commit")
    with write_tx(engine) as conn:
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic_id)
            .values(is_sandbox=True, clock_offset_s=86400)
        )
    record.configure(offset_clock)
    with write_tx(engine) as conn:
        record.write_action(conn, clinic_id, "system", "test", model="test-model")
        record.record_usage(conn, clinic_id, None, "sms", 2, 0.012)
        record.record_usage(conn, clinic_id, "", "sms", 1, 0.006)
        record.record_usage(conn, clinic_id, "judge-key", "ai", 1, 0.5)
        action = conn.execute(select(s.action_record)).mappings().one()
        assert action["at"] == frozen_clock.now(clinic_id) + timedelta(days=1)
        assert action["commit"] == "test-commit" and action["model"] == "test-model"
        row = conn.execute(select(s.usage).where(s.usage.c.service == "sms")).mappings().one()
        assert row["date"] == frozen_clock.base_now().date()
        assert row["judge_id"] == "" and row["units"] == 3
        assert row["est_cost_usd"] == pytest.approx(0.018)
        frozen_clock.advance(minutes=24 * 60)
        record.record_usage(conn, clinic_id, None, "sms", 1, 0.006)
        assert len(conn.execute(select(s.usage)).all()) == 3


def test_action_for_uncommitted_clinic_uses_transaction_connection(engine, offset_clock):
    record.configure(offset_clock)
    with write_tx(engine) as conn:
        clinic = int(
            conn.execute(
                s.clinics.insert()
                .values(
                    slug="dr-transaction",
                    name="Fictional clinic",
                    specialty="cardiology",
                    address="Fictional address",
                    lat=30.0,
                    lng=31.0,
                    phone="01000000098",
                    is_sandbox=True,
                    clock_offset_s=120,
                )
                .returning(s.clinics.c.id)
            ).scalar_one()
        )
        action_id = record.write_action(conn, clinic, "doctor", "signup_complete")
        assert conn.execute(
            select(s.action_record.c.at).where(s.action_record.c.id == action_id)
        ).scalar_one() == offset_clock.base_now() + timedelta(seconds=120)
        with pytest.raises(NoResultFound):
            record.write_action(conn, 99999999, "doctor", "signup_complete")
    with engine.connect() as conn:
        assert conn.execute(
            select(s.action_record.c.id).where(s.action_record.c.id == action_id)
        ).scalar_one() == action_id
