import logging
import re
from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("nowa.access")
PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
    "X-Robots-Tag": "noindex, nofollow",
}


def private_path(path: str) -> bool:
    return bool(re.match(r"^/(l|w|r|s)(/|$)", path))


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = perf_counter()
        status = 500
        path = scope["path"]
        private = private_path(path) or bool(re.match(r"^/(d|c)(/|$)", path))

        async def send_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                if private:
                    headers = MutableHeaders(scope=message)
                    headers.update(PRIVATE_HEADERS)
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            redacted = re.sub(r"^/(l|w|r|s)/[^/]+", r"/\1/<code>", path)
            redacted = redacted.replace("\n", "").replace("\r", "")
            logger.info(
                "%s %s %s %.1fms",
                scope["method"],
                redacted,
                status,
                (perf_counter() - start) * 1000,
            )
