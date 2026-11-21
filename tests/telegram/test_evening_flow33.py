from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from nowa.telegram import keyboards
from nowa.web.strings import text
from tests.core.support import row
from tests.telegram.support import doctor_link, inline_data, tap


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_doctor_arrival_buttons_labels_and_replay(bot, engine, lang):
    router, cid, eid, did, clock, ids, fake = bot
    with write_tx(engine) as conn:
        conn.execute(s.doctors.update().where(s.doctors.c.id == did).values(lang=lang))
    doctor_link(bot, engine)
    tap(router, 2, "more", eid)
    assert f"arrived:{eid}:{ids[0]}:-" in inline_data(fake)
    tap(router, 3, "arrived", eid, ids[0])
    first = row(engine, s.bookings, ids[0])["arrived_at"]
    assert first == clock.now(cid)
    assert f"unarrived:{eid}:{ids[0]}:-" in inline_data(fake)
    assert any(text("tg.arrived", lang) in p.get("text", "") for _, p in fake.calls)
    clock.advance(minutes=1)
    tap(router, 3, "arrived", eid, ids[0])
    assert row(engine, s.bookings, ids[0])["arrived_at"] == first
    tap(router, 4, "unarrived", eid, ids[0])
    assert row(engine, s.bookings, ids[0])["arrived_at"] is None
    # A patient chat cannot invoke a doctor callback even with the exact row IDs.
    tap(router, 5, "arrived", eid, ids[0], chat=202)
    assert row(engine, s.bookings, ids[0])["arrived_at"] is None
    with write_tx(engine) as conn:
        assert not conn.execute(select(s.evening_taps)).first()
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[1])
            .values(state="told_to_leave", told_to_leave_at=clock.now(cid), silent=True)
        )
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[2])
            .values(state="on_my_way", on_my_way_at=clock.now(cid))
        )
        conn.execute(s.evenings.update().where(s.evenings.c.id == eid).values(covers_used=3))
        board = timing.tonight_board(conn, cid, eid, lang)
    body = keyboards.board_text(board, lang)
    for label in ("silent", "told_to_leave", "on_my_way", "cover_limit"):
        assert text("tg." + label, lang) in body


def test_telegram_close_preview_and_wind_down(bot, engine):
    router, cid, eid, did, clock, ids, fake = bot
    doctor_link(bot, engine)
    tap(router, 2, "in", eid, ids[0])
    with write_tx(engine) as conn:
        conn.execute(s.bookings.update().where(s.bookings.c.id == ids[-1]).values(state="booked"))
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[1])
            .values(state="on_my_way", expected_shown=clock.now(cid) + timedelta(minutes=60))
        )
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == ids[2])
            .values(state="told_to_leave", expected_shown=clock.now(cid))
        )
    tap(router, 3, "close", eid)
    preview = timing.close_preview(engine, clock, cid, eid)
    body = next(p["text"] for method, p in reversed(fake.calls) if method == "editMessageText")
    for person in preview.untold + preview.told + preview.passed:
        assert person.patient_name in body
    tap(router, 4, "wind", eid)
    assert f"windok:{eid}:-:{preview.untold_count}" in inline_data(fake)
    tap(router, 5, "windok", eid, arg=str(preview.untold_count))
    assert row(engine, s.evenings, eid)["state"] == "winding_down"
    assert any(text("tg.winding_down", "ar") in p.get("text", "") for _, p in fake.calls)
    tap(router, 6, "close", eid)
    tap(router, 7, "closeok", eid, arg="0")
    assert row(engine, s.evenings, eid)["state"] == "closed"


@pytest.mark.parametrize(
    "value", ["arrived:-:1:-", "arrived:1:-:-", "unarrived:1:1:yes", "windok:1:-:-1"]
)
def test_new_callback_shape_validation(value):
    with pytest.raises(ValueError):
        keyboards.parse(value)
