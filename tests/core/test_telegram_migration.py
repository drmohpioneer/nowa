"""A populated old head upgrades without rewriting legacy deliveries or credentials."""

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from nowa import schema as s
from nowa.__main__ import migrate, migration_config
from nowa.db import create_db_engine


def test_head12_preserves_token_and_enforces_new_claim_scope(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'telegram-upgrade.db'}")
    config = migration_config()
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "12")
            conn.exec_driver_sql(
                "INSERT INTO link_tokens(clinic_id,kind,subject_id,token_hash,expires_at) "
                "VALUES (1,'patient_telegram',7,'fictional-hash','2026-10-03 16:00:00')"
            )
            original = conn.exec_driver_sql("SELECT * FROM link_tokens").all()
        migrate(engine)
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT * FROM link_tokens").all() == original
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert next(
                c for c in inspect(conn).get_columns("link_tokens") if c["name"] == "clinic_id"
            )["nullable"]
        for kind in ("signup_telegram", "reset_telegram"):
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT INTO link_tokens(kind,subject_id,token_hash,expires_at) "
                    "VALUES (?,7,?,'2026-10-03 16:00:00')",
                    (kind, kind),
                )
        for kind in ("patient_telegram", "doctor_telegram", "invalid"):
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT INTO link_tokens(kind,subject_id,token_hash,expires_at) "
                    "VALUES (?,7,?,'2026-10-03 16:00:00')",
                    (kind, kind),
                )
        with pytest.raises(RuntimeError, match="contact claims exist"), engine.begin() as conn:
            config.attributes["connection"] = conn
            command.downgrade(config, "12")
        with engine.connect() as conn:
            assert len(conn.execute(select(s.link_tokens)).all()) == 3
            head = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            assert head == "15"
    finally:
        engine.dispose()
