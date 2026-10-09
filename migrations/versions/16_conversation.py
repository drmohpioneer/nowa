"""Session drafts and grouped question askers (add-only)."""

import sqlalchemy as sa
from alembic import op

revision = "16"
down_revision = "15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("draft", sa.Text(), nullable=True))
    op.create_table(
        "question_askers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=True),
        sa.Column("chat_session_id", sa.Text(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("question_id", "chat_session_id"),
    )
    op.create_index("ix_question_askers_clinic_id", "question_askers", ["clinic_id"])


def downgrade() -> None:
    op.drop_table("question_askers")
    op.drop_column("chat_sessions", "draft")
