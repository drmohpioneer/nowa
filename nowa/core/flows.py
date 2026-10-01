from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import schema as s
from nowa.clock import Clock
from nowa.core import booking, timing
from nowa.core.booking import (
    BookingOk,
    BookingRefused,
    BookingRequest,
    CancelResult,
    ChangeDayResult,
    ConsentInput,
    LinkRefused,
)
from nowa.db import write_tx
from nowa.messaging.outbox import enqueue_message


def _message(conn: Connection, clock: Clock, booking_id: int, template: str, key: str) -> None:
    row = conn.execute(select(s.bookings).where(s.bookings.c.id == booking_id)).mappings().one()
    enqueue_message(
        conn,
        clock,
        row["clinic_id"],
        template,
        row["lang"],
        "patient",
        booking_id,
        timing.patient_blanks(conn, booking_id, template),
        key,
    )


def _booked(
    conn: Connection, clock: Clock, result: BookingOk | BookingRefused, confirm: bool = True
) -> None:
    if not isinstance(result, BookingOk) or result.repeated:
        return
    evening_id: int = conn.execute(
        select(s.bookings.c.evening_id).where(s.bookings.c.id == result.booking_id)
    ).scalar_one()
    if confirm:
        _message(conn, clock, result.booking_id, "1", f"confirm:{result.booking_id}")
    timing.ensure_evening_timers(conn, clock, evening_id)
    timing.recompute(conn, clock, evening_id)


def book(
    engine: Engine, clock: Clock, req: BookingRequest, confirm: bool = True
) -> BookingOk | BookingRefused:
    with write_tx(engine) as conn:
        return book_in_tx(conn, clock, req, confirm)


def book_in_tx(
    conn: Connection, clock: Clock, req: BookingRequest, confirm: bool = True
) -> BookingOk | BookingRefused:
    result = booking.book_in_tx(conn, clock, req)
    _booked(conn, clock, result, confirm)
    return result


def cancel(
    engine: Engine, clock: Clock, link_code: str, last4: str, idempotency_key: str
) -> CancelResult | LinkRefused:
    with write_tx(engine) as conn:
        return cancel_in_tx(conn, clock, link_code, last4, idempotency_key)


def _cancellable_evening(
    conn: Connection,
    clock: Clock,
    link_code: str,
    last4: str,
    idempotency_key: str,
    new_date: date | None = None,
) -> LinkRefused | None:
    booking._advisory_lock(conn, "intent|" + idempotency_key)
    verified = booking._verify(conn, clock, link_code, last4)
    if isinstance(verified, LinkRefused):
        return verified
    evening_ids = {verified["evening_id"]}
    if isinstance(new_date, date) and not isinstance(new_date, datetime):
        target = conn.execute(
            select(s.evenings.c.id).where(
                s.evenings.c.clinic_id == verified["clinic_id"], s.evenings.c.date == new_date
            )
        ).scalar_one_or_none()
        if target is not None:
            evening_ids.add(target)
    # Preserve booking.change_day_in_tx's lock order for opposite two-day moves.
    for evening_id in sorted(evening_ids):
        booking._lock_evening(conn, evening_id)
    state: str = conn.execute(
        select(s.evenings.c.state).where(s.evenings.c.id == verified["evening_id"])
    ).scalar_one()
    if state not in {"scheduled", "doctor_on_way", "running"}:
        return LinkRefused("not_cancellable")
    return None


def cancel_in_tx(
    conn: Connection, clock: Clock, link_code: str, last4: str, idempotency_key: str
) -> CancelResult | LinkRefused:
    refused = _cancellable_evening(conn, clock, link_code, last4, idempotency_key)
    if refused is not None:
        return refused
    result = booking.cancel_in_tx(conn, clock, link_code, last4, idempotency_key)
    if isinstance(result, CancelResult) and not result.repeated:
        _message(conn, clock, result.booking_id, "3", f"cancel:{result.booking_id}")
        timing.recompute(conn, clock, result.evening_id)
    return result


def change_day(
    engine: Engine, clock: Clock, link_code: str, last4: str, new_date: date, idempotency_key: str
) -> ChangeDayResult | BookingRefused | LinkRefused:
    with write_tx(engine) as conn:
        return change_day_in_tx(conn, clock, link_code, last4, new_date, idempotency_key)


def change_day_in_tx(
    conn: Connection, clock: Clock, link_code: str, last4: str, new_date: date, idempotency_key: str
) -> ChangeDayResult | BookingRefused | LinkRefused:
    refused = _cancellable_evening(conn, clock, link_code, last4, idempotency_key, new_date)
    if refused is not None:
        return refused
    result = booking.change_day_in_tx(conn, clock, link_code, last4, new_date, idempotency_key)
    if isinstance(result, ChangeDayResult) and not result.repeated:
        _message(conn, clock, result.new_booking_id, "1", f"confirm:{result.new_booking_id}")
        timing.ensure_evening_timers(conn, clock, result.new_evening_id)
        old_evening: int = conn.execute(
            select(s.bookings.c.evening_id).where(s.bookings.c.id == result.old_booking_id)
        ).scalar_one()
        timing.recompute(conn, clock, old_evening)
        timing.recompute(conn, clock, result.new_evening_id)
    return result


def rebook(
    engine: Engine, clock: Clock, cancelled_booking_id: int, new_date: date, idempotency_key: str
) -> BookingOk | BookingRefused:
    with write_tx(engine) as conn:
        return rebook_in_tx(conn, clock, cancelled_booking_id, new_date, idempotency_key)


def rebook_in_tx(
    conn: Connection, clock: Clock, cancelled_booking_id: int, new_date: date, idempotency_key: str
) -> BookingOk | BookingRefused:
    row = (
        conn.execute(select(s.bookings).where(s.bookings.c.id == cancelled_booking_id))
        .mappings()
        .one_or_none()
    )
    if row is None or row["state"] != "cancelled" or row["source"] != "chat":
        return BookingRefused("invalid_input")
    cancelled = conn.execute(
        select(s.action_record.c.id).where(
            s.action_record.c.booking_id == cancelled_booking_id,
            s.action_record.c.kind.in_(("cancel_tonight", "close_untold")),
        )
    ).first()
    if cancelled is None:
        return BookingRefused("invalid_input")
    identity = conn.execute(
        select(s.patients.c.name, s.contacts.c.phone_e164)
        .select_from(s.patients.join(s.contacts, s.contacts.c.id == row["contact_id"]))
        .where(s.patients.c.id == row["patient_id"])
    ).one()
    consent = (
        conn.execute(select(s.consents).where(s.consents.c.booking_id == cancelled_booking_id))
        .mappings()
        .one()
    )
    req = BookingRequest(
        row["clinic_id"],
        new_date,
        identity.name,
        identity.phone_e164,
        row["lang"],
        row["area_id"],
        ConsentInput(consent["version"], consent["text_hash"], consent["booking_for"]),
        f"rebook:{cancelled_booking_id}",
    )
    result = booking.book_in_tx(conn, clock, req)
    _booked(conn, clock, result)
    return result
