"""Real-socket smoke test for a local demo.
Run from the repository with .venv/bin/python tools/demo_socket_smoke.py.
No install, keys or external network needed; child rejects remote DNS/sockets.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

ROOT = Path(__file__).resolve().parents[1]


def smoke(tmp_path):
    # No clone/install. Launch the real demo command on a new SQLite file and
    # reject remote DNS/socket calls inside the child before importing Nowa.
    script = tmp_path / "guarded_demo.py"
    script.write_text("""import runpy, socket, sys
calls=[]
real_connect=socket.socket.connect
real_dns=socket.getaddrinfo
def connect(self,address):
    if address[0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('REMOTE SOCKET: '+str(address))
    return real_connect(self,address)
def dns(host,*args,**kwargs):
    if host not in ('127.0.0.1','::1','localhost',None):
        raise AssertionError('REMOTE DNS: '+str(host))
    return real_dns(host,*args,**kwargs)
socket.socket.connect=connect
socket.getaddrinfo=dns
sys.argv=['nowa','demo','--no-browser']
runpy.run_module('nowa',run_name='__main__')
""")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["LIBRARY_DATA_DIR"] = str(ROOT / "nowa/library/data")
    env["DEMO_NO_NETWORK"] = "1"
    env["TELEGRAM_BOT_TOKEN"] = "offline-test-key"
    env["MAPBOX_TOKEN"] = "offline-test-key"
    env.pop("GEMINI_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)
    log = tmp_path / "cli.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), str(script)],
            cwd=tmp_path,
            env=env,
            stdout=output,
            stderr=output,
        )
        started = time.monotonic()
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() - started < 30:
                    if process.poll() is not None:
                        raise AssertionError(log.read_text())
                    try:
                        health = client.get("http://127.0.0.1:8000/health")
                        if health.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("Local demo startup timed out: " + log.read_text())
                assert health.json()["ok"]
                page = client.get("http://127.0.0.1:8000/")
                assert page.status_code == 200 and "/demo/evening" in page.text
                headers = {"Origin": "http://127.0.0.1:8000"}
                run = client.post(
                    "http://127.0.0.1:8000/demo/evening/start",
                    headers=headers,
                    json={"idempotency_key": "cli-watch-intent-01"},
                ).json()
                state = client.post(
                    "http://127.0.0.1:8000/demo/evening/" + run["run_id"] + "/advance",
                    headers=headers,
                    json={"token": run["token"], "to_minute": 600},
                    timeout=20,
                )
                assert state.status_code == 200 and state.json()["closed"]
                copy = client.post("http://127.0.0.1:8000/demo/book", headers=headers)
                assert copy.status_code == 303
                chat = copy.headers["location"]
                key = client.post("http://127.0.0.1:8000" + chat + "/session").json()["session"]

                def tap(payload, action, intent):
                    return client.post(
                        "http://127.0.0.1:8000" + chat + "/tap",
                        json={
                            "session": key,
                            "action": action,
                            "payload": payload,
                            "idempotency_key": intent,
                        },
                    ).json()

                card = tap({"identity": 0}, "none", "choose")
                payload = next(
                    b["action"]["payload"]
                    for b in card["buttons"]
                    if b["action"]["kind"] == "book_day"
                )
                booked = tap(payload, "book_day", "confirm")
                assert booked["reply"] and not booked["buttons"]
                print(
                    "Existing Python 3.12 environment -> local front page: "
                    f"{time.monotonic() - started:.2f}s including guarded watch/book smoke"
                )
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        assert process.returncode == 0, log.read_text()
    content = log.read_text()
    assert "AI off (no key): watch an evening and the public link still work" in content
    assert "disabled_demo_no_network" in content
    assert "REMOTE SOCKET" not in content and "REMOTE DNS" not in content
    assert "Traceback" not in content
    assert (tmp_path / "nowa-demo.db").exists()
    print(json.dumps({"cli_exit": process.returncode, "offline_guard": True}))


if __name__ == "__main__":
    with TemporaryDirectory(prefix="nowa-demo-socket-") as directory:
        smoke(Path(directory))
