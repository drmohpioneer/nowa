"""Bounded origin geocoding and permanent query cache ."""

import sqlalchemy as sa
from alembic import op

from nowa.db import UtcDateTime

revision = "31"
down_revision = "29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("bookings", "standbys"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("origin_text", sa.String(40)))
            batch.create_check_constraint(
                "origin_text_unresolved",
                "origin_text IS NULL OR (area_id IS NULL AND length(origin_text) <= 40)",
            )
    op.add_column("areas", sa.Column("source", sa.String(), server_default="reference"))
    op.create_table(
        "geocode_cache",
        sa.Column("query", sa.Text(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id")),
        sa.Column("fetched_at", UtcDateTime(), nullable=False),
    )
    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint(op.f("ck_usage_service_values"), type_="check")
        batch.create_check_constraint(
            "service_values", "service IN ('ai', 'sms', 'mapbox', 'mapbox_geocode', 'telegram')"
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM usage WHERE service = 'mapbox_geocode' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade while geocoding usage exists")
    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint(op.f("ck_usage_service_values"), type_="check")
        batch.create_check_constraint(
            "service_values", "service IN ('ai', 'sms', 'mapbox', 'telegram')"
        )
    for table in ("standbys", "bookings"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(op.f(f"ck_{table}_origin_text_unresolved"), type_="check")
            batch.drop_column("origin_text")
    op.drop_table("geocode_cache")
    with op.batch_alter_table("areas") as batch:
        batch.drop_column("source")
