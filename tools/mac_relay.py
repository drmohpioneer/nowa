"""Owner-run Messages SMS relay; network ambiguity never causes a second send."""

import subprocess
import time

import httpx

from nowa.config import relay_client_config

SCRIPT = """on run argv
  tell application "Messages"
    set smsService to 1st account whose service type = SMS
    send (item 2 of argv) to participant (item 1 of argv) of smsService
  end tell
end run"""


def main() -> None:
    relay_url, token = relay_client_config()
    if not relay_url or len(token.encode()) < 32:
        raise ValueError("NOWA_RELAY_URL and a >=32-byte MAC_RELAY_TOKEN are required")
    base = relay_url.rstrip("/")
    with httpx.Client(headers={"X-Relay-Token": token}, timeout=15) as client:
        while True:
            try:
                response = client.get(base + "/relay/outbox")
                response.raise_for_status()
                messages = response.json()["messages"]
            except (httpx.HTTPError, ValueError):
                print("Relay poll failed; will poll again.")
                time.sleep(5)
                continue
            for message in messages:
                try:
                    result = subprocess.run(
                        ["osascript", "-e", SCRIPT, message["to"], message["text"]],
                        capture_output=True,
                        timeout=60,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    # No ack: an ambiguous local result follows the server's timeout path.
                    print("Relay send outcome unknown; leaving it for delivery timeout.")
                    continue
                if result.returncode != 0:
                    # AppleScript can fail after Messages accepted the send. Never retry it.
                    print("Messages returned an error; leaving it for delivery timeout.")
                    continue
                try:
                    response = client.post(
                        base + "/relay/ack",
                        json={
                            "id": message["id"],
                            "attempt": message["attempt"],
                            "ok": True,
                            "error": None,
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    print("Relay ack failed; the message will not be sent again.")
            time.sleep(5)


if __name__ == "__main__":
    main()
