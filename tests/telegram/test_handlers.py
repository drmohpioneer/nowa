import logging
from datetime import datetime, time
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.clock import CAIRO
from nowa.core import timing
from nowa.db import write_tx
from nowa.telegram import doctor, keyboards
from nowa.telegram.router import Context
from nowa.web.strings import text
from tests.core.support import row
from tests.telegram.support import (
    callback,
    doctor_link,
    inline_data,
    message,
    other_doctor,
    patient_link,
    tap,
)
from tests.web.support import rows


@pytest.mark.parametrize("kind", ["group", "supergroup", "channel"])
def test_non_private_ignored(bot, engine, kind):
    router, _, _, _, _, _, fake = bot
    before = rows(engine, s.action_record)
    router.handle_update(message(1, text="/start d_bad", kind=kind))
    router.handle_update(callback(2, "walkin:1:-:-", kind=kind))
    assert not fake.calls
    assert rows(engine, s.action_record) == before


def test_usage_interactive_has_no_outbox(bot, engine):
    router, _, _, _, clock, _, fake = bot
    before = rows(engine, s.outbox)
    router.handle_update(message(1, text="/start"))
    assert not rows(engine, s.usage)
    doctor_link(bot, engine, update_id=2)
    usage = sum(r["units"] for r in rows(engine, s.usage) if r["service"] == "telegram")
    count = len(fake.calls)
    ctx = Context(engine, clock, fake, 3, "101")
    ctx.refresh()
    ctx.send("menu")
    assert sum(r["units"] for r in rows(engine, s.usage) if r["service"] == "telegram") == usage + 1
    assert len(fake.calls) == count + 1
    assert all(r["est_cost_usd"] == 0 for r in rows(engine, s.usage))
    assert rows(engine, s.outbox) == before


@pytest.mark.parametrize(
    "value",
    [
        "cancel booking 7",
        "pasted-link-code",
        "حجوزاتي ",
        "وقف الرسايل هنا ",
        "🚗 في الطريق",
        "اختار المنطقة",
    ],
)
def test_patient_free_text_never_acts(bot, engine, value, monkeypatch):
    router, _, _, _, _, _, fake = bot
    patient_link(bot, engine, chat=101)
    fake.clear()
    before = rows(engine, s.bookings), rows(engine, s.telegram_links)
    spies = [Mock() for _ in range(3)]
    for name, spy in zip(
        ("patient_on_my_way_in_tx", "cancel_tonight_in_tx", "doctor_on_my_way"), spies
    ):
        monkeypatch.setattr(timing, name, spy)
    router.handle_update(message(9, text=value))
    assert (rows(engine, s.bookings), rows(engine, s.telegram_links)) == before
    assert any(p.get("reply_markup", {}).get("keyboard") for _, p in fake.calls)
    for spy in spies:
        spy.assert_not_called()


def test_patient_booking_isolation_and_buttons(bot, engine):
    router, _, _, _, _, ids, fake = bot
    with write_tx(engine) as conn:
        for i, bid in enumerate(ids):
            patient_id = conn.execute(
                select(s.bookings.c.patient_id).where(s.bookings.c.id == bid)
            ).scalar_one()
            conn.execute(
                s.patients.update()
                .where(s.patients.c.id == patient_id)
                .values(name=f"Patient{i} Fictional")
            )
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="told_to_leave")
        )
    patient_link(bot, engine, index=0, chat=201, update_id=1)
    patient_link(bot, engine, index=1, chat=202, update_id=2)
    patient_link(bot, engine, index=2, chat=201, update_id=3)
    fake.clear()
    router.handle_update(message(4, 201, "حجوزاتي"))
    output = " ".join(p.get("text", "") for _, p in fake.calls)
    assert "Patient0" in output and "Patient2" in output and "Patient1" not in output
    assert f"omw:-:{ids[0]}:-" in inline_data(fake)
    tap(router, 5, "omw", bid=ids[0], chat=202)
    assert row(engine, s.bookings, ids[0])["state"] == "told_to_leave"
    tap(router, 6, "omw", bid=ids[0], chat=201)
    assert row(engine, s.bookings, ids[0])["state"] == "on_my_way"
    assert f"undo:-:{ids[0]}:-" in inline_data(fake)
    at = row(engine, s.bookings, ids[0])["on_my_way_at"]
    tap(router, 6, "omw", bid=ids[0], chat=201)
    assert row(engine, s.bookings, ids[0])["on_my_way_at"] == at
    tap(router, 7, "undo", bid=ids[0], chat=201)
    assert row(engine, s.bookings, ids[0])["state"] == "told_to_leave"


def test_overnight_list_and_doctor_callback_at_0030(bot, engine):
    router, cid, eid, _, clock, ids, fake = bot
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(19), end=time(1)))
    doctor_link(bot, engine)
    patient_link(bot, engine, update_id=2)
    target = datetime(2026, 10, 7, 0, 30, tzinfo=CAIRO)
    clock.advance(minutes=(target - clock.now(cid)).total_seconds() / 60)
    fake.clear()
    router.handle_update(message(3, 201, "حجوزاتي"))
    assert any("Tue 6/10" in p.get("text", "") for _, p in fake.calls)
    tap(router, 4, "in", eid, ids[0])
    assert row(engine, s.bookings, ids[0])["state"] == "seen"
    clock.advance(minutes=31)
    fake.clear()
    router.handle_update(message(5, 201, "حجوزاتي"))
    assert not any("Tue 6/10" in p.get("text", "") for _, p in fake.calls)


@pytest.mark.parametrize("state", ["closed", "cancelled"])
def test_closed_evening_not_listed(bot, engine, state):
    router, _, eid, _, _, _, fake = bot
    patient_link(bot, engine)
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state=state))
    fake.clear()
    router.handle_update(message(3, 201, "حجوزاتي"))
    assert len(fake.calls) == 1
    assert fake.calls[0][1]["text"] == text("tg.no_bookings", "ar")


@pytest.mark.parametrize(
    "verb,eid_field,bid_field,arg",
    [
        ("omw", True, False, "-"),
        ("area", True, False, "1"),
        ("in", True, True, "-"),
        ("walkin", True, False, "-"),
        ("undo", True, False, "-"),
        ("more", True, False, "-"),
        ("close", True, False, "-"),
        ("closeok", True, False, "0"),
        ("cancel", True, False, "-"),
        ("cancelok", True, False, "a" * 32),
    ],
)
def test_patient_only_doctor_mobile_cannot_use_doctor_callbacks(
    bot, engine, monkeypatch, verb, eid_field, bid_field, arg
):
    router, _, eid, did, _, ids, _ = bot
    with write_tx(engine) as conn:
        phone = conn.execute(
            select(s.contacts.c.phone_e164)
            .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
            .where(s.bookings.c.id == ids[0])
        ).scalar_one()
        conn.execute(s.doctors.update().where(s.doctors.c.id == did).values(mobile_e164=phone))
    patient_link(bot, engine, chat=101)
    spies = []
    for name in (
        "doctor_on_my_way",
        "who_comes_in_in_tx",
        "undo_last_in_tx",
        "close_preview",
        "close_evening_in_tx",
        "request_cancel_tonight",
        "cancel_tonight_in_tx",
    ):
        spy = Mock()
        monkeypatch.setattr(timing, name, spy)
        spies.append(spy)
    before = rows(engine, s.bookings), rows(engine, s.evenings)
    tap(router, 3, verb, eid if eid_field else None, ids[0] if bid_field else None, arg)
    assert (rows(engine, s.bookings), rows(engine, s.evenings)) == before
    for spy in spies:
        spy.assert_not_called()


@pytest.mark.parametrize(
    "verb,arg",
    [
        ("omw", "-"),
        ("area", "1"),
        ("in", "-"),
        ("walkin", "-"),
        ("undo", "-"),
        ("more", "-"),
        ("close", "-"),
        ("closeok", "0"),
        ("cancel", "-"),
        ("cancelok", "a" * 32),
    ],
)
def test_foreign_evening_refused(bot, engine, monkeypatch, verb, arg):
    router, cid, _, _, clock, ids, _ = bot
    doctor_link(bot, engine)
    _, _, foreign = other_doctor(engine, clock, cid)
    spy = Mock()
    monkeypatch.setattr(doctor, "prompt", spy)
    before = rows(engine, s.bookings), rows(engine, s.evenings), rows(engine, s.evening_taps)
    tap(router, 3, verb, foreign, ids[0] if verb == "in" else None, arg)
    assert (
        rows(engine, s.bookings),
        rows(engine, s.evenings),
        rows(engine, s.evening_taps),
    ) == before
    spy.assert_not_called()


def test_yesterday_board_and_foreign_booking_refused(bot, engine):
    router, cid, eid, _, clock, ids, _ = bot
    doctor_link(bot, engine)
    _, _, foreign = other_doctor(engine, clock, cid)
    with write_tx(engine) as conn:
        # A valid booking identifier belonging to the other evening.
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(evening_id=foreign)
        )
    tap(router, 3, "in", eid, ids[0])
    assert row(engine, s.bookings, ids[0])["state"] == "booked"
    clock.advance(minutes=24 * 60)
    tap(router, 4, "walkin", eid)
    assert not rows(engine, s.visits)


def test_doctor_keyboard_exact_text_and_no_free_text_action(bot, engine, monkeypatch):
    router, _, _, _, _, _, fake = bot
    doctor_link(bot, engine)
    spy = Mock(wraps=doctor.prompt)
    monkeypatch.setattr(doctor, "prompt", spy)
    router.handle_update(message(2, text="🚗 في الطريق "))
    spy.assert_not_called()
    router.handle_update(message(3, text="🚗 في الطريق"))
    spy.assert_called_once()
    assert any(p.get("reply_markup", {}).get("one_time_keyboard") for _, p in fake.calls)
    before = rows(engine, s.evening_taps)
    router.handle_update(message(4, text="cancel tonight"))
    assert rows(engine, s.evening_taps) == before


def test_mixed_role_menu_and_unlink_keeps_doctor(bot, engine):
    router, _, eid, _, _, ids, fake = bot
    doctor_link(bot, engine)
    patient_link(bot, engine, chat=101)
    fake.clear()
    router.handle_update(message(3, text="حجوزاتي"))
    assert "tgmenu:-:-:-" in inline_data(fake)
    assert not any("Tue 6/10" in p.get("text", "") for _, p in fake.calls)
    tap(router, 4, "tgmenu")
    assert any("Tue 6/10" in p.get("text", "") for _, p in fake.calls)
    assert not any(
        p.get("reply_markup", {}).get("keyboard") == keyboards.patient_menu("en")["keyboard"]
        for _, p in fake.calls
    )
    tap(router, 5, "unlink")
    assert "unlinkok:-:-:-" in inline_data(fake)
    tap(router, 6, "unlinkok")
    assert {r["kind"] for r in rows(engine, s.telegram_links)} == {"doctor"}
    tap(router, 7, "in", eid, ids[0])
    assert row(engine, s.bookings, ids[0])["state"] == "seen"


def test_unlink_text_requires_exact_match_and_confirmation(bot, engine):
    router, _, _, _, _, _, fake = bot
    patient_link(bot, engine)
    patient_link(bot, engine, index=1, update_id=3)
    assert len(rows(engine, s.telegram_links)) == 2
    router.handle_update(message(4, 201, "وقف الرسايل هنا "))
    assert len(rows(engine, s.telegram_links)) == 2
    router.handle_update(message(5, 201, "وقف الرسايل هنا"))
    assert len(rows(engine, s.telegram_links)) == 2
    assert "unlinkok:-:-:-" in inline_data(fake)
    tap(router, 6, "unlinkok", chat=201)
    assert not rows(engine, s.telegram_links)


@pytest.mark.parametrize("data", ["forged", "walkin:1:-:" + "1" * 70, "qsave:1:-:1"])
def test_bad_callback_no_engine_effect(bot, engine, data):
    router, _, _, _, _, _, _ = bot
    doctor_link(bot, engine)
    before = rows(engine, s.bookings), rows(engine, s.evening_taps)
    router.handle_update(callback(3, data))
    assert (rows(engine, s.bookings), rows(engine, s.evening_taps)) == before


def test_privacy_after_link_location_and_text(bot, engine, caplog):
    router, cid, eid, did, clock, _, _ = bot
    from tests.telegram.support import token

    plaintext = "plaintext-token-for-privacy-scan"
    _, payload = token(engine, clock, cid, did, "doctor", plaintext)
    caplog.set_level(logging.INFO, logger="nowa.telegram.router")
    router.handle_update(message(1, text="/start " + payload))
    lat, lng = 30.123456789, 31.987654321
    router.handle_update(message(2, location={"latitude": lat, "longitude": lng}))
    router.handle_update(message(3, text="patient-private-text +201234567899"))
    excluded = {
        "patients",
        "contacts",
        "doctors",
        "telegram_links",
        "link_tokens",
        "clinics",
        "areas",
    }
    dump = " ".join(
        str(rows(engine, table)) for table in s.metadata.sorted_tables if table.name not in excluded
    )
    for value in (plaintext, str(lat), str(lng), "patient-private-text", "+201234567899"):
        assert value not in dump
        assert value not in caplog.text
    assert row(engine, s.evenings, eid)["state"] == "doctor_on_way"
    # Other location messages have no timing effect and locations from patients never act.
    before = rows(engine, s.evening_taps)
    router.handle_update(message(4, location={"latitude": lat, "longitude": lng}))
    assert rows(engine, s.evening_taps) == before


def test_accepted_updates_cannot_act_again(bot, engine):
    router, _, eid, _, _, ids, _ = bot
    doctor_link(bot, engine)
    tap(router, 3, "in", eid, ids[0])
    before = rows(engine, s.evening_taps), rows(engine, s.bookings)
    tap(router, 3, "in", eid, ids[0])
    assert (rows(engine, s.evening_taps), rows(engine, s.bookings)) == before
    tap(router, 4, "walkin", eid)
    before = rows(engine, s.bookings)
    tap(router, 4, "walkin", eid)
    assert rows(engine, s.bookings) == before


@pytest.mark.parametrize("reason", ["already_seen", "changed_since", "evening_closed"])
def test_refused_doctor_replay_keeps_reply_and_board(bot, engine, monkeypatch, reason):
    router, _, eid, _, _, ids, fake = bot
    doctor_link(bot, engine)
    tap(router, 3, "in", eid, ids[0])
    board = next(payload for method, payload in fake.calls if method == "editMessageText")
    verb = "in" if reason == "already_seen" else "undo"
    function = "who_comes_in_in_tx" if verb == "in" else "undo_last_in_tx"
    with write_tx(engine) as conn:
        if reason == "changed_since":
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled")
            )
        elif reason == "evening_closed":
            conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="closed"))
    spy = Mock(wraps=getattr(timing, function))
    monkeypatch.setattr(timing, function, spy)
    before = rows(engine, s.bookings), rows(engine, s.evening_taps)
    replies = []
    for _ in range(2):
        fake.clear()
        tap(router, 4, verb, eid, ids[0] if verb == "in" else None)
        assert fake.calls == [
            ("sendMessage", {"chat_id": "101", "text": text("tg.refused", "ar")}),
            ("answerCallbackQuery", {"callback_query_id": "query-4"}),
        ]
        replies.append(list(fake.calls))
        # No edit means the displayed board, including its buttons, stays as it was.
        assert board["text"] == text("tg.board", "ar")
        assert board["reply_markup"]["inline_keyboard"]
    assert replies[0] == replies[1]
    assert spy.call_count == 2
    assert (rows(engine, s.bookings), rows(engine, s.evening_taps)) == before
    assert not any(r["key"] == "tg:4:handled" for r in rows(engine, s.idempotency_keys))


def test_refused_patient_replay_keeps_reply_and_buttons(bot, engine, monkeypatch):
    router, _, eid, _, _, ids, fake = bot
    with write_tx(engine) as conn:
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="told_to_leave")
        )
    patient_link(bot, engine)
    buttons = next(p["reply_markup"] for _, p in fake.calls if f"omw:-:{ids[0]}:-" in str(p))
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="closed"))
    spy = Mock(wraps=timing.patient_on_my_way_in_tx)
    monkeypatch.setattr(timing, "patient_on_my_way_in_tx", spy)
    before = rows(engine, s.bookings)
    for _ in range(2):
        fake.clear()
        tap(router, 4, "omw", bid=ids[0], chat=201)
        assert fake.calls == [
            ("sendMessage", {"chat_id": "201", "text": text("tg.refused", "ar")}),
            ("answerCallbackQuery", {"callback_query_id": "query-4"}),
        ]
        assert f"omw:-:{ids[0]}:-" in str(buttons)
    assert spy.call_count == 2
    assert rows(engine, s.bookings) == before
    assert not any(r["key"] == "tg:4:handled" for r in rows(engine, s.idempotency_keys))
