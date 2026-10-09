"""address_en."""

import sqlalchemy as sa
from alembic import op

revision = "27c"
down_revision = "27b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("address_en", sa.Text(), nullable=True))
    # Preserve the old single address, then promote the existing Arabic entry.
    op.execute("UPDATE clinics SET address_en = address")
    op.execute(
        "UPDATE clinics SET address = COALESCE((SELECT NULLIF(TRIM(text), '') "
        "FROM clinic_info WHERE clinic_info.clinic_id = clinics.id "
        "AND clinic_info.key = 'address'), address)"
    )
    op.execute("DELETE FROM clinic_info WHERE key = 'address'")


def downgrade() -> None:
    op.execute(
        "INSERT INTO clinic_info (clinic_id, key, text) SELECT id, 'address', address "
        "FROM clinics WHERE slug <> '_nowa' AND NOT EXISTS (SELECT 1 FROM clinic_info "
        "WHERE clinic_info.clinic_id = clinics.id AND clinic_info.key = 'address')"
    )
    op.execute("UPDATE clinics SET address = COALESCE(address_en, address)")
    op.drop_column("clinics", "address_en")
