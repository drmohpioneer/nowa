import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from tests.core.support import move, row, setup


def test_arrived_keeps_place_when_q5_admitted(engine):
    cid, eid, clock, ids = setup(engine, count=7)
    move(clock, 0)
    with write_tx(engine) as conn:
        timing.mark_arrived_in_tx(conn, clock, cid, ids[0], "doctor", "arrived")
    before = row(engine, s.bookings, ids[0])["order_key"]
    assert timing.who_comes_in(engine, clock, cid, eid, ids[4], False, "admit").ok
    assert row(engine, s.bookings, ids[0])["order_key"] == before
    with engine.connect() as conn:
        assert timing.tonight_board(conn, cid, eid).rows[0].booking_id == ids[0]


@pytest.mark.parametrize("state", ["booked", "told_to_leave", "on_my_way"])
def test_close_refused_until_arrived_admitted(engine, state):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[1]).values(state=state))
        timing.mark_arrived_in_tx(conn, clock, cid, ids[1], "doctor", "arrived")
    preview = timing.close_preview(engine, clock, cid, eid)
    assert [p.booking_id for p in preview.arrived] == ids[1:]
    assert preview.untold_count == preview.told_count == preview.passed_count == 0
    result = timing.close_evening(engine, clock, cid, eid, "doctor", "close", 0)
    assert result.reason == "arrived_present" and result.arrived_count == 1
    assert row(engine, s.bookings, ids[1])["state"] == state
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "second").ok
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", 0).ok


def test_wind_down_leaves_arrived_untold_untouched(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    with write_tx(engine) as conn:
        timing.mark_arrived_in_tx(conn, clock, cid, ids[1], "doctor", "arrived")
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    with write_tx(engine) as conn:
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "wind", 0).ok
        assert not conn.execute(
            select(s.outbox).where(
                s.outbox.c.booking_id == ids[1], s.outbox.c.template_id.in_(("2", "4"))
            )
        ).first()
    assert row(engine, s.bookings, ids[1])["state"] == "booked"


def test_undo_skip_refuses_after_skipped_patient_arrives(engine):
    cid, eid, clock, ids = setup(engine, count=6)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[4], False, "skip")
    with write_tx(engine) as conn:
        timing.mark_arrived_in_tx(conn, clock, cid, ids[0], "doctor", "arrive")
    order = row(engine, s.bookings, ids[0])["order_key"]
    assert timing.undo_last(engine, clock, cid, eid, "undo").reason == "changed_since"
    assert row(engine, s.bookings, ids[0])["order_key"] == order
