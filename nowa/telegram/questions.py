"""Doctor-only transport for the core question actions."""

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from nowa import schema as s
from nowa.core import questions
from nowa.db import write_tx
from nowa.telegram import keyboards, linking

if TYPE_CHECKING:
    from nowa.telegram.router import Context


def callback(ctx: "Context", command: keyboards.Callback) -> None:
    with write_tx(ctx.engine) as conn:
        current = linking.identity(conn, ctx.chat_id).doctor
        qid = int(command.arg)
        if current is None or ctx.doctor is None or current["id"] != ctx.doctor["id"]:
            result = questions.QuestionResult(False, "refused")
        elif (
            conn.execute(
                select(s.questions.c.id).where(
                    s.questions.c.id == qid,
                    s.questions.c.clinic_id == current["clinic_id"],
                )
            ).first()
            is None
        ):
            result = questions.QuestionResult(False, "refused")
        else:
            action = {
                "qans": questions.start_answer,
                "qedit": questions.start_answer,
                "qsave": questions.save_for_everyone,
                "qlater": questions.later,
                "qdismiss": questions.dismiss,
            }[command.verb]
            result = action(conn, ctx.clock, current["clinic_id"], qid, ctx.key)
    ctx.send("q_" + result.reason if result.reason != "refused" else "refused")


def draft_message(ctx: "Context", value: str | None) -> bool:
    """Return whether a live answer window consumed this message (including refusal)."""
    with write_tx(ctx.engine) as conn:
        current = linking.identity(conn, ctx.chat_id).doctor
        if current is None or ctx.doctor is None or current["id"] != ctx.doctor["id"]:
            return False
        cid = current["clinic_id"]
        # Replaying a submitted text must never land in a later question's window.
        if linking.used_update(conn, ctx.handled_key):
            return True
        question = (
            conn.execute(
                select(s.questions).where(
                    s.questions.c.clinic_id == cid,
                    s.questions.c.status == "open",
                    s.questions.c.answering_at.is_not(None),
                    s.questions.c.answering_at >= ctx.clock.now(cid) - timedelta(minutes=30),
                )
            )
            .mappings()
            .one_or_none()
        )
        if question is None:
            return False
        # Command order distinguishes a fresh qedit from an already consumed window,
        # even with a retained draft and several taps at the same clock instant.
        actions = conn.execute(
            select(s.idempotency_keys.c.command, s.idempotency_keys.c.result_json)
            .where(
                s.idempotency_keys.c.clinic_id == cid,
                s.idempotency_keys.c.command.in_([
                    f"question_start_answer:{question['id']}",
                    f"question_submit_draft:{question['id']}",
                ]),
            )
            .order_by(s.idempotency_keys.c.id.desc())
        ).mappings()
        latest = next((action for action in actions if action["result_json"].get("ok")), None)
        if latest is None or latest["command"] != f"question_start_answer:{question['id']}":
            return False
        if value is None:
            result = questions.QuestionResult(False, "text_only")
        else:
            result = questions.submit_draft(conn, ctx.clock, cid, question["id"], value, ctx.key)
        linking.remember(conn, ctx.clock, cid, ctx.handled_key, "telegram_update")
    if result.ok:
        assert value is not None
        ctx.send_text(value, keyboards.question_buttons(question["id"], ctx.lang, draft=True))
    else:
        ctx.send("q_" + result.reason)
    return True
