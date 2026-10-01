from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from nowa import record
from nowa import schema as s
from nowa.core import projection, timing
from nowa.core.timers import TimerContext
from nowa.messaging.outbox import enqueue_message
from nowa.messaging.templates import DoctorNames


def leave_now_check(ctx: TimerContext, payload: dict[str, Any]) -> None:
    timing.recompute(ctx.conn, ctx.clock, int(payload["evening_id"]))


def silent_check(ctx: TimerContext, payload: dict[str, Any]) -> None:
    timing.recompute(ctx.conn, ctx.clock, int(payload["evening_id"]))


def are_you_on_way(ctx: TimerContext, payload: dict[str, Any]) -> None:
    evening = timing._evening(ctx.conn, ctx.clinic_id, int(payload["evening_id"]))
    if evening["state"] != "scheduled":
        return
    hours = projection.paper_hours(ctx.conn, ctx.clinic_id, evening["date"])
    if hours is None or ctx.clock.now(ctx.clinic_id) < hours[0]:
        return
    count = ctx.conn.execute(
        select(func.count())
        .select_from(s.bookings)
        .where(
            s.bookings.c.evening_id == evening["id"],
            s.bookings.c.state.in_(projection.WAITING_STATES),
        )
    ).scalar_one()
    if not count:
        return
    doctor = (
        ctx.conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == ctx.clinic_id))
        .mappings()
        .one()
    )
    enqueue_message(
        ctx.conn,
        ctx.clock,
        ctx.clinic_id,
        "5",
        doctor["lang"],
        "doctor",
        None,
        {
            "doctor_name": DoctorNames(doctor["name_ar"], doctor["name_en"]),
            "clinic_start": hours[0],
            "booked_count": count,
        },
        f"are_you_on_way:{evening['id']}:{int(hours[0].timestamp())}",
    )


def evening_auto_close(ctx: TimerContext, payload: dict[str, Any]) -> None:
    evening = timing._evening(ctx.conn, ctx.clinic_id, int(payload["evening_id"]))
    if evening["state"] != "running":
        return
    due = timing._auto_due(ctx.conn, evening)
    if due is None:
        return
    if ctx.clock.now(ctx.clinic_id) < due:
        timing._arm_auto(ctx.conn, ctx.clock, evening)
        return
    timing.close_evening_in_tx(
        ctx.conn, ctx.clock, ctx.clinic_id, evening["id"], "system", f"auto_close:{evening['id']}"
    )


def evening_system_close(ctx: TimerContext, payload: dict[str, Any]) -> None:
    evening = timing._evening(ctx.conn, ctx.clinic_id, int(payload["evening_id"]))
    if evening["state"] not in {"scheduled", "doctor_on_way"}:
        return
    hours = projection.paper_hours(ctx.conn, ctx.clinic_id, evening["date"])
    if hours is None or ctx.clock.now(ctx.clinic_id) < hours[1] + timedelta(hours=2):
        return
    timing.close_evening_in_tx(
        ctx.conn,
        ctx.clock,
        ctx.clinic_id,
        evening["id"],
        "system",
        f"system_close:{evening['id']}",
        _system_no_taps=True,
    )


def evening_report(ctx: TimerContext, payload: dict[str, Any]) -> None:
    evening = timing._evening(ctx.conn, ctx.clinic_id, int(payload["evening_id"]))
    if evening["state"] != "closed":
        return
    command = "evening_report_placeholder"
    marker = str(evening["id"])
    exists = ctx.conn.execute(
        select(s.action_record.c.id).where(
            s.action_record.c.clinic_id == ctx.clinic_id,
            s.action_record.c.kind == command,
            s.action_record.c.text == marker,
        )
    ).first()
    if exists is None:
        record.write_action(ctx.conn, ctx.clinic_id, "system", command, text=marker)


def travel_check(ctx: TimerContext, payload: dict[str, Any]) -> None:
    from nowa.core.travel_mapbox import handle_travel_check

    handle_travel_check(ctx, payload)
