"""Slice 15: a browser token is a claim; only the user's own contact grants authority."""

import hashlib
import re

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import auth, signup, telegram_tokens, timing
from nowa.db import write_tx
from nowa.messaging.outbox import enqueue_message
from nowa.telegram import linking
from nowa.telegram.router import Router
from tests.telegram.support import contact, message, payload
from tests.web.support import rows


def patient_claim(bot, engine):
    _, cid, _, _, clock, ids, _ = bot
    get_settings().telegram_bot_username = "fictional_bot"
    with write_tx(engine) as conn:
        bid = ids[0]
        url = telegram_tokens.booking_url(conn, clock, bid)
        phone = conn.execute(
            select(s.contacts.c.phone_e164)
            .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
            .where(s.bookings.c.id == bid)
        ).scalar_one()
    return payload(url), phone


def test_claim_restart_matching_contact_and_next_leave_now(bot, engine):
    router, cid, _, _, clock, ids, fake = bot
    claim, phone = patient_claim(bot, engine)
    router.handle_update(message(100, 701, "/start " + claim))
    assert rows(engine, s.telegram_links) == []
    assert fake.calls[-1][1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True
    stored = rows(engine, s.link_tokens)[0]
    assert stored["token_hash"] == hashlib.sha256(claim[2:].encode()).hexdigest()
    assert claim[2:] not in str(stored)
    assert rows(engine, s.telegram_pending)[0]["chat_id"] == "701"
    before = list(fake.calls)
    router.handle_update(message(100, 701, "/start " + claim))
    assert fake.calls == before
    # Recreate the router and reconnect: no process state participates in proof.
    engine.dispose()
    router = Router(engine, clock, fake)
    router.handle_update(contact(101, 701, phone.lstrip("+")))
    assert rows(engine, s.telegram_links)[0]["telegram_chat_id"] == "701"
    assert rows(engine, s.link_tokens)[0]["used_at"] is not None
    assert any(p.get("reply_markup", {}).get("remove_keyboard") for _, p in fake.calls)
    confirmation = [
        r for r in rows(engine, s.outbox) if r["idempotency_key"].startswith("telegram_confirm:")
    ]
    assert len(confirmation) == 1 and "/l/" in confirmation[0]["body"]
    assert confirmation[0]["adapter"] == "telegram"
    before = (rows(engine, s.outbox), list(fake.calls))
    router.handle_update(contact(101, 701, phone))
    assert (rows(engine, s.outbox), fake.calls) == before
    with write_tx(engine) as conn:
        oid = enqueue_message(
            conn,
            clock,
            cid,
            "2",
            "en",
            "patient",
            ids[0],
            timing.patient_blanks(conn, ids[0], "2"),
            "contact-leave-now",
        )
    assert next(r for r in rows(engine, s.outbox) if r["id"] == oid)["adapter"] == "telegram"
    router.handle_update(message(102, 702, "/start " + claim))
    assert rows(engine, s.telegram_links)[0]["telegram_chat_id"] == "701"


@pytest.mark.parametrize("forwarded", [False, True])
def test_mismatch_budget_survives_restart_and_other_chats(bot, engine, forwarded):
    router, _, _, _, clock, _, fake = bot
    claim, phone = patient_claim(bot, engine)
    router.handle_update(message(200, 701, "/start " + claim))
    bad = contact(201, 701, phone if forwarded else "+201000000777", user=999 if forwarded else 701)
    router.handle_update(bad)
    assert rows(engine, s.telegram_links) == []
    assert rows(engine, s.telegram_pending)[0]["attempts"] == 1
    assert rows(engine, s.link_tokens)[0]["used_at"] is None
    router.handle_update(bad)
    assert rows(engine, s.telegram_pending)[0]["attempts"] == 1
    router = Router(engine, clock, fake)
    router.handle_update(message(202, 702, "/start " + claim))
    router.handle_update(contact(203, 702, "+201000000777"))
    assert rows(engine, s.telegram_pending)[0]["attempts"] == 2
    assert rows(engine, s.link_tokens)[0]["used_at"] is not None
    router.handle_update(contact(204, 702, phone))
    assert rows(engine, s.telegram_links) == []


def test_switching_to_another_token_does_not_reset_attempts(bot, engine):
    router, _, _, _, _, _, _ = bot
    first, phone = patient_claim(bot, engine)
    second, _ = patient_claim(bot, engine)
    router.handle_update(message(210, 701, "/start " + first))
    router.handle_update(contact(211, 701, "+201000000777"))
    router.handle_update(message(212, 701, "/start " + second))
    router.handle_update(message(213, 701, "/start " + first))
    router.handle_update(contact(214, 701, "+201000000777"))
    router.handle_update(contact(215, 701, phone))
    assert rows(engine, s.telegram_links) == []
    digest = hashlib.sha256(first[2:].encode()).hexdigest()
    claim = next(r for r in rows(engine, s.telegram_pending) if r["token_hash"] == digest)
    assert claim["attempts"] == 2


@pytest.mark.parametrize(
    "mode",
    ["expired_start", "expired_contact", "wrong_kind", "malformed", "no_claim", "missing_user"],
)
def test_adversarial_claims(bot, engine, mode):
    router, _, _, _, clock, _, _ = bot
    claim, phone = patient_claim(bot, engine)
    if mode == "expired_start":
        clock.advance(minutes=15)
    if mode == "wrong_kind":
        claim = "s_" + claim[2:]
    if mode == "malformed":
        claim = "p_!invalid"
    if mode != "no_claim":
        router.handle_update(message(300, 701, "/start " + claim))
    if mode == "expired_contact":
        clock.advance(minutes=15)
    update = contact(301, 701, phone)
    if mode == "missing_user":
        del update["message"]["contact"]["user_id"]
    router.handle_update(update)
    assert rows(engine, s.telegram_links) == []


def test_signup_claim_code_verify_complete_and_registered_refusal(bot, engine):
    router, _, _, did, clock, _, fake = bot
    get_settings().telegram_bot_username = "fictional_bot"
    phone = "+201000004444"
    agreement = signup.load_agreement()
    requested = signup.request_code(engine, clock, agreement, phone, "signup-ip", "en")
    assert requested.telegram_url and requested.cookie is None
    assert not [r for r in rows(engine, s.outbox) if r["template_id"] == "op:signup_code"]
    token_row = rows(engine, s.link_tokens)[0]
    assert token_row["kind"] == "signup_telegram" and token_row["clinic_id"] is None
    router.handle_update(message(400, 701, "/start " + payload(requested.telegram_url)))
    assert not rows(engine, s.telegram_links)
    # A patient cannot use someone else's s_ token and a self-contact for another number.
    router.handle_update(contact(401, 701, "+201000000777"))
    assert not rows(engine, s.telegram_links)
    router.handle_update(contact(402, 701, phone))
    code_msg = next(r for r in rows(engine, s.outbox) if r["template_id"] == "op:signup_code")
    assert code_msg["channel"] == code_msg["adapter"] == "telegram" and code_msg["lang"] == "en"
    code = re.search(r"\b[0-9]{6}\b", code_msg["body"])[0]
    verified = signup.verify_code(engine, clock, phone, code)
    assert verified and signup.verify_code(engine, clock, phone, code) is None
    result = signup.complete(
        engine,
        clock,
        agreement,
        {
            "signup_token": verified,
            "mobile": phone,
            "name_ar": "طبيب تجريبي",
            "name_en": "Fictional Doctor",
            "specialty": "cardiology",
            "address": "Fictional address",
            "pin_kind": "area",
            "area_id": 1,
            "price_egp": 100,
            "password": "fictional-password",
            "agree": True,
            "agreement_version": agreement.version,
            "idempotency_key": "contact-signup-complete",
            "hours": [{"weekday": 1, "start": "19:00", "end": "23:00"}],
        },
    )
    assert result.data["slug"] == "dr-fictional-doctor"
    assert not rows(engine, s.pending_signups) and not rows(engine, s.link_tokens)
    with engine.connect() as conn:
        assert linking.identity(conn, "701").doctor is not None
    old_links = rows(engine, s.telegram_links)
    refused = signup.request_code(engine, clock, agreement, phone, "other-ip", "ar")
    assert refused.allowed and refused.telegram_url and not rows(engine, s.pending_signups)
    router.handle_update(message(403, 702, "/start " + payload(refused.telegram_url)))
    router.handle_update(contact(404, 702, phone))
    assert rows(engine, s.telegram_links) == old_links


@pytest.mark.parametrize("linked", [False, True])
def test_reset_linked_or_contact_proven(bot, engine, linked):
    router, cid, _, did, clock, _, _ = bot
    get_settings().telegram_bot_username = "fictional_bot"
    doctor = next(r for r in rows(engine, s.doctors) if r["id"] == did)
    phone = doctor["mobile_e164"]
    if linked:
        with write_tx(engine) as conn:
            conn.execute(
                s.telegram_links.insert().values(
                    phone_e164=phone,
                    kind="doctor",
                    telegram_chat_id="701",
                    linked_at=clock.now(cid),
                )
            )
    requested = auth.request_reset(engine, clock, phone, "reset-ip")
    assert requested.allowed
    if linked:
        assert requested.telegram_url is None
    else:
        assert requested.telegram_url
        assert not [r for r in rows(engine, s.outbox) if r["template_id"] == "op:reset_code"]
        router.handle_update(message(500, 701, "/start " + payload(requested.telegram_url)))
        assert not rows(engine, s.telegram_links)
        router.handle_update(contact(501, 701, phone))
    messages = [r for r in rows(engine, s.outbox) if r["template_id"] == "op:reset_code"]
    assert len(messages) == 1 and messages[0]["adapter"] == "telegram"
    code = re.search(r"\b[0-9]{6}\b", messages[0]["body"])[0]
    assert auth.confirm_reset(engine, clock, phone, code, "changed-password")
    assert (
        next(r for r in rows(engine, s.outbox) if r["id"] == messages[0]["id"])["body"]
        == "[redacted]"
    )


def test_new_reset_invalidates_old_claim_and_rate_limits_survive(bot, engine):
    router, _, _, did, clock, _, _ = bot
    get_settings().telegram_bot_username = "fictional_bot"
    phone = next(r for r in rows(engine, s.doctors) if r["id"] == did)["mobile_e164"]
    requests = [auth.request_reset(engine, clock, phone, "ip") for _ in range(3)]
    assert auth.request_reset(engine, clock, phone, "ip").telegram_url is None
    assert len(rows(engine, s.auth_codes)) == 3
    router.handle_update(message(510, 701, "/start " + payload(requests[0].telegram_url)))
    router.handle_update(contact(511, 701, phone))
    assert not rows(engine, s.telegram_links)
    router.handle_update(message(512, 701, "/start " + payload(requests[-1].telegram_url)))
    router.handle_update(contact(513, 701, phone))
    assert len(rows(engine, s.telegram_links)) == 1
