"""Durable demo replay state."""
import sqlalchemy as sa
from alembic import op

revision = "12"
down_revision = "11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visit_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_step_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('watch', 'public')", name="kind_values"),
        sa.CheckConstraint("minute BETWEEN 0 AND 600", name="minute_range"),
    )
    op.create_index("ix_demo_runs_clinic_id", "demo_runs", ["clinic_id"])


def downgrade() -> None:
    op.drop_table("demo_runs")
