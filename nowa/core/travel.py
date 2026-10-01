from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from math import asin, ceil, cos, isfinite, radians, sin, sqrt
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Connection, RowMapping

from nowa import schema as s
from nowa.config import Settings, get_settings


@dataclass(frozen=True, repr=False)
class LatLng:
    lat: float
    lng: float

    def __post_init__(self) -> None:
        if not (
            isfinite(self.lat)
            and -90 <= self.lat <= 90
            and isfinite(self.lng)
            and -180 <= self.lng <= 180
        ):
            raise ValueError("Invalid coordinates")


@dataclass(frozen=True)
class TravelContext:
    conn: Connection
    clinic_id: int
    area_id: int | None


class TravelAdapter(Protocol):
    def minutes(
        self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext
    ) -> float | None: ...


class FixedAreaAdapter:
    def minutes(self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext) -> float:
        a, b = radians(origin.lat), radians(dest.lat)
        h = sin((b - a) / 2) ** 2 + cos(a) * cos(b) * sin(radians(dest.lng - origin.lng) / 2) ** 2
        km = 6371 * 2 * asin(min(1, sqrt(h)))
        return float(min(120, max(5, ceil(km * 2.5) + 5)))


@dataclass(frozen=True)
class SafeTimeAdapter:
    safe_drive_min: float

    def minutes(self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext) -> float:
        return self.safe_drive_min


@dataclass(frozen=True)
class TravelChains:
    patient: list[TravelAdapter]
    doctor: list[TravelAdapter]


def chain_for(clinic: Mapping[str, Any] | RowMapping, settings: Settings) -> TravelChains:
    from nowa.core.travel_mapbox import AreaHistoryAdapter, CacheAdapter, MapboxAdapter

    fallback = SafeTimeAdapter(float(clinic["safe_drive_min"]))
    if clinic["is_sandbox"]:
        return TravelChains([FixedAreaAdapter(), fallback], [FixedAreaAdapter(), fallback])
    if settings.mapbox_token and not settings.demo_no_network:
        return TravelChains(
            [CacheAdapter(), AreaHistoryAdapter(), fallback],
            [MapboxAdapter(settings.mapbox_token, settings.mapbox_timeout_s), fallback],
        )
    if settings.demo_mode:
        return TravelChains([FixedAreaAdapter(), fallback], [FixedAreaAdapter(), fallback])
    return TravelChains([fallback], [fallback])


def minutes(
    conn: Connection,
    clinic_id: int,
    at: datetime,
    origin: LatLng | None = None,
    area_id: int | None = None,
    *,
    doctor: bool = False,
) -> float:
    clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
    if origin is None and area_id is not None:
        area = conn.execute(select(s.areas).where(s.areas.c.id == area_id)).mappings().one_or_none()
        if area is None:
            raise ValueError("Invalid area")
        origin = LatLng(area["lat"], area["lng"])
    if origin is None:
        return float(clinic["safe_drive_min"])
    dest = LatLng(clinic["lat"], clinic["lng"])
    chains = chain_for(clinic, get_settings())
    chain = chains.doctor if doctor else chains.patient
    ctx = TravelContext(conn, clinic_id, area_id)
    for adapter in chain:
        # The transactional form uses the remaining doctor chain only.
        from nowa.core.travel_mapbox import MapboxAdapter

        if isinstance(adapter, MapboxAdapter):
            continue
        value = adapter.minutes(origin, dest, at, ctx=ctx)
        if value is not None:
            return value
    return float(clinic["safe_drive_min"])
