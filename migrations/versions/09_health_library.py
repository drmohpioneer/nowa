import sqlalchemy as sa
from alembic import op

revision = "09"
down_revision = "08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_passages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("specialty", sa.Text(), nullable=False),
        sa.Column("site", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("passage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_library_passages_specialty", "library_passages", ["specialty"])


def downgrade() -> None:
    op.drop_table("library_passages")
