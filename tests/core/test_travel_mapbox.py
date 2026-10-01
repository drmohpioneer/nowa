import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from nowa import schema as s
from nowa import worker
from nowa.__main__ import migration_config
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core import timing, timing_handlers, travel, travel_mapbox
from nowa.core.timers import TimerContext, rearm
from nowa.db import write_tx
from tests.core.support import BASE, move, row, setup
from tests.helpers.worker import HandlerSetup, assert_handler_idempotent, drain
from tests.web.support import ORIGIN

POINT = travel.LatLng(30.12345, 31.23456)
DEST = travel.LatLng(30.34567, 31.45678)


@pytest.fixture
def fake_mapbox(monkeypatch):
    class FakeMapbox(travel_mapbox.MapboxAdapter):
        calls = []
        values = [45.0]

        def minutes(self, origin, dest, at, *, ctx):
            assert not ctx.conn.in_transaction(), "HTTP inside a transaction"
            self.calls.append((ctx.clinic_id, ctx.area_id, at))
            return self.values.pop(0) if len(self.values) > 1 else self.values[0]

    monkeypatch.setattr(travel_mapbox, "MapboxAdapter", FakeMapbox)
    return FakeMapbox


@pytest.mark.parametrize(
    "status,body,want",
    [
        (200, {"routes": [{"duration": 1230}]}, 20.5),
        (401, {}, None),
        (429, {}, None),
        (200, {}, None),
        (200, {"routes": []}, None),
        (200, {"routes": [{"duration": "1230"}]}, None),
        (200, {"routes": [{"duration": True}]}, None),
        (200, {"routes": [{"duration": float("inf")}]}, None),
        (200, {"routes": [{"duration": -1}]}, None),
        (200, [], None),
    ],
)
def test_mapbox_response(engine, clinic_id, status, body, want, caplog):
    requests = []

    def respond(request):
        requests.append(request)
        # JSON cannot serialize Infinity in httpx's fixture constructor.
        import json

        return httpx.Response(status, content=json.dumps(body))

    caplog.set_level(logging.INFO)
    with engine.connect() as conn, httpx.Client(transport=httpx.MockTransport(respond)) as http:
        ctx = travel.TravelContext(conn, clinic_id, 1)
        adapter = travel_mapbox.MapboxAdapter("secret-mapbox-token", http=http)
        assert adapter.minutes(POINT, DEST, BASE, ctx=ctx) == want
        assert not conn.in_transaction()
    req = requests[0]
    assert req.url.path.endswith("31.23456,30.12345;31.45678,30.34567")
    assert req.url.params["access_token"] == "secret-mapbox-token"
    assert req.url.params["overview"] == "false"
    assert req.extensions["timeout"]["read"] == 10
    assert len(caplog.messages) == (0 if want is not None else 1)
    for private in ("secret-mapbox-token", "30.12345", "31.23456", "30.34567", "31.45678"):
        assert private not in caplog.text


@pytest.mark.parametrize("failure", ["timeout", "network", "invalid_json"])
def test_mapbox_transport_failure(engine, clinic_id, failure, caplog):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret coordinates", request=request)
        if failure == "network":
            raise httpx.ConnectError("secret token", request=request)
        return httpx.Response(200, content=b"invalid-json")

    with engine.connect() as conn, httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert (
            travel_mapbox.MapboxAdapter("token", http=http).minutes(
                POINT,
                DEST,
                BASE,
                ctx=travel.TravelContext(conn, clinic_id, 1),
            )
            is None
        )
    assert len(caplog.messages) == 1
    assert (
        caplog.messages[0]
        == "Mapbox check failed status="
        + {
            "timeout": "timeout",
            "network": "network_error",
            "invalid_json": "200",
        }[failure]
    )


@pytest.mark.parametrize(
    "sandbox,token,offline,demo,patient,doctor",
    [
        (True, "", False, False, travel.FixedAreaAdapter, travel.FixedAreaAdapter),
        (True, "token", False, True, travel.FixedAreaAdapter, travel.FixedAreaAdapter),
        (False, "token", False, True, travel_mapbox.CacheAdapter, travel_mapbox.MapboxAdapter),
        (False, "token", False, False, travel_mapbox.CacheAdapter, travel_mapbox.MapboxAdapter),
        (False, "token", True, True, travel.FixedAreaAdapter, travel.FixedAreaAdapter),
        (False, "token", True, False, travel.SafeTimeAdapter, travel.SafeTimeAdapter),
        (False, "", False, True, travel.FixedAreaAdapter, travel.FixedAreaAdapter),
        (False, "", False, False, travel.SafeTimeAdapter, travel.SafeTimeAdapter),
    ],
)
def test_chains(sandbox, token, offline, demo, patient, doctor):
    settings = get_settings().model_copy(
        update={
            "mapbox_token": token,
            "demo_no_network": offline,
            "demo_mode": demo,
        }
    )
    chains = travel.chain_for({"is_sandbox": sandbox, "safe_drive_min": 45}, settings)
    assert isinstance(chains.patient[0], patient)
    assert isinstance(chains.doctor[0], doctor)
    assert isinstance(chains.patient[-1], travel.SafeTimeAdapter)
    assert isinstance(chains.doctor[-1], travel.SafeTimeAdapter)


@pytest.mark.parametrize(
    "age,source,want",
    [
        (44, "mapbox", 18),
        (45, "mapbox", 18),
        (46, "mapbox", None),
        (-1, "mapbox", None),
        (1, "failed", None),
        (1, "fetching", None),
    ],
)
def test_cache(engine, clinic_id, age, source, want):
    with write_tx(engine) as conn:
        conn.execute(
            s.travel_estimates.insert().values(
                clinic_id=clinic_id,
                area_id=1,
                minutes=18 if source == "mapbox" else None,
                source=source,
                fetched_at=BASE - timedelta(minutes=age),
            )
        )
        adapter = travel_mapbox.CacheAdapter()
        assert (
            adapter.minutes(POINT, DEST, BASE, ctx=travel.TravelContext(conn, clinic_id, 1)) == want
        )
        assert (
            adapter.minutes(POINT, DEST, BASE, ctx=travel.TravelContext(conn, clinic_id, None))
            is None
        )
        assert (
            adapter.minutes(POINT, DEST, BASE, ctx=travel.TravelContext(conn, clinic_id + 1, 1))
            is None
        )


def test_history_learning(engine, clinic_id):
    at = BASE.astimezone(UTC)
    with write_tx(engine) as conn:
        ctx = travel.TravelContext(conn, clinic_id, 1)
        history = travel_mapbox.AreaHistoryAdapter()
        for value in [10, 20]:
            travel_mapbox.learn(conn, clinic_id, 1, at, value)
        assert history.minutes(POINT, DEST, at, ctx=ctx) is None
        travel_mapbox.learn(conn, clinic_id, 1, at, 30)
        assert history.minutes(POINT, DEST, at, ctx=ctx) == 20
        assert history.minutes(POINT, DEST, at + timedelta(hours=1), ctx=ctx) is None
        assert (
            history.minutes(POINT, DEST, at, ctx=travel.TravelContext(conn, clinic_id + 1, 1))
            is None
        )
        assert (
            history.minutes(POINT, DEST, at, ctx=travel.TravelContext(conn, clinic_id, None))
            is None
        )
        bucket = conn.execute(select(s.area_hour_travel)).mappings().one()
        assert (bucket["weekday"], bucket["hour"], bucket["n"]) == (BASE.weekday(), BASE.hour, 3)
        conn.execute(s.area_hour_travel.update().values(mean_min=20, n=49))
        travel_mapbox.learn(conn, clinic_id, 1, at, 70)
        bucket = conn.execute(select(s.area_hour_travel)).mappings().one()
        assert bucket["mean_min"] == 21 and bucket["n"] == 50
        travel_mapbox.learn(conn, clinic_id, 1, at, 71)
        bucket = conn.execute(select(s.area_hour_travel)).mappings().one()
        assert bucket["mean_min"] == pytest.approx(22) and bucket["n"] == 50


def live_setup(engine, monkeypatch, count=3):
    cid, eid, clock, ids = setup(engine, count=count)
    with write_tx(engine) as conn:
        for i, bid in enumerate(ids):
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == bid).values(area_id=1 if i < 2 else 2)
            )
    monkeypatch.setenv("MAPBOX_TOKEN", "test-mapbox-token")
    get_settings.cache_clear()
    move(clock, 0)
    return cid, eid, clock, ids


def pending(engine, eid):
    with engine.connect() as conn:
        return (
            conn.execute(
                select(s.timers).where(
                    s.timers.c.kind == "travel_check",
                    s.timers.c.status == "pending",
                    s.timers.c.payload_json.is_not(None),
                )
            )
            .mappings()
            .all()
        )


def test_doctor_accounting_replay_and_raw_origin(engine, monkeypatch, fake_mapbox):
    cid, eid, clock, _ = live_setup(engine, monkeypatch)
    fake_mapbox.values = [150]
    result = timing.doctor_on_my_way(engine, clock, cid, eid, None, 1, "way")
    assert result.eta_min == 150 and len(fake_mapbox.calls) == 1
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, 1, "way") == result
    assert len(fake_mapbox.calls) == 1
    with engine.connect() as conn:
        usage = conn.execute(select(s.usage).where(s.usage.c.service == "mapbox")).mappings().one()
        assert usage["units"] == 1 and usage["est_cost_usd"] == 0.002
        learned = conn.execute(select(s.area_hour_travel)).mappings().one()
        assert learned["n"] == 1 and learned["mean_min"] == 150
    assert timing.undo_last(engine, clock, cid, eid, "undo").ok
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, 1, "raw")
    with engine.connect() as conn:
        assert conn.execute(select(s.area_hour_travel.c.n)).scalar_one() == 1
        assert (
            conn.execute(select(s.usage.c.units).where(s.usage.c.service == "mapbox")).scalar_one()
            == 2
        )


def test_doctor_web_live_call_and_replay(engine, monkeypatch, fake_mapbox):
    cid, eid, clock, _ = live_setup(engine, monkeypatch, count=1)
    fake_mapbox.values = [150]
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        assert (
            client.post(
                "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
            ).status_code
            == 200
        )
        headers = ORIGIN | {"X-CSRF-Token": client.cookies.get("nowa_csrf")}
        body = {"area_id": 1, "idempotency_key": "web-way"}
        response = client.post("/d/api/on-my-way", json=body, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] and result["eta_min"] == 150
        clock.advance(minutes=1)
        assert client.post("/d/api/on-my-way", json=body, headers=headers).json() == result
        assert len(fake_mapbox.calls) == 1
        # Recover the HTTP response after a crash between engine commit and HTTP save.
        with write_tx(engine) as conn:
            conn.execute(s.idempotency_keys.delete().where(s.idempotency_keys.c.key == "web-way"))
        assert client.post("/d/api/on-my-way", json=body, headers=headers).json() == result | {
            "projected_start": datetime.fromisoformat(result["projected_start"])
            .astimezone(UTC)
            .isoformat()
        }
        assert len(fake_mapbox.calls) == 1
        assert (
            client.post(
                "/d/api/undo", json={"idempotency_key": "web-way"}, headers=headers
            ).status_code
            == 409
        )
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.usage.c.units).where(s.usage.c.service == "mapbox")).scalar_one()
            == 1
        )
        assert conn.execute(select(s.area_hour_travel.c.n)).scalar_one() == 1
        assert row(engine, s.evenings, eid)["doctor_eta_min"] == 150


@pytest.mark.parametrize(
    "age_s,fresh", [(0, True), (119, True), (120, False), (121, False), (-1, False)]
)
def test_fetching_reservation_expiry(engine, monkeypatch, fake_mapbox, age_s, fresh):
    cid, eid, clock, _ = live_setup(engine, monkeypatch, count=1)
    fake_mapbox.values = [150, 45]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = pending(engine, eid)[0]
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    with write_tx(engine) as conn:
        conn.execute(
            s.travel_estimates.insert().values(
                clinic_id=cid,
                area_id=1,
                minutes=None,
                source="fetching",
                fetched_at=clock.now(cid) - timedelta(seconds=age_s),
            )
        )
        timing.recompute(conn, clock, eid)
    assert len(pending(engine, eid)) == (0 if fresh else 1)
    with write_tx(engine) as conn:
        ctx = TimerContext(
            conn, clock, cid, first["id"], "travel_check", first["due_at"], 1, clock.now(cid)
        )
        timing_handlers.travel_check(ctx, first["payload_json"])
        assert len(ctx.after_commit) == (0 if fresh else 1)
    assert len(fake_mapbox.calls) == 1
    if not fresh:
        ctx.after_commit[0]()
        assert len(fake_mapbox.calls) == 2
        with engine.connect() as conn:
            assert conn.execute(select(s.travel_estimates.c.source)).scalar_one() == "mapbox"
        assert pending(engine, eid)[0]["due_at"] == clock.now(cid) + timedelta(minutes=15)


@pytest.mark.parametrize("value", [45.0, None])
def test_prefetch_refresh_throttle_and_leave(engine, monkeypatch, fake_mapbox, value):
    cid, eid, clock, ids = live_setup(engine, monkeypatch)
    fake_mapbox.values = [150, value]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    initial = pending(engine, eid)
    assert len(initial) == 2
    first = min(initial, key=lambda r: r["due_at"])
    assert first["due_at"] == BASE + timedelta(minutes=150 - 10 - (45 * 1.3 + 10) - 30)
    for _ in range(10):
        with write_tx(engine) as conn:
            timing.recompute(conn, clock, eid)
    assert {r["id"] for r in pending(engine, eid)} == {r["id"] for r in initial}
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    before = len(fake_mapbox.calls)

    def checked_handler(ctx, payload):
        timing_handlers.travel_check(ctx, payload)
        assert len(fake_mapbox.calls) == before
        assert len(ctx.after_commit) == 1
        reserved = ctx.conn.execute(select(s.travel_estimates)).mappings().one()
        assert reserved["source"] == "fetching" and reserved["minutes"] is None
        assert reserved["fetched_at"] == clock.now(cid)

    # The real worker owns and executes the callback after committing the handler.
    drain(engine, clock, {"travel_check": checked_handler}, only_clinic_id=cid)
    assert len(fake_mapbox.calls) == before + 1
    with engine.connect() as conn:
        cached = conn.execute(select(s.travel_estimates)).mappings().one()
        assert cached["source"] == ("failed" if value is None else "mapbox")
        assert cached["minutes"] == value
        assert conn.execute(
            select(s.usage.c.units).where(s.usage.c.service == "mapbox")
        ).scalar_one() == 1 + (value is not None)
        assert conn.execute(select(s.area_hour_travel.c.n)).scalar_one_or_none() == (
            None if value is None else 1
        )
    next_area = next(r for r in pending(engine, eid) if r["payload_json"]["area_id"] == 1)
    assert next_area["due_at"] == clock.now(cid) + timedelta(minutes=15)
    clock.advance(minutes=5)
    with write_tx(engine) as conn:
        ctx = TimerContext(
            conn, clock, cid, first["id"], "travel_check", first["due_at"], 1, clock.now(cid)
        )
        timing_handlers.travel_check(ctx, first["payload_json"])
        assert ctx.after_commit == []
    assert len(fake_mapbox.calls) == before + 1
    assert (
        next(r for r in pending(engine, eid) if r["payload_json"]["area_id"] == 1)["id"]
        == next_area["id"]
    )
    # At the next boundary another call is allowed (failures included).
    clock.advance(minutes=10)
    drain(engine, clock, worker.build_registry(), only_clinic_id=cid)
    assert len(fake_mapbox.calls) == before + 2
    for _ in range(100):
        if all(row(engine, s.bookings, bid)["state"] == "told_to_leave" for bid in ids):
            break
        clock.advance(minutes=1)
        drain(engine, clock, worker.build_registry(), only_clinic_id=cid)
    assert all(row(engine, s.bookings, bid)["travel_min"] == 45 for bid in ids)
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
    assert pending(engine, eid) == []
    assert all(set(r["payload_json"]) == {"evening_id", "area_id"} for r in initial)
    area_calls = [r[2] for r in fake_mapbox.calls if r[1] == 1]
    assert all(b - a >= timedelta(minutes=15) for a, b in zip(area_calls, area_calls[1:]))


def test_travel_handler_idempotent(engine, monkeypatch, fake_mapbox):
    cid, eid, clock, _ = live_setup(engine, monkeypatch)
    fake_mapbox.values = [150, 45]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = min(pending(engine, eid), key=lambda r: r["due_at"])
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    assert_handler_idempotent(
        "travel_check",
        {"evening_id": eid, "area_id": 1},
        lambda: HandlerSetup(engine, clock, cid, {"travel_check": timing_handlers.travel_check}),
    )


@pytest.mark.parametrize("sandbox,offline", [(True, False), (False, True)])
def test_network_disabled_evening(engine, monkeypatch, fake_mapbox, sandbox, offline):
    cid, eid, clock, ids = live_setup(engine, monkeypatch)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=sandbox))
    monkeypatch.setenv("DEMO_NO_NETWORK", str(offline))
    get_settings.cache_clear()
    fake_mapbox.values = [pytest.fail]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, 1, "way")
    for bid in ids:
        with write_tx(engine) as conn:
            timing.recompute(conn, clock, eid)
        clock.advance(minutes=60)
        drain(engine, clock, worker.build_registry(), only_clinic_id=cid)
        timing.who_comes_in(engine, clock, cid, eid, bid, False, f"visit:{bid}")
    assert fake_mapbox.calls == []
    assert pending(engine, eid) == []


def test_prefix_rearm_isolation(engine, monkeypatch):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        for prefix in [
            f"travel_check:{eid}:1:",
            f"travel_check:{eid}:2:",
            f"travel_check:{eid}:1:",
        ]:
            rearm(
                conn,
                clock,
                "travel_check",
                eid,
                BASE,
                {"evening_id": eid, "area_id": int(prefix.split(":")[-2])},
                key_prefix=prefix,
            )
        rearm(conn, clock, "leave_now_check", eid, BASE, {"evening_id": eid})
        assert len(pending(engine, eid)) == 0  # uncommitted rows are private to this transaction
    assert len(pending(engine, eid)) == 2
    with engine.connect() as conn:
        key = conn.execute(
            select(s.timers.c.idempotency_key).where(s.timers.c.kind == "leave_now_check")
        ).scalar_one()
        assert key.startswith(f"leave_now_check:{eid}:{int(BASE.timestamp())}:")


def check_existing_history_migration(engine):
    config = migration_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "06")
        conn.exec_driver_sql(
            "INSERT INTO area_hour_travel (area_id, weekday, hour, mean_min, n) "
            "VALUES (1, 0, 12, 20, 4)"
        )
        command.upgrade(config, "13")
        assert conn.execute(select(s.area_hour_travel)).all() == []
        assert inspect(conn).get_pk_constraint("area_hour_travel")["constrained_columns"] == [
            "clinic_id",
            "area_id",
            "weekday",
            "hour",
        ]
        assert not next(
            c for c in inspect(conn).get_columns("area_hour_travel") if c["name"] == "clinic_id"
        )["nullable"]


def test_existing_history_migration(engine):
    check_existing_history_migration(engine)


@pytest.mark.postgres
def test_postgres_existing_history_migration(postgres_engine):
    check_existing_history_migration(postgres_engine)


def test_cached_refresh_moves_leave_and_uses_config_cost(engine, monkeypatch, fake_mapbox):
    cid, eid, clock, ids = live_setup(engine, monkeypatch, count=1)
    monkeypatch.setenv("MAPBOX_USD_PER_CALL", "0.007")
    get_settings.cache_clear()
    fake_mapbox.values = [150, 20, 60]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = pending(engine, eid)[0]
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    drain(engine, clock, {"travel_check": timing_handlers.travel_check}, only_clinic_id=cid)
    with engine.connect() as conn:
        leave_before = conn.execute(
            select(s.timers.c.due_at).where(
                s.timers.c.kind == "leave_now_check",
                s.timers.c.status == "pending",
            )
        ).scalar_one()
    next_check = pending(engine, eid)[0]
    clock.advance(minutes=(next_check["due_at"] - clock.now(cid)).total_seconds() / 60)
    drain(engine, clock, worker.build_registry(), only_clinic_id=cid)
    booking = row(engine, s.bookings, ids[0])
    assert booking["state"] == "told_to_leave"
    assert booking["travel_min"] == 60
    assert booking["told_to_leave_at"] < leave_before
    assert pending(engine, eid) == []
    assert len(fake_mapbox.calls) == 3
    with engine.connect() as conn:
        usage = conn.execute(select(s.usage).where(s.usage.c.service == "mapbox")).mappings().one()
        assert usage["units"] == 3 and usage["est_cost_usd"] == pytest.approx(0.021)


def test_failed_cache_history_and_clinic_isolation(engine, clinic_id):
    from nowa.demo.template import CLINIC

    with write_tx(engine) as conn:
        second = conn.execute(
            s.clinics.insert()
            .values(
                **dict(CLINIC["clinic"], slug="second-clinic"),
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
        for cid, value in [(clinic_id, 20), (second, 50)]:
            for _ in range(3):
                travel_mapbox.learn(conn, cid, 1, BASE, value)
            conn.execute(
                s.travel_estimates.insert().values(
                    clinic_id=cid,
                    area_id=1,
                    minutes=None,
                    source="failed",
                    fetched_at=BASE,
                )
            )
        for cid, value in [(clinic_id, 20), (second, 50)]:
            ctx = travel.TravelContext(conn, cid, 1)
            assert travel_mapbox.CacheAdapter().minutes(POINT, DEST, BASE, ctx=ctx) is None
            assert travel_mapbox.AreaHistoryAdapter().minutes(POINT, DEST, BASE, ctx=ctx) == value
        assert conn.execute(select(s.area_hour_travel)).rowcount != 0


def test_real_recompute_and_handler_transaction_never_http(engine, monkeypatch):
    cid, eid, clock, _ = live_setup(engine, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("HTTP during deterministic timing")

    monkeypatch.setattr(httpx.Client, "get", forbidden)
    with write_tx(engine) as conn:
        timing.doctor_on_my_way_in_tx(conn, clock, cid, eid, POINT, None, "way", travel_min=150)
        for _ in range(10):
            timing.recompute(conn, clock, eid)
        timing_handlers.leave_now_check(
            TimerContext(conn, clock, cid, 1, "leave_now_check", BASE, 1, clock.now(cid)),
            {"evening_id": eid},
        )
    first = min(pending(engine, eid), key=lambda r: r["due_at"])
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    with write_tx(engine) as conn:
        ctx = TimerContext(conn, clock, cid, 1, "travel_check", BASE, 1, clock.now(cid))
        timing_handlers.travel_check(ctx, first["payload_json"])
        assert len(ctx.after_commit) == 1


@pytest.mark.parametrize("terminal", ["closed", "cancelled", "no_bookings"])
def test_stale_handler_and_cancellation(engine, monkeypatch, fake_mapbox, terminal):
    cid, eid, clock, _ = live_setup(engine, monkeypatch)
    fake_mapbox.values = [150]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = pending(engine, eid)[0]
    with write_tx(engine) as conn:
        if terminal == "no_bookings":
            conn.execute(
                s.bookings.update().where(s.bookings.c.evening_id == eid).values(state="cancelled")
            )
            timing.recompute(conn, clock, eid)
        else:
            conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state=terminal))
            timing._cancel_timers(conn, eid)
        ctx = TimerContext(conn, clock, cid, first["id"], "travel_check", BASE, 1, clock.now(cid))
        timing_handlers.travel_check(ctx, first["payload_json"])
        assert ctx.after_commit == []
    assert pending(engine, eid) == []
    assert len(fake_mapbox.calls) == 1


def test_callback_error_uses_worker_rule(engine, monkeypatch, fake_mapbox, caplog):
    cid, eid, clock, _ = live_setup(engine, monkeypatch)
    fake_mapbox.values = [150, 45]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = min(pending(engine, eid), key=lambda r: r["due_at"])
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)

    def broken(*args):
        raise RuntimeError("private coordinates and token")

    monkeypatch.setattr(travel_mapbox, "learn", broken)
    stats = worker.run_once(engine, clock, {"travel_check": timing_handlers.travel_check})
    assert stats.done == 1 and stats.retried == 0
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.action_record.c.text).where(
                    s.action_record.c.kind == "timer_after_commit_error",
                )
            ).scalar_one()
            == "RuntimeError"
        )
    assert "private coordinates and token" not in caplog.text
    with engine.connect() as conn:
        # Both returned numbers must remain accounted for after a callback error.
        assert (
            conn.execute(
                select(s.usage.c.units).where(
                    s.usage.c.service == "mapbox",
                )
            ).scalar_one()
            == 2
        )
    calls = len(fake_mapbox.calls)
    worker.run_once(engine, clock, {"travel_check": timing_handlers.travel_check})
    assert len(fake_mapbox.calls) == calls


def test_callback_recompute_failure_rolls_back_cache_and_learning(engine, monkeypatch, fake_mapbox):
    cid, eid, clock, _ = live_setup(engine, monkeypatch, count=1)
    fake_mapbox.values = [150, 20]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = pending(engine, eid)[0]
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)

    def broken(*args):
        raise RuntimeError("private provider details")

    monkeypatch.setattr(timing, "recompute", broken)
    stats = worker.run_once(engine, clock, {"travel_check": timing_handlers.travel_check})
    assert stats.done == 1 and stats.retried == 0
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.usage.c.units).where(s.usage.c.service == "mapbox")).scalar_one()
            == 2
        )
        cached = conn.execute(select(s.travel_estimates)).mappings().one()
        assert cached["source"] == "fetching" and cached["minutes"] is None
        assert conn.execute(select(s.area_hour_travel)).all() == []
        assert (
            conn.execute(
                select(s.action_record.c.text).where(
                    s.action_record.c.kind == "timer_after_commit_error"
                )
            ).scalar_one()
            == "RuntimeError"
        )


def test_inflight_callback_recompute_does_not_double_fetch(engine, monkeypatch, fake_mapbox):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cid, eid, clock, _ = live_setup(engine, monkeypatch, count=1)
    fake_mapbox.values = [150, 45]
    timing.doctor_on_my_way(engine, clock, cid, eid, POINT, None, "way")
    first = pending(engine, eid)[0]
    clock.advance(minutes=(first["due_at"] - clock.now(cid)).total_seconds() / 60)
    started, release = Event(), Event()
    original = fake_mapbox.minutes

    def delayed(self, origin, dest, at, *, ctx):
        value = original(self, origin, dest, at, ctx=ctx)
        started.set()
        assert release.wait(10), "test failed to release in-flight HTTP"
        return value

    monkeypatch.setattr(fake_mapbox, "minutes", delayed)
    registry = {"travel_check": timing_handlers.travel_check}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_run = pool.submit(worker.run_once, engine, clock, registry)
        try:
            assert started.wait(5), "first callback did not start"
            # This is a routine booking/settings recompute while HTTP is in flight.
            with write_tx(engine) as conn:
                timing.recompute(conn, clock, eid)
            monkeypatch.setattr(fake_mapbox, "minutes", original)
            second_run = pool.submit(worker.run_once, engine, clock, registry)
            second_run.result(timeout=5)
        finally:
            release.set()
        first_run.result(timeout=5)
    # One doctor call plus at most one pre-fetch for this clinic/area at this instant.
    assert len(fake_mapbox.calls) == 2
