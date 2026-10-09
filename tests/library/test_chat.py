import asyncio
import json

from sqlalchemy import select

from nowa import schema as s
from nowa.ai import health
from nowa.ai.adapters import FixtureAdapter
from nowa.db import write_tx
from nowa.library.answer import LibraryHealthAnswerer
from nowa.library.embed import FixtureEmbedder
from nowa.library.ingest import ingest
from nowa.library.models import read_data
from nowa.library.store import load
from tests.ai.support import book_output, day_payload, output, session, tap, turn
from tests.library.test_library import (
    DOCUMENT,
    PARAGRAPH,
    SENTENCE,
    URL,
    answer_output,
    mock_client,
    response,
)


def test_fixture_ingest_load_chat_records_and_caps(chat, engine, tmp_path, monkeypatch):
    client, app, clinic = chat
    source = tmp_path / "fixture-cardiology.yaml"
    source.write_text(
        json.dumps(
            dict(
                specialty="cardiology",
                sites=[
                    dict(
                        site=site,
                        approved=True,
                        terms_url=f"https://{site}/terms",
                        reuse_terms="Fixture permission, never release content",
                        urls=[URL] if site == "nhs.uk" else [],
                    )
                    for site in ("nhs.uk", "medlineplus.gov", "nhlbi.nih.gov", "cdc.gov")
                ],
            )
        )
    )
    data = tmp_path / "cardiology.jsonl"
    embedder = FixtureEmbedder({DOCUMENT: [1, 0], "exercise": [1, 0]})
    with mock_client(response) as transport:
        asyncio.run(ingest("cardiology", source, data, embedder, client=transport))
    # Load only the corpus built from fixture pages into this test database.
    load(engine, "cardiology", data)
    answerer = LibraryHealthAnswerer(
        engine, embedder, [FixtureAdapter(json.dumps(answer_output()))], tmp_path
    )
    monkeypatch.setattr(health, "get_health_answerer", lambda: answerer)
    key = session(client)
    app.state.ai_chain = [FixtureAdapter(book_output())]
    card = turn(client, key)
    tap(client, key, day_payload(card))
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    reply = turn(client, key, "exercise")
    assert SENTENCE in reply["reply"]
    assert "Fixture heart" in reply["reply"]
    assert reply["source"]["label"] == "Source: NHS · Fixture heart"
    assert reply["source"]["url"] == URL
    assert URL not in reply["reply"]
    assert "Open Government Licence" in reply["source"]["attribution"]
    assert "Licence" not in reply["reply"]
    with engine.connect() as conn:
        row = conn.execute(select(s.health_record)).mappings().one()
        assert row["supporting_sentence"] == SENTENCE
        assert row["source_url"] == URL and row["why"] == "Exercise passage"
        assert row["model"] == "fixture"
        assert row["template_version"] == read_data(data)[2]
        assert conn.execute(select(s.judge_counters.c.ai_msgs)).scalar_one() == 2
        assert (
            conn.execute(select(s.usage.c.units).where(s.usage.c.service == "ai")).scalar_one() == 4
        )
    anonymous = session(client)
    turn(client, anonymous, "exercise")
    with engine.connect() as conn:
        assert len(conn.execute(select(s.health_record)).all()) == 1
        rows = (
            conn.execute(select(s.action_record).where(s.action_record.c.kind == "health_answer"))
            .mappings()
            .all()
        )
        assert len(rows) == 1 and rows[0]["text"] is None
    # Two normalized equal questions, both with zero cosine against this fixture corpus.
    embedder.vectors.update({"سؤال مختلف؟": [0, 1], "سُؤال مختلف!": [0, 1]})
    turn(client, anonymous, "سؤال مختلف؟")
    turn(client, anonymous, "سُؤال مختلف!")
    with engine.connect() as conn:
        assert dict(
            conn.execute(select(s.questions.c.text_display, s.questions.c.count)).all()
        ) == {
            "exercise": 2,
            "سؤال مختلف؟": 2,
        }
        reasons = (
            conn.execute(
                select(s.action_record.c.text).where(s.action_record.c.kind == "health_no_answer")
            )
            .scalars()
            .all()
        )
        assert reasons == ["no_match", "no_match"]
    calls = len(embedder.calls)
    app.state.ai_chain = [FixtureAdapter(output(triage="emergency", is_health_question=True))]
    turn(client, session(client), "help")
    assert len(embedder.calls) == calls


def test_live_factory_never_uses_recording(chat, engine, monkeypatch, tmp_path):
    client, app, clinic = chat
    # The factory reads the configured DB, so point only its engine creation at this test engine.
    monkeypatch.setattr("nowa.library.answer.create_db_engine", lambda: engine)
    with write_tx(engine) as conn:
        conn.execute(s.library_passages.delete())
        conn.execute(
            s.library_passages.insert().values(
                specialty="cardiology",
                site="nhs.uk",
                source_url=URL,
                title="fixture",
                text=PARAGRAPH,
                embedding_json=[1, 0],
                embedding_model="fixture-embedding",
                passage_key="fixture",
                fetched_at=app.state.clock.now(clinic),
            )
        )
    app.state.ai_chain = [FixtureAdapter(output(is_health_question=True))]
    turn(client, session(client), "هل دوا الضغط هفضل واخده طول عمري؟")
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(s.action_record.c.text).where(s.action_record.c.kind == "health_no_answer")
            ).scalar_one()
            == "no_key"
        )
        assert conn.execute(select(s.questions.c.count)).scalar_one() == 1
        assert not conn.execute(select(s.health_record)).all()
