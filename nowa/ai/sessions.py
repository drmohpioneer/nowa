import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.triage.registry import APPROVED_SPECIALTIES


def keyed(value: str) -> str:
    return hmac.new(
        get_settings().server_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def session_hash(key: str) -> str:
    return keyed("session|" + key)


def load_clinic(conn: Connection, clinic_id: int) -> dict[str, Any]:
    row = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().first()
    if row is None:
        raise HTTPException(404)
    if row["specialty"] not in APPROVED_SPECIALTIES:
        raise HTTPException(503)
    return dict(row)


def public_phones(conn: Connection, clinic: Mapping[str, Any]) -> tuple[str, ...]:
    numbers = [clinic["phone"]]
    numbers.extend(
        conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == clinic["id"])
        ).scalars()
    )
    return tuple(numbers + ["0" + number[3:] for number in numbers if number.startswith("+20")])


def load_session(conn: Connection, clinic_id: int, key: str) -> dict[str, Any]:
    row = (
        conn.execute(
            select(s.chat_sessions)
            .where(
                s.chat_sessions.c.clinic_id == clinic_id,
                s.chat_sessions.c.session_key_hash == session_hash(key),
            )
            .with_for_update()
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404)
    return dict(row)


def create_session(engine: Engine, clock: Clock, clinic_id: int) -> str:
    key = secrets.token_urlsafe(32)
    with write_tx(engine) as conn:
        load_clinic(conn, clinic_id)
        conn.execute(
            s.chat_sessions.insert().values(
                clinic_id=clinic_id,
                session_key_hash=session_hash(key),
                lang="ar",
                state="open",
                created_at=clock.now(clinic_id),
            )
        )
    return key


def update_session(conn: Connection, session: dict[str, Any], **values: Any) -> None:
    conn.execute(
        s.chat_sessions.update().where(s.chat_sessions.c.id == session["id"]).values(**values)
    )
    session.update(values)


def prompt_clinic(conn: Connection, clock: Clock, clinic: Mapping[str, Any]) -> dict[str, Any]:
    doctor = (
        conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == clinic["id"]))
        .mappings()
        .one()
    )
    info = conn.execute(
        select(s.clinic_info.c.key, s.clinic_info.c.text)
        .where(s.clinic_info.c.clinic_id == clinic["id"])
        .order_by(s.clinic_info.c.key)
    ).all()
    return dict(
        specialty=clinic["specialty"],
        doctor_name={"ar": doctor["name_ar"], "en": doctor["name_en"]},
        clinic_info={row.key: row.text for row in info},
        today=clock.now(clinic["id"]).date().isoformat(),
    )
