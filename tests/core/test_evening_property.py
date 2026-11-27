"""Forty reproducible evenings exercise stored messages and queue invariants."""

import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.config import GET_READY_MIN
from nowa.core import timing
from nowa.db import write_tx
from tests.core.support import move, setup


def assert_message_clocks(conn):
    for msg, drive in conn.execute(
        select(s.outbox.c.values_json, s.bookings.c.travel_min)
        .join(s.bookings, s.bookings.c.id == s.outbox.c.booking_id)
        .where(s.outbox.c.template_id == "2")
    ):
        leave = datetime.fromisoformat(msg["leave_by"]["value"])
        arrive = datetime.fromisoformat(msg["arrive_by"]["value"])
        # recompute: due = projected - cushion - drive * 1.3 - GET_READY_MIN.
        # leave = sent + GET_READY_MIN; arrive = max(projected - cushion,
        # leave + drive * 1.3). Clock rendering may round by up to one minute.
        assert arrive >= leave
        assert (arrive - leave).total_seconds() / 60 >= drive * 1.3 - 1


@pytest.mark.parametrize("seed", range(40))
def test_random_evening(engine, seed):
    rng = random.Random(seed)
    cid, eid, clock, ids = setup(engine, count=rng.randint(6, 14), pace=rng.randint(8, 20))
    with write_tx(engine) as conn:
        for bid in ids:
            conn.execute(
                s.bookings.update()
                .where(s.bookings.c.id == bid)
                .values(area_id=rng.choice([None, 1, 3, 7, 12]))
            )
    move(clock, rng.randint(0, 45))
    timing.doctor_on_my_way(engine, clock, cid, eid, None, None, "way")
    for tick in range(50):
        clock.advance(minutes=rng.randint(2, 15))
        with write_tx(engine) as conn:
            before = {
                r["id"]: r
                for r in conn.execute(
                    select(s.bookings).where(s.bookings.c.evening_id == eid)
                ).mappings()
            }
            waiting = [
                bid
                for bid, r in before.items()
                if r["state"] in ("booked", "told_to_leave", "on_my_way")
            ]
            state = conn.execute(
                select(s.evenings.c.state).where(s.evenings.c.id == eid)
            ).scalar_one()
            if state == "closed":
                break
            paused = timing._open_pause(conn, cid, eid) is not None
            leaves = set(
                conn.execute(select(s.outbox.c.id).where(s.outbox.c.template_id == "2")).scalars()
            )
            action = rng.choice(
                ["admit", "admit", "arrive", "unarrive", "undo", "pause", "resume", "tick"]
            )
            if tick > 35:
                action = rng.choice([action, "wind", "close"])
            subject = rng.choice(waiting) if waiting else None
            key = f"{action}:{tick}"
            if subject is not None and action == "admit":
                timing.who_comes_in_in_tx(conn, clock, cid, eid, subject, False, key)
            elif subject is not None and action in {"arrive", "unarrive"}:
                command = (
                    timing.mark_arrived_in_tx if action == "arrive" else timing.undo_arrived_in_tx
                )
                command(conn, clock, cid, subject, "doctor", key)
            elif action == "undo":
                timing.undo_last_in_tx(conn, clock, cid, eid, key)
            elif action in {"pause", "resume"}:
                command = timing.pause_in_tx if action == "pause" else timing.resume_in_tx
                command(conn, clock, cid, eid, key)
            elif action in {"wind", "close"}:
                count = timing._untold(conn, eid)
                if action == "wind":
                    timing.wind_down_in_tx(conn, clock, cid, eid, key, count)
                else:
                    timing.close_evening_in_tx(conn, clock, cid, eid, "doctor", key, count)
            timing.recompute(conn, clock, eid)
            after = {
                r["id"]: r
                for r in conn.execute(
                    select(s.bookings).where(s.bookings.c.evening_id == eid)
                ).mappings()
            }
            for bid, old in before.items():
                if old["arrived_at"] is not None and not (action == "admit" and bid == subject):
                    assert after[bid]["order_key"] == old["order_key"]
                    assert after[bid]["state"] not in {"cancelled", "didnt_come"}
            if paused and timing._open_pause(conn, cid, eid) is not None:
                assert (
                    set(
                        conn.execute(
                            select(s.outbox.c.id).where(s.outbox.c.template_id == "2")
                        ).scalars()
                    )
                    == leaves
                )
            assert_message_clocks(conn)


def test_late_send_uses_truthful_arrival_not_stale_shown_time(engine, monkeypatch):
    from nowa.core import travel

    cid, eid, clock, ids = setup(engine, count=1)
    monkeypatch.setattr(travel, "minutes", lambda *args, **kwargs: 10)
    move(clock, 90)
    with write_tx(engine) as conn:
        timing.doctor_on_my_way_in_tx(conn, clock, cid, eid, None, None, "way", travel_min=0)
        msg = conn.execute(select(s.outbox).where(s.outbox.c.template_id == "2")).mappings().one()
        leave = datetime.fromisoformat(msg["values_json"]["leave_by"]["value"])
        arrive = datetime.fromisoformat(msg["values_json"]["arrive_by"]["value"])
        assert leave == clock.now(cid) + timedelta(minutes=GET_READY_MIN)
        assert arrive == leave + timedelta(minutes=13)
        assert_message_clocks(conn)
