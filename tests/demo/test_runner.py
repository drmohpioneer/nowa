import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.clock import CAIRO
from nowa.core import report
from nowa.demo import evening_script as script
from nowa.demo.runner import EveningRunner
from tests.demo.conftest import bookings


def make_runner(engine, clock, cid):
    return EveningRunner(cid, engine=engine, clock=clock)


def test_golden(engine, demo_setup):
    cid, clock = demo_setup
    runner = make_runner(engine, clock, cid)
    runner.start()
    initial = runner.state()
    T = initial["doctor_travel_min"]
    assert abs(T - 35) <= 5
    assert initial["clock"].astimezone(CAIRO).strftime("%a %H:%M") == "Tue 16:00"
    assert bookings(engine, cid)[7]["expected_shown"].astimezone(CAIRO).strftime("%H:%M") == "20:20"
    runner.advance(150)
    assert bookings(engine, cid)[12]["state"] == "cancelled"
    assert bookings(engine, cid)[7]["expected_shown"].astimezone(CAIRO).strftime("%H:%M") == "20:20"
    runner.advance(180)
    with engine.connect() as conn:
        reminder = (
            conn.execute(
                select(s.outbox).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "5")
            )
            .mappings()
            .one()
        )
        assert reminder["status"] == "delivered" and reminder["adapter"] == "screen_phone"
        assert reminder["created_at"].astimezone(CAIRO).strftime("%H:%M") == "19:00"
        assert not conn.execute(
            select(s.outbox.c.id).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "2")
        ).first()
    runner.advance(190)
    with engine.connect() as conn:
        evening = (
            conn.execute(select(s.evenings).where(s.evenings.c.clinic_id == cid)).mappings().one()
        )
        projected = initial["clock"] + timedelta(minutes=190 + T + 8)
        assert evening["projected_start"] == projected
        assert bookings(engine, cid)[7]["expected_shown"] == projected + timedelta(minutes=80)
        # A broad worker must leave all timers of the watch copy alone.
        before = conn.execute(
            select(s.timers.c.id, s.timers.c.status).where(s.timers.c.clinic_id == cid)
        ).all()
    worker.run_once(engine, clock, worker.build_registry())
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.timers.c.id, s.timers.c.status).where(s.timers.c.clinic_id == cid)
            ).all()
            == before
        )
    runner.advance(600)
    states = bookings(engine, cid)
    assert states[11]["state"] == "seen" and states[11]["on_my_way_at"] is None
    assert states[15]["state"] == "didnt_come"
    assert states[19]["source"] == "walkin_tap" and states[19]["state"] == "seen"
    with engine.connect() as conn:
        result = report.build_report(conn, clock, cid, evening["id"])
        assert (result.booked, result.came, result.no_show_count, result.walk_ins) == (17, 17, 1, 1)
        assert result.doctor_arrival == projected
        assert result.health_answers[0]["question"] == script.HEALTH_QUESTION
        assert result.health_answers[0]["model"].endswith("(recorded)")
        assert result.questions[0]["text_display"] == script.DOCTOR_QUESTION
        visits = list(
            conn.execute(
                select(s.visits).where(s.visits.c.clinic_id == cid).order_by(s.visits.c.started_at)
            ).mappings()
        )
        assert len(visits) == 17
        order = [next(n for n, b in states.items() if b["id"] == v["booking_id"]) for v in visits]
        assert order[order.index(9) + 1] == 19
        taps = list(
            conn.execute(select(s.evening_taps).where(s.evening_taps.c.clinic_id == cid)).mappings()
        )
        # The never-arriving head (15) is skipped by the actual doctor tap for 16.
        assert any(
            change["table"] == "bookings"
            and change["id"] == states[15]["id"]
            and "order_key" in (change.get("fields") or {})
            for tap in taps
            for change in tap["after_json"]
        )
        for index, visit in enumerate(visits):
            duration = (visit["ended_at"] - visit["started_at"]).total_seconds() / 60
            assert duration >= script.VISIT_LENGTHS[index]
        visit11 = next(v for v in visits if v["booking_id"] == states[11]["id"])
        assert visit11["started_at"] >= states[11]["told_to_leave_at"] + timedelta(minutes=25)
        leaves = (
            conn.execute(
                select(s.outbox).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "2")
            )
            .mappings()
            .all()
        )
        assert len(leaves) == 17 and len({m["booking_id"] for m in leaves}) == 17
        assert all(m["created_at"] >= initial["clock"] + timedelta(minutes=190) for m in leaves)
        assert not conn.execute(
            select(s.outbox.c.id).where(s.outbox.c.booking_id == states[19]["id"])
        ).first()
    assert runner.state()["closed"]
    print(
        f"Slice 12 trace: T={T}; projected_start={projected}; "
        f"visit_order={order}; counts=17/17/1/1; closed_minute={runner.state()['minute']}"
    )



@pytest.fixture
def fractional_demo_clock(demo_clock):
    demo_clock.base.advance(minutes=0.5 / 60)
    return demo_clock


def test_fractional_clock_positions_and_drains_on_due_minute(
    engine, new_run, fractional_demo_clock
):
    cid = new_run()
    clock = fractional_demo_clock
    runner = make_runner(engine, clock, cid)
    runner.start()
    with engine.connect() as conn:
        zero = runner._zero(conn)
    # Integer-second offsets preserve the base clock's fraction. Ceil must put
    # the clock half a second after the boundary, never half a second before it.
    assert clock.now(cid) == zero + timedelta(seconds=0.5)
    runner.advance(179)
    assert clock.now(cid) == zero + timedelta(minutes=179, seconds=0.5)
    with engine.connect() as conn:
        reminder_timer = conn.execute(
            select(s.timers).where(
                s.timers.c.clinic_id == cid,
                s.timers.c.due_at == zero + timedelta(minutes=180),
                s.timers.c.status == "pending",
            )
        ).mappings().one()
        assert not conn.execute(
            select(s.outbox.c.id).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "5")
        ).first()
    runner.advance(180)
    assert runner.state()["minute"] == 180
    assert clock.now(cid) == zero + timedelta(minutes=180, seconds=0.5)
    with engine.connect() as conn:
        assert conn.execute(
            select(s.timers.c.status).where(s.timers.c.id == reminder_timer["id"])
        ).scalar_one() == "done"
        reminder = conn.execute(
            select(s.outbox).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "5")
        ).mappings().one()
        assert reminder["status"] == "delivered"
        assert reminder["created_at"] == zero + timedelta(minutes=180, seconds=0.5)


def test_script_and_reload_monotonic_order(engine, demo_setup, monkeypatch):
    script.validate()
    cid, clock = demo_setup
    runner = make_runner(engine, clock, cid)
    runner.start()
    events = []
    real_drain = worker.drain
    real_actions = runner._actions

    def drain(*args, **kwargs):
        events.append("drain")
        return real_drain(*args, **kwargs)

    def actions(*args, **kwargs):
        events.append("actions")
        return real_actions(*args, **kwargs)

    monkeypatch.setattr(worker, "drain", drain)
    monkeypatch.setattr(runner, "_actions", actions)
    runner.advance(2)
    assert events == ["drain", "actions", "drain", "actions"]
    runner.advance(1)
    runner.advance(2)
    assert len(events) == 4
    resumed = make_runner(engine, clock, cid)
    assert resumed.state()["minute"] == 2
    resumed.advance(4)
    assert runner.state()["minute"] == 4
    for invalid in (-1, 601, True, 1.5):
        with pytest.raises(ValueError):
            resumed.advance(invalid)


def test_two_runs_identical_bodies(engine, new_run, demo_clock):
    bodies = []
    for key in ("first", "second"):
        cid = new_run(key)
        runner = make_runner(engine, demo_clock, cid)
        runner.advance(600)
        with engine.connect() as conn:
            bodies.append(
                [
                    re.sub(r"/[lwr]/[A-Za-z0-9_-]{22}", "/link/<code>", body)
                    for body in conn.execute(
                        select(s.outbox.c.body)
                        .where(s.outbox.c.clinic_id == cid)
                        .order_by(s.outbox.c.id)
                    ).scalars()
                ]
            )
    assert bodies[0] == bodies[1]


def test_concurrent_advances_and_post_close_noop(engine, demo_setup):
    cid, clock = demo_setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda minute: make_runner(engine, clock, cid).advance(minute), [200, 230]))
    runner = make_runner(engine, clock, cid)
    assert runner.state()["minute"] == 230
    runner.advance(600)
    before = runner.state()
    runner.advance(600)
    assert runner.state() == before
    with engine.connect() as conn:
        assert (
            len(conn.execute(select(s.bookings.c.id).where(s.bookings.c.clinic_id == cid)).all())
            == 19
        )


def test_silent_check_rearms_one_extra_and_keeps_place(engine, demo_setup):
    cid, clock = demo_setup
    runner = make_runner(engine, clock, cid)
    real = runner.registry["silent_check"]
    checks = []

    def observed(ctx, payload):
        row = (
            ctx.conn.execute(select(s.bookings).where(s.bookings.c.id == payload["booking_id"]))
            .mappings()
            .one()
        )
        before_due = ctx.conn.execute(
            select(s.timers.c.due_at).where(
                s.timers.c.clinic_id == cid,
                s.timers.c.kind == "leave_now_check",
                s.timers.c.status == "pending",
            )
        ).scalar_one_or_none()
        real(ctx, payload)
        if row["queue_number"] == 11:
            after_due = ctx.conn.execute(
                select(s.timers.c.due_at).where(
                    s.timers.c.clinic_id == cid,
                    s.timers.c.kind == "leave_now_check",
                    s.timers.c.status == "pending",
                )
            ).scalar_one()
            state = (
                ctx.conn.execute(select(s.bookings).where(s.bookings.c.id == row["id"]))
                .mappings()
                .one()
            )
            checks.append(
                (
                    ctx.now,
                    before_due,
                    after_due,
                    row["order_key"],
                    state["order_key"],
                    state["silent"],
                )
            )

    runner.registry["silent_check"] = observed
    runner.advance(600)
    assert len(checks) == 1
    at, before_due, after_due, before_order, after_order, silent = checks[0]
    assert silent and before_order == after_order == 11
    assert at < after_due <= at + timedelta(minutes=1)
    assert before_due > after_due
    # The engine schedules an earlier leave, then the next minute's drain delivers it.
    with engine.connect() as conn:
        extra = (
            conn.execute(
                select(s.bookings.c.queue_number).where(
                    s.bookings.c.clinic_id == cid,
                    s.bookings.c.told_to_leave_at > at,
                    s.bookings.c.told_to_leave_at <= at + timedelta(minutes=1),
                )
            )
            .scalars()
            .all()
        )
    assert extra == [13]
    print(
        f"Silent trace: at={at}; old_due={before_due}; new_due={after_due}; "
        "next_minute_extra=[13]; order=11 unchanged"
    )


def test_restart_after_close_checkpoint_delivers_pending_report(engine, demo_setup, monkeypatch):
    cid, clock = demo_setup
    runner = make_runner(engine, clock, cid)
    runner.advance(470)
    real = worker.drain

    def interrupted(*args, **kwargs):
        with engine.connect() as conn:
            step = conn.execute(
                select(s.demo_runs.c.step).where(s.demo_runs.c.clinic_id == cid)
            ).scalar_one()
        if step == 2:
            raise RuntimeError("simulated restart after close checkpoint")
        return real(*args, **kwargs)

    monkeypatch.setattr(worker, "drain", interrupted)
    with pytest.raises(RuntimeError, match="simulated restart"):
        runner.advance(600)
    with engine.connect() as conn:
        assert conn.execute(
            select(s.timers.c.id).where(
                s.timers.c.clinic_id == cid,
                s.timers.c.kind == "evening_report",
                s.timers.c.status == "pending",
            )
        ).first()
    monkeypatch.setattr(worker, "drain", real)
    resumed = make_runner(engine, clock, cid)
    resumed.advance(600)
    before = resumed.state()
    resumed.advance(600)
    assert resumed.state() == before
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.timers.c.status).where(
                    s.timers.c.clinic_id == cid, s.timers.c.kind == "evening_report"
                )
            ).scalar_one()
            == "done"
        )
        assert conn.execute(
            select(s.idempotency_keys.c.id).where(
                s.idempotency_keys.c.clinic_id == cid,
                s.idempotency_keys.c.command == "report_snapshot",
            )
        ).one()
        # Accepted slice 11 snapshots an unlinked doctor's report for the dashboard;
        # it sends template 6 only to a linked Telegram doctor, never a new demo path.
        assert not conn.execute(
            select(s.outbox.c.id).where(s.outbox.c.clinic_id == cid, s.outbox.c.template_id == "6")
        ).first()
        assert (
            len(
                conn.execute(
                    select(s.report_questions.c.id).where(s.report_questions.c.clinic_id == cid)
                ).all()
            )
            == 1
        )
