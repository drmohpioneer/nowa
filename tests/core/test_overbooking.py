"""closed-evening learning and deterministic capacity."""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.clock import CAIRO
from nowa.core import booking, clinic_settings, learning, projection, timing
from nowa.db import write_tx
from nowa.seed import seed
from tests.core.support import move, setup
from tests.test_booking import request


def totals(conn, cid, day, came, missing, cancelled=0):
    conn.execute(
        s.daily_totals.insert().values(
            clinic_id=cid,
            date=day,
            booked=came + missing,
            came=came,
            didnt_come=missing,
            cancelled=cancelled,
        )
    )


@pytest.mark.parametrize(
    "n,rate,want", [(0, 0.3, 0.1), (2, 0.15, 0.1), (3, 0.12, 0.12), (10, 0.5, 0.2)]
)
def test_rate_default_threshold_and_cap(engine, clinic_id, n, rate, want):
    with write_tx(engine) as conn:
        assert projection.no_show_rate(conn, clinic_id) == 0.1
        conn.execute(s.learned_no_show.insert().values(clinic_id=clinic_id, n=n, rate=rate))
        assert projection.no_show_rate(conn, clinic_id) == pytest.approx(want)


def test_learning_last_ten_before_filter_weighted_and_isolated(engine):
    cid, eid, _, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.daily_totals.delete().where(s.daily_totals.c.clinic_id == cid))
        # Old qualifying evening must not replace a small evening in the last ten.
        totals(conn, cid, date(2026, 9, 1), 0, 100)
        for i in range(2, 12):
            totals(conn, cid, date(2026, 9, i), 8 if i % 2 else 4, 2 if i % 2 else 0)
        from nowa.demo.template import CLINIC

        clinic_id = conn.execute(
            s.clinics.insert()
            .values(**(CLINIC["clinic"] | {"slug": "other"}))
            .returning(s.clinics.c.id)
        ).scalar_one()
        totals(conn, clinic_id, date(2026, 9, 20), 0, 100)
        learning.learn(conn, cid, eid)
        row = (
            conn.execute(select(s.learned_no_show).where(s.learned_no_show.c.clinic_id == cid))
            .mappings()
            .one()
        )
        assert row["n"] == 5
        assert row["rate"] == pytest.approx(0.2)
        # Recompute, not cumulative; repeated reads of history cannot double count.
        learning.learn(conn, cid, eid)
        assert (
            conn.execute(
                select(s.learned_no_show.c.n).where(s.learned_no_show.c.clinic_id == cid)
            ).scalar_one()
            == 5
        )
        assert projection.no_show_rate(conn, clinic_id) == 0.1


def test_learning_weights_bookings_and_excludes_cancelled_from_denominator(engine):
    cid, eid, _, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.daily_totals.delete().where(s.daily_totals.c.clinic_id == cid))
        totals(conn, cid, date(2026, 9, 1), 8, 2, cancelled=10)
        totals(conn, cid, date(2026, 9, 2), 18, 2)
        totals(conn, cid, date(2026, 9, 3), 0, 0, cancelled=5)
        learning.learn(conn, cid, eid)
        row = conn.execute(select(s.learned_no_show)).mappings().one()
        assert row["n"] == 3
        assert row["rate"] == pytest.approx(4 / 30)


def test_close_snapshots_chat_only_and_learns_current_evening_once(engine):
    cid, eid, clock, ids = setup(engine, count=6)
    with write_tx(engine) as conn:
        conn.execute(s.daily_totals.delete().where(s.daily_totals.c.clinic_id == cid))
        for day in (date(2026, 9, 1), date(2026, 9, 3)):
            totals(conn, cid, day, 9, 1)
        conn.execute(
            s.bookings.update().where(s.bookings.c.id.in_(ids[4:])).values(state="told_to_leave")
        )
    move(clock, 0)
    for i in range(4):
        assert timing.who_comes_in(engine, clock, cid, eid, ids[i], False, f"visit:{i}").ok
        clock.advance(minutes=12)
    assert timing.who_comes_in(engine, clock, cid, eid, None, True, "walkin").ok
    clock.advance(minutes=12)
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", expected_untold=0).ok
    with engine.connect() as conn:
        current = (
            conn.execute(select(s.daily_totals).where(s.daily_totals.c.date == date(2026, 10, 6)))
            .mappings()
            .one()
        )
        assert (current["booked"], current["came"], current["didnt_come"], current["walkins"]) == (
            6,
            4,
            2,
            1,
        )
        learned = conn.execute(select(s.learned_no_show)).mappings().one()
        assert learned["n"] == 3 and learned["rate"] == pytest.approx(4 / 26)
    assert timing.close_evening(
        engine, clock, cid, eid, "doctor", "close-again", expected_untold=0
    ).ok
    with engine.connect() as conn:
        assert conn.execute(select(s.learned_no_show.c.n)).scalar_one() == 3


@pytest.mark.parametrize("start,end", [(time(19), time(23)), (time(22), time(2))])
def test_allowance_boundary_cancellation_cutoff_and_closed_days(engine, start, end):
    cid, eid, clock, ids = setup(engine, count=1, pace=20)
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=start, end=end))
        conn.execute(
            s.learned_no_show.update()
            .where(s.learned_no_show.c.clinic_id == cid)
            .values(n=3, rate=1 / 12)
        )
        # Thirteen waiting people: next at closing + 20 minutes, exactly allowance.
        for i in range(1, 14):
            if i == 1:
                continue
            result = booking.book_in_tx(conn, clock, request(cid, i))
            assert isinstance(result, booking.BookingOk)
        hours = projection.paper_hours(conn, cid, date(2026, 10, 6))
        reason, projected = booking._day_status(conn, cid, date(2026, 10, 6), clock.now(cid))
        assert reason is None and projected == hours[1] + timedelta(minutes=20)
        assert isinstance(booking.book_in_tx(conn, clock, request(cid, 14)), booking.BookingOk)
        assert booking._day_status(conn, cid, date(2026, 10, 6), clock.now(cid))[0] == "full"
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled"))
        assert booking._day_status(conn, cid, date(2026, 10, 6), clock.now(cid))[0] is None
        cutoff_reason = "booking_closed" if start < end else "closed_day"
        assert (
            booking._day_status(conn, cid, date(2026, 10, 6), hours[1] - timedelta(minutes=59))[0]
            == cutoff_reason
        )
        for state in ("closed", "cancelled"):
            conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state=state))
            assert (
                booking._day_status(conn, cid, date(2026, 10, 6), clock.now(cid))[0] == "closed_day"
            )


def test_seed_rate_and_demo_tuesday_capacity(engine):
    seed(engine)
    with engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        learned = conn.execute(select(s.learned_no_show)).mappings().one()
        assert learned["n"] == 3 and learned["rate"] == pytest.approx(0.12)
        assert projection.no_show_rate(conn, cid) == pytest.approx(0.12)
    from nowa.clock import FrozenClock

    clock = FrozenClock(datetime(2026, 10, 6, 16, tzinfo=CAIRO))
    for i in range(1, 22):
        result = booking.book(engine, clock, request(cid, i))
        assert isinstance(result, booking.BookingOk), result
    assert result.expected_shown == datetime(2026, 10, 6, 23, 26, tzinfo=CAIRO)
    assert booking.book(engine, clock, request(cid, 22)).reason == "full"


def test_settings_learned_values_and_thresholds(engine):
    cid, _, _, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        did = conn.execute(select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)).scalar_one()
        learned = clinic_settings.read(conn, cid, did)["learned"]
        assert learned["visit"]["n"] == 10 and learned["visit"]["value"] == 12
        assert learned["gap"] == {"value": 0.0, "n": 0, "still_learning": True}
        assert learned["no_show"] == {"value": 12.0, "n": 3, "still_learning": False}
        conn.execute(s.learned_pace.update().values(n=0))
        conn.execute(s.learned_start_gap.insert().values(clinic_id=cid, n=1, mean_min=-2))
        conn.execute(s.learned_no_show.update().values(n=2, rate=0.4))
        learned = clinic_settings.read(conn, cid, did)["learned"]
        assert learned["visit"]["still_learning"] and learned["visit"]["value"] == 15
        assert learned["gap"] == {"value": -2.0, "n": 1, "still_learning": False}
        assert learned["no_show"] == {"value": 10.0, "n": 2, "still_learning": True}


def test_existing_demo_seed_backfills_history_idempotently(engine):
    seed(engine)
    with write_tx(engine) as conn:
        conn.execute(s.learned_no_show.delete())
        conn.execute(s.daily_totals.delete())
    seed(engine)
    seed(engine)
    with engine.connect() as conn:
        assert len(conn.execute(select(s.daily_totals)).all()) == 3
        assert conn.execute(select(s.learned_no_show.c.rate)).scalar_one() == pytest.approx(0.12)


def test_empty_history_resets_no_show_learning(engine):
    cid, eid, _, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.daily_totals.delete())
        learning.learn(conn, cid, eid)
        row = conn.execute(select(s.learned_no_show)).mappings().one()
        assert row["n"] == 0 and row["rate"] == 0
        assert projection.no_show_rate(conn, cid) == 0.1
