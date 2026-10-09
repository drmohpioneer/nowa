import hashlib
import re

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import signup
from nowa.seed import seed
from nowa.web.markdown_lite import render_markdown
from tests.web import test_signup
from tests.web.test_signup import completion, send

signup_web = test_signup.signup_web


@pytest.fixture
def clarity_web(signup_web, engine):
    seed(engine)
    return signup_web


@pytest.mark.parametrize("path", ["/privacy", "/c/dr-hesham/privacy"])
@pytest.mark.parametrize(
    "lang,title,direction", [("ar", "سياسة الخصوصية", "rtl"), ("en", "Privacy policy", "ltr")]
)
def test_privacy_routes(clarity_web, path, lang, title, direction):
    response = clarity_web.get(path + "?lang=" + lang)
    assert response.status_code == 200
    page = BeautifulSoup(response.text, "html.parser")
    assert page.html["dir"] == direction and page.h1.get_text() == title
    assert "MedlinePlus" in page.get_text() and "30" in page.get_text() and "90" in page.get_text()
    assert "privacy_link" not in response.text


def test_privacy_unknown_slug_and_default_language(clarity_web):
    assert clarity_web.get("/c/missing-clinic/privacy").status_code == 404
    assert clarity_web.get("/c/_nowa/privacy").status_code == 404
    assert 'lang="ar"' in clarity_web.get("/privacy", headers={"Accept-Language": "en"}).text
    for path in ("/", "/demo", "/start", "/c/dr-hesham"):
        page = BeautifulSoup(clarity_web.get(path).text, "html.parser")
        link = page.select_one("footer.legal a")
        assert link and "privacy" in link["href"] and "سياسة الخصوصية" in link.get_text()


def test_agreement_display_and_missing_real_settings(monkeypatch):
    settings = get_settings()
    demo = signup.load_agreement()
    assert demo.text_hash["ar"] != demo.text_hash["en"]
    for lang in ("ar", "en"):
        assert not re.search(r"\[[A-Z]", demo.display[lang])
        assert not any(
            note in demo.display[lang]
            for note in ("draft", "Placeholders", "Owner decision", "قرار للمالك")
        )
        assert demo.text_hash[lang] == hashlib.sha256(demo.display[lang].encode()).hexdigest()
    monkeypatch.setattr(settings, "demo_mode", False)
    real = signup.load_agreement()
    assert "[set at signing]" in real.display["en"]
    assert "[يُحدد عند التعاقد]" in real.display["ar"]
    assert len(real.unfilled) == 10
    with pytest.raises(signup.Refused):
        signup.real_ready(real)
    for key in signup.AGREEMENT_DEFAULTS:
        monkeypatch.setattr(
            settings, "agreement_party_" + key.lower(), "<script>Fictional</script>"
        )
    monkeypatch.setattr(settings, "telegram_bot_token", "fictional-token")
    monkeypatch.setattr(settings, "telegram_bot_username", "fictional_bot")
    filled = signup.load_agreement()
    signup.real_ready(filled)
    assert not filled.unfilled
    assert "<script>" not in str(render_markdown(filled.display["ar"]))
    assert demo.text_hash["ar"] != filled.text_hash["ar"]


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_shown_agreement_language_hash_is_accepted(signup_web, engine, lang):
    page = BeautifulSoup(signup_web.get("/start?lang=" + lang).text, "html.parser")
    assert page.select_one(".agreement h3")
    result = send(signup_web, "/judge/start", {"code": get_settings().judge_codes.split(",")[0]})
    assert result.status_code == 200
    response = signup_web.post(
        "/signup/complete",
        json=completion(result.json()["signup_token"]),
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Referer": "http://127.0.0.1:8000/start?lang=" + lang,
        },
    )
    assert response.status_code == 200, response.text
    with engine.connect() as conn:
        stored = conn.execute(select(s.agreement_acceptances.c.text_hash)).scalar_one()
    assert stored == signup.load_agreement().text_hash[lang]


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_settings_help_shared_hours_and_no_secretary(clarity_web, engine, lang):
    from nowa.web.strings import DOCTOR_TEXTS

    with engine.begin() as conn:
        conn.execute(s.doctors.update().values(lang=lang))
    response = clarity_web.post(
        "/d/login",
        json={"mobile": "01000000001", "password": "demo1234"},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 200
    page = BeautifulSoup(clarity_web.get("/d/settings").text, "html.parser")
    assert page.select_one('#overrides [name="closed"]')["role"] == "switch"
    assert not page.select_one("#secretary_alerts")
    assert len(page.select("#hours .hours-row")) == 7
    for key in ("usual_visit_min", "safe_drive_min", "cushion_min"):
        control = page.select_one('[name="' + key + '"]')
        assert (
            control.parent.select_one("small.help").get_text()
            == DOCTOR_TEXTS[key + "_help"][lang == "en"]
        )
    start = BeautifulSoup(clarity_web.get("/start?lang=" + lang).text, "html.parser")
    assert len(start.select(".hours-row")) == 7
    assert [r.get_text(" ", strip=True) for r in page.select(".hours-row")] == [
        r.get_text(" ", strip=True) for r in start.select(".hours-row")
    ]


def test_saved_override_uses_existing_day_formatter(clarity_web, engine):
    from datetime import date

    with engine.begin() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinic_day_overrides.insert().values(
                clinic_id=cid, date=date(2026, 10, 8), closed=True
            )
        )
    assert (
        clarity_web.post(
            "/d/login",
            json={"mobile": "01000000001", "password": "demo1234"},
            headers={"Origin": "http://127.0.0.1:8000"},
        ).status_code
        == 200
    )
    saved = clarity_web.get("/d/api/settings").json()["overrides"][0]
    assert saved["date"] == "2026-10-08" and saved["date_display"] == "الخميس 8/10"
    assert saved["closed"] is True


@pytest.mark.parametrize("path", ["/", "/demo", "/start"])
def test_automatic_english_footer_opens_english_policy(clarity_web, path):
    page = BeautifulSoup(
        clarity_web.get(path, headers={"Accept-Language": "en-US"}).text, "html.parser"
    )
    link = page.select_one("footer.legal a")
    assert link.get_text() == "Privacy policy"
    assert link["href"] == "/privacy?lang=en"
    policy = BeautifulSoup(clarity_web.get(link["href"]).text, "html.parser")
    assert policy.h1.get_text() == "Privacy policy" and policy.html["dir"] == "ltr"


@pytest.mark.parametrize("lang", ["ar", "en"])
@pytest.mark.parametrize("query", ["", "?lang=unsupported"])
def test_implicit_agreement_language_ignores_another_tabs_cookie(signup_web, engine, lang, query):
    headers = {"Accept-Language": lang}
    page = BeautifulSoup(signup_web.get("/start" + query, headers=headers).text, "html.parser")
    assert page.html["lang"] == lang
    signup_web.cookies.set("nowa_agreement_lang", "ar" if lang == "en" else "en")
    token = send(
        signup_web, "/judge/start", {"code": get_settings().judge_codes.split(",")[0]}
    ).json()["signup_token"]
    response = signup_web.post(
        "/signup/complete",
        json=completion(token),
        headers=headers
        | {
            "Origin": "http://127.0.0.1:8000",
            "Referer": "http://127.0.0.1:8000/start" + query,
        },
    )
    assert response.status_code == 200, response.text
    with engine.connect() as conn:
        stored = conn.execute(select(s.agreement_acceptances.c.text_hash)).scalar_one()
    assert stored == signup.load_agreement().text_hash[lang]


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_review_hub_credentials_belong_to_board_card(clarity_web, lang):
    hub = BeautifulSoup(clarity_web.get("/demo?lang=" + lang).text, "html.parser")
    grid = hub.select_one(".doors")
    assert len(grid.find_all(recursive=False)) == 5
    board = grid.select_one(".board-door")
    assert board and board.select_one("a.door")["href"].startswith("/d/login")
    assert len(board.select(".creds > div")) == 2
    assert not hub.select("a .creds")
    for row in board.select(".creds > div"):
        assert [n.name for n in row.find_all(recursive=False)] == ["span", "code", "button"]
        assert row.button["data-copy"] == row.code["id"]


@pytest.mark.parametrize("lang,prefix", [("ar", "نسخة 0.1"), ("en", "Version 0.1")])
def test_review_agreement_begins_with_section_one(clarity_web, lang, prefix):
    page = BeautifulSoup(clarity_web.get("/start?lang=" + lang).text, "html.parser")
    panel = page.select_one(".agreement")
    assert panel.find(recursive=False).name == "h3"
    assert panel.get_text(strip=True).startswith("1.")
    assert not panel.select("h2")
    assert panel.find_previous_sibling("small").get_text() == prefix
    assert len(panel.select("h3")) == 17


@pytest.mark.parametrize("lang", ["ar", "en"])
@pytest.mark.parametrize(
    "addresses",
    [
        ("عنوان عربي", "English address"),
        ("عنوان عربي", "عنوان آخر"),
        ("English info", "English address"),
        ("عنوان عربي", None),
        ("عنوان عربي", ""),
        ("English info", "عنوان عربي"),
    ],
)
def test_review_poster_one_heading_localized_address_or_fallback(
    clarity_web, engine, lang, addresses
):
    address, address_en = addresses
    with engine.begin() as conn:
        clinic = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == "dr-hesham")
        ).scalar_one()
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(address=address, address_en=address_en)
        )
        # Stale duplicate data must never win over the authoritative pair.
        conn.execute(
            s.clinic_info.insert().values(clinic_id=clinic, key="address", text="Ignored duplicate")
        )
    assert (
        clarity_web.post(
            "/d/login",
            json={"mobile": "01000000001", "password": "demo1234"},
            headers={"Origin": "http://127.0.0.1:8000"},
        ).status_code
        == 200
    )
    page = BeautifulSoup(clarity_web.get("/d/poster?lang=" + lang).text, "html.parser")
    assert len(page.select(".poster h1")) == 1 and not page.select(".poster h2")
    doctor_name = "هشام مصطفى" if lang == "ar" else "Hesham Mostafa"
    assert page.select_one(".poster").get_text().count(doctor_name) == 1
    expected = (address_en or address) if lang == "en" else address
    assert page.select(".poster > p")[-1].get_text() == expected
    assert "Ignored duplicate" not in page.select_one(".poster").get_text()


@pytest.mark.parametrize(
    "key,ar,en",
    [
        (
            "doctor.cushion_min_help",
            "هامش أمان عشان الزحمة. كل ما يزيد، المريض بيستنى في العيادة شوية أكتر.",
            (
                "A safety margin for traffic. The larger it is, the longer patients wait at "
                "the clinic."
            ),
        ),
        (
            "ui.story_emergency_text",
            "لو المريض وصف عرض خطر، نوا بيقوله يتصل بـ 123 فورًا ومش بيحجزله.",
            (
                "If a patient describes a dangerous symptom, Nowa tells them to call 123 now "
                "and does not book."
            ),
        ),
        (
            "doctor.max_per_evening_help",
            "سيبه فاضي لو مش عايز حد أقصى. اللي بييجي من غير حجز مش بيتحسب.",
            "Leave empty for no limit. Patients without a booking are not counted.",
        ),
        (
            "ui.story_message_text",
            "كل مريض بتوصله رسالة «انزل دلوقتي» في الدقيقة اللي تناسب دوره وطريقه.",
            (
                'Each patient gets one "leave now" message at the minute that fits their turn '
                "and their road."
            ),
        ),
        ("ui.told_to_leave", "اتقاله ينزل", "Told to leave"),
        ("doctor.told_to_leave", "اتقاله ينزل", "Told to leave"),
        (
            "doctor.close_untold",
            (
                "{count} مرضى لسه ما اتقالهمش ينزلوا. هتوصلهم رسالة إلغاء مع لينك لحجز يوم "
                "تاني. تأكيد؟"
            ),
            (
                "{count} patients have not been told to leave yet. They will get a "
                "cancellation message with a rebook link. Confirm?"
            ),
        ),
        ("ui.report_no_show_count", "ما جوش", "Did not come"),
        (
            "ui.report_booked",
            "محجوزين (غير {cancelled} اتلغى)",
            "Booked ({cancelled} cancelled)",
        ),
        (
            "signup.map_error",
            "حط لينك جوجل مابس كامل، أو اختار أقرب منطقة للعيادة.",
            "Paste the full Google Maps link or choose the nearest area to the clinic.",
        ),
        (
            "doctor.new_password",
            "كلمة السر الجديدة (٨ حروف أو أرقام على الأقل)",
            "New password (at least 8 characters)",
        ),
        (
            "signup.password",
            "كلمة السر (٨ حروف أو أرقام على الأقل)",
            "Password (at least 8 characters)",
        ),
        ("ui.in_room", "في الكشف", "In the visit"),
    ],
)
def test_review_exact_wording(key, ar, en):
    from nowa.web.strings import STRINGS

    assert STRINGS[key]["ar"] == ar and STRINGS[key]["en"] == en
    assert STRINGS["ui.didnt_come"]["ar"] == "ما جاش"


def test_queue_without_booking_label_wraps_while_patient_names_keep_ellipsis():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "nowa/web/static/nowa.css").read_text()

    def declarations(selector):
        result = {}
        for body in re.findall(re.escape(selector) + r"\s*\{([^}]+)\}", css):
            result.update(part.strip().split(":", 1) for part in body.split(";") if ":" in part)
        return result

    names = declarations(".tile .t-name")
    without_booking = names | declarations('.tile[data-source="walk_in"] .t-name')
    assert without_booking["display"] == "block"
    assert without_booking["white-space"] == "normal"
    assert without_booking["overflow"] == "visible"
    assert without_booking["text-overflow"] == "clip"
    assert names["white-space"] == "nowrap"
    assert names["overflow"] == "hidden" and names["text-overflow"] == "ellipsis"
