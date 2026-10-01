from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from nowa import record
from nowa import schema as s
from nowa.clock import CAIRO, ClinicOffsetClock, FrozenClock
from nowa.db import write_tx
from nowa.demo.copy import create_demo_copy
from nowa.library.store import load


@pytest.fixture
def demo_clock(engine):
    load(
        engine,
        "cardiology",
        Path(__file__).resolve().parents[2] / "nowa/library/data/cardiology.jsonl",
    )
    clock = ClinicOffsetClock(FrozenClock(datetime(2026, 10, 1, 5, tzinfo=CAIRO)), engine)
    record.configure(clock)
    return clock


@pytest.fixture
def new_run(engine, demo_clock):
    def create(key="fixture-run", ip="fixture"):
        cid = create_demo_copy(engine, demo_clock, "watch", ip)
        with write_tx(engine) as conn:
            conn.execute(
                s.demo_runs.insert().values(
                    run_id=key,
                    clinic_id=cid,
                    kind="watch",
                    step=0,
                    visit_index=0,
                    minute=0,
                    started_at=demo_clock.now(cid),
                    last_step_at=demo_clock.now(cid),
                )
            )
        return cid

    return create


@pytest.fixture
def demo_setup(new_run, demo_clock):
    return new_run(), demo_clock


@pytest.fixture
def demo_client(engine, demo_clock):
    from fastapi.testclient import TestClient

    from nowa.app import create_app

    with TestClient(create_app(engine, clock=demo_clock)) as client:
        yield client


def bookings(engine, cid):
    with engine.connect() as conn:
        return {
            r["queue_number"]: dict(r)
            for r in conn.execute(
                select(s.bookings).where(s.bookings.c.clinic_id == cid)
            ).mappings()
        }
