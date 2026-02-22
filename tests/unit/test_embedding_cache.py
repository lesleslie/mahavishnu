"""Unit tests for embedding cache and batch operations."""

from __future__ import annotations

import asyncio

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

