"""Tests for core/mcp_adapter.py — MCPClient and MCPAdapter.

Phase 3 (REQ-004): mocked at the CommonMCPClient.call_tool boundary
instead of httpx2.AsyncClient.post.

``MCPClient.put`` writes through the self-hosted ``mahavishnu_kv_put``
tool on mahavishnu's own MCP server, with the internal service identity.
``MCPAdapter`` — the analytics seam — has no provider: the metric series
it used to read have no writer in the fleet, so every query raises
``NoAnalyticsWriterError`` naming the series.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mcp.types import CallToolResult, TextContent
import pytest

from mahavishnu.core.mcp_adapter import (
    INTERNAL_SERVICE_USER_ID,
    MCPAdapter,
    MCPClient,
    NoAnalyticsWriterError,
)

# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------


def _envelope(
    *,
    structured: dict[str, Any] | None = None,
    text: str | None = None,
    is_error: bool = False,
) -> CallToolResult:
    """Build the wire envelope ``CommonMCPClient.call_tool`` actually returns.

    ``CommonMCPClient.call_tool`` is a pass-through of the MCP SDK's
    ``ClientSession.call_tool``, so the value arriving in ``MCPClient.call_tool``
    is always a ``CallToolResult`` — never an already-unwrapped ``dict`` /
    ``str`` / ``None``. Unwrapping that envelope is the production
    ``MCPClient.call_tool`` seam, so the fakes must hand it a real one.
    """
    content = [] if text is None else [TextContent(type="text", text=text)]
    return CallToolResult(
        content=content, structured_content=structured, is_error=is_error
    )


class TestMCPClientInit:
    def test_base_url_trailing_slash_stripped(self):
        client = MCPClient("http://localhost:8683/")
        assert client.base_url == "http://localhost:8683"

    def test_base_url_no_trailing_slash(self):
        client = MCPClient("http://localhost:8683")
        assert client.base_url == "http://localhost:8683"

    def test_custom_timeout(self):
        client = MCPClient("http://localhost", timeout=10.0)
        assert client.timeout == 10.0

    def test_default_timeout(self):
        client = MCPClient("http://localhost")
        assert client.timeout == 30.0


class TestMCPClientToolsUrl:
    def test_tools_url_matches_base_url(self):
        """After Phase 3 migration, tools_url is an alias for base_url.

        CommonMCPClient's streamable-HTTP transport serves both
        ``initialize`` and ``tools/call`` from the same endpoint.
        """
        client = MCPClient("http://localhost:8683")
        assert client.tools_url == "http://localhost:8683"


@pytest.mark.asyncio
class TestMCPClientCallTool:
    async def test_call_tool_returns_result(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(
            return_value=_envelope(structured={"key": "value"})
        )

        result = await client.call_tool("get", {"key": "test"})
        assert result == {"key": "value"}
        client._mcp.call_tool.assert_awaited_once_with("get", {"key": "test"})

    async def test_call_tool_returns_raw_payload(self):
        """The wrapper passes the tool's payload through unchanged."""
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(
            return_value=_envelope(structured={"data": [1, 2, 3]})
        )

        result = await client.call_tool("list", {})
        assert result == {"data": [1, 2, 3]}

    async def test_call_tool_decodes_json_text_content(self):
        """String returns land in ``content[0].text`` and get JSON-decoded."""
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(
            return_value=_envelope(text='{"key": "value"}')
        )

        result = await client.call_tool("get", {"key": "test"})
        assert result == {"key": "value"}

    async def test_call_tool_returns_error_dict_from_first_text_content(self):
        """Errors surface as ``{"error": ..., "is_error": True}``."""
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(
            return_value=_envelope(text="tool blew up", is_error=True)
        )

        result = await client.call_tool("boom", {})
        assert result == {"error": "tool blew up", "is_error": True}

    async def test_call_tool_returns_none_for_empty_envelope(self):
        """No structured content and no text content unwraps to ``None``."""
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(return_value=_envelope())

        assert await client.call_tool("noop", {}) is None

    async def test_call_tool_passes_arguments(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(return_value=_envelope(text="null"))

        await client.call_tool("my_tool", {"arg1": "val1"})

        client._mcp.call_tool.assert_awaited_once_with("my_tool", {"arg1": "val1"})


@pytest.mark.asyncio
class TestMCPClientPut:
    async def test_put_without_ttl(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(return_value=_envelope(text="ok"))

        result = await client.put("mykey", {"data": 42})
        assert result == "ok"

        call_kwargs = client._mcp.call_tool.await_args
        assert call_kwargs.args[0] == "mahavishnu_kv_put"
        args = call_kwargs.args[1]
        assert args["key"] == "mykey"
        # The KV tool takes a string value, so a structured payload is
        # JSON-encoded on the way out.
        assert json.loads(args["value"]) == {"data": 42}
        assert args["user_id"] == INTERNAL_SERVICE_USER_ID
        assert "ttl" not in args

    async def test_put_with_ttl(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(return_value=_envelope(text="ok"))

        await client.put("key", "val", ttl=3600)

        call_args = client._mcp.call_tool.await_args
        assert call_args.args[0] == "mahavishnu_kv_put"
        args = call_args.args[1]
        assert args["ttl"] == 3600
        assert args["user_id"] == INTERNAL_SERVICE_USER_ID


@pytest.mark.asyncio
class TestMCPClientClose:
    async def test_aclose(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.aclose = AsyncMock()
        await client.aclose()
        client._mcp.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# MCPAdapter
# ---------------------------------------------------------------------------


class TestMCPAdapterInit:
    def test_creates_client(self):
        adapter = MCPAdapter("http://localhost:8680", timeout=5.0)
        assert isinstance(adapter.client, MCPClient)
        assert adapter.client.base_url == "http://localhost:8680"
        assert adapter.client.timeout == 5.0


@pytest.mark.asyncio
class TestMCPAdapterQueryTimeSeries:
    """The analytics series have no writer, so a query must say so.

    Returning an empty list would read as "the series exists but has no
    data yet" — a different, and wrong, statement.
    """

    async def test_raises_naming_the_metric(self):
        adapter = MCPAdapter("http://localhost:8680")

        with pytest.raises(NoAnalyticsWriterError) as excinfo:
            await adapter.query_time_series("git_velocity", "repo1")

        assert "git_velocity" in str(excinfo.value)

    async def test_does_not_call_the_substrate(self):
        adapter = MCPAdapter("http://localhost:8680")
        adapter.client.call_tool = AsyncMock(return_value=[])

        with pytest.raises(NoAnalyticsWriterError):
            await adapter.query_time_series("commits", "repo1")

        adapter.client.call_tool.assert_not_called()


@pytest.mark.asyncio
class TestMCPAdapterAggregatePatterns:
    """Same for the aggregated pattern feed."""

    async def test_raises(self):
        adapter = MCPAdapter("http://localhost:8680")

        with pytest.raises(NoAnalyticsWriterError) as excinfo:
            await adapter.aggregate_patterns("2026-01-01", min_occurrences=3)

        assert "pattern" in str(excinfo.value)

    async def test_does_not_call_the_substrate(self):
        adapter = MCPAdapter("http://localhost:8680")
        adapter.client.call_tool = AsyncMock(return_value=[])

        with pytest.raises(NoAnalyticsWriterError):
            await adapter.aggregate_patterns("2026-01-01")

        adapter.client.call_tool.assert_not_called()
