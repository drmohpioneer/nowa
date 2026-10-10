import re
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.exceptions import HTTPException

from nowa import schema as s
from nowa.clock import CAIRO
from nowa.config import get_settings
from nowa.core import booking, patient_link
from nowa.core.text_norm import western_digits
from nowa.web import strings, tokens
from nowa.web.logging import PRIVATE_HEADERS, private_path
from nowa.web.request import page_language
from nowa.web.templates import environment

router = APIRouter()


class UnknownLink(Exception):
    pass


def require_view(request: Request, code: str) -> booking.BookingView:
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", code):
        raise UnknownLink
    result = patient_link.view(request.app.state.engine, code, request.query_params.get("lang"))
    if result is None:
        raise UnknownLink
    request.state.patient_lang = result.lang
    request.state.clinic_phone = result.clinic_phone
    return result


def error_page(key: str, status: int, lang: str = "ar", phone: str | None = None) -> HTMLResponse:
    return HTMLResponse(
        environment.get_template("patient/error.html").render(
            t=lambda k: strings.text("patient." + k, lang),
            message=key,
            lang=lang,
            phone=phone,
        ),
        status_code=status,
        headers=PRIVATE_HEADERS,
    )


def wants_html(request: Request) -> bool:
    path = request.url.path
    if (
        path.startswith("/d/api/")
        or path == "/health"
        or (path.startswith("/demo/evening/") and path.endswith(("/state", "/advance", "/start")))
    ):
        return False
    accepted: dict[str, float] = {}
    for item in request.headers.get("accept", "").split(","):
        media, *params = item.strip().split(";")
        quality = 1.0
        for param in params:
            if param.strip().startswith("q="):
                try:
                    quality = float(param.strip()[2:])
                except ValueError:
                    quality = 0.0
        accepted[media] = quality
    if "text/html" in accepted:
        return accepted["text/html"] > 0 and accepted["text/html"] >= accepted.get(
            "application/json", 0
        )
    return private_path(path) and "application/json" not in accepted


def browser_error(request: Request, key: str, status: int) -> HTMLResponse:
    lang = (
        page_language(request)
        if request.query_params.get("lang") in {"ar", "en"}
        or request.headers.get("accept-language")
        else getattr(request.state, "patient_lang", "ar")
    )
    return error_page(key, status, lang, getattr(request.state, "clinic_phone", None))


async def unknown_link(request: Request, exc: Exception) -> Response:
    if not wants_html(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404, headers=PRIVATE_HEADERS)
    return browser_error(request, "not_found", 404)


async def http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    if not wants_html(request):
        return await http_exception_handler(request, exc)
    if exc.status_code == 401 and request.url.path.startswith("/d/"):
        return RedirectResponse(
            "/d/login?lang=" + page_language(request) + "&next=" + quote(request.url.path, safe=""),
            status_code=303,
        )
    response = browser_error(
        request, "not_found" if exc.status_code == 404 else "forbidden", exc.status_code
    )
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    if not wants_html(request):
        return await request_validation_exception_handler(request, exc)
    return browser_error(request, "forbidden", 422)


async def server_error(request: Request, exc: Exception) -> Response:
    if not wants_html(request):
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
    return browser_error(request, "server_error", 500)


async def read_form(request: Request) -> dict[str, str]:
    tokens.check_origin(request)
    form = await request.form()
    # Reject ambiguous duplicate fields and uploaded files at the boundary.
    if len(form.multi_items()) != len(form) or any(not isinstance(v, str) for v in form.values()):
        from fastapi import HTTPException

        raise HTTPException(403)
    return {
        k: western_digits(str(v)) if k in {"last4", "date", "exp"} else str(v)
        for k, v in form.items()
    }


FormData = Annotated[dict[str, str], Depends(read_form)]
View = Annotated[booking.BookingView, Depends(require_view)]


def render(
    request: Request,
    code: str,
    view: booking.BookingView,
    *,
    mode: str = "view",
    message: str | None = None,
    tap: tokens.PageToken | None = None,
    auto: bool = False,
    days: list[date] | None = None,
) -> HTMLResponse:
    from nowa.messaging.templates import format_day, format_time

    now = request.app.state.clock.now(view.clinic_id)
    form = tokens.issue("form", view.booking_id, now)
    tap = tap or tokens.issue("omw", view.booking_id, now)

    def t(key: str) -> str:
        return strings.text("patient." + key, view.lang)

    expected = (
        format_time(view.expected_shown.astimezone(CAIRO), view.lang) if view.expected_shown else ""
    )
    with request.app.state.engine.connect() as conn:
        slug = conn.execute(
            select(s.clinics.c.slug).where(s.clinics.c.id == view.clinic_id)
        ).scalar_one()
    allowed_messages = {
        "verify_failed",
        "locked",
        "readonly",
        "day_refused",
        "cancelled_done",
        "new_link",
        "day_changed",
        "sandbox",
        "repeated",
    }
    notice = request.query_params.get("notice")
    if message is None and notice in allowed_messages:
        message = notice
    selected_day = request.query_params.get("date")
    if selected_day not in {day.isoformat() for day in (days or [])}:
        selected_day = None
    changed_day = None
    if message == "day_changed":
        try:
            chosen = date.fromisoformat(request.query_params.get("date", ""))
            changed_day = format_day(chosen, view.lang)
        except ValueError:
            message = "new_link"
    error_action = request.query_params.get("action")
    if error_action not in {"cancel", "change", "rebook", "telegram"}:
        error_action = mode
    return HTMLResponse(
        environment.get_template("patient/page.html").render(
            t=t,
            chat_url="/c/" + slug + "?lang=" + ("ar" if view.lang == "ar" else "en"),
            v=view,
            code=code,
            mode=mode,
            message=message,
            selected_day=selected_day,
            changed_day=changed_day,
            error_action=error_action,
            form=form,
            tap=tap,
            auto=auto,
            day=format_day(view.date, view.lang),
            expected=expected,
            days=[(d.isoformat(), format_day(d, view.lang)) for d in (days or [])],
            map_url=f"https://www.google.com/maps?q={view.clinic_lat},{view.clinic_lng}",
            telegram=bool(get_settings().telegram_bot_username),
            linking_texts={
                key: strings.text("patient." + key, view.lang) for key in strings.LINKING_TEXTS
            }
            | {
                "open_label": strings.text("patient.open_telegram", view.lang),
                "verify_failed": strings.text("patient.verify_failed", view.lang),
                "locked": strings.text("patient.locked", view.lang),
            },
            active=view.evening_state not in {"closed", "cancelled"}
            and view.state in {"booked", "told_to_leave", "on_my_way"},
        )
    )


def available_days(request: Request, view: booking.BookingView) -> list[date]:
    return [
        day
        for day in booking.open_days(
            request.app.state.engine,
            request.app.state.clock,
            view.clinic_id,
            request.app.state.clock.now(view.clinic_id).astimezone(CAIRO).date(),
            5,
        )
        if day != view.date
    ]


def nonce(
    request: Request, view: booking.BookingView, form: dict[str, str], purpose: tokens.Purpose
) -> str:
    return tokens.verify(
        purpose,
        view.booking_id,
        form.get("tap_token" if purpose == "omw" else "form_token", ""),
        form.get("exp", ""),
        request.app.state.clock.now(view.clinic_id),
    )


@router.api_route("/l/{code}", methods=["GET", "HEAD"])
def details(request: Request, code: str, view: View) -> HTMLResponse:
    return render(request, code, view)


@router.api_route("/w/{code}", methods=["GET", "HEAD"])
def way(request: Request, code: str, view: View) -> HTMLResponse:
    message = "wait" if view.state == "booked" else None
    return render(
        request,
        code,
        view,
        mode="way",
        message=message,
        auto=request.query_params.get("manual") != "1",
    )


@router.post("/w/{code}/tap")
def tap(request: Request, code: str, view: View, form: FormData) -> RedirectResponse:
    key = f"omw:{view.booking_id}:{nonce(request, view, form, 'omw')}"
    patient_link.on_my_way(request.app.state.engine, request.app.state.clock, view.booking_id, key)
    return RedirectResponse(f"/w/{code}", status_code=303)


@router.post("/w/{code}/undo")
def undo(request: Request, code: str, view: View, form: FormData) -> RedirectResponse:
    key = f"omw_undo:{view.booking_id}:{nonce(request, view, form, 'omw')}"
    patient_link.undo_on_my_way(
        request.app.state.engine, request.app.state.clock, view.booking_id, key
    )
    return RedirectResponse(f"/w/{code}?manual=1", status_code=303)


@router.api_route("/l/{code}/change", methods=["GET", "HEAD"])
def change_page(request: Request, code: str, view: View) -> HTMLResponse:
    return render(request, code, view, mode="change", days=available_days(request, view))


@router.api_route("/r/{code}", methods=["GET", "HEAD"], response_model=None)
def rebook_page(request: Request, code: str, view: View) -> HTMLResponse | RedirectResponse:
    if view.state != "cancelled" or view.state_reason not in {"cancel_tonight", "close_untold"}:
        return RedirectResponse(
            f"/l/{code}"
            + (
                "?notice=" + request.query_params["notice"]
                if request.query_params.get("notice") in {"verify_failed", "locked", "readonly"}
                else ""
            ),
            status_code=303,
        )
    return render(request, code, view, mode="rebook", days=available_days(request, view))


def result_redirect(
    code: str, mode: str, message: str, day: date | None = None
) -> RedirectResponse:
    path = (
        f"/r/{code}"
        if mode == "rebook"
        else f"/l/{code}/change"
        if mode == "change"
        else f"/l/{code}"
    )
    params = {"notice": message, "action": mode}
    if day is not None:
        params["date"] = day.isoformat()
    return RedirectResponse(
        path + "?" + urlencode(params), status_code=303, headers=PRIVATE_HEADERS
    )


def action_result(
    request: Request, code: str, result: Any, mode: str, day: date | None = None
) -> RedirectResponse:
    if isinstance(result, booking.LinkRefused):
        return result_redirect(
            code, mode, "readonly" if result.reason == "not_cancellable" else result.reason, day
        )
    if isinstance(result, booking.BookingRefused):
        return result_redirect(code, mode, "day_refused", day)
    if isinstance(result, booking.CancelResult):
        return result_redirect(code, "view", "cancelled_done")
    if mode == "change":
        return result_redirect(code, "view", "day_changed", day)
    return result_redirect(code, "view", "new_link")


@router.post("/l/{code}/cancel")
def cancel(request: Request, code: str, view: View, form: FormData) -> RedirectResponse:
    key = f"cancel:{view.booking_id}:{nonce(request, view, form, 'form')}"
    result = patient_link.cancel_by_link(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), key
    )
    return action_result(request, code, result, "cancel")


def change_action(
    request: Request, code: str, view: booking.BookingView, form: dict[str, str], rebook: bool
) -> RedirectResponse:
    key = (
        f"{'rebook' if rebook else 'change'}:{view.booking_id}:{nonce(request, view, form, 'form')}"
    )
    try:
        day = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return result_redirect(code, "rebook" if rebook else "change", "day_refused")
    command = patient_link.rebook_by_link if rebook else patient_link.change_day_by_link
    result = command(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), day, key
    )
    return action_result(request, code, result, "rebook" if rebook else "change", day)


@router.post("/l/{code}/change")
def change(request: Request, code: str, view: View, form: FormData) -> RedirectResponse:
    return change_action(request, code, view, form, False)


@router.post("/r/{code}")
def rebook(request: Request, code: str, view: View, form: FormData) -> RedirectResponse:
    return change_action(request, code, view, form, True)


@router.post("/l/{code}/telegram", response_model=None)
def telegram(
    request: Request, code: str, view: View, form: FormData
) -> HTMLResponse | RedirectResponse | JSONResponse:
    key = f"tg:{view.booking_id}:{nonce(request, view, form, 'form')}"
    if not get_settings().telegram_bot_username:
        return result_redirect(code, "view", "sandbox")
    result = patient_link.create_telegram_token(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), key
    )
    if isinstance(result, booking.LinkRefused):
        return action_result(request, code, result, "telegram")
    if isinstance(result, patient_link.TelegramRefused):
        return result_redirect(code, "view", "sandbox")
    if result.url is not None:
        if "application/json" in request.headers.get("accept", ""):
            fresh = tokens.issue(
                "form", view.booking_id, request.app.state.clock.now(view.clinic_id)
            )
            return JSONResponse(
                {"telegram_url": result.url, "form_token": fresh.value, "exp": fresh.exp},
                headers=PRIVATE_HEADERS,
            )
        return RedirectResponse(result.url, status_code=303)
    return result_redirect(code, "view", "repeated")


@router.api_route("/s/{code}/take", methods=["GET", "HEAD"])
def standby_page(request: Request, code: str) -> HTMLResponse:
    from nowa.core import standby
    from nowa.messaging.templates import format_day, format_time

    with request.app.state.engine.connect() as conn:
        row = standby.lookup(conn, code)
        if row is None:
            raise UnknownLink
        lang = request.query_params.get("lang", row["lang"])
        if lang not in {"ar", "en", "franco"}:
            lang = row["lang"]
        request.state.patient_lang = lang
        now = request.app.state.clock.now(row["clinic_id"])
        reason = booking._day_status(conn, row["clinic_id"], row["date"], now)[0]
        active = (
            row["state"] == "offered"
            and row["expires_at"] > now
            and reason not in {"closed_day", "booking_closed"}
        )
        next_link = standby.next_day_link(
            conn, request.app.state.clock, row["clinic_id"], row["date"]
        )
        next_link += ("&" if "?" in next_link else "?") + "lang=" + ("ar" if lang == "ar" else "en")
    return HTMLResponse(
        environment.get_template("patient/standby.html").render(
            t=lambda k: strings.text("patient." + k, lang),
            lang=lang,
            code=code,
            active=active,
            taken=row["state"] == "taken",
            day=format_day(row["date"], lang),
            expected=format_time(row["expected_time"], lang),
            next_link=next_link,
            form=tokens.issue("standby", row["id"], now),
        ),
        headers=PRIVATE_HEADERS,
    )


@router.post("/s/{code}/take")
def standby_take(request: Request, code: str, form: FormData) -> RedirectResponse:
    from nowa.core import standby
    from nowa.db import write_tx

    with write_tx(request.app.state.engine) as conn:
        row = standby.lookup(conn, code)
        if row is None:
            raise UnknownLink
        tokens.verify(
            "standby",
            row["id"],
            form.get("form_token", ""),
            form.get("exp", ""),
            request.app.state.clock.now(row["clinic_id"]),
        )
        if form.get("action") not in {"take", "decline"}:
            raise HTTPException(422)
        standby.take_in_tx(conn, request.app.state.clock, code, decline=form["action"] == "decline")
    return RedirectResponse(f"/s/{code}/take", status_code=303, headers=PRIVATE_HEADERS)
