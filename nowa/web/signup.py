"""Sign-up HTTP adapters; provisioning remains in the deterministic core."""

import hmac
from dataclasses import asdict
from json import JSONDecodeError
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import signup
from nowa.core.clinic_settings import Input
from nowa.messaging.outbox import screen_messages
from nowa.web.doctor_auth import Origin, start_session
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.request import client_ip

router = APIRouter()


class Code(Input):
    mobile: Annotated[str, Field(max_length=100)]
    lang: Literal["ar", "en"] = "ar"


class Verify(Input):
    mobile: Annotated[str, Field(max_length=100)]
    code: SecretStr


class Judge(Input):
    code: SecretStr


def refusal(exc: signup.Refused) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "reason": exc.reason}, status_code=exc.status, headers=PRIVATE_HEADERS
    )


@router.post("/signup/code")
def code(request: Request, body: Code, origin: Origin) -> JSONResponse:
    try:
        result = signup.request_code(
            request.app.state.engine,
            request.app.state.clock,
            request.app.state.agreement,
            body.mobile,
            client_ip(request),
            body.lang,
        )
    except signup.Refused as exc:
        return refusal(exc)
    response = JSONResponse(
        {"ok": True, "telegram_url": result.telegram_url},
        status_code=200 if result.allowed else 429,
        headers=PRIVATE_HEADERS,
    )
    if result.cookie is not None:
        response.set_cookie(
            "nowa_signup",
            result.cookie,
            max_age=2400,
            httponly=True,
            samesite="lax",
            secure=request.url.hostname not in {"127.0.0.1", "localhost"},
            path="/signup",
        )
    return response


@router.post("/signup/verify")
def verify(request: Request, body: Verify, origin: Origin) -> JSONResponse:
    token = signup.verify_code(
        request.app.state.engine, request.app.state.clock, body.mobile, body.code.get_secret_value()
    )
    return JSONResponse(
        {"signup_token": token} if token else {"ok": False, "reason": "refused"},
        status_code=200 if token else 400,
        headers=PRIVATE_HEADERS,
    )


@router.post("/signup/complete")
async def complete(request: Request, origin: Origin) -> JSONResponse:
    try:
        payload = await request.json()
    except JSONDecodeError:
        raise HTTPException(422) from None
    if not isinstance(payload, dict):
        raise HTTPException(422)
    try:
        result = signup.complete(
            request.app.state.engine, request.app.state.clock, request.app.state.agreement, payload
        )
    except signup.Refused as exc:
        return refusal(exc)
    response = JSONResponse(result.data, headers=PRIVATE_HEADERS)
    if result.tokens is not None:
        start_session(response, result.tokens, host=request.url.hostname)
    return response


@router.post("/judge/start")
def judge(request: Request, body: Judge, origin: Origin) -> JSONResponse:
    try:
        token = signup.judge_start(
            request.app.state.engine,
            request.app.state.clock,
            body.code.get_secret_value(),
            client_ip(request),
        )
    except signup.Refused as exc:
        return refusal(exc)
    return JSONResponse(
        {"signup_token": token} if token else {"ok": False, "reason": "refused"},
        status_code=200 if token else 400,
        headers=PRIVATE_HEADERS,
    )


@router.get("/signup/phone")
def phone(request: Request, after_id: Annotated[int, Query(ge=0)] = 0) -> JSONResponse:
    if not get_settings().demo_mode:
        raise HTTPException(404)
    with request.app.state.engine.connect() as conn:
        cid = signup.system_id(conn)
        try:
            parts = signup.unsign(
                request.cookies.get("nowa_signup", ""),
                "signup_phone",
                request.app.state.clock.now(cid, conn=conn).timestamp(),
            )
            if len(parts) != 4:
                raise ValueError
            pid = int(parts[1])
            nonce = conn.execute(
                select(s.pending_signups.c.nonce).where(s.pending_signups.c.id == pid)
            ).scalar_one_or_none()
            if nonce is None or not hmac.compare_digest(nonce, parts[2]):
                raise ValueError
        except (signup.Refused, ValueError):
            raise HTTPException(403) from None
        return JSONResponse(
            jsonable_encoder(
                [
                    dict(asdict(msg), recipient="doctor")
                    for msg in screen_messages(conn, cid, after_id)
                    if msg.pending_signup_id == pid
                ]
            )
        )
