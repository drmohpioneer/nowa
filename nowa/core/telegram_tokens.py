"""One-time Telegram tokens. Public issuance creates a durable, unproven claim."""

import hashlib
import re
import secrets
from datetime import timedelta
from typing import Any

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


def link_digest(url: str) -> str:
    """Accept only a claim for our configured bot; never fetch user-supplied URLs."""
    username = get_settings().telegram_bot_username
    pattern = rf"https://t\.me/{re.escape(username)}\?start=([psrd])_([A-Za-z0-9_-]{{43}})"
    match = re.fullmatch(pattern, url) if username else None
    if match is None:
        raise ValueError("Invalid Telegram link")
    return hashlib.sha256(match[2].encode()).hexdigest()


def link_status(conn: Connection, clock: Clock, url: str) -> dict[str, Any]:
    digest = link_digest(url)
    row = (
        conn.execute(
            select(s.link_tokens, s.telegram_pending.c.attempts)
            .outerjoin(
                s.telegram_pending, s.telegram_pending.c.token_hash == s.link_tokens.c.token_hash
            )
            .where(s.link_tokens.c.token_hash == digest)
        )
        .mappings()
        .first()
    )
    # Registration deliberately returns an unusable, indistinguishable link for
    # an already registered number. Do not reveal registration through polling.
    if row is None:
        return {"status": "pending", "remaining_seconds": 900, "usable": True}
    cid = row["clinic_id"]
    if cid is None:
        cid = conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == "_nowa")).scalar_one()
    remaining = max(0.0, (row["expires_at"] - clock.now(cid, conn=conn)).total_seconds())
    attempts = row["attempts"] or 0
    if row["used_at"] is not None and attempts < 2:
        state = "linked"
    elif remaining == 0:
        state = "expired"
    elif attempts:
        state = "contact_mismatch"
    else:
        state = "pending"
    return {
        "status": state,
        "remaining_seconds": remaining,
        "usable": row["used_at"] is None and remaining > 0,
    }
