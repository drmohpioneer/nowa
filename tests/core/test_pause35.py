from datetime import timedelta

import pytest
from sqlalchemy import func, select

from nowa import schema as s
from nowa.core import learning, projection, report, timing, timing_handlers
from nowa.db import write_tx
from tests.core.support import move, row, setup
from tests.core.test_timing_scenarios import context


def pause(engine, clock, cid, eid, key="pause"):
    with write_tx(engine) as conn:
        return timing.pause_in_tx(conn, clock, cid, eid, key)


def resume(engine, clock, cid, eid, key="resume"):
    with write_tx(engine) as conn:
        return timing.resume_in_tx(conn, clock, cid, eid, key)


def test_four_admissions_one_minute_no_learning_floor(engine):
    cid, eid, clock, ids = setup(engine, count=5)
    move(clock, 0)
    for i in range(4):
        assert timing.who_comes_in(engine, clock, cid, eid, ids[i], False, f"in:{i}").ok
    with write_tx(engine) as conn:
        assert learning.accepted_lengths(conn, cid, eid) == [0, 0, 0]
        assert projection.current_pace(conn, cid, eid) == 1
        conn.execute(s.learned_pace.delete())
        learning.learn(conn, cid, eid)
        assert conn.execute(select(s.learned_pace.c.mean_visit_min)).scalar_one() == 0


def test_pause_subtracted_from_projection_acceptance_learning_and_report(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    move(clock, 5)
    assert pause(engine, clock, cid, eid).ok
    move(clock, 15)
    with engine.connect() as conn:
        snap = projection.load_snapshot(
            conn, cid, row(engine, s.evenings, eid)["date"], clock.now(cid)
        )
        assert snap.paused and snap.visit_paused_min == 10
        assert projection.doctor_free_at(snap, 12, clock.now(cid)) == clock.now(cid) + timedelta(
            minutes=7
        )
    assert resume(engine, clock, cid, eid).ok
    assert resume(engine, clock, cid, eid).ok
    assert pause(engine, clock, cid, eid).ok  # replay never reopens
    move(clock, 30)
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "second").ok
    assert row(engine, s.visits, first.visit_id)["paused_min"] == 10
    assert row(engine, s.visits, first.visit_id)["accepted"]
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", 0).ok
    with write_tx(engine) as conn:
        assert learning.accepted_lengths(conn, cid, eid) == [20, 0]
        result = report.build_report(conn, clock, cid, eid)
        assert (result.pause_count, result.pause_min, result.avg_visit) == (1, 10, 10)
        for lang in ("ar", "en"):
            assert "10" in result.text(lang)
        from nowa.web.strings import text

        assert "10" in text("doctor.report_pause", "franco").format(min=10, count=1)
        assert conn.execute(
            select(s.action_record.c.kind).where(s.action_record.c.kind.in_(("pause", "resume")))
        ).scalars().all() == ["pause", "resume"]


@pytest.mark.parametrize("walk_in", [False, True])
def test_admission_resumes_in_same_transaction(engine, walk_in):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    pause(engine, clock, cid, eid)
    clock.advance(minutes=10)
    assert timing.who_comes_in(
        engine, clock, cid, eid, None if walk_in else ids[1], walk_in, "next"
    ).ok
    assert row(engine, s.visits, first.visit_id)["paused_min"] == 10
    with engine.connect() as conn:
        assert not conn.execute(
            select(s.evening_pauses).where(s.evening_pauses.c.ended_at.is_(None))
        ).first()


def test_pause_without_visit_and_invalid_states(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    assert pause(engine, clock, cid, eid).reason == "invalid_state"
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="running"))
    assert pause(engine, clock, cid, eid).ok
    clock.advance(minutes=10)
    assert resume(engine, clock, cid, eid).ok
    assert resume(engine, clock, cid, eid, "nothing").ok
    with engine.connect() as conn:
        assert not conn.execute(select(s.visits)).first()
        snap = projection.load_snapshot(
            conn, cid, row(engine, s.evenings, eid)["date"], clock.now(cid)
        )
        assert not snap.paused and snap.visit_paused_min == 0
        assert projection.doctor_free_at(snap, 12, clock.now(cid)) == clock.now(cid)


@pytest.mark.parametrize("command", ["close", "wind"])
def test_close_and_wind_down_end_pause(engine, command):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    pause(engine, clock, cid, eid)
    clock.advance(minutes=10)
    with write_tx(engine) as conn:
        result = (
            timing.close_evening_in_tx(conn, clock, cid, eid, "doctor", "close", 0)
            if command == "close"
            else timing.wind_down_in_tx(conn, clock, cid, eid, "wind", 0)
        )
        assert result.ok
        assert conn.execute(select(s.evening_pauses.c.ended_at)).scalar_one() == clock.now(cid)
        value = report.build_report(conn, clock, cid, eid)
        assert (value.pause_count, value.pause_min) == (1, 10)
    assert row(engine, s.visits, first.visit_id)["paused_min"] == 10


def test_paused_enqueues_nothing_then_resume_sends_due(engine):
    cid, eid, clock, ids = setup(engine, count=12)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    pause(engine, clock, cid, eid)
    with engine.connect() as conn:
        before = conn.execute(
            select(func.count()).select_from(s.outbox).where(s.outbox.c.template_id == "2")
        ).scalar_one()
    clock.advance(minutes=100)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
        assert (
            conn.execute(
                select(func.count()).select_from(s.outbox).where(s.outbox.c.template_id == "2")
            ).scalar_one()
            == before
        )
        assert not conn.execute(
            select(s.timers).where(
                s.timers.c.kind == "leave_now_check", s.timers.c.status == "pending"
            )
        ).first()
        # Make one additional patient due using the existing short-visit learning rule.
        conn.execute(
            s.learned_pace.update()
            .where(s.learned_pace.c.clinic_id == cid)
            .values(mean_visit_min=1)
        )
    resume(engine, clock, cid, eid)
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(s.outbox).where(s.outbox.c.template_id == "2")
            ).scalar_one()
            > before
        )


def test_auto_close_rearms_during_pause(engine):
    cid, eid, clock, ids = setup(engine, count=1)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    pause(engine, clock, cid, eid)
    clock.advance(minutes=900)
    with write_tx(engine) as conn:
        timing_handlers.evening_auto_close(
            context(conn, clock, cid, "evening_auto_close"), {"evening_id": eid}
        )
        assert conn.execute(
            select(s.timers.c.id).where(
                s.timers.c.kind == "evening_auto_close",
                s.timers.c.status == "pending",
                s.timers.c.due_at == clock.now(cid) + timedelta(minutes=60),
            )
        ).first()
    assert row(engine, s.evenings, eid)["state"] == "running"


def test_auto_close_rearms_when_arrived_patient_not_admitted(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first").ok
    with write_tx(engine) as conn:
        assert timing.mark_arrived_in_tx(
            conn, clock, cid, ids[1], "doctor", "arrived"
        ).ok
    before = row(engine, s.bookings, ids[1])
    clock.advance(minutes=900)
    with write_tx(engine) as conn:
        evening = timing._evening(conn, cid, eid)
        assert timing._auto_due(conn, evening) < clock.now(cid)
        timing_handlers.evening_auto_close(
            context(conn, clock, cid, "evening_auto_close"), {"evening_id": eid}
        )
        pending = conn.execute(
            select(s.timers.c.due_at).where(
                s.timers.c.clinic_id == cid,
                s.timers.c.kind == "evening_auto_close",
                s.timers.c.status == "pending",
            )
        ).scalars().all()
        assert pending == [clock.now(cid) + timedelta(minutes=60)]
        assert ids[1] in [r.booking_id for r in timing.tonight_board(conn, cid, eid).rows]
    assert row(engine, s.evenings, eid)["state"] == "running"
    after = row(engine, s.bookings, ids[1])
    assert (after["state"], after["arrived_at"]) == (before["state"], before["arrived_at"])


def test_pause_actions_have_translated_audit_labels():
    from nowa.web.strings import ACTION_SENTENCES, text

    for kind in ("pause", "resume"):
        assert kind in ACTION_SENTENCES
        for lang in ("ar", "en", "franco"):
            assert text("ui.kind_" + kind, lang)


def test_undo_admission_keeps_intervening_pause_out_of_reopened_visit(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    move(clock, 5)
    timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "second")
    move(clock, 10)
    pause(engine, clock, cid, eid)
    move(clock, 20)
    resume(engine, clock, cid, eid)
    assert timing.undo_last(engine, clock, cid, eid, "undo-second").ok
    move(clock, 25)
    assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", 0).ok
    assert row(engine, s.visits, first.visit_id)["paused_min"] == 10
    with engine.connect() as conn:
        assert learning.accepted_lengths(conn, cid, eid) == [15]
