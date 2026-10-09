from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa.clock import SystemClock
from nowa.config import get_settings
from nowa.core.learning import learn_no_show
from nowa.db import conflict_insert, write_tx
from nowa.demo.template import CLINIC, HISTORY
from nowa.schema import (
    clinic_hours,
    clinic_info,
    clinics,
    daily_totals,
    doctors,
    learned_no_show,
    learned_pace,
    learned_start_gap,
)


def seed(engine: Engine) -> None:
    settings = get_settings()
    if not settings.demo_mode:
        raise ValueError("seed is only allowed when DEMO_MODE is true")
    with write_tx(engine) as conn:
        existing = conn.execute(
            select(clinics.c.id).where(clinics.c.slug == "dr-hesham")
        ).scalar_one_or_none()
        if existing is not None:
            if (
                conn.execute(
                    select(learned_no_show.c.clinic_id).where(
                        learned_no_show.c.clinic_id == existing
                    )
                ).first()
                is None
            ):
                seed_history(conn, existing)
            return
        clinic_id: int = conn.execute(
            clinics.insert()
            .values(**CLINIC["clinic"], created_at=SystemClock().now(0))
            .returning(clinics.c.id)
        ).scalar_one()
        conn.execute(
            doctors.insert().values(
                clinic_id=clinic_id,
                **CLINIC["doctor"],
                password_hash=PasswordHasher().hash(settings.demo_doctor_password),
            )
        )
        for table, key in ((clinic_hours, "hours"), (clinic_info, "info")):
            conn.execute(table.insert(), [dict(clinic_id=clinic_id, **row) for row in CLINIC[key]])
        seed_history(conn, clinic_id)
        conn.execute(learned_pace.insert().values(clinic_id=clinic_id, **CLINIC["learned_pace"]))
        conn.execute(
            learned_start_gap.insert().values(
                clinic_id=clinic_id,
                **CLINIC["learned_start_gap"],
            )
        )


def seed_history(conn: Connection, clinic_id: int) -> None:
    for row in HISTORY:
        conn.execute(
            conflict_insert(conn, daily_totals)
            .values(clinic_id=clinic_id, **row)
            .on_conflict_do_nothing(index_elements=[daily_totals.c.clinic_id, daily_totals.c.date])
        )
    learn_no_show(conn, clinic_id)
