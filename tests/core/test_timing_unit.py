import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.core import booking, flows, timers, timing, travel
from nowa.db import write_tx
from tests.core.support import BASE, DAY, move, request, row, setup
from tests.helpers.worker import drain


def pending(engine, kind, eid):
    with engine.connect() as conn:
        return (
            conn.execute(
                select(s.timers).where(s.timers.c.kind == kind, s.timers.c.status == "pending")
            )
            .mappings()
            .all()
        )


def tap(engine, clock, cid, eid, bid, key):
    return timing.who_comes_in(engine, clock, cid, eid, bid, False, key)


def test_gate_equality_freeze_travel(engine, monkeypatch):
    cid, eid, clock, ids = setup(engine, count=1)
    monkeypatch.setattr(
        travel,
        "minutes",
        lambda conn, cid, at, origin=None, area_id=None, *, doctor=False: (
            45.0 if origin is not None else 10.0
        ),
    )
    move(clock, 0)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["state"] == "booked"
    timing.doctor_on_my_way(engine, clock, cid, eid, travel.LatLng(30, 31), None, "way")
    move(clock, 11)
    drain(engine, clock, worker.build_registry())
    assert row(engine, s.bookings, ids[0])["state"] == "booked"
    move(clock, 12)
    drain(engine, clock, worker.build_registry())
    b = row(engine, s.bookings, ids[0])
    assert b["state"] == "told_to_leave" and b["travel_min"] == 10 and b["expected_frozen"]
    shown = b["expected_shown"]
    move(clock, 100)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["expected_shown"] == shown


@pytest.mark.parametrize("drift,changed", [(19, False), (20, True)])
def test_later_only(engine, drift, changed):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, drift - 30)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["expected_shown"] == BASE + timedelta(
        minutes=drift if changed else 0
    )


def test_silent_and_patient_undo(engine):
    cid, eid, clock, ids = setup(engine, count=4)
    move(clock, -30)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    move(clock, -21)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert not row(engine, s.bookings, ids[0])["silent"]
    move(clock, -20)
    drain(engine, clock, worker.build_registry())
    assert row(engine, s.bookings, ids[0])["silent"]
    first = timing.patient_on_my_way(engine, clock, ids[0], "patient")
    at = row(engine, s.bookings, ids[0])["on_my_way_at"]
    clock.advance(minutes=1)
    assert timing.patient_on_my_way(engine, clock, ids[0], "patient") == first
    timing.patient_on_my_way(engine, clock, ids[0], "another")
    assert row(engine, s.bookings, ids[0])["on_my_way_at"] == at
    timing.patient_undo_on_my_way(engine, clock, ids[0], "undo-patient")
    assert row(engine, s.bookings, ids[0])["silent"]
    timing.patient_on_my_way(engine, clock, ids[0], "again")
    assert row(engine, s.bookings, ids[0])["on_my_way_at"] == clock.now(cid)


@pytest.mark.parametrize(
    "index,want", [(1, [3, 4, 1, 5, 6]), (2, [4, 5, 1, 2, 6]), (4, [6, 1, 2, 3, 4])]
)
def test_skip_block(engine, index, want):
    cid, eid, clock, ids = setup(engine, count=6)
    move(clock, 0)
    assert tap(engine, clock, cid, eid, ids[index], "tap").ok
    with engine.connect() as conn:
        board = timing.tonight_board(conn, cid, eid)
    assert [b.queue_number for b in board.rows if b.remaining] == want
    assert sorted(b.queue_number for b in board.rows) == list(range(1, 7))


def test_walkin_undo_and_two_taps(engine):
    cid, eid, clock, ids = setup(engine, count=3)
    move(clock, 0)
    first = tap(engine, clock, cid, eid, ids[0], "first")
    before = [row(engine, s.bookings, b)["order_key"] for b in ids]
    clock.advance(minutes=12)
    walk = timing.who_comes_in(engine, clock, cid, eid, None, True, "walk")
    assert [row(engine, s.bookings, b)["order_key"] for b in ids] == before
    assert timing.undo_last(engine, clock, cid, eid, "undo-walk").ok
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.bookings).where(s.bookings.c.id == walk.booking_id)).first()
            is None
        )
        assert conn.execute(select(s.visits).where(s.visits.c.id == walk.visit_id)).first() is None
        assert (
            conn.execute(select(s.outbox).where(s.outbox.c.booking_id == walk.booking_id)).first()
            is None
        )
    assert row(engine, s.visits, first.visit_id)["ended_at"] is None
    assert timing.undo_last(engine, clock, cid, eid, "undo-first").ok
    assert timing.undo_last(engine, clock, cid, eid, "empty").reason == "nothing_to_undo"


def test_undo_recompute_and_changed_fields(engine):
    cid, eid, clock, ids = setup(engine, count=5)
    move(clock, 0)
    first = tap(engine, clock, cid, eid, ids[0], "first")
    clock.advance(minutes=12)
    second = tap(engine, clock, cid, eid, ids[1], "second")
    with write_tx(engine) as conn:
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[1])
            .values(expected_shown=BASE + timedelta(hours=5))
        )
        timing.recompute(conn, clock, eid)
    clock.advance(minutes=1)
    assert timing.undo_last(engine, clock, cid, eid, "undo").ok
    assert row(engine, s.visits, first.visit_id)["ended_at"] is None
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.visits).where(s.visits.c.id == second.visit_id)).first() is None
        )
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled"))
    assert timing.undo_last(engine, clock, cid, eid, "refuse").reason == "changed_since"


def test_auto_timer_taps_undo_and_rearm(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    assert not pending(engine, "evening_auto_close", eid)
    tap(engine, clock, cid, eid, ids[0], "first")
    due = BASE + timedelta(hours=12, minutes=59)
    assert pending(engine, "evening_auto_close", eid)[0]["due_at"] == due
    move(clock, 800)
    tap(engine, clock, cid, eid, ids[1], "second")
    clock.advance(minutes=10)
    timing.undo_last(engine, clock, cid, eid, "undo")
    assert pending(engine, "evening_auto_close", eid)[0]["due_at"] == clock.now(cid) + timedelta(
        minutes=60
    )
    with write_tx(engine) as conn:
        first = timers.rearm(conn, clock, "leave_now_check", eid, due, {"evening_id": eid})
        second = timers.rearm(conn, clock, "leave_now_check", eid, due, {"evening_id": eid})
        assert first != second
    rows = pending(engine, "leave_now_check", eid)
    assert len(rows) == 1 and f":{int(due.timestamp())}:" in rows[0]["idempotency_key"]


def test_flow_rollback(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    with engine.connect() as conn:
        before = {
            table.name: conn.execute(select(table)).all() for table in s.metadata.sorted_tables
        }
    for name in ("ensure_evening_timers", "recompute"):
        with patch.object(timing, name, side_effect=RuntimeError("failure")):
            with pytest.raises(RuntimeError):
                flows.book(engine, clock, request(cid, 10))
        with engine.connect() as conn:
            assert {
                table.name: conn.execute(select(table)).all() for table in s.metadata.sorted_tables
            } == before


def test_repeat_invalid_booking_and_origin_privacy(engine, caplog):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, -30)
    result = timing.doctor_on_my_way(
        engine, clock, cid, eid, travel.LatLng(12.3456789, 23.4567891), None, "way"
    )
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way") == result
    first = tap(engine, clock, cid, eid, ids[0], "first")
    assert tap(engine, clock, cid, eid, ids[0], "first") == first
    assert tap(engine, clock, cid, eid, ids[0], "second").reason == "already_seen"
    assert tap(engine, clock, cid, eid, -1, "missing").reason == "invalid_booking"
    with engine.connect() as conn:
        for table in s.metadata.sorted_tables:
            for values in conn.execute(select(table)):
                assert "12.3456789" not in repr(values) and "23.4567891" not in repr(values)
                if table is not s.outbox:
                    assert booking.link_code_for(ids[0]) not in repr(values)
    assert "12.3456789" not in caplog.text and booking.link_code_for(ids[0]) not in caplog.text


def test_import_graph():
    root = Path(__file__).resolve().parents[2]
    for name, forbidden in [("booking", {"timing", "flows"}), ("timing", {"flows"})]:
        tree = ast.parse((root / f"nowa/core/{name}.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
                imports.extend(a.name for a in node.names)
        assert not any(part in forbidden for item in imports for part in item.split("."))


def concurrent_tap(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tap(engine, clock, cid, eid, ids[0], "same"), range(2)))
    assert results[0] == results[1] and results[0].ok
    with engine.connect() as conn:
        assert len(conn.execute(select(s.visits)).all()) == 1


def test_concurrent_tap(engine):
    concurrent_tap(engine)


@pytest.mark.postgres
def test_postgres_concurrent_tap(postgres_engine):
    concurrent_tap(postgres_engine)


@pytest.mark.parametrize("mutator", ["cancel", "change_day", "rebook"])
def test_all_flows_rollback(engine, mutator):
    cid, eid, clock, ids = setup(engine, count=1)
    if mutator == "rebook":
        with write_tx(engine) as conn:
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled")
            )
            from nowa import record

            record.write_action(conn, cid, "doctor", "close_untold", ids[0])
    with engine.connect() as conn:
        before = {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables}
    with patch.object(timing, "recompute", side_effect=RuntimeError("failure")):
        with pytest.raises(RuntimeError):
            if mutator == "cancel":
                flows.cancel(engine, clock, booking.link_code_for(ids[0]), "0000", "cancel")
            elif mutator == "change_day":
                flows.change_day(
                    engine,
                    clock,
                    booking.link_code_for(ids[0]),
                    "0000",
                    DAY + timedelta(days=2),
                    "change",
                )
            else:
                flows.rebook(engine, clock, ids[0], DAY + timedelta(days=2), "rebook")
    with engine.connect() as conn:
        assert {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables} == before


def test_hours_rearmed_and_prefix(engine):
    from datetime import time

    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(12, 30), end=time(23, 30)))
        timing.ensure_evening_timers(conn, clock, eid)
        timing.ensure_evening_timers(conn, clock, eid)
        for prefix in ["area:1:", "area:2:", "area:1:"]:
            timers.rearm(
                conn, clock, "travel_check", eid, BASE, {"evening_id": eid}, key_prefix=prefix
            )
    assert len(pending(engine, "are_you_on_way", eid)) == 1
    assert pending(engine, "are_you_on_way", eid)[0]["due_at"] == BASE + timedelta(minutes=30)
    assert len(pending(engine, "evening_system_close", eid)) == 1
    assert pending(engine, "evening_system_close", eid)[0]["due_at"] == BASE + timedelta(
        hours=13, minutes=30
    )
    assert len(pending(engine, "travel_check", eid)) == 2


def test_undo_onway_and_frozen_no_double_send(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    before = row(engine, s.bookings, ids[0])
    result = timing.undo_last(engine, clock, cid, eid, "undo")
    assert result.ok and timing.undo_last(engine, clock, cid, eid, "undo") == result
    e = row(engine, s.evenings, eid)
    assert e["state"] == "scheduled" and e["doctor_on_way_at"] is None
    assert e["doctor_eta_min"] is None and e["projected_start"] is None
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "again")
    after = row(engine, s.bookings, ids[0])
    assert before["expected_shown"] == after["expected_shown"] and after["expected_frozen"]
    with engine.connect() as conn:
        assert len(conn.execute(select(s.outbox).where(s.outbox.c.template_id == "2")).all()) == 1


def test_cross_evening_booking_refused(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    result = flows.book(engine, clock, request(cid, 99, DAY + timedelta(days=2)))
    move(clock, 0)
    assert tap(engine, clock, cid, eid, result.booking_id, "wrong").reason == "invalid_booking"
    with write_tx(engine) as conn:
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="didnt_come")
        )
    assert tap(engine, clock, cid, eid, ids[0], "no-show").reason == "invalid_booking"


@pytest.mark.parametrize(
    "kind",
    ["leave_now_check", "silent_check", "are_you_on_way", "evening_system_close", "evening_report"],
)
def test_handler_replay(engine, kind):
    from tests.helpers.worker import HandlerSetup, assert_handler_idempotent

    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 840 if kind in {"evening_system_close", "evening_report"} else 0)
    if kind == "evening_report":
        with write_tx(engine) as conn:
            conn.execute(s.evenings.update().values(state="closed"))
    assert_handler_idempotent(
        kind,
        {"evening_id": eid, "booking_id": ids[0]},
        lambda: HandlerSetup(engine, clock, cid, worker.build_registry()),
    )
