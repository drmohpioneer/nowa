from datetime import timedelta

import pytest
from sqlalchemy import func, select

from nowa import schema as s
from nowa import worker
from nowa.config import get_settings
from nowa.demo.copy import Busy, create_demo_copy
from nowa.seed import seed

HEADERS = {"Origin": "http://127.0.0.1:8000"}


def start(client, key="web-run-intent-0001"):
    response = client.post("/demo/evening/start", json={"idempotency_key": key}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_start_replay_isolation_state_dashboard(demo_client, engine):
    first = start(demo_client)
    repeated = start(demo_client)
    assert repeated["run_id"] == first["run_id"]
    assert repeated["token"] != first["token"]
    assert "nowa_session" in demo_client.cookies and "nowa_csrf" in demo_client.cookies
    dashboard = demo_client.get("/d")
    assert dashboard.status_code == 200
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.demo_runs)).scalar_one() == 1
        assert conn.execute(select(func.count()).select_from(s.bookings)).scalar_one() == 18
    second = start(demo_client, "web-run-intent-0002")
    for method in ("GET", "POST"):
        url = "/demo/evening/" + second["run_id"]
        response = (
            demo_client.get(url + "/state", params={"token": first["token"]})
            if method == "GET"
            else demo_client.post(
                url + "/advance", json={"token": first["token"], "to_minute": 20}, headers=HEADERS
            )
        )
        assert response.status_code == 403
    url = "/demo/evening/" + first["run_id"]
    assert demo_client.get(url + "/state", params={"token": first["token"]}).json()["minute"] == 0
    response = demo_client.post(
        url + "/advance", json={"token": first["token"], "to_minute": 600}, headers=HEADERS
    )
    assert response.status_code == 200
    data = response.json()
    assert data["closed"] and data["report_url"]
    assert data["phones"][0]["queue_number"] == 7
    demo_client.cookies.set("nowa_session", repeated["token"])
    assert demo_client.get(data["report_url"]).status_code == 200


@pytest.mark.parametrize("minute", [-1, 601, True, 1.5])
def test_advance_validation(demo_client, minute):
    run = start(demo_client)
    response = demo_client.post(
        "/demo/evening/" + run["run_id"] + "/advance",
        json={"token": run["token"], "to_minute": minute},
        headers=HEADERS,
    )
    assert response.status_code == 422


def test_gets_create_nothing_and_public_booking(demo_client, engine, demo_clock, monkeypatch):
    class NoAI:
        calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("AI must never run")

    monkeypatch.setenv("GEMINI_API_KEY", "offline-spy")
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-spy")
    get_settings.cache_clear()
    ai_spy = NoAI()
    demo_client.app.state.ai_chain = [ai_spy]
    for path in ("/", "/demo/evening", "/demo/book"):
        assert demo_client.get(path).status_code == 200
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(s.clinics)).scalar_one() == 1
    response = demo_client.post("/demo/book", headers=HEADERS, follow_redirects=False)
    assert response.status_code == 303
    chat = response.headers["location"]
    html = demo_client.get(chat).text
    assert "لو حالة طارئة اتصل بـ 123" in html
    assert "<input" not in html and "<textarea" not in html
    session = demo_client.post(chat + "/session").json()["session"]

    def tap(action, payload, key):
        return demo_client.post(
            chat + "/tap",
            json={"session": session, "action": action, "payload": payload, "idempotency_key": key},
        )

    before = None
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(s.action_record)).scalar_one()
    assert (
        demo_client.post(
            chat + "/turn",
            json={"session": session, "text": "book me", "idempotency_key": "no-turn"},
        ).status_code
        == 403
    )
    with engine.connect() as conn:
        assert (
            conn.execute(select(func.count()).select_from(s.action_record)).scalar_one() == before
        )
    draft = tap("none", {"identity": 0}, "identity").json()
    day = next(b for b in draft["buttons"] if b["action"]["kind"] == "book_day")
    payload = day["action"]["payload"]
    payload["area_id"] = 1
    booked = tap("book_day", payload, "book")
    assert booked.status_code == 200 and "/l/" not in booked.json()["reply"]
    assert tap("book_day", payload, "book").json() == booked.json()
    with engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == chat.split("/")[-1])
        ).scalar_one()
    worker.drain(engine, demo_clock, worker.build_registry(), only_clinic_id=cid)
    phone = demo_client.get(chat + "/demo/phone", params={"session": session}).json()
    assert len(phone) == 1 and phone[0]["status"] == "delivered" and "/l/" in phone[0]["body"]
    second_session = demo_client.post(chat + "/session").json()["session"]
    assert demo_client.get(chat + "/demo/phone", params={"session": second_session}).json() == []
    seed(engine)
    assert '<input id="message"' in demo_client.get("/c/dr-hesham").text
    # A sandbox with a judge owner also retains the accepted AI chat surface.
    with engine.begin() as conn:
        conn.execute(s.clinics.update().where(s.clinics.c.id == cid).values(judge_id="test-judge"))
    assert '<input id="message"' in demo_client.get(chat).text
    run = start(demo_client)
    assert demo_client.post(
        "/demo/evening/" + run["run_id"] + "/advance",
        json={"token": run["token"], "to_minute": 600},
        headers=HEADERS,
    ).json()["closed"]
    assert ai_spy.calls == 0


def test_public_expiry_uses_system_clock_and_410(demo_client, engine, demo_clock):
    response = demo_client.post("/demo/book", headers=HEADERS, follow_redirects=False)
    chat = response.headers["location"]
    with engine.connect() as conn:
        cid = conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.slug == chat.split("/")[-1])
        ).scalar_one()
        clinic = conn.execute(select(s.clinics).where(s.clinics.c.id == cid)).mappings().one()
        timer = (
            conn.execute(select(s.timers).where(s.timers.c.kind == "sandbox_expire"))
            .mappings()
            .one()
        )
        assert timer["due_at"] == clinic["created_at"] + timedelta(hours=2)
        assert (
            timer["idempotency_key"]
            == f"sandbox_expire:{cid}:{int(clinic['created_at'].timestamp())}"
        )
        assert timer["clinic_id"] != cid
    demo_clock.base.advance(minutes=121)
    worker.drain(engine, demo_clock, worker.build_registry())
    assert demo_client.get(chat).status_code == 410


def test_copy_rate_limit_and_watch_deadline(engine, demo_clock):
    ids = [create_demo_copy(engine, demo_clock, "public", "shared-ip") for _ in range(30)]
    with pytest.raises(Busy):
        create_demo_copy(engine, demo_clock, "public", "shared-ip")
    watch = create_demo_copy(engine, demo_clock, "watch", "other-ip")
    with engine.connect() as conn:
        assert (
            len(
                conn.execute(
                    select(s.clinics.c.id).where(s.clinics.c.slug.startswith("demo-"))
                ).all()
            )
            == 31
        )
        row = conn.execute(select(s.clinics).where(s.clinics.c.id == watch)).mappings().one()
        assert row["sandbox_expires_at"] == row["created_at"] + timedelta(hours=24)
        phones = set(
            conn.execute(
                select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id.in_(ids))
            ).scalars()
        )
        assert len(phones) == 30 and all("+201000001000" <= p <= "+201000001999" for p in phones)


def test_200_copy_cap_evicts_oldest_creation_never_judge_or_real(engine, demo_clock, monkeypatch):
    from nowa.core import auth
    from nowa.demo.template import CLINIC

    # Avoid repeating an expensive password hash for 200 fictional doctors; all
    # copy selection, transactions, constraints, timers and cleanup run unchanged.
    password = auth.hash_password("fixture-only-password")
    monkeypatch.setattr(auth, "hash_password", lambda value: password)
    ids = [create_demo_copy(engine, demo_clock, "public", f"ip-{i // 25}") for i in range(200)]
    with engine.begin() as conn:
        # Creation order, not row id, determines eviction.
        oldest = ids[-2]
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == oldest)
            .values(created_at=demo_clock.now(oldest) - timedelta(days=1))
        )
        judge = conn.execute(
            s.clinics.insert()
            .values(
                **(
                    CLINIC["clinic"]
                    | {
                        "slug": "dr-judge-cap-test",
                        "is_sandbox": True,
                        "judge_id": "owner",
                        "created_at": demo_clock.now(ids[0]) - timedelta(days=2),
                    }
                )
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
        real = conn.execute(
            s.clinics.insert()
            .values(
                **(
                    CLINIC["clinic"]
                    | {
                        "slug": "dr-real-cap-test",
                        "created_at": demo_clock.now(ids[0]) - timedelta(days=3),
                    }
                )
            )
            .returning(s.clinics.c.id)
        ).scalar_one()
        slug = conn.execute(select(s.clinics.c.slug).where(s.clinics.c.id == oldest)).scalar_one()
        mobile = conn.execute(
            select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == oldest)
        ).scalar_one()
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=mobile,
                kind="doctor",
                telegram_chat_id="fixture-chat",
                linked_at=demo_clock.now(oldest),
            )
        )
    new = create_demo_copy(engine, demo_clock, "watch", "last-ip")
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(s.clinics)
                .where(s.clinics.c.slug.startswith("demo-"))
            ).scalar_one()
            == 200
        )
        assert conn.execute(
            select(s.clinics.c.id).where(s.clinics.c.id.in_((judge, real)))
        ).all() == [(judge,), (real,)]
        assert not conn.execute(select(s.clinics.c.id).where(s.clinics.c.slug == slug)).first()
        assert conn.execute(
            select(s.deleted_slugs.c.slug).where(s.deleted_slugs.c.slug == slug)
        ).first()
        assert not conn.execute(
            select(s.telegram_links).where(s.telegram_links.c.phone_e164 == mobile)
        ).first()
        assert (
            conn.execute(
                select(s.doctors.c.mobile_e164).where(s.doctors.c.clinic_id == new)
            ).scalar_one()
            == mobile
        )


def test_lifecycle_timer_after_expiry_and_reused_clinic_id(engine, demo_clock):
    first = create_demo_copy(engine, demo_clock, "public", "one")
    with engine.connect() as conn:
        old_key = conn.execute(
            select(s.timers.c.idempotency_key).where(s.timers.c.kind == "sandbox_expire")
        ).scalar_one()
    demo_clock.base.advance(minutes=121)
    worker.drain(engine, demo_clock, worker.build_registry())
    second = create_demo_copy(engine, demo_clock, "public", "two")
    assert first == second  # SQLite's highest deleted id is reused.
    with engine.connect() as conn:
        old = (
            conn.execute(select(s.timers).where(s.timers.c.idempotency_key == old_key))
            .mappings()
            .one()
        )
        assert old["status"] == "done"
        new = (
            conn.execute(
                select(s.timers).where(
                    s.timers.c.kind == "sandbox_expire", s.timers.c.status == "pending"
                )
            )
            .mappings()
            .one()
        )
        assert new["idempotency_key"] != old_key
    demo_clock.base.advance(minutes=121)
    worker.drain(engine, demo_clock, worker.build_registry())
    with engine.connect() as conn:
        assert not conn.execute(select(s.clinics.c.id).where(s.clinics.c.id == second)).first()
