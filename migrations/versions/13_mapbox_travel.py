import sqlalchemy as sa
from alembic import op

revision = "13"
down_revision = "06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM area_hour_travel")
    with op.batch_alter_table("area_hour_travel") as batch:
        batch.add_column(sa.Column("clinic_id", sa.Integer(), nullable=False))
        batch.create_foreign_key(
            "fk_area_hour_travel_clinic_id_clinics", "clinics", ["clinic_id"], ["id"]
        )
        batch.drop_constraint("pk_area_hour_travel", type_="primary")
        batch.create_primary_key("pk_area_hour_travel", ["clinic_id", "area_id", "weekday", "hour"])
        batch.create_index("ix_area_hour_travel_clinic_id", ["clinic_id"])
    op.create_table(
        "travel_estimates",
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), primary_key=True),
        sa.Column("minutes", sa.Float()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('mapbox', 'fetching', 'failed')", name="source_values"),
        sa.CheckConstraint(
            "(source IN ('fetching', 'failed') AND minutes IS NULL) "
            "OR (source = 'mapbox' AND minutes IS NOT NULL)",
            name="minutes_source",
        ),
    )
    op.create_index("ix_travel_estimates_clinic_id", "travel_estimates", ["clinic_id"])


def downgrade() -> None:
    op.drop_table("travel_estimates")
    op.execute("DELETE FROM area_hour_travel")
    with op.batch_alter_table("area_hour_travel") as batch:
        batch.drop_index("ix_area_hour_travel_clinic_id")
        batch.drop_constraint("fk_area_hour_travel_clinic_id_clinics", type_="foreignkey")
        batch.drop_constraint("pk_area_hour_travel", type_="primary")
        batch.drop_column("clinic_id")
        batch.create_primary_key("pk_area_hour_travel", ["area_id", "weekday", "hour"])
