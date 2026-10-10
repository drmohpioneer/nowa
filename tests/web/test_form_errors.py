"""Field errors, hours labels, judge message, door label."""

import subprocess
from pathlib import Path

from nowa.web import strings
from nowa.web.templates import environment

ROOT = Path(__file__).resolve().parents[2]


def run_node(name: str) -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests/web" / name)], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_field_errors_name_mark_and_clear_the_field():
    run_node("form_errors_dom.cjs")


def test_wrong_last4_on_telegram_form_says_digits_do_not_match():
    run_node("patient_wrong_digits_dom.cjs")


def test_off_day_switch_reads_closed_in_both_languages():
    for lang, closed, opened in (("ar", "مقفول", "شغال"), ("en", "Closed", "Open")):
        for namespace in ("doctor", "signup"):
            def t(key, namespace=namespace, lang=lang):
                return strings.text(namespace + "." + key, lang)

            off = environment.get_template("hours.html").render(t=t, hours_open=False)
            on = environment.get_template("hours.html").render(t=t, hours_open=True)
            assert f'data-off="{closed}"' in off and f'data-on="{opened}"' in off
            # hours.js sets the visible text from these two values on load and on toggle.
            assert f'data-off="{closed}"' in on and f'data-on="{opened}"' in on
            day = t("mon")
            assert f'aria-label="{day}: {closed}"' in off
            assert f'aria-label="{day}: {opened}"' in on


def test_every_field_error_has_both_languages_in_both_catalogs():
    for key in ("field_required", "field_min", "field_time", "field_agree", "field_range"):
        for namespace in ("doctor", "signup"):
            for lang in ("ar", "en"):
                assert strings.text(f"{namespace}.{key}", lang)
    assert strings.text("signup.judge_wrong_code", "ar") == "الكود غلط."
    assert strings.text("signup.judge_wrong_code", "en") == "Wrong code."


def test_front_door_says_register_your_clinic():
    assert strings.text("ui.front_i_m_a_doctor", "ar") == "سجّل عيادتك"
    assert strings.text("ui.front_i_m_a_doctor", "en") == "Register your clinic"
    assert strings.text("signup.doctor_door", "en") == "Register your clinic"


def test_clinic_phone_field_has_the_client_rule_the_server_enforces():
    start = (ROOT / "nowa/web/static/start.html").read_text()
    assert 'name="clinic_phone" type="tel" data-egypt-mobile' in start


def test_server_names_the_clinic_phone_field_in_its_422():
    from nowa.core import signup
    from nowa.web.signup import refusal

    body = refusal(signup.Refused("invalid_clinic_phone", 422, ["clinic_phone"])).body
    assert b'"fields":["clinic_phone"]' in body.replace(b" ", b"")
    assert b"fields" not in refusal(signup.Refused("refused", 400)).body


def test_report_durations_show_units_and_empty_section_is_hidden():
    run_node("report_units_dom.cjs")


def test_learned_minutes_are_whole_numbers_in_settings():
    run_node("settings_feedback_dom.cjs")


def test_closed_evening_board_shows_closed_badge_and_hides_actions():
    run_node("board_closed_dom.cjs")


def test_closed_badge_text_exists_in_both_languages():
    assert strings.text("doctor.tonight_closed", "ar") == "العيادة اتقفلت"
    assert strings.text("doctor.tonight_closed", "en") == "Clinic closed"


def test_telegram_card_does_not_claim_the_code_was_sent():
    for lang in ("ar", "en"):
        text = strings.text("signup.sent_telegram", lang)
        assert text != strings.text("signup.sent", lang)
    assert "الكود اتبعت" not in strings.text("signup.sent_telegram", "ar")
    assert "sent" not in strings.text("signup.sent_telegram", "en").lower()
    script = (ROOT / "nowa/web/static/signup.js").read_text()
    assert 'status(result.telegram_url ? t("sent_telegram") : t("sent"))' in script


def test_drawn_phone_bubbles_follow_their_message_language():
    run_node("phone_spacing_dom.cjs")


def test_ready_page_number_is_isolated_left_to_right():
    script = (ROOT / "nowa/web/static/signup.js").read_text()
    assert 'document.createElement("bdi")' in script and 'number.dir = "ltr"' in script


def test_private_page_notice_spans_the_grid_instead_of_taking_a_column():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    assert ".page.patient>.status{grid-column:1/-1" in css


def test_phone_tap_targets_are_at_least_44px():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    block = css[css.index("/* Tap targets on phones"):]
    for selector in ("#logout", ".qrow button.name", ".who button", "select", ".clinic-link .btn",
                     ".choices button", "summary.quiet-link"):
        assert selector in block, selector
    assert block.count("min-height:44px") >= 6


def test_phone_selects_and_chat_chips_reach_44px_in_webkit_terms():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    block = css[css.index("/* Tap targets on phones"):]
    assert "select,.field select,.choices select{min-height:44px;height:44px}" in block
    assert ".faq button{min-height:44px}" in block


def test_every_chat_bubble_takes_its_direction_from_its_own_text():
    for name in ("chat.js", "public-chat.js"):
        script = (ROOT / "nowa/web/static" / name).read_text()
        assert 'p.setAttribute("dir", textDirection(text))' in script
        assert "document.documentElement.dir);" not in script.split("function line")[1][:300]


def test_field_error_colour_beats_the_muted_label_span_rule():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    assert ".field>span.field-error{display:block;color:var(--danger)" in css


def test_hours_time_inputs_may_shrink_inside_their_day_card_on_phones():
    css = (ROOT / "nowa/web/static/nowa.css").read_text()
    assert ".hours-times label{flex:1 1 150px;min-width:0}" in css
    assert "width:0;flex:1 1 96px;min-width:96px" in css
