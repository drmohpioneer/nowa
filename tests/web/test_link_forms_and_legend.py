"""Offline rendering and shipped-script checks for the link forms and the legend."""

import re
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.app import create_app
from nowa.core import booking, timing
from nowa.db import write_tx
from nowa.messaging import templates
from nowa.web.strings import STRINGS
from tests.core.support import setup
from tests.web.support import ORIGIN, fields

ROOT = Path(__file__).resolve().parents[2]


def test_franco_uses_rakam():
    texts = [value["franco"] for value in STRINGS.values() if "franco" in value]
    texts += [
        value
        for table in (templates.TEMPLATES, templates.EMERGENCY)
        for (_, lang), value in table.items()
        if lang == "franco"
    ]

    # Operational templates nest their multilingual text one level deeper.
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "franco" and isinstance(item, str):
                    texts.append(item)
                else:
                    collect(item)

    collect(templates.OPERATIONAL)
    assert all("ra2m" not in text.lower() for text in texts)


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
@pytest.mark.parametrize("mode", ["change", "rebook", "cancel"])
def test_wrong_last4_redirect_keeps_form_and_selected_day(engine, lang, mode):
    cid, eid, clock, ids = setup(engine, count=1)
    code = booking.link_code_for(ids[0])
    with write_tx(engine) as conn:
        values = dict(lang=lang)
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(**values))
    if mode == "rebook":
        with engine.connect() as conn:
            doctor = conn.execute(
                select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)
            ).scalar_one()
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel-evening").ok
    path = (
        f"/r/{code}"
        if mode == "rebook"
        else f"/l/{code}/change"
        if mode == "change"
        else f"/l/{code}"
    )
    action = f"/l/{code}/cancel" if mode == "cancel" else path
    with TestClient(create_app(engine, clock=clock)) as client:
        opened = client.get(path)
        soup = BeautifulSoup(opened.text, "html.parser")
        selected = soup.select("button[name=date]")[-1]["value"] if mode != "cancel" else None
        for attempt in range(6):
            data = fields(opened, action) | {"last4": "9999"}
            if selected:
                data["date"] = selected
            opened = client.post(action, data=data, headers=ORIGIN)
            assert opened.status_code == 200 and opened.history[-1].status_code == 303
            soup = BeautifulSoup(opened.text, "html.parser")
            form = soup.find("form", action=action)
            reason = "verify_failed" if attempt < 5 else "locked"
            error = form.select_one(".field-error")
            assert error and error.get_text(strip=True) == STRINGS["patient." + reason][lang]
            assert form.select_one("input[name=last4]").get("value", "") == ""
            if mode == "cancel":
                assert form.find_parent("details").has_attr("open")
            else:
                assert form.select_one("button[aria-pressed=true]")["value"] == selected
        with engine.connect() as conn:
            row = conn.execute(select(s.bookings).where(s.bookings.c.id == ids[0])).mappings().one()
            assert row["evening_id"] == eid
            assert row["state"] == ("cancelled" if mode == "rebook" else "booked")


def test_telegram_css_has_measurable_shared_rhythm():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    assert re.search(r"\.tg-bubble\{[^}]*padding:10px 14px;[^}]*line-height:1\.6[;}]", css)
    assert re.search(r"\.tg-bubble p\{[^}]*margin:0", css)
    assert re.search(r"\.feed-list[^}]*gap:12px", css)
    assert re.search(r"\.tg-body[^}]*gap:12px", css)
    assert re.search(r"\.phone\.thread\{[^}]*gap:12px", css)
    assert re.search(r"\.tg-bubble \.link-chip\{[^}]*display:table;[^}]*margin:0", css)


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_legend_groups_use_real_tile_markers(engine, frozen_clock, lang):
    with TestClient(create_app(engine, clock=frozen_clock)) as client:
        page = client.get("/demo/evening", params={"lang": lang})
    soup = BeautifulSoup(page.text, "html.parser")
    groups = soup.select(".legend .legend-group")
    assert [g.select_one("b").get_text() for g in groups] == (
        ["مستني", "متحرك", "خلص"] if lang == "ar" else ["Waiting", "Moving", "Finished"]
    )
    assert [len(g.select(".tile")) for g in groups] == [2, 2, 4]
    assert [m["data-state"] for m in soup.select(".legend .tile")][:7] == [
        "booked",
        "told_to_leave",
        "on_my_way",
        "in_room",
        "seen",
        "cancelled",
        "didnt_come",
    ]
    for state in ("cancelled", "didnt_come"):
        assert soup.select_one(f".legend .tile[data-state={state}] .t-n")
    assert soup.select_one(".legend .tile[data-source=walk_in] .t-n").get_text() == "+"


@pytest.mark.parametrize("script", ["location_dom.cjs", "phone_spacing_dom.cjs"])
def test_location_and_phone_handlers_offline(script):
    result = subprocess.run(
        ["node", "tests/web/" + script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
