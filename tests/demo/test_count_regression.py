"""Retained walk-in-inclusive count regression, per slice 12 DECIDED item 1."""

from datetime import datetime, timedelta

from sqlalchemy import select

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, FrozenClock
from nowa.core import booking, flows, patient_link, report, timing
from nowa.seed import seed


def test_script_population_counts_walkin_in_came(engine):
    """18 chat bookings - cancellation - no-show + seen walk-in = 17 came."""
    seed(engine)
    day = datetime(2026, 10, 6, 16, tzinfo=CAIRO)
    clock = FrozenClock(day)
    record.configure(clock)
    with engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
    ids = []
    for number in range(1, 19):
        result = flows.book(
            engine,
            clock,
            booking.BookingRequest(
                cid,
                day.date(),
                "Fictional Patient",
                f"+201000002{number:03d}",
                "en",
                None,
                booking.ConsentInput("fictional", "fictional", "self"),
                f"slice12-count:book:{number}",
                actor="system",
            ),
        )
        assert isinstance(result, booking.BookingOk), result
        assert result.queue_number == number
        ids.append(result.booking_id)
    with engine.connect() as conn:
        eid = conn.execute(
            select(s.evenings.c.id).where(s.evenings.c.clinic_id == cid)
        ).scalar_one()

    clock.advance(minutes=150)  # 18:30: patient 12 cancels through the link flow.
    cancelled = patient_link.cancel_by_link(
        engine, clock, booking.link_code_for(ids[11]), "2012", "slice12-count:cancel"
    )
    assert isinstance(cancelled, booking.CancelResult), cancelled
    clock.advance(minutes=83)  # 19:53: doctor present; first who-comes-in opens gate.
    for number in range(1, 19):
        if number in (12, 15):
            continue
        tap = timing.who_comes_in(
            engine, clock, cid, eid, ids[number - 1], False, f"slice12-count:visit:{number}"
        )
        assert tap.ok, tap
        clock.advance(minutes=13)
        if number == 9:
            walkin = timing.who_comes_in(
                engine, clock, cid, eid, None, True, "slice12-count:walkin"
            )
            assert walkin.ok, walkin
            clock.advance(minutes=13)

    preview = timing.close_preview(engine, clock, cid, eid)
    assert preview.untold_count == 0
    closed = timing.close_evening(
        engine,
        clock,
        cid,
        eid,
        "doctor",
        "slice12-count:close",
        expected_untold=preview.untold_count,
    )
    assert closed.ok
    with engine.connect() as conn:
        derived = report.build_report(conn, clock, cid, eid)
        states = dict(
            conn.execute(
                select(s.bookings.c.queue_number, s.bookings.c.state).where(
                    s.bookings.c.evening_id == eid
                )
            ).all()
        )
        assert states[11] == "seen"  # Silent patient still counted.
        assert states[12] == "cancelled"
        assert states[15] == "didnt_come"
        assert states[19] == "seen"  # Walk-in also counted by accepted slice 11.
        chat_seen = sum(state == "seen" for number, state in states.items() if number <= 18)
    assert chat_seen == 16
    assert (derived.booked, derived.came, derived.no_show_count, derived.walk_ins) == (17, 17, 1, 1)
    assert derived.came == chat_seen + derived.walk_ins
    assert derived.doctor_arrival == day + timedelta(hours=3, minutes=53)
    print(
        "Slice 12 count trace: chat_bookings=18; cancelled_queue=12; "
        f"no_show_queue=15; chat_seen={chat_seen}; walk_in_queue=19; "
        f"booked={derived.booked}; came={derived.came}; "
        f"no_show={derived.no_show_count}; walk_ins={derived.walk_ins}"
    )
