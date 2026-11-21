from datetime import timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from tests.core.support import BASE, move, row, setup


def test_cover_cap_bounds_whole_evening(engine):
    from datetime import time

    cid, eid, clock, ids = setup(engine, count=13, pace=15)
    start = BASE + timedelta(hours=5)
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(17), end=time(22)))
        for i, bid in enumerate(ids):
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(expected_shown=start + timedelta(minutes=i * 15))
            )
    move(clock, 300)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    ever_silent = set()
    originals = {bid: row(engine, s.bookings, bid)["expected_shown"] for bid in ids}
    for minute in range(300, 601):
        move(clock, minute)
        with write_tx(engine) as conn:
            timing.recompute(conn, clock, eid)
            bookings = conn.execute(select(s.bookings)).mappings().all()
        ever_silent.update(b["id"] for b in bookings if b["silent"])
        assert len(ever_silent) <= 3
        for b in bookings:
            if b["told_to_leave_at"]:
                lead = 10 + b["travel_min"] * 1.3 + 15
                assert b["told_to_leave_at"] >= originals[b["id"]] - timedelta(
                    minutes=lead + 3 * 15
                )
        if minute == 330:
            assert sum(b["told_to_leave_at"] is not None for b in bookings) < 13
    assert len(ever_silent) == 3
    assert row(engine, s.evenings, eid)["covers_used"] == 3


def test_cover_counter_does_not_refund_or_flap(engine):
    cid, eid, clock, ids = setup(engine, count=4)
    move(clock, 0)
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    move(clock, 10)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
        timing.recompute(conn, clock, eid)
    assert row(engine, s.evenings, eid)["covers_used"] == 3
    assert sum(row(engine, s.bookings, bid)["silent"] for bid in ids) == 3
    move(clock, 5)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["silent"]
    assert timing.patient_on_my_way(engine, clock, ids[0], "tap").ok
    assert not row(engine, s.bookings, ids[0])["silent"]
    move(clock, 20)
    timing.patient_undo_on_my_way(engine, clock, ids[0], "undo")
    assert not row(engine, s.bookings, ids[0])["silent"]
    assert row(engine, s.evenings, eid)["covers_used"] == 3
