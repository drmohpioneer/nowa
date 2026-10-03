"""UI tap views do not alter deterministic booking states."""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from nowa import schema as s
from tests.web.test_doctor_web import post
from tests.web.test_doctor_web import web as shared_web


@pytest.fixture
def web(engine, monkeypatch):
    yield from shared_web.__wrapped__(engine, monkeypatch)


def test_room_latest_undo_walkin_close_and_doctor_state(web, engine):
    client, cid, eid, clock, ids = web

    def state():
        response = client.get("/d/api/tonight")
        assert response.status_code == 200
        return response.json()

    assert state()["in_room"] is None
    assert state()["doctor"] == {"on_way_at": None, "arrived_at": None}
    assert post(client, "on-my-way", {"area_id": 1}).json()["ok"]
    assert datetime.fromisoformat(state()["doctor"]["on_way_at"]) == clock.now(cid)
    assert state()["doctor"]["arrived_at"] is None
    clock.advance(minutes=12)
    assert post(client, "who-comes-in", {"booking_id": ids[0]}, "first").json()["ok"]
    first = state()["in_room"]
    assert first == {
        "booking_id": ids[0],
        "queue_number": 1,
        "first_name": "Fictional",
        "since": state()["doctor"]["arrived_at"],
    }
    assert datetime.fromisoformat(first["since"]) == clock.now(cid)
    assert state()["doctor"]["arrived_at"] == first["since"]
    clock.advance(minutes=12)
    assert post(client, "who-comes-in", {"booking_id": ids[1]}, "second").json()["ok"]
    assert state()["in_room"]["booking_id"] == ids[1]
    assert post(client, "undo", key="undo-second").json()["ok"]
    assert state()["in_room"] == first
    assert post(client, "who-comes-in", {"walk_in": True}, "walkin").json()["ok"]
    walk = state()["in_room"]
    assert walk["queue_number"] == 7 and walk["first_name"] is None
    assert post(client, "undo", key="undo-walkin").json()["ok"]
    assert state()["in_room"] == first
    preview = client.get("/d/api/close/preview").json()
    assert post(client, "close", {"expected_untold": preview["untold_count"]}).json()["ok"]
    assert state()["in_room"] is None
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.bookings.c.state).where(s.bookings.c.id == ids[0])).scalar_one()
            == "seen"
        )


def test_doctor_state_restores_button_after_undo(web):
    client, _, _, _, _ = web
    assert post(client, "on-my-way", {"area_id": 1}).json()["ok"]
    assert post(client, "undo").json()["ok"]
    assert client.get("/d/api/tonight").json()["doctor"] == {"on_way_at": None, "arrived_at": None}


def test_doctor_board_renders_real_state_and_undo(web):
    from nowa.web.strings import DOCTOR_TEXTS

    client, _, _, clock, ids = web
    states = [client.get("/d/api/tonight").json()]
    assert post(client, "on-my-way", {"area_id": 1}).json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    clock.advance(minutes=12)
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    assert post(client, "undo", key="undo-arrival").json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    assert post(client, "undo", key="undo-way").json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    result = subprocess.run(
        ["node", "tests/web/doctor_board_dom.cjs"],
        input=json.dumps(
            {"states": states, "texts": {key: value[1] for key, value in DOCTOR_TEXTS.items()}}
        ),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
