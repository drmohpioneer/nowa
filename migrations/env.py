from alembic import context

from nowa import schema  # noqa: F401
from nowa.db import create_db_engine, metadata

config = context.config


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use an online migration connection")
connection = config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    engine = create_db_engine()
    with engine.connect() as connection:
        run_migrations(connection)
    engine.dispose()
