import re
import unicodedata
from collections.abc import Iterable


def mask_phones(text: str, minimum: int = 8, keep: Iterable[str] = ()) -> str:
    public_numbers = {number.removeprefix("+") for number in keep}
    return re.sub(
        r"[0-9\u0660-\u0669]{%d,}" % minimum,
        lambda m: m[0] if m[0] in public_numbers else m[0][:3] + "*" * (len(m[0]) - 3),
        text,
    )


def normalize_question(text: str) -> str:
    text = (
        unicodedata.normalize("NFKC", text)
        .translate(str.maketrans("أإآٱىة٠١٢٣٤٥٦٧٨٩", "اااايه0123456789"))
        .lower()
    )
    text = "".join(c for c in text if c != "ـ" and unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def western_digits(value: str) -> str:
    return value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def greeting_name(value: str) -> str:
    """Keep compound names intact; only an explicit comma or newline ends a greeting."""
    return re.split(r"[,،\n]", value, maxsplit=1)[0].strip()


def origin_text(value: str | None, area_id: int | None) -> str | None:
    """Bounded, phone-masked display text for unresolved origins only."""
    if area_id is not None or value is None:
        return None
    return " ".join(mask_phones(western_digits(value)).split())[:40] or None
