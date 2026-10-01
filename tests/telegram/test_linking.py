from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.db import write_tx
from nowa.telegram import linking
from nowa.web.strings import text
from tests.core.support import setup
from tests.telegram.support import (
    doctor_link,
    message,
    other_doctor,
    patient_link,
    token,
)
from tests.web.support import rows


def test_token_consumed_once_and_replacement_is_kind_scoped(bot, engine):
    router, cid, _, did, clock, ids, fake = bot
    patient_link(bot, engine, update_id=2)
    with engine.connect() as conn:
        contact = conn.execute(
            select(s.bookings.c.contact_id).where(s.bookings.c.id == ids[0])
        ).scalar_one()
        phone = conn.execute(
            select(s.contacts.c.phone_e164).where(s.contacts.c.id == contact)
        ).scalar_one()
    with write_tx(engine) as conn:
        conn.execute(s.doctors.update().where(s.doctors.c.id == did).values(mobile_e164=phone))
    doctor_link(bot, engine, chat=101, update_id=1)
    assert len(rows(engine, s.telegram_links)) == 2
    tid, payload = token(engine, clock, cid, contact, "patient", "replacement-token")
    router.handle_update(message(3, 301, "/start " + payload))
    links = {row["kind"]: row["telegram_chat_id"] for row in rows(engine, s.telegram_links)}
    assert links == {"doctor": "101", "patient": "301"}
    assert all(p.get("chat_id") != "201" for _, p in fake.calls[-3:])
    before = rows(engine, s.action_record)
    router.handle_update(message(3, 301, "/start " + payload))
    assert rows(engine, s.action_record) == before
    router.handle_update(message(4, 401, "/start " + payload))
    assert fake.calls[-1][1]["text"] == text("tg.bad_link", "ar")
    assert next(r for r in rows(engine, s.link_tokens) if r["id"] == tid)["used_at"] is not None
    _, payload = token(engine, clock, cid, did, "doctor", "doctor-replacement")
    router.handle_update(message(5, 501, "/start " + payload))
    assert {r["kind"]: r["telegram_chat_id"] for r in rows(engine, s.telegram_links)} == {
        "doctor": "501",
        "patient": "301",
    }


@pytest.mark.parametrize("role", ["doctor", "patient"])
def test_wrong_kind_keeps_token_unused(bot, engine, role):
    router, cid, _, did, clock, ids, fake = bot
    with engine.connect() as conn:
        subject = (
            did
            if role == "doctor"
            else conn.execute(
                select(s.bookings.c.contact_id).where(s.bookings.c.id == ids[0])
            ).scalar_one()
        )
    tid, payload = token(engine, clock, cid, subject, role)
    payload = ("p_" if role == "doctor" else "d_") + payload[2:]
    router.handle_update(message(1, text="/start " + payload))
    assert rows(engine, s.link_tokens)[0]["id"] == tid
    assert rows(engine, s.link_tokens)[0]["used_at"] is None
    assert rows(engine, s.telegram_links) == []
    assert fake.calls[-1][1]["text"] == text("tg.wrong_kind", "ar")


@pytest.mark.parametrize("same_doctor", [True, False])
def test_second_doctor_link_from_chat_refused(bot, engine, same_doctor):
    router, cid, _, did, clock, _, fake = bot
    doctor_link(bot, engine)
    if not same_doctor:
        cid, did, _ = other_doctor(engine, clock, cid)
    tid, payload = token(engine, clock, cid, did, "doctor", "second-doctor-token")
    before = rows(engine, s.telegram_links)
    router.handle_update(message(2, text="/start " + payload))
    assert rows(engine, s.telegram_links) == before
    assert next(r for r in rows(engine, s.link_tokens) if r["id"] == tid)["used_at"] is None
    assert fake.calls[-1][1]["text"] == text("tg.already_doctor_chat", "ar")


@pytest.mark.parametrize("payload", ["d_bad", "plain-token", "d_" + "a" * 64])
def test_bad_link_fixed_reply(bot, payload):
    router, _, _, _, _, _, fake = bot
    router.handle_update(message(1, text="/start " + payload))
    assert fake.calls == [("sendMessage", {"chat_id": "101", "text": text("tg.bad_link", "ar")})]


def test_expiry_at_exact_instant(bot, engine):
    router, cid, _, did, clock, _, fake = bot
    _, payload = token(engine, clock, cid, did, "doctor")
    clock.advance(minutes=15)
    router.handle_update(message(1, text="/start " + payload))
    assert rows(engine, s.telegram_links) == []
    assert rows(engine, s.link_tokens)[0]["used_at"] is None
    assert fake.calls[-1][1]["text"] == text("tg.bad_link", "ar")


def test_patient_token_on_doctor_mobile_has_no_doctor_identity(bot, engine):
    router, cid, _, did, _, ids, _ = bot
    with write_tx(engine) as conn:
        phone = conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.id == did)
        ).scalar_one()
        contact = conn.execute(
            select(s.bookings.c.contact_id).where(s.bookings.c.id == ids[0])
        ).scalar_one()
        phone = conn.execute(
            select(s.contacts.c.phone_e164).where(s.contacts.c.id == contact)
        ).scalar_one()
        conn.execute(s.doctors.update().where(s.doctors.c.id == did).values(mobile_e164=phone))
    patient_link(bot, engine, chat=101)
    with engine.connect() as conn:
        identity = linking.identity(conn, "101")
    assert identity.doctor is None
    assert identity.patient_phones == (phone,)


@pytest.mark.postgres
def test_concurrent_same_chat_accepts_at_most_one_doctor(postgres_engine):
    engine = postgres_engine
    cid, _, clock, _ = setup(engine, count=1)
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    other, second, _ = other_doctor(engine, clock, cid)
    _, first_payload = token(engine, clock, cid, did, "doctor", "first-token")
    _, second_payload = token(engine, clock, other, second, "doctor", "second-token")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda item: linking.consume(engine, clock, "101", *item),
                [(first_payload, "tg:1"), (second_payload, "tg:2")],
            )
        )
    assert sorted(outcomes) == ["already_doctor_chat", "linked"]
    assert len(rows(engine, s.telegram_links)) == 1
    assert sum(r["used_at"] is not None for r in rows(engine, s.link_tokens)) == 1


@pytest.mark.postgres
def test_concurrent_token_consumption(postgres_engine):
    engine = postgres_engine
    cid, _, clock, _ = setup(engine, count=1)
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    _, payload = token(engine, clock, cid, did, "doctor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda item: linking.consume(engine, clock, str(item), payload, f"tg:{item}"),
                [1, 2],
            )
        )
    assert sorted(outcomes) == ["bad_link", "linked"]
    assert len(rows(engine, s.telegram_links)) == 1
