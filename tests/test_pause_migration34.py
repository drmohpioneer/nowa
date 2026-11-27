import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nowa import schema as s
from nowa.__main__ import migrate, migration_config
from nowa.core import timing
from nowa.db import write_tx
from tests.core.support import move, setup


def test_pause_upgrade_preserves_populated_rows_and_constraints(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    move(clock, 0)
    timing.who_comes_in(engine, clock, cid, eid, ids[0], False, "first")
    config = migration_config()
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        config.attributes["connection"] = conn
        command.downgrade(config, "33")
        before = {
            name: [
                dict(r)
                for r in conn.exec_driver_sql(f"SELECT * FROM {name} ORDER BY id").mappings()
            ]
            for name in ("visits", "outbox", "bookings", "evenings")
        }
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
    migrate(engine)
    assert ScriptDirectory.from_config(migration_config()).get_heads() == ["34"]
    with write_tx(engine) as conn:
        for name in before:
            rows = conn.exec_driver_sql(f"SELECT * FROM {name} ORDER BY id").mappings().all()
            assert [
                {k: v for k, v in r.items() if k not in {"paused_min", "first_attempt_at"}}
                for r in rows
            ] == before[name]
        assert conn.execute(select(s.visits.c.paused_min)).scalar_one() == 0
        assert not conn.execute(
            select(s.outbox).where(s.outbox.c.first_attempt_at.is_not(None))
        ).first()
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()
        values = dict(clinic_id=cid, evening_id=eid, started_at=clock.now(cid), by="doctor")
        conn.execute(s.evening_pauses.insert().values(**values))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(s.evening_pauses.insert().values(**values))
        conn.execute(s.evening_pauses.update().values(ended_at=clock.now(cid)))
        conn.execute(s.evening_pauses.insert().values(**values))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                s.evening_pauses.insert().values(
                    **(values | {"by": "patient", "ended_at": clock.now(cid)})
                )
            )
        conn.execute(s.outbox.update().values(status="superseded"))
