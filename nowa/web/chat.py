from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import Field, ValidationError
from sqlalchemy import select

from nowa import schema as s
from nowa.ai import actions
from nowa.ai.cards import faq, ui
from nowa.ai.conversation import handle_turn
from nowa.ai.schema import ChatResponse, HistoryTurn, StrictModel
from nowa.ai.sessions import create_session, load_clinic
from nowa.demo.public import buttons_only, identity
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.request import client_ip
from nowa.web.strings import DEMO_TEXTS, STRINGS
from nowa.web.templates import environment

router = APIRouter(prefix="/c/{slug}")


class SessionRequest(StrictModel):
    session: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TurnRequest(SessionRequest):
    text: str = Field(min_length=1, max_length=1000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)


class TapRequest(SessionRequest):
    action: Literal["book_day", "consent", "area", "lookup", "none"]
    payload: dict[str, Any]


class ConsentRequest(SessionRequest):
    booking_for: Literal["other"]


class LookupRequest(SessionRequest):
    name: str = Field(min_length=1, max_length=60)
    last4: str = Field(pattern=r"^[0-9]{4}$")


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
    with request.app.state.engine.connect() as conn:
        doctor = conn.execute(
            select(s.doctors.c.name_ar).where(s.doctors.c.clinic_id == clinic["id"])
        ).scalar_one()
        buttons = faq(conn, clinic["id"])
        areas = [dict(r) for r in conn.execute(select(s.areas)).mappings()]
    source = (Path(__file__).parent / "static/chat.html").read_text()
    return HTMLResponse(
        environment.from_string(source).render(
            buttons_only=buttons_only(clinic),
            demo_strings={k: v[0] for k, v in DEMO_TEXTS.items()},
            greeting=ui("greeting", "ar", name=doctor),
            doctor_name=doctor,
            config={
                "slug": slug,
                "demo_strings": {k: v[0] for k, v in DEMO_TEXTS.items()},
                "strings": {
                    lang: {
                        key[5:]: texts[lang]
                        for key, texts in STRINGS.items()
                        if key.startswith("chat.")
                    }
                    for lang in ("ar", "en", "franco")
                },
                "faq": [b.model_dump() for b in buttons],
                "areas": areas,
            },
        ),
        headers=PRIVATE_HEADERS,
    )


@router.post("/session")
def new_session(request: Request, slug: str) -> dict[str, str]:
    clinic = clinic_for(request, slug)
    return {
        "session": create_session(request.app.state.engine, request.app.state.clock, clinic["id"])
    }


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
    clinic = clinic_for(request, slug)
    return actions.consent(
        clinic["id"],
        body.session,
        body.idempotency_key,
        engine=request.app.state.engine,
        clock=request.app.state.clock,
    )


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
