"""Contract 33 regressions over the real engine and persisted outbox."""

from datetime import datetime, timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing, travel
from nowa.db import write_tx
from nowa.messaging.templates import render_saved
from tests.core.support import BASE, move, row, setup


def test_leave_now_named_ready_and_saved_clocks(engine, monkeypatch):
    cid, eid, clock, ids = setup(engine, count=1)
    monkeypatch.setattr(travel, "minutes", lambda *args, **kwargs: 10)
    move(clock, 0)
    with write_tx(engine) as conn:
        timing.doctor_on_my_way_in_tx(conn, clock, cid, eid, None, None, "way", travel_min=45)
    move(clock, 6)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["state"] == "booked"
    move(clock, 7)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert row(engine, s.bookings, ids[0])["state"] == "told_to_leave"
    with engine.connect() as conn:
        msg = conn.execute(select(s.outbox).where(s.outbox.c.template_id == "2")).mappings().one()
    assert datetime.fromisoformat(msg["values_json"]["leave_by"]["value"]) == BASE + timedelta(
        minutes=22
    )
    assert datetime.fromisoformat(msg["values_json"]["arrive_by"]["value"]) == BASE + timedelta(
        minutes=35
    )
    assert "leave home by 12:22" in msg["body"]
    assert "around 12:35" in msg["body"]
    assert render_saved("2", "en", msg["values_json"]) == msg["body"]
