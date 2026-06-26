"""Shared httpx2 client singleton for the Bodai crow HTTP server.

A single ``httpx2.AsyncClient`` is created at server startup and closed
on shutdown. ``follow_redirects=False`` is mandatory — the server validates
redirect targets through ``validate_url()`` manually so DNS-rebinding /
open-redirect SSRF attempts are blocked hop-by-hop.
"""
from __future__ import annotations

import httpx2

from mahavishnu.mcp.crow.settings import CrowSettings

_http_client: httpx2.AsyncClient | None = None


async def init_http_client(settings: CrowSettings) -> None:
    """Create the shared httpx2 client with SSRF-safe defaults."""
    global _http_client
    _http_client = httpx2.AsyncClient(
        http2=True,
        follow_redirects=False,
        timeout=httpx2.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
    )


async def close_http_client() -> None:
    """Close and clear the shared client. Idempotent."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def get_http_client() -> httpx2.AsyncClient:
    """Return the shared client. Raises if init has not run."""
    if _http_client is None:
        raise RuntimeError(
            "HTTP client not initialized — call init_http_client first"
        )
    return _http_client