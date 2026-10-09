"""Script label lookups must be supplied by real rendered pages, not DOM fixtures."""

import json
import re
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core import questions
from nowa.db import write_tx
from nowa.web.strings import text
from tests.web.test_doctor_web import headers, post
from tests.web.test_doctor_web import web as shared_web

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "nowa/web/static"
STATES = {"booked", "told_to_leave", "on_my_way", "seen", "cancelled", "didnt_come", "in_room"}
# These are the possible runtime values, not a catalog imported from the implementation.
DOCTOR_DYNAMIC = {
    '"learned_" + key + "_value"': {
        "learned_visit_value", "learned_gap_value", "learned_no_show_value",
    },
    '"unit_" + name + (few(n) ? "_few" : "_many")': {
        "unit_minutes_few", "unit_minutes_many", "unit_evenings_few", "unit_evenings_many",
        "unit_visits_few", "unit_visits_many",
    },
    "outcomeKey": {
        "q_saved",
        "q_deferred",
        "q_dismissed",
        "q_draft_ready",
        "q_no_draft",
        "q_stale_save",
        "q_already_done",
        "q_text_only",
        "q_refused",
    },
    "label": {
        "report_booked",
        "report_seen",
        "report_cancelled",
        "report_close_cancelled",
        "report_no_show",
        "report_walk_ins",
        "report_total",
        "report_arrival",
        "report_start",
        "report_avg_visit",
        "report_avg_wait",
        "report_failed",
    },
    'room ? "who_next" : "who_first"': {"who_next", "who_first"},
    "key": {"booked_count", "seen_count", "remaining_count", "without_booking_count"},
    'doctor.arrived_at ? "arrived_since" : "on_way_arrival"': {"arrived_since", "on_way_arrival"},
    "row.state": STATES,
    'row.state === "in_room" ? "in_room" : row.state': STATES,
    'action === "draft" ? "q_answer" : "q_" + action': {
        "q_answer",
        "q_save",
        "q_later",
        "q_dismiss",
    },
    'result.reason === "saved" ? "saved" : "q_" + result.reason': {
        "saved",
        "q_answer_prompt",
        "q_draft_ready",
        "q_no_draft",
        "q_stale_save",
        "q_already_done",
        "q_text_only",
        "q_refused",
        "q_later",
        "q_dismiss",
    },
    'path.startsWith("/d/api/questions/") ? "q_" + data.reason : data.reason': {
        "no_evening",
        "invalid_state",
        "already_seen",
        "invalid_booking",
        "evening_closed",
        "nothing_to_undo",
        "changed_since",
        "invalid_token",
        "evening_running",
        "q_refused",
        "q_text_only",
        "q_already_done",
        "q_stale_save",
        "q_no_draft",
    },
}
EVENING_DYNAMIC = {
    "key": {
        "room",
        "next",
        "kind_doctor_on_my_way",
        "kind_close_evening",
        "kind_message_failure",
        "kind_booking_cancelled",
        "action_leave_now",
        "action_reminder",
        "action_walk_in",
        "action_named_who",
        "action_patient_named_way",
        "action_patient_named_undo",
        "kind_who_comes_in",
        "kind_patient_on_my_way",
        "kind_patient_undo_on_my_way",
    },
    "row.state": STATES,
    'key === "room" ? "empty_room" : "no_next"': {"empty_room", "no_next"},
    '{l: "link_booking", w: "link_way", r: "link_rebook"}[match[1]]': {
        "link_booking",
        "link_way",
        "link_rebook",
    },
    "msg.label": {
        "message_booking",
        "message_leave",
        "message_cancelled",
        "message_clinic_cancelled",
        "message_doctor_reminder",
        "message_report",
        "message_question",
        "message_delivery_alert",
        "message_code",
        "message_link",
        "message_linked",
        "message_unlinked",
        "message_bookings",
        "message_capacity",
        "message_triage",
        "message_specialty",
    },
    '"report_" + key': {
        "report_booked",
        "report_seen_booked",
        "report_no_show_count",
        "report_walk_ins",
        "report_total_seen",
        "report_avg_wait",
    },
    'withNowa ? "with_nowa" : "without_nowa"': {"with_nowa", "without_nowa"},
    '"doctor_" + doctorState': {
        "doctor_waiting",
        "doctor_on_way",
        "doctor_arrived",
        "doctor_closed",
    },
    'data.closed ? "final_queue" : "queue"': {"final_queue", "queue"},
}


@pytest.fixture
def web(engine, monkeypatch):
    yield from shared_web.__wrapped__(engine, monkeypatch)


def call_arguments(source: str) -> list[str]:
    """Read each lookup's first argument, respecting strings and nested delimiters."""
    arguments = []
    for match in re.finditer(r"\b(?:t|text)\s*\(", source):
        start = match.end()
        depth = 0
        quote = ""
        escaped = False
        for index in range(start, len(source)):
            char = source[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in "\"'`":
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    arguments.append(source[start:index].strip())
                    break
                depth -= 1
            elif char == "," and depth == 0:
                arguments.append(source[start:index].strip())
                break
        else:
            raise AssertionError("Unterminated label lookup")
    return arguments


def lookups(script: str, dynamic: dict[str, set[str]] | None = None) -> set[str]:
    source = (STATIC / script).read_text()
    keys = set()
    for argument in call_arguments(source):
        literal = re.fullmatch(r"[\"'](\w+)[\"']", argument)
        if literal:
            keys.add(literal[1])
        else:
            assert dynamic and argument in dynamic, f"List possible labels for {script}: {argument}"
            keys.update(dynamic[argument])
    # Direct dot/bracket lookups, including config.strings[data.lang].x.
    prefix = (
        r"(?:strings\(\)|labels|texts|phoneLabels|config\.demo_strings|"
        r"config\.strings\[data\.lang\])"
    )
    for match in re.finditer(prefix + r"(?:\.(\w+)|\[\s*[\"'](\w+)[\"']\s*\])", source):
        keys.add(match[1] or match[2])
    assert keys, f"No label lookups found in {script}"
    return keys


def page(client, path: str, script: str, lang: str) -> BeautifulSoup:
    response = client.get(path)
    assert response.status_code == 200, response.text
    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.select_one(f'script[src="/static/{script}"]')
    # Chat pages start in Arabic; their config carries all session languages.
    if not path.startswith("/c/"):
        assert soup.html["lang"] == lang
    return soup


def labels(soup: BeautifulSoup, selector: str) -> dict[str, str]:
    return {node["data-key"]: node.get_text() for node in soup.select(selector + " [data-key]")}


def supplied(keys: set[str], values: dict[str, str], context: str) -> None:
    missing = keys - values.keys()
    empty = {key for key in keys & values.keys() if not values[key].strip()}
    assert not missing and not empty, f"{context}: missing={sorted(missing)}, empty={sorted(empty)}"


def language(client, lang: str) -> None:
    response = client.put(
        "/d/api/settings/lang",
        json={"lang": lang, "idempotency_key": lang},
        headers=headers(client),
    )
    assert response.status_code == 200


def close(client) -> None:
    assert post(client, "on-my-way", {"area_id": 1}).json()["ok"]
    booking_id = client.get("/d/api/tonight").json()["rows"][0]["booking_id"]
    assert post(client, "who-comes-in", {"booking_id": booking_id}).json()["ok"]
    preview = client.get("/d/api/close/preview").json()
    assert post(client, "close", {"expected_untold": preview["untold_count"]}).json()["ok"]


def test_dashboard_labels_reach_all_doctor_pages(web):
    client, _, eid, *_ = web
    close(client)
    keys = lookups("dashboard.js", DOCTOR_DYNAMIC)
    keys |= {"login_refused", "too_many_attempts", "check_fields"}  # Shared request feedback.
    for lang in ("ar", "en"):
        language(client, lang)
        for path in (
            "/d",
            "/d/settings",
            f"/d/report/{eid}",
            f"/d/login?lang={lang}",
            f"/d/reset?lang={lang}",
        ):
            soup = page(client, path, "dashboard.js", lang)
            supplied(keys, labels(soup, "#translations"), path + ":" + lang)


def test_signup_labels_reach_start(web):
    client, *_ = web
    keys = lookups("signup.js") | {"too_many_attempts", "check_fields"}
    for lang in ("ar", "en"):
        soup = page(client, "/start?lang=" + lang, "signup.js", lang)
        supplied(keys, labels(soup, "#signup-translations"), lang)


def test_evening_labels_reach_stage(web):
    client, *_ = web
    keys = lookups("evening.js", EVENING_DYNAMIC)
    for lang in ("ar", "en"):
        soup = page(client, "/demo/evening?lang=" + lang, "evening.js", lang)
        supplied(keys, json.loads(soup.select_one("#demo-texts").string), lang)


def test_chat_labels_reach_config(web, engine):
    client, cid, *_ = web
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    keys = lookups("chat.js") | {
        "faq_price",
        "faq_address",
        "faq_what_to_bring",
        "faq_other",
        "faq_hours",
        "too_many_attempts",
        "check_fields",
    }
    for lang in ("ar", "en", "franco"):
        soup = page(client, "/c/dr-hesham?lang=" + lang, "chat.js", lang)
        config = json.loads(soup.select_one("#chat-config").string)
        # phone_error is in demo_strings; all other direct lookups are in strings[lang].
        supplied(keys - {"phone_error"}, config["strings"][lang], lang)
        supplied({"phone_error"}, config["demo_strings"], lang)
        supplied({"ar", "en", "franco"}, config["open_telegram"], lang)


def test_public_chat_labels_reach_config(web, engine):
    client, cid, *_ = web
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=True))
    keys = lookups("public-chat.js") | {"too_many_attempts", "check_fields"}
    for lang in ("ar", "en"):
        soup = page(client, "/c/dr-hesham?lang=" + lang, "public-chat.js", lang)
        config = json.loads(soup.select_one("#chat-config").string)
        supplied(keys - {"telegram_note"}, config["demo_strings"], lang)
        supplied({"telegram_note"}, config["strings"][lang], lang)
        supplied({"ar", "en", "franco"}, config["open_telegram"], lang)


def test_judge_labels_reach_page(web):
    client, *_ = web
    get_settings().judge_codes = "fictional-label-check"
    keys = lookups("judge.js") | {"too_many_attempts", "check_fields"}
    for lang in ("ar", "en"):
        soup = page(client, "/judge?lang=" + lang, "judge.js", lang)
        supplied(keys, labels(soup, "#signup-translations"), lang)


def test_feedback_labels_reach_every_callers_page(web, engine):
    client, cid, eid, *_ = web
    get_settings().judge_codes = "fictional-label-check"
    close(client)
    keys = lookups("feedback.js")
    for lang in ("ar", "en"):
        language(client, lang)
        for path, selector in (
            ("/d", "#translations"),
            ("/d/settings", "#translations"),
            (f"/d/report/{eid}", "#translations"),
            (f"/d/login?lang={lang}", "#translations"),
            (f"/d/reset?lang={lang}", "#translations"),
            (f"/start?lang={lang}", "#signup-translations"),
            (f"/judge?lang={lang}", "#signup-translations"),
        ):
            soup = page(client, path, "feedback.js", lang)
            supplied(keys, labels(soup, selector), path + ":" + lang)
        for public in (False, True):
            with write_tx(engine) as conn:
                conn.execute(
                    s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=public)
                )
            soup = page(client, "/c/dr-hesham?lang=" + lang, "feedback.js", lang)
            config = json.loads(soup.select_one("#chat-config").string)
            supplied(keys, config["demo_strings"] if public else config["strings"][lang], lang)


def test_phone_labels_reach_every_callers_page(web):
    client, _, eid, *_ = web
    close(client)
    # The bracketed map selects one of these three keys by URL kind (l/w/r).
    keys = lookups("phone.js") | {"link_booking", "link_way", "link_rebook"}
    for lang in ("ar", "en"):
        language(client, lang)
        for path in (
            "/d",
            "/d/settings",
            f"/d/report/{eid}",
            f"/d/login?lang={lang}",
            f"/d/reset?lang={lang}",
            f"/start?lang={lang}",
            "/c/dr-hesham?lang=" + lang,
        ):
            soup = page(client, path, "phone.js", lang)
            supplied(keys, labels(soup, "#phone-translations"), path + ":" + lang)


def test_dashboard_missing_label_warns_without_hiding_request_errors():
    result = subprocess.run(
        ["node", "tests/web/feedback_dom.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_question_asker_labels_render_from_real_pages(web, engine, lang):
    client, cid, eid, clock, ids = web
    language(client, lang)
    with write_tx(engine) as conn:
        booked = conn.execute(select(s.bookings).where(s.bookings.c.id == ids[0])).mappings().one()
        conn.execute(
            s.patients.update()
            .where(s.patients.c.id == booked["patient_id"])
            .values(name="Mona Adel")
        )
        for key, asker in (
            ("known", questions.Asker(booked["patient_id"], ids[0], "known")),
            ("anonymous", questions.Asker(None, None, "anonymous")),
        ):
            questions.log_question(conn, clock, cid, "هل أجيب التحاليل القديمة معايا؟", key, asker)
    close(client)
    data = client.get("/d/api/questions").json()
    assert len(data) == 1 and len(data[0]["askers"]) == 2
    for path in ("/d", f"/d/report/{eid}"):
        soup = page(client, path, "dashboard.js", lang)
        result = subprocess.run(
            ["node", "tests/web/question_labels_dom.cjs"],
            cwd=ROOT,
            text=True,
            input=json.dumps(
                {
                    "labels": labels(soup, "#translations"),
                    "questions": data,
                    "expected": [
                        text("doctor.question_asker", lang).format(
                            name="Mona Adel", number=1, day=data[0]["askers"][0]["day"]
                        ),
                        text("doctor.question_anonymous", lang),
                    ],
                }
            ),
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
