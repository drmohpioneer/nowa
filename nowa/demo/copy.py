"""Provision isolated fictional clinics; lifecycle deletion is handled at sign-up expiry."""

import secrets
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.core import auth, booking, ratelimit, signup, signup_handlers
from nowa.core.timers import TimerContext, schedule_timer
from nowa.db import write_tx
from nowa.demo.template import CLINIC

Kind = Literal["watch", "public"]


class Busy(Exception):
    pass


def _evict(conn: Connection, clock: Clock, system: int) -> None:
    cid = conn.execute(
        select(s.clinics.c.id)
        .where(s.clinics.c.slug.startswith("demo-"), s.clinics.c.is_sandbox.is_(True))
        .order_by(s.clinics.c.created_at, s.clinics.c.id)
        .limit(1)
    ).scalar_one_or_none()
    if cid is None:
        raise Busy("busy, try again later")
    now = clock.now(system, conn=conn)
    signup_handlers.sandbox_expire(
        TimerContext(conn, clock, system, 0, "sandbox_expire", now, 1, now), {"clinic_id": cid}
    )


def create_demo_copy_in_tx(
    conn: Connection, clock: Clock, kind: Kind, client_ip: str
) -> int | None:
    if kind not in ("watch", "public"):
        raise ValueError("Invalid demo kind")
    booking._advisory_lock(conn, "clinics")
    if not ratelimit.hit(conn, clock, "demo_copy_ip", client_ip, 3600, 30):
        return None  # Caller commits the rate counter even on refusal.
    system = signup.system_id(conn)
    copies = conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug.startswith("demo-"))).all()
    if len(copies) >= 200:
        _evict(conn, clock, system)
    now = clock.now(system, conn=conn)
    expires = now + timedelta(hours=24 if kind == "watch" else 2)
    cid: int = conn.execute(
        s.clinics.insert()
        .values(
            **(
                CLINIC["clinic"]
                | {
                    "slug": "demo-" + secrets.token_hex(16),
                    "is_sandbox": True,
                    "created_at": now,
                    "sandbox_expires_at": expires,
                }
            )
        )
        .returning(s.clinics.c.id)
    ).scalar_one()
    password = auth.hash_password(secrets.token_urlsafe(32))
    for _ in range(1001):
        used: set[str] = set(conn.execute(select(s.doctors.c.mobile_e164)).scalars())
        phone = next(
            (f"+20100000{n:04d}" for n in range(1000, 2000) if f"+20100000{n:04d}" not in used),
            None,
        )
        if phone is None:
            _evict(conn, clock, system)
            continue
        try:
            with conn.begin_nested():
                conn.execute(
                    s.doctors.insert().values(
                        **(CLINIC["doctor"] | {"mobile_e164": phone}),
                        clinic_id=cid,
                        password_hash=password,
                    )
                )
            break
        except IntegrityError:
            # A concurrent sign-up may have claimed the selected mobile.
            if not conn.execute(
                select(s.doctors.c.id).where(s.doctors.c.mobile_e164 == phone)
            ).first():
                raise
    else:
        raise Busy("busy, try again later")
    for table, key in ((s.clinic_hours, "hours"), (s.clinic_info, "info")):
        conn.execute(table.insert(), [dict(clinic_id=cid, **r) for r in CLINIC[key]])
    conn.execute(s.learned_pace.insert().values(clinic_id=cid, **CLINIC["learned_pace"]))
    conn.execute(s.learned_start_gap.insert().values(clinic_id=cid, **CLINIC["learned_start_gap"]))
    schedule_timer(
        conn,
        system,
        "sandbox_expire",
        expires,
        {"clinic_id": cid},
        f"sandbox_expire:{cid}:{int(now.timestamp())}",
    )
    record.write_action(conn, cid, "system", "demo_copy_created")
    return cid


def create_demo_copy(engine: Engine, clock: Clock, kind: Kind, client_ip: str) -> int:
    with write_tx(engine) as conn:
        cid = create_demo_copy_in_tx(conn, clock, kind, client_ip)
    if cid is None:
        raise Busy("busy, try again later")
    return cid
