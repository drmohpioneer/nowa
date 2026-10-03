"""Minute-by-minute replay over accepted engine commands and durable run state."""

import asyncio
import logging
import math
import threading
from dataclasses import asdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from nowa import record, worker
from nowa import schema as s
from nowa.ai.conversation import _health_record
from nowa.ai.health import Answered
from nowa.ai.schema import ChatResponse
from nowa.clock import CAIRO, Clock, FrozenClock
from nowa.core import booking, flows, projection, questions, report, signup, timing, travel
from nowa.db import write_tx
from nowa.demo import evening_script as script
from nowa.library.answer import RecordedHealthAnswerer
from nowa.web.evening_view import tap_state, timeline

logger = logging.getLogger(__name__)
# One web instance per database. Locks serialize requests, not run state.
_LOCKS = tuple(threading.RLock() for _ in range(64))


def stage_start_minute() -> int:
    return min(script.CANCEL_MINUTE, script.ON_WAY_MINUTE) - 10


class EveningRunner:
    def __init__(self, clinic_id: int, *, engine: Engine, clock: Clock) -> None:
        self.clinic_id = clinic_id
        self.engine = engine
        self.clock = clock
        self.registry = worker.build_registry()
        self.lock = _LOCKS[clinic_id % len(_LOCKS)]

    def _run(self, conn: Connection) -> dict[str, Any]:
        return dict(
            conn.execute(
                select(s.demo_runs)
                .where(s.demo_runs.c.clinic_id == self.clinic_id, s.demo_runs.c.kind == "watch")
                .with_for_update()
            )
            .mappings()
            .one()
        )

    def _zero(self, conn: Connection) -> datetime:
        created: datetime = conn.execute(
            select(s.clinics.c.created_at).where(s.clinics.c.id == self.clinic_id)
        ).scalar_one()
        day = created.astimezone(CAIRO).date()
        day += timedelta(days=(1 - day.weekday()) % 7 or 7)
        return datetime.combine(day, time(16), CAIRO)

    def _position(self, minute: int) -> None:
        with write_tx(self.engine) as conn:
            at = self._zero(conn) + timedelta(minutes=minute)
            offset = math.ceil(
                (at - self.clock.now(signup.system_id(conn), conn=conn)).total_seconds()
            )
            conn.execute(
                s.clinics.update()
                .where(s.clinics.c.id == self.clinic_id)
                .values(demo_run_active=True, clock_offset_s=offset)
            )

    def _key(self, run: dict[str, Any], command: str) -> str:
        return f"demo:{run['run_id']}:{command}"

    def start(self) -> None:
        with self.lock:
            with self.engine.connect() as conn:
                step = self._run(conn)["step"]
            if step:
                if step == 2:
                    # A restart may follow the atomic close checkpoint but precede
                    # report delivery. Resume those durable timers without another tap.
                    worker.drain(
                        self.engine, self.clock, self.registry, only_clinic_id=self.clinic_id
                    )
                return
            script.validate()
            self._position(0)  # Committed before booking; shared clock sees the copy's offset.
            with write_tx(self.engine) as conn:
                run = self._run(conn)
                if run["step"]:
                    return
                instant = FrozenClock(self._zero(conn))
                areas = {
                    r.name_en: r.id for r in conn.execute(select(s.areas.c.name_en, s.areas.c.id))
                }
                ids: dict[int, int] = {}
                for patient in script.PATIENTS:
                    result = flows.book_in_tx(
                        conn,
                        instant,
                        booking.BookingRequest(
                            self.clinic_id,
                            instant.now(self.clinic_id).date(),
                            patient.name,
                            patient.phone,
                            patient.lang,
                            areas[patient.area],
                            booking.ConsentInput(
                                "fictional",
                                "fictional",
                                "other" if patient.number == script.KARIM else "self",
                            ),
                            self._key(run, f"book:{patient.number}"),
                            actor="system",
                        ),
                    )
                    if not isinstance(result, booking.BookingOk):
                        raise RuntimeError(
                            f"Demo booking {patient.number} refused: {result.reason}"
                        )
                    if result.queue_number != patient.number:
                        raise RuntimeError("Demo queue diverged")
                    ids[patient.number] = result.booking_id
                data_dir = Path(__file__).resolve().parents[1] / "library/data"
                answer = asyncio.run(
                    RecordedHealthAnswerer(self.engine, data_dir).answer(
                        clinic_id=self.clinic_id,
                        specialty="cardiology",
                        question=script.HEALTH_QUESTION,
                        lang="ar",
                        session_id=run["run_id"],
                    )
                )
                if not isinstance(answer, Answered):
                    raise RuntimeError(f"Recorded demo answer refused: {answer.reason}")
                contact_id: int = conn.execute(
                    select(s.bookings.c.contact_id).where(s.bookings.c.id == ids[script.KARIM])
                ).scalar_one()
                _health_record(
                    conn,
                    instant,
                    self.clinic_id,
                    {"contact_id": contact_id},
                    script.HEALTH_QUESTION,
                    ChatResponse(reply=answer.answer),
                    "normal",
                    answer.model,
                    answer,
                    (),
                )
                record.write_action(
                    conn, self.clinic_id, "patient", "chat_in", text=script.HEALTH_QUESTION
                )
                record.write_action(
                    conn,
                    self.clinic_id,
                    "ai",
                    "chat_out:normal",
                    text=answer.answer,
                    model=answer.model,
                )
                questions.log_question(
                    conn,
                    instant,
                    self.clinic_id,
                    script.DOCTOR_QUESTION,
                    self._key(run, "question"),
                )
                T = travel.minutes(
                    conn,
                    self.clinic_id,
                    instant.now(self.clinic_id),
                    area_id=areas[script.DOCTOR_AREA],
                    doctor=True,
                )
                if abs(T - 35) > 5:
                    raise RuntimeError(f"Doctor travel diverged: T={T}")
                logger.warning("Demo doctor travel: area=%s T=%s min", script.DOCTOR_AREA, T)
                conn.execute(
                    s.demo_runs.update()
                    .where(s.demo_runs.c.run_id == run["run_id"])
                    .values(
                        step=1, minute=0, visit_index=0, last_step_at=instant.now(self.clinic_id)
                    )
                )
            worker.drain(self.engine, self.clock, self.registry, only_clinic_id=self.clinic_id)

    def advance(self, to_minute: int) -> None:
        if type(to_minute) is not int or not 0 <= to_minute <= 600:
            raise ValueError("to_minute must be an integer in 0..600")
        with self.lock:
            self.start()
            with self.engine.connect() as conn:
                run = self._run(conn)
            if run["step"] == 2 or to_minute <= run["minute"]:
                return
            for minute in range(run["minute"] + 1, to_minute + 1):
                self._position(minute)
                # Worker owns its transactions and after-commit sends. Human actions and
                # the minute checkpoint commit together after the unchanged drain returns.
                worker.drain(self.engine, self.clock, self.registry, only_clinic_id=self.clinic_id)
                with write_tx(self.engine) as conn:
                    current = self._run(conn)
                    instant = FrozenClock(self._zero(conn) + timedelta(minutes=minute))
                    closed = self._actions(conn, instant, current, minute)
                    conn.execute(
                        s.demo_runs.update()
                        .where(s.demo_runs.c.run_id == current["run_id"])
                        .values(
                            minute=minute,
                            visit_index=current["visit_index"],
                            step=2 if closed else 1,
                            last_step_at=instant.now(self.clinic_id),
                        )
                    )
                if closed:
                    # Deliver the final report before returning its read-only state.
                    worker.drain(
                        self.engine, self.clock, self.registry, only_clinic_id=self.clinic_id
                    )
                    return

    def _actions(self, conn: Connection, clock: Clock, run: dict[str, Any], minute: int) -> bool:
        cid = self.clinic_id
        now = clock.now(cid)
        rows = [
            dict(r)
            for r in conn.execute(
                select(s.bookings)
                .where(s.bookings.c.clinic_id == cid)
                .order_by(s.bookings.c.order_key, s.bookings.c.id)
            ).mappings()
        ]
        eid = rows[0]["evening_id"]
        by_number = {r["queue_number"]: r for r in rows}
        if minute == script.CANCEL_MINUTE:
            # The link page's orchestration calls this same accepted transaction flow.
            row = by_number[script.CANCEL]
            result = flows.cancel_in_tx(
                conn,
                clock,
                booking.link_code_for(row["id"]),
                script.PATIENTS[script.CANCEL - 1].phone[-4:],
                self._key(run, "cancel"),
            )
            if not isinstance(result, booking.CancelResult):
                raise RuntimeError(f"Demo cancellation refused: {result.reason}")
        if minute == script.ON_WAY_MINUTE:
            area_id: int = conn.execute(
                select(s.areas.c.id).where(s.areas.c.name_en == script.DOCTOR_AREA)
            ).scalar_one()
            on_way = timing.doctor_on_my_way_in_tx(
                conn, clock, cid, eid, None, area_id, self._key(run, "doctor-way")
            )
            if not on_way.ok:
                raise RuntimeError(f"Demo doctor tap refused: {on_way.reason}")
        for row in rows:
            number = row["queue_number"]
            if number > 18 or number in (script.SILENT, script.NO_SHOW, script.CANCEL):
                continue
            told = row["told_to_leave_at"]
            if (
                told
                and row["state"] == "told_to_leave"
                and now >= told + timedelta(minutes=script.PATIENTS[number - 1].reaction_min)
            ):
                tap = timing.patient_on_my_way_in_tx(
                    conn, clock, row["id"], self._key(run, f"patient-way:{number}")
                )
                if not tap.ok:
                    raise RuntimeError(f"Demo patient tap refused: {tap.reason}")
        evening = conn.execute(select(s.evenings).where(s.evenings.c.id == eid)).mappings().one()
        if evening["projected_start"] is None or now < evening["projected_start"]:
            return False
        visit = (
            conn.execute(
                select(s.visits).where(s.visits.c.evening_id == eid, s.visits.c.ended_at.is_(None))
            )
            .mappings()
            .first()
        )
        if visit and now < visit["started_at"] + timedelta(
            minutes=script.VISIT_LENGTHS[run["visit_index"] - 1]
        ):
            return False
        # A direct walk-in is the next actual visit after patient 9's visit ends.
        walk_in = bool(visit and by_number[script.WALK_IN_AFTER]["id"] == visit["booking_id"])
        waiting = [
            dict(r)
            for r in conn.execute(
                select(s.bookings)
                .where(
                    s.bookings.c.evening_id == eid,
                    s.bookings.c.state.in_(projection.WAITING_STATES),
                    s.bookings.c.queue_number != script.NO_SHOW,
                )
                .order_by(s.bookings.c.order_key, s.bookings.c.id)
            ).mappings()
        ]
        if not waiting and not walk_in:
            preview = timing.ClosePreview(timing._untold(conn, eid))
            result_close = timing.close_evening_in_tx(
                conn, clock, cid, eid, "doctor", self._key(run, "close"), preview.untold_count
            )
            if isinstance(result_close, timing.CloseRefused):
                raise RuntimeError(f"Demo close refused: {result_close.reason}")
            return True
        arrived = None
        for row in waiting:
            if row["queue_number"] == script.SILENT:
                ready = row["told_to_leave_at"] and now >= row["told_to_leave_at"] + timedelta(
                    minutes=25
                )
            else:
                ready = row["on_my_way_at"] and now >= row["on_my_way_at"] + timedelta(
                    minutes=row["travel_min"]
                )
            if ready:
                arrived = row["id"]
                break
        if walk_in or arrived is not None:
            tap = timing.who_comes_in_in_tx(
                conn,
                clock,
                cid,
                eid,
                arrived,
                walk_in,
                self._key(run, f"visit:{run['visit_index']}"),
            )
            if not tap.ok:
                raise RuntimeError(f"Demo visit refused: {tap.reason}")
            run["visit_index"] += 1
        return False

    def state(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            run = self._run(conn)
            evening = (
                conn.execute(select(s.evenings).where(s.evenings.c.clinic_id == self.clinic_id))
                .mappings()
                .first()
            )
            clinic = (
                conn.execute(select(s.clinics).where(s.clinics.c.id == self.clinic_id))
                .mappings()
                .one()
            )
            T = travel.minutes(
                conn,
                self.clinic_id,
                self.clock.now(self.clinic_id),
                area_id=conn.execute(
                    select(s.areas.c.id).where(s.areas.c.name_en == script.DOCTOR_AREA)
                ).scalar_one(),
                doctor=True,
            )
            additions: dict[str, Any] = {
                "clinic": {
                    "name": clinic["name"],
                    "specialty": clinic["specialty"],
                    "area": clinic["address"],
                },
                "evening": {
                    "first_minute": 0,
                    "last_minute": 600,
                    "weekday": 1,
                    "start_minute": stage_start_minute(),
                    "start_at": self._zero(conn) + timedelta(minutes=stage_start_minute()),
                    "end_at": self._zero(conn) + timedelta(minutes=600),
                },
                "in_room": tap_state(conn, self.clinic_id, evening["id"] if evening else None)[
                    "in_room"
                ],
            }
            if evening and run["step"] == 2:
                result = report.build_report(conn, self.clock, self.clinic_id, evening["id"])
                additions["report"] = {
                    key: getattr(result, key)
                    for key in ("booked", "came", "no_show_count", "walk_ins", "avg_wait")
                    if getattr(result, key) is not None
                }
            return dict(
                **additions,
                run_id=run["run_id"],
                minute=run["minute"],
                closed=run["step"] == 2,
                clock=self.clock.now(self.clinic_id),
                doctor_travel_min=T,
                queue=[
                    asdict(r)
                    for r in timing.tonight_board(conn, self.clinic_id, evening["id"]).rows
                ]
                if evening
                else [],
                timeline=timeline(conn, self.clinic_id),
                chat_url="/c/" + clinic["slug"],
                report_url=f"/d/report/{evening['id']}" if evening and run["step"] == 2 else None,
            )
