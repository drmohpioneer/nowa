"""Evening pauses and durable first-attempt delivery accounting."""

import sqlalchemy as sa
from alembic import op

from nowa.db import UtcDateTime

revision = "34"
down_revision = "33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evening_pauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("evening_id", sa.Integer(), sa.ForeignKey("evenings.id"), nullable=False),
        sa.Column("started_at", UtcDateTime(), nullable=False),
        sa.Column("ended_at", UtcDateTime()),
        sa.Column("by", sa.Text(), nullable=False),
        sa.CheckConstraint("by IN ('doctor', 'secretary', 'system')", name="by_values"),
    )
    op.create_index("ix_evening_pauses_clinic_id", "evening_pauses", ["clinic_id"])
    op.create_index(
        "ix_evening_pauses_open",
        "evening_pauses",
        ["evening_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )
    op.add_column("visits", sa.Column("paused_min", sa.Float(), nullable=False, server_default="0"))
    with op.batch_alter_table("outbox") as batch:
        batch.add_column(sa.Column("first_attempt_at", UtcDateTime()))
        batch.drop_constraint(op.f("ck_outbox_status_values"), type_="check")
        batch.create_check_constraint(
            "status_values",
            "status IN ('queued', 'sent', 'delivered', 'failed', 'blocked_by_brake', "
            "'blocked_unapproved', 'superseded')",
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM outbox WHERE status = 'superseded' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade superseded messages")
    with op.batch_alter_table("outbox") as batch:
        batch.drop_constraint(op.f("ck_outbox_status_values"), type_="check")
        batch.create_check_constraint(
            "status_values",
            "status IN ('queued', 'sent', 'delivered', 'failed', 'blocked_by_brake', "
            "'blocked_unapproved')",
        )
        batch.drop_column("first_attempt_at")
    with op.batch_alter_table("visits") as batch:
        batch.drop_column("paused_min")
    op.drop_index("ix_evening_pauses_open", table_name="evening_pauses")
    op.drop_index("ix_evening_pauses_clinic_id", table_name="evening_pauses")
    op.drop_table("evening_pauses")
