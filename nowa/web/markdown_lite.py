"""Small, escaped Markdown display subset, with no links or raw HTML."""

import html
import re


def render_markdown(source: str) -> str:
    """Render headings, paragraphs, bold and flat lists; escape everything first."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None

    def inline(value: str) -> str:
        return re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", value)

    def flush() -> None:
        if paragraph:
            blocks.append("<p>" + "\n".join(paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    for line in html.escape(source, quote=True).splitlines():
        if not line.strip():
            flush()
            close_list()
            continue
        heading = re.fullmatch(r"(#{1,3}) (.+)", line)
        item = re.fullmatch(r"(-|[0-9]+\.) (.+)", line)
        if heading:
            flush()
            close_list()
            level = len(heading[1])
            blocks.append(f"<h{level}>{inline(heading[2])}</h{level}>")
        elif item:
            flush()
            kind = "ul" if item[1] == "-" else "ol"
            if list_kind != kind:
                close_list()
                list_kind = kind
                blocks.append(f"<{kind}>")
            blocks.append("<li>" + inline(item[2]) + "</li>")
        else:
            close_list()
            paragraph.append(inline(line))
    flush()
    close_list()
    return "\n".join(blocks)
