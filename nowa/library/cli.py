import argparse
import asyncio
import logging
from pathlib import Path

from nowa.config import get_settings
from nowa.db import create_db_engine
from nowa.library.embed import GeminiEmbedder
from nowa.library.ingest import ingest
from nowa.library.recording import record_questions
from nowa.library.store import load


def main(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="nowa library")
    parser.add_argument("command", choices=("ingest", "load", "record"))
    parser.add_argument("specialty")
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(arguments)
    # The specialty is used as a basename, never a caller-controlled filesystem path.
    if not args.specialty.replace("_", "").isalnum():
        parser.error("Invalid specialty")
    if args.command != "load" and args.path is None:
        parser.error("ingest and record require a YAML file")
    if args.allow_missing and args.command != "ingest":
        parser.error("--allow-missing requires ingest")
    logging.basicConfig(level=logging.INFO)
    try:
        if args.command == "ingest":
            asyncio.run(
                ingest(
                    args.specialty,
                    args.path,
                    get_settings().library_data_dir / f"{args.specialty}.jsonl",
                    GeminiEmbedder(),
                    allow_missing=args.allow_missing,
                )
            )
        else:
            engine = create_db_engine()
            try:
                if args.command == "load":
                    load(engine, args.specialty)
                else:
                    asyncio.run(record_questions(engine, args.specialty, args.path))
            finally:
                engine.dispose()
    except ValueError as exc:
        parser.error(str(exc))
