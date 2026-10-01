import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date, datetime, time
from threading import Barrier

import pytest
from sqlalchemy import func, select

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, FrozenClock
from nowa.core.booking import (
    BookingOk,
    BookingRefused,
    BookingRequest,
    CancelResult,
    ChangeDayResult,
    ConsentInput,
    IdempotencyConflict,
    LinkRefused,
    book,
    book_in_tx,
    booking_view,
    cancel,
    change_day,
    change_day_in_tx,
    get_or_create_evening,
    link_code_for,
    nearest_open_day,
    normalize_name,
    normalize_phone,
    open_days,
    tonight_evening,
    valid_name,
)
from nowa.core.projection import current_pace, load_snapshot, people_ahead_of_new_booking
from nowa.db import write_tx
from nowa.seed import seed

TUESDAY = date(2026, 10, 6)
THURSDAY = date(2026, 10, 8)


def setup(engine, maximum=None, pace=15):
    seed(engine)
    with write_tx(engine) as conn:
        clinic = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinics.update().where(s.clinics.c.id == clinic).values(max_per_evening=maximum)
        )
        conn.execute(s.learned_pace.update().values(mean_visit_min=pace, n=10))
    clock = FrozenClock(datetime(2026, 10, 4, 12, tzinfo=CAIRO))
    record.configure(clock)
    return clinic, clock


@pytest.fixture
def booked_clinic(engine):
    return setup(engine)


def request(clinic, number=1, **changes):
    req = BookingRequest(
        clinic,
        TUESDAY,
        "Karim Mahmoud",
        f"010{number:08d}",
        "ar",
        None,
        ConsentInput("v1", "fictional-hash", "self"),
        f"book-{number}",
    )
    return replace(req, **changes)


def accept(engine, clock, req):
    result = book(engine, clock, req)
    assert isinstance(result, BookingOk), result
    return result


@pytest.mark.parametrize(
    "raw", ["01000000005", "+201000000005", "00201000000005", "010 0000 0005", "010-0000-0005"]
)
def test_phone_normalization(raw):
    assert normalize_phone(raw) == "+201000000005"


@pytest.mark.parametrize(
    "raw",
    ["0212345678", "0101", "+201300000005", "0100000000x", "٠١٠٠٠٠٠٠٠٠٥", "010/00000005", None],
)
def test_bad_phone(raw):
    assert normalize_phone(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["Karim Mahmoud", "كريم محمود", "Abd-El Rahman", "O'Neil", " أَحْـمَد  علي ", "Élodie", "لؤي"],
)
def test_valid_names(raw):
    assert valid_name(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "Abd.Rahman",
        "Karim2",
        "www.x.com",
        "http x",
        "a",
        "a" * 61,
        "<script>",
        "x'; DROP TABLE patients;--",
        "Иван",
        "---",
        None,
    ],
)
def test_invalid_names(raw):
    assert not valid_name(raw)


def test_normalized_identity():
    assert normalize_name(" أَحْـمَد  علي ") == normalize_name("احمد علي")
    assert normalize_name(" KARIM  MAHMOUD ") == "karim mahmoud"
    assert normalize_name("فاطمة مصطفى") == "فاطمه مصطفي"


def test_time_limit_cancel_and_queue_number(engine, booked_clinic):
    clinic, clock = booked_clinic
    accepted = [accept(engine, clock, request(clinic, i)) for i in range(1, 18)]
    assert [r.queue_number for r in accepted] == list(range(1, 18))
    assert [r.expected_shown.astimezone(CAIRO).strftime("%H:%M") for r in accepted] == [
        f"{19 + (i * 15) // 60:02d}:{(i * 15) % 60:02d}" for i in range(17)
    ]
    assert book(engine, clock, request(clinic, 18)) == BookingRefused("full", THURSDAY)
    assert isinstance(
        cancel(engine, clock, accepted[0].link_code, "0001", "cancel-1"), CancelResult
    )
    fresh = accept(engine, clock, request(clinic, 1, idempotency_key="rebook"))
    assert fresh.queue_number == 18
    assert fresh.expected_shown.astimezone(CAIRO).hour == 23


def test_maximum_and_cutoff(engine):
    clinic, clock = setup(engine, maximum=10)
    for i in range(1, 11):
        accept(engine, clock, request(clinic, i))
    assert book(engine, clock, request(clinic, 11)) == BookingRefused("full", THURSDAY)
    clock.advance(minutes=2 * 1440 + 600)  # Tuesday 22:00, a different empty evening.
    req = request(clinic, 12, date=date(2026, 10, 13))
    # Empty today's queue for the cutoff boundary.
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().values(state="cancelled"))
    req = replace(req, date=TUESDAY)
    result = accept(engine, clock, req)
    assert result.expected_shown.astimezone(CAIRO).strftime("%H:%M") == "22:30"
    clock.advance(minutes=1)
    assert book(engine, clock, request(clinic, 13)) == BookingRefused("booking_closed", THURSDAY)


@pytest.mark.parametrize(
    "changes",
    [
        {"patient_name": "Karim2"},
        {"contact_phone": "02"},
        {"lang": "unknown"},
        {"area_id": -1},
        {"area_id": True},
        {"consent": ConsentInput("v1", "hash", "unknown")},
        {"consent": ConsentInput("", "hash", "self")},
        {"consent": ConsentInput("v1", "", "other")},
        {"actor": "doctor"},
    ],
)
def test_invalid_request(engine, booked_clinic, changes):
    clinic, clock = booked_clinic
    assert book(engine, clock, request(clinic, **changes)) == BookingRefused("invalid_input")


def test_closed_days_and_precedence(engine, booked_clinic):
    clinic, clock = booked_clinic
    monday = date(2026, 10, 5)
    assert book(engine, clock, request(clinic, date=monday)) == BookingRefused(
        "closed_day", TUESDAY
    )
    assert book(engine, clock, request(clinic, date=date(2026, 10, 3))).reason == "closed_day"
    with write_tx(engine) as conn:
        conn.execute(
            s.clinic_day_overrides.insert().values(clinic_id=clinic, date=TUESDAY, closed=True)
        )
    assert book(engine, clock, request(clinic)) == BookingRefused("closed_day", THURSDAY)
    for state in ("cancelled", "closed"):
        with write_tx(engine) as conn:
            evening = get_or_create_evening(conn, clinic, THURSDAY)
            conn.execute(s.evenings.update().where(s.evenings.c.id == evening).values(state=state))
        assert book(engine, clock, request(clinic, date=THURSDAY)).reason == "closed_day"
    assert book(engine, clock, request(clinic, patient_name="x")).reason == "invalid_input"


def test_duplicate_phone_cap_and_contact_identity(engine, booked_clinic):
    clinic, clock = booked_clinic
    names = ["أَحْـمد علي", "Mona Ali", "Samir Ali"]
    results = [
        accept(engine, clock, request(clinic, patient_name=name, idempotency_key=f"name-{i}"))
        for i, name in enumerate(names)
    ]
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(max_per_evening=3))
    assert (
        book(
            engine, clock, request(clinic, patient_name="احمد علي", idempotency_key="duplicate")
        ).reason
        == "already_booked"
    )
    assert (
        book(
            engine, clock, request(clinic, patient_name="Fourth Name", idempotency_key="fourth")
        ).reason
        == "phone_cap"
    )
    cancel(engine, clock, results[1].link_code, "0001", "free-phone")
    accept(engine, clock, request(clinic, patient_name="Fourth Name", idempotency_key="fourth"))
    with write_tx(engine) as conn:
        assert conn.execute(select(func.count()).select_from(s.contacts)).scalar_one() == 1
        conn.execute(s.clinics.update().values(max_per_evening=None))
    accept(engine, clock, request(clinic, 2, patient_name="احمد علي"))
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.patients)).scalar_one() == 5


def test_cancelled_and_past_do_not_count(engine, booked_clinic):
    clinic, clock = booked_clinic
    for i, day in enumerate([date(2026, 10, 4), TUESDAY, THURSDAY]):
        accept(
            engine,
            clock,
            request(
                clinic, date=day, patient_name=f"Name {chr(65 + i)}", idempotency_key=f"cap-{i}"
            ),
        )
    clock.advance(minutes=1440)
    accept(
        engine,
        clock,
        request(clinic, date=date(2026, 10, 11), patient_name="Name D", idempotency_key="new-cap"),
    )
    assert (
        book(
            engine,
            clock,
            request(
                clinic, date=date(2026, 10, 13), patient_name="Name E", idempotency_key="cap-full"
            ),
        ).reason
        == "phone_cap"
    )


def test_idempotency_codes_and_privacy(engine, booked_clinic):
    clinic, clock = booked_clinic
    req = request(clinic, patient_name="أحمد علي")
    first = accept(engine, clock, req)
    assert len(first.link_code) == 22
    assert link_code_for(first.booking_id) == first.link_code
    assert first.link_code not in repr(first)
    replay = accept(engine, clock, replace(req, patient_name="Invalid2", contact_phone="bad"))
    assert replay == replace(first, repeated=True, link_code=None)
    with engine.connect() as conn:
        stored = conn.execute(select(s.bookings)).mappings().one()
        assert stored["link_code_hash"] == hashlib.sha256(first.link_code.encode()).hexdigest()
        assert first.link_code not in str(conn.execute(select(s.idempotency_keys)).all())
        assert conn.execute(select(func.count()).select_from(s.consents)).scalar_one() == 1
    with pytest.raises(IdempotencyConflict):
        book(engine, clock, replace(req, clinic_id=clinic + 1))
    with pytest.raises(IdempotencyConflict):
        cancel(engine, clock, first.link_code, "0001", req.idempotency_key)
    other = accept(engine, clock, request(clinic, 2, patient_name="Private Name", lang="en"))
    view = booking_view(engine, first.link_code)
    assert view.patient_first_name == "احمد"
    assert view.doctor_name == "هشام مصطفى"
    assert set(asdict(view)) == {
        "booking_id",
        "clinic_id",
        "lang",
        "evening_state",
        "state_reason",
        "is_sandbox",
        "patient_first_name",
        "doctor_name",
        "date",
        "queue_number",
        "expected_shown",
        "state",
        "clinic_address",
        "clinic_phone",
        "clinic_lat",
        "clinic_lng",
    }
    assert "Private" not in str(asdict(view))
    assert booking_view(engine, other.link_code).doctor_name == "Hesham Mostafa"
    assert booking_view(engine, "unknown") is None


def test_caller_rollback(engine, booked_clinic):
    clinic, clock = booked_clinic
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        assert isinstance(book_in_tx(conn, clock, request(clinic)), BookingOk)
        conn.rollback()
        for table in [
            s.bookings,
            s.consents,
            s.idempotency_keys,
            s.patients,
            s.contacts,
            s.evenings,
        ]:
            assert conn.execute(select(func.count()).select_from(table)).scalar_one() == 0


def test_link_lockout_known_unknown_and_window_reset(engine, booked_clinic):
    clinic, clock = booked_clinic
    first = accept(engine, clock, request(clinic))
    for i in range(5):
        real = cancel(engine, clock, first.link_code, "9999", f"wrong-{i}")
        unknown = cancel(engine, clock, "unknown", "9999", f"unknown-{i}")
        assert real == unknown == LinkRefused("verify_failed")
    assert cancel(engine, clock, first.link_code, "0001", "correct") == LinkRefused("locked")
    assert cancel(engine, clock, "unknown", "0001", "unknown-correct") == LinkRefused("locked")
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.action_record)
                .where(s.action_record.c.kind == "link_verify_failed")
            ).scalar_one()
            == 5
        )
        counters = conn.execute(select(s.rate_counters)).mappings().all()
        assert all(row["count"] >= 5 for row in counters)
        assert all(
            first.link_code not in str(row) and "unknown" not in str(row) for row in counters
        )
    clock.advance(minutes=15)
    result = cancel(engine, clock, first.link_code, "0001", "correct")
    assert isinstance(result, CancelResult)
    assert cancel(engine, clock, first.link_code, "wrong", "correct") == replace(
        result, repeated=True
    )
    assert cancel(engine, clock, first.link_code, "0001", "again") == LinkRefused("not_cancellable")
    assert cancel(engine, clock, "unknown", "0001", "unknown-reset") == LinkRefused("verify_failed")


def test_change_day_savepoint_replay_and_cap_exemption(engine, booked_clinic):
    clinic, clock = booked_clinic
    original = accept(engine, clock, request(clinic, consent=ConsentInput("v1", "hash", "other")))
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(max_per_evening=1))
    accept(engine, clock, request(clinic, 2, date=THURSDAY))
    with write_tx(engine) as conn:
        before = {
            table.name: conn.execute(select(table)).all()
            for table in [s.bookings, s.consents, s.idempotency_keys, s.action_record, s.evenings]
        }
        assert change_day_in_tx(conn, clock, original.link_code, "0001", THURSDAY, "move") == (
            BookingRefused("full", date(2026, 10, 11))
        )
        assert before == {
            table.name: conn.execute(select(table)).all()
            for table in [s.bookings, s.consents, s.idempotency_keys, s.action_record, s.evenings]
        }
        conn.execute(s.clinics.update().values(max_per_evening=None))
    for i, day in enumerate([date(2026, 10, 11), date(2026, 10, 13)]):
        accept(
            engine,
            clock,
            request(
                clinic, date=day, patient_name=f"Name {chr(65 + i)}", idempotency_key=f"family-{i}"
            ),
        )
    moved = change_day(engine, clock, original.link_code, "0001", THURSDAY, "move")
    assert isinstance(moved, ChangeDayResult)
    assert moved.link_code != original.link_code
    assert change_day(engine, clock, original.link_code, "wrong", TUESDAY, "move") == replace(
        moved, link_code=None, repeated=True
    )
    with engine.connect() as conn:
        old = (
            conn.execute(select(s.bookings).where(s.bookings.c.id == original.booking_id))
            .mappings()
            .one()
        )
        new = (
            conn.execute(select(s.bookings).where(s.bookings.c.id == moved.new_booking_id))
            .mappings()
            .one()
        )
        assert old["state"] == "cancelled"
        assert (old["patient_id"], old["contact_id"]) == (new["patient_id"], new["contact_id"])
        consent = (
            conn.execute(select(s.consents).where(s.consents.c.booking_id == moved.new_booking_id))
            .mappings()
            .one()
        )
        assert (consent["booking_for"], consent["version"], consent["text_hash"]) == (
            "other",
            "v1",
            "hash",
        )


def test_golden_path_and_carried_pace(engine):
    clinic, clock = setup(engine, pace=13.33)
    for i in range(1, 7):
        accept(engine, clock, request(clinic, i))
    father = accept(
        engine,
        clock,
        request(
            clinic, 7, patient_name="Mahmoud Hassan", consent=ConsentInput("v1", "hash", "other")
        ),
    )
    assert father.queue_number == 7
    assert father.expected_shown.astimezone(CAIRO).strftime("%H:%M") == "20:20"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.consents.c.booking_for).where(s.consents.c.booking_id == father.booking_id)
            ).scalar_one()
            == "other"
        )
        evening = conn.execute(select(s.evenings.c.id)).scalar_one()
        assert current_pace(conn, clinic, evening) == 13.33
        assert people_ahead_of_new_booking(conn, evening) == 7
    with write_tx(engine) as conn:
        conn.execute(s.learned_pace.update().values(n=0))
        assert current_pace(conn, clinic, evening) == 15
        conn.execute(s.learned_pace.delete())
        assert current_pace(conn, clinic, None) == 15


def test_overrides_overnight_tonight_and_search(engine, booked_clinic):
    clinic, clock = booked_clinic
    assert open_days(engine, clock, clinic, TUESDAY, 2) == [TUESDAY, THURSDAY]
    assert nearest_open_day(engine, clock, clinic, TUESDAY) == THURSDAY
    assert open_days(engine, clock, clinic, TUESDAY, 0) == []
    with write_tx(engine) as conn:
        conn.execute(
            s.clinic_day_overrides.insert().values(
                clinic_id=clinic, date=TUESDAY, start=time(19), end=time(1)
            )
        )
        snapshot = load_snapshot(conn, clinic, TUESDAY, clock.now(clinic))
        assert snapshot.clinic_end == datetime(2026, 10, 7, 1, tzinfo=CAIRO)
        for now in [
            datetime(2026, 10, 6, 13, tzinfo=CAIRO),
            datetime(2026, 10, 7, 2, 59, tzinfo=CAIRO),
        ]:
            tonight = tonight_evening(conn, clinic, now)
            assert tonight.evening_date == TUESDAY and tonight.evening_id is None
        assert tonight_evening(conn, clinic, datetime(2026, 10, 7, 3, 1, tzinfo=CAIRO)) is None
        eid = get_or_create_evening(conn, clinic, TUESDAY)
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="closed"))
        assert tonight_evening(conn, clinic, snapshot.clinic_start).evening_id == eid
        assert load_snapshot(conn, clinic, TUESDAY, clock.now(clinic)).state == "closed"
        conn.execute(s.clinic_hours.delete())
        conn.execute(s.clinic_day_overrides.delete())
    assert nearest_open_day(engine, clock, clinic, TUESDAY) is None
    assert open_days(engine, clock, clinic, TUESDAY, 2) == []


def test_running_evening_and_walkin_waiting_only(engine, booked_clinic):
    clinic, clock = booked_clinic
    clock.advance(minutes=2 * 1440 + 485)  # Tue 20:05
    with write_tx(engine) as conn:
        eid = get_or_create_evening(conn, clinic, TUESDAY)
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="running"))
        walkin = conn.execute(
            s.bookings.insert()
            .values(
                clinic_id=clinic,
                evening_id=eid,
                queue_number=1,
                order_key=1,
                source="walkin_tap",
                state="seen",
                lang="ar",
                created_at=clock.now(clinic),
            )
            .returning(s.bookings.c.id)
        ).scalar_one()
        conn.execute(
            s.visits.insert().values(
                clinic_id=clinic,
                evening_id=eid,
                booking_id=walkin,
                started_at=datetime(2026, 10, 6, 20, tzinfo=CAIRO),
            )
        )
        conn.execute(s.clinics.update().values(max_per_evening=1))
        assert people_ahead_of_new_booking(conn, eid) == 0
    new = accept(engine, clock, request(clinic))
    assert new.queue_number == 2
    assert new.expected_shown.astimezone(CAIRO).strftime("%H:%M") == "20:15"


def concurrent_last_place(engine, limit):
    clinic, clock = setup(engine, maximum=2 if limit == "max" else None)
    fill = 1 if limit == "max" else 16
    for i in range(1, fill + 1):
        accept(engine, clock, request(clinic, i))
    barrier = Barrier(2)

    def attempt(i):
        barrier.wait(timeout=10)
        return book(engine, clock, request(clinic, i))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, i) for i in (30, 31)]
        results = [future.result(timeout=30) for future in futures]
    assert sum(isinstance(r, BookingOk) for r in results) == 1
    assert BookingRefused("full", THURSDAY) in results


@pytest.mark.parametrize("limit", ["max", "time"])
def test_concurrent_last_place_sqlite(engine, limit):
    concurrent_last_place(engine, limit)


@pytest.mark.postgres
@pytest.mark.parametrize("limit", ["max", "time"])
def test_concurrent_last_place_postgres(postgres_engine, limit):
    concurrent_last_place(postgres_engine, limit)


def concurrent_phone_or_intent(engine, mode):
    clinic, clock = setup(engine)
    if mode == "phone":
        for i, day in enumerate([TUESDAY, THURSDAY]):
            accept(
                engine,
                clock,
                request(
                    clinic,
                    date=day,
                    patient_name=f"Person {chr(65 + i)}",
                    idempotency_key=f"prior-{i}",
                ),
            )
    barrier = Barrier(2)

    def attempt(i):
        req = (
            request(
                clinic,
                date=date(2026, 10, 11 + i * 2),
                patient_name=f"Person {chr(67 + i)}",
                idempotency_key=f"new-{i}",
            )
            if (mode == "phone")
            else request(clinic)
        )
        barrier.wait(timeout=10)
        return book(engine, clock, req)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, i) for i in range(2)]
        results = [future.result(timeout=30) for future in futures]
    if mode == "phone":
        assert sum(isinstance(r, BookingOk) for r in results) == 1
        assert BookingRefused("phone_cap") in results
    else:
        assert all(isinstance(r, BookingOk) for r in results)
        assert results[0].booking_id == results[1].booking_id
        assert sum(r.repeated for r in results) == 1
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.contacts)).scalar_one() == 1


@pytest.mark.parametrize("mode", ["phone", "intent"])
def test_concurrent_phone_and_intent_sqlite(engine, mode):
    concurrent_phone_or_intent(engine, mode)


@pytest.mark.postgres
@pytest.mark.parametrize("mode", ["phone", "intent"])
def test_concurrent_phone_and_intent_postgres(postgres_engine, mode):
    concurrent_phone_or_intent(postgres_engine, mode)


def test_contact_unique_constraint(engine, booked_clinic):
    from sqlalchemy.exc import IntegrityError

    clinic, clock = booked_clinic
    accept(engine, clock, request(clinic))
    with pytest.raises(IntegrityError), write_tx(engine) as conn:
        conn.execute(s.contacts.insert().values(clinic_id=clinic, phone_e164="+201000000001"))


def test_successful_verification_consumes_no_failure(engine, booked_clinic):
    clinic, clock = booked_clinic
    original = accept(engine, clock, request(clinic))
    for i in range(7):
        assert (
            change_day(
                engine, clock, original.link_code, "0001", date(2026, 10, 5), f"closed-move-{i}"
            ).reason
            == "closed_day"
        )
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.rate_counters)).scalar_one() == 0
    assert isinstance(cancel(engine, clock, original.link_code, "0001", "cancel-ok"), CancelResult)


def test_replay_preserves_original_result_after_time_changes(engine, booked_clinic):
    clinic, clock = booked_clinic
    req = request(clinic)
    original = accept(engine, clock, req)
    with write_tx(engine) as conn:
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == original.booking_id)
            .values(expected_shown=datetime(2026, 10, 6, 21, tzinfo=CAIRO))
        )
    assert accept(engine, clock, req) == replace(original, link_code=None, repeated=True)
