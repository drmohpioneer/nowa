import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextPassage:
    section: str
    text: str


def sentences(text: str) -> list[str]:
    # Retain punctuation; do not cut a sentence merely to meet the word limit.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"‘“])", text) if s.strip()]


def split_html(html: str, url: str) -> tuple[str, list[TextPassage]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Untitled"
    root = soup.find("main") or soup.find("article") or soup.body
    if not isinstance(root, Tag):
        raise ValueError("No main text")
    if urlsplit(url).hostname in {"medlineplus.gov", "www.medlineplus.gov"}:
        # Only NLM-authored topic summaries are approved, never linked vendor material.
        summary = root.find(id="topic-summary")
        if not isinstance(summary, Tag):
            raise ValueError("No NLM-authored topic summary")
        root = summary
    for node in root.find_all(
        ["nav", "header", "footer", "aside", "script", "style", "form", "figure"]
    ):
        node.decompose()
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    paragraphs: list[str] = []
    for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        if node.name in {"li", "p"} and node.find_parent("li"):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        if node.name and node.name.startswith("h"):
            if paragraphs:
                sections.append((heading, paragraphs))
            heading, paragraphs = text, []
        elif text:
            kept = []
            for sentence in sentences(text):
                count = len(sentence.split())
                if count > 220:
                    logger.warning(
                        "Dropped long sentence url=%s section=%s words=%d", url, heading, count
                    )
                else:
                    kept.append(sentence)
            if kept:
                paragraphs.append(" ".join(kept))
    if paragraphs:
        sections.append((heading, paragraphs))
    if not sections:
        raise ValueError("No main text")
    # Merge small sections forward (the final one backward), retaining headings.
    index = 0
    while len(sections) > 1 and index < len(sections):
        label, parts = sections[index]
        if len(" ".join(parts).split()) < 60:
            if index + 1 < len(sections):
                next_label, next_parts = sections.pop(index + 1)
                sections[index] = (
                    " / ".join(filter(None, [label, next_label])),
                    parts + next_parts,
                )
            else:
                prev_label, prev_parts = sections[index - 1]
                sections[index - 1] = (
                    " / ".join(filter(None, [prev_label, label])),
                    prev_parts + parts,
                )
                sections.pop(index)
                break
        else:
            index += 1
    result: list[TextPassage] = []
    for label, parts in sections:
        chunks: list[str] = []
        pending = ""
        for part in parts:
            # Paragraph boundaries first; split oversized paragraphs on sentences.
            units = [part] if len(part.split()) <= 220 else sentences(part)
            for unit in units:
                joined = (pending + " " + unit).strip()
                if len(joined.split()) > 220:
                    if len(pending.split()) < 60:
                        # This fragment cannot satisfy both bounds without cutting a sentence.
                        logger.warning(
                            "Dropped short fragment url=%s section=%s words=%d",
                            url,
                            label,
                            len(pending.split()),
                        )
                    else:
                        chunks.append(pending)
                    pending = unit
                else:
                    pending = joined
        if pending:
            if len(pending.split()) >= 60:
                chunks.append(pending)
            elif chunks and len((chunks[-1] + " " + pending).split()) <= 220:
                chunks[-1] += " " + pending
            else:
                logger.warning(
                    "Dropped short fragment url=%s section=%s words=%d",
                    url,
                    label,
                    len(pending.split()),
                )
        result.extend(TextPassage(label, text) for text in chunks)
    if not result:
        raise ValueError("No passages within word bounds")
    return title, result
