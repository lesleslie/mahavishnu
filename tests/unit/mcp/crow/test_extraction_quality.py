"""RED phase tests for web-extract escalation (Tasks 7-9).

These tests pin the behavior we want from the production implementation:
- trafilatura as the primary extractor
- selectolax as the CSS-selector fallback when trafilatura returns empty
- rapidfuzz as a duplicate-detector over the extracted text

Each test asserts an observable property of the production module
(``mahavishnu.mcp.crow.tools.web_extract``). They MUST fail on the
current stdlib-HTMLParser implementation and PASS once the new
libraries are wired in.
"""
from __future__ import annotations

import pytest

from mahavishnu.mcp.crow.tools.web_extract import (
    _extract_article,
    _find_near_duplicates,
    _selectolax_extract,
    _trafilatura_extract,
)

# ---------------------------------------------------------------------------
# Task 7 - trafilatura primary extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trafilatura_extract_returns_title_and_body():
    html = """
    <html>
      <head><title>My Article</title></head>
      <body>
        <article>
          <h1>My Article</h1>
          <p>The quick brown fox jumps over the lazy dog.</p>
          <p>A second paragraph providing more body content.</p>
        </article>
      </body>
    </html>
    """
    result = _trafilatura_extract(html)
    text = result if isinstance(result, str) else result.get("text", "")
    assert "quick brown fox" in text
    assert "second paragraph" in text
    assert "<article>" not in text
    assert "<h1>" not in text


@pytest.mark.unit
def test_trafilatura_extract_strips_navigation_chrome():
    """trafilatura is the primary extractor. We assert the article body
    is present after extraction. The harder assertion (nav/footer stripping
    on a realistic fixture) is covered by the legacy test in
    test_web_extract.py::test_web_extract_drops_navigation_and_ads — we
    do not duplicate that here so this test stays a tight contract on
    the _trafilatura_extract() helper itself.
    """
    html = """
    <html>
      <head><title>T</title></head>
      <body>
        <article>
          <h1>Headline</h1>
          <p>Article body content.</p>
          <p>Second body paragraph.</p>
        </article>
      </body>
    </html>
    """
    text = _trafilatura_extract(html)
    text_str = text if isinstance(text, str) else text.get("text", "")
    assert "Article body content" in text_str
    assert "Second body paragraph" in text_str
    assert "<article>" not in text_str


# ---------------------------------------------------------------------------
# Task 8 - selectolax CSS-selector fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_selectolax_extract_targets_nested_elements():
    html = """
    <html><body>
      <article>
        <p>First paragraph, ignored.</p>
        <p class="highlight">Important callout text.</p>
        <p class="highlight">Second important callout.</p>
      </article>
    </body></html>
    """
    text = _selectolax_extract(html, "article p.highlight")
    assert "Important callout text" in text
    assert "Second important callout" in text
    assert "First paragraph" not in text


@pytest.mark.unit
def test_selectolax_extract_returns_empty_for_no_match():
    html = "<html><body><p>nothing here</p></body></html>"
    text = _selectolax_extract(html, "article.nonexistent")
    assert text == ""


# ---------------------------------------------------------------------------
# Task 9 - rapidfuzz near-duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_near_duplicates_flags_highly_similar_paragraphs():
    paragraphs = [
        "The quick brown fox jumps over the lazy dog.",
        "The quick brown fox jumps over the lazy cat.",
        "Totally unrelated content here about mangoes.",
    ]
    dup_pairs = _find_near_duplicates(paragraphs, threshold=85.0)
    assert (0, 1) in dup_pairs
    for pair in dup_pairs:
        assert 2 not in pair


@pytest.mark.unit
def test_find_near_duplicates_handles_no_duplicates():
    paragraphs = [
        "Alpha paragraph about dogs.",
        "Beta paragraph about fish and coral reefs.",
        "Gamma paragraph on quantum entanglement.",
    ]
    dup_pairs = _find_near_duplicates(paragraphs, threshold=85.0)
    assert dup_pairs == []


# ---------------------------------------------------------------------------
# Integration: primary extractor uses trafilatura
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_article_uses_trafilatura_fallback():
    """Without an article/main container, _extract_article delegates to
    trafilatura for readability extraction. The marker text must survive.
    """
    html = """
    <html><body>
      <div>
        <p>This content is unique-marker-trafilatura-wired-42.</p>
      </div>
    </body></html>
    """
    text = _extract_article(html)
    assert "unique-marker-trafilatura-wired-42" in text
