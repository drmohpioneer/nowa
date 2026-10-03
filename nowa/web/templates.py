from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from nowa.web import strings

environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True,
)

environment.globals["ui_text"] = lambda key, lang: strings.text("ui." + key, lang)
