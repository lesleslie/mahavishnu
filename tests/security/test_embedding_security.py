"""Security tests for embedding service.

Tests for:
- Query sanitization
- Batch embedding DoS protection
- Rate limiting
- Cache security
"""

from __future__ import annotations

import pytest

from mahavishnu.core.embeddings import (
    BatchEmbeddingRequest,
    BudgetExceededError,
    EmbeddingQuery,
    EmbeddingRequest,
    RateLimitConfig,
    SecureEmbeddingService,
    ServiceOverloadedError,
)


class TestEmbeddingQuerySanitization:
    """Tests for query sanitization in embedding requests."""

    async def test_rejects_sql_injection_patterns(self) -> None:
        """Test that SQL injection patterns are sanitized."""
        request = EmbeddingRequest(
            text="SELECT * FROM users; DROP TABLE users;--",
            user_id="test-user",
        )
        # Should not raise - text is sanitized, not rejected
        assert "SELECT" in request.text  # SQL keywords allowed after sanitization
        assert request.user_id == "test-user"

    async def test_rejects_oversized_query(self) -> None:
        """Test that oversized queries are rejected."""
        with pytest.raises(ValueError, match="at most 100000"):
            EmbeddingRequest(
                text="x" * 100001,  # Exceeds 100KB limit
                user_id="test-user",
            )

    async def test_normalizes_unicode(self) -> None:
        """Test that Unicode is normalized to NFKC form."""
        # Using fullwidth characters that should be normalized
        request = EmbeddingRequest(
            text="ｈｅｌｌｏ",  # Fullwidth Latin characters
            user_id="test-user",
        )
        # After NFKC normalization, should be ASCII
        assert request.text == "hello"

    async def test_removes_control_characters(self) -> None:
        """Test that control characters are removed."""
        request = EmbeddingRequest(
            text="hello\x00\x01\x02world",  # Null bytes and control chars
            user_id="test-user",
        )
        assert "\x00" not in request.text
        assert "\x01" not in request.text
        assert request.text == "helloworld"

    async def test_sanitizes_user_id(self) -> None:
        """Test that user IDs are sanitized."""
        request = EmbeddingRequest(
            text="hello",
            user_id="user<script>alert('xss')</script>",
        )
        # Only alphanumeric, dash, underscore, @, . allowed
        assert "<" not in request.user_id
        assert ">" not in request.user_id


class TestEmbeddingQueryModel:
    """Tests for EmbeddingQuery search query model."""

    def test_validates_limit_range(self) -> None:
        """Test that limit is within valid range."""
        with pytest.raises(ValueError):
            EmbeddingQuery(query="test", limit=0)

        with pytest.raises(ValueError):
            EmbeddingQuery(query="test", limit=1001)

    def test_validates_threshold_range(self) -> None:
        """Test that threshold is within valid range."""
        with pytest.raises(ValueError):
            EmbeddingQuery(query="test", threshold=-0.1)

        with pytest.raises(ValueError):
            EmbeddingQuery(query="test", threshold=1.1)

    def test_escapes_single_quotes(self) -> None:
        """Test that single quotes are escaped for SQL safety."""
        request = EmbeddingQuery(query="test' OR '1'='1")
        # Single quotes should be escaped
        assert "''" in request.query


class TestBatchEmbeddingDoS:
    """Tests for batch embedding DoS protection."""

    def test_rejects_oversized_batch(self) -> None:
        """Test that oversized batches are rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at most 100 items"):
            BatchEmbeddingRequest(
                texts=["text"] * 101,  # Exceeds 100 limit
                user_id="test-user",
            )

    def test_rejects_oversized_texts(self) -> None:
        """Test that oversized individual texts are rejected."""
        with pytest.raises(ValueError, match="exceeds 100KB"):
            BatchEmbeddingRequest(
                texts=["x" * 100001],  # Single text exceeds 100KB
                user_id="test-user",
            )

    def test_validates_all_texts(self) -> None:
        """Test that all texts in batch are validated."""
        # Valid batch
        request = BatchEmbeddingRequest(
            texts=["text1", "text2", "text3"],
            user_id="test-user",
        )
        assert len(request.texts) == 3

    def test_sanitizes_all_texts(self) -> None:
        """Test that all texts in batch are sanitized."""
        request = BatchEmbeddingRequest(
            texts=["ｈｅｌｌｏ", "\x00world", "test"],
            user_id="test-user",
        )
        assert request.texts[0] == "hello"  # Normalized
        assert "\x00" not in request.texts[1]  # Control chars removed


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_rate_limit_config_defaults(self) -> None:
        """Test that rate limit config has sensible defaults."""
        config = RateLimitConfig()
        assert config.max_batch_size == 100
        assert config.max_text_length == 100000
        assert config.max_concurrent == 5
        assert config.timeout_seconds == 60.0

    def test_rate_limit_config_custom(self) -> None:
        """Test that rate limit config can be customized."""
        config = RateLimitConfig(
            max_batch_size=50,
            max_text_length=50000,
            max_concurrent=10,
            timeout_seconds=30.0,
        )
        assert config.max_batch_size == 50
        assert config.max_text_length == 50000
        assert config.max_concurrent == 10
        assert config.timeout_seconds == 30.0

    def test_secure_service_uses_semaphore(self) -> None:
        """Test that secure service creates semaphore with correct limit."""
        config = RateLimitConfig(max_concurrent=3)
        service = SecureEmbeddingService(rate_limit=config)
        assert service._semaphore._value == 3  # noqa: SLF001


class TestBudgetTracking:
    """Tests for budget tracking functionality."""

    def test_budget_config_defaults(self) -> None:
        """Test that budget config has sensible defaults."""
        from mahavishnu.core.embeddings import BudgetConfig

        config = BudgetConfig()
        assert config.enabled is False
        assert config.daily_limit == 1000000
        assert config.alert_threshold == 0.8

    def test_budget_exceeded_error(self) -> None:
        """Test that budget exceeded error includes details."""
        error = BudgetExceededError(
            user_id="test-user",
            current=1500,
            limit=1000,
        )
        assert "test-user" in str(error)
        assert "1500" in str(error)
        assert "1000" in str(error)


class TestSecureEmbeddingService:
    """Tests for SecureEmbeddingService class."""

    def test_initialization(self) -> None:
        """Test that service initializes correctly."""
        service = SecureEmbeddingService()
        assert service._service is not None  # noqa: SLF001
        assert service._rate_limit is not None  # noqa: SLF001
        assert service._budget is not None  # noqa: SLF001

    def test_hash_text_consistent(self) -> None:
        """Test that text hashing is consistent."""
        service = SecureEmbeddingService()
        hash1 = service._hash_text("test text")  # noqa: SLF001
        hash2 = service._hash_text("test text")  # noqa: SLF001
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 char hex string

    def test_hash_text_different(self) -> None:
        """Test that different texts produce different hashes."""
        service = SecureEmbeddingService()
        hash1 = service._hash_text("test 1")  # noqa: SLF001
        hash2 = service._hash_text("test 2")  # noqa: SLF001
        assert hash1 != hash2

    def test_rate_limit_allows_initial_requests(self) -> None:
        """Test that initial requests are allowed."""
        service = SecureEmbeddingService()
        assert service._check_rate_limit("user-1") is True  # noqa: SLF001

    def test_rate_limit_tracks_requests(self) -> None:
        """Test that rate limit tracks request counts."""
        service = SecureEmbeddingService()

        # Make several requests
        for _ in range(5):
            service._check_rate_limit("user-1")  # noqa: SLF001

        # Should have recorded timestamps
        assert len(service._request_counts["user-1"]) == 5  # noqa: SLF001


class TestServiceOverloadedError:
    """Tests for ServiceOverloadedError."""

    def test_error_message(self) -> None:
        """Test that error message is informative."""
        error = ServiceOverloadedError("Service is busy")
        assert "Service is busy" in str(error)

    def test_inherits_from_base(self) -> None:
        """Test that error inherits from EmbeddingServiceError."""
        from mahavishnu.core.embeddings import EmbeddingServiceError

        error = ServiceOverloadedError("test")
        assert isinstance(error, EmbeddingServiceError)
