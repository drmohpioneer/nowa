"""Stage regression paths using only the in-process ASGI client."""

from tests.demo.test_web import HEADERS, start


def test_audit_66_stage_preserves_doctor_and_previous_report(demo_client):
    demo_client.cookies.set("nowa_session", "prior-doctor-session")
    first = start(demo_client, "audit-stage-cookie-first")
    assert demo_client.cookies.get("nowa_session") == "prior-doctor-session"
    path = "/demo/evening/" + first["run_id"]
    initial = demo_client.get(path + "/state", params={"token": first["token"]}).json()
    assert initial["clock"] == initial["evening"]["start_at"]
    result = demo_client.post(
        path + "/advance", json={"token": first["token"], "to_minute": 600}, headers=HEADERS
    ).json()
    page = demo_client.get(result["report_url"], follow_redirects=False)
    assert page.status_code == 200 and 'id="report-summary"' in page.text
    report = demo_client.get(result["report_url"].replace("/d/report/", "/d/api/report/"))
    assert report.status_code == 200 and report.json()["evening_id"] == int(
        result["report_url"].split("/")[-1]
    )
    start(demo_client, "audit-stage-cookie-second")
    assert demo_client.cookies.get("nowa_session") == "prior-doctor-session"
    page = demo_client.get(result["report_url"], follow_redirects=False)
    assert page.status_code == 200 and 'id="report-summary"' in page.text
    report = demo_client.get(result["report_url"].replace("/d/report/", "/d/api/report/"))
    assert report.status_code == 200 and report.json()["evening_id"] == int(
        result["report_url"].split("/")[-1]
    )


def test_audit_66_stage_visitor_reaches_that_stage_board(demo_client):
    # Without any doctor session, the board is behind the login.
    assert demo_client.get("/d", follow_redirects=False).status_code in (302, 303, 307)
    # Starting the stage gives the visitor that stage's own board, without a login.
    first = start(demo_client, "audit-stage-board-cookie")
    assert demo_client.cookies.get("nowa_session") is None
    board = demo_client.get("/d", follow_redirects=False)
    assert board.status_code == 200 and 'id="queue"' in board.text
    assert first["run_id"]
    # The board's commands work from that stage session: the page names the demo CSRF cookie
    # and the pair the stage set passes the command check (the judge's tap after "Open the board").
    assert '<meta name="csrf-cookie" content="nowa_demo_csrf">' in board.text
    csrf = demo_client.cookies.get("nowa_demo_csrf")
    assert csrf
    tap = demo_client.post(
        "/d/api/on-my-way",
        json={"area_id": 1, "idempotency_key": "audit-66-stage-tap"},
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )
    assert tap.status_code == 200, tap.text


def test_audit_11_demo_book_redirect_keeps_language(demo_client):
    result = demo_client.post("/demo/book?lang=en", headers=HEADERS, follow_redirects=False)
    assert result.status_code == 303 and "lang=en" in result.headers["location"]
    html = demo_client.get(result.headers["location"]).text
    assert '<html lang="en" dir="ltr">' in html and "Book as" in html
