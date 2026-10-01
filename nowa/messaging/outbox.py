from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa.clock import Clock
from nowa.config import get_settings
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
        return phone, None
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
    channel: Literal["sms", "telegram"] | None = None,
    pending_signup_id: int | None = None,
) -> int:
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
        "sms",
        "telegram",
    }:
        raise ValueError("Invalid audience or channel")
    force_screen = False
    if pending_signup_id is not None:
        if audience != "doctor" or booking_id is not None or channel != "sms":
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
    if channel is None:
        channel = "sms" if audience == "patient" else "telegram" if chat else "sms"
        force_screen = audience == "doctor" and not chat and texts.allowed(clinic)
    if channel == "telegram" and not chat:
        raise ValueError("No Telegram link")
    if kind == "secretary" and channel != "telegram":
        raise ValueError("Secretary has no SMS identity")
    settings = get_settings()
    adapter = (
        "telegram"
        if channel == "telegram"
        else (
            "screen_phone"
            if clinic["is_sandbox"] or force_screen
            else settings.sms_adapter or "screen_phone"
        )
    )
    if force_screen:
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
    return _insert(conn, clock, values)


def enqueue_backup_copy(conn: Connection, clock: Clock, outbox_id: int) -> int | None:
    row = conn.execute(select(outbox).where(outbox.c.id == outbox_id)).mappings().one()
    clinic_lock(conn, row["clinic_id"])
    key = row["idempotency_key"] + ":tg"
    existing = conn.execute(
        select(outbox.c.id).where(outbox.c.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    if row["status"] != "failed" or row["channel"] != "sms" or row["audience"] != "patient":
        raise ValueError("Backup requires a failed patient SMS")
    _, chat = recipient(conn, row)
    if not chat:
        return None
    values = {
        key: row[key]
        for key in (
            "clinic_id",
            "booking_id",
            "pending_signup_id",
            "recipient_kind",
            "audience",
            "template_id",
            "lang",
            "body",
        )
    }
    values.update(
        channel="telegram",
        adapter="telegram",
        status="queued",
        idempotency_key=key,
        created_at=clock.now(row["clinic_id"]),
    )
    oid = _insert(conn, clock, values)
    audit(conn, row, "message_backup")
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
