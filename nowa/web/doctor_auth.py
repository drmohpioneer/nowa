import hmac
import secrets
from typing import Annotated, Any
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


def session_token(request: Request) -> str:
    if request.url.path.startswith(("/d/report/", "/d/api/report/")):
        demo = request.cookies.get("nowa_demo_report")
        if demo:
            return demo
    # A real doctor session always wins (audit 66); a visitor who only started the demo
    # stage reaches that stage's own board through the board-scoped demo cookie.
    return request.cookies.get("nowa_session", "") or request.cookies.get("nowa_demo_board", "")


def csrf_cookie_name(request: Request) -> str:
    """The readable CSRF cookie that pairs with the session the request resolves to."""
    return "nowa_csrf" if request.cookies.get("nowa_session") else "nowa_demo_csrf"


def require_session(request: Request) -> auth.Session:
    session = auth.session_for(
        request.app.state.engine,
        request.app.state.clock,
        session_token(request),
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
    url = result.telegram_url
    username = get_settings().telegram_bot_username
    if url is None and username:
        # Match a real claim's shape without tracking or granting a credential.
        url = f"https://t.me/{username}?start=r_{secrets.token_urlsafe(32)}"
    response = JSONResponse(
        {"ok": True, "telegram_url": url}, status_code=200 if result.allowed else 429
    )
    if get_settings().demo_mode and not url and result.allowed:
        cookie = auth.demo_reset_cookie(request.app.state.clock, result.demo_token)
        response.set_cookie(
            "nowa_reset",
            cookie,
            httponly=True,
            samesite="lax",
            max_age=600,
            secure=request.url.hostname not in {"127.0.0.1", "localhost"},
            path="/d/reset",
        )
    return response


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
    attempts_left = auth.reset_attempts_left(
        request.app.state.engine, request.app.state.clock, body.mobile
    )
    return JSONResponse(
        {"ok": True, "redirect": "/d/login"}
        if ok
        else {"ok": False, "reason": "wrong_code", "attempts_left": attempts_left},
        status_code=200 if ok else 400,
    )


@router.get("/d/login", response_model=None)
def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    from nowa.web.doctor_pages import render

    return render(request, "login")


@router.get("/d/reset", response_model=None)
def reset_page(request: Request) -> HTMLResponse | RedirectResponse:
    from nowa.web.doctor_pages import render

    return render(request, "reset")


def doctor_language(request: Request, conn: Any, session: auth.Session) -> str:
    explicit = request.query_params.get("lang")
    if explicit in {"ar", "en"}:
        return explicit
    stored = conn.execute(
        select(s.doctors.c.lang).where(
            s.doctors.c.id == session.doctor_id, s.doctors.c.clinic_id == session.clinic_id
        )
    ).scalar_one()
    return "en" if stored == "en" else "ar"


@router.get("/d/reset/phone")
def reset_phone(request: Request) -> JSONResponse:
    from nowa.web.logging import PRIVATE_HEADERS
    from nowa.web.request import page_language
    from nowa.web.strings import text

    if not get_settings().demo_mode:
        raise HTTPException(404)
    try:
        rows = auth.demo_reset_messages(
            request.app.state.engine, request.app.state.clock, request.cookies.get("nowa_reset", "")
        )
    except ValueError:
        raise HTTPException(403) from None
    messages = [
        dict(
            outbox_id=row["id"],
            body=row["body"],
            created_at=row["created_at"].isoformat(),
            status=row["status"],
            recipient=text("demo.doctor", page_language(request)),
        )
        for row in rows
    ]
    return JSONResponse(messages, headers=PRIVATE_HEADERS)
