import hmac
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import SecretStr
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import auth
from nowa.core.clinic_settings import Input
from nowa.web.request import client_ip
from nowa.web.tokens import check_origin

router = APIRouter()
GENERIC = {"ok": False, "reason": "refused"}


class Login(Input):
    mobile: str
    password: SecretStr


class ResetRequest(Input):
    mobile: str


class ResetConfirm(ResetRequest):
    code: SecretStr
    new_password: SecretStr


def require_session(request: Request) -> auth.Session:
    session = auth.session_for(
        request.app.state.engine,
        request.app.state.clock,
        request.cookies.get("nowa_session", ""),
        touch=False,
    )
    if session is None:
        # The dashboard sends its public slug only to distinguish deletion from login expiry.
        # It never supplies authorization or a clinic_id.
        slug = request.headers.get("X-Clinic-Slug") or request.query_params.get("clinic")
        with request.app.state.engine.connect() as conn:
            if (
                slug
                and conn.execute(
                    select(s.deleted_slugs.c.slug).where(s.deleted_slugs.c.slug == slug)
                ).first()
            ):
                raise HTTPException(410)
        raise HTTPException(401)
    return session


def require_command(request: Request) -> auth.Session:
    check_origin(request)
    session = require_session(request)
    if not hmac.compare_digest(
        session.csrf_hash, auth.token_hash(request.headers.get("X-CSRF-Token", ""))
    ):
        raise HTTPException(403)
    return session


Session = Annotated[auth.Session, Depends(require_session)]
CommandSession = Annotated[auth.Session, Depends(require_command)]
Origin = Annotated[None, Depends(check_origin)]


def start_session(
    response: Response, tokens: auth.SessionTokens, *, host: str | None = None
) -> None:
    settings = get_settings()
    secure = not (
        settings.demo_mode
        and (host or urlsplit(settings.public_base_url).hostname) in {"localhost", "127.0.0.1"}
    )
    for name, value, httponly in (
        ("nowa_session", tokens.token, True),
        ("nowa_csrf", tokens.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value,
            httponly=httponly,
            secure=secure,
            samesite="lax",
            path="/",
            expires=tokens.expires_at,
        )


@router.post("/d/login")
def login(request: Request, body: Login, origin: Origin) -> JSONResponse:
    result = auth.login(
        request.app.state.engine,
        request.app.state.clock,
        body.mobile,
        body.password.get_secret_value(),
        client_ip(request),
    )
    response = JSONResponse(
        {"ok": True} if result.ok else GENERIC,
        status_code=200 if result.ok else 429 if result.limited else 401,
    )
    if result.tokens is not None:
        start_session(response, result.tokens, host=request.url.hostname)
    return response


@router.post("/d/logout")
def logout(request: Request, session: CommandSession) -> JSONResponse:
    auth.logout(request.app.state.engine, request.app.state.clock, session)
    response = JSONResponse({"ok": True})
    response.delete_cookie("nowa_session", path="/")
    response.delete_cookie("nowa_csrf", path="/")
    return response


@router.post("/d/reset/request")
def reset_request(request: Request, body: ResetRequest, origin: Origin) -> JSONResponse:
    result = auth.request_reset(
        request.app.state.engine, request.app.state.clock, body.mobile, client_ip(request)
    )
    return JSONResponse(
        {"ok": True, "telegram_url": result.telegram_url},
        status_code=200 if result.allowed else 429,
    )


@router.post("/d/reset/confirm")
def reset_confirm(request: Request, body: ResetConfirm, origin: Origin) -> JSONResponse:
    password = body.new_password.get_secret_value()
    if len(password) < 8:
        return JSONResponse({"fields": ["new_password"]}, status_code=422)
    ok = auth.confirm_reset(
        request.app.state.engine,
        request.app.state.clock,
        body.mobile,
        body.code.get_secret_value(),
        password,
    )
    return JSONResponse(
        {"ok": True, "redirect": "/d/login"} if ok else GENERIC, status_code=200 if ok else 400
    )


@router.get("/d/login", response_model=None)
def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    from nowa.web.doctor_pages import render

    return render(request, "login")


@router.get("/d/reset", response_model=None)
def reset_page(request: Request) -> HTMLResponse | RedirectResponse:
    from nowa.web.doctor_pages import render

    return render(request, "reset")
