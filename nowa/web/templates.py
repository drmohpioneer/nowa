import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from nowa.web import strings
from nowa.web.markdown_lite import render_markdown


def markdown_html(source: str) -> Markup:
    """Trust only HTML produced by the escaping, fixed-subset converter."""
    return Markup(render_markdown(source))


environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True,
)

environment.globals["ui_text"] = lambda key, lang: strings.text("ui." + key, lang)


def isolate_text(value: str) -> Markup:
    parts: list[Markup] = []
    at = 0
    for match in re.finditer(r"https?://[^\s]+|[+A-Za-z0-9][A-Za-z0-9@._:+/ -]*", value):
        parts.extend(
            (
                escape(value[at : match.start()]),
                Markup('<bdi dir="ltr">') + escape(match[0]) + Markup("</bdi>"),
            )
        )
        at = match.end()
    parts.append(escape(value[at:]))
    return Markup("").join(parts)


environment.filters["isolate"] = isolate_text
