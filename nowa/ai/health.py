from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Answered:
    answer: str
    source_url: str
    source_title: str
    why: str
    evidence: str = ""
    model: str = ""
    library_version: str = ""
    usage: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class NoAnswer:
    reason: str
    usage: list[float] = field(default_factory=list)


class HealthAnswerer(Protocol):
    async def answer(
        self, *, clinic_id: int, specialty: str, question: str, lang: str, session_id: str
    ) -> Answered | NoAnswer: ...


class NoAnswerHealth:
    async def answer(
        self, *, clinic_id: int, specialty: str, question: str, lang: str, session_id: str
    ) -> NoAnswer:
        return NoAnswer("library_not_built")


def get_health_answerer() -> HealthAnswerer:
    from nowa.library.answer import LibraryHealthAnswerer

    return LibraryHealthAnswerer()
