import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from html import unescape
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import record, worker
from nowa import schema as s
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core import booking, flows, patient_link, timing, travel
from nowa.db import write_tx
from nowa.messaging import templates
from nowa.messaging.outbox import enqueue_message
from nowa.messaging.templates import format_day, format_time
from tests.core.support import DAY, move, request, row, setup
from tests.helpers.worker import drain
from tests.web.support import ORIGIN, ROOT, fields, messages, rows


@pytest.fixture
def page(engine, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    get_settings.cache_clear()
    cid, eid, clock, ids = setup(engine, count=2)
    code = booking.link_code_for(ids[0])
    with TestClient(create_app(engine, clock=clock), follow_redirects=False) as client:
        yield client, cid, eid, clock, ids, code


def post(client, path, data):
    result = client.post(path, data=data, headers=ORIGIN)
    if result.status_code == 303 and result.headers["location"].startswith(("/l/", "/w/", "/r/")):
        assert_private_headers(result)
        return client.get(result.headers["location"], follow_redirects=True)
    return result


def leave(engine, page, monkeypatch):
    client, cid, eid, clock, ids, code = page
    monkeypatch.setattr(travel, "minutes", lambda *a, **k: 10.0)
    move(clock, 0)
    assert timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "doctor-way").ok
    assert row(engine, s.bookings, ids[0])["state"] == "told_to_leave"


@pytest.mark.parametrize("lang,dir", [("ar", "rtl"), ("en", "ltr"), ("franco", "ltr")])
def test_view_language_time_and_map(engine, page, lang, dir):
    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(lang=lang))
    response = client.get(f"/l/{code}")
    view = booking.booking_view(engine, code)
    assert response.status_code == 200
    assert f'dir="{dir}"' in response.text
    assert '<footer class="legal">' in response.text
    assert ("سياسة الخصوصية" if lang == "ar" else "Privacy policy") in response.text
    assert ('/privacy"' if lang == "ar" else '/privacy?lang=en"') in response.text
    assert view.patient_first_name in response.text and view.doctor_name in response.text
    assert format_day(DAY, lang) in response.text
    assert format_time(view.expected_shown, lang) in response.text
    assert view.clinic_phone in response.text
    assert f"https://www.google.com/maps?q={view.clinic_lat},{view.clinic_lng}" in response.text
    assert "telegram" not in response.text
    assert 'name="last4"' in response.text
    assert 'name="last4" value=' not in response.text
    assert (
        row(engine, s.contacts, row(engine, s.bookings, ids[0])["contact_id"])["phone_e164"]
        not in response.text
    )


@pytest.mark.parametrize(
    "ua",
    ["WhatsApp", "TelegramBot", "facebookexternalhit", "iMessage", "SMSPreview", "Mozilla/5.0"],
)
@pytest.mark.parametrize("method", ["get", "head"])
def test_preview_and_normal_gets_do_not_write(engine, page, monkeypatch, ua, method):
    leave(engine, page, monkeypatch)
    client, cid, eid, clock, ids, code = page
    tables = [s.bookings, s.evenings, s.outbox, s.timers, s.action_record, s.idempotency_keys]
    before = [rows(engine, t) for t in tables]
    response = getattr(client, method)(f"/w/{code}", headers={"User-Agent": ua})
    assert response.status_code == 200
    assert before == [rows(engine, t) for t in tables]


def test_telegram_tap_undo_retap_and_silent_golden(engine, page, monkeypatch):
    leave(engine, page, monkeypatch)
    client, cid, eid, clock, ids, code = page
    telegram_message = next(m for m in messages(engine, "2") if m["booking_id"] == ids[0])
    assert f"/w/{code}" in telegram_message["body"]
    # The static script calls requestSubmit on the real POST form, including hidden fields.
    script = (ROOT / "nowa/web/static/omw.js").read_text()
    assert 'getElementById("omw")' in script and "requestSubmit" in script
    opened = client.get(
        urlsplit(next(word for word in telegram_message["body"].split() if "/w/" in word)).path
    )
    assert 'id="omw" method="post"' in opened.text and "<noscript>" in opened.text
    data = fields(opened, "/tap")
    assert set(data) == {"tap_token", "exp"}
    done = post(client, f"/w/{code}/tap", data)
    assert done.status_code == 200 and "Done, you're on your way" in unescape(done.text)
    assert set(fields(done, "/undo")) == set(data)
    first = row(engine, s.bookings, ids[0])["on_my_way_at"]
    clock.advance(minutes=2)
    post(client, f"/w/{code}/tap", data)
    assert row(engine, s.bookings, ids[0])["on_my_way_at"] == first
    clock.advance(minutes=9)
    drain(engine, clock, worker.build_registry())
    with engine.connect() as conn:
        assert not next(
            b for b in timing.tonight_board(conn, cid, eid).rows if b.booking_id == ids[0]
        ).silent
    undone = post(client, f"/w/{code}/undo", data)
    assert row(engine, s.bookings, ids[0])["state"] == "told_to_leave"
    fresh = fields(undone, "/tap")
    assert fresh["tap_token"] != data["tap_token"] and "/static/omw.js" not in undone.text
    with write_tx(engine) as conn:
        timing.recompute(conn, clock, eid)
        assert next(
            b for b in timing.tonight_board(conn, cid, eid).rows if b.booking_id == ids[0]
        ).silent
    clock.advance(minutes=1)
    done_again = post(client, f"/w/{code}/tap", fresh)
    assert done_again.status_code == 200
    assert row(engine, s.bookings, ids[0])["on_my_way_at"] > first
    with engine.connect() as conn:
        assert not next(
            b for b in timing.tonight_board(conn, cid, eid).rows if b.booking_id == ids[0]
        ).silent


@pytest.mark.parametrize("action", ["tap", "undo"])
@pytest.mark.parametrize(
    "bad", ["missing", "expired", "binding", "purpose", "foreign", "no_origin"]
)
def test_adversarial_tap(engine, page, monkeypatch, action, bad):
    from nowa.web import tokens

    leave(engine, page, monkeypatch)
    client, cid, eid, clock, ids, code = page
    bid = ids[1] if bad == "binding" else ids[0]
    token = tokens.issue("form" if bad == "purpose" else "omw", bid, clock.now(cid))
    data = {"tap_token": token.value, "exp": str(token.exp)}
    if bad == "missing":
        data = {}
    if bad == "expired":
        clock.advance(minutes=721)
    before = rows(engine, s.bookings)
    response = client.post(
        f"/w/{code}/{action}",
        data=data,
        headers=(
            {"Origin": "https://foreign.example"}
            if bad == "foreign"
            else {}
            if bad == "no_origin"
            else ORIGIN
        ),
    )
    assert response.status_code == 403
    assert rows(engine, s.bookings) == before
    assert response.headers["cache-control"] == "no-store"


def test_booked_tap_waits(engine, page):
    from nowa.web import tokens

    client, cid, eid, clock, ids, code = page
    token = tokens.issue("omw", ids[0], clock.now(cid))
    before = rows(engine, s.bookings)
    response = post(client, f"/w/{code}/tap", {"tap_token": token.value, "exp": str(token.exp)})
    assert "We'll tell you on Telegram when to leave" in unescape(response.text)
    assert rows(engine, s.bookings) == before


@pytest.mark.parametrize("state", ["cancelled", "seen", "didnt_come"])
def test_terminal_booking_readonly(engine, page, state):
    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state=state))
    response = client.get(f"/w/{code}")
    assert response.status_code == 200
    assert ("Book again" if state == "cancelled" else "cannot be changed") in response.text
    assert 'name="tap_token"' not in response.text


@pytest.mark.parametrize("state", ["closed", "cancelled"])
def test_terminal_evening_readonly(engine, page, monkeypatch, state):
    leave(engine, page, monkeypatch)
    client, cid, eid, clock, ids, code = page
    data = fields(client.get(f"/w/{code}"), "/tap")
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state=state))
    before = rows(engine, s.bookings)
    response = client.get(f"/w/{code}")
    assert 'name="tap_token"' not in response.text
    assert post(client, f"/w/{code}/tap", data).status_code == 200
    assert rows(engine, s.bookings) == before
    from nowa.web import tokens

    token = tokens.issue("form", ids[0], clock.now(cid))
    response = post(
        client,
        f"/l/{code}/cancel",
        {
            "last4": "0000",
            "form_token": token.value,
            "exp": str(token.exp),
        },
    )
    assert "cannot be changed" in response.text and 'name="form_token"' not in response.text
    assert rows(engine, s.bookings) == before


def test_cancel_once_and_reason(engine, page):
    client, cid, eid, clock, ids, code = page
    data = fields(client.get(f"/l/{code}"), "/cancel") | {"last4": "0000"}
    response = post(client, f"/l/{code}/cancel", data)
    assert response.text.count("Done, your booking is cancelled") == 1
    assert row(engine, s.bookings, ids[0])["state"] == "cancelled"
    assert booking.booking_view(engine, code).state_reason == "patient"
    assert post(client, f"/l/{code}/cancel", data).status_code == 200
    assert len(messages(engine, "3")) == 1
    assert client.get(f"/r/{code}").headers["location"] == f"/l/{code}"


def test_change_day_and_replay_without_new_code(engine, page):
    client, cid, eid, clock, ids, code = page
    form = client.get(f"/l/{code}/change")
    assert format_day(DAY + timedelta(days=2), "en") in form.text
    data = fields(form, "/change") | {
        "last4": "0000",
        "date": (DAY + timedelta(days=2)).isoformat(),
    }
    response = post(client, f"/l/{code}/change", data)
    assert "Done, your new link will reach you on Telegram" in response.text
    new = rows(engine, s.bookings)[-1]
    assert new["id"] != ids[0] and row(engine, s.bookings, ids[0])["state"] == "cancelled"
    assert booking.link_code_for(new["id"]) not in response.text
    again = post(client, f"/l/{code}/change", data)
    assert "new link will reach you on Telegram" in again.text
    assert len(rows(engine, s.bookings)) == 3
    assert len([m for m in messages(engine, "1") if m["booking_id"] == new["id"]]) == 1


def test_change_day_page_says_changed_not_cancelled(engine, page):
    from nowa.web import strings

    client, cid, eid, clock, ids, code = page
    new_day = DAY + timedelta(days=2)
    data = fields(client.get(f"/l/{code}/change"), "/change") | {
        "last4": "0000",
        "date": new_day.isoformat(),
    }
    response = post(client, f"/l/{code}/change", data)
    assert f"Done, your booking is moved to {format_day(new_day, 'en')}" in response.text
    assert "Done, your booking is cancelled" not in response.text
    assert "Book again" not in response.text
    assert strings.text("patient.day_changed", "ar").format(day="X") == "تمام، غيّرنا حجزك لـX"


def test_full_change_preserves_original(engine, page):
    client, cid, eid, clock, ids, code = page
    target = flows.book(engine, clock, request(cid, 10, DAY + timedelta(days=2)))
    assert isinstance(target, booking.BookingOk)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(max_per_evening=1))
    before = row(engine, s.bookings, ids[0])
    data = fields(client.get(f"/l/{code}/change"), "/change") | {
        "last4": "0000",
        "date": (DAY + timedelta(days=2)).isoformat(),
    }
    response = post(client, f"/l/{code}/change", data)
    assert (
        "unavailable" in response.text
        and format_day(DAY + timedelta(days=5), "en") in response.text
    )
    assert row(engine, s.bookings, ids[0]) == before
    assert not messages(engine, "3")


@pytest.mark.parametrize("kind", ["cancel_tonight", "close_untold"])
def test_rebook_once_from_clinic_cancel(engine, page, kind):
    client, cid, eid, clock, ids, code = page
    if kind == "cancel_tonight":
        doctor = rows(engine, s.doctors)[0]["id"]
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel-tonight").ok
    else:
        for i in range(2, 12):
            assert isinstance(flows.book(engine, clock, request(cid, i)), booking.BookingOk)
        move(clock, 0)
        assert timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "visit").ok
        ids = [rows(engine, s.bookings)[-1]["id"]]
        code = booking.link_code_for(ids[0])
        count = timing.close_preview(engine, clock, cid, eid).untold_count
        assert timing.close_evening(engine, clock, cid, eid, "doctor", "close", count).ok
    initial_count = len(rows(engine, s.bookings))
    assert booking.booking_view(engine, code).state_reason == kind
    form = client.get(f"/r/{code}")
    assert form.status_code == 200
    data = fields(form, f"/r/{code}") | {
        "last4": "0000" if kind == "cancel_tonight" else "0011",
        "date": (DAY + timedelta(days=2)).isoformat(),
    }
    response = post(client, f"/r/{code}", data)
    new = rows(engine, s.bookings)[-1]
    assert (
        "new link will reach you on Telegram" in response.text
        and booking.link_code_for(new["id"]) not in response.text
    )
    fresh_form = fields(client.get(f"/r/{code}"), f"/r/{code}")
    assert fresh_form["form_token"] != data["form_token"]
    data.update(fresh_form)
    assert post(client, f"/r/{code}", data).status_code == 200
    assert len(rows(engine, s.bookings)) == initial_count + 1
    assert len([m for m in messages(engine, "1") if m["booking_id"] == new["id"]]) == 1


def test_shared_last4_lockout_across_actions(engine, page, monkeypatch):
    from nowa.web import tokens

    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    # Rebook on an active booking still verifies before the flow's state refusal.
    paths = [
        f"/l/{code}/cancel",
        f"/l/{code}/change",
        f"/r/{code}",
        f"/l/{code}/telegram",
        f"/l/{code}/cancel",
    ]
    for path in paths:
        token = tokens.issue("form", ids[0], clock.now(cid))
        response = post(
            client,
            path,
            {
                "form_token": token.value,
                "exp": str(token.exp),
                "last4": "9999",
                "date": (DAY + timedelta(days=2)).isoformat(),
            },
        )
        assert "did not match" in response.text
    assert len([r for r in rows(engine, s.action_record) if r["kind"] == "link_verify_failed"]) == 5
    data = fields(client.get(f"/l/{code}"), "/cancel") | {"last4": "0000"}
    assert "Too many attempts" in post(client, f"/l/{code}/cancel", data).text
    assert row(engine, s.bookings, ids[0])["state"] == "booked"
    clock.advance(minutes=15)
    assert "booking is cancelled" in post(client, f"/l/{code}/cancel", data).text


@pytest.mark.parametrize("surface", ["/l/", "/w/", "/l/{code}/change", "/r/"])
def test_same_contact_isolation(engine, page, surface):
    client, cid, eid, clock, ids, code = page
    second = flows.book(
        engine,
        clock,
        replace(
            request(cid, 0, DAY + timedelta(days=2)),
            patient_name="Zain Different",
            idempotency_key="isolated-booking",
        ),
    )
    assert isinstance(second, booking.BookingOk)
    with write_tx(engine) as conn:
        conn.execute(
            s.patients.update()
            .where(s.patients.c.id == row(engine, s.bookings, ids[0])["patient_id"])
            .values(name="Karim Separate")
        )
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == second.booking_id)
            .values(
                expected_shown=row(engine, s.bookings, second.booking_id)["expected_shown"]
                + timedelta(hours=3, minutes=35)
            )
        )
    a, b = booking.booking_view(engine, code), booking.booking_view(engine, second.link_code)
    path = surface.format(code=code) if "{code}" in surface else surface + code
    response = client.get(path)
    if surface == "/r/":
        assert response.status_code == 303
        return
    assert "Karim" in response.text and "Zain" not in response.text
    # Only booked details are checked; the change page legitimately lists other dates.
    if surface != "/l/{code}/change":
        assert (
            format_day(a.date, "en") in response.text
            and format_day(b.date, "en") not in response.text
        )
    assert format_time(b.expected_shown, "en") not in response.text
    assert booking.link_code_for(second.booking_id) not in response.text


@pytest.mark.parametrize("prefix", ["l", "w", "r"])
def test_unknown_malformed_identical(engine, page, prefix):
    client = page[0]
    a = client.get(f"/{prefix}/{'x' * 22}")
    b = client.get(f"/{prefix}/bad-code")
    assert a.status_code == b.status_code == 404 and a.content == b.content


def test_cancel_failure_rolls_back(engine, page, monkeypatch):
    client, cid, eid, clock, ids, code = page
    data = fields(client.get(f"/l/{code}"), "/cancel") | {"last4": "0000"}
    before = rows(engine, s.bookings)

    def fail(*args, **kwargs):
        raise RuntimeError("injected after cancellation")

    monkeypatch.setattr(flows, "_message", fail)
    with pytest.raises(RuntimeError, match="injected"):
        post(client, f"/l/{code}/cancel", data)
    assert rows(engine, s.bookings) == before and not messages(engine, "3")


def test_telegram_form_is_view_only(engine, page):
    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    for path in (f"/w/{code}", f"/l/{code}/change", f"/l/{code}"):
        response = client.get(path)
        assert response.status_code == 200
        assert (f'action="/l/{code}/telegram"' in response.text) == (path == f"/l/{code}")
    doctor = rows(engine, s.doctors)[0]["id"]
    token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel-for-rebook").ok
    for path in (f"/w/{code}", f"/r/{code}", f"/l/{code}"):
        response = client.get(path)
        assert response.status_code == 200
        assert f'action="/l/{code}/telegram"' not in response.text


def test_telegram_token_once_replace_and_expiry(engine, page):
    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=False))
    assert '<button class="btn btn-danger">' in client.get(f"/l/{code}").text
    data = fields(client.get(f"/l/{code}"), "/telegram") | {"last4": "0000"}
    response = post(client, f"/l/{code}/telegram", data)
    assert response.status_code == 303
    url = response.headers["location"]
    assert url.startswith("https://t.me/nowa_test_bot?start=p_")
    token = url.split("p_", 1)[1]
    assert len(token) == 43
    first = rows(engine, s.link_tokens)[0]
    assert first["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert first["subject_id"] == row(engine, s.bookings, ids[0])["contact_id"]
    assert first["expires_at"] == clock.now(cid) + timedelta(minutes=15)
    assert token not in repr(first) and token not in repr(rows(engine, s.idempotency_keys))
    response = post(client, f"/l/{code}/telegram", data)
    assert response.status_code == 200 and "already opened" in response.text
    assert len(rows(engine, s.link_tokens)) == 1
    clock.advance(minutes=1)
    fresh = fields(client.get(f"/l/{code}"), "/telegram") | {"last4": "0000"}
    assert fresh["form_token"] != data["form_token"]
    assert post(client, f"/l/{code}/telegram", fresh).status_code == 303
    tokens = rows(engine, s.link_tokens)
    assert len(tokens) == 2 and tokens[0]["expires_at"] == clock.now(cid)
    assert tokens[1]["expires_at"] > clock.now(cid) and tokens[1]["used_at"] is None


def test_telegram_sandbox_and_repeated_core(engine, page):
    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=True))
    data = fields(client.get(f"/l/{code}"), "/telegram") | {"last4": "0000"}
    assert "not available here" in post(client, f"/l/{code}/telegram", data).text
    assert not rows(engine, s.link_tokens)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=False))
    first = patient_link.create_telegram_token(engine, clock, code, "0000", "tg-test")
    assert first.url
    assert patient_link.create_telegram_token(
        engine, clock, code, "0000", "tg-test"
    ) == patient_link.TokenResult(None, True)
    assert len(rows(engine, s.link_tokens)) == 1


def test_pending_send_block_does_not_gate_page(engine, page, monkeypatch):
    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=False))
    settings = get_settings()
    settings.demo_mode = False
    # All current reference keys are approved; simulate a future PENDING revision
    # using the same file-backed operational key as the messaging gating tests.
    pending = "doctor_alert_brake"
    monkeypatch.setitem(
        templates.OPERATIONAL, pending, dict(templates.OPERATIONAL[pending], status="PENDING")
    )
    with write_tx(engine) as conn:
        doctor_phone = conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == cid)
        ).scalar_one()
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=doctor_phone,
                kind="doctor",
                telegram_chat_id="991",
                linked_at=clock.now(cid),
            )
        )
        outbox_id = enqueue_message(
            conn,
            clock,
            cid,
            "op:" + pending,
            "en",
            "doctor",
            None,
            {"channel_label": "Telegram", "count": 30},
            "pending-page",
        )
    assert row(engine, s.outbox, outbox_id)["status"] == "blocked_unapproved"
    assert client.get(f"/l/{code}").status_code == 200


def test_telegram_concurrent_replay(engine, page):
    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=False))

    def run(_):
        return patient_link.create_telegram_token(engine, clock, code, "0000", "tg-concurrent")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r.repeated for r in results) == [False, True]
    assert len(rows(engine, s.link_tokens)) == 1


@pytest.mark.postgres
def test_telegram_postgres_concurrent_replay(postgres_engine):
    cid, eid, clock, ids = setup(postgres_engine, count=1)
    record.configure(clock)
    get_settings().telegram_bot_username = "nowa_test_bot"
    with write_tx(postgres_engine) as conn:
        conn.execute(s.clinics.update().values(is_sandbox=False))

    def run(_):
        return patient_link.create_telegram_token(
            postgres_engine, clock, booking.link_code_for(ids[0]), "0000", "tg-concurrent"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r.repeated for r in results) == [False, True]
    assert len(rows(postgres_engine, s.link_tokens)) == 1


def assert_private_headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("method", ["get", "head"])
@pytest.mark.parametrize("path", ["/l/{code}", "/w/{code}", "/l/{code}/change", "/r/{code}"])
def test_all_read_routes_have_private_headers(engine, page, method, path):
    client, cid, eid, clock, ids, code = page
    tables = [s.bookings, s.evenings, s.outbox, s.timers, s.action_record, s.idempotency_keys]
    before = [rows(engine, t) for t in tables]
    response = getattr(client, method)(path.format(code=code))
    assert response.status_code == (303 if path.startswith("/r/") else 200)
    assert_private_headers(response)
    assert before == [rows(engine, t) for t in tables]


@pytest.mark.parametrize("action", ["tap", "undo", "cancel", "change", "rebook", "telegram"])
def test_all_post_routes_have_private_headers(engine, page, monkeypatch, action):
    from nowa.web import tokens

    client, cid, eid, clock, ids, code = page
    if action in {"tap", "undo"}:
        leave(engine, page, monkeypatch)
        if action == "undo":
            assert timing.patient_on_my_way(engine, clock, ids[0], "initial-way").ok
        path = f"/w/{code}/{action}"
        token = tokens.issue("omw", ids[0], clock.now(cid))
        data = {"tap_token": token.value, "exp": str(token.exp)}
    else:
        if action == "rebook":
            doctor = rows(engine, s.doctors)[0]["id"]
            confirm = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
            assert timing.cancel_tonight(engine, clock, cid, eid, doctor, confirm, "cancel-all").ok
        if action == "telegram":
            get_settings().telegram_bot_username = "nowa_test_bot"
            with write_tx(engine) as conn:
                conn.execute(s.clinics.update().values(is_sandbox=False))
        path = f"/r/{code}" if action == "rebook" else f"/l/{code}/{action}"
        token = tokens.issue("form", ids[0], clock.now(cid))
        data = {
            "form_token": token.value,
            "exp": str(token.exp),
            "last4": "0000",
            "date": (DAY + timedelta(days=2)).isoformat(),
        }
    response = post(client, path, data)
    assert response.status_code == (303 if action == "telegram" else 200)
    assert_private_headers(response)


@pytest.mark.parametrize("action", ["cancel", "change", "rebook", "telegram"])
@pytest.mark.parametrize(
    "bad",
    ["missing", "expired", "binding", "purpose", "signature", "exp", "foreign", "no_origin"],
)
def test_adversarial_forms_do_not_write(engine, page, action, bad):
    from nowa.web import tokens

    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "nowa_test_bot"
    token = tokens.issue(
        "omw" if bad == "purpose" else "form",
        ids[1] if bad == "binding" else ids[0],
        clock.now(cid),
    )
    data = {
        "form_token": token.value,
        "exp": str(token.exp),
        "last4": "0000",
        "date": (DAY + timedelta(days=2)).isoformat(),
    }
    if bad == "missing":
        del data["form_token"]
    elif bad == "expired":
        clock.advance(minutes=30)
    elif bad == "signature":
        data["form_token"] = (
            token.value[:22] + ("A" if token.value[22] != "A" else "B") + token.value[23:]
        )
    elif bad == "exp":
        data["exp"] = str(token.exp + 1)
    tables = [
        s.bookings,
        s.evenings,
        s.outbox,
        s.timers,
        s.action_record,
        s.idempotency_keys,
        s.link_tokens,
        s.rate_counters,
    ]
    before = [rows(engine, t) for t in tables]
    path = f"/r/{code}" if action == "rebook" else f"/l/{code}/{action}"
    response = client.post(
        path,
        data=data,
        headers={"Origin": "https://foreign.example"}
        if bad == "foreign"
        else {}
        if bad == "no_origin"
        else ORIGIN,
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "This request is invalid" in response.text
    assert_private_headers(response)
    assert before == [rows(engine, t) for t in tables]


@pytest.mark.parametrize("bad", ["duplicate", "upload"])
def test_ambiguous_or_uploaded_form_fields_refused(engine, page, bad):
    from urllib.parse import urlencode

    client, cid, eid, clock, ids, code = page
    data = fields(client.get(f"/l/{code}"), "/cancel") | {"last4": "0000"}
    before = rows(engine, s.bookings)
    if bad == "duplicate":
        response = client.post(
            f"/l/{code}/cancel",
            content=urlencode(list(data.items()) + [("last4", "0000")]),
            headers=ORIGIN | {"Content-Type": "application/x-www-form-urlencoded"},
        )
    else:
        response = client.post(
            f"/l/{code}/cancel",
            data=data,
            files={"extra": ("upload.txt", b"untrusted")},
            headers=ORIGIN,
        )
    assert response.status_code == 403
    assert_private_headers(response)
    assert rows(engine, s.bookings) == before


def test_same_origin_referer_fallback_posts_real_form(engine, page):
    client, cid, eid, clock, ids, code = page
    opened = client.get(f"/l/{code}")
    assert opened.headers["referrer-policy"] == "same-origin"
    data = fields(opened, "/cancel") | {"last4": "0000"}
    response = client.post(
        f"/l/{code}/cancel",
        data=data,
        headers={"Referer": f"http://127.0.0.1:8000/l/{code}"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert row(engine, s.bookings, ids[0])["state"] == "cancelled"


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_forbidden_page_uses_booking_language(engine, page, lang):
    from nowa.web import strings

    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(lang=lang))
    response = post(client, f"/l/{code}/cancel", {})
    assert response.status_code == 403
    assert strings.text("patient.forbidden", lang) in response.text
    assert f'dir="{"rtl" if lang == "ar" else "ltr"}"' in response.text


@pytest.mark.parametrize("prefix", ["l", "w", "r"])
def test_framework_errors_have_html_wording_and_headers(engine, page, prefix):
    client, cid, eid, clock, ids, code = page
    for path, method, status in [
        (f"/{prefix}/{code}/not-a-route", "get", 404),
        (f"/{prefix}/{code}", "put", 405),
        (f"/{prefix}", "get", 404),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == status
        assert response.headers["content-type"].startswith("text/html")
        assert_private_headers(response)
        assert '"detail"' not in response.text
    missing = client.get(f"/{prefix}/{code}/not-a-route")
    assert missing.content == client.get(f"/{prefix}/bad-code").content


@pytest.mark.parametrize("prefix", ["l", "w", "r"])
def test_unhandled_error_has_headers_and_remains_observable(
    engine, page, monkeypatch, prefix, caplog
):
    import logging

    from nowa.web import strings

    client, cid, eid, clock, ids, code = page

    def fail(*args):
        raise RuntimeError("injected private failure")

    monkeypatch.setattr(patient_link, "view", fail)
    caplog.set_level(logging.INFO, logger="nowa.access")
    with TestClient(create_app(engine, clock=clock), raise_server_exceptions=False) as errors:
        response = errors.get(f"/{prefix}/{code}")
    assert response.status_code == 500
    assert_private_headers(response)
    assert strings.text("patient.server_error", "ar") in response.text
    assert code not in response.text and "injected" not in response.text
    log = "\n".join(r.getMessage() for r in caplog.records if r.name == "nowa.access")
    assert f"GET /{prefix}/<code> 500" in log and code not in log
    # Rendering an error page must not swallow the underlying failure.
    with pytest.raises(RuntimeError, match="injected private failure"):
        client.get(f"/{prefix}/{code}")


def test_validation_error_uses_private_ui_and_nonprivate_defaults(engine, page, monkeypatch):
    from fastapi.exceptions import RequestValidationError

    client, cid, eid, clock, ids, code = page

    def fail(*args):
        raise RequestValidationError([{"type": "missing", "loc": ["body", "secret"]}])

    monkeypatch.setattr(patient_link, "view", fail)
    response = client.get(f"/l/{code}")
    assert response.status_code == 422
    assert_private_headers(response)
    assert "secret" not in response.text and '"detail"' not in response.text
    assert client.get("/not-a-route").json() == {"detail": "Not Found"}


def test_external_anchors_suppress_referrer(engine, page):
    from html.parser import HTMLParser

    class Anchors(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.links.append(dict(attrs))

    client, cid, eid, clock, ids, code = page
    for path in (f"/l/{code}", f"/w/{code}", f"/l/{code}/change"):
        parser = Anchors()
        parser.feed(client.get(path).text)
        external = [a for a in parser.links if not a["href"].startswith("/")]
        assert any(a["href"].startswith("https://www.google.com/maps?") for a in external)
        assert all(set(a["rel"].split()) == {"noopener", "noreferrer"} for a in external)


def test_rebook_page_isolates_cancelled_booking_on_shared_contact(engine, page):
    client, cid, eid, clock, ids, code = page
    second = flows.book(
        engine,
        clock,
        replace(
            request(cid, 0, DAY + timedelta(days=2)),
            patient_name="Zain Different",
            idempotency_key="other-day",
        ),
    )
    assert isinstance(second, booking.BookingOk)
    with write_tx(engine) as conn:
        conn.execute(
            s.patients.update()
            .where(s.patients.c.id == row(engine, s.bookings, ids[0])["patient_id"])
            .values(name="Karim Separate")
        )
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == second.booking_id)
            .values(expected_shown=clock.now(cid) + timedelta(hours=3, minutes=35))
        )
    doctor = rows(engine, s.doctors)[0]["id"]
    confirm = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    assert timing.cancel_tonight(engine, clock, cid, eid, doctor, confirm, "clinic-cancel").ok
    a = booking.booking_view(engine, code)
    b = booking.booking_view(engine, second.link_code)
    tables = [s.bookings, s.evenings, s.outbox, s.timers, s.action_record, s.idempotency_keys]
    before = [rows(engine, t) for t in tables]
    response = client.get(f"/r/{code}")
    assert response.status_code == 200
    # Compare booking details only: the available-day buttons may legitimately list B's day.
    details = response.text.split('id="booking-details">', 1)[1].split(
        '<a class="btn btn-ghost"', 1
    )[0]
    assert "Karim" in response.text and "Zain" not in response.text
    assert format_day(a.date, "en") in details and format_day(b.date, "en") not in details
    assert format_time(a.expected_shown, "en") in details
    assert format_time(b.expected_shown, "en") not in details
    assert second.link_code not in response.text
    assert_private_headers(response)
    assert client.head(f"/r/{code}").status_code == 200
    assert before == [rows(engine, t) for t in tables]


def test_telegram_json_card_renews_with_verified_form_only(page, engine):
    client, cid, eid, clock, ids, code = page
    get_settings().telegram_bot_username = "fictional_bot"
    # Existing private-link flow is deliberately unavailable to sandbox bookings.
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    page_response = client.get(f"/l/{code}")
    html = page_response.text
    assert 'id="patient-telegram-form"' in html
    assert "/static/patient-telegram.js" in html
    form = fields(page_response, "/telegram")
    form["last4"] = "0000"
    headers = ORIGIN | {"Accept": "application/json"}
    endpoint = f"/l/{code}/telegram"
    result = client.post(endpoint, data=form, headers=headers)
    assert result.status_code == 200, result.text
    first = result.json()
    clock.advance(minutes=15)
    replacement = client.post(
        endpoint,
        data={"form_token": first["form_token"], "exp": first["exp"], "last4": "0000"},
        headers=headers,
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["telegram_url"] != first["telegram_url"]
    with engine.connect() as conn:
        assert len(conn.execute(select(s.link_tokens)).all()) == 2
        # Private-link proof remains as before; there is no public bypass.
        assert not conn.execute(select(s.telegram_pending)).first()
    bad = client.post(
        endpoint,
        data={
            "form_token": replacement.json()["form_token"],
            "exp": replacement.json()["exp"],
            "last4": "9999",
        },
        headers=headers,
    )
    assert bad.status_code != 200
