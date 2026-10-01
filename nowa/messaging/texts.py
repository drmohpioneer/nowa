from collections.abc import Mapping
from typing import Any

from nowa.config import get_settings


def allowed(clinic: Mapping[Any, Any]) -> bool:
    return bool(clinic["is_sandbox"] or get_settings().demo_mode)
