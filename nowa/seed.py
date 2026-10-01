from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.engine import Engine

from nowa.clock import SystemClock
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.demo.template import CLINIC
from nowa.schema import clinic_hours, clinic_info, clinics, doctors, learned_pace, learned_start_gap


def seed(engine: Engine) -> None:
    settings = get_settings()
    if not settings.demo_mode:
        raise ValueError("seed is only allowed when DEMO_MODE is true")
    with write_tx(engine) as conn:
        if conn.execute(select(clinics.c.id).where(clinics.c.slug == "dr-hesham")).first():
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
        conn.execute(learned_pace.insert().values(clinic_id=clinic_id, **CLINIC["learned_pace"]))
        conn.execute(
            learned_start_gap.insert().values(
                clinic_id=clinic_id,
                **CLINIC["learned_start_gap"],
            )
        )
