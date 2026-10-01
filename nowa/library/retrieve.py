import math
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from nowa.config import get_settings
from nowa.db import create_db_engine
from nowa.library.embed import Embedder
from nowa.library.models import Passage
from nowa.library.store import read_passages


@dataclass(frozen=True)
class ScoredPassage:
    passage: Passage
    score: float


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not all(math.isfinite(x) for x in left + right):
        raise ValueError("Incompatible vectors")
    denominator = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right, strict=True)) / denominator if denominator else 0


def rank(
    passages: list[Passage],
    vector: list[float],
    model: str,
    k: int = 12,
    min_score: float | None = None,
) -> list[ScoredPassage]:
    if any(p.embedding_model != model for p in passages):
        raise ValueError("Embedding model mismatch")
    threshold = get_settings().library_min_score if min_score is None else min_score
    scores = [ScoredPassage(p, cosine(vector, p.embedding)) for p in passages]
    return sorted(
        (p for p in scores if p.score >= threshold), key=lambda p: (-p.score, p.passage.passage_key)
    )[:k]


async def retrieve(
    specialty: str, question: str, embedder: Embedder, k: int = 12, *, engine: Engine | None = None
) -> list[ScoredPassage]:
    owned = engine is None
    engine = engine or create_db_engine()
    try:
        passages = read_passages(engine, specialty)
    finally:
        if owned:
            engine.dispose()
    if not passages:
        return []
    if any(p.embedding_model != embedder.model for p in passages):
        raise ValueError("Embedding model mismatch")
    vectors = await embedder.embed([question], "RETRIEVAL_QUERY")
    if len(vectors) != 1:
        raise ValueError("Query embedding count mismatch")
    return rank(passages, vectors[0], embedder.model, k)
