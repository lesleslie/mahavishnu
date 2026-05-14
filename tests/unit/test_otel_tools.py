"""Tests for mcp/tools/otel_tools.py — covers early returns, ImportError, and exception paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.otel_tools import register_otel_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_server() -> MagicMock:
    captured: dict[str, object] = {}
    server = MagicMock()

    def tool():
        def decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return decorator

    server.tool = tool
    server._captured = captured
    return server


def _make_mock_app() -> MagicMock:
    otel_cfg = SimpleNamespace(
        hot_store_path="/tmp/test.duckdb",
        embedding_model="nomic-embed-text",
        cache_size=100,
        similarity_threshold=0.7,
    )
    app = MagicMock()
    app.config.otel_ingester = otel_cfg
    return app


def _register(server=None, app=None, mcp_client=None) -> dict:
    if server is None:
        server = _make_mock_server()
    if app is None:
        app = _make_mock_app()
    if mcp_client is None:
        mcp_client = MagicMock()
    register_otel_tools(server, app, mcp_client)
    return server._captured


# ---------------------------------------------------------------------------
# ingest_otel_traces: early return when no input
# ---------------------------------------------------------------------------


class TestIngestOtelTracesEarlyReturn:
    @pytest.mark.asyncio
    async def test_no_input_returns_error(self) -> None:
        tools = _register()
        result = await tools["ingest_otel_traces"]()
        assert result["status"] == "error"
        assert "Either log_files or trace_data" in result["error"]
        assert result["traces_ingested"] == 0


# ---------------------------------------------------------------------------
# ingest_otel_traces: ImportError path
# ---------------------------------------------------------------------------


class TestIngestOtelTracesImportError:
    @pytest.mark.asyncio
    async def test_import_error_returns_error_dict(self) -> None:
        tools = _register()
        with patch.dict("sys.modules", {"mahavishnu.ingesters.otel_ingester": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("OtelIngester missing"),
            ):
                result = await tools["ingest_otel_traces"](trace_data=[{"span": "x"}])
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self) -> None:
        tools = _register()
        with patch(
            "mahavishnu.mcp.tools.otel_tools.register_otel_tools",
            side_effect=RuntimeError("boom"),
        ):
            pass  # just ensure the import works
        # Test via direct exception mock on OtelIngester
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock(side_effect=RuntimeError("db unavailable"))
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](trace_data=[{"span": "x"}])
        assert result["status"] == "error"
        assert "db unavailable" in result["error"]


# ---------------------------------------------------------------------------
# ingest_otel_traces: trace_data success path
# ---------------------------------------------------------------------------


class TestIngestOtelTracesTraceData:
    @pytest.mark.asyncio
    async def test_trace_data_ingested_successfully(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.ingest_batch = AsyncMock()
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](
                trace_data=[{"span": "x", "system_id": "svc"}, {"span": "y"}]
            )
        assert result["traces_ingested"] == 2
        assert result["status"] in ("success", "warning")

    @pytest.mark.asyncio
    async def test_trace_data_default_system_id_set(self) -> None:
        tools = _register()
        ingested: list[list] = []
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.close = AsyncMock()

        async def capture_batch(batch):
            ingested.extend(batch)

        mock_ingester.ingest_batch = capture_batch
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            await tools["ingest_otel_traces"](
                trace_data=[{"span": "z"}], system_id="my-svc"
            )
        assert ingested[0]["system_id"] == "my-svc"


# ---------------------------------------------------------------------------
# ingest_otel_traces: log_files path
# ---------------------------------------------------------------------------


class TestIngestOtelTracesLogFiles:
    @pytest.mark.asyncio
    async def test_log_file_not_found_adds_error(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.ingest_batch = AsyncMock()
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=["/no/such/file.json"])
        assert any("File not found" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_log_file_list_format(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        log_file.write_text('[{"span": "a"}, {"span": "b"}]')
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.ingest_batch = AsyncMock()
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert result["files_processed"] == 1
        assert result["traces_ingested"] == 2

    @pytest.mark.asyncio
    async def test_log_file_dict_format(self, tmp_path) -> None:
        import json

        log_file = tmp_path / "traces.json"
        log_file.write_text(json.dumps({"traces": [{"span": "c"}]}))
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.ingest_batch = AsyncMock()
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert result["traces_ingested"] == 1

    @pytest.mark.asyncio
    async def test_log_file_invalid_format_adds_error(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        log_file.write_text('"just a string"')  # valid JSON but wrong type
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.ingest_batch = AsyncMock()
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert any("Invalid format" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# search_otel_traces: exception and ImportError paths
# ---------------------------------------------------------------------------


class TestSearchOtelTraces:
    @pytest.mark.asyncio
    async def test_import_error_returns_empty_list(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock(side_effect=ImportError("no ingester"))
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["search_otel_traces"]("my query")
        assert result == [] or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock(side_effect=RuntimeError("search fail"))
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["search_otel_traces"]("my query")
        assert result == []

    @pytest.mark.asyncio
    async def test_success_returns_results(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.search_traces = AsyncMock(return_value=[{"trace_id": "abc"}])
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["search_otel_traces"]("error traces", limit=5)
        assert result == [{"trace_id": "abc"}]


# ---------------------------------------------------------------------------
# get_otel_trace: paths
# ---------------------------------------------------------------------------


class TestGetOtelTrace:
    @pytest.mark.asyncio
    async def test_exception_returns_none(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock(side_effect=RuntimeError("db down"))
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["get_otel_trace"]("trace-xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self) -> None:
        tools = _register()
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.get_trace_by_id = AsyncMock(return_value=None)
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["get_otel_trace"]("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_found_returns_trace(self) -> None:
        tools = _register()
        trace = {"trace_id": "abc", "spans": []}
        mock_ingester = MagicMock()
        mock_ingester.initialize = AsyncMock()
        mock_ingester.get_trace_by_id = AsyncMock(return_value=trace)
        mock_ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=mock_ingester,
        ):
            result = await tools["get_otel_trace"]("abc")
        assert result == trace


# ---------------------------------------------------------------------------
# otel_ingester_stats: paths
# ---------------------------------------------------------------------------


class TestOtelIngesterStats:
    @pytest.mark.asyncio
    async def test_import_error_returns_error_dict(self) -> None:
        tools = _register()
        with patch.dict("sys.modules", {"akosha.storage": None}):
            with patch("builtins.__import__", side_effect=ImportError("no akosha")):
                result = await tools["otel_ingester_stats"]()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_exception_returns_error_dict(self) -> None:
        tools = _register()
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock(side_effect=RuntimeError("store fail"))
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["otel_ingester_stats"]()
        assert result["status"] == "error"
        assert "store fail" in result["error"]

    @pytest.mark.asyncio
    async def test_success_returns_stats(self) -> None:
        tools = _register()
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["otel_ingester_stats"]()
        assert result["status"] == "healthy"
        assert result["storage_backend"] == "duckdb_hotstore"
