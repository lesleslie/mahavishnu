"""Tests for mahavishnu.mcp.crow.tools.web_extract.

RED phase: tests written before implementation.

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
"""

from __future__ import annotations

import httpx
import pytest

from mahavishnu.mcp.crow.tools.web_extract import web_extract
from tests.unit.mcp.crow.conftest import mock_settings


@pytest.fixture
def mock_http_client(monkeypatch):
    """Replace ``get_http_client`` with a real httpx client that respx can
    intercept. Also stubs DNS so validate_url() passes for respx-mocked URLs.
    """
    import respx

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        fake = httpx.AsyncClient()
        monkeypatch.setattr(
            "mahavishnu.mcp.crow.tools.web_extract.get_http_client",
            lambda: fake,
        )
        try:
            yield router
        finally:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.run(fake.aclose())
                else:
                    loop.run_until_complete(fake.aclose())
            except Exception:
                pass


# ---- happy path -------------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_returns_text_from_html(mock_http_client, tmp_path):
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><article><h1>Title</h1>"
            "<p>This is the main content of the page.</p>"
            "</article></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await web_extract("https://example.com/", mock_settings(tmp_path))
    assert result["url"] == "https://example.com/"
    assert "Title" in result["content"]
    assert "main content" in result["content"]
    assert "<h1>" not in result["content"]
    assert "<p>" not in result["content"]


@pytest.mark.unit
async def test_web_extract_drops_navigation_and_ads(mock_http_client, tmp_path):
    """nav, aside, footer, header, script, style are stripped to content."""
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(
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
    )
    result = await web_extract("https://example.com/", mock_settings(tmp_path))
    assert "Real article content" in result["content"]
    assert "Skip to content" not in result["content"]
    assert "analytics()" not in result["content"]
    assert "Sidebar ads" not in result["content"]
    assert "Footer junk" not in result["content"]


@pytest.mark.unit
async def test_web_extract_max_length_truncates(mock_http_client, tmp_path):
    text = "<html><body><p>" + ("long content " * 100) + "</p></body></html>"
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(200, text=text, headers={"content-type": "text/html"})
    )
    result = await web_extract("https://example.com/", mock_settings(tmp_path), max_length=50)
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
    import socket as _socket

    def _raise(*_a, **_k):
        raise _socket.gaierror("no such host")

    monkeypatch.setattr("socket.getaddrinfo", _raise)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await web_extract("http://nope.invalid/", mock_settings(tmp_path))


# ---- error reporting --------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_returns_error_on_404(mock_http_client, tmp_path):
    mock_http_client.get("https://e.example/").mock(
        return_value=httpx.Response(404, text="<html><body>Not found</body></html>")
    )
    result = await web_extract("https://e.example/", mock_settings(tmp_path))
    assert result["error"] is not None
    assert "404" in result["error"]
    assert result["content"] == ""


@pytest.mark.unit
async def test_web_extract_returns_error_on_timeout(mock_http_client, tmp_path):
    mock_http_client.get("https://e.example/").mock(side_effect=httpx.TimeoutException("timeout"))
    result = await web_extract("https://e.example/", mock_settings(tmp_path))
    assert result["error"] is not None
    assert result["content"] == ""


# ---- batch ------------------------------------------------------------------


@pytest.mark.unit
async def test_web_extract_batch_returns_list(mock_http_client, tmp_path):
    mock_http_client.get("https://a.example/").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>A</p></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    mock_http_client.get("https://b.example/").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>B</p></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    results = await __import__(
        "mahavishnu.mcp.crow.tools.web_extract",
        fromlist=["web_extract_batch"],
    ).web_extract_batch(["https://a.example/", "https://b.example/"], mock_settings(tmp_path))
    assert len(results) == 2
    assert "A" in results[0]["content"]
    assert "B" in results[1]["content"]
