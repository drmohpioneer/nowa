from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.messaging.adapters import SendResult
from nowa.telegram.keyboards import markup_for
from nowa.telegram.router import Router
from tests.core.support import move, setup


@dataclass
class FakeTelegramAPI:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    delivery_reports = False

    def call(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True, "result": {"message_id": len(self.calls)}}

    def send(self, row):
        payload = {"chat_id": row["chat_id"], "text": row["body"]}
        markup = markup_for(row)
        if markup:
            payload["reply_markup"] = markup
        result = self.call("sendMessage", payload)
        return SendResult("accepted", provider_ref=f"fake:{result['result']['message_id']}")

    def clear(self):
        self.calls.clear()


@pytest.fixture
def fake_api():
    return FakeTelegramAPI()


@pytest.fixture
def bot(engine, fake_api):
    cid, eid, clock, ids = setup(engine, count=6)
    move(clock, 0)
    with engine.connect() as conn:
        did = conn.execute(select(s.doctors.c.id)).scalar_one()
    return Router(engine, clock, fake_api), cid, eid, did, clock, ids, fake_api
