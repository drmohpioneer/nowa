"""Draft maintenance hook. Periodic scheduling is a later job."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.clock import Clock


def purge_stale_drafts(conn: Connection, clock: Clock, max_age_hours: int = 24) -> int:
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    count = 0
    clinic_ids: list[int] = list(
        conn.execute(
            select(s.chat_sessions.c.clinic_id)
            .where(s.chat_sessions.c.draft.is_not(None))
            .distinct()
        )
        .scalars()
        .all()
    )
    for clinic_id in clinic_ids:
        count += conn.execute(
            s.chat_sessions.update()
            .where(
                s.chat_sessions.c.clinic_id == clinic_id,
                s.chat_sessions.c.draft.is_not(None),
                func.coalesce(s.chat_sessions.c.last_turn_at, s.chat_sessions.c.created_at)
                < clock.now(clinic_id) - timedelta(hours=max_age_hours),
            )
            .values(draft=None)
        ).rowcount
    return count
