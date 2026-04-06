"""Tests for core/dhara_adapter.py — DharaClient and DharaAdapter."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.dhara_adapter import DharaAdapter, DharaClient


# ---------------------------------------------------------------------------
# DharaClient
# ---------------------------------------------------------------------------


class TestDharaClientInit:
    def test_base_url_trailing_slash_stripped(self):
        client = DharaClient("http://localhost:8683/")
        assert client.base_url == "http://localhost:8683"

    def test_base_url_no_trailing_slash(self):
        client = DharaClient("http://localhost:8683")
        assert client.base_url == "http://localhost:8683"

    def test_custom_timeout(self):
        client = DharaClient("http://localhost", timeout=10.0)
        assert client.timeout == 10.0

    def test_default_timeout(self):
        client = DharaClient("http://localhost")
        assert client.timeout == 30.0


class TestDharaClientToolsUrl:
    def test_tools_url(self):
        client = DharaClient("http://localhost:8683")
        assert client.tools_url == "http://localhost:8683/tools/call"


@pytest.mark.asyncio
class TestDharaClientCallTool:
    async def test_call_tool_returns_result(self):
        client = DharaClient("http://localhost")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"key": "value"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call_tool("get", {"key": "test"})
        assert result == {"key": "value"}
        client._client.post.assert_called_once()

    async def test_call_tool_returns_raw_payload(self):
        """When response doesn't have 'result' key, return full payload."""
        client = DharaClient("http://localhost")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [1, 2, 3]}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call_tool("list", {})
        assert result == {"data": [1, 2, 3]}

    async def test_call_tool_sends_correct_payload(self):
        client = DharaClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": None}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.call_tool("my_tool", {"arg1": "val1"})

        call_kwargs = client._client.post.call_args
        assert call_kwargs[1]["json"]["name"] == "my_tool"
        assert call_kwargs[1]["json"]["arguments"] == {"arg1": "val1"}


@pytest.mark.asyncio
class TestDharaClientPut:
    async def test_put_without_ttl(self):
        client = DharaClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.put("mykey", {"data": 42})
        assert result == "ok"

        call_kwargs = client._client.post.call_args
        args = call_kwargs[1]["json"]["arguments"]
        assert args["key"] == "mykey"
        assert args["value"] == {"data": 42}
        assert "ttl" not in args

    async def test_put_with_ttl(self):
        client = DharaClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.put("key", "val", ttl=3600)

        call_kwargs = client._client.post.call_args
        args = call_kwargs[1]["json"]["arguments"]
        assert args["ttl"] == 3600


@pytest.mark.asyncio
class TestDharaClientClose:
    async def test_aclose(self):
        client = DharaClient("http://localhost")
        client._client = AsyncMock()
        await client.aclose()
        client._client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# DharaAdapter
# ---------------------------------------------------------------------------


class TestDharaAdapterInit:
    def test_creates_client(self):
        adapter = DharaAdapter("http://localhost:8683", timeout=5.0)
        assert isinstance(adapter.client, DharaClient)
        assert adapter.client.base_url == "http://localhost:8683"
        assert adapter.client.timeout == 5.0


@pytest.mark.asyncio
class TestDharaAdapterQueryTimeSeries:
    async def test_returns_list_result(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value=[{"ts": "2026-01-01", "value": 42}]
        )

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1
        assert result[0]["value"] == 42

    async def test_returns_records_from_dict(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value={"records": [{"ts": "2026-01-01"}]}
        )

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_items_from_dict(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value={"items": [{"ts": "2026-01-01"}]}
        )

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_result_key_from_dict(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value={"result": [{"ts": "2026-01-01"}]}
        )

        result = await adapter.query_time_series("commits", "repo1")
        assert len(result) == 1

    async def test_returns_empty_on_unexpected_shape(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value="unexpected string")

        result = await adapter.query_time_series("commits", "repo1")
        assert result == []

    async def test_passes_optional_params(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.query_time_series(
            "commits", "repo1", start_date="2026-01-01", limit=50
        )

        call_args = adapter.client.call_tool.call_args
        args = call_args[1] if call_args[1] else call_args[0][1]
        assert args["start_date"] == "2026-01-01"
        assert args["limit"] == 50

    async def test_omits_optional_params_when_none(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.query_time_series("commits", "repo1")

        call_args = adapter.client.call_tool.call_args
        args = call_args[0][1]
        assert "start_date" not in args
        assert "limit" not in args


@pytest.mark.asyncio
class TestDharaAdapterAggregatePatterns:
    async def test_returns_list_result(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value=[{"pattern": "test", "count": 5}]
        )

        result = await adapter.aggregate_patterns("2026-01-01", min_occurrences=3)
        assert len(result) == 1

    async def test_returns_patterns_from_dict(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value={"patterns": [{"pattern": "test"}]}
        )

        result = await adapter.aggregate_patterns("2026-01-01")
        assert len(result) == 1

    async def test_returns_result_from_dict(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(
            return_value={"result": [{"pattern": "test"}]}
        )

        result = await adapter.aggregate_patterns("2026-01-01")
        assert len(result) == 1

    async def test_returns_empty_on_unexpected_shape(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=42)

        result = await adapter.aggregate_patterns("2026-01-01")
        assert result == []

    async def test_passes_min_occurrences(self):
        adapter = DharaAdapter("http://localhost")
        adapter.client.call_tool = AsyncMock(return_value=[])

        await adapter.aggregate_patterns("2026-01-01", min_occurrences=5)

        call_args = adapter.client.call_tool.call_args
        args = call_args[0][1]
        assert args["min_occurrences"] == 5
        assert args["start_date"] == "2026-01-01"
