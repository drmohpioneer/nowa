from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from sqlalchemy import MetaData, select, update
from sqlalchemy.engine import Engine

from nowa import worker
from nowa.clock import Clock
from nowa.core.timers import TimerContext, TimerHandler, schedule_timer
from nowa.db import write_tx
from nowa.schema import timers
from nowa.worker import drain as drain


@dataclass
class HandlerSetup:
    engine: Engine
    clock: Clock
    clinic_id: int
    registry: dict[str, TimerHandler]


def _snapshot(engine: Engine) -> dict[str, list[str]]:
    metadata = MetaData()
    metadata.reflect(engine)
    with engine.connect() as conn:
        return {
            table.name: sorted(repr(tuple(row)) for row in conn.execute(select(table)))
            for table in metadata.sorted_tables
        }


def assert_handler_idempotent(
    kind: str,
    payload: dict[str, Any],
    setup: Callable[[], HandlerSetup],
) -> None:
    """Setup returns a prepared DB, clock, clinic and registry; replay one claimed invocation."""
    prepared = setup()
    engine, clock = prepared.engine, prepared.clock
    with write_tx(engine) as conn:
        timer_id = schedule_timer(
            conn,
            prepared.clinic_id,
            kind,
            clock.now(prepared.clinic_id),
            payload,
            "idempotency-helper-invocation",
        )
    stats = worker.RunStats()
    stamp = clock.base_now()
    with write_tx(engine) as conn:
        row = (
            conn.execute(
                update(timers)
                .where(timers.c.id == timer_id)
                .values(
                    status="running",
                    attempts=1,
                    locked_at=stamp,
                )
                .returning(*timers.c)
            )
            .mappings()
            .one()
        )
    execute_callbacks = worker._after_commit
    queued: list[int] = []

    def spy(engine: Engine, ctx: TimerContext) -> None:
        queued.append(len(ctx.after_commit))
        execute_callbacks(engine, ctx)

    with patch.object(worker, "_after_commit", side_effect=spy):
        worker._run_timer(engine, clock, prepared.registry[kind], row, stamp, stats)
        assert stats.done == 1, "first handler invocation did not commit"
        first = _snapshot(engine)
        # Replay the exact same claim, so worker bookkeeping is identical in both snapshots.
        with write_tx(engine) as conn:
            conn.execute(update(timers).where(timers.c.id == timer_id).values(status="running"))
        worker._run_timer(engine, clock, prepared.registry[kind], row, stamp, stats)
        assert stats.done == 2, "second handler invocation did not commit"
        assert _snapshot(engine) == first
        assert queued[1] == 0, "repeated handler queued after_commit work"
