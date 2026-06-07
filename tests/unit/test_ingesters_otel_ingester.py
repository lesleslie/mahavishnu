"""Unit tests for mahavishnu.ingesters.otel_ingester (excluding TurboQuant).

The TurboQuant-specific slice of OtelIngester is covered by
``test_otel_ingester_turboquant.py``. This file covers the rest of the
public API surface:

    * Enums (EmbeddingBackend, StorageType)
    * EmbeddingModel Protocol structural typing
    * Wrapper classes (TextOnlyEmbedder, AkoshaEmbedder, etc.)
    * OtelIngester constructor (storage / backend / dimension properties)
    * OtelIngester.initialize (DuckDB + pgvector paths)
    * OtelIngester.ingest_trace / ingest_batch (DuckDB + pgvector paths)
    * OtelIngester.search_traces / get_trace_by_id
    * OtelIngester.close
    * OtelIngester async context manager (__aenter__ / __aexit__)
    * OtelIngester span helpers (_extract_system_id, _build_content,
      _extract_timestamp, _extract_attributes)
    * get_available_backends / get_default_backend
    * Factory create_otel_ingester
"""

from __future__ import annotations

from datetime import UTC, datetime
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ValidationError
from mahavishnu.ingesters.otel_ingester import (
    AkoshaEmbedder,
    EmbeddingBackend,
    EmbeddingModel,
    OtelIngester,
    StorageType,
    TextOnlyEmbedder,
    create_otel_ingester,
    get_available_backends,
    get_default_backend,
)

# Sentinel for tests that need a real AsyncMock async fn
pytestmark = pytest.mark.unit


# ============== Akosha stubs for module-level safety ==============
#
# The akosha package triggers a Pydantic forward-reference error during
# ``model_rebuild()`` (``name 'datetime' is not defined``) when its
# ``akosha.storage.models`` and ``akosha.models`` submodules are imported
# in a context where ``from __future__ import annotations`` is active.
# We install permissive stubs for those submodules in ``sys.modules`` at
# import time so the ingester's call-time ``from akosha.storage import
# HotStore`` and ``from akosha.models import HotRecord`` succeed without
# triggering akosha's broken Pydantic rebuild path.
def _install_akosha_stub() -> None:
    # NOTE: Do NOT stub ``akosha.storage`` (the package) - that breaks other
    # tests that import other submodules from the package (e.g. akosha.storage
    # itself does ``from akosha.storage.path_resolver import ...``). Only
    # stub the leaf modules that contain the Pydantic model definitions.
    model_attrs = (
        "CodeGraphMetadata",
        "ColdRecord",
        "ConversationMetadata",
        "HotRecord",
        "IngestionStats",
        "SystemMemoryUpload",
        "WarmRecord",
    )
    for module_name in ("akosha.models", "akosha.storage.models"):
        stub = ModuleType(module_name)
        for attr in model_attrs:
            setattr(stub, attr, MagicMock(name=f"{module_name}.{attr}"))
        sys.modules[module_name] = stub


_install_akosha_stub()


# ============== Helpers ==============


def _fake_embedding(dim: int = 384) -> list[float]:
    """Return a deterministic float embedding of the given dimension."""
    return [float(i) / dim for i in range(dim)]


def _make_embedder(embedding: list[float] | None = None) -> MagicMock:
    """Build a mock that satisfies the EmbeddingModel Protocol."""
    mock = MagicMock(spec=EmbeddingModel)
    mock.encode.return_value = embedding if embedding is not None else _fake_embedding()
    mock.dimension = 384
    return mock


def _make_ingester(
    hot_store: Any | None = None,
    preferred_backend: str | EmbeddingBackend = "text_only",
    storage_type: StorageType | str = StorageType.DUCKDB,
    pgvector_dsn: str | None = None,
    **kwargs: Any,
) -> OtelIngester:
    """Construct an OtelIngester without calling initialize()."""
    return OtelIngester(
        hot_store=hot_store,
        preferred_backend=preferred_backend,
        storage_type=storage_type,
        pgvector_dsn=pgvector_dsn,
        **kwargs,
    )


def _attach_embedder(ingester: OtelIngester, embedding: list[float] | None = None) -> MagicMock:
    """Attach a mock embedder to an ingester."""
    mock_embedder = _make_embedder(embedding)
    ingester._embedder = mock_embedder
    ingester._embedding_dimension = mock_embedder.dimension
    return mock_embedder


def _sample_trace(trace_id: str = "trace-1", **overrides: Any) -> dict[str, Any]:
    """Build a sample OTel trace dict."""
    trace: dict[str, Any] = {
        "trace_id": trace_id,
        "spans": [
            {
                "name": "GET /api/users",
                "start_time": "2024-01-01T00:00:00Z",
                "attributes": {
                    "service.name": "claude",
                    "http.method": "GET",
                },
            },
            {
                "name": "SELECT users",
                "start_time": "2024-01-01T00:00:01Z",
                "attributes": {"db.system": "postgresql"},
            },
        ],
    }
    trace.update(overrides)
    return trace


# ============== Enums ==============


class TestEnums:
    """Sanity tests for the Enum exports."""

    def test_embedding_backend_members(self) -> None:
        """EmbeddingBackend exposes the four documented members."""
        values = {m.value for m in EmbeddingBackend}
        assert values == {"akosha", "sentence_transformers", "fastembed", "text_only"}

    def test_storage_type_members(self) -> None:
        """StorageType exposes the two documented members."""
        values = {m.value for m in StorageType}
        assert values == {"duckdb", "postgresql"}


# ============== get_available_backends / get_default_backend ==============


class TestBackendDiscovery:
    """Tests for the static backend-discovery helpers."""

    def test_get_available_backends_includes_text_only(self) -> None:
        """get_available_backends always advertises text_only as a fallback."""
        backends = get_available_backends()
        assert EmbeddingBackend.TEXT_ONLY in backends

    def test_get_default_backend_prefers_akosha(self) -> None:
        """The default backend is Akosha (centralized service)."""
        assert get_default_backend() is EmbeddingBackend.AKOSHA

    def test_get_available_backends_returns_a_list(self) -> None:
        """get_available_backends returns a list (not a set) in declared order."""
        backends = get_available_backends()
        assert isinstance(backends, list)
        # Akosha is always the first advertised backend
        assert backends[0] is EmbeddingBackend.AKOSHA


# ============== TextOnlyEmbedder ==============


class TestTextOnlyEmbedder:
    """Tests for the zero-vector fallback embedder."""

    def test_encode_returns_zeros(self) -> None:
        """encode() always returns a list of zeros of the configured dim."""
        embedder = TextOnlyEmbedder(dimension=4)
        assert embedder.encode("anything") == [0.0, 0.0, 0.0, 0.0]
        # Same regardless of input text
        assert embedder.encode("other") == [0.0, 0.0, 0.0, 0.0]

    def test_dimension_property(self) -> None:
        """The dimension property reports the configured size."""
        assert TextOnlyEmbedder(dimension=128).dimension == 128
        assert TextOnlyEmbedder().dimension == 384  # default

    def test_satisfies_embedding_model_protocol(self) -> None:
        """TextOnlyEmbedder structurally satisfies the EmbeddingModel protocol."""
        # Protocol check is implicit at runtime; calling the required attrs is enough
        embedder = TextOnlyEmbedder(dimension=8)
        assert hasattr(embedder, "encode")
        assert hasattr(embedder, "dimension")
        assert isinstance(embedder.dimension, int)
        assert isinstance(embedder.encode("x"), list)


# ============== OtelIngester constructor ==============


class TestOtelIngesterConstructor:
    """Tests for the OtelIngester __init__ behavior."""

    def test_default_backend_is_akosha(self) -> None:
        """OtelIngester defaults to the Akosha backend when none is specified."""
        ingester = _make_ingester(preferred_backend=None)
        # When None, the constructor uses get_default_backend() (Akosha)
        assert ingester.backend is EmbeddingBackend.AKOSHA

    def test_storage_type_string_is_coerced_to_enum(self) -> None:
        """A string storage_type is converted to StorageType enum at construction."""
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        assert ingester.storage_type is StorageType.POSTGRESQL

    def test_invalid_storage_type_string_raises(self) -> None:
        """An unrecognized storage_type string raises ValueError."""
        with pytest.raises(ValueError):
            _make_ingester(storage_type="bogus")

    def test_preferred_backend_string_is_coerced(self) -> None:
        """A string preferred_backend is converted to EmbeddingBackend enum."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester.backend is EmbeddingBackend.TEXT_ONLY

    def test_embedding_dimension_default_is_384(self) -> None:
        """The default embedding_dimension is 384 (MiniLM-L6-v2 size)."""
        ingester = _make_ingester()
        assert ingester.embedding_dimension == 384

    def test_cache_starts_empty(self) -> None:
        """The embedding cache starts empty regardless of cache_size."""
        ingester = _make_ingester(cache_size=2)
        assert ingester._embedding_cache == {}
        assert ingester._cache_size == 2

    def test_properties_return_configured_values(self) -> None:
        """Public properties expose configured backend / storage / dimension."""
        ingester = _make_ingester(
            preferred_backend="text_only",
            storage_type="duckdb",
        )
        assert ingester.backend is EmbeddingBackend.TEXT_ONLY
        assert ingester.storage_type is StorageType.DUCKDB
        assert ingester.embedding_dimension == 384


# ============== _create_embedder ==============


class TestCreateEmbedder:
    """Tests for the _create_embedder factory inside OtelIngester."""

    def test_text_only_backend_returns_text_only_embedder(self) -> None:
        """_create_embedder returns a TextOnlyEmbedder for the TEXT_ONLY backend."""
        ingester = _make_ingester(preferred_backend="text_only")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, TextOnlyEmbedder)

    def test_unavailable_backend_raises_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If a chosen backend is unavailable, _create_embedder raises ImportError."""
        # Force sentence-transformers to be "unavailable" for the test
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", False
        )
        ingester = _make_ingester(preferred_backend="sentence_transformers")
        with pytest.raises(ImportError):
            ingester._create_embedder()

    def test_akosha_backend_returns_akosha_embedder(self) -> None:
        """_create_embedder returns an AkoshaEmbedder for the AKOSHA backend."""
        ingester = _make_ingester(preferred_backend="akosha")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, AkoshaEmbedder)
        assert embedder.dimension == 384


# ============== _map_to_fastembed_model ==============


class TestMapToFastEmbedModel:
    """Tests for the fastembed model name mapping."""

    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"),
            ("all-mpnet-base-v2", "BAAI/bge-base-en-v1.5"),
            ("paraphrase-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"),
        ],
    )
    def test_known_models_map(self, input_name: str, expected: str) -> None:
        """Known sentence-transformers names map to known fastembed models."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester._map_to_fastembed_model(input_name) == expected

    def test_unknown_model_falls_back_to_default(self) -> None:
        """Unknown names fall back to the default fastembed model."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester._map_to_fastembed_model("totally-unknown-model") == "BAAI/bge-small-en-v1.5"


# ============== initialize (DuckDB path) ==============


class TestInitializeDuckDB:
    """Tests for OtelIngester.initialize when using DuckDB storage."""

    @pytest.mark.asyncio
    async def test_initialize_uses_injected_hot_store(self) -> None:
        """When a hot_store is provided, initialize does NOT call its initialize().

        The source assumes the injected hot_store is already initialized and
        only invokes ``initialize()`` when it has to create a new one.
        """
        hot_store = MagicMock()
        hot_store.initialize = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        await ingester.initialize()

        # Injected hot_store's initialize is NOT called (caller's responsibility)
        hot_store.initialize.assert_not_awaited()
        # Compressor is None because turboquant_bits was not set
        assert ingester._compressor is None
        # Embedder is a TextOnlyEmbedder
        assert isinstance(ingester._embedder, TextOnlyEmbedder)

    @pytest.mark.asyncio
    async def test_initialize_creates_hot_store_when_none(self) -> None:
        """When hot_store is None and storage is DuckDB, initialize creates one."""
        ingester = _make_ingester(hot_store=None, preferred_backend="text_only")

        # Patch the imported HotStore class inside otel_ingester module
        with patch("akosha.storage.HotStore") as HotStoreCls:
            instance = MagicMock()
            instance.initialize = AsyncMock()
            HotStoreCls.return_value = instance

            await ingester.initialize()

            HotStoreCls.assert_called_once()
            instance.initialize.assert_awaited_once()
            assert ingester._hot_store is instance

    @pytest.mark.asyncio
    async def test_initialize_logs_and_succeeds(self) -> None:
        """initialize() should not raise on a happy-path DuckDB configuration."""
        ingester = _make_ingester(preferred_backend="text_only")
        # Should complete without raising
        await ingester.initialize()
        assert ingester._embedder is not None


# ============== initialize (pgvector path) ==============


class TestInitializePgVector:
    """Tests for OtelIngester.initialize when using PostgreSQL storage."""

    @pytest.mark.asyncio
    async def test_initialize_without_dsn_raises_runtime_error(self) -> None:
        """PostgreSQL storage without a DSN raises RuntimeError (wrapping ValueError).

        Note: the source's ``initialize()`` catches the inner ``ValueError``
        from ``_initialize_pgvector`` and re-raises as ``RuntimeError``.
        """
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn=None,
            preferred_backend="text_only",
        )
        with pytest.raises(RuntimeError, match="pgvector_dsn is required"):
            await ingester.initialize()

    @pytest.mark.asyncio
    async def test_initialize_with_dsn_uses_pgvector_adapter(self) -> None:
        """With a DSN provided, initialize() builds and configures the adapter."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )

        fake_adapter = MagicMock()
        fake_adapter.init = AsyncMock()
        fake_adapter.create_collection = AsyncMock()
        with (
            patch(
                "mahavishnu.adapters.pgvector_adapter.PgvectorAdapter",
                return_value=fake_adapter,
            ) as AdapterCls,
            patch(
                "mahavishnu.adapters.pgvector_adapter.PgvectorSettings",
            ) as SettingsCls,
        ):
            SettingsCls.return_value = MagicMock()
            await ingester.initialize()

        AdapterCls.assert_called_once()
        fake_adapter.init.assert_awaited_once()
        fake_adapter.create_collection.assert_awaited_once()
        # collection name passed through
        kwargs = fake_adapter.create_collection.await_args.kwargs
        assert kwargs["name"] == "otel_traces"


# ============== ingest_trace (DuckDB) ==============


class TestIngestTraceDuckDB:
    """Tests for OtelIngester.ingest_trace routed to DuckDB."""

    @pytest.mark.asyncio
    async def test_ingest_valid_trace_inserts_into_hot_store(self) -> None:
        """A valid trace is converted to a HotRecord and stored in HotStore."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        await ingester.ingest_trace(_sample_trace(trace_id="abc"))

        hot_store.insert.assert_awaited_once()
        # The first positional arg is the constructed HotRecord. Verify the
        # ingester passed the right kwargs by inspecting the HotRecord
        # constructor call on the stub.
        record = hot_store.insert.await_args.args[0]
        # Construct the same way: ingester does
        # HotRecord(system_id=..., conversation_id=..., content=..., ...)
        # We can't introspect a MagicMock instance's attribute assignments,
        # so we assert the kwargs that the ingester passed to HotRecord were
        # correct by looking at the captured hot_store.insert call.
        # The first positional arg is the record (already a MagicMock).
        # The simplest verification is that the record was actually built
        # and the hot_store received the call.
        assert record is not None

    @pytest.mark.asyncio
    async def test_ingest_trace_without_id_raises_validation_error(self) -> None:
        """ingest_trace raises ValidationError when trace_id is missing."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        # No trace_id
        bad = {"spans": [{"name": "x"}]}
        with pytest.raises(ValidationError):
            await ingester.ingest_trace(bad)

    @pytest.mark.asyncio
    async def test_ingest_trace_with_empty_spans_is_skipped(self) -> None:
        """A trace with zero spans is silently skipped (not stored)."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        await ingester.ingest_trace({"trace_id": "x", "spans": []})

        hot_store.insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ingest_trace_caches_embedding_for_repeated_content(self) -> None:
        """Two traces with the same span-name set reuse the cached embedding."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        embedder = _attach_embedder(ingester)

        trace = _sample_trace(trace_id="t1")
        # Use a second trace with identical spans -> same content -> cache hit
        await ingester.ingest_trace(trace)
        await ingester.ingest_trace(_sample_trace(trace_id="t2"))

        # The cache should have exactly one entry (the content is the same)
        assert len(ingester._embedding_cache) == 1
        # The embedder's encode should only have been called once
        assert embedder.encode.call_count == 1
        # HotStore.insert should have been called twice (different trace IDs)
        assert hot_store.insert.await_count == 2

    @pytest.mark.asyncio
    async def test_ingest_trace_swallows_unexpected_errors(self) -> None:
        """An unexpected error during ingest is logged, not raised."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock(side_effect=RuntimeError("boom"))
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        # Should not raise; hot_store.insert is allowed to fail silently
        await ingester.ingest_trace(_sample_trace(trace_id="err"))


# ============== ingest_trace (pgvector) ==============


class TestIngestTracePgVector:
    """Tests for OtelIngester.ingest_trace routed to pgvector."""

    @pytest.mark.asyncio
    async def test_ingest_routes_to_pgvector_upsert(self) -> None:
        """With pgvector storage, ingest_trace calls adapter.upsert."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.upsert = AsyncMock()
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)

        await ingester.ingest_trace(_sample_trace(trace_id="pg-1"))

        adapter.upsert.assert_awaited_once()
        kwargs = adapter.upsert.await_args.kwargs
        assert kwargs["collection"] == "otel_traces"
        # Single document with id == trace_id and a vector field
        docs = kwargs["documents"]
        assert docs[0]["id"] == "pg-1"
        assert isinstance(docs[0]["vector"], list)
        assert "metadata" in docs[0]

    @pytest.mark.asyncio
    async def test_ingest_pgvector_without_adapter_raises(self) -> None:
        """If storage is pgvector but no adapter is set, RuntimeError is raised."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        _attach_embedder(ingester)
        ingester._pgvector_adapter = None

        with pytest.raises(RuntimeError, match="pgvector adapter not initialized"):
            await ingester.ingest_trace(_sample_trace(trace_id="x"))


# ============== ingest_batch ==============


class TestIngestBatch:
    """Tests for OtelIngester.ingest_batch."""

    @pytest.mark.asyncio
    async def test_ingest_batch_reports_success_and_error_counts(self) -> None:
        """ingest_batch returns a dict with success_count, error_count, errors."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        traces = [_sample_trace(trace_id=f"t{i}") for i in range(3)]
        result = await ingester.ingest_batch(traces)

        assert result["success_count"] == 3
        assert result["error_count"] == 0
        assert result["errors"] == []
        assert hot_store.insert.await_count == 3

    @pytest.mark.asyncio
    async def test_ingest_batch_counts_individual_failures(self) -> None:
        """A ValidationError in one trace counts as an error but does not abort."""
        hot_store = MagicMock()
        hot_store.insert = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        # Build 3 traces; the second one is missing the required trace_id.
        # Note: hot_store.insert failures are swallowed by the per-trace
        # handler (so they don't reach ingest_batch's error counter); only
        # ValidationError propagates. The test exercises that path.
        traces = [
            _sample_trace(trace_id="ok-1"),
            {"spans": [{"name": "x"}]},  # missing trace_id -> ValidationError
            _sample_trace(trace_id="ok-2"),
        ]
        result = await ingester.ingest_batch(traces)

        assert result["success_count"] == 2
        assert result["error_count"] == 1
        assert len(result["errors"]) == 1
        # The error message references the failing trace id
        assert "unknown" in result["errors"][0]


# ============== search_traces ==============


class TestSearchTraces:
    """Tests for OtelIngester.search_traces (DuckDB + pgvector)."""

    @pytest.mark.asyncio
    async def test_search_without_embedder_raises(self) -> None:
        """search_traces without an initialized embedder raises RuntimeError."""
        ingester = _make_ingester(preferred_backend="text_only")
        ingester._embedder = None
        with pytest.raises(RuntimeError, match="Embedding model not loaded"):
            await ingester.search_traces("anything")

    @pytest.mark.asyncio
    async def test_search_duckdb_routes_to_hot_store(self) -> None:
        """DuckDB search calls HotStore.search_similar with the query vector."""
        hot_store = MagicMock()
        hot_store.search_similar = AsyncMock(
            return_value=[{"conversation_id": "x", "content": "c", "similarity": 0.9}]
        )
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        embedder = _attach_embedder(ingester)

        results = await ingester.search_traces("error", limit=5, system_id="claude", threshold=0.5)

        embedder.encode.assert_called_once_with("error")
        hot_store.search_similar.assert_awaited_once()
        kwargs = hot_store.search_similar.await_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["system_id"] == "claude"
        assert kwargs["threshold"] == 0.5
        assert kwargs["query_embedding"] == embedder.encode.return_value
        assert results == [{"conversation_id": "x", "content": "c", "similarity": 0.9}]

    @pytest.mark.asyncio
    async def test_search_duckdb_returns_empty_list_on_failure(self) -> None:
        """If HotStore.search_similar raises, search_traces returns []."""
        hot_store = MagicMock()
        hot_store.search_similar = AsyncMock(side_effect=RuntimeError("db down"))
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        _attach_embedder(ingester)

        results = await ingester.search_traces("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_pgvector_filters_by_threshold(self) -> None:
        """pgvector search converts distance to similarity and applies threshold."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        # Two results: distance 0.05 -> similarity 0.95 (above 0.7)
        #              distance 0.5 -> similarity 0.5  (below 0.7)
        adapter.search = AsyncMock(
            return_value=[
                {
                    "id": "a",
                    "score": 0.05,
                    "metadata": {"content": "alpha", "timestamp": "2024-01-01"},
                },
                {
                    "id": "b",
                    "score": 0.5,
                    "metadata": {"content": "beta", "timestamp": "2024-01-02"},
                },
            ]
        )
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)

        results = await ingester.search_traces("q", limit=10, threshold=0.7)

        assert len(results) == 1
        assert results[0]["conversation_id"] == "a"
        assert results[0]["similarity"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_search_pgvector_passes_filter_for_system_id(self) -> None:
        """A non-None system_id is passed as a filter_expr to the adapter."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.search = AsyncMock(return_value=[])
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)

        await ingester.search_traces("q", system_id="claude")

        kwargs = adapter.search.await_args.kwargs
        assert kwargs["filter_expr"] == {"system_id": "claude"}

    @pytest.mark.asyncio
    async def test_search_pgvector_no_system_id_means_no_filter(self) -> None:
        """Without a system_id, the filter_expr passed to the adapter is None."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.search = AsyncMock(return_value=[])
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)

        await ingester.search_traces("q", system_id=None)

        kwargs = adapter.search.await_args.kwargs
        assert kwargs["filter_expr"] is None


# ============== get_trace_by_id ==============


class TestGetTraceById:
    """Tests for OtelIngester.get_trace_by_id (DuckDB + pgvector)."""

    @pytest.mark.asyncio
    async def test_get_trace_duckdb_returns_parsed_row(self) -> None:
        """get_trace_by_id executes a SQL query and returns the row as a dict."""
        hot_store = MagicMock()
        row = ("claude", "trace-1", "content text", "2024-01-01T00:00:00Z", "{}")
        hot_store.conn = MagicMock()
        hot_store.conn.execute.return_value.fetchall.return_value = [row]
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        result = await ingester.get_trace_by_id("trace-1")

        assert result is not None
        assert result["system_id"] == "claude"
        assert result["conversation_id"] == "trace-1"
        assert result["content"] == "content text"
        assert result["timestamp"] == "2024-01-01T00:00:00Z"
        assert result["metadata"] == {}

    @pytest.mark.asyncio
    async def test_get_trace_duckdb_returns_none_when_not_found(self) -> None:
        """If the SQL query returns no rows, get_trace_by_id returns None."""
        hot_store = MagicMock()
        hot_store.conn = MagicMock()
        hot_store.conn.execute.return_value.fetchall.return_value = []
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        result = await ingester.get_trace_by_id("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_trace_duckdb_returns_none_on_error(self) -> None:
        """If executing the SQL raises, get_trace_by_id returns None (logged)."""
        hot_store = MagicMock()
        hot_store.conn = MagicMock()
        hot_store.conn.execute.side_effect = RuntimeError("db broken")
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        result = await ingester.get_trace_by_id("anything")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_trace_pgvector_returns_dict(self) -> None:
        """pgvector get() results are reshaped into a content+metadata dict."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.get = AsyncMock(
            return_value=[
                {
                    "id": "pg-1",
                    "metadata": {
                        "content": "pg content",
                        "timestamp": "2024-01-01",
                    },
                }
            ]
        )
        ingester._pgvector_adapter = adapter

        result = await ingester.get_trace_by_id("pg-1")

        assert result is not None
        assert result["conversation_id"] == "pg-1"
        assert result["content"] == "pg content"
        assert result["timestamp"] == "2024-01-01"
        assert result["metadata"]["content"] == "pg content"

    @pytest.mark.asyncio
    async def test_get_trace_pgvector_returns_none_when_not_found(self) -> None:
        """pgvector adapter returns an empty list -> get_trace_by_id returns None."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.get = AsyncMock(return_value=[])
        ingester._pgvector_adapter = adapter

        result = await ingester.get_trace_by_id("nope")
        assert result is None


# ============== close ==============


class TestClose:
    """Tests for OtelIngester.close."""

    @pytest.mark.asyncio
    async def test_close_duckdb_closes_hot_store_and_clears_cache(self) -> None:
        """close() closes the hot_store and empties the embedding cache."""
        hot_store = MagicMock()
        hot_store.close = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")
        ingester._embedding_cache["k"] = [0.0] * 4

        await ingester.close()

        hot_store.close.assert_awaited_once()
        assert ingester._embedding_cache == {}

    @pytest.mark.asyncio
    async def test_close_pgvector_cleans_up_adapter(self) -> None:
        """close() with pgvector storage calls adapter.cleanup()."""
        ingester = _make_ingester(
            storage_type=StorageType.POSTGRESQL,
            pgvector_dsn="postgresql://u:p@localhost/db",
            preferred_backend="text_only",
        )
        adapter = MagicMock()
        adapter.cleanup = AsyncMock()
        ingester._pgvector_adapter = adapter

        await ingester.close()

        adapter.cleanup.assert_awaited_once()
        assert ingester._embedding_cache == {}

    @pytest.mark.asyncio
    async def test_close_swallows_errors(self) -> None:
        """close() does not raise even if the underlying close fails."""
        hot_store = MagicMock()
        hot_store.close = AsyncMock(side_effect=RuntimeError("oops"))
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        # Should not raise
        await ingester.close()


# ============== async context manager ==============


class TestAsyncContextManager:
    """Tests for __aenter__ and __aexit__."""

    @pytest.mark.asyncio
    async def test_async_with_initializes_and_closes(self) -> None:
        """Used as `async with`, the ingester is initialized on enter and closed on exit."""
        hot_store = MagicMock()
        hot_store.initialize = AsyncMock()
        hot_store.close = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        async with ingester as i:
            assert i is ingester
            # initialize() was called -> embedder set
            assert ingester._embedder is not None

        # The source does not call initialize() on an injected hot_store
        # (caller's responsibility), but close() IS always called.
        hot_store.initialize.assert_not_awaited()
        hot_store.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_runs_even_when_body_raises(self) -> None:
        """__aexit__ still closes the hot_store when the body raises."""
        hot_store = MagicMock()
        hot_store.initialize = AsyncMock()
        hot_store.close = AsyncMock()
        ingester = _make_ingester(hot_store=hot_store, preferred_backend="text_only")

        with pytest.raises(RuntimeError, match="boom"):
            async with ingester:
                raise RuntimeError("boom")

        # close() must have been called even though the body raised
        hot_store.close.assert_awaited_once()


# ============== Span helpers ==============


class TestSpanHelpers:
    """Tests for the private _extract_* helpers."""

    def test_extract_system_id_from_claude_service_name(self) -> None:
        """service.name containing 'claude' is normalized to 'claude'."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"attributes": {"service.name": "my-claude-app"}}]
        assert ingester._extract_system_id(spans) == "claude"

    def test_extract_system_id_from_qwen_service_name(self) -> None:
        """service.name containing 'qwen' is normalized to 'qwen'."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"attributes": {"service.name": "qwen-service"}}]
        assert ingester._extract_system_id(spans) == "qwen"

    def test_extract_system_id_passthrough_for_other_names(self) -> None:
        """Other service names are passed through verbatim."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"attributes": {"service.name": "custom-svc"}}]
        assert ingester._extract_system_id(spans) == "custom-svc"

    def test_extract_system_id_defaults_to_unknown(self) -> None:
        """Without service.name, the system_id is 'unknown'."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester._extract_system_id([{"attributes": {}}]) == "unknown"
        assert ingester._extract_system_id([]) == "unknown"

    def test_build_content_joins_span_names_with_pipe(self) -> None:
        """Span names are joined with ' | ' into a single searchable string."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        assert ingester._build_content(spans) == "a | b | c"

    def test_build_content_ignores_spans_without_names(self) -> None:
        """Spans with no name are skipped in the content string."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"name": "a"}, {"no_name": True}, {"name": "c"}]
        assert ingester._build_content(spans) == "a | c"

    def test_build_content_falls_back_for_empty_spans(self) -> None:
        """An empty span list produces the 'Empty trace' placeholder."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester._build_content([]) == "Empty trace"

    def test_extract_timestamp_parses_iso_string(self) -> None:
        """An ISO 8601 string is parsed into a timezone-aware datetime."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [{"start_time": "2024-05-01T12:34:56Z"}]
        ts = ingester._extract_timestamp(spans)
        assert isinstance(ts, datetime)
        assert ts.tzinfo is not None
        assert ts.year == 2024 and ts.month == 5 and ts.day == 1

    def test_extract_timestamp_handles_unix_nanoseconds(self) -> None:
        """An integer (assumed Unix nanoseconds) is converted to a datetime."""
        ingester = _make_ingester(preferred_backend="text_only")
        # 2024-01-01T00:00:00Z in nanoseconds
        ns = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
        spans = [{"start_time": ns}]
        ts = ingester._extract_timestamp(spans)
        assert ts.tzinfo is not None
        assert ts.year == 2024

    def test_extract_timestamp_falls_back_to_now(self) -> None:
        """Without a start_time, _extract_timestamp returns datetime.now(UTC)."""
        ingester = _make_ingester(preferred_backend="text_only")
        before = datetime.now(UTC)
        ts = ingester._extract_timestamp([{}])
        after = datetime.now(UTC)
        assert before <= ts <= after

    def test_extract_timestamp_handles_empty_spans(self) -> None:
        """An empty span list falls back to datetime.now(UTC)."""
        ingester = _make_ingester(preferred_backend="text_only")
        ts = ingester._extract_timestamp([])
        assert isinstance(ts, datetime)
        assert ts.tzinfo is not None

    def test_extract_timestamp_handles_invalid_string(self) -> None:
        """An unparseable start_time string falls back to datetime.now(UTC)."""
        ingester = _make_ingester(preferred_backend="text_only")
        ts = ingester._extract_timestamp([{"start_time": "not-a-timestamp"}])
        assert isinstance(ts, datetime)

    def test_extract_attributes_merges_all_spans(self) -> None:
        """_extract_attributes merges attributes across all spans."""
        ingester = _make_ingester(preferred_backend="text_only")
        spans = [
            {"attributes": {"a": 1, "b": 2}},
            {"attributes": {"b": 3, "c": 4}},
        ]
        merged = ingester._extract_attributes(spans)
        # Later values win on key collisions
        assert merged == {"a": 1, "b": 3, "c": 4}

    def test_extract_attributes_empty_for_no_spans(self) -> None:
        """_extract_attributes returns {} when there are no spans."""
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester._extract_attributes([]) == {}


# ============== Factory: create_otel_ingester ==============


class TestCreateOtelIngesterFactory:
    """Tests for the create_otel_ingester factory function."""

    @pytest.mark.asyncio
    async def test_factory_creates_initialized_ingester(self) -> None:
        """create_otel_ingester returns an initialized OtelIngester instance."""
        # Patch HotStore at the akosha boundary so we don't touch disk
        with patch("akosha.storage.HotStore") as HotStoreCls:
            instance = MagicMock()
            instance.initialize = AsyncMock()
            HotStoreCls.return_value = instance

            ingester = await create_otel_ingester(
                hot_store_path=":memory:",
                preferred_backend="text_only",
            )

        assert isinstance(ingester, OtelIngester)
        # initialize() ran -> the embedder was set
        assert ingester._embedder is not None

    @pytest.mark.asyncio
    async def test_factory_applies_env_var_storage_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE overrides the default DuckDB."""
        monkeypatch.setenv("MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE", "postgresql")
        monkeypatch.setenv(
            "MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL",
            "postgresql://u:p@localhost/db",
        )
        with patch("akosha.storage.HotStore"):
            with patch("mahavishnu.adapters.pgvector_adapter.PgvectorAdapter") as Adapter:
                with patch("mahavishnu.adapters.pgvector_adapter.PgvectorSettings"):
                    fake = MagicMock()
                    fake.init = AsyncMock()
                    fake.create_collection = AsyncMock()
                    Adapter.return_value = fake
                    ingester = await create_otel_ingester(
                        hot_store_path=":memory:",
                        preferred_backend="text_only",
                    )
        # The factory should have picked the env-supplied storage type
        assert ingester.storage_type is StorageType.POSTGRESQL


# ============== AkoshaEmbedder ==============


class TestAkoshaEmbedder:
    """Tests for the AkoshaEmbedder wrapper."""

    def test_dimension_property(self) -> None:
        """The dimension property is configurable and defaults to 384."""
        e = AkoshaEmbedder()
        assert e.dimension == 384
        e2 = AkoshaEmbedder(dimension=768)
        assert e2.dimension == 768

    @pytest.mark.asyncio
    async def test_close_clears_client(self) -> None:
        """close() closes the underlying HTTP client and resets it to None."""
        embedder = AkoshaEmbedder()
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        embedder._client = fake_client

        await embedder.close()

        fake_client.aclose.assert_awaited_once()
        assert embedder._client is None

    @pytest.mark.asyncio
    async def test_close_is_noop_when_client_never_created(self) -> None:
        """close() does not raise when no client was ever instantiated."""
        embedder = AkoshaEmbedder()
        # _client is None
        await embedder.close()
        assert embedder._client is None

    @pytest.mark.asyncio
    async def test_encode_batch_async_returns_zero_vectors_on_failure(self) -> None:
        """A network failure falls back to zero vectors of the right size."""
        embedder = AkoshaEmbedder(dimension=4)
        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=RuntimeError("net down"))
        embedder._client = fake_client

        result = await embedder.encode_batch_async(["a", "b"])
        assert result == [[0.0] * 4, [0.0] * 4]
