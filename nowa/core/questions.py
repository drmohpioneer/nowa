from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.core import report
from nowa.core.booking import _open_days, _replay, get_or_create_evening
from nowa.core.text_norm import mask_phones, normalize_question
from nowa.db import conflict_insert
from nowa.messaging.outbox import clinic_lock


@dataclass(frozen=True)
class Asker:
    patient_id: int | None
    booking_id: int | None
    chat_session_id: str


def log_question(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    raw_text: str,
    idempotency_key: str,
    asker: Asker | None = None,
) -> None:
    now = clock.now(clinic_id)
    claimed = conn.execute(
        conflict_insert(conn, s.idempotency_keys)
        .values(
            clinic_id=clinic_id,
            key=f"question:{clinic_id}:{idempotency_key}",
            command="question",
            result_json={},
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=[s.idempotency_keys.c.key])
    ).rowcount
    if not claimed:
        return
    days = _open_days(conn, clock, clinic_id, now.date(), 1)
    if not days:
        return
    evening = get_or_create_evening(conn, clinic_id, days[0])
    # Mask before normalization too: normalization would otherwise restore stored phone digits.
    normalized = normalize_question(mask_phones(raw_text))
    conn.execute(
        conflict_insert(conn, s.questions)
        .values(
            clinic_id=clinic_id,
            evening_id=evening,
            text_norm=normalized,
            text_display=mask_phones(raw_text.strip())[:300],
            count=1,
            status="open",
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[
                s.questions.c.clinic_id,
                s.questions.c.evening_id,
                s.questions.c.text_norm,
            ],
            set_={"count": s.questions.c.count + 1, "status": "open"},
        )
    )

    if asker is not None:
        if (
            asker.patient_id is not None
            and not conn.execute(
                select(s.patients.c.id).where(
                    s.patients.c.id == asker.patient_id, s.patients.c.clinic_id == clinic_id
                )
            ).first()
        ):
            raise ValueError("Asker patient is outside clinic")
        if (
            asker.booking_id is not None
            and not conn.execute(
                select(s.bookings.c.id).where(
                    s.bookings.c.id == asker.booking_id,
                    s.bookings.c.clinic_id == clinic_id,
                    s.bookings.c.patient_id == asker.patient_id,
                )
            ).first()
        ):
            raise ValueError("Asker booking does not match patient")
        question_id: int = conn.execute(
            select(s.questions.c.id).where(
                s.questions.c.clinic_id == clinic_id,
                s.questions.c.evening_id == evening,
                s.questions.c.text_norm == normalized,
            )
        ).scalar_one()
        conn.execute(
            conflict_insert(conn, s.question_askers)
            .values(
                question_id=question_id,
                clinic_id=clinic_id,
                patient_id=asker.patient_id,
                booking_id=asker.booking_id,
                chat_session_id=asker.chat_session_id,
                asked_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    s.question_askers.c.question_id,
                    s.question_askers.c.chat_session_id,
                ],
                set_={"patient_id": asker.patient_id, "booking_id": asker.booking_id},
            )
        )


# All actions run in the caller's write transaction. The clinic lock serializes
# Telegram and dashboard actions, including the single answer window.


@dataclass(frozen=True)
class QuestionResult:
    ok: bool
    reason: str


def act(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    idempotency_key: str,
    command: str,
    text: str | None = None,
    *,
    dashboard: bool = False,
) -> QuestionResult:
    clinic_lock(conn, clinic_id)
    question = (
        conn.execute(
            select(s.questions).where(
                s.questions.c.id == question_id,
                s.questions.c.clinic_id == clinic_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if question is None:
        return QuestionResult(False, "refused")
    key = f"question_action:{clinic_id}:{idempotency_key}"
    verb = f"question_{command}:{question_id}"
    saved = _replay(conn, key, clinic_id, verb)
    if saved is not None:
        return QuestionResult(**saved)
    values: dict[str, Any] = {}
    reason = "already_done"
    if command == "start_answer":
        if question["status"] == "open" or (dashboard and question["status"] == "later"):
            conn.execute(
                s.questions.update()
                .where(
                    s.questions.c.clinic_id == clinic_id,
                    s.questions.c.id != question_id,
                    s.questions.c.answering_at.is_not(None),
                )
                .values(answering_at=None)
            )
            # qedit reopens the text window while retaining the doctor's draft.
            values = dict(status="open", answering_at=clock.now(clinic_id))
            reason = "answer_prompt"
    elif command == "submit_draft":
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
            return QuestionResult(False, "text_only")
        if question["status"] == "open" and question["answering_at"] is not None:
            values = dict(draft_answer=text)
            reason = "draft_ready"
    elif command == "save_for_everyone":
        reason = "stale_save"
        if question["status"] == "open" and question["answering_at"] is not None:
            if question["draft_answer"] is None:
                reason = "no_draft"
            else:
                conn.execute(
                    conflict_insert(conn, s.saved_answers)
                    .values(
                        clinic_id=clinic_id,
                        question_norm=question["text_norm"],
                        answer=question["draft_answer"],
                        saved_at=clock.now(clinic_id),
                    )
                    .on_conflict_do_update(
                        index_elements=["clinic_id", "question_norm"],
                        set_={
                            "answer": question["draft_answer"],
                            "saved_at": clock.now(clinic_id),
                        },
                    )
                )
                values = dict(status="answered", answering_at=None)
                reason = "saved"
    elif command in {"later", "dismiss"}:
        if question["status"] == "open" or (command == "dismiss" and question["status"] == "later"):
            values = dict(status="later" if command == "later" else "dismissed", answering_at=None)
            reason = command
    else:
        raise ValueError("Unknown question action")
    if values:
        conn.execute(
            s.questions.update()
            .where(
                s.questions.c.id == question_id,
                s.questions.c.clinic_id == clinic_id,
            )
            .values(**values)
        )
        record.write_action(conn, clinic_id, "doctor", "question_" + command)
    if command in {"save_for_everyone", "later", "dismiss"} and (
        values or question["status"] != "open"
    ):
        report.resolve_question(conn, clock, clinic_id, question_id)
    result = QuestionResult(bool(values), reason)
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=clinic_id,
            key=key,
            command=verb,
            result_json=asdict(result),
            created_at=clock.now(clinic_id),
        )
    )
    return result


def start_answer(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    idempotency_key: str,
    *,
    dashboard: bool = False,
) -> QuestionResult:
    return act(
        conn, clock, clinic_id, question_id, idempotency_key, "start_answer", dashboard=dashboard
    )


def submit_draft(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    text: str,
    idempotency_key: str,
) -> QuestionResult:
    return act(conn, clock, clinic_id, question_id, idempotency_key, "submit_draft", text)


def save_for_everyone(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    idempotency_key: str,
) -> QuestionResult:
    return act(conn, clock, clinic_id, question_id, idempotency_key, "save_for_everyone")


def later(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    idempotency_key: str,
) -> QuestionResult:
    return act(conn, clock, clinic_id, question_id, idempotency_key, "later")


def dismiss(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    question_id: int,
    idempotency_key: str,
) -> QuestionResult:
    return act(conn, clock, clinic_id, question_id, idempotency_key, "dismiss")
