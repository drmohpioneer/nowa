from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.__main__ import migrate
from nowa.core import travel
from nowa.db import create_db_engine, write_tx
from nowa.telegram.router import Router
from tests.core.support import BASE, move, setup
from tests.golden.test_doctor_api_replay import replay as browser_replay
from tests.helpers.worker import drain
from tests.telegram.conftest import FakeTelegramAPI
from tests.telegram.support import doctor_link, message, tap


def telegram_replay(engine):
    cid, eid, clock, ids = setup(engine, count=20)
    with write_tx(engine) as conn:
        for index, bid in enumerate(ids):
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == bid).values(area_id=index % 12 + 1)
            )
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    api = FakeTelegramAPI()
    router = Router(engine, clock, api)
    doctor_link((router, cid, eid, did, clock, ids, api), engine)
    registry = worker.build_registry()
    for minute in range(-30, 229):
        move(clock, minute)
        if minute == -30:
            tap(router, 2, "omw", eid)
            router.handle_update(message(3, location={"latitude": 30, "longitude": 31}))
        if minute >= 0 and minute % 12 == 0:
            index = minute // 12
            if index < len(ids):
                tap(router, 100 + index, "in", eid, ids[index])
        drain(engine, clock, registry)
    with engine.connect() as conn:
        return sorted(
            (int((at - BASE).total_seconds() / 60), number)
            for at, number in conn.execute(
                select(s.outbox.c.created_at, s.bookings.c.queue_number)
                .join(s.bookings, s.bookings.c.id == s.outbox.c.booking_id)
                .where(s.outbox.c.template_id == "2")
            )
        )


def test_telegram_matches_dashboard_leave_now_order(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        travel,
        "minutes",
        lambda conn, cid, now, origin=None, area_id=None, *, doctor=False: (
            30.0 if origin else float((area_id % 4 + 1) * 10)
        ),
    )
    telegram = telegram_replay(engine)
    other = create_db_engine(f"sqlite:///{tmp_path / 'browser.db'}")
    try:
        migrate(other)
        browser = browser_replay(other, True)
    finally:
        other.dispose()
    assert len(telegram) == len(browser) == 20
    assert telegram == browser
