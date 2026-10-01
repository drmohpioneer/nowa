import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.app import create_app
from nowa.core import auth, clinic_settings, timing
from nowa.db import write_tx
from nowa.demo.template import CLINIC
from tests.core.support import DAY, move, row, setup
from tests.web.support import ORIGIN, rows


@pytest.fixture
def web(engine, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "nowa_test_bot")
    cid, eid, clock, ids = setup(engine, count=6)
    move(clock, 0)
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        )
        assert response.status_code == 200, response.text
        yield client, cid, eid, clock, ids


def headers(client):
    return ORIGIN | {"X-CSRF-Token": client.cookies.get("nowa_csrf")}


def post(client, path, body=None, key=None):
    return client.post(
        "/d/api/" + path,
        json={"idempotency_key": key or path, **(body or {})},
        headers=headers(client),
    )


def board(client):
    response = client.get("/d/api/tonight")
    assert response.status_code == 200
    return response.json()["rows"]


def test_evening_scenario_and_engine_calls(web, engine, monkeypatch):
    client, cid, eid, clock, ids = web
    names = [
        "doctor_on_my_way",
        "who_comes_in_in_tx",
        "undo_last_in_tx",
        "close_preview",
        "close_evening_in_tx",
    ]
    spies = {n: Mock(wraps=getattr(timing, n)) for n in names}
    for n, spy in spies.items():
        monkeypatch.setattr(timing, n, spy)
    assert post(client, "on-my-way", {"lat": 30.123456, "lng": 31.654321}).json()["ok"]
    for i in (0, 2, 3):
        clock.advance(minutes=12)
        assert post(client, "who-comes-in", {"booking_id": ids[i]}, f"tap:{i}").json()["ok"]
        assert next(r for r in board(client) if r["booking_id"] == ids[i])["state"] == "seen"
    before = len(rows(engine, s.visits))
    assert post(client, "who-comes-in", {"booking_id": ids[3]}, "tap:3").json()["ok"]
    assert len(rows(engine, s.visits)) == before
    assert post(client, "undo").json()["ok"]
    assert row(engine, s.bookings, ids[3])["state"] != "seen"
    assert post(client, "who-comes-in", {"walk_in": True}, "walkin").json()["ok"]
    preview = client.get("/d/api/close/preview").json()
    assert post(client, "close", {"expected_untold": preview["untold_count"]}).json()["ok"]
    assert row(engine, s.evenings, eid)["state"] == "closed"
    assert spies["doctor_on_my_way"].call_count == 1
    assert spies["who_comes_in_in_tx"].call_count == 4
    for n in ("undo_last_in_tx", "close_preview", "close_evening_in_tx"):
        assert spies[n].call_count == 1
    for spy in spies.values():
        assert all(call.args[2] == cid for call in spy.call_args_list)


def test_cancel_request_replay_and_confirm(web, engine, monkeypatch):
    client, cid, eid, clock, _ = web
    request_spy = Mock(wraps=timing.request_cancel_tonight)
    confirm_spy = Mock(wraps=timing.cancel_tonight_in_tx)
    monkeypatch.setattr(timing, "request_cancel_tonight", request_spy)
    monkeypatch.setattr(timing, "cancel_tonight_in_tx", confirm_spy)
    first = post(client, "cancel-tonight/request").json()
    assert first["active_count"] == 6
    assert post(client, "cancel-tonight/request").json() == first
    clock.advance(minutes=20)
    refused = post(
        client, "cancel-tonight/confirm", {"confirm_token": first["confirm_token"]}
    ).json()
    assert refused["reason"] == "invalid_token"
    fresh = post(client, "cancel-tonight/request", key="fresh").json()
    assert post(
        client, "cancel-tonight/confirm", {"confirm_token": fresh["confirm_token"]}, "fresh-confirm"
    ).json()["ok"]
    assert row(engine, s.evenings, eid)["state"] == "cancelled"
    assert request_spy.call_count == confirm_spy.call_count == 2
    assert all(
        call.args[2] == cid for call in request_spy.call_args_list + confirm_spy.call_args_list
    )


def test_reset_web_screen_and_session_revoke(web, engine):
    client, cid, _, clock, _ = web
    response = client.post("/d/reset/request", json={"mobile": "01000000001"}, headers=ORIGIN)
    assert response.status_code == 200
    message = [r for r in rows(engine, s.outbox) if r["template_id"] == "op:reset_code"][-1]
    assert message["adapter"] == "screen_phone"
    from nowa import worker
    from nowa.messaging.outbox import screen_messages
    from tests.helpers.worker import drain

    drain(engine, clock, worker.build_registry())
    with engine.connect() as conn:
        drawn = next(m for m in screen_messages(conn, cid, 0) if m.outbox_id == message["id"])
    assert drawn.status == "delivered" and drawn.body == message["body"]
    code = re.search(r"\b[0-9]{6}\b", message["body"]).group()
    assert (
        client.post(
            "/d/reset/confirm",
            json={"mobile": "01000000001", "code": code, "new_password": "new-password"},
            headers=ORIGIN,
        ).status_code
        == 200
    )
    assert row(engine, s.outbox, message["id"])["body"] == "[redacted]"
    assert client.get("/d/api/tonight").status_code == 401
    assert (
        client.post(
            "/d/login", json={"mobile": "01000000001", "password": "new-password"}, headers=ORIGIN
        ).status_code
        == 200
    )


@pytest.mark.parametrize("bad", [None, "wrong", "foreign", "missing_origin"])
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "undo", {}),
        ("POST", "telegram-link", {}),
        ("PUT", "settings/lang", {"lang": "en"}),
        ("DELETE", "settings/overrides/2026-10-06", {}),
    ],
)
def test_csrf_origin_all_verbs(web, engine, bad, method, path, payload):
    client, _, _, _, _ = web
    h = headers(client)
    if bad is None:
        h.pop("X-CSRF-Token")
    elif bad == "wrong":
        h["X-CSRF-Token"] = "wrong"
    elif bad == "foreign":
        h["Origin"] = "https://other.example"
    else:
        h.pop("Origin")
    before = rows(engine, s.idempotency_keys)
    assert (
        client.request(
            method, "/d/api/" + path, json={"idempotency_key": "forbidden", **payload}, headers=h
        ).status_code
        == 403
    )
    assert rows(engine, s.idempotency_keys) == before


@pytest.mark.parametrize(
    "path,body",
    [
        ("/d/login", {"mobile": "01000000001", "password": "demo1234"}),
        ("/d/reset/request", {"mobile": "01000000001"}),
        (
            "/d/reset/confirm",
            {"mobile": "01000000001", "code": "123456", "new_password": "new-password"},
        ),
    ],
)
@pytest.mark.parametrize("h", [{}, {"Origin": "https://foreign.example"}])
def test_anonymous_origin(web, engine, path, body, h):
    client, _, _, _, _ = web
    before = rows(engine, s.auth_codes)
    assert client.post(path, json=body, headers=h).status_code == 403
    assert rows(engine, s.auth_codes) == before


def other_clinic(engine, clock):
    with write_tx(engine) as conn:
        cid = conn.execute(
            s.clinics.insert()
            .values(**dict(CLINIC["clinic"], slug="clinic-b"))
            .returning(s.clinics.c.id)
        ).scalar_one()
        eid = conn.execute(
            s.evenings.insert().values(clinic_id=cid, date=DAY).returning(s.evenings.c.id)
        ).scalar_one()
        bid = conn.execute(
            s.bookings.insert()
            .values(
                clinic_id=cid,
                evening_id=eid,
                queue_number=1,
                order_key=1,
                source="walkin_tap",
                lang="ar",
                created_at=clock.now(cid),
            )
            .returning(s.bookings.c.id)
        ).scalar_one()
    return cid, eid, bid


@pytest.mark.parametrize(
    "path,body",
    [
        ("on-my-way", {"area_id": 1}),
        ("who-comes-in", {"walk_in": True}),
        ("undo", {}),
        ("close", {"expected_untold": 0}),
        ("cancel-tonight/request", {}),
        ("cancel-tonight/confirm", {"confirm_token": "bad"}),
        ("telegram-link", {}),
    ],
)
def test_foreign_evening(web, engine, path, body):
    client, _, _, clock, _ = web
    _, eid, bid = other_clinic(engine, clock)
    before = row(engine, s.evenings, eid)
    assert post(client, path, body | {"evening_id": eid}).status_code == 404
    assert row(engine, s.evenings, eid) == before
    assert bid not in {r["booking_id"] for r in board(client)}
    assert post(client, "who-comes-in", {"booking_id": bid}, "foreign-booking").status_code == 404
    assert client.get(f"/d/api/close/preview?evening_id={eid}").status_code == 404


def test_telegram_hash_and_replay(web, engine, monkeypatch):
    client, cid, _, _, _ = web
    spy = Mock(wraps=timing.recompute)
    monkeypatch.setattr(timing, "recompute", spy)
    response = post(client, "telegram-link").json()
    token = response["url"].split("d_", 1)[1]
    link = rows(engine, s.link_tokens)[0]
    assert link["clinic_id"] == cid and link["token_hash"] == auth.token_hash(token)
    assert token not in str(rows(engine, s.idempotency_keys))
    assert post(client, "telegram-link").json() == {"repeated": True}
    assert len(rows(engine, s.link_tokens)) == 1
    spy.assert_not_called()


@pytest.mark.parametrize(
    "kind,payload,field",
    [
        ("hours", {"hours": [{"weekday": 1, "start": "13:00", "end": "23:59"}]}, "hours"),
        ("overrides", {"date": "2026-10-07", "closed": True}, "overrides"),
        (
            "timing",
            {
                "usual_visit_min": 60,
                "cushion_min": 15,
                "safe_drive_min": 120,
                "max_per_evening": 100,
            },
            "usual_visit_min",
        ),
        ("info", {"items": [{"key": "other", "text": "<script>untrusted</script>"}]}, "items"),
        ("lang", {"lang": "en"}, "lang"),
        ("secretary_alerts", {"on": True}, "on"),
    ],
)
def test_settings_roundtrip_and_engine_spies(web, engine, monkeypatch, kind, payload, field):
    client, _, eid, _, _ = web
    recompute = Mock(wraps=timing.recompute)
    ensure = Mock(wraps=timing.ensure_evening_timers)
    helper = Mock(wraps=clinic_settings.update)
    monkeypatch.setattr(timing, "recompute", recompute)
    monkeypatch.setattr(timing, "ensure_evening_timers", ensure)
    monkeypatch.setattr(clinic_settings, "update", helper)
    response = client.put(
        "/d/api/settings/" + kind, json=payload | {"idempotency_key": kind}, headers=headers(client)
    )
    assert response.status_code == 200, response.text
    saved = client.get("/d/api/settings").json()
    if kind == "overrides":
        assert saved[field][0]["closed"] is True
    else:
        assert saved[field] == payload[field]
    assert helper.call_count == 1
    assert recompute.call_count == (1 if kind in {"hours", "timing"} else 0)
    assert ensure.call_count == (2 if kind == "hours" else 1 if kind == "timing" else 0)
    client.put(
        "/d/api/settings/" + kind, json=payload | {"idempotency_key": kind}, headers=headers(client)
    )
    assert helper.call_count == 1
    if kind == "overrides":
        assert (
            client.request(
                "DELETE",
                "/d/api/settings/overrides/2026-10-07",
                json={"idempotency_key": "del"},
                headers=headers(client),
            ).status_code
            == 200
        )
        assert client.get("/d/api/settings").json()["overrides"] == []


def test_close_count_changed_and_new_intent(web, engine):
    client, cid, _, clock, ids = web
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(safe_drive_min=10))
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    preview = client.get("/d/api/close/preview").json()["untold_count"]
    clock.advance(minutes=15)
    post(client, "who-comes-in", {"booking_id": ids[-1]}, "next")
    response = post(client, "close", {"expected_untold": preview})
    assert response.status_code == 409
    count = response.json()["untold_count"]
    assert post(client, "close", {"expected_untold": count}, "new-close").json()["ok"]


def test_settings_rollback_and_no_recompute_for_max(web, engine, monkeypatch):
    client, cid, _, _, _ = web
    spy = Mock(wraps=timing.recompute)
    monkeypatch.setattr(timing, "recompute", spy)
    original = client.get("/d/api/settings").json()
    for payload in ({"hours": []}, {"hours": [{"weekday": 1, "start": "12:00", "end": "12:01"}]}):
        response = client.put(
            "/d/api/settings/hours",
            json=payload | {"idempotency_key": "bad-hours"},
            headers=headers(client),
        )
        assert response.status_code == 422 and response.json()["reason"] == "bookings_outside"
        assert client.get("/d/api/settings").json() == original
    body = {
        k: original[k]
        for k in ("usual_visit_min", "safe_drive_min", "cushion_min", "max_per_evening")
    }
    body["max_per_evening"] = 2
    assert (
        client.put(
            "/d/api/settings/timing",
            json=body | {"idempotency_key": "max"},
            headers=headers(client),
        ).status_code
        == 200
    )
    spy.assert_not_called()
    assert row(engine, s.clinics, cid)["max_per_evening"] == 2


def test_no_evening_and_logout(web):
    client, _, _, clock, _ = web
    clock.advance(minutes=24 * 60)
    assert client.get("/d/api/tonight").json()["reason"] == "no_evening"
    assert 'id="evening-dot" class="dot"' in client.get("/d").text
    assert post(client, "undo").json()["reason"] == "no_evening"
    assert client.post("/d/logout", headers=headers(client)).status_code == 200
    assert client.get("/d/api/tonight").status_code == 401


def test_pages_cookies_language_and_escaping(web, engine):
    client, cid, _, _, _ = web
    page = client.get("/d")
    assert page.status_code == 200 and 'dir="rtl"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert 'id="evening-dot" class="dot live"' in page.text
    assert " · د. " in page.text
    assert client.get("/d/settings").status_code == 200
    with write_tx(engine) as conn:
        conn.execute(s.doctors.update().where(s.doctors.c.clinic_id == cid).values(lang="en"))
    assert 'dir="ltr"' in client.get("/d").text
    assert "Tonight&#39;s clinic" in client.get("/d").text
    assert " · Dr. " in client.get("/d").text
    assert client.get("/d/login").status_code == client.get("/d/reset").status_code == 200
    response = client.post(
        "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
    )
    cookies = response.headers.get_list("set-cookie")
    assert "HttpOnly" in cookies[0] and "HttpOnly" not in cookies[1]
    assert all("SameSite=lax" in c and "Path=/" in c and "Secure" not in c for c in cookies)
    assert client.post("/d/logout", headers=headers(client)).status_code == 200
    assert client.get("/d", follow_redirects=False).headers["location"] == "/d/login"
    assert client.get("/d/settings", follow_redirects=False).status_code == 303


def test_referrer_and_settings_invalid_atomic(web, engine):
    client, _, _, _, _ = web
    original = client.get("/d/api/settings").json()
    response = client.put(
        "/d/api/settings/timing",
        json={
            "usual_visit_min": 4,
            "cushion_min": 5,
            "safe_drive_min": 10,
            "max_per_evening": None,
            "idempotency_key": "invalid",
        },
        headers=headers(client),
    )
    assert response.status_code == 422 and "usual_visit_min" in response.json()["fields"]
    assert client.get("/d/api/settings").json() == original
    h = {"Referer": "http://127.0.0.1:8000/d", "X-CSRF-Token": client.cookies.get("nowa_csrf")}
    assert (
        client.put(
            "/d/api/settings/lang", json={"lang": "en", "idempotency_key": "referer"}, headers=h
        ).status_code
        == 200
    )
    assert not [r for r in rows(engine, s.idempotency_keys) if r["key"] == "invalid"]


def test_sensitive_data_scan_after_reset(web, engine, caplog):
    client, _, _, _, _ = web
    caplog.set_level("INFO")
    tokens = [client.cookies.get("nowa_session"), client.cookies.get("nowa_csrf")]
    result = post(client, "telegram-link").json()
    tokens.append(result["url"].split("d_", 1)[1])
    post(client, "on-my-way", {"lat": 30.123456789, "lng": 31.987654321})
    client.post("/d/reset/request", json={"mobile": "01000000001"}, headers=ORIGIN)
    message = [r for r in rows(engine, s.outbox) if r["template_id"] == "op:reset_code"][-1]
    code = re.search(r"\b[0-9]{6}\b", message["body"]).group()
    assert (
        client.post(
            "/d/reset/confirm",
            json={"mobile": "01000000001", "code": code, "new_password": "unique-test-password"},
            headers=ORIGIN,
        ).status_code
        == 200
    )
    sensitive = tokens + [code, "unique-test-password", "30.123456789", "31.987654321"]
    excluded = {
        "password_hash",
        "mobile_e164",
        "phone_e164",
        "phone",
        "lat",
        "lng",
        "token_hash",
        "csrf_hash",
        "link_code_hash",
    }
    with engine.connect() as conn:
        for table in s.metadata.tables.values():
            for r in conn.execute(select(table)).mappings():
                content = str({k: v for k, v in r.items() if k not in excluded})
                assert not any(value in content for value in sensitive), table.name
    assert not any(
        value in caplog.text for value in sensitive + ["+201000000001", "01000000001", "demo1234"]
    )


def test_cookie_secure_outside_loopback(monkeypatch):
    from datetime import UTC, datetime

    from fastapi.responses import Response

    from nowa.config import get_settings
    from nowa.web.doctor_auth import start_session

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nowa.example")
    get_settings.cache_clear()
    response = Response()
    start_session(response, auth.SessionTokens("session", "csrf", datetime(2027, 1, 1, tzinfo=UTC)))
    assert all("Secure" in value for value in response.headers.getlist("set-cookie"))


@pytest.mark.parametrize(
    "method,path,payload,status,ok",
    [
        ("POST", "/d/api/on-my-way", {"area_id": 1}, 200, True),
        ("POST", "/d/api/undo", {}, 200, False),
        ("POST", "/d/api/close", {"expected_untold": 999}, 409, False),
        ("PUT", "/d/api/settings/lang", {"lang": "en"}, 200, True),
        ("DELETE", "/d/api/settings/overrides/2026-10-06", {}, 200, True),
        ("POST", "/d/api/telegram-link", {}, 200, None),
        ("POST", "/d/logout", {}, 200, True),
    ],
)
def test_executed_command_updates_session_once(web, engine, method, path, payload, status, ok):
    from sqlalchemy import event

    client, _, _, clock, ids = web
    if path == "/d/api/close":
        assert post(client, "on-my-way", {"area_id": 1}).json()["ok"]
        assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    before = rows(engine, s.doctor_sessions)[0]
    clock.advance(minutes=1)
    updates = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE doctor_sessions SET"):
            updates.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.request(
            method,
            path,
            json={"idempotency_key": "session-touch", **payload},
            headers=headers(client),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == status, response.text
    if ok is not None:
        assert response.json()["ok"] is ok
    after = rows(engine, s.doctor_sessions)[0]
    assert after["last_seen_at"] > before["last_seen_at"]
    assert after["last_seen_at"] == clock.base_now()
    assert len(updates) == 1
    if path != "/d/logout":
        clock.advance(minutes=1)
        assert (
            client.request(
                method,
                path,
                json={"idempotency_key": "session-touch", **payload},
                headers=headers(client),
            ).status_code
            == status
        )
        assert rows(engine, s.doctor_sessions)[0]["last_seen_at"] == after["last_seen_at"]


def test_get_and_failed_csrf_do_not_update_session(web, engine):
    client, _, _, clock, _ = web
    before = rows(engine, s.doctor_sessions)
    clock.advance(minutes=1)
    assert client.get("/d/api/tonight").status_code == 200
    assert client.get("/d").status_code == 200
    assert client.get("/d/settings").status_code == 200
    assert client.get("/d/api/settings").status_code == 200
    assert client.get("/d/api/close/preview").status_code == 200
    assert (
        client.post("/d/api/undo", json={"idempotency_key": "bad-csrf"}, headers=ORIGIN).status_code
        == 403
    )
    assert (
        client.post(
            "/d/api/undo",
            json={"idempotency_key": "bad-origin"},
            headers=headers(client) | {"Origin": "https://foreign.example"},
        ).status_code
        == 403
    )
    assert post(client, "on-my-way", {"area_id": 999999}).status_code == 422
    assert (
        client.put(
            "/d/api/settings/lang",
            json={"lang": "invalid", "idempotency_key": "bad-lang"},
            headers=headers(client),
        ).status_code
        == 422
    )
    assert rows(engine, s.doctor_sessions) == before


def test_foreign_evening_settings_and_delete(web, engine):
    client, _, _, clock, _ = web
    _, eid, _ = other_clinic(engine, clock)
    original = client.get("/d/api/settings").json()
    assert (
        client.put(
            "/d/api/settings/lang",
            json={"lang": "en", "evening_id": eid, "idempotency_key": "foreign"},
            headers=headers(client),
        ).status_code
        == 404
    )
    assert (
        client.request(
            "DELETE",
            "/d/api/settings/overrides/2026-10-06",
            json={"evening_id": eid, "idempotency_key": "foreign-del"},
            headers=headers(client),
        ).status_code
        == 404
    )
    assert client.get("/d/api/settings").json() == original


def test_idempotency_conflict_and_bad_json(web):
    client, _, _, _, _ = web
    assert post(client, "undo", key="same-key").status_code == 200
    assert post(client, "telegram-link", key="same-key").status_code == 409
    response = client.put(
        "/d/api/settings/lang",
        content="{broken",
        headers=headers(client) | {"Content-Type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path,scope", [("/d/login", "doctor_login_ip"), ("/d/reset/request", "doctor_reset_ip")]
)
def test_anonymous_ip_limit_http(web, engine, path, scope):
    client, _, _, _, _ = web
    # A fresh address prevents this fixture's successful login from spending the window.
    from unittest.mock import patch

    from nowa.web import doctor_auth

    with patch.object(doctor_auth, "client_ip", return_value="fresh-ip"):
        for i in range(20):
            body = {"mobile": f"010{i + 100:08d}"}
            if path == "/d/login":
                body["password"] = "wrong"
            assert client.post(path, json=body, headers=ORIGIN).status_code == (
                401 if path == "/d/login" else 200
            )
        body = {"mobile": "01000000001"}
        if path == "/d/login":
            body["password"] = "demo1234"
        assert client.post(path, json=body, headers=ORIGIN).status_code == 429
    assert next(
        r for r in rows(engine, s.rate_counters) if r["scope"] == scope and r["count"] == 21
    )
