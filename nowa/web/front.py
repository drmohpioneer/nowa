from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import auth
from nowa.core.display import clinic_address
from nowa.triage.registry import APPROVED_SPECIALTIES
from nowa.web import strings
from nowa.web.doctor_auth import doctor_language, session_token
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.qr import svg_for
from nowa.web.request import page_language, page_link
from nowa.web.templates import environment, markdown_html

router = APIRouter()


def public_page(request: Request, filename: str, **context: Any) -> HTMLResponse:
    lang = page_language(request)
    return HTMLResponse(
        environment.from_string((Path(__file__).parent / "static" / filename).read_text()).render(
            lang=lang,
            current_path=request.url.path,
            page_title=strings.text("ui.page_" + filename.removesuffix(".html"), lang),
            t=lambda key: (
                strings.text("ui." + key, lang)
                if key in strings.UI_TEXTS
                else strings.text("signup." + key, lang)
            ),
            texts={key: strings.text("signup." + key, lang) for key in strings.SIGNUP_TEXTS},
            link=lambda path: page_link(request, path),
            **context,
        ),
        headers=PRIVATE_HEADERS,
    )


@router.get("/", response_class=HTMLResponse)
def front(request: Request) -> HTMLResponse:
    settings = get_settings()
    return public_page(
        request,
        "front.html",
        demo=settings.demo_mode,
        judge=bool(settings.judge_codes),
    )


@router.get("/start", response_class=HTMLResponse)
@router.get("/signup", response_class=HTMLResponse)
def start_page(request: Request) -> HTMLResponse:
    with request.app.state.engine.connect() as conn:
        areas = [dict(row) for row in conn.execute(select(s.areas)).mappings()]
    return public_page(
        request,
        "start.html",
        areas=areas,
        specialties=sorted(APPROVED_SPECIALTIES),
        agreement=request.app.state.agreement,
        agreement_html=markdown_html(request.app.state.agreement.display[page_language(request)]),
        demo=get_settings().demo_mode,
    )


@router.get("/judge", response_class=HTMLResponse)
def judge_page(request: Request) -> HTMLResponse:
    if not get_settings().judge_codes:
        raise HTTPException(404)
    return public_page(request, "judge.html")


def poster_data(request: Request, clinic_id: int, doctor_id: int) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
        doctor = (
            conn.execute(
                select(s.doctors).where(
                    s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id
                )
            )
            .mappings()
            .one()
        )
        session = auth.Session(0, clinic_id, doctor_id, "")
        lang = doctor_language(request, conn, session)
        poster_address = clinic_address(clinic, lang)
        clinic = dict(
            clinic,
            display_name=strings.text("identity.clinic", lang).format(
                name=doctor["name_en" if lang == "en" else "name_ar"]
            ),
        )
    return {
        "lang": lang,
        "clinic": clinic,
        "doctor": doctor,
        "poster_address": poster_address,
        "chat_url": get_settings().public_base_url + "/c/" + clinic["slug"],
    }


@router.get("/d/qr.svg")
def qr(request: Request) -> Response:
    session = poster_session(request)
    if isinstance(session, RedirectResponse):
        return session
    url = poster_data(request, session.clinic_id, session.doctor_id)["chat_url"]
    return Response(
        svg_for(url),
        media_type="image/svg+xml",
        headers=PRIVATE_HEADERS,
    )


@router.get("/d/poster", response_class=HTMLResponse)
def poster(request: Request) -> Response:
    session = poster_session(request)
    if isinstance(session, RedirectResponse):
        return session
    data = poster_data(request, session.clinic_id, session.doctor_id)
    lang = data["lang"]
    return HTMLResponse(
        environment.get_template("doctor/poster.html").render(
            **data,
            t=lambda key: strings.text("signup." + key, lang),
        ),
        headers=PRIVATE_HEADERS,
    )


@router.get("/favicon.ico")
def favicon() -> Response:
    return Response(
        (Path(__file__).parent / "static/favicon.svg").read_text(), media_type="image/svg+xml"
    )


def poster_session(request: Request) -> auth.Session | RedirectResponse:
    session = auth.session_for(
        request.app.state.engine, request.app.state.clock, session_token(request), touch=False
    )
    if session is None:
        return RedirectResponse(
            "/d/login?lang=" + page_language(request) + "&next=" + quote(request.url.path, safe=""),
            status_code=303,
            headers=PRIVATE_HEADERS,
        )
    return session
