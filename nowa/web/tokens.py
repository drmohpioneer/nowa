import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from nowa.config import get_settings

Purpose = Literal["omw", "form", "standby"]


@dataclass(frozen=True)
class PageToken:
    value: str = field(repr=False)
    exp: int


def _signature(purpose: Purpose, booking_id: int, nonce: bytes, exp: int) -> bytes:
    payload = f"{purpose}|{booking_id}|{nonce.hex()}|{exp}".encode()
    return hmac.new(get_settings().server_secret.encode(), payload, hashlib.sha256).digest()


def issue(purpose: Purpose, booking_id: int, now: datetime) -> PageToken:
    nonce = secrets.token_bytes(16)
    exp = int(now.timestamp()) + (43200 if purpose == "omw" else 1800)
    value = base64.urlsafe_b64encode(nonce + _signature(purpose, booking_id, nonce, exp))
    return PageToken(value.decode().rstrip("="), exp)


def verify(purpose: Purpose, booking_id: int, value: str, exp: str, now: datetime) -> str:
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{64}", value) or not re.fullmatch(r"[0-9]{1,12}", exp):
            raise ValueError
        expiry = int(exp)
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        nonce, signature = raw[:16], raw[16:]
        valid = hmac.compare_digest(signature, _signature(purpose, booking_id, nonce, expiry))
        if not valid or now.timestamp() >= expiry:
            raise ValueError
    except (ValueError, binascii.Error):
        raise HTTPException(403) from None
    return nonce.hex()


def _origin(value: str) -> tuple[str, str | None, int | None]:
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError
    port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
    return url.scheme, url.hostname, port


def check_origin(request: Request) -> None:
    value = request.headers.get("origin")
    if value is None:
        value = request.headers.get("referer")
    try:
        if value is None or _origin(value) != _origin(get_settings().public_base_url):
            raise ValueError
    except ValueError:
        raise HTTPException(403) from None
