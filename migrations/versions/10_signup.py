import secrets

import sqlalchemy as sa
from alembic import op

revision = "10"
down_revision = "09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pending_signups", sa.Column("nonce", sa.Text(), nullable=True))
    pending = sa.table("pending_signups", sa.column("id"), sa.column("nonce"))
    for row_id in op.get_bind().execute(sa.select(pending.c.id)).scalars():
        op.execute(pending.update().where(pending.c.id == row_id).values(nonce=secrets.token_hex(16)))
    with op.batch_alter_table("pending_signups") as batch:
        batch.alter_column("nonce", existing_type=sa.Text(), nullable=False)
    # Recreate on SQLite: ADD COLUMN cannot use a nonconstant default on populated tables.
    with op.batch_alter_table(
        "clinics", recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto"
    ) as batch:
        batch.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
    op.create_table(
        "agreement_acceptances",
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), primary_key=True),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctors.id"), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agreement_acceptances_clinic_id", "agreement_acceptances", ["clinic_id"])
    op.create_table(
        "deleted_slugs",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    clinic = sa.table(
        "clinics",
        *(sa.column(k) for k in ("slug", "name", "specialty", "address", "lat", "lng", "phone")),
    )
    op.execute(
        clinic.insert().values(
            slug="_nowa", name="Nowa", specialty="system", address="", lat=0, lng=0, phone=""
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("pending_signups") as batch:
        batch.drop_column("nonce")
    op.drop_table("agreement_acceptances")
    op.drop_table("deleted_slugs")
    op.execute(sa.text("DELETE FROM clinics WHERE slug = '_nowa'"))
    with op.batch_alter_table("clinics") as batch:
        batch.drop_column("created_at")
