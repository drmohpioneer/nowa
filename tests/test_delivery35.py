from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from nowa import schema as s
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.messaging.adapters import ADAPTERS, TelegramAdapter
from nowa.messaging.pipeline import send_retry
from tests.test_messaging import BLANKS, NOW, FakeAdapter, enqueue, handle, link, row, signup
from tests.test_messaging import prepared as prepared


def urgent(p, template="2", key="urgent", **kwargs):
    blanks = dict(BLANKS)
    for field in ("expected_time", "link"):
        blanks.pop(field)
    if template == "2":
        blanks.pop("day")
        blanks.update(leave_by=NOW, arrive_by=NOW + timedelta(minutes=30), on_my_way_link="/w/test")
    else:
        blanks.update(rebook_link="/r/test")
    return enqueue(p, key=key, template_id=template, blanks=blanks, **kwargs)


@pytest.mark.parametrize(
    "error,outcome",
    [
        (httpx.ConnectError, "refused"),
        (httpx.ConnectTimeout, "refused"),
        (httpx.PoolTimeout, "refused"),
        (httpx.ReadTimeout, "unknown"),
        (httpx.RemoteProtocolError, "unknown"),
        (ValueError, "unknown"),
    ],
)
def test_transport_failures(error, outcome):
    get_settings().telegram_bot_token = "fictional-token"

    def respond(request):
        raise error("fictional")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = TelegramAdapter(client).send({"chat_id": "1", "body": "test"})
    assert result.outcome == outcome
    if outcome == "refused":
        assert result.error == "connect_error"


def test_retries_count_ten_not_thirty(prepared, monkeypatch):
    p = prepared
    fake = FakeAdapter("refused")
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    for i in range(10):
        oid = enqueue(p, key=f"row:{i}")
        for attempt in range(1, 4):
            handle(p, send_retry, oid, attempt)
    fake.outcome = "accepted"
    oid = enqueue(p, key="eleventh")
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == "delivered"
    with p.engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.outbox)
                .where(s.outbox.c.first_attempt_at.is_not(None))
            ).scalar_one()
            == 11
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.action_record)
                .where(s.action_record.c.kind == "send_attempt")
            ).scalar_one()
            == 31
        )


@pytest.mark.parametrize(
    "template,state,superseded",
    [
        ("1", "cancelled", True),
        ("2", "cancelled", True),
        ("2", "seen", True),
        ("4", "cancelled", False),
    ],
)
def test_superseded_booking_messages(prepared, monkeypatch, template, state, superseded):
    p = prepared
    fake = FakeAdapter()
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    oid = enqueue(p) if template == "1" else urgent(p, template)
    with write_tx(p.engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == p.bid).values(state=state))
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == ("superseded" if superseded else "delivered")
    assert len(fake.rows) == (0 if superseded else 1)


def test_clinic_brake_exempts_leave_cancel_and_one_alert(prepared):
    p = prepared
    for i in range(32):
        handle(p, send_retry, enqueue(p, key=f"ordinary:{i}"))
    for template in ("2", "4"):
        oid = urgent(p, template, key=template)
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == "delivered"
    with p.engine.connect() as conn:
        alerts = (
            conn.execute(
                select(s.outbox.c.id).where(s.outbox.c.template_id == "op:doctor_alert_brake")
            )
            .scalars()
            .all()
        )
    assert len(alerts) == 1
    handle(p, send_retry, alerts[0])
    assert row(p, alerts[0])["status"] == "delivered"


@pytest.mark.parametrize("code", [True, False])
def test_sixth_exempt_blocked_per_recipient(prepared, code):
    p = prepared
    sid = signup(p) if code else None
    for i in range(6):
        oid = (
            enqueue(
                p,
                key=f"code:{i}",
                template_id="op:signup_code",
                audience="doctor",
                booking_id=None,
                pending_signup_id=sid,
                blanks={"code": "123456"},
            )
            if code
            else urgent(p, "4", key=f"cancel:{i}")
        )
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == ("delivered" if i < 5 else "blocked_by_brake")
    with p.engine.connect() as conn:
        assert conn.execute(
            select(s.action_record.c.id).where(
                s.action_record.c.kind == "message_block", s.action_record.c.text == "recipient_cap"
            )
        ).first()
        alerts = (
            conn.execute(
                select(s.outbox.c.id).where(s.outbox.c.template_id == "op:doctor_alert_unreachable")
            )
            .scalars()
            .all()
        )
        assert len(alerts) == (0 if code else 1)
    if code:
        oid = urgent(p)
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == "delivered"


def test_connect_failure_retries_then_delivers(prepared, monkeypatch):
    p = prepared
    link(p)
    get_settings().telegram_bot_token = "fictional-token"
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setitem(ADAPTERS, "telegram", TelegramAdapter(client))
        oid = urgent(p)
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == "queued"
        p.clock.advance(minutes=1)
        handle(p, send_retry, oid, 2)
    assert row(p, oid)["status"] == "delivered"


def test_queued_leave_defers_without_attempt_until_resume(prepared, monkeypatch):
    from nowa.core import timing

    p = prepared
    fake = FakeAdapter()
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    oid = urgent(p)
    with write_tx(p.engine) as conn:
        eid = conn.execute(
            select(s.bookings.c.evening_id).where(s.bookings.c.id == p.bid)
        ).scalar_one()
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="running"))
        timing.pause_in_tx(conn, p.clock, p.cid, eid, "pause")
    for _ in range(2):
        handle(p, send_retry, oid)
        p.clock.advance(minutes=1)
    assert not fake.rows and row(p, oid)["attempts"] == 0
    with write_tx(p.engine) as conn:
        assert not conn.execute(
            select(s.action_record).where(s.action_record.c.kind == "send_attempt")
        ).first()
        timing.resume_in_tx(conn, p.clock, p.cid, eid, "resume")
    p.clock.advance(minutes=1)
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == "delivered" and len(fake.rows) == 1


def test_pause_deferral_retires_previous_attempt_timeout(prepared, monkeypatch):
    from nowa.core import timing

    p = prepared
    fake = FakeAdapter("refused")
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    oid = urgent(p)
    handle(p, send_retry, oid)
    with write_tx(p.engine) as conn:
        eid = conn.execute(
            select(s.bookings.c.evening_id).where(s.bookings.c.id == p.bid)
        ).scalar_one()
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="running"))
        timing.pause_in_tx(conn, p.clock, p.cid, eid, "pause")
    p.clock.advance(minutes=1)
    handle(p, send_retry, oid, 2)
    with p.engine.connect() as conn:
        assert (
            conn.execute(
                select(s.timers.c.status).where(s.timers.c.idempotency_key == f"dt:{oid}:1")
            ).scalar_one()
            == "cancelled"
        )
    assert row(p, oid)["attempts"] == 1
    p.clock.advance(minutes=20)
    with write_tx(p.engine) as conn:
        timing.resume_in_tx(conn, p.clock, p.cid, eid, "resume")
    fake.outcome = "accepted"
    handle(p, send_retry, oid, 2)
    assert row(p, oid)["status"] == "delivered"


def test_recipient_cap_retry_identity_and_day_rollover(prepared, monkeypatch):
    p = prepared
    fake = FakeAdapter("refused")
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    retry_id = urgent(p, "4", "retry")
    handle(p, send_retry, retry_id)
    fake.outcome = "accepted"
    for i in range(4):
        handle(p, send_retry, urgent(p, "4", f"fill:{i}"))
    handle(p, send_retry, retry_id, 2)
    assert row(p, retry_id)["status"] == "delivered"
    blocked = urgent(p, "4", "blocked")
    handle(p, send_retry, blocked)
    assert row(p, blocked)["status"] == "blocked_by_brake"
    with write_tx(p.engine) as conn:
        old = dict(
            conn.execute(select(s.bookings).where(s.bookings.c.id == p.bid)).mappings().one()
        )
        pid = conn.execute(
            s.patients.insert()
            .values(clinic_id=p.cid, name="Other Fictional Patient")
            .returning(s.patients.c.id)
        ).scalar_one()
        old.pop("id")
        old.update(patient_id=pid, queue_number=8, order_key=8)
        other_bid = conn.execute(
            s.bookings.insert().values(**old).returning(s.bookings.c.id)
        ).scalar_one()
    other = urgent(p, "2", "same-contact-other-patient", booking_id=other_bid)
    handle(p, send_retry, other)
    assert row(p, other)["status"] == "delivered"
    p.clock.advance(minutes=24 * 60)
    tomorrow = urgent(p, "4", "tomorrow")
    handle(p, send_retry, tomorrow)
    assert row(p, tomorrow)["status"] == "delivered"


def test_doctor_and_screen_share_recipient_cap(prepared):
    p = prepared
    for i in range(6):
        oid = enqueue(
            p,
            key=f"reset:{i}",
            template_id="op:reset_code",
            audience="doctor",
            booking_id=None,
            blanks={"code": "123456"},
        )
        if i % 2:
            with write_tx(p.engine) as conn:
                conn.execute(
                    s.outbox.update().where(s.outbox.c.id == oid).values(recipient_kind="doctor")
                )
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == ("delivered" if i < 5 else "blocked_by_brake")
