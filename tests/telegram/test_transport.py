import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from nowa.__main__ import main
from nowa.app import create_app
from nowa.config import get_settings
from nowa.telegram.api import BotAPI, set_webhook
from tests.telegram.support import message


@pytest.mark.parametrize(
    "secret,header,status",
    [
        (None, None, 404),
        (None, "", 404),
        ("short", "short", 404),
        ("s" * 32, None, 401),
        ("s" * 32, "", 401),
        ("s" * 32, "wrong", 401),
        ("s" * 32, "s" * 32, 200),
    ],
)
def test_webhook_secret_before_body_or_router(bot, engine, monkeypatch, secret, header, status):
    _, _, _, _, clock, _, _ = bot
    if secret is not None:
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    get_settings().telegram_webhook_secret = secret or ""
    with TestClient(create_app(engine, clock=clock)) as client:
        spy = Mock()
        client.app.state.telegram_router = spy
        headers = {} if header is None else {"X-Telegram-Bot-Api-Secret-Token": header}
        response = client.post(
            "/telegram/webhook",
            headers=headers,
            content=json.dumps(message(1)) if status == 200 else "invalid JSON",
        )
    assert response.status_code == status
    assert spy.handle_update.call_count == int(status == 200)


def test_authenticated_bad_json_is_422(bot, engine, monkeypatch):
    _, _, _, _, clock, _, _ = bot
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s" * 32)
    get_settings().telegram_webhook_secret = "s" * 32
    with TestClient(create_app(engine, clock=clock)) as client:
        response = client.post(
            "/telegram/webhook",
            content="bad",
            headers={"X-Telegram-Bot-Api-Secret-Token": "s" * 32},
        )
        assert response.status_code == 422


@pytest.mark.parametrize("secret", [None, "short"])
def test_set_webhook_refuses_weak_secret(monkeypatch, capsys, secret):
    if secret is not None:
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    api = Mock()
    assert set_webhook(api) == 2
    assert "32 bytes" in capsys.readouterr().out
    api.call.assert_not_called()


@pytest.mark.parametrize("ok", [False, True])
def test_cli_set_webhook(monkeypatch, capsys, ok):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s" * 32)
    get_settings().telegram_webhook_secret = "s" * 32
    monkeypatch.setattr("sys.argv", ["nowa", "telegram", "set-webhook"])
    spy = Mock(return_value={"ok": ok, "description": "Bad Request: bad webhook"})
    monkeypatch.setattr(BotAPI, "call", spy)
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == (0 if ok else 2)
    assert capsys.readouterr().out.strip() == (
        "http://127.0.0.1:8000/telegram/webhook" if ok else "Bad Request: bad webhook"
    )
    assert spy.call_args.args == (
        "setWebhook",
        {
            "url": "http://127.0.0.1:8000/telegram/webhook",
            "secret_token": "s" * 32,
            "allowed_updates": ["message", "callback_query"],
        },
    )


def test_cli_weak_secret_exits_two(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["nowa", "telegram", "set-webhook"])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2
    assert "32 bytes" in capsys.readouterr().out


@pytest.mark.parametrize("second_ok", [True, False])
def test_direct_429_retries_once(second_ok):
    get_settings().telegram_bot_token = "fictional-token"
    attempts, sleeps = [], []

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1 or not second_ok:
            return httpx.Response(
                429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 2}}
            )
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        api = BotAPI(client, sleep=sleeps.append)
        assert api.interactive("sendMessage", {"chat_id": "1", "text": "hello"}) == second_ok
    assert len(attempts) == 2
    assert sleeps == [2]


def test_bot_api_disabled_and_timeout():
    assert BotAPI().call("getUpdates", {})["ok"] is False
    get_settings().telegram_bot_token = "fictional-token"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("not logged"))
        )
    ) as client:
        assert BotAPI(client).call("getUpdates", {}) == {
            "ok": False,
            "description": "Telegram transport failed",
        }


def test_failed_direct_reply_logs_outcome_and_records_no_usage(bot, engine, caplog):
    import logging

    from nowa import schema as s
    from nowa.telegram.router import Context
    from tests.telegram.support import doctor_link
    from tests.web.support import rows

    _, _, _, _, clock, _, _ = bot
    doctor_link(bot, engine)
    before = rows(engine, s.usage)
    get_settings().telegram_bot_token = "fictional-token"
    caplog.set_level(logging.INFO)
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(
            429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        ctx = Context(engine, clock, BotAPI(client, sleep=lambda delay: None), 90, "101")
        ctx.refresh()
        ctx.send("menu")
    assert len(attempts) == 2
    assert rows(engine, s.usage) == before
    assert "update_id=90 kind=reply outcome=failed" in caplog.text
    assert "fictional-token" not in caplog.text


@pytest.mark.parametrize("declared", [str(64 * 1024 + 1), None, "1"])
def test_webhook_rejects_oversized_body_without_parsing(monkeypatch, declared):
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException
    from starlette.requests import Request

    from nowa.web import telegram_webhook

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s" * 32)
    get_settings().telegram_webhook_secret = "s" * 32
    parse = Mock(side_effect=AssertionError("oversized body must not be parsed"))
    monkeypatch.setattr(telegram_webhook, "loads", parse)
    handler = Mock()
    headers = [(b"x-telegram-bot-api-secret-token", b"s" * 32)]
    if declared is not None:
        headers.append((b"content-length", declared.encode()))
    chunks = [b"x" * (32 * 1024), b"x" * (32 * 1024 + 1)]
    reads = []

    async def receive():
        reads.append(1)
        chunk = chunks.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    request = Request(
        {"type": "http", "headers": headers,
         "app": SimpleNamespace(state=SimpleNamespace(telegram_router=handler))},
        receive,
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(telegram_webhook.webhook(request))
    assert raised.value.status_code == 413
    assert len(reads) == (0 if declared == str(64 * 1024 + 1) else 2)
    parse.assert_not_called()
    handler.handle_update.assert_not_called()


def test_webhook_accepts_exact_body_limit(bot, engine, monkeypatch):
    _, _, _, _, clock, _, _ = bot
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s" * 32)
    get_settings().telegram_webhook_secret = "s" * 32
    body = json.dumps(message(1)).encode()
    body += b" " * (64 * 1024 - len(body))
    with TestClient(create_app(engine, clock=clock)) as client:
        handler = Mock()
        client.app.state.telegram_router = handler
        response = client.post(
            "/telegram/webhook", content=body,
            headers={"X-Telegram-Bot-Api-Secret-Token": "s" * 32},
        )
    assert response.status_code == 200
    handler.handle_update.assert_called_once_with(message(1))
