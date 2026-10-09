"""Offline acceptance paths with scripted extractor outputs."""

import copy
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.ai.cards import ui
from nowa.ai.sessions import load_session
from nowa.app import create_app
from nowa.core.areas import resolve
from nowa.core.sessions_cleanup import purge_stale_drafts
from nowa.db import write_tx
from tests.ai.support import BASE, book_output, day_payload, output, session, tap, turn


def extract(app, **fields):
    candidate = output(intent="book")
    candidate.fields = candidate.fields.model_copy(update=fields)
    app.state.ai_chain = [FixtureAdapter(candidate)]


def click(client, key, data, action=None, idem="step"):
    b = next(b for b in data["buttons"] if action is None or b["action"]["kind"] == action)
    res = client.post(
        BASE + "/tap",
        json=dict(
            session=key,
            idempotency_key=idem,
            action=b["action"]["kind"],
            payload=b["action"]["payload"],
        ),
    )
    assert res.status_code == 200, res.text
    return res.json()


def draft(engine):
    with engine.connect() as conn:
        raw = conn.execute(
            select(s.chat_sessions.c.draft).order_by(s.chat_sessions.c.id.desc())
        ).scalar()
        return json.loads(raw) if raw else None


def test_all_in_one_other_confirm_replay_and_question_asker(chat, engine):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output("other"))]
    data = turn(client, key, "احجز لوالدي Karim Father 01000000777 الثلاثاء من المعادي")
    assert len(data["buttons"]) == 2
    assert data["buttons"][0]["label"] == ui("confirm_other", "ar")
    assert "01000000777" in data["reply"] and "http" not in data["reply"]
    payload = day_payload(data)
    first = tap(client, key, payload, "confirm")
    assert first["booking_confirmed"] and draft(engine) is None
    assert tap(client, key, payload, "confirm") == first
    app.state.ai_chain = [FixtureAdapter(output(intent="question_for_doctor"))]
    shown = turn(client, key, "هل فيه تحضير للكشف؟")
    assert shown["buttons"][0]["action"] == {"kind": "none", "payload": {"lookup": True}}
    with engine.connect() as conn:
        b = conn.execute(select(s.bookings)).mappings().one()
        asker = conn.execute(select(s.question_askers)).mappings().one()
        assert (asker["patient_id"], asker["booking_id"]) == (b["patient_id"], b["id"])
        assert conn.execute(select(s.patients.c.name)).scalar_one() == "Karim Father"
        assert conn.execute(select(s.chat_sessions.c.consent_other_at)).scalar_one() is not None


def test_step_by_step_and_more_days(chat, engine):
    client, app, _ = chat
    key = session(client)
    extract(app)
    who = turn(client, key, "عايز احجز")
    assert [b["label"] for b in who["buttons"]] == ["ليا", "لحد تاني"]
    assert click(client, key, who)["reply"] == ui("name_ask", "ar")
    extract(app, name="أميرة محمود")
    assert turn(client, key, "أميرة محمود")["reply"] == ui("phone_ask", "ar")
    extract(app, phone="٠١٠١٢٣٤٥٦٧٨")
    days = turn(client, key, "٠١٠١٢٣٤٥٦٧٨")
    assert len(days["buttons"]) == 4
    more = click(client, key, days, "more_days", "more")
    assert len(more["buttons"]) == 7
    assert {b["id"] for b in days["buttons"] if b["id"] != "more_days"} <= {
        b["id"] for b in more["buttons"]
    }
    assert "more_days" not in {b["id"] for b in more["buttons"]}
    area = click(client, key, more, "book", "day")
    assert area["reply"] == ui("area_ask", "ar")
    assert area["buttons"][0]["id"] == "location"
    extract(app, area="Maadi")
    final = turn(client, key, "من المعادي")
    assert len(final["buttons"]) == 2 and day_payload(final)
    assert draft(engine)["phone"] == "+201012345678"


@pytest.mark.parametrize(
    "phone,count", [("010000000", "9"), ("0101234567", "10"), ("٠١٠٠٠٠٠٠٠", "9")]
)
def test_wrong_phone_names_problem(chat, phone, count):
    client, app, _ = chat
    extract(app, booking_for="self", name="كريم", phone=phone)
    data = turn(client, session(client), phone)
    assert data["reply"] == ui("phone_invalid", "ar", count=count)
    assert not data["buttons"]


def test_out_of_order_area_outside_and_closed_day(chat, engine):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="other", area="المنصورة")
    data = turn(client, key, "عايز احجز لوالدتي من المنصورة")
    assert "من المنصورة" in data["reply"] and ui("name_other_ask", "ar") in data["reply"]
    assert draft(engine)["area_id"] is None
    extract(app, name="منى عادل", phone="01012345678")
    from datetime import date

    app.state.ai_chain[0] = FixtureAdapter(
        book_output("other").model_copy(
            update={
                "fields": book_output("other").fields.model_copy(
                    update={
                        "name": "منى عادل",
                        "phone": "01012345678",
                        "day": date(2026, 10, 7),
                        "area": None,
                    }
                )
            }
        )
    )
    closed = turn(client, key, "منى عادل 01012345678 الاربعاء")
    assert "مقفولة" in closed["reply"] and len(closed["buttons"]) == 4
    confirmed = click(client, key, closed, "book", "open-day")
    assert day_payload(confirmed)["draft"]["area_id"] is None
    assert "location" not in str(confirmed["buttons"])


def test_validated_fields_resist_drift_and_allow_explicit_corrections(chat, engine):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    first = turn(client, key, "Karim Father 01000000777 Tuesday Maadi")
    changed = book_output()
    from datetime import date

    changed.fields.phone = "01000000888"
    changed.fields.day = date(2026, 10, 8)
    app.state.ai_chain = [FixtureAdapter(changed)]
    turn(client, key, "no change")
    assert draft(engine)["phone"] == "+201000000777"
    assert draft(engine)["day"] == "2026-10-06"
    fixed = turn(client, key, "لا الخميس مش الثلاثاء ورقمي ٠١٠٠٠٠٠٠٨٨٨")
    assert day_payload(fixed)["draft"]["day"] == "2026-10-08"
    assert day_payload(fixed)["draft"]["phone"] == "+201000000888"
    assert not tap(client, key, day_payload(first))["booking_confirmed"]


@pytest.mark.parametrize("kind", ["out_of_scope", "question_for_doctor", "unclear", "safe"])
def test_dead_end_chips(chat, kind):
    client, app, _ = chat
    candidate = (
        "invalid"
        if kind == "safe"
        else output(triage="unclear")
        if kind == "unclear"
        else output(intent=kind)
    )
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    data = turn(client, key, "سؤال")
    assert data["buttons"][0]["label"] == "احجز كشف"
    if kind == "out_of_scope":
        assert "القلب" in data["reply"] and "cardiology" not in data["reply"]
    else:
        assert ui("next_visit", "ar") in data["reply"]
    assert click(client, key, data, "book")["reply"] == ui("booking_for_ask", "ar")


def test_health_then_book_and_combined_intent(chat, engine, monkeypatch):
    from nowa.ai import health

    client, app, _ = chat
    key = session(client)
    monkeypatch.setattr(health, "get_health_answerer", lambda: health.NoAnswerHealth())
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    data = turn(client, key, "سؤال للدكتور")
    assert click(client, key, data, "book")["reply"] == ui("booking_for_ask", "ar")

    class NoCalls:
        async def answer(self, **kwargs):
            raise AssertionError("combined booking must not call health model")

    monkeypatch.setattr(health, "get_health_answerer", lambda: NoCalls())
    app.state.ai_chain = [FixtureAdapter(book_output(is_health_question=True))]
    data = turn(client, key, "احجز وعندي سؤال")
    assert data["reply"].startswith(ui("question_noted", "ar"))
    assert day_payload(data)
    with engine.connect() as conn:
        assert len(conn.execute(select(s.questions)).all()) == 2


def test_expired_confirm_and_emergency_clear(chat, engine, frozen_clock):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    data = turn(client, key)
    frozen_clock.advance(minutes=31)
    refreshed = tap(client, key, day_payload(data))
    assert refreshed["reply"].startswith(ui("draft_expired", "en"))
    assert day_payload(refreshed)["draft"]["exp"] > day_payload(data)["draft"]["exp"]
    app.state.ai_chain = [FixtureAdapter(output(triage="emergency"))]
    turn(client, key)
    assert draft(engine) is None
    assert tap(client, key, day_payload(refreshed))["state"] == "locked_emergency"


def test_refresh_lazy_cleanup_and_maintenance(chat, engine, frozen_clock):
    client, app, clinic = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    old = session(client)
    turn(client, old)
    new = session(client)
    with write_tx(engine) as conn:
        assert load_session(conn, clinic, old, frozen_clock)["draft"] is None
        assert load_session(conn, clinic, new, frozen_clock)["draft"] is None
    turn(client, new)
    frozen_clock.advance(minutes=24 * 60 + 1)
    with write_tx(engine) as conn:
        assert load_session(conn, clinic, new, frozen_clock)["draft"] is None
    turn(client, new)
    frozen_clock.advance(minutes=24 * 60 + 1)
    with write_tx(engine) as conn:
        assert purge_stale_drafts(conn, frozen_clock) == 1
        assert purge_stale_drafts(conn, frozen_clock) == 0
    assert draft(engine) is None


def test_demo_startup_clears_abandoned_drafts(chat, engine, frozen_clock):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    turn(client, session(client))
    frozen_clock.advance(minutes=24 * 60 + 1)
    with TestClient(create_app(engine, clock=frozen_clock)):
        assert draft(engine) is None


def test_draft_never_logged_or_saved_in_replay(chat, engine, caplog):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    caplog.set_level(logging.DEBUG)
    key = session(client)
    data = turn(client, key, "Karim Father 01000000777 from Maadi")
    invalid = copy.deepcopy(day_payload(data))
    invalid["draft"]["unexpected"] = "01000000777"
    response = client.post(
        BASE + "/tap",
        json=dict(session=key, action="confirm", payload=invalid, idempotency_key="bad"),
    )
    assert response.status_code == 422 and "01000000777" not in response.text
    assert "01000000777" not in caplog.text and "+201000000777" not in caplog.text
    assert "Karim Father" not in caplog.text
    with engine.connect() as conn:
        assert "01000000777" not in str(conn.execute(select(s.action_record)).all())
        assert "+201000000777" not in str(conn.execute(select(s.idempotency_keys)).all())
        assert draft(engine)["phone"] == "+201000000777"


@pytest.mark.parametrize(
    "name,area",
    [
        (name, area)
        for area, names in enumerate(
            [
                ["مصر الجديدة", "هليوبوليس", "Heliopolis", "masr el gedida", "masr elgedida"],
                ["مدينة نصر", "مدينه نصر", "Nasr City", "madinet nasr"],
                ["مدينتي", "مدينتى", "Madinaty", "madinati"],
                ["التجمع", "التجمع الخامس", "New Cairo", "el tagamo3", "تجمع"],
                ["المعادي", "المعادى", "Maadi", "ma3adi", "el ma3adi", "معادي"],
                ["الزمالك", "زمالك", "Zamalek"],
                ["الدقي", "دقى", "Dokki", "do22i"],
                ["المهندسين", "مهندسين", "Mohandessin", "mohandeseen"],
                ["شبرا", "Shubra", "shobra"],
                ["عين شمس", "Ain Shams", "3ein shams"],
                ["العبور", "عبور", "El Obour", "obour"],
                ["أكتوبر", "٦ أكتوبر", "6th of October", "october", "6 October"],
            ],
            1,
        )
        for name in names
    ],
)
def test_area_aliases(name, area):
    assert resolve(name) == area


def test_unknown_and_outside_areas():
    assert resolve("مدينة") == "unknown"
    assert resolve("إيه المناطق؟") == "unknown"
    assert resolve("") == "unknown"
    assert resolve("Maadi or Nasr City") == "unknown"
    assert resolve("المنصورة") is None


@pytest.mark.parametrize("text,lang", [("حجز", "ar"), ("booking", "en"), ("7agz", "franco")])
def test_policy_hash_name_and_confirmation_in_each_language(chat, engine, text, lang):
    from nowa.core.consent import policy_text

    client, app, _ = chat
    candidate = book_output("other")
    candidate.fields.name = "  mona   adel  "
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    shown = turn(client, key, text)
    assert (
        shown["reply"].splitlines()[0]
        == {"ar": "الاسم: Mona Adel", "en": "Name: Mona Adel", "franco": "El esm: Mona Adel"}[lang]
    )
    assert len(shown["buttons"]) == 2
    assert shown["buttons"][0]["label"] == ui("confirm_other", lang)
    assert "http" not in shown["reply"] and "01000000777" in shown["reply"]
    confirmed = tap(client, key, day_payload(shown))
    assert confirmed["booking_confirmed"]
    with engine.connect() as conn:
        consent = conn.execute(select(s.consents)).mappings().one()
        version, hashed, _ = policy_text(lang)
        assert (consent["version"], consent["text_hash"]) == (version, hashed)
        assert consent["booking_for"] == "other"


def test_area_raw_alias_wins_and_unknown_is_asked_again(chat, engine):
    client, app, _ = chat
    candidate = book_output()
    candidate.fields.area = "Nasr City"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    first = turn(client, key, "I live in Maadi")
    assert day_payload(first)["draft"]["area_id"] == 5
    changed = turn(client, key, "Now I will come from Dokki")
    assert day_payload(changed)["draft"]["area_id"] == 7
    # The model cannot resolve an explicitly ambiguous raw answer for the patient.
    ambiguous = turn(client, key, "Maadi or Nasr City")
    assert not any(b["action"]["kind"] == "confirm" for b in ambiguous["buttons"])
    assert draft(engine)["area_text"] and "area_text" not in draft(engine)["validated"]
    fixed = turn(client, key, "Dokki")
    assert day_payload(fixed)["draft"]["area_id"] == 7


def test_area_question_and_second_ambiguous_reply_offer_names(chat, engine):
    client, app, _ = chat
    candidate = book_output()
    candidate.fields.area = None
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    turn(client, key, "حجز")
    extract(app, area="مدينة")
    assert turn(client, key, "مدينة")["reply"] == ui("area_hint", "ar")
    repeated = turn(client, key, "مدينة")
    assert "مدينة نصر" in repeated["reply"] and "المعادي" in repeated["reply"]
    extract(app, area="إيه المناطق؟")
    listed = turn(client, key, "إيه المناطق؟")
    assert "المعادي" in listed["reply"] and "العبور" in listed["reply"]
    assert len(listed["buttons"]) == 1 and listed["buttons"][0]["id"] == "location"
    assert "area_text" not in draft(engine)["validated"]


def test_old_confirm_stays_dead_after_explicit_recovery(chat, engine):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    old = day_payload(turn(client, key))
    app.state.ai_chain = [FixtureAdapter(output(triage="unclear", reply="Can you clarify?"))]
    unclear = turn(client, key)
    fresh = click(client, key, unclear, "book", "restart")
    assert not tap(client, key, old)["booking_confirmed"]
    assert tap(client, key, day_payload(fresh))["booking_confirmed"]
    assert draft(engine) is None


def test_stale_draft_cleanup_from_phone_poll_persists(chat, engine, frozen_clock):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    turn(client, key)
    frozen_clock.advance(minutes=24 * 60 + 1)
    assert client.get(BASE + "/demo/phone", params={"session": key}).status_code == 200
    assert draft(engine) is None


def test_unclear_turn_remembers_fields_without_issuing_confirm(chat, engine):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output(triage="unclear"))]
    shown = turn(client, key, "Karim Father 01000000777 Tuesday Maadi")
    assert not any(b["action"]["kind"] == "confirm" for b in shown["buttons"])
    assert draft(engine)["name"] == "Karim Father"
    assert draft(engine)["phone"] == "+201000000777"
    assert day_payload(click(client, key, shown, "book"))


# regressions from a live walk of the demo.
@pytest.mark.parametrize(
    "previous,text,expected",
    [
        ("ar", "karim hassan", "ar"),
        ("ar", "01012345678", "ar"),
        ("franco", "leya", "franco"),
        ("franco", "Ahmed Samy", "franco"),
        ("ar", "I want to book a visit please", "en"),
        ("en", "عايز أحجز كشف", "ar"),
        (None, "3ayez a7gez kashf", "franco"),
        (None, "Hi", "en"),
        ("ar", "3ayez a7gez", "ar"),
    ],
)
def test_language_sticks_to_session(previous, text, expected):
    from nowa.ai.lang import detect

    assert detect(text, previous) == expected


@pytest.mark.parametrize(
    "opening,name,lang",
    [
        ("عايز أحجز", "karim hassan", "ar"),
        ("3ayez a7gez kashf", "Ahmed Samy", "franco"),
    ],
)
def test_short_name_and_phone_keep_language_in_actual_turns(chat, opening, name, lang):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self")
    turn(client, key, opening)
    extract(app, name=name)
    assert turn(client, key, name)["lang"] == lang
    extract(app, phone="01012345678")
    assert turn(client, key, "01012345678")["lang"] == lang


@pytest.mark.parametrize(
    "field,bad,text",
    [
        ("name", "123", "123"),
        ("phone", "010123456", "010123456"),
        ("day", "2026-10-07", "tomorrow"),
        ("day", "2026-10-05", "2026-10-05"),
    ],
)
def test_rejected_field_explained_once_then_plain_question_and_way_out(
    chat, engine, field, bad, text
):
    from datetime import date

    client, app, _ = chat
    key = session(client)
    initial = dict(booking_for="self")
    if field != "name":
        initial["name"] = "كريم حسن"
    if field == "day":
        initial["phone"] = "01012345678"
    extract(app, **initial)
    turn(client, key, "عايز أحجز")
    extract(app, **{field: date.fromisoformat(bad) if field == "day" else bad})
    rejected = turn(client, key, text)
    assert (
        ui("name_invalid", "ar")
        if field == "name"
        else ui("phone_invalid", "ar", count="٩")
        if field == "phone"
        else "مواعيد"
    ) in rejected["reply"]
    assert field not in draft(engine)
    # An extractor repeating a stale bad value cannot reintroduce it on an unrelated turn.
    plain = turn(client, key, "مش عارف")
    assert ui("way_out", "ar") in plain["reply"]
    assert (
        "مقفولة" not in plain["reply"]
        and "٩ أرقام" not in plain["reply"]
        and ui("name_invalid", "ar") not in plain["reply"]
    )
    assert field not in draft(engine)
    assert len(plain["buttons"]) == (4 if field == "day" else 0)
    # A successful answer advances the step and resets the consecutive-turn counter.
    good = {"name": "كريم حسن", "phone": "01012345678", "day": date(2026, 10, 8)}[field]
    extract(app, **{field: good})
    advanced = turn(client, key, str(good))
    assert ui("way_out", "ar") not in advanced["reply"]


def test_closed_day_keeps_new_area_and_does_not_loop(chat, engine):
    from datetime import date

    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="Karim Hassan", phone="01012345678")
    turn(client, key, "عايز أحجز")
    extract(app, day=date(2026, 10, 7))
    assert "مقفولة" in turn(client, key, "tomorrow")["reply"]
    extract(app, area="Zamalek")
    shown = turn(client, key, "I'm coming from Zamalek")
    assert "closed" not in shown["reply"] and "مقفولة" not in shown["reply"]
    assert draft(engine)["area_id"] == 6
    confirmed = click(client, key, shown, "book", "chosen-day")
    assert day_payload(confirmed)["draft"]["area_id"] == 6


def test_way_out_resets_on_out_of_order_area_after_closed_day_and_hint(chat, engine):
    from datetime import date

    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="كريم حسن", phone="01012345678")
    turn(client, key, "عايز أحجز")
    extract(app, day=date(2026, 10, 7))
    closed = turn(client, key, "بكرة")
    assert "مقفولة" in closed["reply"] and ui("way_out", "ar") not in closed["reply"]
    assert draft(engine)["fruitless"] == 1
    extract(app, area="المدينة")
    hint = turn(client, key, "من المدينة")
    assert hint["reply"] == ui("area_hint", "ar")
    assert draft(engine)["fruitless"] == 2
    extract(app, area="مدينة نصر")
    progress = turn(client, key, "مدينة نصر")
    assert ui("way_out", "ar") not in progress["reply"]
    assert draft(engine)["area_id"] == 2 and draft(engine)["fruitless"] == 0
    extract(app)
    first = turn(client, key, "مش عارف")
    assert ui("way_out", "ar") not in first["reply"]
    second = turn(client, key, "مش عارف")
    third = turn(client, key, "مش عارف")
    assert ui("way_out", "ar") in second["reply"] and ui("way_out", "ar") in third["reply"]
    assert draft(engine)["area_id"] == 2
    confirmed = click(client, key, third, "book", "chosen-day")
    assert day_payload(confirmed)["draft"]["area_id"] == 2


@pytest.mark.parametrize(
    "field,value,text",
    [
        ("name", "أحمد حسن", "أحمد حسن"),
        ("phone", "01112345678", "01112345678"),
        ("booking_for", "other", "لحد تاني"),
    ],
)
def test_way_out_resets_on_correction_while_still_asking_day(chat, engine, field, value, text):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="كريم حسن", phone="01012345678")
    turn(client, key, "عايز أحجز")
    extract(app)
    turn(client, key, "مش عارف")
    assert ui("way_out", "ar") in turn(client, key, "مش عارف")["reply"]
    extract(app, **{field: value})
    corrected = turn(client, key, text)
    assert ui("way_out", "ar") not in corrected["reply"]
    assert draft(engine)["fruitless"] == 0 and draft(engine)["step"] == "day"
    extract(app)
    assert ui("way_out", "ar") not in turn(client, key, "مش عارف")["reply"]


@pytest.mark.parametrize("field", ["name", "phone", "day"])
def test_invalid_explanation_never_has_way_out_even_after_repeated_fruitless_turns(chat, field):
    from datetime import date

    client, app, _ = chat
    key = session(client)
    initial = {"booking_for": "self"}
    if field != "name":
        initial["name"] = "كريم حسن"
    if field == "day":
        initial["phone"] = "01012345678"
    extract(app, **initial)
    turn(client, key, "عايز أحجز")
    extract(app)
    turn(client, key, "مش عارف")
    assert ui("way_out", "ar") in turn(client, key, "مش عارف")["reply"]
    bad = {"name": "123", "phone": "010123456", "day": date(2026, 10, 7)}[field]
    extract(app, **{field: bad})
    rejected = turn(client, key, str(bad))
    assert ui("way_out", "ar") not in rejected["reply"]
    extract(app)
    assert ui("way_out", "ar") in turn(client, key, "مش عارف")["reply"]


@pytest.mark.parametrize(
    "phrase",
    [
        "إلغاء",
        "الغي",
        "ألغي",
        "الغاء",
        "مش عايز",
        "خلاص مش",
        "بلاش",
        "cancel",
        "stop",
        "never mind",
        "khalas",
        "balash",
        "la2 mesh 3ayez",
        "عايز ألغي",
    ],
)
def test_cancel_in_words_clears_only_draft(chat, engine, phrase):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="كريم حسن")
    turn(client, key, "عايز أحجز")
    extract(app)
    stopped = turn(client, key, phrase)
    assert stopped["reply"] == ui("booking_stopped", "ar")
    assert stopped["buttons"][0]["label"] == ui("visit_chip", "ar")
    assert draft(engine) is None
    fresh = turn(client, key, "عايز أحجز")
    assert fresh["reply"] == ui("booking_for_ask", "ar")
    assert not {"name", "phone", "day", "area_text", "booking_for"} & draft(engine).keys()


@pytest.mark.parametrize("phrase", ["عايز ألغي الحجز", "ممكن أغير اليوم؟"])
def test_confirmed_booking_changes_stay_on_telegram(chat, engine, phrase):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key, "عايز أحجز")))
    with engine.connect() as conn:
        before = {
            table.name: conn.execute(select(table)).all()
            for table in (s.bookings, s.outbox, s.timers)
        }
    extract(app, name="اسم مختلف")
    shown = turn(client, key, phrase)
    assert shown["reply"] == ui("manage_booking", "ar")
    assert shown["buttons"][0]["label"] == "شوف حجزك"
    assert draft(engine) is None
    with engine.connect() as conn:
        assert before == {
            table.name: conn.execute(select(table)).all()
            for table in (s.bookings, s.outbox, s.timers)
        }


def test_cancel_without_draft_is_normal_turn_and_emergency_still_wins(chat, engine):
    client, app, _ = chat
    key = session(client)
    assert turn(client, key, "cancel")["reply"] == "Welcome"
    extract(app, booking_for="self")
    turn(client, key, "book")
    app.state.ai_chain = [FixtureAdapter(output(triage="emergency"))]
    assert turn(client, key, "cancel chest pain")["state"] == "locked_emergency"
    assert draft(engine) is None


@pytest.mark.parametrize("step", ["day", "area"])
@pytest.mark.parametrize("place", ["من المدينة", "city", "el madina"])
def test_ambiguous_place_hints_before_any_step(chat, engine, step, place):
    client, app, _ = chat
    key = session(client)
    candidate = book_output()
    candidate.fields.area = None
    if step == "day":
        candidate.fields.day = None
    app.state.ai_chain = [FixtureAdapter(candidate)]
    turn(client, key, "عايز أحجز")
    # Even an incorrect extractor guess cannot accept the raw ambiguous answer.
    extract(app, area="المنصورة")
    shown = turn(client, key, place)
    assert shown["reply"].startswith(ui("area_hint", "ar"))
    assert "برة القاهرة" not in shown["reply"]
    assert "area_text" not in draft(engine)["validated"]


@pytest.mark.parametrize("text,lang", [("حجز", "ar"), ("Hi", "en"), ("7agz", "franco")])
def test_more_days_reply_and_same_session_lookup(chat, engine, text, lang):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="Karim Hassan", phone="01012345678")
    days = turn(client, key, text)
    more = click(client, key, days, "more_days", "more")
    assert more["reply"] == ui("more_days_reply", lang)
    assert click(client, key, days, "more_days", "more") == more
    day = click(client, key, more, "book", "day")
    extract(app, area="Maadi")
    confirm = turn(client, key, "Maadi")
    booked = tap(client, key, day_payload(confirm))
    app.state.ai_chain = [FixtureAdapter(output(intent="my_booking"))]
    found = turn(client, key, "حجزي امتى؟" if lang == "ar" else "my booking")
    assert found["reply"] == booked["reply"]
    assert not found["buttons"] and not found["telegram_url"]
    with engine.connect() as conn:
        assert not conn.execute(select(s.verify_attempts)).all()
    other = session(client)
    lookup = turn(client, other, text)
    assert lookup["buttons"][0]["label"] == ui("booking_chip", lang)
    assert day["buttons"]


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
@pytest.mark.parametrize("who", ["self", "other"])
def test_personal_name_question_and_three_line_outside_summary(chat, engine, lang, who):
    from nowa.ai.sessions import update_session

    client, app, clinic = chat
    key = session(client)
    extract(app, booking_for=who)
    opening = {"ar": "حجز", "en": "booking", "franco": "7agz"}[lang]
    asked = turn(client, key, opening)
    assert asked["reply"] == ui("name_ask" if who == "self" else "name_other_ask", lang)
    candidate = book_output(who)
    candidate.fields.area = "Mansoura"
    app.state.ai_chain = [FixtureAdapter(candidate)]
    summary = turn(client, key, "Mansoura")
    assert (
        summary["reply"].splitlines()[-4:]
        == ui(
            "confirm_summary",
            lang,
            name="Karim Father",
            phone="01000000777",
            day="الثلاثاء 6/10" if lang == "ar" else "Tue 6/10",
            area=ui("outside_summary", lang, place="Mansoura"),
        ).splitlines()
    )
    assert ui("outside_list", lang) not in summary["reply"]
    assert summary["buttons"][0]["label"] == ui(
        "confirm_other" if who == "other" else "confirm", lang
    )
    # Mask and bound a free-text outside place in the summary as well as its acknowledgement.
    with write_tx(engine) as conn:
        current = load_session(conn, clinic, key, app.state.clock)
        value = json.loads(current["draft"])
        value["area_text"] = "Mansoura 01012345678"
        update_session(conn, current, draft=json.dumps(value))
    extract(app)
    assert "01012345678" not in turn(client, key, "ok")["reply"]


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_weekly_hours_in_context_and_fourth_quick_chip(chat, engine, lang):
    from nowa.ai.cards import faq
    from nowa.ai.sessions import load_clinic, prompt_clinic, weekly_hours

    client, app, clinic = chat
    with engine.connect() as conn:
        context = prompt_clinic(conn, app.state.clock, load_clinic(conn, clinic), lang)
        hours = context["clinic_info"]["hours"]
        assert "7:00" in hours and "11:00" in hours
        assert ui("weekday_tue", lang) in hours and ui("weekday_thu", lang) in hours
        assert ui("weekday_sun", lang) in hours and ui("weekday_wed", lang) not in hours
        assert faq(conn, clinic)[-1].action.payload == {"faq": "hours"}
    page = client.get(BASE).text
    from bs4 import BeautifulSoup

    config = json.loads(BeautifulSoup(page, "html.parser").select_one("#chat-config").string)
    assert config["strings"][lang]["faq_hours"] == ui("faq_hours", lang)
    key = session(client)
    turn(client, key, {"ar": "اهلا", "en": "Hi", "franco": "7agz"}[lang])
    res = client.post(
        BASE + "/tap",
        json=dict(session=key, action="none", payload={"faq": "hours"}, idempotency_key="hours"),
    )
    assert res.json()["reply"] == hours
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.delete().where(s.clinic_hours.c.clinic_id == clinic))
        assert not weekly_hours(conn, clinic, lang)
        assert (
            "hours"
            not in prompt_clinic(conn, app.state.clock, load_clinic(conn, clinic), lang)[
                "clinic_info"
            ]
        )


def test_prompt_writing_rules_and_code_owned_clinic_info_chip(chat, engine):
    from nowa.ai.prompt import build_prompt
    from nowa.ai.sessions import load_clinic, prompt_clinic

    client, app, clinic = chat
    with engine.connect() as conn:
        context = prompt_clinic(conn, app.state.clock, load_clinic(conn, clinic))
    prompt = build_prompt(context, [], "اهلا")
    assert "everyday Egyptian dialect, never formal standard Arabic" in prompt.system
    assert "Greet only in the first reply of a session" in prompt.system
    assert "one or two short sentences" in prompt.system
    assert "Never ask for a name, phone and day together" in prompt.system
    assert "Code offers the next-step chip" in prompt.system
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(output(intent="clinic_info", reply="الكشف ٣٠٠ جنيه."))]
    info = turn(client, key, "سعر الكشف كام؟")
    assert info["reply"] == "الكشف 300 جنيه."
    assert info["buttons"][0]["label"] == "احجز كشف"
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key, "احجز")))
    app.state.ai_chain = [FixtureAdapter(output(intent="clinic_info", reply="الكشف ٣٠٠ جنيه."))]
    assert not turn(client, key, "سعر الكشف كام؟")["buttons"]


@pytest.mark.parametrize("supported", [True, False])
def test_question_for_doctor_health_uses_recorded_library_and_logs(
    chat, engine, monkeypatch, supported
):
    from pathlib import Path

    from nowa.ai import health
    from nowa.library.answer import RecordedHealthAnswerer
    from nowa.library.store import load

    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key, "احجز")))
    data_dir = Path(__file__).resolve().parents[2] / "nowa/library/data"
    load(engine, "cardiology", data_dir / "cardiology.jsonl")
    row = json.loads((data_dir / "cardiology_recorded.json").read_text())[0]
    monkeypatch.setattr(
        health, "get_health_answerer", lambda: RecordedHealthAnswerer(engine, data_dir)
    )
    app.state.ai_chain = [
        FixtureAdapter(output(intent="question_for_doctor", is_health_question=True))
    ]
    question = row["question"] if supported else "سؤال غير موجود في المكتبة"
    reply = turn(client, key, question)
    if supported:
        assert reply["reply"].startswith(row["answer"])
        assert reply["source"]["url"] == row["source_url"]
        assert reply["source"]["label"] in reply["reply"]
    else:
        assert reply["reply"].startswith("السؤال ده هيوصل للدكتور نفسه")
        assert reply["source"] is None
    with engine.connect() as conn:
        assert conn.execute(select(s.questions.c.count)).scalar_one() == 1
        records = conn.execute(select(s.health_record)).mappings().all()
        assert len(records) == int(supported)
        if supported:
            assert records[0]["reply_text"] == row["answer"]
            assert records[0]["supporting_sentence"] == row["evidence"]


@pytest.mark.parametrize(
    "intent,triage",
    [
        ("out_of_scope", "normal"),
        ("question_for_doctor", "urgent"),
        ("question_for_doctor", "emergency"),
        ("book", "normal"),
    ],
)
def test_health_routing_still_respects_scope_and_triage(chat, monkeypatch, intent, triage):
    from nowa.ai import health

    class NoCalls:
        async def answer(self, **kwargs):
            raise AssertionError("This branch must never consult the library")

    monkeypatch.setattr(health, "get_health_answerer", lambda: NoCalls())
    client, app, _ = chat
    app.state.ai_chain = [
        FixtureAdapter(output(intent=intent, triage=triage, is_health_question=True))
    ]
    shown = turn(client, session(client), "سؤال")
    if triage == "emergency":
        assert shown["state"] == "locked_emergency" and not shown["buttons"]
    elif triage == "urgent":
        from nowa.messaging.templates import render_operational

        assert shown["reply"].startswith(render_operational("triage_urgent", "ar", {}).text)


def test_stopped_draft_cannot_be_resurrected_by_extractor_history(chat, engine):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    old = day_payload(turn(client, key, "عايز أحجز"))
    turn(client, key, "عايز ألغي")
    # The model repeats the old complete fields even though this is a fresh start.
    fresh = turn(client, key, "عايز أحجز")
    assert fresh["reply"] == ui("booking_for_ask", "ar")
    assert not {"name", "phone", "day", "area_text", "booking_for"} & draft(engine).keys()
    assert not tap(client, key, old)["booking_confirmed"]


def test_unrecognized_day_is_explained_once(chat, engine):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self", name="Karim Hassan", phone="01012345678")
    turn(client, key, "عايز أحجز")
    extract(app)
    first = turn(client, key, "مش فاكر اليوم")
    assert first["reply"] == ui("day_unavailable", "ar")
    second = turn(client, key, "مش عارف")
    assert ui("day_unavailable", "ar") not in second["reply"]
    assert ui("way_out", "ar") in second["reply"] and len(second["buttons"]) == 4
    assert "day" not in draft(engine)


@pytest.mark.parametrize(
    "text", ["I'm in Cairo", "Ahmed El-Sayed Hassan", "Ahmed Samy 01012345678"]
)
def test_short_latin_words_do_not_count_punctuation_or_phone_as_extra_words(text):
    from nowa.ai.lang import detect

    assert detect(text, "ar") == "ar"


@pytest.mark.parametrize(
    "lang,stop,change",
    [
        ("en", "cancel", "change the day"),
        ("franco", "balash", "aghayyar el yom"),
    ],
)
def test_stop_and_manage_replies_in_latin_languages(chat, lang, stop, change):
    client, app, _ = chat
    key = session(client)
    extract(app, booking_for="self")
    turn(client, key, "Hi" if lang == "en" else "3ayez a7gez kashf")
    stopped = turn(client, key, stop)
    assert stopped["reply"] == ui("booking_stopped", lang)
    assert stopped["buttons"][0]["label"] == ui("visit_chip", lang)
    # Supply new fields explicitly after stopping; old extraction is never authority.
    app.state.ai_chain = [FixtureAdapter(book_output())]
    text = "for me Karim Father 01000000777 Tuesday Maadi"
    if lang == "franco":
        text = "leya Karim Father 01000000777 el talat el ma3adi 7agz"
    confirm = turn(client, key, text)
    tap(client, key, day_payload(confirm))
    managed = turn(client, key, change)
    assert managed["reply"] == ui("manage_booking", lang)
    assert managed["buttons"][0]["label"] == ui("booking_chip", lang)


def test_full_day_kept_for_standby_and_alternatives(chat, engine):
    from datetime import date

    client, app, clinic = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key, "احجز")))
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(max_per_evening=1))
    key = session(client)
    extract(app, booking_for="self", name="منى حسن", phone="01012345678")
    turn(client, key, "عايز أحجز")
    extract(app, day=date(2026, 10, 6))
    first = turn(client, key, "الثلاثاء")
    assert first["reply"] == ui("standby_full", "ar")
    assert draft(engine)["day"] == "2026-10-06"
    extract(app)
    next_turn = turn(client, key, "مش عارف")
    assert ui("day_unavailable", "ar") not in next_turn["reply"]
    assert any(b["action"]["payload"].get("standby") == "2026-10-06" for b in next_turn["buttons"])
    assert any(b["action"]["payload"].get("date") == "2026-10-08" for b in next_turn["buttons"])
    assert not any(b["action"]["payload"].get("date") == "2026-10-06" for b in next_turn["buttons"])


def test_model_greeting_flag_comes_from_session_not_supplied_history(chat):
    client, app, _ = chat
    key = session(client)
    adapter = FixtureAdapter(output(intent="clinic_info"))
    app.state.ai_chain = [adapter]
    turn(client, key, "أهلا", history=[{"role": "assistant", "text": "untrusted past greeting"}])
    turn(client, key, "ok", history=[])
    first, second = [json.loads(p.clinic_block.split("\n")[-1]) for p in adapter.prompts]
    assert first["first_reply"] is True and second["first_reply"] is False
    assert first["patient_language"] == second["patient_language"] == "ar"
    assert "hours" in second["clinic_info"]
