import sqlalchemy as sa
from alembic import op

revision = "08"
down_revision = "13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("session_key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("emergency_kind", sa.String()),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id")),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id")),
        sa.Column("last_booking_id", sa.Integer(), sa.ForeignKey("bookings.id")),
        sa.Column("consent_other_at", sa.DateTime(timezone=True)),
        sa.Column("ai_msg_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("turn_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_safe_turn_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_turn_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("lang IN ('ar', 'en', 'franco')", name="lang_values"),
        sa.CheckConstraint("state IN ('open', 'locked_emergency')", name="state_values"),
        sa.CheckConstraint(
            "emergency_kind IN ('general', 'eye_chemical', 'eye', 'filler', 'labour')",
            name="emergency_kind_values",
        ),
    )
    op.create_index("ix_chat_sessions_clinic_id", "chat_sessions", ["clinic_id"])
    op.create_table(
        "judge_counters",
        sa.Column("judge_id", sa.Text(), primary_key=True),
        sa.Column("ai_msgs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "verify_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_verify_attempts_clinic_id", "verify_attempts", ["clinic_id"])
    op.create_index("ix_verify_attempts_key_hash_at", "verify_attempts", ["key_hash", "at"])


def downgrade() -> None:
    for name in ("verify_attempts", "judge_counters", "chat_sessions"):
        op.drop_table(name)
