"""Web fetch tools for the Bodai crow HTTP MCP server.

- ``web_fetch(url, settings, max_length, start_index, raw)`` — fetch a URL
  with **manual** redirect following. The shared httpx2 client is
  configured with ``follow_redirects=False``; on each 3xx response we
  call ``validate_url`` on the *new* URL before issuing the next request.
  This closes the DNS-rebinding / open-redirect SSRF gap.
- ``web_fetch_batch(urls, settings, max_length, max_concurrent)`` —
  bounded-concurrency fan-out. Per-URL failures are captured in-band
  (returned as ``{"error": ...}``) so one timeout does not abort the
  whole batch.

Text extraction: the plan calls for trafilatura + selectolax. Neither is
yet in the dependency tree (escalation deferred to Task 10). For now,
HTML tag-stripping is performed via the stdlib ``html.parser`` so the
default (raw=False) path returns readable text. The ``raw=True`` flag
returns the response body verbatim, which is the SSRF-safe path that
needs no parser.
"""
from __future__ import annotations

import asyncio
import re
import time
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import urljoin

from mahavishnu.mcp.crow.client import get_http_client
from mahavishnu.mcp.crow.path_security import validate_url
from mahavishnu.mcp.crow.settings import CrowSettings


class WebFetchResult(TypedDict):
    url: str
    final_url: str
    status_code: int
    content: str
    truncated: bool
    content_type: str
    duration_ms: int


class BatchItem(TypedDict):
    url: str
    final_url: str | None
    status_code: int | None
    content: str | None
    truncated: bool
    error: str | None
    duration_ms: int


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class _TextExtractor(HTMLParser):
    """Collect visible text from HTML, collapsing whitespace.

    This is intentionally minimal — it strips tags, decodes common
    entities, and joins the text nodes. It is *not* a full readability
    algorithm; that role is delegated to trafilatura when the dep is
    installed (Task 10).
    """

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(data)


_WS_RE = re.compile(r"[ \t\f\v]+")
_NL_RE = re.compile(r"\n{2,}")


def _extract_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Best-effort: fall back to a stripped raw string.
        return re.sub(r"<[^>]+>", "", html)
    text = "".join(parser._chunks)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


async def web_fetch(
    url: str,
    settings: CrowSettings,
    max_length: int = 5000,
    start_index: int = 0,
    raw: bool = False,
) -> WebFetchResult:
    """Fetch ``url`` with manual redirect validation.

    Raises:
        ValueError: scheme is not http/https, DNS resolution fails.
        PermissionError: any hop resolves to a private/reserved address.
        RuntimeError: redirect chain exceeds ``settings.max_redirect_hops``.
    """
    # Validate the initial URL BEFORE acquiring the client so DNS-failure
    # and SSRF errors short-circuit without ever issuing a request.
    validate_url(url)
    client = get_http_client()
    t0 = time.perf_counter()
    current_url = url
    resp = None
    hops = 0
    while True:
        resp = await client.get(current_url, headers={"Accept": "text/html,*/*"})
        if (
            resp.status_code in _REDIRECT_STATUSES
            and hops < settings.max_redirect_hops
        ):
            location = resp.headers.get("location", "")
            if not location:
                break
            current_url = urljoin(current_url, location)
            validate_url(current_url)  # CRITICAL: re-validate every hop
            hops += 1
            continue
        if (
            resp.status_code in _REDIRECT_STATUSES
            and hops >= settings.max_redirect_hops
        ):
            raise RuntimeError(
                f"redirect chain exceeded max_redirect_hops={settings.max_redirect_hops}"
            )
        break
    elapsed = int((time.perf_counter() - t0) * 1000)
    content_type = resp.headers.get("content-type", "")
    if raw:
        body = resp.text
    else:
        body = await asyncio.to_thread(_extract_text, resp.text)
    chunk = body[start_index : start_index + max_length]
    return WebFetchResult(
        url=url,
        final_url=current_url,
        status_code=resp.status_code,
        content=chunk,
        truncated=len(body) > start_index + max_length,
        content_type=content_type,
        duration_ms=elapsed,
    )


async def web_fetch_batch(
    urls: list[str],
    settings: CrowSettings,
    max_length: int = 5000,
    max_concurrent: int | None = None,
    raw: bool = False,
) -> list[BatchItem]:
    """Fetch multiple URLs concurrently. Per-URL failures are returned in-band."""
    if len(urls) > settings.max_batch_urls:
        err = f"batch limit is {settings.max_batch_urls} URLs"
        return [
            BatchItem(
                url=u,
                final_url=None,
                status_code=None,
                content=None,
                truncated=False,
                error=err,
                duration_ms=0,
            )
            for u in urls
        ]
    concurrency = (
        max_concurrent if max_concurrent is not None else settings.max_concurrent_fetches
    )
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(u: str) -> BatchItem:
        async with sem:
            try:
                result = await web_fetch(u, settings, max_length=max_length, raw=raw)
                return BatchItem(
                    url=u,
                    final_url=result["final_url"],
                    status_code=result["status_code"],
                    content=result["content"],
                    truncated=result["truncated"],
                    error=None,
                    duration_ms=result["duration_ms"],
                )
            except Exception as exc:
                return BatchItem(
                    url=u,
                    final_url=None,
                    status_code=None,
                    content=None,
                    truncated=False,
                    error=str(exc),
                    duration_ms=0,
                )

    return list(await asyncio.gather(*(fetch_one(u) for u in urls)))


__all__ = ["web_fetch", "web_fetch_batch", "WebFetchResult", "BatchItem"]