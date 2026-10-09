from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.db import conflict_insert


def accepted_lengths(conn: Connection, clinic_id: int, evening_id: int) -> list[float]:
    rows = conn.execute(
        select(s.visits.c.started_at, s.visits.c.ended_at)
        .where(
            s.visits.c.clinic_id == clinic_id,
            s.visits.c.evening_id == evening_id,
            s.visits.c.accepted.is_(True),
            s.visits.c.ended_at.is_not(None),
        )
        .order_by(s.visits.c.started_at, s.visits.c.id)
    )
    return [(end - start).total_seconds() / 60 for start, end in rows]


def learn(conn: Connection, clinic_id: int, evening_id: int) -> None:
    conn.execute(
        select(s.clinics.c.id).where(s.clinics.c.id == clinic_id).with_for_update()
    ).scalar_one()
    learn_no_show(conn, clinic_id)
    lengths = accepted_lengths(conn, clinic_id, evening_id)
    if lengths:
        old = (
            conn.execute(select(s.learned_pace).where(s.learned_pace.c.clinic_id == clinic_id))
            .mappings()
            .one_or_none()
        )
        n = old["n"] if old else 0
        mean = old["mean_visit_min"] if old else 0.0
        value = (
            (mean * n + sum(lengths)) / (n + len(lengths))
            if n < 50
            else mean * 0.98 + sum(lengths) / len(lengths) * 0.02
        )
        conn.execute(
            conflict_insert(conn, s.learned_pace)
            .values(clinic_id=clinic_id, mean_visit_min=value, n=min(50, n + len(lengths)))
            .on_conflict_do_update(
                index_elements=[s.learned_pace.c.clinic_id],
                set_={"mean_visit_min": value, "n": min(50, n + len(lengths))},
            )
        )
    evening = (
        conn.execute(
            select(s.evenings).where(
                s.evenings.c.id == evening_id, s.evenings.c.clinic_id == clinic_id
            )
        )
        .mappings()
        .one()
    )
    first: datetime | None = conn.execute(
        select(s.visits.c.started_at)
        .where(s.visits.c.evening_id == evening_id)
        .order_by(s.visits.c.started_at, s.visits.c.id)
        .limit(1)
    ).scalar_one_or_none()
    if first is None or evening["doctor_on_way_at"] is None:
        return
    gap = (first - evening["doctor_on_way_at"]).total_seconds() / 60 - evening["doctor_eta_min"]
    old = (
        conn.execute(
            select(s.learned_start_gap).where(s.learned_start_gap.c.clinic_id == clinic_id)
        )
        .mappings()
        .one_or_none()
    )
    n = old["n"] if old else 0
    mean = old["mean_min"] if old else 0.0
    value = (mean * n + gap) / (n + 1) if n < 20 else mean * 0.98 + gap * 0.02
    conn.execute(
        conflict_insert(conn, s.learned_start_gap)
        .values(clinic_id=clinic_id, mean_min=value, n=min(20, n + 1))
        .on_conflict_do_update(
            index_elements=[s.learned_start_gap.c.clinic_id],
            set_={"mean_min": value, "n": min(20, n + 1)},
        )
    )


def learn_no_show(conn: Connection, clinic_id: int) -> None:
    """Recompute from closed-evening aggregates; small evenings still use a window place."""
    recent = conn.execute(
        select(s.daily_totals)
        .where(s.daily_totals.c.clinic_id == clinic_id)
        .order_by(s.daily_totals.c.date.desc())
        .limit(10)
    ).mappings()
    qualifying = [r for r in recent if r["booked"] + r["cancelled"] >= 5]
    missing = sum(r["didnt_come"] for r in qualifying)
    total = sum(r["didnt_come"] + r["came"] for r in qualifying)
    rate = missing / total if total else 0.0
    conn.execute(
        conflict_insert(conn, s.learned_no_show)
        .values(clinic_id=clinic_id, n=len(qualifying), rate=rate)
        .on_conflict_do_update(
            index_elements=[s.learned_no_show.c.clinic_id],
            set_={"n": len(qualifying), "rate": rate},
        )
    )
