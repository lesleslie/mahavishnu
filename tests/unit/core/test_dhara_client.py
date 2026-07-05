"""Tests for core/dhara_client.py — thin Dhara SQL proxy client.

These tests cover the thin client surface added on top of the existing
dhara_adapter.py module. The thin client wraps the Dhara MCP SQL proxy
endpoints with ``execute`` (INSERT/UPDATE/DELETE) and ``query`` (SELECT).

TDD discipline: every test was written before the implementation. The
tests use ``unittest.mock`` to stub the underlying ``DharaClient`` HTTP
transport so we don't need a live Dhara instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mahavishnu.core.dhara_client import DharaSQLProxyError, DharaThinClient

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestDharaThinClientInit:
    def test_base_url_trailing_slash_stripped(self):
        client = DharaThinClient("http://localhost:8683/")
        assert client.base_url == "http://localhost:8683"

    def test_base_url_no_trailing_slash(self):
        client = DharaThinClient("http://localhost:8683")
        assert client.base_url == "http://localhost:8683"

    def test_default_timeout(self):
        client = DharaThinClient("http://localhost")
        assert client.timeout == 30.0

    def test_custom_timeout(self):
        client = DharaThinClient("http://localhost", timeout=5.0)
        assert client.timeout == 5.0

    def test_reuses_adapter_when_provided(self):
        adapter = MagicMock()
        client = DharaThinClient("http://localhost", adapter=adapter)
        assert client._adapter is adapter


# ---------------------------------------------------------------------------
# execute — INSERT/UPDATE/DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecute:
    async def test_execute_insert_returns_rowcount_and_status(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"rowcount": 1, "status": "INSERT"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.execute(
            "INSERT INTO tenants(id, name) VALUES ($1, $2)",
            {"id": "abc", "name": "Acme"},
        )
        assert result == {"rowcount": 1, "status": "INSERT"}

    async def test_execute_update(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rowcount": 3, "status": "UPDATE"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.execute(
            "UPDATE workflows SET status = $1 WHERE tenant_id = $2",
            {"status": "completed", "tenant_id": "t1"},
        )
        assert result == {"rowcount": 3, "status": "UPDATE"}

    async def test_execute_delete(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rowcount": 0, "status": "DELETE"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.execute("DELETE FROM adapters WHERE id = $1", {"id": "x"})
        assert result == {"rowcount": 0, "status": "DELETE"}

    async def test_execute_without_params(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rowcount": 1, "status": "INSERT"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.execute("INSERT INTO foo DEFAULT VALUES")

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["name"] == "sql_proxy_execute"
        # When params is None we still pass an empty dict so the proxy gets
        # a stable payload shape.
        assert body["arguments"]["sql"] == "INSERT INTO foo DEFAULT VALUES"
        assert body["arguments"]["params"] == {}

    async def test_execute_forwards_params(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rowcount": 1, "status": "INSERT"}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.execute(
            "INSERT INTO workflows(id, status) VALUES ($1, $2)",
            {"id": "wf1", "status": "pending"},
        )

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["arguments"]["params"] == {"id": "wf1", "status": "pending"}

    async def test_execute_connection_failure_raises_proxy_error(self):
        client = DharaThinClient("http://localhost")
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )

        with pytest.raises(DharaSQLProxyError) as exc_info:
            await client.execute("INSERT INTO foo (id) VALUES ($1)", {"id": "x"})

        assert "connect" in str(exc_info.value).lower() or "sql_proxy" in str(exc_info.value).lower()

    async def test_execute_aclose_closes_underlying_client(self):
        client = DharaThinClient("http://localhost")
        client._client = AsyncMock()
        await client.aclose()
        client._client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# query — SELECT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQuery:
    async def test_query_returns_rows_as_dicts(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {"rows": [{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}]}
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        rows = await client.query("SELECT id, name FROM tenants")
        assert rows == [{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}]

    async def test_query_empty_result(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rows": []}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        rows = await client.query("SELECT * FROM tenants WHERE 1=0")
        assert rows == []

    async def test_query_forwards_params(self):
        client = DharaThinClient("http://localhost")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"rows": []}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.query(
            "SELECT id FROM workflows WHERE tenant_id = $1",
            {"tenant_id": "t1"},
        )

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["name"] == "sql_proxy_query"
        assert body["arguments"]["params"] == {"tenant_id": "t1"}

    async def test_query_connection_failure_raises_proxy_error(self):
        client = DharaThinClient("http://localhost")
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            side_effect=httpx.ConnectError("nope"),
        )

        with pytest.raises(DharaSQLProxyError):
            await client.query("SELECT 1")


# ---------------------------------------------------------------------------
# Connection pooling / adapter reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConnectionPooling:
    async def test_routes_through_existing_adapter_when_provided(self):
        adapter = MagicMock()
        adapter.call_tool = AsyncMock(return_value={"rowcount": 1, "status": "INSERT"})

        client = DharaThinClient("http://localhost", adapter=adapter)
        result = await client.execute("INSERT INTO foo (id) VALUES ($1)", {"id": "1"})

        assert result == {"rowcount": 1, "status": "INSERT"}
        adapter.call_tool.assert_awaited_once_with(
            "sql_proxy_execute",
            {"sql": "INSERT INTO foo (id) VALUES ($1)", "params": {"id": "1"}},
        )

    async def test_query_routes_through_existing_adapter_when_provided(self):
        adapter = MagicMock()
        adapter.call_tool = AsyncMock(return_value={"rows": [{"id": "1"}]})

        client = DharaThinClient("http://localhost", adapter=adapter)
        rows = await client.query("SELECT id FROM foo")

        assert rows == [{"id": "1"}]
        adapter.call_tool.assert_awaited_once_with(
            "sql_proxy_query",
            {"sql": "SELECT id FROM foo", "params": {}},
        )


# ---------------------------------------------------------------------------
# Async semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAsyncSemantics:
    async def test_execute_is_coroutine(self):
        import inspect

        client = DharaThinClient("http://localhost")
        assert inspect.iscoroutinefunction(client.execute)

    async def test_query_is_coroutine(self):
        import inspect

        client = DharaThinClient("http://localhost")
        assert inspect.iscoroutinefunction(client.query)
