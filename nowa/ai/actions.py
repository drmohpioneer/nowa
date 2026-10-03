from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import record
from nowa import schema as s
from nowa.ai.cards import (
    BookPayload,
    consent_text,
    day_button,
    emergency,
    response,
    ui,
    valid_draft,
)
from nowa.ai.schema import ChatResponse
from nowa.ai.sessions import keyed, load_clinic, load_session, public_phones, update_session
from nowa.clock import Clock
from nowa.core import booking, flows
from nowa.core.projection import WAITING_STATES
from nowa.core.telegram_tokens import booking_url
from nowa.core.text_norm import mask_phones
from nowa.db import write_tx
from nowa.messaging.templates import format_day, format_time, render_operational
from nowa.web.strings import STRINGS


def tap(
    clinic_id: int,
    session_key: str,
    action: str,
    payload: dict[str, Any],
    idempotency_key: str,
    *,
    engine: Engine,
    clock: Clock,
) -> ChatResponse:
    with write_tx(engine) as conn:
        clinic = load_clinic(conn, clinic_id)
        session = load_session(conn, clinic_id, session_key)
        lang = session["lang"]
        # The FAQ is the explicit exception to the emergency lock (contract item 11).
        if action == "none" and isinstance(payload.get("faq"), str):
            text = conn.execute(
                select(s.clinic_info.c.text).where(
                    s.clinic_info.c.clinic_id == clinic_id,
                    s.clinic_info.c.key == payload["faq"],
                )
            ).scalar_one_or_none()
            if text is None:
                raise HTTPException(404)
            return response(session, text)
        if session["state"] == "locked_emergency":
            return emergency(session)
        if action != "book_day":
            raise HTTPException(422)
        result_key = f"chat_booking:{session['session_key_hash']}:{idempotency_key}"
        saved = conn.execute(
            select(s.idempotency_keys.c.result_json).where(
                s.idempotency_keys.c.key == result_key, s.idempotency_keys.c.clinic_id == clinic_id
            )
        ).scalar_one_or_none()
        if saved is not None:
            return ChatResponse.model_validate(saved)
        data = BookPayload.model_validate(payload)
        if not valid_draft(session_key, data.draft, session, clock):
            return response(session, ui("dead_draft", lang))
        version, text_hash, _ = consent_text(data.draft.booking_for, lang, clinic["slug"])
        if (
            data.consent_version != version
            or data.text_hash != text_hash
            or (
                data.draft.booking_for == "other"
                and (
                    session["consent_other_at"] is None
                    or session["consent_other_at"] < clock.now(clinic_id) - timedelta(minutes=30)
                )
            )
        ):
            return response(session, ui("consent_refused", lang))
        result = flows.book_in_tx(
            conn,
            clock,
            booking.BookingRequest(
                clinic_id,
                data.date,
                data.draft.name,
                data.draft.phone,
                lang,
                data.area_id,
                booking.ConsentInput(version, text_hash, data.draft.booking_for),
                f"chat:{session['session_key_hash']}:{idempotency_key}",
                "patient",
            ),
        )
        if isinstance(result, booking.BookingRefused):
            if result.reason == "phone_cap":
                return response(session, render_operational("phone_cap", lang, {}).text)
            if result.reason == "full" and result.nearest_open_day:
                return response(
                    session,
                    render_operational(
                        "just_filled",
                        lang,
                        {
                            "day": data.date,
                            "next_day": result.nearest_open_day,
                        },
                    ).text,
                    [
                        day_button(
                            result.nearest_open_day,
                            data.draft,
                            version,
                            text_hash,
                            lang,
                            data.area_id,
                        )
                    ],
                )
            return response(session, ui("refused", lang))
        row = (
            conn.execute(
                select(s.bookings).where(
                    s.bookings.c.id == result.booking_id, s.bookings.c.clinic_id == clinic_id
                )
            )
            .mappings()
            .one()
        )
        update_session(
            conn,
            session,
            contact_id=row["contact_id"],
            patient_id=row["patient_id"],
            last_booking_id=result.booking_id,
        )
        evening_date: date = conn.execute(
            select(s.evenings.c.date).where(s.evenings.c.id == row["evening_id"])
        ).scalar_one()
        shown = response(
            session,
            ui(
                "booked",
                lang,
                day=format_day(evening_date, lang),
                number=result.queue_number,
                time=format_time(result.expected_shown, lang),
            ),
        )
        shown.telegram_url = booking_url(conn, clock, result.booking_id)
        shown.booking_confirmed = True
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=clinic_id,
                key=result_key,
                command="chat_booking",
                result_json=shown.model_dump(),
                created_at=clock.now(clinic_id),
            )
        )
        return shown


def consent(
    clinic_id: int,
    session_key: str,
    idempotency_key: str,
    *,
    engine: Engine,
    clock: Clock,
) -> ChatResponse:
    with write_tx(engine) as conn:
        load_clinic(conn, clinic_id)
        session = load_session(conn, clinic_id, session_key)
        if session["state"] == "locked_emergency":
            return emergency(session)
        key = f"chat_consent:{session['session_key_hash']}:{idempotency_key}"
        if not conn.execute(
            select(s.idempotency_keys.c.id).where(s.idempotency_keys.c.key == key)
        ).first():
            update_session(conn, session, consent_other_at=clock.now(clinic_id))
            conn.execute(
                s.idempotency_keys.insert().values(
                    clinic_id=clinic_id,
                    key=key,
                    command="chat_consent",
                    result_json={},
                    created_at=clock.now(clinic_id),
                )
            )
        return response(session, ui("consent_done", session["lang"]))


def _is_locked(conn: Connection, clock: Clock, clinic_id: int, key: str) -> bool:
    now = clock.now(clinic_id)
    times: list[datetime] = list(
        conn.execute(
            select(s.verify_attempts.c.at)
            .where(
                s.verify_attempts.c.clinic_id == clinic_id,
                s.verify_attempts.c.key_hash == key,
                s.verify_attempts.c.at > now - timedelta(minutes=30),
            )
            .order_by(s.verify_attempts.c.at, s.verify_attempts.c.id)
        )
        .scalars()
        .all()
    )
    window: list[datetime] = []
    locked_until = now - timedelta(minutes=30)
    for at in times:
        if at < locked_until:
            continue
        window = [x for x in window if x > at - timedelta(minutes=15)]
        window.append(at)
        if len(window) >= 5:
            locked_until = at + timedelta(minutes=15)
            window = []
    return now < locked_until


def _lookup_status(
    conn: Connection,
    clock: Clock,
    session: dict[str, Any],
    patient_id: int,
    contact_id: int,
) -> ChatResponse:
    rows = (
        conn.execute(
            select(s.bookings, s.evenings.c.date)
            .select_from(s.bookings.join(s.evenings, s.bookings.c.evening_id == s.evenings.c.id))
            .where(
                s.bookings.c.clinic_id == session["clinic_id"],
                s.bookings.c.patient_id == patient_id,
                s.bookings.c.contact_id == contact_id,
                s.bookings.c.state.in_(WAITING_STATES),
                s.evenings.c.date >= clock.now(session["clinic_id"]).date(),
                s.evenings.c.state.in_(("scheduled", "doctor_on_way", "running")),
            )
            .order_by(s.evenings.c.date)
        )
        .mappings()
        .all()
    )
    lang = session["lang"]
    return response(
        session,
        "\n".join(
            ui(
                "status",
                lang,
                day=format_day(row["date"], lang),
                number=row["queue_number"],
                time=format_time(row["expected_shown"], lang),
                status=STRINGS["patient." + row["state"]][lang],
            )
            for row in rows
        )
        if rows
        else ui("lookup_failed", lang),
    )


def lookup(
    clinic_id: int,
    session_key: str,
    name: str,
    last4: str,
    idempotency_key: str,
    *,
    engine: Engine,
    clock: Clock,
    client_ip: str,
) -> ChatResponse:
    with write_tx(engine) as conn:
        clinic = load_clinic(conn, clinic_id)
        session = load_session(conn, clinic_id, session_key)
        if session["state"] == "locked_emergency":
            return emergency(session)
        lang = session["lang"]
        key = f"chat_lookup:{session['session_key_hash']}:{idempotency_key}"
        prior = conn.execute(
            select(s.idempotency_keys.c.result_json).where(s.idempotency_keys.c.key == key)
        ).scalar_one_or_none()
        if prior is not None:
            if "patient_id" in prior:
                return _lookup_status(
                    conn, clock, session, prior["patient_id"], prior["contact_id"]
                )
            return response(session, ui(prior["kind"], lang))
        normalized = booking.normalize_name(name)
        name_key, ip_key = keyed(str(clinic_id) + normalized), keyed(str(clinic_id) + client_ip)
        for lock in sorted({name_key, ip_key}):
            booking._advisory_lock(conn, "chat_verify|" + lock)
        name_locked = _is_locked(conn, clock, clinic_id, name_key)
        ip_locked = _is_locked(conn, clock, clinic_id, ip_key)
        if ip_locked and not clinic["is_sandbox"]:
            record.write_action(conn, clinic_id, "system", "would_have_blocked")
        result: dict[str, Any]
        if name_locked or (ip_locked and clinic["is_sandbox"]):
            result = {"kind": "lookup_locked"}
            shown = response(session, ui("lookup_locked", lang))
        else:
            rows = conn.execute(
                select(s.patients.c.id, s.patients.c.name, s.contacts.c.id.label("contact_id"))
                .select_from(s.bookings.join(s.patients).join(s.contacts).join(s.evenings))
                .where(
                    s.bookings.c.clinic_id == clinic_id,
                    s.bookings.c.state.in_(WAITING_STATES),
                    s.contacts.c.phone_e164.endswith(last4),
                    s.evenings.c.date >= clock.now(clinic_id).date(),
                    s.evenings.c.state.in_(("scheduled", "doctor_on_way", "running")),
                )
            ).all()
            matches = {
                (r.id, r.contact_id) for r in rows if booking.normalize_name(r.name) == normalized
            }
            if len(matches) == 1:
                patient_id, contact_id = matches.pop()
                update_session(conn, session, contact_id=contact_id, patient_id=patient_id)
                result = dict(patient_id=patient_id, contact_id=contact_id)
                shown = _lookup_status(conn, clock, session, patient_id, contact_id)
            else:
                for attempt_key in {name_key, ip_key}:
                    conn.execute(
                        s.verify_attempts.insert().values(
                            clinic_id=clinic_id,
                            key_hash=attempt_key,
                            at=clock.now(clinic_id),
                        )
                    )
                result = {"kind": "lookup_failed"}
                shown = response(session, ui("lookup_failed", lang))
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=clinic_id,
                key=key,
                command="chat_lookup",
                result_json=result,
                created_at=clock.now(clinic_id),
            )
        )
        record.write_action(
            conn,
            clinic_id,
            "patient",
            "chat_lookup",
            text=mask_phones(shown.reply, keep=public_phones(conn, clinic)),
        )
        return shown
