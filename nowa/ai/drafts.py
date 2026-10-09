"""Merge extracted candidates into a validated session draft."""

import re
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.ai.cards import mark_progress, save_draft, stored_draft, validated_fields
from nowa.ai.schema import TurnFields
from nowa.clock import Clock
from nowa.core import areas, booking
from nowa.core.text_norm import origin_text
from nowa.reference import AREAS

WEEKDAYS = (
    ("الاثنين", "الاتنين", "monday", "el etnein"),
    ("الثلاثاء", "التلات", "tuesday", "el talat"),
    ("الاربعاء", "الاربع", "wednesday", "el arba3"),
    ("الخميس", "thursday", "el khamees"),
    ("الجمعة", "friday", "el gom3a"),
    ("السبت", "saturday", "el sabt"),
    ("الاحد", "الحد", "sunday", "el 7ad"),
)


def mentioned(key: str, value: str, text: str, today: date) -> bool:
    normalized = areas.normalize(text)
    if key == "phone":

        def digits(value: str) -> str:
            return "".join(c for c in areas.normalize(value) if c.isdecimal())

        phone = booking.normalize_phone(value)
        return digits(value) in digits(text) or bool(phone and phone[3:] in digits(text))
    if key == "day":
        day = date.fromisoformat(value)
        words = [value, f"{day.day}/{day.month}", *WEEKDAYS[day.weekday()]]
        relative = {
            0: ("today", "النهارده", "el naharda"),
            1: ("tomorrow", "بكرة", "bokra"),
            2: ("day after tomorrow", "بعد بكرة", "ba3d bokra"),
        }
        words.extend(relative.get((day - today).days, ()))
        return any(areas.normalize(word) in normalized for word in words)
    if key == "booking_for":
        role_words = (
            ("ليا", "لنفسي", "انا", "for me", "myself", "leya", "nafsy")
            if value == "self"
            else (
                "لحد تاني",
                "لوالدتي",
                "لوالدي",
                "لبابا",
                "لماما",
                "other",
                "mother",
                "father",
                "le mama",
                "le baba",
            )
        )
        return any(areas.normalize(word) in normalized for word in role_words)
    return areas.normalize(value) in normalized


def validate(conn: Connection, clock: Clock, clinic_id: int, draft: dict[str, Any]) -> None:
    valid = set(draft.get("validated", []))
    for key, ok in (
        ("booking_for", draft.get("booking_for") in ("self", "other")),
        ("name", booking.valid_name(draft.get("name", ""))),
        ("phone", booking.normalize_phone(draft.get("phone", "")) is not None),
    ):
        valid.discard(key)
        if ok:
            valid.add(key)
    if "name" in valid:
        draft["name"] = booking.display_name(draft["name"])
    if "phone" in valid:
        draft["phone"] = booking.normalize_phone(draft["phone"])
    valid.discard("day")
    if draft.get("day"):
        day = date.fromisoformat(draft["day"])
        now = clock.now(clinic_id)
        if now.date() <= day < now.date() + timedelta(days=60) and booking._day_status(
            conn, clinic_id, day, now
        )[0] in (None, "full"):
            valid.add("day")
    if "area_text" in draft:
        draft["origin_text"] = origin_text(draft.get("area_text"), draft.get("area_id"))
    else:
        draft.pop("origin_text", None)
    draft["validated"] = sorted(valid)


def area_candidate(
    session: dict[str, Any], fields: TurnFields, text: str, today: date
) -> tuple[str, int | None | Literal["unknown"]] | None:
    """The same deterministic gates before HTTP and after the session is reloaded."""
    draft = stored_draft(session)
    valid = set(draft.get("validated", []))
    raw_match = areas.resolve(text)
    area_text = fields.area
    fresh = session["draft"] is None and session["last_safe_turn_seq"] > 0
    if fresh and area_text is not None and not mentioned("area_text", area_text, text, today):
        area_text = None
    awaiting_area = {"booking_for", "name", "phone", "day"}.issubset(valid) and (
        "area_text" not in valid
    )
    if isinstance(raw_match, int) or areas.ambiguous(text):
        area_text = text
    elif awaiting_area and area_text is None and not any((fields.name, fields.phone, fields.day)):
        area_text = text
    if area_text is None or (
        "area_text" in valid and not mentioned("area_text", area_text, text, today)
    ):
        return None
    resolved = raw_match if isinstance(raw_match, int) else areas.resolve(area_text)
    if raw_match == "unknown" or re.search(r"[?؟]", area_text) or resolved == "unknown":
        resolved = "unknown"
    return area_text, resolved


def merge(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    session: dict[str, Any],
    fields: TurnFields,
    text: str,
    *,
    geocoded: tuple[str, int] | None = None,
) -> tuple[dict[str, Any], bool]:
    draft = stored_draft(session)
    before = validated_fields(draft)
    fresh = session["draft"] is None and session["last_safe_turn_seq"] > 0
    valid = set(draft.get("validated", []))
    for key in ("name", "phone", "day", "booking_for"):
        value = getattr(fields, key)
        if value is None or value == "unknown":
            continue
        value = value.isoformat() if isinstance(value, date) else value
        if fresh and not mentioned(key, value, text, clock.now(clinic_id).date()):
            continue
        if key in draft.get("rejected", []) and not mentioned(
            key, value, text, clock.now(clinic_id).date()
        ):
            continue
        if (
            key in valid
            and draft.get(key) != value
            and not mentioned(key, value, text, clock.now(clinic_id).date())
        ):
            continue
        draft[key] = value
    if (
        draft.get("step") == "day"
        and draft.get("fruitless", 0) == 0
        and not any((fields.name, fields.phone, fields.day, fields.area))
        and areas.resolve(text) is None
    ):
        draft["day_unrecognized_seq"] = session["turn_seq"]
    outside = False
    origin = area_candidate(session, fields, text, clock.now(clinic_id).date())
    if origin is not None:
        area_text, resolved = origin
        if resolved == "unknown":
            draft["area_attempts"] = draft.get("area_attempts", 0) + 1
            if areas.ambiguous(text) or areas.ambiguous(area_text):
                draft["area_hint_seq"] = session["turn_seq"]
        draft["area_text"] = area_text
        valid.discard("area_text")
        draft.pop("area_id", None)
        if resolved != "unknown":
            draft["area_id"] = (
                conn.execute(
                    select(s.areas.c.id).where(s.areas.c.name_en == AREAS[resolved - 1][0])
                ).scalar_one()
                if isinstance(resolved, int)
                else None
            )
            if resolved is None and geocoded is not None and geocoded[0] == area_text:
                draft["area_id"] = conn.execute(
                    select(s.areas.c.id).where(s.areas.c.id == geocoded[1])
                ).scalar_one_or_none()
            valid.add("area_text")
            outside = draft["area_id"] is None
    draft["validated"] = sorted(valid)
    validate(conn, clock, clinic_id, draft)
    mark_progress(draft, before, session["turn_seq"])
    save_draft(conn, session, draft)
    return draft, outside
