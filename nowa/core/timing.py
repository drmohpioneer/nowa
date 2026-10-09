import hashlib
import hmac
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.config import get_settings
from nowa.core import booking, learning, projection, timers, travel
from nowa.core.display import origin_label, patient_display_name
from nowa.core.text_norm import greeting_name
from nowa.core.travel import LatLng
from nowa.db import write_tx
from nowa.messaging.outbox import enqueue_message
from nowa.messaging.templates import DoctorNames


@dataclass(frozen=True)
class TapResult:
    ok: bool
    reason: str | None = None
    booking_id: int | None = None
    visit_id: int | None = None


@dataclass(frozen=True)
class OnMyWayResult:
    ok: bool
    eta_min: float | None = None
    projected_start: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CloseResult:
    ok: bool = True
    untold_cancelled: int = 0


@dataclass(frozen=True)
class CloseRefused:
    reason: str
    untold_count: int = 0
    ok: bool = False


@dataclass(frozen=True)
class ClosePreview:
    untold_count: int


@dataclass(frozen=True)
class BoardRow:
    booking_id: int
    queue_number: int
    patient_first_name: str | None
    state: str
    remaining: bool
    silent: bool
    source: str
    expected_shown: datetime | None
    told_to_leave_at: datetime | None
    on_my_way_at: datetime | None
    no_show_count: int
    origin_display: str = ""


@dataclass(frozen=True)
class Board:
    rows: list[BoardRow]


def _evening(conn: Connection, clinic_id: int, evening_id: int) -> RowMapping:
    return (
        conn.execute(
            select(s.evenings)
            .where(s.evenings.c.id == evening_id, s.evenings.c.clinic_id == clinic_id)
            .with_for_update()
        )
        .mappings()
        .one()
    )


def _replay(conn: Connection, clinic_id: int, key: str, command: str) -> dict[str, Any] | None:
    return booking._replay(conn, key, clinic_id, command)


def _finish(
    conn: Connection,
    clock: Clock,
    evening: RowMapping,
    key: str,
    command: str,
    result: TapResult | OnMyWayResult | CloseResult,
    actor: str = "doctor",
) -> None:
    data = asdict(result)
    if isinstance(result, OnMyWayResult) and result.projected_start is not None:
        data["projected_start"] = result.projected_start.timestamp()
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=evening["clinic_id"],
            key=key,
            command=command,
            result_json=data,
            created_at=clock.now(evening["clinic_id"]),
        )
    )
    record.write_action(conn, evening["clinic_id"], actor, command)
    recompute(conn, clock, evening["id"])


def patient_blanks(conn: Connection, booking_id: int, template: str) -> dict[str, Any]:
    row = conn.execute(select(s.bookings).where(s.bookings.c.id == booking_id)).mappings().one()
    doctor = (
        conn.execute(select(s.doctors).where(s.doctors.c.clinic_id == row["clinic_id"]))
        .mappings()
        .one()
    )
    blanks: dict[str, Any] = {
        "patient_name": dict(
            conn.execute(
                select(s.patients.c.name, s.patients.c.name_en).where(
                    s.patients.c.id == row["patient_id"]
                )
            )
            .mappings()
            .one()
        ),
        "doctor_name": DoctorNames(doctor["name_ar"], doctor["name_en"]),
        "queue_number": row["queue_number"],
        "clinic_phone": conn.execute(
            select(s.clinics.c.phone).where(s.clinics.c.id == row["clinic_id"])
        ).scalar_one(),
    }
    if template in {"1", "3", "4"}:
        blanks["day_franco" if row["lang"] == "franco" else "day"] = conn.execute(
            select(s.evenings.c.date).where(s.evenings.c.id == row["evening_id"])
        ).scalar_one()
    if template == "1":
        blanks.update(
            expected_time=row["expected_shown"], link="/l/" + booking.link_code_for(booking_id)
        )
    if template == "2":
        blanks["on_my_way_link"] = "/w/" + booking.link_code_for(booking_id)
    if template == "4":
        blanks["rebook_link"] = "/r/" + booking.link_code_for(booking_id)
    return blanks


def _arm(conn: Connection, clock: Clock, evening_id: int, kind: str, due: datetime) -> None:
    prefix = f"{kind}:{evening_id}:"
    pending = (
        conn.execute(
            select(s.timers).where(
                s.timers.c.idempotency_key.startswith(prefix, autoescape=True),
                s.timers.c.status == "pending",
            )
        )
        .mappings()
        .all()
    )
    if len(pending) == 1 and pending[0]["due_at"] == due:
        return
    timers.rearm(conn, clock, kind, evening_id, due, {"evening_id": evening_id})


def ensure_evening_timers(conn: Connection, clock: Clock, evening_id: int) -> None:
    row = (
        conn.execute(select(s.evenings).where(s.evenings.c.id == evening_id).with_for_update())
        .mappings()
        .one()
    )
    if row["state"] in {"closed", "cancelled"}:
        return
    hours = projection.paper_hours(conn, row["clinic_id"], row["date"])
    if hours is None:
        return
    for kind, due in (
        ("are_you_on_way", hours[0]),
        ("evening_system_close", hours[1] + timedelta(hours=2)),
    ):
        prefix = f"{kind}:{evening_id}:{int(due.timestamp())}:"
        existing = conn.execute(
            select(s.timers.c.id).where(
                s.timers.c.idempotency_key.startswith(prefix, autoescape=True),
                s.timers.c.status.in_(("pending", "running", "done")),
            )
        ).first()
        pending_changed = conn.execute(
            select(s.timers.c.id).where(
                s.timers.c.idempotency_key.startswith(f"{kind}:{evening_id}:", autoescape=True),
                s.timers.c.status == "pending",
                s.timers.c.due_at != due,
            )
        ).first()
        if existing is None or pending_changed is not None:
            _arm(conn, clock, evening_id, kind, due)


def recompute(conn: Connection, clock: Clock, evening_id: int) -> None:
    evening = (
        conn.execute(select(s.evenings).where(s.evenings.c.id == evening_id).with_for_update())
        .mappings()
        .one()
    )
    if evening["state"] in {"closed", "cancelled"}:
        return
    cid = evening["clinic_id"]
    conn.execute(
        s.bookings.update()
        .where(
            s.bookings.c.evening_id == evening_id,
            s.bookings.c.state != "told_to_leave",
            s.bookings.c.silent.is_(True),
        )
        .values(silent=False)
    )
    now = clock.now(cid)
    snap = projection.load_snapshot(conn, cid, evening["date"], now)
    pace = projection.current_pace(conn, cid, evening_id)
    cushion: int = conn.execute(
        select(s.clinics.c.cushion_min).where(s.clinics.c.id == cid)
    ).scalar_one()
    rows = (
        conn.execute(
            select(s.bookings)
            .where(
                s.bookings.c.evening_id == evening_id,
                s.bookings.c.state.in_(projection.WAITING_STATES),
            )
            .order_by(s.bookings.c.order_key, s.bookings.c.id)
        )
        .mappings()
        .all()
    )
    newly_silent = False
    k = 0
    future: list[datetime] = []
    for row in rows:
        silent = (
            row["state"] == "told_to_leave"
            and row["told_to_leave_at"] is not None
            and now >= row["told_to_leave_at"] + timedelta(minutes=10)
            and row["on_my_way_at"] is None
        )
        changes: dict[str, Any] = {}
        if silent != row["silent"]:
            changes["silent"] = silent
            newly_silent = newly_silent or silent
        projected = projection.expected_time(snap, k, pace, now)
        if not silent:
            k += 1
        if not row["expected_frozen"] and (
            row["expected_shown"] is None
            or projected - row["expected_shown"] >= timedelta(minutes=20)
        ):
            changes["expected_shown"] = projected
        if (
            evening["state"] in {"doctor_on_way", "running"}
            and row["state"] == "booked"
            and row["source"] == "chat"
            and row["told_to_leave_at"] is None
        ):
            drive = travel.minutes(conn, cid, now, area_id=row["area_id"])
            due = projected - timedelta(minutes=cushion + drive * 1.3 + 10)
            if due <= now:
                changes.update(
                    state="told_to_leave",
                    told_to_leave_at=now,
                    expected_frozen=True,
                    travel_min=drive,
                )
                enqueue_message(
                    conn,
                    clock,
                    cid,
                    "2",
                    row["lang"],
                    "patient",
                    row["id"],
                    patient_blanks(conn, row["id"], "2"),
                    f"leave_now:{row['id']}",
                )
                timers.schedule_timer(
                    conn,
                    cid,
                    "silent_check",
                    now + timedelta(minutes=10),
                    {"booking_id": row["id"], "evening_id": evening_id},
                    f"silent_check:{row['id']}",
                )
            else:
                future.append(due)
        if changes:
            conn.execute(s.bookings.update().where(s.bookings.c.id == row["id"]).values(**changes))
    if future:
        _arm(conn, clock, evening_id, "leave_now_check", min(future))
    else:
        key: str
        for key in (
            conn.execute(
                select(s.timers.c.idempotency_key).where(
                    s.timers.c.status == "pending",
                    s.timers.c.idempotency_key.startswith(
                        f"leave_now_check:{evening_id}:", autoescape=True
                    ),
                )
            )
            .scalars()
            .all()
        ):
            timers.cancel_timer(conn, key)

    from nowa.core.travel_mapbox import arm_travel_checks

    arm_travel_checks(conn, clock, evening_id)
    if newly_silent:
        from nowa.core.standby import offer_next

        offer_next(conn, clock, evening_id)


def _auto_due(conn: Connection, evening: RowMapping) -> datetime | None:
    taps = (
        conn.execute(select(s.evening_taps).where(s.evening_taps.c.evening_id == evening["id"]))
        .mappings()
        .all()
    )
    if not any(row["kind"] in {"who_comes_in", "walk_in"} for row in taps):
        return None
    hours = projection.paper_hours(conn, evening["clinic_id"], evening["date"])
    if hours is None:
        return None
    last = max(t for row in taps for t in (row["at"], row["undone_at"]) if t is not None)
    return max(hours[1], cast(datetime, last)) + timedelta(minutes=60)


def _arm_auto(conn: Connection, clock: Clock, evening: RowMapping) -> None:
    due = _auto_due(conn, evening)
    if due is not None:
        _arm(conn, clock, evening["id"], "evening_auto_close", due)


def _json_value(value: Any) -> Any:
    return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value


def _tap_begin(
    conn: Connection, clock: Clock, evening: RowMapping, kind: str, booking_id: int | None, key: str
) -> int:
    return int(
        conn.execute(
            s.evening_taps.insert()
            .values(
                clinic_id=evening["clinic_id"],
                evening_id=evening["id"],
                kind=kind,
                booking_id=booking_id,
                at=clock.now(evening["clinic_id"]),
                prior_json=[],
                after_json=[],
                idempotency_key=key,
            )
            .returning(s.evening_taps.c.id)
        ).scalar_one()
    )


def _tap_end(
    conn: Connection, tap_id: int, prior: list[dict[str, Any]], after: list[dict[str, Any]]
) -> None:
    conn.execute(
        s.evening_taps.update()
        .where(s.evening_taps.c.id == tap_id)
        .values(prior_json=prior, after_json=after)
    )


def _change(
    conn: Connection,
    table: Any,
    row_id: int,
    values: dict[str, Any],
    prior: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> None:
    row = conn.execute(select(table).where(table.c.id == row_id)).mappings().one()
    changed = {k: v for k, v in values.items() if row[k] != v}
    if not changed:
        return
    prior.append(
        {"table": table.name, "id": row_id, "fields": {k: _json_value(row[k]) for k in changed}}
    )
    after.append(
        {
            "table": table.name,
            "id": row_id,
            "fields": {k: _json_value(v) for k, v in changed.items()},
        }
    )
    conn.execute(table.update().where(table.c.id == row_id).values(**changed))


def doctor_on_my_way_in_tx(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    origin: LatLng | None,
    area_id: int | None,
    idempotency_key: str,
    *,
    travel_min: float | None = None,
) -> OnMyWayResult:
    saved = _replay(conn, clinic_id, idempotency_key, "doctor_on_my_way")
    if saved is not None:
        saved["projected_start"] = datetime.fromtimestamp(saved["projected_start"], UTC)
        return OnMyWayResult(**saved)
    evening = _evening(conn, clinic_id, evening_id)
    if evening["state"] != "scheduled":
        return OnMyWayResult(False, reason="invalid_state")
    now = clock.now(clinic_id)
    eta = (
        travel_min
        if travel_min is not None
        else travel.minutes(conn, clinic_id, now, origin, area_id, doctor=True)
    )
    snap = projection.load_snapshot(conn, clinic_id, evening["date"], now)
    projected = now + timedelta(minutes=eta + snap.start_gap_min)
    tap = _tap_begin(conn, clock, evening, "doctor_on_way", None, idempotency_key)
    prior: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    _change(
        conn,
        s.evenings,
        evening_id,
        dict(
            state="doctor_on_way",
            doctor_on_way_at=now,
            doctor_eta_min=eta,
            projected_start=projected,
        ),
        prior,
        after,
    )
    _tap_end(conn, tap, prior, after)
    result = OnMyWayResult(True, eta, projected)
    _finish(conn, clock, evening, idempotency_key, "doctor_on_my_way", result)
    return result


def who_comes_in_in_tx(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    booking_id: int | None,
    walk_in: bool,
    idempotency_key: str,
) -> TapResult:
    saved = _replay(conn, clinic_id, idempotency_key, "who_comes_in")
    if saved is not None:
        return TapResult(**saved)
    evening = _evening(conn, clinic_id, evening_id)
    row = (
        None
        if walk_in
        else conn.execute(
            select(s.bookings).where(
                s.bookings.c.id == booking_id,
                s.bookings.c.clinic_id == clinic_id,
                s.bookings.c.evening_id == evening_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if not walk_in:
        if row is not None and row["state"] == "seen":
            return TapResult(False, "already_seen")
        if row is None or row["state"] not in projection.WAITING_STATES:
            return TapResult(False, "invalid_booking")
    if evening["state"] not in {"scheduled", "doctor_on_way", "running"}:
        return TapResult(False, "invalid_state")
    now = clock.now(clinic_id)
    tap = _tap_begin(
        conn,
        clock,
        evening,
        "walk_in" if walk_in else "who_comes_in",
        None if walk_in else booking_id,
        idempotency_key,
    )
    prior: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    visit = (
        conn.execute(
            select(s.visits).where(
                s.visits.c.evening_id == evening_id, s.visits.c.ended_at.is_(None)
            )
        )
        .mappings()
        .one_or_none()
    )
    if visit is not None:
        duration = (now - visit["started_at"]).total_seconds() / 60
        accepted = visit["est_at_start"] is None or duration <= 2 * visit["est_at_start"]
        _change(conn, s.visits, visit["id"], dict(ended_at=now, accepted=accepted), prior, after)
    pace = projection.current_pace(conn, clinic_id, evening_id)
    if walk_in:
        number, order = conn.execute(
            select(func.max(s.bookings.c.queue_number), func.max(s.bookings.c.order_key)).where(
                s.bookings.c.evening_id == evening_id
            )
        ).one()
        booking_id = int(
            conn.execute(
                s.bookings.insert()
                .values(
                    clinic_id=clinic_id,
                    evening_id=evening_id,
                    queue_number=(number or 0) + 1,
                    order_key=(order or 0) + 1,
                    source="walkin_tap",
                    lang="ar",
                    state="seen",
                    created_at=now,
                )
                .returning(s.bookings.c.id)
            ).scalar_one()
        )
        prior.append({"table": "bookings", "id": booking_id, "fields": None})
        after.append({"table": "bookings", "id": booking_id, "fields": {"state": "seen"}})
        conn.execute(
            s.evening_taps.update().where(s.evening_taps.c.id == tap).values(booking_id=booking_id)
        )
    else:
        assert row is not None and booking_id is not None
        waiting = (
            conn.execute(
                select(s.bookings)
                .where(
                    s.bookings.c.evening_id == evening_id,
                    s.bookings.c.state.in_(projection.WAITING_STATES),
                    s.bookings.c.id != booking_id,
                )
                .order_by(s.bookings.c.order_key, s.bookings.c.id)
            )
            .mappings()
            .all()
        )
        skipped = [b for b in waiting if b["order_key"] < row["order_key"]]
        following = [b for b in waiting if b["order_key"] > row["order_key"]]
        if skipped:
            anchor = (
                following[min(2, len(following)) - 1]["order_key"]
                if following
                else row["order_key"]
            )
            upper = following[2]["order_key"] if len(following) > 2 else anchor + len(skipped) + 1
            step = (upper - anchor) / (len(skipped) + 1)
            for index, skipped_row in enumerate(skipped, 1):
                _change(
                    conn,
                    s.bookings,
                    skipped_row["id"],
                    {"order_key": anchor + index * step},
                    prior,
                    after,
                )
        _change(conn, s.bookings, booking_id, {"state": "seen"}, prior, after)
    visit_id = int(
        conn.execute(
            s.visits.insert()
            .values(
                clinic_id=clinic_id,
                evening_id=evening_id,
                booking_id=booking_id,
                started_at=now,
                est_at_start=pace,
                accepted=True,
            )
            .returning(s.visits.c.id)
        ).scalar_one()
    )
    prior.append({"table": "visits", "id": visit_id, "fields": None})
    after.append(
        {"table": "visits", "id": visit_id, "fields": {"ended_at": None, "accepted": True}}
    )
    _change(conn, s.evenings, evening_id, {"state": "running"}, prior, after)
    _tap_end(conn, tap, prior, after)
    _arm_auto(conn, clock, evening)
    result = TapResult(True, booking_id=booking_id, visit_id=visit_id)
    _finish(conn, clock, evening, idempotency_key, "who_comes_in", result)
    return result


def undo_last_in_tx(
    conn: Connection, clock: Clock, clinic_id: int, evening_id: int, idempotency_key: str
) -> TapResult:
    saved = _replay(conn, clinic_id, idempotency_key, "undo_last")
    if saved is not None:
        return TapResult(**saved)
    evening = _evening(conn, clinic_id, evening_id)
    if evening["state"] in {"closed", "cancelled"}:
        return TapResult(False, "evening_closed")
    tap = (
        conn.execute(
            select(s.evening_taps)
            .where(s.evening_taps.c.evening_id == evening_id, s.evening_taps.c.undone_at.is_(None))
            .order_by(s.evening_taps.c.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if tap is None:
        return TapResult(False, "nothing_to_undo")
    tables = {"bookings": s.bookings, "visits": s.visits, "evenings": s.evenings}
    for change in tap["after_json"]:
        table = tables[change["table"]]
        current = conn.execute(select(table).where(table.c.id == change["id"])).mappings().first()
        if current is None or any(
            _json_value(current[k]) != v for k, v in change["fields"].items()
        ):
            return TapResult(False, "changed_since")
    for change in reversed(tap["prior_json"]):
        table = tables[change["table"]]
        fields = change["fields"]
        if fields is None:
            conn.execute(table.delete().where(table.c.id == change["id"]))
        else:
            values = {
                k: datetime.fromisoformat(v)
                if isinstance(v, str) and (k.endswith("_at") or k == "projected_start")
                else v
                for k, v in fields.items()
            }
            conn.execute(table.update().where(table.c.id == change["id"]).values(**values))
    conn.execute(
        s.evening_taps.update()
        .where(s.evening_taps.c.id == tap["id"])
        .values(undone_at=clock.now(clinic_id))
    )
    _arm_auto(conn, clock, evening)
    result = TapResult(True)
    _finish(conn, clock, evening, idempotency_key, "undo_last", result)
    return result


def _patient_way(
    conn: Connection, clock: Clock, booking_id: int, key: str, undo: bool
) -> TapResult:
    row = conn.execute(select(s.bookings).where(s.bookings.c.id == booking_id)).mappings().first()
    if row is None:
        return TapResult(False, "invalid_booking")
    command = "patient_undo_on_my_way" if undo else "patient_on_my_way"
    evening = _evening(conn, row["clinic_id"], row["evening_id"])
    if evening["state"] in {"closed", "cancelled"}:
        return TapResult(False, "evening_closed")
    saved = _replay(conn, row["clinic_id"], key, command)
    if saved is not None:
        return TapResult(**saved)
    row = conn.execute(select(s.bookings).where(s.bookings.c.id == booking_id)).mappings().one()
    if row["state"] not in {"told_to_leave", "on_my_way"}:
        return TapResult(False, "invalid_booking")
    if undo or row["state"] != "on_my_way":
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == booking_id)
            .values(
                state="told_to_leave" if undo else "on_my_way",
                on_my_way_at=None if undo else clock.now(row["clinic_id"]),
                silent=False,
            )
        )
    result = TapResult(True, booking_id=booking_id)
    _finish(conn, clock, evening, key, command, result, "patient")
    return result


def patient_on_my_way_in_tx(
    conn: Connection, clock: Clock, booking_id: int, idempotency_key: str
) -> TapResult:
    return _patient_way(conn, clock, booking_id, idempotency_key, False)


def patient_undo_on_my_way_in_tx(
    conn: Connection, clock: Clock, booking_id: int, idempotency_key: str
) -> TapResult:
    return _patient_way(conn, clock, booking_id, idempotency_key, True)


def _cancel_timers(conn: Connection, evening_id: int) -> None:
    booking_ids: set[int] = set(
        conn.execute(select(s.bookings.c.id).where(s.bookings.c.evening_id == evening_id)).scalars()
    )
    outbox_ids: set[int] = set(
        conn.execute(select(s.outbox.c.id).where(s.outbox.c.booking_id.in_(booking_ids))).scalars()
    )
    cid: int = conn.execute(
        select(s.evenings.c.clinic_id).where(s.evenings.c.id == evening_id)
    ).scalar_one()
    for row in (
        conn.execute(
            select(s.timers).where(s.timers.c.clinic_id == cid, s.timers.c.status == "pending")
        )
        .mappings()
        .all()
    ):
        payload = row["payload_json"]
        if (
            payload.get("evening_id") == evening_id
            or payload.get("booking_id") in booking_ids
            or payload.get("outbox_id") in outbox_ids
        ):
            timers.cancel_timer(conn, row["idempotency_key"])


def _untold(conn: Connection, evening_id: int) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(s.bookings)
            .where(s.bookings.c.evening_id == evening_id, s.bookings.c.state == "booked")
        ).scalar_one()
    )


def close_preview(engine: Engine, clock: Clock, clinic_id: int, evening_id: int) -> ClosePreview:
    with engine.connect() as conn:
        conn.execute(
            select(s.evenings.c.id).where(
                s.evenings.c.id == evening_id, s.evenings.c.clinic_id == clinic_id
            )
        ).scalar_one()
        return ClosePreview(_untold(conn, evening_id))


def _cancel_bookings(
    conn: Connection, clock: Clock, evening: RowMapping, states: tuple[str, ...], kind: str
) -> int:
    rows = (
        conn.execute(
            select(s.bookings).where(
                s.bookings.c.evening_id == evening["id"], s.bookings.c.state.in_(states)
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        conn.execute(
            s.bookings.update()
            .where(s.bookings.c.id == row["id"])
            .values(state="cancelled", silent=False)
        )
        record.write_action(conn, evening["clinic_id"], "system", kind, row["id"])
        if row["source"] == "chat":
            enqueue_message(
                conn,
                clock,
                evening["clinic_id"],
                "4",
                row["lang"],
                "patient",
                row["id"],
                patient_blanks(conn, row["id"], "4"),
                f"{kind}:{row['id']}",
            )
    return len(rows)


def close_evening_in_tx(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    actor: Literal["doctor", "system"],
    idempotency_key: str,
    expected_untold: int | None = None,
    *,
    _system_no_taps: bool = False,
) -> CloseResult | CloseRefused:
    saved = _replay(conn, clinic_id, idempotency_key, "close_evening")
    if saved is not None:
        return CloseResult(**saved)
    evening = _evening(conn, clinic_id, evening_id)
    allowed = {"scheduled", "doctor_on_way"} if _system_no_taps else {"running"}
    if actor in {"doctor", "system"} and evening["state"] == "closed":
        return CloseResult()
    if actor not in {"doctor", "system"} or evening["state"] not in allowed:
        return CloseRefused("invalid_state")
    count = _untold(conn, evening_id)
    if actor == "doctor" and expected_untold != count:
        return CloseRefused("count_changed", count)
    now = clock.now(clinic_id)
    _cancel_timers(conn, evening_id)
    count = _cancel_bookings(conn, clock, evening, ("booked",), "close_untold")
    if not _system_no_taps:
        conn.execute(
            s.bookings.update()
            .where(
                s.bookings.c.evening_id == evening_id,
                s.bookings.c.state.in_(("told_to_leave", "on_my_way")),
            )
            .values(state="didnt_come", silent=False)
        )
        visit = (
            conn.execute(
                select(s.visits).where(
                    s.visits.c.evening_id == evening_id, s.visits.c.ended_at.is_(None)
                )
            )
            .mappings()
            .one_or_none()
        )
        if visit is not None:
            length = (now - visit["started_at"]).total_seconds() / 60
            accepted = actor == "doctor" and (
                visit["est_at_start"] is None or length <= 2 * visit["est_at_start"]
            )
            conn.execute(
                s.visits.update()
                .where(s.visits.c.id == visit["id"])
                .values(ended_at=now, accepted=accepted)
            )
    conn.execute(
        s.evenings.update()
        .where(s.evenings.c.id == evening_id)
        .values(
            state="closed",
            closed_at=now,
            closed_by="system_no_taps"
            if _system_no_taps
            else "doctor"
            if actor == "doctor"
            else "auto",
        )
    )
    from nowa.core.standby import close

    close(conn, clock, evening_id)
    from nowa.core.report import daily_totals

    daily_totals(conn, clinic_id, evening_id)
    if not _system_no_taps:
        learning.learn(conn, clinic_id, evening_id)
    timers.schedule_timer(
        conn,
        clinic_id,
        "evening_report",
        now,
        {"evening_id": evening_id},
        f"evening_report:{evening_id}",
    )
    result = CloseResult(untold_cancelled=count)
    _finish(conn, clock, evening, idempotency_key, "close_evening", result, actor)
    return result


def _token(clinic_id: int, evening_id: int, doctor_id: int, window: int) -> str:
    message = f"cancel_tonight|{clinic_id}|{evening_id}|{doctor_id}|{window}"
    return (
        hmac.new(get_settings().server_secret.encode(), message.encode(), hashlib.sha256)
        .digest()[:16]
        .hex()
    )


def request_cancel_tonight(
    engine: Engine, clock: Clock, clinic_id: int, evening_id: int, doctor_id: int
) -> str:
    with engine.connect() as conn:
        conn.execute(
            select(s.doctors.c.id).where(
                s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id
            )
        ).scalar_one()
        conn.execute(
            select(s.evenings.c.id).where(
                s.evenings.c.id == evening_id, s.evenings.c.clinic_id == clinic_id
            )
        ).scalar_one()
    return _token(clinic_id, evening_id, doctor_id, int(clock.now(clinic_id).timestamp()) // 600)


def cancel_tonight_in_tx(
    conn: Connection,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    doctor_id: int,
    confirm_token: str,
    idempotency_key: str,
) -> TapResult:
    saved = _replay(conn, clinic_id, idempotency_key, "cancel_tonight")
    if saved is not None:
        return TapResult(**saved)
    evening = _evening(conn, clinic_id, evening_id)
    window = int(clock.now(clinic_id).timestamp()) // 600
    doctor = conn.execute(
        select(s.doctors.c.id).where(
            s.doctors.c.id == doctor_id, s.doctors.c.clinic_id == clinic_id
        )
    ).scalar_one_or_none()
    if doctor is None or not any(
        hmac.compare_digest(confirm_token, _token(clinic_id, evening_id, doctor_id, w))
        for w in (window, window - 1)
    ):
        return TapResult(False, "invalid_token")
    if evening["state"] == "running":
        return TapResult(False, "evening_running")
    if evening["state"] not in {"scheduled", "doctor_on_way"}:
        return TapResult(False, "invalid_state")
    _cancel_timers(conn, evening_id)
    _cancel_bookings(conn, clock, evening, projection.WAITING_STATES, "cancel_tonight")
    conn.execute(
        s.evenings.update()
        .where(s.evenings.c.id == evening_id)
        .values(state="cancelled", cancelled_at=clock.now(clinic_id))
    )
    result = TapResult(True)
    from nowa.core.standby import close

    close(conn, clock, evening_id)
    _finish(conn, clock, evening, idempotency_key, "cancel_tonight", result)
    return result


def tonight_board(conn: Connection, clinic_id: int, evening_id: int, lang: str = "ar") -> Board:
    rows = (
        conn.execute(
            select(s.bookings, s.patients.c.name, s.patients.c.name_en)
            .outerjoin(s.patients, s.patients.c.id == s.bookings.c.patient_id)
            .where(s.bookings.c.clinic_id == clinic_id, s.bookings.c.evening_id == evening_id)
            .order_by(s.bookings.c.order_key, s.bookings.c.id)
        )
        .mappings()
        .all()
    )
    result = []
    for row in rows:
        count = (
            0
            if row["patient_id"] is None
            else conn.execute(
                select(func.count())
                .select_from(s.bookings)
                .where(
                    s.bookings.c.clinic_id == clinic_id,
                    s.bookings.c.patient_id == row["patient_id"],
                    s.bookings.c.state == "didnt_come",
                )
            ).scalar_one()
        )
        result.append(
            BoardRow(
                row["id"],
                row["queue_number"],
                greeting_name(patient_display_name(row, lang)) if row["name"] else None,
                row["state"],
                row["state"] in projection.WAITING_STATES,
                row["silent"],
                row["source"],
                row["expected_shown"],
                row["told_to_leave_at"],
                row["on_my_way_at"],
                count,
                origin_label(row, lang),
            )
        )
    return Board(result)


def doctor_on_my_way(
    engine: Engine,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    origin: LatLng | None,
    area_id: int | None,
    idempotency_key: str,
) -> OnMyWayResult:
    from nowa.core.travel_mapbox import MapboxAdapter, learn, record_call

    settings = get_settings()
    value = None
    with engine.connect() as conn:
        saved = _replay(conn, clinic_id, idempotency_key, "doctor_on_my_way")
        if saved is not None:
            saved["projected_start"] = datetime.fromtimestamp(saved["projected_start"], UTC)
            return OnMyWayResult(**saved)
        evening = _evening(conn, clinic_id, evening_id)
        if evening["state"] != "scheduled":
            return OnMyWayResult(False, reason="invalid_state")
        clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == clinic_id)).mappings().one()
        chosen = origin
        if chosen is None and area_id is not None:
            area = conn.execute(select(s.areas).where(s.areas.c.id == area_id)).mappings().one()
            chosen = LatLng(area["lat"], area["lng"])
        dest = LatLng(clinic["lat"], clinic["lng"])
        chain = travel.chain_for(clinic, settings).doctor
    if chosen is not None and isinstance(chain[0], MapboxAdapter):
        at = clock.now(clinic_id)
        value = chain[0].minutes(
            chosen, dest, at, ctx=travel.TravelContext(conn, clinic_id, area_id)
        )
        if value is not None:
            with write_tx(engine) as accounting:
                record_call(accounting, clinic_id, settings)
                if origin is None and area_id is not None:
                    learn(accounting, clinic_id, area_id, at, value)
    with write_tx(engine) as conn:
        return doctor_on_my_way_in_tx(
            conn, clock, clinic_id, evening_id, origin, area_id, idempotency_key, travel_min=value
        )


def who_comes_in(
    engine: Engine,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    booking_id: int | None,
    walk_in: bool,
    idempotency_key: str,
) -> TapResult:
    with write_tx(engine) as conn:
        return who_comes_in_in_tx(
            conn, clock, clinic_id, evening_id, booking_id, walk_in, idempotency_key
        )


def undo_last(
    engine: Engine, clock: Clock, clinic_id: int, evening_id: int, idempotency_key: str
) -> TapResult:
    with write_tx(engine) as conn:
        return undo_last_in_tx(conn, clock, clinic_id, evening_id, idempotency_key)


def patient_on_my_way(
    engine: Engine, clock: Clock, booking_id: int, idempotency_key: str
) -> TapResult:
    with write_tx(engine) as conn:
        return patient_on_my_way_in_tx(conn, clock, booking_id, idempotency_key)


def patient_undo_on_my_way(
    engine: Engine, clock: Clock, booking_id: int, idempotency_key: str
) -> TapResult:
    with write_tx(engine) as conn:
        return patient_undo_on_my_way_in_tx(conn, clock, booking_id, idempotency_key)


def close_evening(
    engine: Engine,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    actor: Literal["doctor", "system"],
    idempotency_key: str,
    expected_untold: int | None = None,
) -> CloseResult | CloseRefused:
    with write_tx(engine) as conn:
        return close_evening_in_tx(
            conn, clock, clinic_id, evening_id, actor, idempotency_key, expected_untold
        )


def cancel_tonight(
    engine: Engine,
    clock: Clock,
    clinic_id: int,
    evening_id: int,
    doctor_id: int,
    confirm_token: str,
    idempotency_key: str,
) -> TapResult:
    with write_tx(engine) as conn:
        return cancel_tonight_in_tx(
            conn, clock, clinic_id, evening_id, doctor_id, confirm_token, idempotency_key
        )
