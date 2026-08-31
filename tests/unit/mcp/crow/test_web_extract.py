"""Tests for mahavishnu.mcp.crow.tools.web_extract.

ESCALATION: trafilatura is not in the dep tree. This implementation
uses a stdlib HTMLParser-based extractor that strips tags and returns
text. The function signature mirrors what a trafilatura-backed version
would expose so it can be swapped in once trafilatura is added.

The test suite focuses on:
- Happy path (HTML → text)
- SSRF guard (reuses validate_url — same security invariants)
- Extraction quality (text stripped of tags, whitespace collapsed)
- Max-length truncation
- Failure isolation (network errors return structured error, not raise)

Migrated from respx to httpx2.MockTransport via ``tests.unit.mcp.crow._http_mock``.
"""

from __future__ import annotations

import socket as _socket

import httpx2 as httpx
import pytest

from mahavishnu.mcp.crow.tools.web_extract import web_extract, web_extract_batch
from tests.unit.mcp.crow._http_mock import _mock_http_client
from tests.unit.mcp.crow.conftest import mock_settings

_TARGET = "mahavishnu.mcp.crow.tools.web_extract"


# ---- happy path -------------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_returns_text_from_html(tmp_path):
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200,
                text=(
                    "<html><body><article><h1>Title</h1>"
                    "<p>This is the main content of the page.</p>"
                    "</article></body></html>"
                ),
                headers={"content-type": "text/html"},
            )
        },
        target_module=_TARGET,
    ):
        result = await web_extract("https://example.com/", mock_settings(tmp_path))
    assert result["url"] == "https://example.com/"
    assert "Title" in result["content"]
    assert "main content" in result["content"]
    assert "<h1>" not in result["content"]
    assert "<p>" not in result["content"]


@pytest.mark.unit
async def test_web_extract_drops_navigation_and_ads(tmp_path):
    """nav, aside, footer, header, script, style are stripped to content."""
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200,
                text=(
                    "<html><body>"
                    "<nav>Skip to content</nav>"
                    "<script>analytics()</script>"
                    "<article><p>Real article content</p></article>"
                    "<aside>Sidebar ads</aside>"
                    "<footer>Footer junk</footer>"
                    "</body></html>"
                ),
                headers={"content-type": "text/html"},
            )
        },
        target_module=_TARGET,
    ):
        result = await web_extract("https://example.com/", mock_settings(tmp_path))
    assert "Real article content" in result["content"]
    assert "Skip to content" not in result["content"]
    assert "analytics()" not in result["content"]
    assert "Sidebar ads" not in result["content"]
    assert "Footer junk" not in result["content"]


@pytest.mark.unit
async def test_web_extract_max_length_truncates(tmp_path):
    text = "<html><body><p>" + ("long content " * 100) + "</p></body></html>"
    with _mock_http_client(
        {
            "https://example.com/": httpx.Response(
                200, text=text, headers={"content-type": "text/html"}
            )
        },
        target_module=_TARGET,
    ):
        result = await web_extract(
            "https://example.com/", mock_settings(tmp_path), max_length=50
        )
    assert len(result["content"]) <= 50
    assert result["truncated"] is True


# ---- security ---------------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_blocks_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="Only http"):
        await web_extract("file:///etc/passwd", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_extract_blocks_ssrf(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("10.0.0.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        await web_extract("http://internal/", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_extract_dns_failure_raises_value_error(tmp_path, monkeypatch):
    def _raise(*_a, **_k):
        raise _socket.gaierror("no such host")

    monkeypatch.setattr("socket.getaddrinfo", _raise)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await web_extract("http://nope.invalid/", mock_settings(tmp_path))


# ---- error reporting --------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_returns_error_on_404(tmp_path):
    with _mock_http_client(
        {
            "https://e.example/": httpx.Response(
                404, text="<html><body>Not found</body></html>"
            )
        },
        target_module=_TARGET,
    ):
        result = await web_extract("https://e.example/", mock_settings(tmp_path))
    assert result["error"] is not None
    assert "404" in result["error"]
    assert result["content"] == ""


@pytest.mark.unit
async def test_web_extract_returns_error_on_timeout(tmp_path):
    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with _mock_http_client(
        {"https://e.example/": fail_handler},  # type: ignore[dict-item]
        target_module=_TARGET,
    ):
        result = await web_extract("https://e.example/", mock_settings(tmp_path))
    assert result["error"] is not None
    assert result["content"] == ""


# ---- batch ------------------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_batch_returns_list(tmp_path):
    with _mock_http_client(
        {
            "https://a.example/": httpx.Response(
                200,
                text="<html><body><p>A</p></body></html>",
                headers={"content-type": "text/html"},
            ),
            "https://b.example/": httpx.Response(
                200,
                text="<html><body><p>B</p></body></html>",
                headers={"content-type": "text/html"},
            ),
        },
        target_module=_TARGET,
    ):
        results = await web_extract_batch(
            ["https://a.example/", "https://b.example/"], mock_settings(tmp_path)
        )
    assert len(results) == 2
    assert "A" in results[0]["content"]
    assert "B" in results[1]["content"]
