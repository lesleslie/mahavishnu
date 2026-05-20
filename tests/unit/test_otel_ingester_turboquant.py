"""Unit tests for TurboQuant integration in OtelIngester.

Covers:
    1. OtelIngester stores turboquant_bits and initializes compressor lazily
    2. _get_embedding() compresses on cache write, decompresses on cache read
    3. Graceful fallback when compress/decompress raises
    4. No compression when turboquant_bits is None
    5. Cache still works when compressor is unavailable (package absent)
    6. create_otel_ingester() forwards turboquant_bits
    7. OTelIngesterConfig turboquant_bits field validation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.ingesters.otel_ingester import OtelIngester

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_embedding(dim: int = 384) -> list[float]:
    return [float(i) / dim for i in range(dim)]


def _make_ingester(**kwargs) -> OtelIngester:
    """Create an OtelIngester without calling initialize()."""
    return OtelIngester(preferred_backend="text_only", **kwargs)


def _attach_mock_embedder(
    ingester: OtelIngester, embedding: list[float] | None = None
) -> MagicMock:
    """Attach a synchronous mock embedder directly."""
    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = embedding or _fake_embedding()
    mock_embedder.dimension = 384
    ingester._embedder = mock_embedder
    return mock_embedder


def _attach_mock_compressor(
    ingester: OtelIngester,
    available: bool = True,
    compress_return: object = b"packed",
    decompress_return: list[float] | None = None,
) -> MagicMock:
    """Attach a mock TurboQuantCompressor directly."""
    mock_tq = MagicMock()
    mock_tq.available = available
    mock_tq.compress_batch.return_value = [compress_return]
    mock_tq.decompress_batch.return_value = [decompress_return or _fake_embedding()]
    ingester._compressor = mock_tq
    return mock_tq


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestOtelIngesterTurboQuantInit:
    def test_turboquant_bits_stored(self):
        ingester = _make_ingester(turboquant_bits=4)
        assert ingester._turboquant_bits == 4
        assert ingester._compressor is None  # lazy

    def test_turboquant_bits_none_by_default(self):
        ingester = _make_ingester()
        assert ingester._turboquant_bits is None
        assert ingester._compressor is None

    def test_embedding_cache_is_empty_dict(self):
        ingester = _make_ingester(turboquant_bits=4)
        assert ingester._embedding_cache == {}


# ---------------------------------------------------------------------------
# _get_embedding: no compression path
# ---------------------------------------------------------------------------


class TestGetEmbeddingNoCompression:
    """_get_embedding should behave identically to the pre-TurboQuant path when
    no compressor is attached."""

    @pytest.mark.asyncio
    async def test_stores_raw_float_in_cache(self):
        ingester = _make_ingester()
        emb = _fake_embedding()
        _attach_mock_embedder(ingester, emb)

        result = await ingester._get_embedding("hello world")

        assert result == emb
        assert ingester._embedding_cache["hello world"] == emb

    @pytest.mark.asyncio
    async def test_returns_cached_raw_embedding(self):
        ingester = _make_ingester()
        emb = _fake_embedding()
        ingester._embedding_cache["hello"] = emb
        mock_embedder = _attach_mock_embedder(ingester)

        result = await ingester._get_embedding("hello")

        assert result == emb
        mock_embedder.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_fifo_eviction_at_cache_limit(self):
        ingester = _make_ingester(cache_size=2)
        ingester._embedder = MagicMock()
        ingester._embedder.encode.side_effect = lambda t: [hash(t) % 100] * 384
        ingester._embedder.dimension = 384

        await ingester._get_embedding("a")
        await ingester._get_embedding("b")
        assert "a" in ingester._embedding_cache
        assert "b" in ingester._embedding_cache

        await ingester._get_embedding("c")
        assert "a" not in ingester._embedding_cache  # oldest evicted
        assert "b" in ingester._embedding_cache
        assert "c" in ingester._embedding_cache


# ---------------------------------------------------------------------------
# _get_embedding: compression path
# ---------------------------------------------------------------------------


class TestGetEmbeddingWithCompression:
    """_get_embedding stores compressed entries in cache, decompresses on retrieval."""

    @pytest.mark.asyncio
    async def test_compresses_on_cache_write(self):
        ingester = _make_ingester(turboquant_bits=4)
        emb = _fake_embedding()
        _attach_mock_embedder(ingester, emb)
        mock_tq = _attach_mock_compressor(ingester, available=True, compress_return=b"packed")

        result = await ingester._get_embedding("test content")

        mock_tq.compress_batch.assert_called_once_with([emb])
        assert ingester._embedding_cache["test content"] == b"packed"
        assert result == emb  # caller always gets uncompressed

    @pytest.mark.asyncio
    async def test_decompresses_on_cache_read(self):
        restored = _fake_embedding()
        ingester = _make_ingester(turboquant_bits=4)
        _attach_mock_embedder(ingester)
        mock_tq = _attach_mock_compressor(ingester, available=True, decompress_return=restored)

        # Pre-seed the cache with packed data
        ingester._embedding_cache["cached content"] = b"packed_blob"

        result = await ingester._get_embedding("cached content")

        mock_tq.decompress_batch.assert_called_once_with([b"packed_blob"])
        assert result == restored

    @pytest.mark.asyncio
    async def test_no_compress_call_on_cache_hit(self):
        restored = _fake_embedding()
        ingester = _make_ingester(turboquant_bits=4)
        mock_embedder = _attach_mock_embedder(ingester)
        mock_tq = _attach_mock_compressor(ingester, available=True, decompress_return=restored)
        ingester._embedding_cache["existing"] = b"packed"

        await ingester._get_embedding("existing")

        mock_embedder.encode.assert_not_called()
        mock_tq.compress_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_raw_on_compress_failure(self):
        ingester = _make_ingester(turboquant_bits=4)
        emb = _fake_embedding()
        _attach_mock_embedder(ingester, emb)

        mock_tq = MagicMock()
        mock_tq.available = True
        mock_tq.compress_batch.side_effect = RuntimeError("pack failed")
        ingester._compressor = mock_tq

        result = await ingester._get_embedding("content")

        # Should fall back to storing raw embedding
        assert ingester._embedding_cache["content"] == emb
        assert result == emb

    @pytest.mark.asyncio
    async def test_decompress_failure_with_packed_bytes_evicts_and_regenerates(self):
        """When the cache holds real packed bytes and decompress fails, the corrupt
        entry must be evicted and a fresh embedding generated — NOT returning bytes
        to callers who expect list[float]."""
        fresh_emb = _fake_embedding()
        ingester = _make_ingester(turboquant_bits=4)
        mock_embedder = _attach_mock_embedder(ingester, fresh_emb)

        mock_tq = MagicMock()
        mock_tq.available = True
        mock_tq.decompress_batch.side_effect = RuntimeError("bit-width mismatch")
        # After eviction, the re-generated embedding should be stored raw (compress also fails)
        mock_tq.compress_batch.side_effect = RuntimeError("pack still broken")
        ingester._compressor = mock_tq

        # Pre-seed the cache with genuinely packed bytes (not floats)
        ingester._embedding_cache["key"] = b"packed_opaque_bytes"

        result = await ingester._get_embedding("key")

        # Corrupt entry must be evicted; fresh embedding returned
        assert (
            "key" not in ingester._embedding_cache or ingester._embedding_cache["key"] == fresh_emb
        )
        assert result == fresh_emb
        mock_embedder.encode.assert_called_once_with("key")

    @pytest.mark.asyncio
    async def test_unavailable_compressor_stores_raw(self):
        """When turboquant-pro is absent, cache stores raw embeddings."""
        ingester = _make_ingester(turboquant_bits=4)
        emb = _fake_embedding()
        _attach_mock_embedder(ingester, emb)
        _attach_mock_compressor(ingester, available=False)

        result = await ingester._get_embedding("data")

        assert ingester._embedding_cache["data"] == emb
        assert result == emb
        ingester._compressor.compress_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_unavailable_compressor_returns_cached_raw(self):
        """When available=False, cached raw value is returned without decompression."""
        raw = _fake_embedding()
        ingester = _make_ingester(turboquant_bits=4)
        ingester._embedding_cache["key"] = raw
        _attach_mock_embedder(ingester)
        _attach_mock_compressor(ingester, available=False)

        result = await ingester._get_embedding("key")

        assert result == raw
        ingester._compressor.decompress_batch.assert_not_called()


# ---------------------------------------------------------------------------
# create_otel_ingester factory
# ---------------------------------------------------------------------------


class TestCreateOtelIngesterFactory:
    @pytest.mark.asyncio
    async def test_turboquant_bits_forwarded(self):
        mock_hot_store = AsyncMock()
        mock_hot_store.initialize = AsyncMock()

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False),
            patch("akosha.storage.HotStore", return_value=mock_hot_store),
        ):
            from mahavishnu.ingesters.otel_ingester import create_otel_ingester

            ingester = await create_otel_ingester(
                turboquant_bits=4,
                preferred_backend="text_only",
            )

        assert ingester._turboquant_bits == 4
        await ingester.close()

    @pytest.mark.asyncio
    async def test_turboquant_bits_none_default(self):
        mock_hot_store = AsyncMock()
        mock_hot_store.initialize = AsyncMock()

        with patch("akosha.storage.HotStore", return_value=mock_hot_store):
            from mahavishnu.ingesters.otel_ingester import create_otel_ingester

            ingester = await create_otel_ingester(preferred_backend="text_only")

        assert ingester._turboquant_bits is None
        await ingester.close()


# ---------------------------------------------------------------------------
# OTelIngesterConfig turboquant_bits field
# ---------------------------------------------------------------------------


class TestOTelIngesterConfigTurboQuant:
    """Tests for OTelIngesterConfig.turboquant_bits Pydantic field."""

    def test_default_is_4(self):
        from mahavishnu.core.config import OTelIngesterConfig

        c = OTelIngesterConfig()
        assert c.turboquant_bits == 4

    def test_none_disables_compression(self):
        from mahavishnu.core.config import OTelIngesterConfig

        c = OTelIngesterConfig(turboquant_bits=None)
        assert c.turboquant_bits is None

    def test_3_accepted(self):
        from mahavishnu.core.config import OTelIngesterConfig

        c = OTelIngesterConfig(turboquant_bits=3)
        assert c.turboquant_bits == 3

    def test_4_accepted(self):
        from mahavishnu.core.config import OTelIngesterConfig

        c = OTelIngesterConfig(turboquant_bits=4)
        assert c.turboquant_bits == 4

    def test_invalid_bits_raises(self):
        from pydantic import ValidationError

        from mahavishnu.core.config import OTelIngesterConfig

        with pytest.raises(ValidationError, match="turboquant_bits must be 3 or 4"):
            OTelIngesterConfig(turboquant_bits=5)
