import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from nowa.config import get_settings
from nowa.db import conflict_insert, write_tx
from nowa.library.models import Passage, read_data
from nowa.schema import library_passages


def load(engine: Engine, specialty: str, path: Path | None = None) -> None:
    header, passages, _ = read_data(path or get_settings().library_data_dir / f"{specialty}.jsonl")
    if header.specialty != specialty:
        raise ValueError("Library specialty mismatch")
    with write_tx(engine) as conn:
        for passage in passages:
            values = passage.model_dump(exclude={"embedding"})
            values["embedding_json"] = passage.embedding
            statement = conflict_insert(conn, library_passages).values(**values)
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[library_passages.c.passage_key],
                    set_={key: value for key, value in values.items() if key != "passage_key"},
                )
            )
        conn.execute(
            library_passages.delete().where(
                library_passages.c.specialty == specialty,
                library_passages.c.passage_key.not_in([p.passage_key for p in passages]),
            )
        )


def read_passages(engine: Engine, specialty: str) -> list[Passage]:
    with engine.connect() as conn:
        rows = (
            conn.execute(select(library_passages).where(library_passages.c.specialty == specialty))
            .mappings()
            .all()
        )
    result = []
    for row in rows:
        values = dict(row)
        values.pop("id")
        vector = values.pop("embedding_json")
        values["embedding"] = json.loads(vector) if isinstance(vector, str) else vector
        result.append(Passage.model_validate(values))
    return result


def load_all(engine: Engine) -> None:
    for path in sorted(get_settings().library_data_dir.glob("*.jsonl")):
        load(engine, path.stem, path)
