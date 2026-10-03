import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from nowa.config import get_settings


@dataclass(frozen=True)
class SendResult:
    outcome: Literal["accepted", "refused", "unknown"]
    provider_ref: str | None = None
    error: str | None = None
    retry_after_s: int | None = None


class Adapter(Protocol):
    delivery_reports: bool

    def send(self, outbox_row: Mapping[str, Any]) -> SendResult: ...


class ScreenPhoneAdapter:
    delivery_reports = False

    def send(self, outbox_row: Mapping[str, Any]) -> SendResult:
        return SendResult("accepted")


class TelegramAdapter:
    delivery_reports = False

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def send(self, outbox_row: Mapping[str, Any]) -> SendResult:
        if get_settings().demo_no_network:
            logging.getLogger(__name__).warning("kind=telegram outcome=disabled_demo_no_network")
            return SendResult("refused", error="demo_no_network")
        if not outbox_row.get("chat_id"):
            return SendResult("refused", error="no_telegram_link")
        token = get_settings().telegram_bot_token
        if not token:
            return SendResult("refused", error="not_configured")
        try:
            if self.client is None:
                with httpx.Client(timeout=15) as client:
                    response = self._request(client, token, outbox_row)
            else:
                response = self._request(self.client, token, outbox_row)
            data = response.json()
            if response.status_code == 429 and data.get("ok") is False:
                delay = data.get("parameters", {}).get("retry_after")
                if not isinstance(delay, int) or delay < 0:
                    return SendResult("unknown", error="ambiguous_response")
                return SendResult("refused", error="rate_limited", retry_after_s=delay)
            if response.is_success and data.get("ok") is True:
                message_id = data.get("result", {}).get("message_id")
                return SendResult(
                    "accepted", provider_ref=f"tg:{outbox_row['chat_id']}:{message_id}"
                )
            if data.get("ok") is False and 400 <= response.status_code < 500:
                return SendResult("refused", error="provider_rejected")
            return SendResult("unknown", error="ambiguous_response")
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return SendResult("unknown", error="adapter_exception")

    @staticmethod
    def _request(client: httpx.Client, token: str, row: Mapping[str, Any]) -> httpx.Response:
        from nowa.telegram.api import configure_logging
        from nowa.telegram.keyboards import markup_for

        configure_logging()
        payload: dict[str, Any] = {"chat_id": row["chat_id"], "text": row["body"]}
        markup = markup_for(row)
        if markup is not None:
            payload["reply_markup"] = markup
        return client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
        )


ADAPTERS: dict[str, Adapter] = {
    "screen_phone": ScreenPhoneAdapter(),
    "telegram": TelegramAdapter(),
}
