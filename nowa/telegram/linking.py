import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.core import auth, booking, timing
from nowa.db import conflict_insert, write_tx
from nowa.messaging.outbox import enqueue_message


@dataclass(frozen=True)
class Identity:
    doctor: RowMapping | None
    patient_phones: tuple[str, ...]


def identity(conn: Connection, chat_id: str) -> Identity:
    doctor = (
        conn.execute(
            select(s.doctors)
            .join(s.telegram_links, s.telegram_links.c.phone_e164 == s.doctors.c.mobile_e164)
            .where(
                s.telegram_links.c.kind == "doctor", s.telegram_links.c.telegram_chat_id == chat_id
            )
        )
        .mappings()
        .one_or_none()
    )
    phones: tuple[str, ...] = tuple(
        conn.execute(
            select(s.telegram_links.c.phone_e164)
            .where(
                s.telegram_links.c.telegram_chat_id == chat_id, s.telegram_links.c.kind == "patient"
            )
            .order_by(s.telegram_links.c.phone_e164)
        ).scalars()
    )
    return Identity(doctor, phones)


def used_update(conn: Connection, key: str) -> bool:
    return (
        conn.execute(select(s.idempotency_keys.c.id).where(s.idempotency_keys.c.key == key)).first()
        is not None
    )


def remember(conn: Connection, clock: Clock, cid: int, key: str, command: str) -> None:
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=cid, key=key, command=command, result_json={}, created_at=clock.now(cid)
        )
    )


def _cid(conn: Connection, row: RowMapping) -> int:
    return int(
        row["clinic_id"]
        if row["clinic_id"] is not None
        else conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == "_nowa")).scalar_one()
    )


def _subject(conn: Connection, clock: Clock, row: RowMapping) -> str | None:
    if row["kind"] == "signup_telegram":
        pending = (
            conn.execute(
                select(s.pending_signups).where(s.pending_signups.c.id == row["subject_id"])
            )
            .mappings()
            .first()
        )
        if (
            pending is None
            or pending["completed_at"] is not None
            or pending["expires_at"] <= clock.now(_cid(conn, row))
        ):
            return None
        phone: str = pending["mobile_e164"]
        if conn.execute(select(s.doctors.c.id).where(s.doctors.c.mobile_e164 == phone)).first():
            return None
        return phone
    table = s.contacts if row["kind"] == "patient_telegram" else s.doctors
    column = table.c.phone_e164 if table is s.contacts else table.c.mobile_e164
    return conn.execute(
        select(column).where(table.c.id == row["subject_id"], table.c.clinic_id == row["clinic_id"])
    ).scalar_one_or_none()


def _link(conn: Connection, clock: Clock, row: RowMapping, phone: str, chat_id: str) -> None:
    cid = _cid(conn, row)
    role = "patient" if row["kind"] == "patient_telegram" else "doctor"
    now = clock.now(cid)
    conn.execute(
        conflict_insert(conn, s.telegram_links)
        .values(phone_e164=phone, kind=role, telegram_chat_id=chat_id, linked_at=now)
        .on_conflict_do_update(
            index_elements=[s.telegram_links.c.phone_e164, s.telegram_links.c.kind],
            set_={"telegram_chat_id": chat_id, "linked_at": now},
        )
    )
    conn.execute(s.link_tokens.update().where(s.link_tokens.c.id == row["id"]).values(used_at=now))
    record.write_action(conn, cid, role, "telegram_link")


def consume(engine: Engine, clock: Clock, chat_id: str, payload: str, key: str) -> str:
    if re.fullmatch(r"[dpsr]_[A-Za-z0-9_-]{1,62}", payload) is None:
        return "bad_link"
    kind = {"d": "doctor", "p": "patient", "s": "signup", "r": "reset"}[payload[0]] + "_telegram"
    digest = hashlib.sha256(payload[2:].encode()).hexdigest()
    with write_tx(engine) as conn:
        # Match existing doctor identity serialization, including previously unlinked chats.
        conn.execute(select(s.doctors.c.id).order_by(s.doctors.c.id).with_for_update()).all()
        if used_update(conn, key):
            return "duplicate"
        row = (
            conn.execute(
                select(s.link_tokens).where(s.link_tokens.c.token_hash == digest).with_for_update()
            )
            .mappings()
            .first()
        )
        if (
            row is None
            or row["used_at"] is not None
            or row["expires_at"] <= clock.now(_cid(conn, row))
        ):
            return "bad_link"
        if row["kind"] != kind:
            return "wrong_kind"
        if kind != "patient_telegram" and identity(conn, chat_id).doctor is not None:
            return "already_doctor_chat"
        phone = _subject(conn, clock, row)
        if phone is None:
            return "bad_link"
        claim = (
            conn.execute(
                select(s.telegram_pending)
                .where(s.telegram_pending.c.token_hash == digest)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if claim is not None:
            if claim["attempts"] >= 2:
                return "bad_link"
            # Detach, never delete: reopening a token cannot reset its mismatch budget.
            conn.execute(
                s.telegram_pending.update()
                .where(s.telegram_pending.c.chat_id == chat_id)
                .values(chat_id=None)
            )
            conn.execute(
                s.telegram_pending.update()
                .where(s.telegram_pending.c.token_hash == digest)
                .values(chat_id=chat_id)
            )
            remember(conn, clock, _cid(conn, row), key, "telegram_claim")
            return "share_contact"
        if kind in {"signup_telegram", "reset_telegram"}:
            return "bad_link"
        _link(conn, clock, row, phone, chat_id)
        remember(conn, clock, _cid(conn, row), key, "telegram_link")
    return "linked"


def claim_lang(engine: Engine, chat_id: str) -> str:
    with engine.connect() as conn:
        return (
            conn.execute(
                select(s.telegram_pending.c.lang).where(s.telegram_pending.c.chat_id == chat_id)
            ).scalar_one_or_none()
            or "ar"
        )


def prove_contact(
    engine: Engine,
    clock: Clock,
    chat_id: str,
    sender_id: int | None,
    contact_user_id: int | None,
    raw_phone: str,
    key: str,
) -> str:
    with write_tx(engine) as conn:
        conn.execute(select(s.doctors.c.id).order_by(s.doctors.c.id).with_for_update()).all()
        if used_update(conn, key):
            return "duplicate"
        claim = (
            conn.execute(
                select(s.telegram_pending)
                .where(s.telegram_pending.c.chat_id == chat_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if claim is None:
            return "start_first"
        row = (
            conn.execute(
                select(s.link_tokens)
                .where(s.link_tokens.c.token_hash == claim["token_hash"])
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if (
            row is None
            or row["used_at"] is not None
            or row["expires_at"] <= clock.now(_cid(conn, row))
        ):
            return "bad_link"
        cid = _cid(conn, row)
        now = clock.now(cid)
        phone = _subject(conn, clock, row)
        normalized = booking.normalize_phone(
            "+" + raw_phone if raw_phone.startswith("20") else raw_phone
        )
        if phone is None:
            return "bad_link"
        remember(conn, clock, cid, key, "telegram_contact")
        if sender_id is None or sender_id != contact_user_id or normalized != phone:
            attempts = claim["attempts"] + 1
            conn.execute(
                s.telegram_pending.update()
                .where(s.telegram_pending.c.token_hash == claim["token_hash"])
                .values(attempts=attempts)
            )
            if attempts >= 2:
                conn.execute(
                    s.link_tokens.update()
                    .where(s.link_tokens.c.id == row["id"])
                    .values(used_at=now)
                )
            return "contact_mismatch"
        if row["kind"] != "patient_telegram" and identity(conn, chat_id).doctor is not None:
            return "already_doctor_chat"
        code_row = None
        if row["kind"] in {"signup_telegram", "reset_telegram"}:
            purpose = "signup" if row["kind"] == "signup_telegram" else "reset"
            query = select(s.auth_codes).where(
                s.auth_codes.c.purpose == purpose,
                s.auth_codes.c.phone_key == auth.keyed_hash(phone),
                s.auth_codes.c.used_at.is_(None),
                s.auth_codes.c.attempts < 5,
            )
            if purpose == "signup":
                query = query.where(s.auth_codes.c.pending_signup_id == row["subject_id"])
            code_row = (
                conn.execute(query.order_by(s.auth_codes.c.id.desc()).limit(1).with_for_update())
                .mappings()
                .first()
            )
            if code_row is None:
                return "bad_link"
        _link(conn, clock, row, phone, chat_id)
        conn.execute(
            s.telegram_pending.update()
            .where(s.telegram_pending.c.token_hash == claim["token_hash"])
            .values(chat_id=None)
        )
        if code_row is not None:
            code = f"{secrets.randbelow(1000000):06d}"
            conn.execute(
                s.auth_codes.update()
                .where(s.auth_codes.c.id == code_row["id"])
                .values(code_hash=auth.keyed_hash(code), expires_at=now + timedelta(minutes=10))
            )
            purpose = code_row["purpose"]
            enqueue_message(
                conn,
                clock,
                cid,
                "op:" + purpose + "_code",
                claim["lang"],
                "doctor",
                None,
                {"code": code},
                f"{purpose}_code:{code_row['id']}",
                pending_signup_id=code_row["pending_signup_id"],
            )
            return "code_sent"
        # Deliver the private booking link only now that the phone has been proven.
        rows = (
            conn.execute(
                select(s.bookings).where(
                    s.bookings.c.contact_id == row["subject_id"],
                    s.bookings.c.clinic_id == cid,
                    s.bookings.c.state.in_(("booked", "told_to_leave", "on_my_way")),
                )
            )
            .mappings()
            .all()
        )
        for booked in rows:
            enqueue_message(
                conn,
                clock,
                cid,
                "1",
                booked["lang"],
                "patient",
                booked["id"],
                timing.patient_blanks(conn, booked["id"], "1"),
                f"telegram_confirm:{row['id']}:{booked['id']}",
            )
        return "linked"


def unlink(engine: Engine, clock: Clock, chat_id: str, clinic_id: int, key: str) -> None:
    with write_tx(engine) as conn:
        conn.execute(select(s.doctors.c.id).order_by(s.doctors.c.id).with_for_update()).all()
        if used_update(conn, key):
            return
        conn.execute(
            s.telegram_links.delete().where(
                s.telegram_links.c.telegram_chat_id == chat_id, s.telegram_links.c.kind == "patient"
            )
        )
        remember(conn, clock, clinic_id, key, "telegram_unlink")
        record.write_action(conn, clinic_id, "patient", "telegram_unlink")
