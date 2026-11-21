from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import select

from nowa import schema as s
from nowa.__main__ import migrate, migration_config
from nowa.db import write_tx
from tests.core.support import setup


def test_evening_migration_preserves_existing_rows_and_has_one_head(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    config = migration_config()
    # Build the exact preceding schema with populated fictional rows.
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        config.attributes["connection"] = conn
        command.downgrade(config, "31")
        before = {
            name: conn.exec_driver_sql(f"SELECT * FROM {name} ORDER BY id").mappings().all()
            for name in ("evenings", "bookings")
        }
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
    migrate(engine)
    assert ScriptDirectory.from_config(migration_config()).get_heads() == ["33"]
    with engine.connect() as conn:
        for name, added, default in (
            ("evenings", "covers_used", 0),
            ("bookings", "arrived_at", None),
        ):
            after = conn.exec_driver_sql(f"SELECT * FROM {name} ORDER BY id").mappings().all()
            assert [{k: v for k, v in r.items() if k != added} for r in after] == [
                dict(r) for r in before[name]
            ]
            assert all(r[added] == default for r in after)
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(state="winding_down"))
        conn.execute(
            s.bookings.update().where(s.bookings.c.id == ids[0]).values(arrived_at=clock.now(cid))
        )
    with engine.connect() as conn:
        assert conn.execute(
            select(s.bookings.c.arrived_at).where(s.bookings.c.id == ids[0])
        ).scalar_one() == clock.now(cid)
