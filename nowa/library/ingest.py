import hashlib
import logging
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from nowa.clock import SystemClock
from nowa.library.embed import Embedder
from nowa.library.models import Header, Passage, atomic_write, encode_data, read_data, stable_key
from nowa.library.sources import Site, read_sources, validate_url
from nowa.library.split import split_html

logger = logging.getLogger(__name__)
USER_AGENT = "NowaLibrary/1.0"


async def fetch(
    client: httpx.AsyncClient, url: str, site: Site, robots: RobotFileParser | None = None
) -> httpx.Response:
    current = url
    for hop in range(4):
        validate_url(current, site.site)
        if robots is not None and not robots.can_fetch(USER_AGENT, current):
            raise ValueError("robots.txt disallows URL")
        response = await client.get(current, follow_redirects=False)
        if response.status_code in (301, 302, 307, 308):
            if hop == 3 or not response.headers.get("location"):
                raise ValueError(f"Redirect limit or missing location: {url}")
            current = urljoin(current, response.headers["location"])
            # Validate before any request to a redirected host.
            validate_url(current, site.site)
            continue
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {url}")
        return response
    raise ValueError(f"Redirect limit: {url}")


async def ingest(
    specialty: str,
    sources_path: Path,
    output: Path,
    embedder: Embedder,
    *,
    allow_missing: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    sources = read_sources(sources_path, specialty)
    previous = read_data(output)[1] if output.exists() else []
    failed: list[str] = []
    rows: list[Passage] = []
    owned = client is None
    client = client or httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT})
    try:
        for site in sources.sites:
            try:
                # Read policy at the publisher's final host. Some bare hosts redirect
                # /robots.txt to their homepage, which is not a robots policy.
                terms_response = await fetch(client, site.terms_url, site)
                final_host = urlsplit(str(terms_response.url)).netloc
                robots_response = await fetch(client, f"https://{final_host}/robots.txt", site)
                if urlsplit(str(robots_response.url)).path != "/robots.txt":
                    raise ValueError("robots.txt redirected to a non-policy page")
                robots = RobotFileParser(str(robots_response.url))
                robots.parse(robots_response.text.splitlines())
            except Exception as exc:
                logger.error(
                    "Source verification failed site=%s error=%s", site.site, type(exc).__name__
                )
                failed.extend(site.urls)
                continue
            for url in site.urls:
                try:
                    canonical = urlsplit(url)._replace(
                        netloc=urlsplit(str(robots_response.url)).netloc
                    )
                    if not robots.can_fetch(USER_AGENT, canonical.geturl()):
                        raise ValueError("robots.txt disallows URL")
                    response = await fetch(client, url, site, robots)
                    if not robots.can_fetch(USER_AGENT, str(response.url)):
                        raise ValueError("robots.txt disallows final URL")
                    title, parts = split_html(response.text, url)
                    fetched_at = SystemClock().now(0)
                    vectors = await embedder.embed(
                        [f"{title} > {part.section}\n{part.text}" for part in parts],
                        "RETRIEVAL_DOCUMENT",
                    )
                    if len(vectors) != len(parts):
                        raise ValueError("Embedding count mismatch")
                    rows.extend(
                        Passage(
                            passage_key=stable_key(url, part.section, part.text),
                            specialty=specialty,
                            site=site.site,
                            source_url=url,
                            title=title + " > " + part.section,
                            text=part.text,
                            embedding=vector,
                            embedding_model=embedder.model,
                            fetched_at=fetched_at,
                        )
                        for part, vector in zip(parts, vectors, strict=True)
                    )
                except Exception as exc:
                    logger.error("Ingestion failed url=%s error=%s", url, type(exc).__name__)
                    failed.append(url)
        if failed and not allow_missing:
            raise ValueError("Failed URLs: " + ", ".join(failed))
        if failed:
            logger.warning("Skipped URLs: %s", ", ".join(failed))
            carried = [p for p in previous if p.source_url in failed]
            if any(p.embedding_model != embedder.model for p in carried):
                raise ValueError("Carried embedding model mismatch")
            rows.extend(carried)
        rows = list({p.passage_key: p for p in rows}.values())
        header = Header(
            specialty=specialty,
            ingested_at=SystemClock().now(0),
            sources_sha256=hashlib.sha256(sources_path.read_bytes()).hexdigest(),
            embedding_model=embedder.model,
            count=len(rows),
        )
        atomic_write(output, encode_data(header, rows))
        return failed
    finally:
        if owned:
            await client.aclose()
