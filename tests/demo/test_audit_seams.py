from sqlalchemy import select

from nowa import schema as s
from nowa.core.display import patient_display_name
from nowa.db import write_tx
from nowa.demo.evening_script import PATIENTS
from tests.demo.test_web import HEADERS, start


def test_audit_2_bilingual_script_identity(demo_client, engine):
    run = start(demo_client, "bilingual-script")
    path = "/demo/evening/" + run["run_id"] + "/state"
    ar = demo_client.get(path, params={"token": run["token"], "lang": "ar"}).json()
    en = demo_client.get(path, params={"token": run["token"], "lang": "en"}).json()
    assert ar["queue"][8]["patient_first_name"] == "منى عادل"
    assert en["queue"][8]["patient_first_name"] == "Mona Adel"
    with engine.connect() as conn:
        names = (
            conn.execute(select(s.patients).where(s.patients.c.clinic_id == ar["clinic_id"]))
            .mappings()
            .all()
            if "clinic_id" in ar
            else conn.execute(select(s.patients).where(s.patients.c.name_en.is_not(None)))
            .mappings()
            .all()
        )
    assert len(names) == 18
    for patient, row in zip(PATIENTS, names, strict=True):
        assert patient_display_name(row, "ar") == patient.name
        assert patient_display_name(row, "en") == patient.name_en
    assert (
        patient_display_name({"name": "Real Typed Name", "name_en": None}, "ar")
        == "Real Typed Name"
    )


def test_audit_7_saved_values_english_and_old_rows(demo_client, engine):
    run = start(demo_client, "saved-message-values")
    path = "/demo/evening/" + run["run_id"]
    result = demo_client.post(
        path + "/advance?lang=en", json={"token": run["token"], "to_minute": 600}, headers=HEADERS
    ).json()
    messages = result["phones"]
    assert {"1", "2", "3", "5"} <= {m["template_id"] for m in messages}
    assert all(not any("\u0600" <= char <= "\u06ff" for char in m["body"]) for m in messages)
    assert all(m["sent_in_arabic"] for m in messages)
    first = next(m for m in messages if m["template_id"] == "1")
    with write_tx(engine) as conn:
        conn.execute(
            s.outbox.update()
            .where(s.outbox.c.id == first["outbox_id"])
            .values(values_json=None, body="Original historical body")
        )
    saved = demo_client.get(path + "/state", params={"token": run["token"], "lang": "en"}).json()
    old = next(m for m in saved["phones"] if m["outbox_id"] == first["outbox_id"])
    assert old["body"] == "Original historical body" and not old["sent_in_arabic"]
