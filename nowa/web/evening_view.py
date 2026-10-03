"""Read-only presentation of the engine's taps; never changes queue truth."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import schema as s


def booking_names(conn: Connection, clinic_id: int) -> dict[int, dict[str, Any]]:
    return {
        row.id: {
            "booking_id": row.id,
            "queue_number": row.queue_number,
            "first_name": row.name.split()[0] if row.name else None,
            "source": row.source,
        }
        for row in conn.execute(
            select(
                s.bookings.c.id, s.bookings.c.queue_number, s.bookings.c.source, s.patients.c.name
            )
            .outerjoin(
                s.patients,
                (s.patients.c.id == s.bookings.c.patient_id)
                & (s.patients.c.clinic_id == clinic_id),
            )
            .where(s.bookings.c.clinic_id == clinic_id)
        )
    }


def tap_state(conn: Connection, clinic_id: int, evening_id: int | None) -> dict[str, Any]:
    doctor: dict[str, Any] = {"on_way_at": None, "arrived_at": None}
    result: dict[str, Any] = {"in_room": None, "doctor": doctor}
    if evening_id is None:
        return result
    state: str = conn.execute(
        select(s.evenings.c.state).where(
            s.evenings.c.clinic_id == clinic_id, s.evenings.c.id == evening_id
        )
    ).scalar_one()
    taps = (
        conn.execute(
            select(s.evening_taps)
            .where(
                s.evening_taps.c.clinic_id == clinic_id,
                s.evening_taps.c.evening_id == evening_id,
                s.evening_taps.c.undone_at.is_(None),
            )
            .order_by(s.evening_taps.c.at, s.evening_taps.c.id)
        )
        .mappings()
        .all()
    )
    ways = [tap for tap in taps if tap["kind"] == "doctor_on_way"]
    visits = [tap for tap in taps if tap["kind"] in {"who_comes_in", "walk_in"}]
    doctor["on_way_at"] = ways[0]["at"].isoformat() if ways else None
    doctor["arrived_at"] = visits[0]["at"].isoformat() if visits else None
    if visits and state not in {"closed", "cancelled"}:
        latest = visits[-1]
        booking = booking_names(conn, clinic_id).get(latest["booking_id"])
        if booking is not None:
            result["in_room"] = {
                key: booking[key] for key in ("booking_id", "queue_number", "first_name")
            } | {"since": latest["at"].isoformat()}
    return result


def timeline(conn: Connection, clinic_id: int) -> list[dict[str, Any]]:
    actions = [
        dict(row)
        for row in conn.execute(
            select(
                s.action_record.c.id,
                s.action_record.c.at,
                s.action_record.c.kind,
                s.action_record.c.booking_id,
            )
            .where(s.action_record.c.clinic_id == clinic_id)
            .order_by(s.action_record.c.id)
        ).mappings()
    ]
    names = booking_names(conn, clinic_id)
    taps = {
        row["idempotency_key"]: row
        for row in conn.execute(
            select(s.evening_taps)
            .where(s.evening_taps.c.clinic_id == clinic_id)
            .order_by(s.evening_taps.c.id)
        ).mappings()
    }
    # _finish inserts one engine command result, then one action of that command.
    # Their per-command insertion order is the durable binding, including several
    # patient taps in one minute. Timestamp equality would fail on a fractional
    # offset clock. HTTP replay rows have different commands and are excluded.
    recovered: dict[int, Any] = {}
    commands = ("who_comes_in", "doctor_on_my_way", "patient_on_my_way", "patient_undo_on_my_way")
    for command in commands:
        events = [event for event in actions if event["kind"] == command]
        results = (
            conn.execute(
                select(s.idempotency_keys)
                .where(
                    s.idempotency_keys.c.clinic_id == clinic_id,
                    s.idempotency_keys.c.command == command,
                )
                .order_by(s.idempotency_keys.c.id)
            )
            .mappings()
            .all()
        )
        # Never guess a binding if retention has removed part of the audit trail.
        if len(events) != len(results):
            continue
        for event, saved in zip(events, results, strict=True):
            tap = taps.get(saved["key"])
            recovered[event["id"]] = (tap, saved["result_json"].get("booking_id"))
    for event in actions:
        tap, bid = recovered.get(event["id"], (None, event["booking_id"]))
        event["booking"] = names.get(tap["booking_id"] if tap else bid)
        event["tap_kind"] = tap["kind"] if tap else None
        event["undone_at"] = tap["undone_at"] if tap else None
    return actions
