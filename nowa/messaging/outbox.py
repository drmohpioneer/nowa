from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa.clock import Clock
from nowa.core.timers import schedule_timer
from nowa.messaging import texts
from nowa.messaging.templates import render, render_operational
from nowa.record import write_action
from nowa.schema import (
    bookings,
    clinics,
    contacts,
    doctors,
    outbox,
    patients,
    pending_signups,
    secretary_links,
    telegram_links,
)


def clinic_lock(conn: Connection, clinic_id: int) -> Mapping[Any, Any]:
    return (
        conn.execute(select(clinics).where(clinics.c.id == clinic_id).with_for_update())
        .mappings()
        .one()
    )


def doctor_row(conn: Connection, clinic_id: int) -> Mapping[Any, Any]:
    return conn.execute(select(doctors).where(doctors.c.clinic_id == clinic_id)).mappings().one()


def secretary_chat(conn: Connection, clinic_id: int) -> str | None:
    return conn.execute(
        select(secretary_links.c.telegram_chat_id).where(
            secretary_links.c.clinic_id == clinic_id,
            secretary_links.c.revoked_at.is_(None),
            secretary_links.c.used_at.is_not(None),
            secretary_links.c.telegram_chat_id.is_not(None),
        )
    ).scalar_one_or_none()


def telegram_chat(conn: Connection, phone: str, kind: str) -> str | None:
    return conn.execute(
        select(telegram_links.c.telegram_chat_id).where(
            telegram_links.c.phone_e164 == phone, telegram_links.c.kind == kind
        )
    ).scalar_one_or_none()


def recipient(conn: Connection, row: Mapping[Any, Any]) -> tuple[str | None, str | None]:
    kind = row["recipient_kind"]
    if kind == "pending_signup":
        phone = conn.execute(
            select(pending_signups.c.mobile_e164).where(
                pending_signups.c.id == row["pending_signup_id"]
            )
        ).scalar_one_or_none()
        return phone, telegram_chat(conn, phone, "doctor") if phone else None
    if kind == "secretary":
        return None, secretary_chat(conn, row["clinic_id"])
    if kind == "patient_contact":
        phone = conn.execute(
            select(contacts.c.phone_e164)
            .join(bookings, bookings.c.contact_id == contacts.c.id)
            .where(
                bookings.c.id == row["booking_id"],
                bookings.c.clinic_id == row["clinic_id"],
                contacts.c.clinic_id == row["clinic_id"],
            )
        ).scalar_one_or_none()
        return phone, telegram_chat(conn, phone, "patient") if phone else None
    if kind in {"doctor", "screen"}:
        doctor = doctor_row(conn, row["clinic_id"])
        phone = doctor["mobile_e164"]
        return phone, telegram_chat(conn, phone, "doctor")
    raise ValueError("Unknown recipient kind")


def audit(conn: Connection, row: Mapping[Any, Any], kind: str, note: str | None = None) -> None:
    write_action(conn, row["clinic_id"], "system", kind, booking_id=row["booking_id"], text=note)


def _insert(conn: Connection, clock: Clock, values: dict[str, Any]) -> int:
    oid = int(conn.execute(outbox.insert().values(**values).returning(outbox.c.id)).scalar_one())
    audit(conn, values, "message_enqueue")
    if values["status"] == "queued":
        schedule_timer(
            conn,
            values["clinic_id"],
            "send_retry",
            clock.now(values["clinic_id"]),
            {"outbox_id": oid, "attempt": 1},
            f"send:{oid}:1",
        )
    else:
        audit(conn, values, "message_block", values["status"])
    return oid


def enqueue_message(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    template_id: str,
    lang: str,
    audience: str,
    booking_id: int | None,
    blanks: dict[str, Any],
    idempotency_key: str,
    channel: str | None = None,
    pending_signup_id: int | None = None,
) -> int:
    if channel not in {None, "telegram"}:
        raise ValueError("Invalid channel")
    existing = conn.execute(
        select(outbox.c.id).where(outbox.c.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    clinic = clinic_lock(conn, clinic_id)
    existing = conn.execute(
        select(outbox.c.id).where(outbox.c.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    if audience not in {"patient", "doctor", "secretary"} or channel not in {
        None,
        "telegram",
    }:
        raise ValueError("Invalid audience or channel")
    if pending_signup_id is not None:
        if audience != "doctor" or booking_id is not None:
            raise ValueError("Invalid pending sign-up recipient")
        signup = (
            conn.execute(select(pending_signups).where(pending_signups.c.id == pending_signup_id))
            .mappings()
            .one_or_none()
        )
        if (
            signup is None
            or signup["expires_at"] <= clock.now(clinic_id)
            or signup["completed_at"] is not None
        ):
            raise ValueError("Missing, expired or completed sign-up")
        kind = "pending_signup"
    elif audience == "patient":
        if booking_id is None:
            raise ValueError("Patient needs a booking")
        kind = "patient_contact"
    else:
        kind = audience
        if booking_id is not None:
            if (
                conn.execute(
                    select(bookings.c.id).where(
                        bookings.c.id == booking_id, bookings.c.clinic_id == clinic_id
                    )
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("Booking does not belong to clinic")
    values: dict[str, Any] = dict(
        clinic_id=clinic_id,
        booking_id=booking_id,
        pending_signup_id=pending_signup_id,
        recipient_kind=kind,
    )
    phone, chat = recipient(conn, values)
    if kind == "secretary" and not chat:
        raise ValueError("No active secretary link")
    if kind != "secretary" and not phone:
        raise ValueError("No recipient")
    channel = "telegram"
    no_channel = not chat and not texts.allowed(clinic)
    adapter = "telegram" if chat or no_channel else "screen_phone"
    if audience == "doctor" and not chat and kind != "pending_signup" and not no_channel:
        values["recipient_kind"] = "screen"
    approved = True
    if template_id.startswith("op:"):
        rendered = render_operational(template_id[3:], lang, blanks)
        body, approved = rendered.text, rendered.approved
    else:
        if template_id not in {"1", "2", "3", "4", "5", "6"}:
            raise ValueError("Only outbox templates 1-6 are allowed")
        body = render(template_id, lang, blanks)
    values.update(
        audience=audience,
        template_id=template_id,
        lang=lang,
        channel=channel,
        adapter=adapter,
        body=body,
        status="queued" if approved or texts.allowed(clinic) else "blocked_unapproved",
        idempotency_key=idempotency_key,
        created_at=clock.now(clinic_id),
    )
    if no_channel:
        values["status"] = "failed"
    oid = _insert(conn, clock, values)
    if no_channel:
        failed = conn.execute(select(outbox).where(outbox.c.id == oid)).mappings().one()
        audit(conn, failed, "message_failure", "no_channel")
        alert_failure(conn, clock, failed)
    return oid


@dataclass(frozen=True)
class ScreenMessage:
    outbox_id: int
    audience: str
    booking_id: int | None
    template_id: str
    body: str
    status: str
    created_at: datetime
    pending_signup_id: int | None = None


def screen_messages(conn: Connection, clinic_id: int, after_id: int) -> list[ScreenMessage]:
    rows = conn.execute(
        select(outbox)
        .where(
            outbox.c.clinic_id == clinic_id,
            outbox.c.adapter == "screen_phone",
            outbox.c.id > after_id,
        )
        .order_by(outbox.c.id)
    ).mappings()
    return [
        ScreenMessage(
            row["id"],
            row["audience"],
            row["booking_id"],
            row["template_id"],
            row["body"],
            row["status"],
            row["created_at"],
            row["pending_signup_id"],
        )
        for row in rows
    ]


def alert_failure(conn: Connection, clock: Clock, row: Mapping[Any, Any]) -> None:
    """One alert path for unavailable recipients and exhausted delivery attempts."""
    if row["audience"] != "patient":
        return
    booking = (
        conn.execute(
            select(bookings).where(
                bookings.c.id == row["booking_id"], bookings.c.clinic_id == row["clinic_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    phone, _ = recipient(conn, row)
    name = (
        None
        if booking is None
        else conn.execute(
            select(patients.c.name).where(
                patients.c.id == booking["patient_id"], patients.c.clinic_id == row["clinic_id"]
            )
        ).scalar_one_or_none()
    )
    if not booking or not phone or not name:
        audit(conn, row, "message_alert_unavailable", "no_recipient")
        return
    doctor = doctor_row(conn, row["clinic_id"])
    blanks = {"patient_name": name, "queue_number": booking["queue_number"], "phone": phone}
    enqueue_message(
        conn,
        clock,
        row["clinic_id"],
        "op:doctor_alert_unreachable",
        doctor["lang"],
        "doctor",
        row["booking_id"],
        blanks,
        row["idempotency_key"] + ":alert:doctor",
    )
    clinic = clinic_lock(conn, row["clinic_id"])
    if clinic["secretary_alerts_on"] and secretary_chat(conn, row["clinic_id"]):
        enqueue_message(
            conn,
            clock,
            row["clinic_id"],
            "op:doctor_alert_unreachable",
            "ar",
            "secretary",
            row["booking_id"],
            blanks,
            row["idempotency_key"] + ":alert:secretary",
        )
