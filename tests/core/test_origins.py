"""reference provenance and bounded origin persistence."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nowa import schema as s
from nowa.core import areas, booking, flows, report, standby, timing
from nowa.db import write_tx
from nowa.reference import AREAS, load_reference
from tests.core.support import DAY, request, setup
from tests.core.test_standby import cancel, full, offer_code

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = [
    ("Heliopolis", "مصر الجديدة", 30.0911, 31.3228),
    ("Nasr City", "مدينة نصر", 30.0561, 31.3300),
    ("Madinaty", "مدينتي", 30.1057, 31.6440),
    ("New Cairo 5th Settlement", "التجمع الخامس", 30.0074, 31.4913),
    ("Maadi", "المعادي", 29.9602, 31.2569),
    ("Zamalek", "الزمالك", 30.0609, 31.2197),
    ("Dokki", "الدقي", 30.0384, 31.2120),
    ("Mohandessin", "المهندسين", 30.0555, 31.2006),
    ("Shubra", "شبرا", 30.0880, 31.2450),
    ("Ain Shams", "عين شمس", 30.1300, 31.3190),
    ("El Obour", "العبور", 30.1930, 31.4780),
    ("6th of October", "٦ أكتوبر", 29.9740, 30.9450),
]


def test_reference_source_and_stable_ids(engine):
    source = json.loads((ROOT / "docs/reference/greater-cairo-areas.json").read_text())
    assert len(AREAS) == len(source["rows"]) == len(areas.ALIASES) == 72
    assert AREAS[:12] == ORIGINAL
    assert AREAS[12:] == [
        (r["name_en"], r["name_ar"], r["lat"], r["lng"]) for r in source["rows"][12:]
    ]
    for name_en, name_ar, lat, lng in AREAS:
        assert name_en and name_ar and 29.70 <= lat <= 30.40 and 30.75 <= lng <= 31.90
    with engine.connect() as conn:
        before = conn.execute(select(s.areas).order_by(s.areas.c.id)).all()
    load_reference(engine)
    with engine.connect() as conn:
        assert conn.execute(select(s.areas).order_by(s.areas.c.id)).all() == before
        assert conn.execute(select(s.areas.c.id).order_by(s.areas.c.id)).scalars().all() == list(
            range(1, 73)
        )
    for file in ("README.md",):
        assert "Area coordinates © OpenStreetMap contributors, ODbL" in (ROOT / file).read_text()


@pytest.mark.parametrize("index", range(72))
def test_every_area_names_and_aliases(index):
    for alias in (*AREAS[index][:2], *areas.ALIASES[index].split("|")):
        assert areas.resolve(alias) == index + 1, alias


@pytest.mark.parametrize("text", ["gesr elsewis", "gesr el suez", "جسر السويس", "men gesr el swes"])
def test_gesr_el_suez_kept_alongside_nozha(text):
    result = areas.resolve(text)
    assert isinstance(result, int) and AREAS[result - 1][0] == "Gesr El Suez"
    assert AREAS[areas.resolve("El Nozha") - 1][0] == "El Nozha"


@pytest.mark.parametrize(
    "area_id,raw,expected",
    [
        (None, "  Fictional  01012345678  District ", "Fictional 010******** District"),
        (None, "منطقة ٠١٠١٢٣٤٥٦٧٨", "منطقة 010********"),
        (None, "x" * 60, "x" * 40),
        (None, "  ", None),
        (None, None, None),
        (5, "Fictional", None),
    ],
)
def test_engine_masks_and_bounds_origin(engine, area_id, raw, expected):
    cid, _, clock, _ = setup(engine, count=1)
    req = replace(request(cid, 51), area_id=area_id, origin_text=raw)
    result = flows.book(engine, clock, req)
    assert isinstance(result, booking.BookingOk)
    assert flows.book(engine, clock, req).booking_id == result.booking_id
    with engine.connect() as conn:
        row = (
            conn.execute(select(s.bookings).where(s.bookings.c.id == result.booking_id))
            .mappings()
            .one()
        )
        assert row["origin_text"] == expected


@pytest.mark.parametrize(
    "lang,note", [("ar", "خارج القايمة"), ("en", "not on the list"), ("franco", "khareg el kayma")]
)
def test_board_report_and_change_day_preserve_origin(engine, lang, note):
    cid, eid, clock, _ = setup(engine, count=1)
    req = replace(request(cid, 51), origin_text="Fictional District")
    result = flows.book(engine, clock, req)
    with engine.connect() as conn:
        board = timing.tonight_board(conn, cid, eid, lang)
        assert board.rows[0].origin_display == ""
        assert board.rows[1].origin_display == f"Fictional District ({note})"
        built = report.build_report(conn, clock, cid, eid, lang)
        assert built.origins == [
            {"queue_number": 2, "origin_display": board.rows[1].origin_display}
        ]
        assert "origins" not in built.blanks()  # Fixed Telegram report template stays unchanged.
    changed = flows.change_day(
        engine,
        clock,
        result.link_code,
        req.contact_phone[-4:],
        DAY + timedelta(days=2),
        "move-origin",
    )
    assert isinstance(changed, booking.ChangeDayResult)
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.bookings.c.origin_text).where(s.bookings.c.id == changed.new_booking_id)
            ).scalar_one()
            == "Fictional District"
        )


def test_standby_origin_survives_take(engine):
    cid, _, clock, ids = full(engine)
    req = replace(request(cid, 51), origin_text="Fictional 01012345678")
    with write_tx(engine) as conn:
        conn.execute(
            s.telegram_links.insert().values(
                phone_e164=booking.normalize_phone(req.contact_phone),
                kind="patient",
                telegram_chat_id="fictional-origin",
                linked_at=clock.now(cid),
            )
        )
        joined = standby.join_in_tx(conn, clock, req)
        assert isinstance(joined, standby.Joined)
        assert (
            conn.execute(select(s.standbys.c.origin_text)).scalar_one() == "Fictional 010********"
        )
    cancel(engine, clock, ids[0])
    with write_tx(engine) as conn:
        taken = standby.take_in_tx(conn, clock, offer_code(engine, joined.standby_id))
        assert isinstance(taken, booking.BookingOk)
        assert (
            conn.execute(
                select(s.bookings.c.origin_text).where(s.bookings.c.id == taken.booking_id)
            ).scalar_one()
            == "Fictional 010********"
        )


@pytest.mark.parametrize("table", [s.bookings, s.standbys])
@pytest.mark.parametrize(
    "values", [{"origin_text": "x" * 41}, {"origin_text": "Fictional", "area_id": 5}]
)
def test_database_enforces_origin_constraints(engine, table, values):
    cid, _, clock, _ = setup(engine, count=1)
    if table is s.standbys:
        from tests.core.test_standby import join

        join(engine, clock, cid)
    with pytest.raises(IntegrityError), write_tx(engine) as conn:
        conn.execute(table.update().values(**values))


def test_rebook_origin_and_clinic_isolation(engine):
    cid, eid, clock, _ = setup(engine, count=1)
    result = flows.book(engine, clock, replace(request(cid, 51), origin_text="Fictional District"))
    with engine.connect() as conn:
        doctor = conn.execute(select(s.doctors.c.id)).scalar_one()
    token = timing.request_cancel_tonight(engine, clock, cid, eid, doctor)
    assert timing.cancel_tonight(engine, clock, cid, eid, doctor, token, "cancel").ok
    booked = flows.rebook(engine, clock, result.booking_id, DAY + timedelta(days=2), "rebook")
    assert isinstance(booked, booking.BookingOk)
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.bookings.c.origin_text).where(s.bookings.c.id == booked.booking_id)
            ).scalar_one()
            == "Fictional District"
        )
        assert timing.tonight_board(conn, cid + 100, eid).rows == []


def test_populated_migration_preserves_bookings_and_standbys(engine):
    from alembic import command

    from nowa.__main__ import migrate, migration_config
    from tests.core.test_standby import join

    cid, _, clock, _ = full(engine)
    join(engine, clock, cid)
    with engine.connect() as conn:
        before = {
            table.name: conn.execute(select(table)).mappings().all()
            for table in (s.bookings, s.standbys)
        }
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        with conn.begin():
            config = migration_config()
            config.attributes["connection"] = conn
            command.downgrade(config, "29")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
    migrate(engine)
    with engine.connect() as conn:
        for table in (s.bookings, s.standbys):
            assert conn.execute(select(table)).mappings().all() == before[table.name]
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
