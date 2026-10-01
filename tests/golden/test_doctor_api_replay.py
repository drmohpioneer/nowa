from fastapi.testclient import TestClient
from sqlalchemy import select

from nowa import schema as s
from nowa import worker
from nowa.__main__ import migrate
from nowa.app import create_app
from nowa.core import timing, travel
from nowa.db import create_db_engine, write_tx
from tests.core.support import BASE, move, setup
from tests.helpers.worker import drain
from tests.web.support import ORIGIN


def replay(engine, browser):
    cid, eid, clock, ids = setup(engine, count=20)
    with write_tx(engine) as conn:
        for index, bid in enumerate(ids):
            conn.execute(
                s.bookings.update().where(s.bookings.c.id == bid).values(area_id=index % 12 + 1)
            )
    registry = worker.build_registry()
    with TestClient(create_app(engine, clock=clock), base_url="http://127.0.0.1:8000") as client:
        client.post(
            "/d/login", json={"mobile": "01000000001", "password": "demo1234"}, headers=ORIGIN
        )
        h = ORIGIN | {"X-CSRF-Token": client.cookies.get("nowa_csrf")}
        for minute in range(-30, 229):
            move(clock, minute)
            if minute == -30:
                if browser:
                    assert client.post(
                        "/d/api/on-my-way",
                        json={"lat": 30, "lng": 31, "idempotency_key": "way"},
                        headers=h,
                    ).json()["ok"]
                else:
                    assert timing.doctor_on_my_way(
                        engine, clock, cid, eid, travel.LatLng(30, 31), None, "way"
                    ).ok
            if minute >= 0 and minute % 12 == 0:
                index = minute // 12
                if index < len(ids):
                    if browser:
                        assert client.post(
                            "/d/api/who-comes-in",
                            json={"booking_id": ids[index], "idempotency_key": f"tap:{index}"},
                            headers=h,
                        ).json()["ok"]
                    else:
                        assert timing.who_comes_in(
                            engine, clock, cid, eid, ids[index], False, f"tap:{index}"
                        ).ok
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


def test_browser_api_matches_direct_engine_leave_order(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        travel,
        "minutes",
        lambda conn, cid, now, origin=None, area_id=None, *, doctor=False: (
            30.0 if origin else float((area_id % 4 + 1) * 10)
        ),
    )
    direct = replay(engine, False)
    other = create_db_engine(f"sqlite:///{tmp_path / 'browser.db'}")
    try:
        migrate(other)
        browser = replay(other, True)
    finally:
        other.dispose()
    assert len(browser) == len(direct) == 20
    assert browser == direct
