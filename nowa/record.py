from datetime import date

from sqlalchemy.engine import Connection

from nowa.clock import Clock
from nowa.config import get_settings
from nowa.db import conflict_insert
from nowa.schema import action_record, usage

_clock: Clock | None = None


def configure(clock: Clock) -> None:
    global _clock
    _clock = clock


def configured_clock() -> Clock:
    if _clock is None:
        raise RuntimeError("record.configure(clock) must be called first")
    return _clock


def write_action(
    conn: Connection,
    clinic_id: int,
    actor: str,
    kind: str,
    booking_id: int | None = None,
    patient_id: int | None = None,
    text: str | None = None,
    model: str | None = None,
) -> int:
    return int(
        conn.execute(
            action_record.insert()
            .values(
                clinic_id=clinic_id,
                at=configured_clock().now(clinic_id, conn=conn),
                actor=actor,
                kind=kind,
                booking_id=booking_id,
                patient_id=patient_id,
                text=text,
                model=model,
                commit=get_settings().render_git_commit,
            )
            .returning(action_record.c.id)
        ).scalar_one()
    )


def usage_date() -> date:
    return configured_clock().base_now().date()


def record_usage(
    conn: Connection,
    clinic_id: int,
    judge_id: str | None,
    service: str,
    units: int,
    est_cost_usd: float,
) -> None:
    conn.execute(
        conflict_insert(conn, usage)
        .values(
            date=usage_date(),
            clinic_id=clinic_id,
            judge_id=judge_id or "",
            service=service,
            units=units,
            est_cost_usd=est_cost_usd,
        )
        .on_conflict_do_update(
            index_elements=[usage.c.date, usage.c.clinic_id, usage.c.judge_id, usage.c.service],
            set_={
                "units": usage.c.units + units,
                "est_cost_usd": usage.c.est_cost_usd + est_cost_usd,
            },
        )
    )
