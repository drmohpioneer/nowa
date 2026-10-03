"""The v2 public entrances and the real replay payload, no provider calls."""

import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from nowa import schema as s
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core.report import build_report
from nowa.demo.runner import EveningRunner
from nowa.web.request import page_language
from nowa.web.strings import ACTION_SENTENCES, UI_TEXTS
from tests.demo.test_web import HEADERS, start


@pytest.mark.parametrize(
    "query,header,expected",
    [
        ("lang=ar", "en-US,en;q=0.8", "ar"),
        ("lang=en", "ar-EG", "en"),
        ("", "fr-FR,ar;q=0.9", "en"),
        ("", "AR-eg,en", "ar"),
        ("", "", "ar"),
        ("lang=xx", "en", "en"),
        ("lang=xx", "", "ar"),
    ],
)
def test_page_language(query, header, expected):
    request = Request(
        {
            "type": "http",
            "query_string": query.encode(),
            "headers": [(b"accept-language", header.encode())],
        }
    )
    assert page_language(request) == expected


def test_public_entrances(demo_client, monkeypatch):
    front = BeautifulSoup(demo_client.get("/?lang=ar").text, "html.parser")
    assert not front.find("form")
    assert front.select_one('a[href="/demo?lang=ar"]')
    assert front.select_one('a[href="/start?lang=ar"]')
    assert "هنقولك على تليجرام امتى تتحرك" in front.get_text()
    hub = BeautifulSoup(demo_client.get("/demo?lang=en").text, "html.parser")
    assert len(hub.select(".door")) == 4
    assert len(hub.select('a[href="/demo/evening?lang=en"]')) == 2
    assert hub.select_one('a[href="/d/login?lang=en"]')
    assert hub.select_one('form[action="/demo/book?lang=en"][method="post"]')
    assert "+201000000001" in hub.get_text()
    assert (
        demo_client.post("/demo/book", headers={"Origin": "https://foreign.test"}).status_code
        == 403
    )
    signup = demo_client.get("/start?lang=en")
    assert signup.status_code == 200
    assert signup.text == demo_client.get("/signup?lang=en").text
    for ident in ("code-form", "verify-form", "complete-form", "signup-phone", "signup-success"):
        assert f'id="{ident}"' in signup.text
    monkeypatch.setenv("JUDGE_CODES", "")
    get_settings.cache_clear()
    assert demo_client.get("/judge").status_code == 404
    monkeypatch.setenv("JUDGE_CODES", "fictional-v2-judge")
    get_settings.cache_clear()
    judge = BeautifulSoup(demo_client.get("/judge").text, "html.parser")
    assert len(judge.find_all("form")) == 1
    assert judge.select_one("#judge-form")
    assert not judge.select_one("#code-form")


def test_hub_not_registered_outside_demo(engine, demo_clock, monkeypatch):
    # Reuse explicit test secrets so production config stays valid without an env install.
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", False)
    with TestClient(create_app(engine, clock=demo_clock)) as client:
        assert client.get("/demo").status_code == 404


@pytest.mark.parametrize(
    "path", ["/", "/demo", "/start", "/signup", "/judge", "/demo/evening", "/demo/book"]
)
def test_english_static_text_and_arabic_direction(demo_client, monkeypatch, path):
    monkeypatch.setenv("JUDGE_CODES", "fictional-v2-judge")
    get_settings.cache_clear()
    en = BeautifulSoup(demo_client.get(path + "?lang=en").text, "html.parser")
    assert en.html["lang"] == "en" and en.html["dir"] == "ltr"
    # Hidden translations and the approved agreement belong to later signup steps,
    # not the initial English page. Patient identities are permitted runtime data.
    for node in en.select("[hidden],script,style"):
        node.decompose()
    assert not re.search(r"[\u0600-\u06ff]", en.get_text())
    ar = demo_client.get(path + "?lang=ar")
    assert 'lang="ar" dir="rtl"' in ar.text
    assert 'lang="en"' in demo_client.get(path, headers={"Accept-Language": "en-US"}).text


def test_full_replay_report_and_action_coverage(demo_client, engine, demo_clock):
    run = start(demo_client, "ui-v2-replay-intent")
    url = "/demo/evening/" + run["run_id"]
    initial = demo_client.get(url + "/state", params={"token": run["token"]}).json()
    assert "report" not in initial
    assert set(initial["clinic"]) == {"name", "specialty", "area"}
    assert initial["evening"] == {"first_minute": 0, "last_minute": 600, "weekday": 1}
    stages = {"initial": initial}
    for label, minute in (("on_way", 190), ("active", 235)):
        stages[label] = demo_client.post(
            url + "/advance", json={"token": run["token"], "to_minute": minute}, headers=HEADERS
        ).json()
    result = demo_client.post(
        url + "/advance", json={"token": run["token"], "to_minute": 600}, headers=HEADERS
    )
    assert result.status_code == 200
    payload = result.json()
    assert payload["closed"] and payload["report"]
    with engine.connect() as conn:
        cid, eid = conn.execute(select(s.evenings.c.clinic_id, s.evenings.c.id)).one()
        expected = asdict(build_report(conn, demo_clock, cid, eid))
    assert payload["report"] == {key: expected[key] for key in payload["report"]}
    assert set(payload["report"]) == {"booked", "came", "no_show_count", "walk_ins", "avg_wait"}
    stages["closed"] = payload
    stages["texts"] = {key: value[1] for key, value in UI_TEXTS.items()}
    rendered = subprocess.run(
        ["node", "tests/web/evening_dom.cjs"],
        input=json.dumps(stages),
        text=True,
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    kinds = {event["kind"] for event in payload["timeline"]}
    assert kinds <= ACTION_SENTENCES.keys(), kinds - ACTION_SENTENCES.keys()
    for kind in kinds:
        key = ACTION_SENTENCES[kind]
        assert UI_TEXTS[key][0] and UI_TEXTS[key][1]
    # This is the existing loss of booking IDs, not a UI-invented patient binding.
    assert all(
        event["booking_id"] is None
        for event in payload["timeline"]
        if event["kind"] == "who_comes_in"
    )


def test_state_before_runner_start_has_no_report(engine, demo_setup):
    cid, clock = demo_setup
    assert "report" not in EveningRunner(cid, engine=engine, clock=clock).state()
