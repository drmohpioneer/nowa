"""regressions, using real transactions and the existing worker."""

from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa.app import create_app
from nowa.config import get_settings
from nowa.core import booking, flows, report, timing
from nowa.db import write_tx
from tests.core.support import DAY, move, request, setup
from tests.web.support import ORIGIN, fields


def full(engine):
    cid, eid, clock, ids = setup(engine, count=2)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(max_per_evening=2))
    return cid, eid, clock, ids


def join(engine, clock, cid, i=50, day=DAY, phone=None):
    from nowa.core import standby

    req = request(cid, i, day)
    if phone:
        req = replace(req, contact_phone=phone)
    with write_tx(engine) as conn:
        normalized = booking.normalize_phone(req.contact_phone)
        if not conn.execute(
            select(s.telegram_links).where(s.telegram_links.c.phone_e164 == normalized)
        ).first():
            conn.execute(
                s.telegram_links.insert().values(
                    phone_e164=normalized,
                    kind="patient",
                    telegram_chat_id=f"fictional-{i}",
                    linked_at=clock.now(cid),
                )
            )
        return standby.join_in_tx(conn, clock, req)


def cancel(engine, clock, bid, key=None):
    with engine.connect() as conn:
        phone = conn.execute(
            select(s.contacts.c.phone_e164).join(s.bookings).where(s.bookings.c.id == bid)
        ).scalar_one()
    return flows.cancel(engine, clock, booking.link_code_for(bid), phone[-4:], key or f"free:{bid}")


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(s.standbys).order_by(s.standbys.c.position)).mappings().all()


def offer_code(engine, sid):
    with engine.connect() as conn:
        path = conn.execute(
            select(s.outbox.c.values_json).where(
                s.outbox.c.standby_id == sid, s.outbox.c.template_id == "op:standby_offer"
            )
        ).scalar_one()["take_link"]
    return path.split("/")[2]


def test_join_duplicate_phone_identity_consent_and_cap(engine):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    first = join(engine, clock, cid)
    assert isinstance(first, standby.Joined)
    second = join(engine, clock, cid, i=51, phone=request(cid, 50).contact_phone)
    assert second == standby.Joined(first.standby_id, 1, True)
    row = rows(engine)[0]
    assert row["state"] == "waiting" and row["consent_version"] == "v1"
    assert row["consent_text_hash"] == "fictional" and row["booking_for"] == "self"
    assert row["evening_id"] == eid and row["date"] == DAY
    assert "phone" not in s.standbys.c and "name" not in s.standbys.c
    for offset in (2, 7):
        assert isinstance(
            join(engine, clock, cid, i=50, day=DAY + timedelta(days=offset)), standby.Joined
        )
    assert join(engine, clock, cid, i=50, day=DAY + timedelta(days=9)).reason == "phone_cap"
    assert (
        flows.book(
            engine,
            clock,
            replace(request(cid, 50, DAY + timedelta(days=14)), idempotency_key="cap"),
        ).reason
        == "phone_cap"
    )


def test_two_frees_distinct_reserved_offers_and_take_replay(engine):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    b = join(engine, clock, cid, 51)
    assert isinstance(cancel(engine, clock, ids[0]), booking.CancelResult)
    assert rows(engine)[0]["state"] == "offered"
    assert flows.book(engine, clock, request(cid, 99)).reason == "full"
    cancel(engine, clock, ids[0])  # Repeating the first free cannot offer a second place.
    assert [r["state"] for r in rows(engine)] == ["offered", "waiting"]
    cancel(engine, clock, ids[1])
    assert [r["state"] for r in rows(engine)] == ["offered", "offered"]
    assert flows.book(engine, clock, request(cid, 99)).reason == "full"
    code = offer_code(engine, a.standby_id)
    with write_tx(engine) as conn:
        taken = standby.take_in_tx(conn, clock, code)
        replay = standby.take_in_tx(conn, clock, code)
        assert isinstance(taken, booking.BookingOk) and replay.repeated
        assert taken.queue_number == 3
        booked = (
            conn.execute(select(s.bookings).where(s.bookings.c.id == taken.booking_id))
            .mappings()
            .one()
        )
        assert booked["patient_id"] == rows_in_conn(conn)[0]["patient_id"]
        assert conn.execute(
            select(s.outbox.c.id).where(
                s.outbox.c.booking_id == taken.booking_id, s.outbox.c.template_id == "1"
            )
        ).one()
        assert report.build_report(conn, clock, cid, eid).standby_taken == 1
    assert [r["state"] for r in rows(engine)] == ["taken", "offered"]
    assert rows(engine)[1]["id"] == b.standby_id


def rows_in_conn(conn):
    return conn.execute(select(s.standbys).order_by(s.standbys.c.position)).mappings().all()


def test_expiry_worker_passes_on_once(engine):
    from nowa.core import standby
    from nowa.worker import build_registry, run_once

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    cancel(engine, clock, ids[0])
    first = rows(engine)[0]
    assert first["expires_at"] == clock.now(cid) + timedelta(minutes=20)
    clock.advance(minutes=20)
    registry = {"standby_expire": build_registry()["standby_expire"]}
    assert run_once(engine, clock, registry).done == 1
    assert [r["state"] for r in rows(engine)] == ["expired", "offered"]
    with write_tx(engine) as conn:
        assert isinstance(
            standby.take_in_tx(conn, clock, offer_code(engine, a.standby_id)),
            booking.BookingRefused,
        )
        standby.offer_next(conn, clock, eid)
        assert (
            len(
                conn.execute(
                    select(s.outbox).where(s.outbox.c.template_id == "op:standby_offer")
                ).all()
            )
            == 2
        )


def test_decline_passes_on(engine):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    cancel(engine, clock, ids[0])
    code = offer_code(engine, a.standby_id)
    with write_tx(engine) as conn:
        standby.take_in_tx(conn, clock, code, decline=True)
        standby.take_in_tx(conn, clock, code, decline=True)
    assert [r["state"] for r in rows(engine)] == ["declined", "offered"]


@pytest.mark.parametrize("close_kind", ["cutoff", "closed", "cancelled"])
def test_late_take_and_close_notifications(engine, close_kind):
    from nowa.core import standby

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    join(engine, clock, cid, 51)
    if close_kind == "cutoff":
        move(clock, 11 * 60 + 40)  # 23:40, after 22:59 cutoff.
        cancel(engine, clock, ids[0])
        assert [r["state"] for r in rows(engine)] == ["waiting", "waiting"]
        return
    cancel(engine, clock, ids[0])
    code = offer_code(engine, a.standby_id)
    if close_kind == "closed":
        with write_tx(engine) as conn:
            timing.close_evening_in_tx(
                conn, clock, cid, eid, "system", "close", _system_no_taps=True
            )
    else:
        with engine.connect() as conn:
            doctor = conn.execute(
                select(s.doctors.c.id).where(s.doctors.c.clinic_id == cid)
            ).scalar_one()
        token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
        timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel-evening")
    with write_tx(engine) as conn:
        assert isinstance(standby.take_in_tx(conn, clock, code), booking.BookingRefused)
        standby.close(conn, clock, eid)
        messages = (
            conn.execute(select(s.outbox).where(s.outbox.c.template_id == "op:standby_closed"))
            .mappings()
            .all()
        )
        assert len(messages) == 2
        assert all("?day=" in r["values_json"]["next_day_link"] for r in messages)
    assert [r["state"] for r in rows(engine)] == ["expired", "expired"]


def test_silent_recompute_offers_only_when_capacity_fits(engine):
    cid, eid, clock, ids = full(engine)
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(max_per_evening=None))
    join(engine, clock, cid)
    # A time-limited full day rather than the explicit numerical cap.
    from datetime import time

    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(start=time(12), end=time(12, 12)))
        conn.execute(
            s.evenings.update()
            .where(s.evenings.c.id == eid)
            .values(paper_start=time(12), paper_end=time(12, 12))
        )
        conn.execute(s.standbys.update().values(state="waiting", offer_code_hash=None))
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[0])
            .values(
                state="told_to_leave",
                told_to_leave_at=clock.now(cid) - timedelta(minutes=10),
                expected_frozen=True,
            )
        )
        assert booking._day_status(conn, cid, DAY, clock.now(cid))[0] == "full"
        timing.recompute(conn, clock, eid)
    # Silence keeps the original booking's place in admission .
    # It triggers an offer only when the unchanged admission rule also fits.
    assert rows(engine)[0]["state"] == "waiting"
    with write_tx(engine) as conn:
        conn.execute(s.clinic_hours.update().values(end=time(13)))
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[0]).values(silent=False))
        timing.recompute(conn, clock, eid)
    assert rows(engine)[0]["state"] == "offered"


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_private_page_get_no_mutation_post_origin_token_and_take(engine, lang, caplog):
    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    cancel(engine, clock, ids[0])
    code = offer_code(engine, a.standby_id)
    app = create_app(engine, clock=clock)
    with TestClient(app) as client:
        page = client.get(f"/s/{code}/take?lang={lang}")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        assert rows(engine)[0]["state"] == "offered"
        body = fields(page, "/take") | {"action": "take"}
        assert client.post(f"/s/{code}/take", data=body).status_code == 403
        assert (
            client.post(
                f"/s/{code}/take", data=body | {"form_token": "bad"}, headers=ORIGIN
            ).status_code
            == 403
        )
        assert client.post(f"/s/{code}/take", data=body, headers=ORIGIN).status_code == 200
        assert rows(engine)[0]["state"] == "taken"
        assert client.post(f"/s/{code}/take", data=body, headers=ORIGIN).status_code == 200
        assert client.get("/s/invalid/take").status_code == 404


def test_pending_templates_and_recipient_isolation(engine):
    from nowa.messaging.outbox import enqueue_message, recipient
    from nowa.messaging.templates import OPERATIONAL
    from nowa.telegram.keyboards import markup_for

    cid, eid, clock, ids = full(engine)
    a = join(engine, clock, cid)
    get_settings().demo_mode = False
    with write_tx(engine) as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(is_sandbox=False))
    cancel(engine, clock, ids[0])
    with write_tx(engine) as conn:
        row = (
            conn.execute(select(s.outbox).where(s.outbox.c.standby_id == a.standby_id))
            .mappings()
            .one()
        )
        assert row["status"] == "blocked_unapproved"
        assert OPERATIONAL["standby_offer"]["status"] == "PENDING"
        assert recipient(conn, row)[1] == "fictional-50"
        assert urlsplit(markup_for(row)["inline_keyboard"][0][0]["url"]).path.startswith("/s/")
        with pytest.raises(ValueError, match="No recipient"):
            enqueue_message(
                conn,
                clock,
                1,
                "op:standby_offer",
                "en",
                "patient",
                None,
                {},
                "cross-clinic",
                standby_id=a.standby_id,
            )
