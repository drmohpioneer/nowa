import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.config import get_settings
from nowa.db import write_tx
from tests.ai.support import BASE, book_output, day_payload, session, tap, turn


@pytest.mark.parametrize("username", ["", "fictional_bot"])
def test_only_success_has_one_replayable_token_and_drawn_phone(chat, engine, username):
    client, app, cid = chat
    get_settings().telegram_bot_username = username
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    offer = turn(client, key)
    assert offer["telegram_url"] is None and not offer["booking_confirmed"]
    with engine.connect() as conn:
        assert not conn.execute(select(s.link_tokens)).first()
    confirmed = tap(client, key, day_payload(offer), "confirmed")
    assert confirmed["booking_confirmed"]
    assert bool(confirmed["telegram_url"]) == bool(username)
    assert "/l/" not in str(confirmed) and "/w/" not in str(confirmed)
    assert tap(client, key, day_payload(offer), "confirmed") == confirmed
    # A later ordinary chat turn must not destroy the stored successful response.
    turn(client, key, "hello")
    assert tap(client, key, day_payload(offer), "confirmed") == confirmed
    with engine.connect() as conn:
        tokens = conn.execute(select(s.link_tokens)).mappings().all()
        assert len(tokens) == int(bool(username))
        contact = conn.execute(select(s.bookings.c.contact_id)).scalar_one()
        if username:
            assert tokens[0]["subject_id"] == contact
    page = client.get(BASE).text
    assert 'id="phone"' in page and 'id="chat-phone"' in page and 'id="message"' in page
    phone = client.get(BASE + "/demo/phone", params={"session": key}).json()
    assert len(phone) == 1 and phone[0]["recipient_name"] == "Karim Father"
    assert phone[0]["channel"] == "telegram" and phone[0]["recipient"] == "+201000000777"
    other = session(client)
    assert client.get(BASE + "/demo/phone", params={"session": other}).json() == []
    # Real clinics never expose a drawn phone, even with a bound contact.
    get_settings().demo_mode = False
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    assert client.get(BASE + "/demo/phone", params={"session": key}).status_code == 403
    assert 'id="phone"' not in client.get(BASE).text


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_overbooked_time_honest_on_all_surfaces(chat, engine, frozen_clock, lang):
    from datetime import datetime

    from nowa.clock import CAIRO
    from nowa.core import booking, flows
    from nowa.messaging.templates import format_time
    from tests.test_booking import request
    from tests.web.support import ORIGIN

    client, app, cid = chat
    # Eighteen people at 13.3 minutes put the next one just before closing;
    # number 20 is the first booking beyond 23:00.
    for i in range(1, 20):
        assert isinstance(flows.book(engine, frozen_clock, request(cid, i)), booking.BookingOk)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    turn(client, key, "English please" if lang == "en" else "بالعربي")
    offered = turn(client, key, "book")
    confirmed = tap(client, key, day_payload(offered), "overbook-confirm")
    assert confirmed["booking_confirmed"], confirmed
    with engine.connect() as conn:
        booked = (
            conn.execute(select(s.bookings).where(s.bookings.c.queue_number == 20)).mappings().one()
        )
        body = conn.execute(
            select(s.outbox.c.body).where(
                s.outbox.c.booking_id == booked["id"], s.outbox.c.template_id == "1"
            )
        ).scalar_one()
    assert booked["expected_shown"] == datetime(2026, 10, 6, 23, 13, tzinfo=CAIRO)
    patient_time = format_time(booked["expected_shown"], lang)
    assert patient_time in confirmed["reply"]
    assert patient_time in body
    assert (
        patient_time
        in client.get("/l/" + booking.link_code_for(booked["id"]), params={"lang": lang}).text
    )
    frozen_clock.advance(
        minutes=(datetime(2026, 10, 6, 16, tzinfo=CAIRO) - frozen_clock.now(cid)).total_seconds()
        / 60
    )
    assert (
        client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        ).status_code
        == 200
    )
    board = client.get("https://testserver/d/api/tonight", params={"lang": lang}).json()
    row = next(r for r in board["rows"] if r["booking_id"] == booked["id"])
    assert datetime.fromisoformat(row["expected_shown"]) == booked["expected_shown"]
    import json
    import subprocess
    from pathlib import Path

    from nowa.web.strings import DOCTOR_TEXTS

    result = subprocess.run(
        ["node", "tests/web/doctor_board_dom.cjs"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        input=json.dumps(
            {"states": [board], "texts": {k: v[lang == "en"] for k, v in DOCTOR_TEXTS.items()}}
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_renewal_is_expiry_gated_replayable_and_session_scoped(chat, engine, frozen_clock):
    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    confirmed = tap(client, key, day_payload(turn(client, key)), "confirmed")
    old = confirmed["telegram_url"]

    def renew(owner, url, replay="renew"):
        return client.post(
            BASE + "/tap",
            json={
                "session": owner,
                "idempotency_key": replay,
                "action": "none",
                "payload": {"telegram_renew": url},
            },
        )

    other = session(client)
    assert renew(other, old).status_code == 403
    assert renew(key, old).status_code == 409
    frozen_clock.advance(minutes=15)
    renewed = renew(key, old)
    assert renewed.status_code == 200
    new = renewed.json()["telegram_url"]
    assert new != old
    assert renew(key, old, "different-key").json() == renewed.json()
    assert renew(key, new).status_code == 409
    with engine.connect() as conn:
        tokens = conn.execute(select(s.link_tokens)).mappings().all()
        assert len(tokens) == 2
        assert all(t["clinic_id"] == cid for t in tokens)
        assert len(conn.execute(select(s.telegram_pending)).all()) == 2
        assert not conn.execute(select(s.telegram_links)).first()
    # The emergency boundary precedes even this presentation action.
    from nowa.ai.sessions import session_hash

    with write_tx(engine) as conn:
        conn.execute(
            s.chat_sessions.update()
            .where(s.chat_sessions.c.session_key_hash == session_hash(key))
            .values(state="locked_emergency", emergency_kind="general")
        )
    frozen_clock.advance(minutes=15)
    assert renew(key, new).json()["state"] == "locked_emergency"
