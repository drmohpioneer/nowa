from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import select

from nowa import schema as s

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = {"Origin": "http://127.0.0.1:8000"}


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs["action"], "fields": {}}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and attrs.get("type") == "hidden":
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def fields(response, suffix):
    return next(f["fields"] for f in Forms(response.text).forms if f["action"].endswith(suffix))


def rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table).order_by(*table.primary_key.columns)).mappings().all()


def messages(engine, template):
    return [r for r in rows(engine, s.outbox) if r["template_id"] == template]
