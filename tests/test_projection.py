from dataclasses import replace
from datetime import date, datetime, timedelta
from random import Random

import pytest

from nowa.clock import CAIRO
from nowa.core.projection import EveningSnapshot, doctor_free_at, expected_time

DAY = date(2026, 10, 6)


def at(hour, minute=0, second=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=CAIRO)


def snap(**changes):
    base = EveningSnapshot(1, DAY, "scheduled", at(19), at(23), None, None, 8, None)
    return replace(base, **changes)


@pytest.mark.parametrize(
    "snapshot,now,want",
    [
        (snap(), at(12, day=date(2026, 10, 4)), at(19)),
        (snap(), at(19, 40), at(20, 10)),
        (
            snap(state="doctor_on_way", doctor_on_way_at=at(19, 10), doctor_eta_min=35),
            at(19, 20),
            at(19, 53),
        ),
        (
            snap(state="doctor_on_way", doctor_on_way_at=at(19, 10), doctor_eta_min=35),
            at(20),
            at(20),
        ),
        (snap(state="running", visit_started_at=at(20)), at(20, 5), at(20, 15)),
        (snap(state="running", visit_started_at=at(20)), at(20, 20), at(20, 21)),
        (snap(state="running"), at(20, 5), at(20, 5)),
    ],
)
def test_anchors(snapshot, now, want):
    assert doctor_free_at(snapshot, 15, now) == want
    assert expected_time(snapshot, 2, 15, now) == want + timedelta(minutes=30)


def test_rounding_and_golden_projection():
    sunday = at(12, day=date(2026, 10, 4))
    assert expected_time(snap(), 6, 13.33, sunday) == at(20, 20)
    tapped = snap(state="doctor_on_way", doctor_on_way_at=at(19, 10), doctor_eta_min=35)
    assert expected_time(tapped, 6, 13.33, at(19, 10)) == at(21, 13)
    assert expected_time(snap(state="running"), 0, 15, at(20, 0, 1)) == at(20, 1)
    assert expected_time(snap(state="running"), 0, 15, at(20)) == at(20)


@pytest.mark.parametrize(
    "snapshot,position,pace",
    [
        (snap(), -1, 15),
        (snap(), 0, 0),
        (snap(), 0, -1),
        (snap(state="doctor_on_way"), 0, 15),
        (snap(state="doctor_on_way", doctor_on_way_at=at(19)), 0, 15),
        (snap(state="doctor_on_way", doctor_eta_min=35), 0, 15),
        (snap(state="closed"), 0, 15),
        (snap(state="cancelled"), 0, 15),
    ],
)
def test_invalid(snapshot, position, pace):
    with pytest.raises(ValueError):
        expected_time(snapshot, position, pace, at(19))


def test_randomized_never_in_past():
    rng = Random(19)
    for _ in range(500):
        now = at(12) + timedelta(minutes=rng.uniform(0, 720))
        snapshot = rng.choice(
            [
                snap(),
                snap(state="running", visit_started_at=at(19)),
                snap(state="running"),
                snap(state="doctor_on_way", doctor_on_way_at=at(18), doctor_eta_min=35),
            ]
        )
        result = expected_time(snapshot, rng.randrange(30), rng.uniform(0.1, 45), now)
        assert result >= now
        assert result.second == result.microsecond == 0
