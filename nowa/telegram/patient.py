from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.engine import Connection, RowMapping

from nowa import schema as s
from nowa.clock import Clock
from nowa.core import projection, timing
from nowa.db import write_tx
from nowa.messaging.templates import format_day, format_time
from nowa.telegram import keyboards, linking
from nowa.web.strings import text

if TYPE_CHECKING:
    from nowa.telegram.router import Context


def bookings(conn: Connection, clock: Clock, phones: tuple[str, ...]) -> list[RowMapping]:
    rows = (
        conn.execute(
            select(
                s.bookings,
                s.patients.c.name.label("patient_name"),
                s.doctors.c.name_ar,
                s.doctors.c.name_en,
                s.evenings.c.date,
            )
            .join(s.contacts, s.contacts.c.id == s.bookings.c.contact_id)
            .join(s.patients, s.patients.c.id == s.bookings.c.patient_id)
            .join(s.doctors, s.doctors.c.clinic_id == s.bookings.c.clinic_id)
            .join(s.evenings, s.evenings.c.id == s.bookings.c.evening_id)
            .where(
                s.contacts.c.phone_e164.in_(phones),
                s.bookings.c.state.in_(("booked", "told_to_leave", "on_my_way")),
                s.evenings.c.state.not_in(("closed", "cancelled")),
            )
            .order_by(s.evenings.c.date, s.bookings.c.id)
        )
        .mappings()
        .all()
    )
    result = []
    for row in rows:
        hours = projection.paper_hours(conn, row["clinic_id"], row["date"])
        if hours is not None and hours[1] > clock.now(row["clinic_id"]):
            result.append(row)
    return result


def own(conn: Connection, chat_id: str, booking_id: int) -> RowMapping | None:
    return (
        conn.execute(
            select(s.bookings)
            .join(s.contacts, s.contacts.c.id == s.bookings.c.contact_id)
            .join(s.telegram_links, s.telegram_links.c.phone_e164 == s.contacts.c.phone_e164)
            .where(
                s.bookings.c.id == booking_id,
                s.telegram_links.c.kind == "patient",
                s.telegram_links.c.telegram_chat_id == chat_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def menu(ctx: "Context") -> None:
    with ctx.engine.connect() as conn:
        links = linking.identity(conn, ctx.chat_id)
        rows = bookings(conn, ctx.clock, links.patient_phones)
    if rows:
        if ctx.doctor is None:
            ctx.clinic_id = rows[0]["clinic_id"]
        markup = (
            {"inline_keyboard": [[keyboards.button("unlink", "unlink", lang=ctx.lang)]]}
            if ctx.doctor is not None
            else keyboards.patient_menu(ctx.lang)
        )
        ctx.send("menu", markup)
        for row in rows:
            if ctx.doctor is None:
                ctx.clinic_id = row["clinic_id"]
            lang = row["lang"]
            ctx.send_text(
                text("tg.booking", lang).format(
                    patient=row["patient_name"].split()[0],
                    doctor=row["name_ar" if lang == "ar" else "name_en"],
                    day=format_day(row["date"], lang),
                    number=row["queue_number"],
                    time=format_time(row["expected_shown"], lang),
                ),
                keyboards.patient_booking(row["id"], row["state"], lang),
            )
    else:
        ctx.send(
            "no_bookings",
            keyboards.doctor_menu(ctx.lang)
            if ctx.doctor is not None
            else keyboards.patient_menu(ctx.lang),
        )


def callback(ctx: "Context", command: keyboards.Callback) -> None:
    if command.verb == "tgmenu":
        menu(ctx)
        return
    if command.verb in {"unlink", "unlinkok"}:
        with ctx.engine.connect() as conn:
            phones = linking.identity(conn, ctx.chat_id).patient_phones
            cid = conn.execute(
                select(s.contacts.c.clinic_id)
                .where(s.contacts.c.phone_e164.in_(phones))
                .order_by(s.contacts.c.id)
                .limit(1)
            ).scalar_one_or_none()
        if not phones or cid is None:
            ctx.send("refused")
            return
        if ctx.doctor is None:
            ctx.clinic_id = cid
        if command.verb == "unlink":
            ctx.edit(
                "unlink_confirm",
                {"inline_keyboard": [[keyboards.button("unlinkok", "unlinkok", lang=ctx.lang)]]},
            )
        else:
            linking.unlink(ctx.engine, ctx.clock, ctx.chat_id, cid, ctx.key)
            ctx.edit("unlinked", {"inline_keyboard": []})
        return
    assert command.booking_id is not None
    with write_tx(ctx.engine) as conn:
        row = own(conn, ctx.chat_id, command.booking_id)
        ok = row is not None
        if row is not None and ctx.doctor is None:
            ctx.clinic_id = row["clinic_id"]
        if row is not None and not linking.used_update(conn, ctx.handled_key):
            action = (
                timing.patient_on_my_way_in_tx
                if command.verb == "omw"
                else (timing.patient_undo_on_my_way_in_tx)
            )
            result = action(conn, ctx.clock, command.booking_id, ctx.key)
            if result.ok:
                linking.remember(
                    conn, ctx.clock, row["clinic_id"], ctx.handled_key, "telegram_update"
                )
            ok = result.ok
        state: str = (
            conn.execute(
                select(s.bookings.c.state).where(s.bookings.c.id == command.booking_id)
            ).scalar_one_or_none()
            or ""
        )
    if not ok or row is None:
        ctx.send("refused")
        return
    ctx.call(
        "editMessageReplyMarkup",
        {
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "reply_markup": keyboards.patient_booking(command.booking_id, state, row["lang"]),
        },
    )
