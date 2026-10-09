import secrets
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    false,
    text,
    true,
)

from nowa.db import UtcDateTime, metadata


def id_column() -> Column[int]:
    return Column("id", Integer, primary_key=True)


def clinic_column(*, primary_key: bool = False) -> Column[int]:
    return Column(
        "clinic_id",
        Integer,
        ForeignKey("clinics.id"),
        nullable=False,
        index=True,
        primary_key=primary_key,
    )


def stamp(name: str, *, nullable: bool = True) -> Column[Any]:
    return Column(name, UtcDateTime(), nullable=nullable)


def enum_check(column: str, values: str) -> CheckConstraint:
    allowed = ", ".join(repr(value) for value in values.split())
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_values")


clinics = Table(
    "clinics",
    metadata,
    id_column(),
    Column("slug", Text, nullable=False, unique=True),
    Column("created_at", UtcDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("name", Text, nullable=False),
    Column("specialty", Text, nullable=False),
    Column("address", Text, nullable=False),
    Column("address_en", Text),
    Column("lat", Float, nullable=False),
    Column("lng", Float, nullable=False),
    Column("phone", Text, nullable=False),
    Column("max_per_evening", Integer),
    Column("usual_visit_min", Integer, nullable=False, server_default="15"),
    Column("cushion_min", Integer, nullable=False, server_default="10"),
    Column("safe_drive_min", Integer, nullable=False, server_default="45"),
    Column("secretary_alerts_on", Boolean, nullable=False, server_default=false()),
    Column("is_sandbox", Boolean, nullable=False, server_default=false()),
    stamp("sandbox_expires_at"),
    Column("clock_offset_s", Integer, nullable=False, server_default="0"),
    Column("judge_id", Text),
    Column("demo_run_active", Boolean, nullable=False, server_default=false()),
    CheckConstraint("cushion_min IN (5, 10, 15)", name="cushion"),
    CheckConstraint("clock_offset_s = 0 OR is_sandbox", name="sandbox_offset"),
    CheckConstraint("max_per_evening IS NULL OR max_per_evening > 0", name="positive_max"),
    CheckConstraint("usual_visit_min > 0", name="positive_visit"),
)
patients = Table(
    "patients",
    metadata,
    id_column(),
    clinic_column(),
    Column("name", Text, nullable=False),
    Column("name_en", Text),
)
contacts = Table(
    "contacts",
    metadata,
    id_column(),
    clinic_column(),
    Column("phone_e164", Text, nullable=False),
    UniqueConstraint("clinic_id", "phone_e164"),
)
pending_signups = Table(
    "pending_signups",
    metadata,
    id_column(),
    Column("mobile_e164", Text, nullable=False),
    Column("nonce", Text, nullable=False, default=lambda: secrets.token_hex(16)),
    stamp("created_at", nullable=False),
    stamp("expires_at", nullable=False),
    stamp("completed_at"),
)
telegram_links = Table(
    "telegram_links",
    metadata,
    Column("phone_e164", Text, primary_key=True),
    Column("kind", String, primary_key=True),
    Column("telegram_chat_id", Text, nullable=False),
    stamp("linked_at", nullable=False),
    enum_check("kind", "doctor patient"),
)
doctors = Table(
    "doctors",
    metadata,
    id_column(),
    clinic_column(),
    Column("name_ar", Text, nullable=False),
    Column("name_en", Text, nullable=False),
    Column("mobile_e164", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("lang", String, nullable=False),
    enum_check("lang", "ar en franco"),
)
clinic_hours = Table(
    "clinic_hours",
    metadata,
    id_column(),
    clinic_column(),
    Column("weekday", Integer, nullable=False),
    Column("start", Time, nullable=False),
    Column("end", Time, nullable=False),
    CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
)
clinic_day_overrides = Table(
    "clinic_day_overrides",
    metadata,
    id_column(),
    clinic_column(),
    Column("date", Date, nullable=False),
    Column("closed", Boolean, nullable=False, server_default=false()),
    Column("start", Time),
    Column("end", Time),
    UniqueConstraint("clinic_id", "date"),
    CheckConstraint('closed OR (start IS NOT NULL AND "end" IS NOT NULL)', name="open_hours"),
)
clinic_info = Table(
    "clinic_info",
    metadata,
    id_column(),
    clinic_column(),
    Column("key", Text, nullable=False),
    Column("text", Text, nullable=False),
    UniqueConstraint("clinic_id", "key"),
)
saved_answers = Table(
    "saved_answers",
    metadata,
    clinic_column(),
    Column("question_norm", Text, nullable=False),
    Column("answer", Text, nullable=False),
    stamp("saved_at", nullable=False),
    UniqueConstraint("clinic_id", "question_norm"),
)
evenings = Table(
    "evenings",
    metadata,
    id_column(),
    clinic_column(),
    Column("date", Date, nullable=False),
    Column("state", String, nullable=False, server_default="scheduled"),
    stamp("doctor_on_way_at"),
    Column("doctor_eta_min", Float),
    stamp("projected_start"),
    stamp("cancelled_at"),
    stamp("closed_at"),
    Column("closed_by", String),
    Column("paper_start", Time),
    Column("paper_end", Time),
    UniqueConstraint("clinic_id", "date"),
    enum_check("state", "scheduled doctor_on_way running closed cancelled"),
    enum_check("closed_by", "doctor auto system_no_taps"),
)
areas = Table(
    "areas",
    metadata,
    id_column(),
    Column("name_ar", Text, nullable=False),
    Column("name_en", Text, nullable=False, unique=True),
    Column("lat", Float, nullable=False),
    Column("lng", Float, nullable=False),
    Column("source", String, server_default="reference"),
)
geocode_cache = Table(
    "geocode_cache",
    metadata,
    Column("query", Text, primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id")),
    stamp("fetched_at", nullable=False),
)
bookings = Table(
    "bookings",
    metadata,
    id_column(),
    clinic_column(),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("patient_id", Integer, ForeignKey("patients.id")),
    Column("contact_id", Integer, ForeignKey("contacts.id")),
    Column("queue_number", Integer, nullable=False),
    Column("order_key", Float, nullable=False),
    Column("source", String, nullable=False),
    Column("lang", String, nullable=False),
    Column("state", String, nullable=False, server_default="booked"),
    stamp("expected_shown"),
    Column("expected_frozen", Boolean, nullable=False, server_default=false()),
    stamp("told_to_leave_at"),
    stamp("on_my_way_at"),
    Column("travel_min", Float),
    Column("link_code_hash", Text),
    Column("area_id", Integer, ForeignKey("areas.id")),
    Column("origin_text", String(40)),
    CheckConstraint(
        "origin_text IS NULL OR (area_id IS NULL AND length(origin_text) <= 40)",
        name="origin_text_unresolved",
    ),
    stamp("created_at", nullable=False),
    Column("silent", Boolean, nullable=False, server_default=false()),
    UniqueConstraint("evening_id", "queue_number"),
    CheckConstraint(
        "source = 'walkin_tap' OR (patient_id IS NOT NULL AND contact_id IS NOT NULL)",
        name="booking_identity",
    ),
    enum_check("source", "chat walkin_tap"),
    enum_check("lang", "ar en franco"),
    enum_check("state", "booked told_to_leave on_my_way seen cancelled didnt_come"),
)
visits = Table(
    "visits",
    metadata,
    id_column(),
    clinic_column(),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("booking_id", Integer, ForeignKey("bookings.id"), nullable=False),
    stamp("started_at", nullable=False),
    stamp("ended_at"),
    Column("accepted", Boolean, nullable=False, server_default=true()),
    Column("est_at_start", Float),
)
evening_taps = Table(
    "evening_taps",
    metadata,
    id_column(),
    clinic_column(),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("booking_id", Integer),
    stamp("at", nullable=False),
    Column("prior_json", JSON, nullable=False),
    Column("after_json", JSON, nullable=False),
    stamp("undone_at"),
    Column("idempotency_key", Text, nullable=False, unique=True),
    enum_check("kind", "doctor_on_way who_comes_in walk_in"),
)
standbys = Table(
    "standbys",
    metadata,
    id_column(),
    clinic_column(),
    Column("date", Date, nullable=False),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("patient_id", Integer, ForeignKey("patients.id"), nullable=False),
    Column("contact_id", Integer, ForeignKey("contacts.id"), nullable=False),
    Column("area_id", Integer, ForeignKey("areas.id")),
    Column("origin_text", String(40)),
    CheckConstraint(
        "origin_text IS NULL OR (area_id IS NULL AND length(origin_text) <= 40)",
        name="origin_text_unresolved",
    ),
    Column("booking_for", String, nullable=False),
    Column("consent_version", Text, nullable=False),
    Column("consent_text_hash", Text, nullable=False),
    stamp("consented_at", nullable=False),
    Column("lang", String, nullable=False),
    Column("position", Integer, nullable=False),
    Column("state", String, nullable=False),
    stamp("created_at", nullable=False),
    stamp("offered_at"),
    stamp("expires_at"),
    Column("offer_code_hash", Text, unique=True),
    stamp("expected_time"),
    Column("booking_id", Integer, ForeignKey("bookings.id")),
    UniqueConstraint("clinic_id", "date", "contact_id"),
    UniqueConstraint("evening_id", "position"),
    enum_check("state", "waiting offered taken expired declined"),
    enum_check("booking_for", "self other"),
    enum_check("lang", "ar en franco"),
)

outbox = Table(
    "outbox",
    metadata,
    id_column(),
    clinic_column(),
    Column("booking_id", Integer, ForeignKey("bookings.id")),
    Column("pending_signup_id", Integer, ForeignKey("pending_signups.id", ondelete="SET NULL")),
    Column("standby_id", Integer, ForeignKey("standbys.id")),
    Column("recipient_kind", String, nullable=False),
    Column("audience", String, nullable=False),
    Column("template_id", Text, nullable=False),
    Column("lang", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("adapter", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("values_json", JSON),
    Column("status", String, nullable=False, server_default="queued"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("provider_ref", Text),
    stamp("next_attempt_at"),
    stamp("created_at", nullable=False),
    enum_check(
        "recipient_kind", "patient_contact standby_contact doctor secretary pending_signup screen"
    ),
    enum_check("audience", "patient doctor secretary"),
    enum_check("lang", "ar en franco"),
    enum_check("channel", "sms telegram"),
    enum_check("adapter", "screen_phone mac_relay telegram we_business"),
    enum_check("status", "queued sent delivered failed blocked_by_brake blocked_unapproved"),
)
timers = Table(
    "timers",
    metadata,
    id_column(),
    clinic_column(),
    Column("kind", String, nullable=False),
    stamp("due_at", nullable=False),
    Column("payload_json", JSON, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    stamp("locked_at"),
    Column("last_error", Text),
    Column("idempotency_key", Text, nullable=False, unique=True),
    enum_check("status", "pending running done cancelled failed"),
    enum_check(
        "kind",
        "travel_check leave_now_check silent_check are_you_on_way evening_auto_close "
        "evening_system_close send_retry delivery_timeout evening_report retention_daily "
        "sandbox_expire pending_signup_purge standby_expire",
    ),
    Index("ix_timers_status_due_at", "status", "due_at"),
)
action_record = Table(
    "action_record",
    metadata,
    id_column(),
    clinic_column(),
    stamp("at", nullable=False),
    Column("actor", String, nullable=False),
    Column("kind", Text, nullable=False),
    Column("booking_id", Integer, ForeignKey("bookings.id")),
    Column("patient_id", Integer, ForeignKey("patients.id")),
    Column("text", Text),
    Column("model", Text),
    Column("commit", Text, nullable=False),
    enum_check("actor", "patient doctor secretary system ai"),
    Index("ix_action_record_clinic_id_at", "clinic_id", "at"),
)
health_record = Table(
    "health_record",
    metadata,
    id_column(),
    clinic_column(),
    stamp("at", nullable=False),
    Column("phone_key", Text, nullable=False),
    Column("kind", String, nullable=False),
    Column("trigger_text", Text, nullable=False),
    Column("reply_text", Text, nullable=False),
    Column("template_version", Text, nullable=False),
    Column("model", Text),
    Column("commit", Text, nullable=False),
    Column("source_url", Text),
    Column("source_title", Text),
    Column("supporting_sentence", Text),
    Column("why", Text),
    enum_check("kind", "triage_emergency triage_urgent health_answer"),
)
daily_totals = Table(
    "daily_totals",
    metadata,
    id_column(),
    clinic_column(),
    Column("date", Date, nullable=False),
    *(
        Column(name, Integer, nullable=False, server_default="0")
        for name in ("booked", "came", "didnt_come", "walkins", "cancelled")
    ),
    Column("avg_wait_min", Float),
    Column("avg_visit_min", Float),
    Column("start_delay_min", Float),
    UniqueConstraint("clinic_id", "date"),
)
learned_pace = Table(
    "learned_pace",
    metadata,
    clinic_column(primary_key=True),
    Column("mean_visit_min", Float, nullable=False),
    Column("n", Integer, nullable=False),
)
learned_start_gap = Table(
    "learned_start_gap",
    metadata,
    clinic_column(primary_key=True),
    Column("mean_min", Float, nullable=False),
    Column("n", Integer, nullable=False),
)
learned_no_show = Table(
    "learned_no_show",
    metadata,
    clinic_column(primary_key=True),
    Column("n", Integer, nullable=False),
    Column("rate", Float, nullable=False),
)
area_hour_travel = Table(
    "area_hour_travel",
    metadata,
    clinic_column(primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id"), primary_key=True),
    Column("weekday", Integer, primary_key=True),
    Column("hour", Integer, primary_key=True),
    Column("mean_min", Float, nullable=False),
    Column("n", Integer, nullable=False),
    CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
    CheckConstraint("hour BETWEEN 0 AND 23", name="hour_range"),
)
travel_estimates = Table(
    "travel_estimates",
    metadata,
    clinic_column(primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id"), primary_key=True),
    Column("minutes", Float),
    Column("source", String, nullable=False),
    Column("fetched_at", UtcDateTime(), nullable=False),
    CheckConstraint("source IN ('mapbox', 'fetching', 'failed')", name="source_values"),
    CheckConstraint(
        "(source IN ('fetching', 'failed') AND minutes IS NULL) "
        "OR (source = 'mapbox' AND minutes IS NOT NULL)",
        name="minutes_source",
    ),
)
consents = Table(
    "consents",
    metadata,
    clinic_column(),
    Column("contact_id", Integer, ForeignKey("contacts.id"), nullable=False),
    Column("booking_id", Integer, ForeignKey("bookings.id"), nullable=False),
    Column("booking_for", String, nullable=False),
    Column("version", Text, nullable=False),
    Column("text_hash", Text, nullable=False),
    stamp("at", nullable=False),
    enum_check("booking_for", "self other"),
)
questions = Table(
    "questions",
    metadata,
    id_column(),
    clinic_column(),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("text_norm", Text, nullable=False),
    Column("text_display", Text),
    Column("count", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("draft_answer", Text),
    stamp("answering_at"),
    stamp("created_at", nullable=False),
    UniqueConstraint("clinic_id", "evening_id", "text_norm"),
    enum_check("status", "open answered later dismissed"),
)
report_questions = Table(
    "report_questions",
    metadata,
    id_column(),
    clinic_column(),
    Column("evening_id", Integer, ForeignKey("evenings.id"), nullable=False),
    Column("question_id", Integer, ForeignKey("questions.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    stamp("sent_at"),
    stamp("resolved_at"),
    Column("resolved_reason", Text),
    UniqueConstraint("evening_id", "question_id"),
)
secretary_links = Table(
    "secretary_links",
    metadata,
    clinic_column(),
    Column("token_hash", Text, nullable=False),
    stamp("used_at"),
    Column("telegram_chat_id", Text),
    stamp("revoked_at"),
)
link_tokens = Table(
    "link_tokens",
    metadata,
    id_column(),
    Column("clinic_id", Integer, ForeignKey("clinics.id"), nullable=True, index=True),
    Column("kind", String, nullable=False),
    Column("subject_id", Integer, nullable=False),
    Column("token_hash", Text, nullable=False),
    stamp("expires_at", nullable=False),
    stamp("used_at"),
    enum_check("kind", "doctor_telegram patient_telegram signup_telegram reset_telegram"),
    CheckConstraint(
        "clinic_id IS NOT NULL OR kind IN ('signup_telegram', 'reset_telegram')",
        name="clinic_scope",
    ),
)
# Public claims are created before /start. NULL chat keeps attempt counts on detached claims.
telegram_pending = Table(
    "telegram_pending",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("chat_id", Text, nullable=True, unique=True),
    Column("attempts", Integer, nullable=False, server_default="0"),
    stamp("created_at", nullable=False),
    Column("lang", Text, nullable=False, server_default="ar"),
    CheckConstraint("attempts BETWEEN 0 AND 2", name="attempts_range"),
    enum_check("lang", "ar en franco"),
)
rate_counters = Table(
    "rate_counters",
    metadata,
    Column("scope", Text, primary_key=True),
    Column("key_hash", Text, primary_key=True),
    Column("window_start", UtcDateTime(), primary_key=True),
    Column("window_s", Integer, nullable=False),
    Column("count", Integer, nullable=False),
)
idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    id_column(),
    clinic_column(),
    Column("key", Text, nullable=False, unique=True),
    Column("command", Text, nullable=False),
    Column("result_json", JSON, nullable=False),
    stamp("created_at", nullable=False),
)
usage = Table(
    "usage",
    metadata,
    Column("date", Date, nullable=False),
    clinic_column(),
    Column("judge_id", Text, nullable=False, server_default=text("''")),
    Column("service", String, nullable=False),
    Column("units", Integer, nullable=False),
    Column("est_cost_usd", Float, nullable=False),
    UniqueConstraint("date", "clinic_id", "judge_id", "service"),
    enum_check("service", "ai sms mapbox mapbox_geocode telegram"),
)

doctor_sessions = Table(
    "doctor_sessions",
    metadata,
    id_column(),
    clinic_column(),
    Column("doctor_id", Integer, ForeignKey("doctors.id"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("csrf_hash", Text, nullable=False),
    stamp("created_at", nullable=False),
    stamp("expires_at", nullable=False),
    stamp("last_seen_at", nullable=False),
    stamp("revoked_at"),
)
auth_codes = Table(
    "auth_codes",
    metadata,
    id_column(),
    clinic_column(),
    Column("purpose", String, nullable=False),
    Column("phone_key", Text, nullable=False),
    Column("code_hash", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    stamp("created_at", nullable=False),
    stamp("expires_at", nullable=False),
    stamp("used_at"),
    Column("pending_signup_id", Integer, ForeignKey("pending_signups.id", ondelete="CASCADE")),
    enum_check("purpose", "reset signup"),
)
Index(
    "ix_auth_codes_phone_key_purpose_created_at",
    auth_codes.c.phone_key,
    auth_codes.c.purpose,
    auth_codes.c.created_at,
)

chat_sessions = Table(
    "chat_sessions",
    metadata,
    id_column(),
    clinic_column(),
    Column("session_key_hash", Text, nullable=False, unique=True),
    Column("lang", String, nullable=False),
    Column("state", String, nullable=False),
    Column("emergency_kind", String),
    Column("contact_id", Integer, ForeignKey("contacts.id")),
    Column("patient_id", Integer, ForeignKey("patients.id")),
    Column("last_booking_id", Integer, ForeignKey("bookings.id")),
    Column("draft", Text),
    stamp("consent_other_at"),
    Column("ai_msg_count", Integer, nullable=False, server_default="0"),
    Column("turn_seq", Integer, nullable=False, server_default="0"),
    Column("last_safe_turn_seq", Integer, nullable=False, server_default="0"),
    stamp("created_at", nullable=False),
    stamp("last_turn_at"),
    enum_check("lang", "ar en franco"),
    enum_check("state", "open locked_emergency"),
    enum_check("emergency_kind", "general eye_chemical eye filler labour"),
)
judge_counters = Table(
    "judge_counters",
    metadata,
    Column("judge_id", Text, primary_key=True),
    Column("ai_msgs", Integer, nullable=False, server_default="0"),
    stamp("updated_at", nullable=False),
)
verify_attempts = Table(
    "verify_attempts",
    metadata,
    id_column(),
    clinic_column(),
    Column("key_hash", Text, nullable=False),
    stamp("at", nullable=False),
    Index("ix_verify_attempts_key_hash_at", "key_hash", "at"),
)

library_passages = Table(
    "library_passages",
    metadata,
    id_column(),
    Column("specialty", Text, nullable=False, index=True),
    Column("site", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("embedding_json", JSON, nullable=False),
    Column("embedding_model", Text, nullable=False),
    Column("passage_key", Text, nullable=False, unique=True),
    Column("fetched_at", UtcDateTime(), nullable=False),
)

agreement_acceptances = Table(
    "agreement_acceptances",
    metadata,
    clinic_column(primary_key=True),
    Column("doctor_id", Integer, ForeignKey("doctors.id"), primary_key=True),
    Column("version", Text, primary_key=True),
    Column("text_hash", Text, nullable=False),
    stamp("at", nullable=False),
)
deleted_slugs = Table(
    "deleted_slugs",
    metadata,
    Column("slug", Text, primary_key=True),
    stamp("deleted_at", nullable=False),
)


demo_runs = Table(
    "demo_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    clinic_column(),
    Column("kind", Text, nullable=False),
    Column("step", Integer, nullable=False, server_default="0"),
    Column("visit_index", Integer, nullable=False, server_default="0"),
    Column("minute", Integer, nullable=False, server_default="0"),
    stamp("started_at", nullable=False),
    stamp("last_step_at", nullable=False),
    enum_check("kind", "watch public"),
    CheckConstraint("minute BETWEEN 0 AND 600", name="minute_range"),
)

question_askers = Table(
    "question_askers",
    metadata,
    id_column(),
    clinic_column(),
    Column("question_id", Integer, ForeignKey("questions.id"), nullable=False),
    Column("patient_id", Integer, ForeignKey("patients.id")),
    Column("booking_id", Integer, ForeignKey("bookings.id")),
    Column("chat_session_id", Text, nullable=False),
    stamp("asked_at", nullable=False),
    UniqueConstraint("question_id", "chat_session_id"),
)
