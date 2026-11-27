from datetime import timedelta
from html import unescape

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import booking, flows, timing
from nowa.db import write_tx
from nowa.web.strings import text
from tests.core.support import DAY, row
from tests.web.support import fields
from tests.web.test_doctor_web import headers, other_clinic, post
from tests.web.test_doctor_web import web as web
from tests.web.test_patient_link import page as page
from tests.web.test_patient_link import post as patient_post


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_same_day_change_refused_without_new_rows(page, engine, lang):
    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(lang=lang))
    path = f"/l/{code}/change"
    opened = client.get(path)
    response = patient_post(
        client, path, fields(opened, path) | {"last4": "0000", "date": DAY.isoformat()}
    )
    assert text("patient.same_day", lang) in unescape(response.text)
    with engine.connect() as conn:
        assert len(conn.execute(select(s.bookings)).all()) == 2
    assert row(engine, s.bookings, ids[0])["state"] == "booked"


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_rebook_page_names_existing_booking(page, engine, lang):
    client, cid, eid, clock, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(lang=lang))
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    token = timing.request_cancel_tonight(engine, clock, cid, eid, did)
    timing.cancel_tonight(engine, clock, cid, eid, did, token, "cancel")
    result = flows.rebook(engine, clock, ids[0], DAY + timedelta(days=2), "new")
    response = client.get(f"/r/{code}")
    assert text("patient.already_rebooked", lang) in unescape(response.text)
    assert f"/l/{booking.link_code_for(result.booking_id)}" in response.text
    assert 'button name="date"' not in response.text


def test_arrived_close_409_and_pause_routes(web, engine):
    client, cid, eid, clock, ids = web
    post(client, "who-comes-in", {"booking_id": ids[0]})
    post(client, "arrived", {"booking_id": ids[1]})
    preview = client.get("/d/api/close/preview").json()
    assert preview["arrived_count"] == 1
    response = post(client, "close", {"expected_untold": preview["untold_count"]})
    assert response.status_code == 409 and response.json()["reason"] == "arrived_present"
    assert response.json()["arrived_count"] == 1
    assert post(client, "pause").json()["ok"]
    since = client.get("/d/api/tonight").json()["paused_since"]
    clock.advance(minutes=10)
    assert post(client, "pause").json()["ok"]
    assert client.get("/d/api/tonight").json()["paused_since"] == since
    assert post(client, "resume").json()["ok"]
    assert client.get("/d/api/tonight").json()["paused_since"] is None
    for route in ("pause", "resume"):
        assert (
            client.post(
                "/d/api/" + route,
                json={"idempotency_key": "bad"},
                headers=headers(client) | {"X-CSRF-Token": "bad"},
            ).status_code
            == 403
        )
    _, foreign_eid, _ = other_clinic(engine, clock)
    assert post(client, "pause", {"evening_id": foreign_eid}, "foreign").status_code == 404
    client.cookies.clear()
    assert (
        client.post(
            "/d/api/pause",
            json={"idempotency_key": "anonymous"},
            headers={"Origin": "http://127.0.0.1:8000"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "route,body",
    [
        ("pause", {"evening_id": 2**70}),
        ("on-my-way", {"area_id": 2**70}),
        ("who-comes-in", {"booking_id": 2**70}),
        ("arrived", {"booking_id": 2**70}),
    ],
)
def test_body_ids_have_database_bounds(web, route, body):
    client, *_ = web
    assert post(client, route, body).status_code == 422


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_timing_capacity_cannot_drop_below_booked(web, engine, lang):
    client, cid, eid, clock, ids = web
    body = {
        "idempotency_key": "smaller",
        "usual_visit_min": 15,
        "cushion_min": 10,
        "safe_drive_min": 45,
        "max_per_evening": 5,
    }
    response = client.put("/d/api/settings/timing", json=body, headers=headers(client))
    assert response.status_code == 422 and response.json()["reason"] == "below_booked"
    assert row(engine, s.clinics, cid)["max_per_evening"] is None
    assert text("doctor.below_booked", lang)
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="cancelled"))
    body["idempotency_key"] = "fits"
    assert client.put("/d/api/settings/timing", json=body, headers=headers(client)).json()["ok"]
