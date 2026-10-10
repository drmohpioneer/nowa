from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, FrozenClock
from nowa.config import get_settings
from nowa.core.timers import TimerContext
from nowa.db import write_tx
from nowa.messaging import texts
from nowa.messaging.adapters import ADAPTERS, SendResult, TelegramAdapter
from nowa.messaging.outbox import enqueue_message, recipient, screen_messages
from nowa.messaging.pipeline import delivery_timeout, on_delivery_report, on_send_result, send_retry
from nowa.messaging.templates import (
    EMERGENCY,
    OPERATIONAL,
    DoctorNames,
    format_day,
    format_time,
    render,
    render_emergency,
    render_operational,
)
from nowa.seed import seed

DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 20, 20, tzinfo=CAIRO)
NAMES = DoctorNames("هشام مصطفى", "Hesham Mostafa")
BLANKS = dict(
    patient_name="كريم محمود",
    doctor_name=NAMES,
    day=DAY,
    queue_number=7,
    expected_time=NOW,
    link="/l/fictional",
    clinic_phone="01000000000",
)


@pytest.fixture
def prepared(engine):
    seed(engine)
    clock = FrozenClock(NOW)
    record.configure(clock)
    with write_tx(engine) as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        eid = conn.execute(
            s.evenings.insert().values(clinic_id=cid, date=DAY).returning(s.evenings.c.id)
        ).scalar_one()
        pid = conn.execute(
            s.patients.insert().values(clinic_id=cid, name="كريم محمود").returning(s.patients.c.id)
        ).scalar_one()
        contact = conn.execute(
            s.contacts.insert()
            .values(clinic_id=cid, phone_e164="+201000000007")
            .returning(s.contacts.c.id)
        ).scalar_one()
        bid = conn.execute(
            s.bookings.insert()
            .values(
                clinic_id=cid,
                evening_id=eid,
                patient_id=pid,
                contact_id=contact,
                queue_number=7,
                order_key=7,
                source="chat",
                lang="ar",
                created_at=clock.now(cid),
            )
            .returning(s.bookings.c.id)
        ).scalar_one()
    return SimpleNamespace(engine=engine, clock=clock, cid=cid, bid=bid)


def enqueue(p, key="golden", **changes):
    params = dict(
        clinic_id=p.cid,
        template_id="1",
        lang="ar",
        audience="patient",
        booking_id=p.bid,
        blanks=BLANKS,
        idempotency_key=key,
    )
    params.update(changes)
    with write_tx(p.engine) as conn:
        return enqueue_message(conn, p.clock, **params)


def row(p, oid):
    with p.engine.connect() as conn:
        return conn.execute(select(s.outbox).where(s.outbox.c.id == oid)).mappings().one()


def handle(p, handler, oid, attempt=1, dispatch=True):
    with write_tx(p.engine) as conn:
        ctx = TimerContext(
            conn, p.clock, p.cid, 1, handler.__name__, p.clock.now(p.cid), 1, p.clock.now(p.cid)
        )
        handler(ctx, {"outbox_id": oid, "attempt": attempt})
    if dispatch:
        for call in ctx.after_commit:
            call()
    return ctx


def link(p, kind="patient", phone="+201000000007"):
    with write_tx(p.engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=phone,
                kind=kind,
                telegram_chat_id="fictional-chat",
                linked_at=p.clock.now(p.cid),
            )
        )


class FakeAdapter:
    def __init__(self, outcome="accepted", reports=False, retry_after=None):
        self.delivery_reports = reports
        self.outcome = outcome
        self.retry_after = retry_after
        self.rows = []

    def send(self, row):
        self.rows.append(dict(row))
        return SendResult(
            self.outcome,
            "fixture:1" if self.outcome == "accepted" else None,
            "fixture_refused",
            self.retry_after,
        )


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
@pytest.mark.parametrize(
    "offset,ar,en",
    [
        (0, "الاثنين", "Mon"),
        (1, "الثلاثاء", "Tue"),
        (2, "الأربعاء", "Wed"),
        (3, "الخميس", "Thu"),
        (4, "الجمعة", "Fri"),
        (5, "السبت", "Sat"),
        (6, "الأحد", "Sun"),
    ],
)
def test_day(offset, ar, en, lang):
    day = date(2026, 10, 5) + timedelta(days=offset)
    assert format_day(day, lang) == f"{ar if lang == 'ar' else en} {day.day}/10"


@pytest.mark.parametrize(
    "hour,minute,second,expected",
    [
        (20, 20, 0, "8:20"),
        (21, 13, 0, "9:15"),
        (0, 0, 0, "12:00"),
        (23, 59, 0, "12:00"),
        (12, 2, 29, "12:00"),
        (12, 2, 30, "12:05"),
    ],
)
def test_time(hour, minute, second, expected):
    assert format_time(NOW.replace(hour=hour, minute=minute, second=second), "ar") == expected + (
        " ص" if hour in (0, 23) else " م"
    )
    assert format_time(
        NOW.replace(hour=hour, minute=minute, second=second).astimezone(__import__("datetime").UTC),
        "en",
    ) == expected + (" AM" if hour in (0, 23) else " PM")


def test_render_boundaries():
    text = render("1", "ar", BLANKS)
    assert text == (
        "كريم محمود: حجزك مع د. هشام مصطفى الثلاثاء 6/10، رقمك 7، معادك حوالي 8:20 م "
        "وممكن يتأخر. هنقولك على تليجرام امتى تتحرك. التفاصيل والعنوان: "
        "http://127.0.0.1:8000/l/fictional تليفون العيادة 01000000000"
    )
    for bad in [
        dict(BLANKS, link="https://wrong.test"),
        dict(BLANKS, unknown="x"),
        dict(BLANKS, patient_name=""),
        {k: v for k, v in BLANKS.items() if k != "link"},
    ]:
        with pytest.raises(ValueError):
            render("1", "ar", bad)
    english = dict(BLANKS, doctor_name=DoctorNames("هشام", None))
    with pytest.raises(ValueError):
        render("1", "en", english)
    with pytest.raises(ValueError):
        format_time(datetime(2026, 10, 6, 20, 20), "ar")
    assert render_operational(
        "secretary_link", "ar", {"doctor_name": NAMES, "secretary_link": "/secretary/x"}
    ).text.endswith("http://127.0.0.1:8000/secretary/x")


@pytest.mark.parametrize("kind", ["general", "eye_chemical", "eye", "filler", "labour", None, "x"])
@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_emergency(kind, lang):
    resolved = kind if kind in {"general", "eye_chemical", "eye", "filler", "labour"} else "general"
    expected_lang = "en" if lang == "franco" and resolved != "general" else lang
    assert render_emergency(kind, lang) == EMERGENCY[resolved, expected_lang]


@pytest.mark.parametrize(
    "sandbox,demo", [(False, False), (False, True), (True, False), (True, True)]
)
def test_allowed(sandbox, demo):
    get_settings().demo_mode = demo
    assert texts.allowed({"is_sandbox": sandbox}) == (sandbox or demo)


def test_golden(prepared):
    p = prepared
    oid = enqueue(p)
    assert enqueue(p, template_id="7", blanks={}) == oid
    handle(p, send_retry, oid)
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == "delivered"
    with p.engine.connect() as conn:
        messages = screen_messages(conn, p.cid, 0)
        assert [m.outbox_id for m in messages] == [oid]
        assert messages[0].body == render("1", "ar", BLANKS)
        assert screen_messages(conn, p.cid + 1, 0) == []
        assert screen_messages(conn, p.cid, oid) == []
        assert not conn.execute(select(s.usage)).all()
        notes = conn.execute(select(s.action_record.c.text)).scalars().all()
        assert notes == [None, "telegram", "accepted", None]


@pytest.mark.parametrize(
    "sandbox,demo,linked,expected",
    [
        (False, False, True, ("telegram", "telegram", "doctor")),
        (True, False, False, ("telegram", "screen_phone", "screen")),
        (False, True, False, ("telegram", "screen_phone", "screen")),
        (False, False, False, ("telegram", "telegram", "doctor")),
    ],
)
def test_doctor_channels(prepared, sandbox, demo, linked, expected):
    p = prepared
    get_settings().demo_mode = demo
    with write_tx(p.engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == p.cid).values(is_sandbox=sandbox))
    if linked:
        link(p, "doctor", "+201000000001")
    oid = enqueue(
        p,
        audience="doctor",
        template_id="5",
        blanks=dict(doctor_name=NAMES, clinic_start=NOW, booked_count=1),
    )
    r = row(p, oid)
    assert (r["channel"], r["adapter"], r["recipient_kind"]) == expected
    with p.engine.connect() as conn:
        assert recipient(conn, r)[0] == "+201000000001"


def test_explicit_sms_refused_and_secretary_requires_link(prepared):
    with pytest.raises(ValueError):
        enqueue(prepared, channel="sms")
    oid = enqueue(prepared)
    with pytest.raises(ValueError):
        enqueue(prepared, channel="sms")  # Invalid channel is rejected even on replay.
    assert row(prepared, oid)["channel"] == "telegram"
    with pytest.raises(ValueError):
        enqueue(prepared, key="secretary", audience="secretary")


def test_invalid_enqueue_atomic(prepared):
    p = prepared
    for changes in [
        dict(template_id="7"),
        dict(booking_id=None),
        dict(booking_id=999),
        dict(audience="unknown"),
        dict(blanks={}),
        dict(channel="other"),
    ]:
        with pytest.raises((ValueError, KeyError)):
            enqueue(p, **changes)
    with p.engine.connect() as conn:
        assert not conn.execute(select(s.outbox)).all()
        assert not conn.execute(select(s.timers)).all()


def signup(p, **changes):
    with write_tx(p.engine) as conn:
        values = dict(
            mobile_e164="+201000000099",
            created_at=p.clock.now(p.cid),
            expires_at=p.clock.now(p.cid) + timedelta(minutes=10),
        )
        values.update(changes)
        return conn.execute(
            s.pending_signups.insert().values(**values).returning(s.pending_signups.c.id)
        ).scalar_one()


def test_pending_signup(prepared, monkeypatch):
    p = prepared
    sid = signup(p)
    fake = FakeAdapter()
    monkeypatch.setitem(ADAPTERS, "screen_phone", fake)
    params = dict(
        audience="doctor",
        booking_id=None,
        channel="telegram",
        pending_signup_id=sid,
        template_id="op:signup_code",
        blanks={"code": "123456"},
    )
    oid = enqueue(p, **params)
    handle(p, send_retry, oid)
    assert fake.rows[0]["phone"] == "+201000000099"
    for i, changes in enumerate(
        [
            dict(booking_id=p.bid),
            dict(audience="patient"),
            dict(channel="sms"),
            dict(pending_signup_id=999),
            dict(pending_signup_id=signup(p, expires_at=NOW)),
            dict(pending_signup_id=signup(p, completed_at=NOW)),
        ]
    ):
        with pytest.raises(ValueError):
            enqueue(p, key=f"invalid-{i}", **(params | changes))
    oid2 = enqueue(p, key="deleted", **params)
    with write_tx(p.engine) as conn:
        conn.execute(s.pending_signups.delete().where(s.pending_signups.c.id == sid))
    handle(p, send_retry, oid2)
    assert row(p, oid2)["status"] == "failed"
    assert len(fake.rows) == 1
    with p.engine.connect() as conn:
        assert row(p, oid2)["pending_signup_id"] is None
        assert (
            conn.execute(
                select(s.action_record.c.text).where(s.action_record.c.kind == "message_failure")
            ).scalar_one()
            == "no_recipient"
        )


@pytest.mark.parametrize(
    "sandbox,demo,adapter",
    [
        (False, False, "telegram"),
        (True, False, "screen_phone"),
        (False, True, "screen_phone"),
    ],
)
def test_pending_gate(prepared, monkeypatch, sandbox, demo, adapter):
    p = prepared
    get_settings().demo_mode = demo
    with write_tx(p.engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == p.cid).values(is_sandbox=sandbox))
    if adapter == "telegram":
        link(p, "doctor", "+201000000001")
    entry = dict(OPERATIONAL["doctor_alert_brake"], status="PENDING")
    monkeypatch.setitem(OPERATIONAL, "doctor_alert_brake", entry)
    rendered = render_operational(
        "doctor_alert_brake", "ar", {"channel_label": "Telegram", "count": 30}
    )
    assert not rendered.approved
    oid = enqueue(
        p,
        audience="doctor",
        booking_id=None,
        template_id="op:doctor_alert_brake",
        blanks={"channel_label": "Telegram", "count": 30},
        channel="telegram",
    )
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == ("delivered" if sandbox or demo else "blocked_unapproved")


@pytest.mark.parametrize("mode", ["refused", "unknown", "crash", "report_timeout"])
def test_failure_chains(prepared, monkeypatch, mode):
    p = prepared
    link(p)
    fake = FakeAdapter(
        "unknown" if mode == "unknown" else "refused" if mode == "refused" else "accepted",
        reports=mode == "report_timeout",
    )
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    oid = enqueue(p)
    if mode == "refused":
        for n in (1, 2, 3):
            handle(p, send_retry, oid, n)
            before = all_state(p)
            on_send_result(p.engine, p.clock, oid, n, SendResult("refused"))
            handle(p, send_retry, oid, n)
            assert all_state(p) == before
            p.clock.advance(minutes=2)
        assert len(fake.rows) == 3
    else:
        ctx = handle(p, send_retry, oid, dispatch=mode != "crash")
        handle(p, send_retry, oid)
        assert len(fake.rows) == (0 if mode == "crash" else 1)
        assert not handle(p, send_retry, oid).after_commit
        p.clock.advance(minutes=5)
        handle(p, delivery_timeout, oid)
        assert len(ctx.after_commit) == 1
    assert row(p, oid)["status"] == "failed"
    with p.engine.connect() as conn:
        rows = conn.execute(select(s.outbox).order_by(s.outbox.c.id)).mappings().all()
        assert len(rows) == 2
        assert rows[1]["template_id"] == "op:doctor_alert_unreachable"
    before = all_state(p)
    handle(p, delivery_timeout, oid)
    assert all_state(p) == before


def all_state(p):
    with p.engine.connect() as conn:
        return [
            conn.execute(select(table).order_by(*table.primary_key.columns)).all()
            for table in (s.outbox, s.timers, s.action_record, s.usage)
        ]


@pytest.mark.parametrize("kind", [None, "doctor"])
def test_screen_failure_alerts_once(prepared, monkeypatch, kind):
    p = prepared
    if kind:
        link(p, kind)
    monkeypatch.setitem(ADAPTERS, "screen_phone", FakeAdapter("unknown"))
    oid = enqueue(p)
    handle(p, send_retry, oid)
    p.clock.advance(minutes=5)
    handle(p, delivery_timeout, oid)
    with p.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.outbox)).scalar_one() == 2


def test_reporting_and_usage(prepared, monkeypatch):
    p = prepared
    fake = FakeAdapter(reports=True)
    link(p)
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    oid = enqueue(p)
    handle(p, send_retry, oid)
    assert row(p, oid)["status"] == "sent"
    with p.engine.connect() as conn:
        usage = conn.execute(select(s.usage)).mappings().one()
        assert usage["service"] == "telegram"
        assert usage["units"] == 1
        assert usage["est_cost_usd"] == 0
    p.clock.advance(minutes=5)
    handle(p, delivery_timeout, oid)
    before = all_state(p)
    on_delivery_report(p.engine, p.clock, "fixture:1", "delivered")
    after = all_state(p)
    assert before[-1] == after[-1]
    assert row(p, oid)["status"] == "failed"
    on_delivery_report(p.engine, p.clock, "fixture:1", "delivered")
    assert all_state(p) == after
    on_delivery_report(p.engine, p.clock, "unknown", "delivered")
    assert all_state(p) == after


def test_delivery_report_duplicate(prepared, monkeypatch):
    p = prepared
    monkeypatch.setitem(ADAPTERS, "screen_phone", FakeAdapter(reports=True))
    oid = enqueue(p)
    handle(p, send_retry, oid)
    on_delivery_report(p.engine, p.clock, "fixture:1", "delivered")
    assert row(p, oid)["status"] == "delivered"
    before = all_state(p)
    on_delivery_report(p.engine, p.clock, "fixture:1", "delivered")
    handle(p, delivery_timeout, oid)
    assert all_state(p) == before


def test_telegram_retry_after(prepared, monkeypatch):
    p = prepared
    link(p)
    fake = FakeAdapter("refused", retry_after=600)
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    oid = enqueue(p, channel="telegram")
    handle(p, send_retry, oid)
    with p.engine.connect() as conn:
        retry = conn.execute(select(s.timers).where(s.timers.c.idempotency_key == f"send:{oid}:2"))
        assert retry.mappings().one()["due_at"] == (NOW + timedelta(minutes=10)).astimezone(
            __import__("datetime").UTC
        )
        assert (
            conn.execute(
                select(s.timers.c.status).where(s.timers.c.idempotency_key == f"dt:{oid}:1")
            ).scalar_one()
            == "cancelled"
        )
        assert not conn.execute(select(s.usage)).all()


@pytest.mark.parametrize(
    "status,data,outcome,delay",
    [
        (200, {"ok": True, "result": {"message_id": 42}}, "accepted", None),
        (429, {"ok": False, "parameters": {"retry_after": 600}}, "refused", 600),
        (400, {"ok": False}, "refused", None),
        (500, {"ok": False}, "unknown", None),
        (200, {}, "unknown", None),
        (429, {"ok": False}, "unknown", None),
    ],
)
def test_telegram_http(monkeypatch, status, data, outcome, delay):
    get_settings().telegram_bot_token = "fictional-token"
    requests = []

    def responder(request):
        requests.append(request)
        return httpx.Response(status, json=data)

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        result = TelegramAdapter(client).send({"chat_id": "123", "body": "<untrusted> & text"})
    assert result.outcome == outcome
    assert result.retry_after_s == delay
    assert requests[0].read() == b'{"chat_id":"123","text":"<untrusted> & text"}'


def test_telegram_timeout():
    get_settings().telegram_bot_token = "fictional-token"

    def responder(request):
        raise httpx.ReadTimeout("timeout")

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        adapter = TelegramAdapter(client)
        assert adapter.send({"chat_id": "123", "body": "x"}).outcome == "unknown"
        assert adapter.send({"body": "x"}).error == "no_telegram_link"


def test_telegram_brake(prepared, monkeypatch):
    p = prepared
    link(p)
    with write_tx(p.engine) as conn:
        values = dict(conn.execute(select(s.bookings)).mappings().one())
        del values["id"]
        conn.execute(s.bookings.insert().values(**(values | dict(queue_number=8, order_key=8))))
    monkeypatch.setitem(ADAPTERS, "telegram", FakeAdapter())
    for channel in ("telegram",):
        for n in range(32):
            oid = enqueue(p, key=f"{channel}:{n}", channel=channel)
            handle(p, send_retry, oid)
            assert row(p, oid)["status"] == ("delivered" if n < 30 else "blocked_by_brake")
        with p.engine.connect() as conn:
            count = conn.execute(
                select(func.count())
                .select_from(s.action_record)
                .where(s.action_record.c.kind == "send_attempt", s.action_record.c.text == channel)
            ).scalar_one()
            assert count == 30
    with p.engine.connect() as conn:
        alerts = conn.execute(
            select(s.outbox).where(s.outbox.c.template_id == "op:doctor_alert_brake")
        )
        ids = [r["id"] for r in alerts.mappings()]
        assert len(ids) == 1
    for oid in ids:
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == "delivered"
    p.clock.advance(minutes=24 * 60)
    tomorrow = enqueue(p, key="tomorrow")
    handle(p, send_retry, tomorrow)
    assert row(p, tomorrow)["status"] == "delivered"


def test_enqueue_concurrent(prepared):
    p = prepared
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: enqueue(p), range(4)))
    assert len(set(ids)) == 1


@pytest.mark.postgres
def test_postgres_enqueue_serialization(postgres_engine):
    seed(postgres_engine)
    clock = FrozenClock(NOW)
    record.configure(clock)
    with postgres_engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
    p = SimpleNamespace(engine=postgres_engine, clock=clock, cid=cid, bid=None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(
            pool.map(
                lambda _: enqueue(
                    p,
                    audience="doctor",
                    template_id="op:reset_code",
                    blanks={"code": "123456"},
                    channel="telegram",
                ),
                range(4),
            )
        )
    assert len(set(ids)) == 1


def test_delayed_refusal_cancels_earlier_timeout(prepared):
    p = prepared
    oid = enqueue(p)
    handle(p, send_retry, oid, dispatch=False)
    p.clock.advance(minutes=4)
    on_send_result(p.engine, p.clock, oid, 1, SendResult("refused", retry_after_s=120))
    with p.engine.connect() as conn:
        assert (
            conn.execute(
                select(s.timers.c.status).where(s.timers.c.idempotency_key == f"dt:{oid}:1")
            ).scalar_one()
            == "cancelled"
        )
        retry_at = conn.execute(
            select(s.timers.c.due_at).where(s.timers.c.idempotency_key == f"send:{oid}:2")
        ).scalar_one()
        assert retry_at == p.clock.now(p.cid) + timedelta(minutes=2)
    assert row(p, oid)["status"] == "queued"


def test_secretary_alerts(prepared, monkeypatch):
    p = prepared
    with write_tx(p.engine) as conn:
        conn.execute(
            s.clinics.update().where(s.clinics.c.id == p.cid).values(secretary_alerts_on=True)
        )
        conn.execute(
            s.secretary_links.insert().values(
                clinic_id=p.cid,
                token_hash="fictional",
                used_at=NOW,
                telegram_chat_id="secretary-fixture",
            )
        )
    monkeypatch.setitem(ADAPTERS, "screen_phone", FakeAdapter("unknown"))
    oid = enqueue(p)
    handle(p, send_retry, oid)
    p.clock.advance(minutes=5)
    handle(p, delivery_timeout, oid)
    with p.engine.connect() as conn:
        alert = (
            conn.execute(select(s.outbox).where(s.outbox.c.audience == "secretary"))
            .mappings()
            .one()
        )
        assert (alert["channel"], alert["adapter"], alert["recipient_kind"]) == (
            "telegram",
            "telegram",
            "secretary",
        )
        assert recipient(conn, alert) == (None, "secretary-fixture")
    fake = FakeAdapter()
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    handle(p, send_retry, alert["id"])
    assert fake.rows[0]["chat_id"] == "secretary-fixture"


def test_telegram_failure_alerts_once(prepared, monkeypatch):
    p = prepared
    link(p)
    fake = FakeAdapter("refused")
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    oid = enqueue(p, channel="telegram")
    for attempt in (1, 2, 3):
        handle(p, send_retry, oid, attempt)
    assert row(p, oid)["status"] == "failed"
    with p.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.outbox)).scalar_one() == 2
        assert not conn.execute(select(s.usage)).all()


def test_brake_scales_with_non_cancelled_bookings(prepared):
    p = prepared
    with write_tx(p.engine) as conn:
        booking = dict(conn.execute(select(s.bookings)).mappings().one())
        del booking["id"]
        for number in range(8, 19):
            conn.execute(
                s.bookings.insert().values(
                    **(
                        booking
                        | dict(
                            queue_number=number,
                            order_key=number,
                            state="cancelled" if number == 18 else "booked",
                        )
                    )
                )
            )
    # 11 non-cancelled bookings permit 33 attempts, the cancelled row adds nothing.
    for n in range(34):
        oid = enqueue(p, key=f"scaled:{n}")
        handle(p, send_retry, oid)
        assert row(p, oid)["status"] == ("delivered" if n < 33 else "blocked_by_brake")


@pytest.mark.postgres
def test_postgres_brake_concurrency(postgres_engine, monkeypatch):
    seed(postgres_engine)
    clock = FrozenClock(NOW)
    record.configure(clock)
    with postgres_engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
    p = SimpleNamespace(engine=postgres_engine, clock=clock, cid=cid, bid=None)
    ids = [
        enqueue(
            p,
            key=f"race:{n}",
            audience="doctor",
            template_id="op:reset_code",
            blanks={"code": "123456"},
            channel="telegram",
        )
        for n in range(32)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda oid: handle(p, send_retry, oid), ids))
    with postgres_engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.action_record)
                .where(s.action_record.c.kind == "send_attempt")
            ).scalar_one()
            == 30
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.outbox)
                .where(s.outbox.c.status == "blocked_by_brake")
            ).scalar_one()
            == 2
        )


def test_duplicate_failed_delivery_report(prepared, monkeypatch):
    p = prepared
    monkeypatch.setitem(ADAPTERS, "screen_phone", FakeAdapter(reports=True))
    oid = enqueue(p)
    handle(p, send_retry, oid)
    on_delivery_report(p.engine, p.clock, "fixture:1", "failed")
    assert row(p, oid)["status"] == "failed"
    before = all_state(p)
    on_delivery_report(p.engine, p.clock, "fixture:1", "failed")
    assert all_state(p) == before


@pytest.mark.parametrize(
    "sandbox,demo,linked",
    [(False, False, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_patient_channel_resolution_and_no_channel_alert_once(prepared, sandbox, demo, linked):
    p = prepared
    get_settings().demo_mode = demo
    with write_tx(p.engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == p.cid).values(is_sandbox=sandbox))
    if linked:
        link(p)
    oid = enqueue(p)
    first = row(p, oid)
    assert first["channel"] == "telegram"
    assert first["adapter"] == ("telegram" if linked or not (sandbox or demo) else "screen_phone")
    no_channel = not (linked or sandbox or demo)
    assert first["status"] == ("failed" if no_channel else "queued")
    before = all_state(p)
    assert enqueue(p) == oid
    assert all_state(p) == before
    with p.engine.connect() as conn:
        messages = conn.execute(select(s.outbox)).mappings().all()
        failures = (
            conn.execute(
                select(s.action_record.c.text).where(s.action_record.c.kind == "message_failure")
            )
            .scalars()
            .all()
        )
        assert len(messages) == (2 if no_channel else 1)
        if no_channel:
            assert failures == ["no_channel", "no_channel"]
            assert messages[1]["template_id"] == "op:doctor_alert_unreachable"
            assert messages[1]["status"] == "failed"
            assert not conn.execute(select(s.timers)).first()


@pytest.mark.parametrize("adapter", ["screen_phone", "mac_relay", "we_business"])
def test_legacy_queued_rows_fail_without_dispatch_or_rewriting_history(prepared, adapter):
    p = prepared
    oid = enqueue(p)
    # Simulate a queued legacy row; the upgrade keeps historical columns intact.
    with write_tx(p.engine) as conn:
        conn.execute(
            s.outbox.update().where(s.outbox.c.id == oid).values(channel="sms", adapter=adapter)
        )
    assert not handle(p, send_retry, oid).after_commit
    failed = row(p, oid)
    assert failed["status"] == "failed" and failed["channel"] == "sms"
    with p.engine.connect() as conn:
        alert = conn.execute(select(s.outbox).where(s.outbox.c.id != oid)).mappings().one()
        assert alert["template_id"] == "op:doctor_alert_unreachable"
        assert alert["channel"] == "telegram"
        assert not conn.execute(select(s.usage)).first()
    before = all_state(p)
    handle(p, send_retry, oid)
    assert all_state(p) == before
