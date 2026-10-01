import logging

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nowa import schema as s
from nowa.__main__ import migrate
from nowa.app import create_app
from nowa.db import create_db_engine, metadata, write_tx
from nowa.demo.template import CLINIC
from nowa.reference import AREAS, REFERENCE_LOADERS, load_reference
from nowa.seed import seed


def counts(engine):
    with engine.connect() as conn:
        return {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in metadata.tables.values()
        }


def test_seed_golden_idempotency_and_health(engine, monkeypatch, caplog):
    monkeypatch.setenv("DEMO_DOCTOR_PASSWORD", "fictional-test-password")
    seed(engine)
    first = counts(engine)
    seed(engine)
    assert counts(engine) == first
    with engine.connect() as conn:
        clinic = (
            conn.execute(select(s.clinics).where(s.clinics.c.slug == "dr-hesham")).mappings().one()
        )
        assert clinic["slug"] == "dr-hesham"
        assert (clinic["max_per_evening"], clinic["usual_visit_min"], clinic["clock_offset_s"]) == (
            30,
            15,
            0,
        )
        doctor = conn.execute(select(s.doctors)).mappings().one()
        assert doctor["name_ar"] == "هشام مصطفى" and doctor["name_en"] == "Hesham Mostafa"
        assert PasswordHasher().verify(doctor["password_hash"], "fictional-test-password")
        hours = conn.execute(select(s.clinic_hours)).mappings().all()
        assert {row["weekday"] for row in hours} == {6, 1, 3}
        assert all(row["start"].hour == 19 and row["end"].hour == 23 for row in hours)
        assert conn.execute(select(s.learned_pace.c.mean_visit_min)).scalar_one() == 13.3
        assert conn.execute(select(s.learned_start_gap.c.mean_min)).scalar_one() == 8
    with caplog.at_level(logging.WARNING), TestClient(create_app(engine)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "db": True,
            "commit": "local",
            "worker": {"last_run_at": None, "overdue": 0},
        }
        client.get("/health")
    assert sum("AI_RATES_JSON" in message for message in caplog.messages) == 1


def test_seed_checks_slug_not_empty_table(engine):
    with write_tx(engine) as conn:
        assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]
    seed(engine)
    seed(engine)
    with engine.connect() as conn:
        assert set(conn.execute(select(s.clinics.c.slug)).scalars()) == {"_nowa", "dr-hesham"}
        assert len(conn.execute(select(s.doctors)).all()) == 1


def test_reference_migration_idempotency_and_registered_loader(engine):
    calls = []

    def loader(db):
        with db.connect() as conn:
            assert len(conn.execute(select(s.areas)).all()) == 12
        calls.append(db)

    REFERENCE_LOADERS.append(loader)
    try:
        migrate(engine)
        migrate(engine)
        assert calls == [engine, engine]
        with engine.connect() as conn:
            rows = conn.execute(
                select(s.areas.c.name_en, s.areas.c.name_ar, s.areas.c.lat, s.areas.c.lng)
            ).all()
            assert set(rows) == set(AREAS)
            assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]
        with write_tx(engine) as conn:
            conn.execute(s.areas.update().where(s.areas.c.name_en == "Heliopolis").values(lat=0))
        load_reference(engine)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    select(s.areas.c.lat).where(s.areas.c.name_en == "Heliopolis")
                ).scalar_one()
                == 30.0911
            )
    finally:
        REFERENCE_LOADERS.remove(loader)


def test_reference_in_production_and_seed_refused(engine, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nowa.example")
    # The migration helper operates on the supplied test engine; production config is active.
    migrate(engine)
    assert counts(engine)["areas"] == 12
    with pytest.raises(ValueError, match="DEMO_MODE"):
        seed(engine)
    assert counts(engine)["clinics"] == 1
    with engine.connect() as conn:
        assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]


def test_health_proves_schema_read(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'unmigrated.db'}")
    try:
        with TestClient(create_app(engine)) as client:
            response = client.get("/health")
            assert response.status_code == 503
            assert response.json() == {"ok": False}
    finally:
        engine.dispose()


def test_sqlite_pragmas_and_transaction_rollback(engine):
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    with pytest.raises(RuntimeError), write_tx(engine) as conn:
        conn.execute(s.clinics.insert().values(**CLINIC["clinic"]))
        raise RuntimeError("rollback")
    assert counts(engine)["clinics"] == 1
    with engine.connect() as conn:
        assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]
