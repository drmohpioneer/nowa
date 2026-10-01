import hashlib
import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMBEDDING_MODEL = "gemini-embedding-001"


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passage_key: str
    specialty: str
    site: str
    source_url: str
    title: str
    text: str
    embedding: list[float]
    embedding_model: str
    fetched_at: datetime

    @field_validator("embedding")
    @classmethod
    def valid_vector(cls, value: list[float]) -> list[float]:
        if not value or not all(math.isfinite(x) for x in value):
            raise ValueError("Invalid embedding")
        return value


class Header(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specialty: str
    ingested_at: datetime
    sources_sha256: str
    embedding_model: str
    count: int = Field(ge=0)


def read_data(path: Path) -> tuple[Header, list[Passage], str]:
    lines = path.read_bytes().splitlines()
    if not lines:
        raise ValueError("Empty library file")
    header = Header.model_validate_json(lines[0])
    passages = [Passage.model_validate_json(line) for line in lines[1:]]
    if header.count != len(passages):
        raise ValueError("Library count mismatch")
    if len({p.passage_key for p in passages}) != len(passages):
        raise ValueError("Duplicate passage key")
    if any(
        p.specialty != header.specialty or p.embedding_model != header.embedding_model
        for p in passages
    ):
        raise ValueError("Library specialty or model mismatch")
    return header, passages, hashlib.sha256(lines[0]).hexdigest()


@lru_cache(maxsize=None)
def library_version(path: Path) -> str:
    # Release files are immutable for a process; replacement requires redeployment.
    # Cache per specialty file, including its configured directory for fixture isolation.
    with path.open("rb") as stream:
        header_line = stream.readline().rstrip(b"\r\n")
    Header.model_validate_json(header_line)
    return hashlib.sha256(header_line).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def encode_data(header: Header, passages: list[Passage]) -> str:
    return "\n".join([header.model_dump_json()] + [p.model_dump_json() for p in passages]) + "\n"


def stable_key(url: str, section: str, text: str) -> str:
    return hashlib.sha256(json.dumps([url, section, text], ensure_ascii=False).encode()).hexdigest()
