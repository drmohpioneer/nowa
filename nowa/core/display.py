"""Language selection over authoritative identity/address fields."""

from collections.abc import Mapping
from typing import Any


def patient_display_name(row: Mapping[Any, Any], lang: str) -> str:
    return str((row.get("name_en") if lang == "en" else None) or row.get("name") or "")


def clinic_address(row: Mapping[Any, Any], lang: str) -> str:
    return str((row.get("address_en") if lang == "en" else None) or row.get("address") or "")


def origin_label(row: Mapping[Any, Any], lang: str) -> str:
    from nowa.core.text_norm import origin_text
    from nowa.web.strings import STRINGS

    value = origin_text(row.get("origin_text"), row.get("area_id"))
    return STRINGS["chat.outside_summary"][lang].format(place=value) if value else ""
