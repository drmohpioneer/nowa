import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.engine import Engine

from nowa.db import conflict_insert, write_tx
from nowa.schema import areas

REFERENCE_LOADERS: list[Callable[[Engine], None]] = []
_ORIGINAL_AREAS = [
    ("Heliopolis", "مصر الجديدة", 30.0911, 31.3228),
    ("Nasr City", "مدينة نصر", 30.0561, 31.3300),
    ("Madinaty", "مدينتي", 30.1057, 31.6440),
    ("New Cairo 5th Settlement", "التجمع الخامس", 30.0074, 31.4913),
    ("Maadi", "المعادي", 29.9602, 31.2569),
    ("Zamalek", "الزمالك", 30.0609, 31.2197),
    ("Dokki", "الدقي", 30.0384, 31.2120),
    ("Mohandessin", "المهندسين", 30.0555, 31.2006),
    ("Shubra", "شبرا", 30.0880, 31.2450),
    ("Ain Shams", "عين شمس", 30.1300, 31.3190),
    ("El Obour", "العبور", 30.1930, 31.4780),
    ("6th of October", "٦ أكتوبر", 29.9740, 30.9450),
]


def _load_areas() -> list[tuple[str, str, float, float]]:
    source = Path(__file__).resolve().parents[1] / "docs/reference/greater-cairo-areas.json"
    rows = json.loads(source.read_text())["rows"]
    originals = {row[0]: row for row in _ORIGINAL_AREAS}
    return [
        *originals.values(),
        *[
            (row["name_en"], row["name_ar"], row["lat"], row["lng"])
            for row in rows
            if row["name_en"] not in originals
        ],
    ]


AREAS = _load_areas()


def load_reference(engine: Engine) -> None:
    with write_tx(engine) as conn:
        for name_en, name_ar, lat, lng in AREAS:
            conn.execute(
                conflict_insert(conn, areas)
                .values(
                    name_en=name_en,
                    name_ar=name_ar,
                    lat=lat,
                    lng=lng,
                )
                .on_conflict_do_update(
                    index_elements=[areas.c.name_en],
                    set_={"name_ar": name_ar, "lat": lat, "lng": lng},
                )
            )
    from nowa.library.store import load_all

    load_all(engine)
    for loader in REFERENCE_LOADERS:
        loader(engine)
