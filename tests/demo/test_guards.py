import socket
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import select

from nowa import schema as s
from nowa.config import get_settings
from nowa.core.travel import LatLng, TravelContext
from nowa.core.travel_mapbox import MapboxAdapter
from nowa.demo.runner import EveningRunner
from nowa.messaging.adapters import TelegramAdapter
from nowa.telegram.api import BotAPI
from nowa.telegram.poller import run_forever

ROOT = Path(__file__).resolve().parents[2]


def test_no_network_guards(engine, demo_setup, monkeypatch, caplog):
    cid, clock = demo_setup
    for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "MAPBOX_TOKEN"):
        monkeypatch.setenv(name, "offline-test-key")
    monkeypatch.setenv("DEMO_NO_NETWORK", "1")
    get_settings.cache_clear()
    blocked = []

    def connect(sock, address):
        blocked.append(address)
        raise AssertionError("Outbound socket attempted")

    monkeypatch.setattr(socket.socket, "connect", connect)
    runner = EveningRunner(cid, engine=engine, clock=clock)
    runner.advance(600)
    assert runner.state()["closed"]
    spy = Mock()
    assert (
        TelegramAdapter(spy).send({"chat_id": "123", "body": "fictional"}).error
        == "demo_no_network"
    )
    assert not BotAPI(spy).call("sendMessage", {"chat_id": 123})["ok"]
    with engine.connect() as conn:
        assert (
            MapboxAdapter("offline", http=spy).minutes(
                LatLng(30, 31),
                LatLng(30.1, 31.1),
                clock.now(cid),
                ctx=TravelContext(conn, cid, None),
            )
            is None
        )
    run_forever(Mock(), spy, stop=Mock())
    spy.assert_not_called()
    assert spy.method_calls == []
    assert blocked == []
    assert "disabled_demo_no_network" in caplog.text
    with engine.connect() as conn:
        assert not conn.execute(select(s.usage).where(s.usage.c.clinic_id == cid)).first()


def test_cli_startup_network_guard_in_process(tmp_path, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from nowa import __main__, app
    from nowa.demo import launch

    for name in ("TELEGRAM_BOT_TOKEN", "MAPBOX_TOKEN"):
        monkeypatch.setenv(name, "offline-test-key")
    monkeypatch.delenv("DEMO_NO_NETWORK", raising=False)
    monkeypatch.setenv("PORT", "8765")
    monkeypatch.setenv("LIBRARY_DATA_DIR", str(ROOT / "nowa/library/data"))
    get_settings.cache_clear()
    monkeypatch.setattr(launch, "check_port", lambda: None)
    blocked = []

    def connect(sock, address):
        blocked.append(address)
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(__main__.sys, "argv", ["nowa", "demo", "--no-browser"])
    called = []

    def serve(target, **kwargs):
        assert target == "nowa.app:create_demo_app"
        assert kwargs["port"] == 8765 and kwargs["factory"]
        called.append(target)
        with TestClient(app.create_demo_app()) as client:
            assert client.get("/health").json()["ok"]
            assert "/demo/evening" in client.get("/").text
            headers = {"Origin": "http://127.0.0.1:8000"}
            run = client.post(
                "/demo/evening/start",
                json={"idempotency_key": "cli-start-guard-01"},
                headers=headers,
            ).json()
            result = client.post(
                "/demo/evening/" + run["run_id"] + "/advance",
                json={"token": run["token"], "to_minute": 600},
                headers=headers,
            )
            assert result.status_code == 200 and result.json()["closed"]
            assert (
                client.post("/demo/book", headers=headers, follow_redirects=False).status_code
                == 303
            )

    monkeypatch.setattr(__main__.uvicorn, "run", serve)
    __main__.main()
    assert called == ["nowa.app:create_demo_app"]
    assert blocked == []
    assert get_settings().demo_no_network
    assert "disabled_demo_no_network" in caplog.text
    assert (tmp_path / "nowa-demo.db").exists()


def test_port_busy_exit(monkeypatch, capsys):
    import errno

    from nowa.demo.launch import check_port

    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    sock.bind.side_effect = OSError(errno.EADDRINUSE, "busy")
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    import pytest

    with pytest.raises(SystemExit) as exc:
        check_port()
    assert exc.value.code == 1
    assert "Port 8000 is busy" in capsys.readouterr().err


def test_port_permission_error_is_not_reported_busy(monkeypatch, capsys):
    import errno

    from nowa.demo.launch import check_port

    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    sock.bind.side_effect = PermissionError(errno.EPERM, "denied")
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    import pytest

    with pytest.raises(SystemExit) as exc:
        check_port()
    assert exc.value.code == 1
    assert "Cannot bind port 8000" in capsys.readouterr().err
