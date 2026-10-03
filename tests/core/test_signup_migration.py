"""Decision 064: populated upgrades preserve identities and fail atomically."""

import shutil

import pytest
from alembic import command

from nowa import __main__ as cli
from nowa.db import create_db_engine


def head09(engine):
    config = cli.migration_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "09")
        conn.exec_driver_sql(
            "INSERT INTO clinics(slug,name,specialty,address,lat,lng,phone) "
            "VALUES ('dr-fictional','Fictional','cardiology','Fictional',30,31,'')"
        )
        conn.exec_driver_sql(
            "INSERT INTO doctors(clinic_id,name_ar,name_en,mobile_e164,password_hash,lang) "
            "VALUES (1,'خيالي','Fictional','+201000000005','unused','ar')"
        )
    return config


def test_populated_head09_upgrade_preserves_rows_and_foreign_keys(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'populated-09.db'}")
    try:
        head09(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO patients(clinic_id,name) VALUES (1,'Fictional')")
            conn.exec_driver_sql(
                "INSERT INTO contacts(clinic_id,phone_e164) VALUES (1,'+201000002000')"
            )
            conn.exec_driver_sql("INSERT INTO evenings(clinic_id,date) VALUES (1,'2026-10-01')")
            conn.exec_driver_sql(
                "INSERT INTO bookings(clinic_id,evening_id,patient_id,contact_id,queue_number,"
                "order_key,source,lang,created_at) "
                "VALUES (1,1,1,1,1,1,'chat','ar',CURRENT_TIMESTAMP)"
            )
            for phone in ("+201000000006", "+201000000007"):
                conn.exec_driver_sql(
                    "INSERT INTO pending_signups(mobile_e164,created_at,expires_at) "
                    "VALUES (?,CURRENT_TIMESTAMP,'2026-10-02 12:00:00')",
                    (phone,),
                )
            conn.exec_driver_sql(
                "INSERT INTO auth_codes(clinic_id,purpose,phone_key,pending_signup_id,"
                "code_hash,created_at,expires_at) "
                "VALUES (1,'signup','fictional',1,'hash',CURRENT_TIMESTAMP,'2026-10-02')"
            )
            conn.exec_driver_sql(
                "INSERT INTO outbox(clinic_id,pending_signup_id,recipient_kind,audience,"
                "template_id,lang,channel,adapter,body,status,idempotency_key,created_at) "
                "VALUES (1,1,'pending_signup','doctor','op:signup_code','ar','sms',"
                "'screen_phone','fictional','queued','fictional',CURRENT_TIMESTAMP)"
            )
            before = {
                table: conn.exec_driver_sql(f"SELECT * FROM {table}").all()
                for table in (
                    "doctors",
                    "patients",
                    "contacts",
                    "evenings",
                    "bookings",
                    "auth_codes",
                    "outbox",
                )
            }
        cli.migrate(engine)
        with engine.connect() as conn:
            assert (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "15"
            )
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            for table, rows in before.items():
                after = conn.exec_driver_sql(f"SELECT * FROM {table}").all()
                if table == "evenings":
                    assert [tuple(row[:-2]) for row in after] == [tuple(row) for row in rows]
                    assert all(tuple(row[-2:]) == (None, None) for row in after)
                else:
                    assert after == rows
            assert conn.exec_driver_sql("SELECT created_at FROM clinics WHERE id=1").scalar_one()
            pending = conn.exec_driver_sql(
                "SELECT id,mobile_e164,nonce FROM pending_signups ORDER BY id"
            ).all()
            assert [(row[0], row[1]) for row in pending] == [
                (1, "+201000000006"),
                (2, "+201000000007"),
            ]
            assert len({row[2] for row in pending}) == 2
            assert all(len(bytes.fromhex(row[2])) == 16 for row in pending)
    finally:
        engine.dispose()


def test_dangling_foreign_key_upgrade_rolls_back_and_restores_enforcement(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    try:
        config = head09(engine)
        source = config.get_main_option("script_location")
        scripts = tmp_path / "migrations"
        shutil.copytree(source, scripts)
        (scripts / "versions" / "11_broken.py").write_text("""from alembic import op
import sqlalchemy as sa
revision = "11_broken"
down_revision = "15"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("broken_child",
                    sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id")))
    op.execute(sa.text("INSERT INTO broken_child VALUES (999999)"))
""")
        config.set_main_option("script_location", str(scripts))
        monkeypatch.setattr(cli, "migration_config", lambda: config)
        with pytest.raises(RuntimeError, match="invalid foreign keys"):
            cli.migrate(engine)
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "09"
            )
            assert conn.exec_driver_sql("SELECT count(*) FROM doctors").scalar_one() == 1
            assert conn.exec_driver_sql("SELECT count(*) FROM clinics").scalar_one() == 1
            tables = set(
                conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars()
            )
            assert "broken_child" not in tables
            assert "agreement_acceptances" not in tables
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(clinics)")}
            assert "created_at" not in columns
            assert "nonce" not in {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(pending_signups)")
            }
    finally:
        engine.dispose()



def test_populated_head10_evening_upgrade_through_runner(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'populated-10.db'}")
    try:
        config = cli.migration_config()
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "10")
            # Head 10 includes the permanent system clinic (id 1).
            conn.exec_driver_sql(
                "INSERT INTO clinics(id,slug,name,specialty,address,lat,lng,phone) "
                "VALUES (2,'dr-fictional','Fictional','cardiology','Fictional',30,31,'')"
            )
            conn.exec_driver_sql(
                "INSERT INTO doctors(clinic_id,name_ar,name_en,mobile_e164,password_hash,lang) "
                "VALUES (2,'خيالي','Fictional','+201000000005','unused','ar')"
            )
            conn.exec_driver_sql("INSERT INTO patients(clinic_id,name) VALUES (2,'Fictional')")
            conn.exec_driver_sql(
                "INSERT INTO contacts(clinic_id,phone_e164) VALUES (2,'+201000002000')"
            )
            conn.exec_driver_sql("INSERT INTO evenings(clinic_id,date,state,closed_at,closed_by) "
                                 "VALUES (2,'2026-10-01','closed',CURRENT_TIMESTAMP,'doctor')")
            conn.exec_driver_sql(
                "INSERT INTO bookings(clinic_id,evening_id,patient_id,contact_id,queue_number,"
                "order_key,source,lang,created_at) "
                "VALUES (2,1,1,1,1,1,'chat','ar',CURRENT_TIMESTAMP)"
            )
            before = {table: conn.exec_driver_sql(f"SELECT * FROM {table}").all()
                      for table in ("clinics", "doctors", "patients", "contacts", "bookings")}
            evening = conn.exec_driver_sql("SELECT * FROM evenings").one()
        cli.migrate(engine)
        with engine.connect() as conn:
            assert (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "15"
            )
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            for table, original in before.items():
                assert conn.exec_driver_sql(f"SELECT * FROM {table}").all() == original
            upgraded = conn.exec_driver_sql("SELECT * FROM evenings").one()
            assert tuple(upgraded[:-2]) == tuple(evening)
            assert tuple(upgraded[-2:]) == (None, None)
            columns = {r[1]: r for r in conn.exec_driver_sql("PRAGMA table_info(evenings)")}
            assert all(columns[name][2] == "TIME" and columns[name][3] == 0
                       for name in ("paper_start", "paper_end"))
            conn.exec_driver_sql("UPDATE evenings SET paper_start='23:00:00',paper_end='01:00:00'")
            assert conn.exec_driver_sql("SELECT paper_start,paper_end FROM evenings").one() == (
                "23:00:00", "01:00:00",
            )
    finally:
        engine.dispose()
