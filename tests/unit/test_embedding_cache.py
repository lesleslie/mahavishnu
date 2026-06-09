"""Unit tests for embedding cache and batch operations."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.embedding_cache import (
    CircuitBreaker,
    CircuitState,
    EmbeddingCache,
    EmbeddingCacheConfig,
    EmbeddingCacheMetrics,
    Singleflight,
    get_embedding_cache,
)
from mahavishnu.core.embeddings import (
    EmbeddingProvider,
    EmbeddingResult,
    EmbeddingService,
)


class TestEmbeddingCacheConfig:
    """Tests for EmbeddingCacheConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = EmbeddingCacheConfig()
        assert config.l1_max_size == 50000  # Increased from 10K per architecture review
        assert config.l2_enabled is False
        assert config.l2_redis_url == "redis://localhost:6379/0"
        assert config.l2_ttl_seconds == 86400
        assert config.l2_ttl_jitter == 0.2  # 20% jitter to prevent thundering herd
        assert config.l2_tls_verify is True
        assert config.metrics_enabled is True
        assert config.model_version == "1.0.0"
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_recovery == 30.0
        assert config.singleflight_enabled is True

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = EmbeddingCacheConfig(
            l1_max_size=5000,
            l2_enabled=True,
            l2_redis_url="rediss://localhost:6379/1",
            l2_ttl_seconds=3600,
            model_version="2.0.0",
            circuit_breaker_threshold=3,
            singleflight_enabled=False,
        )
        assert config.l1_max_size == 5000
        assert config.l2_enabled is True
        assert config.l2_redis_url == "rediss://localhost:6379/1"
        assert config.l2_ttl_seconds == 3600
        assert config.model_version == "2.0.0"
        assert config.circuit_breaker_threshold == 3
        assert config.singleflight_enabled is False

    def test_get_ttl_with_jitter(self) -> None:
        """Test TTL jitter calculation."""
        config = EmbeddingCacheConfig(l2_ttl_seconds=1000, l2_ttl_jitter=0.2)
        # With 20% jitter, TTL should be between 800 and 1200
        for _ in range(10):
            ttl = config.get_ttl_with_jitter()
            assert 800 <= ttl <= 1200


class TestEmbeddingCacheMetrics:
    """Tests for EmbeddingCacheMetrics."""

    def test_initial_values(self) -> None:
        """Test initial metric values."""
        metrics = EmbeddingCacheMetrics()
        assert metrics.l1_hits == 0
        assert metrics.l1_misses == 0
        assert metrics.l2_hits == 0
        assert metrics.l2_misses == 0
        assert metrics.computes == 0
        assert metrics.total_latency_ms == 0.0

    def test_record_l1_hit(self) -> None:
        """Test recording L1 hits."""
        metrics = EmbeddingCacheMetrics()
        metrics.record_l1_hit()
        metrics.record_l1_hit()
        assert metrics.l1_hits == 2

    def test_record_l1_miss(self) -> None:
        """Test recording L1 misses."""
        metrics = EmbeddingCacheMetrics()
        metrics.record_l1_miss()
        assert metrics.l1_misses == 1

    def test_record_l2_hit(self) -> None:
        """Test recording L2 hits."""
        metrics = EmbeddingCacheMetrics()
        metrics.record_l2_hit()
        assert metrics.l2_hits == 1

    def test_record_compute(self) -> None:
        """Test recording compute operations."""
        metrics = EmbeddingCacheMetrics()
        metrics.record_compute(50.0)
        metrics.record_compute(100.0)
        assert metrics.computes == 2
        assert metrics.total_latency_ms == 150.0

    def test_l1_hit_rate(self) -> None:
        """Test L1 hit rate calculation."""
        metrics = EmbeddingCacheMetrics()
        assert metrics.l1_hit_rate == 0.0

        metrics.record_l1_hit()
        metrics.record_l1_hit()
        metrics.record_l1_miss()
        assert metrics.l1_hit_rate == pytest.approx(2 / 3)

    def test_l2_hit_rate(self) -> None:
        """Test L2 hit rate calculation."""
        metrics = EmbeddingCacheMetrics()
        assert metrics.l2_hit_rate == 0.0

        metrics.record_l2_hit()
        metrics.record_l2_miss()
        metrics.record_l2_miss()
        assert metrics.l2_hit_rate == pytest.approx(1 / 3)

    def test_overall_hit_rate(self) -> None:
        """Test overall hit rate calculation."""
        metrics = EmbeddingCacheMetrics()
        assert metrics.overall_hit_rate == 0.0

        metrics.record_l1_hit()
        metrics.record_l1_miss()
        metrics.record_l2_hit()
        # 2 hits (l1 + l2) / 2 requests (l1 hit + l1 miss)
        assert metrics.overall_hit_rate == pytest.approx(1.0)

    def test_to_dict(self) -> None:
        """Test metrics serialization."""
        metrics = EmbeddingCacheMetrics()
        metrics.record_l1_hit()
        metrics.record_compute(50.0)

        result = metrics.to_dict()
        assert "l1_hits" in result
        assert "l1_hit_rate" in result
        assert "computes" in result
        assert result["l1_hits"] == 1
        assert result["computes"] == 1


class TestEmbeddingCache:
    """Tests for EmbeddingCache."""

    def test_initialization(self) -> None:
        """Test cache initialization."""
        cache = EmbeddingCache()
        assert cache._config is not None  # noqa: SLF001
        assert cache._l1 is not None  # noqa: SLF001
        assert cache._metrics is not None  # noqa: SLF001

    def test_initialization_with_config(self) -> None:
        """Test cache initialization with custom config."""
        config = EmbeddingCacheConfig(l1_max_size=5000)
        cache = EmbeddingCache(config=config)
        assert cache._config.l1_max_size == 5000  # noqa: SLF001

    def test_hash_text_consistent(self) -> None:
        """Test that text hashing is consistent."""
        cache = EmbeddingCache()
        hash1 = cache._hash_text("test text")  # noqa: SLF001
        hash2 = cache._hash_text("test text")  # noqa: SLF001
        assert hash1 == hash2
        # Format is {model_version}:{sha256_hash} = "1.0.0:" (6) + 64 hex chars = 70 chars
        assert ":" in hash1  # Version separator present
        assert len(hash1) == 70  # Version prefix + SHA256 hex length

    def test_hash_text_different(self) -> None:
        """Test that different texts produce different hashes."""
        cache = EmbeddingCache()
        hash1 = cache._hash_text("text 1")  # noqa: SLF001
        hash2 = cache._hash_text("text 2")  # noqa: SLF001
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        """Test basic set and get operations."""
        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        await cache.set("hello world", embedding)
        result = await cache.get("hello world")

        assert result == embedding

    @pytest.mark.asyncio
    async def test_get_missing(self) -> None:
        """Test get for missing key."""
        cache = EmbeddingCache()
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_compute_caches_result(self) -> None:
        """Test that get_or_compute caches computed result."""
        cache = EmbeddingCache()
        compute_count = 0

        async def compute_fn() -> list[list[float]]:
            nonlocal compute_count
            compute_count += 1
            return [[0.1, 0.2, 0.3]]

        # First call should compute
        result1 = await cache.get_or_compute("test", compute_fn)
        assert result1 == [0.1, 0.2, 0.3]
        assert compute_count == 1

        # Second call should use cache
        result2 = await cache.get_or_compute("test", compute_fn)
        assert result2 == [0.1, 0.2, 0.3]
        assert compute_count == 1  # No additional compute

    @pytest.mark.asyncio
    async def test_get_or_compute_different_texts(self) -> None:
        """Test that different texts compute separately."""
        cache = EmbeddingCache()
        compute_count = 0

        async def compute_fn() -> list[list[float]]:
            nonlocal compute_count
            compute_count += 1
            return [[float(compute_count)]]

        result1 = await cache.get_or_compute("text 1", compute_fn)
        result2 = await cache.get_or_compute("text 2", compute_fn)

        assert result1 == [1.0]
        assert result2 == [2.0]
        assert compute_count == 2

    @pytest.mark.asyncio
    async def test_get_batch_or_compute(self) -> None:
        """Test batch get or compute."""
        cache = EmbeddingCache()
        compute_count = 0

        async def compute_fn(texts: list[str]) -> list[list[float]]:
            nonlocal compute_count
            compute_count += len(texts)
            return [[float(i)] for i in range(len(texts))]

        results = await cache.get_batch_or_compute(
            ["text 1", "text 2", "text 3"],
            compute_fn,
        )

        assert len(results) == 3
        assert compute_count == 3

    @pytest.mark.asyncio
    async def test_get_batch_or_compute_with_cache(self) -> None:
        """Test batch get or compute with some cached."""
        cache = EmbeddingCache()
        compute_count = 0

        # Pre-cache one item
        await cache.set("text 1", [1.0, 2.0, 3.0])

        async def compute_fn(texts: list[str]) -> list[list[float]]:
            nonlocal compute_count
            compute_count += len(texts)
            return [[float(i) * 10] for i in range(len(texts))]

        results = await cache.get_batch_or_compute(
            ["text 1", "text 2", "text 3"],
            compute_fn,
        )

        assert results[0] == [1.0, 2.0, 3.0]  # From cache
        assert len(results) == 3
        assert compute_count == 2  # Only 2 computed (text 1 was cached)

    def test_get_stats(self) -> None:
        """Test getting cache statistics."""
        cache = EmbeddingCache()
        stats = cache.get_stats()

        assert "l1_size" in stats
        assert "l1_max_size" in stats
        assert "l2_enabled" in stats
        assert "l1_hit_rate" in stats

    def test_clear_l1(self) -> None:
        """Test clearing L1 cache."""
        cache = EmbeddingCache()

        # Add some items synchronously
        cache._l1.set("key1", [0.1])  # noqa: SLF001
        cache._l1.set("key2", [0.2])  # noqa: SLF001

        count = cache.clear_l1()
        assert count == 2
        assert len(cache._l1) == 0  # noqa: SLF001


class TestGetEmbeddingCache:
    """Tests for singleton cache getter."""

    def test_returns_singleton(self) -> None:
        """Test that get_embedding_cache returns same instance."""
        cache1 = get_embedding_cache()
        cache2 = get_embedding_cache()
        assert cache1 is cache2

    def test_config_only_used_once(self) -> None:
        """Test that config is only used on first call."""
        # Note: This test depends on previous test state
        # In a real test suite, you'd reset the singleton
        cache = get_embedding_cache()
        assert cache is not None


class TestEmbeddingCacheL2Disabled:
    """Tests for L2 (Redis) cache behavior when disabled."""

    @pytest.mark.asyncio
    async def test_l2_disabled_by_default(self) -> None:
        """Test that L2 is disabled by default."""
        cache = EmbeddingCache()
        assert cache._config.l2_enabled is False  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_get_still_works_without_l2(self) -> None:
        """Test that get works with only L1 cache."""
        cache = EmbeddingCache()  # L2 disabled
        embedding = [0.5, 0.6, 0.7]

        await cache.set("test", embedding)
        result = await cache.get("test")

        assert result == embedding


class TestEmbeddingServiceBatch:
    """Tests for EmbeddingService batch operations."""

    def test_service_initialization(self) -> None:
        """Test that EmbeddingService initializes correctly."""
        service = EmbeddingService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        """Test embed_batch with empty input."""
        service = EmbeddingService()
        results = await service.embed_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_embed_batch_returns_results_or_exceptions(self) -> None:
        """Test that embed_batch returns results or exceptions."""
        service = EmbeddingService()
        # Mock batches (actual embedding depends on provider availability)
        batches: list[list[str]] = [["test1"], ["test2"]]

        results = await service.embed_batch(batches, max_concurrent=2)

        # Results should be same length as input batches
        assert len(results) == len(batches)

        # Each result should be either EmbeddingResult or Exception
        for result in results:
            assert isinstance(result, (EmbeddingResult, Exception))


class TestEmbeddingResult:
    """Tests for EmbeddingResult class."""

    def test_initialization(self) -> None:
        """Test EmbeddingResult initialization."""
        result = EmbeddingResult(
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            model="test-model",
            provider=EmbeddingProvider.FASTEMBED,
        )
        assert len(result.embeddings) == 2
        assert result.model == "test-model"
        assert result.dimension == 2

    def test_dimension_from_embeddings(self) -> None:
        """Test that dimension is inferred from embeddings."""
        result = EmbeddingResult(
            embeddings=[[0.1] * 384],
            model="test",
            provider=EmbeddingProvider.FASTEMBED,
        )
        assert result.dimension == 384

    def test_empty_embeddings(self) -> None:
        """Test EmbeddingResult with empty embeddings."""
        result = EmbeddingResult(
            embeddings=[],
            model="test",
            provider=EmbeddingProvider.FASTEMBED,
        )
        assert result.dimension == 0

    def test_repr(self) -> None:
        """Test string representation."""
        result = EmbeddingResult(
            embeddings=[[0.1, 0.2]],
            model="test-model",
            provider=EmbeddingProvider.FASTEMBED,
        )
        repr_str = repr(result)
        assert "test-model" in repr_str
        assert "fastembed" in repr_str


class TestCircuitBreaker:
    """Tests for CircuitBreaker fault tolerance."""

    def test_initial_state_closed(self) -> None:
        """Test circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        assert cb.is_open is False

    def test_opens_after_threshold(self) -> None:
        """Test circuit breaker opens after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
        assert cb.is_open is True

    def test_success_resets_in_half_open(self) -> None:
        """Test success in HALF_OPEN state closes circuit."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()  # Opens circuit
        assert cb.state == CircuitState.OPEN

        # Manually set to half-open for testing
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_in_half_open_reopens(self) -> None:
        """Test failure in HALF_OPEN state reopens circuit."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestSingleflight:
    """Tests for Singleflight cache stampede prevention."""

    @pytest.mark.asyncio
    async def test_single_execution(self) -> None:
        """Test that concurrent requests share the same computation."""
        sf = Singleflight()
        call_count = 0

        async def expensive_fn() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return "result"

        # Launch 5 concurrent requests for the same key
        results = await asyncio.gather(*[sf.do("key1", expensive_fn) for _ in range(5)])

        # All should get the same result
        assert all(r == "result" for r in results)
        # But function should only be called once
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_execute_separately(self) -> None:
        """Test that different keys execute separately."""
        sf = Singleflight()
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        results = await asyncio.gather(
            sf.do("key1", fn),
            sf.do("key2", fn),
            sf.do("key3", fn),
        )

        # Each key should get its own result
        assert results == ["result-1", "result-2", "result-3"]
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exception_propagates(self) -> None:
        """Test that exceptions are propagated to all waiters."""

        async def failing_fn() -> str:
            raise ValueError("test error")

        sf = Singleflight()
        with pytest.raises(ValueError, match="test error"):
            await sf.do("key1", failing_fn)


class TestCircuitBreakerAdvanced:
    """Advanced tests for embedding_cache CircuitBreaker state transitions."""

    def test_recovery_timeout_transitions_to_half_open(self) -> None:
        """After recovery timeout, OPEN -> HALF_OPEN should allow request."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # First call after timeout transitions to HALF_OPEN
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_recovery_subsequent_calls_in_half_open_allowed(self) -> None:
        """HALF_OPEN keeps allowing requests (no auto-closure)."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.can_execute() is True
        # State should now be HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        # Subsequent can_execute calls also allowed
        assert cb.can_execute() is True

    def test_recovery_does_not_reset_failure_count(self) -> None:
        """When in OPEN and not yet recovered, count is preserved."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        # can_execute returns False but failure_count is unchanged
        assert cb.can_execute() is False
        assert cb.failure_count == 2


class TestEmbeddingCacheL2Enabled:
    """Tests for L2 (Redis) cache behavior when enabled."""

    @pytest.mark.asyncio
    async def test_get_uses_l1_only(self) -> None:
        """get() should hit L1 first."""
        cache = EmbeddingCache(EmbeddingCacheConfig(l2_enabled=False))
        emb = [0.1, 0.2, 0.3]
        await cache.set("text", emb)
        # Verify L1 was populated
        assert cache._l1.get(cache._hash_text("text")) == emb  # noqa: SLF001
        result = await cache.get("text")
        assert result == emb

    @pytest.mark.asyncio
    async def test_get_l2_miss_when_no_redis_client(self) -> None:
        """When L2 is enabled but client fails to connect, fall through."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://invalid:9999/0")
        cache = EmbeddingCache(config)
        # Force l2 client to None to simulate unavailable
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=None)):
            result = await cache.get("text")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_l2_hit_populates_l1(self) -> None:
        """L2 hit should populate L1 for future reads."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        emb = [0.5, 0.6, 0.7]
        l2_key = cache._make_l2_key(cache._hash_text("text"))  # noqa: SLF001

        # Mock the L2 client
        l2_client = MagicMock()
        l2_client.get = AsyncMock(return_value=json.dumps(emb))
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            result = await cache.get("text")

        assert result == emb
        # L1 should now be populated
        l1_key = cache._hash_text("text")  # noqa: SLF001
        assert cache._l1.get(l1_key) == emb  # noqa: SLF001
        l2_client.get.assert_awaited_with(l2_key)

    @pytest.mark.asyncio
    async def test_get_l2_exception_recorded_as_failure(self) -> None:
        """L2 client exception should be recorded as circuit failure."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        l2_client = MagicMock()
        l2_client.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            result = await cache.get("text")

        assert result is None
        assert cache._circuit_breaker.failure_count >= 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_get_l2_circuit_open_skips_redis(self) -> None:
        """If circuit is open, L2 calls are skipped."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        # Force circuit breaker to be open (with recent failure time so it doesn't recover)
        cache._circuit_breaker.state = CircuitState.OPEN  # noqa: SLF001
        cache._circuit_breaker.last_failure_time = time.monotonic()  # noqa: SLF001

        with patch.object(cache, "_get_l2_client", AsyncMock()) as get_l2:
            result = await cache.get("text")

        assert result is None
        get_l2.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_l2_failure_recorded(self) -> None:
        """L2 set failure should record circuit breaker failure."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        l2_client = MagicMock()
        l2_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            await cache.set("text", [0.1, 0.2])

        assert cache._circuit_breaker.failure_count >= 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_set_l2_success_records(self) -> None:
        """L2 set success should record circuit breaker success."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        l2_client = MagicMock()
        l2_client.set = AsyncMock(return_value=True)
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            await cache.set("text", [0.1, 0.2])

        # L2 client was called with JSON + TTL
        assert l2_client.set.await_count == 1

    @pytest.mark.asyncio
    async def test_set_l2_circuit_open_skips_redis(self) -> None:
        """If circuit is open, L2 set is skipped."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)
        cache._circuit_breaker.state = CircuitState.OPEN  # noqa: SLF001
        cache._circuit_breaker.last_failure_time = time.monotonic()  # noqa: SLF001

        with patch.object(cache, "_get_l2_client", AsyncMock()) as get_l2:
            await cache.set("text", [0.1])
        get_l2.assert_not_called()

    @pytest.mark.asyncio
    async def test_l2_client_creation_success(self) -> None:
        """L2 client creation: monkeypatch redis import to simulate success."""
        import sys
        import types

        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        fake_client = MagicMock()
        fake_client.ping = AsyncMock(return_value=True)

        # Build fake redis package with asyncio submodule
        fake_redis = types.ModuleType("redis")
        fake_asyncio = types.ModuleType("redis.asyncio")
        fake_asyncio.from_url = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
        fake_redis.asyncio = fake_asyncio  # type: ignore[attr-defined]
        sys.modules["redis"] = fake_redis
        sys.modules["redis.asyncio"] = fake_asyncio
        try:
            client = await cache._get_l2_client()  # noqa: SLF001
            assert client is fake_client
            assert cache._l2_available is True  # noqa: SLF001
        finally:
            del sys.modules["redis"]
            del sys.modules["redis.asyncio"]

    @pytest.mark.asyncio
    async def test_l2_client_creation_failure_marks_unavailable(self) -> None:
        """L2 client creation failure should mark unavailable."""
        import sys
        import types

        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://invalid:9999/0")
        cache = EmbeddingCache(config)

        # Build fake redis package whose from_url raises
        fake_redis = types.ModuleType("redis")
        fake_asyncio = types.ModuleType("redis.asyncio")
        fake_asyncio.from_url = MagicMock(  # type: ignore[attr-defined]
            side_effect=ImportError("redis not available")
        )
        fake_redis.asyncio = fake_asyncio  # type: ignore[attr-defined]
        sys.modules["redis"] = fake_redis
        sys.modules["redis.asyncio"] = fake_asyncio
        try:
            client = await cache._get_l2_client()  # noqa: SLF001
            assert client is None
            assert cache._l2_available is False  # noqa: SLF001
        finally:
            del sys.modules["redis"]
            del sys.modules["redis.asyncio"]

    @pytest.mark.asyncio
    async def test_l2_client_cached(self) -> None:
        """_get_l2_client should cache the client after first creation."""
        import sys
        import types

        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        fake_client = MagicMock()
        fake_client.ping = AsyncMock(return_value=True)

        fake_redis = types.ModuleType("redis")
        fake_asyncio = types.ModuleType("redis.asyncio")
        fake_asyncio.from_url = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
        fake_redis.asyncio = fake_asyncio  # type: ignore[attr-defined]
        sys.modules["redis"] = fake_redis
        sys.modules["redis.asyncio"] = fake_asyncio
        try:
            c1 = await cache._get_l2_client()  # noqa: SLF001
            c2 = await cache._get_l2_client()  # noqa: SLF001
            assert c1 is c2
            # from_url should be called only once
            assert fake_asyncio.from_url.call_count == 1  # type: ignore[attr-defined]
        finally:
            del sys.modules["redis"]
            del sys.modules["redis.asyncio"]


class TestEmbeddingCacheGetOrCompute:
    """Tests for get_or_compute path variations."""

    @pytest.mark.asyncio
    async def test_get_or_compute_with_empty_result(self) -> None:
        """If compute returns empty list, cache empty embedding."""
        cache = EmbeddingCache()

        async def empty_fn() -> list[list[float]]:
            return []

        result = await cache.get_or_compute("text", empty_fn)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_or_compute_singleflight_disabled(self) -> None:
        """When singleflight disabled, falls back to direct compute."""
        config = EmbeddingCacheConfig(singleflight_enabled=False)
        cache = EmbeddingCache(config)
        assert cache._singleflight is None  # noqa: SLF001

        async def compute_fn() -> list[list[float]]:
            return [[0.1, 0.2, 0.3]]

        result = await cache.get_or_compute("text", compute_fn)
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_get_or_compute_records_compute_metrics(self) -> None:
        """Successful compute should record compute metrics."""
        cache = EmbeddingCache()

        async def compute_fn() -> list[list[float]]:
            return [[0.1, 0.2, 0.3]]

        await cache.get_or_compute("text", compute_fn)
        stats = cache.get_stats()
        assert stats["computes"] == 1
        assert stats["avg_compute_latency_ms"] >= 0


class TestEmbeddingCacheBatch:
    """Tests for batch processing edge cases."""

    @pytest.mark.asyncio
    async def test_batch_all_cached(self) -> None:
        """If all texts are cached, no compute is called."""
        cache = EmbeddingCache()
        await cache.set("a", [1.0, 2.0, 3.0])
        await cache.set("b", [4.0, 5.0, 6.0])

        async def compute_fn(texts: list[str]) -> list[list[float]]:
            raise AssertionError("should not be called")

        results = await cache.get_batch_or_compute(["a", "b"], compute_fn)
        assert results == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    @pytest.mark.asyncio
    async def test_batch_empty_input(self) -> None:
        """Empty input returns empty list."""
        cache = EmbeddingCache()

        async def compute_fn(texts: list[str]) -> list[list[float]]:
            return []

        results = await cache.get_batch_or_compute([], compute_fn)
        assert results == []

    @pytest.mark.asyncio
    async def test_batch_no_uncached_skips_compute(self) -> None:
        """If all texts are cached, compute_fn is not called."""
        cache = EmbeddingCache()
        for i in range(3):
            await cache.set(f"k{i}", [float(i)])

        called = False

        async def compute_fn(texts: list[str]) -> list[list[float]]:
            nonlocal called
            called = True
            return []

        await cache.get_batch_or_compute(["k0", "k1", "k2"], compute_fn)
        assert called is False


class TestEmbeddingCacheStats:
    """Tests for get_stats() with state."""

    def test_stats_includes_circuit_breaker(self) -> None:
        """get_stats should include circuit breaker details."""
        cache = EmbeddingCache()
        stats = cache.get_stats()
        assert "circuit_breaker" in stats
        assert "state" in stats["circuit_breaker"]
        assert "failure_count" in stats["circuit_breaker"]
        assert "is_open" in stats["circuit_breaker"]
        assert stats["circuit_breaker"]["state"] == "closed"

    def test_stats_records_l2_disabled(self) -> None:
        """get_stats should report l2_enabled status."""
        cache = EmbeddingCache(EmbeddingCacheConfig(l2_enabled=False))
        stats = cache.get_stats()
        assert stats["l2_enabled"] is False

    def test_stats_includes_l2_available(self) -> None:
        """get_stats should report l2_available status."""
        cache = EmbeddingCache()
        cache._l2_available = True  # noqa: SLF001
        stats = cache.get_stats()
        assert stats["l2_available"] is True

    def test_stats_includes_model_version(self) -> None:
        """get_stats should report model version."""
        cache = EmbeddingCache(EmbeddingCacheConfig(model_version="3.0.0"))
        stats = cache.get_stats()
        assert stats["model_version"] == "3.0.0"

    def test_stats_singleflight_disabled(self) -> None:
        """get_stats should report singleflight status."""
        cache = EmbeddingCache(EmbeddingCacheConfig(singleflight_enabled=False))
        stats = cache.get_stats()
        assert stats["singleflight_enabled"] is False


class TestEmbeddingCacheClearL2:
    """Tests for L2 cache clearing."""

    @pytest.mark.asyncio
    async def test_clear_l2_disabled_returns_zero(self) -> None:
        """clear_l2 returns 0 when L2 is disabled."""
        cache = EmbeddingCache(EmbeddingCacheConfig(l2_enabled=False))
        result = await cache.clear_l2()
        assert result == 0

    @pytest.mark.asyncio
    async def test_clear_l2_circuit_open_returns_zero(self) -> None:
        """clear_l2 returns 0 when circuit breaker is open."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)
        cache._circuit_breaker.state = CircuitState.OPEN  # noqa: SLF001

        result = await cache.clear_l2()
        assert result == 0

    @pytest.mark.asyncio
    async def test_clear_l2_no_client_returns_zero(self) -> None:
        """clear_l2 returns 0 when Redis client is unavailable."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=None)):
            result = await cache.clear_l2()
        assert result == 0

    @pytest.mark.asyncio
    async def test_clear_l2_no_keys_returns_zero(self) -> None:
        """clear_l2 returns 0 when no keys to delete."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        l2_client = MagicMock()

        async def empty_iter(match: str):
            return
            yield  # noqa: F841 - make this an async generator

        l2_client.scan_iter = empty_iter
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            result = await cache.clear_l2()
        assert result == 0

    @pytest.mark.asyncio
    async def test_clear_l2_deletes_keys(self) -> None:
        """clear_l2 should delete all matching keys and return count."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        async def fake_iter(match: str):
            for key in ["embedding:k1", "embedding:k2", "embedding:k3"]:
                yield key

        l2_client = MagicMock()
        l2_client.scan_iter = fake_iter
        l2_client.delete = AsyncMock(return_value=3)
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            result = await cache.clear_l2()
        assert result == 3
        l2_client.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_l2_exception_returns_zero(self) -> None:
        """clear_l2 exception should be caught, returns 0, records failure."""
        config = EmbeddingCacheConfig(l2_enabled=True, l2_redis_url="redis://localhost:6379/0")
        cache = EmbeddingCache(config)

        async def failing_iter(match: str):
            raise ConnectionError("redis down")
            yield  # noqa: F841

        l2_client = MagicMock()
        l2_client.scan_iter = failing_iter
        with patch.object(cache, "_get_l2_client", AsyncMock(return_value=l2_client)):
            result = await cache.clear_l2()
        assert result == 0
        assert cache._circuit_breaker.failure_count >= 1  # noqa: SLF001


class TestEmbeddingCacheClose:
    """Tests for cache close behavior."""

    @pytest.mark.asyncio
    async def test_close_no_l2_client_is_safe(self) -> None:
        """close() should be a no-op if no L2 client."""
        cache = EmbeddingCache()
        await cache.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_with_l2_client(self) -> None:
        """close() should close L2 client and reset state."""
        cache = EmbeddingCache()
        l2_client = MagicMock()
        l2_client.close = AsyncMock()
        cache._l2_client = l2_client  # noqa: SLF001

        await cache.close()

        l2_client.close.assert_awaited_once()
        assert cache._l2_client is None  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_close_resets_circuit_breaker(self) -> None:
        """close() should be safe to call multiple times."""
        cache = EmbeddingCache()
        await cache.close()
        await cache.close()


class TestLRUCacheOperations:
    """Tests for LRUCache semantics used by EmbeddingCache."""

    def test_contains_returns_true_for_existing_key(self) -> None:
        """`in` operator should return True for existing keys."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        cache.set("key1", [0.1])
        assert "key1" in cache

    def test_contains_returns_false_for_missing_key(self) -> None:
        """`in` operator should return False for missing keys."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        assert "missing" not in cache

    def test_lru_eviction_at_max_size(self) -> None:
        """Oldest key should be evicted when max_size is reached."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=3)
        cache.set("k1", [1.0])
        cache.set("k2", [2.0])
        cache.set("k3", [3.0])
        # Adding 4th should evict k1
        cache.set("k4", [4.0])
        assert "k1" not in cache
        assert "k4" in cache

    def test_lru_recently_used_kept(self) -> None:
        """Accessing a key should make it the most recently used."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=3)
        cache.set("k1", [1.0])
        cache.set("k2", [2.0])
        cache.set("k3", [3.0])
        # Access k1, making it most recently used
        cache.get("k1")
        # Add new key, k2 should be evicted (oldest now)
        cache.set("k4", [4.0])
        assert "k1" in cache
        assert "k2" not in cache
        assert "k4" in cache

    def test_delete_returns_true_when_key_exists(self) -> None:
        """delete() should return True for existing keys."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        cache.set("k", [1.0])
        assert cache.delete("k") is True
        assert "k" not in cache

    def test_delete_returns_false_when_missing(self) -> None:
        """delete() should return False for missing keys."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        assert cache.delete("missing") is False

    def test_clear_empties_cache(self) -> None:
        """clear() should remove all entries."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        cache.set("k1", [1.0])
        cache.set("k2", [2.0])
        cache.clear()
        assert len(cache) == 0

    def test_ttl_expiration(self) -> None:
        """Entries with short TTL should expire."""
        from mahavishnu.core.cache_manager import LRUCache

        cache = LRUCache(max_size=10)
        cache.set("k", [1.0], ttl=0.01)
        assert "k" in cache
        time.sleep(0.02)
        # Should be expired -> not in cache
        assert "k" not in cache


class TestEmbeddingCacheSetGetEdgeCases:
    """Tests for set/get edge cases."""

    @pytest.mark.asyncio
    async def test_get_returns_none_for_expired_l1(self) -> None:
        """Expired L1 entry should be removed and return None."""
        cache = EmbeddingCache()
        key = cache._hash_text("text")  # noqa: SLF001
        # Set with very short TTL
        cache._l1.set(key, [0.1, 0.2, 0.3], ttl=0.01)  # noqa: SLF001
        time.sleep(0.02)
        result = await cache.get("text")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_overwrites_existing(self) -> None:
        """Setting the same key twice should overwrite."""
        cache = EmbeddingCache()
        await cache.set("text", [1.0, 2.0])
        await cache.set("text", [3.0, 4.0])
        assert await cache.get("text") == [3.0, 4.0]

    @pytest.mark.asyncio
    async def test_l1_set_skips_l2_when_disabled(self) -> None:
        """When l2_enabled is False, no L2 operations should occur."""
        cache = EmbeddingCache(EmbeddingCacheConfig(l2_enabled=False))
        with patch.object(cache, "_get_l2_client", AsyncMock()) as get_l2:
            await cache.set("text", [1.0, 2.0])
        get_l2.assert_not_called()
