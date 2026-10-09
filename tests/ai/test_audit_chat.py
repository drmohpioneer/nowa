"""deterministic patient chat paths."""

import json
import re
from html import unescape

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.db import write_tx
from tests.ai.support import BASE, book_output, day_payload, output, session, tap, turn


def action(client, key, kind, payload, idem="audit-action"):
    result = client.post(
        BASE + "/tap", json=dict(session=key, action=kind, payload=payload, idempotency_key=idem)
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_audit_19_emergency_blocks_faq_but_plain_chest_pain_is_open(chat):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(output(triage="unclear", reply="Is the pain ongoing?"))]
    plain = turn(client, key, "عندي ألم في صدري")
    assert plain["state"] == "open"
    app.state.ai_chain = [FixtureAdapter(output(triage="emergency"))]
    emergency = turn(client, key, "ألم شديد في صدري وعرقان")
    assert emergency["state"] == "locked_emergency"
    for faq in ("price", "hours", "address"):
        result = action(client, key, "none", {"faq": faq}, faq)
        assert result["state"] == "locked_emergency" and "123" in result["reply"]
        assert not result["buttons"]


def test_audit_20_lookup_requires_intent_after_triage(chat):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key, "book")))
    app.state.ai_chain = [FixtureAdapter(output(triage="unclear", reply="Is the pain ongoing?"))]
    result = turn(client, key, "عندي ألم في صدري")
    assert not any(b["action"]["kind"] == "lookup" for b in result["buttons"])
    choice = result["buttons"][0]["action"]
    lookup = action(client, key, choice["kind"], choice["payload"])
    assert [b["action"]["kind"] for b in lookup["buttons"]] == ["lookup"]
    from nowa.ai.prompt import OUTPUT_RULES

    assert "ONE fact only" in OUTPUT_RULES


@pytest.mark.parametrize("field", ["name", "phone", "day", "area_text"])
def test_audit_22_edit_summary_invalidates_old_confirmation(chat, engine, field):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    summary = turn(client, key, "book")
    # The summary shows the phone the way patients read it, never in +20 form.
    assert "01000000777" in summary["reply"] and "+20" not in summary["reply"]
    assert all(label in summary["reply"] for label in ("Name:", "Day:", "Coming from:", "Mobile:"))
    old = day_payload(summary)
    picker = action(client, key, "none", {"edit": "pick"}, "pick")
    assert {b["action"]["payload"]["edit"] for b in picker["buttons"]} == {
        "name",
        "phone",
        "day",
        "area_text",
    }
    edited = action(client, key, "none", {"edit": field}, "edit-field")
    assert not any(b["action"]["kind"] == "confirm" for b in edited["buttons"])
    assert not tap(client, key, old)["booking_confirmed"]
    with engine.connect() as conn:
        assert conn.execute(select(s.bookings.c.id)).first() is None
        stored = json.loads(conn.execute(select(s.chat_sessions.c.draft)).scalar_one())
        assert field not in stored["validated"]
        for text in conn.execute(select(s.action_record.c.text)).scalars():
            assert not text or "+201000000777" not in text


def test_audit_23_lookup_retry_and_31_normalization(chat):
    client, _, _ = chat
    key = session(client)
    result = client.post(
        BASE + "/lookup",
        json=dict(session=key, name="Missing Patient", last4="١٢٣٤", idempotency_key="lookup"),
    )
    assert result.status_code == 200
    data = result.json()
    assert [b["action"]["kind"] for b in data["buttons"]] == ["lookup"]
    assert "راجع الاسم بالكامل" in data["reply"]


def test_audit_11_24_page_and_session_language(chat, engine):
    client, _, _ = chat
    html = client.get(BASE + "?lang=en&from=demo").text
    assert '<html lang="en" dir="ltr">' in html
    assert "Clinic chat · Nowa" in html and "Dr. Hesham Mostafa" in unescape(html)
    config = json.loads(
        re.search(r'<script id="chat-config" type="application/json">(.*?)</script>', html)[1]
    )
    assert config["lang"] == "en"
    key = client.post(BASE + "/session?lang=en").json()["session"]
    from nowa.ai.sessions import session_hash

    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.chat_sessions.c.lang).where(
                    s.chat_sessions.c.session_key_hash == session_hash(key)
                )
            ).scalar_one()
            == "en"
        )


def test_audit_28_public_area_prompt_has_no_typing_request(chat, engine):
    client, _, cid = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(judge_id=None))
    key = session(client)
    identity = action(client, key, "none", {"identity": 0})
    choice = next(b["action"] for b in identity["buttons"] if b["action"]["kind"] == "book")
    areas = action(client, key, choice["kind"], choice["payload"], "day")
    assert areas["reply"] == "اختار منطقتك"
    assert areas["buttons"] and all(b["action"]["kind"] == "set_area" for b in areas["buttons"])
    assert not re.search("[٠-٩]", json.dumps(areas, ensure_ascii=False))
