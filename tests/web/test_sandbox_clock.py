"""Clock presentation must not become the input to sandbox time commands."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from nowa import schema as s
from nowa.app import create_app
from nowa.clock import CAIRO, ClinicOffsetClock, FrozenClock
from nowa.db import write_tx
from tests.core.support import setup
from tests.web.support import ORIGIN
from tests.web.test_doctor_web import post

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("lang", ["ar", "en"])
@pytest.mark.parametrize("timezone", ["UTC", "America/Los_Angeles"])
def test_sandbox_clock_localized_initial_advance_and_jump(engine, lang, timezone):
    cid, *_ = setup(engine, count=1)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=True))
    clock = ClinicOffsetClock(FrozenClock(datetime(2026, 10, 13, 22, 40, tzinfo=CAIRO)), engine)
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        assert client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        ).status_code == 200
        page = client.get("/d", params={"lang": lang})
        assert page.status_code == 200
        soup = BeautifulSoup(page.text, "html.parser")
        node = soup.select_one("#sandbox-clock")
        initial_iso = clock.now(cid).isoformat()
        assert node["data-iso"] == initial_iso
        assert initial_iso not in node.get_text()
        scripts = [script["src"] for script in soup.select("script[src]")]
        assert scripts.index("/static/clock.js") < scripts.index("/static/dashboard.js")
        snapshots = []
        for index, minutes in enumerate((10, 60, 180, 10)):
            response = post(client, "sandbox/advance", {"minutes": minutes}, f"clock:{index}")
            assert response.status_code == 200
            snapshots.append(response.json())
            assert datetime.fromisoformat(snapshots[-1]["now"]) == clock.now(cid)

    result = subprocess.run(
        ["node", "tests/web/sandbox_clock_dom.cjs"],
        input=json.dumps({
            "lang": lang,
            "iso": node["data-iso"],
            "initial_text": node.get_text(),
            "texts": {
                item["data-key"]: item.get_text()
                for item in soup.select("#translations [data-key]")
            },
            "snapshots": snapshots,
        }),
        cwd=ROOT, env=os.environ | {"TZ": timezone},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
