from datetime import timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.core import booking, flows, report, timing
from nowa.db import write_tx
from tests.core.support import DAY, move, row, setup


def closing_evening(engine):
    cid, eid, clock, ids = setup(engine, count=6)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "admit")
    now = clock.now(cid)
    states = ["seen", "booked", "booked", "told_to_leave", "on_my_way", "on_my_way"]
    with write_tx(engine) as conn:
        conn.execute(s.daily_totals.delete().where(s.daily_totals.c.clinic_id == cid))
        for i, (bid, state) in enumerate(zip(ids, states, strict=True)):
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(
                    state=state,
                    expected_shown=now + timedelta(minutes=0 if i == 5 else 60),
                    silent=False,
                )
            )
            pid = conn.execute(
                select(s.bookings.c.patient_id).where(s.bookings.c.id == bid)
            ).scalar_one()
            conn.execute(
                s.patients.update()
                .where(s.patients.c.id == pid)
                .values(name=f"Fictional {chr(65 + i)}", name_en=f"Fictional {chr(65 + i)}")
            )
    return cid, eid, clock, ids


def test_close_classifies_names_times_and_learns_only_passed(engine):
    cid, eid, clock, ids = closing_evening(engine)
    preview = timing.close_preview(engine, clock, cid, eid)
    assert [p.booking_id for p in preview.untold] == ids[1:3]
    assert [p.booking_id for p in preview.told] == ids[3:5]
    assert [p.booking_id for p in preview.passed] == ids[5:]
    assert [p.patient_name for p in preview.untold + preview.told + preview.passed] == [
        f"Fictional {chr(65 + i)}" for i in range(1, 6)
    ]
    assert preview.told[0].expected_shown == clock.now(cid) + timedelta(minutes=60)
    assert preview.passed[0].expected_shown == clock.now(cid)
    closed = timing.close_evening(engine, clock, cid, eid, "doctor", "close", 2)
    assert closed.ok
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", 2) == closed
    assert [row(engine, s.bookings, bid)["state"] for bid in ids] == [
        "seen",
        "cancelled",
        "cancelled",
        "cancelled",
        "cancelled",
        "didnt_come",
    ]
    with engine.connect() as conn:
        messages = (
            conn.execute(select(s.outbox).where(s.outbox.c.template_id == "4")).mappings().all()
        )
        assert {m["idempotency_key"] for m in messages} == {
            *(f"close_untold:{bid}" for bid in ids[1:3]),
            *(f"close_told:{bid}" for bid in ids[3:5]),
        }
        totals = report.build_report(conn, clock, cid, eid)
        assert (
            totals.booked,
            totals.seen_booked,
            totals.cancelled,
            totals.cancelled_at_close,
            totals.no_show_count,
        ) == (2, 1, 4, 4, 1)
        learned = (
            conn.execute(select(s.learned_no_show).where(s.learned_no_show.c.clinic_id == cid))
            .mappings()
            .one()
        )
        assert learned["n"] == 1 and learned["rate"] == 0.5
    old = booking.booking_view(engine, booking.link_code_for(ids[3]))
    assert old.state_reason == "close_told"
    assert isinstance(
        flows.rebook(engine, clock, ids[3], DAY + timedelta(days=2), "rebook"), booking.BookingOk
    )
