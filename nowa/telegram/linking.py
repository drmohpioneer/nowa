import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.db import conflict_insert, write_tx


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


def consume(engine: Engine, clock: Clock, chat_id: str, payload: str, key: str) -> str:
    if re.fullmatch(r"[dp]_[A-Za-z0-9_-]{1,62}", payload) is None:
        return "bad_link"
    role = "doctor" if payload[0] == "d" else "patient"
    digest = hashlib.sha256(payload[2:].encode()).hexdigest()
    with write_tx(engine) as conn:
        # Serialize link changes against each other, including a chat's first doctor link.
        # Locking identity rows in a stable order needs no new bot-state table.
        conn.execute(select(s.doctors.c.id).order_by(s.doctors.c.id).with_for_update()).all()
        if used_update(conn, key):
            return "linked"
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
            or row["expires_at"] <= clock.now(row["clinic_id"])
        ):
            return "bad_link"
        if row["kind"] != role + "_telegram":
            return "wrong_kind"
        if role == "doctor" and identity(conn, chat_id).doctor is not None:
            return "already_doctor_chat"
        table = s.doctors if role == "doctor" else s.contacts
        phone_column = table.c.mobile_e164 if role == "doctor" else table.c.phone_e164
        phone = conn.execute(
            select(phone_column).where(
                table.c.id == row["subject_id"], table.c.clinic_id == row["clinic_id"]
            )
        ).scalar_one_or_none()
        if phone is None:
            return "bad_link"
        now = clock.now(row["clinic_id"])
        conn.execute(
            conflict_insert(conn, s.telegram_links)
            .values(phone_e164=phone, kind=role, telegram_chat_id=chat_id, linked_at=now)
            .on_conflict_do_update(
                index_elements=[s.telegram_links.c.phone_e164, s.telegram_links.c.kind],
                set_={"telegram_chat_id": chat_id, "linked_at": now},
            )
        )
        conn.execute(
            s.link_tokens.update().where(s.link_tokens.c.id == row["id"]).values(used_at=now)
        )
        remember(conn, clock, row["clinic_id"], key, "telegram_link")
        record.write_action(conn, row["clinic_id"], role, "telegram_link")
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
