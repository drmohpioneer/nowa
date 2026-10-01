"""Run with system python3 (Playwright); backend stays in the existing .venv.

Creates an isolated temporary demo database, exercises real HTTP controls, and
keeps 24 product PNGs in tests/visual/out. No database fixtures or app edits.
All browser requests are restricted to the temporary loopback server.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests/visual/out"
BACKEND = ROOT / ".venv/bin/python"


def checked(response):
    assert response.ok, f"HTTP {response.status}: {response.text()}"
    return response.json()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="nowa-visual-") as directory:
        # Explicit no-key configuration, independent of any developer environment.
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "RENDER",
                "DATABASE_URL",
                "SERVER_SECRET",
                "LINK_SECRET",
                "GEMINI_API_KEY",
                "OPENROUTER_API_KEY",
                "MAPBOX_TOKEN",
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_WEBHOOK_SECRET",
                "MAC_RELAY_TOKEN",
                "MAC_RELAY_ALLOWLIST",
            }
        }
        env.update(
            DATABASE_URL=f"sqlite:///{directory}/demo.db",
            DEMO_MODE="1",
            DEMO_NO_NETWORK="1",
            SMS_ADAPTER="screen_phone",
            WORKER_IN_PROCESS="1",
            PUBLIC_BASE_URL=origin,
            PORT=str(port),
            DEMO_DOCTOR_PASSWORD="demo1234",
            JUDGE_CODES="fictional-visual-judge",
            TRUSTED_PROXY_HOPS="0",
        )
        for command in ("migrate", "seed"):
            subprocess.run(
                [str(BACKEND), "-m", "nowa", command],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        with (OUT / "server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    str(BACKEND),
                    "-m",
                    "uvicorn",
                    "nowa.app:create_demo_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(150):
                    if server.poll() is not None:
                        raise RuntimeError("Demo server exited; see tests/visual/out/server.log")
                    try:
                        with urllib.request.urlopen(origin + "/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Demo server did not become ready")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    evidence = []
                    for scheme in ("light", "dark"):
                        for width, height in ((390, 844), (1280, 800)):
                            context = browser.new_context(
                                viewport={"width": width, "height": height},
                                device_scale_factor=2,
                                color_scheme=scheme,
                            )
                            external = []

                            def local_only(route):
                                if route.request.url.startswith(origin + "/"):
                                    route.continue_()
                                else:
                                    external.append(route.request.url)
                                    route.abort()

                            context.route("**/*", local_only)
                            page = context.new_page()
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)))

                            def shot(name, path):
                                response = page.goto(origin + path)
                                assert response.status == 200, (name, response.status)
                                page.wait_for_load_state("networkidle")
                                page.evaluate("document.fonts.ready")
                                assert page.evaluate(
                                    "document.documentElement.scrollWidth <= innerWidth"
                                ), name
                                file = OUT / f"{name}-{width}-{scheme}.png"
                                page.screenshot(
                                    path=str(file), full_page=True, animations="disabled"
                                )
                                evidence.append(file.relative_to(ROOT).as_posix())

                            shot("front", "/")
                            shot("login", "/d/login")
                            page.locator('#login [name="mobile"]').fill("01000000001")
                            page.locator('#login [name="password"]').fill("demo1234")
                            page.locator("#login button").click()
                            page.wait_for_url(origin + "/d")
                            assert (
                                checked(context.request.get(origin + "/d/api/tonight"))["rows"]
                                == []
                            )
                            # The base seed has no bookings. Existing demo controls seed and
                            # advance a fresh watch copy, without modifying the base clinic.
                            run = checked(
                                context.request.post(
                                    origin + "/demo/evening/start",
                                    data={"idempotency_key": f"visual-{width}-{scheme}-evening"},
                                    headers={"Origin": origin},
                                )
                            )
                            checked(
                                context.request.post(
                                    origin + f"/demo/evening/{run['run_id']}/advance",
                                    data={"token": run["token"], "to_minute": 235},
                                    headers={"Origin": origin},
                                )
                            )
                            state = checked(
                                context.request.get(
                                    origin + f"/demo/evening/{run['run_id']}/state",
                                    params={"token": run["token"]},
                                )
                            )
                            leave = next(
                                row for row in state["queue"] if row["state"] == "told_to_leave"
                            )
                            sms = next(
                                msg["body"]
                                for msg in state["phones"]
                                if msg["booking_id"] == leave["booking_id"]
                                and msg["template_id"] == "2"
                            )
                            code = re.search(r"/w/([A-Za-z0-9_-]{22})", sms)[1]
                            shot("doctor", "/d")
                            assert page.locator("#who button:not(.walk)").count() <= 4
                            assert page.locator("#queue .qrow").count() == len(state["queue"])
                            assert page.locator("#in-room").inner_text() == "—"
                            shot("chat", "/c/dr-hesham")
                            shot("patient", "/l/" + code)
                            assert page.locator(".now-card").count() == 1
                            # Load a paused watch run using its existing sessionStorage contract.
                            page.goto(origin + "/demo/evening")
                            page.evaluate(
                                "run => sessionStorage.setItem('nowa-watch', JSON.stringify(run))",
                                dict(run, playing=False),
                            )
                            shot("evening", "/demo/evening")
                            assert not errors, errors
                            assert not external, external
                            context.close()
                    browser.close()
                    (OUT / "files.json").write_text(json.dumps(evidence, indent=2) + "\n")
                    print("\n".join(evidence))
                    print(
                        f"PASS: {len(evidence)} screenshots; both sizes and schemes; "
                        "no horizontal overflow, external requests or browser exceptions"
                    )
            finally:
                server.terminate()
                server.wait(timeout=20)


if __name__ == "__main__":
    main()
