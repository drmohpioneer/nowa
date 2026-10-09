"""Public demo pages and authenticated views of each isolated copy."""

import secrets
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import Field
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.sessions import load_session
from nowa.config import get_settings
from nowa.core import auth, booking, signup
from nowa.core.clinic_settings import Input
from nowa.core.display import patient_display_name
from nowa.core.text_norm import greeting_name
from nowa.db import write_tx
from nowa.demo.copy import Busy, create_demo_copy, create_demo_copy_in_tx
from nowa.demo.evening_script import KARIM
from nowa.demo.runner import EveningRunner, stage_start_minute
from nowa.messaging.outbox import ScreenMessage, screen_messages
from nowa.web.chat import clinic_for
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.request import client_ip, page_language
from nowa.web.strings import MESSAGE_LABELS, STRINGS
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


def page(request: Request) -> HTMLResponse:
    from nowa.web.front import public_page
    from nowa.web.strings import UI_TEXTS

    lang = page_language(request)
    return public_page(
        request,
        "evening.html",
        stage_texts={key: value[0 if lang == "ar" else 1] for key, value in UI_TEXTS.items()},
        start_time=f"{16 + stage_start_minute() // 60:02}:{stage_start_minute() % 60:02}",
    )


@router.get("/demo", response_class=HTMLResponse)
def hub(request: Request) -> HTMLResponse:
    from nowa.demo.template import CLINIC
    from nowa.web.front import public_page

    if not get_settings().demo_mode:
        raise HTTPException(404)
    return public_page(
        request,
        "demo.html",
        mobile="0" + CLINIC["doctor"]["mobile_e164"][3:],
        password=get_settings().demo_doctor_password,
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
    runner(request, cid).advance(stage_start_minute())
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)).scalar_one()
    tokens = auth.create_session(engine, clock, cid, did)
    response = JSONResponse({"run_id": run_id, "token": tokens.token}, headers=PRIVATE_HEADERS)
    with engine.connect() as conn:
        eid = conn.execute(
            select(s.evenings.c.id).where(s.evenings.c.clinic_id == cid)
        ).scalar_one()
    secure = request.url.scheme == "https"
    # The board-scoped pair mirrors a login's pair (session + readable CSRF) without touching a real
    # doctor's cookies (audit 66); the board picks the pair through its csrf-cookie meta tag.
    for name, value, path, httponly in (
        ("nowa_demo_session", tokens.token, "/demo/evening", True),
        ("nowa_demo_board", tokens.token, "/d", True),
        ("nowa_demo_csrf", tokens.csrf_token, "/d", False),
    ):
        response.set_cookie(
            name,
            value,
            httponly=httponly,
            secure=secure,
            samesite="lax",
            path=path,
            expires=tokens.expires_at,
        )
    for path in (f"/d/report/{eid}", f"/d/api/report/{eid}"):
        response.set_cookie(
            "nowa_demo_report",
            tokens.token,
            httponly=True,
            secure=secure,
            samesite="lax",
            path=path,
            expires=tokens.expires_at,
        )
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
    lang = page_language(request)
    with request.app.state.engine.connect() as conn:
        messages = []
        for msg in screen_messages(conn, cid, 0):
            phone = STRINGS["demo.doctor"][lang]
            number = 0
            name = (
                conn.execute(
                    select(s.doctors.c.name_en if lang == "en" else s.doctors.c.name_ar).where(
                        s.doctors.c.clinic_id == cid
                    )
                ).scalar_one_or_none()
                or ""
            )
            if msg.booking_id is not None:
                row = conn.execute(
                    select(
                        s.contacts.c.phone_e164,
                        s.bookings.c.queue_number,
                        s.bookings.c.contact_id,
                        s.patients.c.name,
                        s.patients.c.name_en,
                    )
                    .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
                    .outerjoin(s.patients, s.patients.c.id == s.bookings.c.patient_id)
                    .where(s.bookings.c.id == msg.booking_id, s.bookings.c.clinic_id == cid)
                ).first()
                if row is None or (contact_id is not None and row.contact_id != contact_id):
                    continue
                if contact_id is not None and msg.audience != "patient":
                    continue
                phone, number = row.phone_e164, row.queue_number
                if msg.audience == "patient":
                    name = (
                        greeting_name(patient_display_name(row._mapping, lang)) if row.name else ""
                    )
            elif msg.standby_id is not None:
                standby_row = (
                    conn.execute(
                        select(
                            s.contacts.c.phone_e164,
                            s.standbys.c.contact_id,
                            s.patients.c.name,
                            s.patients.c.name_en,
                        )
                        .select_from(s.standbys.join(s.contacts).join(s.patients))
                        .where(
                            s.standbys.c.id == msg.standby_id,
                            s.standbys.c.clinic_id == cid,
                        )
                    )
                    .mappings()
                    .first()
                )
                if standby_row is None or (
                    contact_id is not None and standby_row["contact_id"] != contact_id
                ):
                    continue
                phone = standby_row["phone_e164"]
                name = greeting_name(patient_display_name(standby_row, lang))
            elif contact_id is not None:
                continue
            messages.append(
                dict(
                    dict(
                        asdict(msg),
                        body=stage_body(msg, lang)
                        if request.url.path.startswith("/demo/evening/")
                        else msg.body,
                    ),
                    sent_in_arabic=lang == "en"
                    and msg.lang == "ar"
                    and msg.values_json is not None,
                    recipient=phone,
                    recipient_name=name,
                    channel="telegram",
                    queue_number=number,
                    label=MESSAGE_LABELS.get(msg.template_id),
                )
            )
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
        jsonable_encoder(replay.state(page_language(request)) | {"phones": phones(request, cid)}),
        headers=PRIVATE_HEADERS,
    )


@router.get("/demo/evening/{run_id}/state")
def state(
    request: Request, run_id: str, token: Annotated[str, Query(min_length=1, max_length=128)]
) -> JSONResponse:
    cid = authorized(request, run_id, token)
    return JSONResponse(
        jsonable_encoder(
            runner(request, cid).state(page_language(request)) | {"phones": phones(request, cid)}
        ),
        headers=PRIVATE_HEADERS,
    )


@router.get("/demo/book", response_class=HTMLResponse)
def book_page(request: Request) -> HTMLResponse:
    from nowa.web.front import public_page

    return public_page(request, "book.html")


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
    return RedirectResponse(
        "/c/" + slug + "?from=demo&lang=" + page_language(request),
        status_code=303,
        headers=PRIVATE_HEADERS,
    )


@router.get("/c/{slug}/demo/phone")
def public_phone(
    request: Request, slug: str, session: Annotated[str, Query(min_length=1, max_length=128)]
) -> JSONResponse:
    clinic = clinic_for(request, slug)
    if not (get_settings().demo_mode or clinic["is_sandbox"]):
        raise HTTPException(403)
    with write_tx(request.app.state.engine) as conn:
        chat = load_session(conn, clinic["id"], session, request.app.state.clock)
    result = phones(request, clinic["id"], chat["contact_id"]) if chat["contact_id"] else []
    return JSONResponse(jsonable_encoder(result), headers=PRIVATE_HEADERS)


def stage_body(msg: ScreenMessage, lang: str) -> str:
    from nowa.messaging.templates import render_saved

    if lang == "en" and msg.values_json is not None:
        return render_saved(msg.template_id, lang, msg.values_json)
    return msg.body
