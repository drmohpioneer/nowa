import logging
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: str
    terms_url: str = ""
    reuse_terms: str = ""
    approved: bool = False
    urls: list[str]


class Sources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specialty: str
    sites: list[Site]


def host_matches(host: str, site: str) -> bool:
    return host.removeprefix("www.") == site.removeprefix("www.")


def validate_url(url: str, site: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not host_matches(parsed.hostname, site)
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError(f"URL outside approved host: {url}")


def read_sources(path: Path, specialty: str) -> Sources:
    sources = Sources.model_validate(yaml.safe_load(path.read_bytes()))
    if sources.specialty != specialty:
        raise ValueError("Sources specialty mismatch")
    approved: list[Site] = []
    for site in sources.sites:
        if site.terms_url:
            validate_url(site.terms_url, site.site)
        for url in site.urls:
            validate_url(url, site.site)
        if not site.approved or not site.terms_url.strip() or not site.reuse_terms.strip():
            logger.warning("Skipping unapproved site or missing reuse terms: %s", site.site)
            continue
        approved.append(site)
    if len({s.site.removeprefix("www.") for s in sources.sites}) != len(sources.sites):
        raise ValueError("Duplicate source host")
    if specialty == "cardiology" and {s.site.removeprefix("www.") for s in sources.sites} != {
        "nhs.uk",
        "medlineplus.gov",
        "nhlbi.nih.gov",
        "cdc.gov",
    }:
        raise ValueError("Cardiology requires the four approved hosts")
    return Sources(specialty=specialty, sites=approved)
