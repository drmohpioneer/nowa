import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.core import timing, travel
from tests.core.support import BASE, move, setup
from tests.helpers.worker import drain

ROOT = Path(__file__).resolve().parents[2]
ROUND15 = dict(
    display="frozen",
    update_min=20,
    learn="mean",
    cushion_min=10,
    traffic_mult=1.3,
    buffer=10,
    on_my_way=True,
    gate_on_tap=True,
    p_reply=1.0,
    grace=15,
    late_after=2,
)


def simulator():
    spec = importlib.util.spec_from_file_location(
        "nowa_reference_sim", ROOT / "docs/reference/sim.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def traces(sim, policy, scenario, seed, count):
    told, calls = [], []
    for p in range(count):
        res, trace = sim.run(policy | {"watch": p}, seed, scenario, trace=True)
        told += [(t, p + 1) for t, _, event in trace if event == "gets LEAVE NOW"]
        calls += [(t, p) for t, _, event in trace if event == "called in"]
    return res, sorted(told), sorted(calls)


@pytest.mark.parametrize(
    "name,start,pace,cushion",
    [
        ("g_on_time", 0, 12, 10),
        ("g_late_doctor", 45, 12, 10),
        ("g_slow_pace", 15, 16, 10),
        ("g_cushion5", 0, 12, 5),
        ("g_cushion15", 0, 12, 15),
    ],
)
def test_deterministic(engine, monkeypatch, name, start, pace, cushion):
    sim = simulator()
    drives = [10, 20, 30, 40] * 5
    world = dict(
        N=20,
        doctor_says=pace,
        true_pace=pace,
        doctor_start=start,
        doc_travel=30,
        late_warned=False,
        noshow=[False] * 20,
        travel=drives,
        traffic=[1.0] * 20,
        slow_leave=[False] * 20,
        tap_lag=0,
        visits=[pace] * 20,
        slow_by=[0] * 20,
        map=drives,
    )
    monkeypatch.setattr(sim, "world", lambda seed, scenario: world)
    res, told, calls = traces(sim, ROUND15 | {"cushion_min": cushion}, {}, 0, 20)
    assert res["missed"] == res["late_rejoins"] == 0, "Bad fixture"
    assert all(b[0] == a[0] + pace for a, b in zip(calls, calls[1:])), "Bad fixture"
    cid, eid, clock, ids = setup(engine, pace, cushion)
    from nowa.db import write_tx

    with write_tx(engine) as conn:
        for p, bid in enumerate(ids):
            aid = conn.execute(
                s.areas.insert()
                .values(name_ar=f"منطقة {p}", name_en=f"Fixture {p}", lat=30, lng=31)
                .returning(s.areas.c.id)
            ).scalar_one()
            conn.execute(s.bookings.update().where(s.bookings.c.id == bid).values(area_id=aid))
            world.setdefault("area_drives", {})[aid] = drives[p]
    monkeypatch.setattr(
        travel,
        "minutes",
        lambda conn, clinic_id, at, origin=None, area_id=None, *, doctor=False: (
            30.0 if area_id is None else float(world["area_drives"][area_id])
        ),
    )
    registry = worker.build_registry()
    by_time = dict(calls)
    for minute in range(-60, calls[-1][0] + 1):
        move(clock, minute)
        if minute == start - 30:
            assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
        if minute in by_time:
            assert timing.who_comes_in(
                engine, clock, cid, eid, ids[by_time[minute]], False, f"tap:{minute}"
            ).ok
        drain(engine, clock, registry)
        with engine.connect() as conn:
            fresh = (
                conn.execute(
                    select(s.outbox.c.booking_id).where(
                        s.outbox.c.template_id == "2", s.outbox.c.created_at == clock.now(cid)
                    )
                )
                .scalars()
                .all()
            )
        for bid in fresh:
            assert timing.patient_on_my_way(engine, clock, bid, f"reply:{bid}").ok
    with engine.connect() as conn:
        actual = sorted(
            (int((at - BASE).total_seconds() / 60), number)
            for at, number in conn.execute(
                select(s.outbox.c.created_at, s.bookings.c.queue_number)
                .join(s.bookings, s.bookings.c.id == s.outbox.c.booking_id)
                .where(s.outbox.c.template_id == "2")
            )
        )
    with engine.connect() as conn:
        assert set(conn.execute(select(s.outbox.c.channel, s.outbox.c.adapter)).all()) == {
            ("telegram", "screen_phone")
        }
    assert actual == told, {"fixture": name, "sim": told, "engine": actual, "calls": calls}


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize(
    "name,scenario,cushion",
    [
        ("r15_on_time", {"lates": [0], "paces": [12]}, 10),
        ("r15_late_doctor", {"lates": [45], "paces": [12]}, 10),
        ("r15_slow_pace", {"lates": [15], "paces": [16]}, 10),
        ("r15_cushion5", {}, 5),
        ("r15_cushion15", {}, 15),
    ],
)
def test_stochastic_invariants(engine, monkeypatch, seed, name, scenario, cushion):
    sim = simulator()
    scenario = {"N": 30, "carry": "mean", "doc_travel": [30, 30]} | scenario
    world = sim.world(seed, scenario)
    _, _, calls = traces(sim, ROUND15 | {"cushion_min": cushion}, scenario, seed, 30)
    cid, eid, clock, ids = setup(engine, world["doctor_says"], cushion, 30)
    from nowa.db import write_tx

    area_drives = {}
    with write_tx(engine) as conn:
        for p, bid in enumerate(ids):
            aid = conn.execute(
                s.areas.insert()
                .values(name_ar=f"منطقة {p}", name_en=f"Stochastic {p}", lat=30, lng=31)
                .returning(s.areas.c.id)
            ).scalar_one()
            conn.execute(s.bookings.update().where(s.bookings.c.id == bid).values(area_id=aid))
            area_drives[aid] = world["map"][p]
    monkeypatch.setattr(
        travel,
        "minutes",
        lambda conn, clinic_id, at, origin=None, area_id=None, *, doctor=False: (
            30.0 if area_id is None else area_drives[area_id]
        ),
    )
    registry = worker.build_registry()
    by_time = dict(calls)
    previous = {}
    replied = set()
    for minute in range(-60, calls[-1][0] + 1):
        move(clock, minute)
        if minute == world["doctor_start"] - 30:
            assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way").ok
        if minute in by_time:
            assert timing.who_comes_in(
                engine, clock, cid, eid, ids[by_time[minute]], False, f"tap:{minute}"
            ).ok
        drain(engine, clock, registry)
        with engine.connect() as conn:
            messages = (
                conn.execute(select(s.outbox).where(s.outbox.c.template_id == "2")).mappings().all()
            )
        for msg in messages:
            bid = msg["booking_id"]
            assert msg["created_at"] >= BASE + timedelta(minutes=world["doctor_start"] - 30)
            if bid not in replied and not world["noshow"][ids.index(bid)]:
                assert timing.patient_on_my_way(engine, clock, bid, f"reply:{bid}").ok
                replied.add(bid)
        assert len({m["booking_id"] for m in messages}) == len(messages)
        with engine.connect() as conn:
            current = {r["id"]: r for r in conn.execute(select(s.bookings)).mappings()}
        for p, bid in enumerate(ids):
            b = current[bid]
            assert b["queue_number"] == p + 1
            if bid in previous:
                old = previous[bid]
                if old["expected_frozen"]:
                    assert b["expected_shown"] == old["expected_shown"]
                elif b["expected_shown"] != old["expected_shown"]:
                    assert b["expected_shown"] - old["expected_shown"] >= timedelta(minutes=20)
        previous = current
