import hashlib
from datetime import timedelta

from sqlalchemy import select

from nowa import schema as s
from nowa.db import write_tx
from nowa.telegram import keyboards


def message(update_id, chat=101, text=None, location=None, kind="private"):
    content = {"message_id": 7, "chat": {"id": chat, "type": kind}}
    if text is not None:
        content["text"] = text
    if location is not None:
        content["location"] = location
    return {"update_id": update_id, "message": content}


def callback(update_id, data, chat=101, kind="private"):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"query-{update_id}",
            "data": data,
            "message": {"message_id": 70, "chat": {"id": chat, "type": kind}},
        },
    }


def tap(router, update_id, verb, eid=None, bid=None, arg="-", chat=101):
    router.handle_update(callback(update_id, keyboards.build(verb, eid, bid, arg), chat))


def token(engine, clock, cid, subject, role, value="fixture-link-token", expired=False):
    with write_tx(engine) as conn:
        tid = conn.execute(
            s.link_tokens.insert()
            .values(
                clinic_id=cid,
                kind=role + "_telegram",
                subject_id=subject,
                token_hash=hashlib.sha256(value.encode()).hexdigest(),
                expires_at=clock.now(cid) + timedelta(minutes=-1 if expired else 15),
            )
            .returning(s.link_tokens.c.id)
        ).scalar_one()
    return tid, ("d_" if role == "doctor" else "p_") + value


def doctor_link(bot, engine, chat=101, update_id=1):
    router, cid, _, did, clock, _, _ = bot
    _, payload = token(engine, clock, cid, did, "doctor", f"doctor-token-{update_id}")
    router.handle_update(message(update_id, chat, "/start " + payload))


def patient_link(bot, engine, index=0, chat=201, update_id=2):
    router, cid, _, _, clock, ids, _ = bot
    with engine.connect() as conn:
        contact = conn.execute(
            select(s.bookings.c.contact_id).where(s.bookings.c.id == ids[index])
        ).scalar_one()
    tid, payload = token(engine, clock, cid, contact, "patient", f"patient-token-{update_id}")
    router.handle_update(message(update_id, chat, "/start " + payload))
    return tid


def inline_data(fake):
    return [
        button["callback_data"]
        for _, payload in fake.calls
        for row in payload.get("reply_markup", {}).get("inline_keyboard", [])
        for button in row
        if "callback_data" in button
    ]


def other_doctor(engine, clock, cid):
    with write_tx(engine) as conn:
        clinic = dict(conn.execute(select(s.clinics).where(s.clinics.c.id == cid)).mappings().one())
        clinic.pop("id")
        clinic["slug"] = "fictional-other-clinic"
        other = conn.execute(
            s.clinics.insert().values(**clinic).returning(s.clinics.c.id)
        ).scalar_one()
        doc = dict(
            conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == cid)).mappings().one()
        )
        doc.pop("id")
        doc.update(clinic_id=other, mobile_e164="+201000000888")
        did = conn.execute(s.doctors.insert().values(**doc).returning(s.doctors.c.id)).scalar_one()
        for hours in conn.execute(
            select(s.clinic_hours).where(s.clinic_hours.c.clinic_id == cid)
        ).mappings():
            values = dict(hours)
            values.pop("id")
            conn.execute(s.clinic_hours.insert().values(**(values | {"clinic_id": other})))
        eid = conn.execute(
            s.evenings.insert()
            .values(clinic_id=other, date=clock.now(cid).date(), state="scheduled")
            .returning(s.evenings.c.id)
        ).scalar_one()
    return other, did, eid
