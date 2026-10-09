"""Chat standby confirmation and completion after Telegram contact proof."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.ai.cards import Draft, button, day_buttons, response, save_draft, stored_draft, ui
from nowa.ai.schema import ChatResponse
from nowa.ai.sessions import update_session
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core import booking, standby, telegram_tokens
from nowa.core.consent import policy_text
from nowa.messaging.outbox import telegram_chat
from nowa.messaging.templates import render_operational


def request_for(session: dict[str, Any], draft: dict[str, Any]) -> booking.BookingRequest:
    version, digest, _ = policy_text(session["lang"])
    return booking.BookingRequest(
        session["clinic_id"],
        date.fromisoformat(draft["day"]),
        draft["name"],
        draft["phone"],
        session["lang"],
        draft.get("area_id"),
        booking.ConsentInput(
            draft.get("consent_version", version),
            draft.get("consent_text_hash", digest),
            draft["booking_for"],
        ),
        f"standby_chat:{session['id']}:{session['turn_seq']}",
        origin_text=draft.get("origin_text"),
    )


def complete(
    conn: Connection, clock: Clock, session: dict[str, Any], draft: dict[str, Any]
) -> ChatResponse:
    result = standby.join_in_tx(conn, clock, request_for(session, draft))
    if isinstance(result, booking.BookingRefused):
        save_draft(conn, session, {"standby_refused": result.reason})
    else:
        save_draft(
            conn, session, {"standby_result": result.standby_id, "repeated": result.repeated}
        )
    return status(conn, clock, session)


def status(conn: Connection, clock: Clock, session: dict[str, Any]) -> ChatResponse:
    draft = stored_draft(session)
    if draft.get("standby_result"):
        row = (
            conn.execute(
                select(s.standbys).where(
                    s.standbys.c.id == draft["standby_result"],
                    s.standbys.c.clinic_id == session["clinic_id"],
                    s.standbys.c.contact_id == session["contact_id"],
                )
            )
            .mappings()
            .one()
        )
        return response(
            session,
            ui(
                "standby_duplicate" if draft.get("repeated") else "standby_joined",
                session["lang"],
                position=row["position"],
            ),
        )
    if draft.get("awaiting_telegram") and draft.get("standby_confirm_seq") == session["turn_seq"]:
        shown = response(
            session,
            ui("standby_link", session["lang"]),
            [
                button(
                    "standby_status",
                    ui("standby_check", session["lang"]),
                    "none",
                    standby_status=True,
                ),
            ],
        )
        shown.standby_pending = True
        return shown
    if draft.get("standby_refused") == "phone_cap":
        return response(session, render_operational("phone_cap", session["lang"], {}).text)
    return response(session, ui("refused", session["lang"]))


def confirm(conn: Connection, clock: Clock, session: dict[str, Any], signed: Draft) -> ChatResponse:
    draft = stored_draft(session)
    if draft.get("standby_result") or draft.get("standby_refused"):
        return status(conn, clock, session)
    values = signed.model_dump(mode="json")
    req = request_for(session, values)
    if not booking._valid_request(conn, req):
        return response(session, ui("refused", session["lang"]))
    eid = booking.get_or_create_evening(conn, req.clinic_id, req.date)
    booking._lock_evening(conn, eid)
    contact_id = standby.contact_for(conn, req)
    update_session(conn, session, contact_id=contact_id)
    phone = booking.normalize_phone(req.contact_phone)
    assert phone is not None
    if telegram_chat(conn, phone, "patient"):
        return complete(conn, clock, session, values)
    if booking.active_for_phone(conn, clock, req.clinic_id, contact_id) >= 3:
        return response(session, render_operational("phone_cap", session["lang"], {}).text)
    if not get_settings().telegram_bot_username:
        return response(
            session,
            ui("standby_unavailable", session["lang"]),
            day_buttons(conn, clock, session["clinic_id"], session["lang"]),
        )
    # Keep the original validated draft, never create a waiting entry before proof.
    draft.update(
        awaiting_telegram=True,
        standby=True,
        standby_confirm_seq=session["turn_seq"],
        consent_version=req.consent.version,
        consent_text_hash=req.consent.text_hash,
    )
    save_draft(conn, session, draft)
    shown = status(conn, clock, session)
    if get_settings().telegram_bot_username:
        _, shown.telegram_url = telegram_tokens.mint(
            conn, clock, req.clinic_id, "patient_telegram", contact_id, lang=session["lang"]
        )
    return shown


def linked(conn: Connection, clock: Clock, clinic_id: int, contact_id: int) -> None:
    sessions = (
        conn.execute(
            select(s.chat_sessions)
            .where(
                s.chat_sessions.c.clinic_id == clinic_id,
                s.chat_sessions.c.contact_id == contact_id,
                s.chat_sessions.c.state == "open",
                s.chat_sessions.c.draft.is_not(None),
            )
            .with_for_update()
        )
        .mappings()
        .all()
    )
    for row in sessions:
        session = dict(row)
        draft = stored_draft(session)
        if (
            draft.get("awaiting_telegram")
            and draft.get("standby_confirm_seq") == session["turn_seq"]
            and session["last_safe_turn_seq"] < session["turn_seq"]
            and (clock.now(clinic_id) - session["last_turn_at"]).total_seconds() < 1800
        ):
            complete(conn, clock, session, draft)
