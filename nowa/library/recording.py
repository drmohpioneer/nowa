import json
import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine

from nowa import record
from nowa.ai.health import Answered
from nowa.clock import SystemClock
from nowa.config import get_settings
from nowa.db import write_tx
from nowa.library.answer import LibraryHealthAnswerer, required_lines_match
from nowa.library.models import atomic_write
from nowa.schema import clinics

logger = logging.getLogger(__name__)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text_ar: str
    approved: bool
    must_end_with: str | None = Field(default=None, min_length=1)
    must_contain: str | None = Field(default=None, min_length=1)


class Questions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specialty: str
    questions: list[Question]


async def record_questions(
    engine: Engine,
    specialty: str,
    path: Path,
    answerer: LibraryHealthAnswerer | None = None,
    output: Path | None = None,
) -> None:
    settings = get_settings()
    if not settings.demo_mode or not settings.gemini_api_key:
        raise ValueError("record requires DEMO_MODE and GEMINI_API_KEY")
    questions = Questions.model_validate(yaml.safe_load(path.read_bytes()))
    if questions.specialty != specialty:
        raise ValueError("Question specialty mismatch")
    with engine.connect() as conn:
        clinic = conn.execute(select(clinics).where(clinics.c.slug == "dr-hesham")).mappings().one()
    if clinic["specialty"] != specialty:
        raise ValueError("Seed clinic specialty mismatch")
    record.configure(SystemClock())
    answerer = answerer or LibraryHealthAnswerer(engine)
    rows = []
    failures = []
    for question in questions.questions:
        if not question.approved:
            continue
        for attempt in range(1, 4):
            answer = await answerer.answer(
                clinic_id=clinic["id"],
                specialty=specialty,
                question=question.text_ar,
                lang="ar",
                session_id="record:" + question.id,
            )
            with write_tx(engine) as conn:
                for estimate in answer.usage:
                    record.record_usage(conn, clinic["id"], None, "ai", 1, estimate)
            if isinstance(answer, Answered) and required_lines_match(
                answer.answer,
                must_end_with=question.must_end_with,
                must_contain=question.must_contain,
            ):
                break
            reason = answer.reason if not isinstance(answer, Answered) else "required_line_missing"
            rejected = answer if isinstance(answer, Answered) else answerer.last_output
            logger.warning(
                "Refused recording question=%s attempt=%s reason=%s model=%s "
                "answer=%r evidence=%r",
                question.id,
                attempt,
                reason,
                answer.model if isinstance(answer, Answered) else answerer.last_model,
                rejected.answer if rejected else None,
                rejected.evidence if rejected else None,
            )
        else:
            failures.append(question.id + ":" + reason)
            continue
        assert isinstance(answer, Answered)
        rows.append(
            dict(
                question=question.text_ar,
                lang="ar",
                must_end_with=question.must_end_with,
                must_contain=question.must_contain,
                answer=answer.answer,
                source_url=answer.source_url,
                source_title=answer.source_title,
                evidence=answer.evidence,
                why=answer.why,
                model=answer.model,
                library_version=answer.library_version,
                passage_keys=[p.passage.passage_key for p in answerer.last_retrieved],
                commit=settings.render_git_commit,
                recorded_at=SystemClock().now(clinic["id"]).isoformat(),
            )
        )
    if failures:
        raise ValueError("Refused recording questions: " + ", ".join(failures))
    atomic_write(
        output or settings.library_data_dir / f"{specialty}_recorded.json",
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
    )
