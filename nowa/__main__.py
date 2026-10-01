import argparse
import signal
import sys
import threading
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from nowa import record, worker
from nowa.clock import ClinicOffsetClock, SystemClock
from nowa.config import configure_demo_network, get_settings
from nowa.db import create_db_engine
from nowa.reference import load_reference
from nowa.seed import seed


def migration_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def migrate(engine: Engine) -> None:
    config = migration_config()
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            # SQLite ignores this PRAGMA inside a transaction. End SQLAlchemy's
            # implicit transaction before explicitly starting the atomic upgrade.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
            try:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                config.attributes["connection"] = conn
                command.upgrade(config, "head")
                if conn.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise RuntimeError("Migration left invalid foreign keys")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()
    else:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
    load_reference(engine)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "library":
        from nowa.library.cli import main as library_main

        library_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(prog="nowa")
    parser.add_argument(
        "command", choices=("demo", "migrate", "seed", "serve", "worker", "telegram", "aitest")
    )
    parser.add_argument("telegram_command", nargs="?", choices=("set-webhook",))
    from nowa.ai.live_test import positive_runs

    parser.add_argument("--runs", type=positive_runs, default=3)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.no_browser and args.command != "demo":
        parser.error("--no-browser requires demo")
    if args.command == "demo":
        configure_demo_network()
    try:
        settings = get_settings()
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "aitest":
        from nowa.ai.live_test import run_cli

        raise SystemExit(run_cli(args.runs))
    if args.command == "telegram":
        if args.telegram_command != "set-webhook":
            parser.error("telegram requires set-webhook")
        from nowa.telegram.api import BotAPI, set_webhook

        raise SystemExit(set_webhook(BotAPI()))
    if args.telegram_command is not None:
        parser.error("set-webhook requires telegram")
    if args.command == "worker":
        engine = create_db_engine()
        if engine.dialect.name != "postgresql":
            engine.dispose()
            parser.error("SQLite runs the worker inside the demo server")
        clock = ClinicOffsetClock(SystemClock(), engine)
        record.configure(clock)
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda signum, frame: stop.set())
        try:
            worker.run_forever(engine, clock, worker.build_registry(), stop=stop)
        finally:
            engine.dispose()
        return
    if args.command in {"demo", "seed"} and not settings.demo_mode:
        parser.error(f"{args.command} is only allowed when DEMO_MODE is true")
    if args.command == "demo":
        from nowa.demo.launch import check_port

        check_port()
        if not settings.gemini_api_key and not settings.openrouter_api_key:
            print("AI off (no key): watch an evening and the public link still work", flush=True)
    if args.command in {"demo", "migrate", "seed"}:
        engine = create_db_engine()
        try:
            if args.command in {"demo", "migrate"}:
                migrate(engine)
            if args.command in {"demo", "seed"}:
                seed(engine)
        finally:
            engine.dispose()
    if args.command in {"demo", "serve"}:
        if args.command == "demo" and not args.no_browser:
            from nowa.demo.launch import open_when_ready

            threading.Thread(target=open_when_ready, daemon=True).start()
        uvicorn.run(
            "nowa.app:create_demo_app" if args.command == "demo" else "nowa.app:create_app",
            factory=True,
            host="127.0.0.1" if args.command == "demo" else "0.0.0.0",
            port=8000 if args.command == "demo" else settings.port,
            proxy_headers=False,
            access_log=False,
        )


if __name__ == "__main__":
    main()
