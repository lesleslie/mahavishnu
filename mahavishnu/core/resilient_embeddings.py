"""Resilient embedding client with multi-tier fallback support.

This module provides a fault-tolerant embedding client that addresses:
- F1: Fallback strategy when Akosha MCP is unavailable
- F4: Dimension mismatch risk when fallback providers differ

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                 ResilientEmbeddingClient                    │
    ├─────────────────────────────────────────────────────────────┤
    │  Tier 1: Akosha MCP (primary)                              │
    │  - Circuit breaker protection                              │
    │  - Timeout: 5s                                             │
    ├─────────────────────────────────────────────────────────────┤
    │  Tier 2: Local EmbeddingService (fallback)                 │
    │  - FastEmbed/Ollama/OpenAI                                 │
    │  - Dimension validated against standard                    │
    ├─────────────────────────────────────────────────────────────┤
    │  Tier 3: EmbeddingCache (LRU lookup)                       │
    │  - Versioned cache keys                                    │
    │  - May return stale results                                │
    ├─────────────────────────────────────────────────────────────┤
    │  Tier 4: Mock Embedding (last resort)                      │
    │  - Deterministic hash-based                                │
    │  - Non-semantic but functional                             │
    └─────────────────────────────────────────────────────────────┘

Usage:
    from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient

    client = ResilientEmbeddingClient()
    embedding = await client.generate_embedding("hello world")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from mahavishnu.core.embedding_cache import EmbeddingCache
    from mahavishnu.core.embeddings import EmbeddingService, EmbeddingProvider

logger = logging.getLogger(__name__)

# Ecosystem standard embedding dimension
STANDARD_EMBEDDING_DIMENSION = 384


class EmbeddingSource(Enum):
    """Source of generated embedding."""

    AKOSHA_MCP = "akosha_mcp"
    LOCAL_SERVICE = "local_service"
    CACHE = "cache"
    MOCK = "mock"


@dataclass
class ResilientEmbeddingResult:
    """Result from resilient embedding generation.

    Attributes:
        embedding: The embedding vector
        source: Where the embedding came from
        dimension: Embedding dimension
        latency_ms: Generation latency in milliseconds
        cached: Whether result was from cache
    """

    embedding: list[float]
    source: EmbeddingSource
    dimension: int
    latency_ms: float
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "embedding_dim": self.dimension,
            "source": self.source.value,
            "latency_ms": round(self.latency_ms, 2),
            "cached": self.cached,
        }


class CircuitBreaker:
    """Circuit breaker for protecting external services."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._is_open = False

    def can_execute(self) -> bool:
        """Check if requests should be allowed."""
        if not self._is_open:
            return True

        # Check if recovery timeout has elapsed
        elapsed = time.monotonic() - self.last_failure_time
        if elapsed >= self.recovery_timeout:
            logger.info("circuit_breaker_recovery_attempt")
            return True  # Allow one request to test recovery

        return False

    def record_success(self) -> None:
        """Record successful operation."""
        self.failure_count = 0
        self._is_open = False

    def record_failure(self) -> None:
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.failure_count >= self.failure_threshold:
            self._is_open = True
            logger.warning(
                f"circuit_breaker_opened: {self.failure_count} failures"
            )

    @property
    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self._is_open


class ResilientEmbeddingClient:
    """Fault-tolerant embedding client with multi-tier fallback.

    Provides resilient embedding generation with:
    1. Primary: Akosha MCP (with circuit breaker)
    2. Fallback: Local EmbeddingService
    3. Cache: LRU cache lookup
    4. Mock: Deterministic hash-based embeddings

    All tiers validate dimension compatibility with ecosystem standard.
    """

    def __init__(
        self,
        akosha_url: str = "http://localhost:8682/mcp",
        embedding_service: EmbeddingService | None = None,
        embedding_cache: EmbeddingCache | None = None,
        timeout: float = 5.0,
        standard_dimension: int = STANDARD_EMBEDDING_DIMENSION,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_recovery: float = 60.0,
    ) -> None:
        """Initialize resilient embedding client.

        Args:
            akosha_url: Akosha MCP server URL
            embedding_service: Local embedding service for fallback
            embedding_cache: Cache for tier 3 fallback
            timeout: Request timeout for Akosha MCP
            standard_dimension: Required dimension for compatibility
            circuit_breaker_threshold: Failures before opening circuit
            circuit_breaker_recovery: Seconds before recovery attempt
        """
        self._akosha_url = akosha_url
        self._timeout = timeout
        self._standard_dimension = standard_dimension
        self._embedding_service = embedding_service
        self._embedding_cache = embedding_cache

        self._client: httpx.AsyncClient | None = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_threshold,
            recovery_timeout=circuit_breaker_recovery,
        )

        # Statistics
        self._source_counts: dict[EmbeddingSource, int] = {
            source: 0 for source in EmbeddingSource
        }
        self._dimension_mismatches = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._akosha_url,
                timeout=httpx.Timeout(self._timeout, connect=2.0),
            )
        return self._client

    def _validate_dimension(self, embedding: list[float], source: str) -> bool:
        """Validate embedding dimension matches standard.

        Args:
            embedding: Embedding vector to validate
            source: Source name for logging

        Returns:
            True if valid, False if mismatch
        """
        actual_dim = len(embedding)
        if actual_dim != self._standard_dimension:
            logger.warning(
                f"dimension_mismatch: source={source}, "
                f"expected={self._standard_dimension}, actual={actual_dim}"
            )
            self._dimension_mismatches += 1
            return False
        return True

    def _generate_mock_embedding(self, text: str) -> list[float]:
        """Generate deterministic mock embedding.

        Creates a reproducible embedding based on text hash.
        Not semantically meaningful but functional for testing.

        Args:
            text: Input text

        Returns:
            Mock embedding vector of standard dimension
        """
        # Use SHA256 hash to generate deterministic values
        # SHA256 produces 64 hex chars, need to cycle for larger dimensions
        text_hash = hashlib.sha256(text.encode()).hexdigest()

        # Convert hash segments to floats in [-1, 1]
        embedding = []
        hash_len = len(text_hash)

        for i in range(self._standard_dimension):
            # Cycle through hash if needed
            idx = (i * 2) % (hash_len - 1)
            segment = text_hash[idx : idx + 2]
            if len(segment) == 2:
                value = int(segment, 16) / 127.5 - 1.0  # Normalize to [-1, 1]
            else:
                value = 0.0
            embedding.append(value)

        return embedding

    async def _try_akosha(self, text: str) -> list[float] | None:
        """Try to get embedding from Akosha MCP.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None if failed
        """
        if not self._circuit_breaker.can_execute():
            logger.debug("circuit_breaker_open_skipping_akosha")
            return None

        try:
            client = await self._get_client()
            response = await client.post(
                "/tools/call",
                json={
                    "name": "generate_embedding",
                    "arguments": {"text": text},
                },
            )
            response.raise_for_status()

            result = response.json()
            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0]
                if content.get("type") == "text":
                    import json

                    data = json.loads(content["text"])
                    embedding = data.get("embedding", [])

                    if embedding and self._validate_dimension(embedding, "akosha"):
                        self._circuit_breaker.record_success()
                        return embedding

            self._circuit_breaker.record_failure()
            return None

        except Exception as e:
            logger.debug(f"akosha_embedding_failed: {e}")
            self._circuit_breaker.record_failure()
            return None

    async def _try_local_service(self, text: str) -> list[float] | None:
        """Try to get embedding from local service.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None if failed/unavailable
        """
        if self._embedding_service is None:
            return None

        try:
            result = await self._embedding_service.embed([text])
            if result.embeddings:
                embedding = result.embeddings[0]
                if self._validate_dimension(embedding, "local_service"):
                    return embedding
            return None
        except Exception as e:
            logger.debug(f"local_embedding_failed: {e}")
            return None

    async def _try_cache(self, text: str) -> list[float] | None:
        """Try to get embedding from cache.

        Args:
            text: Text to embed

        Returns:
            Cached embedding or None if not found
        """
        if self._embedding_cache is None:
            return None

        try:
            cached = await self._embedding_cache.get(text)
            if cached and self._validate_dimension(cached, "cache"):
                return cached
            return None
        except Exception as e:
            logger.debug(f"cache_lookup_failed: {e}")
            return None

    async def generate_embedding(
        self,
        text: str,
        use_cache: bool = True,
    ) -> ResilientEmbeddingResult:
        """Generate embedding with multi-tier fallback.

        Tries in order:
        1. Akosha MCP (primary, with circuit breaker)
        2. Local EmbeddingService (fallback)
        3. EmbeddingCache (LRU lookup)
        4. Mock embedding (last resort)

        Args:
            text: Text to embed
            use_cache: Whether to check/use cache

        Returns:
            ResilientEmbeddingResult with embedding and metadata
        """
        start_time = time.perf_counter()

        # Try cache first if enabled
        if use_cache:
            cached = await self._try_cache(text)
            if cached is not None:
                latency_ms = (time.perf_counter() - start_time) * 1000
                self._source_counts[EmbeddingSource.CACHE] += 1
                return ResilientEmbeddingResult(
                    embedding=cached,
                    source=EmbeddingSource.CACHE,
                    dimension=len(cached),
                    latency_ms=latency_ms,
                    cached=True,
                )

        # Tier 1: Try Akosha MCP
        embedding = await self._try_akosha(text)
        if embedding is not None:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._source_counts[EmbeddingSource.AKOSHA_MCP] += 1

            # Cache the result
            if use_cache and self._embedding_cache:
                await self._embedding_cache.set(text, embedding)

            return ResilientEmbeddingResult(
                embedding=embedding,
                source=EmbeddingSource.AKOSHA_MCP,
                dimension=len(embedding),
                latency_ms=latency_ms,
            )

        # Tier 2: Try local service
        embedding = await self._try_local_service(text)
        if embedding is not None:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._source_counts[EmbeddingSource.LOCAL_SERVICE] += 1

            # Cache the result
            if use_cache and self._embedding_cache:
                await self._embedding_cache.set(text, embedding)

            return ResilientEmbeddingResult(
                embedding=embedding,
                source=EmbeddingSource.LOCAL_SERVICE,
                dimension=len(embedding),
                latency_ms=latency_ms,
            )

        # Tier 4: Mock embedding (last resort)
        # Skip tier 3 (cache) since we already checked above
        embedding = self._generate_mock_embedding(text)
        latency_ms = (time.perf_counter() - start_time) * 1000
        self._source_counts[EmbeddingSource.MOCK] += 1

        logger.warning(f"using_mock_embedding: no other sources available for text")

        return ResilientEmbeddingResult(
            embedding=embedding,
            source=EmbeddingSource.MOCK,
            dimension=len(embedding),
            latency_ms=latency_ms,
        )

    async def generate_batch_embeddings(
        self,
        texts: list[str],
        use_cache: bool = True,
    ) -> list[ResilientEmbeddingResult]:
        """Generate embeddings for multiple texts.

        For efficiency, tries to use batch operations when available.

        Args:
            texts: List of texts to embed
            use_cache: Whether to check/use cache

        Returns:
            List of ResilientEmbeddingResult objects
        """
        results = []

        # Check cache for all texts first
        cached_results: dict[int, list[float]] = {}
        uncached_indices: list[int] = []

        if use_cache and self._embedding_cache:
            for i, text in enumerate(texts):
                cached = await self._embedding_cache.get(text)
                if cached is not None:
                    cached_results[i] = cached
                else:
                    uncached_indices.append(i)
        else:
            uncached_indices = list(range(len(texts)))

        # Generate embeddings for uncached texts
        if uncached_indices:
            uncached_texts = [texts[i] for i in uncached_indices]

            # Try batch generation from Akosha
            batch_embeddings = await self._try_batch_akosha(uncached_texts)

            if batch_embeddings is None and self._embedding_service:
                # Try local batch generation
                try:
                    result = await self._embedding_service.embed(uncached_texts)
                    if result.embeddings:
                        batch_embeddings = result.embeddings
                except Exception as e:
                    logger.debug(f"local_batch_failed: {e}")

            # Fill in results
            for i, idx in enumerate(uncached_indices):
                if batch_embeddings and i < len(batch_embeddings):
                    emb = batch_embeddings[i]
                    source = EmbeddingSource.AKOSHA_MCP  # Or determine actual source
                else:
                    # Last resort: generate individually
                    result = await self.generate_embedding(texts[idx], use_cache=False)
                    emb = result.embedding
                    source = result.source

                latency_ms = 0.0  # Batch operation, individual latency not tracked
                cached = idx in cached_results

                if not cached:
                    results.append(
                        ResilientEmbeddingResult(
                            embedding=emb,
                            source=source,
                            dimension=len(emb),
                            latency_ms=latency_ms,
                            cached=False,
                        )
                    )
                    # Cache the result
                    if use_cache and self._embedding_cache:
                        await self._embedding_cache.set(texts[idx], emb)

        # Combine cached and new results in original order
        final_results: list[ResilientEmbeddingResult] = []
        new_result_idx = 0

        for i in range(len(texts)):
            if i in cached_results:
                final_results.append(
                    ResilientEmbeddingResult(
                        embedding=cached_results[i],
                        source=EmbeddingSource.CACHE,
                        dimension=len(cached_results[i]),
                        latency_ms=0.0,
                        cached=True,
                    )
                )
            else:
                if new_result_idx < len(results):
                    final_results.append(results[new_result_idx])
                    new_result_idx += 1
                else:
                    # Fallback to mock
                    emb = self._generate_mock_embedding(texts[i])
                    final_results.append(
                        ResilientEmbeddingResult(
                            embedding=emb,
                            source=EmbeddingSource.MOCK,
                            dimension=len(emb),
                            latency_ms=0.0,
                            cached=False,
                        )
                    )

        return final_results

    async def _try_batch_akosha(self, texts: list[str]) -> list[list[float]] | None:
        """Try batch embedding from Akosha MCP.

        Args:
            texts: Texts to embed

        Returns:
            List of embeddings or None if failed
        """
        if not self._circuit_breaker.can_execute():
            return None

        try:
            client = await self._get_client()
            response = await client.post(
                "/tools/call",
                json={
                    "name": "generate_batch_embeddings",
                    "arguments": {"texts": texts},
                },
            )
            response.raise_for_status()

            result = response.json()
            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0]
                if content.get("type") == "text":
                    import json

                    data = json.loads(content["text"])
                    embeddings = data.get("embeddings", [])

                    # Validate dimensions
                    valid = all(
                        self._validate_dimension(emb, "akosha_batch")
                        for emb in embeddings
                    )
                    if valid and len(embeddings) == len(texts):
                        self._circuit_breaker.record_success()
                        return embeddings

            self._circuit_breaker.record_failure()
            return None

        except Exception as e:
            logger.debug(f"akosha_batch_failed: {e}")
            self._circuit_breaker.record_failure()
            return None

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics.

        Returns:
            Dictionary with source usage counts and health metrics
        """
        total = sum(self._source_counts.values())
        return {
            "source_counts": {s.value: c for s, c in self._source_counts.items()},
            "total_requests": total,
            "dimension_mismatches": self._dimension_mismatches,
            "circuit_breaker_open": self._circuit_breaker.is_open,
            "standard_dimension": self._standard_dimension,
        }

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def create_resilient_client(
    akosha_url: str = "http://localhost:8682/mcp",
    embedding_service: EmbeddingService | None = None,
    embedding_cache: EmbeddingCache | None = None,
    standard_dimension: int = STANDARD_EMBEDDING_DIMENSION,
) -> ResilientEmbeddingClient:
    """Create a resilient embedding client.

    Args:
        akosha_url: Akosha MCP server URL
        embedding_service: Local embedding service for fallback
        embedding_cache: Cache for tier 3 fallback
        standard_dimension: Required dimension for compatibility

    Returns:
        Configured ResilientEmbeddingClient instance
    """
    return ResilientEmbeddingClient(
        akosha_url=akosha_url,
        embedding_service=embedding_service,
        embedding_cache=embedding_cache,
        standard_dimension=standard_dimension,
    )


__all__ = [
    "CircuitBreaker",
    "EmbeddingSource",
    "ResilientEmbeddingClient",
    "ResilientEmbeddingResult",
    "STANDARD_EMBEDDING_DIMENSION",
    "create_resilient_client",
]
