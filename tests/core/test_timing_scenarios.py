from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.config import get_settings
from nowa.core import booking, flows, timing, timing_handlers, travel
from nowa.core.timers import TimerContext
from nowa.db import write_tx
from nowa.messaging.outbox import recipient
from tests.core.support import BASE, DAY, move, request, row, setup
from tests.helpers.worker import drain


def context(conn, clock, cid, kind):
    return TimerContext(conn, clock, cid, 999, kind, clock.now(cid), 1, clock.now(cid))


def messages(engine, template):
    with engine.connect() as conn:
        return (
            conn.execute(select(s.outbox).where(s.outbox.c.template_id == template))
            .mappings()
            .all()
        )


def test_vision(engine, monkeypatch):
    cid, eid, clock, ids = setup(engine, pace=13.33, count=18)
    # Shift this fixture's paper start to the vision's 19:00 and its end into the next day.
    from datetime import time

    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(19), end=time(2)))
        conn.execute(s.learned_start_gap.insert().values(clinic_id=cid, mean_min=8, n=10))
        for i, bid in enumerate(ids):
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(expected_shown=BASE + timedelta(hours=7, minutes=round(i * 13.33)))
            )
    monkeypatch.setattr(travel, "minutes", lambda *a, **k: 35.0)
    move(clock, 430)
    result = timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    assert result.projected_start == BASE + timedelta(hours=7, minutes=53)
    seventh = row(engine, s.bookings, ids[6])
    assert seventh["expected_shown"] == BASE + timedelta(hours=9, minutes=13)
    assert seventh["state"] == "booked"


def test_one_silent_pulls_exactly_one(engine, monkeypatch):
    cid, eid, clock, ids = setup(engine, count=8)
    monkeypatch.setattr(travel, "minutes", lambda *a, **k: 10.0)
    move(clock, 0)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    for msg in messages(engine, "2"):
        if msg["booking_id"] != ids[0]:
            timing.patient_on_my_way(engine, clock, msg["booking_id"], f"reply:{msg['id']}")
    move(clock, 9)
    drain(engine, clock, worker.build_registry())
    before = messages(engine, "2")
    for msg in before:
        if msg["booking_id"] != ids[0]:
            timing.patient_on_my_way(engine, clock, msg["booking_id"], f"reply-nine:{msg['id']}")
    move(clock, 10)
    drain(engine, clock, worker.build_registry())
    assert len(messages(engine, "2")) == len(before) + 1
    silent = row(engine, s.bookings, ids[0])
    assert silent["silent"] and silent["queue_number"] == 1 and silent["order_key"] == 1


@pytest.mark.parametrize("sandbox,demo", [(True, False), (False, False), (False, True)])
def test_doctor_reminder_routing(engine, monkeypatch, sandbox, demo):
    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=sandbox))
    monkeypatch.setenv("DEMO_MODE", str(demo).lower())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nowa.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture:fixture@localhost/fixture")
    get_settings.cache_clear()
    move(clock, 0)
    drain(engine, clock, worker.build_registry())
    reminders = messages(engine, "5")
    assert len(reminders) == 1 and reminders[0]["channel"] == "sms"
    assert reminders[0]["lang"] == "ar"
    if sandbox or demo:
        assert reminders[0]["adapter"] == "screen_phone"
    with engine.connect() as conn:
        phone, _ = recipient(conn, reminders[0])
        assert phone == conn.execute(select(s.doctors.c.mobile_e164)).scalar_one()
    assert not messages(engine, "2")


def test_reminder_after_tap_is_stale(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, -30)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    move(clock, 0)
    drain(engine, clock, worker.build_registry())
    assert not messages(engine, "5")


@pytest.mark.parametrize("state", ["scheduled", "doctor_on_way", "running"])
def test_system_close(engine, state):
    cid, eid, clock, ids = setup(engine, count=8)
    move(clock, 0)
    if state != "scheduled":
        timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    if state == "running":
        timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "tap")
    before = [row(engine, s.bookings, b)["state"] for b in ids]
    move(clock, 839)
    with write_tx(engine) as conn:
        timing_handlers.evening_system_close(
            context(conn, clock, cid, "evening_system_close"), {"evening_id": eid}
        )
    e = row(engine, s.evenings, eid)
    if state == "running":
        assert e["state"] == "running"
        return
    assert e["state"] == "closed" and e["closed_by"] == "system_no_taps"
    after = [row(engine, s.bookings, b)["state"] for b in ids]
    assert after == ["cancelled" if b == "booked" else b for b in before]
    assert len(messages(engine, "4")) == before.count("booked")
    with engine.connect() as conn:
        assert conn.execute(
            select(s.timers.c.id).where(s.timers.c.kind == "evening_report")
        ).first()


@pytest.mark.parametrize("actor", ["doctor", "system"])
def test_close_learning_preview_and_once(engine, actor):
    cid, eid, clock, ids = setup(engine, count=10)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    move(clock, 12)
    second = timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "second")
    move(clock, 24)
    preview = timing.close_preview(engine, clock, cid, eid)
    if actor == "doctor":
        assert (
            timing.close_evening(
                engine, clock, cid, eid, actor, "close", preview.untold_count + 1
            ).reason
            == "count_changed"
        )
    result = timing.close_evening(
        engine, clock, cid, eid, actor, "close", preview.untold_count if actor == "doctor" else None
    )
    assert result.ok and result.untold_cancelled == preview.untold_count
    assert timing.close_evening(engine, clock, cid, eid, actor, "close", None) == result
    assert row(engine, s.visits, first.visit_id)["accepted"]
    assert row(engine, s.visits, second.visit_id)["accepted"] == (actor == "doctor")
    with engine.connect() as conn:
        learned = conn.execute(select(s.learned_pace)).mappings().one()
        assert learned["n"] == (12 if actor == "doctor" else 11)
        assert learned["mean_visit_min"] == 12
        states = list(conn.execute(select(s.bookings.c.state)).scalars())
        assert "didnt_come" in states and "booked" not in states
    assert len(messages(engine, "4")) == preview.untold_count


def test_auto_close_conditions(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    move(clock, 60)
    with write_tx(engine) as conn:
        timing_handlers.evening_auto_close(
            context(conn, clock, cid, "evening_auto_close"), {"evening_id": eid}
        )
    assert row(engine, s.evenings, eid)["state"] == "running"
    move(clock, 779)
    drain(engine, clock, worker.build_registry())
    assert row(engine, s.evenings, eid)["closed_by"] == "auto"
    assert not row(engine, s.visits, 1)["accepted"]


@pytest.mark.parametrize("bad", ["forged", "expired", "other_evening"])
def test_cancel_token_refusals(engine, bad):
    cid, eid, clock, ids = setup(engine, count=1)
    with engine.connect() as conn:
        doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
    token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    if bad == "forged":
        token = "f" * 32
    if bad == "expired":
        clock.advance(minutes=21)
    if bad == "other_evening":
        with write_tx(engine) as conn:
            other = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        token = timing.request_cancel_tonight(engine, clock, cid, other, doctor)
    assert (
        timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel").reason
        == "invalid_token"
    )
    assert row(engine, s.evenings, eid)["state"] == "scheduled"


def test_cancel_and_rebook_once(engine):
    cid, eid, clock, ids = setup(engine, count=3)
    with engine.connect() as conn:
        doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
    token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    assert len(token) == 32
    clock.advance(minutes=10)
    result = timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel")
    assert (
        result.ok
        and timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel") == result
    )
    msgs = messages(engine, "4")
    assert len(msgs) == 3
    for msg in msgs:
        assert "/r/" + booking.link_code_for(msg["booking_id"]) in msg["body"]
    with engine.connect() as conn:
        for timer in conn.execute(
            select(s.timers).where(s.timers.c.status == "pending")
        ).mappings():
            assert timer["payload_json"].get("evening_id") != eid
    booked = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=2), "rebook-intent")
    assert isinstance(booked, booking.BookingOk)
    again = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=5), "different-intent")
    assert again.repeated and again.booking_id == booked.booking_id
    assert len([m for m in messages(engine, "1") if m["booking_id"] == booked.booking_id]) == 1


def test_running_cancel_refused_and_close_rebook(engine):
    cid, eid, clock, ids = setup(engine, count=12)
    with engine.connect() as conn:
        doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
    move(clock, 0)
    token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    assert (
        timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel").reason
        == "evening_running"
    )
    clock.advance(minutes=12)
    preview = timing.close_preview(engine, clock, cid, eid)
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", preview.untold_count).ok
    assert row(engine, s.bookings, ids[-1])["state"] == "cancelled"
    assert isinstance(
        flows.rebook(engine, clock, ids[-1], DAY + timedelta(days=2), "rebook"), booking.BookingOk
    )


@pytest.mark.parametrize("flow,confirm", [("book", True), ("book", False), ("rebook", True)])
def test_flow_in_tx_outer_rollback(engine, flow, confirm):
    cid, eid, clock, ids = setup(engine, count=1)
    if flow == "rebook":
        with engine.connect() as conn:
            doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel").ok
    with engine.connect() as conn:
        before = {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables}

    with pytest.raises(RuntimeError, match="outer rollback"):
        with write_tx(engine) as conn:
            if flow == "book":
                result = flows.book_in_tx(
                    conn, clock, request(cid, 10, DAY + timedelta(days=2)), confirm=confirm
                )
            else:
                result = flows.rebook_in_tx(
                    conn, clock, ids[0], DAY + timedelta(days=2), "rebook"
                )
            assert isinstance(result, booking.BookingOk) and not result.repeated
            assert conn.in_transaction()
            new_evening = conn.execute(
                select(s.bookings.c.evening_id).where(s.bookings.c.id == result.booking_id)
            ).scalar_one()
            confirmations = conn.execute(
                select(s.outbox).where(s.outbox.c.booking_id == result.booking_id)
            ).mappings().all()
            assert len(confirmations) == int(confirm)
            if confirm:
                assert confirmations[0]["template_id"] == "1"
                assert confirmations[0]["idempotency_key"] == f"confirm:{result.booking_id}"
            kinds = {
                timer["kind"]
                for timer in conn.execute(select(s.timers)).mappings()
                if timer["payload_json"].get("evening_id") == new_evening
            }
            assert {"are_you_on_way", "evening_system_close"} <= kinds
            raise RuntimeError("outer rollback")

    with engine.connect() as conn:
        assert {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables} == before


def test_flow_commit_and_replay(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    result = flows.book(engine, clock, request(cid, 4))
    again = flows.book(engine, clock, request(cid, 4))
    assert again.repeated and result.booking_id == again.booking_id
    change = flows.change_day(
        engine, clock, booking.link_code_for(ids[0]), "0000", DAY + timedelta(days=2), "change"
    )
    assert isinstance(change, booking.ChangeDayResult)
    assert flows.change_day(
        engine, clock, booking.link_code_for(ids[0]), "0000", DAY + timedelta(days=2), "change"
    ).repeated
    cancelled = flows.cancel(engine, clock, booking.link_code_for(ids[1]), "0001", "cancel")
    assert isinstance(cancelled, booking.CancelResult)
    assert flows.cancel(engine, clock, booking.link_code_for(ids[1]), "0001", "cancel").repeated
    assert len(messages(engine, "3")) == 1
    assert len([m for m in messages(engine, "1") if m["booking_id"] == change.new_booking_id]) == 1
    with engine.connect() as conn:
        for evening_id in [eid, change.new_evening_id]:
            kinds = {
                r["kind"]
                for r in conn.execute(
                    select(s.timers).where(s.timers.c.status == "pending")
                ).mappings()
                if r["payload_json"].get("evening_id") == evening_id
            }
            assert {"are_you_on_way", "evening_system_close"} <= kinds


@pytest.mark.parametrize("action", ["cancel", "change_day"])
@pytest.mark.parametrize("close", ["system", "doctor", "cancel_tonight"])
@pytest.mark.parametrize("in_tx", [False, True])
def test_flows_refuse_closed_or_cancelled_evening(engine, action, close, in_tx):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
    assert row(engine, s.bookings, ids[1])["state"] == "told_to_leave"
    if close == "system":
        move(clock, 839)
        with write_tx(engine) as conn:
            timing_handlers.evening_system_close(
                context(conn, clock, cid, "evening_system_close"), {"evening_id": eid}
            )
        assert row(engine, s.bookings, ids[1])["state"] == "told_to_leave"
    elif close == "doctor":
        assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "tap").ok
        preview = timing.close_preview(engine, clock, cid, eid)
        assert timing.close_evening(
            engine, clock, cid, eid, "doctor", "close", preview.untold_count
        ).ok
        assert row(engine, s.bookings, ids[1])["state"] == "didnt_come"
    else:
        with engine.connect() as conn:
            doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "close").ok
    assert row(engine, s.evenings, eid)["state"] == (
        "cancelled" if close == "cancel_tonight" else "closed"
    )
    tables = (s.bookings, s.evenings, s.outbox, s.timers, s.idempotency_keys, s.action_record)
    with engine.connect() as conn:
        before = [
            conn.execute(select(table).order_by(table.c.id)).mappings().all() for table in tables
        ]
    args = (clock, booking.link_code_for(ids[1]), "0001")
    if action == "change_day":
        args += (DAY + timedelta(days=2),)
    args += ("refused-flow",)
    if in_tx:
        with write_tx(engine) as conn:
            result = getattr(flows, action + "_in_tx")(conn, *args)
    else:
        result = getattr(flows, action)(engine, *args)
    assert result == booking.LinkRefused("not_cancellable")
    with engine.connect() as conn:
        after = [
            conn.execute(select(table).order_by(table.c.id)).mappings().all() for table in tables
        ]
    assert after == before


def test_flow_cancel_while_running(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "tap").ok
    assert row(engine, s.evenings, eid)["state"] == "running"
    result = flows.cancel(engine, clock, booking.link_code_for(ids[1]), "0001", "cancel")
    assert isinstance(result, booking.CancelResult) and not result.repeated
    assert row(engine, s.bookings, ids[1])["state"] == "cancelled"
    assert len(messages(engine, "3")) == 1
    assert row(engine, s.evenings, eid)["state"] == "running"


def test_hours_changed_back_after_old_timer_done(engine):
    from datetime import time

    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    drain(engine, clock, worker.build_registry())
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(12, 30)))
        timing.ensure_evening_timers(conn, clock, eid)
        conn.execute(s.clinic_hours.update().values(start=time(12)))
        timing.ensure_evening_timers(conn, clock, eid)
        rows = (
            conn.execute(
                select(s.timers).where(
                    s.timers.c.kind == "are_you_on_way", s.timers.c.status == "pending"
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1 and rows[0]["due_at"] == BASE
    drain(engine, clock, worker.build_registry())
    assert len(messages(engine, "5")) == 1


def test_silent_patient_called_in_clears_board_flag(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    move(clock, 10)
    drain(engine, clock, worker.build_registry())
    assert row(engine, s.bookings, ids[0])["silent"]
    assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "tap").ok
    with engine.connect() as conn:
        called = next(
            b for b in timing.tonight_board(conn, cid, eid).rows if b.booking_id == ids[0]
        )
        assert called.state == "seen" and not called.silent and not called.remaining
