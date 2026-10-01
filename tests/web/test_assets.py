"""Slice 14: self-hosted assets and device-driven colour modes."""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "nowa/web"
FONT_FILES = ["sora-latin-300-700.woff2"] + [
    f"ibm-plex-sans-arabic-{subset}-{weight}.woff2"
    for subset in ("arabic", "latin")
    for weight in (400, 500, 600, 700)
]
EXTERNAL_ASSET = re.compile(
    r'<link\b[^>]*\bhref\s*=\s*[\"\']\s*(?:https?:)?//'
    r'|<(?:script|img)\b[^>]*\bsrc\s*=\s*[\"\']\s*(?:https?:)?//'
    r'|@import\s+(?:url\(\s*)?[\"\']?\s*(?:https?:)?//'
    r'|url\(\s*[\"\']?\s*(?:https?:)?//',
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    "path", sorted(p for p in WEB.rglob("*") if p.suffix in {".html", ".css"})
)
def test_pages_use_only_local_assets(path):
    source = path.read_text()
    assert not EXTERNAL_ASSET.search(source), str(path.relative_to(WEB))
    assert "data-theme" not in source


@pytest.mark.parametrize("name", FONT_FILES)
def test_self_hosted_font_files(name):
    # Google serves Sora's three requested weights in one variable Latin file,
    # and Plex's four weights in eight separate Arabic/Latin files.
    assert (WEB / "static/fonts" / name).read_bytes().startswith(b"wOF2")
    assert name in (WEB / "static/nowa.css").read_text()


def test_fonts_licences_and_modes():
    css = (WEB / "static/nowa.css").read_text()
    for family in ("Sora", "IBM Plex Sans Arabic"):
        assert re.search(r"@font-face\s*\{[^}]*font-family:\s*['\"]" + family, css)
    assert "font-display: swap" in css
    assert "prefers-color-scheme: dark" in css
    assert "#0B1024" in css and "#F4F1EA" in css
    assert "prefers-reduced-motion:reduce" in css
    for licence in ("Sora-OFL.txt", "IBM-Plex-Sans-Arabic-OFL.txt"):
        assert "SIL OPEN FONT LICENSE" in (WEB / "static/fonts" / licence).read_text()


@pytest.mark.parametrize(
    "source",
    [
        '<link href="https://fonts.example/font.css">',
        '<script src="http://scripts.example/a.js"></script>',
        '<img src="https://images.example/a.png">',
        '@import "https://styles.example/a.css";',
        'src: url("https://fonts.example/a.woff2")',
        '<link href="//fonts.example/a.css">',
    ],
)
def test_asset_guard_detects_external_forms(source):
    assert EXTERNAL_ASSET.search(source)


def test_asset_guard_allows_navigation_and_inline_svg():
    assert not EXTERNAL_ASSET.search(
        '<a href="https://maps.example/clinic">Map</a>'
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    )
