import uuid

from nowa.ai.schema import TurnOutput

BASE = "/c/dr-hesham"


def output(**values):
    return TurnOutput.model_validate(
        dict(
            triage="normal",
            intent="other",
            fields=dict(day=None, name=None, phone=None, area=None, booking_for="unknown"),
            is_health_question=False,
            reply="Welcome",
            **{},
        )
        | values
    )


def book_output(booking_for="self", **values):
    return output(
        intent="book",
        fields=dict(
            day="2026-10-06",
            name="Karim Father",
            phone="01000000777",
            area=None,
            booking_for=booking_for,
        ),
        **values,
    )


def session(client):
    result = client.post(BASE + "/session")
    assert result.status_code == 200, result.text
    return result.json()["session"]


def turn(client, session, text="hello", key=None, history=None):
    result = client.post(
        BASE + "/turn",
        json=dict(
            session=session,
            text=text,
            idempotency_key=key or uuid.uuid4().hex,
            history=history or [],
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()


def day_payload(data):
    return next(
        b["action"]["payload"] for b in data["buttons"] if b["action"]["kind"] == "book_day"
    )


def tap(client, session, payload, key=None):
    result = client.post(
        BASE + "/tap",
        json=dict(
            session=session,
            action="book_day",
            payload=payload,
            idempotency_key=key or uuid.uuid4().hex,
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()
