import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Lang = Literal["ar", "en", "franco"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TurnFields(StrictModel):
    day: date | None
    name: str | None
    phone: str | None
    area: str | None
    booking_for: Literal["self", "other", "unknown"]

    @field_validator("day", mode="before")
    @classmethod
    def iso_day(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, date):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None
            ):
                raise ValueError("day must be an ISO date")
        return value


class TurnOutput(StrictModel):
    triage: Literal["normal", "urgent", "emergency", "unclear"]
    emergency_kind: Literal["general", "eye_chemical", "eye", "filler", "labour"] = "general"
    intent: Literal[
        "book", "my_booking", "clinic_info", "question_for_doctor", "out_of_scope", "other"
    ]
    fields: TurnFields
    is_health_question: bool = Field(strict=True)
    reply: str = Field(max_length=800)

    @field_validator("emergency_kind", mode="before")
    @classmethod
    def emergency_fallback(cls, value: Any) -> str:
        return (
            value if value in ("general", "eye_chemical", "eye", "filler", "labour") else "general"
        )


def gemini_schema(schema: type[BaseModel]) -> dict[str, Any]:
    result = schema.model_json_schema()
    result["propertyOrdering"] = list(result.get("properties", {}))
    return result


TURN_JSON_SCHEMA = gemini_schema(TurnOutput)


class HistoryTurn(StrictModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class Action(StrictModel):
    kind: Literal["book_day", "consent", "area", "lookup", "none"]
    payload: dict[str, Any] = Field(default_factory=dict)


class Button(StrictModel):
    id: str
    label: str
    action: Action


class ChatResponse(StrictModel):
    telegram_url: str | None = None
    booking_confirmed: bool = False
    reply: str
    buttons: list[Button] = Field(default_factory=list)
    state: Literal["open", "locked_emergency"] = "open"
    lang: Lang = "ar"
