from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core import booking, timing
from nowa.core import patient_link as private_link
from nowa.db import write_tx
from nowa.messaging.adapters import ADAPTERS
from nowa.messaging.outbox import enqueue_message
from nowa.telegram import keyboards
from nowa.web.strings import text
from tests.core.support import row
from tests.helpers.worker import drain
from tests.telegram.support import callback, doctor_link, inline_data, message, tap
from tests.web.support import ORIGIN, rows


def headers(client):
    return ORIGIN | {"X-CSRF-Token": client.cookies.get("nowa_csrf")}


def test_real_06_and_05_tokens_primary_delivery_and_unlink(bot, engine, monkeypatch):
    router, cid, eid, _, clock, ids, fake = bot
    get_settings().telegram_bot_username = "fictional_bot"
    monkeypatch.setitem(ADAPTERS, "telegram", fake)
    # Actual F7 issuer, not a manufactured doctor token.
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        assert (
            client.post(
                "/d/login", headers=ORIGIN, json={"mobile": "01000000001", "password": "demo1234"}
            ).status_code
            == 200
        )
        response = client.post(
            "/d/api/telegram-link", headers=headers(client), json={"idempotency_key": "real-f7"}
        )
        payload = parse_qs(urlsplit(response.json()["url"]).query)["start"][0]
    router.handle_update(message(1, text="/start " + payload))
    # Actual link-code issuer; the demo clinic is a real-shaped, fictional clinic, not sandbox.
    code = booking.link_code_for(ids[0])
    with engine.connect() as conn:
        last4 = conn.execute(
            select(s.contacts.c.phone_e164)
            .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
            .where(s.bookings.c.id == ids[0])
        ).scalar_one()[-4:]
    link = private_link.create_telegram_token(engine, clock, code, last4, "real-05")
    assert isinstance(link, private_link.TokenResult) and link.url
    router.handle_update(
        message(2, 201, "/start " + parse_qs(urlsplit(link.url).query)["start"][0])
    )
    registry = worker.build_registry()
    # At clinic start, template 5 is sent via the existing outbox adapter with two buttons.
    fake.clear()
    drain(engine, clock, registry)
    template5 = next(r for r in rows(engine, s.outbox) if r["template_id"] == "5")
    assert template5["status"] == "delivered" and template5["channel"] == "telegram"
    assert any(
        {b["callback_data"] for b in p.get("reply_markup", {}).get("inline_keyboard", [[]])[0]}
        == {f"omw:{eid}:-:-", f"cancel:{eid}:-:-"}
        for _, p in fake.calls
        if p.get("text") == template5["body"]
    )
    tap(router, 3, "omw", eid)
    router.handle_update(message(4, location={"latitude": 30.111, "longitude": 31.222}))
    assert row(engine, s.evenings, eid)["state"] == "doctor_on_way"

    with write_tx(engine) as conn:
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="told_to_leave")
        )
        oid = enqueue_message(
            conn,
            clock,
            cid,
            "2",
            "en",
            "patient",
            ids[0],
            timing.patient_blanks(conn, ids[0], "2"),
            "scenario-telegram",
        )
    for delay in (0, 1, 2):
        clock.advance(minutes=delay)
        drain(engine, clock, registry)
    delivered = row(engine, s.outbox, oid)
    assert delivered["status"] == "delivered" and delivered["channel"] == "telegram"
    assert not any(r["idempotency_key"] == "scenario-telegram:tg" for r in rows(engine, s.outbox))
    assert f"omw:-:{ids[0]}:-" in inline_data(fake)
    tap(router, 5, "omw", bid=ids[0], chat=201)
    assert row(engine, s.bookings, ids[0])["state"] == "on_my_way"
    assert f"undo:-:{ids[0]}:-" in inline_data(fake)
    router.handle_update(message(6, 201, "حجوزاتي"))
    tap(router, 7, "unlink", chat=201)
    tap(router, 8, "unlinkok", chat=201)
    assert {r["kind"] for r in rows(engine, s.telegram_links)} == {"doctor"}
    get_settings().demo_mode = False
    with write_tx(engine) as conn:
        enqueue_message(
            conn,
            clock,
            cid,
            "2",
            "en",
            "patient",
            ids[0],
            timing.patient_blanks(conn, ids[0], "2"),
            "after-unlink",
        )
    for delay in (0, 1, 2):
        clock.advance(minutes=delay)
        drain(engine, clock, registry)
    assert not any(r["idempotency_key"] == "after-unlink:tg" for r in rows(engine, s.outbox))
    alert = next(
        r for r in rows(engine, s.outbox) if r["idempotency_key"] == "after-unlink:alert:doctor"
    )
    assert alert["status"] == "delivered"
    assert any(p.get("text") == alert["body"] and "reply_markup" not in p for _, p in fake.calls)


def test_doctor_full_evening_actions_and_close_count_change(bot, engine):
    router, _, eid, _, clock, ids, fake = bot
    doctor_link(bot, engine)
    tap(router, 2, "omw", eid)
    tap(router, 3, "area", eid, arg="1")
    assert row(engine, s.evenings, eid)["state"] == "doctor_on_way"
    tap(router, 4, "in", eid, ids[0])
    clock.advance(minutes=12)
    tap(router, 5, "in", eid, ids[2])
    tap(router, 6, "undo", eid)
    assert row(engine, s.bookings, ids[2])["state"] != "seen"
    tap(router, 7, "walkin", eid)
    assert any(r["source"] == "walkin_tap" for r in rows(engine, s.bookings))
    tap(router, 8, "more", eid)
    tap(router, 9, "close", eid)
    data = next(data for data in reversed(inline_data(fake)) if data.startswith("closeok:"))
    old_count = int(keyboards.parse(data).arg)
    # A new patient enters between the preview and the confirm; engine must re-ask.
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[-1]).values(state="booked"))
    current = timing.close_preview(engine, clock, bot[1], eid).untold_count
    if current == old_count:
        with write_tx(engine) as conn:
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == ids[-1]).values(state="on_my_way")
            )
    router.handle_update(callback(10, data))
    assert row(engine, s.evenings, eid)["state"] == "running"
    new_data = next(d for d in reversed(inline_data(fake)) if d.startswith("closeok:"))
    assert new_data != data
    reask = [p for method, p in fake.calls if method == "editMessageText"][-1]
    fake.clear()
    router.handle_update(callback(10, data))
    assert fake.calls == [
        ("editMessageText", reask),
        ("answerCallbackQuery", {"callback_query_id": "query-10"}),
    ]
    assert reask["text"] == text("tg.close_untold", "ar").format(
        count=int(keyboards.parse(new_data).arg)
    )
    assert inline_data(fake) == [new_data]
    assert row(engine, s.evenings, eid)["state"] == "running"
    assert not any(r["key"] == "tg:10:handled" for r in rows(engine, s.idempotency_keys))
    router.handle_update(callback(11, new_data))
    assert row(engine, s.evenings, eid)["state"] == "closed"
    assert any(method == "editMessageText" for method, _ in fake.calls)


def test_cancel_has_second_confirmation(bot, engine):
    router, _, eid, _, _, _, fake = bot
    doctor_link(bot, engine)
    tap(router, 2, "cancel", eid)
    assert row(engine, s.evenings, eid)["state"] == "scheduled"
    data = next(d for d in inline_data(fake) if d.startswith("cancelok:"))
    router.handle_update(callback(3, data))
    assert row(engine, s.evenings, eid)["state"] == "cancelled"
    assert all(r["state"] == "cancelled" for r in rows(engine, s.bookings))


@pytest.mark.parametrize(
    "command,function,verb,payload",
    [
        ("on-my-way", "doctor_on_my_way", "area", {"area_id": 1}),
        ("who-comes-in", "who_comes_in_in_tx", "in", {}),
        ("who-comes-in", "who_comes_in_in_tx", "walkin", {"walk_in": True}),
        ("undo", "undo_last_in_tx", "undo", {}),
        ("close/preview", "close_preview", "close", {}),
        ("close", "close_evening_in_tx", "closeok", {"expected_untold": 0}),
        ("cancel-tonight/request", "request_cancel_tonight", "cancel", {}),
        ("cancel-tonight/confirm", "cancel_tonight_in_tx", "cancelok", {}),
    ],
)
def test_same_engine_function_and_arguments_as_dashboard(
    bot, engine, monkeypatch, command, function, verb, payload
):
    router, cid, eid, did, clock, ids, _ = bot
    doctor_link(bot, engine)
    spy = Mock(wraps=getattr(timing, function))
    monkeypatch.setattr(timing, function, spy)
    if verb == "in":
        payload = {"booking_id": ids[0]}
    if verb == "cancelok":
        payload = {"confirm_token": timing.request_cancel_tonight(engine, clock, cid, eid, did)}
    arg = str(
        payload.get("area_id", payload.get("expected_untold", payload.get("confirm_token", "-")))
    )
    tap(router, 8, verb, eid, ids[0] if verb == "in" else None, arg)
    assert spy.call_count == 1
    tg_args = spy.call_args.args
    spy.reset_mock()
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        client.post(
            "/d/login", headers=ORIGIN, json={"mobile": "01000000001", "password": "demo1234"}
        )
        if verb == "close":
            client.get("/d/api/" + command)
        else:
            client.post(
                "/d/api/" + command,
                headers=headers(client),
                json=payload | {"evening_id": eid, "idempotency_key": "same-engine-http"},
            )
    assert spy.call_count == 1
    http_args = spy.call_args.args
    # Each adapter opens its own caller-owned transaction; both use the same Engine/Clock.
    if function.endswith("_in_tx"):
        assert tg_args[0].engine is http_args[0].engine is engine
    else:
        assert tg_args[0] is http_args[0] is engine
    key_index = {
        "doctor_on_my_way": 6,
        "who_comes_in_in_tx": 6,
        "undo_last_in_tx": 4,
        "close_evening_in_tx": 5,
        "cancel_tonight_in_tx": 6,
    }.get(function)
    assert tg_args[1:key_index] == http_args[1:key_index]
    if key_index is not None:
        assert tg_args[key_index] == "tg:8"
        assert http_args[key_index] == "engine:same-engine-http"
        assert tg_args[key_index + 1 :] == http_args[key_index + 1 :]
