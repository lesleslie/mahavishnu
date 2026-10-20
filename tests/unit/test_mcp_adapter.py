"""Tests for core/mcp_adapter.py — MCPClient and MCPAdapter.

Phase 3 (REQ-004): mocked at the CommonMCPClient.call_tool boundary
instead of httpx2.AsyncClient.post.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mcp.types import CallToolResult, TextContent
import pytest

from mahavishnu.core.mcp_adapter import MCPAdapter, MCPClient

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
    return CallToolResult(content=content, structured_content=structured, is_error=is_error)


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
        client._mcp.call_tool = AsyncMock(return_value=_envelope(text='{"key": "value"}'))

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
        assert call_kwargs.args[0] == "put"
        args = call_kwargs.args[1]
        assert args["key"] == "mykey"
        assert args["value"] == {"data": 42}
        assert "ttl" not in args

    async def test_put_with_ttl(self):
        client = MCPClient("http://localhost")
        client._mcp = MagicMock()
        client._mcp.call_tool = AsyncMock(return_value=_envelope(text="ok"))

        await client.put("key", "val", ttl=3600)

        call_args = client._mcp.call_tool.await_args
        assert call_args.args[0] == "put"
        args = call_args.args[1]
        assert args["ttl"] == 3600


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
        adapter = MCPAdapter("http://localhost:8683", timeout=5.0)
        assert isinstance(adapter.client, MCPClient)
        assert adapter.client.base_url == "http://localhost:8683"
        assert adapter.client.timeout == 5.0


@pytest.mark.asyncio
class TestMCPAdapterQueryTimeSeries:
    async def test_returns_list_result(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[{"ts": "2026-01-01", "value": 42}])

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1
        assert result[0]["value"] == 42

    async def test_returns_records_from_dict(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value={"records": [{"ts": "2026-01-01"}]})

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_items_from_dict(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value={"items": [{"ts": "2026-01-01"}]})

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_result_key_from_dict(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value={"result": [{"ts": "2026-01-01"}]})

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_empty_on_unexpected_shape(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value="unexpected string")

        result = await adapter.query_time_series("commits", "repo1")
        assert result == []

    async def test_passes_optional_params(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.query_time_series("commits", "repo1", start_date="2026-01-01", limit=50)

        call_args = adapter.client.call_tool.call_args
        args = call_args[1] if call_args[1] else call_args[0][1]
        assert args["start_date"] == "2026-01-01"
        assert args["limit"] == 50

    async def test_omits_optional_params_when_none(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.query_time_series("commits", "repo1")

        call_args = adapter.client.call_tool.call_args
        args = call_args[0][1]
        assert "start_date" not in args
        assert "limit" not in args


@pytest.mark.asyncio
class TestMCPAdapterAggregatePatterns:
    async def test_returns_list_result(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[{"pattern": "test", "count": 5}])

        result = await adapter.aggregate_patterns("2026-01-01", min_occurrences=3)
        assert len(result) == 1

    async def test_returns_patterns_from_dict(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value={"patterns": [{"pattern": "test"}]})

        result = await adapter.aggregate_patterns("2026-01-01")
        assert len(result) == 1

    async def test_returns_result_from_dict(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value={"result": [{"pattern": "test"}]})

        result = await adapter.aggregate_patterns("2026-01-01")
        assert len(result) == 1

    async def test_returns_empty_on_unexpected_shape(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=42)

        result = await adapter.aggregate_patterns("2026-01-01")
        assert result == []

    async def test_passes_min_occurrences(self):
        adapter = MCPAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.aggregate_patterns("2026-01-01", min_occurrences=5)

        call_args = adapter.client.call_tool.call_args
        args = call_args[0][1]
        assert args["min_occurrences"] == 5
        assert args["start_date"] == "2026-01-01"
