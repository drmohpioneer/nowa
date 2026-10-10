"""Provisioning and lifecycle regressions."""

import hashlib
import hmac
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from nowa import record, worker
from nowa import schema as s
from nowa.config import get_settings
from nowa.core import auth, signup
from nowa.core.timers import schedule_timer
from nowa.db import write_tx

PHONE = "+201000000005"


def code_for(engine):
    with engine.connect() as conn:
        body = conn.execute(
            select(s.outbox.c.body)
            .where(s.outbox.c.template_id == "op:signup_code")
            .order_by(s.outbox.c.id.desc())
            .limit(1)
        ).scalar_one()
        return re.search(r"\b[0-9]{6}\b", body)[0]


def payload(token, **changes):
    result = dict(
        signup_token=token,
        mobile=PHONE,
        name_ar="كريم محمود",
        name_en="Karim Mahmoud",
        specialty="cardiology",
        address="Fictional clinic",
        lat=30.0911,
        lng=31.3228,
        pin_kind="here",
        hours=[dict(weekday=day, start="19:00", end="23:00") for day in range(7)],
        price_egp=300,
        password="fictional-password",
        agreement_version="0.1",
        agree=True,
        idempotency_key="fictional-completion",
    )
    result.update(changes)
    return result


def test_phone_limit_survives_completion_third_allowed_fourth_refused(engine, offset_clock):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    assert signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar").allowed
    code = code_for(engine)
    token = signup.verify_code(engine, offset_clock, PHONE, code)
    assert token
    completed = signup.complete(engine, offset_clock, agreement, payload(token))
    assert completed.tokens is not None
    with engine.connect() as conn:
        assert not conn.execute(select(s.pending_signups)).all()
        assert not conn.execute(select(s.auth_codes)).all()
        assert conn.execute(select(s.outbox.c.pending_signup_id)).scalar_one() is None
        acceptance = conn.execute(select(s.agreement_acceptances)).mappings().one()
        assert acceptance["version"] == "0.1"
        assert (
            acceptance["text_hash"] == hashlib.sha256(agreement.display["ar"].encode()).hexdigest()
        )
    assert signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar").allowed
    assert signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar").allowed
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(s.pending_signups)).scalar_one()
    assert not signup.request_code(
        engine, offset_clock, agreement, PHONE, "fictional-ip", "ar"
    ).allowed
    with engine.connect() as conn:
        assert (
            conn.execute(select(func.count()).select_from(s.pending_signups)).scalar_one() == before
        )
        counter = (
            conn.execute(
                select(s.rate_counters).where(s.rate_counters.c.scope == "signup_code_phone")
            )
            .mappings()
            .one()
        )
        expected = hmac.new(
            get_settings().server_secret.encode(),
            f"signup_code_phone|{auth.keyed_hash(PHONE)}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert counter["key_hash"] == expected
        assert PHONE not in str(counter)
        assert counter["count"] == 4
    # Replay comes before all validation, and never creates a new session.
    replay = signup.complete(
        engine,
        offset_clock,
        agreement,
        {"idempotency_key": "fictional-completion", "signup_token": "expired"},
    )
    assert replay.data == completed.data and replay.tokens is None
    with pytest.raises(signup.Refused, match="already_registered"):
        signup.complete(engine, offset_clock, agreement, payload(token, idempotency_key="another"))


def test_code_five_tries_newest_expiry_and_single_use(engine, offset_clock, frozen_clock):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    old = code_for(engine)
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    code = code_for(engine)
    if old != code:
        assert signup.verify_code(engine, offset_clock, PHONE, old) is None
    with engine.connect() as conn:
        row = (
            conn.execute(select(s.auth_codes).order_by(s.auth_codes.c.id.desc()).limit(1))
            .mappings()
            .one()
        )
        assert row["expires_at"] - row["created_at"] == timedelta(minutes=10)
        assert row["code_hash"] == auth.keyed_hash(code) and row["code_hash"] != code
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert signup.verify_code(engine, offset_clock, PHONE, wrong) is None
    assert signup.verify_code(engine, offset_clock, PHONE, code) is None
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    code = code_for(engine)
    frozen_clock.advance(minutes=10)
    assert signup.verify_code(engine, offset_clock, PHONE, code) is None


def test_verify_success_consumed_once(engine, offset_clock):
    record.configure(offset_clock)
    signup.request_code(engine, offset_clock, signup.load_agreement(), PHONE, "fictional-ip", "en")
    code = code_for(engine)
    assert signup.verify_code(engine, offset_clock, PHONE, code)
    assert signup.verify_code(engine, offset_clock, PHONE, code) is None


def test_code_ip_limit_precedes_phone_counter_and_signup_writes(engine, offset_clock):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    for index in range(10):
        assert signup.request_code(
            engine, offset_clock, agreement, f"+201000003{index:03d}", "fictional-ip", "ar"
        ).allowed
    assert not signup.request_code(
        engine, offset_clock, agreement, PHONE, "fictional-ip", "ar"
    ).allowed
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.pending_signups)).scalar_one() == 10
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.rate_counters)
                .where(s.rate_counters.c.scope == "signup_code_phone")
            ).scalar_one()
            == 10
        )


def test_reused_pending_signup_gets_own_purge_deadline(
    engine, offset_clock, frozen_clock
):
    record.configure(offset_clock)
    now = offset_clock.now(1)
    with write_tx(engine) as conn:
        cid = signup.system_id(conn)
        pid = conn.execute(
            s.pending_signups.insert()
            .values(mobile_e164=PHONE, created_at=now, expires_at=now + timedelta(minutes=40))
            .returning(s.pending_signups.c.id)
        ).scalar_one()
        old_timer = schedule_timer(
            conn,
            cid,
            "pending_signup_purge",
            now + timedelta(hours=24, minutes=40),
            {"pending_signup_id": pid},
            f"pending_signup_purge:{pid}:{int(now.timestamp())}",
        )
        conn.execute(s.pending_signups.delete().where(s.pending_signups.c.id == pid))
    frozen_clock.advance(minutes=60)
    later = offset_clock.now(cid)
    with write_tx(engine) as conn:
        replacement = conn.execute(
            s.pending_signups.insert()
            .values(
                mobile_e164="+201000000006",
                created_at=later,
                expires_at=later + timedelta(minutes=40),
            )
            .returning(s.pending_signups.c.id)
        ).scalar_one()
        returned = schedule_timer(
            conn,
            cid,
            "pending_signup_purge",
            later + timedelta(hours=24, minutes=40),
            {"pending_signup_id": replacement},
            f"pending_signup_purge:{replacement}:{int(later.timestamp())}",
        )
        assert replacement == pid and returned != old_timer

    from nowa.core.signup_handlers import pending_signup_purge

    frozen_clock.advance(
        minutes=24 * 60 - 20
    )  # Original timer due; replacement is not eligible yet.
    stats = worker.run_once(engine, offset_clock, {"pending_signup_purge": pending_signup_purge})
    assert stats.done == 1
    frozen_clock.advance(minutes=60)  # Replacement's agreed purge deadline.
    stats = worker.run_once(engine, offset_clock, {"pending_signup_purge": pending_signup_purge})
    assert stats.done == 1
    with engine.connect() as conn:
        assert not conn.execute(select(s.pending_signups.c.id)).all()
        assert (
            conn.execute(select(s.timers.c.status).where(s.timers.c.id == old_timer)).scalar_one()
            == "done"
        )
        assert (
            conn.execute(select(s.timers.c.status).where(s.timers.c.id == returned)).scalar_one()
            == "done"
        )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("specialty", "dermatology", "invalid_specialty"),
        ("name_en", "Karim2", "invalid_name"),
        ("name_ar", "<كريم>", "invalid_name"),
        ("price_egp", -1, "invalid_input"),
        ("agree", False, "agreement_required"),
        ("hours", [], "no_working_days"),
    ],
)
def test_refused_completion_rolls_back_clinic_creation(engine, offset_clock, field, value, reason):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    token = signup.verify_code(engine, offset_clock, PHONE, code_for(engine))
    with pytest.raises(signup.Refused, match=reason):
        signup.complete(engine, offset_clock, agreement, payload(token, **{field: value}))
    with engine.connect() as conn:
        assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]
        assert not conn.execute(select(s.doctors)).all()
        assert not conn.execute(select(s.agreement_acceptances)).all()


def test_reused_clinic_gets_pending_expiry_for_seven_real_days(
    engine, offset_clock, frozen_clock, monkeypatch
):
    """Exercise provisioning and the real expiry handler with SQLite ID reuse."""
    record.configure(offset_clock)
    monkeypatch.setenv("JUDGE_CODES", "fictional-judge-code")
    get_settings.cache_clear()
    agreement = signup.load_agreement()

    def create(key):
        token = signup.judge_start(engine, offset_clock, "fictional-judge-code", "fictional-ip")
        assert token
        result = signup.complete(
            engine, offset_clock, agreement, payload(token, idempotency_key=key)
        )
        with engine.connect() as conn:
            clinic = (
                conn.execute(select(s.clinics).where(s.clinics.c.slug == result.data["slug"]))
                .mappings()
                .one()
            )
            timer = (
                conn.execute(
                    select(s.timers).where(
                        s.timers.c.kind == "sandbox_expire", s.timers.c.status == "pending"
                    )
                )
                .mappings()
                .one()
            )
        assert (
            timer["idempotency_key"]
            == f"sandbox_expire:{clinic['id']}:{int(clinic['created_at'].timestamp())}"
        )
        assert timer["clinic_id"] != clinic["id"]
        assert timer["due_at"] == clinic["created_at"] + timedelta(days=7)
        assert timer["payload_json"] == {"clinic_id": clinic["id"]}
        return clinic, timer

    from nowa.core.signup_handlers import sandbox_expire

    registry = {"sandbox_expire": sandbox_expire}
    first, old_timer = create("first-judge")
    # Its seeded evening fast-forward cannot expire a timer on the permanent system clinic.
    assert (
        worker.run_once(
            engine, offset_clock, registry, only_clinic_id=old_timer["clinic_id"]
        ).claimed
        == 0
    )
    frozen_clock.advance(minutes=7 * 24 * 60)
    assert (
        worker.run_once(engine, offset_clock, registry, only_clinic_id=old_timer["clinic_id"]).done
        == 1
    )
    second, new_timer = create("second-judge")
    assert second["id"] == first["id"]  # SQLite highest-id reuse is part of this regression.
    assert new_timer["id"] != old_timer["id"] and new_timer["status"] == "pending"
    frozen_clock.advance(minutes=7 * 24 * 60 - 1)
    assert (
        worker.run_once(
            engine, offset_clock, registry, only_clinic_id=new_timer["clinic_id"]
        ).claimed
        == 0
    )
    frozen_clock.advance(minutes=1)
    assert (
        worker.run_once(engine, offset_clock, registry, only_clinic_id=new_timer["clinic_id"]).done
        == 1
    )
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.clinics.c.id).where(s.clinics.c.id == second["id"])).first()
            is None
        )
        assert (
            conn.execute(
                select(s.timers.c.status).where(s.timers.c.id == new_timer["id"])
            ).scalar_one()
            == "done"
        )


@pytest.mark.parametrize(
    "link",
    [
        "https://www.google.com/maps/@30.0911,31.3228,15z",
        "https://maps.google.com/?q=30.0911,31.3228",
        "https://www.google.com/maps/place/Fictional/data=!3d30.0911!4d31.3228",
    ],
)
def test_map_coordinates_parse_without_fetch_and_explicit_coordinates_win(engine, link):
    body = signup.Complete.model_validate(
        payload("candidate", pin_kind="link", lat=None, lng=None, map_link=link)
    )
    with engine.connect() as conn:
        assert signup.coordinates(conn, body) == (30.0911, 31.3228)
        explicit = body.model_copy(
            update={"lat": 30.2, "lng": 31.3, "map_link": "https://maps.app.goo.gl/short"}
        )
        assert signup.coordinates(conn, explicit) == (30.2, 31.3)


@pytest.mark.parametrize(
    "link",
    [
        "https://maps.app.goo.gl/short",
        "https://goo.gl/maps/short",
        "https://example.com/?q=30,31",
        "https://www.google.com/maps/no-coordinates",
        "https://[malformed/?q=30,31",
    ],
)
def test_unsupported_map_links_have_fixed_refusal(engine, link):
    body = signup.Complete.model_validate(
        payload("candidate", pin_kind="link", lat=None, lng=None, map_link=link)
    )
    with (
        engine.connect() as conn,
        pytest.raises(signup.Refused, match="paste the full link or pick the area"),
    ):
        signup.coordinates(conn, body)


def test_area_rough_pin_rejects_overnight_hours_and_checks_price_boundaries(engine, offset_clock):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    token = signup.verify_code(engine, offset_clock, PHONE, code_for(engine))
    with engine.connect() as conn:
        area = conn.execute(select(s.areas).limit(1)).mappings().one()
    with pytest.raises(signup.Refused, match="invalid_input"):
        signup.complete(
            engine,
            offset_clock,
            agreement,
            payload(token, hours=[dict(weekday=0, start="19:00", end="01:00")]),
        )
    result = signup.complete(
        engine,
        offset_clock,
        agreement,
        payload(
            token,
            pin_kind="area",
            lat=None,
            lng=None,
            area_id=area["id"],
            price_egp=100000,
            hours=[dict(weekday=0, start="19:00", end="23:00")],
        ),
    )
    with engine.connect() as conn:
        clinic = (
            conn.execute(select(s.clinics).where(s.clinics.c.slug == result.data["slug"]))
            .mappings()
            .one()
        )
        assert (clinic["lat"], clinic["lng"]) == (area["lat"], area["lng"])
        assert clinic["phone"] == PHONE
        assert clinic["max_per_evening"] is None
        assert (clinic["cushion_min"], clinic["usual_visit_min"], clinic["safe_drive_min"]) == (
            10,
            15,
            45,
        )
        assert (
            conn.execute(
                select(s.clinic_info.c.text).where(
                    s.clinic_info.c.clinic_id == clinic["id"], s.clinic_info.c.key == "other"
                )
            ).scalar_one_or_none()
            is None
        )
        hour = (
            conn.execute(select(s.clinic_hours).where(s.clinic_hours.c.clinic_id == clinic["id"]))
            .mappings()
            .one()
        )
        assert hour["start"].hour == 19 and hour["end"].hour == 23
    assert signup.Complete.model_validate(payload("candidate", price_egp=0)).price_egp == 0


@pytest.mark.parametrize(
    "phone", ["+201000000900", "+201000000999", "+201000001000", "+201000001999"]
)
def test_ordinary_signup_rejects_reserved_mobile_ranges(engine, offset_clock, phone):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, phone, "fictional-ip", "ar")
    token = signup.verify_code(engine, offset_clock, phone, code_for(engine))
    with pytest.raises(signup.Refused, match="invalid_mobile"):
        signup.complete(engine, offset_clock, agreement, payload(token, mobile=phone))


def test_slug_collisions_include_deleted_slugs_and_reserved_stems(engine, frozen_clock):
    with write_tx(engine) as conn:
        assert signup.slug_for(conn, "Karim Mahmoud") == "dr-karim-mahmoud"
        conn.execute(
            s.clinics.insert().values(
                slug="dr-karim-mahmoud",
                name="Fictional",
                specialty="cardiology",
                address="",
                lat=30,
                lng=31,
                phone="",
                created_at=frozen_clock.base_now(),
            )
        )
        conn.execute(
            s.deleted_slugs.insert().values(
                slug="dr-karim-mahmoud-2", deleted_at=frozen_clock.base_now()
            )
        )
        assert signup.slug_for(conn, "Karim Mahmoud") == "dr-karim-mahmoud-3"
        for reserved in signup.RESERVED:
            with pytest.raises(signup.Refused, match="invalid_name"):
                signup.slug_for(conn, reserved)


def test_abandoned_pending_signup_purge_preserves_text_and_cascades_codes(
    engine, offset_clock, frozen_clock
):
    record.configure(offset_clock)
    signup.request_code(engine, offset_clock, signup.load_agreement(), PHONE, "fictional-ip", "ar")
    with engine.connect() as conn:
        pending = conn.execute(select(s.pending_signups)).mappings().one()
        outbox = conn.execute(select(s.outbox)).mappings().one()
        assert outbox["pending_signup_id"] == pending["id"]
        assert outbox["recipient_kind"] == "pending_signup"
        assert pending["expires_at"] - pending["created_at"] == timedelta(minutes=40)
    registry = {"pending_signup_purge": worker.build_registry()["pending_signup_purge"]}
    frozen_clock.advance(minutes=24 * 60 + 39)
    assert worker.run_once(engine, offset_clock, registry).claimed == 0
    frozen_clock.advance(minutes=1)
    assert worker.run_once(engine, offset_clock, registry).done == 1
    with engine.connect() as conn:
        assert conn.execute(select(s.pending_signups)).all() == []
        assert conn.execute(select(s.auth_codes)).all() == []
        message = conn.execute(select(s.outbox)).mappings().one()
        assert message["pending_signup_id"] is None and message["body"] == outbox["body"]
    assert worker.run_once(engine, offset_clock, registry).claimed == 0


def test_completion_failure_at_action_record_rolls_back_all_writes(
    engine, offset_clock, monkeypatch
):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    token = signup.verify_code(engine, offset_clock, PHONE, code_for(engine))

    with engine.connect() as conn:
        prior_actions = conn.execute(select(s.action_record)).all()

    def fail(*args, **kwargs):
        raise RuntimeError("fictional write failure")

    monkeypatch.setattr(record, "write_action", fail)
    with pytest.raises(RuntimeError, match="fictional write failure"):
        signup.complete(engine, offset_clock, agreement, payload(token))
    with engine.connect() as conn:
        assert conn.execute(select(s.clinics.c.slug)).scalars().all() == ["_nowa"]
        for table in (
            s.doctors,
            s.clinic_hours,
            s.clinic_info,
            s.agreement_acceptances,
            s.idempotency_keys,
        ):
            assert conn.execute(select(table)).all() == [], table.name
        assert conn.execute(select(s.action_record)).all() == prior_actions
        assert conn.execute(select(s.pending_signups.c.completed_at)).scalar_one() is None


def test_concurrent_judges_get_distinct_lowest_reserved_mobiles(engine, offset_clock, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    record.configure(offset_clock)
    monkeypatch.setenv("JUDGE_CODES", "fictional-judge-code")
    get_settings.cache_clear()
    agreement = signup.load_agreement()
    tokens = [
        signup.judge_start(engine, offset_clock, "fictional-judge-code", f"ip-{i}")
        for i in range(2)
    ]

    def create(i):
        return signup.complete(
            engine, offset_clock, agreement, payload(tokens[i], idempotency_key=f"concurrent-{i}")
        ).data

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert {r["mobile"] for r in results} == {"+201000000900", "+201000000901"}
    assert {r["slug"] for r in results} == {"dr-karim-mahmoud", "dr-karim-mahmoud-2"}


@pytest.mark.postgres
def test_postgres_concurrent_judges_get_distinct_reserved_mobiles(
    postgres_engine, frozen_clock, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from nowa.clock import ClinicOffsetClock

    clock = ClinicOffsetClock(frozen_clock, postgres_engine)
    record.configure(clock)
    monkeypatch.setenv("JUDGE_CODES", "fictional-judge-code")
    get_settings.cache_clear()
    agreement = signup.load_agreement()
    tokens = [
        signup.judge_start(postgres_engine, clock, "fictional-judge-code", f"ip-{i}")
        for i in range(2)
    ]

    def create(i):
        return signup.complete(
            postgres_engine, clock, agreement, payload(tokens[i], idempotency_key=f"concurrent-{i}")
        ).data

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert {r["mobile"] for r in results} == {"+201000000900", "+201000000901"}
    assert len({r["slug"] for r in results}) == 2


def test_signed_candidates_refuse_malformed_unicode_signature(engine, offset_clock):
    now = offset_clock.now(1).timestamp()
    with pytest.raises(signup.Refused):
        signup.unsign(f"signup|candidate|1|{int(now) + 100}.غيرصحيح", "signup", now)


def test_seed_fallback_when_original_hours_fit_no_patient(engine, offset_clock, monkeypatch):
    from nowa.core import booking, flows
    from nowa.core.sandbox import seed_sandbox_evening

    real_book = flows.book_in_tx
    attempts = []

    def first_full(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            return booking.BookingRefused("full")
        return real_book(*args, **kwargs)

    monkeypatch.setattr(flows, "book_in_tx", first_full)
    record.configure(offset_clock)
    monkeypatch.setenv("JUDGE_CODES", "fictional-judge-code")
    get_settings.cache_clear()
    token = signup.judge_start(engine, offset_clock, "fictional-judge-code", "fictional-ip")
    result = signup.complete(
        engine,
        offset_clock,
        signup.load_agreement(),
        payload(token, hours=[dict(weekday=day, start="19:00", end="19:01") for day in range(7)]),
    )
    with engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == result.data["slug"])
        ).scalar_one()
        hours = (
            conn.execute(select(s.clinic_hours).where(s.clinic_hours.c.clinic_id == cid))
            .mappings()
            .all()
        )
        bookings = conn.execute(select(s.bookings).where(s.bookings.c.clinic_id == cid)).all()
        assert len(bookings) >= 1
        assert len(hours) == 7 and all(h["start"].hour == 19 and h["end"].hour == 23 for h in hours)
        before = conn.execute(
            select(s.clinics.c.clock_offset_s).where(s.clinics.c.id == cid)
        ).scalar_one()
    seed_sandbox_evening(engine, offset_clock, cid)
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.bookings).where(s.bookings.c.clinic_id == cid)).all() == bookings
        )
        assert (
            conn.execute(
                select(s.clinics.c.clock_offset_s).where(s.clinics.c.id == cid)
            ).scalar_one()
            == before
        )


def test_hosted_readiness_requires_bot_and_filled_agreement(engine, offset_clock, monkeypatch):
    settings = get_settings()
    settings.demo_mode = False
    settings.telegram_bot_token = "fixture-token"
    settings.telegram_bot_username = "fixture_bot"
    with pytest.raises(signup.Refused, match="not open yet"):
        signup.real_ready(signup.load_agreement())
    for key in signup.AGREEMENT_DEFAULTS:
        monkeypatch.setattr(settings, "agreement_party_" + key.lower(), "Fictional value")
    filled = signup.load_agreement()
    settings.telegram_bot_username = ""
    with pytest.raises(signup.Refused, match="not open yet"):
        signup.real_ready(filled)
    settings.telegram_bot_username = "fixture_bot"
    record.configure(offset_clock)
    result = signup.request_code(engine, offset_clock, filled, PHONE, "fictional-ip", "ar")
    assert result.allowed and result.cookie is None and result.telegram_url
    with engine.connect() as conn:
        assert not conn.execute(select(s.outbox)).first()
        assert conn.execute(select(s.link_tokens.c.kind)).scalar_one() == "signup_telegram"


@pytest.mark.parametrize("prefix", ["Dr ", "Dr.", "DR ", "Doctor", "د. ", "د", "دكتور ", "الدكتور"])
def test_doctor_honorific_stripped_before_storage(engine, offset_clock, prefix):
    record.configure(offset_clock)
    agreement = signup.load_agreement()
    signup.request_code(engine, offset_clock, agreement, PHONE, "fictional-ip", "ar")
    token = signup.verify_code(engine, offset_clock, PHONE, code_for(engine))
    result = signup.complete(
        engine,
        offset_clock,
        agreement,
        payload(token, name_en=prefix + "Hesham Mostafa", name_ar=prefix + "هشام مصطفى"),
    )
    assert result.tokens is not None
    with engine.connect() as conn:
        clinic = (
            conn.execute(select(s.clinics).where(s.clinics.c.slug == result.data["slug"]))
            .mappings()
            .one()
        )
        doctor = (
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == clinic["id"]))
            .mappings()
            .one()
        )
        assert clinic["slug"] == "dr-hesham-mostafa"
        assert clinic["name"] == "عيادة د. هشام مصطفى"
        assert doctor["name_en"] == "Hesham Mostafa"
        assert doctor["name_ar"] == "هشام مصطفى"
