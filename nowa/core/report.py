"""Read-only evening derivation and transactional report/card delivery."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.clock import CAIRO, Clock
from nowa.core import booking, projection
from nowa.core.timers import TimerContext
from nowa.db import conflict_insert
from nowa.messaging.outbox import clinic_lock, doctor_row, enqueue_message, telegram_chat
from nowa.messaging.templates import render


def display_text(value: str, patient_names: Sequence[str] = ()) -> str:
    # The chat storage policy is unchanged; reports have the stronger display policy.
    for name in sorted(patient_names, key=len, reverse=True):
        parts = name.split()
        if len(parts) > 1:
            pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in parts) + r"(?!\w)"
            value = re.sub(pattern, lambda match: parts[0], value, flags=re.IGNORECASE)
    def mask(match: re.Match[str]) -> str:
        digits = "".join(char for char in match[0] if char.isdecimal())
        return digits[:3] + "*" * (len(digits) - 3)

    return re.sub(r"\d(?:[ \-()]*\d){5,}", mask, value)


@dataclass(frozen=True)
class Report:
    evening_id: int
    day_date: date
    booked: int
    came: int
    walk_ins: int
    no_show_count: int
    no_show_names: list[str]
    doctor_arrival: datetime | None
    clinic_start: datetime
    avg_visit: int | None
    avg_wait: int | None
    failed_names: list[str]
    health_answers: list[dict[str, Any]]
    next_day: date | None
    next_day_bookings: int
    questions: list[dict[str, Any]]

    @property
    def health_q_count(self) -> int:
        return len(self.health_answers)

    def blanks(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("evening_id", "health_answers", "questions"):
            del values[key]
        values["health_q_count"] = self.health_q_count
        for key in ("no_show_names", "failed_names"):
            if values[key]:
                values[key] = ", ".join(values[key])
        return values

    def text(self, lang: str) -> str:
        return render("6", lang, self.blanks())


def _mean(values: list[float]) -> int | None:
    if not values:
        return None
    mean = sum((Decimal(str(value)) for value in values), Decimal(0)) / len(values)
    return int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _patient_names(conn: Connection, clinic_id: int) -> list[str]:
    return list(
        conn.execute(
            select(s.patients.c.name).where(
                s.patients.c.clinic_id == clinic_id,
            )
        ).scalars()
    )


def pending_questions(conn: Connection, clinic_id: int) -> list[dict[str, Any]]:
    names = _patient_names(conn, clinic_id)
    return [
        {
            **{
                key: row[key]
                for key in (
                    "id",
                    "evening_id",
                    "count",
                    "status",
                    "draft_answer",
                    "answering_at",
                    "created_at",
                )
            },
            "text_display": display_text(row["text_display"] or "", names),
        }
        for row in conn.execute(
            select(s.questions)
            .where(
                s.questions.c.clinic_id == clinic_id,
                s.questions.c.status.in_(["open", "later"]),
            )
            .order_by(s.questions.c.count.desc(), s.questions.c.created_at, s.questions.c.id)
        ).mappings()
    ]


def _paper_window(
    conn: Connection, clinic_id: int, evening: Mapping[Any, Any]
) -> tuple[datetime, datetime]:
    if evening["paper_start"] is not None and evening["paper_end"] is not None:
        start = datetime.combine(evening["date"], evening["paper_start"], CAIRO)
        end = datetime.combine(evening["date"], evening["paper_end"], CAIRO)
        if end <= start:
            end += timedelta(days=1)
        return start, end
    hours = projection.paper_hours(conn, clinic_id, evening["date"])
    if hours is None:
        raise ValueError("date has no open paper hours")
    return hours


def build_report(conn: Connection, clock: Clock, clinic_id: int, evening_id: int) -> Report:
    evening = (
        conn.execute(
            select(s.evenings).where(
                s.evenings.c.id == evening_id, s.evenings.c.clinic_id == clinic_id
            )
        )
        .mappings()
        .one()
    )
    paper_start, _ = _paper_window(conn, clinic_id, evening)
    bookings = (
        conn.execute(
            select(s.bookings, s.patients.c.name)
            .outerjoin(
                s.patients,
                (s.patients.c.id == s.bookings.c.patient_id)
                & (s.patients.c.clinic_id == clinic_id),
            )
            .where(s.bookings.c.clinic_id == clinic_id, s.bookings.c.evening_id == evening_id)
            .order_by(s.bookings.c.queue_number)
        )
        .mappings()
        .all()
    )
    visits = (
        conn.execute(
            select(s.visits)
            .where(s.visits.c.clinic_id == clinic_id, s.visits.c.evening_id == evening_id)
            .order_by(s.visits.c.started_at, s.visits.c.id)
        )
        .mappings()
        .all()
    )
    by_booking = {row["id"]: row for row in bookings}
    waits = []
    for visit in visits:
        row = by_booking[visit["booking_id"]]
        if row["on_my_way_at"] is not None and row["travel_min"] is not None:
            arrival = row["on_my_way_at"] + timedelta(minutes=row["travel_min"])
            waits.append(max(0.0, (visit["started_at"] - arrival).total_seconds() / 60))
    lengths = [
        (v["ended_at"] - v["started_at"]).total_seconds() / 60
        for v in visits
        if v["accepted"] and v["ended_at"] is not None
    ]
    messages = (
        conn.execute(
            select(s.outbox)
            .where(
                s.outbox.c.clinic_id == clinic_id,
                s.outbox.c.booking_id.in_(by_booking),
                s.outbox.c.audience == "patient",
            )
            .order_by(s.outbox.c.created_at, s.outbox.c.id)
        )
        .mappings()
        .all()
    )
    keys = {msg["idempotency_key"]: msg for msg in messages}
    latest = {
        msg["booking_id"]: msg for msg in messages if not msg["idempotency_key"].endswith(":tg")
    }
    failed = set()
    for bid, msg in latest.items():
        backup = keys.get(msg["idempotency_key"] + ":tg")
        if msg["status"] == "failed" and not (backup and backup["status"] == "delivered"):
            failed.add(by_booking[bid]["patient_id"])

    def first_name(row: Mapping[Any, Any]) -> str:
        return display_text(row["name"].split()[0]) if row["name"] else ""

    failed_names = []
    seen_patients = set()
    for row in bookings:
        if row["patient_id"] in failed and row["patient_id"] not in seen_patients:
            name = first_name(row)
            if name:
                failed_names.append(name)
            seen_patients.add(row["patient_id"])
    names = _patient_names(conn, clinic_id)
    health = [
        dict(
            question=display_text(row["trigger_text"], names),
            answer=display_text(row["reply_text"], names),
            source_title=display_text(row["source_title"] or "", names),
            source_url=row["source_url"],
            why=display_text(row["why"] or "", names),
            at=row["at"],
            model=row["model"],
        )
        for row in conn.execute(
            select(s.health_record)
            .where(
                s.health_record.c.clinic_id == clinic_id,
                s.health_record.c.kind == "health_answer",
                s.health_record.c.at >= paper_start - timedelta(hours=6),
                s.health_record.c.at <= (evening["closed_at"] or clock.now(clinic_id)),
            )
            .order_by(s.health_record.c.at, s.health_record.c.id)
        ).mappings()
    ]
    # The existing nearest_open_day wrapper opens a new connection; reuse its exact
    # connection-level implementation so capacity checks see the caller's transaction.
    days = booking._open_days(conn, clock, clinic_id, evening["date"] + timedelta(days=1), 1)
    next_day = days[0] if days else None
    next_count = (
        0
        if next_day is None
        else conn.execute(
            select(func.count())
            .select_from(s.bookings)
            .join(s.evenings)
            .where(
                s.bookings.c.clinic_id == clinic_id,
                s.evenings.c.clinic_id == clinic_id,
                s.evenings.c.date == next_day,
                s.bookings.c.state != "cancelled",
            )
        ).scalar_one()
    )
    no_shows = [row for row in bookings if row["state"] == "didnt_come"]
    return Report(
        evening_id,
        evening["date"],
        sum(row["source"] == "chat" and row["state"] != "cancelled" for row in bookings),
        sum(row["state"] == "seen" for row in bookings),
        sum(row["source"] == "walkin_tap" for row in bookings),
        len(no_shows),
        [name for row in no_shows if (name := first_name(row))],
        visits[0]["started_at"] if visits else None,
        paper_start,
        _mean(lengths),
        _mean(waits),
        failed_names,
        health,
        next_day,
        int(next_count),
        pending_questions(conn, clinic_id),
    )


def card_blanks(
    question: Mapping[Any, Any],
    position: int,
    total: int,
    patient_names: Sequence[str] = (),
) -> dict[str, Any]:
    return dict(
        n=position,
        total=total,
        text=display_text(question["text_display"] or "", patient_names),
        count=question["count"],
    )


def _latest_snapshot(conn: Connection, clinic_id: int) -> int | None:
    key = conn.execute(
        select(s.idempotency_keys.c.key)
        .where(
            s.idempotency_keys.c.clinic_id == clinic_id,
            s.idempotency_keys.c.command == "report_snapshot",
        )
        .order_by(s.idempotency_keys.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return None if key is None else int(key.rsplit(":", 1)[1])


def send_next(conn: Connection, clock: Clock, clinic_id: int, evening_id: int) -> None:
    if evening_id != _latest_snapshot(conn, clinic_id):
        return
    doctor = doctor_row(conn, clinic_id)
    linked = telegram_chat(conn, doctor["mobile_e164"], "doctor") is not None
    rows = (
        conn.execute(
            select(s.report_questions)
            .where(
                s.report_questions.c.clinic_id == clinic_id,
                s.report_questions.c.evening_id == evening_id,
                s.report_questions.c.resolved_at.is_(None),
            )
            .order_by(s.report_questions.c.position)
        )
        .mappings()
        .all()
    )
    for row in rows:
        question = (
            conn.execute(
                select(s.questions).where(
                    s.questions.c.id == row["question_id"],
                    s.questions.c.clinic_id == clinic_id,
                )
            )
            .mappings()
            .one()
        )
        if question["status"] != "open":
            conn.execute(
                s.report_questions.update()
                .where(s.report_questions.c.id == row["id"])
                .values(resolved_at=clock.now(clinic_id))
            )
            continue
        if row["sent_at"] is not None or not linked:
            return
        enqueue_message(
            conn,
            clock,
            clinic_id,
            "op:question_card",
            doctor["lang"],
            "doctor",
            None,
            card_blanks(question, row["position"], row["total"], _patient_names(conn, clinic_id)),
            f"report:{evening_id}:q:{question['id']}",
            channel="telegram",
        )
        conn.execute(
            s.report_questions.update()
            .where(s.report_questions.c.id == row["id"])
            .values(sent_at=clock.now(clinic_id))
        )
        return


def resolve_question(conn: Connection, clock: Clock, clinic_id: int, question_id: int) -> None:
    latest = _latest_snapshot(conn, clinic_id)
    if latest is None:
        return
    conn.execute(
        s.report_questions.update()
        .where(
            s.report_questions.c.clinic_id == clinic_id,
            s.report_questions.c.evening_id == latest,
            s.report_questions.c.question_id == question_id,
            s.report_questions.c.resolved_at.is_(None),
        )
        .values(resolved_at=clock.now(clinic_id))
    )
    send_next(conn, clock, clinic_id, latest)


def evening_report(ctx: TimerContext, payload: dict[str, Any]) -> None:
    clinic_lock(ctx.conn, ctx.clinic_id)
    eid = int(payload["evening_id"])
    evening = (
        ctx.conn.execute(
            select(s.evenings).where(
                s.evenings.c.id == eid, s.evenings.c.clinic_id == ctx.clinic_id
            )
        )
        .mappings()
        .one()
    )
    if evening["state"] != "closed":
        return
    key = f"report_snapshot:{eid}"
    # A marker is necessary even for an empty snapshot or an unlinked doctor.
    claimed = ctx.conn.execute(
        conflict_insert(ctx.conn, s.idempotency_keys)
        .values(
            clinic_id=ctx.clinic_id,
            key=key,
            command="report_snapshot",
            result_json={},
            created_at=ctx.clock.now(ctx.clinic_id),
        )
        .on_conflict_do_nothing(index_elements=[s.idempotency_keys.c.key])
    ).rowcount
    if not claimed:
        return
    start, end = _paper_window(ctx.conn, ctx.clinic_id, evening)
    ctx.conn.execute(
        s.evenings.update()
        .where(s.evenings.c.id == eid, s.evenings.c.clinic_id == ctx.clinic_id)
        .values(paper_start=start.time(), paper_end=end.time())
    )
    ctx.conn.execute(
        s.report_questions.update()
        .where(
            s.report_questions.c.clinic_id == ctx.clinic_id,
            s.report_questions.c.evening_id != eid,
            s.report_questions.c.resolved_at.is_(None),
        )
        .values(resolved_at=ctx.clock.now(ctx.clinic_id), resolved_reason="superseded")
    )
    report = build_report(ctx.conn, ctx.clock, ctx.clinic_id, eid)
    for position, question in enumerate(report.questions, 1):
        ctx.conn.execute(
            conflict_insert(ctx.conn, s.report_questions)
            .values(
                clinic_id=ctx.clinic_id,
                evening_id=eid,
                question_id=question["id"],
                position=position,
                total=len(report.questions),
            )
            .on_conflict_do_nothing(index_elements=["evening_id", "question_id"])
        )
        if question["status"] == "later":
            ctx.conn.execute(
                s.questions.update()
                .where(s.questions.c.id == question["id"])
                .values(status="open", answering_at=None)
            )
    doctor = doctor_row(ctx.conn, ctx.clinic_id)
    if telegram_chat(ctx.conn, doctor["mobile_e164"], "doctor") is not None:
        enqueue_message(
            ctx.conn,
            ctx.clock,
            ctx.clinic_id,
            "6",
            doctor["lang"],
            "doctor",
            None,
            report.blanks(),
            f"report:{eid}",
            channel="telegram",
        )
        send_next(ctx.conn, ctx.clock, ctx.clinic_id, eid)
