"""Run with system python3 (Playwright); backend stays in the existing .venv.

Creates an isolated temporary demo database, exercises real HTTP controls, and
keeps v2 product PNGs in tests/visual/out. No database fixtures or app edits.
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
            WORKER_IN_PROCESS="0",
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
        with (OUT / "v2-server.log").open("w") as log:
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
                        raise RuntimeError("Demo server exited; see tests/visual/out/v2-server.log")
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
                                file = OUT / f"v2-{name}-{width}-{scheme}.png"
                                page.screenshot(
                                    path=str(file), full_page=True, animations="disabled"
                                )
                                evidence.append(file.relative_to(ROOT).as_posix())

                            shot("front", "/?lang=ar")
                            shot("demo", "/demo?lang=ar")
                            shot("start", "/start?lang=ar")
                            shot("evening-idle", "/demo/evening?lang=ar")
                            # Start through the real big play control, pause and retain its
                            # sessionStorage credential. Every later frame reuses this copy.
                            assert page.locator("#clock").inner_text() == "18:20"
                            advances = []
                            page.on(
                                "request",
                                lambda request: (
                                    advances.append(request.post_data_json["to_minute"])
                                    if request.url.endswith("/advance") and request.method == "POST"
                                    else None
                                ),
                            )
                            page.locator("#start-play").click()
                            page.wait_for_function("Boolean(sessionStorage.getItem('nowa-watch'))")
                            page.wait_for_function(
                                "document.querySelector('#stage').dataset.run === 'playing'"
                            )
                            page.locator("#pause").click()
                            assert advances[0] == 140 and advances.count(140) == 1
                            run = page.evaluate("JSON.parse(sessionStorage.getItem('nowa-watch'))")

                            def advance_to(minute):
                                return checked(
                                    context.request.post(
                                        origin + f"/demo/evening/{run['run_id']}/advance",
                                        data={"token": run["token"], "to_minute": minute},
                                        headers={"Origin": origin},
                                    )
                                )

                            def stage_shot(name, language="ar"):
                                shot(name, "/demo/evening?lang=" + language)
                                page.wait_for_function(
                                    "document.querySelector('#stage').dataset.run !== 'idle'"
                                )
                                assert page.evaluate(
                                    "document.documentElement.scrollWidth <= innerWidth"
                                ), name
                                page.screenshot(
                                    path=str(OUT / f"v2-{name}-{width}-{scheme}.png"),
                                    full_page=True,
                                    animations="disabled",
                                )

                            # FIX 1 starts at 140 (first event minus ten), still before
                            # the doctor's on-my-way action at 190.
                            advance_to(140)
                            stage_shot("evening-mid")
                            if width == 1280:
                                shot("front-en", "/?lang=en")
                                shot("demo-en", "/demo?lang=en")
                                stage_shot("evening-mid-en", "en")
                            state = advance_to(235)
                            stage_shot("evening-active")
                            assert page.locator('#queue [data-state="in_room"]').count() == 1
                            assert (
                                state["in_room"]["first_name"]
                                in page.locator("#now-band").inner_text()
                            )
                            assert page.evaluate("""() =>
                              [...document.querySelectorAll('.tile .t-name')]
                                .filter(n => getComputedStyle(n).display !== 'none').every(n => {
                                  const name = n.getBoundingClientRect();
                                  const tile = n.parentElement.getBoundingClientRect();
                                  return n.dir === 'auto' && n.scrollWidth <= n.clientWidth &&
                                    name.left >= tile.left && name.right <= tile.right;
                                })""")

                            def rail_order(direction):
                                assert page.evaluate(
                                    """direction => {
                                  const ticks = [...document.querySelectorAll('#rail .tick')];
                                  const start = ticks[0].getBoundingClientRect().left;
                                  const end = ticks[1].getBoundingClientRect().left;
                                  return ticks[0].textContent === '18:20' &&
                                    ticks[1].textContent === '02:00' &&
                                    (direction === 'rtl' ? start > end : start < end);
                                }""",
                                    direction,
                                )

                            rail_order("rtl")
                            if width == 1280:
                                stage_shot("evening-active-en", "en")
                                rail_order("ltr")
                                assert page.locator("#feed .tg-kind").count() == len(
                                    state["phones"]
                                )
                                assert "Leave now" in page.locator("#feed").inner_text()
                            # The start endpoint already establishes the doctor session.
                            shot("doctor", "/d")
                            assert (
                                page.locator("#who button:not(.walk)").count()
                                + page.locator("#next-action button").count()
                                <= 4
                            )
                            assert page.locator("#queue .qrow").count() == len(state["queue"])
                            assert page.locator("#on-way").is_hidden()
                            assert page.locator("#onway-state").is_visible()
                            assert page.locator('#queue [data-state="in_room"]').count() == 1
                            leave = next(
                                row for row in state["queue"] if row["state"] == "told_to_leave"
                            )
                            message = next(
                                msg["body"]
                                for msg in state["phones"]
                                if msg["booking_id"] == leave["booking_id"]
                                and msg["template_id"] == "2"
                            )
                            code = re.search(r"/w/([A-Za-z0-9_-]{22})", message)[1]
                            shot("patient", "/l/" + code)
                            assert page.locator(".now-card").count() == 1
                            shot("chat", "/c/dr-hesham")
                            closed = advance_to(600)
                            assert closed["closed"] and closed["report"]
                            stage_shot("evening-closed")
                            assert page.locator("#report").get_attribute("href")
                            assert (
                                page.locator("#rail .fill").evaluate("n => n.style.width") == "100%"
                            )
                            assert page.locator("#report-card .report-sub").count() == 1
                            assert page.locator("#report-card .eyebrow").count() == 0
                            assert page.evaluate("""() => {
                                const nums = [...document.querySelectorAll('#queue .t-n')]
                                  .map(n => n.textContent);
                                const avg = document.querySelector('[data-stat="avg_wait"]');
                                const gridWidth = avg.parentElement.getBoundingClientRect().width;
                                return nums[nums.indexOf('+') - 1] === '9' &&
                                  Math.abs(avg.getBoundingClientRect().width - gridWidth) < 1;
                            }""")
                            assert not errors, errors
                            assert not external, external
                            context.close()
                    browser.close()
                    (OUT / "v2-files.json").write_text(json.dumps(evidence, indent=2) + "\n")
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
