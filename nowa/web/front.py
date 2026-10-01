from pathlib import Path
from typing import Any

import segno
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.triage.registry import APPROVED_SPECIALTIES
from nowa.web import strings
from nowa.web.doctor_auth import Session
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.templates import environment

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/signup", response_class=HTMLResponse)
def front(request: Request) -> HTMLResponse:
    lang = "en" if request.query_params.get("lang") == "en" else "ar"
    with request.app.state.engine.connect() as conn:
        areas = [dict(row) for row in conn.execute(select(s.areas)).mappings()]
    return HTMLResponse(
        environment.from_string((Path(__file__).parent / "static/front.html").read_text()).render(
            lang=lang,
            t=lambda key: strings.text("signup." + key, lang),
            texts={key: strings.text("signup." + key, lang) for key in strings.SIGNUP_TEXTS},
            areas=areas,
            specialties=sorted(APPROVED_SPECIALTIES),
            agreement=request.app.state.agreement,
            demo=get_settings().demo_mode,
            judge_enabled=bool(get_settings().judge_codes),
            watch_enabled=any(
                getattr(route, "path", "") == "/demo/evening" for route in request.app.routes
            ),
        ),
        headers=PRIVATE_HEADERS,
    )


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
    return {
        "clinic": clinic,
        "doctor": doctor,
        "chat_url": get_settings().public_base_url + "/c/" + clinic["slug"],
    }


@router.get("/d/qr.svg")
def qr(request: Request, session: Session) -> Response:
    url = poster_data(request, session.clinic_id, session.doctor_id)["chat_url"]
    return Response(
        segno.make(url, micro=False).svg_inline(scale=8),
        media_type="image/svg+xml",
        headers=PRIVATE_HEADERS,
    )


@router.get("/d/poster", response_class=HTMLResponse)
def poster(request: Request, session: Session) -> HTMLResponse:
    lang = "en" if request.query_params.get("lang") == "en" else "ar"
    return HTMLResponse(
        environment.get_template("doctor/poster.html").render(
            **poster_data(request, session.clinic_id, session.doctor_id),
            lang=lang,
            t=lambda key: strings.text("signup." + key, lang),
        ),
        headers=PRIVATE_HEADERS,
    )
