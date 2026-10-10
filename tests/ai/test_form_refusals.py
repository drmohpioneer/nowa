"""Every booking refusal says its own reason and leaves the chat usable."""

import pytest

from nowa.ai.adapters import FixtureAdapter
from nowa.ai.cards import refused_reply, ui
from tests.ai.support import book_output, day_payload, session, tap, turn


def book_once(client, app):
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output("self"))]
    data = turn(client, key, "احجز لي Karim Father 01000000777 الثلاثاء من المعادي")
    return key, tap(client, key, day_payload(data))


def test_duplicate_booking_says_already_booked(chat):
    client, app, _ = chat
    _, first = book_once(client, app)
    assert first["booking_confirmed"]
    _, second = book_once(client, app)
    assert not second.get("booking_confirmed")
    assert second["reply"] == ui("refused_already_booked", "ar")
    assert second["reply"] != ui("refused", "ar")
    kinds = [b["action"]["kind"] for b in second["buttons"]]
    assert kinds[0] == "lookup", "the first chip looks up the booking"
    assert "book" in kinds, "the usual day chips are offered again"


def test_already_booked_reply_reveals_no_booking_details(chat):
    """Abuse case: someone who knows a patient's name and phone probes for their booking.
    The refusal may say a booking exists; it must not hand over its number, time or link."""
    client, app, _ = chat
    _, first = book_once(client, app)
    _, second = book_once(client, app)
    reply = second["reply"]
    assert not any(ch.isdigit() for ch in reply)
    assert "http" not in reply and "/l/" not in reply
    for button in second["buttons"]:
        assert "/l/" not in str(button), "no private link inside a chip"
    assert not second.get("telegram_url") and not second.get("link")


@pytest.mark.parametrize("reason", ["closed_day", "booking_closed", "invalid_input"])
@pytest.mark.parametrize("lang", ["ar", "en"])
def test_each_refusal_reason_has_its_own_message(chat, engine, reason, lang):
    client, app, _ = chat
    with engine.connect() as conn:
        shown = refused_reply(
            conn,
            app.state.clock,
            {"lang": lang, "clinic_id": 1, "state": "open"},
            reason,
        )
    assert shown.reply == ui("refused_" + reason, lang)
    assert shown.reply != ui("refused", lang)
    assert all(b.action.kind != "lookup" for b in shown.buttons)


def test_unknown_refusal_keeps_generic_message(chat, engine):
    client, app, _ = chat
    with engine.connect() as conn:
        shown = refused_reply(
            conn, app.state.clock, {"lang": "ar", "clinic_id": 1, "state": "open"}, "other"
        )
    assert shown.reply == ui("refused", "ar")
