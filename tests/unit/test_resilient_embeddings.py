"""Unit tests for resilient embedding client."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.embedding_cache import EmbeddingCache
from mahavishnu.core.embeddings import (
    EmbeddingProvider,
    EmbeddingResult,
    EmbeddingService,
)
from mahavishnu.core.resilient_embeddings import (
    STANDARD_EMBEDDING_DIMENSION,
    CircuitBreaker,
    EmbeddingSource,
    ResilientEmbeddingClient,
    ResilientEmbeddingResult,
    create_resilient_client,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_closed(self) -> None:
        """Test circuit breaker starts closed."""
        cb = CircuitBreaker()
        assert cb.can_execute() is True
        assert cb.is_open is False

    def test_opens_after_threshold(self) -> None:
        """Test circuit breaker opens after threshold failures."""
        cb = CircuitBreaker(failure_threshold=3)

        cb.record_failure()
        assert cb.is_open is False

        cb.record_failure()
        assert cb.is_open is False

        cb.record_failure()
        assert cb.is_open is True
        assert cb.can_execute() is False

    def test_success_resets_failures(self) -> None:
        """Test that success resets failure count."""
        cb = CircuitBreaker(failure_threshold=3)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()

        assert cb.failure_count == 0
        assert cb.is_open is False


class TestResilientEmbeddingResult:
    """Tests for ResilientEmbeddingResult."""

    def test_to_dict(self) -> None:
        """Test dictionary conversion."""
        result = ResilientEmbeddingResult(
            embedding=[0.1, 0.2, 0.3],
            source=EmbeddingSource.MOCK,
            dimension=3,
            latency_ms=1.5,
            cached=False,
        )
        d = result.to_dict()

        assert d["embedding_dim"] == 3
        assert d["source"] == "mock"
        assert d["latency_ms"] == 1.5
        assert d["cached"] is False


class TestResilientEmbeddingClient:
    """Tests for ResilientEmbeddingClient."""

    def test_initialization(self) -> None:
        """Test client initialization."""
        client = ResilientEmbeddingClient()
        assert client._standard_dimension == STANDARD_EMBEDDING_DIMENSION
        assert client._akosha_url == "http://localhost:8682/mcp"

    def test_mock_embedding_deterministic(self) -> None:
        """Test that mock embeddings are deterministic."""
        client = ResilientEmbeddingClient()

        text = "hello world"
        emb1 = client._generate_mock_embedding(text)
        emb2 = client._generate_mock_embedding(text)

        assert emb1 == emb2
        assert len(emb1) == STANDARD_EMBEDDING_DIMENSION

    def test_mock_embedding_different_texts(self) -> None:
        """Test that different texts produce different mock embeddings."""
        client = ResilientEmbeddingClient()

        emb1 = client._generate_mock_embedding("hello")
        emb2 = client._generate_mock_embedding("world")

        assert emb1 != emb2

    def test_dimension_validation(self) -> None:
        """Test dimension validation."""
        client = ResilientEmbeddingClient(standard_dimension=384)

        # Valid dimension
        valid = [0.1] * 384
        assert client._validate_dimension(valid, "test") is True

        # Invalid dimension
        invalid = [0.1] * 768
        assert client._validate_dimension(invalid, "test") is False

    def test_dimension_mismatch_tracking(self) -> None:
        """Test that dimension mismatches are tracked."""
        client = ResilientEmbeddingClient(standard_dimension=384)

        # Trigger mismatches
        client._validate_dimension([0.1] * 100, "test")
        client._validate_dimension([0.1] * 200, "test")

        assert client._dimension_mismatches == 2

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_mock_on_no_sources(self) -> None:
        """Test that mock embedding is returned when no sources available."""
        client = ResilientEmbeddingClient()

        # With no Akosha, no local service, and no cache, should return mock
        result = await client.generate_embedding("test query", use_cache=False)

        assert result.source == EmbeddingSource.MOCK
        assert len(result.embedding) == STANDARD_EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        """Test statistics retrieval."""
        client = ResilientEmbeddingClient()

        stats = client.get_stats()
        assert "source_counts" in stats
        assert "total_requests" in stats
        assert "circuit_breaker_open" in stats
        assert stats["standard_dimension"] == STANDARD_EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_close_client(self) -> None:
        """Test client cleanup."""
        client = ResilientEmbeddingClient()
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_batch_embeddings(self) -> None:
        """Test batch embedding generation."""
        client = ResilientEmbeddingClient()

        texts = ["hello", "world", "test"]
        results = await client.generate_batch_embeddings(texts, use_cache=False)

        assert len(results) == 3
        for result in results:
            assert len(result.embedding) == STANDARD_EMBEDDING_DIMENSION


class TestCreateResilientClient:
    """Tests for factory function."""

    def test_creates_client(self) -> None:
        """Test that factory creates a client."""
        client = create_resilient_client()
        assert isinstance(client, ResilientEmbeddingClient)

    def test_custom_dimension(self) -> None:
        """Test that custom dimension is accepted."""
        client = create_resilient_client(standard_dimension=768)
        assert client._standard_dimension == 768

    def test_custom_akosha_url(self) -> None:
        """Test that custom Akosha URL is accepted."""
        client = create_resilient_client(akosha_url="http://custom:8080/mcp")
        assert client._akosha_url == "http://custom:8080/mcp"


class TestCircuitBreakerRecovery:
    """Tests for circuit breaker recovery and half-open transitions."""

    def test_recovery_allows_one_trial_after_timeout(self) -> None:
        """Circuit should allow one trial after recovery timeout elapses."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        assert cb.can_execute() is False

        # Wait beyond recovery_timeout
        time.sleep(0.02)
        # Recovery attempt: one call allowed
        assert cb.can_execute() is True

    def test_success_in_half_open_closes_circuit(self) -> None:
        """A successful call after recovery should close the circuit."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.is_open is True

        time.sleep(0.02)
        assert cb.can_execute() is True  # half-open
        cb.record_success()
        assert cb.is_open is False
        assert cb.failure_count == 0

    def test_is_open_property_reflects_state(self) -> None:
        """is_open should reflect the underlying state."""
        cb = CircuitBreaker(failure_threshold=1)
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True


class TestResilientEmbeddingClientAkosha:
    """Tests for ResilientEmbeddingClient Akosha fallback paths."""

    @pytest.mark.asyncio
    async def test_akosha_success_caches_and_records_source(self) -> None:
        """Successful Akosha response should populate cache and count."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=2)
        cache = EmbeddingCache()
        client._embedding_cache = cache  # noqa: SLF001

        embedding = [0.1] * STANDARD_EMBEDDING_DIMENSION
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"embedding": ' + str(embedding).replace("'", '"') + "}",
                }
            ]
        }
        fake_response.raise_for_status = MagicMock()

        with patch.object(
            client,
            "_get_client",
            AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response))),
        ):
            result = await client.generate_embedding("hello", use_cache=True)

        assert result.source == EmbeddingSource.AKOSHA_MCP
        assert result.embedding == embedding
        # Should be cached
        cached = await cache.get("hello")
        assert cached == embedding

    @pytest.mark.asyncio
    async def test_akosha_http_failure_falls_through(self) -> None:
        """If Akosha raises, client should fall through to local/mock."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=10)
        client._embedding_service = None  # noqa: SLF001

        with patch.object(
            client,
            "_get_client",
            AsyncMock(side_effect=httpx.HTTPError("connection failed")),
        ):
            result = await client.generate_embedding("hi", use_cache=False)

        # No local service, no cache: should fall back to mock
        assert result.source == EmbeddingSource.MOCK

    @pytest.mark.asyncio
    async def test_akosha_invalid_response_falls_through(self) -> None:
        """If Akosha returns unexpected JSON shape, fall through."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=10)
        client._embedding_service = None  # noqa: SLF001

        fake_response = MagicMock()
        fake_response.json.return_value = {"unexpected": "shape"}
        fake_response.raise_for_status = MagicMock()

        with patch.object(
            client,
            "_get_client",
            AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response))),
        ):
            result = await client.generate_embedding("hi", use_cache=False)

        assert result.source == EmbeddingSource.MOCK

    @pytest.mark.asyncio
    async def test_akosha_dimension_mismatch_falls_through(self) -> None:
        """Akosha returning wrong-dim vector should be rejected (no success)."""
        client = ResilientEmbeddingClient(
            circuit_breaker_threshold=10,
            standard_dimension=STANDARD_EMBEDDING_DIMENSION,
        )
        client._embedding_service = None  # noqa: SLF001

        bad_embedding = [0.5] * 10  # Wrong dim
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"embedding": ' + str(bad_embedding) + "}",
                }
            ]
        }
        fake_response.raise_for_status = MagicMock()

        with patch.object(
            client,
            "_get_client",
            AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake_response))),
        ):
            result = await client.generate_embedding("hi", use_cache=False)

        # Falls through to mock because dimension mismatch
        assert result.source == EmbeddingSource.MOCK
        assert client._dimension_mismatches >= 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_circuit_open_short_circuits_akosha(self) -> None:
        """When circuit is open, Akosha call should be skipped."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=1)
        client._circuit_breaker._is_open = True  # noqa: SLF001
        client._circuit_breaker.last_failure_time = time.monotonic()  # noqa: SLF001

        post_mock = AsyncMock()
        with patch.object(client, "_get_client", AsyncMock()) as client_mock:
            client_mock.return_value.post = post_mock
            await client._try_akosha("anything")  # noqa: SLF001

        # No HTTP call should have been made
        post_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_try_local_service_none_when_service_unset(self) -> None:
        """Local service path returns None when service is not configured."""
        client = ResilientEmbeddingClient()
        result = await client._try_local_service("test")  # noqa: SLF001
        assert result is None

    @pytest.mark.asyncio
    async def test_try_local_service_wrong_dim_returns_none(self) -> None:
        """Local service returning wrong dim should be rejected."""
        client = ResilientEmbeddingClient(standard_dimension=STANDARD_EMBEDDING_DIMENSION)
        service = MagicMock(spec=EmbeddingService)
        service.embed = AsyncMock(
            return_value=EmbeddingResult(
                embeddings=[[0.0] * 5],  # wrong dim
                model="m",
                provider=EmbeddingProvider.FASTEMBED,
            )
        )
        client._embedding_service = service  # noqa: SLF001

        result = await client._try_local_service("test")  # noqa: SLF001
        assert result is None
        assert client._dimension_mismatches >= 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_try_local_service_exception_returns_none(self) -> None:
        """Exception in local service should be swallowed (return None)."""
        client = ResilientEmbeddingClient()
        service = MagicMock(spec=EmbeddingService)
        service.embed = AsyncMock(side_effect=RuntimeError("boom"))
        client._embedding_service = service  # noqa: SLF001

        result = await client._try_local_service("test")  # noqa: SLF001
        assert result is None

    @pytest.mark.asyncio
    async def test_try_cache_none_when_cache_unset(self) -> None:
        """Cache path returns None when cache is not configured."""
        client = ResilientEmbeddingClient()
        result = await client._try_cache("text")  # noqa: SLF001
        assert result is None

    @pytest.mark.asyncio
    async def test_try_cache_returns_embedding_on_hit(self) -> None:
        """Cache hit should return the stored embedding."""
        client = ResilientEmbeddingClient(standard_dimension=STANDARD_EMBEDDING_DIMENSION)
        cache = EmbeddingCache()
        emb = [0.1] * STANDARD_EMBEDDING_DIMENSION
        await cache.set("text", emb)
        client._embedding_cache = cache  # noqa: SLF001

        result = await client._try_cache("text")  # noqa: SLF001
        assert result == emb

    @pytest.mark.asyncio
    async def test_try_cache_wrong_dim_returns_none(self) -> None:
        """Cached value with wrong dim is rejected."""
        client = ResilientEmbeddingClient(standard_dimension=STANDARD_EMBEDDING_DIMENSION)
        cache = EmbeddingCache()
        # Set with correct dim but client expects different dim
        client._standard_dimension = 999  # noqa: SLF001
        await cache.set("text", [0.1] * STANDARD_EMBEDDING_DIMENSION)
        client._embedding_cache = cache  # noqa: SLF001

        result = await client._try_cache("text")  # noqa: SLF001
        assert result is None

    @pytest.mark.asyncio
    async def test_try_cache_exception_returns_none(self) -> None:
        """Cache exception should be swallowed (return None)."""
        client = ResilientEmbeddingClient()
        cache = MagicMock()
        cache.get = AsyncMock(side_effect=RuntimeError("boom"))
        client._embedding_cache = cache  # noqa: SLF001

        result = await client._try_cache("text")  # noqa: SLF001
        assert result is None

    @pytest.mark.asyncio
    async def test_local_service_used_when_akosha_fails(self) -> None:
        """When Akosha fails, local service should be tried."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=10)
        service = MagicMock(spec=EmbeddingService)
        emb = [0.2] * STANDARD_EMBEDDING_DIMENSION
        service.embed = AsyncMock(
            return_value=EmbeddingResult(
                embeddings=[emb],
                model="m",
                provider=EmbeddingProvider.FASTEMBED,
            )
        )
        client._embedding_service = service  # noqa: SLF001

        with patch.object(
            client,
            "_get_client",
            AsyncMock(side_effect=httpx.HTTPError("nope")),
        ):
            result = await client.generate_embedding("hello", use_cache=False)

        assert result.source == EmbeddingSource.LOCAL_SERVICE
        assert result.embedding == emb
        service.embed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_akosha_and_local(self) -> None:
        """Cache hit should return cached result without calling providers."""
        client = ResilientEmbeddingClient()
        cache = EmbeddingCache()
        emb = [0.3] * STANDARD_EMBEDDING_DIMENSION
        await cache.set("text", emb)
        client._embedding_cache = cache  # noqa: SLF001

        # No _akosha or _local_service should be hit
        with patch.object(
            client, "_try_akosha", AsyncMock(side_effect=AssertionError("should not call"))
        ) as akosha_mock, patch.object(
            client,
            "_try_local_service",
            AsyncMock(side_effect=AssertionError("should not call")),
        ) as local_mock:
            result = await client.generate_embedding("text", use_cache=True)

        assert result.source == EmbeddingSource.CACHE
        assert result.cached is True
        assert result.embedding == emb
        akosha_mock.assert_not_called()
        local_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_skipped_when_use_cache_false(self) -> None:
        """use_cache=False should bypass cache reads."""
        client = ResilientEmbeddingClient()
        cache = EmbeddingCache()
        emb = [0.4] * STANDARD_EMBEDDING_DIMENSION
        await cache.set("text", emb)
        client._embedding_cache = cache  # noqa: SLF001

        # With use_cache=False, should not consult cache
        with patch.object(
            client, "_try_cache", AsyncMock(side_effect=AssertionError("should not call"))
        ) as cache_mock:
            result = await client.generate_embedding("text", use_cache=False)

        # Mock fallback used
        assert result.source == EmbeddingSource.MOCK
        cache_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_creates_client_once(self) -> None:
        """_get_client should reuse the same client across calls."""
        client = ResilientEmbeddingClient()
        try:
            c1 = await client._get_client()  # noqa: SLF001
            c2 = await client._get_client()  # noqa: SLF001
            assert c1 is c2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        """close() called twice should not error."""
        client = ResilientEmbeddingClient()
        await client.close()
        await client.close()  # Should not raise


class TestBatchEmbeddingsEdgeCases:
    """Tests for batch embedding edge cases."""

    @pytest.mark.asyncio
    async def test_batch_empty_input(self) -> None:
        """Empty input list returns empty list."""
        client = ResilientEmbeddingClient()
        result = await client.generate_batch_embeddings([], use_cache=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_with_cache_hits(self) -> None:
        """All texts cached -> all from cache."""
        client = ResilientEmbeddingClient()
        cache = EmbeddingCache()
        e1 = [0.1] * STANDARD_EMBEDDING_DIMENSION
        e2 = [0.2] * STANDARD_EMBEDDING_DIMENSION
        await cache.set("a", e1)
        await cache.set("b", e2)
        client._embedding_cache = cache  # noqa: SLF001

        results = await client.generate_batch_embeddings(["a", "b"], use_cache=True)
        assert len(results) == 2
        assert results[0].source == EmbeddingSource.CACHE
        assert results[0].embedding == e1
        assert results[1].source == EmbeddingSource.CACHE
        assert results[1].embedding == e2

    @pytest.mark.asyncio
    async def test_batch_uses_cache_when_enabled(self) -> None:
        """With use_cache=False, the cache should not be consulted."""
        client = ResilientEmbeddingClient()
        cache = EmbeddingCache()
        client._embedding_cache = cache  # noqa: SLF001

        with patch.object(
            cache, "get", AsyncMock(side_effect=AssertionError("should not call"))
        ) as get_mock:
            await client.generate_batch_embeddings(["a"], use_cache=False)
        get_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_akosha_failure_falls_back_per_item(self) -> None:
        """When batch Akosha fails, each item is generated individually."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=1)
        # Pre-open circuit to short-circuit Akosha batch
        client._circuit_breaker._is_open = True  # noqa: SLF001
        client._circuit_breaker.last_failure_time = time.monotonic()  # noqa: SLF001

        results = await client.generate_batch_embeddings(["a", "b"], use_cache=False)
        assert len(results) == 2
        for r in results:
            # Falls through to mock
            assert r.source == EmbeddingSource.MOCK


class TestGetStatsAdvanced:
    """Tests for get_stats() with non-trivial state."""

    @pytest.mark.asyncio
    async def test_stats_records_sources_after_calls(self) -> None:
        """Stats should reflect source counts after generation calls."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=10)
        await client.generate_embedding("text1", use_cache=False)
        await client.generate_embedding("text2", use_cache=False)

        stats = client.get_stats()
        assert stats["source_counts"]["mock"] >= 2
        assert stats["total_requests"] >= 2

    @pytest.mark.asyncio
    async def test_stats_records_circuit_open(self) -> None:
        """Stats should report circuit_breaker_open=True when opened."""
        client = ResilientEmbeddingClient(circuit_breaker_threshold=1)
        client._circuit_breaker._is_open = True  # noqa: SLF001

        stats = client.get_stats()
        assert stats["circuit_breaker_open"] is True
