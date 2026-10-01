"""Local demo launch checks; never contacts a remote host."""

import errno
import logging
import socket
import sys
import threading
import webbrowser

import httpx


def check_port() -> None:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 8000))
        except OSError as exc:
            message = (
                "Port 8000 is busy; stop the other server and retry."
                if exc.errno == errno.EADDRINUSE
                else f"Cannot bind port 8000: {exc.strerror}"
            )
            print(message, file=sys.stderr)
            raise SystemExit(1) from None


def open_when_ready() -> None:
    pause = threading.Event()
    with httpx.Client(trust_env=False, timeout=1) as client:
        for _ in range(150):
            try:
                response = client.get("http://127.0.0.1:8000/health")
                if response.status_code == 200 and response.json().get("ok"):
                    if not webbrowser.open("http://127.0.0.1:8000"):
                        logging.getLogger(__name__).warning(
                            "Browser did not open; visit http://127.0.0.1:8000"
                        )
                    return
            except (httpx.HTTPError, ValueError):
                pass  # The local server is still starting; retry within a bounded window.
            pause.wait(0.2)
    logging.getLogger(__name__).error("Demo /health was not ready; browser was not opened")
