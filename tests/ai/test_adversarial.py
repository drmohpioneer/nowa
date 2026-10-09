import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.ai.cards import ui
from nowa.ai.conversation import handle_turn
from nowa.ai.live_test import DENYLIST, SEEDED_IDENTITIES, injection_pass, snapshot
from nowa.ai.sessions import create_session
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.seed import seed
from tests.ai.support import BASE, book_output, day_payload, output, session, tap, turn
from tests.ai.test_scenarios import rows

ROOT = Path(__file__).resolve().parents[2]
MESSAGES = json.loads((ROOT / "tests/fixtures/injection_messages.json").read_text())


@pytest.mark.parametrize("sandbox", [True, False])
@pytest.mark.parametrize("variant", ["claims", "extra", "names", "questions"])
def test_injection_denylist(chat, engine, sandbox, variant):
    client, app, clinic = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(is_sandbox=sandbox))
        for name, phone in SEEDED_IDENTITIES:
            conn.execute(s.patients.insert().values(clinic_id=clinic, name=name))
            conn.execute(s.contacts.insert().values(clinic_id=clinic, phone_e164=phone))
        conn.execute(
            s.evenings.insert().values(
                clinic_id=clinic, date=__import__("datetime").date(2026, 10, 1)
            )
        )
    candidate = output(reply="تم إلغاء حجز كريم")
    if variant == "extra":
        candidate = json.dumps(candidate.model_dump(mode="json") | {"action": "cancel"})
    if variant == "names":
        candidate = output(
            reply="Here is " + SEEDED_IDENTITIES[0][0] + " " + SEEDED_IDENTITIES[1][1]
        )
    if variant == "questions":
        candidate = output(intent="question_for_doctor")
    adapter = FixtureAdapter(candidate)
    app.state.ai_chain = [adapter]
    for message in MESSAGES:
        key = session(client)
        before = snapshot(engine)
        data = turn(client, key, message)
        assert injection_pass(before, snapshot(engine), data["reply"])
    for prompt in adapter.prompts:
        for name, phone in SEEDED_IDENTITIES:
            assert name not in prompt.system + prompt.conversation
            assert phone not in prompt.system + prompt.conversation
    assert bool(rows(engine, s.rate_counters)) is not sandbox
    assert bool(rows(engine, s.judge_counters)) is sandbox
    assert set(DENYLIST) == {
        "bookings",
        "outbox",
        "timers",
        "consents",
        "patients",
        "contacts",
        "health_record",
        "visits",
        "evening_taps",
    }


def test_lookup_success_and_lockout_across_sessions(chat, engine, frozen_clock):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    tap(client, key, day_payload(turn(client, key)))
    new = session(client)
    result = client.post(
        BASE + "/lookup",
        json=dict(session=new, name="Karim Father", last4="0777", idempotency_key="ok"),
    )
    assert (
        result.status_code == 200
        and "number 1" in result.json()["reply"]
        or "رقم 1" in result.json()["reply"]
    )
    stored = rows(engine, s.chat_sessions)[-1]
    assert stored["contact_id"] and stored["patient_id"]
    assert "Karim" not in result.json()["reply"] and "/l/" not in result.json()["reply"]
    for i in range(5):
        result = client.post(
            BASE + "/lookup",
            json=dict(
                session=session(client), name="Karim Father", last4="0000", idempotency_key=str(i)
            ),
        )
        assert result.status_code == 200
        if i == 3:
            frozen_clock.advance(minutes=14)
    assert len(rows(engine, s.verify_attempts)) == 10
    frozen_clock.advance(minutes=2)  # Early failures aged out, lock lasts 15 min from fifth.
    result = client.post(
        BASE + "/lookup",
        json=dict(
            session=session(client), name="Karim Father", last4="0777", idempotency_key="locked"
        ),
    )
    assert result.json()["reply"] == ui("lookup_locked", "ar")
    frozen_clock.advance(minutes=14)
    result = client.post(
        BASE + "/lookup",
        json=dict(
            session=session(client), name="Karim Father", last4="0777", idempotency_key="unlocked"
        ),
    )
    assert result.json()["reply"] != ui("lookup_locked", "ar")


def test_real_ip_lock_is_only_recorded(chat, engine):
    client, app, clinic = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(is_sandbox=False))
    for i in range(6):
        response = client.post(
            BASE + "/lookup",
            json=dict(
                session=session(client), name=f"Person {i}", last4="0000", idempotency_key=str(i)
            ),
        )
        assert response.json()["reply"] == ui("lookup_failed", "ar")
    assert any(r["kind"] == "would_have_blocked" for r in rows(engine, s.action_record))


def test_cross_clinic_and_specialty_gate(chat, engine):
    client, _, clinic = chat
    key = session(client)
    with write_tx(engine) as conn:
        source = dict(
            conn.execute(select(s.clinics).where(s.clinics.c.id == clinic)).mappings().one()
        )
        source.pop("id")
        conn.execute(s.clinics.insert().values(**(source | {"slug": "other"})))
        conn.execute(s.clinics.insert().values(**(source | {"slug": "eyes", "specialty": "eye"})))
    for path, data in [
        ("turn", dict(text="hello", history=[])),
        ("tap", dict(action="none", payload={"faq": "price"})),
        ("lookup", dict(name="Person", last4="1234")),
    ]:
        assert (
            client.post(
                "/c/other/" + path, json=dict(session=key, idempotency_key="one", **data)
            ).status_code
            == 404
        )
    assert client.get("/c/eyes").status_code == 503
    assert client.get("/c/absent").status_code == 404
    assert client.get(BASE).status_code == 200


def test_no_keys_safe_and_no_judge_cap(chat, engine):
    client, app, clinic = chat
    del app.state.ai_chain
    key = session(client)
    assert "123" in turn(client, key)["reply"]
    assert not rows(engine, s.usage)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(judge_id=None))
    spy = FixtureAdapter(AssertionError("adapter must not be called"))
    app.state.ai_chain = [spy]
    public_session = session(client)
    blocked = client.post(BASE + "/turn", json=dict(
        session=public_session, text="hello", idempotency_key="public-blocked-turn"
    ))
    assert blocked.status_code == 403
    # The demo guard blocks the HTTP text surface; retain proof that the accepted core
    # cap itself returns its fixed reply and never reaches an adapter.
    capped = asyncio.run(handle_turn(
        clinic, public_session, "hello", "core-cap-proof", [],
        engine=engine, clock=app.state.clock, chain=[spy], client_ip="fixture"
    ))
    assert capped.reply.startswith("Chat is unavailable") and capped.buttons
    assert not spy.prompts
    faq = client.post(
        BASE + "/tap",
        json=dict(session=key, idempotency_key="faq", action="none", payload={"faq": "price"}),
    )
    assert faq.status_code == 200 and "300" in faq.json()["reply"]


def test_pending_turn_replay_and_no_open_model_transaction(chat, engine, frozen_clock):
    _, _, clinic = chat
    key = create_session(engine, frozen_clock, clinic)

    class PendingAdapter(FixtureAdapter):
        async def generate(self, prompt, schema, timeout_s):
            # The replay must see the committed claim while the first call is still running.
            with pytest.raises(HTTPException) as caught:
                await handle_turn(
                    clinic,
                    key,
                    "hello",
                    "same",
                    [],
                    engine=engine,
                    clock=frozen_clock,
                    chain=[FixtureAdapter(AssertionError())],
                )
            assert caught.value.status_code == 409
            with write_tx(engine) as conn:
                conn.execute(
                    s.clinics.update().where(s.clinics.c.id == clinic).values(cushion_min=10)
                )
            return await super().generate(prompt, schema, timeout_s)

    result = asyncio.run(
        handle_turn(
            clinic,
            key,
            "hello",
            "same",
            [],
            engine=engine,
            clock=frozen_clock,
            chain=[PendingAdapter(output())],
        )
    )
    assert result.reply == "Welcome"
    assert rows(engine, s.judge_counters)[0]["ai_msgs"] == 1


def check_judge_concurrency(engine, clock):
    seed(engine)
    with write_tx(engine) as conn:
        clinic = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(is_sandbox=True, judge_id="cap")
        )
        conn.execute(
            s.judge_counters.insert().values(
                judge_id="cap", ai_msgs=199, updated_at=clock.now(clinic)
            )
        )
    keys = [create_session(engine, clock, clinic) for _ in range(20)]
    adapter = FixtureAdapter(output())

    def call(key):
        return asyncio.run(
            handle_turn(
                clinic, key, "hello", "one", [], engine=engine, clock=clock, chain=[adapter]
            )
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(call, keys))
    assert len(adapter.prompts) == 1
    assert sum(r.reply == "Welcome" for r in results) == 1
    assert rows(engine, s.judge_counters)[0]["ai_msgs"] == 200


def test_judge_concurrency(engine, frozen_clock):
    check_judge_concurrency(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_judge_concurrency(postgres_engine, frozen_clock):
    check_judge_concurrency(postgres_engine, frozen_clock)


def test_caps_daily_budget_and_real_watch(chat, engine, monkeypatch):
    client, app, clinic = chat
    key = session(client)
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "0")
    get_settings.cache_clear()
    adapter = app.state.ai_chain[0]
    assert turn(client, key)["reply"].startswith("Chat is unavailable")
    assert not adapter.prompts and not rows(engine, s.judge_counters)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(is_sandbox=False))
        conn.execute(s.chat_sessions.update().values(ai_msg_count=30))
    monkeypatch.setenv("AI_CLINIC_DAILY_CEILING", "2")
    get_settings.cache_clear()
    assert turn(client, key)["reply"] == "Welcome"
    assert turn(client, key)["reply"] == "Welcome"
    assert turn(client, key)["reply"].startswith("Chat is unavailable")
    assert len(adapter.prompts) == 2
    assert len([r for r in rows(engine, s.action_record) if r["kind"] == "would_have_blocked"]) == 3
    assert not rows(engine, s.judge_counters)


def check_emergency_tap_race(engine, clock):
    import threading

    from nowa.ai.actions import tap as tap_command
    from nowa.messaging.templates import render_emergency

    seed(engine)
    with write_tx(engine) as conn:
        clinic = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(is_sandbox=True, judge_id="race")
        )
    key = create_session(engine, clock, clinic)
    card = asyncio.run(
        handle_turn(
            clinic,
            key,
            "hello",
            "card",
            [],
            engine=engine,
            clock=clock,
            chain=[FixtureAdapter(book_output())],
        )
    )
    payload = day_payload(card.model_dump())
    start = threading.Barrier(2)

    def emergency_turn():
        start.wait()
        return asyncio.run(
            handle_turn(
                clinic,
                key,
                "hello",
                "emergency",
                [],
                engine=engine,
                clock=clock,
                chain=[FixtureAdapter(output(triage="emergency"))],
            )
        )

    def booking_tap():
        start.wait()
        return tap_command(clinic, key, "confirm", payload, "tap", engine=engine, clock=clock)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(emergency_turn), pool.submit(booking_tap)
        emergency_result, tap_result = first.result(), second.result()
    assert emergency_result.state == "locked_emergency"
    booked = rows(engine, s.bookings)
    assert len(booked) in (0, 1)
    if not booked:
        assert tap_result.reply == render_emergency("general", "en")
    after = snapshot(engine)
    assert tap_command(
        clinic, key, "confirm", payload, "tap", engine=engine, clock=clock
    ).reply == (render_emergency("general", "en"))
    assert snapshot(engine) == after


def test_emergency_tap_race(engine, frozen_clock):
    check_emergency_tap_race(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_emergency_tap_race(postgres_engine, frozen_clock):
    check_emergency_tap_race(postgres_engine, frozen_clock)


def test_budget_uses_usage_day_not_sandbox_virtual_day(chat, engine, frozen_clock):
    from nowa import record
    from nowa.ai.caps import acquire_ai_turn
    from nowa.clock import ClinicOffsetClock

    _, _, clinic = chat
    clock = ClinicOffsetClock(frozen_clock, engine)
    record.configure(clock)
    with write_tx(engine) as conn:
        record.record_usage(conn, clinic, "fictional-judge", "ai", 1, 10)
        conn.execute(
            s.clinics.update().where(s.clinics.c.id == clinic).values(clock_offset_s=172800)
        )
    with write_tx(engine) as conn:
        config = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic)).mappings().one()
        assert not acquire_ai_turn(conn, clock, config, {"ai_msg_count": 0}, "test")
    assert not rows(engine, s.judge_counters)


def test_real_daily_ceiling_does_not_reset_at_utc_midnight(chat, engine, frozen_clock, monkeypatch):
    from nowa.ai.caps import acquire_ai_turn

    _, _, clinic = chat
    monkeypatch.setenv("AI_CLINIC_DAILY_CEILING", "1")
    get_settings.cache_clear()
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(is_sandbox=False))
    frozen_clock.advance(minutes=7 * 60)  # Next day 02:00 Cairo, still previous UTC day.
    with write_tx(engine) as conn:
        config = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic)).mappings().one()
        assert acquire_ai_turn(conn, frozen_clock, config, {"ai_msg_count": 0}, "test")
    frozen_clock.advance(minutes=2 * 60)  # Same local day, next UTC day.
    with write_tx(engine) as conn:
        assert not acquire_ai_turn(conn, frozen_clock, config, {"ai_msg_count": 0}, "test")


def test_lost_turn_claim_race_is_pending_without_effects(chat, engine, frozen_clock, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.engine import Connection
    from sqlalchemy.sql import Select

    from nowa.ai.sessions import session_hash

    _, _, clinic = chat
    key = create_session(engine, frozen_clock, clinic)
    with write_tx(engine) as conn:
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=clinic,
                key=f"chat_turn:{session_hash(key)}:race",
                command="chat_turn",
                result_json={},
                created_at=frozen_clock.now(clinic),
            )
        )
    before = rows(engine, s.chat_sessions)
    original = Connection.execute
    hidden = False

    def execute(conn, statement, *args, **kwargs):
        nonlocal hidden
        if (
            not hidden
            and isinstance(statement, Select)
            and list(statement.selected_columns) == [s.idempotency_keys.c.result_json]
        ):
            hidden = True
            # Simulate SELECT seeing no row, but the claim INSERT seeing the winner's row.
            return SimpleNamespace(first=lambda: None)
        return original(conn, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", execute)
    adapter = FixtureAdapter(AssertionError("loser must not call AI"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            handle_turn(
                clinic, key, "hello", "race", [], engine=engine, clock=frozen_clock, chain=[adapter]
            )
        )
    assert caught.value.status_code == 409 and hidden
    assert not adapter.prompts
    assert rows(engine, s.chat_sessions) == before
    assert not rows(engine, s.judge_counters) and not rows(engine, s.usage)
    assert not rows(engine, s.action_record) and not rows(engine, s.rate_counters)
    assert len(rows(engine, s.idempotency_keys)) == 1


@pytest.mark.postgres
def test_postgres_same_key_two_threads(postgres_engine, frozen_clock):
    from concurrent.futures import FIRST_COMPLETED, wait
    from threading import Barrier, Event

    engine = postgres_engine
    seed(engine)
    clinic = next(row["id"] for row in rows(engine, s.clinics) if row["slug"] == "dr-hesham")
    with write_tx(engine) as conn:
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(is_sandbox=True, judge_id="claim-race")
        )
    key = create_session(engine, frozen_clock, clinic)
    start, entered, release = Barrier(2), Event(), Event()

    class BlockingAdapter(FixtureAdapter):
        async def generate(self, prompt, schema, timeout_s):
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
            return await super().generate(prompt, schema, timeout_s)

    adapter = BlockingAdapter(output())

    def call():
        start.wait(timeout=5)
        try:
            return asyncio.run(
                handle_turn(
                    clinic,
                    key,
                    "hello",
                    "race",
                    [],
                    engine=engine,
                    clock=frozen_clock,
                    chain=[adapter],
                )
            )
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
        try:
            assert entered.wait(5)
            done, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(done) == 1 and next(iter(done)).result() == 409
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert sum(r == 409 for r in results) == 1
    assert sum(getattr(r, "reply", None) == "Welcome" for r in results) == 1
    assert len(adapter.prompts) == 1
    assert rows(engine, s.chat_sessions)[0]["turn_seq"] == 1
    assert rows(engine, s.judge_counters)[0]["ai_msgs"] == 1
    assert rows(engine, s.usage)[0]["units"] == 1
    assert len(rows(engine, s.idempotency_keys)) == 1
    assert len(rows(engine, s.action_record)) == 2
