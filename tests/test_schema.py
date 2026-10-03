import ast
import re
from datetime import date
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select
from sqlalchemy.exc import IntegrityError

from nowa import schema as s
from nowa.db import metadata, write_tx
from nowa.demo.template import CLINIC

ROOT = Path(__file__).resolve().parents[1]


def check_migration(engine):
    with engine.connect() as conn:
        assert (
            compare_metadata(
                MigrationContext.configure(conn, opts={"compare_server_default": True}), metadata
            )
            == []
        )
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "15"
        assert len(conn.execute(select(s.areas)).all()) == 12
        assert list(conn.execute(select(s.clinics.c.slug)).scalars()) == ["_nowa"]
        assert not conn.execute(select(s.clinic_hours)).all()
        assert not conn.execute(select(s.doctors)).all()
        recipient_check = next(
            c for c in s.outbox.constraints if c.name == "ck_outbox_recipient_kind_values"
        )
        migrated_check = next(
            c
            for c in inspect(conn).get_check_constraints("outbox")
            if c["name"] == recipient_check.name
        )
        if conn.dialect.name == "sqlite":
            assert migrated_check["sqltext"] == str(recipient_check.sqltext)


def test_migration(engine):
    check_migration(engine)
    assert set(inspect(engine).get_table_names()) == set(metadata.tables) | {"alembic_version"}


@pytest.mark.postgres
def test_postgres_migration(postgres_engine):
    check_migration(postgres_engine)


def test_clinic_ownership_and_identity_columns():
    exempt = {
        "telegram_pending",
        "clinics",
        "telegram_links",
        "pending_signups",
        "areas",
        "rate_counters",
        "judge_counters",
        "library_passages",
        "deleted_slugs",
    }
    allowed = {
        ("patients", "name"),
        ("contacts", "phone_e164"),
        ("doctors", "name_ar"),
        ("doctors", "name_en"),
        ("doctors", "mobile_e164"),
        ("telegram_links", "phone_e164"),
        ("pending_signups", "mobile_e164"),
        ("clinics", "name"),
        ("clinics", "phone"),
        ("areas", "name_ar"),
        ("areas", "name_en"),
    }
    found = set()
    for table in metadata.tables.values():
        if table.name not in exempt:
            col = table.c.clinic_id
            assert col.nullable == (table.name == "link_tokens")
            assert any(fk.target_fullname == "clinics.id" for fk in col.foreign_keys)
            assert any(list(index.columns)[0] is col for index in table.indexes)
        for col in table.columns:
            if "name" in col.name or "phone" in col.name or "mobile" in col.name:
                if col.name == "phone_key":
                    continue  # Explicit keyed hash, never the phone.
                found.add((table.name, col.name))
    assert found == allowed


def test_package_boundary_greps():
    for path in (ROOT / "nowa").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".html", ".js"}:
            continue
        source = path.read_text()
        relative = path.relative_to(ROOT).as_posix()
        if relative != "nowa/config.py":
            assert "os.environ" not in source
        if relative != "nowa/web/request.py":
            assert "request.client.host" not in source
            assert "x-forwarded-for" not in source.lower()
        if relative != "nowa/web/templates.py":
            for forbidden in ("innerHTML", "|safe", "Markup(", "parse_mode"):
                assert forbidden not in source
        if path.suffix != ".py":
            continue
        tree = ast.parse(source)
        if relative == "nowa/clock.py":
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == "SystemClock":
                    node.body = [ast.Pass()]
            source = ast.unparse(tree)
        assert not re.search(r"\b(?:datetime\.(?:now|utcnow)|date\.today|time\.time)\s*\(", source)
        if relative not in {
            "nowa/clock.py",
            "nowa/core/ratelimit.py",
            "nowa/core/auth.py",
            "nowa/record.py",
            "nowa/worker.py",
        }:
            assert ".base_now(" not in source


def test_single_writer_boundaries():
    writers = {
        "rate_counters": "nowa/core/ratelimit.py",
        "action_record": "nowa/record.py",
        "usage": "nowa/record.py",
    }
    for path in (ROOT / "nowa").rglob("*.py"):
        source = path.read_text()
        for table, owner in writers.items():
            if path.relative_to(ROOT).as_posix() == owner:
                continue
            assert not re.search(rf"\b{table}\.(?:insert|update|delete)\(", source)
            assert not re.search(rf"\b(?:insert|update|delete)\(\s*{table}\b", source)
            assert not re.search(rf"conflict_insert\([^,]+,\s*{table}\b", source)


def check_constraints(engine, clock):
    with write_tx(engine) as conn:
        clinic = conn.execute(
            s.clinics.insert().values(**CLINIC["clinic"]).returning(s.clinics.c.id)
        ).scalar_one()
        evening = conn.execute(
            s.evenings.insert()
            .values(clinic_id=clinic, date=date(2026, 9, 30))
            .returning(s.evenings.c.id)
        ).scalar_one()
        doctor = dict(clinic_id=clinic, **CLINIC["doctor"], password_hash="fictional-test-hash")
        conn.execute(s.doctors.insert().values(**doctor))
        booking = dict(
            clinic_id=clinic,
            evening_id=evening,
            queue_number=1,
            order_key=1,
            source="walkin_tap",
            lang="ar",
            created_at=clock.now(clinic),
        )
        conn.execute(s.bookings.insert().values(**booking))
        telegram = dict(
            phone_e164="+201000000001", telegram_chat_id="123", linked_at=clock.now(clinic)
        )
        conn.execute(s.telegram_links.insert().values(**telegram, kind="doctor"))
        conn.execute(s.telegram_links.insert().values(**telegram, kind="patient"))
    invalid = [
        s.clinics.update().where(s.clinics.c.id == clinic).values(clock_offset_s=1),
        s.clinics.update().where(s.clinics.c.id == clinic).values(max_per_evening=0),
        s.clinics.update().where(s.clinics.c.id == clinic).values(usual_visit_min=0),
        s.clinics.update().where(s.clinics.c.id == clinic).values(cushion_min=7),
        s.evenings.insert().values(clinic_id=clinic, date=date(2026, 9, 30)),
        s.bookings.insert().values(**booking),
        s.bookings.insert().values(**dict(booking, source="chat", queue_number=2)),
        s.doctors.insert().values(**doctor),
        s.telegram_links.insert().values(**telegram, kind="doctor"),
        s.clinic_day_overrides.insert().values(clinic_id=clinic, date=date(2026, 10, 1)),
        s.clinic_hours.insert().values(
            clinic_id=clinic,
            weekday=7,
            start=CLINIC["hours"][0]["start"],
            end=CLINIC["hours"][0]["end"],
        ),
    ]
    for statement in invalid:
        with pytest.raises(IntegrityError), write_tx(engine) as conn:
            conn.execute(statement)
    with write_tx(engine) as conn:
        conn.execute(
            s.clinics.update()
            .where(s.clinics.c.id == clinic)
            .values(is_sandbox=True, clock_offset_s=120)
        )
        conn.execute(
            s.clinic_day_overrides.insert().values(
                clinic_id=clinic, date=date(2026, 10, 1), closed=True
            )
        )
        patient = conn.execute(
            s.patients.insert()
            .values(clinic_id=clinic, name="Fictional")
            .returning(s.patients.c.id)
        ).scalar_one()
        contact = conn.execute(
            s.contacts.insert()
            .values(clinic_id=clinic, phone_e164="+201000000002")
            .returning(s.contacts.c.id)
        ).scalar_one()
        for identity in ({"patient_id": patient}, {"contact_id": contact}):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    s.bookings.insert().values(
                        **dict(booking, source="chat", queue_number=2, **identity)
                    )
                )
        conn.execute(
            s.bookings.insert().values(
                **dict(
                    booking, source="chat", queue_number=2, patient_id=patient, contact_id=contact
                )
            )
        )


def test_constraints(engine, frozen_clock):
    check_constraints(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_constraints(postgres_engine, frozen_clock):
    check_constraints(postgres_engine, frozen_clock)


def test_enum_constraints_present():
    expected = {
        "doctors": ["lang"],
        "telegram_links": ["kind"],
        "evenings": ["state", "closed_by"],
        "bookings": ["source", "lang", "state"],
        "outbox": ["recipient_kind", "audience", "lang", "channel", "adapter", "status"],
        "timers": ["status", "kind"],
        "action_record": ["actor"],
        "health_record": ["kind"],
        "consents": ["booking_for"],
        "questions": ["status"],
        "link_tokens": ["kind"],
        "usage": ["service"],
    }
    for table, columns in expected.items():
        checks = [
            str(c.sqltext)
            for c in metadata.tables[table].constraints
            if isinstance(c, CheckConstraint)
        ]
        for column in columns:
            assert any(sql.startswith(f"{column} IN (") for sql in checks)
    for table, columns in {
        "usage": ["date", "clinic_id", "judge_id", "service"],
        "saved_answers": ["clinic_id", "question_norm"],
        "questions": ["clinic_id", "evening_id", "text_norm"],
    }.items():
        assert any(
            list(c.columns.keys()) == columns
            for c in metadata.tables[table].constraints
            if isinstance(c, UniqueConstraint)
        )


def test_migration_postgres_ddl_portability():
    import importlib.util

    from sqlalchemy import Boolean
    from sqlalchemy.dialects import postgresql

    migration = ROOT / "migrations" / "versions" / "00_initial_nowa_schema.py"
    spec = importlib.util.spec_from_file_location("initial_migration", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    # Collect all tables first, so foreign-key resolution has the whole migrated schema.
    from sqlalchemy import MetaData, Table
    from sqlalchemy.schema import CreateTable

    captured = MetaData()

    class CaptureMigration:
        @staticmethod
        def f(name):
            return name

        @staticmethod
        def create_table(name, *columns, **kwargs):
            Table(name, captured, *columns)

        @staticmethod
        def create_index(*args, **kwargs):
            pass

    module.op = CaptureMigration
    module.upgrade()
    for table in captured.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=postgresql.dialect())))
        for column in table.columns:
            if isinstance(column.type, Boolean) and column.server_default is not None:
                assert (
                    str(column.server_default.arg.compile(dialect=postgresql.dialect())) == "false"
                )
    assert set(captured.tables) == set(metadata.tables) - {
        "telegram_pending",
        "evening_taps",
        "report_questions",
        "demo_runs",
        "doctor_sessions",
        "auth_codes",
        "travel_estimates",
        "chat_sessions",
        "judge_counters",
        "library_passages",
        "deleted_slugs",
        "agreement_acceptances",
        "verify_attempts",
    }
    assert len(statements) == len(captured.tables)
    timing_spec = importlib.util.spec_from_file_location(
        "timing_migration", ROOT / "migrations/versions/04_timing_engine.py"
    )
    timing_module = importlib.util.module_from_spec(timing_spec)
    timing_spec.loader.exec_module(timing_module)

    class CaptureTiming(CaptureMigration):
        @staticmethod
        def add_column(table, column):
            captured.tables[table].append_column(column)

    timing_module.op = CaptureTiming
    timing_module.upgrade()
    auth_spec = importlib.util.spec_from_file_location(
        "auth_migration", ROOT / "migrations/versions/06_doctor_auth.py"
    )
    auth_module = importlib.util.module_from_spec(auth_spec)
    auth_spec.loader.exec_module(auth_module)
    auth_module.op = CaptureMigration
    auth_module.upgrade()
    travel_spec = importlib.util.spec_from_file_location(
        "travel_migration", ROOT / "migrations/versions/13_mapbox_travel.py"
    )
    travel_module = importlib.util.module_from_spec(travel_spec)
    travel_spec.loader.exec_module(travel_module)
    # The batch-alter portion is exercised against real SQLite and Postgres below.
    from contextlib import nullcontext

    class CaptureTravel(CaptureMigration):
        @staticmethod
        def execute(sql):
            pass

        @staticmethod
        def batch_alter_table(name):
            class Batch:
                def add_column(self, column):
                    captured.tables[name].append_column(column)

                def __getattr__(self, name):
                    return lambda *args, **kwargs: None

            return nullcontext(Batch())

    travel_module.op = CaptureTravel
    travel_module.upgrade()
    chat_spec = importlib.util.spec_from_file_location(
        "chat_migration", ROOT / "migrations/versions/08_chat_ai.py"
    )
    chat_module = importlib.util.module_from_spec(chat_spec)
    chat_spec.loader.exec_module(chat_module)
    chat_module.op = CaptureMigration
    chat_module.upgrade()
    library_spec = importlib.util.spec_from_file_location(
        "library_migration", ROOT / "migrations/versions/09_health_library.py"
    )
    library_module = importlib.util.module_from_spec(library_spec)
    library_spec.loader.exec_module(library_module)
    library_module.op = CaptureMigration
    library_module.upgrade()
    signup_spec = importlib.util.spec_from_file_location(
        "signup_migration", ROOT / "migrations/versions/10_signup.py"
    )
    signup_module = importlib.util.module_from_spec(signup_spec)
    signup_spec.loader.exec_module(signup_module)

    class CaptureSignup(CaptureTravel):
        add_column = CaptureTiming.add_column

        @staticmethod
        def get_bind():
            from types import SimpleNamespace

            return SimpleNamespace(
                dialect=SimpleNamespace(name="postgresql"),
                execute=lambda stmt: SimpleNamespace(scalars=lambda: []),
            )

        @staticmethod
        def batch_alter_table(name, **kwargs):
            return CaptureTravel.batch_alter_table(name)

    signup_module.op = CaptureSignup
    signup_module.upgrade()
    report_spec = importlib.util.spec_from_file_location(
        "report_migration", ROOT / "migrations/versions/11_evening_report.py"
    )
    report_module = importlib.util.module_from_spec(report_spec)
    report_spec.loader.exec_module(report_module)
    report_module.op = CaptureTiming
    report_module.upgrade()
    demo_spec = importlib.util.spec_from_file_location(
        "demo_migration", ROOT / "migrations/versions/12_demo_runs.py"
    )
    demo_module = importlib.util.module_from_spec(demo_spec)
    demo_spec.loader.exec_module(demo_module)
    demo_module.op = CaptureMigration
    demo_module.upgrade()
    telegram_spec = importlib.util.spec_from_file_location(
        "telegram_migration", ROOT / "migrations/versions/15_telegram_only.py"
    )
    telegram_module = importlib.util.module_from_spec(telegram_spec)
    telegram_spec.loader.exec_module(telegram_module)
    telegram_module.op = CaptureTravel
    telegram_module.upgrade()
    assert set(captured.tables) == set(metadata.tables)
    for table in captured.sorted_tables:
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert (
        str(
            captured.tables["visits"].c.accepted.server_default.arg.compile(
                dialect=postgresql.dialect()
            )
        )
        == "true"
    )


def test_pending_signup_delete_preserves_outbox(engine, clinic_id, frozen_clock):
    with write_tx(engine) as conn:
        signup = conn.execute(
            s.pending_signups.insert()
            .values(
                mobile_e164="+201000000099",
                created_at=frozen_clock.now(clinic_id),
                expires_at=frozen_clock.now(clinic_id),
            )
            .returning(s.pending_signups.c.id)
        ).scalar_one()
        values = dict(
            clinic_id=clinic_id,
            pending_signup_id=signup,
            recipient_kind="pending_signup",
            audience="doctor",
            template_id="op:signup_code",
            lang="ar",
            channel="sms",
            adapter="screen_phone",
            body="fictional test",
            idempotency_key="signup",
            created_at=frozen_clock.now(clinic_id),
        )
        conn.execute(s.outbox.insert().values(**values))
        conn.execute(s.pending_signups.delete().where(s.pending_signups.c.id == signup))
        assert conn.execute(select(s.outbox.c.pending_signup_id)).scalar_one() is None
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(s.outbox.insert().values(**dict(values, pending_signup_id=None)))


def check_outbox_recipient_kind_rejected(engine, clock):
    with write_tx(engine) as conn:
        clinic = conn.execute(
            s.clinics.insert().values(**CLINIC["clinic"]).returning(s.clinics.c.id)
        ).scalar_one()
        values = dict(
            clinic_id=clinic,
            recipient_kind="screen",
            audience="doctor",
            template_id="5",
            lang="ar",
            channel="sms",
            adapter="screen_phone",
            body="fictional test",
            idempotency_key="valid-recipient",
            created_at=clock.now(clinic),
        )
        conn.execute(s.outbox.insert().values(**values))
        with (
            pytest.raises(IntegrityError, match="ck_outbox_recipient_kind_values"),
            conn.begin_nested(),
        ):
            conn.execute(
                s.outbox.insert().values(
                    **dict(values, recipient_kind="bogus", idempotency_key="invalid-recipient")
                )
            )


def test_outbox_recipient_kind_rejected(engine, frozen_clock):
    check_outbox_recipient_kind_rejected(engine, frozen_clock)


@pytest.mark.postgres
def test_postgres_outbox_recipient_kind_rejected(postgres_engine, frozen_clock):
    check_outbox_recipient_kind_rejected(postgres_engine, frozen_clock)


def test_usage_default_and_uniqueness(engine, clinic_id):
    values = dict(
        date=date(2026, 9, 30), clinic_id=clinic_id, service="sms", units=1, est_cost_usd=0.006
    )
    with write_tx(engine) as conn:
        conn.execute(s.usage.insert().values(**values))
        assert conn.execute(select(s.usage.c.judge_id)).scalar_one() == ""
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(s.usage.insert().values(**values))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(s.usage.insert().values(**dict(values, judge_id=None)))


def test_required_indexes_and_rate_key(engine):
    inspector = inspect(engine)
    assert any(
        index["column_names"] == ["phone_key", "purpose", "created_at"]
        for index in inspector.get_indexes("auth_codes")
    )
    assert any(
        index["column_names"] == ["status", "due_at"] for index in inspector.get_indexes("timers")
    )
    assert any(
        index["column_names"] == ["clinic_id", "at"]
        for index in inspector.get_indexes("action_record")
    )
    assert inspector.get_pk_constraint("rate_counters")["constrained_columns"] == [
        "scope",
        "key_hash",
        "window_start",
    ]
