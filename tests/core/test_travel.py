from datetime import datetime
from math import ceil

import pytest

from nowa.clock import CAIRO
from nowa.core import travel

AT = datetime(2026, 10, 6, 12, tzinfo=CAIRO)


@pytest.mark.parametrize(
    "delta,want", [(0, 5), (0.01, ceil(6371 * 0.01 * 3.141592653589793 / 180 * 2.5) + 5), (80, 120)]
)
def test_fixed_formula(delta, want, engine, clinic_id):
    with engine.connect() as conn:
        ctx = travel.TravelContext(conn, clinic_id, None)
    assert (
        travel.FixedAreaAdapter().minutes(travel.LatLng(0, 0), travel.LatLng(delta, 0), AT, ctx=ctx)
        == want
    )


@pytest.mark.parametrize("lat,lng", [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))])
def test_coordinate_boundary(lat, lng):
    with pytest.raises(ValueError):
        travel.LatLng(lat, lng)


def test_fallback(engine, clinic_id, monkeypatch):
    class Missing:
        def minutes(self, origin, dest, at, *, ctx):
            return None

    monkeypatch.setattr(
        travel,
        "chain_for",
        lambda clinic, settings: travel.TravelChains(
            [Missing(), travel.SafeTimeAdapter(47.5)], [Missing(), travel.SafeTimeAdapter(47.5)]
        ),
    )
    with engine.connect() as conn:
        assert travel.minutes(conn, clinic_id, AT, travel.LatLng(0, 0)) == 47.5
        assert travel.minutes(conn, clinic_id, AT) == 45
