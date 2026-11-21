from nowa.messaging.outbox import ScreenMessage
from nowa.web.demo import stage_body
from tests.core.support import BASE


def test_legacy_leave_message_keeps_sent_body():
    message = ScreenMessage(
        1,
        "patient",
        1,
        "2",
        "original sent text",
        "delivered",
        BASE,
        values_json={"patient_name": "Fictional"},
    )
    assert stage_body(message, "en") == "original sent text"
