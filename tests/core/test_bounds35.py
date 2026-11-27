from datetime import timedelta

import pytest
from sqlalchemy import select

from nowa import schema as s
from nowa.core import projection, timing_handlers
from nowa.db import write_tx
from tests.core.support import setup
from tests.core.test_timing_scenarios import context


@pytest.mark.parametrize("seconds,sent", [(-1, True), (0, False), (1, False)])
def test_doctor_reminder_stops_at_paper_end(engine, seconds, sent):
    cid, eid, clock, _ = setup(engine, count=1)
    with write_tx(engine) as conn:
        day = conn.execute(select(s.evenings.c.date)).scalar_one()
        end = projection.paper_hours(conn, cid, day)[1]
        clock.advance(
            minutes=((end + timedelta(seconds=seconds)) - clock.now(cid)).total_seconds() / 60
        )
        timing_handlers.are_you_on_way(
            context(conn, clock, cid, "are_you_on_way"), {"evening_id": eid}
        )
        assert (
            bool(conn.execute(select(s.outbox).where(s.outbox.c.template_id == "5")).first())
            == sent
        )
