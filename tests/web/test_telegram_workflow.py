"""offline presentation and contact-proof status regressions."""

import base64
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from nowa.app import create_app
from nowa.config import get_settings
from nowa.telegram import linking
from nowa.web import strings

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = {"Origin": "http://127.0.0.1:8000"}


@pytest.fixture
def web(engine, frozen_clock):
    get_settings().telegram_bot_username = "fictional_bot"
    with TestClient(
        create_app(engine, clock=frozen_clock), base_url="http://127.0.0.1:8000"
    ) as client:
        yield client


def issue(web):
    response = web.post("/signup/code", json={"mobile": "01000000005"}, headers=ORIGIN)
    assert response.status_code == 200
    return response.json()["telegram_url"]


def status(web, url, qr=False):
    response = web.post("/telegram/link-status", json={"url": url, "qr": qr}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_a_same_link_server_qr(web):
    from tests.web.test_signup import decode_svg

    url = issue(web)
    data = status(web, url, True)
    raw = base64.b64decode(data["qr"].split(",", 1)[1])
    assert decode_svg(raw.decode()) == url
    assert b'xmlns="http://www.w3.org/2000/svg"' in raw
    assert data["remaining_seconds"] == 900


def test_b_expiry_renewal_keeps_signup_limits(web, frozen_clock):
    first = issue(web)
    frozen_clock.advance(minutes=15)
    assert status(web, first)["status"] == "expired"
    second = issue(web)
    assert second != first
    assert status(web, second)["remaining_seconds"] == 900
    issue(web)
    assert (
        web.post("/signup/code", json={"mobile": "01000000005"}, headers=ORIGIN).status_code == 429
    )


def test_c_mismatch_poll_and_ownership_budget(web, engine, frozen_clock):
    url = issue(web)
    payload = parse_qs(urlsplit(url).query)["start"][0]
    assert linking.consume(engine, frozen_clock, "123", payload, "start") == "share_contact"
    assert (
        linking.prove_contact(engine, frozen_clock, "123", 123, 999, "201000000005", "forwarded")
        == "contact_mismatch"
    )
    assert status(web, url)["status"] == "contact_mismatch"
    assert (
        linking.prove_contact(engine, frozen_clock, "123", 123, 123, "201000000006", "wrong")
        == "contact_mismatch"
    )
    assert status(web, url)["usable"] is False
    assert (
        linking.prove_contact(engine, frozen_clock, "123", 123, 123, "201000000005", "burned")
        == "bad_link"
    )


def test_c_success_is_not_confused_with_burned_token(web, engine, frozen_clock):
    url = issue(web)
    payload = parse_qs(urlsplit(url).query)["start"][0]
    linking.consume(engine, frozen_clock, "123", payload, "start")
    assert (
        linking.prove_contact(engine, frozen_clock, "123", 123, 123, "201000000005", "proof")
        == "code_sent"
    )
    assert status(web, url)["status"] == "linked"
    assert "01000000005" not in str(status(web, url))


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_c_copy_explains_mismatch(lang):
    assert strings.text("tg.contact_mismatch", lang) == strings.text(
        "patient.telegram_mismatch", lang
    )
    assert len(strings.text("tg.contact_mismatch", lang)) > 70


def test_status_rejects_origin_and_arbitrary_urls(web):
    url = issue(web)
    assert web.post("/telegram/link-status", json={"url": url}).status_code == 403
    for bad in ("https://evil.test/a", "https://t.me/other?start=p_abc", "javascript:alert(1)"):
        assert (
            web.post("/telegram/link-status", json={"url": bad}, headers=ORIGIN).status_code == 422
        )


@pytest.mark.parametrize("width", [390, 900, 1280])
def test_abc_offline_dom(width):
    result = subprocess.run(
        ["node", "tests/web/linking_workflow_dom.cjs", str(width)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_patient_link_offline_dom():
    result = subprocess.run(
        ["node", "tests/web/patient_linking_dom.cjs"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
