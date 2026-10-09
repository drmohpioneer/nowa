import secrets
from dataclasses import asdict
from datetime import UTC, date, timedelta
from json import JSONDecodeError
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.engine import Connection

from nowa import record
from nowa import schema as s
from nowa.core import auth, booking, clinic_settings, timing
from nowa.core.clinic_settings import Input
from nowa.core.travel import LatLng
from nowa.db import write_tx
from nowa.web.doctor_auth import CommandSession, Session, doctor_language
from nowa.web.evening_view import tap_state

router = APIRouter(prefix="/d/api")


class Command(Input):
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    evening_id: Annotated[int | None, Field(strict=True, gt=0)] = None


class OnWay(Command):
    lat: Annotated[float | None, Field(ge=-90, le=90, allow_inf_nan=False)] = None
    lng: Annotated[float | None, Field(ge=-180, le=180, allow_inf_nan=False)] = None
    area_id: Annotated[int | None, Field(strict=True, gt=0)] = None

    @model_validator(mode="after")
    def location(self) -> "OnWay":
        if not (
            (self.lat is not None and self.lng is not None and self.area_id is None)
            or (self.lat is None and self.lng is None and self.area_id is not None)
        ):
            raise ValueError("lat, lng or area_id")
        return self


class Who(Command):
    booking_id: Annotated[int | None, Field(strict=True, gt=0)] = None
    walk_in: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def one_subject(self) -> "Who":
        if (self.booking_id is not None) == self.walk_in:
            raise ValueError("booking_id or walk_in")
        return self


class Close(Command):
    expected_untold: Annotated[int, Field(strict=True, ge=0)]


class Cancel(Command):
    confirm_token: str


def own(conn: Connection, session: auth.Session, body: Command | None) -> None:
    # evening_id checks ownership only; evening commands always act on tonight's evening.
    for table, row_id in (
        (s.evenings, body.evening_id if body else None),
        (s.bookings, body.booking_id if isinstance(body, Who) else None),
    ):
        if (
            row_id is not None
            and conn.execute(
                select(table.c.id).where(
                    table.c.id == row_id, table.c.clinic_id == session.clinic_id
                )
            ).first()
            is None
        ):
            raise HTTPException(404)


def evening(conn: Connection, request: Request, session: auth.Session) -> int | None:
    tonight = booking.tonight_evening(
        conn, session.clinic_id, request.app.state.clock.now(session.clinic_id)
    )
    return tonight.evening_id if tonight else None


def replay(
    conn: Connection, session: auth.Session, key: str, command: str
) -> dict[str, Any] | None:
    try:
        return booking._replay(conn, key, session.clinic_id, "http:" + command)
    except booking.IdempotencyConflict:
        raise HTTPException(409, detail={"reason": "idempotency_conflict"}) from None


def save(
    conn: Connection,
    request: Request,
    session: auth.Session,
    key: str,
    command: str,
    data: dict[str, Any],
    status: int = 200,
) -> None:
    conn.execute(
        s.idempotency_keys.insert().values(
            clinic_id=session.clinic_id,
            key=key,
            command="http:" + command,
            result_json={"data": jsonable_encoder(data), "status": status},
            created_at=request.app.state.clock.now(session.clinic_id),
        )
    )


@router.get("/tonight")
def tonight(request: Request, session: Session) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        eid = evening(conn, request, session)
        lang = doctor_language(request, conn, session)
        board = (
            timing.tonight_board(conn, session.clinic_id, eid, lang)
            if eid is not None
            else timing.Board([])
        )
        areas = [
            dict(r)
            for r in conn.execute(
                select(s.areas.c.id, s.areas.c.name_ar, s.areas.c.name_en)
            ).mappings()
        ]
        from nowa.core.standby import count

        return {
            "standby_count": count(conn, session.clinic_id, eid),
            **tap_state(conn, session.clinic_id, eid, lang),
            "can_undo": eid is not None
            and conn.execute(
                select(s.evening_taps.c.id).where(
                    s.evening_taps.c.clinic_id == session.clinic_id,
                    s.evening_taps.c.evening_id == eid,
                    s.evening_taps.c.undone_at.is_(None),
                )
            ).first()
            is not None,
            "latest_report_id": conn.execute(
                select(s.evenings.c.id)
                .where(
                    s.evenings.c.clinic_id == session.clinic_id,
                    s.evenings.c.state == "closed",
                )
                .order_by(s.evenings.c.date.desc())
                .limit(1)
            ).scalar_one_or_none(),
            "evening_id": eid,
            "rows": [asdict(r) for r in board.rows],
            "areas": areas,
            "reason": "no_evening" if eid is None else None,
        }


def run(request: Request, session: auth.Session, body: Command, command: str) -> JSONResponse:
    with write_tx(request.app.state.engine) as conn:
        own(conn, session, body)
        saved = replay(conn, session, body.idempotency_key, command)
        if saved is not None:
            return JSONResponse(saved["data"], status_code=saved["status"])
        eid = evening(conn, request, session)
        clock = request.app.state.clock
        cid = session.clinic_id
        key = "engine:" + body.idempotency_key
        status = 200
        if eid is None:
            data: dict[str, Any] = {"ok": False, "reason": "no_evening"}
        elif command == "who-comes-in":
            assert isinstance(body, Who)
            data = asdict(
                timing.who_comes_in_in_tx(conn, clock, cid, eid, body.booking_id, body.walk_in, key)
            )
        elif command == "undo":
            data = asdict(timing.undo_last_in_tx(conn, clock, cid, eid, key))
        elif command == "close":
            assert isinstance(body, Close)
            result = timing.close_evening_in_tx(
                conn, clock, cid, eid, "doctor", key, body.expected_untold
            )
            data = asdict(result)
            if isinstance(result, timing.CloseRefused) and result.reason == "count_changed":
                status = 409
        elif command == "cancel-tonight/request":
            token = timing.request_cancel_tonight(
                request.app.state.engine, clock, cid, eid, session.doctor_id
            )
            board = timing.tonight_board(conn, cid, eid)
            data = {
                "confirm_token": token,
                "active_count": sum(r.remaining and r.source == "chat" for r in board.rows),
            }
        elif command == "cancel-tonight/confirm":
            assert isinstance(body, Cancel)
            data = asdict(
                timing.cancel_tonight_in_tx(
                    conn, clock, cid, eid, session.doctor_id, body.confirm_token, key
                )
            )
        else:
            raise ValueError("Unknown command")
        if eid is not None:
            auth.touch_session(conn, clock, session)
        save(conn, request, session, body.idempotency_key, command, data, status)
        return JSONResponse(jsonable_encoder(data), status_code=status)


@router.post("/on-my-way")
def on_way(request: Request, body: OnWay, session: CommandSession) -> JSONResponse:
    engine, clock = request.app.state.engine, request.app.state.clock
    with engine.connect() as conn:
        own(conn, session, body)
        saved = replay(conn, session, body.idempotency_key, "on-my-way")
        if saved is not None:
            return JSONResponse(saved["data"], status_code=saved["status"])
        eid = evening(conn, request, session)
        if (
            eid is not None
            and body.area_id is not None
            and conn.execute(select(s.areas.c.id).where(s.areas.c.id == body.area_id)).first()
            is None
        ):
            raise HTTPException(422, detail={"fields": ["area_id"]})
    origin = LatLng(body.lat, body.lng) if body.lat is not None and body.lng is not None else None
    data = (
        {"ok": False, "reason": "no_evening"}
        if eid is None
        else asdict(
            timing.doctor_on_my_way(
                engine,
                clock,
                session.clinic_id,
                eid,
                origin,
                body.area_id,
                "engine:" + body.idempotency_key,
            )
        )
    )
    # The engine replay key also covers a crash before the HTTP result is saved.
    with write_tx(engine) as conn:
        saved = replay(conn, session, body.idempotency_key, "on-my-way")
        if saved is not None:
            return JSONResponse(saved["data"], status_code=saved["status"])
        if eid is not None:
            auth.touch_session(conn, clock, session)
        save(conn, request, session, body.idempotency_key, "on-my-way", data)
        return JSONResponse(jsonable_encoder(data))


@router.post("/who-comes-in")
def who(request: Request, body: Who, session: CommandSession) -> JSONResponse:
    return run(request, session, body, "who-comes-in")


@router.post("/undo")
def undo(request: Request, body: Command, session: CommandSession) -> JSONResponse:
    return run(request, session, body, "undo")


@router.get("/close/preview")
def preview(request: Request, session: Session, evening_id: int | None = None) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        own(conn, session, Command(idempotency_key="preview", evening_id=evening_id))
        eid = evening(conn, request, session)
    if eid is None:
        return {"ok": False, "reason": "no_evening"}
    return asdict(
        timing.close_preview(
            request.app.state.engine, request.app.state.clock, session.clinic_id, eid
        )
    )


@router.post("/close")
def close(request: Request, body: Close, session: CommandSession) -> JSONResponse:
    return run(request, session, body, "close")


@router.post("/cancel-tonight/request")
def cancel_request(request: Request, body: Command, session: CommandSession) -> JSONResponse:
    return run(request, session, body, "cancel-tonight/request")


@router.post("/cancel-tonight/confirm")
def cancel_confirm(request: Request, body: Cancel, session: CommandSession) -> JSONResponse:
    return run(request, session, body, "cancel-tonight/confirm")


@router.get("/settings")
def settings(request: Request, session: Session) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        data = clinic_settings.read(conn, session.clinic_id, session.doctor_id)
        from nowa.messaging.templates import format_day

        for override in data["overrides"]:
            override["date_display"] = format_day(
                override["date"], doctor_language(request, conn, session)
            ) + (
                f"/{override['date'].year}"
                if override["date"].year != request.app.state.clock.now(session.clinic_id).year
                else ""
            )
        return data


SETTING_MODELS: dict[str, type[Input]] = {
    "hours": clinic_settings.Hours,
    "overrides": clinic_settings.Override,
    "timing": clinic_settings.Timing,
    "info": clinic_settings.Info,
    "lang": clinic_settings.Language,
    "secretary_alerts": clinic_settings.Alerts,
}


@router.put("/settings/{kind}")
async def put_settings(request: Request, kind: str, session: CommandSession) -> JSONResponse:
    if kind not in SETTING_MODELS:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except JSONDecodeError:
        return JSONResponse({"fields": [kind]}, status_code=422)
    if not isinstance(payload, dict):
        raise HTTPException(422, detail={"fields": [kind]})
    try:
        command = Command.model_validate(
            {
                "idempotency_key": payload.get("idempotency_key"),
                "evening_id": payload.get("evening_id"),
            }
        )
        with request.app.state.engine.connect() as conn:
            own(conn, session, command)
        value = SETTING_MODELS[kind].model_validate(
            {k: v for k, v in payload.items() if k not in {"idempotency_key", "evening_id"}}
        )
    except ValidationError as exc:
        return JSONResponse(
            {"fields": [".".join(str(p) for p in e["loc"]) or kind for e in exc.errors()]},
            status_code=422,
        )
    return change_settings(request, session, command.idempotency_key, kind, value)


def change_settings(
    request: Request, session: auth.Session, key: str, kind: str, value: Input | date
) -> JSONResponse:
    with write_tx(request.app.state.engine) as conn:
        saved = replay(conn, session, key, "settings/" + kind)
        if saved is not None:
            return JSONResponse(saved["data"], status_code=saved["status"])
        try:
            affected, eid = clinic_settings.update(
                conn, request.app.state.clock, session.clinic_id, session.doctor_id, kind, value
            )
        except clinic_settings.InvalidSetting as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=422)
        except clinic_settings.BookingsOutside:
            data = {"ok": False, "reason": "bookings_outside"}
            save(conn, request, session, key, "settings/" + kind, data, 422)
            return JSONResponse(data, status_code=422)
        for row_id in affected:
            timing.ensure_evening_timers(conn, request.app.state.clock, row_id)
        if eid is not None:
            timing.recompute(conn, request.app.state.clock, eid)
            timing.ensure_evening_timers(conn, request.app.state.clock, eid)
        data = {"ok": True}
        auth.touch_session(conn, request.app.state.clock, session)
        save(conn, request, session, key, "settings/" + kind, data)
        return JSONResponse(data)


@router.delete("/settings/overrides/{day}")
def delete_override(
    request: Request, day: date, body: Command, session: CommandSession
) -> JSONResponse:
    with request.app.state.engine.connect() as conn:
        own(conn, session, body)
    return change_settings(request, session, body.idempotency_key, "delete_override", day)


@router.post("/telegram-link")
def telegram_link(request: Request, body: Command, session: CommandSession) -> dict[str, Any]:
    with write_tx(request.app.state.engine) as conn:
        own(conn, session, body)
        saved = replay(conn, session, body.idempotency_key, "telegram-link")
        if saved is not None:
            return {"repeated": True}
        from nowa.config import get_settings

        username = get_settings().telegram_bot_username
        if not username:
            raise HTTPException(422, detail={"fields": ["telegram"]})
        token = secrets.token_urlsafe(32)
        conn.execute(
            s.link_tokens.insert().values(
                clinic_id=session.clinic_id,
                kind="doctor_telegram",
                subject_id=session.doctor_id,
                token_hash=auth.token_hash(token),
                expires_at=request.app.state.clock.now(session.clinic_id).astimezone(UTC)
                + timedelta(minutes=15),
            )
        )
        save(conn, request, session, body.idempotency_key, "telegram-link", {"repeated": True})
        record.write_action(conn, session.clinic_id, "doctor", "doctor_telegram_link")
        auth.touch_session(conn, request.app.state.clock, session)
        return {"url": f"https://t.me/{username}?start=d_{token}"}


class Advance(Input):
    minutes: Annotated[int, Field(strict=True, ge=1, le=180)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]


@router.post("/sandbox/advance")
def sandbox_advance(request: Request, body: Advance, session: CommandSession) -> JSONResponse:
    with write_tx(request.app.state.engine) as conn:
        clinic = (
            conn.execute(
                select(s.clinics).where(s.clinics.c.id == session.clinic_id).with_for_update()
            )
            .mappings()
            .one()
        )
        if not clinic["is_sandbox"]:
            raise HTTPException(403)
        saved = replay(conn, session, body.idempotency_key, "sandbox/advance")
        if saved is not None:
            return JSONResponse(saved["data"])
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == session.clinic_id)
            .values(clock_offset_s=clinic["clock_offset_s"] + body.minutes * 60)
        )
        data = {
            "ok": True,
            "now": request.app.state.clock.now(session.clinic_id, conn=conn).isoformat(),
        }
        record.write_action(conn, session.clinic_id, "doctor", "sandbox_advance")
        save(conn, request, session, body.idempotency_key, "sandbox/advance", data)
        return JSONResponse(data)


@router.get("/sandbox/phone")
def sandbox_phone(
    request: Request, session: Session, after_id: Annotated[int, Query(ge=0)] = 0
) -> JSONResponse:
    from nowa.messaging.outbox import screen_messages

    with request.app.state.engine.connect() as conn:
        sandbox = conn.execute(
            select(s.clinics.c.is_sandbox).where(s.clinics.c.id == session.clinic_id)
        ).scalar_one()
        if not sandbox:
            raise HTTPException(403)
        messages = []
        for msg in screen_messages(conn, session.clinic_id, after_id):
            recipient = "doctor"
            if msg.audience == "patient" and msg.booking_id is not None:
                phone = conn.execute(
                    select(s.contacts.c.phone_e164)
                    .join(s.bookings, s.bookings.c.contact_id == s.contacts.c.id)
                    .where(
                        s.bookings.c.id == msg.booking_id,
                        s.bookings.c.clinic_id == session.clinic_id,
                    )
                ).scalar_one()
                recipient = "*******" + phone[-4:]
            messages.append(dict(asdict(msg), recipient=recipient))
        return JSONResponse(jsonable_encoder(messages))


RowId = Annotated[int, Path(gt=0, le=2**63 - 1)]


class QuestionDraft(Command):
    text: Annotated[str, Field(min_length=1, max_length=1000)]


def own_question(conn: Connection, session: auth.Session, question_id: int) -> None:
    if (
        conn.execute(
            select(s.questions.c.id).where(
                s.questions.c.id == question_id,
                s.questions.c.clinic_id == session.clinic_id,
            )
        ).first()
        is None
    ):
        raise HTTPException(404)


@router.get("/report/{evening_id}")
def evening_report(request: Request, evening_id: RowId, session: Session) -> dict[str, Any]:
    from nowa.core.report import build_report
    from nowa.messaging.templates import format_doctor_time

    with request.app.state.engine.connect() as conn:
        own(conn, session, Command(idempotency_key="read", evening_id=evening_id))
        if (
            conn.execute(
                select(s.evenings.c.state).where(s.evenings.c.id == evening_id)
            ).scalar_one()
            != "closed"
        ):
            raise HTTPException(404)
        lang = doctor_language(request, conn, session)
        value = build_report(conn, request.app.state.clock, session.clinic_id, evening_id, lang)
        data = asdict(value)
        from nowa.web.strings import health_source_label

        for answer in data["health_answers"]:
            answer["at_display"] = format_doctor_time(answer["at"])
            answer["source_label"] = health_source_label(
                answer["source_title"], answer["source_url"], lang
            )
        return dict(
            data,
            health_q_count=value.health_q_count,
            text=value.text(lang),
            doctor_arrival_display=format_doctor_time(value.doctor_arrival)
            if value.doctor_arrival
            else None,
            clinic_start_display=format_doctor_time(value.clinic_start),
        )


@router.get("/questions")
def pending_questions(request: Request, session: Session) -> list[dict[str, Any]]:
    from nowa.core.report import pending_questions

    with request.app.state.engine.connect() as conn:
        lang = doctor_language(request, conn, session)
        return pending_questions(conn, session.clinic_id, lang)


def question_action(
    request: Request,
    session: auth.Session,
    question_id: int,
    body: Command,
    command: str,
) -> JSONResponse:
    from nowa.core import questions

    with write_tx(request.app.state.engine) as conn:
        own_question(conn, session, question_id)
        own(conn, session, body)
        name = f"questions/{question_id}/{command}"
        saved = replay(conn, session, body.idempotency_key, name)
        if saved is not None:
            return JSONResponse(saved["data"], status_code=saved["status"])
        clock, cid = request.app.state.clock, session.clinic_id
        key = "engine:" + body.idempotency_key
        if command == "draft":
            assert isinstance(body, QuestionDraft)
            result = questions.start_answer(
                conn, clock, cid, question_id, key + ":start", dashboard=True
            )
            if result.ok:
                result = questions.submit_draft(conn, clock, cid, question_id, body.text, key)
        else:
            action = {
                "save": questions.save_for_everyone,
                "later": questions.later,
                "dismiss": questions.dismiss,
            }[command]
            result = action(conn, clock, cid, question_id, key)
        data = asdict(result)
        auth.touch_session(conn, clock, session)
        save(conn, request, session, body.idempotency_key, name, data)
        return JSONResponse(data)


@router.post("/questions/{question_id}/draft")
def question_draft(
    request: Request, question_id: RowId, body: QuestionDraft, session: CommandSession
) -> JSONResponse:
    return question_action(request, session, question_id, body, "draft")


@router.post("/questions/{question_id}/save")
def question_save(
    request: Request, question_id: RowId, body: Command, session: CommandSession
) -> JSONResponse:
    return question_action(request, session, question_id, body, "save")


@router.post("/questions/{question_id}/later")
def question_later(
    request: Request, question_id: RowId, body: Command, session: CommandSession
) -> JSONResponse:
    return question_action(request, session, question_id, body, "later")


@router.post("/questions/{question_id}/dismiss")
def question_dismiss(
    request: Request, question_id: RowId, body: Command, session: CommandSession
) -> JSONResponse:
    return question_action(request, session, question_id, body, "dismiss")
