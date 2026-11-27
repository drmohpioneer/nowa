from datetime import timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.core import booking, flows, timing
from nowa.db import write_tx
from tests.core.support import DAY, move, request, setup


def test_winding_down_refuses_new_booking(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    with write_tx(engine) as conn:
        assert timing.wind_down_in_tx(conn, clock, cid, eid, "wind", 0).ok
    result = flows.book(engine, clock, request(cid, 90))
    assert isinstance(result, booking.BookingRefused) and result.reason == "closed_day"


def test_rebook_distinguishes_new_intent_and_true_replay(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    token = timing.request_cancel_tonight(engine, clock, cid, eid, did)
    timing.cancel_tonight(engine, clock, cid, eid, did, token, "cancel")
    first = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=2), "first")
    assert isinstance(first, booking.BookingOk)
    replay = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=2), "first")
    assert replay.repeated and replay.booking_id == first.booking_id
    for key, day in (("other", 2), ("other", 5), ("first", 5)):
        result = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=day), key)
        assert isinstance(result, booking.BookingRefused) and result.reason == "already_rebooked"
