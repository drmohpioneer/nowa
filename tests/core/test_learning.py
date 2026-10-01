from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import learning, projection, timing
from nowa.db import write_tx
from tests.core.support import BASE, move, row, setup


@pytest.mark.parametrize(
    "lengths,want", [([], 12), ([18], 14), ([18, 10], 13), ([18, 10, 8], 12), ([6] + [15] * 10, 15)]
)
def test_pace(engine, lengths, want):
    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        for i, length in enumerate(lengths):
            start = BASE + timedelta(minutes=i * 30)
            conn.execute(
                s.visits.insert().values(
                    clinic_id=cid,
                    evening_id=eid,
                    booking_id=ids[0],
                    started_at=start,
                    ended_at=start + timedelta(minutes=length),
                    accepted=True,
                    est_at_start=12,
                )
            )
        conn.execute(
            s.visits.insert().values(
                clinic_id=cid,
                evening_id=eid,
                booking_id=ids[0],
                started_at=BASE,
                ended_at=BASE + timedelta(minutes=99),
                accepted=False,
                est_at_start=12,
            )
        )
        assert projection.current_pace(conn, cid, eid) == pytest.approx(want)


@pytest.mark.parametrize("length,accepted", [(24, True), (24.1, False)])
def test_f6(engine, length, accepted):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    first = timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "a")
    move(clock, length)
    timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "b")
    assert row(engine, s.visits, first.visit_id)["accepted"] is accepted


@pytest.mark.parametrize(
    "n,k,want_n,want",
    [(0, 2, 2, 18), (49, 2, 50, (12 * 49 + 36) / 51), (50, 2, 50, 12 * 0.98 + 18 * 0.02)],
)
def test_pace_learning_cap(engine, n, k, want_n, want):
    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.learned_pace.update().values(mean_visit_min=12, n=n))
        for i in range(k):
            start = BASE + timedelta(minutes=i * 18)
            conn.execute(
                s.visits.insert().values(
                    clinic_id=cid,
                    evening_id=eid,
                    booking_id=ids[0],
                    started_at=start,
                    ended_at=start + timedelta(minutes=18),
                    accepted=True,
                    est_at_start=12,
                )
            )
        learning.learn(conn, cid, eid)
        learned = conn.execute(select(s.learned_pace)).mappings().one()
        assert learned["n"] == want_n and learned["mean_visit_min"] == pytest.approx(want)


@pytest.mark.parametrize("n,gap", [(0, -8), (19, 8), (20, -8)])
def test_gap_cap(engine, n, gap):
    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.learned_start_gap.insert().values(clinic_id=cid, mean_min=5, n=n))
        conn.execute(
            s.evenings.update().values(
                doctor_on_way_at=BASE - timedelta(minutes=30), doctor_eta_min=30
            )
        )
        conn.execute(
            s.visits.insert().values(
                clinic_id=cid,
                evening_id=eid,
                booking_id=ids[0],
                started_at=BASE + timedelta(minutes=gap),
                accepted=True,
                est_at_start=12,
            )
        )
        learning.learn(conn, cid, eid)
        learned = conn.execute(select(s.learned_start_gap)).mappings().one()
        want = (5 * n + gap) / (n + 1) if n < 20 else 5 * 0.98 + gap * 0.02
        assert learned["n"] == min(20, n + 1) and learned["mean_min"] == pytest.approx(want)
