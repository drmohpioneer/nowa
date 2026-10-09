"""Bounded origin lookup; HTTP runs outside transactions.

Successful query-cache entries never expire. Null entries (misses, errors,
timeouts or interrupted attempts) expire after 24 hours; the next request
atomically reserves the query again before calling the provider.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.engine import Engine

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core.areas import normalize
from nowa.core.travel import LatLng, chain_for
from nowa.core.travel_mapbox import MapboxAdapter
from nowa.db import conflict_insert, write_tx

logger = logging.getLogger(__name__)
ENDPOINT = "https://api.mapbox.com/search/geocode/v6/forward"
BBOX = "30.75,29.70,31.90,30.40"
TYPES = "place,locality,neighborhood,district"


@dataclass(frozen=True, repr=False)
class GeocodeHit:
    name: str
    point: LatLng


def valid_query(query: str) -> bool:
    """Provider limits, and no phone numbers in a shared permanent origin cache."""
    digits = "".join(c for c in normalize(query) if c.isdecimal())
    return bool(
        normalize(query)
        and len(query) <= 256
        and len(query.split()) <= 20
        and ";" not in query
        and len(digits) < 8
    )


class GeocodeAdapter:
    def __init__(self, token: str, timeout_s: float = 10, http: httpx.Client | None = None) -> None:
        self.token = token
        self.timeout_s = timeout_s
        self.http = http

    def locate(self, query: str, proximity: LatLng, lang: str) -> GeocodeHit | None:
        if get_settings().demo_no_network or not valid_query(query):
            return None
        params: dict[str, str | int] = {
            "access_token": self.token,
            "q": query,
            "bbox": BBOX,
            "proximity": f"{proximity.lng},{proximity.lat}",
            "limit": 1,
            "types": TYPES,
            "language": "ar" if lang == "ar" else "en",
            "permanent": "true",
            "autocomplete": "false",
        }
        status: str | int = "network_error"
        try:
            if self.http is None:
                with httpx.Client() as client:
                    response = client.get(ENDPOINT, params=params, timeout=self.timeout_s)
            else:
                response = self.http.get(ENDPOINT, params=params, timeout=self.timeout_s)
            status = response.status_code
            if status == 200:
                features = response.json()["features"]
                if features == []:
                    return None
                feature = features[0]
                props = feature["properties"]
                geometry = feature["geometry"]
                lng, lat = geometry["coordinates"]
                name = props.get("name_preferred") or props["name"]
                if (
                    geometry["type"] == "Point"
                    and props["feature_type"] in TYPES.split(",")
                    and type(lng) in (int, float)
                    and type(lat) in (int, float)
                    and 30.75 <= lng <= 31.90
                    and 29.70 <= lat <= 30.40
                    and isinstance(name, str)
                    and name.strip()
                    and len(name) <= 256
                    and not re.search(r"\d{8,}", name)
                ):
                    return GeocodeHit(name.strip(), LatLng(float(lat), float(lng)))
        except httpx.TimeoutException:
            status = "timeout"
        except httpx.RequestError:
            status = "network_error"
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError):
            pass
        # Never log the query, response, exception text, coordinates or token.
        logger.warning("Mapbox geocode failed status=%s", status)
        return None


def geocode_origin(
    engine: Engine,
    clock: Clock,
    clinic: Mapping[str, Any],
    queries: Sequence[str],
    lang: str,
    *,
    adapter: GeocodeAdapter | None = None,
) -> int | None:
    """Resolve queries in order; reserve each key before HTTP, account after HTTP.

    Null entries suppress repeat calls for 24 hours, including after process
    failure. Hits remain permanent. Neither HTTP nor a model runs in these write_txs.
    """
    settings = get_settings()
    if not any(isinstance(a, MapboxAdapter) for a in chain_for(clinic, settings).doctor):
        return None
    client = adapter or GeocodeAdapter(settings.mapbox_token, settings.mapbox_timeout_s)
    proximity = LatLng(clinic["lat"], clinic["lng"])
    for query in queries:
        if not valid_query(query):
            continue
        key = normalize(query)
        with write_tx(engine) as conn:
            now = clock.now(clinic["id"], conn=conn).astimezone(UTC)
            claimed = conn.execute(
                conflict_insert(conn, s.geocode_cache)
                .values(query=key, area_id=None, fetched_at=now)
                .on_conflict_do_update(
                    index_elements=[s.geocode_cache.c.query],
                    set_={"fetched_at": now},
                    where=s.geocode_cache.c.area_id.is_(None)
                    & (s.geocode_cache.c.fetched_at <= now - timedelta(hours=24)),
                )
            ).rowcount
            if not claimed:
                cached: int | None = conn.execute(
                    select(s.geocode_cache.c.area_id).where(s.geocode_cache.c.query == key)
                ).scalar_one()
                if cached is not None:
                    return cached
                continue
        hit = client.locate(query, proximity, lang)
        # Independent accounting survives a later cache/result write failure.
        with write_tx(engine) as conn:
            record.record_usage(
                conn, clinic["id"], None, "mapbox_geocode", 1, settings.mapbox_usd_per_call
            )
        if hit is None:
            continue
        with write_tx(engine) as conn:
            conn.execute(
                conflict_insert(conn, s.areas)
                .values(
                    name_en=hit.name,
                    name_ar=hit.name,
                    lat=hit.point.lat,
                    lng=hit.point.lng,
                    source="geocoded",
                )
                .on_conflict_do_nothing(index_elements=[s.areas.c.name_en])
            )
            area_id: int = conn.execute(
                select(s.areas.c.id).where(s.areas.c.name_en == hit.name)
            ).scalar_one()
            conn.execute(
                s.geocode_cache.update()
                .where(s.geocode_cache.c.query == key)
                .values(area_id=area_id, fetched_at=clock.now(clinic["id"], conn=conn))
            )
        return area_id
    return None
