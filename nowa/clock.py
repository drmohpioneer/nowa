from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa.schema import clinics

CAIRO = ZoneInfo("Africa/Cairo")


class Clock(Protocol):
    def now(self, clinic_id: int, conn: Connection | None = None) -> datetime: ...
    def base_now(self) -> datetime: ...


class SystemClock:
    def now(self, clinic_id: int, conn: Connection | None = None) -> datetime:
        return self.base_now()

    def base_now(self) -> datetime:
        return datetime.now(CAIRO)


class FrozenClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("FrozenClock requires an aware datetime")
        self._instant = start.astimezone(UTC)

    def now(self, clinic_id: int, conn: Connection | None = None) -> datetime:
        return self._instant.astimezone(CAIRO)

    def base_now(self) -> datetime:
        return self._instant.astimezone(CAIRO)

    def advance(self, *, minutes: float) -> None:
        self._instant += timedelta(minutes=minutes)


class ClinicOffsetClock:
    def __init__(self, base: Clock, engine: Engine) -> None:
        self.base = base
        self.engine = engine

    def now(self, clinic_id: int, conn: Connection | None = None) -> datetime:
        statement = select(clinics.c.clock_offset_s).where(clinics.c.id == clinic_id)
        if conn is not None:
            offset: int = conn.execute(statement).scalar_one()
        else:
            with self.engine.connect() as own_conn:
                offset = own_conn.execute(statement).scalar_one()
        return (self.base.now(clinic_id).astimezone(UTC) + timedelta(seconds=offset)).astimezone(
            CAIRO
        )

    def base_now(self) -> datetime:
        return self.base.base_now()
