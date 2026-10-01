"""One contact per clinic and phone (Decision 052)."""

from alembic import op

revision = "01"
down_revision = "00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.create_unique_constraint("uq_contacts_clinic_id", ["clinic_id", "phone_e164"])


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.drop_constraint("uq_contacts_clinic_id", type_="unique")
