"""Source presentation independent of model wording."""

from urllib.parse import urlparse

from nowa.ai.schema import Source
from nowa.web.strings import STRINGS

PUBLISHERS = {"nhs.uk": "NHS", "medlineplus.gov": "MedlinePlus"}
ATTRIBUTIONS = {
    "nhs.uk": (
        "Health information from the NHS website, licensed under the Open Government Licence v3.0"
    ),
    "medlineplus.gov": "Source: MedlinePlus, National Library of Medicine",
}


def source_link(url: str, title: str, lang: str) -> Source:
    host = (urlparse(url).hostname or "").removeprefix("www.")
    clean = " ".join(title.split()).split(" - NHS")[0].split(" > ")[0].strip()
    if lang != "en":
        key = "high_blood_pressure" if "/high-blood-pressure" in url else "health_information"
        clean = STRINGS["source." + key][lang]
    publisher = PUBLISHERS.get(host, host)
    label = {"ar": "المصدر", "en": "Source", "franco": "El masdar"}[lang]
    return Source(
        label=f"{label}: {publisher} · {clean}", url=url, attribution=ATTRIBUTIONS.get(host, "")
    )
