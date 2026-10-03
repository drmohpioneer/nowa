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
    assert len(phone) == 1 and phone[0]["recipient_name"] == "karim"
    assert phone[0]["channel"] == "telegram" and phone[0]["recipient"] == "+201000000777"
    other = session(client)
    assert client.get(BASE + "/demo/phone", params={"session": other}).json() == []
    # Real clinics never expose a drawn phone, even with a bound contact.
    get_settings().demo_mode = False
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    assert client.get(BASE + "/demo/phone", params={"session": key}).status_code == 403
    assert 'id="phone"' not in client.get(BASE).text
