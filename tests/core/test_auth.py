import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from nowa import schema as s
from nowa.core import auth
from nowa.db import write_tx
from nowa.seed import seed
from tests.web.support import rows

PHONE = "01000000001"
PASSWORD = "demo1234"


def doctor(engine):
    seed(engine)
    return rows(engine, s.doctors)[0]


def reset_code(engine):
    return re.search(r"\b[0-9]{6}\b", rows(engine, s.outbox)[-1]["body"]).group()


def test_password_and_session(engine, frozen_clock):
    d = doctor(engine)
    assert PasswordHasher().verify(auth.hash_password("some password"), "some password")
    tokens = auth.create_session(engine, frozen_clock, d["clinic_id"], d["id"])
    row = rows(engine, s.doctor_sessions)[0]
    assert row["token_hash"] == auth.token_hash(tokens.token)
    assert row["csrf_hash"] == auth.token_hash(tokens.csrf_token)
    assert tokens.token not in str(row) and tokens.csrf_token not in str(row)
    session = auth.session_for(engine, frozen_clock, tokens.token)
    assert session.doctor_id == d["id"]
    frozen_clock.advance(minutes=30 * 24 * 60)
    assert auth.session_for(engine, frozen_clock, tokens.token) is None


@pytest.mark.parametrize("phone", [PHONE, "01099999999"])
def test_login_window_and_dummy(engine, frozen_clock, phone, monkeypatch):
    doctor(engine)
    calls = []
    original = auth._hasher.verify

    def verify(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(auth, "_hasher", SimpleNamespace(verify=verify))
    for i in range(5):
        result = auth.login(engine, frozen_clock, phone, PASSWORD if i == 2 else "wrong", "ip")
        assert not result.limited
        assert result.ok == (phone == PHONE and i == 2)
    assert auth.login(engine, frozen_clock, phone, PASSWORD, "ip").limited
    assert len(calls) == 5
    if phone != PHONE:
        assert all(h == auth._dummy for h in calls)
    frozen_clock.advance(minutes=15)
    assert not auth.login(engine, frozen_clock, phone, PASSWORD, "ip").limited


def test_login_ip_first(engine, frozen_clock, monkeypatch):
    doctor(engine)
    calls = []
    monkeypatch.setattr(
        auth, "_hasher", SimpleNamespace(verify=lambda *args: calls.append(args) or False)
    )
    for i in range(20):
        assert not auth.login(engine, frozen_clock, f"010{i:08d}", "wrong", "ip").limited
    assert auth.login(engine, frozen_clock, PHONE, PASSWORD, "ip").limited
    assert len(calls) == 20


@pytest.mark.parametrize("expire", [False, True])
def test_reset_death_and_expiry(engine, frozen_clock, expire):
    doctor(engine)
    assert auth.request_reset(engine, frozen_clock, PHONE, "ip")
    code = reset_code(engine)
    if expire:
        frozen_clock.advance(minutes=10)
    else:
        for _ in range(5):
            assert not auth.confirm_reset(engine, frozen_clock, PHONE, "not-code", "newpassword")
    assert not auth.confirm_reset(engine, frozen_clock, PHONE, code, "newpassword")
    assert rows(engine, s.auth_codes)[0]["attempts"] == (0 if expire else 5)
    assert code in rows(engine, s.outbox)[0]["body"]
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert rows(engine, s.outbox)[0]["body"] == "[redacted]"


def test_reset_newest_limit_redaction_and_revoke(engine, frozen_clock):
    d = doctor(engine)
    tokens = auth.create_session(engine, frozen_clock, d["clinic_id"], d["id"])
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    old = reset_code(engine)
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    new = reset_code(engine)
    assert rows(engine, s.auth_codes)[0]["used_at"] is not None
    assert rows(engine, s.outbox)[0]["body"] == "[redacted]"
    # Force a distinct wrong value even in the rare case randomly generated codes coincide.
    assert not auth.confirm_reset(engine, frozen_clock, PHONE, "not-" + old, "newpassword")
    with pytest.raises(ValueError, match="new_password"):
        auth.confirm_reset(engine, frozen_clock, PHONE, new, "short")
    assert rows(engine, s.auth_codes)[1]["attempts"] == 1
    assert auth.confirm_reset(engine, frozen_clock, PHONE, new, "newpassword")
    assert rows(engine, s.outbox)[1]["body"] == "[redacted]"
    assert auth.session_for(engine, frozen_clock, tokens.token) is None
    assert auth.login(engine, frozen_clock, PHONE, "newpassword", "ip").ok
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    before = len(rows(engine, s.outbox))
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert len(rows(engine, s.outbox)) == before == 3


def test_reset_recipient_kind_unknown_and_redaction_guard(engine, frozen_clock):
    d = doctor(engine)
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=d["mobile_e164"],
                kind="patient",
                telegram_chat_id="patient",
                linked_at=frozen_clock.now(d["clinic_id"]),
            )
        )
    assert auth.request_reset(engine, frozen_clock, "01099999999", "ip")
    assert not rows(engine, s.outbox)
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert [r["channel"] for r in rows(engine, s.outbox)] == ["telegram"]
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=d["mobile_e164"],
                kind="doctor",
                telegram_chat_id="doctor",
                linked_at=frozen_clock.now(d["clinic_id"]),
            )
        )
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert [r["channel"] for r in rows(engine, s.outbox)] == ["telegram", "telegram"]
    with write_tx(engine) as conn:
        oid = rows(engine, s.outbox)[0]["id"]
        conn.execute(
            s.outbox.update().where(s.outbox.c.id == oid).values(template_id="5", body="unchanged")
        )
        with pytest.raises(ValueError):
            auth.redact_code_row(conn, oid)
        assert (
            conn.execute(select(s.outbox.c.body).where(s.outbox.c.id == oid)).scalar_one()
            == "unchanged"
        )


def test_reset_ip_limit(engine, frozen_clock):
    doctor(engine)
    for _ in range(20):
        assert auth.request_reset(engine, frozen_clock, "01099999999", "ip")
    assert not auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert not rows(engine, s.outbox)


def concurrent_reset(engine, clock):
    doctor(engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda i: auth.request_reset(engine, clock, PHONE, str(i)), range(4))
        )
    assert all(results)
    assert len(rows(engine, s.auth_codes)) == 3
    assert sum(r["used_at"] is None for r in rows(engine, s.auth_codes)) == 1


def test_concurrent_reset(engine, frozen_clock):
    concurrent_reset(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_reset_serialization(postgres_engine, frozen_clock):
    concurrent_reset(postgres_engine, frozen_clock)


def test_throttled_request_redacts_expired_but_keeps_live_code(engine, frozen_clock):
    doctor(engine)
    for _ in range(3):
        auth.request_reset(engine, frozen_clock, PHONE, "ip")
    code = reset_code(engine)
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert code in rows(engine, s.outbox)[-1]["body"]
    assert rows(engine, s.auth_codes)[-1]["used_at"] is None
    frozen_clock.advance(minutes=10)
    auth.request_reset(engine, frozen_clock, PHONE, "ip")
    assert len(rows(engine, s.auth_codes)) == 3
    assert all(r["body"] == "[redacted]" for r in rows(engine, s.outbox))
