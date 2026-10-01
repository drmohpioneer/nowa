import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

import httpx
from sqlalchemy import case, select
from sqlalchemy.engine import Connection, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, Clock
from nowa.config import Settings, get_settings
from nowa.core import projection, timers, travel
from nowa.core.travel import LatLng, TravelContext
from nowa.db import conflict_insert, write_tx

logger = logging.getLogger(__name__)


class _HideMapboxRequest(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "api.mapbox.com" not in record.getMessage()


# httpx's request log includes the token and coordinates in the URL.
logging.getLogger("httpx").addFilter(_HideMapboxRequest())


class MapboxAdapter:
    def __init__(self, token: str, timeout_s: float = 10, http: httpx.Client | None = None):
        self.token = token
        self.timeout_s = timeout_s
        self.http = http

    def minutes(
        self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext
    ) -> float | None:
        if get_settings().demo_no_network:
            logger.warning("kind=mapbox outcome=disabled_demo_no_network")
            return None
        url = (
            "https://api.mapbox.com/directions/v5/mapbox/driving-traffic/"
            f"{origin.lng},{origin.lat};{dest.lng},{dest.lat}"
        )
        status: int | str = "network_error"
        try:
            if self.http is None:
                with httpx.Client() as client:
                    response = client.get(
                        url,
                        params={"access_token": self.token, "overview": "false"},
                        timeout=self.timeout_s,
                    )
            else:
                response = self.http.get(
                    url,
                    params={"access_token": self.token, "overview": "false"},
                    timeout=self.timeout_s,
                )
            status = response.status_code
            if status == 200:
                duration = response.json()["routes"][0]["duration"]
                if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                    value = float(duration)
                    if isfinite(value) and value >= 0:
                        return value / 60
        except httpx.TimeoutException:
            status = "timeout"
        except httpx.RequestError:
            status = "network_error"
        except (ValueError, KeyError, IndexError, TypeError, OverflowError):
            pass
        logger.warning("Mapbox check failed status=%s", status)
        return None


class AreaHistoryAdapter:
    def minutes(
        self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext
    ) -> float | None:
        if ctx.area_id is None:
            return None
        local = at.astimezone(CAIRO)
        value = ctx.conn.execute(
            select(s.area_hour_travel.c.mean_min).where(
                s.area_hour_travel.c.clinic_id == ctx.clinic_id,
                s.area_hour_travel.c.area_id == ctx.area_id,
                s.area_hour_travel.c.weekday == local.weekday(),
                s.area_hour_travel.c.hour == local.hour,
                s.area_hour_travel.c.n >= 3,
            )
        ).scalar_one_or_none()
        return float(value) if value is not None else None


class CacheAdapter:
    def minutes(
        self, origin: LatLng, dest: LatLng, at: datetime, *, ctx: TravelContext
    ) -> float | None:
        if ctx.area_id is None:
            return None
        value = ctx.conn.execute(
            select(s.travel_estimates.c.minutes).where(
                s.travel_estimates.c.clinic_id == ctx.clinic_id,
                s.travel_estimates.c.area_id == ctx.area_id,
                s.travel_estimates.c.source == "mapbox",
                s.travel_estimates.c.fetched_at.between(at - timedelta(minutes=45), at),
            )
        ).scalar_one_or_none()
        return float(value) if value is not None else None


def learn(conn: Connection, clinic_id: int, area_id: int, at: datetime, minutes: float) -> None:
    local = at.astimezone(CAIRO)
    table = s.area_hour_travel
    conn.execute(
        conflict_insert(conn, table)
        .values(
            clinic_id=clinic_id,
            area_id=area_id,
            weekday=local.weekday(),
            hour=local.hour,
            mean_min=minutes,
            n=1,
        )
        .on_conflict_do_update(
            index_elements=[table.c.clinic_id, table.c.area_id, table.c.weekday, table.c.hour],
            set_={
                "mean_min": case(
                    (table.c.n >= 50, table.c.mean_min * 0.98 + minutes * 0.02),
                    else_=(table.c.mean_min * table.c.n + minutes) / (table.c.n + 1),
                ),
                "n": case((table.c.n >= 50, 50), else_=table.c.n + 1),
            },
        )
    )


def record_call(conn: Connection, clinic_id: int, settings: Settings) -> None:
    record.record_usage(conn, clinic_id, None, "mapbox", 1, settings.mapbox_usd_per_call)


def _estimate(conn: Connection, clinic_id: int, area_id: int) -> RowMapping | None:
    return (
        conn.execute(
            select(s.travel_estimates).where(
                s.travel_estimates.c.clinic_id == clinic_id,
                s.travel_estimates.c.area_id == area_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _fresh(row: Mapping[str, Any] | RowMapping | None, now: datetime) -> bool:
    if row is None:
        return False
    lifetime = timedelta(minutes=2 if row["source"] == "fetching" else 15)
    return bool(now - lifetime < row["fetched_at"] <= now)


def _upsert_estimate(
    conn: Connection,
    clinic_id: int,
    area_id: int,
    minutes: float | None,
    source: str,
    at: datetime,
) -> None:
    table = s.travel_estimates
    values = dict(minutes=minutes, source=source, fetched_at=at)
    conn.execute(
        conflict_insert(conn, table)
        .values(clinic_id=clinic_id, area_id=area_id, **values)
        .on_conflict_do_update(index_elements=[table.c.clinic_id, table.c.area_id], set_=values)
    )


def _leave_moments(
    conn: Connection,
    clock: Clock,
    evening: Mapping[str, Any] | RowMapping,
) -> dict[int, datetime]:
    cid = evening["clinic_id"]
    now = clock.now(cid)
    snap = projection.load_snapshot(conn, cid, evening["date"], now)
    pace = projection.current_pace(conn, cid, evening["id"])
    cushion: int = conn.execute(
        select(s.clinics.c.cushion_min).where(s.clinics.c.id == cid)
    ).scalar_one()
    rows = conn.execute(
        select(s.bookings)
        .where(
            s.bookings.c.evening_id == evening["id"],
            s.bookings.c.state.in_(projection.WAITING_STATES),
        )
        .order_by(s.bookings.c.order_key, s.bookings.c.id)
    ).mappings()
    moments: dict[int, datetime] = {}
    k = 0
    for row in rows:
        projected = projection.expected_time(snap, k, pace, now)
        if not row["silent"]:
            k += 1
        if row["state"] == "booked" and row["source"] == "chat" and row["area_id"] is not None:
            area_id = row["area_id"]
            drive = travel.minutes(conn, cid, now, area_id=area_id)
            leave = projected - timedelta(minutes=cushion + drive * 1.3 + 10)
            moments[area_id] = min(moments.get(area_id, leave), leave)
    return moments


def arm_travel_checks(conn: Connection, clock: Clock, evening_id: int) -> None:
    evening = (
        conn.execute(
            select(s.evenings)
            .where(
                s.evenings.c.id == evening_id,
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    clinic = (
        conn.execute(
            select(s.clinics).where(
                s.clinics.c.id == evening["clinic_id"],
            )
        )
        .mappings()
        .one()
    )
    if not isinstance(travel.chain_for(clinic, get_settings()).doctor[0], MapboxAdapter):
        return
    now = clock.now(evening["clinic_id"])
    moments = (
        {} if evening["state"] in {"closed", "cancelled"} else _leave_moments(conn, clock, evening)
    )
    pending = (
        conn.execute(
            select(s.timers).where(
                s.timers.c.status == "pending",
                s.timers.c.idempotency_key.startswith(
                    f"travel_check:{evening_id}:", autoescape=True
                ),
            )
        )
        .mappings()
        .all()
    )
    for row in pending:
        area_id = row["payload_json"]["area_id"]
        if area_id not in moments or moments[area_id] <= now:
            timers.cancel_timer(conn, row["idempotency_key"])
    for area_id, leave in moments.items():
        if leave <= now:
            continue
        estimate = _estimate(conn, evening["clinic_id"], area_id)
        prefix = f"travel_check:{evening_id}:{area_id}:"
        matching = [row for row in pending if row["idempotency_key"].startswith(prefix)]
        due = max(leave - timedelta(minutes=30), now)
        if _fresh(estimate, now):
            assert estimate is not None
            if estimate["source"] == "fetching":
                for row in matching:
                    timers.cancel_timer(conn, row["idempotency_key"])
                continue
            due = max(due, estimate["fetched_at"] + timedelta(minutes=15))
        if len(matching) == 1 and matching[0]["idempotency_key"].split(":")[-2] == str(
            int(due.timestamp())
        ):
            continue
        timers.rearm(
            conn,
            clock,
            "travel_check",
            evening_id,
            due,
            {"evening_id": evening_id, "area_id": area_id},
            key_prefix=prefix,
        )


def handle_travel_check(ctx: timers.TimerContext, payload: dict[str, Any]) -> None:
    from nowa.core import timing

    conn = ctx.conn
    evening_id, area_id = int(payload["evening_id"]), int(payload["area_id"])
    evening = timing._evening(conn, ctx.clinic_id, evening_id)
    if evening["state"] in {"closed", "cancelled"}:
        return
    clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == ctx.clinic_id)).mappings().one()
    settings = get_settings()
    adapter = travel.chain_for(clinic, settings).doctor[0]
    if not isinstance(adapter, MapboxAdapter):
        return
    leave = _leave_moments(conn, ctx.clock, evening).get(area_id)
    now = ctx.clock.now(ctx.clinic_id)
    if leave is None or leave <= now:
        return
    if _fresh(_estimate(conn, ctx.clinic_id, area_id), now):
        arm_travel_checks(conn, ctx.clock, evening_id)
        return
    area = conn.execute(select(s.areas).where(s.areas.c.id == area_id)).mappings().one()
    origin, dest = LatLng(area["lat"], area["lng"]), LatLng(clinic["lat"], clinic["lng"])
    engine, clock, cid = conn.engine, ctx.clock, ctx.clinic_id
    _upsert_estimate(conn, cid, area_id, None, "fetching", now)

    def fetch() -> None:
        at = clock.now(cid)
        value = adapter.minutes(origin, dest, at, ctx=TravelContext(conn, cid, area_id))
        if value is not None:
            # Accounting survives any downstream cache/learning/recompute failure.
            with write_tx(engine) as accounting:
                record_call(accounting, cid, settings)
        with write_tx(engine) as write:
            _upsert_estimate(
                write, cid, area_id, value, "failed" if value is None else "mapbox", at
            )
            if value is not None:
                learn(write, cid, area_id, at, value)
            timing.recompute(write, clock, evening_id)

    ctx.after_commit.append(fetch)
