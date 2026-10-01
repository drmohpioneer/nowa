import hashlib
import math
from typing import Literal, Protocol

from google import genai
from google.genai import types

from nowa.config import get_settings
from nowa.library.models import EMBEDDING_MODEL

Task = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]: ...


class GeminiEmbedder:
    model = EMBEDDING_MODEL

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        key = get_settings().gemini_api_key
        if not key:
            raise ValueError("Embedding key missing")
        vectors: list[list[float]] = []
        async with genai.Client(api_key=key).aio as client:
            for start in range(0, len(texts), 50):
                result = await client.models.embed_content(
                    model=self.model,
                    contents=texts[start : start + 50],
                    config=types.EmbedContentConfig(
                        task_type=task,
                        output_dimensionality=768,
                        http_options=types.HttpOptions(timeout=20000),
                    ),
                )
                embeddings = result.embeddings or []
                batch = [e.values or [] for e in embeddings]
                if len(batch) != len(texts[start : start + 50]) or any(
                    len(v) != 768 or not all(math.isfinite(x) for x in v) for v in batch
                ):
                    raise ValueError("Invalid embedding response")
                vectors.extend(batch)
        return vectors


class FixtureEmbedder:
    model = "fixture-embedding"

    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = vectors or {}
        self.calls: list[tuple[list[str], Task]] = []

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        self.calls.append((texts, task))
        return [
            self.vectors.get(text, [float(x) for x in hashlib.sha256(text.encode()).digest()])
            for text in texts
        ]
