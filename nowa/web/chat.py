from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import select

from nowa import schema as s
from nowa.ai import actions
from nowa.ai.cards import faq, ui
from nowa.ai.conversation import handle_turn
from nowa.ai.schema import ChatResponse, HistoryTurn, StrictModel
from nowa.ai.sessions import create_session, load_clinic
from nowa.config import get_settings
from nowa.core.display import patient_display_name
from nowa.core.text_norm import western_digits
from nowa.demo.evening_script import PATIENTS
from nowa.demo.public import buttons_only, identity
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.request import client_ip, page_language
from nowa.web.strings import DEMO_TEXTS, STRINGS, doctor_label
from nowa.web.templates import environment

router = APIRouter(prefix="/c/{slug}")


class SessionRequest(StrictModel):
    session: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TurnRequest(SessionRequest):
    text: str = Field(min_length=1, max_length=1000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)


class TapRequest(SessionRequest):
    action: Literal["confirm", "set_area", "set_for", "more_days", "book", "lookup", "none"]
    payload: dict[str, Any]


class ConsentRequest(SessionRequest):
    booking_for: Literal["other"]


class LookupRequest(SessionRequest):
    name: str = Field(min_length=1, max_length=60)
    last4: str = Field(pattern=r"^[0-9]{4}$")

    @field_validator("last4", mode="before")
    @classmethod
    def normalize_last4(cls, value: Any) -> Any:
        return western_digits(value) if isinstance(value, str) else value


def clinic_for(request: Request, slug: str) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        if conn.execute(
            select(s.deleted_slugs.c.slug).where(s.deleted_slugs.c.slug == slug)
        ).first():
            raise HTTPException(410)
        clinic_id = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == slug)
        ).scalar_one_or_none()
        if clinic_id is None or slug == "_nowa":
            raise HTTPException(404)
        return load_clinic(conn, clinic_id)


@router.get("", response_class=HTMLResponse)
def page(request: Request, slug: str) -> HTMLResponse:
    clinic = clinic_for(request, slug)
    lang = page_language(request)
    with request.app.state.engine.connect() as conn:
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == clinic["id"]))
            .mappings()
            .one()
        )
        buttons = faq(conn, clinic["id"])
        areas = [
            dict(r)
            for r in conn.execute(
                select(s.areas.c.id, s.areas.c.lat, s.areas.c.lng).order_by(s.areas.c.id)
            ).mappings()
        ]
    source = (Path(__file__).parent / "static/chat.html").read_text()
    return HTMLResponse(
        environment.from_string(source).render(
            buttons_only=buttons_only(clinic),
            drawn_phone=bool(get_settings().demo_mode or clinic["is_sandbox"]),
            lang=lang,
            from_demo=request.query_params.get("from") == "demo",
            demo_strings={k: v[0 if lang == "ar" else 1] for k, v in DEMO_TEXTS.items()},
            greeting=ui("greeting", lang, name=doctor_label(doctor["name_" + lang], lang)),
            doctor_name=doctor_label(doctor["name_" + lang], lang),
            config={
                "fictional_names": [
                    patient_display_name({"name": patient.name, "name_en": patient.name_en}, lang)
                    for patient in PATIENTS[:3]
                ],
                "slug": slug,
                "lang": lang,
                "names": {
                    key: doctor_label(doctor["name_ar" if key == "ar" else "name_en"], key)
                    for key in ("ar", "en", "franco")
                },
                "open_telegram": STRINGS["patient.open_telegram"],
                "demo_strings": {k: v[0 if lang == "ar" else 1] for k, v in DEMO_TEXTS.items()},
                "strings": {
                    lang: {
                        key[5:]: texts[lang]
                        for key, texts in STRINGS.items()
                        if key.startswith("chat.")
                    }
                    for lang in ("ar", "en", "franco")
                },
                "faq": [
                    dict(b.model_dump(), label=ui("faq_" + b.action.payload["faq"], lang))
                    for b in buttons
                ],
                "areas": areas,
            },
        ),
        headers=PRIVATE_HEADERS,
    )


@router.post("/session")
def new_session(request: Request, response: Response, slug: str) -> dict[str, str]:
    clinic = clinic_for(request, slug)
    cookie = "nowa_chat_" + str(clinic["id"])
    key = create_session(
        request.app.state.engine,
        request.app.state.clock,
        clinic["id"],
        previous_key=request.cookies.get(cookie),
        lang="en" if page_language(request) == "en" else "ar",
    )
    # Used solely to clear the old draft on refresh, never to restore identity.
    response.set_cookie(
        cookie,
        key,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path=f"/c/{slug}",
        max_age=86400,
    )
    return {"session": key}


@router.post("/turn")
async def turn(request: Request, slug: str, body: TurnRequest) -> ChatResponse:
    clinic = clinic_for(request, slug)
    if buttons_only(clinic):
        raise HTTPException(403)
    return await handle_turn(
        clinic["id"],
        body.session,
        body.text,
        body.idempotency_key,
        body.history,
        engine=request.app.state.engine,
        clock=request.app.state.clock,
        chain=getattr(request.app.state, "ai_chain", None),
        client_ip=client_ip(request),
    )


@router.post("/tap")
def tap(request: Request, slug: str, body: TapRequest) -> ChatResponse:
    clinic = clinic_for(request, slug)
    if buttons_only(clinic) and body.action == "none" and "identity" in body.payload:
        return identity(
            request.app.state.engine,
            request.app.state.clock,
            clinic["id"],
            body.session,
            body.payload["identity"],
        )
    try:
        return actions.tap(
            clinic["id"],
            body.session,
            body.action,
            body.payload,
            body.idempotency_key,
            engine=request.app.state.engine,
            clock=request.app.state.clock,
        )
    except ValidationError:
        raise HTTPException(422) from None


@router.post("/consent")
def consent(request: Request, slug: str, body: ConsentRequest) -> ChatResponse:
    raise HTTPException(410)


@router.post("/lookup")
def lookup(request: Request, slug: str, body: LookupRequest) -> ChatResponse:
    clinic = clinic_for(request, slug)
    return actions.lookup(
        clinic["id"],
        body.session,
        body.name,
        body.last4,
        body.idempotency_key,
        engine=request.app.state.engine,
        clock=request.app.state.clock,
        client_ip=client_ip(request),
    )
