from datetime import date, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, Clock
from nowa.core import booking, projection


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class HoursRow(Input):
    weekday: Annotated[int, Field(strict=True, ge=0, le=6)]
    start: Annotated[str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
    end: Annotated[str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]


class Hours(Input):
    hours: list[HoursRow]

    @model_validator(mode="after")
    def distinct(self) -> "Hours":
        if len({h.weekday for h in self.hours}) != len(self.hours):
            raise ValueError("hours: duplicate weekday")
        return self


class Override(Input):
    date: date
    closed: Annotated[bool, Field(strict=True)]
    start: Annotated[str | None, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")] = None
    end: Annotated[str | None, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")] = None

    @model_validator(mode="after")
    def open_times(self) -> "Override":
        if not self.closed and (self.start is None or self.end is None):
            raise ValueError("start, end: required when open")
        return self


class Timing(Input):
    usual_visit_min: Annotated[int, Field(strict=True, ge=5, le=60)]
    cushion_min: Literal[5, 10, 15]
    safe_drive_min: Annotated[int, Field(strict=True, ge=10, le=120)]
    max_per_evening: Annotated[int | None, Field(strict=True, ge=1, le=100)]


class InfoRow(Input):
    key: Literal["price", "address", "what_to_bring", "other"]
    text: Annotated[str, Field(max_length=500)]


class Info(Input):
    items: list[InfoRow]

    @model_validator(mode="after")
    def distinct(self) -> "Info":
        if len({r.key for r in self.items}) != len(self.items):
            raise ValueError("items: duplicate key")
        return self


class Language(Input):
    lang: Literal["ar", "en"]


class Alerts(Input):
    on: Annotated[bool, Field(strict=True)]


class BookingsOutside(Exception):
    pass


def read(conn: Connection, clinic_id: int, doctor_id: int) -> dict[str, Any]:
    clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
    lang: str = conn.execute(
        select(s.doctors.c.lang).where(
            s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id
        )
    ).scalar_one()
    hours = conn.execute(
        select(s.clinic_hours)
        .where(s.clinic_hours.c.clinic_id == clinic_id)
        .order_by(s.clinic_hours.c.weekday)
    ).mappings()
    overrides = conn.execute(
        select(s.clinic_day_overrides)
        .where(s.clinic_day_overrides.c.clinic_id == clinic_id)
        .order_by(s.clinic_day_overrides.c.date)
    ).mappings()
    return {
        "hours": [
            {
                "weekday": r["weekday"],
                "start": r["start"].strftime("%H:%M"),
                "end": r["end"].strftime("%H:%M"),
            }
            for r in hours
        ],
        "overrides": [
            {
                "date": r["date"],
                "closed": r["closed"],
                "start": r["start"].strftime("%H:%M") if r["start"] else None,
                "end": r["end"].strftime("%H:%M") if r["end"] else None,
            }
            for r in overrides
        ],
        **{
            k: clinic[k]
            for k in ("usual_visit_min", "cushion_min", "safe_drive_min", "max_per_evening")
        },
        "items": [
            dict(r)
            for r in conn.execute(
                select(s.clinic_info.c.key, s.clinic_info.c.text).where(
                    s.clinic_info.c.clinic_id == clinic_id
                )
            ).mappings()
        ],
        "lang": lang,
        "on": clinic["secretary_alerts_on"],
    }


def update(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    doctor_id: int,
    kind: str,
    value: Input | date,
) -> tuple[list[int], int | None]:
    conn.execute(
        select(s.doctors.c.id)
        .where(s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id)
        .with_for_update()
    ).scalar_one()
    conn.execute(
        select(s.evenings.c.id)
        .where(s.evenings.c.clinic_id == clinic_id)
        .order_by(s.evenings.c.id)
        .with_for_update()
    ).all()
    clinic = (
        conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id).with_for_update())
        .mappings()
        .one()
    )
    now = clock.now(clinic_id)
    tonight_before = booking.tonight_evening(conn, clinic_id, now)
    tonight_date = tonight_before.evening_date if tonight_before else None
    changes_projection = False
    calendar = kind in {"hours", "overrides", "delete_override"}
    changed_day = (
        value.date if isinstance(value, Override) else value if isinstance(value, date) else None
    )
    changed_weekdays: set[int] = set()
    if isinstance(value, Hours):
        old_hours = {
            r["weekday"]: (r["start"], r["end"])
            for r in conn.execute(
                select(s.clinic_hours).where(s.clinic_hours.c.clinic_id == clinic_id)
            ).mappings()
        }
        new_hours = {
            h.weekday: (time.fromisoformat(h.start), time.fromisoformat(h.end)) for h in value.hours
        }
        changed_weekdays = {
            day
            for day in old_hours.keys() | new_hours.keys()
            if old_hours.get(day) != new_hours.get(day)
        }
    old_paper = projection.paper_hours(conn, clinic_id, tonight_date) if tonight_date else None
    active = (
        conn.execute(
            select(s.bookings.c.expected_shown, s.evenings.c.date)
            .join(s.evenings, s.evenings.c.id == s.bookings.c.evening_id)
            .where(
                s.bookings.c.clinic_id == clinic_id,
                s.bookings.c.state.in_(projection.WAITING_STATES),
                s.evenings.c.date
                >= min(now.astimezone(CAIRO).date(), tonight_date or now.astimezone(CAIRO).date()),
            )
        )
        .mappings()
        .all()
        if calendar
        else []
    )
    previous_papers = {
        r["date"]: projection.paper_hours(conn, clinic_id, r["date"]) for r in active
    }
    with conn.begin_nested():
        if isinstance(value, Hours):
            conn.execute(s.clinic_hours.delete().where(s.clinic_hours.c.clinic_id == clinic_id))
            for h in value.hours:
                conn.execute(
                    s.clinic_hours.insert().values(
                        clinic_id=clinic_id,
                        weekday=h.weekday,
                        start=time.fromisoformat(h.start),
                        end=time.fromisoformat(h.end),
                    )
                )
        elif isinstance(value, Override):
            conn.execute(
                s.clinic_day_overrides.delete().where(
                    s.clinic_day_overrides.c.clinic_id == clinic_id,
                    s.clinic_day_overrides.c.date == value.date,
                )
            )
            conn.execute(
                s.clinic_day_overrides.insert().values(
                    clinic_id=clinic_id,
                    date=value.date,
                    closed=value.closed,
                    start=time.fromisoformat(value.start)
                    if value.start and not value.closed
                    else None,
                    end=time.fromisoformat(value.end) if value.end and not value.closed else None,
                )
            )
        elif kind == "delete_override":
            conn.execute(
                s.clinic_day_overrides.delete().where(
                    s.clinic_day_overrides.c.clinic_id == clinic_id,
                    s.clinic_day_overrides.c.date == value,
                )
            )
        elif isinstance(value, Timing):
            changes_projection = any(
                clinic[k] != getattr(value, k)
                for k in ("usual_visit_min", "cushion_min", "safe_drive_min")
            )
            conn.execute(
                s.clinics.update().where(s.clinics.c.id == clinic_id).values(**value.model_dump())
            )
        elif isinstance(value, Info):
            conn.execute(s.clinic_info.delete().where(s.clinic_info.c.clinic_id == clinic_id))
            for item in value.items:
                conn.execute(
                    s.clinic_info.insert().values(clinic_id=clinic_id, **item.model_dump())
                )
        elif isinstance(value, Language):
            conn.execute(
                s.doctors.update()
                .where(s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id)
                .values(lang=value.lang)
            )
        elif isinstance(value, Alerts):
            conn.execute(
                s.clinics.update()
                .where(s.clinics.c.id == clinic_id)
                .values(secretary_alerts_on=value.on)
            )
        else:
            raise ValueError("Unknown setting")
        if calendar:
            for row in active:
                if changed_day is not None and row["date"] != changed_day:
                    continue
                if kind == "hours" and row["date"].weekday() not in changed_weekdays:
                    continue
                paper = projection.paper_hours(conn, clinic_id, row["date"])
                prior = previous_papers[row["date"]]
                if paper is None or (
                    prior is not None
                    and paper[1] != prior[1]
                    and row["expected_shown"] is not None
                    and row["expected_shown"] > paper[1]
                ):
                    raise BookingsOutside
            changes_projection = tonight_date is not None and (
                projection.paper_hours(conn, clinic_id, tonight_date) != old_paper
            )
    affected: list[int] = []
    if calendar:
        affected = [
            r["id"]
            for r in conn.execute(
                select(s.evenings).where(
                    s.evenings.c.clinic_id == clinic_id,
                    s.evenings.c.state.not_in(("closed", "cancelled")),
                )
            ).mappings()
            if (
                r["date"].weekday() in changed_weekdays
                if kind == "hours"
                else r["date"] == changed_day
            )
        ]
    tonight = booking.tonight_evening(conn, clinic_id, now)
    recompute_id = tonight.evening_id if tonight and changes_projection else None
    record.write_action(conn, clinic_id, "doctor", "settings_" + kind)
    return affected, recompute_id
