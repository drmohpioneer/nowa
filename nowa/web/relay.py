import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from nowa.config import get_settings, secret_ok
from nowa.db import write_tx
from nowa.messaging.adapters import SendResult
from nowa.messaging.outbox import recipient
from nowa.messaging.pipeline import on_send_result
from nowa.schema import outbox


def authorize(request: Request, x_relay_token: Annotated[str | None, Header()] = None) -> None:
    if get_settings().demo_no_network:
        logging.getLogger(__name__).warning("kind=mac_relay outcome=disabled_demo_no_network")
        raise HTTPException(404)
    if not secret_ok("MAC_RELAY_TOKEN"):
        raise HTTPException(404)
    if any("token" in key.lower() for key in request.query_params):
        raise HTTPException(401)
    if not x_relay_token or not secrets.compare_digest(
        x_relay_token.encode(), get_settings().mac_relay_token.encode()
    ):
        raise HTTPException(401)


router = APIRouter(prefix="/relay", dependencies=[Depends(authorize)])


@router.get("/outbox")
def poll(request: Request, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> dict[str, object]:
    messages = []
    with write_tx(request.app.state.engine) as conn:
        rows = conn.execute(
            select(outbox)
            .where(
                outbox.c.adapter == "mac_relay",
                outbox.c.status == "queued",
                outbox.c.next_attempt_at.is_not(None),
            )
            .order_by(outbox.c.id)
            .limit(limit)
            .with_for_update()
        ).mappings()
        for row in rows:
            if row["next_attempt_at"] > request.app.state.clock.now(row["clinic_id"]):
                continue
            phone, _ = recipient(conn, row)
            if phone not in {
                p.strip() for p in get_settings().mac_relay_allowlist.split(",") if p.strip()
            }:
                continue
            conn.execute(
                update(outbox).where(outbox.c.id == row["id"]).values(next_attempt_at=None)
            )
            messages.append(
                {"id": row["id"], "attempt": row["attempts"], "to": phone, "text": row["body"]}
            )
            if len(messages) == limit:
                break
    return {"messages": messages}


class Ack(BaseModel):
    id: int = Field(gt=0)
    attempt: int = Field(ge=1, le=3)
    ok: bool
    error: str | None = None


@router.post("/ack")
def ack(request: Request, body: Ack) -> dict[str, bool]:
    with request.app.state.engine.connect() as conn:
        row = conn.execute(select(outbox).where(outbox.c.id == body.id)).mappings().one_or_none()
        valid = row is not None and row["adapter"] == "mac_relay" and row["next_attempt_at"] is None
    if valid:
        on_send_result(
            request.app.state.engine,
            request.app.state.clock,
            body.id,
            body.attempt,
            SendResult(
                "accepted" if body.ok else "refused",
                provider_ref=f"mac:{body.id}:{body.attempt}" if body.ok else None,
                error="relay_refused" if not body.ok else None,
            ),
        )
    return {"ok": True}
