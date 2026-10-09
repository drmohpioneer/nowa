"""deterministic origin matching, without a model or HTTP."""

import pytest

from nowa.core import areas


@pytest.mark.parametrize(
    "text,expected",
    [("heliplolis", 1), ("men heliplolis", 1), ("madint nasr", 2), ("el ma3ady", 5)],
)
def test_typo_origins(text, expected):
    assert areas.resolve(text) == expected


@pytest.mark.parametrize("text", ["مدينة", "Maadi or Nasr City", "which areas?", ""])
def test_ambiguous_origins_still_ask(text):
    assert areas.resolve(text) == "unknown"


def test_fuzzy_longest_alias_and_cross_area_tie(monkeypatch):
    monkeypatch.setattr(areas, "AREAS", [("abcde", "abcde", 0, 0), ("abcdx", "abcdx", 0, 0)])
    monkeypatch.setattr(areas, "ALIASES", ("abcde", "abcdx"))
    assert areas.resolve("abcdf") == "unknown"
    assert areas.resolve("abcde") == 1  # An exact hit wins before fuzziness.
    monkeypatch.setattr(areas, "ALIASES", ("abcde|abcdef", "abcdx"))
    assert areas.resolve("abcdeg") == 1


def test_transposition_and_short_alias_threshold():
    assert areas.resolve("Maaid") == 5
    assert areas.resolve("dxki") == 7
    assert areas.resolve("dxxi") is None
    assert areas.resolve("المنصورة") is None
