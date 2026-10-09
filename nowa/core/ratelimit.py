import hashlib
import hmac
from datetime import UTC, datetime
from math import floor

from sqlalchemy import BigInteger, cast, delete, extract, func
from sqlalchemy.engine import Connection

from nowa.clock import Clock
from nowa.config import get_settings
from nowa.db import conflict_insert
from nowa.schema import rate_counters


def hit(conn: Connection, clock: Clock, scope: str, key: str, window_s: int, limit: int) -> bool:
    if window_s <= 0 or limit < 0:
        raise ValueError("window_s must be positive and limit nonnegative")
    now = clock.base_now()
    start = datetime.fromtimestamp(floor(now.timestamp() / window_s) * window_s, UTC)
    key_hash = hmac.new(
        get_settings().server_secret.encode(), f"{scope}|{key}".encode(), hashlib.sha256
    ).hexdigest()
    epoch = (
        cast(func.strftime("%s", rate_counters.c.window_start), BigInteger)
        if conn.dialect.name == "sqlite"
        else extract("epoch", rate_counters.c.window_start)
    )
    conn.execute(
        delete(rate_counters).where(
            rate_counters.c.scope == scope,
            epoch + rate_counters.c.window_s < now.timestamp() - 86400,
        )
    )
    statement = (
        conflict_insert(conn, rate_counters)
        .values(
            scope=scope,
            key_hash=key_hash,
            window_start=start,
            window_s=window_s,
            count=1,
        )
        .on_conflict_do_update(
            index_elements=[
                rate_counters.c.scope,
                rate_counters.c.key_hash,
                rate_counters.c.window_start,
            ],
            set_={"count": rate_counters.c.count + 1},
        )
        .returning(rate_counters.c.count)
    )
    return bool(conn.execute(statement).scalar_one() <= limit)


def exhausted(
    conn: Connection, clock: Clock, scope: str, key: str, window_s: int, limit: int
) -> bool:
    from sqlalchemy import select

    start = datetime.fromtimestamp(floor(clock.base_now().timestamp() / window_s) * window_s, UTC)
    key_hash = hmac.new(
        get_settings().server_secret.encode(), f"{scope}|{key}".encode(), hashlib.sha256
    ).hexdigest()
    count = conn.execute(
        select(rate_counters.c.count).where(
            rate_counters.c.scope == scope,
            rate_counters.c.key_hash == key_hash,
            rate_counters.c.window_start == start,
        )
    ).scalar_one_or_none()
    return count is not None and count >= limit
