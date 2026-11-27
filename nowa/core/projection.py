from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, RowMapping

from nowa import schema as s
from nowa.clock import CAIRO

EveningState = Literal[
    "scheduled", "doctor_on_way", "running", "winding_down", "closed", "cancelled"
]
WAITING_STATES = ("booked", "told_to_leave", "on_my_way")


@dataclass(frozen=True)
class EveningSnapshot:
    clinic_id: int
    evening_date: date
    state: EveningState
    clinic_start: datetime
    clinic_end: datetime
    doctor_on_way_at: datetime | None
    doctor_eta_min: float | None
    start_gap_min: float
    visit_started_at: datetime | None
    visit_paused_min: float = 0.0
    paused: bool = False


def doctor_free_at(snap: EveningSnapshot, pace_min: float, now: datetime) -> datetime:
    if pace_min <= 0:
        raise ValueError("pace must be positive")
    if snap.state == "scheduled":
        return max(snap.clinic_start, now + timedelta(minutes=30))
    if snap.state == "doctor_on_way":
        if snap.doctor_on_way_at is None or snap.doctor_eta_min is None:
            raise ValueError("on-way evening requires tap and ETA")
        return max(
            now, snap.doctor_on_way_at + timedelta(minutes=snap.doctor_eta_min + snap.start_gap_min)
        )
    if snap.state in {"running", "winding_down"}:
        if snap.visit_started_at is None:
            return now
        return max(
            now + timedelta(minutes=1),
            snap.visit_started_at + timedelta(minutes=snap.visit_paused_min + pace_min),
        )
    raise ValueError("closed or cancelled evening has no projection")


def expected_time(snap: EveningSnapshot, position: int, pace_min: float, now: datetime) -> datetime:
    if position < 0 or pace_min <= 0:
        raise ValueError("position must be nonnegative and pace positive")
    result = doctor_free_at(snap, pace_min, now) + timedelta(minutes=position * pace_min)
    minute = result.replace(second=0, microsecond=0)
    return minute + timedelta(minutes=1) if result != minute else minute


def paper_hours(
    conn: Connection, clinic_id: int, evening_date: date
) -> tuple[datetime, datetime] | None:
    override = (
        conn.execute(
            select(s.clinic_day_overrides).where(
                s.clinic_day_overrides.c.clinic_id == clinic_id,
                s.clinic_day_overrides.c.date == evening_date,
            )
        )
        .mappings()
        .first()
    )
    hours: RowMapping | None
    if override is not None:
        if override["closed"]:
            return None
        hours = override
    else:
        hours = (
            conn.execute(
                select(s.clinic_hours).where(
                    s.clinic_hours.c.clinic_id == clinic_id,
                    s.clinic_hours.c.weekday == evening_date.weekday(),
                )
            )
            .mappings()
            .first()
        )
        if hours is None:
            return None
    start = datetime.combine(evening_date, hours["start"], CAIRO)
    end = datetime.combine(evening_date, hours["end"], CAIRO)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def load_snapshot(
    conn: Connection, clinic_id: int, evening_date: date, now: datetime
) -> EveningSnapshot:
    hours = paper_hours(conn, clinic_id, evening_date)
    if hours is None:
        raise ValueError("date has no open paper hours")
    evening = (
        conn.execute(
            select(s.evenings).where(
                s.evenings.c.clinic_id == clinic_id, s.evenings.c.date == evening_date
            )
        )
        .mappings()
        .first()
    )
    gap = conn.execute(
        select(s.learned_start_gap.c.mean_min).where(
            s.learned_start_gap.c.clinic_id == clinic_id, s.learned_start_gap.c.n >= 1
        )
    ).scalar_one_or_none()
    visit = (
        None
        if evening is None
        else conn.execute(
            select(s.visits.c.started_at, s.visits.c.paused_min).where(
                s.visits.c.evening_id == evening["id"], s.visits.c.ended_at.is_(None)
            )
        )
        .mappings()
        .one_or_none()
    )
    pause = (
        None
        if evening is None
        else conn.execute(
            select(s.evening_pauses.c.started_at).where(
                s.evening_pauses.c.clinic_id == clinic_id,
                s.evening_pauses.c.evening_id == evening["id"],
                s.evening_pauses.c.ended_at.is_(None),
            )
        ).scalar_one_or_none()
    )
    paused_so_far = (
        0.0
        if visit is None
        else float(visit["paused_min"])
        + (
            max(0.0, (now - max(pause, visit["started_at"])).total_seconds() / 60)
            if pause is not None
            else 0.0
        )
    )
    return EveningSnapshot(
        clinic_id,
        evening_date,
        "scheduled" if evening is None else cast(EveningState, evening["state"]),
        *hours,
        None if evening is None else evening["doctor_on_way_at"],
        None if evening is None else evening["doctor_eta_min"],
        float(gap) if gap is not None else 0.0,
        None if visit is None else visit["started_at"],
        paused_so_far,
        pause is not None,
    )


def current_pace(conn: Connection, clinic_id: int, evening_id: int | None) -> float:
    pace: float | None = conn.execute(
        select(s.learned_pace.c.mean_visit_min).where(
            s.learned_pace.c.clinic_id == clinic_id, s.learned_pace.c.n >= 1
        )
    ).scalar_one_or_none()
    if pace is None:
        pace = conn.execute(
            select(s.clinics.c.usual_visit_min).where(s.clinics.c.id == clinic_id)
        ).scalar_one()
    if evening_id is None:
        return max(float(pace), 1.0)
    from nowa.core.learning import accepted_lengths

    lengths = accepted_lengths(conn, clinic_id, evening_id)
    if len(lengths) >= 3:
        recent = lengths[-10:]
        return max(sum(recent) / len(recent), 1.0)
    return max((float(pace) * 2 + sum(lengths)) / (2 + len(lengths)), 1.0)


def people_ahead_of_new_booking(conn: Connection, evening_id: int | None) -> int:
    if evening_id is None:
        return 0
    return int(
        conn.execute(
            select(func.count())
            .select_from(s.bookings)
            .where(s.bookings.c.evening_id == evening_id, s.bookings.c.state.in_(WAITING_STATES))
        ).scalar_one()
    )


def no_show_rate(conn: Connection, clinic_id: int) -> float:
    rate = conn.execute(
        select(s.learned_no_show.c.rate).where(
            s.learned_no_show.c.clinic_id == clinic_id, s.learned_no_show.c.n >= 3
        )
    ).scalar_one_or_none()
    return 0.10 if rate is None else min(float(rate), 0.20)
