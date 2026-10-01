import base64
import hashlib
import hmac
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, Clock
from nowa.config import get_settings
from nowa.core import ratelimit
from nowa.core.projection import (
    WAITING_STATES,
    current_pace,
    expected_time,
    load_snapshot,
    paper_hours,
    people_ahead_of_new_booking,
)
from nowa.db import write_tx

RefusalReason = Literal[
    "full", "booking_closed", "closed_day", "already_booked", "phone_cap", "invalid_input"
]


@dataclass(frozen=True)
class ConsentInput:
    version: str
    text_hash: str
    booking_for: Literal["self", "other"]


@dataclass(frozen=True)
class BookingRequest:
    clinic_id: int
    date: date
    patient_name: str
    contact_phone: str = field(repr=False)
    lang: Literal["ar", "en", "franco"]
    area_id: int | None
    consent: ConsentInput
    idempotency_key: str
    actor: Literal["patient", "system"] = "patient"


@dataclass(frozen=True)
class BookingOk:
    booking_id: int
    queue_number: int
    expected_shown: datetime
    link_code: str | None = field(repr=False)
    repeated: bool = False


@dataclass(frozen=True)
class BookingRefused:
    reason: RefusalReason
    nearest_open_day: date | None = None


@dataclass(frozen=True)
class LinkRefused:
    reason: Literal["verify_failed", "locked", "not_cancellable"]


@dataclass(frozen=True)
class VerifyOk:
    booking_id: int


@dataclass(frozen=True)
class CancelResult:
    booking_id: int
    evening_id: int
    repeated: bool = False


@dataclass(frozen=True)
class ChangeDayResult:
    old_booking_id: int
    new_booking_id: int
    new_evening_id: int
    link_code: str | None = field(repr=False)
    repeated: bool = False


@dataclass(frozen=True)
class TonightEvening:
    evening_date: date
    evening_id: int | None


@dataclass(frozen=True)
class BookingView:
    booking_id: int
    clinic_id: int
    lang: Literal["ar", "en", "franco"]
    evening_state: str
    state_reason: Literal["cancel_tonight", "close_untold", "patient", "clinic"] | None
    is_sandbox: bool
    patient_first_name: str
    doctor_name: str
    date: date
    queue_number: int
    expected_shown: datetime | None
    state: str
    clinic_address: str
    clinic_phone: str = field(repr=False)
    clinic_lat: float
    clinic_lng: float


class IdempotencyConflict(Exception):
    pass


def _display_name(raw: str) -> str:
    raw = raw.translate(str.maketrans("أإآٱ", "اااا", "ـ"))
    raw = "".join(
        c
        for c in raw
        if not (unicodedata.category(c).startswith("M") and "ARABIC" in unicodedata.name(c, ""))
    )
    return " ".join(raw.split())


def normalize_name(raw: str) -> str:
    words = _display_name(raw).casefold().replace("ى", "ي").split()
    return " ".join(word[:-1] + "ه" if word.endswith("ة") else word for word in words)


def valid_name(raw: str) -> bool:
    if not isinstance(raw, str):
        return False
    name = _display_name(raw)
    if not 2 <= len(name) <= 60 or any(x in name.casefold() for x in ("http", "www")):
        return False
    return all(
        c in " -'"
        or (
            unicodedata.category(c).startswith("L")
            and any(script in unicodedata.name(c, "") for script in ("ARABIC", "LATIN"))
        )
        for c in name
    ) and any(c.isalpha() for c in name)


def normalize_phone(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    phone = re.sub(r"[\s-]", "", raw)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    elif phone.startswith("01"):
        phone = "+2" + phone
    return phone if re.fullmatch(r"\+201[0125][0-9]{8}", phone) else None


def link_code_for(booking_id: int) -> str:
    digest = hmac.new(
        get_settings().link_secret.encode(), f"link|{booking_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode().rstrip("=")


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _advisory_lock(conn: Connection, key: str) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


def _replay(conn: Connection, key: str, clinic_id: int, command: str) -> dict[str, Any] | None:
    _advisory_lock(conn, "intent|" + key)
    row = (
        conn.execute(select(s.idempotency_keys).where(s.idempotency_keys.c.key == key))
        .mappings()
        .first()
    )
    if row is None:
        return None
    if row["clinic_id"] != clinic_id or row["command"] != command:
        raise IdempotencyConflict("key belongs to another clinic or command")
    return dict(row["result_json"])


def _remember(
    conn: Connection, clock: Clock, clinic_id: int, key: str, command: str, result: dict[str, int]
) -> None:
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=clinic_id,
            key=key,
            command=command,
            result_json=result,
            created_at=clock.now(clinic_id),
        )
    )


def get_or_create_evening(conn: Connection, clinic_id: int, evening_date: date) -> int:
    query = select(s.evenings.c.id).where(
        s.evenings.c.clinic_id == clinic_id, s.evenings.c.date == evening_date
    )
    existing = conn.execute(query).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    try:
        with conn.begin_nested():
            return int(
                conn.execute(
                    s.evenings.insert()
                    .values(clinic_id=clinic_id, date=evening_date)
                    .returning(s.evenings.c.id)
                ).scalar_one()
            )
    except IntegrityError:
        existing = conn.execute(query).scalar_one_or_none()
        if existing is None:
            raise
        return int(existing)


def _lock_evening(conn: Connection, evening_id: int) -> None:
    conn.execute(
        select(s.evenings.c.id).where(s.evenings.c.id == evening_id).with_for_update()
    ).scalar_one()


def _day_status(
    conn: Connection, clinic_id: int, day: date, now: datetime
) -> tuple[RefusalReason | None, datetime | None]:
    hours = paper_hours(conn, clinic_id, day)
    evening = (
        conn.execute(
            select(s.evenings).where(s.evenings.c.clinic_id == clinic_id, s.evenings.c.date == day)
        )
        .mappings()
        .first()
    )
    if (
        day < now.astimezone(CAIRO).date()
        or hours is None
        or (evening is not None and evening["state"] in ("closed", "cancelled"))
    ):
        return "closed_day", None
    if now > hours[1] - timedelta(minutes=60):
        return "booking_closed", None
    evening_id = None if evening is None else evening["id"]
    projected = expected_time(
        load_snapshot(conn, clinic_id, day, now),
        people_ahead_of_new_booking(conn, evening_id),
        current_pace(conn, clinic_id, evening_id),
        now,
    )
    maximum: int | None = conn.execute(
        select(s.clinics.c.max_per_evening).where(s.clinics.c.id == clinic_id)
    ).scalar_one()
    count = conn.execute(
        select(func.count())
        .select_from(s.bookings)
        .where(
            s.bookings.c.evening_id == evening_id,
            s.bookings.c.source == "chat",
            s.bookings.c.state != "cancelled",
        )
    ).scalar_one()
    if projected > hours[1] or (maximum is not None and count >= maximum):
        return "full", projected
    return None, projected


def _open_days(
    conn: Connection, clock: Clock, clinic_id: int, from_date: date, n: int
) -> list[date]:
    now = clock.now(clinic_id)
    days: list[date] = []
    for offset in range(60):
        if len(days) >= n:
            break
        day = from_date + timedelta(days=offset)
        if _day_status(conn, clinic_id, day, now)[0] is None:
            days.append(day)
    return days


def open_days(engine: Engine, clock: Clock, clinic_id: int, from_date: date, n: int) -> list[date]:
    with engine.connect() as conn:
        return _open_days(conn, clock, clinic_id, from_date, n)


def nearest_open_day(engine: Engine, clock: Clock, clinic_id: int, after_date: date) -> date | None:
    with engine.connect() as conn:
        days = _open_days(conn, clock, clinic_id, after_date + timedelta(days=1), 1)
        return days[0] if days else None


def _refused(
    conn: Connection, clock: Clock, req: BookingRequest, reason: RefusalReason
) -> BookingRefused:
    days = (
        _open_days(conn, clock, req.clinic_id, req.date + timedelta(days=1), 1)
        if (reason in ("full", "booking_closed", "closed_day"))
        else []
    )
    return BookingRefused(reason, days[0] if days else None)


def _valid_request(conn: Connection, req: BookingRequest) -> bool:
    return (
        isinstance(req.date, date)
        and not isinstance(req.date, datetime)
        and valid_name(req.patient_name)
        and normalize_phone(req.contact_phone) is not None
        and req.lang in ("ar", "en", "franco")
        and isinstance(req.consent, ConsentInput)
        and req.consent.booking_for in ("self", "other")
        and isinstance(req.consent.version, str)
        and bool(req.consent.version.strip())
        and isinstance(req.consent.text_hash, str)
        and bool(req.consent.text_hash.strip())
        and req.actor in ("patient", "system")
        and isinstance(req.idempotency_key, str)
        and bool(req.idempotency_key)
        and (
            req.area_id is None
            or (
                type(req.area_id) is int
                and conn.execute(select(s.areas.c.id).where(s.areas.c.id == req.area_id)).first()
                is not None
            )
        )
    )


def _book(
    conn: Connection,
    clock: Clock,
    req: BookingRequest,
    exempt_phone_cap: bool = False,
    remember: bool = True,
) -> BookingOk | BookingRefused:
    if remember:
        replay = _replay(conn, req.idempotency_key, req.clinic_id, "book")
        if replay is not None:
            return BookingOk(
                replay["booking_id"],
                replay["queue_number"],
                datetime.fromtimestamp(replay["expected_epoch"], UTC),
                None,
                True,
            )
    if not _valid_request(conn, req):
        return BookingRefused("invalid_input")
    now = clock.now(req.clinic_id)
    reason, _ = _day_status(conn, req.clinic_id, req.date, now)
    if reason in ("closed_day", "booking_closed"):
        return _refused(conn, clock, req, reason)
    evening_id = get_or_create_evening(conn, req.clinic_id, req.date)
    _lock_evening(conn, evening_id)
    reason, projected = _day_status(conn, req.clinic_id, req.date, now)
    if reason in ("closed_day", "booking_closed"):
        return _refused(conn, clock, req, reason)
    phone = normalize_phone(req.contact_phone)
    assert phone is not None
    _advisory_lock(conn, f"{req.clinic_id}|{phone}")
    contact_query = select(s.contacts.c.id).where(
        s.contacts.c.clinic_id == req.clinic_id, s.contacts.c.phone_e164 == phone
    )
    contact_id: int | None = conn.execute(contact_query).scalar_one_or_none()
    histories: Sequence[RowMapping] = (
        conn.execute(
            select(s.patients.c.id, s.patients.c.name, s.bookings.c.evening_id, s.bookings.c.state)
            .select_from(s.bookings.join(s.patients, s.bookings.c.patient_id == s.patients.c.id))
            .where(s.bookings.c.clinic_id == req.clinic_id, s.bookings.c.contact_id == contact_id)
        )
        .mappings()
        .all()
        if contact_id is not None
        else []
    )
    matching = [
        row for row in histories if normalize_name(row["name"]) == normalize_name(req.patient_name)
    ]
    if any(row["evening_id"] == evening_id and row["state"] != "cancelled" for row in matching):
        return BookingRefused("already_booked")
    active = (
        conn.execute(
            select(func.count())
            .select_from(s.bookings.join(s.evenings, s.bookings.c.evening_id == s.evenings.c.id))
            .where(
                s.bookings.c.clinic_id == req.clinic_id,
                s.bookings.c.contact_id == contact_id,
                s.bookings.c.state != "cancelled",
                s.evenings.c.date >= now.astimezone(CAIRO).date(),
            )
        ).scalar_one()
        if contact_id is not None
        else 0
    )
    if not exempt_phone_cap and active >= 3:
        return BookingRefused("phone_cap")
    if reason == "full":
        return _refused(conn, clock, req, reason)
    assert projected is not None
    if contact_id is None:
        try:
            with conn.begin_nested():
                contact_id = conn.execute(
                    s.contacts.insert()
                    .values(clinic_id=req.clinic_id, phone_e164=phone)
                    .returning(s.contacts.c.id)
                ).scalar_one()
        except IntegrityError:
            contact_id = conn.execute(contact_query).scalar_one_or_none()
            if contact_id is None:
                raise
    patient_id = (
        matching[0]["id"]
        if matching
        else conn.execute(
            s.patients.insert()
            .values(clinic_id=req.clinic_id, name=_display_name(req.patient_name))
            .returning(s.patients.c.id)
        ).scalar_one()
    )
    number, order = conn.execute(
        select(func.max(s.bookings.c.queue_number), func.max(s.bookings.c.order_key)).where(
            s.bookings.c.evening_id == evening_id
        )
    ).one()
    queue_number = (number or 0) + 1
    booking_id = int(
        conn.execute(
            s.bookings.insert()
            .values(
                clinic_id=req.clinic_id,
                evening_id=evening_id,
                patient_id=patient_id,
                contact_id=contact_id,
                queue_number=queue_number,
                order_key=(order or 0) + 1,
                source="chat",
                state="booked",
                lang=req.lang,
                area_id=req.area_id,
                expected_shown=projected,
                expected_frozen=False,
                created_at=now,
            )
            .returning(s.bookings.c.id)
        ).scalar_one()
    )
    code = link_code_for(booking_id)
    conn.execute(
        s.bookings.update()
        .where(s.bookings.c.id == booking_id)
        .values(link_code_hash=_code_hash(code))
    )
    conn.execute(
        s.consents.insert().values(
            clinic_id=req.clinic_id,
            contact_id=contact_id,
            booking_id=booking_id,
            booking_for=req.consent.booking_for,
            version=req.consent.version,
            text_hash=req.consent.text_hash,
            at=now,
        )
    )
    if remember:
        _remember(
            conn,
            clock,
            req.clinic_id,
            req.idempotency_key,
            "book",
            {
                "booking_id": booking_id,
                "queue_number": queue_number,
                "expected_epoch": int(projected.timestamp()),
            },
        )
    record.write_action(conn, req.clinic_id, req.actor, "booking_created", booking_id, patient_id)
    return BookingOk(booking_id, queue_number, projected, code)


def book_in_tx(conn: Connection, clock: Clock, req: BookingRequest) -> BookingOk | BookingRefused:
    return _book(conn, clock, req)


def book(engine: Engine, clock: Clock, req: BookingRequest) -> BookingOk | BookingRefused:
    with write_tx(engine) as conn:
        return book_in_tx(conn, clock, req)


def _lookup(conn: Connection, code: str) -> RowMapping | None:
    return (
        conn.execute(select(s.bookings).where(s.bookings.c.link_code_hash == _code_hash(code)))
        .mappings()
        .first()
    )


def _verify(conn: Connection, clock: Clock, code: str, last4: str) -> RowMapping | LinkRefused:
    _advisory_lock(conn, "verify|" + code)
    row = _lookup(conn, code)
    phone = conn.execute(
        select(s.contacts.c.phone_e164).where(
            s.contacts.c.id == (None if row is None else row["contact_id"])
        )
    ).scalar_one_or_none()
    correct = hmac.compare_digest(str(last4), "----" if phone is None else phone[-4:])
    # A successful verification probes the same limiter, but consumes no failure.
    with conn.begin_nested() as probe:
        allowed = ratelimit.hit(conn, clock, "link_verify", code, 900, 5)
        if correct and row is not None:
            probe.rollback()
    if not correct or row is None:
        if row is not None:
            record.write_action(conn, row["clinic_id"], "patient", "link_verify_failed", row["id"])
        return LinkRefused("verify_failed" if allowed else "locked")
    if not allowed:
        return LinkRefused("locked")
    return row


def verify_link(conn: Connection, clock: Clock, code: str, last4: str) -> VerifyOk | LinkRefused:
    result = _verify(conn, clock, code, last4)
    return result if isinstance(result, LinkRefused) else VerifyOk(result["id"])


def _cancel_row(conn: Connection, row: RowMapping) -> CancelResult | LinkRefused:
    _lock_evening(conn, row["evening_id"])
    row = (
        conn.execute(select(s.bookings).where(s.bookings.c.id == row["id"]).with_for_update())
        .mappings()
        .one()
    )
    if row["state"] not in WAITING_STATES:
        return LinkRefused("not_cancellable")
    conn.execute(s.bookings.update().where(s.bookings.c.id == row["id"]).values(state="cancelled"))
    record.write_action(conn, row["clinic_id"], "patient", "booking_cancelled", row["id"])
    return CancelResult(row["id"], row["evening_id"])


def cancel_in_tx(
    conn: Connection, clock: Clock, link_code: str, last4: str, idempotency_key: str
) -> CancelResult | LinkRefused:
    # Acquire the intent lock first, consistently with book/change_day.
    _advisory_lock(conn, "intent|" + idempotency_key)
    row = _lookup(conn, link_code)
    if row is not None:
        replay = _replay(conn, idempotency_key, row["clinic_id"], "cancel")
        if replay is not None:
            return CancelResult(replay["booking_id"], replay["evening_id"], True)
    verified = _verify(conn, clock, link_code, last4)
    if isinstance(verified, LinkRefused):
        return verified
    result = _cancel_row(conn, verified)
    if isinstance(result, CancelResult):
        _remember(
            conn,
            clock,
            verified["clinic_id"],
            idempotency_key,
            "cancel",
            {"booking_id": result.booking_id, "evening_id": result.evening_id},
        )
    return result


def cancel(
    engine: Engine, clock: Clock, link_code: str, last4: str, idempotency_key: str
) -> CancelResult | LinkRefused:
    with write_tx(engine) as conn:
        return cancel_in_tx(conn, clock, link_code, last4, idempotency_key)


def change_day_in_tx(
    conn: Connection, clock: Clock, link_code: str, last4: str, new_date: date, idempotency_key: str
) -> ChangeDayResult | BookingRefused | LinkRefused:
    _advisory_lock(conn, "intent|" + idempotency_key)
    row = _lookup(conn, link_code)
    if row is not None:
        replay = _replay(conn, idempotency_key, row["clinic_id"], "change_day")
        if replay is not None:
            return ChangeDayResult(
                replay["old_booking_id"],
                replay["new_booking_id"],
                replay["new_evening_id"],
                None,
                True,
            )
    verified = _verify(conn, clock, link_code, last4)
    if isinstance(verified, LinkRefused):
        return verified
    with conn.begin_nested() as change:
        # Two-day moves take evening locks in ID order, including opposite moves.
        if isinstance(new_date, date) and not isinstance(new_date, datetime):
            target = get_or_create_evening(conn, verified["clinic_id"], new_date)
            for evening_id in sorted({verified["evening_id"], target}):
                _lock_evening(conn, evening_id)
        cancelled = _cancel_row(conn, verified)
        if isinstance(cancelled, LinkRefused):
            change.rollback()
            return cancelled
        identity = conn.execute(
            select(s.patients.c.name, s.contacts.c.phone_e164)
            .select_from(s.patients.join(s.contacts, s.contacts.c.id == verified["contact_id"]))
            .where(s.patients.c.id == verified["patient_id"])
        ).one()
        consent = (
            conn.execute(select(s.consents).where(s.consents.c.booking_id == verified["id"]))
            .mappings()
            .one()
        )
        req = BookingRequest(
            verified["clinic_id"],
            new_date,
            identity.name,
            identity.phone_e164,
            verified["lang"],
            verified["area_id"],
            ConsentInput(consent["version"], consent["text_hash"], consent["booking_for"]),
            idempotency_key,
        )
        booked = _book(conn, clock, req, exempt_phone_cap=True, remember=False)
        if isinstance(booked, BookingRefused):
            change.rollback()
            return booked
        evening: int = conn.execute(
            select(s.bookings.c.evening_id).where(s.bookings.c.id == booked.booking_id)
        ).scalar_one()
        result = ChangeDayResult(verified["id"], booked.booking_id, evening, booked.link_code)
        _remember(
            conn,
            clock,
            verified["clinic_id"],
            idempotency_key,
            "change_day",
            {
                "old_booking_id": result.old_booking_id,
                "new_booking_id": result.new_booking_id,
                "new_evening_id": result.new_evening_id,
            },
        )
        return result


def change_day(
    engine: Engine, clock: Clock, link_code: str, last4: str, new_date: date, idempotency_key: str
) -> ChangeDayResult | BookingRefused | LinkRefused:
    with write_tx(engine) as conn:
        return change_day_in_tx(conn, clock, link_code, last4, new_date, idempotency_key)


def booking_view(engine: Engine, link_code: str) -> BookingView | None:
    with engine.connect() as conn:
        row = _lookup(conn, link_code)
        if row is None:
            return None
        patient = conn.execute(
            select(s.patients.c.name).where(s.patients.c.id == row["patient_id"])
        ).scalar_one_or_none()
        clinic = (
            conn.execute(select(s.clinics).where(s.clinics.c.id == row["clinic_id"]))
            .mappings()
            .one()
        )
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == row["clinic_id"]))
            .mappings()
            .one()
        )
        evening = conn.execute(
            select(s.evenings.c.date, s.evenings.c.state).where(
                s.evenings.c.id == row["evening_id"]
            )
        ).one()
        reason: Literal["cancel_tonight", "close_untold", "patient", "clinic"] | None = None
        if row["state"] == "cancelled":
            action = conn.execute(
                select(s.action_record.c.kind, s.action_record.c.actor)
                .where(
                    s.action_record.c.booking_id == row["id"],
                    s.action_record.c.kind.in_(
                        ("booking_cancelled", "cancel_tonight", "close_untold")
                    ),
                )
                .order_by(s.action_record.c.id.desc())
                .limit(1)
            ).first()
            if action is not None:
                if action.kind == "cancel_tonight":
                    reason = "cancel_tonight"
                elif action.kind == "close_untold":
                    reason = "close_untold"
                else:
                    reason = "patient" if action.actor == "patient" else "clinic"
        return BookingView(
            row["id"],
            row["clinic_id"],
            row["lang"],
            evening.state,
            reason,
            clinic["is_sandbox"],
            "" if patient is None else patient.split()[0],
            doctor["name_ar" if row["lang"] == "ar" else "name_en"],
            evening.date,
            row["queue_number"],
            row["expected_shown"],
            row["state"],
            clinic["address"],
            clinic["phone"],
            clinic["lat"],
            clinic["lng"],
        )


def tonight_evening(conn: Connection, clinic_id: int, now: datetime) -> TonightEvening | None:
    today = now.astimezone(CAIRO).date()
    for day in (today - timedelta(days=1), today):
        hours = paper_hours(conn, clinic_id, day)
        if hours is None:
            continue
        start, end = hours
        if start - timedelta(hours=6) <= now <= end + timedelta(hours=2) or (
            day == today and now < start
        ):
            evening_id = conn.execute(
                select(s.evenings.c.id).where(
                    s.evenings.c.clinic_id == clinic_id, s.evenings.c.date == day
                )
            ).scalar_one_or_none()
            return TonightEvening(day, evening_id)
    return None
