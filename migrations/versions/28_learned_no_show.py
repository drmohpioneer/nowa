"""Clinic no-show learning ."""

import sqlalchemy as sa
from alembic import op

revision = "28"
down_revision = "27c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learned_no_show",
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), primary_key=True),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
    )
    op.create_index("ix_learned_no_show_clinic_id", "learned_no_show", ["clinic_id"])


def downgrade() -> None:
    op.drop_table("learned_no_show")
