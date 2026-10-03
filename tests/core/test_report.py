"""Hand-computed reports, durable questions, and real channel flows."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.app import create_app
from nowa.core import booking, questions, report, timing
from nowa.core.timers import TimerContext
from nowa.db import write_tx
from nowa.messaging.templates import render_operational
from nowa.telegram import keyboards
from nowa.telegram.router import Router
from nowa.worker import build_registry, run_once
from tests.ai.support import output, session, turn
from tests.core.support import BASE, DAY, move, row, setup
from tests.telegram.conftest import FakeTelegramAPI
from tests.telegram.support import callback, message, other_doctor, tap
from tests.web.support import ORIGIN, rows

GOLDENS = Path(__file__).resolve().parents[1] / "fixtures" / "report"


def question(conn, clock, cid, eid, text="هل الضغط مرض مزمن؟", count=1, status="open"):
    from nowa.core.text_norm import normalize_question

    return conn.execute(
        s.questions.insert()
        .values(
            clinic_id=cid,
            evening_id=eid,
            text_norm=normalize_question(text),
            text_display=text,
            count=count,
            status=status,
            created_at=clock.now(cid),
        )
        .returning(s.questions.c.id)
    ).scalar_one()


def link(conn, cid, clock):
    phone = conn.execute(
        select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == cid)
    ).scalar_one()
    conn.execute(
        s.telegram_links.insert().values(
            phone_e164=phone,
            kind="doctor",
            telegram_chat_id="101",
            linked_at=clock.now(cid),
        )
    )


def context(conn, clock, cid, eid):
    return TimerContext(conn, clock, cid, 0, "evening_report", clock.now(cid), 1, clock.now(cid))


@pytest.fixture
def fixture_evening(engine):
    cid, eid, clock, ids = setup(engine, count=8)
    move(clock, 96)
    names = [
        "Karim Mahmoud",
        "Nour Hassan",
        "Ahmed Ali",
        "Mona Said",
        "Salma Zaki",
        "Omar Amin",
        "Hana Sami",
        "Ali Adel",
    ]
    states = ["seen", "seen", "seen", "didnt_come", "cancelled", "booked", "didnt_come", "seen"]
    with write_tx(engine) as conn:
        for bid, name, state in zip(ids, names, states, strict=True):
            pid = row(engine, s.bookings, bid)["patient_id"]
            conn.execute(s.patients.update().where(s.patients.c.id == pid).values(name=name))
            conn.execute(s.bookings.update().where(s.bookings.c.id == bid).values(state=state))
        walk = conn.execute(
            s.bookings.insert()
            .values(
                clinic_id=cid,
                evening_id=eid,
                queue_number=9,
                order_key=9,
                source="walkin_tap",
                lang="en",
                state="seen",
                created_at=BASE,
            )
            .returning(s.bookings.c.id)
        ).scalar_one()
        for bid, start, length, accepted in [
            (ids[0], 0, 10, True),
            (ids[1], 10, 11, True),
            (ids[2], 21, 50, False),
            (walk, 71, 12, True),
            (ids[7], 83, 13, True),
        ]:
            conn.execute(
                s.visits.insert().values(
                    clinic_id=cid,
                    evening_id=eid,
                    booking_id=bid,
                    started_at=BASE + timedelta(minutes=start),
                    ended_at=BASE + timedelta(minutes=start + length),
                    accepted=accepted,
                )
            )
        for bid, minute in [(ids[0], -15), (ids[1], -10), (ids[2], 21)]:
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(
                    on_my_way_at=BASE + timedelta(minutes=minute),
                    travel_min=10,
                )
            )
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
        # Historical deliveries: Karim fails twice; Nour's backup and Ahmed's newer message succeed.
        for bid, key, status, offset in [
            (ids[0], "failed-one", "failed", 1),
            (ids[0], "failed-two", "failed", 2),
            (ids[1], "backup", "failed", 3),
            (ids[1], "backup:tg", "delivered", 4),
            (ids[2], "old-failed", "failed", 5),
            (ids[2], "new-delivered", "delivered", 6),
            (ids[3], "no-backup", "failed", 7),
        ]:
            conn.execute(
                s.outbox.insert().values(
                    clinic_id=cid,
                    booking_id=bid,
                    recipient_kind="patient_contact",
                    audience="patient",
                    template_id="2",
                    lang="en",
                    channel="telegram" if key.endswith(":tg") else "sms",
                    adapter="telegram" if key.endswith(":tg") else "screen_phone",
                    body="fictional",
                    status=status,
                    idempotency_key=key,
                    created_at=BASE + timedelta(minutes=offset),
                )
            )
        for minute in (-361, -360, 90, 97):
            conn.execute(
                s.health_record.insert().values(
                    clinic_id=cid,
                    at=BASE + timedelta(minutes=minute),
                    phone_key="hash",
                    kind="health_answer",
                    trigger_text="هل 123456 خطر؟ <b>literal</b>",
                    reply_text="معلومة ١٢٣٤٥٦٧",
                    template_version="fixture",
                    model="fixture",
                    commit="local",
                    source_title="NHS",
                    source_url="https://www.nhs.uk/",
                    why="دليل 987654",
                )
            )
        next_eid = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        for i, bid in enumerate(ids[:2]):
            existing = dict(
                conn.execute(select(s.bookings).where(s.bookings.c.id == bid)).mappings().one()
            )
            existing.pop("id")
            existing.update(
                evening_id=next_eid, queue_number=i + 1, order_key=i + 1, state="booked"
            )
            conn.execute(s.bookings.insert().values(**existing))
        qids = [
            question(conn, clock, cid, eid, "سؤال واحد", 1),
            question(conn, clock, cid, eid, "سؤال مكرر", 4, "later"),
        ]
    return cid, eid, clock, ids, qids


def test_hand_computed_report_is_pure_read(fixture_evening, engine):
    cid, eid, clock, _, qids = fixture_evening
    with engine.connect() as conn:
        before = {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables}
        value = report.build_report(conn, clock, cid, eid)
        after = {t.name: conn.execute(select(t)).all() for t in s.metadata.sorted_tables}
    assert before == after
    assert (value.booked, value.came, value.walk_ins, value.no_show_count) == (7, 5, 1, 2)
    assert value.no_show_names == ["Mona", "Hana"]
    assert value.doctor_arrival == BASE
    assert value.clinic_start == BASE
    assert value.avg_visit == 12  # (10+11+12+13)/4 = 11.5, half up
    assert value.avg_wait == 5  # (5+10+0)/3; no estimate recomputation
    assert value.failed_names == ["Karim", "Mona"]
    assert value.health_q_count == 2
    assert value.next_day == DAY + timedelta(days=2)
    assert value.next_day_bookings == 2
    assert [q["id"] for q in value.questions] == qids[::-1]
    health = str(value.health_answers)
    assert "123456" not in health and "١٢٣٤٥٦٧" not in health and "987654" not in health
    assert "<b>literal</b>" in health


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_report_and_card_goldens(fixture_evening, engine, lang):
    cid, eid, clock, _, _ = fixture_evening
    with engine.connect() as conn:
        value = report.build_report(conn, clock, cid, eid)
    assert value.text(lang) == (GOLDENS / f"report-{lang}.txt").read_text().rstrip("\n")
    for count in (1, 4):
        card = render_operational(
            "question_card", lang, dict(n=1, total=3, text="<b>ضغط</b>", count=count)
        )
        assert card.approved
        assert card.text == (GOLDENS / f"card-{lang}-{count}.txt").read_text().rstrip("\n")


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_empty_report_optional_lines_and_no_next_day(engine, lang):
    cid, eid, clock, ids = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled"))
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=BASE,
                closed_by="system_no_taps",
            )
        )
        # Keep this evening's paper hours while closing the following 60 days.
        for offset in range(1, 61):
            conn.execute(
                s.clinic_day_overrides.insert().values(
                    clinic_id=cid,
                    date=DAY + timedelta(days=offset),
                    closed=True,
                )
            )
        value = report.build_report(conn, clock, cid, eid)
    text = value.text(lang)
    assert value.next_day is None and value.next_day_bookings == 0
    assert value.doctor_arrival is value.avg_visit is value.avg_wait is None
    assert "❌" in text and "()" not in text
    assert all(icon not in text for icon in ("⏰", "⏱️", "⌛", "📩", "🩺"))
    assert text.endswith("📅 : 0 حجوزات لحد دلوقتي" if lang == "ar" else "📅 : 0 bookings so far")
    assert "\n\n\n" not in text
    assert text == (GOLDENS / f"report-empty-{lang}.txt").read_text().rstrip("\n")


def test_next_day_capacity_and_override(fixture_evening, engine):
    cid, eid, clock, _, _ = fixture_evening
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(max_per_evening=2))
        value = report.build_report(conn, clock, cid, eid)
        assert value.next_day == DAY + timedelta(days=5)  # Thursday full -> Sunday
        conn.execute(
            s.clinic_day_overrides.insert().values(
                clinic_id=cid,
                date=DAY,
                closed=False,
                start=BASE.time().replace(hour=13),
                end=BASE.time().replace(hour=23),
            )
        )
        assert report.build_report(conn, clock, cid, eid).clinic_start.hour == 13


def test_question_transitions_replay_stale_window_and_latest_save(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        q1 = question(conn, clock, cid, eid)
        q2 = question(conn, clock, cid, eid, "سؤال تاني", status="later")
        assert questions.start_answer(conn, clock, cid, q1, "a").ok
        assert questions.save_for_everyone(conn, clock, cid, q1, "empty").reason == "no_draft"
        assert questions.submit_draft(conn, clock, cid, q1, "Answer <b>verbatim</b>", "draft").ok
        assert questions.start_answer(conn, clock, cid, q2, "later-bot").reason == "already_done"
        assert questions.start_answer(conn, clock, cid, q2, "b", dashboard=True).ok
        assert questions.save_for_everyone(conn, clock, cid, q1, "stale").reason == "stale_save"
        assert questions.submit_draft(conn, clock, cid, q2, "answer two", "draft2").ok
        assert questions.later(conn, clock, cid, q2, "later").ok
        assert questions.start_answer(conn, clock, cid, q1, "edit").ok
        assert questions.submit_draft(conn, clock, cid, q1, "final answer", "final").ok
        assert questions.save_for_everyone(conn, clock, cid, q1, "save").ok
        count = len(conn.execute(select(s.action_record)).all())
        assert questions.save_for_everyone(conn, clock, cid, q1, "save").ok
        assert (
            questions.save_for_everyone(conn, clock, cid, q1, "save-again").reason == "stale_save"
        )
        assert len(conn.execute(select(s.action_record)).all()) == count
        assert conn.execute(select(s.saved_answers.c.answer)).scalar_one() == "final answer"
        # A fresh question in a later evening with the same norm overwrites the saved answer.
        next_eid = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        q3 = question(conn, clock, cid, next_eid)
        assert questions.start_answer(conn, clock, cid, q3, "a3").ok
        assert questions.submit_draft(conn, clock, cid, q3, "newest", "d3").ok
        assert questions.save_for_everyone(conn, clock, cid, q3, "s3").ok
        assert conn.execute(select(s.saved_answers.c.answer)).scalar_one() == "newest"
        assert questions.dismiss(conn, clock, cid, q1, "dismiss-done").reason == "already_done"
    assert row(engine, s.questions, q2)["status"] == "later"


@pytest.mark.parametrize("value", ["", "x" * 1001])
def test_draft_size_refused_without_writes(engine, value):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        qid = question(conn, clock, cid, eid)
        questions.start_answer(conn, clock, cid, qid, "start")
        assert questions.submit_draft(conn, clock, cid, qid, value, "bad").reason == "text_only"
        assert conn.execute(select(s.questions.c.draft_answer)).scalar_one() is None


def test_close_worker_restart_cards_and_saved_chat(engine, monkeypatch):
    cid, eid, clock, ids = setup(engine, count=3)
    move(clock, 0)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        conn.execute(s.doctors.update().where(s.doctors.c.clinic_id == cid).values(lang="en"))
        # log_question is the chat's real grouping implementation.
        for index, text in enumerate(
            ["هل الضغط مرض مزمن؟", "هل الضغط مرض مزمن", "هَل الضَغط مرض مزمن؟", "هل الضغط مرض مزمن؟"]
        ):
            questions.log_question(conn, clock, cid, text, f"log:{index}")
        q1 = conn.execute(select(s.questions.c.id)).scalar_one()
        q2 = question(conn, clock, cid, eid, "<b>السؤال 123456</b>", count=2)
        q3 = question(conn, clock, cid, eid, "السؤال الثالث")
    # Exercise a real undo: its temporary visit must disappear from the report.
    assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "in1").ok
    clock.advance(minutes=10)
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "in2").ok
    assert timing.undo_last(engine, clock, cid, eid, "undo").ok
    assert timing.who_comes_in(engine, clock, cid, eid, ids[1], False, "in2-again").ok
    clock.advance(minutes=11)
    preview = timing.close_preview(engine, clock, cid, eid)
    assert timing.close_evening(
        engine, clock, cid, eid, "doctor", "close1", preview.untold_count
    ).ok
    assert timing.close_evening(
        engine, clock, cid, eid, "doctor", "close2", preview.untold_count
    ).ok
    # Only run the report kind here; sends are kept in the outbox for inspection.
    registry = {"evening_report": build_registry()["evening_report"]}
    assert run_once(engine, clock, registry).done == 1
    assert run_once(engine, clock, registry).claimed == 0
    assert [r["position"] for r in rows(engine, s.report_questions)] == [1, 2, 3]
    assert len([r for r in rows(engine, s.outbox) if r["template_id"] == "6"]) == 1

    def cards():
        return [r for r in rows(engine, s.outbox) if r["template_id"] == "op:question_card"]

    assert len(cards()) == 1 and "(asked by 4 patients)" in cards()[0]["body"]
    fake = FakeTelegramAPI()
    router = Router(engine, clock, fake)
    tap(router, 100, "qans", arg=str(q1))
    router.handle_update(message(101, text="Doctor answer, kept <b>literally</b>"))
    assert fake.calls[-1][1]["text"] == "Doctor answer, kept <b>literally</b>"
    assert [
        b["callback_data"] for b in fake.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
    ] == [f"qsave:-:-:{q1}", f"qedit:-:-:{q1}"]
    assert row(engine, s.questions, q1)["answering_at"] is not None
    tap(router, 102, "qsave", arg=str(q1))
    # A restarted process reconstructs all position and answer state from the DB.
    router = Router(engine, clock, fake)
    assert len(cards()) == 2
    assert "123456" not in cards()[1]["body"] and "<b>" in cards()[1]["body"]
    tap(router, 103, "qsave", arg=str(q1))
    assert len(cards()) == 2
    tap(router, 104, "qlater", arg=str(q2))
    assert len(cards()) == 3 and row(engine, s.questions, q2)["status"] == "later"
    tap(router, 105, "qdismiss", arg=str(q3))
    assert all(r["resolved_at"] is not None for r in rows(engine, s.report_questions))
    with engine.connect() as conn:
        value = report.build_report(conn, clock, cid, eid)
        assert value.came == 2 and value.avg_visit == 11  # (10+11)/2, half up
    # Force a handler replay after resolution: immutable snapshot, no re-open or send.
    with write_tx(engine) as conn:
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    assert len(cards()) == 3 and row(engine, s.questions, q2)["status"] == "later"
    from unittest.mock import Mock

    health_factory = Mock(side_effect=AssertionError("saved answer must bypass health calls"))
    monkeypatch.setattr("nowa.ai.health.get_health_answerer", health_factory)
    app = create_app(engine, clock=clock)
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    with TestClient(app) as client:
        data = turn(client, session(client), "هل الضَغط مرض مزمن")
        assert data["reply"] == "Doctor answer, kept <b>literally</b>"
    health_factory.assert_not_called()
    # A new closed evening's snapshot resets the deferred question and sends it.
    with write_tx(engine) as conn:
        next_eid = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == next_eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="system_no_taps",
            )
        )
        report.evening_report(context(conn, clock, cid, next_eid), {"evening_id": next_eid})
    assert row(engine, s.questions, q2)["status"] == "open"
    assert len(cards()) == 4


def test_unlinked_snapshot_stable_empty_and_deferred(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
        qid = question(conn, clock, cid, eid, status="later")
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    assert rows(engine, s.report_questions) == []
    assert not any(r["template_id"] in {"6", "op:question_card"} for r in rows(engine, s.outbox))
    assert row(engine, s.questions, qid)["status"] == "later"
    with write_tx(engine) as conn:
        next_eid = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == next_eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
        report.evening_report(context(conn, clock, cid, next_eid), {"evening_id": next_eid})
    snapshot = rows(engine, s.report_questions)
    assert len(snapshot) == 1 and snapshot[0]["sent_at"] is None
    assert row(engine, s.questions, qid)["status"] == "open"


def test_telegram_newest_window_expiry_media_and_replay(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        q1 = question(conn, clock, cid, eid)
        q2 = question(conn, clock, cid, eid, "second")
    fake = FakeTelegramAPI()
    router = Router(engine, clock, fake)
    tap(router, 1, "qans", arg=str(q1))
    tap(router, 2, "qans", arg=str(q2))
    router.handle_update(message(3, text="second only"))
    assert row(engine, s.questions, q1)["draft_answer"] is None
    assert row(engine, s.questions, q2)["draft_answer"] == "second only"
    router.handle_update(message(4, text="this gets the menu"))
    assert row(engine, s.questions, q2)["draft_answer"] == "second only"
    tap(router, 5, "qedit", arg=str(q1))
    router.handle_update(message(3, text="replay must not affect q1"))
    assert row(engine, s.questions, q1)["draft_answer"] is None
    media = message(6)
    media["message"]["voice"] = {"file_id": "fictional"}
    router.handle_update(media)
    assert "1000" in fake.calls[-1][1]["text"] or "١٠٠٠" in fake.calls[-1][1]["text"]
    assert row(engine, s.questions, q1)["draft_answer"] is None
    clock.advance(minutes=31)
    router.handle_update(message(7, text="expired"))
    assert row(engine, s.questions, q1)["draft_answer"] is None
    assert "expired" not in str(fake.calls)
    assert all("parse_mode" not in payload for _, payload in fake.calls)


def test_dashboard_authorization_draft_and_telegram_progression(engine, fixture_evening):
    cid, eid, clock, _, qids = fixture_evening
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    other, _, other_eid = other_doctor(engine, clock, cid)
    with write_tx(engine) as conn:
        foreign_q = question(conn, clock, other, other_eid)
    app = create_app(engine, clock=clock)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get(f"/d/report/{eid}", follow_redirects=False).status_code == 303
        assert client.get(f"/d/api/report/{eid}").status_code == 401
        assert (
            client.post(
                "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
            ).status_code
            == 200
        )
        headers = ORIGIN | {"X-CSRF-Token": client.cookies.get("nowa_csrf")}
        assert client.get(f"/d/api/report/{other_eid}").status_code == 404
        assert client.get(f"/d/report/{other_eid}").status_code == 404
        assert client.get(f"/d/api/report/{eid}").json()["health_q_count"] == 2
        assert client.get(f"/d/report/{eid}").status_code == 200
        assert client.get("/d/api/tonight").json()["latest_report_id"] == eid
        assert '<div id="questions">' in client.get("/d").text
        qid = qids[1]
        path = f"/d/api/questions/{qid}"
        assert (
            client.post(
                path + "/draft", json={"idempotency_key": "bad", "text": "text"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/d/api/questions/{foreign_q}/dismiss",
                json={"idempotency_key": "foreign"},
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            client.post(
                path + "/draft",
                json={"idempotency_key": "long", "text": "x" * 1001},
                headers=headers,
            ).status_code
            == 422
        )
        body = {"idempotency_key": "draft", "text": "dashboard <b>verbatim</b>"}
        assert client.post(path + "/draft", json=body, headers=headers).json()["ok"]
        assert client.post(path + "/draft", json=body, headers=headers).json()["ok"]
        assert client.post(
            path + "/save", json={"idempotency_key": "save"}, headers=headers
        ).json()["ok"]
        # Telegram's stale card cannot mutate the answered question or duplicate card 2.
        fake = FakeTelegramAPI()
        router = Router(engine, clock, fake)
        tap(router, 55, "qans", arg=str(qid))
        assert fake.calls[0][1]["text"] in {"السؤال ده اتخلص", "This question is already done"}
        cards = [r for r in rows(engine, s.outbox) if r["template_id"] == "op:question_card"]
        assert len(cards) == 2
        pending = client.get("/d/api/questions").json()
        assert [q["id"] for q in pending] == [qids[0]]
        assert client.post(
            f"/d/api/questions/{qids[0]}/later", json={"idempotency_key": "later"}, headers=headers
        ).json()["ok"]
        assert client.get("/d/api/questions").json()[0]["status"] == "later"
        # DECIDED 2(b): dashboard draft reopens a deferred question immediately.
        assert client.post(
            f"/d/api/questions/{qids[0]}/draft",
            json={"idempotency_key": "reopen", "text": "answer"},
            headers=headers,
        ).json()["ok"]
        assert row(engine, s.questions, qids[0])["status"] == "open"
        assert client.post(
            f"/d/api/questions/{qids[0]}/dismiss",
            json={"idempotency_key": "dismiss"},
            headers=headers,
        ).json()["ok"]
    assert row(engine, s.questions, foreign_q)["status"] == "open"


@pytest.mark.parametrize(
    "data",
    [
        "qans:1:-:1",
        "qans:-:-:0",
        "qsave:-:-:999999999999999999999999999",
        "qans:-:-:" + "1" * 70,
        "forged",
    ],
)
def test_forged_question_callbacks(engine, data):
    cid, _, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
    fake = FakeTelegramAPI()
    Router(engine, clock, fake).handle_update(callback(1, data))
    assert fake.calls[0][1]["text"] in {
        "الطلب ده مش متاح. افتح القائمة تاني",
        "This action is unavailable. Open the menu again",
    }
    assert rows(engine, s.questions) == []


def test_other_clinic_question_and_patient_role_refused(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    other, _, other_eid = other_doctor(engine, clock, cid)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        own_q = question(conn, clock, cid, eid)
        foreign_q = question(conn, clock, other, other_eid)
    fake = FakeTelegramAPI()
    router = Router(engine, clock, fake)
    tap(router, 1, "qans", arg=str(foreign_q))
    tap(router, 2, "qans", arg=str(own_q), chat=201)
    assert row(engine, s.questions, foreign_q)["answering_at"] is None
    assert row(engine, s.questions, own_q)["answering_at"] is None


def test_report_and_card_buttons_and_skip_resolved(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        q1 = question(conn, clock, cid, eid, "first", count=3)
        q2 = question(conn, clock, cid, eid, "second", count=2)
        q3 = question(conn, clock, cid, eid, "third")
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
        # Simulate the chat's or another channel's resolved state before progression.
        conn.execute(s.questions.update().where(s.questions.c.id == q2).values(status="answered"))
        questions.dismiss(conn, clock, cid, q1, "dismiss")
    cards = [r for r in rows(engine, s.outbox) if r["template_id"] == "op:question_card"]
    assert [r["idempotency_key"] for r in cards] == [f"report:{eid}:q:{q1}", f"report:{eid}:q:{q3}"]
    assert all(r["resolved_at"] is not None for r in rows(engine, s.report_questions)[:2])
    for lang, label in [("ar", "اعرض"), ("en", "View")]:
        markup = keyboards.markup_for(
            {"template_id": "6", "idempotency_key": f"report:{eid}", "lang": lang}
        )
        assert markup["inline_keyboard"][0][0] == {
            "text": label,
            "url": f"http://127.0.0.1:8000/d/report/{eid}",
        }
        card = keyboards.markup_for(dict(cards[0], lang=lang))
        assert [b["callback_data"] for b in card["inline_keyboard"][0]] == [
            f"qans:-:-:{q1}",
            f"qlater:-:-:{q1}",
            f"qdismiss:-:-:{q1}",
        ]


@pytest.mark.parametrize("digits", ["123456", "١٢٣٤٥٦", "۱۲۳۴۵۶", "１２３４５６"])
def test_display_masking_six_unicode_digits(digits):
    assert report.display_text("literal <b> " + digits) == "literal <b> " + digits[:3] + "***"


def test_report_send_pipeline_is_offline_idempotent_and_has_markup(engine, monkeypatch):
    from nowa.messaging.adapters import ADAPTERS
    from tests.helpers.worker import drain

    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        question(conn, clock, cid, eid)
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    fake = FakeTelegramAPI()
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    registry = build_registry()
    drain(engine, clock, registry)
    sent = [r for r in rows(engine, s.outbox) if r["template_id"] in {"6", "op:question_card"}]
    assert len(sent) == 2 and all(r["status"] == "delivered" for r in sent)
    assert [method for method, _ in fake.calls] == ["sendMessage", "sendMessage"]
    assert all(
        "reply_markup" in payload and "parse_mode" not in payload for _, payload in fake.calls
    )
    drain(engine, clock, build_registry())
    assert len(fake.calls) == 2


def test_report_transaction_rolls_back_snapshot_and_reset(engine, monkeypatch):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        qid = question(conn, clock, cid, eid, status="later")
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(
                state="closed",
                closed_at=clock.now(cid),
                closed_by="doctor",
            )
        )
    original = report.enqueue_message

    def fail(*args, **kwargs):
        raise RuntimeError("fixture enqueue failure")

    monkeypatch.setattr(report, "enqueue_message", fail)
    with pytest.raises(RuntimeError, match="fixture enqueue failure"):
        with write_tx(engine) as conn:
            report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    assert rows(engine, s.report_questions) == []
    assert row(engine, s.questions, qid)["status"] == "later"
    assert not [r for r in rows(engine, s.idempotency_keys) if r["command"] == "report_snapshot"]
    monkeypatch.setattr(report, "enqueue_message", original)
    with write_tx(engine) as conn:
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    assert len(rows(engine, s.report_questions)) == 1
    assert row(engine, s.questions, qid)["status"] == "open"


def test_display_preserves_markup_masks_known_full_names_and_does_not_write(
    engine, fixture_evening
):
    cid, eid, clock, _, qids = fixture_evening
    raw = "<b>Mona Said</b> called Karim Mahmoud at 1234567"
    with write_tx(engine) as conn:
        conn.execute(
            s.questions.update().where(s.questions.c.id == qids[1]).values(text_display=raw)
        )
        conn.execute(
            s.health_record.update()
            .where(s.health_record.c.clinic_id == cid)
            .values(
                trigger_text=raw,
                reply_text=raw,
                why=raw,
            )
        )
        link(conn, cid, clock)
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    with engine.connect() as conn:
        value = report.build_report(conn, clock, cid, eid)
        assert (
            conn.execute(
                select(s.questions.c.text_display).where(s.questions.c.id == qids[1])
            ).scalar_one()
            == raw
        )
        assert all(
            text == raw for text in conn.execute(select(s.health_record.c.reply_text)).scalars()
        )
    visible = value.text("en") + str(value.health_answers) + str(value.questions)
    cards = [r["body"] for r in rows(engine, s.outbox) if r["template_id"] == "op:question_card"]
    visible += "".join(cards)
    assert all(hidden not in visible for hidden in ("Said", "Mahmoud", "1234567"))
    assert "<b>Mona</b> called Karim at 123****" in visible


@pytest.mark.parametrize("remove", ["hours", "override"])
def test_snapshot_paper_window_survives_hours_change(engine, fixture_evening, remove):
    cid, eid, clock, _, _ = fixture_evening
    with write_tx(engine) as conn:
        if remove == "override":
            conn.execute(s.clinic_day_overrides.insert().values(
                clinic_id=cid, date=DAY, closed=False,
                start=BASE.time().replace(hour=23), end=BASE.time().replace(hour=1),
            ))
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
        expected = report.build_report(conn, clock, cid, eid)
        conn.execute(s.clinic_hours.delete().where(
            s.clinic_hours.c.clinic_id == cid, s.clinic_hours.c.weekday == DAY.weekday(),
        ))
        conn.execute(s.clinic_day_overrides.delete().where(
            s.clinic_day_overrides.c.clinic_id == cid, s.clinic_day_overrides.c.date == DAY,
        ))
        # Replay must use the durable window and must not change it.
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
        actual = report.build_report(conn, clock, cid, eid)
        assert actual == expected
        start, end = report._paper_window(
            conn, cid,
            conn.execute(select(s.evenings).where(s.evenings.c.id == eid)).mappings().one(),
        )
        assert end > start
        if remove == "override":
            assert end.date() == DAY + timedelta(days=1)
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        assert client.post("/d/login", json={"mobile": "01000000001", "password": "demo1234"},
                           headers=ORIGIN).status_code == 200
        response = client.get(f"/d/api/report/{eid}")
        assert response.status_code == 200
        data = response.json()
        assert (data["booked"], data["came"], data["avg_visit"], data["avg_wait"]) == (7, 5, 12, 5)
        assert data["health_q_count"] == expected.health_q_count
        assert data["text"] == expected.text("ar")


def test_missing_unstored_paper_window_still_raises(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.delete().where(s.clinic_hours.c.clinic_id == cid))
        with pytest.raises(ValueError, match="date has no open paper hours"):
            report.build_report(conn, clock, cid, eid)


def test_new_snapshot_supersedes_old_queue_and_only_latest_advances(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        q1 = question(conn, clock, cid, eid, "first", count=2)
        q2 = question(conn, clock, cid, eid, "second")
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(
            state="closed", closed_at=clock.now(cid), closed_by="doctor",
        ))
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
        second = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=2))
        conn.execute(s.evenings.update().where(s.evenings.c.id == second).values(
            state="closed", closed_at=clock.now(cid), closed_by="doctor",
        ))
        report.evening_report(context(conn, clock, cid, second), {"evening_id": second})
        old = conn.execute(select(s.report_questions).where(
            s.report_questions.c.evening_id == eid,
        )).mappings().all()
        assert all(
            r["resolved_at"] is not None and r["resolved_reason"] == "superseded" for r in old
        )
        assert conn.execute(select(s.questions.c.status)).scalars().all() == ["open", "open"]
        report.send_next(conn, clock, cid, eid)
        report.evening_report(context(conn, clock, cid, eid), {"evening_id": eid})
    def cards():
        return [r["idempotency_key"] for r in rows(engine, s.outbox)
                if r["template_id"] == "op:question_card"]
    assert cards() == [f"report:{eid}:q:{q1}", f"report:{second}:q:{q1}"]
    router = Router(engine, clock, FakeTelegramAPI())
    tap(router, 800, "qlater", arg=str(q1))
    assert cards() == [f"report:{eid}:q:{q1}", f"report:{second}:q:{q1}", f"report:{second}:q:{q2}"]
    assert row(engine, s.questions, q1)["status"] == "later"
    tap(router, 801, "qdismiss", arg=str(q2))
    # Even an empty next snapshot closes the old progression queue.
    with write_tx(engine) as conn:
        conn.execute(s.questions.update().where(s.questions.c.id == q1).values(status="dismissed"))
        third = booking.get_or_create_evening(conn, cid, DAY + timedelta(days=5))
        conn.execute(s.evenings.update().where(s.evenings.c.id == third).values(
            state="closed", closed_at=clock.now(cid), closed_by="doctor",
        ))
        report.evening_report(context(conn, clock, cid, third), {"evening_id": third})
        report.send_next(conn, clock, cid, second)
    assert len(cards()) == 3


@pytest.mark.parametrize("raw,masked", [
    ("010 1234 5678", "010********"),
    ("010-1234-5678", "010********"),
    ("+20 101 234 5678", "+201*********"),
    ("(010) 1234-5678", "(010********"),
    ("١٢٣ ٤٥٦", "١٢٣***"),
    ("۱۲۳-۴۵۶", "۱۲۳***"),
    ("１２３(４５６)", "１２３***)"),
])
def test_display_masks_separated_digits(raw, masked):
    assert report.display_text("literal <b>" + raw + "</b>") == "literal <b>" + masked + "</b>"
    assert report.display_text("12345 / 12345") == "12345 / 12345"


def test_qedit_retains_draft_replaces_with_next_text_and_can_save_without_edit(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        link(conn, cid, clock)
        q1 = question(conn, clock, cid, eid)
        q2 = question(conn, clock, cid, eid, "second")
    fake = FakeTelegramAPI()
    router = Router(engine, clock, fake)
    tap(router, 900, "qans", arg=str(q1))
    router.handle_update(message(901, text="original <b>verbatim</b>"))
    tap(router, 902, "qans", arg=str(q2))
    assert row(engine, s.questions, q1)["draft_answer"] == "original <b>verbatim</b>"
    assert row(engine, s.questions, q1)["answering_at"] is None
    tap(router, 903, "qedit", arg=str(q1))
    assert row(engine, s.questions, q1)["draft_answer"] == "original <b>verbatim</b>"
    # Restart and the same frozen instant do not lose or consume the new window.
    router = Router(engine, clock, fake)
    router.handle_update(message(901, text="replayed"))
    assert row(engine, s.questions, q1)["draft_answer"] == "original <b>verbatim</b>"
    router.handle_update(message(904, text="replacement"))
    assert row(engine, s.questions, q1)["draft_answer"] == "replacement"
    router.handle_update(message(905, text="unrelated menu text"))
    assert row(engine, s.questions, q1)["draft_answer"] == "replacement"
    tap(router, 906, "qedit", arg=str(q1))
    assert row(engine, s.questions, q1)["draft_answer"] == "replacement"
    tap(router, 907, "qsave", arg=str(q1))
    assert rows(engine, s.saved_answers)[0]["answer"] == "replacement"


def test_report_health_time_cairo_display(engine, fixture_evening):
    cid, eid, clock, _, _ = fixture_evening
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        assert client.post("/d/login", json={"mobile": "01000000001", "password": "demo1234"},
                           headers=ORIGIN).status_code == 200
        health = client.get(f"/d/api/report/{eid}").json()["health_answers"]
        # SQLite returns UTC: 03:00/10:30 UTC are 06:00/13:30 in Cairo on this date.
        assert [a["at_display"] for a in health] == ["6:00", "1:30"]
        assert [a["at"] for a in health] == ["2026-10-06T03:00:00Z", "2026-10-06T10:30:00Z"]
    script = (Path(__file__).resolve().parents[2] / "nowa/web/static/dashboard.js").read_text()
    assert '["question", "answer", "why", "at_display", "model"]' in script
