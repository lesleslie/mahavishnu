"""Coverage tests for mahavishnu.ingesters.otel_ingester.

Covers all major paths in OTelIngester and friends, including:
* Enums and Protocol
* AkoshaEmbedder (sync encode wrapper, async _encode_async, batch async, check_available, close)
* SentenceTransformersWrapper / FastEmbedWrapper (unavailable paths)
* TextOnlyEmbedder
* OtelIngester constructor paths and properties
* _create_embedder across all backends
* _map_to_fastembed_model
* initialize (DuckDB + pgvector paths, fallback backends, turboquant init)
* _initialize_pgvector (no DSN)
* ingest_trace / ingest_batch (DuckDB + pgvector, validation, errors)
* search_traces / _search_duckdb / _search_pgvector
* get_trace_by_id / _get_trace_duckdb / _get_trace_pgvector
* close
* _get_embedding (no embedder, errors, caching)
* _extract_system_id, _build_content, _extract_timestamp, _extract_attributes
* async context manager
* create_otel_ingester factory
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
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
    FastEmbedWrapper,
    OtelIngester,
    SentenceTransformersWrapper,
    StorageType,
    TextOnlyEmbedder,
    create_otel_ingester,
    get_available_backends,
    get_default_backend,
)

pytestmark = pytest.mark.unit


# ============== Akosha stubs for module-level safety ==============
def _install_akosha_stub() -> None:
    """Stub akosha.models and akosha.storage.models to bypass Pydantic rebuild bug."""
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
        sys.modules.setdefault(module_name, stub)


_install_akosha_stub()


# ============== Helpers ==============


def _fake_embedding(dim: int = 384) -> list[float]:
    return [float(i) / dim for i in range(dim)]


def _make_ingester(**kwargs: Any) -> OtelIngester:
    """Construct an OtelIngester with text_only backend by default."""
    kwargs.setdefault("preferred_backend", "text_only")
    return OtelIngester(**kwargs)


def _attach_embedder(ingester: OtelIngester, embedding: list[float] | None = None) -> MagicMock:
    """Attach a mock embedder to an ingester."""
    mock_embedder = MagicMock(spec=EmbeddingModel)
    mock_embedder.encode.return_value = embedding if embedding is not None else _fake_embedding()
    mock_embedder.dimension = 384
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
        ],
    }
    trace.update(overrides)
    return trace


# ============== Enums / Protocol ==============


class TestEnumsProtocol:
    def test_embedding_backend_values(self) -> None:
        assert {b.value for b in EmbeddingBackend} == {
            "akosha",
            "sentence_transformers",
            "fastembed",
            "text_only",
        }

    def test_storage_type_values(self) -> None:
        assert {s.value for s in StorageType} == {"duckdb", "postgresql"}

    def test_text_only_embedder_satisfies_protocol(self) -> None:
        """TextOnlyEmbedder implements the EmbeddingModel Protocol structurally."""
        embedder = TextOnlyEmbedder(dimension=8)
        # isinstance check on a runtime_checkable Protocol
        assert isinstance(embedder, EmbeddingModel)
        assert embedder.encode("foo") == [0.0] * 8
        assert embedder.dimension == 8


# ============== get_available_backends / get_default_backend ==============


class TestBackendDiscovery:
    def test_includes_text_only(self) -> None:
        assert EmbeddingBackend.TEXT_ONLY in get_available_backends()

    def test_default_is_akosha(self) -> None:
        assert get_default_backend() is EmbeddingBackend.AKOSHA

    def test_akosha_is_first(self) -> None:
        backends = get_available_backends()
        assert backends[0] is EmbeddingBackend.AKOSHA
        assert backends[-1] is EmbeddingBackend.TEXT_ONLY


# ============== TextOnlyEmbedder ==============


class TestTextOnlyEmbedder:
    def test_encode_returns_zeros(self) -> None:
        embedder = TextOnlyEmbedder(dimension=4)
        assert embedder.encode("anything") == [0.0] * 4
        assert embedder.encode("other") == [0.0] * 4

    def test_default_dimension_384(self) -> None:
        assert TextOnlyEmbedder().dimension == 384

    def test_custom_dimension(self) -> None:
        assert TextOnlyEmbedder(dimension=128).dimension == 128


# ============== SentenceTransformersWrapper ==============


class TestSentenceTransformersWrapper:
    def test_raises_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", False
        )
        with pytest.raises(ImportError, match="sentence-transformers not available"):
            SentenceTransformersWrapper()

    def test_encode_and_dimension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sentence-transformers is available, encode returns the model output."""
        fake_model = MagicMock()
        fake_array = MagicMock()
        fake_array.tolist.return_value = _fake_embedding()
        fake_model.encode.return_value = fake_array

        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", True
        )
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SentenceTransformer",
            MagicMock(return_value=fake_model),
        )

        wrapper = SentenceTransformersWrapper()
        result = wrapper.encode("hello")
        assert result == _fake_embedding()
        assert wrapper.dimension == 384


# ============== FastEmbedWrapper ==============


class TestFastEmbedWrapper:
    def test_raises_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.FASTEMBED_AVAILABLE", False
        )
        with pytest.raises(ImportError, match="fastembed not available"):
            FastEmbedWrapper()

    def test_encode_and_dimension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When fastembed is available, encode() pulls the first result."""
        fake_array = MagicMock()
        fake_array.tolist.return_value = _fake_embedding()
        fake_model = MagicMock()
        fake_model.embed.return_value = iter([fake_array])

        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.FASTEMBED_AVAILABLE", True
        )
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.TextEmbedding",
            MagicMock(return_value=fake_model),
        )

        wrapper = FastEmbedWrapper()
        result = wrapper.encode("hello")
        assert result == _fake_embedding()
        assert wrapper.dimension == 384


# ============== AkoshaEmbedder ==============


class TestAkoshaEmbedder:
    def test_init_defaults(self) -> None:
        embedder = AkoshaEmbedder()
        assert embedder._akosha_url == "http://localhost:8682/mcp"
        assert embedder._timeout == 30.0
        assert embedder._dimension == 384
        assert embedder._client is None
        assert embedder._available is None

    def test_init_custom_values(self) -> None:
        embedder = AkoshaEmbedder(
            akosha_url="http://custom:9999/mcp",
            timeout=10.0,
            dimension=768,
        )
        assert embedder._akosha_url == "http://custom:9999/mcp"
        assert embedder._timeout == 10.0
        assert embedder._dimension == 768

    def test_dimension_property(self) -> None:
        embedder = AkoshaEmbedder(dimension=512)
        assert embedder.dimension == 512

    def test_encode_no_running_loop(self) -> None:
        """encode() with no running event loop calls asyncio.run()."""
        embedder = AkoshaEmbedder()

        async def _fake(text: str) -> list[float]:
            return [0.1] * embedder._dimension

        with patch.object(embedder, "_encode_async", _fake):
            result = embedder.encode("hello")
        assert result == [0.1] * embedder._dimension

    def test_encode_in_running_loop(self) -> None:
        """encode() with a running event loop uses ThreadPoolExecutor."""
        embedder = AkoshaEmbedder()

        async def _fake(text: str) -> list[float]:
            return [0.2] * embedder._dimension

        with patch.object(embedder, "_encode_async", _fake):
            # When there is a running loop, the function dispatches to a thread
            async def _runner() -> list[float]:
                return embedder.encode("hi")

            result = asyncio.run(_runner())
        assert result == [0.2] * embedder._dimension

    async def test_encode_async_success(self) -> None:
        """_encode_async POSTs to /tools/call and parses the JSON content."""
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"embedding": [0.5] * 384}),
                }
            ]
        }

        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            result = await embedder._encode_async("test")
        assert result == [0.5] * 384

    async def test_encode_async_unexpected_response(self) -> None:
        """Unexpected content shape returns a zero vector."""
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"no_content": True}

        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            result = await embedder._encode_async("test")
        assert result == [0.0] * 384

    async def test_encode_async_exception_returns_zeros(self) -> None:
        embedder = AkoshaEmbedder()
        with patch.object(embedder, "_get_client", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await embedder._encode_async("test")
        assert result == [0.0] * 384

    async def test_check_available_success(self) -> None:
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.status_code = 200

        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            available = await embedder.check_available()
        assert available is True
        assert embedder._available is True
        # Second call should not re-check
        with patch.object(embedder, "_get_client", AsyncMock(side_effect=AssertionError("should not be called"))):
            available2 = await embedder.check_available()
        assert available2 is True

    async def test_check_available_failure(self) -> None:
        embedder = AkoshaEmbedder()
        with patch.object(embedder, "_get_client", AsyncMock(side_effect=RuntimeError("nope"))):
            available = await embedder.check_available()
        assert available is False
        assert embedder._available is False

    async def test_check_available_non_200(self) -> None:
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.status_code = 500
        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            available = await embedder.check_available()
        assert available is False

    async def test_encode_batch_async_success(self) -> None:
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"embeddings": [[0.1] * 384, [0.2] * 384]}),
                }
            ]
        }
        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            result = await embedder.encode_batch_async(["a", "b"])
        assert result == [[0.1] * 384, [0.2] * 384]

    async def test_encode_batch_async_unexpected(self) -> None:
        embedder = AkoshaEmbedder()
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"content": []}
        with patch.object(embedder, "_get_client", AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response)))):
            result = await embedder.encode_batch_async(["a", "b"])
        assert result == [[0.0] * 384, [0.0] * 384]

    async def test_encode_batch_async_exception(self) -> None:
        embedder = AkoshaEmbedder()
        with patch.object(embedder, "_get_client", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await embedder.encode_batch_async(["a"])
        assert result == [[0.0] * 384]

    async def test_get_client_lazy(self) -> None:
        embedder = AkoshaEmbedder()
        client = await embedder._get_client()
        # Second call returns the same client instance
        client2 = await embedder._get_client()
        assert client is client2

    async def test_close_releases_client(self) -> None:
        embedder = AkoshaEmbedder()
        # Force client creation
        await embedder._get_client()
        assert embedder._client is not None
        await embedder.close()
        assert embedder._client is None

    async def test_close_when_no_client(self) -> None:
        embedder = AkoshaEmbedder()
        # No client ever created
        await embedder.close()
        assert embedder._client is None


# ============== OtelIngester constructor / properties ==============


class TestOtelIngesterConstructor:
    def test_string_storage_type_coerced(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        assert ingester.storage_type is StorageType.POSTGRESQL

    def test_invalid_storage_type_raises(self) -> None:
        with pytest.raises(ValueError):
            _make_ingester(storage_type="bogus")

    def test_string_preferred_backend_coerced(self) -> None:
        ingester = _make_ingester(preferred_backend="text_only")
        assert ingester.backend is EmbeddingBackend.TEXT_ONLY

    def test_default_backend_is_akosha(self) -> None:
        ingester = _make_ingester(preferred_backend=None)
        assert ingester.backend is EmbeddingBackend.AKOSHA

    def test_default_embedding_dimension(self) -> None:
        ingester = _make_ingester()
        assert ingester.embedding_dimension == 384

    def test_cache_size_default(self) -> None:
        ingester = _make_ingester()
        assert ingester._cache_size == 1000

    def test_pgvector_collection_default(self) -> None:
        ingester = _make_ingester()
        assert ingester._pgvector_collection == "otel_traces"

    def test_duckdb_path_default(self) -> None:
        ingester = _make_ingester()
        assert ingester._duckdb_path == ":memory:"

    def test_akosha_url_default(self) -> None:
        ingester = _make_ingester()
        assert ingester._akosha_url == "http://localhost:8682/mcp"

    def test_hot_store_kept(self) -> None:
        hot = MagicMock(name="hot_store")
        ingester = _make_ingester(hot_store=hot)
        assert ingester._hot_store is hot

    def test_embedding_cache_empty(self) -> None:
        ingester = _make_ingester()
        assert ingester._embedding_cache == {}


# ============== _create_embedder / _map_to_fastembed_model ==============


class TestCreateEmbedder:
    def test_akosha(self) -> None:
        ingester = _make_ingester(preferred_backend="akosha")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, AkoshaEmbedder)
        assert embedder.dimension == 384

    def test_text_only(self) -> None:
        ingester = _make_ingester(preferred_backend="text_only")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, TextOnlyEmbedder)

    def test_sentence_transformers_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", False
        )
        ingester = _make_ingester(preferred_backend="sentence_transformers")
        with pytest.raises(ImportError, match="sentence-transformers is not available"):
            ingester._create_embedder()

    def test_fastembed_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.FASTEMBED_AVAILABLE", False
        )
        ingester = _make_ingester(preferred_backend="fastembed")
        with pytest.raises(ImportError, match="fastembed is not available"):
            ingester._create_embedder()

    def test_fastembed_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_model = MagicMock()
        fake_array = MagicMock()
        fake_array.tolist.return_value = _fake_embedding()
        fake_model.embed.return_value = iter([fake_array])

        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.FASTEMBED_AVAILABLE", True
        )
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.TextEmbedding",
            MagicMock(return_value=fake_model),
        )

        ingester = _make_ingester(preferred_backend="fastembed", embedding_model="all-mpnet-base-v2")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, FastEmbedWrapper)

    def test_sentence_transformers_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_model = MagicMock()
        fake_array = MagicMock()
        fake_array.tolist.return_value = _fake_embedding()
        fake_model.encode.return_value = fake_array

        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", True
        )
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SentenceTransformer",
            MagicMock(return_value=fake_model),
        )

        ingester = _make_ingester(preferred_backend="sentence_transformers")
        embedder = ingester._create_embedder()
        assert isinstance(embedder, SentenceTransformersWrapper)


class TestMapToFastEmbedModel:
    def test_known_mappings(self) -> None:
        ingester = _make_ingester()
        assert ingester._map_to_fastembed_model("all-MiniLM-L6-v2") == "BAAI/bge-small-en-v1.5"
        assert ingester._map_to_fastembed_model("all-mpnet-base-v2") == "BAAI/bge-base-en-v1.5"
        assert ingester._map_to_fastembed_model("paraphrase-MiniLM-L6-v2") == "BAAI/bge-small-en-v1.5"

    def test_unknown_mapping(self) -> None:
        ingester = _make_ingester()
        assert ingester._map_to_fastembed_model("mystery") == "BAAI/bge-small-en-v1.5"


# ============== initialize / _initialize_duckdb / _initialize_pgvector ==============


class TestInitialize:
    async def test_initialize_duckdb(self) -> None:
        ingester = _make_ingester()
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            await ingester.initialize()
        assert ingester._hot_store is mock_hot
        mock_hot.initialize.assert_awaited_once()

    async def test_initialize_duckdb_with_existing_hot_store(self) -> None:
        existing = AsyncMock()
        existing.initialize = AsyncMock()
        ingester = _make_ingester(hot_store=existing)
        with patch("akosha.storage.HotStore") as cls:
            await ingester.initialize()
        cls.assert_not_called()
        existing.initialize.assert_not_called()

    async def test_initialize_pgvector_no_dsn(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn=None)
        with pytest.raises(RuntimeError, match="OTel ingester initialization failed"):
            await ingester.initialize()

    async def test_initialize_pgvector_with_dsn(self) -> None:
        ingester = _make_ingester(
            storage_type="postgresql", pgvector_dsn="postgres://localhost/db"
        )
        fake_adapter = AsyncMock()
        fake_adapter.init = AsyncMock()
        fake_adapter.create_collection = AsyncMock()
        with patch(
            "mahavishnu.adapters.pgvector_adapter.PgvectorAdapter",
            return_value=fake_adapter,
        ) as AdapterCls, patch(
            "mahavishnu.adapters.pgvector_adapter.PgvectorSettings",
            return_value=MagicMock(),
        ) as SettingsCls:
            await ingester.initialize()
        assert ingester._pgvector_adapter is fake_adapter
        fake_adapter.init.assert_awaited_once()
        fake_adapter.create_collection.assert_awaited_once()

    async def test_initialize_runtime_error(self) -> None:
        ingester = _make_ingester()
        with patch.object(ingester, "_initialize_duckdb", AsyncMock(side_effect=ValueError("boom"))):
            with pytest.raises(RuntimeError, match="OTel ingester initialization failed"):
                await ingester.initialize()

    async def test_initialize_uses_turboquant_when_available(self) -> None:
        ingester = _make_ingester(turboquant_bits=4)
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_compressor = MagicMock()
        mock_compressor.available = True
        mock_compressor.estimate_savings.return_value = {
            "uncompressed_kb": 1500.0,
            "compressed_kb": 188.0,
        }
        with patch("akosha.storage.HotStore", return_value=mock_hot), patch(
            "mahavishnu.ingesters.otel_ingester.TurboQuantCompressor",
            return_value=mock_compressor,
        ):
            await ingester.initialize()
        assert ingester._compressor is mock_compressor

    async def test_initialize_turboquant_unavailable(self) -> None:
        ingester = _make_ingester(turboquant_bits=4)
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_compressor = MagicMock()
        mock_compressor.available = False
        with patch("akosha.storage.HotStore", return_value=mock_hot), patch(
            "mahavishnu.ingesters.otel_ingester.TurboQuantCompressor",
            return_value=mock_compressor,
        ):
            await ingester.initialize()
        assert ingester._compressor is mock_compressor

    async def test_initialize_import_error_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ingester = _make_ingester(preferred_backend="sentence_transformers")
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        monkeypatch.setattr(
            "mahavishnu.ingesters.otel_ingester.SENTENCE_TRANSFORMERS_AVAILABLE", False
        )
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            await ingester.initialize()
        # After fallback, embedder should be set
        assert ingester._embedder is not None
        # And backend should have moved to a working one (TEXT_ONLY eventually)
        assert ingester.backend in (EmbeddingBackend.TEXT_ONLY, EmbeddingBackend.AKOSHA)

    async def test_initialize_embedder_already_loaded(self) -> None:
        ingester = _make_ingester()
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        embedder = MagicMock()
        embedder.dimension = 768
        ingester._embedder = embedder
        with patch("akosha.storage.HotStore", return_value=mock_hot), patch.object(
            ingester, "_create_embedder"
        ) as create:
            await ingester.initialize()
        create.assert_not_called()


# ============== _try_fallback_backends ==============


class TestTryFallbackBackends:
    def test_falls_back_to_text_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ingester = _make_ingester(preferred_backend="akosha")
        # Make every embedder creation fail
        with patch.object(ingester, "_create_embedder", side_effect=ImportError("nope")):
            result = ingester._try_fallback_backends()
        assert isinstance(result, TextOnlyEmbedder)
        assert ingester.backend is EmbeddingBackend.TEXT_ONLY

    def test_finds_working_fallback(self) -> None:
        ingester = _make_ingester(preferred_backend="akosha")
        # First two calls fail, third succeeds
        success = MagicMock()
        success.dimension = 256
        with patch.object(ingester, "_create_embedder", side_effect=[ImportError("a"), ImportError("b"), success]):
            result = ingester._try_fallback_backends()
        assert result is success


# ============== ingest_trace / ingest_batch ==============


class TestIngestTraceDuckdb:
    async def test_ingest_valid_trace(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.insert = AsyncMock()
        ingester._hot_store = hot
        _attach_embedder(ingester)

        await ingester.ingest_trace(_sample_trace())
        hot.insert.assert_awaited_once()

    async def test_ingest_missing_trace_id_raises(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        ingester._hot_store = hot
        with pytest.raises(ValidationError, match="trace_id"):
            await ingester.ingest_trace({"spans": []})

    async def test_ingest_no_spans_skipped(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.insert = AsyncMock()
        ingester._hot_store = hot
        _attach_embedder(ingester)
        await ingester.ingest_trace({"trace_id": "abc", "spans": []})
        hot.insert.assert_not_called()

    async def test_ingest_uninitialized_raises(self) -> None:
        ingester = _make_ingester()
        # No hot_store set
        with pytest.raises(RuntimeError, match="HotStore not initialized"):
            await ingester._ingest_trace_duckdb(_sample_trace())

    async def test_ingest_general_error_logged(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.insert = AsyncMock(side_effect=RuntimeError("db down"))
        ingester._hot_store = hot
        _attach_embedder(ingester)
        # Should not raise; errors are absorbed
        await ingester._ingest_trace_duckdb(_sample_trace())


class TestIngestTracePgvector:
    async def test_ingest_valid_trace(self) -> None:
        ingester = _make_ingester(
            storage_type="postgresql", pgvector_dsn="postgres://x"
        )
        adapter = AsyncMock()
        adapter.upsert = AsyncMock()
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)

        await ingester.ingest_trace(_sample_trace())
        adapter.upsert.assert_awaited_once()
        call = adapter.upsert.await_args
        assert call.kwargs["collection"] == "otel_traces"
        assert call.kwargs["documents"][0]["id"] == "trace-1"

    async def test_ingest_uninitialized_raises(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        with pytest.raises(RuntimeError, match="pgvector adapter not initialized"):
            await ingester._ingest_trace_pgvector(_sample_trace())

    async def test_ingest_missing_trace_id_raises(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        ingester._pgvector_adapter = adapter
        with pytest.raises(ValidationError, match="trace_id"):
            await ingester._ingest_trace_pgvector({"spans": []})

    async def test_ingest_no_spans_skipped(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.upsert = AsyncMock()
        ingester._pgvector_adapter = adapter
        await ingester.ingest_trace({"trace_id": "abc", "spans": []})
        adapter.upsert.assert_not_called()

    async def test_ingest_error_logged(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.upsert = AsyncMock(side_effect=RuntimeError("pg down"))
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)
        # Should not raise
        await ingester._ingest_trace_pgvector(_sample_trace())


class TestIngestBatch:
    async def test_batch_with_success_and_error(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.insert = AsyncMock()
        ingester._hot_store = hot
        _attach_embedder(ingester)

        valid = _sample_trace("t1")
        broken = {"spans": []}  # no trace_id
        # Make broken hit the validation path so it raises
        with patch.object(ingester, "_ingest_trace_duckdb", new=AsyncMock(side_effect=ValidationError("trace_id"))):
            stats = await ingester.ingest_batch([valid, broken])
        assert stats["error_count"] >= 1
        assert isinstance(stats["errors"], list)

    async def test_batch_all_success(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.insert = AsyncMock()
        ingester._hot_store = hot
        _attach_embedder(ingester)
        stats = await ingester.ingest_batch([_sample_trace("a"), _sample_trace("b")])
        assert stats["success_count"] == 2
        assert stats["error_count"] == 0


# ============== search_traces / _search_duckdb / _search_pgvector ==============


class TestSearchTracesDuckdb:
    async def test_search_returns_results(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.search_similar = AsyncMock(return_value=[{"a": 1}])
        ingester._hot_store = hot
        _attach_embedder(ingester)
        results = await ingester.search_traces("query", limit=5)
        assert results == [{"a": 1}]

    async def test_search_no_embedder_raises(self) -> None:
        ingester = _make_ingester()
        ingester._embedder = None
        with pytest.raises(RuntimeError, match="Embedding model not loaded"):
            await ingester.search_traces("query")

    async def test_search_exception_returns_empty(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.search_similar = AsyncMock(side_effect=RuntimeError("boom"))
        ingester._hot_store = hot
        _attach_embedder(ingester)
        results = await ingester.search_traces("query")
        assert results == []

    async def test_search_duckdb_uninitialized(self) -> None:
        ingester = _make_ingester()
        with pytest.raises(RuntimeError, match="HotStore not initialized"):
            await ingester._search_duckdb([0.1] * 4, 5, None, 0.5)


class TestSearchTracesPgvector:
    async def test_search_with_system_filter(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.search = AsyncMock(
            return_value=[
                {
                    "id": "t1",
                    "score": 0.1,
                    "metadata": {"content": "c", "timestamp": "ts"},
                }
            ]
        )
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)
        results = await ingester.search_traces("q", system_id="claude", threshold=0.5)
        assert len(results) == 1
        assert results[0]["conversation_id"] == "t1"
        assert results[0]["similarity"] == 0.9
        # system_id passed as filter
        call = adapter.search.await_args
        assert call.kwargs["filter_expr"] == {"system_id": "claude"}

    async def test_search_below_threshold_filtered(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.search = AsyncMock(
            return_value=[
                {
                    "id": "t1",
                    "score": 0.9,  # similarity = 0.1, below default threshold 0.7
                    "metadata": {},
                }
            ]
        )
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)
        results = await ingester.search_traces("q")
        assert results == []

    async def test_search_pgvector_uninitialized(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        with pytest.raises(RuntimeError, match="pgvector adapter not initialized"):
            await ingester._search_pgvector([0.1] * 4, 5, None, 0.5)

    async def test_search_pgvector_exception(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.search = AsyncMock(side_effect=RuntimeError("pg down"))
        ingester._pgvector_adapter = adapter
        _attach_embedder(ingester)
        results = await ingester.search_traces("q")
        assert results == []


# ============== get_trace_by_id ==============


class TestGetTraceById:
    async def test_get_duckdb_found(self) -> None:
        ingester = _make_ingester()
        hot = MagicMock()
        hot.conn = MagicMock()
        hot.conn.execute.return_value.fetchall.return_value = [
            ("claude", "t1", "content", datetime.now(UTC), {"k": "v"})
        ]
        ingester._hot_store = hot
        result = await ingester.get_trace_by_id("t1")
        assert result is not None
        assert result["conversation_id"] == "t1"
        assert result["metadata"] == {"k": "v"}

    async def test_get_duckdb_json_metadata_string(self) -> None:
        ingester = _make_ingester()
        hot = MagicMock()
        hot.conn = MagicMock()
        hot.conn.execute.return_value.fetchall.return_value = [
            ("claude", "t1", "content", datetime.now(UTC), json.dumps({"k": "v"}))
        ]
        ingester._hot_store = hot
        result = await ingester.get_trace_by_id("t1")
        assert result["metadata"] == {"k": "v"}

    async def test_get_duckdb_not_found(self) -> None:
        ingester = _make_ingester()
        hot = MagicMock()
        hot.conn = MagicMock()
        hot.conn.execute.return_value.fetchall.return_value = []
        ingester._hot_store = hot
        result = await ingester.get_trace_by_id("missing")
        assert result is None

    async def test_get_duckdb_uninitialized(self) -> None:
        ingester = _make_ingester()
        with pytest.raises(RuntimeError, match="HotStore not initialized"):
            await ingester._get_trace_duckdb("t1")

    async def test_get_duckdb_error(self) -> None:
        ingester = _make_ingester()
        hot = MagicMock()
        hot.conn = MagicMock()
        hot.conn.execute.side_effect = RuntimeError("db down")
        ingester._hot_store = hot
        result = await ingester.get_trace_by_id("t1")
        assert result is None

    async def test_get_pgvector_found(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.get = AsyncMock(
            return_value=[
                {
                    "id": "t1",
                    "metadata": {"content": "c", "timestamp": "ts"},
                }
            ]
        )
        ingester._pgvector_adapter = adapter
        result = await ingester.get_trace_by_id("t1")
        assert result is not None
        assert result["conversation_id"] == "t1"
        assert result["content"] == "c"

    async def test_get_pgvector_json_metadata_string(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.get = AsyncMock(
            return_value=[
                {
                    "id": "t1",
                    "metadata": json.dumps({"content": "c", "timestamp": "ts"}),
                }
            ]
        )
        ingester._pgvector_adapter = adapter
        result = await ingester.get_trace_by_id("t1")
        assert result["metadata"] == {"content": "c", "timestamp": "ts"}

    async def test_get_pgvector_not_found(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.get = AsyncMock(return_value=[])
        ingester._pgvector_adapter = adapter
        result = await ingester.get_trace_by_id("missing")
        assert result is None

    async def test_get_pgvector_uninitialized(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        with pytest.raises(RuntimeError, match="pgvector adapter not initialized"):
            await ingester._get_trace_pgvector("t1")

    async def test_get_pgvector_error(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.get = AsyncMock(side_effect=RuntimeError("pg down"))
        ingester._pgvector_adapter = adapter
        result = await ingester.get_trace_by_id("t1")
        assert result is None


# ============== close ==============


class TestClose:
    async def test_close_duckdb(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.close = AsyncMock()
        ingester._hot_store = hot
        ingester._embedding_cache["x"] = [0.1, 0.2]
        await ingester.close()
        hot.close.assert_awaited_once()
        assert ingester._embedding_cache == {}

    async def test_close_pgvector(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.cleanup = AsyncMock()
        ingester._pgvector_adapter = adapter
        await ingester.close()
        adapter.cleanup.assert_awaited_once()

    async def test_close_no_storage(self) -> None:
        ingester = _make_ingester()
        # Should not raise
        await ingester.close()
        assert ingester._embedding_cache == {}

    async def test_close_duckdb_error_swallowed(self) -> None:
        ingester = _make_ingester()
        hot = AsyncMock()
        hot.close = AsyncMock(side_effect=RuntimeError("close failed"))
        ingester._hot_store = hot
        # Should not raise
        await ingester.close()

    async def test_close_pgvector_error_swallowed(self) -> None:
        ingester = _make_ingester(storage_type="postgresql", pgvector_dsn="postgres://x")
        adapter = AsyncMock()
        adapter.cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))
        ingester._pgvector_adapter = adapter
        # Should not raise
        await ingester.close()


# ============== _get_embedding ==============


class TestGetEmbedding:
    async def test_no_embedder_raises(self) -> None:
        ingester = _make_ingester()
        ingester._embedder = None
        with pytest.raises(RuntimeError, match="Embedding model not loaded"):
            await ingester._get_embedding("text")

    async def test_encode_propagates_exception(self) -> None:
        ingester = _make_ingester()
        embedder = MagicMock()
        embedder.encode.side_effect = RuntimeError("embed failed")
        ingester._embedder = embedder
        with pytest.raises(RuntimeError, match="embed failed"):
            await ingester._get_embedding("text")

    async def test_cache_hit_returns_cached(self) -> None:
        ingester = _make_ingester()
        emb = _fake_embedding()
        ingester._embedding_cache["text"] = emb
        embedder = MagicMock()
        ingester._embedder = embedder
        result = await ingester._get_embedding("text")
        assert result is emb
        embedder.encode.assert_not_called()


# ============== Span helpers ==============


class TestSpanHelpers:
    def test_extract_system_id_claude(self) -> None:
        ingester = _make_ingester()
        spans = [{"attributes": {"service.name": "claude-service"}}]
        assert ingester._extract_system_id(spans) == "claude"

    def test_extract_system_id_qwen(self) -> None:
        ingester = _make_ingester()
        spans = [{"attributes": {"service.name": "qwen-runtime"}}]
        assert ingester._extract_system_id(spans) == "qwen"

    def test_extract_system_id_unknown_service(self) -> None:
        ingester = _make_ingester()
        spans = [{"attributes": {"service.name": "custom-svc"}}]
        assert ingester._extract_system_id(spans) == "custom-svc"

    def test_extract_system_id_missing(self) -> None:
        ingester = _make_ingester()
        assert ingester._extract_system_id([]) == "unknown"
        spans = [{"attributes": {}}]
        assert ingester._extract_system_id(spans) == "unknown"

    def test_build_content(self) -> None:
        ingester = _make_ingester()
        spans = [{"name": "span1"}, {"name": "span2"}, {"name": ""}]
        assert ingester._build_content(spans) == "span1 | span2"

    def test_build_content_empty(self) -> None:
        ingester = _make_ingester()
        assert ingester._build_content([]) == "Empty trace"
        assert ingester._build_content([{"name": ""}]) == "Empty trace"

    def test_extract_timestamp_string(self) -> None:
        ingester = _make_ingester()
        spans = [{"start_time": "2024-01-01T00:00:00Z"}]
        ts = ingester._extract_timestamp(spans)
        assert ts == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_extract_timestamp_int_unix_ns(self) -> None:
        ingester = _make_ingester()
        # 2024-01-01T00:00:00Z in nanoseconds
        ns = 1704067200 * 1_000_000_000
        spans = [{"start_time": ns}]
        ts = ingester._extract_timestamp(spans)
        assert ts == datetime.fromtimestamp(1704067200, tz=UTC)

    def test_extract_timestamp_empty_spans(self) -> None:
        ingester = _make_ingester()
        ts = ingester._extract_timestamp([])
        # Just verify it's a datetime, not exact value
        assert isinstance(ts, datetime)

    def test_extract_timestamp_no_start_time(self) -> None:
        ingester = _make_ingester()
        spans = [{}]
        ts = ingester._extract_timestamp(spans)
        assert isinstance(ts, datetime)

    def test_extract_timestamp_invalid_falls_back(self) -> None:
        ingester = _make_ingester()
        spans = [{"start_time": "not-a-date"}]
        ts = ingester._extract_timestamp(spans)
        assert isinstance(ts, datetime)

    def test_extract_attributes(self) -> None:
        ingester = _make_ingester()
        spans = [
            {"attributes": {"a": 1, "b": 2}},
            {"attributes": {"b": 3, "c": 4}},
        ]
        attrs = ingester._extract_attributes(spans)
        assert attrs == {"a": 1, "b": 3, "c": 4}

    def test_extract_attributes_empty(self) -> None:
        ingester = _make_ingester()
        assert ingester._extract_attributes([]) == {}


# ============== async context manager ==============


class TestAsyncContextManager:
    async def test_aenter_aexit(self) -> None:
        ingester = _make_ingester()
        with patch.object(ingester, "initialize", AsyncMock()) as init, patch.object(
            ingester, "close", AsyncMock()
        ) as close:
            async with ingester as ctx:
                assert ctx is ingester
            init.assert_awaited_once()
            close.assert_awaited_once()


# ============== create_otel_ingester factory ==============


class TestCreateOtelIngester:
    async def test_creates_duckdb_ingester(self) -> None:
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            ingester = await create_otel_ingester(
                preferred_backend="text_only",
                storage_type="duckdb",
                hot_store_path=":memory:",
            )
        try:
            assert ingester.storage_type is StorageType.DUCKDB
            assert ingester.backend is EmbeddingBackend.TEXT_ONLY
        finally:
            await ingester.close()

    async def test_string_storage_type_coerced(self) -> None:
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            ingester = await create_otel_ingester(
                storage_type="duckdb",
                preferred_backend="text_only",
                hot_store_path=":memory:",
            )
        try:
            assert ingester.storage_type is StorageType.DUCKDB
        finally:
            await ingester.close()

    async def test_env_var_storage_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE overrides default."""
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        monkeypatch.setenv("MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE", "duckdb")
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            ingester = await create_otel_ingester(
                storage_type="duckdb",
                preferred_backend="text_only",
                hot_store_path=":memory:",
            )
        try:
            assert ingester.storage_type is StorageType.DUCKDB
        finally:
            await ingester.close()

    async def test_env_var_pg_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL provides pg DSN when arg is None."""
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        monkeypatch.setenv(
            "MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL", "postgres://env-host/db"
        )
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            ingester = await create_otel_ingester(
                storage_type="duckdb",
                preferred_backend="text_only",
                hot_store_path=":memory:",
                pgvector_dsn=None,
            )
        try:
            # Env var supplies DSN when parameter is None
            assert ingester._pgvector_dsn == "postgres://env-host/db"
        finally:
            await ingester.close()

    async def test_hot_store_path_file(self) -> None:
        """Non-':memory:' path passes a file path to HotStore."""
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_hot) as cls:
            ingester = await create_otel_ingester(
                preferred_backend="text_only",
                hot_store_path="/tmp/test_otel.duckdb",
            )
        try:
            # The factory creates its own HotStore with the file path
            cls.assert_called_once_with(database_path="/tmp/test_otel.duckdb")
        finally:
            await ingester.close()

    async def test_tilde_path_expansion(self) -> None:
        """Tilde in hot_store_path is expanded in _duckdb_path."""
        mock_hot = AsyncMock()
        mock_hot.initialize = AsyncMock()
        mock_hot.close = AsyncMock()
        with patch("akosha.storage.HotStore", return_value=mock_hot):
            ingester = await create_otel_ingester(
                preferred_backend="text_only",
                hot_store_path="~/test_otel.duckdb",
            )
        try:
            # The factory stores the expanded path in _duckdb_path
            assert "~" not in ingester._duckdb_path
            assert ingester._duckdb_path.startswith("/")
        finally:
            await ingester.close()
