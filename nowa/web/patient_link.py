import re
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException

from nowa.clock import CAIRO
from nowa.config import get_settings
from nowa.core import booking, patient_link
from nowa.web import strings, tokens
from nowa.web.logging import PRIVATE_HEADERS, private_path
from nowa.web.templates import environment

router = APIRouter()


class UnknownLink(Exception):
    pass


def require_view(request: Request, code: str) -> booking.BookingView:
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", code):
        raise UnknownLink
    result = patient_link.view(request.app.state.engine, code)
    if result is None:
        raise UnknownLink
    request.state.patient_lang = result.lang
    return result


def error_page(key: str, status: int, lang: str = "ar") -> HTMLResponse:
    return HTMLResponse(
        environment.get_template("patient/error.html").render(
            t=lambda k: strings.text("patient." + k, lang),
            message=key,
            lang=lang,
        ),
        status_code=status,
        headers=PRIVATE_HEADERS,
    )


async def unknown_link(request: Request, exc: Exception) -> HTMLResponse:
    return error_page("not_found", 404)


async def http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    if not private_path(request.url.path):
        return await http_exception_handler(request, exc)
    response = error_page(
        "not_found" if exc.status_code == 404 else "forbidden",
        exc.status_code,
        getattr(request.state, "patient_lang", "ar"),
    )
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    if not private_path(request.url.path):
        return await request_validation_exception_handler(request, exc)
    return error_page("forbidden", 422, getattr(request.state, "patient_lang", "ar"))


async def server_error(request: Request, exc: Exception) -> Response:
    # Starlette's outer ServerErrorMiddleware still re-raises the exception for logging.
    if not private_path(request.url.path):
        return PlainTextResponse("Internal Server Error", status_code=500)
    return error_page("server_error", 500, getattr(request.state, "patient_lang", "ar"))


async def read_form(request: Request) -> dict[str, str]:
    tokens.check_origin(request)
    form = await request.form()
    # Reject ambiguous duplicate fields and uploaded files at the boundary.
    if len(form.multi_items()) != len(form) or any(not isinstance(v, str) for v in form.values()):
        from fastapi import HTTPException

        raise HTTPException(403)
    return {k: str(v) for k, v in form.items()}


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
        t(view.state)
        if view.state in {"told_to_leave", "on_my_way"}
        else format_time(view.expected_shown.astimezone(CAIRO), view.lang)
        if view.expected_shown
        else ""
    )
    return HTMLResponse(
        environment.get_template("patient/page.html").render(
            t=t,
            v=view,
            code=code,
            mode=mode,
            message=message,
            form=form,
            tap=tap,
            auto=auto,
            day=format_day(view.date, view.lang),
            expected=expected,
            days=[(d.isoformat(), format_day(d, view.lang)) for d in (days or [])],
            map_url=f"https://www.google.com/maps?q={view.clinic_lat},{view.clinic_lng}",
            telegram=bool(get_settings().telegram_bot_username),
            active=view.evening_state not in {"closed", "cancelled"}
            and view.state in {"booked", "told_to_leave", "on_my_way"},
        )
    )


def available_days(request: Request, view: booking.BookingView) -> list[date]:
    return booking.open_days(
        request.app.state.engine,
        request.app.state.clock,
        view.clinic_id,
        request.app.state.clock.now(view.clinic_id).astimezone(CAIRO).date(),
        5,
    )


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
    return render(request, code, view, mode="way", message=message, auto=True)


@router.post("/w/{code}/tap")
def tap(request: Request, code: str, view: View, form: FormData) -> HTMLResponse:
    key = f"omw:{view.booking_id}:{nonce(request, view, form, 'omw')}"
    patient_link.on_my_way(request.app.state.engine, request.app.state.clock, view.booking_id, key)
    fresh = require_view(request, code)
    page_token = tokens.PageToken(form["tap_token"], int(form["exp"]))
    return render(
        request,
        code,
        fresh,
        mode="way",
        tap=page_token,
        message="wait" if fresh.state == "booked" else None,
    )


@router.post("/w/{code}/undo")
def undo(request: Request, code: str, view: View, form: FormData) -> HTMLResponse:
    key = f"omw_undo:{view.booking_id}:{nonce(request, view, form, 'omw')}"
    patient_link.undo_on_my_way(
        request.app.state.engine, request.app.state.clock, view.booking_id, key
    )
    return render(request, code, require_view(request, code), mode="way")


@router.api_route("/l/{code}/change", methods=["GET", "HEAD"])
def change_page(request: Request, code: str, view: View) -> HTMLResponse:
    return render(request, code, view, mode="change", days=available_days(request, view))


@router.api_route("/r/{code}", methods=["GET", "HEAD"], response_model=None)
def rebook_page(request: Request, code: str, view: View) -> HTMLResponse | RedirectResponse:
    if view.state != "cancelled" or view.state_reason not in {"cancel_tonight", "close_untold"}:
        return RedirectResponse(f"/l/{code}", status_code=303)
    return render(request, code, view, mode="rebook", days=available_days(request, view))


def action_result(request: Request, code: str, result: Any, mode: str) -> HTMLResponse:
    view = require_view(request, code)
    if isinstance(result, booking.LinkRefused):
        return render(
            request,
            code,
            view,
            mode="readonly" if result.reason == "not_cancellable" else mode,
            message="readonly" if result.reason == "not_cancellable" else result.reason,
            days=available_days(request, view) if mode != "view" else [],
        )
    if isinstance(result, booking.BookingRefused):
        return render(
            request,
            code,
            view,
            mode=mode,
            message="day_refused",
            days=available_days(request, view),
        )
    return render(
        request,
        code,
        view,
        mode="readonly",
        message="cancelled_done" if isinstance(result, booking.CancelResult) else "new_sms",
    )


@router.post("/l/{code}/cancel")
def cancel(request: Request, code: str, view: View, form: FormData) -> HTMLResponse:
    key = f"cancel:{view.booking_id}:{nonce(request, view, form, 'form')}"
    result = patient_link.cancel_by_link(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), key
    )
    return action_result(request, code, result, "view")


def change_action(
    request: Request, code: str, view: booking.BookingView, form: dict[str, str], rebook: bool
) -> HTMLResponse:
    key = (
        f"{'rebook' if rebook else 'change'}:{view.booking_id}:{nonce(request, view, form, 'form')}"
    )
    try:
        day = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return render(
            request,
            code,
            view,
            mode="rebook" if rebook else "change",
            message="day_refused",
            days=available_days(request, view),
        )
    command = patient_link.rebook_by_link if rebook else patient_link.change_day_by_link
    result = command(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), day, key
    )
    return action_result(request, code, result, "rebook" if rebook else "change")


@router.post("/l/{code}/change")
def change(request: Request, code: str, view: View, form: FormData) -> HTMLResponse:
    return change_action(request, code, view, form, False)


@router.post("/r/{code}")
def rebook(request: Request, code: str, view: View, form: FormData) -> HTMLResponse:
    return change_action(request, code, view, form, True)


@router.post("/l/{code}/telegram", response_model=None)
def telegram(
    request: Request, code: str, view: View, form: FormData
) -> HTMLResponse | RedirectResponse:
    key = f"tg:{view.booking_id}:{nonce(request, view, form, 'form')}"
    if not get_settings().telegram_bot_username:
        return render(request, code, view, message="sandbox")
    result = patient_link.create_telegram_token(
        request.app.state.engine, request.app.state.clock, code, form.get("last4", ""), key
    )
    if isinstance(result, booking.LinkRefused):
        return action_result(request, code, result, "view")
    if isinstance(result, patient_link.TelegramRefused):
        return render(request, code, view, message="sandbox")
    if result.url is not None:
        return RedirectResponse(result.url, status_code=303)
    return render(request, code, view, message="repeated")
