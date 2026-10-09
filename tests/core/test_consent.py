import hashlib

import pytest

from nowa.core import consent


@pytest.mark.parametrize("lang", ["ar", "en", "franco"])
def test_policy_exact_language_hash_without_legacy_chat_text(lang):
    version, hashed, text = consent.policy_text(lang)
    assert version == "0.2"
    assert hashed == hashlib.sha256(text.encode()).hexdigest()
    assert "30" in text and "90" in text
    assert (
        "Health information from the NHS website, licensed under the Open Government Licence v3.0"
        in text
    )
    assert "MedlinePlus" in text
    assert "{privacy_link}" not in text and "<!--" not in text
    source = consent.POLICY_PATH.read_text()
    assert "## Self" not in source and "## Booking for someone else" not in source
    assert "## Button label" not in source and "{privacy_link}" not in source


def test_policy_invalid_language_and_missing_section(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="language"):
        consent.policy_text("xx")
    source = tmp_path / "policy.md"
    source.write_text("Version: 0.2\n<!-- policy:ar -->text<!-- /policy -->")
    monkeypatch.setattr(consent, "POLICY_PATH", source)
    with pytest.raises(ValueError, match="missing"):
        consent.policy_text("en")
