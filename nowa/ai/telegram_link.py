"""Renew a session's expired patient claim through the existing tap adapter."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.ai.cards import response
from nowa.ai.schema import ChatResponse
from nowa.clock import Clock
from nowa.core import telegram_tokens


def renew(conn: Connection, clock: Clock, session: dict[str, Any], url: Any) -> ChatResponse:
    if not isinstance(url, str):
        raise HTTPException(422)
    try:
        digest = telegram_tokens.link_digest(url)
    except ValueError:
        raise HTTPException(422) from None
    row = (
        conn.execute(
            select(s.link_tokens)
            .where(
                s.link_tokens.c.token_hash == digest,
                s.link_tokens.c.kind == "patient_telegram",
                s.link_tokens.c.clinic_id == session["clinic_id"],
                s.link_tokens.c.subject_id == session["contact_id"],
            )
            .with_for_update()
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(403)
    key = f"telegram_renew:{session['session_key_hash']}:{digest}"
    saved = conn.execute(
        select(s.idempotency_keys.c.result_json).where(
            s.idempotency_keys.c.clinic_id == session["clinic_id"],
            s.idempotency_keys.c.key == key,
        )
    ).scalar_one_or_none()
    if saved is not None:
        return ChatResponse.model_validate(saved)
    state = telegram_tokens.link_status(conn, clock, url)
    if state["status"] != "expired":
        raise HTTPException(409)
    _, replacement = telegram_tokens.mint(
        conn,
        clock,
        session["clinic_id"],
        "patient_telegram",
        session["contact_id"],
        lang=session["lang"],
    )
    shown = response(session, "")
    shown.telegram_url = replacement
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=session["clinic_id"],
            key=key,
            command="telegram_renew",
            result_json=shown.model_dump(),
            created_at=clock.now(session["clinic_id"]),
        )
    )
    return shown
