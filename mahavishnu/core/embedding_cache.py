"""Two-tier embedding cache with L1 (memory) and L2 (Redis) support.

Provides efficient caching for embedding vectors:
- L1: In-memory LRU cache for fast access (~100ns latency)
- L2: Redis cache for distributed sharing (~1ms latency)
- Automatic cache key hashing for security
- Prometheus metrics for monitoring

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │                  EmbeddingCache                          │
    ├─────────────────────────────────────────────────────────┤
    │  L1 Cache (In-Memory LRU)                               │
    │  - 10,000 entries max                                   │
    │  - ~100ns latency                                       │
    ├─────────────────────────────────────────────────────────┤
    │  L2 Cache (Redis)                                       │
    │  - 1M+ entries                                          │
    │  - ~1ms latency                                         │
    │  - TTL: 24 hours                                        │
    ├─────────────────────────────────────────────────────────┤
    │  Compute (FastEmbed/Ollama/OpenAI)                      │
    │  - ~50-500ms latency                                    │
    └─────────────────────────────────────────────────────────┘

Usage:
    from mahavishnu.core.embedding_cache import EmbeddingCache, EmbeddingCacheConfig

    cache = EmbeddingCache()

    # Get embedding (checks L1 -> L2 -> compute)
    embedding = await cache.get_or_compute(
        text="hello world",
        compute_fn=lambda: embedding_service.embed(["hello world"])
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine

from mahavishnu.core.cache_manager import LRUCache

logger = logging.getLogger(__name__)

# Type alias for compute function
ComputeFn = Callable[[], Coroutine[Any, Any, list[list[float]]]]


class CircuitState(Enum):
    """Circuit breaker states for Redis."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for Redis fault tolerance.

    Prevents cascading failures when Redis is unavailable,
    allowing the cache to gracefully fall back to L1 + compute.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    failure_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    last_failure_time: float = 0.0

    def can_execute(self) -> bool:
        """Check if Redis requests should be allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("redis-circuit-breaker-half-open")
                return True
            return False

        return True  # HALF_OPEN allows one request

    def record_success(self) -> None:
        """Record successful Redis operation."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("redis-circuit-breaker-closed")

    def record_failure(self) -> None:
        """Record failed Redis operation."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("redis-circuit-breaker-reopened")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "redis-circuit-breaker-opened",
                extra={"failure_count": self.failure_count},
            )

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        return self.state == CircuitState.OPEN


class Singleflight:
    """Prevents cache stampede by coalescing concurrent requests.

    When multiple concurrent requests arrive for the same uncached key,
    only one computation is performed and all waiters receive the result.

    This prevents thundering herd problems at cold start or when keys expire.
    """

    def __init__(self) -> None:
        self._in_flight: dict[str, asyncio.Future] = {}

    async def do(self, key: str, fn: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        """Execute fn only once for concurrent requests with same key.

        Args:
            key: Cache key being requested
            fn: Async function to compute value if not in flight

        Returns:
            Result of fn (shared among all concurrent callers)
        """
        # If already computing, wait for existing result
        if key in self._in_flight:
            return await self._in_flight[key]

        # Create future for this computation
        future: asyncio.Future = asyncio.Future()
        self._in_flight[key] = future

        try:
            result = await fn()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            del self._in_flight[key]


@dataclass
class EmbeddingCacheConfig:
    """Configuration for embedding cache.

    Attributes:
        l1_max_size: Maximum entries in L1 (memory) cache
        l2_enabled: Whether L2 (Redis) cache is enabled
        l2_redis_url: Redis connection URL (use rediss:// for TLS)
        l2_ttl_seconds: TTL for L2 cache entries (base value)
        l2_ttl_jitter: Jitter factor for TTL (0.0-1.0, prevents thundering herd)
        l2_tls_verify: Whether to verify TLS certificate
        metrics_enabled: Whether to emit Prometheus metrics
        model_version: Version string for cache key namespacing
        circuit_breaker_threshold: Failures before opening circuit
        circuit_breaker_recovery: Seconds before retry
        singleflight_enabled: Whether to coalesce concurrent requests
    """

    l1_max_size: int = 50000  # Increased from 10K per architecture review
    l2_enabled: bool = False
    l2_redis_url: str = "redis://localhost:6379/0"
    l2_ttl_seconds: int = 86400  # 24 hours base
    l2_ttl_jitter: float = 0.2  # +/- 20% jitter
    l2_tls_verify: bool = True
    metrics_enabled: bool = True
    model_version: str = "1.0.0"  # Bump on model change to invalidate cache
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery: float = 30.0
    singleflight_enabled: bool = True

    def get_ttl_with_jitter(self) -> int:
        """Get TTL with random jitter to prevent synchronized expiration.

        Returns:
            TTL in seconds with jitter applied
        """
        jitter = self.l2_ttl_seconds * self.l2_ttl_jitter * (2 * random.random() - 1)
        return int(self.l2_ttl_seconds + jitter)


@dataclass
class EmbeddingCacheMetrics:
    """Metrics for embedding cache monitoring.

    Attributes:
        l1_hits: L1 cache hits
        l1_misses: L1 cache misses
        l2_hits: L2 cache hits
        l2_misses: L2 cache misses
        computes: Number of embeddings computed
        total_latency_ms: Total latency in milliseconds
    """

    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0
    computes: int = 0
    total_latency_ms: float = 0.0

    def record_l1_hit(self) -> None:
        """Record an L1 cache hit."""
        self.l1_hits += 1

    def record_l1_miss(self) -> None:
        """Record an L1 cache miss."""
        self.l1_misses += 1

    def record_l2_hit(self) -> None:
        """Record an L2 cache hit."""
        self.l2_hits += 1

    def record_l2_miss(self) -> None:
        """Record an L2 cache miss."""
        self.l2_misses += 1

    def record_compute(self, latency_ms: float) -> None:
        """Record an embedding computation.

        Args:
            latency_ms: Latency in milliseconds
        """
        self.computes += 1
        self.total_latency_ms += latency_ms

    @property
    def l1_hit_rate(self) -> float:
        """Calculate L1 cache hit rate."""
        total = self.l1_hits + self.l1_misses
        return self.l1_hits / total if total > 0 else 0.0

    @property
    def l2_hit_rate(self) -> float:
        """Calculate L2 cache hit rate."""
        total = self.l2_hits + self.l2_misses
        return self.l2_hits / total if total > 0 else 0.0

    @property
    def overall_hit_rate(self) -> float:
        """Calculate overall cache hit rate."""
        total_hits = self.l1_hits + self.l2_hits
        total_requests = self.l1_hits + self.l1_misses
        return total_hits / total_requests if total_requests > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "l1_hits": self.l1_hits,
            "l1_misses": self.l1_misses,
            "l1_hit_rate": f"{self.l1_hit_rate:.2%}",
            "l2_hits": self.l2_hits,
            "l2_misses": self.l2_misses,
            "l2_hit_rate": f"{self.l2_hit_rate:.2%}",
            "overall_hit_rate": f"{self.overall_hit_rate:.2%}",
            "computes": self.computes,
            "avg_compute_latency_ms": (
                self.total_latency_ms / self.computes if self.computes > 0 else 0
            ),
        }


class EmbeddingCache:
    """Two-tier embedding cache with L1 (memory) and L2 (Redis) support.

    Features:
    - L1 in-memory LRU cache for ultra-fast access
    - L2 Redis cache for distributed sharing
    - Automatic cache key hashing for security
    - Metrics collection for monitoring
    - Graceful fallback when Redis unavailable

    Example:
        cache = EmbeddingCache()

        # Simple get/set
        await cache.set("hello world", [0.1, 0.2, 0.3])
        embedding = await cache.get("hello world")

        # Get or compute pattern
        embedding = await cache.get_or_compute(
            text="hello world",
            compute_fn=lambda: service.embed(["hello world"])
        )
    """

    NAMESPACE = "embedding"

    def __init__(
        self,
        config: EmbeddingCacheConfig | None = None,
    ):
        """Initialize embedding cache.

        Args:
            config: Cache configuration (uses defaults if not provided)
        """
        self._config = config or EmbeddingCacheConfig()
        self._l1 = LRUCache(max_size=self._config.l1_max_size)
        self._l2_client: Any = None  # Redis client, lazy loaded
        self._metrics = EmbeddingCacheMetrics()
        self._l2_available: bool | None = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self._config.circuit_breaker_threshold,
            recovery_timeout=self._config.circuit_breaker_recovery,
        )
        self._singleflight = Singleflight() if self._config.singleflight_enabled else None

    def _hash_text(self, text: str) -> str:
        """Create versioned cache key hash from text.

        Uses SHA256 for consistent, collision-resistant hashing.
        Includes model_version in the key to invalidate cache on model changes.

        Args:
            text: Input text

        Returns:
            Versioned hash string for cache key
        """
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self._config.model_version}:{text_hash}"

    def _make_l2_key(self, key: str) -> str:
        """Create full L2 (Redis) key with namespace.

        Args:
            key: Versioned key from _hash_text

        Returns:
            Full Redis key with namespace prefix
        """
        return f"{self.NAMESPACE}:{key}"

    async def _get_l2_client(self) -> Any:
        """Get or create Redis client for L2 cache.

        Returns:
            Redis client or None if unavailable
        """
        if self._l2_client is not None:
            return self._l2_client

        if not self._config.l2_enabled:
            return None

        try:
            import redis.asyncio as aioredis

            self._l2_client = aioredis.from_url(
                self._config.l2_redis_url,
                decode_responses=True,
                ssl_cert_reqs="required" if self._config.l2_tls_verify else "none",
            )
            # Test connection
            await self._l2_client.ping()
            self._l2_available = True
            logger.info("L2 Redis cache connected")
            return self._l2_client
        except Exception as e:
            logger.warning(f"L2 Redis cache unavailable: {e}")
            self._l2_available = False
            return None

    async def get(self, text: str) -> list[float] | None:
        """Get embedding from cache.

        Checks L1 first, then L2 with circuit breaker protection.

        Args:
            text: Text to look up

        Returns:
            Cached embedding or None if not found
        """
        key = self._hash_text(text)

        # Check L1
        result = self._l1.get(key)
        if result is not None:
            self._metrics.record_l1_hit()
            return result

        self._metrics.record_l1_miss()

        # Check L2 with circuit breaker
        if self._config.l2_enabled and self._circuit_breaker.can_execute():
            client = await self._get_l2_client()
            if client is not None:
                try:
                    cached = await client.get(self._make_l2_key(key))
                    if cached is not None:
                        embedding = json.loads(cached)
                        # Populate L1 cache
                        self._l1.set(key, embedding)
                        self._metrics.record_l2_hit()
                        self._circuit_breaker.record_success()
                        return embedding
                except Exception as e:
                    logger.debug(f"L2 cache get failed: {e}")
                    self._circuit_breaker.record_failure()

            self._metrics.record_l2_miss()

        return None

    async def set(
        self,
        text: str,
        embedding: list[float],
    ) -> None:
        """Set embedding in cache.

        Stores in both L1 and L2 with TTL jitter for L2.

        Args:
            text: Text key
            embedding: Embedding vector
        """
        key = self._hash_text(text)

        # Set in L1
        self._l1.set(key, embedding)

        # Set in L2 with circuit breaker protection and TTL jitter
        if self._config.l2_enabled and self._circuit_breaker.can_execute():
            client = await self._get_l2_client()
            if client is not None:
                try:
                    ttl = self._config.get_ttl_with_jitter()
                    await client.set(
                        self._make_l2_key(key),
                        json.dumps(embedding),
                        ex=ttl,
                    )
                    self._circuit_breaker.record_success()
                except Exception as e:
                    logger.debug(f"L2 cache set failed: {e}")
                    self._circuit_breaker.record_failure()

    async def get_or_compute(
        self,
        text: str,
        compute_fn: ComputeFn,
    ) -> list[float]:
        """Get embedding from cache or compute if not found.

        This is the primary method for cache usage. Uses singleflight
        pattern to prevent cache stampede when multiple concurrent
        requests arrive for the same uncached key.

        Args:
            text: Text to embed
            compute_fn: Async function to compute embedding if not cached

        Returns:
            Embedding vector (from cache or computed)
        """
        # Try cache first
        cached = await self.get(text)
        if cached is not None:
            return cached

        # Use singleflight to prevent cache stampede
        if self._singleflight is not None:
            key = self._hash_text(text)

            async def _compute_and_cache() -> list[float]:
                start_time = time.perf_counter()
                result = await compute_fn()
                latency_ms = (time.perf_counter() - start_time) * 1000

                embedding = result[0] if result else []
                await self.set(text, embedding)
                self._metrics.record_compute(latency_ms)
                return embedding

            return await self._singleflight.do(key, _compute_and_cache)

        # Fallback without singleflight
        start_time = time.perf_counter()
        result = await compute_fn()
        latency_ms = (time.perf_counter() - start_time) * 1000

        embedding = result[0] if result else []
        await self.set(text, embedding)
        self._metrics.record_compute(latency_ms)

        return embedding

    async def get_batch_or_compute(
        self,
        texts: list[str],
        compute_fn: Callable[[list[str]], Coroutine[Any, Any, list[list[float]]]],
    ) -> list[list[float]]:
        """Get batch of embeddings from cache or compute missing ones.

        Efficiently handles batch requests by:
        1. Checking cache for each text
        2. Computing only missing embeddings
        3. Caching new results

        Args:
            texts: List of texts to embed
            compute_fn: Async function to compute embeddings for uncached texts

        Returns:
            List of embedding vectors
        """
        results: list[list[float]] = []
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache for each text
        for i, text in enumerate(texts):
            cached = await self.get(text)
            if cached is not None:
                results.append(cached)
            else:
                results.append([])  # Placeholder
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Compute missing embeddings
        if uncached_texts:
            start_time = time.perf_counter()
            computed = await compute_fn(uncached_texts)
            latency_ms = (time.perf_counter() - start_time) * 1000

            # Fill in results and cache
            for idx, text, embedding in zip(
                uncached_indices, uncached_texts, computed
            ):
                results[idx] = embedding
                await self.set(text, embedding)

            # Record metrics
            self._metrics.record_compute(latency_ms)

        return results

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache metrics including circuit breaker status
        """
        stats = self._metrics.to_dict()
        stats["l1_size"] = len(self._l1)
        stats["l1_max_size"] = self._config.l1_max_size
        stats["l2_enabled"] = self._config.l2_enabled
        stats["l2_available"] = self._l2_available
        stats["model_version"] = self._config.model_version
        stats["singleflight_enabled"] = self._config.singleflight_enabled
        stats["circuit_breaker"] = {
            "state": self._circuit_breaker.state.value,
            "failure_count": self._circuit_breaker.failure_count,
            "is_open": self._circuit_breaker.is_open,
        }
        return stats

    def clear_l1(self) -> int:
        """Clear L1 cache.

        Returns:
            Number of entries cleared
        """
        count = len(self._l1)
        self._l1.clear()
        return count

    async def clear_l2(self) -> int:
        """Clear L2 cache with circuit breaker protection.

        Returns:
            Number of entries cleared (approximate)
        """
        if not self._config.l2_enabled:
            return 0

        if not self._circuit_breaker.can_execute():
            logger.warning("L2 cache clear skipped: circuit breaker open")
            return 0

        client = await self._get_l2_client()
        if client is None:
            return 0

        try:
            # Find and delete all embedding keys
            keys: list[str] = []
            async for key in client.scan_iter(match=f"{self.NAMESPACE}:*"):
                keys.append(key)

            if keys:
                await client.delete(*keys)
                self._circuit_breaker.record_success()
                return len(keys)
            return 0
        except Exception as e:
            logger.warning(f"L2 cache clear failed: {e}")
            self._circuit_breaker.record_failure()
            return 0

    async def close(self) -> None:
        """Close cache connections."""
        if self._l2_client is not None:
            await self._l2_client.close()
            self._l2_client = None


# Singleton instance
_embedding_cache: EmbeddingCache | None = None


def get_embedding_cache(
    config: EmbeddingCacheConfig | None = None,
) -> EmbeddingCache:
    """Get singleton embedding cache instance.

    Args:
        config: Cache configuration (only used on first call)

    Returns:
        EmbeddingCache singleton
    """
    global _embedding_cache

    if _embedding_cache is None:
        _embedding_cache = EmbeddingCache(config=config)

    return _embedding_cache


__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "EmbeddingCache",
    "EmbeddingCacheConfig",
    "EmbeddingCacheMetrics",
    "Singleflight",
    "get_embedding_cache",
]
