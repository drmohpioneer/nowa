from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from nowa import record
from nowa import schema as s
from nowa.ai.chain import Attempt
from nowa.clock import Clock, FrozenClock
from nowa.config import get_settings
from nowa.core import ratelimit
from nowa.db import conflict_insert


def acquire_ai_turn(
    conn: Connection,
    clock: Clock,
    clinic: Mapping[str, Any],
    session: Mapping[str, Any],
    client_ip: str,
) -> bool:
    settings = get_settings()
    clinic_id = clinic["id"]
    now = clock.now(clinic_id)
    if clinic["is_sandbox"]:
        judge = clinic["judge_id"]
        if not judge:
            return False
        spent: float = conn.execute(
            select(func.coalesce(func.sum(s.usage.c.est_cost_usd), 0)).where(
                s.usage.c.service == "ai",
                s.usage.c.judge_id != "",
                s.usage.c.date == record.usage_date(),
            )
        ).scalar_one()
        if spent >= settings.ai_daily_budget_usd:
            return False
        conn.execute(
            conflict_insert(conn, s.judge_counters)
            .values(
                judge_id=judge,
                ai_msgs=0,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[s.judge_counters.c.judge_id])
        )
        return bool(
            conn.execute(
                s.judge_counters.update()
                .where(
                    s.judge_counters.c.judge_id == judge,
                    s.judge_counters.c.ai_msgs < settings.judge_ai_msg_cap,
                )
                .values(ai_msgs=s.judge_counters.c.ai_msgs + 1, updated_at=now)
            ).rowcount
        )
    ip_allowed = ratelimit.hit(conn, clock, "chat_turns_ip", client_ip, 86400, 100)
    if session["ai_msg_count"] >= 30 or not ip_allowed:
        record.write_action(conn, clinic_id, "system", "would_have_blocked")
    # Clinic-date in the key gives the safety net the clinic's calendar day.
    return ratelimit.hit(
        conn,
        FrozenClock(now.replace(hour=12, minute=0, second=0)),
        "chat_turns_clinic",
        f"{clinic_id}|{now.date()}",
        86400,
        settings.ai_clinic_daily_ceiling,
    )


def record_attempts(
    conn: Connection, clinic: Mapping[str, Any], attempts: Sequence[Attempt]
) -> None:
    rates = get_settings().ai_rates_json
    for attempt in attempts:
        if attempt.responded:
            rate = rates.get(attempt.model, {"in": 0, "out": 0})
            estimate = (
                attempt.input_tokens * rate["in"] + attempt.output_tokens * rate["out"]
            ) / 1e6
            record.record_usage(
                conn,
                clinic["id"],
                clinic["judge_id"] if clinic["is_sandbox"] else None,
                "ai",
                1,
                estimate,
            )
