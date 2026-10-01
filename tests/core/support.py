from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, FrozenClock
from nowa.core import booking, flows
from nowa.db import write_tx
from nowa.seed import seed

DAY = date(2026, 10, 6)
BASE = datetime(2026, 10, 6, 12, tzinfo=CAIRO)


def setup(engine, pace=12, cushion=10, count=20):
    seed(engine)
    clock = FrozenClock(BASE - timedelta(days=1))
    record.configure(clock)
    with write_tx(engine) as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(s.clinics.update().values(max_per_evening=None, cushion_min=cushion))
        conn.execute(s.clinic_hours.update().values(start=time(12), end=time(23, 59)))
        conn.execute(s.learned_pace.update().values(mean_visit_min=pace, n=10))
        conn.execute(s.learned_start_gap.delete())
    ids = []
    for i in range(count):
        result = flows.book(engine, clock, request(cid, i))
        assert isinstance(result, booking.BookingOk), result
        ids.append(result.booking_id)
    with engine.connect() as conn:
        eid = conn.execute(select(s.evenings.c.id)).scalar_one()
    return cid, eid, clock, ids


def request(cid, i, day=DAY):
    return booking.BookingRequest(
        cid,
        day,
        "Fictional Patient",
        f"010{i:08d}",
        "en",
        None,
        booking.ConsentInput("v1", "fictional", "self"),
        f"book:{i}",
    )


def move(clock, minute):
    clock.advance(minutes=(BASE + timedelta(minutes=minute) - clock.now(1)).total_seconds() / 60)


def row(engine, table, row_id):
    with engine.connect() as conn:
        return conn.execute(select(table).where(table.c.id == row_id)).mappings().one()
