"""Persist resolved outbox recipient kind ."""

from alembic import op
from sqlalchemy import Column, String, text

revision = "02"
down_revision = "01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", Column("recipient_kind", String, nullable=True))
    op.execute(
        text(
            "UPDATE outbox SET recipient_kind = CASE "
            "WHEN pending_signup_id IS NOT NULL THEN 'pending_signup' "
            "WHEN audience = 'patient' THEN 'patient_contact' "
            "ELSE audience END"
        )
    )
    with op.batch_alter_table("outbox") as batch:
        batch.alter_column("recipient_kind", existing_type=String(), nullable=False)
    with op.batch_alter_table("outbox") as batch:
        batch.create_check_constraint(
            op.f("ck_outbox_recipient_kind_values"),
            "recipient_kind IN "
            "('patient_contact', 'doctor', 'secretary', 'pending_signup', 'screen')",
        )


def downgrade() -> None:
    with op.batch_alter_table("outbox") as batch:
        batch.drop_constraint(op.f("ck_outbox_recipient_kind_values"), type_="check")
        batch.drop_column("recipient_kind")
