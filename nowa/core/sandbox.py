"""Fictional evening seed used by judge provisioning."""

from datetime import time, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import schema as s
from nowa.clock import CAIRO, Clock, FrozenClock
from nowa.core import booking, flows, projection
from nowa.db import write_tx

NAMES = (
    "Karim",
    "Nour",
    "Ahmed",
    "Mona",
    "Salma",
    "Omar",
    "Hana",
    "Youssef",
    "Farida",
    "Ali",
    "Laila",
    "Mostafa",
)
LANGS: tuple[Literal["ar", "en", "franco"], ...] = ("ar", "en", "franco")


def seed_sandbox_evening(engine: Engine, clock: Clock, clinic_id: int) -> None:
    with write_tx(engine) as conn:
        seed_sandbox_evening_in_tx(conn, clock, clinic_id)


def seed_sandbox_evening_in_tx(conn: Connection, clock: Clock, clinic_id: int) -> None:
    # All seed rows and clock positioning commit with the clinic that owns them.
    # Snapshot shared clinic time while the new clinic is visible on this connection.
    clock = FrozenClock(clock.now(clinic_id, conn=conn))
    clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
    if not clinic["is_sandbox"]:
        raise ValueError("Only sandbox clinics may be seeded")
    if conn.execute(
        select(s.idempotency_keys.c.id).where(
            s.idempotency_keys.c.clinic_id == clinic_id,
            s.idempotency_keys.c.command == "sandbox_seed",
        )
    ).first():
        return
    area_ids: list[int] = list(
        conn.execute(select(s.areas.c.id).order_by(s.areas.c.id)).scalars()
    )
    if not area_ids:
        raise ValueError("Sandbox seeding requires reference areas")
    now = clock.now(clinic_id)
    for attempt in range(2):
        days = booking._open_days(conn, clock, clinic_id, now.astimezone(CAIRO).date(), 8)
        choices = [
            (day, paper)
            for day in days
            if (paper := projection.paper_hours(conn, clinic_id, day)) is not None
            and paper[0] > now + timedelta(minutes=60)
        ]
        if choices:
            day, paper = choices[0]
            succeeded = False
            for index, name in enumerate(NAMES):
                result = flows.book_in_tx(
                    conn,
                    clock,
                    booking.BookingRequest(
                        clinic_id,
                        day,
                        name,
                        f"+201000002{index:03d}",
                        LANGS[index % 3],
                        area_ids[index % len(area_ids)],
                        booking.ConsentInput("fictional", "fictional", "self"),
                        f"sandbox_seed:{clinic_id}:{int(clinic['created_at'].timestamp())}:{index}",
                        actor="system",
                    ),
                    confirm=False,
                )
                if isinstance(result, booking.BookingOk):
                    succeeded = True
                elif result.reason == "full":
                    break
                else:
                    raise ValueError("Sandbox seed booking refused: " + result.reason)
            if succeeded:
                offset = int((paper[0] - timedelta(minutes=45) - now).total_seconds())
                conn.execute(
                    s.clinics.update()
                    .where(s.clinics.c.id == clinic_id)
                    .values(clock_offset_s=offset)
                )
                conn.execute(
                    s.idempotency_keys.insert().values(
                        clinic_id=clinic_id,
                        key=f"sandbox_seed_done:{clinic_id}:{int(clinic['created_at'].timestamp())}",
                        command="sandbox_seed",
                        result_json={},
                        created_at=now,
                    )
                )
                return
        if attempt == 0:
            conn.execute(s.clinic_hours.delete().where(s.clinic_hours.c.clinic_id == clinic_id))
            conn.execute(
                s.clinic_hours.insert(),
                [
                    dict(clinic_id=clinic_id, weekday=day, start=time(19), end=time(23))
                    for day in range(7)
                ],
            )
    raise ValueError("Sandbox seeding produced no bookings")
