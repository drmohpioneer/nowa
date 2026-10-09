from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import auth
from nowa.core.display import clinic_address
from nowa.web import strings
from nowa.web.doctor_auth import csrf_cookie_name, doctor_language, session_token
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
    doctor_name = None
    doctor_day = None
    evening_label = None
    if mode in {"tonight", "settings", "report"}:
        session = auth.session_for(
            request.app.state.engine,
            request.app.state.clock,
            session_token(request),
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
            return RedirectResponse(
                "/d/login?lang=" + lang + "&next=" + quote(request.url.path, safe=""),
                status_code=303,
                headers=PRIVATE_HEADERS,
            )
        with request.app.state.engine.connect() as conn:
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
            if mode == "tonight":
                evening_id = tonight.evening_id if tonight else None
            if tonight:
                paper = projection.paper_hours(conn, session.clinic_id, tonight.evening_date)
                paper_start = paper[0].isoformat() if paper else None
            doctor = (
                conn.execute(
                    select(s.doctors).where(
                        s.doctors.c.id == session.doctor_id,
                        s.doctors.c.clinic_id == session.clinic_id,
                    )
                )
                .mappings()
                .one()
            )
            lang = doctor_language(request, conn, session)
            doctor_name = doctor["name_en"] if lang == "en" else doctor["name_ar"]
            from nowa.messaging.templates import format_day

            chosen_date = tonight.evening_date if tonight else clinic_now.date()
            doctor_day = format_day(chosen_date, lang)
            evening_label = (
                strings.text("doctor.tonight", lang)
                if evening_id is not None and chosen_date == clinic_now.date()
                else doctor_day
                if evening_id is not None
                else strings.text("doctor.no_evening", lang)
            )
            clinic = dict(
                clinic,
                display_address=clinic_address(clinic, lang),
                display_name=strings.text("identity.clinic", lang).format(name=doctor_name),
            )
    return HTMLResponse(
        environment.get_template("doctor/page.html").render(
            evening_id=evening_id,
            doctor_name=doctor_name,
            doctor_day=doctor_day,
            evening_label=evening_label,
            switch_url=request.url.path + ("?lang=ar" if lang == "en" else "?lang=en"),
            clinic=clinic,
            chat_url=chat_url,
            clinic_now=clinic_now,
            paper_start=paper_start,
            telegram_enabled=bool(get_settings().telegram_bot_username),
            csrf_cookie=csrf_cookie_name(request),
            signup_t=lambda key: strings.text("signup." + key, lang),
            mode=mode,
            lang=lang,
            ui_t=lambda key: strings.text("ui." + key, lang),
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
