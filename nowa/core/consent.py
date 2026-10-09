"""Policy-only consent text, separate from the transitional chat sentences."""

import hashlib
import re
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "docs/reference/patient-consent.md"


def policy_text(lang: str) -> tuple[str, str, str]:
    if lang not in {"ar", "en", "franco"}:
        raise ValueError("Unsupported policy language")
    source = POLICY_PATH.read_text(encoding="utf-8")
    version = re.search(r"^Version:\s*(\S+)", source, re.MULTILINE)
    section = re.search(rf"<!-- policy:{lang} -->\s*(.*?)\s*<!-- /policy -->", source, re.DOTALL)
    if version is None or section is None:
        raise ValueError("Policy version or language section is missing")
    text = section[1]
    return version[1], hashlib.sha256(text.encode()).hexdigest(), text
