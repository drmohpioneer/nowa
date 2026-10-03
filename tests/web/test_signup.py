"""Slice-10 HTTP acceptance and credential regressions."""

import re

# All traffic uses the real HTTP adapters, schema and engine; no provider is called.
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest
import zxingcpp
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core import signup
from nowa.core.sandbox import seed_sandbox_evening
from nowa.db import metadata, write_tx
from tests.helpers.worker import drain
from tests.web.test_doctor_web import post as command


def completion(token):
    return dict(
        signup_token=token,
        mobile="+201000000005",
        name_ar="كريم محمود",
        name_en="Karim Mahmoud",
        specialty="cardiology",
        address="Fictional clinic",
        lat=30.0911,
        lng=31.3228,
        pin_kind="here",
        hours=[dict(weekday=day, start="19:00", end="23:00") for day in range(7)],
        price_egp=300,
        password="fictional-password",
        agreement_version="0.1",
        agree=True,
        idempotency_key="fictional-http-completion",
    )


def test_completed_signup_cookie_cannot_display_replacement_signup_code(engine, offset_clock):
    """Decision 063: same-time ID reuse cannot reuse the completed bearer credential."""
    origin = {"Origin": "http://127.0.0.1:8000"}
    with TestClient(
        create_app(engine, clock=offset_clock), base_url="http://127.0.0.1:8000"
    ) as client:
        assert (
            client.post(
                "/signup/code", json={"mobile": "+201000000005"}, headers=origin
            ).status_code
            == 200
        )
        old_cookie = client.cookies.get("nowa_signup")
        with engine.connect() as conn:
            nonce = conn.execute(select(s.pending_signups.c.nonce)).scalar_one()
            assert re.fullmatch(r"[a-f0-9]{32}", nonce)
            assert old_cookie.split("|")[2] == nonce
        first_messages = client.get("/signup/phone").json()
        first = first_messages[0]
        code = re.search(r"\b[0-9]{6}\b", first["body"])[0]
        token = client.post(
            "/signup/verify", json={"mobile": "+201000000005", "code": code}, headers=origin
        ).json()["signup_token"]
        assert (
            client.post("/signup/complete", json=completion(token), headers=origin).status_code
            == 200
        )
        with engine.connect() as conn:
            assert not conn.execute(select(s.pending_signups)).all()
            assert (
                conn.execute(
                    select(s.outbox.c.pending_signup_id).where(s.outbox.c.id == first["outbox_id"])
                ).scalar_one()
                is None
            )
        assert client.get("/signup/phone").status_code == 403
        # Completion and replacement share one FrozenClock instant; IDs and expiry repeat.
        assert (
            client.post(
                "/signup/code", json={"mobile": "+201000000006"}, headers=origin
            ).status_code
            == 200
        )
        new_cookie = client.cookies.get("nowa_signup")
        assert new_cookie != old_cookie
        with engine.connect() as conn:
            replacement_nonce = conn.execute(select(s.pending_signups.c.nonce)).scalar_one()
            assert replacement_nonce != nonce
            assert new_cookie.split("|")[2] == replacement_nonce
        replacement_messages = client.get("/signup/phone").json()
        replacement = replacement_messages[0]
        assert replacement["pending_signup_id"] == first["pending_signup_id"]
        assert replacement["outbox_id"] != first["outbox_id"]
        # Present the completed sign-up's still-valid bearer credential.
        client.cookies.clear()
        client.cookies.set("nowa_signup", old_cookie, path="/signup")
        assert client.get("/signup/phone").status_code == 403
        client.cookies.set("nowa_signup", new_cookie, path="/signup")
        assert client.get("/signup/phone").json() == replacement_messages


ORIGIN = {"Origin": "http://127.0.0.1:8000"}


@pytest.fixture
def signup_web(engine, offset_clock, monkeypatch):
    monkeypatch.setenv("JUDGE_CODES", "fictional-judge-code,second-fictional-code")
    get_settings.cache_clear()
    with TestClient(
        create_app(engine, clock=offset_clock), base_url="http://127.0.0.1:8000"
    ) as client:
        yield client


def send(client, path, body):
    return client.post(path, json=body, headers=ORIGIN)


def ordinary_token(client, phone="+201000000005"):
    assert send(client, "/signup/code", {"mobile": phone}).status_code == 200
    messages = client.get("/signup/phone").json()
    code = re.search(r"\b[0-9]{6}\b", messages[-1]["body"])[0]
    response = send(client, "/signup/verify", {"mobile": phone, "code": code})
    assert response.status_code == 200, response.text
    return response.json()["signup_token"]


def judge_token(client):
    response = send(client, "/judge/start", {"code": "fictional-judge-code"})
    assert response.status_code == 200, response.text
    return response.json()["signup_token"]


def finish(client, token, **changes):
    return send(client, "/signup/complete", completion(token) | changes)


def clinic_for(engine, slug):
    with engine.connect() as conn:
        return dict(
            conn.execute(select(s.clinics).where(s.clinics.c.slug == slug)).mappings().one()
        )


def decode_svg(svg):
    """Rasterize segno's horizontal strokes from the ACTUAL endpoint SVG, then decode."""
    root = ET.fromstring(svg)
    path = root.find("path")
    scale = int(re.fullmatch(r"scale\((\d+)\)", path.attrib["transform"])[1])
    size = int(root.attrib["width"]) // scale
    image = bytearray([255]) * (size * size)
    x = y = 0
    tokens = re.findall(r"([Mmh])(-?\d+(?:\.\d+)?)(?: (-?\d+(?:\.\d+)?))?", path.attrib["d"])
    for verb, a, b in tokens:
        if verb == "M":
            x, y = float(a), float(b)
        elif verb == "m":
            x, y = x + float(a), y + float(b)
        else:
            length = int(a)
            for pixel in range(int(x), int(x) + length):
                image[int(y) * size + pixel] = 0
            x += length
    # Expand for robust QR detection without installing image dependencies.
    enlarged = bytearray()
    for row in range(size):
        pixels = bytes(v for v in image[row * size : (row + 1) * size] for _ in range(scale))
        enlarged.extend(pixels * scale)
    decoded = zxingcpp.read_barcode(memoryview(enlarged).cast("B", shape=[size * scale] * 2))
    assert decoded is not None
    return decoded.text


def test_doctor_signup_screenphone_login_chat_qr_poster_and_expired_replay(
    signup_web, engine, offset_clock, frozen_clock
):
    client = signup_web
    assert client.get("/d/qr.svg").status_code == 401
    token = ordinary_token(client)
    drain(engine, offset_clock, worker.build_registry())
    assert client.get("/signup/phone").json()[-1]["status"] == "delivered"
    result = finish(client, token, address="<script>alert(1)</script>").json()
    assert client.cookies.get("nowa_session") and client.cookies.get("nowa_csrf")
    assert client.get("/d/api/settings").json()["items"]
    dashboard = client.get("/d").text
    assert result["slug"] in dashboard
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in dashboard
    assert client.get("/c/" + result["slug"]).status_code == 200
    svg = client.get("/d/qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert decode_svg(svg.text) == result["chat_url"]
    poster = client.get("/d/poster").text
    assert result["chat_url"] in poster and 'src="/d/qr.svg"' in poster
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in poster
    assert "<script>alert(1)</script>" not in poster
    assert "size: A4" in client.get("/static/nowa.css").text
    assert finish(client, token, idempotency_key="new-key").json()["reason"] == "already_registered"
    frozen_clock.advance(minutes=31)
    with engine.connect() as conn:
        before = conn.execute(select(s.doctor_sessions.c.id)).all()
    replay = send(
        client,
        "/signup/complete",
        {"idempotency_key": "fictional-http-completion", "signup_token": token},
    )
    assert replay.json() == result and "set-cookie" not in replay.headers
    with engine.connect() as conn:
        assert conn.execute(select(s.doctor_sessions.c.id)).all() == before
    assert command(client, "sandbox/advance", {"minutes": 10}).status_code == 403
    assert client.get("/d/api/sandbox/phone").status_code == 403


def test_front_page_bilingual_agreement_judge_and_hidden_watch(signup_web, engine, monkeypatch):
    ar = signup_web.get("/").text
    en = signup_web.get("/?lang=en").text
    assert 'dir="rtl"' in ar and 'dir="ltr"' in en
    assert "<form" not in ar
    assert "/demo" in ar and "/start" in ar and "/d/login" in ar
    assert 'id="judge-form"' in signup_web.get("/judge").text
    start = signup_web.get("/start").text
    assert 'id="code-form"' in start
    assert "dermatology" not in start
    assert "0.1" in start and "[COMPANY_NAME]" in start
    # The stage entrance now belongs to the hub, not the front page.
    assert "/demo/evening" in signup_web.get("/demo").text
    monkeypatch.setenv("JUDGE_CODES", "")
    get_settings.cache_clear()
    assert signup_web.get("/judge").status_code == 404
    assert 'id="judge-form"' not in signup_web.get("/").text
    assert send(signup_web, "/judge/start", {"code": ""}).status_code == 400
    assert signup_web.get("/c/_nowa").status_code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("specialty", "dermatology"),
        ("name_en", "Karim2"),
        ("name_en", "http Karim"),
        ("name_en", "www Karim"),
        ("name_en", "<Karim>"),
        ("price_egp", 100001),
        ("price_egp", 1.5),
        ("password", "short"),
        ("agree", False),
        ("agreement_version", "obsolete"),
        ("hours", []),
        ("hours", [dict(weekday=0, start="25:00", end="23:00")]),
        ("hours", [dict(weekday=0, start="19:00", end="23:00")] * 2),
        ("lat", 0),
        ("lng", 0),
    ],
)
def test_http_completion_rejects_tampering_without_partial_creation(
    signup_web, engine, field, value
):
    token = ordinary_token(signup_web)
    response = finish(signup_web, token, **{field: value})
    assert response.status_code == 422, response.text
    with engine.connect() as conn:
        assert conn.execute(select(s.clinics.c.slug)).scalars().all() == ["_nowa"]
        assert conn.execute(select(s.doctors)).all() == []
        assert conn.execute(select(s.agreement_acceptances)).all() == []
        assert conn.execute(select(s.pending_signups.c.completed_at)).scalar_one() is None


def test_signup_code_generic_response_ip_limit_and_cookie_isolation(signup_web, engine):
    registered = finish(signup_web, ordinary_token(signup_web))
    assert registered.status_code == 200
    refused = send(signup_web, "/signup/code", {"mobile": "+201000000005"})
    assert refused.status_code == 200 and refused.json() == {"ok": True, "telegram_url": None}
    with engine.connect() as conn:
        assert not conn.execute(select(s.pending_signups)).first()
    assert signup_web.get("/signup/phone").status_code == 403
    a = send(signup_web, "/signup/code", {"mobile": "+201000000007"})
    cookie_a = signup_web.cookies.get("nowa_signup")
    msgs_a = signup_web.get("/signup/phone").json()
    b = send(signup_web, "/signup/code", {"mobile": "+201000000006"})
    assert a.json() == b.json() == {"ok": True, "telegram_url": None}
    assert a.status_code == b.status_code == 200
    msgs_b = signup_web.get("/signup/phone").json()
    assert {m["outbox_id"] for m in msgs_a}.isdisjoint(m["outbox_id"] for m in msgs_b)
    signup_web.cookies.set("nowa_signup", cookie_a, path="/signup")
    assert signup_web.get("/signup/phone").json() == msgs_a
    signup_web.cookies.set("nowa_signup", "forged", path="/signup")
    assert signup_web.get("/signup/phone").status_code == 403
    signup_web.cookies.clear()
    assert signup_web.get("/signup/phone").status_code == 403
    for index in range(6):
        assert (
            send(signup_web, "/signup/code", {"mobile": f"+201000003{index:03d}"}).status_code
            == 200
        )
    with engine.connect() as conn:
        before = conn.execute(select(s.pending_signups.c.id)).all()
    assert send(signup_web, "/signup/code", {"mobile": "+201000003010"}).status_code == 429
    with engine.connect() as conn:
        assert conn.execute(select(s.pending_signups.c.id)).all() == before


def test_wrong_code_five_then_right_and_expired_cookie(signup_web, frozen_clock):
    send(signup_web, "/signup/code", {"mobile": "+201000000005"})
    code = re.search(r"\b[0-9]{6}\b", signup_web.get("/signup/phone").json()[-1]["body"])[0]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            send(
                signup_web, "/signup/verify", {"mobile": "+201000000005", "code": wrong}
            ).status_code
            == 400
        )
    assert (
        send(signup_web, "/signup/verify", {"mobile": "+201000000005", "code": code}).status_code
        == 400
    )
    frozen_clock.advance(minutes=40)
    assert signup_web.get("/signup/phone").status_code == 403


def test_hosted_guard_no_demo_phone_but_judge_works(signup_web, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        signup, "get_settings", lambda: settings.model_copy(update={"demo_mode": False})
    )
    import nowa.web.signup as http_signup

    monkeypatch.setattr(http_signup, "get_settings", signup.get_settings)
    assert signup_web.get("/signup/phone").status_code == 404
    response = send(signup_web, "/signup/code", {"mobile": "+201000000005"})
    assert response.status_code == 503 and response.json()["reason"] == "not open yet"
    assert "set-cookie" not in response.headers
    assert send(signup_web, "/judge/start", {"code": "fictional-judge-code"}).status_code == 200


def test_judge_exact_compare_all_codes_and_ip_limit_before_compare(signup_web, monkeypatch):
    spy = Mock(wraps=signup.hmac.compare_digest)
    monkeypatch.setattr(signup.hmac, "compare_digest", spy)
    for value, status in [
        ("fictional-judge-code", 200),
        ("fictional-judge-code ", 400),
        ("FICTIONAL-JUDGE-CODE", 400),
    ]:
        spy.reset_mock()
        assert send(signup_web, "/judge/start", {"code": value}).status_code == status
        assert spy.call_count == 2
        assert [c.args[1] for c in spy.call_args_list] == [
            b"fictional-judge-code",
            b"second-fictional-code",
        ]
    for _ in range(17):
        assert send(signup_web, "/judge/start", {"code": "wrong"}).status_code == 400
    spy.reset_mock()
    assert send(signup_web, "/judge/start", {"code": "fictional-judge-code"}).status_code == 429
    spy.assert_not_called()


def test_judge_limit_and_candidate_single_use(signup_web, engine):
    first = judge_token(signup_web)
    assert finish(signup_web, first).status_code == 200
    assert finish(signup_web, first, idempotency_key="reused").json()["reason"] == "reused_token"
    # Capacity is checked again at completion, even for a previously issued candidate.
    waiting = judge_token(signup_web)
    for i in range(2):
        assert (
            finish(signup_web, judge_token(signup_web), idempotency_key=f"judge-{i}").status_code
            == 200
        )
    assert finish(signup_web, waiting, idempotency_key="fourth").status_code == 429
    assert send(signup_web, "/judge/start", {"code": "fictional-judge-code"}).status_code == 429
    with engine.connect() as conn:
        phones = conn.execute(select(s.doctors.c.mobile_e164)).scalars().all()
        assert phones == ["+201000000900", "+201000000901", "+201000000902"]


def test_judge_golden_path_seed_advance_leave_phone_expire_and_tombstones(
    signup_web, engine, offset_clock, frozen_clock
):
    result = finish(signup_web, judge_token(signup_web)).json()
    clinic = clinic_for(engine, result["slug"])
    cid = clinic["id"]
    assert result["mobile"] == "+201000000900"
    assert signup_web.get("/c/" + result["slug"]).status_code == 200
    queue = signup_web.get("/d/api/tonight").json()
    assert len(queue["rows"]) == 12
    with engine.connect() as conn:
        assert not conn.execute(select(s.outbox).where(s.outbox.c.template_id == "1")).all()
        kinds = set(
            conn.execute(select(s.timers.c.kind).where(s.timers.c.clinic_id == cid)).scalars()
        )
        assert {"are_you_on_way", "evening_system_close"} <= kinds
        before = conn.execute(select(s.bookings)).all()
        offset = conn.execute(
            select(s.clinics.c.clock_offset_s).where(s.clinics.c.id == cid)
        ).scalar_one()
    seed_sandbox_evening(engine, offset_clock, cid)
    with engine.connect() as conn:
        assert conn.execute(select(s.bookings)).all() == before
        assert (
            conn.execute(
                select(s.clinics.c.clock_offset_s).where(s.clinics.c.id == cid)
            ).scalar_one()
            == offset
        )
    assert command(signup_web, "sandbox/advance", {"minutes": -1}).status_code == 422
    assert command(signup_web, "sandbox/advance", {"minutes": 181}).status_code == 422
    assert command(signup_web, "sandbox/advance", {"minutes": 45}, "start").status_code == 200
    current = offset_clock.now(cid)
    assert command(signup_web, "sandbox/advance", {"minutes": 45}, "start").status_code == 200
    assert offset_clock.now(cid) == current
    assert command(signup_web, "on-my-way", {"lat": 30.0911, "lng": 31.3228}).json()["ok"]
    assert command(signup_web, "sandbox/advance", {"minutes": 180}, "fast").status_code == 200
    drain(engine, offset_clock, worker.build_registry(), only_clinic_id=cid)
    messages = signup_web.get("/d/api/sandbox/phone").json()
    leave = [m for m in messages if m["template_id"] == "2"]
    assert leave and len({m["booking_id"] for m in leave}) == len(leave)
    assert all(re.fullmatch(r"\*{7}\d{4}", m["recipient"]) for m in leave)
    assert all(m["status"] == "delivered" for m in leave)
    latest = max(m["outbox_id"] for m in messages)
    assert signup_web.get(f"/d/api/sandbox/phone?after_id={latest}").json() == []
    with engine.connect() as conn:
        assert conn.execute(select(s.clinics.c.id).where(s.clinics.c.id == cid)).first()
    frozen_clock.advance(minutes=7 * 24 * 60)
    registry = {"sandbox_expire": worker.build_registry()["sandbox_expire"]}
    assert worker.run_once(engine, offset_clock, registry).done == 1
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            if "clinic_id" in table.c:
                assert not conn.execute(select(table).where(table.c.clinic_id == cid)).all(), (
                    table.name
                )
        assert not conn.execute(select(s.clinics).where(s.clinics.c.id == cid)).all()
        assert (
            conn.execute(
                select(s.timers.c.status).where(s.timers.c.kind == "sandbox_expire")
            ).scalar_one()
            == "done"
        )
    assert signup_web.get("/c/" + result["slug"]).status_code == 410
    assert signup_web.get("/c/unknown-fictional").status_code == 404
    assert send(signup_web, "/c/" + result["slug"] + "/session", {}).status_code == 410
    common = {"session": "fictional-session", "idempotency_key": "deleted-clinic"}
    for route, fields in (
        ("turn", {"text": "Fictional question"}),
        ("tap", {"action": "none", "payload": {}}),
        ("consent", {"booking_for": "other"}),
        ("lookup", {"name": "Karim", "last4": "2000"}),
    ):
        assert (
            send(signup_web, "/c/" + result["slug"] + "/" + route, common | fields).status_code
            == 410
        )

    assert signup_web.get("/d?clinic=" + result["slug"]).status_code == 410
    assert (
        signup_web.get("/d/api/tonight", headers={"X-Clinic-Slug": result["slug"]}).status_code
        == 410
    )
    assert signup_web.get("/d/api/tonight").status_code == 401


def test_sandbox_isolation_and_telegram_cleanup_on_mobile_reuse(
    signup_web, engine, offset_clock, frozen_clock, monkeypatch
):
    from nowa.core import timing
    from nowa.messaging.outbox import enqueue_message
    from nowa.messaging.templates import DoctorNames
    from nowa.telegram.router import Router
    from tests.telegram.conftest import FakeTelegramAPI
    from tests.telegram.support import message, tap

    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "fictional_bot")
    get_settings.cache_clear()
    first = finish(signup_web, judge_token(signup_web)).json()
    clinic = clinic_for(engine, first["slug"])
    cid = clinic["id"]
    queue = signup_web.get("/d/api/tonight").json()
    eid = queue["evening_id"]
    bid = queue["rows"][0]["booking_id"]
    with engine.connect() as conn:
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == cid)).mappings().one()
        )
        contact = (
            conn.execute(select(s.contacts).where(s.contacts.c.clinic_id == cid).limit(1))
            .mappings()
            .one()
        )
    # The patient phone is explicitly allowlisted; sandbox routing must still select ScreenPhone.
    with write_tx(engine) as conn:
        mid = enqueue_message(
            conn,
            offset_clock,
            cid,
            "2",
            "ar",
            "patient",
            bid,
            timing.patient_blanks(conn, bid, "2"),
            "fictional-sandbox-patient",
        )
        row = conn.execute(select(s.outbox).where(s.outbox.c.id == mid)).mappings().one()
        assert row["adapter"] == "screen_phone"
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=doctor["mobile_e164"],
                kind="patient",
                telegram_chat_id="303",
                linked_at=offset_clock.now(cid, conn=conn),
            )
        )
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=contact["phone_e164"],
                kind="patient",
                telegram_chat_id="404",
                linked_at=offset_clock.now(cid, conn=conn),
            )
        )
    link = command(signup_web, "telegram-link").json()["url"]
    api = FakeTelegramAPI()
    router = Router(engine, offset_clock, api)
    router.handle_update(message(900, chat=101, text="/start " + link.split("start=")[1]))
    with write_tx(engine) as conn:
        linked = (
            conn.execute(
                select(s.telegram_links).where(
                    s.telegram_links.c.phone_e164 == doctor["mobile_e164"]
                )
            )
            .mappings()
            .all()
        )
        assert {r["kind"] for r in linked} == {"doctor", "patient"}
        doctor_mid = enqueue_message(
            conn,
            offset_clock,
            cid,
            "5",
            "ar",
            "doctor",
            None,
            {
                "doctor_name": DoctorNames("كريم محمود", "Karim Mahmoud"),
                "clinic_start": offset_clock.now(cid),
                "booked_count": 12,
            },
            "fictional-sandbox-doctor",
        )
        assert (
            conn.execute(select(s.outbox.c.channel).where(s.outbox.c.id == doctor_mid)).scalar_one()
            == "telegram"
        )
    # A cannot use a foreign clinic_id, evening or booking. Accepted ownership guard is exercised.
    second = finish(signup_web, judge_token(signup_web), idempotency_key="second-sandbox").json()
    second_cid = clinic_for(engine, second["slug"])["id"]
    assert command(signup_web, "who-comes-in", {"booking_id": bid}).status_code == 404
    assert (
        command(signup_web, "sandbox/advance", {"minutes": 1, "clinic_id": cid}).status_code == 422
    )
    with write_tx(engine) as conn:
        own_mid = enqueue_message(
            conn,
            offset_clock,
            second_cid,
            "5",
            "ar",
            "doctor",
            None,
            {
                "doctor_name": DoctorNames("كريم محمود", "Karim Mahmoud"),
                "clinic_start": offset_clock.now(second_cid),
                "booked_count": 12,
            },
            "fictional-second-doctor",
        )
    assert [m["outbox_id"] for m in signup_web.get("/d/api/sandbox/phone").json()] == [own_mid]
    frozen_clock.advance(minutes=7 * 24 * 60)
    assert (
        worker.run_once(
            engine, offset_clock, {"sandbox_expire": worker.build_registry()["sandbox_expire"]}
        ).done
        == 2
    )
    with engine.connect() as conn:
        assert not conn.execute(select(s.telegram_links)).all()
        assert not conn.execute(select(s.link_tokens)).all()
    # Expiry frees the lowest reserved number; neither kind of Telegram authority survives.
    replacement = finish(signup_web, judge_token(signup_web), idempotency_key="replacement").json()
    assert replacement["mobile"] == first["mobile"]
    assert replacement["slug"] not in {first["slug"], second["slug"]}
    before = signup_web.get("/d/api/tonight").json()
    api.clear()
    tap(router, 901, "in", eid, bid, chat=101)
    assert signup_web.get("/d/api/tonight").json() == before
    assert all("reply_markup" not in payload for _, payload in api.calls)
    with engine.connect() as conn:
        assert not conn.execute(select(s.telegram_links)).all()
    with write_tx(engine) as conn:
        replacement_cid = clinic_for(engine, replacement["slug"])["id"]
        mid = enqueue_message(
            conn,
            offset_clock,
            replacement_cid,
            "5",
            "ar",
            "doctor",
            None,
            {
                "doctor_name": DoctorNames("كريم محمود", "Karim Mahmoud"),
                "clinic_start": offset_clock.now(replacement_cid),
                "booked_count": 12,
            },
            "fictional-replacement-doctor",
        )
        row = conn.execute(select(s.outbox).where(s.outbox.c.id == mid)).mappings().one()
        assert row["channel"] == "telegram" and row["adapter"] == "screen_phone"


@pytest.mark.parametrize("pin_kind, mark", [("area", "pin:area"), ("here", "pin:exact")])
def test_signup_pin_mark_is_private_action_text(signup_web, engine, pin_kind, mark):
    token = ordinary_token(signup_web)
    changes = {"pin_kind": pin_kind}
    if pin_kind == "area":
        with engine.connect() as conn:
            area_id = conn.execute(select(s.areas.c.id).limit(1)).scalar_one()
        changes.update(lat=None, lng=None, area_id=area_id)
    response = finish(signup_web, token, **changes)
    assert response.status_code == 200, response.text
    slug = response.json()["slug"]
    chat = signup_web.get(f"/c/{slug}")
    assert chat.status_code == 200
    assert "faq:other" not in chat.text
    assert "rough pin" not in chat.text
    clinic = clinic_for(engine, slug)
    with engine.connect() as conn:
        assert conn.execute(
            select(s.action_record.c.text).where(
                s.action_record.c.clinic_id == clinic["id"],
                s.action_record.c.kind == "signup_complete",
            )
        ).scalar_one() == mark
        assert set(conn.execute(
            select(s.clinic_info.c.key).where(s.clinic_info.c.clinic_id == clinic["id"])
        ).scalars()) == {"price", "address"}


@pytest.mark.parametrize("lang, status", [("franco", 422), ("ar", 200), ("en", 200)])
def test_signup_code_accepts_only_page_languages(signup_web, engine, lang, status):
    response = send(signup_web, "/signup/code", {"mobile": "+201000000005", "lang": lang})
    assert response.status_code == status, response.text
    with engine.connect() as conn:
        codes = conn.execute(select(s.auth_codes)).all()
        messages = conn.execute(select(s.outbox).where(s.outbox.c.template_id == "op:signup_code"))
        rows = messages.mappings().all()
    if status == 422:
        assert not codes and not rows
    else:
        assert len(codes) == len(rows) == 1
        assert rows[0]["lang"] == lang


def test_judge_config_entries_stripped_but_input_stays_exact(signup_web, monkeypatch):
    monkeypatch.setenv("JUDGE_CODES", "a, b\n c")
    get_settings.cache_clear()
    for value in ("a", "b", "c"):
        assert send(signup_web, "/judge/start", {"code": value}).status_code == 200
    for value in (" b", "c ", "B"):
        assert send(signup_web, "/judge/start", {"code": value}).status_code == 400


def test_judge_seed_failure_rolls_back_creation_and_can_retry(signup_web, engine, monkeypatch):
    from nowa.core import flows

    token = judge_token(signup_web)
    with engine.connect() as conn:
        before = {table.name: conn.execute(select(table)).all() for table in metadata.sorted_tables}
    real_book = flows.book_in_tx
    calls = []

    def fail_after_first_booking(conn, clock, req, confirm=True):
        calls.append(req.clinic_id)
        if len(calls) == 2:
            # The first real booking and newly created clinic exist in THIS transaction.
            assert conn.execute(select(s.bookings.c.id).where(
                s.bookings.c.clinic_id == req.clinic_id
            )).first()
            raise RuntimeError("fictional seed failure")
        return real_book(conn, clock, req, confirm=confirm)

    monkeypatch.setattr(flows, "book_in_tx", fail_after_first_booking)
    with pytest.raises(RuntimeError, match="fictional seed failure"):
        finish(signup_web, token)
    assert len(calls) == 2
    with engine.connect() as conn:
        after = {table.name: conn.execute(select(table)).all() for table in metadata.sorted_tables}
    assert after == before
    monkeypatch.setattr(flows, "book_in_tx", real_book)
    response = finish(signup_web, token)
    assert response.status_code == 200, response.text
    clinic = clinic_for(engine, response.json()["slug"])
    with engine.connect() as conn:
        bookings = conn.execute(select(s.bookings).where(
            s.bookings.c.clinic_id == clinic["id"]
        )).all()
        assert len(bookings) == 12
    assert finish(signup_web, "expired-token").json() == response.json()
    with engine.connect() as conn:
        assert conn.execute(select(s.bookings).where(
            s.bookings.c.clinic_id == clinic["id"]
        )).all() == bookings
