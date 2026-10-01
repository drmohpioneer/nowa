import logging
import threading
from typing import Any

from pydantic import ValidationError

from nowa.config import get_settings
from nowa.telegram.api import API
from nowa.telegram.router import Router, Update

logger = logging.getLogger(__name__)


def run_forever(router: Router, api: API, *, stop: threading.Event) -> None:
    if get_settings().demo_no_network:
        logger.warning("kind=poller outcome=disabled_demo_no_network")
        return
    result = api.call("deleteWebhook", {"drop_pending_updates": False})
    if result.get("ok") is not True:
        logger.error("kind=poller outcome=delete_webhook_failed")
        return
    offset: int | None = None
    while not stop.is_set():
        payload: dict[str, Any] = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result = api.call("getUpdates", payload)
        updates = result.get("result")
        if result.get("ok") is not True or not isinstance(updates, list):
            logger.warning("kind=poller outcome=poll_failed")
            stop.wait(1)
            continue
        failed = False
        for update in updates:
            if stop.is_set():
                break
            update_id = update.get("update_id") if isinstance(update, dict) else None
            # A malformed numeric ID still identifies the update to acknowledge.
            if isinstance(update_id, str) and update_id.isascii() and update_id.isdecimal():
                if len(update_id) <= 20:
                    update_id = int(update_id)
            if type(update_id) is not int or not isinstance(update, dict):
                logger.warning("kind=poller outcome=invalid_update")
                continue
            try:
                Update.model_validate(update)
            except ValidationError:
                logger.warning(
                    "update_id=%s kind=poller outcome=invalid_update", update_id
                )
                offset = max(offset or 0, update_id + 1)
                continue
            try:
                router.handle_update(update)
            except Exception:
                logger.error("update_id=%s kind=poller outcome=handler_failed", update["update_id"])
                failed = True
                break
            offset = max(offset or 0, update["update_id"] + 1)
        if failed or not updates:
            stop.wait(1)
