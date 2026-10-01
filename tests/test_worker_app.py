import sys
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nowa import record, worker
from nowa import schema as s
from nowa.__main__ import main
from nowa.app import create_app
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.messaging.adapters import ADAPTERS, SendResult
from nowa.messaging.outbox import screen_messages
from tests.helpers.worker import HandlerSetup, assert_handler_idempotent, drain
from tests.test_messaging import enqueue, row
from tests.test_messaging import prepared as messaging_prepared
from tests.test_worker import actions, add

prepared = messaging_prepared


def wait_until(check, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        threading.Event().wait(0.01)
    assert check(), "worker did not make progress before deadline"


def test_demo_delivery_and_restart_with_retry(prepared, monkeypatch):
    p = prepared
    calls = []
    adapter = ADAPTERS["screen_phone"]

    def send(message):
        calls.append(message["id"])
        return SendResult("refused" if len(calls) == 2 else "accepted")

    monkeypatch.setattr(adapter, "send", send)
    app = create_app(p.engine, demo_worker=True, clock=p.clock)
    with TestClient(app):
        oid = enqueue(p)
        wait_until(lambda: row(p, oid)["status"] == "delivered", 2)
        with p.engine.connect() as conn:
            messages = screen_messages(conn, p.cid, 0)
            assert len(messages) == 1 and messages[0].status == "delivered"
            assert messages[0].outbox_id == oid
        retry_oid = enqueue(p, "retry")
        wait_until(lambda: row(p, retry_oid)["attempts"] == 1, 2)
        wait_until(lambda: actions(p.engine, "message_result") == 2, 2)
    assert not app.state.worker_thread.is_alive()
    assert row(p, retry_oid)["status"] == "queued"
    p.clock.advance(minutes=1)
    app = create_app(p.engine, demo_worker=True, clock=p.clock)
    with TestClient(app):
        wait_until(lambda: row(p, retry_oid)["status"] == "delivered", 2)
    assert calls == [oid, retry_oid, retry_oid]
    assert row(p, retry_oid)["attempts"] == 2


def test_send_commit_crash_before_callback(prepared, monkeypatch):
    p = prepared
    oid = enqueue(p)
    calls = []
    monkeypatch.setattr(ADAPTERS["screen_phone"], "send", lambda message: calls.append(message))
    with patch.object(worker, "_after_commit", side_effect=SystemExit):
        with pytest.raises(SystemExit):
            worker.run_once(p.engine, p.clock, worker.build_registry())
    assert calls == [] and row(p, oid)["attempts"] == 1
    assert row(p, oid)["status"] == "queued"
    p.clock.advance(minutes=5)
    assert worker.run_once(p.engine, p.clock, worker.build_registry()).done == 1
    assert row(p, oid)["status"] == "failed"
    assert actions(p.engine, "message_failure") == 1
    assert calls == []
    worker.run_once(
        p.engine, p.clock, {"delivery_timeout": worker.build_registry()["delivery_timeout"]}
    )
    assert actions(p.engine, "message_failure") == 1


@pytest.mark.parametrize("kind", ["send_retry", "delivery_timeout"])
def test_messaging_handlers_idempotent_through_worker(prepared, kind):
    p = prepared
    oid = enqueue(p)
    if kind == "delivery_timeout":
        with patch.object(worker, "_after_commit"):
            drain(p.engine, p.clock, worker.build_registry())
        p.clock.advance(minutes=5)
    assert_handler_idempotent(
        kind,
        {"outbox_id": oid, "attempt": 1},
        lambda: HandlerSetup(
            p.engine,
            p.clock,
            p.cid,
            worker.build_registry(),
        ),
    )


def health_scenario(engine, clock, monkeypatch, enabled, never):
    if enabled:
        monkeypatch.setenv("WORKER_IN_PROCESS", "1")
    get_settings.cache_clear()
    record.configure(clock)
    from nowa.demo.template import CLINIC

    with write_tx(engine) as conn:
        cid = conn.execute(
            s.clinics.insert()
            .values(**CLINIC["clinic"])
            .returning(
                s.clinics.c.id,
            )
        ).scalar_one()
        shifted = conn.execute(
            s.clinics.insert()
            .values(
                **dict(
                    CLINIC["clinic"],
                    slug="shifted",
                    is_sandbox=True,
                    clock_offset_s=600,
                )
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
    app = create_app(engine, clock=clock)
    target = worker.run_forever if not never else lambda *a, **kw: None
    with patch.object(worker, "run_forever", side_effect=target) as loop, TestClient(app) as client:
        if enabled and not never:
            wait_until(lambda: client.get("/health").json()["worker"]["last_run_at"], 3)
            app.state.worker_stop.set()
            app.state.worker_thread.join(timeout=3)
            assert not app.state.worker_thread.is_alive()
        else:
            assert client.get("/health").json()["worker"]["last_run_at"] is None
        assert loop.call_count == int(enabled)
        add(engine, clock, cid, minutes=-1)
        add(engine, clock, shifted, "shifted", minutes=-1)
        clock.advance(minutes=3)
        assert client.get("/health").status_code == 200
        clock.advance(minutes=1 / 60)
        response = client.get("/health")
        assert response.status_code == (503 if enabled else 200)
        assert response.json()["worker"]["overdue"] == 1


@pytest.mark.parametrize("enabled,never", [(True, False), (True, True), (False, True)])
def test_health_local(engine, frozen_clock, monkeypatch, enabled, never):
    health_scenario(engine, frozen_clock, monkeypatch, enabled, never)


@pytest.mark.postgres
@pytest.mark.parametrize("enabled,never", [(True, False), (True, True), (False, True)])
def test_health_postgres(postgres_engine, frozen_clock, monkeypatch, enabled, never):
    health_scenario(postgres_engine, frozen_clock, monkeypatch, enabled, never)


def test_worker_cli_sqlite_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nowa", "worker"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "SQLite runs the worker inside the demo server" in capsys.readouterr().err


@pytest.mark.postgres
def test_worker_cli_postgres_signal(postgres_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(postgres_engine.url))
    get_settings.cache_clear()
    import nowa.__main__ as cli

    monkeypatch.setattr(cli, "create_db_engine", lambda: postgres_engine)
    monkeypatch.setattr(sys, "argv", ["nowa", "worker"])
    signals = {}
    monkeypatch.setattr(
        cli.signal, "signal", lambda number, handler: signals.update({number: handler})
    )

    def loop(engine, clock, registry, *, stop):
        assert record.configured_clock() is clock
        assert set(registry) == {"send_retry", "delivery_timeout"}
        worker.run_once(engine, clock, registry)
        signals[cli.signal.SIGTERM](None, None)
        assert stop.is_set()
        stop.clear()
        signals[cli.signal.SIGINT](None, None)
        assert stop.is_set()

    monkeypatch.setattr(worker, "run_forever", loop)
    main()


def test_demo_cli_chooses_worker_factory(monkeypatch):
    import nowa.__main__ as cli

    calls = []
    from nowa.demo import launch

    monkeypatch.setattr(launch, "check_port", lambda: None)
    monkeypatch.setattr(sys, "argv", ["nowa", "demo", "--no-browser"])
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app_factory, **kw: calls.append((app_factory, kw))
    )
    main()
    assert calls[0][0] == "nowa.app:create_demo_app"
    assert calls[0][1]["factory"] is True
