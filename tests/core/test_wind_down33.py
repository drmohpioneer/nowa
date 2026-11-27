from datetime import timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.core import booking, flows, standby, timing, timing_handlers
from nowa.db import write_tx
from tests.core.support import DAY, move, row, setup
from tests.core.test_standby import cancel, full, join, offer_code, rows
from tests.core.test_timing_scenarios import context


def test_wind_down_once_stops_calls_preserves_admission_undo_and_close(engine):
    cid, eid, clock, ids = setup(engine, count=12)
    move(clock, 0)
    with write_tx(engine) as conn:
        assert not timing.wind_down_in_tx(conn, clock, cid, eid, "early", 12).ok
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    before = timing.close_preview(engine, clock, cid, eid)
    assert before.untold_count > 0
    with write_tx(engine) as conn:
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "stale", 99).reason == "count_changed"
        result = timing.wind_down_in_tx(conn, clock, cid, eid, "wind", before.untold_count)
        assert result.ok
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "wind", before.untold_count) == result
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "repeat", 0).ok
        messages = (
            conn.execute(select(s.outbox).where(s.outbox.c.template_id == "4")).mappings().all()
        )
        assert len(messages) == before.untold_count
        assert {m["idempotency_key"] for m in messages} == {
            f"wind_down:{p.booking_id}" for p in before.untold
        }
        leaves = (
            conn.execute(select(s.outbox.c.id).where(s.outbox.c.template_id == "2")).scalars().all()
        )
        assert not conn.execute(
            select(s.evening_taps).where(s.evening_taps.c.kind == "wind_down")
        ).first()
    assert row(engine, s.evenings, eid)["state"] == "winding_down"
    clock.advance(minutes=15)
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "second").ok
    assert row(engine, s.evenings, eid)["state"] == "winding_down"
    assert timing.undo_last(engine, clock, cid, eid, "undo-second").ok
    assert row(engine, s.evenings, eid)["state"] == "winding_down"
    # Undo the first admission as well, without reopening reception.
    assert timing.undo_last(engine, clock, cid, eid, "undo-first").ok
    assert row(engine, s.evenings, eid)["state"] == "winding_down"
    with write_tx(engine) as conn:
        assert timing.mark_arrived_in_tx(conn, clock, cid, ids[1], "doctor", "arrival").ok
        timing.recompute(conn, clock, eid)
        assert (
            conn.execute(select(s.outbox.c.id).where(s.outbox.c.template_id == "2")).scalars().all()
            == leaves
        )
    cancelled = before.untold[0].booking_id
    assert (
        booking.booking_view(engine, booking.link_code_for(cancelled)).state_reason == "wind_down"
    )
    assert isinstance(
        flows.rebook(engine, clock, cancelled, DAY + timedelta(days=2), "rebook"), booking.BookingOk
    )
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "admit-arrived").ok
    preview = timing.close_preview(engine, clock, cid, eid)
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", preview.untold_count).ok
    for p in preview.told:
        assert row(engine, s.bookings, p.booking_id)["state"] == "cancelled"
    for p in preview.passed:
        assert row(engine, s.bookings, p.booking_id)["state"] == "didnt_come"


def test_wind_down_keeps_live_offer_claimable_but_makes_no_new_offer(engine):
    cid, eid, clock, ids = full(engine)
    first = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    cancel(engine, clock, ids[0])
    code = offer_code(engine, first.standby_id)
    move(clock, 0)
    # Recreate the live reservation at the current clock, without expiring its promise.
    with write_tx(engine) as conn:
        conn.execute(
            s.standbys.update()
            .where(s.standbys.c.id == first.standby_id)
            .values(expires_at=clock.now(cid) + timedelta(minutes=20))
        )
    timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "admit")
    with write_tx(engine) as conn:
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "wind", 0).ok
        standby.offer_next(conn, clock, eid)
        assert [
            r["state"]
            for r in conn.execute(select(s.standbys).order_by(s.standbys.c.position)).mappings()
        ] == ["offered", "waiting"]
        taken = standby.take_in_tx(conn, clock, code)
        assert isinstance(taken, booking.BookingOk)
    assert [r["state"] for r in rows(engine)] == ["taken", "waiting"]


def test_wind_down_auto_close_uses_existing_deadline(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    with write_tx(engine) as conn:
        due = timing._auto_due(conn, timing._evening(conn, cid, eid))
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "wind", 0).ok
        assert timing._auto_due(conn, timing._evening(conn, cid, eid)) == due
    clock.advance(minutes=(due - clock.now(cid)).total_seconds() / 60)
    with write_tx(engine) as conn:
        timing_handlers.evening_auto_close(
            context(conn, clock, cid, "evening_auto_close"), {"evening_id": eid}
        )
    assert row(engine, s.evenings, eid)["state"] == "closed"
