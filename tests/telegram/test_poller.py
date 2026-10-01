import logging
import threading
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from nowa.app import create_app
from nowa.config import get_settings
from nowa.telegram import poller
from tests.telegram.support import message


def test_poller_deletes_webhook_and_acknowledges_after_handling():
    stop = threading.Event()
    router = Mock()
    calls = []

    class FakeAPI:
        def call(self, method, payload):
            calls.append((method, payload))
            if method == "deleteWebhook":
                return {"ok": True}
            if "offset" not in payload:
                return {"ok": True, "result": [message(40), message(41)]}
            stop.set()
            return {"ok": True, "result": []}

    poller.run_forever(router, FakeAPI(), stop=stop)
    assert calls == [
        ("deleteWebhook", {"drop_pending_updates": False}),
        ("getUpdates", {"timeout": 25, "allowed_updates": ["message", "callback_query"]}),
        (
            "getUpdates",
            {"timeout": 25, "allowed_updates": ["message", "callback_query"], "offset": 42},
        ),
    ]
    assert router.handle_update.call_args_list[0].args == (message(40),)
    assert router.handle_update.call_args_list[1].args == (message(41),)


def test_poller_does_not_ack_failed_handler():
    stop = Mock()
    stop.is_set.side_effect = [False, False, False, False, True]
    router = Mock()
    router.handle_update.side_effect = [RuntimeError("private error never logged"), None]
    api = Mock()
    api.call.side_effect = [
        {"ok": True},
        {"ok": True, "result": [message(5)]},
        {"ok": True, "result": [message(5)]},
    ]
    poller.run_forever(router, api, stop=stop)
    assert router.handle_update.call_count == 2
    assert "offset" not in api.call.call_args_list[1].args[1]
    assert "offset" not in api.call.call_args_list[2].args[1]
    stop.wait.assert_called_once_with(1)


@pytest.mark.parametrize(
    "token,demo,no_network,expected",
    [
        (False, True, False, False),
        (True, True, False, True),
        (True, False, False, False),
        (True, True, True, False),
        (False, True, True, False),
    ],
)
def test_app_polls_only_demo_with_token(
    bot, engine, monkeypatch, caplog, token, demo, no_network, expected
):
    _, _, _, _, clock, _, _ = bot
    if token:
        get_settings().telegram_bot_token = "fictional-token"
    get_settings().demo_no_network = no_network
    caplog.set_level(logging.INFO)
    spy = Mock()
    monkeypatch.setattr(poller, "run_forever", spy)
    monkeypatch.setattr("nowa.worker.run_forever", Mock())
    with TestClient(create_app(engine, clock=clock, demo_worker=demo)):
        pass
    assert spy.call_count == int(expected)
    assert sum("disabled_demo_no_network" in m for m in caplog.messages) == int(demo and no_network)


def test_poller_reports_failed_delete_without_polling(caplog):
    api = Mock()
    api.call.return_value = {"ok": False, "description": "must not log provider detail"}
    poller.run_forever(Mock(), api, stop=threading.Event())
    api.call.assert_called_once_with("deleteWebhook", {"drop_pending_updates": False})
    assert "delete_webhook_failed" in caplog.text
    assert "provider detail" not in caplog.text


@pytest.mark.parametrize(
    "bad",
    [
        {"update_id": 40, "message": {"text": "private content"}},
        {"update_id": 40, "callback_query": "private content"},
        message("40", text="private content"),
    ],
)
def test_poller_skips_malformed_update_and_advances_offset(caplog, bad):
    stop = threading.Event()
    router = Mock()
    calls = []

    class FakeAPI:
        def call(self, method, payload):
            calls.append((method, payload))
            if method == "deleteWebhook":
                return {"ok": True}
            if "offset" not in payload:
                return {"ok": True, "result": [bad]}
            if payload["offset"] == 41:
                return {"ok": True, "result": [message(41)]}
            stop.set()
            return {"ok": True, "result": []}

    poller.run_forever(router, FakeAPI(), stop=stop)
    router.handle_update.assert_called_once_with(message(41))
    assert [p.get("offset") for m, p in calls if m == "getUpdates"] == [None, 41, 42]
    assert "update_id=40 kind=poller outcome=invalid_update" in caplog.text
    assert "private content" not in caplog.text
