import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import timing
from nowa.db import write_tx
from nowa.telegram import keyboards
from nowa.web.strings import text
from tests.telegram.support import doctor_link, inline_data, tap


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_pause_buttons_replay_and_arrived_close_refusal(bot, engine, lang):
    router, cid, eid, did, clock, ids, fake = bot
    with write_tx(engine) as conn:
        conn.execute(s.doctors.update().where(s.doctors.c.id == did).values(lang=lang))
    doctor_link(bot, engine)
    tap(router, 2, "in", eid, ids[0])
    assert f"pause:{eid}:-:-" in inline_data(fake)
    tap(router, 3, "pause", eid)
    clock.advance(minutes=10)
    tap(router, 3, "pause", eid)
    with engine.connect() as conn:
        board = timing.tonight_board(conn, cid, eid, lang)
        assert len(conn.execute(select(s.evening_pauses)).all()) == 1
    rows = keyboards.board(eid, board, lang)["inline_keyboard"]
    assert rows[-2][0]["callback_data"] == f"wind:{eid}:-:-"
    assert rows[-1][0]["callback_data"] == f"resume:{eid}:-:-"
    assert text("tg.paused_since", lang).split("{time}")[0] in keyboards.board_text(board, lang)
    tap(router, 4, "arrived", eid, ids[1])
    tap(router, 5, "close", eid)
    response = next(p for method, p in reversed(fake.calls) if method == "editMessageText")
    assert response["reply_markup"]["inline_keyboard"] == []
    assert text("tg.arrived_present", lang) in response["text"]
    tap(router, 6, "resume", eid)
    with engine.connect() as conn:
        assert timing.tonight_board(conn, cid, eid).paused_since is None
    # A patient cannot pause the doctor's evening.
    tap(router, 7, "pause", eid, chat=202)
    with engine.connect() as conn:
        assert timing.tonight_board(conn, cid, eid).paused_since is None
