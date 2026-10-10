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
