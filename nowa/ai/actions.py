from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import record
from nowa import schema as s
from nowa.ai.cards import (
    BookPayload,
    button,
    day_buttons,
    emergency,
    form,
    full_day,
    mark_progress,
    next_step,
    refused_reply,
    response,
    save_draft,
    stored_draft,
    ui,
    valid_draft,
    validated_fields,
)
from nowa.ai.drafts import validate
from nowa.ai.schema import ChatResponse
from nowa.ai.sessions import (
    keyed,
    load_clinic,
    load_session,
    public_phones,
    update_session,
    weekly_hours,
)
from nowa.clock import Clock
from nowa.core import booking, flows
from nowa.core.consent import policy_text
from nowa.core.projection import WAITING_STATES
from nowa.core.telegram_tokens import booking_url
from nowa.core.text_norm import mask_phones, western_digits
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
        session = load_session(conn, clinic_id, session_key, clock)
        lang = session["lang"]
        if session["state"] == "locked_emergency":
            return emergency(session)
        if action == "none" and set(payload) == {"telegram_renew"}:
            from nowa.ai.telegram_link import renew

            return renew(conn, clock, session, payload["telegram_renew"])
        if action == "none" and isinstance(payload.get("faq"), str):
            if payload["faq"] == "hours":
                return response(
                    session, weekly_hours(conn, clinic_id, lang) or ui("no_hours", lang)
                )
            if payload["faq"] == "address":
                from nowa.core.display import clinic_address

                return response(session, clinic_address(clinic, lang))
            text = conn.execute(
                select(s.clinic_info.c.text).where(
                    s.clinic_info.c.clinic_id == clinic_id,
                    s.clinic_info.c.key == payload["faq"],
                )
            ).scalar_one_or_none()
            if text is None:
                raise HTTPException(404)
            return response(session, western_digits(text))
        if action == "none" and payload == {"standby_status": True}:
            from nowa.ai.standby import status

            return status(conn, clock, session)
        if action == "none" and set(payload) == {"standby"}:
            return step_tap(conn, clock, clinic, session, "standby", payload, idempotency_key)
        if action == "lookup" or (action == "none" and payload == {"lookup": True}):
            return response(session, ui("lookup", lang), form(lang))
        if action == "none" and set(payload) == {"edit"}:
            field = payload["edit"]
            if field == "pick":
                return response(
                    session,
                    ui("edit_pick", lang),
                    [
                        button("edit:" + key, ui("edit_" + key, lang), "none", edit=key)
                        for key in ("name", "phone", "day", "area_text")
                    ],
                )
            if field not in ("name", "phone", "day", "area_text"):
                raise HTTPException(422)
            return step_tap(conn, clock, clinic, session, "edit", payload, idempotency_key)
        if action in ("book", "set_for", "set_area", "more_days"):
            return step_tap(conn, clock, clinic, session, action, payload, idempotency_key)
        if action != "confirm":
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
            # Only a genuine expired signature may be refreshed; tampering and
            # safety-invalidated drafts must not acquire a new usable signature.
            import hmac

            from nowa.ai.cards import signature

            if (
                hmac.compare_digest(signature(session_key, data.draft), data.draft.sig)
                and data.draft.exp <= clock.now(clinic_id).timestamp()
                and session["last_safe_turn_seq"] < data.draft.turn_seq == session["turn_seq"]
                and session["draft"]
            ):
                draft = stored_draft(session)
                validate(conn, clock, clinic_id, draft)
                save_draft(conn, session, draft)
                shown = step_response(conn, clock, clinic, session, draft)
                shown.reply = ui("draft_expired", lang) + "\n" + shown.reply
                return shown
            return response(session, ui("dead_draft", lang))
        if data.draft.standby:
            from nowa.ai.standby import confirm

            return confirm(conn, clock, session, data.draft)
        version, text_hash, _ = policy_text(lang)
        result = flows.book_in_tx(
            conn,
            clock,
            booking.BookingRequest(
                clinic_id,
                data.draft.day,
                fictional_name_ar(clinic, data.draft.phone) or data.draft.name,
                data.draft.phone,
                lang,
                data.draft.area_id,
                booking.ConsentInput(version, text_hash, data.draft.booking_for),
                f"chat:{session['session_key_hash']}:{idempotency_key}",
                "patient",
                patient_name_en=fictional_name_en(clinic, data.draft.phone),
                origin_text=data.draft.origin_text,
            ),
        )
        if isinstance(result, booking.BookingRefused):
            if result.reason == "phone_cap":
                return response(session, render_operational("phone_cap", lang, {}).text)
            if result.reason == "full":
                return full_day(conn, clock, session, data.draft.day)
            return refused_reply(conn, clock, session, result.reason)
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
            draft=None,
            consent_other_at=clock.now(clinic_id) if data.draft.booking_for == "other" else None,
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


def step_tap(
    conn: Connection,
    clock: Clock,
    clinic: dict[str, Any],
    session: dict[str, Any],
    action: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> ChatResponse:
    key = f"chat_step:{session['session_key_hash']}:{idempotency_key}"
    prior = conn.execute(
        select(s.idempotency_keys.c.id).where(s.idempotency_keys.c.key == key)
    ).first()
    if prior:
        if action == "more_days":
            return response(
                session,
                ui("more_days_reply", session["lang"]),
                day_buttons(conn, clock, clinic["id"], session["lang"], more=True),
            )
        return step_response(conn, clock, clinic, session, stored_draft(session))
    # The rules permit an explicit new booking start after an unclear turn.
    # Previously issued confirm signatures remain invalidated by last_safe_turn_seq.
    if (
        session["turn_seq"]
        and session["turn_seq"] <= session["last_safe_turn_seq"]
        and not (action == "book" and not payload)
    ):
        return response(session, ui("dead_draft", session["lang"]))
    if action == "more_days":
        if payload:
            raise HTTPException(422)
        # Expanding the choices is a view action, not draft validation or progress.
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=clinic["id"],
                key=key,
                command="chat_step",
                result_json={},
                created_at=clock.now(clinic["id"]),
            )
        )
        return response(
            session,
            ui("more_days_reply", session["lang"]),
            day_buttons(conn, clock, clinic["id"], session["lang"], more=True),
        )
    draft = stored_draft(session)
    if action == "book" and (draft.get("standby_result") or draft.get("awaiting_telegram")):
        draft = {"validated": []}
    before = validated_fields(draft)
    if action in ("book", "edit"):
        draft.pop("standby", None)
    if action == "standby":
        try:
            day = date.fromisoformat(payload["standby"])
        except (TypeError, ValueError):
            raise HTTPException(422) from None
        if booking._day_status(conn, clinic["id"], day, clock.now(clinic["id"]))[0] not in (
            None,
            "full",
        ):
            return response(session, ui("refused", session["lang"]))
        draft.update(day=day.isoformat(), standby=True)

    if action == "edit":
        field = payload["edit"]
        draft.pop(field, None)
        draft["validated"] = [key for key in draft.get("validated", []) if key != field]
        if field == "area_text":
            draft.pop("area_id", None)
            draft.pop("area_attempts", None)
    elif action == "set_for":
        if payload.get("booking_for") not in ("self", "other") or set(payload) != {"booking_for"}:
            raise HTTPException(422)
        draft["booking_for"] = payload["booking_for"]
    elif action == "set_area":
        if set(payload) != {"area_id"}:
            raise HTTPException(422)
        area_id = payload["area_id"]
        area = (
            conn.execute(select(s.areas).where(s.areas.c.id == area_id)).mappings().first()
            if type(area_id) is int
            else None
        )
        if area_id is not None and area is None:
            raise HTTPException(422)
        draft["area_id"] = area_id
        draft["area_text"] = (
            area["name_ar" if session["lang"] == "ar" else "name_en"] if area else ""
        )
        draft["validated"] = sorted(set(draft.get("validated", [])) | {"area_text"})
    elif action == "book":
        if payload:
            if set(payload) != {"date"} or not isinstance(payload["date"], str):
                raise HTTPException(422)
            try:
                draft["day"] = date.fromisoformat(payload["date"]).isoformat()
            except ValueError:
                raise HTTPException(422) from None
    elif payload and action != "standby":
        raise HTTPException(422)
    validate(conn, clock, clinic["id"], draft)
    update_session(
        conn, session, turn_seq=session["turn_seq"] + 1, last_turn_at=clock.now(clinic["id"])
    )
    mark_progress(draft, before, session["turn_seq"])
    save_draft(conn, session, draft)
    # Store no response/payload: those contain a signed identity draft.
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=clinic["id"],
            key=key,
            command="chat_step",
            result_json={},
            created_at=clock.now(clinic["id"]),
        )
    )
    return step_response(conn, clock, clinic, session, draft)


def step_response(
    conn: Connection,
    clock: Clock,
    clinic: dict[str, Any],
    session: dict[str, Any],
    draft: dict[str, Any],
) -> ChatResponse:
    shown = next_step(conn, clock, clinic, session, draft)
    if clinic["is_sandbox"] and clinic["judge_id"] is None:
        from nowa.demo.public import public_areas

        shown = public_areas(conn, session, draft, shown)
    return shown


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
        session = load_session(conn, clinic_id, session_key, clock)
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
            return response(
                session,
                ui(prior["kind"], lang),
                form(lang) if prior["kind"] == "lookup_failed" else [],
            )
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
                select(
                    s.patients.c.id,
                    s.patients.c.name,
                    s.patients.c.name_en,
                    s.contacts.c.id.label("contact_id"),
                )
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
                (r.id, r.contact_id)
                for r in rows
                if normalized
                in {booking.normalize_name(r.name), booking.normalize_name(r.name_en or r.name)}
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
                shown = response(session, ui("lookup_failed", lang), form(lang))
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


def fictional_name_en(clinic: dict[str, Any], phone: str) -> str | None:
    from nowa.demo.evening_script import PATIENTS
    from nowa.demo.public import buttons_only

    if not buttons_only(clinic):
        return None
    return next(
        (
            patient.name_en
            for patient in PATIENTS
            if patient.phone == booking.normalize_phone(phone)
        ),
        None,
    )


def fictional_name_ar(clinic: dict[str, Any], phone: str) -> str | None:
    from nowa.demo.evening_script import PATIENTS
    from nowa.demo.public import buttons_only

    if not buttons_only(clinic):
        return None
    return next(
        (patient.name for patient in PATIENTS if patient.phone == booking.normalize_phone(phone)),
        None,
    )
