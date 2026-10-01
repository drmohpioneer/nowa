import os
from datetime import datetime

import pytest
from alembic import command

from nowa import record
from nowa.__main__ import migrate, migration_config
from nowa.clock import CAIRO, ClinicOffsetClock, FrozenClock
from nowa.config import get_settings
from nowa.db import create_db_engine, write_tx
from nowa.demo.template import CLINIC
from nowa.library.answer import get_library_engine
from nowa.library.models import library_version
from nowa.schema import clinics


@pytest.fixture(autouse=True)
def settings_env(monkeypatch, tmp_path):
    for name in (
        "WORKER_IN_PROCESS",
        "RENDER",
        "DATABASE_URL",
        "DEMO_MODE",
        "PUBLIC_BASE_URL",
        "TRUSTED_PROXY_HOPS",
        "SERVER_SECRET",
        "LINK_SECRET",
        "LIBRARY_MIN_SCORE",
        "LIBRARY_DATA_DIR",
        "EMBEDDING_USD_PER_CALL",
        "AI_RATES_JSON",
        "AI_CHAIN",
        "RENDER_GIT_COMMIT",
        "DEMO_DOCTOR_PASSWORD",
        "SMS_PART_COST_USD",
        "SMS_ADAPTER",
        "MAC_RELAY_TOKEN",
        "MAC_RELAY_ALLOWLIST",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "TELEGRAM_BOT_USERNAME",
        "NOWA_RELAY_URL",
        "MAPBOX_USD_PER_CALL",
        "MAPBOX_TOKEN",
        "MAPBOX_TIMEOUT_S",
        "DEMO_NO_NETWORK",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "JUDGE_AI_MSG_CAP",
        "AI_DAILY_BUDGET_USD",
        "AI_CLINIC_DAILY_CEILING",
    ):
        monkeypatch.delenv(name, raising=False)
    library_data = tmp_path / "empty-library-data"
    library_data.mkdir()
    monkeypatch.setenv("LIBRARY_DATA_DIR", str(library_data))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("SERVER_SECRET", "test-server-" * 4)
    monkeypatch.setenv("LINK_SECRET", "test-link-" * 4)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_library_engine.cache_clear()
    library_version.cache_clear()
    yield
    if get_library_engine.cache_info().currsize:
        get_library_engine().dispose()
    get_library_engine.cache_clear()
    library_version.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def engine(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    migrate(engine)
    # Reference loading reads settings; tests may override env after this fixture.
    get_settings.cache_clear()
    yield engine
    engine.dispose()


@pytest.fixture
def frozen_clock():
    clock = FrozenClock(datetime(2026, 9, 30, 19, tzinfo=CAIRO))
    record.configure(clock)
    return clock


@pytest.fixture
def offset_clock(engine, frozen_clock):
    return ClinicOffsetClock(frozen_clock, engine)


@pytest.fixture
def clinic_id(engine):
    with write_tx(engine) as conn:
        return conn.execute(
            clinics.insert().values(**CLINIC["clinic"]).returning(clinics.c.id)
        ).scalar_one()


@pytest.fixture
def postgres_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if "CI" in os.environ:
            pytest.fail("TEST_DATABASE_URL is required when CI is set")
        pytest.skip("TEST_DATABASE_URL is not set locally")
    engine = create_db_engine(url)
    config = migration_config()
    # This fixture owns the disposable CI test database, never DATABASE_URL.
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "base")
    migrate(engine)
    # Reference loading reads settings; tests may override env after this fixture.
    get_settings.cache_clear()
    yield engine
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "base")
    engine.dispose()
