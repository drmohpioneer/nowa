import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from nowa.web.strings import text
from tests.core.support import row
from tests.web.test_doctor_web import headers, other_clinic, post
from tests.web.test_doctor_web import web as web


def test_doctor_arrived_routes_are_scoped_replayable_and_separate(web, engine):
    client, cid, eid, clock, ids = web
    first = post(client, "arrived", {"booking_id": ids[0]}).json()
    assert first["ok"]
    clock.advance(minutes=1)
    assert post(client, "arrived", {"booking_id": ids[0]}).json() == first
    snapshot = client.get("/d/api/tonight").json()
    assert snapshot["rows"][0]["arrived_at"]
    assert not snapshot["can_undo"]
    assert post(client, "arrived/undo", {"booking_id": ids[0]}).json()["ok"]
    assert row(engine, s.bookings, ids[0])["arrived_at"] is None
    _, foreign_eid, foreign_bid = other_clinic(engine, clock)
    assert post(client, "arrived", {"booking_id": foreign_bid}, "foreign").status_code == 404
    assert (
        post(
            client, "arrived", {"booking_id": ids[0], "evening_id": foreign_eid}, "foreign-e"
        ).status_code
        == 404
    )
    with engine.connect() as conn:
        assert not conn.execute(select(s.evening_taps)).first()


@pytest.mark.parametrize("route", ["arrived", "arrived/undo", "wind-down"])
def test_new_commands_require_doctor_session_and_csrf(web, engine, route):
    client, cid, eid, clock, ids = web
    payload = (
        {"idempotency_key": "unauthorized", "booking_id": ids[0]}
        if route != "wind-down"
        else {"idempotency_key": "unauthorized", "expected_untold": 6}
    )
    bad_headers = headers(client) | {"X-CSRF-Token": "wrong"}
    assert client.post("/d/api/" + route, json=payload, headers=bad_headers).status_code == 403
    client.cookies.clear()
    assert client.post("/d/api/" + route, json=payload, headers=bad_headers).status_code == 401


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_board_flow_words_available_in_all_languages(web, engine, lang):
    client, cid, eid, clock, ids = web
    for key in (
        "silent",
        "told_to_leave",
        "on_my_way",
        "arrived",
        "mark_arrived",
        "undo_arrived",
        "cover_limit",
        "wind_down",
        "winding_down",
        "wind_down_confirm",
        "close_groups",
    ):
        assert text("doctor." + key, lang)
    assert post(client, "arrived", {"booking_id": ids[0]}).json()["ok"]
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(covers_used=3))
    snapshot = client.get("/d/api/tonight").json()
    assert snapshot["cover_cap_reached"]
    assert snapshot["rows"][0]["arrived_at"]


def test_web_wind_down_and_close_preview(web, engine):
    client, cid, eid, clock, ids = web
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[-1]).values(state="booked"))
    preview = client.get("/d/api/close/preview").json()
    assert set(preview) >= {
        "untold",
        "told",
        "passed",
        "untold_count",
        "told_count",
        "passed_count",
    }
    assert preview["untold"][0]["patient_name"]
    assert post(client, "wind-down", {"expected_untold": 99}, "stale").status_code == 409
    assert post(client, "wind-down", {"expected_untold": preview["untold_count"]}).json()["ok"]
    assert client.get("/d/api/tonight").json()["evening_state"] == "winding_down"
    assert post(client, "close", {"expected_untold": 0}).json()["ok"]
    assert timing.close_preview(engine, clock, cid, eid).untold_count == 0


def test_shipped_evening_controls_and_close_lists(web, engine):
    import json
    import subprocess
    from datetime import timedelta
    from pathlib import Path

    from nowa.web.strings import DOCTOR_TEXTS

    client, cid, eid, clock, ids = web
    states = [client.get("/d/api/tonight").json()]
    assert post(client, "arrived", {"booking_id": ids[1]}).json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    with write_tx(engine) as conn:
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(covers_used=3))
        for bid, state, delta in (
            (ids[2], "told_to_leave", -1),
            (ids[3], "on_my_way", 30),
            (ids[-1], "booked", 60),
        ):
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(state=state, expected_shown=clock.now(cid) + timedelta(minutes=delta))
            )
    states.append(client.get("/d/api/tonight").json())
    preview = client.get("/d/api/close/preview").json()
    assert post(client, "wind-down", {"expected_untold": preview["untold_count"]}).json()["ok"]
    states.append(client.get("/d/api/tonight").json())
    result = subprocess.run(
        ["node", "tests/web/evening_flow33_dom.cjs"],
        input=json.dumps(
            {
                "states": states,
                "preview": preview,
                "texts": {k: v[1] for k, v in DOCTOR_TEXTS.items()},
            }
        ),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
