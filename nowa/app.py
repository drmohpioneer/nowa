import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from nowa import record, worker
from nowa.clock import ClinicOffsetClock, Clock, SystemClock
from nowa.config import get_settings
from nowa.core.signup import load_agreement
from nowa.db import create_db_engine
from nowa.schema import clinics
from nowa.telegram import poller
from nowa.telegram.api import BotAPI
from nowa.telegram.router import configure as configure_telegram
from nowa.web.chat import router as chat_router
from nowa.web.demo import page as demo_page
from nowa.web.demo import router as demo_router
from nowa.web.doctor_api import router as doctor_api_router
from nowa.web.doctor_auth import router as doctor_auth_router
from nowa.web.doctor_pages import router as doctor_pages_router
from nowa.web.front import router as front_router
from nowa.web.logging import AccessLogMiddleware
from nowa.web.patient_link import (
    UnknownLink,
    http_error,
    server_error,
    unknown_link,
    validation_error,
)
from nowa.web.patient_link import router as patient_router
from nowa.web.signup import router as signup_router
from nowa.web.telegram_webhook import router as telegram_webhook_router


def create_app(
    engine: Engine | None = None,
    *,
    demo_worker: bool = False,
    clock: Clock | None = None,
) -> FastAPI:
    settings = get_settings()
    db_engine = engine if engine is not None else create_db_engine()

    app_clock = clock if clock is not None else ClinicOffsetClock(SystemClock(), db_engine)
    started_at = worker.start_clock(app_clock)
    worker_enabled = demo_worker or bool(settings.worker_in_process)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.clock = app_clock
        record.configure(app.state.clock)
        app.state.telegram_router = configure_telegram(db_engine, app_clock)
        if not settings.ai_rates_json:
            logging.getLogger(__name__).warning("AI_RATES_JSON is empty; AI estimated cost is 0")
        stop = threading.Event()
        thread = None
        telegram_thread = None
        if demo_worker and settings.demo_no_network:
            logging.getLogger(__name__).warning("kind=poller outcome=disabled_demo_no_network")
        if demo_worker and settings.telegram_bot_token and not settings.demo_no_network:
            api = BotAPI(sleep=stop.wait)
            app.state.telegram_router.api = api
            telegram_thread = threading.Thread(
                target=poller.run_forever,
                args=(app.state.telegram_router, api),
                kwargs={"stop": stop},
                name="nowa-telegram",
            )
            telegram_thread.start()
        if worker_enabled:
            thread = threading.Thread(
                target=worker.run_forever,
                args=(db_engine, app_clock, worker.build_registry()),
                kwargs={"stop": stop},
                name="nowa-worker",
            )
            app.state.worker_stop = stop
            app.state.worker_thread = thread
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                thread.join()
            if telegram_thread is not None:
                telegram_thread.join()
            if engine is None:
                db_engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.engine = db_engine
    app.state.agreement = load_agreement()
    app.include_router(front_router)
    # The accepted front page discovers the watch entry among direct route paths.
    app.add_api_route("/demo/evening", demo_page, methods=["GET"])
    app.include_router(demo_router)
    app.include_router(signup_router)
    app.include_router(chat_router)
    app.include_router(doctor_auth_router)
    app.include_router(doctor_api_router)
    app.include_router(doctor_pages_router)
    app.include_router(patient_router)
    app.include_router(telegram_webhook_router)
    app.add_exception_handler(UnknownLink, unknown_link)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, server_error)
    app.add_middleware(AccessLogMiddleware)
    app.mount(
        "/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static"
    )

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            with db_engine.connect() as conn:
                conn.execute(select(clinics.c.id).limit(1)).all()
            status, stale = worker.health(
                db_engine,
                app_clock,
                started_at,
                required=worker_enabled,
            )
        except SQLAlchemyError:
            return JSONResponse({"ok": False}, status_code=503)
        return JSONResponse(
            {"ok": not stale, "db": True, "commit": settings.render_git_commit, "worker": status},
            status_code=503 if stale else 200,
        )

    return app


def create_demo_app() -> FastAPI:
    return create_app(demo_worker=True)
