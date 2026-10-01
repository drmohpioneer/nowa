import hashlib
import hmac
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.ai.schema import Action, Button, ChatResponse, StrictModel, TurnFields
from nowa.ai.sessions import keyed
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core import booking
from nowa.messaging.templates import format_day, render_emergency
from nowa.web.strings import STRINGS


class Draft(StrictModel):
    name: str = Field(max_length=60)
    phone: str = Field(max_length=20)
    booking_for: Literal["self", "other"]
    turn_seq: int = Field(ge=1)
    exp: int
    sig: str = Field(max_length=64)


class BookPayload(StrictModel):
    date: date
    area_id: int | None
    consent_version: str
    text_hash: str
    draft: Draft


def ui(key: str, lang: str, **values: Any) -> str:
    return STRINGS["chat." + key][lang].format(**values)


def response(
    session: dict[str, Any], reply: str, buttons: list[Button] | None = None
) -> ChatResponse:
    return ChatResponse(
        reply=reply, buttons=buttons or [], state=session["state"], lang=session["lang"]
    )


def emergency(session: dict[str, Any]) -> ChatResponse:
    return response(session, render_emergency(session["emergency_kind"], session["lang"]))


def button(id: str, label: str, kind: Any, **payload: Any) -> Button:
    return Button(id=id, label=label, action=Action(kind=kind, payload=payload))


def faq(conn: Connection, clinic_id: int) -> list[Button]:
    return [
        button("faq:" + row.key, row.key, "none", faq=row.key)
        for row in conn.execute(
            select(s.clinic_info.c.key)
            .where(s.clinic_info.c.clinic_id == clinic_id)
            .order_by(s.clinic_info.c.key)
        )
    ]


def form(lang: str) -> list[Button]:
    return [button("lookup", ui("lookup", lang), "lookup")]


def consent_text(booking_for: str, lang: str, slug: str) -> tuple[str, str, str]:
    path = Path(__file__).resolve().parents[2] / "docs/reference/patient-consent.md"
    source = path.read_text()
    version_match = re.search(r"^Version: ([\d.]+)", source, re.M)
    assert version_match is not None
    section = source.split("## Self" if booking_for == "self" else "## Booking for someone else")[1]
    prefix = {"ar": "AR", "en": "EN", "franco": "Franco"}[lang]
    match = re.search(rf"^{prefix}: (.+)$", section.split("\n## ")[0], re.M)
    assert match is not None
    text = match[1].format(privacy_link=get_settings().public_base_url + f"/c/{slug}/privacy")
    return version_match[1], hashlib.sha256(text.encode()).hexdigest(), text


def signature(session_key: str, draft: Draft) -> str:
    return keyed(
        f"draft|{session_key}|{draft.name}|{draft.phone}|{draft.booking_for}|"
        f"{draft.turn_seq}|{draft.exp}"
    )


def valid_draft(session_key: str, draft: Draft, session: dict[str, Any], clock: Clock) -> bool:
    return (
        hmac.compare_digest(signature(session_key, draft), draft.sig)
        and draft.exp > clock.now(session["clinic_id"]).timestamp()
        and session["last_safe_turn_seq"] < draft.turn_seq <= session["turn_seq"]
    )


def day_button(
    day: date,
    draft: Draft,
    version: str,
    text_hash: str,
    lang: str,
    area_id: int | None = None,
) -> Button:
    return button(
        "book:" + day.isoformat(),
        format_day(day, lang),
        "book_day",
        date=day.isoformat(),
        area_id=area_id,
        consent_version=version,
        text_hash=text_hash,
        draft=draft.model_dump(),
    )


def booking_card(
    conn: Connection,
    clock: Clock,
    clinic: dict[str, Any],
    session: dict[str, Any],
    session_key: str,
    fields: TurnFields,
    turn_seq: int,
) -> tuple[ChatResponse, str]:
    lang = session["lang"]
    for missing, key in (
        (fields.booking_for == "unknown", "booking_for_ask"),
        (not fields.name or not booking.valid_name(fields.name), "name_ask"),
        (not fields.phone or not booking.normalize_phone(fields.phone), "phone_ask"),
    ):
        if missing:
            return response(session, ui(key, lang)), "reply"
    assert fields.name and fields.phone and fields.booking_for != "unknown"
    draft = Draft(
        name=booking.normalize_name(fields.name),
        phone=booking.normalize_phone(fields.phone) or "",
        booking_for=fields.booking_for,
        turn_seq=turn_seq,
        exp=int((clock.now(clinic["id"]) + timedelta(minutes=30)).timestamp()),
        sig="",
    )
    draft.sig = signature(session_key, draft)
    days = booking._open_days(conn, clock, clinic["id"], clock.now(clinic["id"]).date(), 7)
    if fields.day in days:
        days = [fields.day] + [d for d in days if d != fields.day]
    if not days:
        return response(session, ui("no_days", lang)), "reply"
    version, text_hash, text = consent_text(draft.booking_for, lang, clinic["slug"])
    buttons = [day_button(day, draft, version, text_hash, lang) for day in days]
    if draft.booking_for == "other":
        buttons.insert(0, button("consent", ui("consent", lang), "consent", booking_for="other"))
    for area in conn.execute(select(s.areas).order_by(s.areas.c.id)).mappings():
        buttons.append(
            button(
                f"area:{area['id']}",
                area["name_ar" if lang == "ar" else "name_en"],
                "area",
                area_id=area["id"],
            )
        )
    buttons.append(button("area:none", ui("area_other", lang), "area", area_id=None))
    if draft.booking_for == "self":
        buttons.append(button("location", ui("location", lang), "area", current_location=True))
    return response(session, ui("card", lang) + "\n" + text, buttons), "card"
