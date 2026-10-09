from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from nowa import schema as s
from nowa.core import clinic_settings as settings
from nowa.core import projection
from nowa.db import write_tx
from tests.core.support import DAY, move, row, setup


@pytest.mark.parametrize(
    "field,values",
    [
        ("usual_visit_min", [5, 60]),
        ("safe_drive_min", [10, 120]),
        ("max_per_evening", [None, 1, 100]),
        ("cushion_min", [5, 10, 15]),
    ],
)
def test_range_edges(field, values):
    for value in values:
        payload = dict(usual_visit_min=15, safe_drive_min=45, max_per_evening=None, cushion_min=10)
        payload[field] = value
        assert getattr(settings.Timing.model_validate(payload), field) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("usual_visit_min", 4),
        ("usual_visit_min", 61),
        ("usual_visit_min", True),
        ("safe_drive_min", 9),
        ("safe_drive_min", 121),
        ("max_per_evening", 0),
        ("max_per_evening", 101),
        ("max_per_evening", ""),
        ("cushion_min", 7),
    ],
)
def test_range_refusals(field, value):
    payload = dict(usual_visit_min=15, safe_drive_min=45, max_per_evening=None, cushion_min=10)
    payload[field] = value
    with pytest.raises(ValidationError):
        settings.Timing.model_validate(payload)


@pytest.mark.parametrize(
    "model,payload",
    [
        (settings.Hours, {"hours": [{"weekday": 7, "start": "19:00", "end": "01:00"}]}),
        (settings.Hours, {"hours": [{"weekday": 1, "start": "24:00", "end": "01:00"}]}),
        (settings.Override, {"date": "2026-10-06", "closed": False}),
        (settings.Info, {"items": [{"key": "price", "text": "x" * 501}]}),
        (settings.Info, {"items": [{"key": "bad", "text": "ok"}]}),
        (settings.Language, {"lang": "franco"}),
        (settings.Alerts, {"on": "false"}),
    ],
)
def test_other_validation(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def change(engine, clock, cid, kind, value):
    with write_tx(engine) as conn:
        did = conn.execute(select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)).scalar_one()
        return settings.update(conn, clock, cid, did, kind, value)


def test_calendar_protection_and_later_start(engine):
    cid, eid, clock, ids = setup(engine, count=3)
    move(clock, 0)
    original = row(engine, s.bookings, ids[-1])["expected_shown"]
    with pytest.raises(settings.BookingsOutside):
        change(engine, clock, cid, "hours", settings.Hours(hours=[]))
    with pytest.raises(settings.BookingsOutside):
        change(engine, clock, cid, "overrides", settings.Override(date=DAY, closed=True))
    with pytest.raises(settings.BookingsOutside):
        change(
            engine,
            clock,
            cid,
            "overrides",
            settings.Override(date=DAY, closed=False, start="12:00", end="12:01"),
        )
    with engine.connect() as conn:
        assert not conn.execute(select(s.clinic_day_overrides)).all()
    affected, tonight = change(
        engine,
        clock,
        cid,
        "overrides",
        settings.Override(date=DAY, closed=False, start="15:00", end="23:59"),
    )
    assert affected == [eid] and tonight == eid
    assert row(engine, s.bookings, ids[-1])["expected_shown"] == original


def test_reject_overnight_hours_and_track_changed_days(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    move(clock, 0)
    with pytest.raises(ValidationError):
        settings.HoursRow(weekday=DAY.weekday(), start="19:00", end="01:00")
    affected, tonight = change(
        engine,
        clock,
        cid,
        "hours",
        settings.Hours(
            hours=[settings.HoursRow(weekday=DAY.weekday(), start="19:00", end="23:59")]
        ),
    )
    assert affected == [eid] and tonight == eid
    with engine.connect() as conn:
        paper = projection.paper_hours(conn, cid, DAY)
        assert paper[1].date() == DAY
    affected, tonight = change(
        engine,
        clock,
        cid,
        "overrides",
        settings.Override(date=DAY + timedelta(days=1), closed=True),
    )
    assert affected == [] and tonight is None


@pytest.mark.parametrize(
    "kind,value",
    [
        ("info", settings.Info(items=[settings.InfoRow(key="price", text="x" * 500)])),
        ("lang", settings.Language(lang="en")),
        ("secretary_alerts", settings.Alerts(on=True)),
        (
            "timing",
            settings.Timing(
                usual_visit_min=15, cushion_min=10, safe_drive_min=45, max_per_evening=100
            ),
        ),
    ],
)
def test_settings_without_projection(engine, kind, value):
    cid, _, clock, _ = setup(engine, count=1)
    move(clock, 0)
    assert change(engine, clock, cid, kind, value) == ([], None)
