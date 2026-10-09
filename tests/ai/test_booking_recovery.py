"""day expansion and recovery of a booking in progress."""

import json

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai import conversation
from nowa.ai.cards import ui
from nowa.ai.chain import ChainResult
from nowa.ai.sessions import load_session, update_session
from nowa.db import write_tx
from tests.ai.support import BASE, output, session, turn


def test_more_days_retains_first_day_and_exact_draft(chat, engine):
    client, app, clinic = chat
    key = session(client)
    with write_tx(engine) as conn:
        current = load_session(conn, clinic, key, app.state.clock)
        raw = json.dumps({"validated": ["booking_for"], "booking_for": "self", "name": "Pending"})
        update_session(conn, current, draft=raw)
    from nowa.ai.cards import day_buttons

    with engine.connect() as conn:
        first = day_buttons(conn, app.state.clock, clinic, "ar")[0].id
    for idem in ("more", "more", "more-again"):
        shown = client.post(
            BASE + "/tap",
            json=dict(
                session=key,
                action="more_days",
                payload={},
                idempotency_key=idem,
            ),
        ).json()
        assert len(shown["buttons"]) == 7
        assert first in {b["id"] for b in shown["buttons"]}
        assert "more_days" not in {b["id"] for b in shown["buttons"]}
        with engine.connect() as conn:
            assert conn.execute(select(s.chat_sessions.c.draft)).scalar_one() == raw


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
@pytest.mark.parametrize("failure", ["safe", "missing", "private"])
@pytest.mark.parametrize("step", ["name", "phone", "day", "area", "confirm"])
def test_failed_chain_reasks_pending_step_without_123(
    chat, engine, monkeypatch, lang, failure, step
):
    client, app, clinic = chat
    key = session(client)
    draft = {"booking_for": "self", "validated": ["booking_for"]}
    for field, value in [
        ("name", "Fictional Patient"),
        ("phone", "+201000000777"),
        ("day", "2026-10-06"),
        ("area_text", "Maadi"),
    ]:
        if field == {"area": "area_text", "confirm": None}.get(step, step):
            break
        draft[field] = value
        draft["validated"].append(field)
    if step == "confirm":
        draft["area_id"] = 5
    with write_tx(engine) as conn:
        current = load_session(conn, clinic, key, app.state.clock)
        update_session(conn, current, draft=json.dumps(draft), lang=lang, turn_seq=1)
    candidate = output(reply="Private /l/withheld") if failure == "private" else None

    async def failed(*args, **kwargs):
        return ChainResult(candidate, "fixed", safe_mode=failure == "safe")

    monkeypatch.setattr(conversation, "run_structured", failed)
    shown = turn(client, key, {"ar": "تمام", "en": "okay", "franco": "tamam"}[lang])
    assert "123" not in shown["reply"]
    assert shown["reply"].startswith(ui("draft_retry", lang) + "\n")
    assert "/l/withheld" not in shown["reply"]
    if step in ("day", "area", "confirm"):
        assert shown["buttons"]
    if step == "area":
        assert shown["buttons"][0]["id"] == "location"
        assert ui("area_ask", lang) in shown["reply"]
    with engine.connect() as conn:
        saved = json.loads(conn.execute(select(s.chat_sessions.c.draft)).scalar_one())
    for field in draft["validated"]:
        assert saved[field] == draft[field]
