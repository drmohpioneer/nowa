"""Mapbox v6 contract tests: all HTTP is intercepted in-process."""

import logging

import httpx
import pytest
from sqlalchemy import event, select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core.geocoding import BBOX, ENDPOINT, TYPES, GeocodeAdapter, geocode_origin
from nowa.core.travel import LatLng
from nowa.db import write_tx


def feature(lng=31.4, lat=30.2, name="Fictional District", kind="neighborhood"):
    return {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {"name": name, "feature_type": kind},
            }
        ]
    }


@pytest.fixture
def mapbox_clinic(engine, clinic_id, monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "fictional-mapbox-token")
    monkeypatch.setenv("MAPBOX_USD_PER_CALL", "0.007")
    get_settings.cache_clear()
    with engine.connect() as conn:
        return dict(
            conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
        )


@pytest.mark.parametrize("lang,expected", [("ar", "ar"), ("en", "en"), ("franco", "en")])
def test_forward_endpoint_bounds_permanent_storage_and_timeout(lang, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=feature())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = GeocodeAdapter("test-secret", 2.5, http).locate(
            "Fictional District", LatLng(30.1, 31.3), lang
        )
    assert result.name == "Fictional District"
    assert result.point == LatLng(30.2, 31.4)
    request = calls[0]
    assert str(request.url).split("?")[0] == ENDPOINT
    assert dict(request.url.params) == {
        "access_token": "test-secret",
        "q": "Fictional District",
        "bbox": BBOX,
        "proximity": "31.3,30.1",
        "limit": "1",
        "types": TYPES,
        "language": expected,
        "permanent": "true",
        "autocomplete": "false",
    }
    assert set(request.extensions["timeout"].values()) == {2.5}


@pytest.mark.parametrize(
    "body",
    [
        feature(lng=30.74),
        feature(lng=31.91),
        feature(lat=29.69),
        feature(lat=30.41),
        feature(lng=True),
        feature(lat="30.2"),
        feature(kind="address"),
        feature(name=""),
        {"features": []},
        {},
        {"features": [None]},
        {"features": None},
    ],
)
def test_rejects_out_of_bounds_or_malformed_features(body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        assert GeocodeAdapter("test", http=http).locate("District", LatLng(30, 31), "ar") is None


@pytest.mark.parametrize("failure", [401, 429, 500, "timeout", "network", "json"])
def test_errors_are_safe_and_logs_contain_no_private_values(failure, caplog):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("test-secret private query", request=request)
        if failure == "network":
            raise httpx.ConnectError("test-secret private query", request=request)
        if failure == "json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(failure)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with caplog.at_level(logging.DEBUG):
            assert (
                GeocodeAdapter("test-secret", http=http).locate(
                    "private query", LatLng(30.1, 31.3), "en"
                )
                is None
            )
    assert "Mapbox geocode failed status=" in caplog.text
    assert not any(
        value in caplog.text for value in ("test-secret", "private query", "31.3", "30.1")
    )


def test_hit_cache_usage_and_reentrant_reservation(engine, frozen_clock, mapbox_clinic):
    calls = []

    def handler(request):
        assert engine.pool.checkedout() == 0  # HTTP has no open database connection.
        calls.append(request)
        assert geocode_origin(engine, frozen_clock, mapbox_clinic, ["DISTRICT"], "ar") is None
        return httpx.Response(200, json=feature())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = GeocodeAdapter("test", http=http)
        area_id = geocode_origin(
            engine, frozen_clock, mapbox_clinic, ["District"], "en", adapter=adapter
        )
        assert (
            geocode_origin(
                engine, frozen_clock, mapbox_clinic, [" district "], "en", adapter=adapter
            )
            == area_id
        )
    assert len(calls) == 1
    with engine.connect() as conn:
        area = conn.execute(select(s.areas).where(s.areas.c.id == area_id)).mappings().one()
        assert area["source"] == "geocoded" and (area["lat"], area["lng"]) == (30.2, 31.4)
        cache = conn.execute(select(s.geocode_cache)).mappings().one()
        assert cache["query"] == "district" and cache["area_id"] == area_id
        assert cache["fetched_at"] == frozen_clock.now(mapbox_clinic["id"])
        usage = conn.execute(select(s.usage)).mappings().one()
        assert (usage["clinic_id"], usage["service"], usage["units"], usage["est_cost_usd"]) == (
            mapbox_clinic["id"],
            "mapbox_geocode",
            1,
            0.007,
        )


def test_miss_then_raw_hit_both_cached(engine, frozen_clock, mapbox_clinic):
    calls = []

    def handler(request):
        calls.append(request.url.params["q"])
        return httpx.Response(200, json={"features": []} if len(calls) == 1 else feature())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = GeocodeAdapter("test", http=http)
        queries = ["normalized candidate", "Raw District"]
        area_id = geocode_origin(
            engine, frozen_clock, mapbox_clinic, queries, "ar", adapter=adapter
        )
        assert (
            geocode_origin(engine, frozen_clock, mapbox_clinic, queries, "ar", adapter=adapter)
            == area_id
        )
    assert calls == queries
    with engine.connect() as conn:
        assert conn.execute(select(s.usage.c.units)).scalar_one() == 2
        assert len(conn.execute(select(s.geocode_cache)).all()) == 2


@pytest.mark.parametrize("failure", ["miss", "bounds", "timeout", "error"])
def test_null_cache_expires_after_24_hours(engine, frozen_clock, mapbox_clinic, failure):
    calls = []

    def handler(request):
        assert engine.pool.checkedout() == 0
        calls.append(request)
        # A concurrent request observes the renewed reservation, including at expiry.
        assert geocode_origin(engine, frozen_clock, mapbox_clinic, ["DISTRICT"], "ar") is None
        if len(calls) > 1:
            return httpx.Response(200, json=feature())
        if failure == "timeout":
            raise httpx.ReadTimeout("fictional", request=request)
        if failure == "error":
            return httpx.Response(500)
        return httpx.Response(
            200, json=feature(lat=31) if failure == "bounds" else {"features": []}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = GeocodeAdapter("test", http=http)

        def lookup():
            return geocode_origin(
                engine, frozen_clock, mapbox_clinic, ["District"], "en", adapter=adapter
            )

        assert lookup() is None
        frozen_clock.advance(minutes=24 * 60 - 1 / 60)
        assert lookup() is None
        assert len(calls) == 1
        frozen_clock.advance(minutes=1 / 60)
        area_id = lookup()
        assert area_id is not None
        assert len(calls) == 2
        # A successful entry stays permanent, even well beyond the null TTL.
        frozen_clock.advance(minutes=366 * 24 * 60)
        assert lookup() == area_id
        assert len(calls) == 2
    with engine.connect() as conn:
        assert sum(conn.execute(select(s.usage.c.units)).scalars()) == 2
        assert conn.execute(select(s.geocode_cache.c.area_id)).scalar_one() == area_id


def test_expired_interrupted_reservation_can_retry(engine, frozen_clock, mapbox_clinic):
    with write_tx(engine) as conn:
        conn.execute(
            s.geocode_cache.insert().values(
                query="district", area_id=None, fetched_at=frozen_clock.now(mapbox_clinic["id"])
            )
        )
    frozen_clock.advance(minutes=24 * 60)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"features": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = GeocodeAdapter("test", http=http)
        for _ in range(2):
            assert (
                geocode_origin(
                    engine, frozen_clock, mapbox_clinic, ["district"], "en", adapter=adapter
                )
                is None
            )
    assert len(calls) == 1
    with engine.connect() as conn:
        assert conn.execute(select(s.geocode_cache.c.fetched_at)).scalar_one() == (
            frozen_clock.now(mapbox_clinic["id"])
        )


@pytest.mark.parametrize("mode", ["sandbox", "offline", "no_token", "no_token_real"])
def test_chain_exclusions_never_call_or_cache(
    engine, frozen_clock, mapbox_clinic, monkeypatch, mode
):
    clinic = dict(mapbox_clinic)
    if mode == "sandbox":
        clinic["is_sandbox"] = True
    elif mode == "offline":
        monkeypatch.setenv("DEMO_NO_NETWORK", "true")
    else:
        monkeypatch.delenv("MAPBOX_TOKEN")
        if mode == "no_token_real":
            monkeypatch.setenv("DEMO_MODE", "false")
            monkeypatch.setenv("PUBLIC_BASE_URL", "https://clinic.example")
            monkeypatch.setenv("DATABASE_URL", "postgresql://unused/production")
    get_settings.cache_clear()

    def handler(request):
        pytest.fail("excluded chain called Mapbox")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert (
            geocode_origin(
                engine,
                frozen_clock,
                clinic,
                ["District"],
                "en",
                adapter=GeocodeAdapter("test", http=http),
            )
            is None
        )
    with engine.connect() as conn:
        assert not conn.execute(select(s.geocode_cache)).all()
        assert not conn.execute(select(s.usage)).all()


def test_usage_survives_result_write_failure(engine, frozen_clock, mapbox_clinic):
    def fail_area_write(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO areas"):
            raise RuntimeError("injected result write failure")

    event.listen(engine, "before_cursor_execute", fail_area_write)
    try:
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=feature()))
        ) as http:
            with pytest.raises(RuntimeError, match="injected"):
                geocode_origin(
                    engine,
                    frozen_clock,
                    mapbox_clinic,
                    ["District"],
                    "en",
                    adapter=GeocodeAdapter("test", http=http),
                )
    finally:
        event.remove(engine, "before_cursor_execute", fail_area_write)
    with engine.connect() as conn:
        assert conn.execute(select(s.usage.c.units)).scalar_one() == 1
        assert conn.execute(select(s.geocode_cache.c.area_id)).scalar_one() is None


def test_cache_is_shared_but_usage_belongs_to_calling_clinic(engine, frozen_clock, mapbox_clinic):
    from nowa.demo.template import CLINIC

    with write_tx(engine) as conn:
        other = dict(CLINIC["clinic"], slug="fictional-other")
        other_id = conn.execute(
            s.clinics.insert().values(**other).returning(s.clinics.c.id)
        ).scalar_one()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=feature()))
    ) as http:
        area_id = geocode_origin(
            engine,
            frozen_clock,
            mapbox_clinic,
            ["District"],
            "en",
            adapter=GeocodeAdapter("test", http=http),
        )
    assert (
        geocode_origin(engine, frozen_clock, dict(other, id=other_id), ["District"], "ar")
        == area_id
    )
    with engine.connect() as conn:
        assert conn.execute(select(s.usage.c.clinic_id)).scalar_one() == mapbox_clinic["id"]


@pytest.mark.parametrize("failure", ["miss", "bounds", "timeout"])
def test_failed_queries_are_accounted_once_and_cached(engine, frozen_clock, mapbox_clinic, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("fictional", request=request)
        return httpx.Response(
            200, json=feature(lat=31) if failure == "bounds" else {"features": []}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = GeocodeAdapter("test", http=http)
        for _ in range(2):
            assert (
                geocode_origin(
                    engine, frozen_clock, mapbox_clinic, ["District"], "en", adapter=adapter
                )
                is None
            )
    assert len(calls) == 1
    with engine.connect() as conn:
        assert conn.execute(select(s.usage.c.units)).scalar_one() == 1
        assert conn.execute(select(s.geocode_cache.c.area_id)).scalar_one() is None


@pytest.mark.parametrize(
    "query", ["", "x" * 257, "word " * 21, "bad;query", "01012345678", "٠١٠ ١٢٣٤ ٥٦٧٨"]
)
def test_invalid_or_phone_queries_never_leave_process(engine, frozen_clock, mapbox_clinic, query):
    def handler(request):
        pytest.fail("invalid input reached HTTP")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert (
            geocode_origin(
                engine,
                frozen_clock,
                mapbox_clinic,
                [query],
                "en",
                adapter=GeocodeAdapter("test", http=http),
            )
            is None
        )
    with engine.connect() as conn:
        assert not conn.execute(select(s.geocode_cache)).all()
        assert not conn.execute(select(s.usage)).all()


def test_geocoded_area_uses_existing_per_clinic_history(engine, frozen_clock, mapbox_clinic):
    from nowa.core import travel
    from nowa.core.travel_mapbox import learn

    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=feature()))
    ) as http:
        area_id = geocode_origin(
            engine,
            frozen_clock,
            mapbox_clinic,
            ["District"],
            "en",
            adapter=GeocodeAdapter("test", http=http),
        )
    clinic_id = mapbox_clinic["id"]
    now = frozen_clock.now(clinic_id)
    with write_tx(engine) as conn:
        assert (
            travel.minutes(conn, clinic_id, now, area_id=area_id) == mapbox_clinic["safe_drive_min"]
        )
        for _ in range(3):
            learn(conn, clinic_id, area_id, now, 27)
        assert travel.minutes(conn, clinic_id, now, area_id=area_id) == 27


def test_migration_preserves_reference_ids_and_usage(tmp_path, frozen_clock):
    from alembic import command
    from alembic.script import ScriptDirectory

    from nowa.__main__ import migrate, migration_config
    from nowa.db import create_db_engine
    from nowa.reference import AREAS

    engine = create_db_engine(f"sqlite:///{tmp_path / 'area-upgrade.db'}")
    config = migration_config()
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "29")
            for index, (name_en, name_ar, lat, lng) in enumerate(AREAS, 1):
                conn.exec_driver_sql(
                    "INSERT INTO areas (id, name_en, name_ar, lat, lng) VALUES (?, ?, ?, ?, ?)",
                    (index, name_en, name_ar, lat, lng),
                )
            before = conn.exec_driver_sql("SELECT * FROM areas ORDER BY id").all()
            conn.exec_driver_sql(
                "INSERT INTO usage (date,clinic_id,judge_id,service,units,est_cost_usd) "
                "VALUES ('2026-09-30',1,'','mapbox',3,0.006)"
            )
            usage_before = conn.execute(select(s.usage)).all()
        migrate(engine)
        with engine.connect() as conn:
            assert (
                conn.exec_driver_sql(
                    "SELECT id,name_ar,name_en,lat,lng FROM areas ORDER BY id"
                ).all()
                == before
            )
            assert set(conn.execute(select(s.areas.c.source)).scalars()) == {"reference"}
            assert conn.execute(select(s.usage)).all() == usage_before
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert ScriptDirectory.from_config(config).get_heads() == ["31"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", [False, True])
def test_owned_http_client_and_transport_close_without_threads(monkeypatch, failure):
    import threading

    from nowa.core import geocoding

    before = set(threading.enumerate())
    clients = []
    transports = []
    client_type = httpx.Client

    class TrackingTransport(httpx.MockTransport):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def handler(request):
        if failure:
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, json=feature())

    def factory():
        transport = TrackingTransport(handler)
        client = client_type(transport=transport)
        transports.append(transport)
        clients.append(client)
        return client

    monkeypatch.setattr(geocoding.httpx, "Client", factory)
    result = GeocodeAdapter("fictional").locate("Fictional District", LatLng(30, 31), "en")
    assert (result is None) == failure
    assert len(clients) == 1 and clients[0].is_closed and transports[0].closed
    assert set(threading.enumerate()) == before
