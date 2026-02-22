"""Unit tests for resilient embedding client."""

from __future__ import annotations

import pytest

from mahavishnu.core.resilient_embeddings import (
    CircuitBreaker,
    EmbeddingSource,
    ResilientEmbeddingClient,
    ResilientEmbeddingResult,
    STANDARD_EMBEDDING_DIMENSION,
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
