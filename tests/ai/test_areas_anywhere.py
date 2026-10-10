"""chat presentation and origin acceptance regressions."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.ai.cards import ui
from nowa.core.text_norm import western_digits
from nowa.db import write_tx
from tests.ai.support import BASE, book_output, session, turn


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_neutral_unlisted_wording(lang):
    assert (
        ui("outside_summary", lang, place="Fictional Place")
        == {
            "ar": "Fictional Place (خارج القايمة)",
            "en": "Fictional Place (not on the list)",
            "franco": "Fictional Place (khareg el kayma)",
        }[lang]
    )
    assert (
        ui("area_outside", lang, place="Fictional Place")
        == {
            "ar": "تمام، من Fictional Place. هنحسب وقت الطريق على الطريق ده.",
            "en": "Got it, from Fictional Place. We'll allow time for that trip.",
            "franco": "Tamam, men Fictional Place. Hane7seb wakt el taree2 lel meshwar da.",
        }[lang]
    )


def test_no_outside_cairo_claim_in_product():
    root = Path(__file__).resolve().parents[2] / "nowa"
    for path in root.rglob("*"):
        if path.suffix in {".py", ".js", ".html", ".json", ".txt"}:
            source = path.read_text().casefold()
            assert not any(
                p in source for p in ("outside cairo", "برة القاهرة", "barra el qahera")
            ), path


def add_extra_area(engine):
    with write_tx(engine) as conn:
        return conn.execute(
            s.areas.insert()
            .values(
                name_en="Fictional Unfeatured District", name_ar="منطقة اختبار", lat=30.2, lng=31.4
            )
            .returning(s.areas.c.id)
        ).scalar_one()


def test_location_payload_all_rows_coordinates_only(chat, engine):
    client, _, _ = chat
    extra_id = add_extra_area(engine)
    html = client.get(BASE).text
    config = json.loads(
        re.search(r'<script id="chat-config" type="application/json">(.*?)</script>', html, re.S)[1]
    )
    with engine.connect() as conn:
        ids = list(conn.execute(select(s.areas.c.id)).scalars())
    assert sorted(a["id"] for a in config["areas"]) == sorted(ids)
    assert extra_id in ids
    assert all(set(a) == {"id", "lat", "lng"} for a in config["areas"])
    assert len(json.dumps(config["areas"]).encode()) < len(ids) * 80


def test_area_list_stays_featured_and_invites_other_places(chat, engine):
    client, app, _ = chat
    add_extra_area(engine)
    key = session(client)
    candidate = book_output()
    candidate.fields.area = None
    app.state.ai_chain = [FixtureAdapter(candidate)]
    turn(client, key, "عايز أحجز")
    candidate.fields.area = "إيه المناطق؟"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    shown = turn(client, key, "إيه المناطق؟")
    with engine.connect() as conn:
        names = list(
            conn.execute(select(s.areas.c.name_ar).order_by(s.areas.c.id).limit(12)).scalars()
        )
    assert all(western_digits(name) in shown["reply"] for name in names)
    assert "منطقة اختبار" not in shown["reply"]
    assert "واكتب أي منطقة تانية" in shown["reply"]


@pytest.mark.parametrize(
    "mode", ["real", "raw", "private", "sandbox", "offline", "alias", "ambiguous", "emergency"]
)
def test_geocoding_in_chat_respects_boundaries(chat, engine, monkeypatch, mode):
    import httpx

    from nowa.config import get_settings
    from nowa.core import geocoding
    from tests.ai.support import day_payload, tap
    from tests.core.test_geocoding import feature

    client, app, clinic_id = chat
    monkeypatch.setenv("MAPBOX_TOKEN", "fictional-mapbox-token")
    if mode == "offline":
        monkeypatch.setenv("DEMO_NO_NETWORK", "true")
    get_settings.cache_clear()
    if mode != "sandbox":
        with write_tx(engine) as conn:
            conn.execute(
                s.clinics.update().where(s.clinics.c.id == clinic_id).values(is_sandbox=False)
            )
    calls = []

    def handler(request):
        assert engine.pool.checkedout() == 0
        calls.append(request.url.params["q"])
        if mode in ("raw", "private") and len(calls) == 1:
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json=feature())

    candidate = book_output()
    candidate.fields.area = "Fictional District" if mode != "alias" else "Maadi"
    if mode == "emergency":
        candidate.triage = "emergency"
        candidate.emergency_kind = "general"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    adapter_type = geocoding.GeocodeAdapter
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        monkeypatch.setattr(
            geocoding, "GeocodeAdapter", lambda token, timeout: adapter_type(token, timeout, http)
        )
        text = "مدينة" if mode == "ambiguous" else "from Fictional District"
        if mode == "private":
            text = "Karim Father 01000000777 from Fictional District"
        shown = turn(client, key, text, key="origin")
        turn(client, key, text, key="origin")  # Replay makes no second paid call.
    assert calls == {
        "real": ["fictional district"],
        "raw": ["fictional district", "from Fictional District"],
        "private": ["fictional district"],
    }.get(mode, [])
    if mode in ("ambiguous", "emergency"):
        assert not any(b["action"]["kind"] == "confirm" for b in shown["buttons"])
    else:
        area_id = day_payload(shown)["draft"]["area_id"]
        if mode in ("real", "raw"):
            booked = tap(client, key, day_payload(shown))
            assert booked["booking_confirmed"]
            with engine.connect() as conn:
                assert (
                    conn.execute(
                        select(s.areas.c.source).where(s.areas.c.id == area_id)
                    ).scalar_one()
                    == "geocoded"
                )
                assert conn.execute(select(s.bookings.c.area_id)).scalar_one() == area_id
            assert "not on the list" not in shown["reply"]
        elif mode == "alias":
            assert area_id == 5
        else:
            assert area_id is None


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_signed_origin_saved_and_tampering_refused(chat, engine, lang):
    from tests.ai.support import day_payload, tap

    client, app, _ = chat
    candidate = book_output()
    candidate.fields.area = "Fictional District"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = client.post(BASE + "/session?lang=" + lang).json()["session"]
    shown = turn(client, key, "Fictional District")
    payload = day_payload(shown)
    assert payload["draft"]["origin_text"] == "Fictional District"
    tampered = json.loads(json.dumps(payload))
    tampered["draft"]["origin_text"] = "Different District"
    assert not tap(client, key, tampered, key="tampered").get("booking_confirmed")
    assert tap(client, key, payload, key="valid")["booking_confirmed"]
    with engine.connect() as conn:
        assert conn.execute(select(s.bookings.c.origin_text)).scalar_one() == "Fictional District"


def test_origin_cleared_when_edit_resolves_area(chat, engine):
    from tests.ai.support import day_payload, tap

    client, app, _ = chat
    candidate = book_output()
    candidate.fields.area = "Fictional District"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    turn(client, key, "Fictional District")
    edited = client.post(
        BASE + "/tap",
        json={
            "session": key,
            "action": "set_area",
            "payload": {"area_id": 5},
            "idempotency_key": "resolved",
        },
    ).json()
    payload = day_payload(edited)
    assert payload["draft"]["origin_text"] is None
    assert tap(client, key, payload)["booking_confirmed"]
    with engine.connect() as conn:
        assert conn.execute(select(s.bookings.c.origin_text)).scalar_one() is None


@pytest.mark.parametrize("linked", [False, True])
def test_standby_signed_origin_survives_telegram_proof(chat, engine, frozen_clock, linked):
    from nowa.config import get_settings
    from nowa.core import booking, flows
    from nowa.telegram import linking
    from tests.ai.support import day_payload, tap
    from tests.ai.test_standby_chat import choose
    from tests.test_booking import request

    client, app, cid = chat
    get_settings().telegram_bot_username = "fictional_bot"
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(max_per_evening=1))
        if not linked:
            # The Telegram proof path belongs to a real clinic; a practice clinic needs none.
            conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
        if linked:
            conn.execute(
                s.telegram_links.insert().values(
                    phone_e164="+201000000777",
                    kind="patient",
                    telegram_chat_id="fictional",
                    linked_at=frozen_clock.now(cid),
                )
            )
    assert isinstance(flows.book(engine, frozen_clock, request(cid, 1)), booking.BookingOk)
    candidate = book_output()
    candidate.fields.area = "Fictional District"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    offered = turn(client, key, "from Fictional District")
    selected = choose(client, key, offered, "standby")
    assert day_payload(selected)["draft"]["origin_text"] == "Fictional District"
    response = tap(client, key, day_payload(selected))
    if not linked:
        token = response["telegram_url"].split("start=")[1]
        assert linking.consume(engine, frozen_clock, "901", token, "start") == "share_contact"
        assert (
            linking.prove_contact(engine, frozen_clock, "901", 901, 901, "01000000777", "proof")
            == "linked"
        )
    with engine.connect() as conn:
        assert conn.execute(select(s.standbys.c.origin_text)).scalar_one() == "Fictional District"
