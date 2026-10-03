"""One-time Telegram tokens. Public issuance creates a durable, unproven claim."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings

PREFIX = {
    "patient_telegram": "p",
    "doctor_telegram": "d",
    "signup_telegram": "s",
    "reset_telegram": "r",
}


def mint(
    conn: Connection,
    clock: Clock,
    clinic_id: int | None,
    kind: str,
    subject_id: int,
    *,
    contact_proof: bool = True,
    lang: str = "ar",
) -> tuple[int, str]:
    now_cid = (
        clinic_id
        if clinic_id is not None
        else int(
            conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == "_nowa")).scalar_one()
        )
    )
    now = clock.now(now_cid, conn=conn)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    tid = int(
        conn.execute(
            s.link_tokens.insert()
            .values(
                clinic_id=clinic_id,
                kind=kind,
                subject_id=subject_id,
                token_hash=digest,
                expires_at=now + timedelta(minutes=15),
            )
            .returning(s.link_tokens.c.id)
        ).scalar_one()
    )
    if contact_proof:
        conn.execute(
            s.telegram_pending.insert().values(
                token_hash=digest,
                created_at=now,
                lang=lang,
            )
        )
    return tid, f"https://t.me/{get_settings().telegram_bot_username}?start={PREFIX[kind]}_{token}"


def booking_url(conn: Connection, clock: Clock, booking_id: int) -> str | None:
    if not get_settings().telegram_bot_username:
        return None
    row = conn.execute(select(s.bookings).where(s.bookings.c.id == booking_id)).mappings().one()
    _, url = mint(
        conn, clock, row["clinic_id"], "patient_telegram", row["contact_id"], lang=row["lang"]
    )
    return url


def delete_signup_tokens(conn: Connection, pending_id: int) -> None:
    """Delete credentials before a pending id can be reused by SQLite."""
    where = (s.link_tokens.c.kind == "signup_telegram", s.link_tokens.c.subject_id == pending_id)
    hashes = select(s.link_tokens.c.token_hash).where(*where)
    conn.execute(s.telegram_pending.delete().where(s.telegram_pending.c.token_hash.in_(hashes)))
    conn.execute(s.link_tokens.delete().where(*where))
