import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.core import booking, flows, timing
from nowa.core.telegram_tokens import mint
from nowa.core.text_norm import western_digits
from nowa.db import write_tx


@dataclass(frozen=True)
class TokenResult:
    url: str | None = field(repr=False)
    repeated: bool = False


@dataclass(frozen=True)
class TelegramRefused:
    reason: Literal["sandbox"] = "sandbox"


def view(engine: Engine, code: str, lang: str | None = None) -> booking.BookingView | None:
    return booking.booking_view(engine, code, lang)


def _last4(value: str) -> str:
    value = western_digits(value)
    return value if re.fullmatch(r"[0-9]{4}", value) else ""


def cancel_by_link(
    engine: Engine, clock: Clock, code: str, last4: str, key: str
) -> booking.CancelResult | booking.LinkRefused:
    return flows.cancel(engine, clock, code, _last4(last4), key)


def change_day_by_link(
    engine: Engine, clock: Clock, code: str, last4: str, date: date, key: str
) -> booking.ChangeDayResult | booking.BookingRefused | booking.LinkRefused:
    return flows.change_day(engine, clock, code, _last4(last4), date, key)


def rebook_by_link(
    engine: Engine, clock: Clock, code: str, last4: str, date: date, key: str
) -> booking.BookingOk | booking.BookingRefused | booking.LinkRefused:
    with write_tx(engine) as conn:
        verified = booking.verify_link(conn, clock, code, _last4(last4))
    if isinstance(verified, booking.LinkRefused):
        return verified
    return flows.rebook(engine, clock, verified.booking_id, date, key)


def on_my_way(engine: Engine, clock: Clock, booking_id: int, key: str) -> timing.TapResult:
    return timing.patient_on_my_way(engine, clock, booking_id, key)


def undo_on_my_way(engine: Engine, clock: Clock, booking_id: int, key: str) -> timing.TapResult:
    return timing.patient_undo_on_my_way(engine, clock, booking_id, key)


def create_telegram_token(
    engine: Engine, clock: Clock, code: str, last4: str, idempotency_key: str
) -> TokenResult | TelegramRefused | booking.LinkRefused:
    with write_tx(engine) as conn:
        verified = booking.verify_link(conn, clock, code, _last4(last4))
        if isinstance(verified, booking.LinkRefused):
            return verified
        row = conn.execute(
            select(s.bookings.c.clinic_id, s.bookings.c.contact_id, s.clinics.c.is_sandbox)
            .join(s.clinics, s.clinics.c.id == s.bookings.c.clinic_id)
            .where(s.bookings.c.id == verified.booking_id)
        ).one()
        if row.is_sandbox:
            return TelegramRefused()
        # Serialize both intent replay and replacement of this contact's unused tokens.
        conn.execute(
            select(s.contacts.c.id).where(s.contacts.c.id == row.contact_id).with_for_update()
        ).one()
        replay = (
            conn.execute(
                select(s.idempotency_keys).where(s.idempotency_keys.c.key == idempotency_key)
            )
            .mappings()
            .first()
        )
        if replay is not None:
            if replay["clinic_id"] != row.clinic_id or replay["command"] != "patient_telegram":
                raise booking.IdempotencyConflict(idempotency_key)
            return TokenResult(None, True)
        now = clock.now(row.clinic_id)
        conn.execute(
            s.link_tokens.update()
            .where(
                s.link_tokens.c.clinic_id == row.clinic_id,
                s.link_tokens.c.kind == "patient_telegram",
                s.link_tokens.c.subject_id == row.contact_id,
                s.link_tokens.c.used_at.is_(None),
            )
            .values(expires_at=now)
        )
        token_id, url = mint(
            conn, clock, row.clinic_id, "patient_telegram", row.contact_id, contact_proof=False
        )
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=row.clinic_id,
                key=idempotency_key,
                command="patient_telegram",
                result_json={"token_id": token_id},
                created_at=now,
            )
        )
        record.write_action(
            conn, row.clinic_id, "patient", "patient_telegram_token", verified.booking_id
        )
        return TokenResult(url)
