import logging
from datetime import timedelta

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from nowa.app import create_app
from nowa.web import tokens
from tests.web.support import ROOT


@pytest.mark.parametrize("purpose,seconds", [("omw", 43200), ("form", 1800)])
def test_token_lifetime_and_nonce(purpose, seconds, frozen_clock):
    now = frozen_clock.now(1)
    a = tokens.issue(purpose, 1, now)
    b = tokens.issue(purpose, 1, now)
    assert a.exp == int(now.timestamp()) + seconds
    nonce = tokens.verify(purpose, 1, a.value, str(a.exp), now)
    assert len(nonce) == 32
    assert tokens.verify(purpose, 1, a.value, str(a.exp), now) == nonce
    assert tokens.verify(purpose, 1, b.value, str(b.exp), now) != nonce
    assert tokens.verify(purpose, 1, a.value, str(a.exp), now + timedelta(seconds=seconds - 1))
    with pytest.raises(HTTPException) as exc:
        tokens.verify(purpose, 1, a.value, str(a.exp), now + timedelta(seconds=seconds))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("purpose", ["omw", "form"])
@pytest.mark.parametrize("bad", ["binding", "purpose", "signature", "exp", "empty", "junk", "long"])
def test_token_refusals(purpose, bad, frozen_clock):
    now = frozen_clock.now(1)
    t = tokens.issue(purpose, 1, now)
    value, exp, bid, kind = t.value, str(t.exp), 1, purpose
    if bad == "binding":
        bid = 2
    elif bad == "purpose":
        kind = "form" if purpose == "omw" else "omw"
    elif bad == "signature":
        value = value[:22] + ("A" if value[22] != "A" else "B") + value[23:]
    elif bad == "exp":
        exp = str(t.exp + 1)
    elif bad == "empty":
        value = ""
    elif bad == "junk":
        value = "!" * 64
    else:
        exp = "9" * 5000
    with pytest.raises(HTTPException) as exc:
        tokens.verify(kind, bid, value, exp, now)
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "headers,allowed",
    [
        ({"origin": "http://127.0.0.1:8000"}, True),
        ({"referer": "http://127.0.0.1:8000/l/code?q=test"}, True),
        ({"origin": "http://127.0.0.1:8000", "referer": "https://foreign.example"}, True),
        ({"origin": "https://foreign.example", "referer": "http://127.0.0.1:8000"}, False),
        ({"origin": "http://foreign.example:8000"}, False),
        ({"origin": "https://127.0.0.1:8000"}, False),
        ({"origin": "http://127.0.0.1:8001"}, False),
        ({"origin": "null"}, False),
        ({"origin": "http://127.0.0.1:bad"}, False),
        ({"origin": "http://user@127.0.0.1:8000"}, False),
        ({"origin": "", "referer": "http://127.0.0.1:8000"}, False),
        ({}, False),
    ],
)
def test_origin_and_referer(headers, allowed):
    request = Request(
        {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    )
    if allowed:
        tokens.check_origin(request)
    else:
        with pytest.raises(HTTPException) as exc:
            tokens.check_origin(request)
        assert exc.value.status_code == 403


def test_origin_default_port(monkeypatch):
    from nowa.config import get_settings

    get_settings().public_base_url = "https://nowa.example"
    tokens.check_origin(
        Request({"type": "http", "headers": [(b"origin", b"https://nowa.example:443")]})
    )
    with pytest.raises(HTTPException) as exc:
        tokens.check_origin(
            Request({"type": "http", "headers": [(b"origin", b"https://nowa.example:0")]})
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize("prefix", ["l", "w", "r"])
def test_access_log_and_unknown_security(engine, frozen_clock, prefix, caplog):
    caplog.set_level(logging.INFO, logger="nowa.access")
    code = "a" * 22
    with TestClient(create_app(engine, clock=frozen_clock)) as client:
        response = client.get(
            f"/{prefix}/{code}?hidden-query=private", headers={"X-Secret": "hidden-header"}
        )
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
    log = "\n".join(r.getMessage() for r in caplog.records if r.name == "nowa.access")
    assert f"GET /{prefix}/<code> 404" in log and "ms" in log
    for secret in (code, "hidden-query", "private", "hidden-header", "X-Secret", "testclient"):
        assert secret not in log


def test_static_script_is_fixed_and_posts_the_form():
    script = (ROOT / "nowa/web/static/omw.js").read_text()
    assert len(script.splitlines()) < 40
    assert 'getElementById("omw")' in script and "form.requestSubmit()" in script
    assert "innerHTML" not in script
