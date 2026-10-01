"""Public demo pages and authenticated views of each isolated copy."""

import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import Field
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.sessions import load_session
from nowa.core import auth, booking, signup
from nowa.core.clinic_settings import Input
from nowa.db import write_tx
from nowa.demo.copy import Busy, create_demo_copy, create_demo_copy_in_tx
from nowa.demo.evening_script import KARIM
from nowa.demo.public import buttons_only
from nowa.demo.runner import EveningRunner
from nowa.messaging.outbox import screen_messages
from nowa.web.chat import clinic_for
from nowa.web.doctor_auth import start_session
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.request import client_ip
from nowa.web.strings import DEMO_TEXTS, STRINGS
from nowa.web.templates import environment
from nowa.web.tokens import check_origin

router = APIRouter()


class Start(Input):
    idempotency_key: str = Field(min_length=16, max_length=128)


class Advance(Input):
    to_minute: int = Field(strict=True, ge=0, le=600)
    token: str = Field(min_length=1, max_length=128, repr=False)


def runner(request: Request, cid: int) -> EveningRunner:
    return EveningRunner(cid, engine=request.app.state.engine, clock=request.app.state.clock)


def busy() -> HTMLResponse:
    return HTMLResponse("busy, try again later", status_code=429, headers=PRIVATE_HEADERS)


def page() -> HTMLResponse:
    source = Path(__file__).parent / "static/evening.html"
    return HTMLResponse(
        environment.from_string(source.read_text()).render(
            texts={k: v[0] for k, v in DEMO_TEXTS.items()}
        ),
        headers=PRIVATE_HEADERS,
    )


@router.post("/demo/evening/start", response_model=None)
def start(request: Request, body: Start) -> JSONResponse | HTMLResponse:
    check_origin(request)
    engine, clock = request.app.state.engine, request.app.state.clock
    key = "demo_start:" + body.idempotency_key
    with write_tx(engine) as conn:
        booking._advisory_lock(conn, "clinics")
        saved = conn.execute(
            select(s.idempotency_keys.c.result_json).where(
                s.idempotency_keys.c.key == key, s.idempotency_keys.c.command == "demo_start"
            )
        ).scalar_one_or_none()
        if saved is not None:
            run_id = saved["run_id"]
            cid = conn.execute(
                select(s.demo_runs.c.clinic_id).where(s.demo_runs.c.run_id == run_id)
            ).scalar_one_or_none()
            if cid is None:
                raise HTTPException(410)
        else:
            cid = create_demo_copy_in_tx(conn, clock, "watch", client_ip(request))
            if cid is not None:
                run_id = secrets.token_urlsafe(24)
                now = clock.now(signup.system_id(conn), conn=conn)
                conn.execute(
                    s.demo_runs.insert().values(
                        run_id=run_id,
                        clinic_id=cid,
                        kind="watch",
                        step=0,
                        minute=0,
                        visit_index=0,
                        started_at=now,
                        last_step_at=now,
                    )
                )
                # System-owned intent survives copy eviction, so a replay cannot create again.
                conn.execute(
                    s.idempotency_keys.insert().values(
                        clinic_id=signup.system_id(conn),
                        key=key,
                        command="demo_start",
                        result_json={"run_id": run_id},
                        created_at=now,
                    )
                )
    if cid is None:
        return busy()
    runner(request, cid).start()
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)).scalar_one()
    tokens = auth.create_session(engine, clock, cid, did)
    response = JSONResponse({"run_id": run_id, "token": tokens.token}, headers=PRIVATE_HEADERS)
    start_session(response, tokens, host=request.url.hostname)
    return response


def authorized(request: Request, run_id: str, token: str) -> int:
    session = auth.session_for(
        request.app.state.engine, request.app.state.clock, token, touch=False
    )
    if session is None:
        raise HTTPException(403)
    with request.app.state.engine.connect() as conn:
        cid = conn.execute(
            select(s.demo_runs.c.clinic_id).where(
                s.demo_runs.c.run_id == run_id, s.demo_runs.c.kind == "watch"
            )
        ).scalar_one_or_none()
    if cid != session.clinic_id:
        raise HTTPException(403)
    return session.clinic_id


def phones(request: Request, cid: int, contact_id: int | None = None) -> list[dict[str, Any]]:
    with request.app.state.engine.connect() as conn:
        messages = []
        for msg in screen_messages(conn, cid, 0):
            phone = STRINGS["demo.doctor"]["ar"]
            number = 0
            if msg.booking_id is not None:
                row = conn.execute(
                    select(
                        s.contacts.c.phone_e164, s.bookings.c.queue_number, s.bookings.c.contact_id
                    )
                    .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
                    .where(s.bookings.c.id == msg.booking_id, s.bookings.c.clinic_id == cid)
                ).first()
                if row is None or (contact_id is not None and row.contact_id != contact_id):
                    continue
                phone, number = row.phone_e164, row.queue_number
            elif contact_id is not None:
                continue
            messages.append(dict(asdict(msg), recipient=phone, queue_number=number))
        return sorted(
            messages, key=lambda m: (m["queue_number"] != KARIM, m["queue_number"], m["outbox_id"])
        )


@router.post("/demo/evening/{run_id}/advance")
def advance(request: Request, run_id: str, body: Advance) -> JSONResponse:
    check_origin(request)
    cid = authorized(request, run_id, body.token)
    replay = runner(request, cid)
    replay.advance(body.to_minute)
    return JSONResponse(
        jsonable_encoder(replay.state() | {"phones": phones(request, cid)}), headers=PRIVATE_HEADERS
    )


@router.get("/demo/evening/{run_id}/state")
def state(
    request: Request, run_id: str, token: Annotated[str, Query(min_length=1, max_length=128)]
) -> JSONResponse:
    cid = authorized(request, run_id, token)
    return JSONResponse(
        jsonable_encoder(runner(request, cid).state() | {"phones": phones(request, cid)}),
        headers=PRIVATE_HEADERS,
    )


@router.get("/demo/book", response_class=HTMLResponse)
def book_page() -> HTMLResponse:
    return HTMLResponse(
        environment.from_string(
            '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="stylesheet" href="/static/nowa.css"><main class="page chat">'
            '<div class="topbar"><span class="logo" aria-label="Nowa"><span>n</span>'
            '<i class="o" aria-hidden="true"></i><span>wa</span></span></div>'
            '<section class="card section">'
            "<h1>{{ title }}</h1><p>{{ banner }}</p>"
            '<form action="/demo/book" method="post">'
            '<button class="btn btn-main">{{ start }}</button></form></section>'
            "</main></html>"
        ).render(
            title=STRINGS["demo.public_book"]["ar"],
            banner=STRINGS["demo.banner"]["ar"],
            start=STRINGS["demo.start_booking"]["ar"],
        ),
        headers=PRIVATE_HEADERS,
    )


@router.post("/demo/book", response_model=None)
def book_copy(request: Request) -> RedirectResponse | HTMLResponse:
    check_origin(request)
    try:
        cid = create_demo_copy(
            request.app.state.engine, request.app.state.clock, "public", client_ip(request)
        )
    except Busy:
        return busy()
    with request.app.state.engine.connect() as conn:
        slug = conn.execute(select(s.clinics.c.slug).where(s.clinics.c.id == cid)).scalar_one()
    return RedirectResponse("/c/" + slug, status_code=303, headers=PRIVATE_HEADERS)


@router.get("/c/{slug}/demo/phone")
def public_phone(
    request: Request, slug: str, session: Annotated[str, Query(min_length=1, max_length=128)]
) -> JSONResponse:
    clinic = clinic_for(request, slug)
    if not buttons_only(clinic):
        raise HTTPException(403)
    with request.app.state.engine.connect() as conn:
        chat = load_session(conn, clinic["id"], session)
    result = phones(request, clinic["id"], chat["contact_id"]) if chat["contact_id"] else []
    return JSONResponse(jsonable_encoder(result), headers=PRIVATE_HEADERS)
