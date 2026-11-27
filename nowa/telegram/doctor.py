from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.core import booking, timing
from nowa.core.travel import LatLng
from nowa.db import write_tx
from nowa.telegram import keyboards, linking
from nowa.web.strings import text

if TYPE_CHECKING:
    from nowa.telegram.router import Context


def tonight(conn: Connection, ctx: "Context") -> int | None:
    if ctx.doctor is None:
        return None
    value = booking.tonight_evening(
        conn, ctx.doctor["clinic_id"], ctx.clock.now(ctx.doctor["clinic_id"])
    )
    return value.evening_id if value else None


def authorized(conn: Connection, ctx: "Context", command: keyboards.Callback) -> bool:
    current = linking.identity(conn, ctx.chat_id).doctor
    if current is None or ctx.doctor is None or current["id"] != ctx.doctor["id"]:
        return False
    if command.evening_id is None or tonight(conn, ctx) != command.evening_id:
        return False
    if command.booking_id is not None:
        return (
            conn.execute(
                select(s.bookings.c.id).where(
                    s.bookings.c.id == command.booking_id,
                    s.bookings.c.evening_id == command.evening_id,
                    s.bookings.c.clinic_id == current["clinic_id"],
                )
            ).first()
            is not None
        )
    return True


def show_board(ctx: "Context", *, edit: bool = False, full: bool = False) -> None:
    assert ctx.doctor is not None
    with ctx.engine.connect() as conn:
        eid = tonight(conn, ctx)
        value = timing.tonight_board(conn, ctx.doctor["clinic_id"], eid, ctx.lang) if eid else None
    if value is None or eid is None:
        ctx.send("no_evening", keyboards.doctor_menu(ctx.lang))
        return
    markup = keyboards.board(eid, value, ctx.lang, full=full)
    if edit:
        ctx.edit_text(keyboards.board_text(value, ctx.lang), markup)
    else:
        ctx.send("board", keyboards.doctor_menu(ctx.lang))
        ctx.send_text(keyboards.board_text(value, ctx.lang), markup)


def prompt(ctx: "Context") -> None:
    ctx.send("location_prompt", keyboards.location(ctx.lang))
    areas(ctx)


def areas(ctx: "Context") -> None:
    with ctx.engine.connect() as conn:
        eid = tonight(conn, ctx)
        rows = conn.execute(select(s.areas).order_by(s.areas.c.id)).mappings().all()
    if eid is None:
        ctx.send("no_evening")
        return
    ctx.send(
        "area",
        {
            "inline_keyboard": [
                [
                    {
                        "text": row["name_ar" if ctx.lang == "ar" else "name_en"],
                        "callback_data": keyboards.build("area", eid, arg=str(row["id"])),
                    }
                ]
                for row in rows
            ]
        },
    )


def on_way(
    ctx: "Context",
    origin: LatLng | None,
    area_id: int | None,
    command: keyboards.Callback | None = None,
) -> None:
    assert ctx.doctor is not None
    with ctx.engine.connect() as conn:
        eid = tonight(conn, ctx)
        current = linking.identity(conn, ctx.chat_id).doctor
        valid = (
            current is not None
            and current["id"] == ctx.doctor["id"]
            and eid is not None
            and (command is None or authorized(conn, ctx, command))
        )
        if area_id is not None:
            valid = (
                valid
                and conn.execute(select(s.areas.c.id).where(s.areas.c.id == area_id)).first()
                is not None
            )
        state = conn.execute(select(s.evenings.c.state).where(s.evenings.c.id == eid)).scalar()
        repeated = linking.used_update(conn, ctx.handled_key)
    if not valid or eid is None:
        ctx.send("refused")
        return
    if repeated:
        show_board(ctx, edit=ctx.message_id is not None)
        return
    if state != "scheduled":
        ctx.send("location_ignored")
        return
    result = timing.doctor_on_my_way(
        ctx.engine, ctx.clock, ctx.doctor["clinic_id"], eid, origin, area_id, ctx.key
    )
    with write_tx(ctx.engine) as conn:
        if result.ok and not linking.used_update(conn, ctx.handled_key):
            linking.remember(
                conn, ctx.clock, ctx.doctor["clinic_id"], ctx.handled_key, "telegram_update"
            )
    if result.ok:
        show_board(ctx, edit=ctx.message_id is not None)
    else:
        ctx.send("refused")


def close_confirm(ctx: "Context", eid: int) -> None:
    assert ctx.doctor is not None
    preview = timing.close_preview(ctx.engine, ctx.clock, ctx.doctor["clinic_id"], eid, ctx.lang)
    ctx.edit_text(
        keyboards.close_preview_text(preview, ctx.lang),
        {
            "inline_keyboard": []
            if preview.arrived
            else [
                [
                    keyboards.button(
                        "closeok", "closeok", eid, arg=str(preview.untold_count), lang=ctx.lang
                    )
                ]
            ]
        },
    )


def wind_down_confirm(ctx: "Context", eid: int) -> None:
    assert ctx.doctor is not None
    count = timing.close_preview(ctx.engine, ctx.clock, ctx.doctor["clinic_id"], eid).untold_count
    ctx.edit_text(
        text("tg.wind_down_confirm", ctx.lang).format(count=count),
        {
            "inline_keyboard": [
                [keyboards.button("wind_down", "windok", eid, arg=str(count), lang=ctx.lang)]
            ]
        },
    )


def callback(ctx: "Context", command: keyboards.Callback) -> None:
    with ctx.engine.connect() as conn:
        valid = authorized(conn, ctx, command)
    if not valid:
        ctx.send("refused")
        return
    assert ctx.doctor is not None and command.evening_id is not None
    cid, eid = ctx.doctor["clinic_id"], command.evening_id
    if command.verb == "omw":
        prompt(ctx)
        return
    if command.verb == "area":
        on_way(ctx, None, int(command.arg), command)
        return
    if command.verb == "more":
        show_board(ctx, edit=True, full=True)
        return
    if command.verb == "wind":
        wind_down_confirm(ctx, eid)
        return
    if command.verb == "close":
        close_confirm(ctx, eid)
        return
    if command.verb == "cancel":
        token = timing.request_cancel_tonight(ctx.engine, ctx.clock, cid, eid, ctx.doctor["id"])
        ctx.edit(
            "cancel_confirm",
            {
                "inline_keyboard": [
                    [keyboards.button("cancelok", "cancelok", eid, arg=token, lang=ctx.lang)]
                ]
            },
        )
        return
    with write_tx(ctx.engine) as conn:
        if not authorized(conn, ctx, command):
            result: timing.TapResult | timing.CloseResult | timing.CloseRefused = timing.TapResult(
                False, "unauthorized"
            )
        elif linking.used_update(conn, ctx.handled_key):
            result = timing.TapResult(True)
        else:
            if command.verb in {"in", "walkin"}:
                result = timing.who_comes_in_in_tx(
                    conn, ctx.clock, cid, eid, command.booking_id, command.verb == "walkin", ctx.key
                )
            elif command.verb in {"arrived", "unarrived"}:
                assert command.booking_id is not None
                action = (
                    timing.mark_arrived_in_tx
                    if command.verb == "arrived"
                    else timing.undo_arrived_in_tx
                )
                result = action(conn, ctx.clock, cid, command.booking_id, "doctor", ctx.key)
            elif command.verb in {"pause", "resume"}:
                pause_action = (
                    timing.pause_in_tx if command.verb == "pause" else timing.resume_in_tx
                )
                result = pause_action(conn, ctx.clock, cid, eid, ctx.key)
            elif command.verb == "undo":
                result = timing.undo_last_in_tx(conn, ctx.clock, cid, eid, ctx.key)
            elif command.verb == "windok":
                result = timing.wind_down_in_tx(
                    conn, ctx.clock, cid, eid, ctx.key, int(command.arg)
                )
            elif command.verb == "closeok":
                result = timing.close_evening_in_tx(
                    conn, ctx.clock, cid, eid, "doctor", ctx.key, int(command.arg)
                )
            elif command.verb == "cancelok":
                result = timing.cancel_tonight_in_tx(
                    conn, ctx.clock, cid, eid, ctx.doctor["id"], command.arg, ctx.key
                )
            else:
                result = timing.TapResult(False, "unavailable")
            if result.ok:
                linking.remember(conn, ctx.clock, cid, ctx.handled_key, "telegram_update")
    if isinstance(result, timing.CloseRefused) and result.reason in {
        "count_changed",
        "arrived_present",
    }:
        if command.verb == "windok":
            wind_down_confirm(ctx, eid)
        else:
            close_confirm(ctx, eid)
    elif result.ok:
        show_board(ctx, edit=True)
    else:
        ctx.send("refused")
