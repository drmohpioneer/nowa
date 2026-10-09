"""name_en."""

import sqlalchemy as sa
from alembic import op

revision = "27a"
down_revision = "16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("name_en", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "name_en")
