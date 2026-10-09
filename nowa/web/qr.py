"""The shared, local SVG maker for posters and Telegram links."""

import io

import segno


def svg_for(url: str) -> bytes:
    svg = io.BytesIO()
    segno.make(url, micro=False).save(
        svg,
        kind="svg",
        scale=8,
        border=2,
        light="#ffffff",
        dark="#000000",
        xmldecl=True,
        svgns=True,
    )
    return svg.getvalue()
