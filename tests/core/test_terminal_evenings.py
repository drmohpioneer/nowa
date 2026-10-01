"""Public timing/flow commands cannot mutate a terminal evening."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import booking, flows, timing, timing_handlers
from nowa.db import write_tx
from tests.core.support import DAY, move, request, row, setup
from tests.core.test_timing_scenarios import context

COMMANDS = (
    "doctor_on_my_way",
    "who_comes_in",
    "walk_in",
    "undo_last",
    "patient_on_my_way",
    "patient_undo_on_my_way",
    "close_evening",
    "cancel_tonight",
    "recompute",
    "ensure_evening_timers",
    "book",
    "cancel",
    "change_day",
    "rebook",
)
TABLES = (
    s.bookings, s.evenings, s.visits, s.evening_taps, s.outbox, s.timers,
    s.idempotency_keys, s.action_record, s.learned_pace, s.learned_start_gap,
    s.patients, s.contacts, s.consents,
)


def snapshot(engine):
    with engine.connect() as conn:
        return [conn.execute(select(table)).mappings().all() for table in TABLES]


def doctor_id(engine):
    with engine.connect() as conn:
        return conn.execute(select(s.doctors.c.id)).scalar_one()


def command(engine, clock, cid, eid, ids, name, in_tx):
    key = "terminal-check"
    if name == "book":
        return flows.book(engine, clock, request(cid, 90))
    if name == "rebook":
        return flows.rebook(engine, clock, ids[-1], DAY, key)
    if name in {"recompute", "ensure_evening_timers"}:
        with write_tx(engine) as conn:
            return getattr(timing, name)(conn, clock, eid)
    if name in {"cancel", "change_day"}:
        module = flows
        args = (clock, booking.link_code_for(ids[1]), "0001")
        if name == "change_day":
            args += (DAY + timedelta(days=2),)
        args += (key,)
    else:
        module = timing
        args = (clock, cid, eid)
        if name == "doctor_on_my_way":
            args += (None, None, key)
        elif name in {"who_comes_in", "walk_in"}:
            args += (None if name == "walk_in" else ids[1], name == "walk_in", key)
            name = "who_comes_in"
        elif name == "undo_last":
            args += (key,)
        elif name.startswith("patient_"):
            args = (clock, ids[1], key)
        elif name == "close_evening":
            args += ("doctor", key, 0)
        elif name == "cancel_tonight":
            doctor = doctor_id(engine)
            token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
            args += (doctor, token, key)
    if in_tx:
        with write_tx(engine) as conn:
            return getattr(module, name + "_in_tx")(conn, *args)
    return getattr(module, name)(engine, *args)


@pytest.mark.parametrize("name", COMMANDS)
@pytest.mark.parametrize("terminal", ["closed", "cancelled"])
@pytest.mark.parametrize("in_tx", [False, True])
def test_terminal_commands_leave_all_domain_rows_unchanged(engine, name, terminal, in_tx):
    cid, eid, clock, ids = setup(engine, count=12)
    move(clock, 0)
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
    assert row(engine, s.bookings, ids[1])["state"] == "told_to_leave"
    if terminal == "closed":
        move(clock, 839)
        with write_tx(engine) as conn:
            timing_handlers.evening_system_close(
                context(conn, clock, cid, "evening_system_close"), {"evening_id": eid}
            )
        assert row(engine, s.bookings, ids[1])["state"] == "told_to_leave"
    else:
        doctor = doctor_id(engine)
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "end").ok
    assert row(engine, s.evenings, eid)["state"] == terminal
    assert row(engine, s.bookings, ids[-1])["state"] == "cancelled"
    if name in {"book", "rebook"}:
        # Isolate the terminal-state guard from the past-day / paper-hours cutoff.
        move(clock, 0)
    before = snapshot(engine)
    result = command(engine, clock, cid, eid, ids, name, in_tx)
    if name in {"recompute", "ensure_evening_timers"}:
        assert result is None
    elif name == "close_evening" and terminal == "closed":
        assert result == timing.CloseResult()
    elif name in {"book", "rebook"}:
        assert isinstance(result, booking.BookingRefused) and result.reason == "closed_day"
    elif name in {"cancel", "change_day"}:
        assert result == booking.LinkRefused("not_cancellable")
    else:
        assert not result.ok
        if name in {"patient_on_my_way", "patient_undo_on_my_way", "undo_last"}:
            assert result.reason == "evening_closed"
    assert snapshot(engine) == before


@pytest.mark.parametrize("name", ["patient_on_my_way", "patient_undo_on_my_way"])
@pytest.mark.parametrize("terminal", ["closed", "cancelled"])
def test_patient_old_key_is_refused_after_terminal_transition(engine, name, terminal):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
    assert timing.patient_on_my_way(engine, clock, ids[1], "patient_on_my_way").ok
    if name == "patient_undo_on_my_way":
        assert timing.patient_undo_on_my_way(engine, clock, ids[1], name).ok
    if terminal == "closed":
        move(clock, 839)
        with write_tx(engine) as conn:
            timing_handlers.evening_system_close(
                context(conn, clock, cid, "evening_system_close"), {"evening_id": eid}
            )
    else:
        doctor = doctor_id(engine)
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "end").ok
    before = snapshot(engine)
    assert getattr(timing, name)(engine, clock, ids[1], name) == timing.TapResult(
        False, "evening_closed"
    )
    assert snapshot(engine) == before


@pytest.mark.parametrize("name", COMMANDS)
def test_commands_keep_their_active_evening_behavior(engine, name):
    cid, eid, clock, ids = setup(engine, count=12)
    move(clock, 0)
    if name == "doctor_on_my_way":
        assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
        assert row(engine, s.evenings, eid)["state"] == "doctor_on_way"
        assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first").ok
        before = snapshot(engine)
        assert command(engine, clock, cid, eid, ids, name, False).reason == "invalid_state"
        assert snapshot(engine) == before
        return
    if name == "cancel_tonight":
        doctor = doctor_id(engine)
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel").ok
        assert row(engine, s.evenings, eid)["state"] == "cancelled"
        return
    assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first").ok
    assert row(engine, s.evenings, eid)["state"] == "running"
    if name == "rebook":
        source = flows.book(engine, clock, request(cid, 90, DAY + timedelta(days=2)))
        assert isinstance(source, booking.BookingOk)
        with engine.connect() as conn:
            source_eid = conn.execute(
                select(s.bookings.c.evening_id).where(s.bookings.c.id == source.booking_id)
            ).scalar_one()
        doctor = doctor_id(engine)
        token = timing.request_cancel_tonight(engine, clock, cid, source_eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, source_eid, doctor, token, "end").ok
        ids[-1] = source.booking_id
    if name == "close_evening":
        preview = timing.close_preview(engine, clock, cid, eid)
        assert timing.close_evening(
            engine, clock, cid, eid, "doctor", "close", preview.untold_count
        ).ok
        return
    if name == "patient_undo_on_my_way":
        assert timing.patient_on_my_way(engine, clock, ids[1], "patient-way").ok
    if name == "ensure_evening_timers":
        # Removing timers makes successful re-arming observable.
        with write_tx(engine) as conn:
            conn.execute(s.timers.delete())
    if name == "recompute":
        clock.advance(minutes=10)
        assert not row(engine, s.bookings, ids[1])["silent"]
    result = command(engine, clock, cid, eid, ids, name, False)
    if name in {"book", "rebook"}:
        assert isinstance(result, booking.BookingOk) and not result.repeated
        assert row(engine, s.bookings, result.booking_id)["evening_id"] == eid
    elif name == "cancel":
        assert isinstance(result, booking.CancelResult) and not result.repeated
    elif name == "change_day":
        assert isinstance(result, booking.ChangeDayResult) and not result.repeated
    elif name == "ensure_evening_timers":
        with engine.connect() as conn:
            assert conn.execute(select(s.timers.c.id)).first() is not None
    elif name == "recompute":
        assert row(engine, s.bookings, ids[1])["silent"]
    else:
        assert result.ok


@pytest.mark.parametrize("terminal", ["closed", "cancelled"])
def test_reads_remain_allowed_on_terminal_evenings(engine, terminal):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
    doctor = doctor_id(engine)
    if terminal == "closed":
        move(clock, 839)
        with write_tx(engine) as conn:
            timing_handlers.evening_system_close(
                context(conn, clock, cid, "evening_system_close"), {"evening_id": eid}
            )
    else:
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "end").ok
    before = snapshot(engine)
    assert timing.close_preview(engine, clock, cid, eid).untold_count == 0
    assert len(timing.request_cancel_tonight(engine, clock, cid, eid, doctor)) == 32
    with engine.connect() as conn:
        assert len(timing.tonight_board(conn, cid, eid).rows) == 2
        assert timing.patient_blanks(conn, ids[1], "2")
    assert snapshot(engine) == before
