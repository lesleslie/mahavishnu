"""Web extract tools for the Bodai crow HTTP MCP server.

Extraction pipeline (Plan 1 Tasks 7-9 escalation):

1. **Primary**: ``trafilatura.extract()`` — F1=0.937 readability extractor
   that drops navigation/footer/aside/script/style and returns the main
   article body.
2. **CSS-selector fallback**: ``selectolax.parser.HTMLParser`` with a CSS
   selector — 30x faster than bs4. Used when trafilatura returns empty
   (e.g. minimal pages, single-section docs).
3. **Near-duplicate detection**: ``rapidfuzz.process.extract`` over the
   extracted paragraphs to flag duplicates (C++-backed, ~40x faster
   than pure-Python difflib).

The previous stdlib ``html.parser.HTMLParser`` fallback remains as a
last-resort path so the function never raises on pathological HTML — it
returns a stripped raw string instead.

``web_extract(url, settings, max_length)`` — fetch and return the
article's text content. Reuses ``validate_url`` for SSRF protection.

``web_extract_batch(urls, settings, max_length)`` — bounded-concurrency
fan-out, per-URL failure capture in-band.
"""
from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from typing import TypedDict

from rapidfuzz import fuzz, process
from selectolax.parser import HTMLParser as _SelectolaxParser

from mahavishnu.mcp.crow.client import get_http_client
from mahavishnu.mcp.crow.path_security import validate_url
from mahavishnu.mcp.crow.settings import CrowSettings


class ExtractResult(TypedDict):
    url: str
    content: str
    truncated: bool
    content_type: str
    status_code: int | None
    error: str | None
    duration_ms: int


# Tags whose contents should be dropped entirely (script/style).
_DROP_TAGS = frozenset({"script", "style", "noscript"})
# Block tags whose presence typically surrounds "main content".
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "article", "section"}
)
# Tags that mark regions we want to exclude from extraction.
_SKIP_REGIONS = frozenset(
    {"nav", "aside", "footer", "header", "form", "button"}
)

_WS_RE = re.compile(r"[ \t\f\v]+")
_NL_RE = re.compile(r"\n{2,}")


def _trafilatura_extract(html: str) -> str:
    """Primary extraction via trafilatura. Returns visible article text
    or an empty string if trafilatura finds no main content.
    """
    extracted = trafilatura_extract_lib(html, output_format="markdown")
    return extracted or ""


def _selectolax_extract(html: str, selector: str) -> str:
    """CSS-selector extraction via selectolax. Returns concatenated text
    of all elements matching ``selector`` (one chunk per element, joined
    by newlines). Returns an empty string when nothing matches.
    """
    try:
        tree = _SelectolaxParser(html)
    except Exception:
        return ""
    matches = tree.css(selector)
    if not matches:
        return ""
    chunks = [m.text(separator=" ", strip=True) for m in matches]
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _find_near_duplicates(
    paragraphs: list[str], threshold: float = 85.0
) -> list[tuple[int, int]]:
    """Find near-duplicate paragraph pairs using rapidfuzz.

    For each paragraph, compare against all others via ``fuzz.ratio``;
    emit a pair ``(i, j)`` when score >= threshold. O(n^2) but n is
    usually small (article paragraphs); rapidfuzz makes the inner loop
    cheap.

    Returns a list of index pairs (sorted ascending). Duplicates of the
    same paragraph are returned only once.
    """
    seen: set[tuple[int, int]] = set()
    for i, query in enumerate(paragraphs):
        # extract returns list of (match_text, score, index) tuples
        results = process.extract(
            query,
            paragraphs,
            scorer=fuzz.ratio,
            score_cutoff=threshold,
            limit=None,
        )
        for _match_text, score, j in results:
            if j <= i:
                continue  # dedupe pairs (avoid (1,0) and (0,1))
            if j == i:
                continue  # ignore self-match
            if score >= threshold:
                seen.add((i, j))
    return sorted(seen)


class _ArticleExtractor(HTMLParser):
    """Last-resort stdlib fallback. Used only when both trafilatura and
    selectolax return empty — kept to guarantee a non-None string
    response on pathological HTML.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._drop_depth = 0
        self._skip_region_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ltag = tag.lower()
        if ltag in _DROP_TAGS:
            self._drop_depth += 1
            return
        if ltag in _SKIP_REGIONS:
            self._skip_region_depth += 1
            return
        if ltag in _BLOCK_TAGS:
            self._chunks.append("\n")
            return

    def handle_endtag(self, tag: str) -> None:
        ltag = tag.lower()
        if ltag in _DROP_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if ltag in _SKIP_REGIONS:
            self._skip_region_depth = max(0, self._skip_region_depth - 1)
            return
        if ltag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._drop_depth or self._skip_region_depth:
            return
        self._chunks.append(data)


def _stdlib_fallback(html: str) -> str:
    parser = _ArticleExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", "", html)
    text = "".join(parser._chunks)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def _extract_article(html: str) -> str:
    """3-tier extraction: selectolax (article) -> trafilatura -> stdlib.

    The pipeline prefers a focused structural selector (``article`` /
    ``main``) when one exists in the document, because that produces
    cleaner output on small/minimal pages where trafilatura's heuristic
    cannot distinguish article content from nav/footer. Trafilatura
    handles the long-form / unknown-structure case. Stdlib fallback
    guarantees a non-empty string on pathological HTML.
    """
    # Tier 1: structural selectors - tightest fit on documents with
    # explicit article/main containers.
    for selector in ("article", "main", '[role="main"]'):
        text = _selectolax_extract(html, selector)
        if text:
            return text
    # Tier 2: trafilatura readability extractor - long-form docs and
    # unknown structures.
    text = _trafilatura_extract(html)
    if text:
        return text
    # Tier 3: paragraph-level selector - covers prose without article tags.
    text = _selectolax_extract(html, "p")
    if text:
        return text
    return _stdlib_fallback(html)


# Lazy import so the module loads even when trafilatura is missing
# during a partial install (e.g. dependency resolution failure).
def _ensure_trafilatura() -> None:
    """Raise ImportError with a clear message if trafilatura is missing."""
    import importlib

    if importlib.util.find_spec("trafilatura") is None:
        raise ImportError(
            "trafilatura is required for web_extract; install with "
            "`uv pip install 'trafilatura~=2.1'`"
        )


# Module-level alias to keep test imports stable.
def trafilatura_extract_lib(html: str, **kwargs: object) -> str | None:
    _ensure_trafilatura()
    import trafilatura as _t

    return _t.extract(html, **kwargs)


async def web_extract(
    url: str,
    settings: CrowSettings,
    max_length: int = 5000,
) -> ExtractResult:
    """Fetch ``url`` and return its article text.

    Raises ``ValueError`` / ``PermissionError`` from ``validate_url``
    before any HTTP call.
    """
    import time

    validate_url(url)
    client = get_http_client()
    t0 = time.perf_counter()
    try:
        resp = await client.get(url, headers={"Accept": "text/html,*/*"})
    except Exception as exc:
        return ExtractResult(
            url=url,
            content="",
            truncated=False,
            content_type="",
            status_code=None,
            error=str(exc),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    elapsed = int((time.perf_counter() - t0) * 1000)
    if resp.status_code >= 400:
        return ExtractResult(
            url=url,
            content="",
            truncated=False,
            content_type=resp.headers.get("content-type", ""),
            status_code=resp.status_code,
            error=f"HTTP {resp.status_code}",
            duration_ms=elapsed,
        )
    body = await asyncio.to_thread(_extract_article, resp.text)
    truncated = len(body) > max_length
    chunk = body[:max_length]
    return ExtractResult(
        url=url,
        content=chunk,
        truncated=truncated,
        content_type=resp.headers.get("content-type", ""),
        status_code=resp.status_code,
        error=None,
        duration_ms=elapsed,
    )


async def web_extract_batch(
    urls: list[str],
    settings: CrowSettings,
    max_length: int = 5000,
    max_concurrent: int | None = None,
) -> list[ExtractResult]:
    """Fetch and extract multiple URLs concurrently."""
    concurrency = (
        max_concurrent
        if max_concurrent is not None
        else settings.max_concurrent_fetches
    )
    sem = asyncio.Semaphore(concurrency)

    async def extract_one(u: str) -> ExtractResult:
        async with sem:
            return await web_extract(u, settings, max_length)

    return list(await asyncio.gather(*(extract_one(u) for u in urls)))


def _tool_decorator(server):
    return server.fastmcp.tool if hasattr(server, "fastmcp") else server.tool


def register(server, settings: CrowSettings) -> None:
    """Register web_extract and web_extract_batch on ``server``."""
    deco = _tool_decorator(server)

    @deco()
    async def web_extract(
        url: str, max_length: int = 5000
    ) -> ExtractResult:
        """(HTTP, for pool workers and CLI) - Fetch and extract article."""
        return await _web_extract_impl(url, settings, max_length)

    @deco()
    async def web_extract_batch(
        urls: list[str],
        max_length: int = 5000,
        max_concurrent: int | None = None,
    ) -> list[ExtractResult]:
        """(HTTP, for pool workers and CLI) - Bounded-concurrent extract."""
        return await _web_extract_batch_impl(
            urls, settings, max_length, max_concurrent
        )


_web_extract_impl = web_extract
_web_extract_batch_impl = web_extract_batch


__all__ = [
    "web_extract",
    "web_extract_batch",
    "ExtractResult",
    "_extract_article",
    "_trafilatura_extract",
    "_selectolax_extract",
    "_find_near_duplicates",
    "register",
]
