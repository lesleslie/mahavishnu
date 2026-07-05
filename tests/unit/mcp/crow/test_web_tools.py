"""Tests for mahavishnu.mcp.crow.tools.web_tools — web_fetch + redirect loop.

RED phase: tests written before implementation.

Critical security: validate_url is called on EVERY redirect hop, including
the initial URL. This closes the DNS-rebinding / open-redirect SSRF gap.
"""

from __future__ import annotations

import httpx
import pytest

from mahavishnu.mcp.crow.tools.web_tools import web_fetch, web_fetch_batch
from tests.unit.mcp.crow.conftest import mock_settings


@pytest.fixture
def mock_http_client(monkeypatch):
    """Replace the shared ``get_http_client`` with a real ``httpx.AsyncClient``
    so respx can intercept calls. respx patches the ``httpx`` package;
    httpx2 is not patched, so for tests we substitute the standard client.
    Also stubs DNS so validate_url() passes for respx-mocked URLs.
    """
    import respx

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        fake = httpx.AsyncClient()
        monkeypatch.setattr("mahavishnu.mcp.crow.tools.web_tools.get_http_client", lambda: fake)
        try:
            yield router
        finally:
            import asyncio

            try:
                asyncio.run(fake.aclose())
            except Exception:
                pass


# ---- happy path -------------------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_returns_raw_content(mock_http_client, tmp_path):
    mock_http_client.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>Hello world</p></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await web_fetch("https://example.com/page", mock_settings(tmp_path), raw=True)
    assert result["url"] == "https://example.com/page"
    assert "Hello world" in result["content"]
    assert result["status_code"] == 200


@pytest.mark.unit
async def test_web_fetch_extracts_text_from_html(mock_http_client, tmp_path):
    """Default (raw=False) returns text content with HTML tags stripped."""
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>Hello <b>world</b></p></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await web_fetch("https://example.com/", mock_settings(tmp_path))
    # Tags stripped, text preserved
    assert "Hello" in result["content"]
    assert "world" in result["content"]
    assert "<p>" not in result["content"]
    assert "<b>" not in result["content"]


@pytest.mark.unit
async def test_web_fetch_returns_truncated_flag(mock_http_client, tmp_path):
    long_text = "x" * 1000
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(200, text=long_text, headers={"content-type": "text/plain"})
    )
    result = await web_fetch(
        "https://example.com/", mock_settings(tmp_path), max_length=100, raw=True
    )
    assert result["truncated"] is True
    assert len(result["content"]) == 100


@pytest.mark.unit
async def test_web_fetch_respects_max_length(mock_http_client, tmp_path):
    text = "abcdef" * 100
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(200, text=text, headers={"content-type": "text/plain"})
    )
    result = await web_fetch(
        "https://example.com/", mock_settings(tmp_path), max_length=10, raw=True
    )
    assert len(result["content"]) == 10


@pytest.mark.unit
async def test_web_fetch_handles_start_index(mock_http_client, tmp_path):
    mock_http_client.get("https://example.com/").mock(
        return_value=httpx.Response(200, text="hello world", headers={"content-type": "text/plain"})
    )
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
async def test_web_fetch_validates_every_redirect_hop(mock_http_client, tmp_path):
    """Public URL -> public URL -> private IP. Must block at the private hop."""

    # First two hops resolve to public, third resolves to private.
    addrs_by_call = iter(
        [
            [(None, None, None, None, ("93.184.216.34", 0))],
            [(None, None, None, None, ("93.184.216.34", 0))],
            [(None, None, None, None, ("10.0.0.1", 0))],  # private — must block
        ]
    )
    monkey_calls = {"i": 0}

    def fake_getaddrinfo(host, *a, **kw):
        monkey_calls["i"] += 1
        return next(addrs_by_call)

    import socket as _s

    _s.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]

    mock_http_client.get("https://a.example/").mock(
        return_value=httpx.Response(302, headers={"location": "https://b.example/"})
    )
    mock_http_client.get("https://b.example/").mock(
        return_value=httpx.Response(302, headers={"location": "http://internal/"})
    )
    with pytest.raises(PermissionError, match="SSRF"):
        await web_fetch("https://a.example/", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_fetch_redirect_chain_within_max_hops(mock_http_client, tmp_path):
    """Chain of N redirects that all resolve to public IPs must succeed."""
    import socket as _socket

    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    # 3-hop chain ending in 200
    mock_http_client.get("https://a.example/").mock(
        return_value=httpx.Response(301, headers={"location": "https://b.example/"})
    )
    mock_http_client.get("https://b.example/").mock(
        return_value=httpx.Response(302, headers={"location": "https://c.example/"})
    )
    mock_http_client.get("https://c.example/").mock(
        return_value=httpx.Response(302, headers={"location": "https://d.example/"})
    )
    mock_http_client.get("https://d.example/").mock(
        return_value=httpx.Response(
            200, text="<html><body>final</body></html>", headers={"content-type": "text/html"}
        )
    )
    result = await web_fetch("https://a.example/", mock_settings(tmp_path), raw=True)
    assert result["status_code"] == 200
    assert "final" in result["content"]


@pytest.mark.unit
async def test_web_fetch_redirect_chain_exceeds_max_hops(mock_http_client, tmp_path):
    """Chain of N+1 redirects must fail with a clear error."""
    import socket as _socket

    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    # Create a redirect loop that exceeds max_redirect_hops=5
    for i in range(7):
        nxt = f"https://r{i + 1}.example/"
        mock_http_client.get(f"https://r{i}.example/").mock(
            return_value=httpx.Response(302, headers={"location": nxt})
        )
    with pytest.raises(RuntimeError, match="redirect"):
        await web_fetch(
            "https://r0.example/",
            mock_settings(tmp_path, max_redirect_hops=3),
        )


@pytest.mark.unit
async def test_web_fetch_redirect_to_relative_url_resolves_against_current(
    mock_http_client, tmp_path
):
    """Relative Location header must resolve against the current URL."""
    import socket as _socket

    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    mock_http_client.get("https://example.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "/b"})
    )
    mock_http_client.get("https://example.com/b").mock(
        return_value=httpx.Response(
            200, text="<html><body>ok</body></html>", headers={"content-type": "text/html"}
        )
    )
    result = await web_fetch("https://example.com/a", mock_settings(tmp_path), raw=True)
    assert result["status_code"] == 200
    assert result["final_url"] == "https://example.com/b"


@pytest.mark.unit
async def test_web_fetch_redirect_to_suspicious_scheme_blocked(mock_http_client, tmp_path):
    """Redirecting to file:// must be blocked at the redirect-validation step."""
    import socket as _socket

    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, ("93.184.216.34", 0))
    ]
    mock_http_client.get("https://a.example/").mock(
        return_value=httpx.Response(302, headers={"location": "file:///etc/passwd"})
    )
    with pytest.raises(ValueError, match="Only http"):
        await web_fetch("https://a.example/", mock_settings(tmp_path))


# ---- batch ------------------------------------------------------------------


@pytest.mark.unit
async def test_web_fetch_batch_partial_failure(mock_http_client, tmp_path):
    """One URL fails, the other succeeds — partial result, no raise."""
    mock_http_client.get("https://bad.example.com").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    mock_http_client.get("https://good.example.com").mock(
        return_value=httpx.Response(
            200,
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    results = await web_fetch_batch(
        ["https://bad.example.com", "https://good.example.com"],
        mock_settings(tmp_path),
        raw=True,
    )
    assert results[0]["error"] is not None
    assert results[1]["status_code"] == 200


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
async def test_web_fetch_reports_duration(mock_http_client, tmp_path):
    mock_http_client.get("https://e.example/").mock(
        return_value=httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
    )
    result = await web_fetch("https://e.example/", mock_settings(tmp_path), raw=True)
    assert result["duration_ms"] >= 0
