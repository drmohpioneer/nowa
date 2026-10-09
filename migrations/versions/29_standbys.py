"""Day standby entries and outbox recipients ."""

import sqlalchemy as sa
from alembic import op

from nowa.db import UtcDateTime

revision = "29"
down_revision = "28"
branch_labels = None
depends_on = None


TIMER_KINDS = "travel_check leave_now_check silent_check are_you_on_way evening_auto_close evening_system_close send_retry delivery_timeout evening_report retention_daily sandbox_expire pending_signup_purge"


def timer_constraint(extra: str) -> None:
    allowed = ", ".join(repr(k) for k in (TIMER_KINDS + extra).split())
    with op.batch_alter_table("timers") as batch:
        batch.drop_constraint(op.f("ck_timers_kind_values"), type_="check")
        batch.create_check_constraint("kind_values", f"kind IN ({allowed})")


def upgrade() -> None:
    timer_constraint(" standby_expire")
    op.create_table(
        "standbys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("evening_id", sa.Integer(), sa.ForeignKey("evenings.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id")),
        sa.Column("booking_for", sa.String(), nullable=False),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("consent_text_hash", sa.Text(), nullable=False),
        sa.Column("consented_at", UtcDateTime(), nullable=False),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("offered_at", UtcDateTime()),
        sa.Column("expires_at", UtcDateTime()),
        sa.Column("offer_code_hash", sa.Text(), unique=True),
        sa.Column("expected_time", UtcDateTime()),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id")),
        sa.UniqueConstraint("clinic_id", "date", "contact_id"),
        sa.UniqueConstraint("evening_id", "position"),
        sa.CheckConstraint(
            "state IN ('waiting', 'offered', 'taken', 'expired', 'declined')", name="state_values"
        ),
        sa.CheckConstraint("booking_for IN ('self', 'other')", name="booking_for_values"),
        sa.CheckConstraint("lang IN ('ar', 'en', 'franco')", name="lang_values"),
    )
    op.create_index("ix_standbys_clinic_id", "standbys", ["clinic_id"])
    with op.batch_alter_table("outbox") as batch:
        batch.add_column(sa.Column("standby_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_outbox_standby_id_standbys", "standbys", ["standby_id"], ["id"]
        )
        batch.drop_constraint(op.f("ck_outbox_recipient_kind_values"), type_="check")
        batch.create_check_constraint(
            "recipient_kind_values",
            "recipient_kind IN ('patient_contact', 'standby_contact', 'doctor', 'secretary', 'pending_signup', 'screen')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM timers WHERE kind = 'standby_expire'")
    timer_constraint("")
    op.execute("DELETE FROM outbox WHERE standby_id IS NOT NULL")
    with op.batch_alter_table("outbox") as batch:
        batch.drop_constraint(op.f("ck_outbox_recipient_kind_values"), type_="check")
        batch.create_check_constraint(
            "recipient_kind_values",
            "recipient_kind IN ('patient_contact', 'doctor', 'secretary', 'pending_signup', 'screen')",
        )
        batch.drop_constraint("fk_outbox_standby_id_standbys", type_="foreignkey")
        batch.drop_column("standby_id")
    op.drop_table("standbys")
