import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core import booking, ratelimit, telegram_tokens
from nowa.db import write_tx
from nowa.messaging.outbox import enqueue_message, telegram_chat

_hasher = PasswordHasher()
_dummy = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def keyed_hash(value: str) -> str:
    return hmac.new(
        get_settings().server_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class SessionTokens:
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class Session:
    session_id: int
    clinic_id: int
    doctor_id: int
    csrf_hash: str = field(repr=False)


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    limited: bool = False
    tokens: SessionTokens | None = field(default=None, repr=False)


def _create_session(
    conn: Connection, clock: Clock, clinic_id: int, doctor_id: int
) -> SessionTokens:
    now = clock.base_now().astimezone(UTC)
    tokens = SessionTokens(
        secrets.token_urlsafe(32), secrets.token_urlsafe(32), now + timedelta(days=30)
    )
    conn.execute(
        s.doctor_sessions.insert().values(
            clinic_id=clinic_id,
            doctor_id=doctor_id,
            token_hash=token_hash(tokens.token),
            csrf_hash=token_hash(tokens.csrf_token),
            created_at=now,
            expires_at=tokens.expires_at,
            last_seen_at=now,
        )
    )
    record.write_action(conn, clinic_id, "doctor", "doctor_login")
    return tokens


def create_session(engine: Engine, clock: Clock, clinic_id: int, doctor_id: int) -> SessionTokens:
    with write_tx(engine) as conn:
        conn.execute(
            select(s.doctors.c.id).where(
                s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id
            )
        ).scalar_one()
        return _create_session(conn, clock, clinic_id, doctor_id)


def login(engine: Engine, clock: Clock, mobile: str, password: str, client_ip: str) -> LoginResult:
    with write_tx(engine) as conn:
        if not ratelimit.hit(conn, clock, "doctor_login_ip", client_ip, 900, 20):
            return LoginResult(False, limited=True)
        phone = booking.normalize_phone(mobile)
        if not ratelimit.hit(conn, clock, "doctor_login", phone or mobile, 900, 5):
            return LoginResult(False, limited=True)
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.mobile_e164 == phone))
            .mappings()
            .one_or_none()
        )
        try:
            valid: bool = _hasher.verify(doctor["password_hash"] if doctor else _dummy, password)
        except VerificationError:
            valid = False
        if not valid or doctor is None:
            return LoginResult(False)
        return LoginResult(
            True, tokens=_create_session(conn, clock, doctor["clinic_id"], doctor["id"])
        )


def session_for(engine: Engine, clock: Clock, token: str, *, touch: bool = True) -> Session | None:
    with write_tx(engine) as conn:
        now = clock.base_now().astimezone(UTC)
        row = (
            conn.execute(
                select(s.doctor_sessions).where(
                    s.doctor_sessions.c.token_hash == token_hash(token),
                    s.doctor_sessions.c.revoked_at.is_(None),
                    s.doctor_sessions.c.expires_at > now,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if touch:
            conn.execute(
                s.doctor_sessions.update()
                .where(s.doctor_sessions.c.id == row["id"])
                .values(last_seen_at=now)
            )
        return Session(row["id"], row["clinic_id"], row["doctor_id"], row["csrf_hash"])


def touch_session(conn: Connection, clock: Clock, session: Session) -> None:
    conn.execute(
        s.doctor_sessions.update()
        .where(s.doctor_sessions.c.id == session.session_id)
        .values(last_seen_at=clock.base_now().astimezone(UTC))
    )


def logout(engine: Engine, clock: Clock, session: Session) -> None:
    with write_tx(engine) as conn:
        conn.execute(
            s.doctor_sessions.update()
            .where(s.doctor_sessions.c.id == session.session_id)
            .values(
                revoked_at=clock.base_now().astimezone(UTC),
                last_seen_at=clock.base_now().astimezone(UTC),
            )
        )
        record.write_action(conn, session.clinic_id, "doctor", "doctor_logout")


def redact_code_row(conn: Connection, outbox_id: int) -> None:
    template: str = conn.execute(
        select(s.outbox.c.template_id).where(s.outbox.c.id == outbox_id)
    ).scalar_one()
    if template != "op:reset_code":
        raise ValueError("Only reset-code messages may be redacted")
    conn.execute(s.outbox.update().where(s.outbox.c.id == outbox_id).values(body="[redacted]"))


def _redact(conn: Connection, code_id: int) -> None:
    oid: int
    for oid in conn.execute(
        select(s.outbox.c.id).where(
            s.outbox.c.idempotency_key.in_((f"reset_code:{code_id}", f"reset_code:{code_id}:tg"))
        )
    ).scalars():
        redact_code_row(conn, oid)


@dataclass(frozen=True)
class ResetResult:
    allowed: bool
    telegram_url: str | None = field(default=None, repr=False)

    def __bool__(self) -> bool:
        return self.allowed


def request_reset(engine: Engine, clock: Clock, mobile: str, client_ip: str) -> ResetResult:
    with write_tx(engine) as conn:
        if not ratelimit.hit(conn, clock, "doctor_reset_ip", client_ip, 900, 20):
            return ResetResult(False)
        phone = booking.normalize_phone(mobile)
        # The doctor lock serializes concurrent requests and confirms for this phone.
        doctor = (
            conn.execute(
                select(s.doctors).where(s.doctors.c.mobile_e164 == phone).with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if doctor is None:
            return ResetResult(True)
        now = clock.base_now().astimezone(UTC)
        phone_key = keyed_hash(phone or "")
        where = (s.auth_codes.c.phone_key == phone_key, s.auth_codes.c.purpose == "reset")
        count = conn.execute(
            select(func.count())
            .select_from(s.auth_codes)
            .where(*where, s.auth_codes.c.created_at >= now - timedelta(hours=1))
        ).scalar_one()
        older = conn.execute(select(s.auth_codes).where(*where)).mappings().all()
        for row in older:
            if row["expires_at"] <= now:
                _redact(conn, row["id"])
        if count >= 3:
            return ResetResult(True)
        for row in older:
            if row["used_at"] is None:
                conn.execute(
                    s.auth_codes.update().where(s.auth_codes.c.id == row["id"]).values(used_at=now)
                )
            if row["used_at"] is None and row["expires_at"] > now:
                _redact(conn, row["id"])
        deferred = bool(get_settings().telegram_bot_username) and not telegram_chat(
            conn, phone or "", "doctor"
        )
        code = secrets.token_urlsafe(32) if deferred else f"{secrets.randbelow(1000000):06d}"
        conn.execute(
            s.link_tokens.update()
            .where(
                s.link_tokens.c.kind == "reset_telegram",
                s.link_tokens.c.subject_id == doctor["id"],
                s.link_tokens.c.used_at.is_(None),
            )
            .values(expires_at=now)
        )
        code_id: int = conn.execute(
            s.auth_codes.insert()
            .values(
                clinic_id=doctor["clinic_id"],
                purpose="reset",
                phone_key=phone_key,
                code_hash=keyed_hash(code),
                attempts=0,
                created_at=now,
                expires_at=now + timedelta(minutes=10),
            )
            .returning(s.auth_codes.c.id)
        ).scalar_one()
        url = None
        if deferred:
            _, url = telegram_tokens.mint(
                conn,
                clock,
                doctor["clinic_id"],
                "reset_telegram",
                doctor["id"],
                lang=doctor["lang"],
            )
        else:
            enqueue_message(
                conn,
                clock,
                doctor["clinic_id"],
                "op:reset_code",
                doctor["lang"],
                "doctor",
                None,
                {"code": code},
                f"reset_code:{code_id}",
            )
        record.write_action(conn, doctor["clinic_id"], "doctor", "doctor_reset_request")
        return ResetResult(True, url)


def confirm_reset(engine: Engine, clock: Clock, mobile: str, code: str, new_password: str) -> bool:
    if len(new_password) < 8:
        raise ValueError("new_password")
    with write_tx(engine) as conn:
        phone = booking.normalize_phone(mobile)
        doctor = (
            conn.execute(
                select(s.doctors).where(s.doctors.c.mobile_e164 == phone).with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        now = clock.base_now().astimezone(UTC)
        row = (
            conn.execute(
                select(s.auth_codes)
                .where(
                    s.auth_codes.c.phone_key == keyed_hash(phone or ""),
                    s.auth_codes.c.purpose == "reset",
                    s.auth_codes.c.used_at.is_(None),
                    s.auth_codes.c.expires_at > now,
                )
                .order_by(s.auth_codes.c.created_at.desc(), s.auth_codes.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if doctor is None or row is None:
            return False
        changed = conn.execute(
            s.auth_codes.update()
            .where(s.auth_codes.c.id == row["id"], s.auth_codes.c.attempts < 5)
            .values(attempts=s.auth_codes.c.attempts + 1)
        )
        if changed.rowcount == 0 or not hmac.compare_digest(row["code_hash"], keyed_hash(code)):
            return False
        conn.execute(
            s.doctors.update()
            .where(s.doctors.c.id == doctor["id"])
            .values(password_hash=hash_password(new_password))
        )
        conn.execute(
            s.auth_codes.update().where(s.auth_codes.c.id == row["id"]).values(used_at=now)
        )
        conn.execute(
            s.doctor_sessions.update()
            .where(s.doctor_sessions.c.doctor_id == doctor["id"])
            .values(revoked_at=now)
        )
        _redact(conn, row["id"])
        record.write_action(conn, doctor["clinic_id"], "doctor", "doctor_reset_complete")
        return True
