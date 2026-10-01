"""Doctor tap history and visit estimates."""

import sqlalchemy as sa
from alembic import op

revision = "04"
down_revision = "02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visits", sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("visits", sa.Column("est_at_start", sa.Float(), nullable=True))
    op.create_table(
        "evening_taps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("evening_id", sa.Integer(), sa.ForeignKey("evenings.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prior_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.CheckConstraint(
            "kind IN ('doctor_on_way', 'who_comes_in', 'walk_in')", name="kind_values"
        ),
    )
    op.create_index("ix_evening_taps_clinic_id", "evening_taps", ["clinic_id"])


def downgrade() -> None:
    op.drop_table("evening_taps")
    with op.batch_alter_table("visits") as batch:
        batch.drop_column("est_at_start")
        batch.drop_column("accepted")
