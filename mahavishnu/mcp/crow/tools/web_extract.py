"""Web extract tools for the Bodai crow HTTP MCP server.

ESCALATION: The plan calls for ``trafilatura`` for content extraction.
``trafilatura`` is not in the current dependency tree, so this
implementation uses a stdlib-based extractor that strips tags, drops
navigation/footer/aside blocks, and returns visible text. The function
signature mirrors a trafilatura-backed version so it can be swapped in
once the dep is added (Task 10).

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


class _ArticleExtractor(HTMLParser):
    """Minimal article extractor.

    Drops the contents of any element in ``_DROP_TAGS``. When we enter a
    tag in ``_SKIP_REGIONS`` we set a flag and skip text until the
    matching close. When we enter a block tag, we append a newline so
    the output keeps paragraph structure.
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


_WS_RE = re.compile(r"[ \t\f\v]+")
_NL_RE = re.compile(r"\n{2,}")


def _extract_article(html: str) -> str:
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


__all__ = ["web_extract", "web_extract_batch", "ExtractResult"]