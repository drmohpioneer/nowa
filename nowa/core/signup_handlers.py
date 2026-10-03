"""Transactional lifecycle handlers; their timers belong to the permanent system clinic."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from nowa import schema as s
from nowa.core.telegram_tokens import delete_signup_tokens
from nowa.core.timers import TimerContext
from nowa.db import conflict_insert, metadata


def pending_signup_purge(ctx: TimerContext, payload: dict[str, Any]) -> None:
    row = (
        ctx.conn.execute(
            select(s.pending_signups).where(s.pending_signups.c.id == payload["pending_signup_id"])
        )
        .mappings()
        .first()
    )
    if row and (
        row["completed_at"] is not None or ctx.now >= row["expires_at"] + timedelta(hours=24)
    ):
        delete_signup_tokens(ctx.conn, row["id"])
        ctx.conn.execute(s.pending_signups.delete().where(s.pending_signups.c.id == row["id"]))


def sandbox_expire(ctx: TimerContext, payload: dict[str, Any]) -> None:
    cid = payload["clinic_id"]
    clinic = (
        ctx.conn.execute(select(s.clinics).where(s.clinics.c.id == cid).with_for_update())
        .mappings()
        .first()
    )
    if clinic is None:
        return
    if not clinic["is_sandbox"]:
        raise ValueError("Cannot expire a real clinic")
    phones: list[str] = list(
        ctx.conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == cid)
        ).scalars()
    )
    phones.extend(
        ctx.conn.execute(
            select(s.contacts.c.phone_e164).where(s.contacts.c.clinic_id == cid)
        ).scalars()
    )
    ctx.conn.execute(s.telegram_links.delete().where(s.telegram_links.c.phone_e164.in_(phones)))
    ctx.conn.execute(
        conflict_insert(ctx.conn, s.deleted_slugs)
        .values(slug=clinic["slug"], deleted_at=ctx.now)
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    for table in reversed(metadata.sorted_tables):
        if "clinic_id" in table.c:
            ctx.conn.execute(table.delete().where(table.c.clinic_id == cid))
    ctx.conn.execute(s.clinics.delete().where(s.clinics.c.id == cid))
