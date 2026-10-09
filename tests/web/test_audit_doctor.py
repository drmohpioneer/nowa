"""regressions, exercised offline on real routes and stored rows."""

from pathlib import Path

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import auth, clinic_settings
from nowa.db import write_tx
from tests.web import test_doctor_web as doctor_web

web = doctor_web.web
headers = doctor_web.headers
post = doctor_web.post


@pytest.mark.parametrize(
    "item,path,needle",
    [
        (37, "nowa/web/templates/doctor/page.html", "t('board_eyebrow')"),
        (38, "nowa/web/templates/doctor/page.html", 'id="pace-count" class="num ltr" dir="ltr"'),
        (39, "nowa/web/static/dashboard.js", "data.can_undo"),
        (43, "nowa/web/templates/doctor/page.html", 'id="close-panel"'),
        (44, "nowa/web/static/dashboard.js", "data.evening_id == null"),
        (46, "nowa/web/static/nowa.css", '.qrow[data-state="seen"]{opacity:1}'),
        (47, "nowa/web/static/dashboard.js", "questionIcon"),
        (48, "nowa/web/static/dashboard.js", "empty_questions"),
        (49, "nowa/web/templates/doctor/page.html", 'id="report-summary"'),
        (50, "nowa/web/static/dashboard.js", "source_label"),
        (53, "nowa/web/static/feedback.js", "localStatus"),
        (54, "nowa/web/templates/doctor/page.html", "data-counter"),
        (55, "nowa/web/templates/doctor/page.html", "novalidate"),
        (57, "nowa/web/static/phone.js", "if (stopped) return;"),
        (58, "nowa/web/static/signup.js", "wrong_code"),
        (59, "nowa/web/static/start.html", "data-counter"),
        (60, "nowa/web/templates/doctor/page.html", 'id="reset-confirm" hidden'),
        (61, "nowa/web/templates/doctor/page.html", "auth-language"),
    ],
)
def test_audit_presentation(item, path, needle):
    assert needle in (Path(__file__).resolve().parents[2] / path).read_text(), item


def test_audit_8_login_failures_only(web, engine):
    _, _, _, clock, _ = web
    for i in range(10):
        assert auth.login(engine, clock, "01000000001", "demo1234", f"ok-{i}").ok
    with engine.connect() as conn:
        assert not conn.execute(
            select(s.rate_counters).where(s.rate_counters.c.scope == "doctor_login")
        ).all()
    for i in range(5):
        assert not auth.login(engine, clock, "01000000001", "wrong", f"bad-{i}").ok
    assert auth.login(engine, clock, "01000000001", "demo1234", "locked").limited


def test_audit_41_request_language(web):
    client, *_ = web
    assert '<html lang="en" dir="ltr">' in client.get("/d?lang=en").text


def test_audit_42_date_label(web, engine):
    client, cid, eid, clock, _ = web
    from datetime import timedelta
    from unittest.mock import patch

    from nowa.core.booking import TonightEvening

    with patch(
        "nowa.core.booking.tonight_evening",
        return_value=TonightEvening(clock.now(cid).date() + timedelta(days=7), eid),
    ):
        page = client.get("/d").text
    assert "الثلاثاء 13/10" in page
    assert 'live"></span>عيادة النهارده</span>' not in page


@pytest.mark.parametrize(
    "item,kind,payload",
    [
        (51, "hours", {"hours": [{"weekday": 1, "start": "23:00", "end": "19:00"}]}),
        (52, "overrides", {"date": "2020-01-01", "closed": True}),
        (
            52,
            "overrides",
            {"date": "2026-10-07", "closed": False, "start": "22:00", "end": "20:00"},
        ),
        (54, "info", {"items": [{"key": "other", "text": "   "}]}),
    ],
)
def test_audit_settings_rejected(web, item, kind, payload):
    client, *_ = web
    before = client.get("/d/api/settings").json()
    response = client.put(
        "/d/api/settings/" + kind,
        json=payload | {"idempotency_key": f"bad-{item}"},
        headers=headers(client),
    )
    assert response.status_code == 422, response.text
    assert client.get("/d/api/settings").json() == before


def test_audit_31_numeric_input():
    value = clinic_settings.Timing.model_validate(
        dict(usual_visit_min="١٥", safe_drive_min="٤٥", cushion_min="١٠", max_per_evening="٣٠")
    )
    assert value.usual_visit_min == 15 and value.max_per_evening == 30


def test_audit_56_poster(web):
    client, *_ = web
    page = client.get("/d/poster?lang=en").text
    assert "Hesham Mostafa" in page and "Back to the board" in page
    client.cookies.clear()
    for path in ["/d/poster", "/d/qr.svg"]:
        assert client.get(path, follow_redirects=False).status_code == 303


def test_audit_40_deferred_dismiss(web, engine):
    client, cid, eid, clock, _ = web
    with write_tx(engine) as conn:
        qid = conn.execute(
            s.questions.insert()
            .values(
                clinic_id=cid,
                evening_id=eid,
                text_norm="question",
                text_display="Is it open?",
                count=1,
                status="open",
                created_at=clock.now(cid),
            )
            .returning(s.questions.c.id)
        ).scalar_one()
    assert post(client, f"questions/{qid}/later").json()["ok"]
    assert client.get("/d/api/questions").json()[0]["status"] == "later"
    assert post(client, f"questions/{qid}/dismiss").json()["ok"]
    assert client.get("/d/api/questions").json() == []


def test_audit_2_7_30_schema():
    assert "name_en" in s.patients.c
    assert "values_json" in s.outbox.c
    assert "address_en" in s.clinics.c


def test_audit_39_undo_state(web):
    client, _, _, _, ids = web
    assert client.get("/d/api/tonight").json()["can_undo"] is False
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    assert client.get("/d/api/tonight").json()["can_undo"] is True
    assert post(client, "undo").json()["ok"]
    assert client.get("/d/api/tonight").json()["can_undo"] is False


def test_audit_60_demo_reset_scope_attempts_redaction(web, engine):
    import re

    from nowa.config import get_settings
    from tests.web.test_doctor_web import ORIGIN

    client, *_ = web
    get_settings().telegram_bot_username = ""
    assert client.get("/d/reset/phone").status_code == 403
    assert (
        client.post("/d/reset/request", json={"mobile": "01000000001"}, headers=ORIGIN).status_code
        == 200
    )
    messages = client.get("/d/reset/phone").json()
    assert len(messages) == 1
    code = re.search(r"\b[0-9]{6}\b", messages[0]["body"])[0]
    wrong = "000000" if code != "000000" else "111111"
    response = client.post(
        "/d/reset/confirm",
        json={"mobile": "01000000001", "code": wrong, "new_password": "fictional-new"},
        headers=ORIGIN,
    ).json()
    assert response == {"ok": False, "reason": "wrong_code", "attempts_left": 4}
    other = client.cookies.get("nowa_reset")
    client.cookies.set("nowa_reset", other + "tampered", path="/d/reset")
    assert client.get("/d/reset/phone").status_code == 403
    client.cookies.set("nowa_reset", other, path="/d/reset")
    assert client.post(
        "/d/reset/confirm",
        json={
            "mobile": "01000000001",
            "code": code.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")),
            "new_password": "fictional-new",
        },
        headers=ORIGIN,
    ).json()["ok"]
    assert client.get("/d/reset/phone").json() == []
    with engine.connect() as conn:
        row = (
            conn.execute(select(s.outbox).where(s.outbox.c.template_id == "op:reset_code"))
            .mappings()
            .one()
        )
        assert row["body"] == "[redacted]" and row["values_json"] is None


def test_audit_30_settings_address_pair(web, engine):
    client, cid, *_ = web
    payload = {
        "address": "عنوان جديد",
        "address_en": "New address",
        "items": [{"key": "price", "text": "٣٠٠"}],
        "idempotency_key": "address-pair",
    }
    assert (
        client.put("/d/api/settings/info", json=payload, headers=headers(client)).status_code == 200
    )
    value = client.get("/d/api/settings").json()
    assert value["address"] == "عنوان جديد" and value["address_en"] == "New address"
    assert value["items"] == [{"key": "price", "text": "300"}]
    assert "New address" in client.get("/d?lang=en").text
    assert "عنوان جديد" in client.get("/d?lang=ar").text
    payload.update(address_en="", idempotency_key="address-fallback")
    assert (
        client.put("/d/api/settings/info", json=payload, headers=headers(client)).status_code == 200
    )
    with engine.connect() as conn:
        assert (
            conn.execute(select(s.clinics.c.address_en).where(s.clinics.c.id == cid)).scalar_one()
            == "عنوان جديد"
        )
        assert not conn.execute(select(s.clinic_info).where(s.clinic_info.c.key == "address")).all()


def test_audit_43_49_50_report(web, engine):
    client, cid, eid, clock, ids = web
    assert post(client, "who-comes-in", {"booking_id": ids[0]}).json()["ok"]
    at = client.get("/d/api/tonight").json()["doctor"]["arrived_at"]
    clock.advance(minutes=12)
    count = client.get("/d/api/close/preview").json()["untold_count"]
    assert post(client, "close", {"expected_untold": count}).json()["ok"]
    result = client.get(f"/d/api/report/{eid}?lang=en").json()
    from datetime import datetime

    assert datetime.fromisoformat(result["doctor_arrival"]) == datetime.fromisoformat(at)
    assert result["cancelled_at_close"] == count
    assert result["doctor_arrival_display"] == "12:00"
    assert "[View]" not in result["text"] and "Cancelled at close:" in result["text"]
    assert "<pre" not in client.get(f"/d/report/{eid}").text


@pytest.mark.parametrize(
    "count,ar,en",
    [
        (1, "1 سؤال", "1 health question"),
        (2, "2 سؤالين", "2 health questions"),
        (3, "3 أسئلة", "3 health questions"),
    ],
)
def test_audit_49_question_plural(count, ar, en):
    from nowa.web.strings import health_question_count

    assert health_question_count(count, "ar").startswith(ar)
    assert health_question_count(count, "en") == en


def test_audit_59_slug_word_boundary(engine):
    from nowa.core.signup import slug_for

    with engine.connect() as conn:
        value = slug_for(conn, "Abdelrahman Mohamed Abdelaziz El Shashtawy Abdelrahman Mohamed")
    assert len(value) <= 60 and value.endswith("abdelrahman")


def test_audit_46_54_61_contrast():
    import re

    css = (Path(__file__).resolve().parents[2] / "nowa/web/static/nowa.css").read_text()

    def luminance(hexcolor):
        rgb = [int(hexcolor[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        rgb = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(a * b for a, b in zip(rgb, [0.2126, 0.7152, 0.0722], strict=True))

    colors = {
        key: re.findall(r"--" + key + r":(#[0-9A-Fa-f]{6})", css)
        for key in ["muted", "surface", "bg", "chip"]
    }
    for scheme in [0, 1]:
        for background in ["surface", "bg", "chip"]:
            values = sorted(
                [luminance(colors["muted"][scheme]), luminance(colors[background][scheme])]
            )
            assert (values[1] + 0.05) / (values[0] + 0.05) >= 4.5


def test_audit_40_53_57_shipped_handlers(web, engine):
    import json
    import subprocess

    client, cid, eid, clock, _ = web
    states, results = [], []

    def add(text):
        with write_tx(engine) as conn:
            return conn.execute(
                s.questions.insert()
                .values(
                    clinic_id=cid,
                    evening_id=eid,
                    text_norm=text,
                    text_display=text,
                    count=1,
                    status="open",
                    created_at=clock.now(cid),
                )
                .returning(s.questions.c.id)
            ).scalar_one()

    first = add("Can I bring my tests?")
    states.append(client.get("/d/api/questions").json())
    results.append(post(client, f"questions/{first}/draft", {"text": "A fictional answer"}).json())
    states.append(client.get("/d/api/questions").json())
    results.append(post(client, f"questions/{first}/save").json())
    states.append(client.get("/d/api/questions").json())
    second = add("Is there parking?")
    next_question = client.get("/d/api/questions").json()
    results.append(post(client, f"questions/{second}/later").json())
    states.append(client.get("/d/api/questions").json())
    results.append(post(client, f"questions/{second}/dismiss").json())
    states.append(client.get("/d/api/questions").json())
    root = Path(__file__).resolve().parents[2]
    output = subprocess.run(
        ["node", str(root / "tests/web/audit_doctor_dom.cjs")],
        input=json.dumps({"states": states, "results": results, "nextQuestion": next_question}),
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    assert output.returncode == 0, output.stdout + output.stderr


@pytest.mark.parametrize("value", [None, 1900, {}, [], True])
def test_hours_malformed_external_input_is_validation_error(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        clinic_settings.HoursRow.model_validate({"weekday": 1, "start": value, "end": "23:00"})


def test_audit_53_57_58_signup_handlers():
    import subprocess

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/web/signup_feedback_dom.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_audit_rendered_controls(web, lang):
    from bs4 import BeautifulSoup

    from nowa.web.strings import text

    client, *_ = web
    board = BeautifulSoup(client.get("/d?lang=" + lang).text, "html.parser")
    assert board.select_one(".eyebrow").get_text() == text("doctor.board_eyebrow", lang)
    assert board.select_one("#pace-count")["dir"] == "ltr"
    assert board.select_one("#undo").has_attr("disabled")
    assert board.select_one("#undo")["aria-label"] == text("doctor.undo_empty", lang)
    panel = board.select_one("#close-panel")
    assert panel.has_attr("hidden") and panel["role"] == "dialog"
    assert len(panel.select("button")) == 2
    settings = BeautifulSoup(client.get("/d/settings?lang=" + lang).text, "html.parser")
    assert settings.select_one("[data-weekday]")["data-weekday"] == "5"
    assert settings.select_one("textarea[name=address]").has_attr("required")
    assert not settings.select_one("textarea[name=address_en]").has_attr("required")
    for form in settings.select("form"):
        assert form.has_attr("novalidate")
    signup = BeautifulSoup(client.get("/start?lang=" + lang).text, "html.parser")
    for name in ["name_ar", "name_en"]:
        field = signup.select_one(f"input[name={name}]")
        assert field["maxlength"] == "60" and field.has_attr("data-counter")
    for link in signup.select("#signup-success a"):
        assert "btn" in link["class"]
    for path in ["/d/login", "/d/reset"]:
        page = BeautifulSoup(client.get(path + "?lang=" + lang).text, "html.parser")
        assert page.select_one("a.logo")["href"] == "/?lang=" + lang
        assert (
            "lang=" + ("en" if lang == "ar" else "ar") in page.select_one(".auth-language")["href"]
        )
        if path.endswith("reset"):
            assert not page.select_one("#reset-request").has_attr("hidden")
            assert page.select_one("#reset-confirm").has_attr("hidden")


def test_audit_44_no_evening_shipped_board(web):
    import json
    import subprocess

    from nowa.web.strings import DOCTOR_TEXTS

    client, _, _, clock, _ = web
    clock.advance(minutes=30 * 24 * 60)
    from tests.web.test_doctor_web import ORIGIN

    assert (
        client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        ).status_code
        == 200
    )
    response = client.get("/d/api/tonight")
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["evening_id"] is None
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/web/doctor_board_dom.cjs"],
        cwd=root,
        text=True,
        input=json.dumps(
            {"states": [snapshot], "texts": {key: value[1] for key, value in DOCTOR_TEXTS.items()}}
        ),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
