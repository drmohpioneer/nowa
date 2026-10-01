from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import record
from nowa import schema as s
from nowa.ai import health
from nowa.ai.adapters import LLMAdapter, default_chain
from nowa.ai.caps import acquire_ai_turn, record_attempts
from nowa.ai.cards import booking_card, emergency, faq, form, response, ui
from nowa.ai.chain import Attempt, ChainResult, run_structured
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
from nowa.core.questions import log_question
from nowa.core.text_norm import mask_phones, normalize_question
from nowa.db import conflict_insert, write_tx
from nowa.messaging.templates import DoctorNames, render_operational


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
    return ChatResponse(reply=text, buttons=buttons, state=result["state"], lang=lang)


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
                supporting_sentence=mask_phones(answer.supporting_sentence, keep=keep),
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
        session = load_session(conn, clinic_id, session_key)
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
            lang=detect(text, session["lang"]),
            last_turn_at=clock.now(clinic_id),
        )
        locked = session["state"] == "locked_emergency"
        allowed = False if locked else acquire_ai_turn(conn, clock, clinic, session, client_ip)
        context = prompt_clinic(conn, clock, clinic) if allowed else None
        saved = saved_answer(conn, clinic_id, text) if allowed else None
    result: ChainResult[TurnOutput] | None = None
    answer: health.Answered | health.NoAnswer | None = None
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
            and candidate.triage == "normal"
            and saved is None
            and candidate.intent not in ("out_of_scope", "question_for_doctor")
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
        session = load_session(conn, clinic_id, session_key)
        keep = public_phones(conn, clinic)
        if result:
            record_attempts(conn, clinic, result.attempts)
            update_session(conn, session, ai_msg_count=session["ai_msg_count"] + 1)
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
                line = render_operational("triage_unclear", session["lang"], {}).text
                if result.model == "fixed":
                    line += "\n" + ui("clinic_phone", session["lang"], phone=clinic["phone"])
                shown, kind, label = response(session, line), "safe", "safe_mode"
            elif candidate.triage == "emergency":
                update_session(
                    conn, session, state="locked_emergency", emergency_kind=candidate.emergency_kind
                )
                shown, kind, label = emergency(session), "emergency", "emergency"
            elif candidate.triage == "unclear":
                shown, label = response(session, candidate.reply), "unclear"
            else:
                label = candidate.triage
                saved = saved_answer(conn, clinic_id, text)
                if candidate.triage == "urgent" and candidate.is_health_question:
                    shown = response(
                        session, render_operational("health_no_answer", session["lang"], {}).text
                    )
                    log_question(conn, clock, clinic_id, text, key)
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
                                "specialty": clinic["specialty"],
                            },
                        ).text,
                    )
                elif candidate.intent == "question_for_doctor" or candidate.is_health_question:
                    if isinstance(answer, health.Answered) and label == "normal":
                        accepted_answer = answer
                        shown = response(
                            session,
                            answer.answer
                            + "\n"
                            + ui("source_label", session["lang"], source_title=answer.source_title)
                            + "\n"
                            + answer.source_url,
                        )
                    else:
                        shown = response(
                            session,
                            render_operational("health_no_answer", session["lang"], {}).text,
                        )
                        log_question(conn, clock, clinic_id, text, key)
                elif candidate.intent == "book":
                    if seq <= session["last_safe_turn_seq"]:
                        shown = response(session, ui("dead_draft", session["lang"]))
                    else:
                        shown, kind = booking_card(
                            conn, clock, clinic, session, session_key, candidate.fields, seq
                        )
                elif candidate.intent == "my_booking":
                    shown, kind = (
                        response(session, ui("lookup", session["lang"]), form(session["lang"])),
                        "form",
                    )
                else:
                    shown = response(session, candidate.reply)
                if label == "urgent":
                    shown.reply = render_operational("triage_urgent", session["lang"], {}).text + (
                        "\n" + shown.reply
                    )
        _health_record(
            conn, clock, clinic_id, session, text, shown, label, model, accepted_answer, keep
        )
        return _finish(conn, clinic, session, key, seq, text, shown, kind, label, model, keep)
