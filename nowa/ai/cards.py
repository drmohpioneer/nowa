import hmac
import json
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.ai.schema import Action, Button, ChatResponse, StrictModel
from nowa.ai.sessions import keyed, session_hash, update_session
from nowa.clock import Clock
from nowa.core import areas, booking
from nowa.core.display import patient_display_name
from nowa.core.projection import paper_hours
from nowa.core.text_norm import mask_phones, origin_text, western_digits
from nowa.messaging.templates import format_day, render_emergency
from nowa.web.strings import STRINGS, doctor_label


class Draft(StrictModel):
    name: str = Field(max_length=60)
    phone: str = Field(max_length=20)
    booking_for: Literal["self", "other"]
    day: date
    area_id: int | None
    origin_text: str | None = Field(default=None, max_length=40)
    standby: bool = False
    turn_seq: int = Field(ge=1)
    exp: int
    sig: str = Field(max_length=64)


class BookPayload(StrictModel):
    draft: Draft


def ui(key: str, lang: str, **values: Any) -> str:
    return western_digits(STRINGS["chat." + key][lang].format(**values))


def response(
    session: dict[str, Any], reply: str, buttons: list[Button] | None = None
) -> ChatResponse:
    return ChatResponse(
        reply=western_digits(reply),
        buttons=buttons or [],
        state=session["state"],
        lang=session["lang"],
    )


def emergency(session: dict[str, Any]) -> ChatResponse:
    return response(session, render_emergency(session["emergency_kind"], session["lang"]))


def button(id: str, label: str, kind: Any, **payload: Any) -> Button:
    return Button(id=id, label=label, action=Action(kind=kind, payload=payload))


def faq(conn: Connection, clinic_id: int) -> list[Button]:
    return [
        button("faq:" + row.key, ui("faq_" + row.key, "ar"), "none", faq=row.key)
        for row in conn.execute(
            select(s.clinic_info.c.key)
            .where(s.clinic_info.c.clinic_id == clinic_id, s.clinic_info.c.key != "address")
            .order_by(s.clinic_info.c.key)
        )
    ] + [
        button("faq:address", ui("faq_address", "ar"), "none", faq="address"),
        button("faq:hours", ui("faq_hours", "ar"), "none", faq="hours"),
    ]


def form(lang: str) -> list[Button]:
    return [button("lookup", ui("booking_chip", lang), "lookup")]


def _signature(key_hash: str, draft: Draft) -> str:
    body = draft.model_dump(mode="json", exclude={"sig"})
    return keyed("draft|" + key_hash + "|" + json.dumps(body, sort_keys=True))


def signature(session_key: str, draft: Draft) -> str:
    return _signature(session_hash(session_key), draft)


def valid_draft(session_key: str, draft: Draft, session: dict[str, Any], clock: Clock) -> bool:
    return (
        hmac.compare_digest(signature(session_key, draft), draft.sig)
        and draft.exp > clock.now(session["clinic_id"]).timestamp()
        and session["last_safe_turn_seq"] < draft.turn_seq == session["turn_seq"]
        and session["draft"] is not None
    )


def stored_draft(session: dict[str, Any]) -> dict[str, Any]:
    return json.loads(session["draft"]) if session["draft"] else {"validated": []}


def save_draft(conn: Connection, session: dict[str, Any], draft: dict[str, Any]) -> None:
    update_session(conn, session, draft=json.dumps(draft, ensure_ascii=False))


def validated_fields(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        key: draft.get(key)
        for key in ("booking_for", "name", "phone", "day", "area_text", "area_id")
        if key in draft.get("validated", [])
        or (key == "area_id" and "area_text" in draft.get("validated", []))
    }


def mark_progress(draft: dict[str, Any], before: dict[str, Any], turn_seq: int) -> None:
    if any(
        key not in before or before[key] != value for key, value in validated_fields(draft).items()
    ):
        # Keep only the turn number, never another stored copy of names or phones.
        draft["progress_seq"] = turn_seq


def day_buttons(
    conn: Connection, clock: Clock, clinic_id: int, lang: str, *, more: bool = False
) -> list[Button]:
    days = booking._open_days(conn, clock, clinic_id, clock.now(clinic_id).date(), 7)
    chosen = days if more else days[:3]
    buttons = [
        button("day:" + day.isoformat(), format_day(day, lang), "book", date=day.isoformat())
        for day in chosen
    ]
    if not more and len(days) > 3:
        buttons.append(button("more_days", ui("more_days", lang), "more_days"))
    return buttons


def next_step(
    conn: Connection,
    clock: Clock,
    clinic: dict[str, Any],
    session: dict[str, Any],
    draft: dict[str, Any],
) -> ChatResponse:
    "Render once per turn, discard rejected slots, and track progress without identity copies."
    step = next(
        (
            key
            for key in ("booking_for", "name", "phone", "day", "area_text")
            if key not in draft.get("validated", [])
        ),
        "confirm",
    )
    shown = _next_step(conn, clock, clinic, session, draft)
    rejected = [
        key
        for key in ("name", "phone", "day")
        if draft.get(key) and key not in draft.get("validated", [])
    ]
    explaining = (
        bool(rejected)
        or draft.get("day_unrecognized_seq") == session["turn_seq"]
        or (
            draft.get("area_hint_seq") == session["turn_seq"] and draft.get("area_attempts", 0) == 1
        )
    )
    if draft.get("step_seq") != session["turn_seq"]:
        if draft.get("progress_seq") == session["turn_seq"] or step == "confirm":
            draft["fruitless"] = 0
        elif draft.get("step"):
            draft["fruitless"] = (
                draft.get("fruitless", 0) + 1
                if draft.get("step_seq") == session["turn_seq"] - 1
                else 1
            )
        else:
            draft["fruitless"] = int(explaining)
        draft.update(step=step, step_seq=session["turn_seq"])
        for key in rejected:
            draft.pop(key)
        # Mark only field names, never retain a second copy of the rejected value.
        draft["rejected"] = sorted(set(draft.get("rejected", [])) | set(rejected))
        save_draft(conn, session, draft)
    if draft.get("fruitless", 0) >= 2 and not explaining:
        shown.reply += "\n" + ui("way_out", session["lang"])
    return shown


def _next_step(
    conn: Connection,
    clock: Clock,
    clinic: dict[str, Any],
    session: dict[str, Any],
    draft: dict[str, Any],
) -> ChatResponse:
    lang = session["lang"]
    if draft.get("area_hint_seq") == session["turn_seq"] and draft.get("area_attempts", 0) == 1:
        return response(session, ui("area_hint", lang))
    if draft.get("booking_for") not in ("self", "other"):
        return response(
            session,
            ui("booking_for_ask", lang),
            [
                button("for:self", ui("for_self", lang), "set_for", booking_for="self"),
                button("for:other", ui("for_other", lang), "set_for", booking_for="other"),
            ],
        )
    if not booking.valid_name(draft.get("name", "")):
        return response(
            session,
            ui(
                "name_invalid"
                if draft.get("name")
                else "name_ask"
                if draft["booking_for"] == "self"
                else "name_other_ask",
                lang,
            ),
        )
    if not booking.normalize_phone(draft.get("phone", "")):
        raw = draft.get("phone", "")
        count = booking.phone_problem(raw)
        return response(session, ui("phone_invalid" if raw else "phone_ask", lang, count=count))
    if "day" not in draft.get("validated", []):
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == clinic["id"]))
            .mappings()
            .one()
        )
        line = ui(
            "day_ask",
            lang,
            doctor=doctor_label(doctor["name_ar" if lang == "ar" else "name_en"], lang),
        )
        if draft.get("day"):
            day = date.fromisoformat(draft["day"])
            closed = paper_hours(conn, clinic["id"], day) is None
            line = ui(
                "day_closed" if closed else "day_unavailable", lang, day=format_day(day, lang)
            )
        elif draft.get("day_unrecognized_seq") == session["turn_seq"]:
            line = ui("day_unavailable", lang)
        buttons = day_buttons(conn, clock, clinic["id"], lang)
        return response(session, line if buttons else ui("no_days", lang), buttons)
    if (
        not draft.get("standby")
        and booking._day_status(
            conn,
            clinic["id"],
            date.fromisoformat(draft["day"]),
            clock.now(clinic["id"]),
        )[0]
        == "full"
    ):
        return full_day(conn, clock, session, date.fromisoformat(draft["day"]))
    if "area_text" not in draft.get("validated", []):
        line = ui("area_ask", lang)
        if draft.get("area_text"):
            if areas.ambiguous(draft["area_text"]) and draft.get("area_attempts", 0) <= 1:
                line = ui("area_hint", lang)
            else:
                names: list[str] = list(
                    conn.execute(
                        select(s.areas.c.name_ar if lang == "ar" else s.areas.c.name_en)
                        .where(s.areas.c.id <= 12)
                        .order_by(s.areas.c.id)
                    ).scalars()
                )
                line = ui("area_list", lang, areas="، ".join(names))
        buttons = (
            [button("location", ui("location", lang), "set_area", current_location=True)]
            if draft["booking_for"] == "self"
            else []
        )
        return response(session, line, buttons)
    signed = Draft(
        name=patient_display_name({"name": booking.display_name(draft["name"])}, session["lang"]),
        phone=draft["phone"],
        booking_for=draft["booking_for"],
        day=draft["day"],
        area_id=draft.get("area_id"),
        origin_text=origin_text(draft.get("area_text"), draft.get("area_id")),
        standby=bool(draft.get("standby")),
        turn_seq=session["turn_seq"],
        exp=int((clock.now(clinic["id"]) + timedelta(minutes=30)).timestamp()),
        sig="",
    )
    signed.sig = _signature(session["session_key_hash"], signed)
    area = conn.execute(
        select(s.areas.c.name_ar if lang == "ar" else s.areas.c.name_en).where(
            s.areas.c.id == signed.area_id
        )
    ).scalar_one_or_none()
    line = ui(
        "confirm_summary",
        lang,
        name=signed.name,
        phone=booking.local_phone(signed.phone),
        day=format_day(signed.day, lang),
        area=area
        or (
            ui(
                "outside_summary",
                lang,
                place=signed.origin_text or "",
            )
            if draft["area_text"].strip()
            else ui("outside_cairo", lang)
        ),
    )
    return response(
        session,
        line,
        [
            button(
                "confirm",
                ui(
                    "confirm_other"
                    if signed.booking_for == "other"
                    else "standby_confirm"
                    if signed.standby
                    else "confirm",
                    lang,
                ),
                "confirm",
                draft=signed.model_dump(mode="json"),
            ),
            button("edit", ui("edit", lang), "none", edit="pick"),
        ],
    )


def outside_ack(draft: dict[str, Any], lang: str) -> str:
    return ui("area_outside", lang, place=mask_phones(draft["area_text"])[:40])


def full_day(conn: Connection, clock: Clock, session: dict[str, Any], day: date) -> ChatResponse:
    days = booking._open_days(conn, clock, session["clinic_id"], day + timedelta(days=1), 1)
    buttons = [
        button("day:" + d.isoformat(), format_day(d, session["lang"]), "book", date=d.isoformat())
        for d in days
    ]
    buttons.append(
        button("standby", ui("standby_join", session["lang"]), "none", standby=day.isoformat())
    )
    return response(session, ui("standby_full", session["lang"]), buttons)


def refused_reply(
    conn: Connection, clock: Clock, session: dict[str, Any], reason: str
) -> ChatResponse:
    """Say why a booking was refused, then offer the usual next steps. Mapping only."""
    lang = session["lang"]
    key = "refused_" + reason
    if key not in {
        "refused_already_booked",
        "refused_closed_day",
        "refused_booking_closed",
        "refused_invalid_input",
    }:
        return response(session, ui("refused", lang))
    buttons = form(lang) if reason == "already_booked" else []
    buttons += day_buttons(conn, clock, session["clinic_id"], lang)
    return response(session, ui(key, lang), buttons)
