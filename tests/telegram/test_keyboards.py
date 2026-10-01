import json
from dataclasses import replace

import httpx
import pytest

from nowa.config import get_settings
from nowa.core import timing
from nowa.messaging.adapters import TelegramAdapter
from nowa.telegram import keyboards as k
from nowa.web.strings import STRINGS, text

CASES = [
    ("omw", 1, None, "-"),
    ("omw", None, 2, "-"),
    ("area", 1, None, "12"),
    ("in", 1, 2, "-"),
    ("walkin", 1, None, "-"),
    ("undo", 1, None, "-"),
    ("undo", None, 2, "-"),
    ("more", 1, None, "-"),
    ("close", 1, None, "-"),
    ("closeok", 1, None, "0"),
    ("cancel", 1, None, "-"),
    ("cancelok", 1, None, "a" * 32),
    ("unlink", None, None, "-"),
    ("unlinkok", None, None, "-"),
    ("tgmenu", None, None, "-"),
] + [(verb, None, None, "123") for verb in ("qans", "qsave", "qlater", "qdismiss", "qedit")]


@pytest.mark.parametrize("verb,eid,bid,arg", CASES)
def test_grammar(verb, eid, bid, arg):
    value = k.build(verb, eid, bid, arg)
    assert len(value.encode()) <= 64
    assert k.parse(value) == k.Callback(verb, eid, bid, arg)
    assert (
        k.parse(
            k.build(
                verb,
                9223372036854775807 if eid else None,
                9223372036854775807 if bid else None,
                arg,
            )
        ).verb
        == verb
    )


@pytest.mark.parametrize(
    "data",
    [
        "bad:1:-:-",
        "in:1:2",
        "in:1:2:-:extra",
        "in:0:2:-",
        "in:-:2:-",
        "omw:1:2:-",
        "undo:-:-:-",
        "in:1:-:-",
        "unlink:1:-:-",
        "more:1:2:-",
        "walkin:1:-:7",
        "cancelok:1:-:bad",
        "closeok:1:-:-1",
        "area:1:-:0",
        "qsave:1:2:3",
        "qans:1:-:123",
        "area:1:-:" + "1" * 70,
        "more:01:-:-",
        "omw:١:-:-",
        "omw:-:9223372036854775808:-",
        "area:1:-:9223372036854775808",
    ],
)
def test_forged_grammar(data):
    with pytest.raises(ValueError):
        k.parse(data)


@pytest.mark.parametrize("template", ["1", "2", "3", "4", "5", "6", "op:doctor_alert_unreachable"])
def test_outbox_markup(template):
    row = {
        "template_id": template,
        "idempotency_key": "are_you_on_way:99:1791298800",
        "booking_id": 8,
        "lang": "en",
    }
    markup = k.markup_for(row)
    if template == "5":
        assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == [
            "omw:99:-:-",
            "cancel:99:-:-",
        ]
    elif template == "2":
        assert markup["inline_keyboard"][0][0]["callback_data"] == "omw:-:8:-"
    else:
        assert markup is None


def test_malformed_template5_key():
    assert k.markup_for({"template_id": "5", "idempotency_key": "other:1:2"}) is None


@pytest.mark.parametrize("state", ["booked", "told_to_leave", "on_my_way"])
def test_patient_buttons(state):
    rows = k.patient_booking(1, state, "ar")["inline_keyboard"]
    assert rows[0][0]["url"].startswith(get_settings().public_base_url + "/l/")
    if state != "booked":
        assert rows[1][0]["callback_data"] == (
            "undo:-:1:-" if state == "on_my_way" else "omw:-:1:-"
        )
    else:
        assert len(rows) == 1


def test_board_uses_engine_order_and_names():
    row = timing.BoardRow(7, 8, "كريم", "booked", True, False, "chat", None, None, None, 2)
    board = timing.Board([replace(row, booking_id=i + 7, queue_number=i + 8) for i in range(5)])
    short = k.board(1, board, "ar")["inline_keyboard"]
    full = k.board(1, board, "ar", full=True)["inline_keyboard"]
    assert short[0][0]["text"] == "8 كريم ⚠️2"
    assert [r[0]["callback_data"] for r in short[:3]] == ["in:1:7:-", "in:1:8:-", "in:1:9:-"]
    assert short[3][0]["text"] == "المزيد"
    assert len(full) == len(short) + 1
    assert k.location("ar")["keyboard"][0][0]["request_location"] is True
    assert k.location("ar")["one_time_keyboard"] is True
    assert k.patient_menu()["keyboard"] == [["حجوزاتي"], ["وقف الرسايل هنا"]]


def test_adapter_uses_shared_markup_and_plain_text():
    get_settings().telegram_bot_token = "fictional-token"
    captured = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                captured.append(json.loads(request.content))
                or httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            )
        )
    ) as client:
        row = {
            "chat_id": "101",
            "body": "<untrusted>",
            "template_id": "5",
            "lang": "ar",
            "idempotency_key": "are_you_on_way:1:123",
        }
        assert TelegramAdapter(client).send(row).outcome == "accepted"
    assert captured[0]["reply_markup"] == k.markup_for(row)
    assert captured[0]["text"] == "<untrusted>"
    assert set(captured[0]) == {"chat_id", "text", "reply_markup"}


def test_all_ui_wording_is_under_tg():
    assert all(
        set(value) == {"ar", "en", "franco"}
        for key, value in STRINGS.items()
        if key.startswith("tg.")
    )
    assert text("tg.omw", "ar") == "🚗 في الطريق"
