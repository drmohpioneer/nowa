import logging
import threading
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from nowa import record
from nowa.clock import Clock
from nowa.core import report, signup_handlers, standby, timing_handlers
from nowa.core.timers import TimerContext, TimerHandler
from nowa.db import write_tx
from nowa.messaging.pipeline import delivery_timeout, send_retry
from nowa.schema import clinics, timers

logger = logging.getLogger(__name__)
last_run_at: datetime | None = None
KINDS = frozenset(
    {
        "travel_check",
        "leave_now_check",
        "silent_check",
        "standby_expire",
        "are_you_on_way",
        "evening_auto_close",
        "evening_system_close",
        "send_retry",
        "delivery_timeout",
        "evening_report",
        "retention_daily",
        "sandbox_expire",
        "pending_signup_purge",
    }
)


@dataclass
class RunStats:
    recovered: int = 0
    claimed: int = 0
    done: int = 0
    retried: int = 0
    failed: int = 0
    skipped_unknown: int = 0


def register(registry: dict[str, TimerHandler], kind: str, handler: TimerHandler) -> None:
    if kind not in KINDS:
        raise ValueError(f"Unknown timer kind: {kind}")
    if kind in registry:
        raise ValueError(f"Duplicate timer kind: {kind}")
    registry[kind] = handler


def build_registry() -> dict[str, TimerHandler]:
    registry: dict[str, TimerHandler] = {}
    register(registry, "standby_expire", standby.expire)
    register(registry, "send_retry", send_retry)
    register(registry, "delivery_timeout", delivery_timeout)
    register(registry, "travel_check", timing_handlers.travel_check)
    register(registry, "leave_now_check", timing_handlers.leave_now_check)
    register(registry, "silent_check", timing_handlers.silent_check)
    register(registry, "are_you_on_way", timing_handlers.are_you_on_way)
    register(registry, "evening_auto_close", timing_handlers.evening_auto_close)
    register(registry, "evening_system_close", timing_handlers.evening_system_close)
    register(registry, "evening_report", report.evening_report)
    register(registry, "sandbox_expire", signup_handlers.sandbox_expire)
    register(registry, "pending_signup_purge", signup_handlers.pending_signup_purge)
    return registry


def _scope(only_clinic_id: int | None) -> ColumnElement[bool]:
    return (
        clinics.c.demo_run_active.is_(False)
        if only_clinic_id is None
        else clinics.c.id == only_clinic_id
    )


def _due_scopes(
    conn: Connection,
    clock: Clock,
    only_clinic_id: int | None,
) -> Iterable[ColumnElement[bool]]:
    scope = _scope(only_clinic_id)
    yield scope & (clinics.c.clock_offset_s == 0) & (timers.c.due_at <= clock.base_now())
    shifted: list[int] = list(
        conn.execute(select(clinics.c.id).where(scope, clinics.c.clock_offset_s != 0)).scalars()
    )
    for clinic_id in shifted:
        yield scope & (clinics.c.id == clinic_id) & (timers.c.due_at <= clock.now(clinic_id))


def due_pending(
    conn: Connection,
    clock: Clock,
    registry: dict[str, TimerHandler],
    only_clinic_id: int | None = None,
    *,
    lock: bool = False,
    eligible_only: bool = True,
) -> tuple[list[RowMapping], Counter[str]]:
    rows: list[RowMapping] = []
    unknown: Counter[str] = Counter()
    for scope in _due_scopes(conn, clock, only_clinic_id):
        query = select(timers).join(clinics).where(timers.c.status == "pending", scope)
        candidates = query.where(timers.c.kind.in_(registry))
        if eligible_only:
            candidates = candidates.where(timers.c.attempts < 5)
        if lock:
            candidates = candidates.with_for_update(of=timers, skip_locked=True)
        rows.extend(conn.execute(candidates).mappings())
        unknown.update(
            conn.execute(
                query.with_only_columns(timers.c.kind).where(timers.c.kind.not_in(registry))
            ).scalars()
        )
    rows.sort(key=lambda row: row["due_at"])
    return rows, unknown


def _owned(timer_id: int, lock_stamp: datetime) -> ColumnElement[bool]:
    return (
        (timers.c.id == timer_id)
        & (timers.c.status == "running")
        & (timers.c.locked_at == lock_stamp)
    )


def _recover(engine: Engine, clock: Clock, stats: RunStats) -> None:
    with write_tx(engine) as conn:
        stale = (
            conn.execute(
                select(timers)
                .where(
                    timers.c.status == "running",
                    timers.c.locked_at < clock.base_now() - timedelta(minutes=5),
                )
                .with_for_update(of=timers)
            )
            .mappings()
            .all()
        )
        for row in stale:
            exhausted = row["attempts"] >= 5
            conn.execute(
                update(timers)
                .where(_owned(row["id"], row["locked_at"]))
                .values(
                    status="failed" if exhausted else "pending",
                    locked_at=None,
                    **({"last_error": "stale"} if exhausted else {}),
                )
            )
            record.write_action(
                conn,
                row["clinic_id"],
                "system",
                "timer_failed" if exhausted else "timer_recovered",
            )
            if exhausted:
                stats.failed += 1
            else:
                stats.recovered += 1


def _claim(
    engine: Engine,
    clock: Clock,
    registry: dict[str, TimerHandler],
    batch: int,
    only_clinic_id: int | None,
    stats: RunStats,
) -> tuple[list[RowMapping], datetime]:
    with write_tx(engine) as conn:
        lock_stamp = clock.base_now()
        candidates, unknown = due_pending(conn, clock, registry, only_clinic_id, lock=True)
        stats.skipped_unknown = sum(unknown.values())
        for kind, count in unknown.items():
            logger.warning("Unknown timer kind %s: %d due pending", kind, count)
        ids = [row["id"] for row in candidates[:batch]]
        claimed = (
            conn.execute(
                update(timers)
                .where(timers.c.id.in_(ids), timers.c.status == "pending")
                .values(status="running", attempts=timers.c.attempts + 1, locked_at=lock_stamp)
                .returning(*timers.c)
            )
            .mappings()
            .all()
            if ids
            else []
        )
    claimed = sorted(claimed, key=lambda row: row["due_at"])
    stats.claimed = len(claimed)
    return claimed, lock_stamp


class _OwnershipLost(Exception):
    pass


def _after_commit(engine: Engine, ctx: TimerContext) -> None:
    for callback in ctx.after_commit:
        try:
            callback()
        except Exception as exc:
            logger.error("Timer %s after commit failed: %s", ctx.timer_id, type(exc).__name__)
            with write_tx(engine) as conn:
                record.write_action(
                    conn,
                    ctx.clinic_id,
                    "system",
                    "timer_after_commit_error",
                    text=type(exc).__name__,
                )


def _run_timer(
    engine: Engine,
    clock: Clock,
    handler: TimerHandler,
    row: RowMapping,
    lock_stamp: datetime,
    stats: RunStats,
) -> None:
    try:
        with write_tx(engine) as conn:
            ctx = TimerContext(
                conn,
                clock,
                row["clinic_id"],
                row["id"],
                row["kind"],
                row["due_at"],
                row["attempts"],
                clock.now(row["clinic_id"]),
            )
            handler(ctx, row["payload_json"])
            result = conn.execute(
                update(timers).where(_owned(row["id"], lock_stamp)).values(status="done")
            )
            if result.rowcount != 1:
                raise _OwnershipLost
    except _OwnershipLost:
        logger.warning("Timer %s ownership lost; handler transaction rolled back", row["id"])
        return
    except Exception as exc:
        exhausted = row["attempts"] >= 5
        with write_tx(engine) as conn:
            result = conn.execute(
                update(timers)
                .where(_owned(row["id"], lock_stamp))
                .values(
                    status="failed" if exhausted else "pending",
                    locked_at=None,
                    last_error=type(exc).__name__,
                    **(
                        {}
                        if exhausted
                        else {
                            "due_at": clock.now(row["clinic_id"])
                            + timedelta(seconds=30 * row["attempts"])
                        }
                    ),
                )
            )
            if result.rowcount != 1:
                logger.warning("Timer %s ownership lost; failure ignored", row["id"])
                return
            if exhausted:
                record.write_action(conn, row["clinic_id"], "system", "timer_failed")
        if exhausted:
            stats.failed += 1
            logger.error("Timer %s failed: %s", row["id"], type(exc).__name__)
        else:
            stats.retried += 1
        return
    stats.done += 1
    _after_commit(engine, ctx)


def run_once(
    engine: Engine,
    clock: Clock,
    registry: dict[str, TimerHandler],
    batch: int = 50,
    only_clinic_id: int | None = None,
    stop: threading.Event | None = None,
) -> RunStats:
    global last_run_at
    if batch < 1:
        raise ValueError("batch must be positive")
    stats = RunStats()
    try:
        _recover(engine, clock, stats)
        claimed, lock_stamp = _claim(engine, clock, registry, batch, only_clinic_id, stats)
        for index, row in enumerate(claimed):
            if stop is not None and stop.is_set():
                with write_tx(engine) as conn:
                    conn.execute(
                        update(timers)
                        .where(
                            timers.c.id.in_([r["id"] for r in claimed[index:]]),
                            timers.c.status == "running",
                            timers.c.locked_at == lock_stamp,
                        )
                        .values(status="pending", locked_at=None, attempts=timers.c.attempts - 1)
                    )
                break
            _run_timer(engine, clock, registry[row["kind"]], row, lock_stamp, stats)
        return stats
    finally:
        last_run_at = clock.base_now()


def run_forever(
    engine: Engine,
    clock: Clock,
    registry: dict[str, TimerHandler],
    poll_s: float = 1.0,
    *,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            stats = run_once(engine, clock, registry, stop=stop)
        except SQLAlchemyError as exc:
            logger.error("Timer tick database error: %s", type(exc).__name__)
            stop.wait(poll_s)
        else:
            if stats.claimed == 0:
                stop.wait(poll_s)


def health(
    engine: Engine,
    clock: Clock,
    started_at: datetime,
    *,
    required: bool,
) -> tuple[dict[str, str | int | None], bool]:
    now = clock.base_now()
    stamp = last_run_at
    with engine.connect() as conn:
        overdue = conn.execute(
            select(func.count())
            .select_from(timers)
            .join(clinics)
            .where(
                timers.c.status == "pending",
                clinics.c.clock_offset_s == 0,
                timers.c.due_at < now - timedelta(minutes=3),
            )
        ).scalar_one()
    stale = required and (stamp or started_at) < now - timedelta(minutes=3)
    return {"last_run_at": stamp.isoformat() if stamp else None, "overdue": overdue}, stale


def start_clock(clock: Clock) -> datetime:
    global last_run_at
    last_run_at = None
    return clock.base_now()


def drain(
    engine: Engine,
    clock: Clock,
    registry: dict[str, TimerHandler],
    only_clinic_id: int | None = None,
    max_rounds: int = 1000,
) -> None:
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    for _ in range(max_rounds):
        run_once(engine, clock, registry, only_clinic_id=only_clinic_id)
        with engine.connect() as conn:
            remaining, _ = due_pending(
                conn,
                clock,
                registry,
                only_clinic_id,
                eligible_only=False,
            )
        if not remaining:
            return
    raise AssertionError(
        f"After {max_rounds} rounds due kinds remain: {sorted({row['kind'] for row in remaining})}"
    )
