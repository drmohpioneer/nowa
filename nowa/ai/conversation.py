from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from starlette.concurrency import run_in_threadpool

from nowa import record
from nowa import schema as s
from nowa.ai import health
from nowa.ai.adapters import LLMAdapter, default_chain
from nowa.ai.caps import acquire_ai_turn, record_attempts
from nowa.ai.cards import (
    button,
    emergency,
    faq,
    form,
    next_step,
    outside_ack,
    response,
    stored_draft,
    ui,
)
from nowa.ai.chain import Attempt, ChainResult, run_structured
from nowa.ai.drafts import area_candidate, mentioned, merge
from nowa.ai.lang import detect
from nowa.ai.prompt import build_prompt
from nowa.ai.schema import ChatResponse, HistoryTurn, TurnOutput
from nowa.ai.sessions import (
    keyed,
    load_clinic,
    load_session,
    prompt_clinic,
    public_phones,
    update_session,
)
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core.areas import normalize
from nowa.core.geocoding import geocode_origin
from nowa.core.questions import Asker, log_question
from nowa.core.text_norm import mask_phones, normalize_question
from nowa.db import conflict_insert, write_tx
from nowa.library.source_display import source_link
from nowa.messaging.templates import DoctorNames, format_day, format_time, render_operational
from nowa.triage.registry import specialty_label


def requested_stop(text: str) -> bool:
    phrases = (
        "إلغاء",
        "الغي",
        "ألغي",
        "الغاء",
        "مش عايز",
        "خلاص مش",
        "بلاش",
        "cancel",
        "stop",
        "never mind",
        "khalas",
        "balash",
        "la2 mesh 3ayez",
    )
    value = " " + normalize(text) + " "
    return any(" " + normalize(phrase) + " " in value for phrase in phrases)


def requested_change(text: str) -> bool:
    phrases = (
        "اغير اليوم",
        "غير اليوم",
        "تغيير اليوم",
        "اغير المعاد",
        "غير المعاد",
        "change day",
        "change the day",
        "change my day",
        "reschedule",
        "aghayar el yom",
        "aghayyar el yom",
        "ghayar el yom",
    )
    value = " " + normalize(text) + " "
    return any(" " + normalize(phrase) + " " in value for phrase in phrases)


def own_booking(conn: Connection, session: dict[str, Any]) -> ChatResponse | None:
    row = (
        conn.execute(
            select(s.bookings, s.evenings.c.date)
            .join(s.evenings, s.bookings.c.evening_id == s.evenings.c.id)
            .where(
                s.bookings.c.id == session["last_booking_id"],
                s.bookings.c.clinic_id == session["clinic_id"],
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    lang = session["lang"]
    return response(
        session,
        ui(
            "booked",
            lang,
            day=format_day(row["date"], lang),
            number=row["queue_number"],
            time=format_time(row["expected_shown"], lang),
        ),
    )


def saved_answer(conn: Connection, clinic_id: int, text: str) -> str | None:
    value: str | None = conn.execute(
        select(s.saved_answers.c.answer).where(
            s.saved_answers.c.clinic_id == clinic_id,
            s.saved_answers.c.question_norm == normalize_question(text),
        )
    ).scalar_one_or_none()
    return value


def replay(
    conn: Connection,
    clinic_id: int,
    session: dict[str, Any],
    result: dict[str, Any],
) -> ChatResponse:
    if session["state"] == "locked_emergency":
        return emergency(session)
    if not result:
        raise HTTPException(409)
    text: str = conn.execute(
        select(s.action_record.c.text).where(
            s.action_record.c.id == result["chat_out_action_id"],
            s.action_record.c.clinic_id == clinic_id,
        )
    ).scalar_one()
    lang = result["lang"]
    buttons = (
        form(lang)
        if result["kind"] == "form"
        else faq(conn, clinic_id)
        if result["kind"] == "capped"
        else []
    )
    if result["kind"] == "card":
        text += "\n" + ui("draft_replay_reask", lang)
    return ChatResponse(
        reply=text,
        buttons=result.get("buttons", buttons),
        state=result["state"],
        lang=lang,
        source=result.get("source"),
    )


def _finish(
    conn: Connection,
    clinic: dict[str, Any],
    session: dict[str, Any],
    key: str,
    seq: int,
    text: str,
    shown: ChatResponse,
    kind: str,
    label: str,
    model: str,
    keep: Sequence[str],
) -> ChatResponse:
    record.write_action(conn, clinic["id"], "patient", "chat_in", text=mask_phones(text, keep=keep))
    action_id = record.write_action(
        conn,
        clinic["id"],
        "system" if kind in ("safe", "emergency", "capped") else "ai",
        "chat_out:" + label,
        text=mask_phones(shown.reply, keep=keep),
        model=model,
    )
    conn.execute(
        s.idempotency_keys.update()
        .where(s.idempotency_keys.c.key == key)
        .values(
            result_json=dict(
                turn_seq=seq,
                kind=kind,
                label=label,
                state=shown.state,
                lang=shown.lang,
                chat_out_action_id=action_id,
                source=shown.source.model_dump() if shown.source else None,
                buttons=[b.model_dump() for b in shown.buttons] if kind != "card" else [],
            ),
        )
    )
    if label in ("safe_mode", "emergency", "unclear"):
        update_session(conn, session, last_safe_turn_seq=max(session["last_safe_turn_seq"], seq))
    return shown


def _private_reply(conn: Connection, clinic_id: int, session: dict[str, Any], reply: str) -> bool:
    # Candidate text is checked locally; identities are never added to the prompt.
    names = conn.execute(
        select(s.patients.c.id, s.patients.c.name).where(
            s.patients.c.clinic_id == clinic_id,
        )
    ).all()
    phones = conn.execute(
        select(s.contacts.c.id, s.contacts.c.phone_e164).where(
            s.contacts.c.clinic_id == clinic_id,
        )
    ).all()
    normalized = reply.casefold()
    return (
        any(row.id != session["patient_id"] and row.name.casefold() in normalized for row in names)
        or any(
            row.id != session["contact_id"]
            and (row.phone_e164 in reply or row.phone_e164[2:] in reply)
            for row in phones
        )
        or "/l/" in reply
        or "/w/" in reply
    )


def _health_record(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    session: dict[str, Any],
    text: str,
    shown: ChatResponse,
    label: str,
    model: str,
    answer: health.Answered | None,
    keep: Sequence[str],
) -> None:
    phone = conn.execute(
        select(s.contacts.c.phone_e164).where(
            s.contacts.c.id == session["contact_id"],
            s.contacts.c.clinic_id == clinic_id,
        )
    ).scalar_one_or_none()
    if phone is None:
        if answer:
            record.write_action(conn, clinic_id, "ai", "health_answer", model=answer.model)
        return
    values = dict(
        clinic_id=clinic_id,
        at=clock.now(clinic_id),
        phone_key=keyed(phone),
        trigger_text=mask_phones(text, keep=keep),
        reply_text=mask_phones(shown.reply, keep=keep),
        model=model,
        commit=get_settings().render_git_commit,
    )
    if label in ("urgent", "emergency"):
        conn.execute(
            s.health_record.insert().values(
                **values, kind="triage_" + label, template_version="2026-09-28"
            )
        )
    if answer:
        values["model"] = answer.model
        values["reply_text"] = mask_phones(answer.answer, keep=keep)
        conn.execute(
            s.health_record.insert().values(
                **values,
                kind="health_answer",
                template_version=answer.library_version,
                source_url=answer.source_url,
                source_title=mask_phones(answer.source_title, keep=keep),
                supporting_sentence=mask_phones(answer.evidence, keep=keep),
                why=mask_phones(answer.why, keep=keep),
            )
        )


async def handle_turn(
    clinic_id: int,
    session_key: str,
    text: str,
    idempotency_key: str,
    history: Sequence[HistoryTurn],
    *,
    engine: Engine,
    clock: Clock,
    chain: Sequence[LLMAdapter] | None = None,
    client_ip: str = "",
    attempts: list[Attempt] | None = None,
) -> ChatResponse:
    if len(text) > 1000 or len(history) > 10 or not idempotency_key:
        raise HTTPException(422)
    with write_tx(engine) as conn:
        clinic = load_clinic(conn, clinic_id)
        session = load_session(conn, clinic_id, session_key, clock)
        key = f"chat_turn:{session['session_key_hash']}:{idempotency_key}"
        prior = conn.execute(
            select(s.idempotency_keys.c.result_json).where(
                s.idempotency_keys.c.key == key,
                s.idempotency_keys.c.clinic_id == clinic_id,
            )
        ).first()
        if prior:
            return replay(conn, clinic_id, session, prior.result_json)
        claimed = conn.execute(
            conflict_insert(conn, s.idempotency_keys)
            .values(
                clinic_id=clinic_id,
                key=key,
                command="chat_turn",
                result_json={},
                created_at=clock.now(clinic_id),
            )
            .on_conflict_do_nothing(index_elements=[s.idempotency_keys.c.key])
        ).rowcount
        if not claimed:
            raise HTTPException(409)
        seq = session["turn_seq"] + 1
        update_session(
            conn,
            session,
            turn_seq=seq,
            lang=detect(text, session["lang"] if session["turn_seq"] else None),
            last_turn_at=clock.now(clinic_id),
        )
        locked = session["state"] == "locked_emergency"
        allowed = False if locked else acquire_ai_turn(conn, clock, clinic, session, client_ip)
        context = prompt_clinic(conn, clock, clinic, session["lang"]) if allowed else None
        if context is not None:
            context["first_reply"] = seq == 1
        saved = saved_answer(conn, clinic_id, text) if allowed else None
    result: ChainResult[TurnOutput] | None = None
    answer: health.Answered | health.NoAnswer | None = None
    geocoded: tuple[str, int] | None = None
    if allowed:
        assert context is not None
        result = await run_structured(
            build_prompt(context, history, text),
            TurnOutput,
            chain if chain is not None else default_chain(),
        )
        if attempts is not None:
            attempts.extend(result.attempts)
        candidate = result.output
        if (
            candidate
            and not result.safe_mode
            and candidate.triage == "normal"
            and not candidate.is_health_question
            and candidate.intent in ("book", "other")
            and not requested_stop(text)
        ):
            # All provider IO finishes before the next chat write transaction.
            with engine.connect() as conn:
                safe_candidate = not _private_reply(conn, clinic_id, session, candidate.reply)
            origin = area_candidate(session, candidate.fields, text, clock.now(clinic_id).date())
            if safe_candidate and origin is not None and origin[1] is None:
                queries = [normalize(origin[0])]
                # A raw fallback is an origin, never a whole name/phone booking request.
                contains_identity = any(
                    value and mentioned(field, value, text, clock.now(clinic_id).date())
                    for field, value in (
                        ("name", candidate.fields.name), ("phone", candidate.fields.phone)
                    )
                )
                if not contains_identity:
                    queries.append(text)
                area_id = await run_in_threadpool(
                    geocode_origin, engine, clock, clinic, queries, session["lang"]
                )
                if area_id is not None:
                    geocoded = (origin[0], area_id)
        if (
            candidate
            and candidate.triage == "normal"
            and saved is None
            and candidate.intent not in ("out_of_scope", "book")
            and candidate.is_health_question
        ):
            answer = await health.get_health_answerer().answer(
                clinic_id=clinic_id,
                specialty=clinic["specialty"],
                question=text,
                lang=session["lang"],
                session_id=str(session["id"]),
            )
    with write_tx(engine) as conn:
        session = load_session(conn, clinic_id, session_key, clock)
        keep = public_phones(conn, clinic)
        if result:
            record_attempts(conn, clinic, result.attempts)
            update_session(conn, session, ai_msg_count=session["ai_msg_count"] + 1)
            if result.safe_mode or any(a.error for a in result.attempts):
                # The record is how a failed turn is diagnosed later: provider, error, seconds.
                record.write_action(
                    conn,
                    clinic_id,
                    "system",
                    "ai_attempts",
                    text="; ".join(
                        f"{a.model}: {a.error or 'ok'} {a.seconds:.1f}s" for a in result.attempts
                    )
                    or "no attempts",
                    model=result.model,
                )
        if isinstance(answer, health.NoAnswer):
            record.write_action(
                conn,
                clinic_id,
                "system",
                "health_no_answer",
                text=mask_phones(answer.reason, keep=keep),
            )
        if answer:
            for estimate in answer.usage:
                record.record_usage(
                    conn,
                    clinic_id,
                    clinic["judge_id"] if clinic["is_sandbox"] else None,
                    "ai",
                    1,
                    estimate,
                )
        model = result.model if result else "code"
        kind = "reply"
        label = "normal"
        accepted_answer = None
        if session["state"] == "locked_emergency":
            shown, kind, label = emergency(session), "emergency", "emergency"
        elif not allowed:
            shown = response(
                session, ui("capped", session["lang"], phone=clinic["phone"]), faq(conn, clinic_id)
            )
            kind = "capped"
        else:
            assert result is not None
            candidate = result.output
            if (
                result.safe_mode
                or candidate is None
                or (
                    candidate.triage != "emergency"
                    and _private_reply(conn, clinic_id, session, candidate.reply)
                )
            ):
                # a failed extraction re-asks the draft's pending step.
                # Emergency candidates still take the unchanged lock path below.
                draft = stored_draft(session)
                if any(k != "validated" for k in draft):
                    shown = next_step(conn, clock, clinic, session, draft)
                    shown.reply = ui("draft_retry", session["lang"]) + "\n" + shown.reply
                    kind, label = "safe", "safe_draft"
                else:
                    line = render_operational(
                        "chain_fallback", session["lang"], {"clinic_phone": clinic["phone"]}
                    ).text
                    shown, kind, label = response(session, line), "safe", "safe_mode"
            elif candidate.triage == "emergency":
                update_session(
                    conn,
                    session,
                    state="locked_emergency",
                    emergency_kind=candidate.emergency_kind,
                    draft=None,
                )
                shown, kind, label = emergency(session), "emergency", "emergency"
            elif candidate.triage == "unclear":
                if seq == session["turn_seq"]:
                    merge(conn, clock, clinic_id, session, candidate.fields, text)
                shown, label = (
                    response(
                        session,
                        candidate.reply
                        + "\n"
                        + ui(
                            "next_booking" if session["last_booking_id"] else "next_visit",
                            session["lang"],
                        ),
                    ),
                    "unclear",
                )
            else:
                label = candidate.triage
                if seq != session["turn_seq"]:
                    return response(session, ui("dead_draft", session["lang"]))
                # Safety branches above always take precedence over stopping a draft.
                if label == "normal":
                    stop = requested_stop(text)
                    has_booking = session["last_booking_id"] is not None
                    if has_booking and (stop or requested_change(text)):
                        shown = response(
                            session, ui("manage_booking", session["lang"]), form(session["lang"])
                        )
                        return _finish(
                            conn, clinic, session, key, seq, text, shown, "form", label, model, keep
                        )
                    active_draft = any(
                        k in stored_draft(session)
                        for k in (
                            "step",
                            "booking_for",
                            "name",
                            "phone",
                            "day",
                            "area_text",
                        )
                    )
                    if stop and active_draft and not has_booking:
                        update_session(conn, session, draft=None, last_safe_turn_seq=seq)
                        shown = response(
                            session,
                            ui("booking_stopped", session["lang"]),
                            [button("next", ui("visit_chip", session["lang"]), "book")],
                        )
                        return _finish(
                            conn,
                            clinic,
                            session,
                            key,
                            seq,
                            text,
                            shown,
                            "reply",
                            label,
                            model,
                            keep,
                        )
                draft, outside = merge(
                    conn, clock, clinic_id, session, candidate.fields, text, geocoded=geocoded
                )
                saved = saved_answer(conn, clinic_id, text)
                if candidate.triage == "urgent" and candidate.is_health_question:
                    shown = response(
                        session, render_operational("health_no_answer", session["lang"], {}).text
                    )
                    log_question(
                        conn,
                        clock,
                        clinic_id,
                        text,
                        key,
                        Asker(
                            session["patient_id"], session["last_booking_id"], str(session["id"])
                        ),
                    )
                elif candidate.intent == "book" or (
                    candidate.intent == "other"
                    and any(k != "validated" for k in draft)
                    and not candidate.is_health_question
                ):
                    if seq <= session["last_safe_turn_seq"]:
                        shown = response(session, ui("dead_draft", session["lang"]))
                    else:
                        shown = next_step(conn, clock, clinic, session, draft)
                        kind = "card"
                        if outside:
                            shown.reply = outside_ack(draft, session["lang"]) + "\n" + shown.reply
                        if candidate.is_health_question:
                            log_question(
                                conn,
                                clock,
                                clinic_id,
                                text,
                                key,
                                Asker(
                                    session["patient_id"],
                                    session["last_booking_id"],
                                    str(session["id"]),
                                ),
                            )
                            shown.reply = ui("question_noted", session["lang"]) + "\n" + shown.reply
                elif saved is not None:
                    shown = response(session, saved)
                elif candidate.intent == "out_of_scope":
                    assert context is not None
                    shown = response(
                        session,
                        render_operational(
                            "out_of_specialty",
                            session["lang"],
                            {
                                "doctor_name": DoctorNames(
                                    context["doctor_name"]["ar"], context["doctor_name"]["en"]
                                ),
                                "specialty": specialty_label(clinic["specialty"], session["lang"]),
                            },
                        ).text,
                    )
                elif candidate.intent == "question_for_doctor" or candidate.is_health_question:
                    if isinstance(answer, health.Answered) and label == "normal":
                        accepted_answer = answer
                        source = source_link(
                            answer.source_url, answer.source_title, session["lang"]
                        )
                        shown = response(session, answer.answer + "\n" + source.label)
                        shown.source = source
                    else:
                        shown = response(
                            session,
                            render_operational("health_no_answer", session["lang"], {}).text,
                        )
                    log_question(
                        conn,
                        clock,
                        clinic_id,
                        text,
                        key,
                        Asker(
                            session["patient_id"], session["last_booking_id"], str(session["id"])
                        ),
                    )
                elif candidate.intent == "my_booking":
                    known = own_booking(conn, session) if session["last_booking_id"] else None
                    shown = known or response(
                        session, ui("lookup", session["lang"]), form(session["lang"])
                    )
                    kind = "reply" if known else "form"
                else:
                    shown = response(session, candidate.reply)
                    if candidate.intent == "clinic_info" and not session["last_booking_id"]:
                        shown.buttons = [button("next", ui("visit_chip", session["lang"]), "book")]
                if label == "urgent":
                    shown.reply = render_operational("triage_urgent", session["lang"], {}).text + (
                        "\n" + shown.reply
                    )
        if (
            label != "urgent"
            and kind != "emergency"
            and (
                label in ("safe_mode", "unclear")
                or (result and result.output and result.output.intent == "out_of_scope")
                or (
                    result
                    and result.output
                    and kind == "reply"
                    and accepted_answer is None
                    and saved is None
                    and (
                        result.output.is_health_question
                        or result.output.intent == "question_for_doctor"
                    )
                )
            )
        ):
            has_booking = session["last_booking_id"] is not None
            if has_booking and label != "unclear":
                # Replace the booking invitation, retaining the safety/topic sentence.
                shown.reply = (
                    shown.reply.rsplit(". ", 1)[0].rstrip(".")
                    + ". "
                    + ui("next_booking", session["lang"])
                )
            shown.buttons = [
                button(
                    "next",
                    ui("booking_chip" if has_booking else "visit_chip", session["lang"]),
                    "none" if has_booking else "book",
                    **({"lookup": True} if has_booking else {}),
                )
            ]
        _health_record(
            conn, clock, clinic_id, session, text, shown, label, model, accepted_answer, keep
        )
        return _finish(conn, clinic, session, key, seq, text, shown, kind, label, model, keep)
