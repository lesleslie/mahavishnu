"""Integration smoke test for ``mcp_common.clients.common_mcp_client.CommonMCPClient``.

Mahavishnu is a consumer of the unified Bodai MCP transport; this smoke
verifies that:

* ``CommonMCPClient`` instantiates against a real base URL without
  raising (SSRF guard accepts http/https).
* The ``tools_url`` property mirrors ``base_url`` per the Phase 3
  streamable-HTTP contract.
* ``aclose()`` is idempotent — calling it twice is a no-op.

This is intentionally minimal. End-to-end exercises live in the
``test_cross_repo_smoke`` file in this directory.
"""

from __future__ import annotations

import pytest


def test_common_mcp_client_importable() -> None:
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    assert CommonMCPClient is not None


def test_common_mcp_client_tools_url_mirrors_base_url() -> None:
    """tools_url must equal base_url per Phase 3 contract."""
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    client = CommonMCPClient(base_url="http://localhost:8680/mcp", timeout=5.0)
    assert client.tools_url == "http://localhost:8680/mcp"
    assert client.base_url == "http://localhost:8680/mcp"


def test_common_mcp_client_rejects_non_http_schemes() -> None:
    """SSRF guard: file://, gopher://, etc. are rejected at construction."""
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    with pytest.raises(ValueError, match="scheme"):
        CommonMCPClient(base_url="file:///etc/passwd")


def test_common_mcp_client_aclose_is_idempotent() -> None:
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    client = CommonMCPClient(base_url="http://localhost:8680/mcp")
    # No session was established; both calls should be safe no-ops.
    import asyncio

    asyncio.run(client.aclose())
    asyncio.run(client.aclose())


def test_common_mcp_client_error_hierarchy() -> None:
    """All client-side errors inherit from mcp_common.exceptions.MCPServerError."""
    from mcp_common.clients.common_mcp_client import (
        MCPClientError,
        MCPClientHTTPError,
        MCPClientTimeoutError,
    )
    from mcp_common.exceptions import MCPServerError

    assert issubclass(MCPClientError, MCPServerError)
    assert issubclass(MCPClientHTTPError, MCPClientError)
    assert issubclass(MCPClientTimeoutError, MCPClientError)
