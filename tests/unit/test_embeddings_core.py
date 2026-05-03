"""Tests for mahavishnu.core.embeddings — data classes, circuit breaker, utilities."""

from __future__ import annotations

import time

import pytest

from mahavishnu.core.embeddings import (
    BatchEmbeddingRequest,
    BudgetConfig,
    BudgetExceededError,
    CircuitBreaker,
    CircuitState,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingQuery,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingServiceError,
    RateLimitConfig,
    ServiceOverloadedError,
    cosine_similarity,
    euclidean_distance,
)


class TestEmbeddingProvider:
    """Test EmbeddingProvider enum."""

    def test_values(self):
        assert EmbeddingProvider.FASTEMBED.value == "fastembed"
        assert EmbeddingProvider.OLLAMA.value == "ollama"
        assert EmbeddingProvider.OPENAI.value == "openai"
        assert EmbeddingProvider.SENTENCE_TRANSFORMERS.value == "sentence_transformers"


class TestEmbeddingServiceError:
    """Test exception hierarchy."""

    def test_base_error(self):
        err = EmbeddingServiceError("test")
        assert str(err) == "test"

    def test_provider_error_is_service_error(self):
        err = EmbeddingProviderError("not available")
        assert isinstance(err, EmbeddingServiceError)

    def test_budget_exceeded_error(self):
        err = BudgetExceededError("user1", 500, 1000)
        assert err.user_id == "user1"
        assert err.current == 500
        assert err.limit == 1000
        assert "Budget exceeded" in str(err)
        assert isinstance(err, EmbeddingServiceError)

    def test_service_overloaded_error(self):
        err = ServiceOverloadedError("overloaded")
        assert isinstance(err, EmbeddingServiceError)


class TestEmbeddingResult:
    """Test EmbeddingResult data class."""

    def test_basic_creation(self):
        result = EmbeddingResult(
            embeddings=[[0.1, 0.2, 0.3]],
            model="test-model",
            provider=EmbeddingProvider.OLLAMA,
        )
        assert result.embeddings == [[0.1, 0.2, 0.3]]
        assert result.model == "test-model"
        assert result.provider == EmbeddingProvider.OLLAMA
        assert result.dimension == 3
        assert result.model_version is not None
        assert len(result.model_version) == 16
        assert result.created_at is not None

    def test_explicit_dimension(self):
        result = EmbeddingResult(
            embeddings=[[1, 2, 3, 4]],
            model="m",
            provider=EmbeddingProvider.OPENAI,
            dimension=4,
        )
        assert result.dimension == 4

    def test_explicit_version(self):
        result = EmbeddingResult(
            embeddings=[[1]],
            model="m",
            provider=EmbeddingProvider.FASTEMBED,
            model_version="custom_v1",
        )
        assert result.model_version == "custom_v1"

    def test_empty_embeddings(self):
        result = EmbeddingResult(
            embeddings=[],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
        )
        assert result.dimension == 0

    def test_is_compatible_same(self):
        r1 = EmbeddingResult(
            embeddings=[[1, 2]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
        )
        r2 = EmbeddingResult(
            embeddings=[[3, 4]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
        )
        assert r1.is_compatible_with(r2) is True

    def test_is_compatible_different_model(self):
        r1 = EmbeddingResult(
            embeddings=[[1]],
            model="model-a",
            provider=EmbeddingProvider.OLLAMA,
        )
        r2 = EmbeddingResult(
            embeddings=[[1]],
            model="model-b",
            provider=EmbeddingProvider.OLLAMA,
        )
        assert r1.is_compatible_with(r2) is False

    def test_is_compatible_different_dimension(self):
        r1 = EmbeddingResult(
            embeddings=[[1, 2]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
            dimension=2,
        )
        r2 = EmbeddingResult(
            embeddings=[[1, 2, 3]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
            dimension=3,
        )
        assert r1.is_compatible_with(r2) is False

    def test_to_metadata(self):
        result = EmbeddingResult(
            embeddings=[[1]],
            model="test-model",
            provider=EmbeddingProvider.OPENAI,
        )
        meta = result.to_metadata()
        assert meta["model"] == "test-model"
        assert meta["provider"] == "openai"
        assert meta["dimension"] == 1
        assert len(meta["model_version"]) == 16
        assert "created_at" in meta

    def test_repr(self):
        result = EmbeddingResult(
            embeddings=[[1, 2]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
        )
        r = repr(result)
        assert "EmbeddingResult" in r
        assert "ollama" in r
        assert "dimension=2" in r


class TestCircuitState:
    """Test CircuitState enum."""

    def test_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreaker:
    """Test CircuitBreaker dataclass."""

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0
        assert cb.is_open is False

    def test_can_execute_closed(self):
        cb = CircuitBreaker()
        assert cb.can_execute() is True

    def test_can_execute_half_open(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN
        assert cb.can_execute() is True

    def test_open_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True
        assert cb.can_execute() is False

    def test_record_success_only_resets_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        # record_success only resets when HALF_OPEN
        cb.record_success()
        assert cb.failure_count == 2  # not reset from CLOSED state

    def test_record_success_resets_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_record_success_half_open_closes(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_recovery_timeout_transitions(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.02)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_custom_threshold(self):
        cb = CircuitBreaker(failure_threshold=10)
        for _ in range(9):
            cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True


class TestCosineSimilarity:
    """Test cosine_similarity function."""

    def test_identical_vectors(self):
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert cosine_similarity([0, 0], [1, 1]) == pytest.approx(0.0)

    def test_both_zero_vectors(self):
        assert cosine_similarity([0, 0], [0, 0]) == pytest.approx(0.0)

    def test_different_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            cosine_similarity([1, 2], [1])

    def test_3d_vectors(self):
        a = [1, 2, 3]
        b = [4, 5, 6]
        result = cosine_similarity(a, b)
        assert -1.0 <= result <= 1.0


class TestEuclideanDistance:
    """Test euclidean_distance function."""

    def test_identical_vectors(self):
        assert euclidean_distance([1, 2], [1, 2]) == pytest.approx(0.0)

    def test_simple_distance(self):
        assert euclidean_distance([0, 0], [3, 4]) == pytest.approx(5.0)

    def test_different_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            euclidean_distance([1], [1, 2])

    def test_zero_vectors(self):
        assert euclidean_distance([0, 0], [0, 0]) == pytest.approx(0.0)

    def test_3d_vectors(self):
        result = euclidean_distance([0, 0, 0], [1, 2, 2])
        assert result == pytest.approx(3.0)


class TestEmbeddingRequest:
    """Test EmbeddingRequest Pydantic model."""

    def test_valid_request(self):
        req = EmbeddingRequest(text="hello world", user_id="user1")
        assert req.text == "hello world"
        assert req.user_id == "user1"
        assert req.system_id is None

    def test_system_id(self):
        req = EmbeddingRequest(text="test", user_id="u1", system_id="sys1")
        assert req.system_id == "sys1"

    def test_empty_text_raises(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="", user_id="u1")

    def test_text_too_long_raises(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="x" * 100001, user_id="u1")

    def test_user_id_too_long_raises(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="test", user_id="u" * 257)

    def test_sanitize_removes_control_chars(self):
        req = EmbeddingRequest(text="hello\x00world", user_id="u1")
        assert "\x00" not in req.text

    def test_sanitize_strips_whitespace(self):
        req = EmbeddingRequest(text="  hello  ", user_id="u1")
        assert req.text == "hello"

    def test_sanitize_id_removes_special_chars(self):
        req = EmbeddingRequest(text="test", user_id="user<script>")
        assert "<script>" not in req.user_id


class TestBatchEmbeddingRequest:
    """Test BatchEmbeddingRequest Pydantic model."""

    def test_valid_batch(self):
        req = BatchEmbeddingRequest(texts=["a", "b"], user_id="u1")
        assert len(req.texts) == 2

    def test_empty_batch_raises(self):
        with pytest.raises(Exception):
            BatchEmbeddingRequest(texts=[], user_id="u1")

    def test_batch_too_large_raises(self):
        with pytest.raises(Exception):
            BatchEmbeddingRequest(texts=["t"] * 101, user_id="u1")

    def test_text_too_long_in_batch_raises(self):
        with pytest.raises(ValueError, match="100KB"):
            BatchEmbeddingRequest(texts=["x" * 100001], user_id="u1")


class TestEmbeddingQuery:
    """Test EmbeddingQuery Pydantic model."""

    def test_valid_query(self):
        q = EmbeddingQuery(query="search term")
        assert q.query == "search term"
        assert q.limit == 10
        assert q.threshold == 0.0

    def test_custom_params(self):
        q = EmbeddingQuery(query="test", limit=50, threshold=0.5)
        assert q.limit == 50
        assert q.threshold == 0.5

    def test_limit_bounds(self):
        q = EmbeddingQuery(query="test", limit=1)
        assert q.limit == 1

    def test_empty_query_raises(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="")

    def test_query_too_long_raises(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="x" * 10001)

    def test_sanitize_escaping(self):
        q = EmbeddingQuery(query="it's a test")
        assert "''" in q.query


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.max_batch_size == 100
        assert cfg.max_text_length == 100000
        assert cfg.max_concurrent == 5
        assert cfg.timeout_seconds == 60.0


class TestBudgetConfig:
    """Test BudgetConfig dataclass."""

    def test_defaults(self):
        cfg = BudgetConfig()
        assert cfg.enabled is False
        assert cfg.daily_limit == 1000000
        assert cfg.alert_threshold == 0.8
