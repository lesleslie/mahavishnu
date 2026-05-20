"""Unit tests for mahavishnu.ingesters.turboquant_compressor.

Covers:
    1. TurboQuantCompressor instantiation and properties
    2. Availability flag (package present / absent)
    3. Compression ratio and byte-budget arithmetic
    4. compress_batch / decompress_batch with mocked TurboQuantPGVector
    5. Graceful ImportError when turboquant-pro is not installed
    6. estimate_savings calculations
    7. search_pgvector async wrapper
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_compressor(bits: int = 4, dimension: int = 384, seed: int = 42):
    """Instantiate TurboQuantCompressor without importing the real package."""
    from mahavishnu.ingesters.turboquant_compressor import TurboQuantCompressor

    return TurboQuantCompressor(dimension=dimension, bits=bits, seed=seed)


def _fake_embedding(dim: int = 384) -> list[float]:
    return [float(i) / dim for i in range(dim)]


# ---------------------------------------------------------------------------
# Properties and arithmetic (no TurboQuant package needed)
# ---------------------------------------------------------------------------


class TestTurboQuantCompressorProperties:
    """Tests for pure-math properties that do not call TurboQuantPGVector."""

    def test_default_dimension(self):
        c = _make_compressor()
        assert c._dimension == 384

    def test_custom_dimension_and_bits(self):
        c = _make_compressor(bits=3, dimension=768)
        assert c._dimension == 768
        assert c.bits == 3

    def test_invalid_bits_raises(self):
        with pytest.raises(ValueError, match="turboquant_bits must be 3 or 4"):
            _make_compressor(bits=5)

    def test_bits_2_raises(self):
        with pytest.raises(ValueError):
            _make_compressor(bits=2)

    def test_compression_ratio_4bit(self):
        c = _make_compressor(bits=4)
        assert c.compression_ratio == pytest.approx(8.0)

    def test_compression_ratio_3bit(self):
        c = _make_compressor(bits=3)
        assert c.compression_ratio == pytest.approx(32.0 / 3)

    def test_compressed_bytes_per_vector_4bit(self):
        c = _make_compressor(bits=4, dimension=384)
        # (384 * 4 + 7) // 8 = 192
        assert c.compressed_bytes_per_vector() == 192

    def test_compressed_bytes_per_vector_3bit(self):
        c = _make_compressor(bits=3, dimension=384)
        # (384 * 3 + 7) // 8 = 144
        assert c.compressed_bytes_per_vector() == 144

    def test_estimate_savings_keys(self):
        c = _make_compressor(bits=4, dimension=384)
        savings = c.estimate_savings(1000)
        assert set(savings.keys()) == {"uncompressed_kb", "compressed_kb", "savings_kb", "ratio"}

    def test_estimate_savings_values(self):
        c = _make_compressor(bits=4, dimension=384)
        savings = c.estimate_savings(1000)
        # 1000 * 384 * 4 bytes / 1024 = 1500 KB uncompressed
        assert savings["uncompressed_kb"] == pytest.approx(1500.0)
        # 1000 * 192 bytes / 1024 = 187.5 KB compressed
        assert savings["compressed_kb"] == pytest.approx(187.5)
        assert savings["savings_kb"] == pytest.approx(1312.5)
        assert savings["ratio"] == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Availability flag
# ---------------------------------------------------------------------------


class TestTurboQuantAvailability:
    """Tests for the TURBOQUANT_AVAILABLE flag logic."""

    def test_available_false_when_not_installed(self):
        with patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False):
            c = _make_compressor()
            assert c.available is False

    def test_available_true_when_installed(self):
        with patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True):
            c = _make_compressor()
            assert c.available is True

    def test_compress_batch_raises_when_unavailable(self):
        with patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False):
            c = _make_compressor()
            with pytest.raises(ImportError, match="turboquant-pro not installed"):
                c.compress_batch([[0.1] * 384])

    def test_decompress_batch_raises_when_unavailable(self):
        with patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False):
            c = _make_compressor()
            with pytest.raises(ImportError, match="turboquant-pro not installed"):
                c.decompress_batch([b"dummy"])


# ---------------------------------------------------------------------------
# compress_batch / decompress_batch (mocked TurboQuantPGVector)
# ---------------------------------------------------------------------------


class TestTurboQuantBatchOps:
    """Tests for compress_batch and decompress_batch with a mocked backend."""

    def _patched_tq(self, compress_return=None, decompress_return=None):
        """Return a context manager that patches TurboQuantPGVector."""
        mock_tq_instance = MagicMock()
        if compress_return is not None:
            mock_tq_instance.compress.return_value = compress_return
        if decompress_return is not None:
            mock_tq_instance.decompress.return_value = decompress_return
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)
        return (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch("mahavishnu.ingesters.turboquant_compressor.TurboQuantPGVector", mock_tq_cls),
            mock_tq_instance,
        )

    # TurboQuantPGVector only exists in module namespace when package is installed.
    # Use create=True so patch can inject it even when the import failed.
    _TQ_PATCH = "mahavishnu.ingesters.turboquant_compressor.TurboQuantPGVector"

    def test_compress_batch_calls_compress_per_embedding(self):
        mock_tq_instance = MagicMock()
        mock_tq_instance.compress.return_value = b"compressed"
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch(self._TQ_PATCH, mock_tq_cls, create=True),
        ):
            c = _make_compressor()
            embeddings = [_fake_embedding() for _ in range(3)]
            result = c.compress_batch(embeddings)

        assert mock_tq_instance.compress.call_count == 3
        assert result == [b"compressed", b"compressed", b"compressed"]

    def test_decompress_batch_calls_decompress_per_entry(self):
        restored = _fake_embedding()
        mock_tq_instance = MagicMock()
        mock_tq_instance.decompress.return_value = restored
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch(self._TQ_PATCH, mock_tq_cls, create=True),
        ):
            c = _make_compressor()
            result = c.decompress_batch([b"packed1", b"packed2"])

        assert mock_tq_instance.decompress.call_count == 2
        assert result == [restored, restored]

    def test_tq_instance_is_reused(self):
        """_get_tq() should construct TurboQuantPGVector only once."""
        mock_tq_instance = MagicMock()
        mock_tq_instance.compress.return_value = b"x"
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch(self._TQ_PATCH, mock_tq_cls, create=True),
        ):
            c = _make_compressor()
            c.compress_batch([_fake_embedding()])
            c.compress_batch([_fake_embedding()])

        assert mock_tq_cls.call_count == 1

    def test_compress_batch_empty_list(self):
        mock_tq_instance = MagicMock()
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch(self._TQ_PATCH, mock_tq_cls, create=True),
        ):
            c = _make_compressor()
            result = c.compress_batch([])

        assert result == []
        mock_tq_instance.compress.assert_not_called()


# ---------------------------------------------------------------------------
# search_pgvector (async)
# ---------------------------------------------------------------------------


class TestTurboQuantSearchPgvector:
    """Tests for the async pgvector search wrapper."""

    _TQ_PATCH = "mahavishnu.ingesters.turboquant_compressor.TurboQuantPGVector"

    @pytest.mark.asyncio
    async def test_search_pgvector_delegates_to_search_compressed(self):
        expected_results = [("id1", 0.95, {"key": "val"})]
        mock_tq_instance = MagicMock()
        mock_tq_instance.search_compressed.return_value = expected_results
        mock_tq_cls = MagicMock(return_value=mock_tq_instance)

        mock_conn = MagicMock()

        with (
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
            patch(self._TQ_PATCH, mock_tq_cls, create=True),
        ):
            c = _make_compressor()
            result = await c.search_pgvector(
                conn=mock_conn,
                table="otel_traces",
                query_embedding=_fake_embedding(),
                top_k=5,
            )

        assert result == expected_results
        mock_tq_instance.search_compressed.assert_called_once()
        _, kwargs = mock_tq_instance.search_compressed.call_args
        assert kwargs.get("top_k") == 5 or mock_tq_instance.search_compressed.call_args[0][3] == 5

    @pytest.mark.asyncio
    async def test_search_pgvector_raises_when_unavailable(self):
        with patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False):
            c = _make_compressor()
            with pytest.raises(ImportError):
                await c.search_pgvector(
                    conn=MagicMock(),
                    table="traces",
                    query_embedding=_fake_embedding(),
                )
