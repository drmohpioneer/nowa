"""Mint an existing booking card from a fixed fictional identity."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import schema as s
from nowa.ai.cards import button, next_step, save_draft, ui
from nowa.ai.drafts import validate
from nowa.ai.schema import ChatResponse
from nowa.ai.sessions import load_clinic, load_session, update_session
from nowa.clock import Clock
from nowa.core.display import patient_display_name
from nowa.core.text_norm import western_digits
from nowa.db import write_tx
from nowa.demo.evening_script import PATIENTS


def buttons_only(clinic: dict[str, Any]) -> bool:
    return bool(clinic["is_sandbox"] and clinic["judge_id"] is None)


def identity(
    engine: Engine, clock: Clock, clinic_id: int, session_key: str, choice: int
) -> ChatResponse:
    with write_tx(engine) as conn:
        clinic = load_clinic(conn, clinic_id)
        if not buttons_only(clinic) or type(choice) is not int or not 0 <= choice < 3:
            raise HTTPException(403)
        session = load_session(conn, clinic_id, session_key, clock)
        patient = PATIENTS[choice]
        seq = session["turn_seq"] + 1
        update_session(conn, session, turn_seq=seq, last_turn_at=clock.now(clinic_id))
        draft = dict(
            name=patient_display_name(
                {"name": patient.name, "name_en": patient.name_en}, session["lang"]
            ),
            phone=patient.phone,
            booking_for="self",
            validated=[],
        )
        validate(conn, clock, clinic_id, draft)
        save_draft(conn, session, draft)
        return next_step(conn, clock, clinic, session, draft)


def public_areas(
    conn: Connection, session: dict[str, Any], draft: dict[str, Any], shown: ChatResponse
) -> ChatResponse:
    shown.buttons = [b for b in shown.buttons if b.id != "location"]
    if "day" in draft.get("validated", []) and "area_text" not in draft.get("validated", []):
        lang = session["lang"]
        shown.reply = ui("area_ask", lang)
        shown.buttons = [
            button(
                f"area:{r.id}",
                western_digits(r.name_ar if lang == "ar" else r.name_en),
                "set_area",
                area_id=r.id,
            )
            for r in conn.execute(select(s.areas).where(s.areas.c.id <= 12).order_by(s.areas.c.id))
        ]
        shown.buttons.append(button("area:none", ui("area_other", lang), "set_area", area_id=None))
    return shown
