from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from nowa.clock import Clock
from nowa.db import conflict_insert
from nowa.schema import timers


def schedule_timer(
    conn: Connection,
    clinic_id: int,
    kind: str,
    due_at: datetime,
    payload: dict[str, Any],
    idempotency_key: str,
) -> int:
    existing = conn.execute(
        select(timers.c.id).where(timers.c.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
        for value in payload.values()
    ):
        raise ValueError("Timer payload values must be finite numbers or numeric IDs")
    conn.execute(
        conflict_insert(conn, timers)
        .values(
            clinic_id=clinic_id,
            kind=kind,
            due_at=due_at,
            payload_json=payload,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=[timers.c.idempotency_key])
    )
    return int(
        conn.execute(
            select(timers.c.id).where(timers.c.idempotency_key == idempotency_key)
        ).scalar_one()
    )


def cancel_timer(conn: Connection, idempotency_key: str) -> bool:
    result = conn.execute(
        update(timers)
        .where(
            timers.c.idempotency_key == idempotency_key,
            timers.c.status == "pending",
        )
        .values(status="cancelled")
    )
    return result.rowcount == 1


@dataclass
class TimerContext:
    conn: Connection
    clock: Clock
    clinic_id: int
    timer_id: int
    kind: str
    due_at: datetime
    attempt: int
    now: datetime
    after_commit: list[Callable[[], None]] = field(default_factory=list)


TimerHandler = Callable[[TimerContext, dict[str, Any]], None]


def rearm(
    conn: Connection,
    clock: Clock,
    kind: str,
    evening_id: int,
    due_at: datetime,
    payload: dict[str, Any],
    *,
    key_prefix: str | None = None,
) -> int:
    import secrets

    from nowa.schema import evenings

    clinic_id: int = conn.execute(
        select(evenings.c.clinic_id).where(evenings.c.id == evening_id).with_for_update()
    ).scalar_one()
    prefix = key_prefix if key_prefix is not None else f"{kind}:{evening_id}:"
    keys: Sequence[str] = (
        conn.execute(
            select(timers.c.idempotency_key).where(
                timers.c.clinic_id == clinic_id,
                timers.c.status == "pending",
                timers.c.idempotency_key.startswith(prefix, autoescape=True),
            )
        )
        .scalars()
        .all()
    )
    for key in keys:
        cancel_timer(conn, key)
    epoch = int(due_at.timestamp())
    return schedule_timer(
        conn, clinic_id, kind, due_at, payload, f"{prefix}{epoch}:{secrets.token_hex(4)}"
    )
