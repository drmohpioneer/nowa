import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine, RowMapping

from nowa import record
from nowa import schema as s
from nowa.clock import Clock
from nowa.core.travel import LatLng
from nowa.db import write_tx
from nowa.telegram import doctor, keyboards, linking, patient, questions
from nowa.telegram.api import API, BotAPI, interactive
from nowa.web.strings import STRINGS, text

logger = logging.getLogger(__name__)


class Chat(BaseModel):
    id: int = Field(strict=True)
    type: str


class Location(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Message(BaseModel):
    message_id: int = Field(strict=True, gt=0)
    chat: Chat
    text: str | None = None
    location: Location | None = None
    voice: dict[str, Any] | None = None
    photo: list[dict[str, Any]] | None = None
    document: dict[str, Any] | None = None


class Query(BaseModel):
    id: str
    message: Message | None = None
    data: str | None = None


class Update(BaseModel):
    update_id: int = Field(strict=True, ge=0)
    message: Message | None = None
    callback_query: Query | None = None


@dataclass
class Context:
    engine: Engine
    clock: Clock
    api: API
    update_id: int
    chat_id: str
    message_id: int | None = None
    doctor: RowMapping | None = None
    clinic_id: int | None = None
    lang: str = "ar"

    @property
    def key(self) -> str:
        return f"tg:{self.update_id}"

    @property
    def handled_key(self) -> str:
        return self.key + ":handled"

    def refresh(self) -> linking.Identity:
        self.clinic_id = None
        self.lang = "ar"
        with self.engine.connect() as conn:
            value = linking.identity(conn, self.chat_id)
            self.doctor = value.doctor
            if self.doctor is not None:
                self.clinic_id = self.doctor["clinic_id"]
                self.lang = self.doctor["lang"]
            else:
                rows = patient.bookings(conn, self.clock, value.patient_phones)
                if rows:
                    self.clinic_id = rows[0]["clinic_id"]
                    self.lang = rows[0]["lang"]
        return value

    def call(self, method: str, payload: dict[str, Any]) -> None:
        if interactive(self.api, method, payload):
            if self.clinic_id is not None:
                with write_tx(self.engine) as conn:
                    judge_id: str | None = conn.execute(
                        select(s.clinics.c.judge_id).where(s.clinics.c.id == self.clinic_id)
                    ).scalar_one()
                    record.record_usage(conn, self.clinic_id, judge_id, "telegram", 1, 0)
        else:
            logger.warning("update_id=%s kind=reply outcome=failed", self.update_id)

    def send_text(self, value: str, markup: keyboards.Markup | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": value}
        if markup is not None:
            payload["reply_markup"] = markup
        self.call("sendMessage", payload)

    def send(self, key: str, markup: keyboards.Markup | None = None) -> None:
        self.send_text(text("tg." + key, self.lang), markup)

    def edit_text(self, value: str, markup: keyboards.Markup) -> None:
        if self.message_id is None:
            self.send_text(value, markup)
        else:
            self.call(
                "editMessageText",
                {
                    "chat_id": self.chat_id,
                    "message_id": self.message_id,
                    "text": value,
                    "reply_markup": markup,
                },
            )

    def edit(self, key: str, markup: keyboards.Markup) -> None:
        self.edit_text(text("tg." + key, self.lang), markup)


def matches(value: str | None, key: str) -> bool:
    return value in STRINGS["tg." + key].values()


class Router:
    def __init__(self, engine: Engine, clock: Clock, api: API | None = None) -> None:
        self.engine, self.clock = engine, clock
        self.api = api if api is not None else BotAPI()

    def handle_update(self, update: dict[str, Any]) -> None:
        try:
            value = Update.model_validate(update)
        except ValidationError:
            logger.info("kind=update outcome=invalid")
            return
        query = value.callback_query
        message = query.message if query else value.message
        if message is None or message.chat.type != "private":
            logger.info("update_id=%s kind=update outcome=ignored", value.update_id)
            return
        ctx = Context(
            self.engine,
            self.clock,
            self.api,
            value.update_id,
            str(message.chat.id),
            message.message_id if query else None,
        )
        links = ctx.refresh()
        try:
            if query is not None:
                self._callback(ctx, query)
                ctx.call("answerCallbackQuery", {"callback_query_id": query.id})
            else:
                self._message(ctx, links, message)
        except Exception:
            logger.error("update_id=%s kind=update outcome=failed", value.update_id)
            raise
        logger.info(
            "update_id=%s kind=%s outcome=handled",
            value.update_id,
            "callback" if query else "message",
        )

    @staticmethod
    def _callback(ctx: Context, query: Query) -> None:
        try:
            command = keyboards.parse(query.data or "")
        except ValueError:
            ctx.send("refused")
            return
        if command.verb.startswith("q"):
            questions.callback(ctx, command)
        elif command.verb in {"unlink", "unlinkok", "tgmenu"} or (
            command.evening_id is None and command.booking_id is not None
        ):
            patient.callback(ctx, command)
        else:
            doctor.callback(ctx, command)

    @staticmethod
    def _message(ctx: Context, links: linking.Identity, message: Message) -> None:
        value = message.text
        if value == "/start" or (value is not None and value.startswith("/start ")):
            if value == "/start":
                ctx.send("how_to")
                return
            assert value is not None
            outcome = linking.consume(ctx.engine, ctx.clock, ctx.chat_id, value[7:], ctx.key)
            ctx.refresh()
            ctx.send(outcome)
            if outcome == "linked":
                if ctx.doctor is not None:
                    doctor.show_board(ctx)
                else:
                    patient.menu(ctx)
            return
        if ctx.doctor is not None:
            answer_text = (
                None
                if any(
                    item is not None for item in (message.voice, message.photo, message.document)
                )
                else value
            )
            if questions.draft_message(ctx, answer_text):
                return
            if message.location is not None:
                doctor.on_way(
                    ctx, LatLng(message.location.latitude, message.location.longitude), None
                )
            elif matches(value, "omw") or matches(value, "location"):
                doctor.prompt(ctx)
            elif matches(value, "area"):
                doctor.areas(ctx)
            else:
                doctor.show_board(ctx)
        elif links.patient_phones:
            if matches(value, "unlink"):
                patient.callback(ctx, keyboards.Callback("unlink"))
            else:
                patient.menu(ctx)
        else:
            ctx.send("how_to")


_router: Router | None = None


def configure(engine: Engine, clock: Clock, api: API | None = None) -> Router:
    global _router
    _router = Router(engine, clock, api)
    return _router


def handle_update(update: dict[str, Any]) -> None:
    if _router is None:
        raise RuntimeError("Telegram router is not configured")
    _router.handle_update(update)
