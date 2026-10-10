"""Full-day draft, Telegram prerequisite and standby board surfaces."""

import uuid

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.config import get_settings
from nowa.core import booking, flows
from nowa.db import write_tx
from nowa.telegram import linking
from tests.ai.support import BASE, book_output, day_payload, session, tap, turn
from tests.core.test_standby import cancel, offer_code
from tests.test_booking import request
from tests.web.support import ORIGIN, fields


def choose(client, key, data, id):
    b = next(b for b in data["buttons"] if b["id"] == id)
    result = client.post(
        BASE + "/tap",
        json={
            "session": key,
            "idempotency_key": uuid.uuid4().hex,
            "action": b["action"]["kind"],
            "payload": b["action"]["payload"],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def wanted(chat, engine, frozen_clock, lang="en", real=False):
    client, app, cid = chat
    if real:
        with write_tx(engine) as conn:
            conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(max_per_evening=1))
    booked = flows.book(engine, frozen_clock, request(cid, 1))
    assert isinstance(booked, booking.BookingOk)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    data = turn(client, key, "English please" if lang == "en" else "بالعربي")
    assert {b["id"] for b in data["buttons"]} >= {"standby", "day:2026-10-08"}
    selected = choose(client, key, data, "standby")
    assert day_payload(selected)["draft"]["standby"]
    return key, selected, booked


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_linked_join_confirmation_and_duplicate(chat, engine, frozen_clock, lang):
    client, app, cid = chat
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164="+201000000777",
                kind="patient",
                telegram_chat_id="fictional",
                linked_at=frozen_clock.now(cid),
            )
        )
    key, selected, booked = wanted(chat, engine, frozen_clock, lang)
    result = tap(client, key, day_payload(selected))
    assert "1" in result["reply"] and ("تليجرام" if lang == "ar" else "Telegram") in result["reply"]
    assert not result["booking_confirmed"] and not result["standby_pending"]
    assert "/s/" not in str(result) and "/l/" not in str(result)
    with engine.connect() as conn:
        row = conn.execute(select(s.standbys)).mappings().one()
        assert row["position"] == 1 and row["state"] == "waiting"
        assert conn.execute(select(s.bookings)).mappings().all()[0]["id"] == booked.booking_id
    # Same signed submission is replayable without another standby or consent.
    assert tap(client, key, day_payload(selected)) == result


def test_missing_telegram_completes_only_after_contact_proof(chat, engine, frozen_clock):
    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    key, selected, booked = wanted(chat, engine, frozen_clock, real=True)
    result = tap(client, key, day_payload(selected))
    assert result["standby_pending"] and result["telegram_url"]
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()
        assert len(conn.execute(select(s.bookings)).all()) == 1
    payload = result["telegram_url"].split("start=")[1]
    assert linking.consume(engine, frozen_clock, "900", payload, "start") == "share_contact"
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()
    assert (
        linking.prove_contact(engine, frozen_clock, "900", 900, 901, "01000000777", "wrong")
        == "contact_mismatch"
    )
    assert (
        linking.prove_contact(engine, frozen_clock, "900", 900, 900, "01000000777", "proof")
        == "linked"
    )
    confirmed = choose(client, key, result, "standby_status")
    assert not confirmed["standby_pending"] and "1" in confirmed["reply"]
    with engine.connect() as conn:
        standby = conn.execute(select(s.standbys)).mappings().one()
        assert standby["state"] == "waiting"
    cancel(engine, frozen_clock, booked.booking_id)
    code = offer_code(engine, standby["id"])
    page = client.get(f"/s/{code}/take")
    taken = client.post(
        f"/s/{code}/take", data=fields(page, "/take") | {"action": "take"}, headers=ORIGIN
    )
    assert taken.status_code == 200
    with engine.connect() as conn:
        assert conn.execute(select(s.standbys.c.state)).scalar_one() == "taken"
        assert len(conn.execute(select(s.consents)).all()) == 2


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_board_count_report_and_demo_facts(chat, engine, frozen_clock, lang):
    import json
    import subprocess
    from datetime import datetime
    from pathlib import Path

    from nowa.clock import CAIRO
    from nowa.core import report
    from nowa.web.strings import DOCTOR_TEXTS

    client, app, cid = chat
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164="+201000000777",
                kind="patient",
                telegram_chat_id="fictional",
                linked_at=frozen_clock.now(cid),
            )
        )
    key, selected, booked = wanted(chat, engine, frozen_clock, lang)
    tap(client, key, day_payload(selected))
    frozen_clock.advance(
        minutes=(datetime(2026, 10, 6, 16, tzinfo=CAIRO) - frozen_clock.now(cid)).total_seconds()
        / 60
    )
    assert (
        client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        ).status_code
        == 200
    )
    data = client.get("https://testserver/d/api/tonight", params={"lang": lang}).json()
    assert data["standby_count"] == 1
    assert 'id="standby-count"' in client.get("https://testserver/d", params={"lang": lang}).text
    result = subprocess.run(
        ["node", "tests/web/doctor_board_dom.cjs"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        input=json.dumps(
            {"states": [data], "texts": {k: v[lang == "en"] for k, v in DOCTOR_TEXTS.items()}}
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cancel(engine, frozen_clock, booked.booking_id)
    with engine.connect() as conn:
        sid = conn.execute(select(s.standbys.c.id)).scalar_one()
    code = offer_code(engine, sid)
    page = client.get(f"/s/{code}/take")
    client.post(f"/s/{code}/take", data=fields(page, "/take") | {"action": "take"}, headers=ORIGIN)
    with engine.connect() as conn:
        value = report.build_report(conn, frozen_clock, cid, data["evening_id"])
        assert value.standby_taken == 1
    assert client.get("https://testserver/d/api/tonight").json()["standby_count"] == 0


@pytest.mark.parametrize("invalidation", ["emergency", "edit", "stop"])
def test_pending_proof_cannot_join_a_changed_or_emergency_draft(
    chat, engine, frozen_clock, invalidation
):
    from nowa.ai.sessions import session_hash

    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    key, selected, _ = wanted(chat, engine, frozen_clock, real=True)
    result = tap(client, key, day_payload(selected))
    payload = result["telegram_url"].split("start=")[1]
    linking.consume(engine, frozen_clock, "900", payload, "start")
    # Apply the same session invalidations used by the conversation/step layers.
    with write_tx(engine) as conn:
        values = (
            {"state": "locked_emergency", "draft": None}
            if invalidation == "emergency"
            else {"draft": None}
            if invalidation == "stop"
            else {"turn_seq": s.chat_sessions.c.turn_seq + 1}
        )
        conn.execute(
            s.chat_sessions.update()
            .where(s.chat_sessions.c.session_key_hash == session_hash(key))
            .values(**values)
        )
    assert (
        linking.prove_contact(engine, frozen_clock, "900", 900, 900, "01000000777", "proof")
        == "linked"
    )
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()


def test_unconfigured_linking_explains_and_offers_next_day(chat, engine, frozen_clock):
    client, app, cid = chat
    key, selected, _ = wanted(chat, engine, frozen_clock, real=True)
    shown = tap(client, key, day_payload(selected))
    assert not shown["standby_pending"] and not shown["telegram_url"]
    assert "unavailable" in shown["reply"]
    assert any(b["action"]["payload"].get("date") == "2026-10-08" for b in shown["buttons"])
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()


def test_other_person_permission_and_tampered_mode(chat, engine, frozen_clock):
    from nowa.ai.cards import ui

    client, app, cid = chat
    key, selected, _ = wanted(chat, engine, frozen_clock)
    result = client.post(
        BASE + "/tap",
        json={
            "session": key,
            "idempotency_key": "other",
            "action": "set_for",
            "payload": {"booking_for": "other"},
        },
    )
    assert result.status_code == 200
    selected = result.json()
    assert selected["buttons"][0]["label"] == ui("confirm_other", "en")
    payload = day_payload(selected)
    payload["draft"]["standby"] = False
    refused = tap(client, key, payload)
    assert refused["reply"] == ui("dead_draft", "en")
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()


def test_second_session_same_phone_gets_existing_position(chat, engine, frozen_clock):
    client, app, cid = chat
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164="+201000000777",
                kind="patient",
                telegram_chat_id="fictional",
                linked_at=frozen_clock.now(cid),
            )
        )
    key, selected, _ = wanted(chat, engine, frozen_clock, "ar")
    tap(client, key, day_payload(selected))
    key, selected, _ = wanted(chat, engine, frozen_clock, "ar")
    shown = tap(client, key, day_payload(selected))
    assert shown["reply"] == "إنت في القايمة خلاص، رقمك 1."
    with engine.connect() as conn:
        assert len(conn.execute(select(s.standbys)).all()) == 1


def test_practice_patient_joins_waiting_list_without_telegram(chat, engine, frozen_clock):
    from nowa.messaging.outbox import screen_messages

    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    key, selected, booked = wanted(chat, engine, frozen_clock)
    result = tap(client, key, day_payload(selected))
    assert not result["standby_pending"] and not result["telegram_url"]
    assert "1" in result["reply"]
    with engine.connect() as conn:
        row = conn.execute(select(s.standbys)).mappings().one()
        assert row["state"] == "waiting" and row["position"] == 1
        assert not conn.execute(select(s.telegram_links)).first()
    # A freed place shows the offer, with its take link, on the drawn phone.
    cancel(engine, frozen_clock, booked.booking_id)
    code = offer_code(engine, row["id"])
    with engine.connect() as conn:
        offers = [m for m in screen_messages(conn, cid, 0) if m.template_id == "op:standby_offer"]
    assert len(offers) == 1 and f"/s/{code}/take" in offers[0].body
    page = client.get(f"/s/{code}/take")
    taken = client.post(
        f"/s/{code}/take", data=fields(page, "/take") | {"action": "take"}, headers=ORIGIN
    )
    assert taken.status_code == 200
    with engine.connect() as conn:
        assert conn.execute(select(s.standbys.c.state)).scalar_one() == "taken"
        live = select(s.bookings).where(s.bookings.c.state != "cancelled")
        assert len(conn.execute(live).all()) == 1


def test_real_clinic_waiting_list_still_needs_telegram(chat, engine, frozen_clock):
    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    key, selected, _ = wanted(chat, engine, frozen_clock, real=True)
    result = tap(client, key, day_payload(selected))
    assert result["standby_pending"] and result["telegram_url"]
    with engine.connect() as conn:
        assert not conn.execute(select(s.standbys)).first()
