"""Deterministic standby admission, offers and expiry. Callers own transactions."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, Clock
from nowa.core import booking
from nowa.core.text_norm import origin_text
from nowa.core.timers import TimerContext, schedule_timer
from nowa.messaging.outbox import enqueue_message, telegram_chat
from nowa.messaging.templates import DoctorNames


@dataclass(frozen=True)
class Joined:
    standby_id: int
    position: int
    repeated: bool = False


def contact_for(conn: Connection, req: booking.BookingRequest) -> int:
    phone = booking.normalize_phone(req.contact_phone)
    assert phone is not None
    booking._advisory_lock(conn, f"{req.clinic_id}|{phone}")
    cid: int | None = conn.execute(
        select(s.contacts.c.id).where(
            s.contacts.c.clinic_id == req.clinic_id,
            s.contacts.c.phone_e164 == phone,
        )
    ).scalar_one_or_none()
    if cid is None:
        cid = conn.execute(
            s.contacts.insert()
            .values(
                clinic_id=req.clinic_id,
                phone_e164=phone,
            )
            .returning(s.contacts.c.id)
        ).scalar_one()
    return int(cid)


def telegram_required(conn: Connection, clinic_id: int) -> bool:
    """A practice clinic shows every message on the drawn phone, so it needs no link."""
    sandbox = conn.execute(
        select(s.clinics.c.is_sandbox).where(s.clinics.c.id == clinic_id)
    ).scalar_one()
    return not sandbox


def join_in_tx(
    conn: Connection, clock: Clock, req: booking.BookingRequest
) -> Joined | booking.BookingRefused:
    if not booking._valid_request(conn, req):
        return booking.BookingRefused("invalid_input")
    now = clock.now(req.clinic_id)
    if booking._day_status(conn, req.clinic_id, req.date, now)[0] in {
        "closed_day",
        "booking_closed",
    }:
        return booking.BookingRefused("booking_closed")
    eid = booking.get_or_create_evening(conn, req.clinic_id, req.date)
    booking._lock_evening(conn, eid)
    if booking._day_status(conn, req.clinic_id, req.date, now)[0] in {
        "closed_day",
        "booking_closed",
    }:
        return booking.BookingRefused("booking_closed")
    contact_id = contact_for(conn, req)
    prior = (
        conn.execute(
            select(s.standbys).where(
                s.standbys.c.clinic_id == req.clinic_id,
                s.standbys.c.date == req.date,
                s.standbys.c.contact_id == contact_id,
            )
        )
        .mappings()
        .first()
    )
    if prior:
        return Joined(prior["id"], prior["position"], True)
    phone = booking.normalize_phone(req.contact_phone)
    assert phone is not None
    if telegram_required(conn, req.clinic_id) and telegram_chat(conn, phone, "patient") is None:
        return booking.BookingRefused("invalid_input")
    if booking.active_for_phone(conn, clock, req.clinic_id, contact_id) >= 3:
        return booking.BookingRefused("phone_cap")
    identities = (
        conn.execute(
            select(s.patients)
            .join(s.bookings)
            .where(
                s.bookings.c.clinic_id == req.clinic_id,
                s.bookings.c.contact_id == contact_id,
            )
        )
        .mappings()
        .all()
    )
    identities = list(identities) + list(
        conn.execute(
            select(s.patients)
            .join(s.standbys)
            .where(
                s.standbys.c.clinic_id == req.clinic_id,
                s.standbys.c.contact_id == contact_id,
            )
        ).mappings()
    )
    patient_id = next(
        (
            r["id"]
            for r in identities
            if booking.normalize_name(req.patient_name)
            in {
                booking.normalize_name(r["name"]),
                booking.normalize_name(r["name_en"] or r["name"]),
            }
        ),
        None,
    )
    if (
        patient_id is not None
        and conn.execute(
            select(s.bookings.c.id).where(
                s.bookings.c.evening_id == eid,
                s.bookings.c.patient_id == patient_id,
                s.bookings.c.state != "cancelled",
            )
        ).first()
    ):
        return booking.BookingRefused("already_booked")
    if patient_id is None:
        patient_id = conn.execute(
            s.patients.insert()
            .values(
                clinic_id=req.clinic_id,
                name=booking.display_name(req.patient_name),
                name_en=req.patient_name_en,
            )
            .returning(s.patients.c.id)
        ).scalar_one()
    position = (
        conn.execute(
            select(func.max(s.standbys.c.position)).where(
                s.standbys.c.evening_id == eid,
            )
        ).scalar_one()
        or 0
    ) + 1
    sid: int = conn.execute(
        s.standbys.insert()
        .values(
            clinic_id=req.clinic_id,
            date=req.date,
            evening_id=eid,
            patient_id=patient_id,
            contact_id=contact_id,
            area_id=req.area_id,
            origin_text=origin_text(req.origin_text, req.area_id),
            booking_for=req.consent.booking_for,
            consent_version=req.consent.version,
            consent_text_hash=req.consent.text_hash,
            consented_at=now,
            position=position,
            state="waiting",
            lang=req.lang,
            created_at=now,
        )
        .returning(s.standbys.c.id)
    ).scalar_one()
    record.write_action(conn, req.clinic_id, "patient", "standby_joined", patient_id=patient_id)
    from nowa.core.timing import ensure_evening_timers

    ensure_evening_timers(conn, clock, eid)
    offer_next(conn, clock, eid)
    return Joined(sid, position)


def count(conn: Connection, clinic_id: int, evening_id: int | None, *, taken: bool = False) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(s.standbys)
            .where(
                s.standbys.c.clinic_id == clinic_id,
                s.standbys.c.evening_id == evening_id,
                s.standbys.c.state.in_(("taken",) if taken else ("waiting", "offered")),
            )
        ).scalar_one()
    )


def lookup(conn: Connection, code: str) -> RowMapping | None:
    if len(code) != 43:
        return None
    return (
        conn.execute(
            select(s.standbys).where(
                s.standbys.c.offer_code_hash == hashlib.sha256(code.encode()).hexdigest(),
            )
        )
        .mappings()
        .first()
    )


def next_day_link(conn: Connection, clock: Clock, clinic_id: int, day: date) -> str:
    days = booking._open_days(
        conn,
        clock,
        clinic_id,
        max(
            day + timedelta(days=1),
            clock.now(clinic_id).astimezone(CAIRO).date(),
        ),
        1,
    )
    slug: str = conn.execute(
        select(s.clinics.c.slug).where(s.clinics.c.id == clinic_id)
    ).scalar_one()
    return f"/c/{slug}" + ("?day=" + days[0].isoformat() if days else "")


def identity_blanks(conn: Connection, row: RowMapping) -> dict[str, Any]:
    patient = (
        conn.execute(
            select(s.patients.c.name, s.patients.c.name_en).where(
                s.patients.c.id == row["patient_id"],
                s.patients.c.clinic_id == row["clinic_id"],
            )
        )
        .mappings()
        .one()
    )
    doctor = conn.execute(
        select(s.doctors.c.name_ar, s.doctors.c.name_en).where(
            s.doctors.c.clinic_id == row["clinic_id"],
        )
    ).one()
    return {
        "patient_name": dict(patient),
        "doctor_name": DoctorNames(doctor.name_ar, doctor.name_en),
    }


def offer_next(conn: Connection, clock: Clock, evening_id: int) -> None:
    evening = (
        conn.execute(select(s.evenings).where(s.evenings.c.id == evening_id).with_for_update())
        .mappings()
        .one()
    )
    cid, day = evening["clinic_id"], evening["date"]
    now = clock.now(cid)
    # The timer may be late after a restart; expiry is also enforced on every entry.
    conn.execute(
        s.standbys.update()
        .where(
            s.standbys.c.evening_id == evening_id,
            s.standbys.c.state == "offered",
            s.standbys.c.expires_at <= now,
        )
        .values(state="expired")
    )
    # Existing live offers already consume capacity in _day_status. A second
    # freed place can therefore go to a different standby without sharing a hold.
    reason, projected = booking._day_status(conn, cid, day, now)
    if reason is not None:
        return
    row = (
        conn.execute(
            select(s.standbys)
            .where(
                s.standbys.c.evening_id == evening_id,
                s.standbys.c.state == "waiting",
            )
            .order_by(s.standbys.c.position)
            .limit(1)
        )
        .mappings()
        .first()
    )
    if row is None:
        return
    code = secrets.token_urlsafe(32)
    expires = now + timedelta(minutes=20)
    conn.execute(
        s.standbys.update()
        .where(s.standbys.c.id == row["id"])
        .values(
            state="offered",
            offered_at=now,
            expires_at=expires,
            expected_time=projected,
            offer_code_hash=hashlib.sha256(code.encode()).hexdigest(),
        )
    )
    enqueue_message(
        conn,
        clock,
        cid,
        "op:standby_offer",
        row["lang"],
        "patient",
        None,
        {
            **identity_blanks(conn, row),
            "day": day,
            "expected_time": projected,
            "take_link": f"/s/{code}/take",
        },
        f"standby_offer:{row['id']}:{row['created_at'].timestamp()}",
        standby_id=row["id"],
    )
    schedule_timer(
        conn,
        cid,
        "standby_expire",
        expires,
        {"evening_id": evening_id},
        f"standby_expire:{row['id']}:{row['created_at'].timestamp()}",
    )


def expire(ctx: TimerContext, payload: dict[str, Any]) -> None:
    eid = payload.get("evening_id")
    if not isinstance(eid, int) or isinstance(eid, bool):
        return
    if ctx.conn.execute(
        select(s.evenings.c.id).where(
            s.evenings.c.id == eid,
            s.evenings.c.clinic_id == ctx.clinic_id,
        )
    ).first():
        offer_next(ctx.conn, ctx.clock, eid)


def close(conn: Connection, clock: Clock, evening_id: int) -> None:
    rows = (
        conn.execute(
            select(s.standbys).where(
                s.standbys.c.evening_id == evening_id,
                s.standbys.c.state.in_(("waiting", "offered")),
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        enqueue_message(
            conn,
            clock,
            row["clinic_id"],
            "op:standby_closed",
            row["lang"],
            "patient",
            None,
            {
                **identity_blanks(conn, row),
                "day": row["date"],
                "next_day_link": next_day_link(conn, clock, row["clinic_id"], row["date"]),
            },
            f"standby_closed:{row['id']}:{row['created_at'].timestamp()}",
            standby_id=row["id"],
        )
        conn.execute(
            s.standbys.update().where(s.standbys.c.id == row["id"]).values(state="expired")
        )


def take_in_tx(
    conn: Connection, clock: Clock, code: str, *, decline: bool = False
) -> booking.BookingOk | booking.BookingRefused:
    row = lookup(conn, code)
    if row is None:
        return booking.BookingRefused("invalid_input")
    booking._lock_evening(conn, row["evening_id"])
    row = lookup(conn, code)
    assert row is not None
    if row["state"] == "taken":
        booked = (
            conn.execute(select(s.bookings).where(s.bookings.c.id == row["booking_id"]))
            .mappings()
            .one()
        )
        return booking.BookingOk(
            booked["id"], booked["queue_number"], booked["expected_shown"], None, True
        )
    if row["state"] != "offered" or row["expires_at"] <= clock.now(row["clinic_id"]):
        offer_next(conn, clock, row["evening_id"])
        return booking.BookingRefused("booking_closed")
    # Remove the reservation before the normal booking rechecks admission; no other
    # transaction can acquire this evening until the booking and state both commit.
    conn.execute(
        s.standbys.update()
        .where(s.standbys.c.id == row["id"])
        .values(state="declined" if decline else "taken")
    )
    if decline:
        offer_next(conn, clock, row["evening_id"])
        return booking.BookingRefused("invalid_input")
    identity = conn.execute(
        select(s.patients.c.name, s.patients.c.name_en, s.contacts.c.phone_e164)
        .select_from(s.patients.join(s.contacts, s.contacts.c.id == row["contact_id"]))
        .where(s.patients.c.id == row["patient_id"])
    ).one()
    from nowa.core import flows

    req = booking.BookingRequest(
        row["clinic_id"],
        row["date"],
        identity.name,
        identity.phone_e164,
        row["lang"],
        row["area_id"],
        booking.ConsentInput(row["consent_version"], row["consent_text_hash"], row["booking_for"]),
        f"standby_take:{row['id']}:{row['created_at'].timestamp()}",
        patient_name_en=identity.name_en,
        origin_text=row["origin_text"],
    )
    result = flows.book_in_tx(conn, clock, req)
    conn.execute(
        s.standbys.update()
        .where(s.standbys.c.id == row["id"])
        .values(
            state="taken" if isinstance(result, booking.BookingOk) else "expired",
            booking_id=result.booking_id if isinstance(result, booking.BookingOk) else None,
        )
    )
    offer_next(conn, clock, row["evening_id"])
    return result
