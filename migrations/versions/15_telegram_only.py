"""Telegram claims and contact proof; legacy message rows remain readable."""

import sqlalchemy as sa
from alembic import op

revision = "15"
down_revision = "12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("link_tokens") as batch:
        batch.drop_constraint(op.f("ck_link_tokens_kind_values"), type_="check")
        batch.create_check_constraint(
            "kind_values",
            "kind IN ('doctor_telegram', 'patient_telegram', 'signup_telegram', 'reset_telegram')",
        )
        batch.alter_column("clinic_id", existing_type=sa.Integer(), nullable=True)
        batch.create_check_constraint(
            "clinic_scope", "clinic_id IS NOT NULL OR kind IN ('signup_telegram', 'reset_telegram')"
        )
    op.create_table(
        "telegram_pending",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("chat_id", sa.Text(), nullable=True, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lang", sa.Text(), nullable=False, server_default="ar"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 2", name="attempts_range"),
        sa.CheckConstraint("lang IN ('ar', 'en', 'franco')", name="lang_values"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if (
        conn.execute(
            sa.text(
                "SELECT 1 FROM link_tokens WHERE kind IN ('signup_telegram','reset_telegram') "
                "OR clinic_id IS NULL"
            )
        ).first()
        or conn.execute(sa.text("SELECT 1 FROM telegram_pending")).first()
    ):
        raise RuntimeError("Cannot downgrade while Telegram contact claims exist")
    op.drop_table("telegram_pending")
    with op.batch_alter_table("link_tokens") as batch:
        batch.drop_constraint(op.f("ck_link_tokens_clinic_scope"), type_="check")
        batch.drop_constraint(op.f("ck_link_tokens_kind_values"), type_="check")
        batch.create_check_constraint(
            "kind_values", "kind IN ('doctor_telegram', 'patient_telegram')"
        )
        batch.alter_column("clinic_id", existing_type=sa.Integer(), nullable=False)
