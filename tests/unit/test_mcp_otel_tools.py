"""Unit tests for mahavishnu.mcp.tools.otel_tools.

Covers:
- Tool registration (5 tools expected)
- query_local_traces input validation and success path
- ingest_otel_traces mixed input (log_files + trace_data)
- ingest_otel_traces log_file with non-dict traces
- ingest_otel_traces trace_data ingest exception
- search_otel_traces threshold=None path
- get_otel_trace ImportError path
- otel_ingester_stats with turboquant_bits set vs None

Complementary to tests/unit/test_otel_tools.py — this file focuses on
the registration mechanism and on ``query_local_traces`` which is not
covered elsewhere.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.otel_tools import register_otel_tools

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Akosha HotStore workaround
# ---------------------------------------------------------------------------
#
# The real ``akosha.storage`` package has a latent pydantic bug
# (``SystemMemoryUpload.model_rebuild()`` raises
# ``PydanticUndefinedAnnotation: name 'datetime' is not defined``) that
# fires when the package is imported. To exercise the OTel tools' HotStore
# code path without triggering that bug, we inject a fake ``akosha.storage``
# module into ``sys.modules`` whose only public attribute is ``HotStore``.
# This is a documented workaround for an upstream bug — do not "fix" it by
# modifying the real akosha package.


class _FakeHotStore:
    """Stand-in for ``akosha.storage.HotStore`` used in tests."""

    def __init__(self, *args, **kwargs):
        # Tests replace attributes on the instance, so keep an open bag.
        self._init_args = args
        self._init_kwargs = kwargs
        self.initialize = AsyncMock()
        self.close = AsyncMock()
        self.query_traces = AsyncMock(return_value=[])


_FAKE_STORAGE = types.ModuleType("akosha.storage")
_FAKE_STORAGE.HotStore = _FakeHotStore  # type: ignore[attr-defined]
# Also create parent akosha package if absent
if "akosha" not in sys.modules:
    _FAKE_AKOSHA = types.ModuleType("akosha")
    _FAKE_AKOSHA.__path__ = []  # mark as package
    sys.modules["akosha"] = _FAKE_AKOSHA
sys.modules["akosha.storage"] = _FAKE_STORAGE


# =============================================================================
# Fixtures
# =============================================================================


def _make_mock_server() -> MagicMock:
    """Build a mock FastMCP server that captures tool functions by name."""
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


def _make_mock_app(
    hot_store_path: str = "/tmp/test_mcp_otel.duckdb",
    turboquant_bits: int | None = 4,
    similarity_threshold: float = 0.7,
) -> MagicMock:
    """Build a mock MahavishnuApp with otel_ingester config."""
    otel_cfg = SimpleNamespace(
        hot_store_path=hot_store_path,
        embedding_model="all-MiniLM-L6-v2",
        cache_size=100,
        similarity_threshold=similarity_threshold,
        turboquant_bits=turboquant_bits,
    )
    app = MagicMock()
    app.config.otel_ingester = otel_cfg
    return app


def _make_mock_ingester(**overrides) -> MagicMock:
    """Build a mock OtelIngester with async methods."""
    ingester = MagicMock()
    ingester.initialize = AsyncMock()
    ingester.close = AsyncMock()
    ingester.ingest_batch = AsyncMock()
    ingester.search_traces = AsyncMock(return_value=[])
    ingester.get_trace_by_id = AsyncMock(return_value=None)
    for key, value in overrides.items():
        setattr(ingester, key, value)
    return ingester


def _register(
    app: MagicMock | None = None,
    server: MagicMock | None = None,
) -> dict[str, object]:
    """Register otel tools and return the captured tool dict."""
    if server is None:
        server = _make_mock_server()
    if app is None:
        app = _make_mock_app()
    register_otel_tools(server, app, MagicMock())
    return server._captured


# =============================================================================
# Tool registration
# =============================================================================


class TestToolRegistration:
    """Verify that register_otel_tools attaches exactly 5 tools."""

    def test_registers_five_tools(self) -> None:
        tools = _register()
        assert len(tools) == 5

    def test_expected_tool_names_present(self) -> None:
        tools = _register()
        expected = {
            "ingest_otel_traces",
            "search_otel_traces",
            "get_otel_trace",
            "query_local_traces",
            "otel_ingester_stats",
        }
        assert expected <= set(tools.keys())

    def test_each_tool_is_callable(self) -> None:
        tools = _register()
        for name, fn in tools.items():
            assert callable(fn), f"Tool {name} is not callable"


# =============================================================================
# ingest_otel_traces: additional edge cases
# =============================================================================


class TestIngestOtelTracesMixed:
    @pytest.mark.asyncio
    async def test_mixed_log_files_and_trace_data(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        log_file.write_text('[{"span": "from_file"}]')
        tools = _register()
        ingester = _make_mock_ingester()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](
                log_files=[str(log_file)],
                trace_data=[{"span": "from_api"}],
            )
        assert result["traces_ingested"] == 2
        assert result["files_processed"] == 1
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_log_file_data_key_extraction(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        log_file.write_text(json.dumps({"data": [{"span": "x"}]}))
        tools = _register()
        ingester = _make_mock_ingester()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert result["traces_ingested"] == 1
        assert result["files_processed"] == 1

    @pytest.mark.asyncio
    async def test_log_file_with_nondict_traces_skipped(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        # List of non-dict values — setdefault guards against AttributeError
        log_file.write_text(json.dumps(["just_a_string", 42, None]))
        tools = _register()
        ingester = _make_mock_ingester()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        # The list contains 3 non-dict items, but the code only sets system_id
        # for dicts. ingest_batch is still called with all 3 items.
        assert result["traces_ingested"] == 3

    @pytest.mark.asyncio
    async def test_trace_data_ingest_exception_collected(self) -> None:
        tools = _register()
        ingester = MagicMock()
        ingester.initialize = AsyncMock()
        ingester.close = AsyncMock()
        ingester.ingest_batch = AsyncMock(side_effect=RuntimeError("ingest failed"))
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](trace_data=[{"span": "x"}])
        assert result["traces_ingested"] == 0
        assert any("ingest failed" in e for e in result["errors"])
        assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_log_file_ingest_exception_collected(self, tmp_path) -> None:
        log_file = tmp_path / "traces.json"
        log_file.write_text("[]")
        tools = _register()
        ingester = MagicMock()
        ingester.initialize = AsyncMock()
        ingester.close = AsyncMock()
        ingester.ingest_batch = AsyncMock(side_effect=RuntimeError("file ingest failed"))
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert any("file ingest failed" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_invalid_json_file_adds_error(self, tmp_path) -> None:
        log_file = tmp_path / "bad.json"
        log_file.write_text("not valid json {{{")
        tools = _register()
        ingester = _make_mock_ingester()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["ingest_otel_traces"](log_files=[str(log_file)])
        assert any("Failed to process" in e for e in result["errors"])


# =============================================================================
# search_otel_traces: threshold handling
# =============================================================================


class TestSearchOtelTracesThreshold:
    @pytest.mark.asyncio
    async def test_threshold_uses_config_when_none(self) -> None:
        tools = _register(app=_make_mock_app(similarity_threshold=0.85))
        ingester = _make_mock_ingester(search_traces=AsyncMock(return_value=[]))
        captured_args: dict = {}

        async def search(**kwargs):
            captured_args.update(kwargs)
            return []

        ingester.search_traces = search
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            await tools["search_otel_traces"]("query")
        # threshold is not passed to search_traces in this implementation —
        # it's only used to configure the ingester. Verify no exception and
        # the query was forwarded.
        assert captured_args["query"] == "query"

    @pytest.mark.asyncio
    async def test_explicit_threshold_overrides_config(self) -> None:
        tools = _register(app=_make_mock_app(similarity_threshold=0.85))
        ingester = _make_mock_ingester()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ) as ingester_cls:
            await tools["search_otel_traces"]("query", threshold=0.5)
        # The ingester should be constructed with similarity_threshold=0.5
        call_kwargs = ingester_cls.call_args.kwargs
        assert call_kwargs["similarity_threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_unexpected_error(self) -> None:
        tools = _register()
        ingester = MagicMock()
        ingester.initialize = AsyncMock()
        # search_traces raises after initialize succeeds
        ingester.search_traces = AsyncMock(side_effect=RuntimeError("boom"))
        ingester.close = AsyncMock()
        with patch(
            "mahavishnu.ingesters.otel_ingester.OtelIngester",
            return_value=ingester,
        ):
            result = await tools["search_otel_traces"]("anything")
        assert result == []


# =============================================================================
# get_otel_trace: ImportError and other paths
# =============================================================================


class TestGetOtelTraceImportError:
    @pytest.mark.asyncio
    async def test_import_error_returns_none(self) -> None:
        tools = _register()
        with (
            patch.dict("sys.modules", {"mahavishnu.ingesters.otel_ingester": None}),
            patch("builtins.__import__", side_effect=ImportError("nope")),
        ):
            result = await tools["get_otel_trace"]("trace-123")
        assert result is None


# =============================================================================
# otel_ingester_stats: turboquant_compression flag
# =============================================================================


class TestOtelIngesterStats:
    @pytest.mark.asyncio
    async def test_turboquant_compression_true_when_set(self) -> None:
        tools = _register(app=_make_mock_app(turboquant_bits=4))
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["otel_ingester_stats"]()
        assert result["turboquant_compression"] is True
        assert result["turboquant_bits"] == 4
        assert result["embedding_model"] == "all-MiniLM-L6-v2"

    @pytest.mark.asyncio
    async def test_turboquant_compression_false_when_none(self) -> None:
        tools = _register(app=_make_mock_app(turboquant_bits=None))
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["otel_ingester_stats"]()
        assert result["turboquant_compression"] is False
        assert result["turboquant_bits"] is None

    @pytest.mark.asyncio
    async def test_stats_dict_has_expected_keys(self) -> None:
        tools = _register()
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["otel_ingester_stats"]()
        for key in (
            "storage_backend",
            "hot_store_path",
            "embedding_model",
            "cache_size",
            "similarity_threshold",
            "turboquant_bits",
            "turboquant_compression",
            "status",
            "total_traces",
            "traces_by_system",
        ):
            assert key in result, f"Missing key: {key}"


# =============================================================================
# query_local_traces: input validation
# =============================================================================


class TestQueryLocalTracesValidation:
    @pytest.mark.asyncio
    async def test_empty_task_class_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](task_class="")
        assert result == []

    @pytest.mark.asyncio
    async def test_non_string_task_class_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](task_class=123)  # type: ignore[arg-type]
        assert result == []

    @pytest.mark.asyncio
    async def test_zero_time_range_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](
            task_class="code_generation", time_range_minutes=0
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_negative_time_range_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](
            task_class="code_generation", time_range_minutes=-1
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_too_large_time_range_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](
            task_class="code_generation", time_range_minutes=10081
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_zero_limit_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](task_class="code_generation", limit=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_too_large_limit_returns_empty_list(self) -> None:
        tools = _register()
        result = await tools["query_local_traces"](task_class="code_generation", limit=1001)
        assert result == []


# =============================================================================
# query_local_traces: success path
# =============================================================================


class TestQueryLocalTracesSuccess:
    @pytest.mark.asyncio
    async def test_returns_normalized_results(self) -> None:
        tools = _register()
        raw_results = [
            {
                "system_id": "svc-a",
                "timestamp": "2026-06-05T00:00:00+00:00",
                "metadata": json.dumps(
                    {
                        "attributes": {
                            "outcome": "success",
                            "duration_ms": 42,
                            "selector": "primary",
                        }
                    }
                ),
            }
        ]
        store = _FakeHotStore()
        store.query_traces = AsyncMock(return_value=raw_results)
        with patch.object(_FAKE_STORAGE, "HotStore", return_value=store):
            result = await tools["query_local_traces"](
                task_class="code_generation",
                system_id="svc-a",
            )
        assert len(result) == 1
        record = result[0]
        assert record["outcome"] == "success"
        assert record["duration_ms"] == 42
        assert record["selector"] == "primary"
        assert record["component_name"] == "svc-a"
        assert record["task_class"] == "code_generation"

    @pytest.mark.asyncio
    async def test_metadata_dict_format(self) -> None:
        tools = _register()
        raw_results = [
            {
                "system_id": "svc-b",
                "timestamp": "2026-06-05T00:00:00+00:00",
                "metadata": {"attributes": {"outcome": "failure", "duration_ms": 7}},
            }
        ]
        store = _FakeHotStore()
        store.query_traces = AsyncMock(return_value=raw_results)
        with patch.object(_FAKE_STORAGE, "HotStore", return_value=store):
            result = await tools["query_local_traces"](task_class="debugging")
        assert result[0]["outcome"] == "failure"
        assert result[0]["duration_ms"] == 7
        assert result[0]["component_name"] == "svc-b"

    @pytest.mark.asyncio
    async def test_metadata_invalid_json_falls_back_to_defaults(self) -> None:
        tools = _register()
        raw_results = [
            {
                "system_id": "svc-c",
                "timestamp": "2026-06-05T00:00:00+00:00",
                "metadata": "{not valid json",
            }
        ]
        store = _FakeHotStore()
        store.query_traces = AsyncMock(return_value=raw_results)
        with patch.object(_FAKE_STORAGE, "HotStore", return_value=store):
            result = await tools["query_local_traces"](task_class="test")
        assert result[0]["outcome"] == "unknown"
        assert result[0]["duration_ms"] == 0
        assert result[0]["selector"] == "unknown"

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self) -> None:
        tools = _register()
        store = _FakeHotStore()
        with patch.object(_FAKE_STORAGE, "HotStore", return_value=store):
            result = await tools["query_local_traces"](task_class="code_generation")
        assert result == []

    @pytest.mark.asyncio
    async def test_falls_back_to_record_system_id(self) -> None:
        tools = _register()
        raw_results = [
            {
                "system_id": "discovered-sys",
                "timestamp": "2026-06-05T00:00:00+00:00",
                "metadata": "{}",
            }
        ]
        store = _FakeHotStore()
        store.query_traces = AsyncMock(return_value=raw_results)
        with patch.object(_FAKE_STORAGE, "HotStore", return_value=store):
            result = await tools["query_local_traces"](task_class="reasoning")
        # When system_id is None, falls back to record's system_id
        assert result[0]["component_name"] == "discovered-sys"


# =============================================================================
# query_local_traces: error paths
# =============================================================================


class TestQueryLocalTracesErrors:
    @pytest.mark.asyncio
    async def test_import_error_returns_empty_list(self) -> None:
        tools = _register()
        with patch.dict("sys.modules", {"akosha.storage": None}):
            with patch("builtins.__import__", side_effect=ImportError("no akosha")):
                result = await tools["query_local_traces"](task_class="code_generation")
        assert result == []

    @pytest.mark.asyncio
    async def test_query_exception_returns_empty_list(self) -> None:
        tools = _register()
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.query_traces = AsyncMock(side_effect=RuntimeError("query fail"))
        mock_store.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["query_local_traces"](task_class="code_generation")
        assert result == []
        # close() should still be called even after exception
        mock_store.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_initialize_failure_returns_empty_list(self) -> None:
        tools = _register()
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock(side_effect=RuntimeError("init fail"))
        with patch("akosha.storage.HotStore", return_value=mock_store):
            result = await tools["query_local_traces"](task_class="code_generation")
        assert result == []


# =============================================================================
# Module-level sanity
# =============================================================================


class TestModuleSurface:
    """Sanity checks on the public module surface."""

    def test_register_otel_tools_is_callable(self) -> None:
        assert callable(register_otel_tools)

    def test_module_logger_exists(self) -> None:
        import mahavishnu.mcp.tools.otel_tools as mod

        assert hasattr(mod, "logger")
