"""Evening cover budget, patient arrival flag and wind-down state."""

import sqlalchemy as sa
from alembic import op

from nowa.db import UtcDateTime

revision = "33"
down_revision = "31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("arrived_at", UtcDateTime(), nullable=True))
    with op.batch_alter_table("evenings") as batch:
        batch.add_column(sa.Column("covers_used", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_constraint(op.f("ck_evenings_state_values"), type_="check")
        batch.create_check_constraint(
            "state_values",
            "state IN ('scheduled', 'doctor_on_way', 'running', 'winding_down', 'closed', 'cancelled')",
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM evenings WHERE state = 'winding_down' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade an evening while it is winding down")
    with op.batch_alter_table("evenings") as batch:
        batch.drop_constraint(op.f("ck_evenings_state_values"), type_="check")
        batch.create_check_constraint(
            "state_values",
            "state IN ('scheduled', 'doctor_on_way', 'running', 'closed', 'cancelled')",
        )
        batch.drop_column("covers_used")
    with op.batch_alter_table("bookings") as batch:
        batch.drop_column("arrived_at")
