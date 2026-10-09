from nowa.web.markdown_lite import render_markdown


def test_supported_blocks_and_plain_unsupported_syntax():
    rendered = str(
        render_markdown(
            "# Title\n\n## Section\n### Topic\n\nA **bold** word.\nNext line.\n\n"
            "- First\n- Second\n\n1. One\n2. Two\n\n#### Plain\n"
            "[link](https://example.test)\n| table |"
        )
    )
    assert "<h1>Title</h1>" in rendered and "<h2>Section</h2>" in rendered
    assert "<h3>Topic</h3>" in rendered and "<strong>bold</strong>" in rendered
    assert "<p>A <strong>bold</strong> word.\nNext line.</p>" in rendered
    assert "<ul>\n<li>First</li>\n<li>Second</li>\n</ul>" in rendered
    assert "<ol>\n<li>One</li>\n<li>Two</li>\n</ol>" in rendered
    assert "#### Plain" in rendered and "[link]" in rendered and "| table |" in rendered
    assert "<a " not in rendered and "<table" not in rendered


def test_source_and_placeholder_html_are_text():
    rendered = str(
        render_markdown('<script>alert("bad")</script>\n\n**<img src=x onerror=bad>** &')
    )
    assert "<script>" not in rendered and "<img" not in rendered
    assert "&lt;script&gt;" in rendered and "&quot;bad&quot;" in rendered
    assert "<strong>&lt;img" in rendered and "&amp;" in rendered
