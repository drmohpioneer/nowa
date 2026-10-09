"""FIX 1 regressions over real taps and the authorized read-only UI views."""

from datetime import datetime

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.demo import evening_script as script
from tests.demo.test_web import HEADERS, start


@pytest.mark.parametrize("fractional_seconds", [0, 0.5])
def test_stage_room_timeline_labels_and_replay_bounds(
    demo_client, engine, demo_clock, fractional_seconds
):
    demo_clock.base.advance(minutes=fractional_seconds / 60)
    run = start(demo_client, "ui-v2-fix-replay-intent")
    url = "/demo/evening/" + run["run_id"]
    initial = demo_client.get(url + "/state", params={"token": run["token"]}).json()
    assert initial["in_room"] is None
    assert (
        initial["evening"]["start_minute"] == min(script.CANCEL_MINUTE, script.ON_WAY_MINUTE) - 10
    )
    assert datetime.fromisoformat(initial["evening"]["start_at"]).strftime("%H:%M") == "18:20"
    active = demo_client.post(
        url + "/advance", json={"token": run["token"], "to_minute": 250}, headers=HEADERS
    ).json()
    assert active["in_room"]["first_name"] == "نور حسن"
    response = demo_client.get("/d/api/tonight", headers={"Cookie": "nowa_session=" + run["token"]})
    assert response.status_code == 200, response.text
    board = response.json()
    assert board["in_room"] == active["in_room"]
    assert board["doctor"]["on_way_at"] and board["doctor"]["arrived_at"]
    closed = demo_client.post(
        url + "/advance", json={"token": run["token"], "to_minute": 600}, headers=HEADERS
    ).json()
    assert closed["in_room"] is None
    with engine.connect() as conn:
        taps = conn.execute(select(s.evening_taps).order_by(s.evening_taps.c.id)).mappings().all()
        patient_results = (
            conn.execute(
                select(s.idempotency_keys.c.result_json)
                .where(s.idempotency_keys.c.command == "patient_on_my_way")
                .order_by(s.idempotency_keys.c.id)
            )
            .scalars()
            .all()
        )
    who = [event for event in closed["timeline"] if event["kind"] == "who_comes_in"]
    assert [event["booking"]["booking_id"] for event in who] == [
        tap["booking_id"] for tap in taps if tap["kind"] in {"who_comes_in", "walk_in"}
    ]
    way = [event for event in closed["timeline"] if event["kind"] == "patient_on_my_way"]
    assert [event["booking"]["booking_id"] for event in way] == [
        result["booking_id"] for result in patient_results
    ]
    assert all(
        event["booking"]["first_name"]
        for event in who + way
        if event["booking"]["source"] != "walkin_tap"
    )
    assert any(event["booking"]["source"] == "walkin_tap" for event in who)
    from nowa.web.strings import UI_TEXTS

    for lang in ("ar", "en"):
        payload = demo_client.get(
            url + "/state", params={"token": run["token"], "lang": lang}
        ).json()
        for msg in payload["phones"]:
            assert msg["label"] in UI_TEXTS
            assert UI_TEXTS[msg["label"]][0] and UI_TEXTS[msg["label"]][1]


def test_every_known_outbox_template_has_bilingual_label():
    from nowa.messaging.templates import OPERATIONAL, TEMPLATES
    from nowa.web.strings import MESSAGE_LABELS, UI_TEXTS

    assert set(MESSAGE_LABELS) == {key[0] for key in TEMPLATES} | {
        "op:" + key for key in OPERATIONAL
    }
    for key in MESSAGE_LABELS.values():
        assert UI_TEXTS[key][0] and UI_TEXTS[key][1]
    assert MESSAGE_LABELS.get("unknown") is None
