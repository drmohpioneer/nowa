"""Doctor provisioning. Tokens are candidates; one database transaction owns completion."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import time, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core import auth, booking, ratelimit, telegram_tokens
from nowa.core.clinic_settings import Hours, numeric_input
from nowa.core.text_norm import western_digits
from nowa.core.timers import schedule_timer
from nowa.db import write_tx
from nowa.messaging.outbox import enqueue_message
from nowa.triage.registry import APPROVED_SPECIALTIES

RESERVED = frozenset("d c l w p api static signup judge demo relay health _nowa".split())


AGREEMENT_DEFAULTS: dict[str, tuple[str, str]] = {
    "COMPANY_NAME": ("نوا، نسخة تجريبية", "Nowa, demo"),
    "COMPANY_ADDRESS": ("القاهرة", "Cairo"),
    "COMMERCIAL_REGISTER_NUMBER": ("تجريبي", "Demo"),
    "PRIVACY_EMAIL": ("يتحدد عند التعاقد", "Set at contracting"),
    "DPO_NAME": ("نوا، نسخة تجريبية", "Nowa, demo"),
    "RENDER_REGION": ("القاهرة", "Cairo"),
    "BACKUP_WINDOW_DAYS": ("30", "30"),
    "PILOT_END_DATE": ("نهاية فترة التجربة", "End of the demo period"),
    "LIABILITY_CAP_EGP": ("0", "0"),
    "NOTICE_DAYS": ("30", "30"),
}


@dataclass(frozen=True)
class Agreement:
    version: str
    display: dict[str, str]
    text_hash: dict[str, str]
    unfilled: tuple[str, ...] = ()


def load_agreement() -> Agreement:
    path = Path(__file__).resolve().parents[2] / "docs/reference/doctor-agreement.md"
    source = path.read_text(encoding="utf-8")
    match = re.search(r"^Version:\s*(\S+)", source, re.MULTILINE)
    if match is None:
        raise ValueError("Doctor agreement has no version")
    settings = get_settings()
    placeholders = set(re.findall(r"\[([A-Z][A-Z0-9_]*)\]", source))
    unknown = placeholders - AGREEMENT_DEFAULTS.keys()
    if unknown:
        raise ValueError("Unknown agreement placeholder: " + ", ".join(sorted(unknown)))
    unfilled = tuple(
        sorted(
            key
            for key in placeholders
            if not getattr(settings, "agreement_party_" + key.lower()).strip()
        )
    )
    display: dict[str, str] = {}
    for lang, index in (("ar", 0), ("en", 1)):
        section = re.search(
            rf"<!-- display:{lang} -->\s*(.*?)\s*<!-- /display -->", source, re.DOTALL
        )
        if section is None:
            raise ValueError("Doctor agreement has no display text for " + lang)
        text = section[1]
        for key, defaults in AGREEMENT_DEFAULTS.items():
            value = getattr(settings, "agreement_party_" + key.lower()).strip()
            if not value:
                value = (
                    defaults[index]
                    if settings.demo_mode
                    else ("[يُحدد عند التعاقد]" if lang == "ar" else "[set at signing]")
                )
            text = text.replace("[" + key + "]", value)
        display[lang] = text
    return Agreement(
        match[1],
        display,
        {lang: hashlib.sha256(text.encode()).hexdigest() for lang, text in display.items()},
        unfilled,
    )


class Refused(Exception):
    def __init__(self, reason: str = "refused", status: int = 400, fields: list[str] | None = None):
        self.reason, self.status, self.fields = reason, status, fields
        super().__init__(reason)


def system_id(conn: Connection) -> int:
    return int(conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == "_nowa")).scalar_one())


def real_ready(agreement: Agreement) -> None:
    settings = get_settings()
    if not settings.demo_mode and (
        not settings.telegram_bot_token or not settings.telegram_bot_username or agreement.unfilled
    ):
        raise Refused("not open yet", 503)


def sign(payload: str) -> str:
    return payload + "." + auth.keyed_hash(payload)


def unsign(token: str, prefix: str, now_s: float) -> list[str]:
    try:
        payload, signature = token.rsplit(".", 1)
        parts = payload.split("|")
        if parts[0] != prefix or not hmac.compare_digest(
            signature.encode(), auth.keyed_hash(payload).encode()
        ):
            raise ValueError
        if int(parts[-1]) <= now_s:
            raise ValueError
        return parts
    except (ValueError, IndexError):
        raise Refused() from None


@dataclass(frozen=True)
class CodeResult:
    allowed: bool
    cookie: str | None = field(default=None, repr=False)
    telegram_url: str | None = field(default=None, repr=False)


def request_code(
    engine: Engine, clock: Clock, agreement: Agreement, mobile: str, ip: str, lang: str
) -> CodeResult:
    real_ready(agreement)
    phone = booking.normalize_phone(mobile)
    with write_tx(engine) as conn:
        if not ratelimit.hit(conn, clock, "signup_code_ip", ip, 3600, 10):
            return CodeResult(False)
        if phone is None:
            raise Refused("invalid_mobile", 422)
        phone_key = auth.keyed_hash(phone)
        if not ratelimit.hit(conn, clock, "signup_code_phone", phone_key, 3600, 3):
            return CodeResult(False)
        if conn.execute(select(s.doctors.c.id).where(s.doctors.c.mobile_e164 == phone)).first():
            return CodeResult(True, telegram_url=unavailable_url())
        cid = system_id(conn)
        now = clock.now(cid, conn=conn)
        expires = now + timedelta(minutes=40)
        nonce = secrets.token_hex(16)
        pid = int(
            conn.execute(
                s.pending_signups.insert()
                .values(mobile_e164=phone, nonce=nonce, created_at=now, expires_at=expires)
                .returning(s.pending_signups.c.id)
            ).scalar_one()
        )
        conn.execute(
            s.auth_codes.update()
            .where(
                s.auth_codes.c.phone_key == phone_key,
                s.auth_codes.c.purpose == "signup",
                s.auth_codes.c.used_at.is_(None),
            )
            .values(used_at=now)
        )
        deferred = bool(get_settings().telegram_bot_username)
        code = secrets.token_urlsafe(32) if deferred else f"{secrets.randbelow(1000000):06d}"
        aid = int(
            conn.execute(
                s.auth_codes.insert()
                .values(
                    clinic_id=cid,
                    purpose="signup",
                    phone_key=phone_key,
                    pending_signup_id=pid,
                    code_hash=auth.keyed_hash(code),
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                .returning(s.auth_codes.c.id)
            ).scalar_one()
        )
        url = None
        if deferred:
            _, url = telegram_tokens.mint(conn, clock, None, "signup_telegram", pid, lang=lang)
        else:
            enqueue_message(
                conn,
                clock,
                cid,
                "op:signup_code",
                lang,
                "doctor",
                None,
                {"code": code},
                f"signup_code:{aid}:{secrets.token_hex(16)}",
                pending_signup_id=pid,
            )
        schedule_timer(
            conn,
            cid,
            "pending_signup_purge",
            expires + timedelta(hours=24),
            {"pending_signup_id": pid},
            f"pending_signup_purge:{pid}:{int(now.timestamp())}",
        )
        cookie = sign(f"signup_phone|{pid}|{nonce}|{int(expires.timestamp())}")
        return CodeResult(True, cookie if get_settings().demo_mode and not deferred else None, url)


def unavailable_url() -> str | None:
    # Same browser shape for a registered number, but no usable credential or identity row.
    username = get_settings().telegram_bot_username
    return f"https://t.me/{username}?start=s_{secrets.token_urlsafe(32)}" if username else None


def verify_code(engine: Engine, clock: Clock, mobile: str, code: str) -> str | None:
    phone = booking.normalize_phone(mobile)
    if phone is None:
        return None
    with write_tx(engine) as conn:
        now = clock.now(system_id(conn), conn=conn)
        row = (
            conn.execute(
                select(s.auth_codes)
                .where(
                    s.auth_codes.c.purpose == "signup",
                    s.auth_codes.c.phone_key == auth.keyed_hash(phone),
                    s.auth_codes.c.used_at.is_(None),
                    s.auth_codes.c.expires_at > now,
                )
                .order_by(s.auth_codes.c.created_at.desc(), s.auth_codes.c.id.desc())
                .limit(1)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        changed = conn.execute(
            s.auth_codes.update()
            .where(
                s.auth_codes.c.id == row["id"],
                s.auth_codes.c.attempts < 5,
                s.auth_codes.c.used_at.is_(None),
            )
            .values(attempts=s.auth_codes.c.attempts + 1)
        )
        if changed.rowcount != 1 or not hmac.compare_digest(
            row["code_hash"], auth.keyed_hash(western_digits(code))
        ):
            return None
        conn.execute(
            s.auth_codes.update().where(s.auth_codes.c.id == row["id"]).values(used_at=now)
        )
        return sign(f"signup|{row['phone_key']}|{row['id']}|{int(now.timestamp()) + 1800}")


def judge_start(engine: Engine, clock: Clock, code: str, ip: str) -> str | None:
    with write_tx(engine) as conn:
        if not ratelimit.hit(conn, clock, "judge_start_ip", ip, 900, 20):
            raise Refused(status=429)
        matched = False
        for configured in re.split(r"[,\r\n]", get_settings().judge_codes):
            configured = configured.strip()
            if configured:
                # Compare bytes so arbitrary Unicode input cannot raise TypeError.
                matched = hmac.compare_digest(code.encode(), configured.encode()) or matched
        if not matched:
            return None
        now = clock.now(system_id(conn), conn=conn)
        judge = auth.keyed_hash(code)
        judge_capacity(conn, judge, now)
        return sign(f"judge|{judge}|{secrets.token_hex(16)}|{int(now.timestamp()) + 1800}")


def judge_capacity(conn: Connection, judge: str, now: Any) -> None:
    count = conn.execute(
        select(func.count())
        .select_from(s.clinics)
        .where(s.clinics.c.judge_id == judge, s.clinics.c.created_at >= now - timedelta(hours=24))
    ).scalar_one()
    if count >= 3:
        raise Refused("judge_limit", 429)


class Complete(Hours):
    signup_token: SecretStr
    mobile: str = ""
    name_ar: Annotated[str, Field(min_length=2, max_length=60)]
    name_en: Annotated[str, Field(min_length=2, max_length=60)]
    specialty: str
    address: Annotated[str, Field(min_length=1, max_length=500)]
    address_en: Annotated[str, Field(max_length=500)] = ""
    lat: Annotated[float | None, Field(allow_inf_nan=False)] = None
    lng: Annotated[float | None, Field(allow_inf_nan=False)] = None
    pin_kind: Literal["here", "link", "area"]
    map_link: Annotated[str, Field(max_length=2000)] = ""
    area_id: Annotated[int | None, Field(strict=True, gt=0)] = None
    price_egp: Annotated[int, Field(strict=True, ge=0, le=100000)]
    clinic_phone: str = ""
    password: SecretStr
    agreement_version: str
    agree: Annotated[bool, Field(strict=True)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("price_egp", "area_id", mode="before")
    @classmethod
    def digits(cls, value: Any) -> Any:
        return numeric_input(value)

    @field_validator("name_ar", "name_en", "address", "address_en")
    @classmethod
    def meaningful(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value and info.field_name != "address_en":
            raise ValueError("text_required")
        return value


def coordinates(conn: Connection, body: Complete) -> tuple[float, float]:
    if body.pin_kind == "area":
        area = conn.execute(select(s.areas).where(s.areas.c.id == body.area_id)).mappings().first()
        if area is None:
            raise Refused("invalid_pin", 422)
        lat, lng = area["lat"], area["lng"]
    elif body.lat is not None and body.lng is not None:
        lat, lng = body.lat, body.lng
    elif body.pin_kind == "link":
        link = unquote(body.map_link)
        try:
            host = urlsplit(link).hostname or ""
        except ValueError:
            raise Refused("paste the full link or pick the area", 422) from None
        if host in {"maps.app.goo.gl", "goo.gl"}:
            raise Refused("paste the full link or pick the area", 422)
        match = None
        if host in {
            "google.com",
            "www.google.com",
            "maps.google.com",
            "google.com.eg",
            "www.google.com.eg",
        }:
            number = r"(-?\d+(?:\.\d+)?)"
            for pattern in (
                "@" + number + "," + number,
                r"[?&]q=" + number + "," + number,
                "!3d" + number + "!4d" + number,
            ):
                match = re.search(pattern, link)
                if match:
                    break
        if match is None:
            raise Refused("paste the full link or pick the area", 422)
        lat, lng = float(match[1]), float(match[2])
    else:
        raise Refused("invalid_pin", 422)
    if not 22 <= lat <= 32 or not 25 <= lng <= 36:
        raise Refused("invalid_pin", 422)
    return float(lat), float(lng)


def strip_honorific(raw: str) -> str:
    # Longest prefixes first; accepted with or without a following space.
    return re.sub(r"^(?:Doctor|Dr\.?|الدكتور|دكتور|د\.?)\s*", "", raw.strip(), flags=re.I)


def slug_for(conn: Connection, name: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not stem or stem in RESERVED or name.casefold() in RESERVED:
        raise Refused("invalid_name", 422)
    # Bound the slug without cutting the final word, including long direct callers.
    words: list[str] = []
    for word in stem.split("-"):
        if len("dr-" + "-".join(words + [word])) > 60:
            break
        words.append(word)
    if not words:
        raise Refused("invalid_name", 422)
    base, suffix = "dr-" + "-".join(words), 1
    while True:
        slug = base if suffix == 1 else f"{base}-{suffix}"
        if (
            not conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == slug)).first()
            and not conn.execute(
                select(s.deleted_slugs.c.slug).where(s.deleted_slugs.c.slug == slug)
            ).first()
        ):
            return slug
        suffix += 1


def result_for(conn: Connection, cid: int) -> dict[str, Any]:
    clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == cid)).mappings().first()
    if clinic is None:
        raise Refused("gone", 410)
    slug = clinic["slug"]
    result: dict[str, Any] = {
        "slug": slug,
        "chat_url": get_settings().public_base_url + "/c/" + slug,
        "poster_url": get_settings().public_base_url + "/d/poster",
    }
    if clinic["is_sandbox"]:
        result["mobile"] = conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == cid)
        ).scalar_one()
    return result


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]
    tokens: auth.SessionTokens | None = field(default=None, repr=False)


def complete(
    engine: Engine,
    clock: Clock,
    agreement: Agreement,
    payload: dict[str, Any],
    *,
    agreement_lang: str = "ar",
) -> Completion:
    if agreement_lang not in {"ar", "en"}:
        raise Refused("invalid_language", 422)
    # Validate only after replay; a replay can contain expired tokens or obsolete form fields.
    pid: int | None = None
    judge = False
    with write_tx(engine) as conn:
        cid_system = system_id(conn)
        conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.id == cid_system).with_for_update()
        ).one()
        key = payload.get("idempotency_key")
        if isinstance(key, str):
            existing = (
                conn.execute(select(s.idempotency_keys).where(s.idempotency_keys.c.key == key))
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["command"] != "signup_complete":
                    raise Refused("idempotency_conflict", 409)
                return Completion(result_for(conn, existing["result_json"]["clinic_id"]))
        try:
            body = Complete.model_validate(payload)
        except ValidationError:
            raise Refused("invalid_input", 422) from None
        now = clock.now(cid_system, conn=conn)
        token = body.signup_token.get_secret_value()
        judge = token.startswith("judge|")
        parts = unsign(token, "judge" if judge else "signup", now.timestamp())
        if len(parts) != 4:
            raise Refused()
        if judge:
            if not re.fullmatch(r"[a-f0-9]{32}", parts[2]):
                raise Refused()
            if conn.execute(
                select(s.idempotency_keys.c.id).where(s.idempotency_keys.c.key == parts[2])
            ).first():
                raise Refused("reused_token")
            judge_capacity(conn, parts[1], now)
            used: set[str] = set(conn.execute(select(s.doctors.c.mobile_e164)).scalars())
            phone = next(
                (
                    f"+201000000{n:03d}"
                    for n in range(900, 1000)
                    if f"+201000000{n:03d}" not in used
                ),
                None,
            )
            if phone is None:
                raise Refused("judge_numbers_full")
        else:
            real_ready(agreement)
            phone = booking.normalize_phone(body.mobile)
            if phone is None or reserved_phone(phone):
                raise Refused("invalid_mobile", 422)
            if not hmac.compare_digest(auth.keyed_hash(phone), parts[1]):
                raise Refused()
            if conn.execute(select(s.doctors.c.id).where(s.doctors.c.mobile_e164 == phone)).first():
                raise Refused("already_registered")
            if not parts[2].isdigit():
                raise Refused()
            code_row = (
                conn.execute(
                    select(s.auth_codes)
                    .where(
                        s.auth_codes.c.id == int(parts[2]),
                        s.auth_codes.c.purpose == "signup",
                        s.auth_codes.c.phone_key == parts[1],
                        s.auth_codes.c.used_at.is_not(None),
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if code_row is None:
                raise Refused()
            pid = code_row["pending_signup_id"]
            pending = (
                conn.execute(select(s.pending_signups).where(s.pending_signups.c.id == pid))
                .mappings()
                .first()
            )
            if (
                pending is None
                or pending["completed_at"] is not None
                or pending["expires_at"] <= now
            ):
                raise Refused()
        if body.specialty not in APPROVED_SPECIALTIES:
            raise Refused("invalid_specialty", 422)
        name_ar = strip_honorific(body.name_ar)
        name_en = strip_honorific(body.name_en)
        if not booking.valid_name(name_ar) or not booking.valid_name(name_en):
            raise Refused("invalid_name", 422)
        if not body.hours:
            raise Refused("no_working_days", 422)
        if len(body.password.get_secret_value()) < 8:
            raise Refused("invalid_input", 422)
        if not body.agree or body.agreement_version != agreement.version:
            raise Refused("agreement_required", 422)
        lat, lng = coordinates(conn, body)
        clinic_phone = booking.normalize_phone(body.clinic_phone) if body.clinic_phone else phone
        if clinic_phone is None:
            raise Refused("invalid_clinic_phone", 422, ["clinic_phone"])
        slug = slug_for(conn, name_en)
        cid = int(
            conn.execute(
                s.clinics.insert()
                .values(
                    slug=slug,
                    created_at=now,
                    name=f"عيادة د. {name_ar}",
                    specialty=body.specialty,
                    address=body.address,
                    address_en=body.address_en or body.address,
                    lat=lat,
                    lng=lng,
                    phone=clinic_phone,
                    is_sandbox=judge,
                    sandbox_expires_at=now + timedelta(days=7) if judge else None,
                    judge_id=parts[1] if judge else None,
                )
                .returning(s.clinics.c.id)
            ).scalar_one()
        )
        password_hash = auth.hash_password(body.password.get_secret_value())
        while True:
            try:
                # A uniqueness collision must roll back only this insert on Postgres.
                with conn.begin_nested():
                    did = int(
                        conn.execute(
                            s.doctors.insert()
                            .values(
                                clinic_id=cid,
                                name_ar=name_ar,
                                name_en=name_en,
                                mobile_e164=phone,
                                password_hash=password_hash,
                                lang="ar",
                            )
                            .returning(s.doctors.c.id)
                        ).scalar_one()
                    )
                break
            except IntegrityError:
                if (
                    not judge
                    or not conn.execute(
                        select(s.doctors.c.id).where(s.doctors.c.mobile_e164 == phone)
                    ).first()
                ):
                    raise
                used.add(phone)
                phone = next(
                    (
                        f"+201000000{n:03d}"
                        for n in range(900, 1000)
                        if f"+201000000{n:03d}" not in used
                    ),
                    None,
                )
                if phone is None:
                    raise Refused("judge_numbers_full") from None
                if not body.clinic_phone:
                    conn.execute(
                        s.clinics.update().where(s.clinics.c.id == cid).values(phone=phone)
                    )
        for hour in body.hours:
            conn.execute(
                s.clinic_hours.insert().values(
                    clinic_id=cid,
                    weekday=hour.weekday,
                    start=time.fromisoformat(hour.start),
                    end=time.fromisoformat(hour.end),
                )
            )
        for info_key, info_text in (("price", western_digits(str(body.price_egp))),):
            conn.execute(s.clinic_info.insert().values(clinic_id=cid, key=info_key, text=info_text))
        conn.execute(
            s.agreement_acceptances.insert().values(
                clinic_id=cid,
                doctor_id=did,
                version=agreement.version,
                text_hash=agreement.text_hash[agreement_lang],
                at=now,
            )
        )
        record.write_action(
            conn,
            cid,
            "doctor",
            "signup_complete",
            text="pin:area" if body.pin_kind == "area" else "pin:exact",
        )
        conn.execute(
            s.idempotency_keys.insert().values(
                clinic_id=cid,
                key=body.idempotency_key,
                command="signup_complete",
                result_json={"clinic_id": cid},
                created_at=now,
            )
        )
        if judge:
            conn.execute(
                s.idempotency_keys.insert().values(
                    clinic_id=cid,
                    key=parts[2],
                    command="judge_signup",
                    result_json={"clinic_id": cid},
                    created_at=now,
                )
            )
            schedule_timer(
                conn,
                cid_system,
                "sandbox_expire",
                now + timedelta(days=7),
                {"clinic_id": cid},
                f"sandbox_expire:{cid}:{int(now.timestamp())}",
            )
        else:
            conn.execute(
                s.pending_signups.update()
                .where(s.pending_signups.c.id == pid)
                .values(completed_at=now)
            )
        if judge:
            from nowa.core.sandbox import seed_sandbox_evening_in_tx

            seed_sandbox_evening_in_tx(conn, clock, cid)
        data = result_for(conn, cid)
    if pid is not None:
        with write_tx(engine) as conn:
            telegram_tokens.delete_signup_tokens(conn, pid)
            conn.execute(s.pending_signups.delete().where(s.pending_signups.c.id == pid))
    return Completion(data, auth.create_session(engine, clock, cid, did))


READY_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def ready_clinic(
    engine: Engine,
    clock: Clock,
    agreement: Agreement,
    token: str,
    agree: bool,
    *,
    agreement_lang: str = "ar",
) -> tuple[Completion, str]:
    """One-click practice clinic: fictional defaults through the same completion as the form."""
    if not token.startswith("judge|"):
        raise Refused("judge_token_required", 403)
    with engine.connect() as conn:
        area_id = conn.execute(
            select(s.areas.c.id).where(s.areas.c.name_en == "Nasr City")
        ).scalar_one_or_none()
        if area_id is None:
            area_id = conn.execute(select(func.min(s.areas.c.id))).scalar_one_or_none()
    if area_id is None:
        raise Refused("invalid_pin", 422)
    password = "".join(secrets.choice(READY_PASSWORD_ALPHABET) for _ in range(12))
    payload: dict[str, Any] = {
        "signup_token": token,
        "name_ar": "ياسر عادل",
        "name_en": "Yasser Adel",
        "specialty": "cardiology",
        "address": "شارع تجريبي ٢٠، مدينة نصر، القاهرة",
        "address_en": "20 Practice Street, Nasr City, Cairo",
        "pin_kind": "area",
        "area_id": area_id,
        "hours": [{"weekday": day, "start": "19:00", "end": "23:00"} for day in range(7)],
        "price_egp": 300,
        "password": password,
        "agreement_version": agreement.version,
        "agree": agree,
        "idempotency_key": "ready-" + secrets.token_hex(16),
    }
    done = complete(engine, clock, agreement, payload, agreement_lang=agreement_lang)
    return done, password


def reserved_phone(phone: str) -> bool:
    return (
        "+201000000900" <= phone <= "+201000000999" or "+201000001000" <= phone <= "+201000001999"
    )
