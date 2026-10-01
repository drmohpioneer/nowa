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
