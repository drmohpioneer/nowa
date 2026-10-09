"""Origin labels from real authenticated endpoints through the shipped DOM code."""

import json
import subprocess
from pathlib import Path

import pytest

from nowa import schema as s
from nowa.db import write_tx
from nowa.web.strings import DOCTOR_TEXTS
from tests.web.test_doctor_web import post
from tests.web.test_doctor_web import web as web_fixture

web = web_fixture
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("lang,note", [("ar", "خارج القايمة"), ("en", "not on the list")])
def test_board_and_report_origin_dom(web, engine, lang, note):
    client, _, eid, _, ids = web
    text = "<script>Fictional</script>"
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(origin_text=text))
    data = client.get("/d/api/tonight", params={"lang": lang}).json()
    assert data["rows"][0]["origin_display"] == f"{text} ({note})"
    assert data["rows"][1]["origin_display"] == ""
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    preview = client.get("/d/api/close/preview").json()
    assert post(client, "close", {"expected_untold": preview["untold_count"]}).json()["ok"]
    response = client.get(f"/d/api/report/{eid}", params={"lang": lang})
    assert response.status_code == 200
    built = response.json()
    assert built["origins"] == [{"queue_number": 1, "origin_display": f"{text} ({note})"}]
    result = subprocess.run(
        ["node", "tests/web/origins_dom.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        input=json.dumps(
            {
                "board": data,
                "report": built,
                "texts": {k: v[lang == "en"] for k, v in DOCTOR_TEXTS.items()},
            }
        ),
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    client.cookies.clear()
    assert client.get(f"/d/api/report/{eid}").status_code == 401
