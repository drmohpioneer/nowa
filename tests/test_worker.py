import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.exc import OperationalError

from nowa import record, worker
from nowa import schema as s
from nowa.clock import ClinicOffsetClock
from nowa.core.timers import cancel_timer, schedule_timer
from nowa.db import write_tx
from nowa.demo.template import CLINIC
from tests.helpers.worker import HandlerSetup, assert_handler_idempotent, drain


def add(engine, clock, cid, key="one", kind="send_retry", minutes=0, attempts=0):
    with write_tx(engine) as conn:
        tid = schedule_timer(conn, cid, kind, clock.now(cid) + timedelta(minutes=minutes), {}, key)
        conn.execute(s.timers.update().where(s.timers.c.id == tid).values(attempts=attempts))
        return tid


def timer(engine, tid):
    with engine.connect() as conn:
        return conn.execute(select(s.timers).where(s.timers.c.id == tid)).mappings().one()


def actions(engine, kind):
    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(s.action_record)
            .where(
                s.action_record.c.kind == kind,
            )
        ).scalar_one()


def effect(ctx, payload):
    record.write_action(ctx.conn, ctx.clinic_id, "system", "effect")


def test_registry():
    registry = worker.build_registry()
    assert set(registry) == {
        "travel_check",
        "send_retry",
        "delivery_timeout",
        "leave_now_check",
        "silent_check",
        "standby_expire",
        "are_you_on_way",
        "evening_auto_close",
        "evening_system_close",
        "evening_report",
        "sandbox_expire",
        "pending_signup_purge",
    }
    with pytest.raises(ValueError, match="Duplicate"):
        worker.register(registry, "send_retry", effect)
    with pytest.raises(ValueError, match="Unknown"):
        worker.register(registry, "invented", effect)


def test_due_cancel_unknown_batch(engine, frozen_clock, clinic_id, caplog):
    first = add(engine, frozen_clock, clinic_id, "first", minutes=-1)
    second = add(engine, frozen_clock, clinic_id, "second")
    future = add(engine, frozen_clock, clinic_id, "future", minutes=1)
    cancelled = add(engine, frozen_clock, clinic_id, "cancelled")
    unknown = add(engine, frozen_clock, clinic_id, "unknown", "travel_check", -10)
    add(engine, frozen_clock, clinic_id, "unknown2", "travel_check", -10, attempts=5)
    add(engine, frozen_clock, clinic_id, "future-unknown", "silent_check", 2)
    with write_tx(engine) as conn:
        cancel_timer(conn, "cancelled")
    stats = worker.run_once(engine, frozen_clock, {"send_retry": effect}, batch=1)
    assert (stats.claimed, stats.done, stats.skipped_unknown) == (1, 1, 2)
    assert timer(engine, first)["status"] == "done"
    assert timer(engine, second)["status"] == "pending"
    assert timer(engine, future)["status"] == "pending"
    assert timer(engine, cancelled)["status"] == "cancelled"
    assert timer(engine, unknown)["attempts"] == 0
    assert caplog.messages == ["Unknown timer kind travel_check: 2 due pending"]
    drain(engine, frozen_clock, {"send_retry": effect})
    assert actions(engine, "effect") == 2
    assert worker.last_run_at == frozen_clock.base_now()


def test_rollback_backoff_exhaustion(engine, frozen_clock, clinic_id, caplog):
    tid = add(engine, frozen_clock, clinic_id)
    callbacks = []

    def fail(ctx, payload):
        effect(ctx, payload)
        ctx.after_commit.append(lambda: callbacks.append(1))
        raise ValueError("private patient text")

    for attempt in range(1, 6):
        now = frozen_clock.now(clinic_id)
        stats = worker.run_once(engine, frozen_clock, {"send_retry": fail})
        row = timer(engine, tid)
        assert row["attempts"] == attempt and row["last_error"] == "ValueError"
        assert actions(engine, "effect") == 0 and callbacks == []
        if attempt < 5:
            assert stats.retried == 1
            assert row["due_at"] == now + timedelta(seconds=30 * attempt)
            assert worker.run_once(engine, frozen_clock, {"send_retry": fail}).claimed == 0
            frozen_clock.advance(minutes=attempt / 2)
        else:
            assert stats.failed == 1 and row["status"] == "failed"
    assert actions(engine, "timer_failed") == 1
    assert "private patient text" not in caplog.text
    assert worker.run_once(engine, frozen_clock, {"send_retry": effect}).claimed == 0


def claim(engine, clock, registry):
    return worker._claim(engine, clock, registry, 50, None, worker.RunStats())


def test_abandoned_recovery_and_five_crashes(engine, frozen_clock, clinic_id):
    tid = add(engine, frozen_clock, clinic_id)
    registry = {"send_retry": effect}
    claim(engine, frozen_clock, registry)
    frozen_clock.advance(minutes=4)
    assert worker.run_once(engine, frozen_clock, registry).claimed == 0
    frozen_clock.advance(minutes=1)
    assert worker.run_once(engine, frozen_clock, registry).recovered == 0
    frozen_clock.advance(minutes=1 / 60)
    stats = worker.run_once(engine, frozen_clock, registry)
    assert (stats.recovered, stats.done) == (1, 1)
    assert timer(engine, tid)["attempts"] == 2
    assert actions(engine, "effect") == 1
    doomed = add(engine, frozen_clock, clinic_id, "doomed")
    for attempt in range(1, 6):
        claim(engine, frozen_clock, registry)
        assert timer(engine, doomed)["attempts"] == attempt
        frozen_clock.advance(minutes=5 + 1 / 60)
        worker._recover(engine, frozen_clock, worker.RunStats())
    assert timer(engine, doomed)["status"] == "failed"
    assert timer(engine, doomed)["last_error"] == "stale"
    assert actions(engine, "timer_failed") == 1
    assert worker.run_once(engine, frozen_clock, registry).claimed == 0


def test_partial_crash_then_restart(engine, frozen_clock, clinic_id):
    tid = add(engine, frozen_clock, clinic_id)

    def crash(ctx, payload):
        effect(ctx, payload)
        raise SystemExit()

    with pytest.raises(SystemExit):
        worker.run_once(engine, frozen_clock, {"send_retry": crash})
    assert actions(engine, "effect") == 0
    assert timer(engine, tid)["status"] == "running"
    frozen_clock.advance(minutes=6)
    assert worker.run_once(engine, frozen_clock, {"send_retry": effect}).done == 1
    assert actions(engine, "effect") == 1


def test_after_commit_error_continues_and_never_retries(engine, frozen_clock, clinic_id, caplog):
    tid = add(engine, frozen_clock, clinic_id)
    callbacks = []

    def handler(ctx, payload):
        effect(ctx, payload)

        def fail():
            assert timer(engine, tid)["status"] == "done"
            raise RuntimeError("secret")

        ctx.after_commit.extend([fail, lambda: callbacks.append(1)])

    assert worker.run_once(engine, frozen_clock, {"send_retry": handler}).done == 1
    assert callbacks == [1] and actions(engine, "timer_after_commit_error") == 1
    assert "secret" not in caplog.text
    assert worker.run_once(engine, frozen_clock, {"send_retry": handler}).claimed == 0


def test_stop_releases_claims_including_fifth_attempt(engine, frozen_clock, clinic_id):
    tids = [add(engine, frozen_clock, clinic_id, str(i), attempts=4) for i in range(3)]
    stop = threading.Event()

    def handler(ctx, payload):
        effect(ctx, payload)
        ctx.after_commit.append(stop.set)

    stats = worker.run_once(engine, frozen_clock, {"send_retry": handler}, stop=stop)
    assert (stats.claimed, stats.done) == (3, 1)
    rows = [timer(engine, tid) for tid in tids]
    assert sorted(row["attempts"] for row in rows) == [4, 4, 5]
    assert all(row["locked_at"] is None for row in rows if row["status"] == "pending")
    drain(engine, frozen_clock, {"send_retry": effect})
    assert actions(engine, "effect") == 3


def test_offsets_demo_scope_and_base_recovery(engine, frozen_clock, clinic_id):
    clock = ClinicOffsetClock(frozen_clock, engine)
    record.configure(clock)
    with write_tx(engine) as conn:
        sandbox = conn.execute(
            s.clinics.insert()
            .values(
                **dict(
                    CLINIC["clinic"],
                    slug="sandbox",
                    is_sandbox=True,
                )
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
    seed_tid = add(engine, clock, clinic_id, "seed", minutes=120)
    sandbox_tid = add(engine, clock, sandbox, "sandbox", minutes=120)
    abandoned = add(engine, clock, sandbox, "abandoned")
    claim(engine, clock, {"send_retry": effect})
    with write_tx(engine) as conn:
        conn.execute(
            s.clinics.update().where(s.clinics.c.id == sandbox).values(clock_offset_s=7260)
        )
    stats = worker.run_once(engine, clock, {"send_retry": effect})
    assert stats.done == 1 and stats.recovered == 0
    assert timer(engine, sandbox_tid)["status"] == "done"
    assert timer(engine, abandoned)["status"] == "running"
    assert timer(engine, seed_tid)["status"] == "pending"
    with write_tx(engine) as conn:
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == sandbox)
            .values(
                demo_run_active=True,
                clock_offset_s=0,
            )
        )
    active = add(engine, clock, sandbox, "active")
    other = add(engine, clock, clinic_id, "other")
    unknown = add(engine, clock, sandbox, "unknown", "travel_check")
    stats = worker.run_once(engine, clock, {"send_retry": effect}, only_clinic_id=sandbox)
    assert stats.done == 1 and stats.skipped_unknown == 1
    assert timer(engine, other)["status"] == "pending"
    assert timer(engine, active)["status"] == "done"
    assert timer(engine, unknown)["status"] == "pending"
    active2 = add(engine, clock, sandbox, "active2")
    assert worker.run_once(engine, clock, {"send_retry": effect}).skipped_unknown == 0
    assert timer(engine, active2)["status"] == "pending"
    frozen_clock.advance(minutes=121)
    worker.run_once(engine, clock, {"send_retry": effect})
    assert timer(engine, seed_tid)["status"] == "done"


def concurrency(engine, clock):
    with write_tx(engine) as conn:
        cid = conn.execute(
            s.clinics.insert()
            .values(**CLINIC["clinic"])
            .returning(
                s.clinics.c.id,
            )
        ).scalar_one()
        for i in range(200):
            schedule_timer(conn, cid, "send_retry", clock.now(cid), {}, f"timer:{i}")
    table = Table("worker_effects", MetaData(), Column("timer_id", Integer, primary_key=True))
    table.create(engine)
    barrier = threading.Barrier(2)

    def handler(ctx, payload):
        ctx.conn.execute(table.insert().values(timer_id=ctx.timer_id))

    def run():
        barrier.wait(timeout=10)
        drain(engine, clock, {"send_retry": handler})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            for future in futures:
                future.result(timeout=30)
        with engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(table)).scalar_one() == 200
            rows = conn.execute(select(s.timers)).mappings().all()
            assert len(rows) == 200
            assert all(row["status"] == "done" and row["attempts"] == 1 for row in rows)
            assert all(row["last_error"] is None for row in rows)
    finally:
        table.drop(engine)


def test_two_sqlite_workers(engine, frozen_clock):
    concurrency(engine, frozen_clock)


@pytest.mark.postgres
def test_two_postgres_workers(postgres_engine, frozen_clock):
    concurrency(postgres_engine, frozen_clock)


def test_lost_ownership_rolls_back_and_discards_callbacks(engine, frozen_clock, clinic_id):
    tid = add(engine, frozen_clock, clinic_id)
    registry = {"send_retry": effect}
    old, stamp = claim(engine, frozen_clock, registry)
    frozen_clock.advance(minutes=6)
    assert worker.run_once(engine, frozen_clock, registry).done == 1
    callbacks = []

    def stale_handler(ctx, payload):
        effect(ctx, payload)
        ctx.after_commit.append(lambda: callbacks.append(1))

    stats = worker.RunStats()
    worker._run_timer(engine, frozen_clock, stale_handler, old[0], stamp, stats)
    assert stats.done == 0 and actions(engine, "effect") == 1 and callbacks == []
    assert timer(engine, tid)["status"] == "done"

    def stale_failure(ctx, payload):
        raise ValueError()

    worker._run_timer(engine, frozen_clock, stale_failure, old[0], stamp, stats)
    assert timer(engine, tid)["last_error"] is None and stats.retried == 0


def test_forever_no_sleep_with_backlog_and_database_error(engine, frozen_clock, monkeypatch):
    stop = threading.Event()
    waits = []
    ticks = []

    def tick(*args, **kwargs):
        ticks.append(1)
        if len(ticks) == 1:
            return worker.RunStats(claimed=50)
        if len(ticks) == 2:
            return worker.RunStats()
        if len(ticks) == 3:
            raise OperationalError("private", {}, Exception("private"))
        stop.set()
        return worker.RunStats(claimed=1)

    monkeypatch.setattr(worker, "run_once", tick)
    monkeypatch.setattr(stop, "wait", lambda timeout: waits.append(timeout))
    worker.run_forever(engine, frozen_clock, {}, poll_s=0.1, stop=stop)
    assert len(ticks) == 4 and waits == [0.1, 0.1]


def test_database_failure_updates_heartbeat(engine, frozen_clock, monkeypatch):
    monkeypatch.setattr(worker, "last_run_at", None)
    with patch.object(worker, "_recover", side_effect=OperationalError("x", {}, Exception())):
        with pytest.raises(OperationalError):
            worker.run_once(engine, frozen_clock, {})
    assert worker.last_run_at == frozen_clock.base_now()


def test_drain_limit(engine, frozen_clock, clinic_id):
    add(engine, frozen_clock, clinic_id)

    def repeating(ctx, payload):
        schedule_timer(ctx.conn, clinic_id, "send_retry", ctx.now, {}, str(ctx.timer_id))

    with pytest.raises(AssertionError, match="3 rounds.*send_retry"):
        drain(engine, frozen_clock, {"send_retry": repeating}, max_rounds=3)


def test_idempotency_helper_detects_non_idempotent_handler(engine, frozen_clock, clinic_id):
    with pytest.raises(AssertionError):
        assert_handler_idempotent(
            "send_retry",
            {},
            lambda: HandlerSetup(
                engine,
                frozen_clock,
                clinic_id,
                {"send_retry": effect},
            ),
        )


def test_merged_due_order_total_batch(engine, frozen_clock, clinic_id):
    with write_tx(engine) as conn:
        shifted = conn.execute(
            s.clinics.insert()
            .values(
                **dict(
                    CLINIC["clinic"],
                    slug="shifted",
                    is_sandbox=True,
                    clock_offset_s=7200,
                )
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
    clock = ClinicOffsetClock(frozen_clock, engine)
    first = add(engine, frozen_clock, clinic_id, "first", minutes=-3)
    second = add(engine, frozen_clock, shifted, "second", minutes=-2)
    third = add(engine, frozen_clock, clinic_id, "third", minutes=-1)
    fourth = add(engine, frozen_clock, shifted, "fourth", minutes=60)
    order = []
    registry = {"send_retry": lambda ctx, payload: order.append(ctx.timer_id)}
    stats = worker.run_once(engine, clock, registry, batch=2)
    assert stats.claimed == 2 and order == [first, second]
    drain(engine, clock, registry)
    assert order == [first, second, third, fourth]


def stale_in_flight(engine, clock, monkeypatch, pause_in_handler):
    with write_tx(engine) as conn:
        cid = conn.execute(
            s.clinics.insert()
            .values(**CLINIC["clinic"])
            .returning(
                s.clinics.c.id,
            )
        ).scalar_one()
    tid = add(engine, clock, cid)
    paused = threading.Event()
    resume = threading.Event()
    callback_calls = []
    original = worker._run_timer

    def handler(ctx, payload):
        if pause_in_handler and ctx.attempt == 1:
            paused.set()
            assert resume.wait(10)
        effect(ctx, payload)
        ctx.after_commit.append(lambda: callback_calls.append(ctx.attempt))

    def run_timer(*args):
        if not pause_in_handler and args[3]["attempts"] == 1:
            paused.set()
            assert resume.wait(10)
        return original(*args)

    monkeypatch.setattr(worker, "_run_timer", run_timer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(worker.run_once, engine, clock, {"send_retry": handler})
        try:
            assert paused.wait(10)
            clock.advance(minutes=6)
            new = worker.run_once(engine, clock, {"send_retry": handler})
            assert new.done == 1 and new.recovered == 1
        finally:
            resume.set()
        assert old.result(timeout=10).done == 0
    assert actions(engine, "effect") == 1
    assert callback_calls == [2]
    assert timer(engine, tid)["status"] == "done"


def test_sqlite_recovery_while_old_worker_stalled(engine, frozen_clock, monkeypatch):
    stale_in_flight(engine, frozen_clock, monkeypatch, pause_in_handler=False)


@pytest.mark.postgres
def test_postgres_recovery_during_handler(postgres_engine, frozen_clock, monkeypatch):
    stale_in_flight(postgres_engine, frozen_clock, monkeypatch, pause_in_handler=True)


@pytest.mark.postgres
def test_postgres_skip_locked(postgres_engine, frozen_clock):
    engine = postgres_engine
    with write_tx(engine) as conn:
        cid = conn.execute(
            s.clinics.insert()
            .values(**CLINIC["clinic"])
            .returning(
                s.clinics.c.id,
            )
        ).scalar_one()
    first = add(engine, frozen_clock, cid, "locked", minutes=-1)
    second = add(engine, frozen_clock, cid, "available")
    with engine.begin() as lock_conn:
        lock_conn.execute(select(s.timers).where(s.timers.c.id == first).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_once, engine, frozen_clock, {"send_retry": effect})
            stats = future.result(timeout=5)
        assert stats.claimed == 1 and stats.done == 1
        assert timer(engine, first)["status"] == "pending"
        assert timer(engine, second)["status"] == "done"
    assert worker.run_once(engine, frozen_clock, {"send_retry": effect}).done == 1


def test_drain_rejects_stranded_due_registered_timer(engine, frozen_clock, clinic_id):
    add(engine, frozen_clock, clinic_id, attempts=5)
    with pytest.raises(AssertionError, match="2 rounds.*send_retry"):
        drain(engine, frozen_clock, {"send_retry": effect}, max_rounds=2)


def test_stop_already_set_releases_entire_batch(engine, frozen_clock, clinic_id):
    tid = add(engine, frozen_clock, clinic_id)
    stop = threading.Event()
    stop.set()
    stats = worker.run_once(engine, frozen_clock, {"send_retry": effect}, stop=stop)
    assert stats.claimed == 1 and stats.done == 0
    assert timer(engine, tid)["status"] == "pending"
    assert timer(engine, tid)["attempts"] == 0
