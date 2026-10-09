"""values_json."""

import sqlalchemy as sa
from alembic import op

revision = "27b"
down_revision = "27a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("values_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox", "values_json")
