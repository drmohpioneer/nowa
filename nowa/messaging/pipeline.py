import logging
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from nowa.clock import Clock
from nowa.core.timers import TimerContext, cancel_timer, schedule_timer
from nowa.db import write_tx
from nowa.messaging.adapters import ADAPTERS, SendResult
from nowa.messaging.outbox import (
    alert_failure,
    audit,
    clinic_lock,
    doctor_row,
    enqueue_message,
    recipient,
)
from nowa.record import record_usage
from nowa.schema import action_record, bookings, evenings, outbox, standbys, timers


def _row(conn: Connection, oid: int) -> RowMapping | None:
    return (
        conn.execute(select(outbox).where(outbox.c.id == oid).with_for_update())
        .mappings()
        .one_or_none()
    )


def _failure(conn: Connection, clock: Clock, row: RowMapping, reason: str) -> None:
    conn.execute(
        update(outbox).where(outbox.c.id == row["id"]).values(status="failed", next_attempt_at=None)
    )
    cancel_timer(conn, f"dt:{row['id']}:{row['attempts']}")
    audit(conn, row, "message_failure", reason)
    alert_failure(conn, clock, row)


def send_retry(ctx: TimerContext, payload: dict[str, Any]) -> None:
    clinic_lock(ctx.conn, ctx.clinic_id)
    row = _row(ctx.conn, payload["outbox_id"])
    attempt = payload["attempt"]
    if (
        row is None
        or row["clinic_id"] != ctx.clinic_id
        or row["status"] != "queued"
        or row["attempts"] >= attempt
    ):
        return
    if row["template_id"] == "op:standby_offer":
        offer = (
            ctx.conn.execute(
                select(standbys).where(
                    standbys.c.id == row["standby_id"],
                    standbys.c.clinic_id == ctx.clinic_id,
                )
            )
            .mappings()
            .first()
        )
        if offer is None or offer["state"] != "offered" or offer["expires_at"] <= ctx.now:
            ctx.conn.execute(update(outbox).where(outbox.c.id == row["id"]).values(status="failed"))
            audit(ctx.conn, row, "message_failure", "standby_offer_ended")
            return
    if row["channel"] != "telegram" or row["adapter"] not in ADAPTERS:
        _failure(ctx.conn, ctx.clock, row, "no_channel")
        return
    day = ctx.clock.now(ctx.clinic_id).date()
    start = ctx.clock.now(ctx.clinic_id).replace(hour=0, minute=0, second=0, microsecond=0)
    count = ctx.conn.execute(
        select(func.count())
        .select_from(action_record)
        .where(
            action_record.c.clinic_id == ctx.clinic_id,
            action_record.c.kind == "send_attempt",
            action_record.c.text == row["channel"],
            action_record.c.at >= start,
            action_record.c.at < start + timedelta(days=1),
        )
    ).scalar_one()
    booked = ctx.conn.execute(
        select(func.count())
        .select_from(bookings)
        .join(evenings, evenings.c.id == bookings.c.evening_id)
        .where(
            bookings.c.clinic_id == ctx.clinic_id,
            evenings.c.date == day,
            bookings.c.state != "cancelled",
        )
    ).scalar_one()
    exempt = row["template_id"] == "op:doctor_alert_brake"
    if not exempt and count >= max(30, 3 * booked):
        ctx.conn.execute(
            update(outbox)
            .where(outbox.c.id == row["id"])
            .values(status="blocked_by_brake", next_attempt_at=None)
        )
        audit(ctx.conn, row, "message_brake", row["channel"])
        audit(ctx.conn, row, "message_block", "blocked_by_brake")
        doctor = doctor_row(ctx.conn, ctx.clinic_id)
        label = "تليجرام" if doctor["lang"] == "ar" else "Telegram"
        enqueue_message(
            ctx.conn,
            ctx.clock,
            ctx.clinic_id,
            "op:doctor_alert_brake",
            doctor["lang"],
            "doctor",
            None,
            {"channel_label": label, "count": count},
            f"brake:{ctx.clinic_id}:{row['channel']}:{day}",
        )
        return
    audit(ctx.conn, row, "send_attempt", row["channel"])
    phone, chat = recipient(ctx.conn, row)
    if (
        row["recipient_kind"] == "pending_signup"
        and not phone
        or row["recipient_kind"] in {"patient_contact", "standby_contact", "doctor", "screen"}
        and not phone
    ):
        _failure(ctx.conn, ctx.clock, row, "no_recipient")
        return
    if row["adapter"] == "telegram" and not chat:
        _failure(ctx.conn, ctx.clock, row, "no_telegram_link")
        return
    ctx.conn.execute(
        update(outbox)
        .where(outbox.c.id == row["id"])
        .values(attempts=attempt, next_attempt_at=None)
    )
    schedule_timer(
        ctx.conn,
        ctx.clinic_id,
        "delivery_timeout",
        ctx.now + timedelta(minutes=5),
        {"outbox_id": row["id"], "attempt": attempt},
        f"dt:{row['id']}:{attempt}",
    )
    adapter = ADAPTERS[row["adapter"]]
    dispatch_row = dict(row, attempts=attempt, phone=phone, chat_id=chat)
    engine = ctx.conn.engine

    def dispatch() -> None:
        try:
            result = adapter.send(dispatch_row)
        except Exception:
            result = SendResult("unknown", error="adapter_exception")
        on_send_result(engine, ctx.clock, row["id"], attempt, result)

    ctx.after_commit.append(dispatch)


def on_send_result(
    engine: Engine, clock: Clock, outbox_id: int, attempt: int, result: SendResult
) -> None:
    with write_tx(engine) as conn:
        # Lock the clinic before the row, matching the timer lock order.
        clinic_id = conn.execute(
            select(outbox.c.clinic_id).where(outbox.c.id == outbox_id)
        ).scalar_one_or_none()
        if clinic_id is None:
            return
        clinic_lock(conn, clinic_id)
        row = _row(conn, outbox_id)
        if row is None or row["status"] != "queued" or row["attempts"] != attempt:
            return
        if (
            conn.execute(
                select(timers.c.id).where(
                    timers.c.idempotency_key == f"send:{outbox_id}:{attempt + 1}"
                )
            ).scalar_one_or_none()
            is not None
        ):
            return
        audit(conn, row, "message_result", result.outcome)
        if result.outcome == "accepted":
            reports = ADAPTERS[row["adapter"]].delivery_reports
            conn.execute(
                update(outbox)
                .where(outbox.c.id == outbox_id)
                .values(
                    status="sent" if reports else "delivered",
                    provider_ref=result.provider_ref,
                    next_attempt_at=None,
                )
            )
            if not reports:
                cancel_timer(conn, f"dt:{outbox_id}:{attempt}")
                audit(conn, row, "message_delivery")
            if row["adapter"] == "telegram":
                record_usage(conn, clinic_id, None, "telegram", 1, 0)
        elif result.outcome == "unknown":
            conn.execute(
                update(outbox)
                .where(outbox.c.id == outbox_id)
                .values(status="sent", provider_ref=None, next_attempt_at=None)
            )
        elif result.outcome == "refused":
            conn.execute(
                update(outbox).where(outbox.c.id == outbox_id).values(next_attempt_at=None)
            )
            if attempt >= 3:
                _failure(conn, clock, row, result.error or "refused")
            else:
                delay = max(60 if attempt == 1 else 120, result.retry_after_s or 0)
                timeout_at = conn.execute(
                    select(timers.c.due_at).where(
                        timers.c.idempotency_key == f"dt:{outbox_id}:{attempt}"
                    )
                ).scalar_one()
                if clock.now(clinic_id) + timedelta(seconds=delay) > timeout_at:
                    cancel_timer(conn, f"dt:{outbox_id}:{attempt}")
                schedule_timer(
                    conn,
                    clinic_id,
                    "send_retry",
                    clock.now(clinic_id) + timedelta(seconds=delay),
                    {"outbox_id": outbox_id, "attempt": attempt + 1},
                    f"send:{outbox_id}:{attempt + 1}",
                )
        else:
            raise ValueError("Unknown send outcome")


def delivery_timeout(ctx: TimerContext, payload: dict[str, Any]) -> None:
    clinic_lock(ctx.conn, ctx.clinic_id)
    row = _row(ctx.conn, payload["outbox_id"])
    if (
        row is None
        or row["clinic_id"] != ctx.clinic_id
        or row["status"] not in {"queued", "sent"}
        or row["attempts"] != payload["attempt"]
    ):
        return
    _failure(ctx.conn, ctx.clock, row, "no_delivery")


def on_delivery_report(
    engine: Engine, clock: Clock, provider_ref: str, outcome: Literal["delivered", "failed"]
) -> None:
    if outcome not in {"delivered", "failed"}:
        raise ValueError("Unknown delivery outcome")
    with write_tx(engine) as conn:
        clinic_id = conn.execute(
            select(outbox.c.clinic_id).where(outbox.c.provider_ref == provider_ref)
        ).scalar_one_or_none()
        if clinic_id is None:
            logging.getLogger(__name__).warning("Unknown delivery provider reference")
            return
        clinic_lock(conn, clinic_id)
        row = (
            conn.execute(
                select(outbox).where(outbox.c.provider_ref == provider_ref).with_for_update()
            )
            .mappings()
            .one()
        )
        if row["status"] == "failed":
            note = f"{row['id']}:{outcome}"
            if (
                conn.execute(
                    select(action_record.c.id).where(
                        action_record.c.clinic_id == clinic_id,
                        action_record.c.kind == "delivery_report",
                        action_record.c.text == note,
                    )
                ).first()
                is not None
            ):
                return
            if (
                conn.execute(
                    select(action_record.c.id).where(
                        action_record.c.clinic_id == clinic_id,
                        action_record.c.kind == "delivery_late",
                        action_record.c.text == note,
                    )
                ).first()
                is None
            ):
                audit(conn, row, "delivery_late", note)
        elif row["status"] == "sent":
            if outcome == "failed":
                audit(conn, row, "delivery_report", f"{row['id']}:{outcome}")
                _failure(conn, clock, row, "provider_failed")
            else:
                conn.execute(
                    update(outbox).where(outbox.c.id == row["id"]).values(status="delivered")
                )
                cancel_timer(conn, f"dt:{row['id']}:{row['attempts']}")
                audit(conn, row, "message_delivery")
