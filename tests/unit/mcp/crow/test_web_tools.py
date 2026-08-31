"""Tests for mahavishnu.mcp.crow.tools.web_tools — web_fetch + redirect loop.

Critical security: validate_url is called on EVERY redirect hop, including
the initial URL. This closes the DNS-rebinding / open-redirect SSRF gap.

Migrated from respx to httpx2.MockTransport. The ``mock_http_client`` fixture
builds a URL → response map and injects an httpx2.AsyncClient whose transport
dispatches based on URL.
"""

from __future__ import annotations

import socket as _socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx2 as httpx
import pytest

from mahavishnu.mcp.crow.tools.web_tools import web_fetch, web_fetch_batch
from tests.unit.mcp.crow.conftest import mock_settings


def _url_router(
    url_to_response: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]],
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that maps request URLs to responses.

    ``url_to_response`` keys are substring-matched against ``str(request.url)``.
    First match wins. Raises ``AssertionError`` if no key matches so test
    authors know their mocks are under-specified.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for needle, response in url_to_response.items():
            if needle in str(request.url):
                if callable(response):
                    return response(request)
                return response
        raise AssertionError(
            f"MockTransport received unexpected request: {request.method} {request.url}"
        )

    return handler


@contextmanager
def _stub_dns(ip: str = "93.184.216.34") -> Iterator[patch]:
    """Stub ``socket.getaddrinfo`` so ``validate_url()`` passes for test URLs."""
    original = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, (ip, 0))
    ]
    try:
        yield patch.object(_socket, "getaddrinfo", _socket.getaddrinfo)
    finally:
        _socket.getaddrinfo = original  # type: ignore[assignment]


@contextmanager
def _mock_http_client(
    url_to_response: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]],
    target_module: str = "mahavishnu.mcp.crow.tools.web_tools",
    dns_ip: str = "93.184.216.34",
    stub_dns: bool = True,
) -> Iterator[None]:
    """Inject an ``httpx2.AsyncClient`` with a URL-routed MockTransport.

    Replaces the ``mock_http_client`` pytest fixture used by these tests
    when they were written against respx.

    Set ``stub_dns=False`` when the test needs to control ``socket.getaddrinfo``
    per-call (e.g., redirect validation that simulates a private-IP hop).
    """
    handler = _url_router(url_to_response)
    transport = httpx.MockTransport(handler)
    fake = httpx.AsyncClient(
        follow_redirects=False, transport=transport
    )

    dns_ctx = _stub_dns(dns_ip) if stub_dns else _nullctx()
    with dns_ctx, patch(
        f"{target_module}.get_http_client", return_value=fake
    ):
        try:
            yield
        finally:
            import asyncio

            try:
                asyncio.run(fake.aclose())
            except Exception:  # noqa: BLE001
                pass


@contextmanager
def _nullctx() -> Iterator[None]:
    yield


# ---- happy path -------------------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_returns_raw_content(tmp_path):
    with _mock_http_client(
        {
            "https://example.com/page": httpx.Response(
                200,
                text="<html><body><p>Hello world</p></body></html>",
                headers={"content-type": "text/html"},
            )
        }
    ):
        result = await web_fetch(
            "https://example.com/page", mock_settings(tmp_path), raw=True
        )
    assert result["url"] == "https://example.com/page"
    assert "Hello world" in result["content"]
    assert result["status_code"] == 200


@pytest.mark.unit
async def test_web_fetch_extracts_text_from_html(tmp_path):
    """Default (raw=False) returns text content with HTML tags stripped."""
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200,
                text="<html><body><p>Hello <b>world</b></p></body></html>",
                headers={"content-type": "text/html"},
            )
        }
    ):
        result = await web_fetch("https://example.com/", mock_settings(tmp_path))
    # Tags stripped, text preserved
    assert "Hello" in result["content"]
    assert "world" in result["content"]
    assert "<p>" not in result["content"]
    assert "<b>" not in result["content"]


@pytest.mark.unit
async def test_web_fetch_returns_truncated_flag(tmp_path):
    long_text = "x" * 1000
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200, text=long_text, headers={"content-type": "text/plain"}
            )
        }
    ):
        result = await web_fetch(
            "https://example.com/", mock_settings(tmp_path), max_length=100, raw=True
        )
    assert result["truncated"] is True
    assert len(result["content"]) == 100


@pytest.mark.unit
async def test_web_fetch_respects_max_length(tmp_path):
    text = "abcdef" * 100
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200, text=text, headers={"content-type": "text/plain"}
            )
        }
    ):
        result = await web_fetch(
            "https://example.com/", mock_settings(tmp_path), max_length=10, raw=True
        )
    assert len(result["content"]) == 10


@pytest.mark.unit
async def test_web_fetch_handles_start_index(tmp_path):
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200, text="hello world", headers={"content-type": "text/plain"}
            )
        }
    ):
        result = await web_fetch(
            "https://example.com/",
            mock_settings(tmp_path),
            start_index=6,
            max_length=5,
            raw=True,
        )
    assert result["content"] == "world"


# ---- security: scheme / SSRF ------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_blocks_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="Only http"):
        await web_fetch("file:///etc/passwd", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_fetch_blocks_ftp_scheme(tmp_path):
    with pytest.raises(ValueError, match="Only http"):
        await web_fetch("ftp://internal/file", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_fetch_blocks_ssrf_to_private_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        await web_fetch("http://internal.corp/", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_fetch_dns_failure_raises_value_error(tmp_path, monkeypatch):
    import socket as _socket

    def _raise(*_a, **_k):
        raise _socket.gaierror("no such host")

    monkeypatch.setattr("socket.getaddrinfo", _raise)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await web_fetch("http://nope.invalid/", mock_settings(tmp_path))


# ---- security: redirect loop ------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_validates_every_redirect_hop(tmp_path):
    """Public URL -> public URL -> private IP. Must block at the private hop."""

    # First two hops resolve to public, third resolves to private.
    addrs_by_call = iter(
        [
            [(None, None, None, None, ("93.184.216.34", 0))],
            [(None, None, None, None, ("93.184.216.34", 0))],
            [(None, None, None, None, ("10.0.0.1", 0))],  # private — must block
        ]
    )

    def fake_getaddrinfo(host, *a, **kw):
        return next(addrs_by_call)

    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]

    try:
        with _mock_http_client(
            {
                "https://a.example/": httpx.Response(
                    302, headers={"location": "https://b.example/"}
                ),
                "https://b.example/": httpx.Response(
                    302, headers={"location": "http://internal/"}
                ),
            },
            stub_dns=False,
        ):
            with pytest.raises(PermissionError, match="SSRF"):
                await web_fetch("https://a.example/", mock_settings(tmp_path))
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


@pytest.mark.unit
async def test_web_fetch_redirect_chain_within_max_hops(tmp_path):
    """Chain of N redirects that all resolve to public IPs must succeed."""
    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    try:
        with _mock_http_client(
            {
                "https://a.example/": httpx.Response(
                    301, headers={"location": "https://b.example/"}
                ),
                "https://b.example/": httpx.Response(
                    302, headers={"location": "https://c.example/"}
                ),
                "https://c.example/": httpx.Response(
                    302, headers={"location": "https://d.example/"}
                ),
                "https://d.example/": httpx.Response(
                    200,
                    text="<html><body>final</body></html>",
                    headers={"content-type": "text/html"},
                ),
            }
        ):
            result = await web_fetch(
                "https://a.example/", mock_settings(tmp_path), raw=True
            )
        assert result["status_code"] == 200
        assert "final" in result["content"]
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


@pytest.mark.unit
async def test_web_fetch_redirect_chain_exceeds_max_hops(tmp_path):
    """Chain of N+1 redirects must fail with a clear error."""
    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    try:
        # Create a redirect loop that exceeds max_redirect_hops=5
        url_to_response: dict[str, httpx.Response] = {}
        for i in range(7):
            nxt = f"https://r{i + 1}.example/"
            url_to_response[f"https://r{i}.example/"] = httpx.Response(
                302, headers={"location": nxt}
            )
        with _mock_http_client(url_to_response):
            with pytest.raises(RuntimeError, match="redirect"):
                await web_fetch(
                    "https://r0.example/",
                    mock_settings(tmp_path, max_redirect_hops=3),
                )
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


@pytest.mark.unit
async def test_web_fetch_redirect_to_relative_url_resolves_against_current(tmp_path):
    """Relative Location header must resolve against the current URL."""
    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    try:
        with _mock_http_client(
            {
                "https://example.com/a": httpx.Response(
                    302, headers={"location": "/b"}
                ),
                "https://example.com/b": httpx.Response(
                    200,
                    text="<html><body>ok</body></html>",
                    headers={"content-type": "text/html"},
                ),
            }
        ):
            result = await web_fetch(
                "https://example.com/a", mock_settings(tmp_path), raw=True
            )
        assert result["status_code"] == 200
        assert result["final_url"] == "https://example.com/b"
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


@pytest.mark.unit
async def test_web_fetch_redirect_to_suspicious_scheme_blocked(tmp_path):
    """Redirecting to file:// must be blocked at the redirect-validation step."""
    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    try:
        with _mock_http_client(
            {
                "https://a.example/": httpx.Response(
                    302, headers={"location": "file:///etc/passwd"}
                ),
            }
        ):
            with pytest.raises(ValueError, match="Only http"):
                await web_fetch("https://a.example/", mock_settings(tmp_path))
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


# ---- batch ------------------------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_batch_partial_failure(tmp_path):
    """One URL fails, the other succeeds — partial result, no raise."""
    original_getaddrinfo = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    try:
        with _mock_http_client(
            {
                "https://good.example.com": httpx.Response(
                    200,
                    text="<html><body>ok</body></html>",
                    headers={"content-type": "text/html"},
                ),
            }
        ):
            results = await web_fetch_batch(
                ["https://bad.example.com", "https://good.example.com"],
                mock_settings(tmp_path),
                raw=True,
            )
        assert results[0]["error"] is not None
        assert results[1]["status_code"] == 200
    finally:
        _socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


@pytest.mark.unit
async def test_web_fetch_batch_rejects_over_limit(tmp_path):
    settings = mock_settings(tmp_path, max_batch_urls=2)
    urls = [f"https://e.com/{i}" for i in range(5)]
    results = await web_fetch_batch(urls, settings, raw=True)
    assert len(results) == 5
    assert all(r["error"] is not None for r in results)
    assert "batch limit" in results[0]["error"]


# ---- duration reporting -----------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_reports_duration(tmp_path):
    with _mock_http_client(
        {
            "https://e.example/": httpx.Response(
                200, text="ok", headers={"content-type": "text/plain"}
            )
        }
    ):
        result = await web_fetch(
            "https://e.example/", mock_settings(tmp_path), raw=True
        )
    assert result["duration_ms"] >= 0
