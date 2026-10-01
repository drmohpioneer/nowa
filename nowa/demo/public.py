"""Mint an existing slice-08 booking card from a fixed fictional identity."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.engine import Engine

from nowa.ai.cards import booking_card
from nowa.ai.schema import ChatResponse, TurnFields
from nowa.ai.sessions import load_clinic, load_session, update_session
from nowa.clock import Clock
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
        session = load_session(conn, clinic_id, session_key)
        patient = PATIENTS[choice]
        seq = session["turn_seq"] + 1
        update_session(conn, session, turn_seq=seq)
        shown, _ = booking_card(
            conn,
            clock,
            clinic,
            session,
            session_key,
            TurnFields(
                day=None, area=None, name=patient.name, phone=patient.phone, booking_for="self"
            ),
            seq,
        )
        # Public booking uses area buttons, never a browser location prompt.
        shown.buttons = [b for b in shown.buttons if b.id != "location"]
        return shown
