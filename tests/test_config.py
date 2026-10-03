import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from nowa.config import Settings, secret_ok

ROOT = Path(__file__).resolve().parents[1]


def production(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/nowa_test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nowa.example/")


@pytest.mark.parametrize("name", ["SERVER_SECRET", "LINK_SECRET"])
@pytest.mark.parametrize("value", [None, "x" * 31])
def test_production_secret_validation(monkeypatch, name, value, tmp_path):
    production(monkeypatch)
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name) as error:
        Settings()
    if value:
        assert value not in str(error.value)
    assert not (tmp_path / ".nowa-secrets").exists()


def test_production_base_and_database(monkeypatch, tmp_path):
    production(monkeypatch)
    (tmp_path / ".nowa-secrets").write_text("not JSON; must never be read")
    assert Settings().public_base_url == "https://nowa.example"
    monkeypatch.delenv("PUBLIC_BASE_URL")
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nowa.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///bad.db")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings()


def test_demo_secret_persistence_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("SERVER_SECRET")
    monkeypatch.delenv("LINK_SECRET")
    first = Settings()
    path = tmp_path / ".nowa-secrets"
    contents = path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(first.server_secret.encode()) >= 32
    assert first.server_secret != first.link_secret
    second = Settings()
    assert (first.server_secret, first.link_secret) == (second.server_secret, second.link_secret)
    assert path.read_bytes() == contents
    monkeypatch.setenv("SERVER_SECRET", "override-" * 5)
    third = Settings()
    assert third.server_secret == "override-" * 5
    assert third.link_secret == second.link_secret
    assert path.read_bytes() == contents
    assert set(json.loads(contents)) == {"SERVER_SECRET", "LINK_SECRET"}
    assert ".nowa-secrets" in (ROOT / ".gitignore").read_text().splitlines()


def test_demo_secret_next_to_database(monkeypatch, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.delenv("LINK_SECRET")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder / 'demo.db'}")
    Settings()
    assert (folder / ".nowa-secrets").exists()
    assert not (tmp_path / ".nowa-secrets").exists()


@pytest.mark.parametrize(
    "value, expected", [(None, False), ("a" * 31, False), ("a" * 32, True), ("é" * 16, True)]
)
def test_secret_ok(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ROUTE_SECRET", raising=False)
    else:
        monkeypatch.setenv("ROUTE_SECRET", value)
    assert secret_ok("ROUTE_SECRET") is expected


def test_demo_guard_and_proxy_default(monkeypatch):
    monkeypatch.setenv("RENDER", "")
    with pytest.raises(ValueError, match="DEMO_MODE is not allowed on a hosted deploy"):
        Settings()
    production(monkeypatch)
    assert Settings().trusted_proxy_hops == 1
    monkeypatch.delenv("RENDER")
    assert Settings().trusted_proxy_hops == 0


def test_defaults_and_costs(monkeypatch):
    monkeypatch.delenv("DEMO_MODE")
    settings = Settings()
    assert settings.demo_mode is True
    assert settings.public_base_url == "http://127.0.0.1:8000"
    assert settings.mapbox_usd_per_call == 0.002
    assert settings.ai_rates_json == {}
    assert settings.library_min_score == 0.64
    monkeypatch.setenv("AI_RATES_JSON", '{"model": {"in": 1.0, "out": 2.0}}')
    assert Settings().ai_rates_json["model"]["out"] == 2
    production(monkeypatch)
    monkeypatch.delenv("DEMO_MODE")
    assert Settings().demo_mode is False


@pytest.mark.parametrize("command", ["seed", "demo"])
def test_production_refuses_demo_commands(monkeypatch, tmp_path, command):
    production(monkeypatch)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    result = subprocess.run(
        [sys.executable, "-m", "nowa", command], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "only allowed when DEMO_MODE is true" in result.stderr
    assert not list(tmp_path.glob("*.db"))
    assert not (tmp_path / ".nowa-secrets").exists()
