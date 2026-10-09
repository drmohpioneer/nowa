"""Run with system python3 (Playwright); backend stays in the existing .venv.

Creates an isolated temporary demo database, exercises real HTTP controls, and
keeps v2 product PNGs in tests/visual/out. No database fixtures or app edits.
All browser requests are restricted to the temporary loopback server.
"""

import argparse
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


def measure_hub(page, width):
    measured = page.evaluate("""() => {
        const box = n => { const r = n.getBoundingClientRect();
            return {x:r.x, y:r.y, width:r.width, height:r.height,
                right:r.right, bottom:r.bottom}; };
        const board = document.querySelector('.board-door');
        return {cards: [...document.querySelector('.doors').children].map(box),
            board: board ? box(board) : null,
            creds: [...document.querySelectorAll('.creds > div')].map(row => ({
                box:box(row), parts:[...row.children].map(box),
                buttonWidth:row.querySelector('button').getBoundingClientRect().width,
                contentWidth: (() => { const range = document.createRange();
                    range.selectNodeContents(row.querySelector('button'));
                    return range.getBoundingClientRect().width; })(),
                padding: parseFloat(getComputedStyle(row.querySelector('button')).paddingLeft)
                    + parseFloat(getComputedStyle(row.querySelector('button')).paddingRight)
            }))};
    }""")
    assert len(measured["cards"]) == 5
    assert measured["board"] is not None
    rows = {}
    for card in measured["cards"]:
        rows.setdefault(round(card["y"]), []).append(card)
    assert sorted(map(len, rows.values())) == ([1] * 5 if width == 390 else [2, 3])
    for cards in rows.values():
        assert max(c["height"] for c in cards) - min(c["height"] for c in cards) < 1
    board = measured["board"]
    assert len(measured["creds"]) == 2
    for row in measured["creds"]:
        box = row["box"]
        assert board["x"] <= box["x"] < box["right"] <= board["right"]
        assert board["y"] <= box["y"] < box["bottom"] <= board["bottom"]
        # All three parts share a line; copy width is text plus padding and border only.
        assert max(p["y"] for p in row["parts"]) < min(p["bottom"] for p in row["parts"])
        assert abs(row["buttonWidth"] - row["contentWidth"] - row["padding"] - 2) < 2
    return measured


def measure_queue_names(page, required=True, require_walk_in=False):
    measured = page.locator(".tile .t-name").evaluate_all("""nodes => nodes
        .map(n => {
            const box = n.getBoundingClientRect(), tile = n.parentElement.getBoundingClientRect();
            const style = getComputedStyle(n), range = document.createRange();
            range.selectNodeContents(n);
            const text = range.getBoundingClientRect();
            return {name:n.textContent, title:n.title, accessible:n.getAttribute('aria-label'),
                source:n.parentElement.dataset.source, display:style.display,
                whiteSpace:style.whiteSpace, overflow:style.overflow,
                textOverflow:style.textOverflow,
                scrollWidth:n.scrollWidth, clientWidth:n.clientWidth,
                scrollHeight:n.scrollHeight, clientHeight:n.clientHeight,
                textTop:text.top, textBottom:text.bottom, top:box.top, bottom:box.bottom,
                dir:n.dir, height:box.height, lineHeight:parseFloat(style.lineHeight),
                left:box.left, right:box.right, tileLeft:tile.left, tileRight:tile.right};
        })""")
    # Phone-width tiles hide names by design, so there is nothing to measure there.
    assert any(
        n["display"] != "none" and n.get("source") != "walk_in" for n in measured
    ) or not required
    assert any(n.get("source") == "walk_in" for n in measured) or not require_walk_in
    for name in measured:
        if name.get("source") == "walk_in":
            assert name["display"] != "none"
            assert name["whiteSpace"] == "normal" and name["overflow"] == "visible"
            assert name["textOverflow"] == "clip"
            assert name["scrollWidth"] <= name["clientWidth"] + 1
            assert name["scrollHeight"] <= name["clientHeight"] + 1
            # Glyph boxes may exceed the line box by about a pixel; that is not clipping.
            assert name["top"] - 1.5 <= name["textTop"], name
            assert name["textBottom"] <= name["bottom"] + 1.5, name
        elif name["display"] == "none":
            continue
        else:
            assert name["height"] <= name["lineHeight"] + 1
            assert name["whiteSpace"] == "nowrap" and name["textOverflow"] == "ellipsis"
        # names take the page direction, never dir=auto.
        assert name["dir"] in ("rtl", "ltr")
        assert name["name"] == name["title"] == name["accessible"]
        assert name["tileLeft"] <= name["left"] <= name["right"] <= name["tileRight"]
    return measured


def main(browser_name="chromium"):
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    scratch = ROOT / ".scratch"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nowa-visual-", dir=scratch) as directory:
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
                "TELEGRAM_BOT_USERNAME",
                "TELEGRAM_WEBHOOK_SECRET",
                "MAC_RELAY_TOKEN",
                "MAC_RELAY_ALLOWLIST",
            }
            and not key.startswith("AGREEMENT_PARTY_")
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
                    browser = getattr(playwright, browser_name).launch()
                    evidence = []
                    control_positions = []
                    review_measurements = []
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

                            for language in ("ar", "en"):
                                shot("front-" + language, "/?lang=" + language)
                                shot("demo-" + language, "/demo?lang=" + language)
                                review_measurements.append(
                                    dict(
                                        width=width,
                                        scheme=scheme,
                                        language=language,
                                        hub=measure_hub(page, width),
                                    )
                                )
                            shot("front", "/?lang=ar")
                            shot("demo", "/demo?lang=ar")
                            shot("start", "/start?lang=ar")
                            for lang in ("ar", "en"):
                                shot("privacy-" + lang, "/privacy?lang=" + lang)
                                shot("clinic-privacy-" + lang, "/c/dr-hesham/privacy?lang=" + lang)
                                token = checked(
                                    context.request.post(
                                        origin + "/judge/start",
                                        data={"code": "fictional-visual-judge"},
                                        headers={"Origin": origin},
                                    )
                                )["signup_token"]
                                page.evaluate(
                                    "token => sessionStorage.setItem('nowa-judge-signup', token)",
                                    token,
                                )
                                shot("agreement-" + lang, "/start?lang=" + lang)
                                assert page.locator("#complete-form").is_visible()
                                assert page.locator(".agreement h3").count() == 17
                                assert page.locator(".agreement").inner_text().startswith("1.")
                                version = "نسخة 0.1" if lang == "ar" else "Version 0.1"
                                assert (
                                    page.locator("#complete-form > small.help").inner_text()
                                    == version
                                )
                                assert page.locator("#complete-form > h2").first.evaluate(
                                    "n => parseFloat(getComputedStyle(n).marginTop) >= 24"
                                )
                                assert not re.search(
                                    r"\[[A-Z]", page.locator(".agreement").inner_text()
                                )
                                assert page.locator(".hours-row").count() == 7
                                row = page.locator(".hours-row").first
                                before = row.locator('[name="start"]').input_value()
                                row.locator('[name="enabled"]').uncheck()
                                assert row.locator(".hours-times").is_hidden()
                                row.locator('[name="enabled"]').check()
                                assert row.locator('[name="start"]').input_value() == before
                                page.locator(".agreement").evaluate(
                                    "n => n.scrollTop = n.scrollHeight"
                                )

                            shot("evening-idle", "/demo/evening?lang=ar")
                            # Start through the real big play control, pause and retain its
                            # sessionStorage credential. Every later frame reuses this copy.
                            assert page.locator("#clock").inner_text() == "18:20"
                            advances = []
                            page.on(
                                "request",
                                lambda request: (
                                    advances.append(request.post_data_json["to_minute"])
                                    if request.url.split("?")[0].endswith("/advance")
                                    and request.method == "POST"
                                    else None
                                ),
                            )
                            page.locator("#start-play").click()
                            page.wait_for_function("Boolean(sessionStorage.getItem('nowa-watch'))")
                            page.wait_for_function(
                                "document.querySelector('#stage').dataset.run === 'playing'"
                            )
                            page.locator("#pause").click()
                            # The server itself opens the stage at 18:20 (minute 140).
                            assert advances and min(advances) > 140
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
                            positions = {language: {} for language in ("ar", "en")}

                            def measure_controls(state_name):
                                for language in ("ar", "en"):
                                    stage_shot("evening-" + state_name + "-" + language, language)
                                    page.wait_for_function(
                                        "state => document.querySelector('#doctor-chip')"
                                        ".dataset.doctor === state",
                                        arg=state_name,
                                    )
                                    positions[language][state_name] = (
                                        page.locator("#speed").bounding_box()["x"]
                                    )

                            measure_controls("waiting")
                            if width == 1280:
                                shot("front-en", "/?lang=en")
                                shot("demo-en", "/demo?lang=en")
                                stage_shot("evening-mid-en", "en")
                            on_way_state = advance_to(190)
                            measure_controls("on_way")
                            eta_min = on_way_state["doctor"]["eta_min"]
                            assert f"{eta_min} min left" in (
                                page.locator("#doctor-label").inner_text()
                            )
                            advance_to(192)
                            stage_shot("evening-countdown-en", "en")
                            assert f"{eta_min - 2} min left" in (
                                page.locator("#doctor-label").inner_text()
                            )
                            state = advance_to(235)
                            measure_controls("arrived")
                            for language, values in positions.items():
                                if width == 1280:
                                    assert max(values.values()) - min(values.values()) < 0.1, values
                                control_positions.append(
                                    {
                                        "width": width,
                                        "browser": browser_name,
                                        "scheme": scheme,
                                        "language": language,
                                        "speed_x": values,
                                    }
                                )
                            stage_shot("evening-active")
                            assert page.locator('#queue [data-state="in_room"]').count() == 1
                            assert (
                                state["in_room"]["first_name"]
                                in page.locator("#now-band").inner_text()
                            )
                            measure_queue_names(page, required=width == 1280)

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
                            shot("settings", "/d/settings")
                            assert page.locator("#hours .hours-row").count() == 7
                            assert page.locator("#secretary_alerts").count() == 0
                            assert page.locator("#timing small.help").count() == 3
                            shot("doctor", "/d")
                            assert page.locator("#on-way").is_hidden()
                            assert page.locator("#onway-state").is_visible()
                            assert page.locator('#queue .qrow[data-state="in_room"]').count() == 1
                            shot("poster", "/d/poster")
                            assert page.locator(".poster h1").count() == 1
                            assert page.locator(".poster h2").count() == 0
                            assert "مصر الجديدة" in page.locator(".poster").inner_text()
                            assert page.locator('img[src="/d/qr.svg"]').evaluate(
                                "img => img.complete && img.naturalWidth > 0"
                            )
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
                            public = context.request.post(
                                origin + "/demo/book", headers={"Origin": origin},
                                max_redirects=0,
                            )
                            assert public.status == 303
                            page.goto(origin + public.headers["location"])
                            page.locator("#controls > button").first.click()
                            page.wait_for_function(
                                "document.querySelectorAll('#controls button').length === 4"
                            )
                            page.get_by_role("button", name="يوم تاني", exact=True).click()
                            page.wait_for_function(
                                "[...document.querySelectorAll('#chat .bubble')]"
                                ".at(-1).textContent === 'مواعيد تانية:'"
                            )
                            assert page.locator("#chat .bubble.me").last.inner_text() == "يوم تاني"
                            page.locator("#controls button").first.click()
                            page.wait_for_function(
                                "document.querySelectorAll('#controls button').length === 13"
                            )
                            page.get_by_role("button", name="المعادي", exact=True).click()
                            confirm = page.get_by_role("button", name="تأكيد الحجز", exact=True)
                            confirm.wait_for()
                            # Audit 22: the summary offers confirm plus an edit control.
                            assert page.locator("#controls button").count() >= 2
                            assert page.locator("#controls .btn-main").count() == 1
                            assert confirm.evaluate("n => getComputedStyle(n).backgroundColor") != (
                                "rgba(0, 0, 0, 0)"
                            )
                            assert not re.search(
                                r"\+20\d|https?://", page.locator("#chat").inner_text()
                            )
                            # no bubble uses dir=auto.
                            assert page.locator('.bubble[dir="auto"]').count() == 0
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= innerWidth"
                            )
                            file = OUT / f"v23-confirm-{width}-{scheme}.png"
                            page.screenshot(path=str(file), full_page=True, animations="disabled")
                            evidence.append(file.relative_to(ROOT).as_posix())
                            confirm.click()
                            page.locator("#chat-phone").wait_for(state="visible")
                            closed = advance_to(600)
                            assert closed["closed"] and closed["report"]
                            for language in ("ar", "en"):
                                stage_shot(
                                    "evening-closed" if language == "ar" else "evening-closed-en",
                                    language,
                                )
                                names = measure_queue_names(
                                    page, required=width == 1280, require_walk_in=True
                                )
                                total = page.locator('[data-stat="total_seen"]').bounding_box()
                                grid = page.locator("#report-stats").bounding_box()
                                assert abs(total["width"] - grid["width"]) < 1
                                review_measurements.append(
                                    dict(
                                        width=width,
                                        scheme=scheme,
                                        language=language,
                                        total=total,
                                        report_grid=grid,
                                        queue_names=names,
                                    )
                                )
                            assert page.locator("#report").get_attribute("href")
                            # Audit 5: at close the rail shows the real closing time, not 100%.
                            fill = page.locator("#rail .fill").evaluate(
                                "n => parseFloat(n.style.width)"
                            )
                            assert 0 < fill <= 100
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
                    (OUT / "slice22-controls.json").write_text(
                        json.dumps(control_positions, indent=2) + "\n"
                    )
                    (OUT / "slice24-layout.json").write_text(
                        json.dumps(review_measurements, ensure_ascii=False, indent=2) + "\n"
                    )
                    print(json.dumps(control_positions, indent=2))
                    print("\n".join(evidence))
                    print(
                        f"PASS: {len(evidence)} screenshots; both sizes and schemes; "
                        "no horizontal overflow, external requests or browser exceptions"
                    )
            finally:
                server.terminate()
                server.wait(timeout=20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chromium", "webkit"), default="chromium")
    main(parser.parse_args().browser)
