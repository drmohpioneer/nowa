from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from tests.core.support import move, row, setup


@pytest.mark.parametrize("actor", ["doctor", "secretary"])
@pytest.mark.parametrize("state", ["booked", "told_to_leave", "on_my_way"])
def test_arrival_never_silent_or_told_and_separate_undo(engine, actor, state):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    with write_tx(engine) as conn:
        if state != "booked":
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == ids[1])
                .values(
                    state=state,
                    told_to_leave_at=clock.now(cid) - timedelta(minutes=20),
                    silent=state == "told_to_leave",
                )
            )
        result = timing.mark_arrived_in_tx(conn, clock, cid, ids[1], actor, "arrival")
        assert result.ok
        assert timing.mark_arrived_in_tx(conn, clock, cid, ids[1], actor, "arrival") == result
    arrived = row(engine, s.bookings, ids[1])["arrived_at"]
    assert arrived == clock.now(cid)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "admit")
    move(clock, 30)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
        assert timing.mark_arrived_in_tx(conn, clock, cid, ids[1], actor, "repeat").ok
        b = conn.execute(select(s.bookings).where(s.bookings.c.id == ids[1])).mappings().one()
        assert b["arrived_at"] == arrived and not b["silent"]
        assert not conn.execute(
            select(s.outbox).where(s.outbox.c.booking_id == ids[1], s.outbox.c.template_id == "2")
        ).first()
        assert conn.execute(select(s.evening_taps.c.kind)).scalars().all() == ["who_comes_in"]
        board = timing.tonight_board(conn, cid, eid)
        assert next(r for r in board.rows if r.booking_id == ids[1]).arrived_at == arrived
        assert timing.undo_arrived_in_tx(conn, clock, cid, ids[1], "doctor", "undo-arrived").ok
        assert timing.undo_arrived_in_tx(conn, clock, cid, ids[1], "doctor", "undo-arrived").ok
    assert row(engine, s.bookings, ids[1])["arrived_at"] is None
    assert timing.undo_last(engine, clock, cid, eid, "undo-admit").ok


def test_arrival_refuses_foreign_and_terminal_rows(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    with write_tx(engine) as conn:
        assert not timing.mark_arrived_in_tx(conn, clock, cid + 999, ids[0], "doctor", "foreign").ok
        assert not timing.mark_arrived_in_tx(conn, clock, cid, ids[0], "patient", "patient").ok
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled"))
        assert not timing.mark_arrived_in_tx(conn, clock, cid, ids[0], "doctor", "cancelled").ok
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="booked"))
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="closed"))
        assert not timing.mark_arrived_in_tx(conn, clock, cid, ids[0], "doctor", "closed").ok


def test_walkin_created_arrived(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    result = timing.who_comes_in(engine, clock, cid, eid, None, True, "walkin")
    assert row(engine, s.bookings, result.booking_id)["arrived_at"] == clock.now(cid)
    with engine.connect() as conn:
        assert not conn.execute(
            select(s.outbox).where(s.outbox.c.booking_id == result.booking_id)
        ).first()
