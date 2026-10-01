import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from nowa.config import get_settings, secret_ok


class TelegramLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx's request URL includes the bot credential, even at INFO level.
        if "api.telegram.org/bot" in record.getMessage():
            record.msg = "kind=telegram_transport outcome=response"
            record.args = ()
        return True


def configure_logging() -> None:
    logger = logging.getLogger("httpx")
    if not any(isinstance(value, TelegramLogFilter) for value in logger.filters):
        logger.addFilter(TelegramLogFilter())


class API(Protocol):
    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class BotAPI:
    def __init__(
        self, client: httpx.Client | None = None, *, sleep: Callable[[float], object] = time.sleep
    ) -> None:
        self.client = client
        self.sleep = sleep

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if get_settings().demo_no_network:
            logging.getLogger(__name__).warning("kind=telegram outcome=disabled_demo_no_network")
            return {"ok": False, "description": "Demo network disabled"}
        token = get_settings().telegram_bot_token
        if not token:
            return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is not set"}
        try:
            if self.client is None:
                with httpx.Client(timeout=40) as client:
                    return self._request(client, token, method, payload)
            return self._request(self.client, token, method, payload)
        except (httpx.HTTPError, ValueError, TypeError):
            return {"ok": False, "description": "Telegram transport failed"}

    @staticmethod
    def _request(
        client: httpx.Client, token: str, method: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        configure_logging()
        response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
        data = response.json()
        if not isinstance(data, dict):
            return {"ok": False, "description": "Invalid Telegram response"}
        if not response.is_success and data.get("ok") is True:
            return {"ok": False, "description": "Invalid Telegram response"}
        return data

    def interactive(self, method: str, payload: dict[str, Any]) -> bool:
        return interactive(self, method, payload)


def interactive(api: API, method: str, payload: dict[str, Any]) -> bool:
    result = api.call(method, payload)
    parameters = result.get("parameters")
    delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
    if result.get("error_code") == 429 and type(delay) is int and delay >= 0:
        (api.sleep if isinstance(api, BotAPI) else time.sleep)(delay)
        result = api.call(method, payload)
    return result.get("ok") is True


def set_webhook(api: API) -> int:
    if not secret_ok("TELEGRAM_WEBHOOK_SECRET"):
        print("TELEGRAM_WEBHOOK_SECRET must be set and at least 32 bytes long")
        return 2
    settings = get_settings()
    url = settings.public_base_url + "/telegram/webhook"
    result = api.call(
        "setWebhook",
        {
            "url": url,
            "secret_token": settings.telegram_webhook_secret,
            "allowed_updates": ["message", "callback_query"],
        },
    )
    if result.get("ok") is not True:
        print(result.get("description", "Telegram webhook registration failed"))
        return 2
    print(url)
    return 0
