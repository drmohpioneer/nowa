import sqlalchemy as sa
from alembic import op

revision = "06"
down_revision = "04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doctor_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_doctor_sessions_clinic_id", "doctor_sessions", ["clinic_id"])
    op.create_table(
        "auth_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("phone_key", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "pending_signup_id",
            sa.Integer(),
            sa.ForeignKey("pending_signups.id", ondelete="CASCADE"),
        ),
        sa.CheckConstraint("purpose IN ('reset', 'signup')", name="purpose_values"),
    )
    op.create_index("ix_auth_codes_clinic_id", "auth_codes", ["clinic_id"])
    op.create_index(
        "ix_auth_codes_phone_key_purpose_created_at",
        "auth_codes",
        ["phone_key", "purpose", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("auth_codes")
    op.drop_table("doctor_sessions")
