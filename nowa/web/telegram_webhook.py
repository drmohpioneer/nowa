import hmac
from json import JSONDecodeError, loads
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from nowa.config import get_settings, secret_ok

router = APIRouter()
MAX_BODY_BYTES = 64 * 1024


@router.post("/telegram/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    if not secret_ok("TELEGRAM_WEBHOOK_SECRET"):
        raise HTTPException(404)
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied.encode(), get_settings().telegram_webhook_secret.encode()):
        raise HTTPException(401)
    content_length = request.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(422) from None
        if declared_length > MAX_BODY_BYTES:
            raise HTTPException(413)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413)
        body.extend(chunk)
    try:
        value = loads(body)
    except JSONDecodeError:
        raise HTTPException(422) from None
    if not isinstance(value, dict):
        raise HTTPException(422)
    # The synchronous engine and Bot API work must not block the ASGI event loop.
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(request.app.state.telegram_router.handle_update, value)
    return {"ok": True}
