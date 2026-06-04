"""TurboQuant Pro embedding compression for the Mahavishnu ingestion pipeline.

TurboQuant (Zandieh et al., ICLR 2026) compresses float32 embedding vectors to
3-4 bits per element using randomized rotations, achieving 5-10x memory reduction
with 0.978+ cosine similarity preserved. No retraining or calibration required.

Install: uv pip install turboquant-pro
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Optional dependency — import only for static analysis, never at runtime.
    from turboquant_pro import TurboQuantPGVector as _TurboQuantPGVector

    TURBOQUANT_AVAILABLE = True
else:
    try:
        from turboquant_pro import TurboQuantPGVector as _TurboQuantPGVector
    except ImportError:
        _TurboQuantPGVector = None  # type: ignore[assignment,misc]
    TURBOQUANT_AVAILABLE = _TurboQuantPGVector is not None

logger = logging.getLogger(__name__)

# Opaque binary format produced by TurboQuantPGVector.compress().
# The internal representation is not a stable Python type — treat as bytes-like.
type TQPackedVector = Any

__all__ = ["TurboQuantCompressor", "TQPackedVector", "TURBOQUANT_AVAILABLE"]


class TurboQuantCompressor:
    """Compresses float32 embedding vectors using TurboQuant Pro.

    Wraps TurboQuantPGVector with:
    - Graceful no-op fallback when turboquant-pro is not installed
    - Batch compress/decompress for lists of embeddings
    - Async pgvector compressed similarity search

    Example:
        >>> compressor = TurboQuantCompressor(dimension=384, bits=4)
        >>> if compressor.available:
        ...     compressed = compressor.compress_batch(embeddings)
        ...     restored = compressor.decompress_batch(compressed)
    """

    def __init__(
        self,
        dimension: int = 384,
        bits: int = 4,
        seed: int = 42,
    ) -> None:
        """Initialize compressor.

        Args:
            dimension: Embedding dimension (384 for bge-small/MiniLM models)
            bits: Bits per element — 3 gives 10.7x ratio, 4 gives 8x (recommended)
            seed: Random seed for reproducible quantization matrices

        Raises:
            ValueError: If bits is not 3 or 4
        """
        if bits not in (3, 4):
            raise ValueError(
                f"turboquant_bits must be 3 or 4, got {bits}. "
                "3 gives 10.7x ratio, 4 gives 8x (recommended)."
            )
        self._dimension = dimension
        self._bits = bits
        self._seed = seed
        self._tq: _TurboQuantPGVector | None = None  # type: ignore[valid-type]

    @property
    def available(self) -> bool:
        """True if turboquant-pro is installed and usable."""
        return TURBOQUANT_AVAILABLE

    @property
    def compression_ratio(self) -> float:
        """Float32-to-bits compression ratio (e.g. bits=4 → ratio=8.0)."""
        return 32.0 / self._bits

    @property
    def bits(self) -> int:
        """Configured bits per element."""
        return self._bits

    def _get_tq(self) -> Any:
        if not TURBOQUANT_AVAILABLE:
            raise ImportError(
                "turboquant-pro not installed. Install with: uv pip install turboquant-pro"
            )
        if self._tq is None:
            self._tq = _TurboQuantPGVector(  # type: ignore[valid-type,call-arg,misc]
                dim=self._dimension,
                bits=self._bits,
                seed=self._seed,
            )
        return self._tq

    def compress_batch(self, embeddings: list[list[float]]) -> list[TQPackedVector]:
        """Compress a list of float32 embeddings to TurboQuant packed format.

        Args:
            embeddings: Float32 embedding vectors (each of length self._dimension)

        Returns:
            Compressed representations (TurboQuant internal packed format)

        Raises:
            ImportError: If turboquant-pro is not installed
            RuntimeError: If compression fails for a specific embedding
        """
        logger.debug(f"turboquant_compress_batch_start count={len(embeddings)} bits={self._bits}")
        tq = self._get_tq()
        compressed: list[TQPackedVector] = []
        for i, emb in enumerate(embeddings):
            try:
                compressed.append(tq.compress(emb))
            except Exception as e:
                raise RuntimeError(
                    f"TurboQuant compression failed at index {i}/{len(embeddings)}: {e}"
                ) from e
        logger.debug(f"turboquant_compress_batch_complete count={len(embeddings)}")
        return compressed

    def decompress_batch(self, compressed: list[TQPackedVector]) -> list[list[float]]:
        """Reconstruct float32 embeddings from TurboQuant compressed format.

        Reconstructed vectors preserve 0.978+ cosine similarity vs originals.

        Args:
            compressed: TurboQuant compressed embeddings from compress_batch()

        Returns:
            Reconstructed float32 embedding vectors
        """
        tq = self._get_tq()
        return [tq.decompress(c) for c in compressed]

    async def search_pgvector(
        self,
        conn: Any,
        table: str,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[Any]:
        """Similarity search against a TurboQuant-compressed pgvector table.

        The table must have been populated via TurboQuant Pro's insert API.
        Uses compressed bit-kernel operators for 5-8x faster search vs float32.

        Args:
            conn: asyncpg or psycopg2 connection to the PostgreSQL database
            table: Target table name containing compressed embeddings
            query_embedding: Uncompressed float32 query vector
            top_k: Number of nearest neighbours to return

        Returns:
            List of (id, score, metadata) result tuples
        """
        tq = self._get_tq()
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(  # type: ignore
                None,
                lambda: tq.search_compressed(conn, table, query_embedding, top_k=top_k),
            )
        except Exception as e:
            logger.error(f"turboquant_search_pgvector_failed table={table} top_k={top_k} error={e}")
            raise

    def compressed_bytes_per_vector(self) -> int:
        """Storage bytes required per compressed vector at configured bit-width."""
        return (self._dimension * self._bits + 7) // 8

    def estimate_savings(self, vector_count: int) -> dict[str, float]:
        """Estimate compression savings for a given number of vectors.

        Args:
            vector_count: Number of embedding vectors

        Returns:
            Dict with uncompressed_kb, compressed_kb, savings_kb, ratio
        """
        uncompressed_bytes = vector_count * self._dimension * 4  # float32 = 4 bytes
        compressed_bytes = vector_count * self.compressed_bytes_per_vector()
        return {
            "uncompressed_kb": uncompressed_bytes / 1024,
            "compressed_kb": compressed_bytes / 1024,
            "savings_kb": (uncompressed_bytes - compressed_bytes) / 1024,
            "ratio": self.compression_ratio,
        }
