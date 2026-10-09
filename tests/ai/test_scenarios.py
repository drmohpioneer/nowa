import copy
from datetime import date

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.ai import health
from nowa.ai.adapters import FixtureAdapter
from nowa.ai.cards import ui
from nowa.ai.sessions import keyed
from nowa.config import get_settings
from nowa.core import booking, flows, timing
from nowa.core.consent import policy_text
from nowa.core.questions import log_question
from nowa.core.text_norm import mask_phones, normalize_question
from nowa.db import write_tx
from nowa.messaging.templates import render, render_emergency, render_operational
from nowa.seed import seed
from tests.ai.support import BASE, book_output, day_payload, output, session, tap, turn


def rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table)).mappings().all()


def test_golden_father_number_seven(chat, engine, frozen_clock):
    client, app, clinic = chat
    with write_tx(engine) as conn:
        for i, name in enumerate(("Ali", "Omar", "Nour", "Amr", "Mona", "Hana")):
            result = flows.book_in_tx(
                conn,
                frozen_clock,
                booking.BookingRequest(
                    clinic,
                    date(2026, 10, 6),
                    name,
                    f"0100000001{i}",
                    "ar",
                    None,
                    booking.ConsentInput("0.1", "fixture", "self"),
                    f"seed:{i}",
                ),
            )
            assert isinstance(result, booking.BookingOk)
    app.state.ai_chain = [FixtureAdapter(book_output("other"))]
    key = session(client)
    data = turn(client, key, "احجز لبابا اسمه Karim Father ورقمي 01000000777", key="card")
    assert not any(b["id"] == "location" for b in data["buttons"])
    payload = day_payload(data)
    assert payload["draft"]["day"] == "2026-10-06"
    assert len(rows(engine, s.bookings)) == 6
    assert (
        client.post(
            BASE + "/consent", json=dict(session=key, booking_for="other", idempotency_key="gone")
        ).status_code
        == 410
    )
    data = tap(client, key, payload, "book")
    assert "7" in data["reply"] and "/l/" not in str(data)
    tap(client, key, payload, "book")
    assert any(p["name"] == "Karim Father" for p in rows(engine, s.patients))
    booked = rows(engine, s.bookings)
    assert len(booked) == 7
    b = booked[-1]
    with engine.connect() as conn:
        expected = render("1", "ar", timing.patient_blanks(conn, b["id"], "1"))
    outbox = [r for r in rows(engine, s.outbox) if r["booking_id"] == b["id"]]
    assert len(outbox) == 1 and outbox[0]["body"] == expected
    stored = rows(engine, s.consents)[-1]
    version, hashed, text = policy_text("ar")
    assert stored["booking_for"] == "other"
    assert (stored["version"], stored["text_hash"]) == (version, hashed)
    assert text not in data["reply"]
    assert rows(engine, s.chat_sessions)[0]["consent_other_at"] is not None
    assert rows(engine, s.timers)
    assert "01000000777" in app.state.ai_chain[0].prompts[0].conversation
    incoming = [r for r in rows(engine, s.action_record) if r["kind"] == "chat_in"]
    assert "010********" in incoming[0]["text"]
    assert "01000000777" not in str(rows(engine, s.idempotency_keys))
    assert "+201000000777" not in str(rows(engine, s.idempotency_keys))


@pytest.mark.parametrize(
    "who,ask,location", [("self", False, True), ("other", False, False), ("unknown", True, False)]
)
def test_booking_for(chat, who, ask, location):
    client, app, _ = chat
    candidate = book_output(who)
    candidate.fields.area = None
    app.state.ai_chain = [FixtureAdapter(candidate)]
    data = turn(client, session(client), "حجز")
    assert any(b["id"] == "location" for b in data["buttons"]) == location
    if ask:
        assert data["reply"] == ui("booking_for_ask", "ar") and len(data["buttons"]) == 2


@pytest.mark.parametrize("name", ["Karim 01000000005", "Dr. Karim", "www.x.com"])
def test_invalid_name(chat, name):
    client, app, _ = chat
    candidate = book_output()
    candidate.fields.name = name
    app.state.ai_chain = [FixtureAdapter(candidate)]
    data = turn(client, session(client), "احجز")
    assert data["reply"] == ui("name_invalid", "ar") and not data["buttons"]


@pytest.mark.parametrize(
    "typed,shown,lookup_name",
    [
        ("KARIM MAHMOUD", "Karim Mahmoud", "karim mahmoud"),
        ("فاطمة مصطفى", "فاطمة مصطفى", "فاطمه مصطفي"),
    ],
)
def test_display_name_survives_draft_storage_and_lookup(chat, engine, typed, shown, lookup_name):
    client, app, _ = chat
    candidate = book_output()
    candidate.fields.name = typed
    app.state.ai_chain = [FixtureAdapter(candidate)]
    key = session(client)
    payload = day_payload(turn(client, key, "حجز"))
    assert payload["draft"]["name"] == shown
    tap(client, key, payload, "display-name-book")
    patient = rows(engine, s.patients)[0]
    assert patient["name"] == shown
    lookup_session = session(client)
    result = client.post(
        BASE + "/lookup",
        json=dict(session=lookup_session, name=lookup_name, last4="0777", idempotency_key="look"),
    )
    assert result.status_code == 200
    assert "رقم 1" in result.json()["reply"]
    assert rows(engine, s.chat_sessions)[-1]["patient_id"] == patient["id"]


@pytest.mark.parametrize("label", ["emergency", "unclear", "safe"])
def test_stale_draft_and_emergency_paths(chat, engine, label):
    client, app, _ = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    payload = day_payload(turn(client, key))
    app.state.ai_chain = [FixtureAdapter("invalid" if label == "safe" else output(triage=label))]
    after = turn(client, key)
    refused = tap(client, key, payload, "stale")
    assert not rows(engine, s.bookings)
    if label == "emergency":
        assert after["reply"] == refused["reply"] == render_emergency("general", "en")
        assert tap(client, key, payload, "stale") == refused
        lookup = client.post(
            BASE + "/lookup",
            json=dict(session=key, name="Karim", last4="0777", idempotency_key="look"),
        )
        assert lookup.json()["reply"] == refused["reply"]
        assert turn(client, key)["reply"] == refused["reply"]
        assert not any(b["action"]["kind"] == "confirm" for b in after["buttons"])
        # Refresh / new tab is an independent session.
        app.state.ai_chain = [FixtureAdapter(book_output())]
        assert day_payload(turn(client, session(client)))
    else:
        assert refused["reply"] == ui("dead_draft", "en")
        app.state.ai_chain = [FixtureAdapter(book_output())]
        fresh = day_payload(turn(client, key))
        tap(client, key, fresh)
        assert len(rows(engine, s.bookings)) == 1


def test_urgent_saved_and_questions(chat, engine, frozen_clock, monkeypatch):
    client, app, clinic = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output(triage="urgent"))]
    card = turn(client, key, "حجز")
    assert card["reply"].startswith(render_operational("triage_urgent", "ar", {}).text)
    tap(client, key, day_payload(card))
    assert len(rows(engine, s.bookings)) == 1
    assert not rows(engine, s.health_record)  # Triage happened before a phone was verified.
    question = "إيه أسباب الرعشة؟"
    with write_tx(engine) as conn:
        conn.execute(
            s.saved_answers.insert().values(
                clinic_id=clinic,
                question_norm=normalize_question(question),
                answer="Saved by the doctor",
                saved_at=frozen_clock.now(clinic),
            )
        )
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]

    class Spy:
        async def answer(self, **kwargs):
            raise AssertionError("saved/urgent must not call health")

    monkeypatch.setattr(health, "get_health_answerer", lambda: Spy())
    assert turn(client, key, question)["reply"] == "Saved by the doctor"
    app.state.ai_chain = [FixtureAdapter(output(triage="urgent", is_health_question=True))]
    urgent = turn(client, key, "سؤال طبي")
    assert urgent["reply"] == (
        render_operational("triage_urgent", "ar", {}).text
        + "\n"
        + render_operational("health_no_answer", "ar", {}).text
    )
    assert rows(engine, s.health_record)[0]["phone_key"] == keyed("+201000000777")
    monkeypatch.setattr(health, "get_health_answerer", lambda: health.NoAnswerHealth())
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    anonymous = session(client)
    for text in ("إيه أسباب الدوخة؟", "ايه اسباب الدوخه"):
        assert (
            turn(client, anonymous, text)["reply"]
            == render_operational("health_no_answer", "ar", {}).text
        )
    grouped = [
        r
        for r in rows(engine, s.questions)
        if r["text_norm"] == normalize_question("ايه اسباب الدوخه")
    ]
    assert len(grouped) == 1 and grouped[0]["count"] == 2
    assert len(rows(engine, s.health_record)) == 1
    with write_tx(engine) as conn:
        log_question(conn, frozen_clock, clinic, "رقم 12345678 السؤال", "same")
        log_question(conn, frozen_clock, clinic, "رقم 12345678 السؤال", "same")
    last = rows(engine, s.questions)[-1]
    assert last["count"] == 1 and "12345678" not in str(last)


def test_health_answer_records_and_usage(chat, engine, monkeypatch):
    client, app, clinic = chat
    answer = health.Answered(
        "A supported general answer.",
        "https://www.nhs.uk/heart/",
        "NHS",
        "Reason",
        "A supported sentence.",
        "library-model",
        "v1",
        [0.01, 0.02],
    )

    class Answerer:
        async def answer(self, **kwargs):
            # A second writer can commit while the answerer runs: no open write transaction.
            with write_tx(engine) as conn:
                conn.execute(
                    s.clinics.update().where(s.clinics.c.id == clinic).values(cushion_min=10)
                )
            return answer

    monkeypatch.setattr(health, "get_health_answerer", lambda: Answerer())
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    data = turn(client, key)
    assert data["source"]["url"] == answer.source_url
    assert answer.source_url not in data["reply"]
    assert not rows(engine, s.health_record)
    assert any(
        r["kind"] == "health_answer" and r["text"] is None for r in rows(engine, s.action_record)
    )
    app.state.ai_chain = [FixtureAdapter(book_output())]
    tap(client, key, day_payload(turn(client, key)))
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    turn(client, key)
    record = rows(engine, s.health_record)[0]
    assert record["phone_key"] == keyed("+201000000777")
    assert record["supporting_sentence"] == answer.evidence
    assert record["template_version"] == "v1" and record["model"] == "library-model"
    usage = rows(engine, s.usage)[0]
    assert usage["units"] == 7 and usage["est_cost_usd"] == pytest.approx(0.06)


@pytest.mark.parametrize(
    "change", ["name", "phone", "day", "area_id", "booking_for", "exp", "expiry"]
)
def test_tamper_and_expiry(chat, engine, frozen_clock, change):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    payload = copy.deepcopy(day_payload(turn(client, key)))
    if change == "expiry":
        frozen_clock.advance(minutes=31)
    else:
        payload["draft"][change] = dict(
            name="Changed",
            phone="+201000000123",
            day="2026-10-08",
            area_id=2,
            booking_for="other",
            exp=9999999999,
        )[change]
    reply = tap(client, key, payload)
    assert not rows(engine, s.bookings)
    if change == "expiry":
        assert reply["reply"].startswith(ui("draft_expired", "en"))
        tap(client, key, day_payload(reply))
        assert len(rows(engine, s.bookings)) == 1


def test_atomic_flow_failure(chat, engine, monkeypatch):
    client, app, _ = chat
    app.state.ai_chain = [FixtureAdapter(book_output())]
    key = session(client)
    payload = day_payload(turn(client, key))
    original = flows.book_in_tx

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after booking and message")

    monkeypatch.setattr(flows, "book_in_tx", broken)
    with pytest.raises(RuntimeError, match="after booking"):
        tap(client, key, payload)
    assert not rows(engine, s.bookings) and not rows(engine, s.outbox)
    assert not rows(engine, s.consents) and not rows(engine, s.timers)


def test_replay_and_usage(chat, engine, monkeypatch):
    client, app, _ = chat
    monkeypatch.setenv("AI_RATES_JSON", '{"bad":{"in":2,"out":4},"good":{"in":1,"out":3}}')
    get_settings.cache_clear()
    bad, good = FixtureAdapter("bad", "bad"), FixtureAdapter(output(), "good")
    app.state.ai_chain = [bad, good]
    key = session(client)
    first = turn(client, key, key="one")
    assert turn(client, key, key="one") == first
    assert len(bad.prompts) == len(good.prompts) == 1
    usage = rows(engine, s.usage)[0]
    assert usage["units"] == 2 and usage["est_cost_usd"] == pytest.approx(0.00065)
    assert rows(engine, s.judge_counters)[0]["ai_msgs"] == 1
    app.state.ai_chain = [FixtureAdapter(TimeoutError()), good]
    turn(client, key)
    assert rows(engine, s.usage)[0]["units"] == 3
    app.state.ai_chain = [FixtureAdapter(book_output())]
    card = turn(client, key, key="card")
    replay = turn(client, key, key="card")
    assert replay["reply"] == mask_phones(card["reply"]) + "\n" + ui("draft_replay_reask", "en")
    assert not replay["buttons"]


@pytest.mark.parametrize("text,lang", [("حجز", "ar"), ("booking", "en"), ("7agz", "franco")])
def test_fixed_lines_and_full_phone_cap(chat, engine, frozen_clock, text, lang):
    client, app, clinic = chat
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output(triage="urgent"))]
    data = turn(client, key, text)
    assert data["reply"].startswith(render_operational("triage_urgent", lang, {}).text + "\n")
    payload = day_payload(data)
    with write_tx(engine) as conn:
        # Simulate another patient taking the final place after the card was rendered.
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(max_per_evening=1))
        assert isinstance(
            flows.book_in_tx(
                conn,
                frozen_clock,
                booking.BookingRequest(
                    clinic,
                    date(2026, 10, 6),
                    "Another Person",
                    "01000000042",
                    lang,
                    None,
                    booking.ConsentInput("0.1", "fixture", "self"),
                    "filled",
                ),
            ),
            booking.BookingOk,
        )
    refused = tap(client, key, payload)
    next_day = date.fromisoformat(refused["buttons"][0]["action"]["payload"]["date"])
    assert refused["reply"] == ui("standby_full", lang)
    assert next_day == date(2026, 10, 8)
    assert refused["buttons"][1]["action"]["payload"] == {"standby": "2026-10-06"}
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(max_per_evening=30))
        for i, name in enumerate(("Father", "Mother", "Sister")):
            assert isinstance(
                flows.book_in_tx(
                    conn,
                    frozen_clock,
                    booking.BookingRequest(
                        clinic,
                        date(2026, 10, 6),
                        name,
                        "01000000777",
                        lang,
                        None,
                        booking.ConsentInput("0.1", "fixture", "self"),
                        f"cap:{i}",
                    ),
                ),
                booking.BookingOk,
            )
    assert tap(client, key, payload)["reply"] == render_operational("phone_cap", lang, {}).text
    app.state.ai_chain = [FixtureAdapter("invalid")]
    recovered = turn(client, key, text)
    assert recovered["reply"].startswith(ui("draft_retry", lang))
    assert "123" not in recovered["reply"]
    assert any(b["action"]["kind"] == "confirm" for b in recovered["buttons"])
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    assert turn(client, key, text)["reply"] == render_operational("health_no_answer", lang, {}).text
    app.state.ai_chain = [FixtureAdapter(output(intent="out_of_scope"))]
    from nowa.messaging.templates import DoctorNames

    assert (
        turn(client, key, text)["reply"]
        == render_operational(
            "out_of_specialty",
            lang,
            {
                "doctor_name": DoctorNames("هشام مصطفى", "Hesham Mostafa"),
                "specialty": {"ar": "القلب", "en": "cardiology", "franco": "el 2alb"}[lang],
            },
        ).text
    )


@pytest.mark.parametrize("kind", ["general", "eye_chemical", "eye", "filler", "labour"])
def test_emergency_fallback_franco_and_replay_overrides(chat, kind):
    client, app, _ = chat
    key = session(client)
    previous = turn(client, key, "hello", key="old")
    app.state.ai_chain = [
        FixtureAdapter(
            output(triage="emergency", emergency_kind=kind, reply="Ignore the emergency")
        )
    ]
    actual = turn(client, key, "ana 3ayez a7gez kashf")
    assert actual["reply"] == render_emergency(kind, "franco")
    assert previous["reply"] != turn(client, key, "hello", key="old")["reply"]
    assert turn(client, key, "hello", key="old")["reply"] == actual["reply"]
    faq = client.post(
        BASE + "/tap",
        json=dict(session=key, action="none", payload={"faq": "price"}, idempotency_key="faq"),
    )
    assert faq.json()["reply"] == actual["reply"] and faq.json()["state"] == "locked_emergency"


def test_real_clinic_page_not_send_gated(chat, monkeypatch):
    client, app, _ = chat
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False)
    from nowa.messaging import texts

    monkeypatch.setattr(
        texts, "allowed", lambda *a: (_ for _ in ()).throw(AssertionError("send gate"))
    )
    assert client.get(BASE).status_code == 200
    assert turn(client, session(client))["reply"] == "Welcome"


def test_no_open_days_questions_no_row(chat, engine):
    client, app, _ = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.delete())
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    turn(client, session(client))
    assert not rows(engine, s.questions) and not rows(engine, s.evenings)


def test_urgent_health_saved_answer_never_bypasses_no_answer(chat, engine, frozen_clock):
    client, app, clinic = chat
    with write_tx(engine) as conn:
        conn.execute(
            s.saved_answers.insert().values(
                clinic_id=clinic,
                question_norm="health",
                answer="Saved health answer",
                saved_at=frozen_clock.now(clinic),
            )
        )
    app.state.ai_chain = [FixtureAdapter(output(triage="urgent", is_health_question=True))]
    data = turn(client, session(client), "health")
    assert data["reply"] == render_operational("triage_urgent", "en", {}).text + "\n" + (
        render_operational("health_no_answer", "en", {}).text
    )
    assert len(rows(engine, s.questions)) == 1


@pytest.mark.parametrize("clinic_phone", ["01000000000", "+201000000000"])
def test_stored_chat_preserves_business_phones_and_masks_patient(chat, engine, clinic_phone):
    client, app, clinic = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(phone=clinic_phone))
    reply = (
        f"Clinic {clinic_phone} local 01000000000 doctor +201000000001 "
        "01000000001 patient 01000000777"
    )
    app.state.ai_chain = [FixtureAdapter(output(reply=reply))]
    key = session(client)
    turn(client, key, text=reply, key="phones")
    texts = [r["text"] for r in rows(engine, s.action_record) if r["kind"].startswith("chat_")]
    expected = reply.replace("01000000777", "010********")
    assert texts == [expected, expected]


@pytest.mark.parametrize("clinic_phone", ["01000000000", "+201000000000"])
def test_safe_mode_replays_business_phone_byte_identically(chat, engine, clinic_phone):
    from nowa.ai.adapters import FixedReplyAdapter

    client, app, clinic = chat
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == clinic).values(phone=clinic_phone))
    app.state.ai_chain = [FixedReplyAdapter()]
    key = session(client)
    first = turn(client, key, text="سلام", key="safe-phones")
    repeated = turn(client, key, text="سلام", key="safe-phones")
    assert first["reply"].encode() == repeated["reply"].encode()
    assert first == repeated and clinic_phone in first["reply"]
    assert rows(engine, s.judge_counters)[0]["ai_msgs"] == 1


def test_questions_mask_at_eight_digits(engine, frozen_clock):
    seed(engine)
    clinic = next(row["id"] for row in rows(engine, s.clinics) if row["slug"] == "dr-hesham")
    with write_tx(engine) as conn:
        log_question(conn, frozen_clock, clinic, "number 1234567 and 12345678", "eight")
    question = rows(engine, s.questions)[0]
    assert question["text_display"] == "number 1234567 and 123*****"
    assert question["text_norm"] == "number 1234567 and 123"


def test_chain_failure_answers_plainly_with_buttons_and_records_attempts(chat, engine):
    client, app, clinic = chat
    app.state.ai_chain = [
        FixtureAdapter(TimeoutError()),
        FixtureAdapter("not json", model="second"),
    ]
    key = session(client)
    data = turn(client, key, text="hi")
    line = render_operational("chain_fallback", "en", {}).text
    assert data["reply"].startswith(line), data["reply"]
    assert ui("clinic_phone", "en", phone="01000000000") in data["reply"]
    assert "123" not in data["reply"].split(".")[0]
    assert [b["label"] for b in data["buttons"]] == [ui("visit_chip", "en")]
    attempts = [r for r in rows(engine, s.action_record) if r["kind"] == "ai_attempts"]
    assert len(attempts) == 1
    assert "fixture: TimeoutError" in attempts[0]["text"]
    assert "second: ValidationError" in attempts[0]["text"]
    assert attempts[0]["model"] == "fixed"


def test_chain_failure_mid_booking_asks_the_pending_step_again(chat, engine):
    client, app, clinic = chat
    app.state.ai_chain = [
        FixtureAdapter(
            output(
                intent="book",
                fields=dict(day=None, name=None, phone=None, area=None, booking_for="self"),
            )
        )
    ]
    key = session(client)
    first = turn(client, key, text="عايز أحجز")
    assert first["reply"] and rows(engine, s.chat_sessions)[0]["draft"]
    app.state.ai_chain = [FixtureAdapter("not json")]
    data = turn(client, key, text="منى عادل")
    line = ui("draft_retry", "ar")
    assert "123" not in data["reply"]
    assert data["reply"].startswith(line)
    assert data["reply"] != line, "the pending booking step is asked again under the line"
    assert (
        data["reply"].split("\n", 1)[1] == first["reply"].split("\n")[-1]
        or first["reply"] in data["reply"]
    )
    assert rows(engine, s.chat_sessions)[0]["draft"], "the booking draft survives the failure"
