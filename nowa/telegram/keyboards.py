import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nowa.config import get_settings
from nowa.core import booking, timing
from nowa.web.strings import text

Markup = dict[str, Any]
VERBS = {
    "omw",
    "area",
    "in",
    "walkin",
    "undo",
    "more",
    "close",
    "closeok",
    "cancel",
    "cancelok",
    "unlink",
    "unlinkok",
    "tgmenu",
    "qans",
    "qsave",
    "qlater",
    "qdismiss",
    "qedit",
}


@dataclass(frozen=True)
class Callback:
    verb: str
    evening_id: int | None = None
    booking_id: int | None = None
    arg: str = "-"


def parse(value: str) -> Callback:
    if len(value.encode()) > 64:
        raise ValueError("callback length")
    parts = value.split(":")
    if len(parts) != 4 or parts[0] not in VERBS:
        raise ValueError("callback shape")
    verb, evening, subject, arg = parts
    if not all(v == "-" or re.fullmatch(r"[1-9][0-9]*", v) for v in (evening, subject)):
        raise ValueError("callback ids")
    eid = None if evening == "-" else int(evening)
    bid = None if subject == "-" else int(subject)
    if any(value is not None and value > 2**63 - 1 for value in (eid, bid)):
        raise ValueError("callback id range")
    if verb in {"unlink", "unlinkok", "tgmenu"}:
        valid = eid is None and bid is None and arg == "-"
    elif verb in {"omw", "undo"}:
        valid = (eid is None) != (bid is None) and arg == "-"
    elif verb == "in":
        valid = eid is not None and bid is not None and arg == "-"
    elif verb in {"area", "closeok"}:
        valid = (
            eid is not None
            and bid is None
            and bool(re.fullmatch(r"[1-9][0-9]*" if verb == "area" else r"0|[1-9][0-9]*", arg))
        )
    elif verb == "cancelok":
        valid = eid is not None and bid is None and bool(re.fullmatch(r"[0-9a-f]{32}", arg))
    elif verb.startswith("q"):
        valid = eid is None and bid is None and bool(re.fullmatch(r"[1-9][0-9]*", arg))
    else:
        valid = eid is not None and bid is None and arg == "-"
    if not valid:
        raise ValueError("callback fields")
    if verb in {"area", "closeok"} or verb.startswith("q"):
        if int(arg) > 2**63 - 1:
            raise ValueError("callback argument range")
    return Callback(verb, eid, bid, arg)


def build(
    verb: str, evening_id: int | None = None, booking_id: int | None = None, arg: str = "-"
) -> str:
    value = f"{verb}:{evening_id if evening_id is not None else '-'}:"
    value += f"{booking_id if booking_id is not None else '-'}:{arg}"
    parse(value)
    return value


def button(
    key: str,
    verb: str,
    evening_id: int | None = None,
    booking_id: int | None = None,
    arg: str = "-",
    lang: str = "ar",
) -> dict[str, str]:
    return {
        "text": text("tg." + key, lang),
        "callback_data": build(verb, evening_id, booking_id, arg),
    }


def patient_menu(lang: str = "ar") -> Markup:
    return {
        "keyboard": [[text("tg.bookings", lang)], [text("tg.unlink", lang)]],
        "resize_keyboard": True,
    }


def doctor_menu(lang: str) -> Markup:
    return {"keyboard": [[text("tg.omw", lang)]], "resize_keyboard": True}


def location(lang: str) -> Markup:
    return {
        "keyboard": [
            [{"text": text("tg.location", lang), "request_location": True}],
            [text("tg.area", lang)],
        ],
        "one_time_keyboard": True,
        "resize_keyboard": True,
    }


def patient_booking(booking_id: int, state: str, lang: str, *, details: bool = True) -> Markup:
    rows = []
    if details:
        rows.append(
            [
                {
                    "text": text("tg.details", lang),
                    "url": get_settings().public_base_url
                    + "/l/"
                    + booking.link_code_for(booking_id),
                }
            ]
        )
    if state in {"told_to_leave", "on_my_way"}:
        undo = state == "on_my_way"
        rows.append(
            [
                button(
                    "patient_undo" if undo else "patient_omw",
                    "undo" if undo else "omw",
                    booking_id=booking_id,
                    lang=lang,
                )
            ]
        )
    return {"inline_keyboard": rows}


def board(evening_id: int, value: timing.Board, lang: str, *, full: bool = False) -> Markup:
    remaining = [row for row in value.rows if row.remaining]
    rows = []
    for row in remaining if full else remaining[:3]:
        label = text("tg.board_row", lang).format(
            number=row.queue_number,
            patient=row.patient_first_name or text("tg.unknown_patient", lang),
            mark=text("tg.no_show_mark", lang).format(count=row.no_show_count)
            if row.no_show_count
            else "",
        )
        rows.append([{"text": label, "callback_data": build("in", evening_id, row.booking_id)}])
    if not full:
        rows.append([button("more", "more", evening_id, lang=lang)])
    rows.extend(
        [
            [
                button("walkin", "walkin", evening_id, lang=lang),
                button("undo", "undo", evening_id, lang=lang),
            ],
            [
                button("close", "close", evening_id, lang=lang),
                button("cancel", "cancel", evening_id, lang=lang),
            ],
            [button("bookings", "tgmenu", lang=lang)],
        ]
    )
    return {"inline_keyboard": rows}


def question_buttons(question_id: int, lang: str, *, draft: bool = False) -> Markup:
    verbs = (
        [("q_save", "qsave"), ("q_answer", "qedit")]
        if draft
        else [("q_answer", "qans"), ("q_later", "qlater"), ("q_dismiss", "qdismiss")]
    )
    return {
        "inline_keyboard": [
            [button(key, verb, arg=str(question_id), lang=lang) for key, verb in verbs]
        ]
    }


def markup_for(outbox_row: Mapping[str, Any]) -> Markup | None:
    lang = outbox_row.get("lang", "ar")
    key = outbox_row.get("idempotency_key", "")
    if outbox_row.get("template_id") == "6":
        match = re.fullmatch(r"report:([1-9][0-9]*)", key)
        if match is None:
            return None
        return {
            "inline_keyboard": [
                [
                    {
                        "text": text("tg.q_view", lang),
                        "url": get_settings().public_base_url + "/d/report/" + match[1],
                    }
                ]
            ]
        }
    if outbox_row.get("template_id") == "op:question_card":
        match = re.fullmatch(r"report:([1-9][0-9]*):q:([1-9][0-9]*)", key)
        return question_buttons(int(match[2]), lang) if match else None
    if outbox_row.get("template_id") == "5":
        key = outbox_row.get("idempotency_key", "")
        match = re.fullmatch(r"are_you_on_way:([1-9][0-9]*):[0-9]+", key)
        if match is None:
            return None
        eid = int(match[1])
        return {
            "inline_keyboard": [
                [button("omw", "omw", eid, lang=lang), button("cancel", "cancel", eid, lang=lang)]
            ]
        }
    if outbox_row.get("template_id") == "2" and outbox_row.get("booking_id") is not None:
        return patient_booking(outbox_row["booking_id"], "told_to_leave", lang, details=False)
    return None
