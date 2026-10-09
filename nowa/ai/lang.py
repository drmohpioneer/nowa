import re
import unicodedata

from nowa.ai.schema import Lang


def detect(text: str, previous: Lang | None = None) -> Lang:
    if any(c.isalpha() and "ARABIC" in unicodedata.name(c, "") for c in text):
        return "ar"
    latin_words = [word for word in text.split() if re.search(r"[A-Za-z]", word)]
    if previous is not None and len(latin_words) < 4:
        return previous
    if re.search(r"[A-Za-z][235789][A-Za-z]|\b[235789][A-Za-z]+", text):
        return "franco"
    if any(c.isalpha() for c in text):
        return "en"
    return previous or "ar"
