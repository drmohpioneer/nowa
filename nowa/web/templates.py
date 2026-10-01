from pathlib import Path

from jinja2 import Environment, FileSystemLoader

environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True,
)
