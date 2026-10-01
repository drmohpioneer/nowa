import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.ai.adapters import FixtureAdapter
from nowa.app import create_app
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.seed import seed
from tests.ai.support import output


@pytest.fixture
def chat(engine, frozen_clock, monkeypatch):
    # The no-argument health factory opens the configured database independently
    # during its transaction-free phase; point it at this fixture's migrated DB.
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    get_settings.cache_clear()
    seed(engine)
    with write_tx(engine) as conn:
        clinic = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(is_sandbox=True, judge_id="fictional-judge")
        )
    app = create_app(engine, clock=frozen_clock)
    app.state.ai_chain = [FixtureAdapter(output())]
    with TestClient(app) as client:
        yield client, app, clinic
