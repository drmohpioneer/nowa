"""regressions."""

import re
import subprocess

import pytest
from fastapi.testclient import TestClient

from nowa.app import create_app
from nowa.web.strings import STRINGS, UI_TEXTS
from tests.web import test_patient_link
from tests.web.support import ROOT, fields

page = test_patient_link.page


def source(path):
    return (ROOT / path).read_text()


@pytest.mark.parametrize(
    "file", ["chat.js", "public-chat.js", "phone.js", "evening.js", "chat.html"]
)
def test_audit_1_page_direction(file):
    text = source("nowa/web/static/" + file)
    assert '"auto"' not in text


@pytest.mark.parametrize("file", ["chat.js", "public-chat.js"])
def test_audit_18_scroll(file):
    assert "scrollIntoView" in source("nowa/web/static/" + file)


@pytest.mark.parametrize(
    "number,needle",
    [
        (3, "word-break:normal"),
        (6, ".tile-heading"),
        (9, ".stage-language"),
        (25, ".chat-wrap .layout:has"),
        (46, '.tile[data-state="seen"]{opacity:1'),
        (64, "--muted:#626977"),
        (65, ":where(button,a,input,select,textarea,summary)"),
    ],
)
def test_audit_css(number, needle):
    assert needle in source("nowa/web/static/nowa.css")


def test_audit_4_timeline_matches_ids():
    text = source("nowa/web/static/evening.js")
    assert (
        "msg.outbox_id" in text
        and "Date.parse(msg.created_at) === Date.parse(event.at)" not in text
    )
    assert "message:" in text


def test_audit_5_clock_source():
    text = source("nowa/web/static/evening.js")
    assert "data.closed ? 100" not in text
    assert "const clock = time(data.clock)" in text


def test_audit_10_legend():
    text = source("nowa/web/static/evening.html")
    for state in ("cancelled", "didnt_come", "walkin"):
        assert "'" + state + "'" in text
    assert 'class="tile legend-marker"' in text
    assert 'data-source="walk_in"' in text
    assert UI_TEXTS["doctor_avatar"][0] == "د"


def test_audit_12_ticker_spacing():
    text = source("nowa/web/static/front.html")
    assert "ticker-copy" in text


def test_audit_13_books_for_father():
    assert "books for his father" in UI_TEXTS["front_karim_books_his_father_and_gets_number"][1]


def test_audit_14_feature_full_stops():
    for key, pair in UI_TEXTS.items():
        if key.startswith("story_") and key.endswith("_text"):
            assert all(value.endswith(".") for value in pair), key


def test_audit_15_hub_doors():
    text = source("nowa/web/static/demo.html")
    assert "/demo/evening#report" in text and "/c/dr-hesham?from=demo" in text
    assert "«" in UI_TEXTS["door_chat_sub"][0]
    assert 'location.hash === "#report"' in source("nowa/web/static/evening.js")


def test_audit_16_current_navigation():
    assert "current_path" in source("nowa/web/templates/public-topbar.html")


def test_audit_17_favicon_and_titles(engine, frozen_clock):
    with TestClient(create_app(engine, clock=frozen_clock)) as client:
        icon = client.get("/favicon.ico")
        assert icon.status_code == 200 and "image/svg+xml" in icon.headers["content-type"]
        for path in ("/", "/demo", "/demo/book", "/demo/evening"):
            for lang in ("ar", "en"):
                html = client.get(path, params={"lang": lang}).text
                assert " · " in re.search(r"<title>(.*?)</title>", html)[1]
                assert 'rel="icon"' in html
    assert UI_TEXTS["switch_language"][1] == "العربية"


def test_audit_21_echo_choices():
    text = source("nowa/web/static/chat.js")
    assert "line(b.label, true)" in text and "line(el.textContent, true)" in text


def test_audit_24_prompt():
    from nowa.ai.prompt import STATIC_ROLE

    assert "never re-introduce yourself" in STATIC_ROLE


def test_audit_26_source_language():
    from nowa.library.source_display import source_link

    assert (
        source_link(
            "https://www.nhs.uk/conditions/high-blood-pressure-hypertension/",
            "High blood pressure",
            "ar",
        ).label
        == "المصدر: NHS · ضغط الدم المرتفع"
    )


def test_audit_27_chat_navigation():
    html = source("nowa/web/static/chat.html")
    assert 'id="chat-home"' in html and 'id="chat-back"' in html and 'id="chat-language"' in html


def test_audit_29_compound_name(page, engine):
    from sqlalchemy import select

    from nowa import schema as s
    from nowa.core import booking
    from nowa.db import write_tx

    client, _, _, _, ids, code = page
    with write_tx(engine) as conn:
        pid = conn.execute(
            select(s.bookings.c.patient_id).where(s.bookings.c.id == ids[0])
        ).scalar_one()
        conn.execute(
            s.patients.update().where(s.patients.c.id == pid).values(name="عبد الرحمن محمد")
        )
    assert booking.booking_view(engine, code).patient_first_name == "عبد الرحمن محمد"
    assert "عبد الرحمن محمد" in client.get("/l/" + code).text


def test_audit_31_arabic_digits(page):
    client, _, _, _, _, code = page
    html = client.get("/l/" + code)
    assert "[0-9٠-٩۰-۹]{4}" in html.text
    result = client.post(
        "/l/" + code + "/cancel",
        data=fields(html, "/cancel") | {"last4": "٠٠٠٠"},
        headers={"Origin": "http://127.0.0.1:8000"},
        follow_redirects=True,
    )
    assert "booking is cancelled" in result.text


def test_audit_32_cancelled_only(page):
    client, _, _, _, _, code = page
    html = client.get("/l/" + code)
    result = client.post(
        "/l/" + code + "/cancel",
        data=fields(html, "/cancel") | {"last4": "0000"},
        headers={"Origin": "http://127.0.0.1:8000"},
        follow_redirects=True,
    )
    assert "Book again" in result.text and "turn-hero" not in result.text
    assert 'id="booking-details"' not in result.text


def test_audit_33_state_is_not_time(page, engine):
    from nowa import schema as s
    from nowa.db import write_tx

    client, _, _, _, ids, code = page
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(state="on_my_way"))
    html = client.get("/w/" + code).text
    assert 'Expected time · <span class="num">On my way' not in html
    assert 'id="journey-progress"' in source("nowa/web/templates/patient/page.html")


def test_audit_34_failed_post_redirect(page):
    client, _, _, _, _, code = page
    html = client.get("/l/" + code)
    result = client.post(
        "/l/" + code + "/cancel",
        data=fields(html, "/cancel") | {"last4": "9999"},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert result.status_code == 303
    assert "did not match" in client.get(result.headers["location"]).text


def test_audit_35_exclude_current_day(page):
    from tests.core.support import DAY

    client, _, _, _, _, code = page
    html = client.get("/l/" + code + "/change").text
    assert f'value="{DAY.isoformat()}"' not in html


def test_audit_36_doctor_and_error_language(page):
    client, _, _, _, _, code = page
    assert "Dr. Hesham Mostafa" in client.get("/l/" + code).text
    for prefix in ("l", "w", "r"):
        html = client.get("/" + prefix + "/missing?lang=en").text
        assert 'lang="en"' in html and 'href="/' in html


def test_audit_38_counter_isolated():
    assert 'id="pace-count" class="num ltr"' in source("nowa/web/templates/doctor/page.html")


def test_audit_45_shared_states():
    assert STRINGS["doctor.seen"]["ar"] == "اتكشف"
    assert STRINGS["doctor.in_room"]["ar"] == "في الكشف"


@pytest.mark.parametrize("path", ["/nope", "/c/nobody", "/d/report/0", "/d/report/abc"])
def test_audit_62_branded_errors(engine, frozen_clock, path):
    with TestClient(create_app(engine, clock=frozen_clock), follow_redirects=False) as client:
        html = client.get(path + "?lang=en", headers={"Accept": "text/html"})
        assert html.status_code in (303, 404, 422)
        if html.status_code != 303:
            assert '<html lang="en"' in html.text
        api = client.get(path, headers={"Accept": "application/json"})
        assert api.headers["content-type"].startswith("application/json")


def test_audit_63_patient_time():
    from datetime import datetime

    from nowa.clock import CAIRO
    from nowa.messaging.templates import format_time

    assert format_time(datetime(2026, 10, 6, 19, 14, tzinfo=CAIRO), "ar") == "7:15 م"
    assert format_time(datetime(2026, 10, 6, 9, 5, tzinfo=CAIRO), "en") == "9:05 AM"


@pytest.mark.parametrize("script", ["chat_dom.cjs", "conversation_dom.cjs", "telegram_dom.cjs"])
def test_audit_shipped_chat_handlers(script):
    result = subprocess.run(
        ["node", "tests/web/" + script], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_audit_46_64_contrast_tokens():
    def luminance(color):
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(
            weight * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
            for weight, v in zip((0.2126, 0.7152, 0.0722), values)
        )

    css = source("nowa/web/static/nowa.css")
    for scheme in css.split("\n  color-scheme:")[1:3]:
        tokens = dict(re.findall(r"--([a-z-]+):(#[A-Fa-f0-9]{6})", scheme.split("}")[0]))
        for key in ("bg", "surface", "stage-a", "chip"):
            low, high = sorted([luminance(tokens["muted"]), luminance(tokens[key])])
            assert (high + 0.05) / (low + 0.05) >= 4.5, (key, tokens)


def test_audit_1_isolation_escapes_patient_text():
    from nowa.web.templates import isolate_text

    result = str(isolate_text("أهلاً Youssef Adel +201000000000 <script>alert(1)</script>"))
    assert '<bdi dir="ltr">Youssef Adel +201000000000 ' in result
    assert "<script>" not in result and "&lt;" in result
