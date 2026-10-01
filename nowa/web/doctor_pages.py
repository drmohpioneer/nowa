from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from nowa import schema as s
from nowa.core import auth
from nowa.web import strings
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.templates import environment

router = APIRouter()


def render(
    request: Request, mode: str, evening_id: int | None = None
) -> HTMLResponse | RedirectResponse:
    lang = "en" if request.query_params.get("lang") == "en" else "ar"
    clinic = None
    chat_url = None
    paper_start = None
    clinic_now = None
    if mode in {"tonight", "settings", "report"}:
        session = auth.session_for(
            request.app.state.engine,
            request.app.state.clock,
            request.cookies.get("nowa_session", ""),
            touch=False,
        )
        if session is None:
            with request.app.state.engine.connect() as conn:
                slug = request.query_params.get("clinic")
                if (
                    slug
                    and conn.execute(
                        select(s.deleted_slugs.c.slug).where(s.deleted_slugs.c.slug == slug)
                    ).first()
                ):
                    raise HTTPException(410)
            return RedirectResponse("/d/login", status_code=303, headers=PRIVATE_HEADERS)
        with request.app.state.engine.connect() as conn:
            from nowa.config import get_settings
            from nowa.core import booking, projection

            if (
                mode == "report"
                and conn.execute(
                    select(s.evenings.c.id).where(
                        s.evenings.c.id == evening_id,
                        s.evenings.c.clinic_id == session.clinic_id,
                        s.evenings.c.state == "closed",
                    )
                ).first()
                is None
            ):
                raise HTTPException(404)
            clinic = (
                conn.execute(select(s.clinics).where(s.clinics.c.id == session.clinic_id))
                .mappings()
                .one()
            )
            chat_url = get_settings().public_base_url + "/c/" + clinic["slug"]
            clinic_now = request.app.state.clock.now(session.clinic_id, conn=conn)
            tonight = booking.tonight_evening(conn, session.clinic_id, clinic_now)
            if tonight:
                paper = projection.paper_hours(conn, session.clinic_id, tonight.evening_date)
                paper_start = paper[0].isoformat() if paper else None
            lang = conn.execute(
                select(s.doctors.c.lang).where(
                    s.doctors.c.id == session.doctor_id, s.doctors.c.clinic_id == session.clinic_id
                )
            ).scalar_one()
    return HTMLResponse(
        environment.get_template("doctor/page.html").render(
            evening_id=evening_id,
            clinic=clinic,
            chat_url=chat_url,
            clinic_now=clinic_now,
            paper_start=paper_start,
            signup_t=lambda key: strings.text("signup." + key, lang),
            mode=mode,
            lang=lang,
            t=lambda key: strings.text("doctor." + key, lang),
            translations={key: strings.text("doctor." + key, lang) for key in strings.DOCTOR_TEXTS},
        ),
        headers=PRIVATE_HEADERS,
    )


@router.get("/d", response_model=None)
def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    return render(request, "tonight")


@router.get("/d/settings", response_model=None)
def settings(request: Request) -> HTMLResponse | RedirectResponse:
    return render(request, "settings")


@router.get("/d/report/{evening_id}", response_model=None)
def report_page(
    request: Request, evening_id: Annotated[int, Path(gt=0, le=2**63 - 1)]
) -> HTMLResponse | RedirectResponse:
    return render(request, "report", evening_id)
