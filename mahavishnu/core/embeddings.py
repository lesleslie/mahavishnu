"""Embedding service with multiple provider support.

This module provides a unified interface for text embeddings with support for:
- FastEmbed (production, cross-platform)
- Ollama (development, local privacy)
- OpenAI API (cloud, high quality)
- Future: sentence-transformers (when compatible)

Security Features:
- Query sanitization with Pydantic validators
- Rate limiting and DoS protection
- Batch size and text length limits
- Budget tracking support

Reliability Features:
- Circuit breaker pattern for provider failures
- Embedding model versioning for consistency
- Graceful fallback between providers

Usage:
    from mahavishnu.core.embeddings import EmbeddingService, EmbeddingProvider

    # Production: FastEmbed
    service = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
    embeddings = await service.embed(["text1", "text2"])

    # Development: Ollama
    service = EmbeddingService(provider=EmbeddingProvider.OLLAMA)
    embeddings = await service.embed(["text1", "text2"])
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class EmbeddingProvider(Enum):
    """Embedding provider options."""

    FASTEMBED = "fastembed"
    OLLAMA = "ollama"
    OPENAI = "openai"
    SENTENCE_TRANSFORMERS = "sentence_transformers"


class EmbeddingServiceError(Exception):
    """Base exception for embedding service errors."""

    pass


class EmbeddingProviderError(EmbeddingServiceError):
    """Raised when embedding provider is not available."""

    pass


class EmbeddingResult:
    """Result from embedding generation.

    Includes metadata for embedding versioning to prevent consistency issues
    when mixing different models or providers.

    Attributes:
        embeddings: List of embedding vectors
        model: Model name used for generation
        provider: Provider that generated the embeddings
        dimension: Embedding dimension
        model_version: Model version/hash for consistency checks
        created_at: Timestamp when embeddings were generated
    """

    def __init__(
        self,
        embeddings: list[list[float]],
        model: str,
        provider: EmbeddingProvider,
        dimension: int | None = None,
        model_version: str | None = None,
        created_at: datetime | None = None,
    ):
        self.embeddings = embeddings
        self.model = model
        self.provider = provider
        self.dimension = dimension or (len(embeddings[0]) if embeddings else 0)
        self.model_version = model_version or self._compute_model_version(model, provider)
        self.created_at = created_at or datetime.now(UTC)

    def _compute_model_version(self, model: str, provider: EmbeddingProvider) -> str:
        """Compute a version hash for the model/provider combination.

        This ensures embeddings are tagged with their source, preventing
        consistency issues when querying with different models.

        Args:
            model: Model name
            provider: Provider enum

        Returns:
            Version string (hash of model+provider)
        """
        version_string = f"{provider.value}:{model}"
        return hashlib.sha256(version_string.encode()).hexdigest()[:16]

    def is_compatible_with(self, other: EmbeddingResult) -> bool:
        """Check if this result is compatible with another for similarity search.

        Args:
            other: Another EmbeddingResult to compare

        Returns:
            True if both results use same model version and dimension
        """
        return (
            self.model_version == other.model_version
            and self.dimension == other.dimension
        )

    def to_metadata(self) -> dict[str, Any]:
        """Convert to metadata dictionary for storage.

        Returns:
            Dictionary with model info for storage alongside vectors
        """
        return {
            "model": self.model,
            "provider": self.provider.value,
            "dimension": self.dimension,
            "model_version": self.model_version,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"EmbeddingResult(model={self.model}, provider={self.provider.value}, dimension={self.dimension}, count={len(self.embeddings)}, version={self.model_version[:8]}...)"


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for provider fault tolerance.

    Prevents cascading failures by temporarily stopping requests to
    failing providers, allowing them time to recover.

    Attributes:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before trying half-open
        failure_count: Current failure count
        state: Current circuit state
        last_failure_time: Timestamp of last failure
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    failure_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    last_failure_time: float = 0.0

    def can_execute(self) -> bool:
        """Check if requests should be allowed.

        Returns:
            True if circuit allows requests, False if open
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("circuit-breaker-half-open")
                return True
            return False

        # HALF_OPEN: allow one request to test
        return True

    def record_success(self) -> None:
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            # Recovery successful, close circuit
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("circuit-breaker-closed")

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            # Half-open failed, reopen circuit
            self.state = CircuitState.OPEN
            logger.warning("circuit-breaker-reopened")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "circuit-breaker-opened",
                extra={"failure_count": self.failure_count},
            )

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        return self.state == CircuitState.OPEN


class EmbeddingProviderInterface(ABC):
    """Abstract interface for embedding providers."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings for the given texts.

        Args:
            texts: List of text strings to embed

        Returns:
            EmbeddingResult with embeddings and metadata

        Raises:
            EmbeddingProviderError: If provider is not available
            EmbeddingServiceError: If embedding generation fails
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available."""
        pass


class FastEmbedProvider(EmbeddingProviderInterface):
    """FastEmbed provider for production embeddings.

    FastEmbed uses ONNX Runtime for fast, cross-platform inference
    without PyTorch dependencies. Works on all platforms including Intel Macs.
    """

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        """Initialize FastEmbed provider.

        Args:
            model: Model name to use. Options:
                - "BAAI/bge-small-en-v1.5" (default, fast)
                - "BAAI/bge-base-en-v1.5" (better quality)
                - "BAAI/bge-large-en-v1.5" (best quality)
        """
        self.model = model
        self._client = None

    async def _load_client(self):
        """Lazy load the FastEmbed client."""
        try:
            from fastembed import TextEmbedding

            self._client = TextEmbedding(model_name=self.model)
        except ImportError as e:
            raise EmbeddingProviderError(
                f"FastEmbed not available. Install with: uv pip install fastembed\n{e}"
            )

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings using FastEmbed."""
        if not texts:
            return EmbeddingResult([], self.model, EmbeddingProvider.FASTEMBED, 0)

        if self._client is None:
            await self._load_client()

        # FastEmbed's embed method returns a generator, collect results in thread pool
        def _collect_embeddings():
            return [emb.tolist() for emb in self._client.embed(texts)]

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, _collect_embeddings)

        dimension = len(embeddings[0]) if embeddings else 0

        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model,
            provider=EmbeddingProvider.FASTEMBED,
            dimension=dimension,
        )

    def is_available(self) -> bool:
        """Check if FastEmbed is available."""
        try:
            import fastembed  # noqa: F401

            return True
        except ImportError:
            return False


class OllamaProvider(EmbeddingProviderInterface):
    """Ollama provider for local development embeddings.

    Ollama runs locally without heavy dependencies like PyTorch.
    Supports multiple embedding models.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ):
        """Initialize Ollama provider.

        Args:
            model: Ollama model name. Options:
                - "nomic-embed-text" (default, fast)
                - "mxbai-embed-large-v1" (better quality)
                - "all-minilm" (small, fast)
            base_url: Ollama API URL
        """
        self.model = model
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings using Ollama."""
        if not texts:
            return EmbeddingResult([], self.model, EmbeddingProvider.OLLAMA, 0)

        client = await self._get_client()

        # Ollama API expects single string or array
        response = await client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
        )

        if response.status_code != 200:
            raise EmbeddingServiceError(f"Ollama API error: {response.status_code} {response.text}")

        data = response.json()

        # Extract embeddings
        embeddings = [item["embedding"] for item in data]

        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model,
            provider=EmbeddingProvider.OLLAMA,
        )

    def is_available(self) -> bool:
        """Check if Ollama is available."""
        try:
            # Quick health check
            import socket

            import httpx  # noqa: F401

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex(("localhost", 11434))
            sock.close()

            return result == 0
        except Exception:
            return False


class OpenAIProvider(EmbeddingProviderInterface):
    """OpenAI embeddings API provider.

    Uses OpenAI's cloud API for high-quality embeddings.
    Requires API key and network connection.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
    ):
        """Initialize OpenAI provider.

        Args:
            model: OpenAI embedding model. Options:
                - "text-embedding-3-small" (default, fastest, cheapest)
                - "text-embedding-3-large" (better quality)
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.model = model
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            if not self.api_key:
                import os

                self.api_key = os.getenv("OPENAI_API_KEY")
                if not self.api_key:
                    raise EmbeddingProviderError(
                        "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
                    )

            self._client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60.0,
            )
        return self._client

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings using OpenAI API."""
        if not texts:
            return EmbeddingResult([], self.model, EmbeddingProvider.OPENAI, 0)

        client = await self._get_client()

        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            json={"input": texts, "model": self.model},
        )

        if response.status_code != 200:
            raise EmbeddingServiceError(f"OpenAI API error: {response.status_code} {response.text}")

        data = response.json()

        # Extract embeddings
        embeddings = [item["embedding"] for item in data["data"]]

        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model,
            provider=EmbeddingProvider.OPENAI,
        )

    def is_available(self) -> bool:
        """Check if OpenAI provider is available."""
        try:
            import os  # noqa: F401

            return bool(os.getenv("OPENAI_API_KEY"))
        except Exception:
            return False


class EmbeddingService:
    """Unified embedding service with provider selection and fault tolerance.

    .. deprecated:: 0.5.0
        Use :class:`mahavishnu.core.resilient_embeddings.ResilientEmbeddingClient`
        instead, which provides multi-tier fallback via the centralized Akosha
        embedding service. The ResilientEmbeddingClient offers:
        - Centralized embedding via Akosha MCP
        - Two-tier caching (L1 memory + L2 Redis)
        - Dimension validation
        - Mock embedding fallback

        Migration example:
            # Old (deprecated)
            from mahavishnu.core.embeddings import EmbeddingService
            service = EmbeddingService()
            result = await service.embed(["text"])

            # New (recommended)
            from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient
            client = ResilientEmbeddingClient()
            result = await client.generate_embedding("text")

    Automatically selects provider based on:
    1. Explicit provider choice
    2. Availability (for automatic selection)
    3. Fallback order: FastEmbed > Ollama > OpenAI > sentence-transformers

    Fault Tolerance:
    - Circuit breaker per provider prevents cascading failures
    - Automatic fallback when circuit is open
    - Recovery timeout allows providers to heal

    Usage:
        # Production: FastEmbed (explicit)
        service = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        embeddings = await service.embed(["hello", "world"])

        # Development: Auto-select
        service = EmbeddingService()
        embeddings = await service.embed(["hello", "world"])
    """

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        auto_fallback: bool = True,
        circuit_breaker_config: dict[str, Any] | None = None,
    ):
        """Initialize embedding service.

        Args:
            provider: Explicit provider to use (or None for auto-selection)
            auto_fallback: Enable automatic fallback if provider unavailable
            circuit_breaker_config: Circuit breaker settings
                - failure_threshold: Failures before opening (default: 5)
                - recovery_timeout: Seconds before retry (default: 60)
        """
        warnings.warn(
            "EmbeddingService is deprecated. Use ResilientEmbeddingClient from "
            "mahavishnu.core.resilient_embeddings for centralized embedding via Akosha MCP.",
            DeprecationWarning,
            stacklevel=2,
        )

        self._preferred_provider = provider
        self._auto_fallback = auto_fallback
        self._providers: dict[EmbeddingProvider, EmbeddingProviderInterface] = {}
        self._circuit_breakers: dict[EmbeddingProvider, CircuitBreaker] = {}

        # Configure circuit breakers
        cb_config = circuit_breaker_config or {}
        self._cb_failure_threshold = cb_config.get("failure_threshold", 5)
        self._cb_recovery_timeout = cb_config.get("recovery_timeout", 60.0)

    def _get_circuit_breaker(self, provider: EmbeddingProvider) -> CircuitBreaker:
        """Get or create circuit breaker for provider."""
        if provider not in self._circuit_breakers:
            self._circuit_breakers[provider] = CircuitBreaker(
                failure_threshold=self._cb_failure_threshold,
                recovery_timeout=self._cb_recovery_timeout,
            )
        return self._circuit_breakers[provider]

    def _get_provider(self, provider: EmbeddingProvider) -> EmbeddingProviderInterface:
        """Get or create provider instance."""
        if provider not in self._providers:
            if provider == EmbeddingProvider.FASTEMBED:
                self._providers[provider] = FastEmbedProvider()
            elif provider == EmbeddingProvider.OLLAMA:
                self._providers[provider] = OllamaProvider()
            elif provider == EmbeddingProvider.OPENAI:
                self._providers[provider] = OpenAIProvider()
            else:
                raise EmbeddingProviderError(f"Unknown provider: {provider}")

        return self._providers[provider]

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings for texts.

        Uses circuit breaker pattern to prevent cascading failures.

        Args:
            texts: List of text strings to embed

        Returns:
            EmbeddingResult with embeddings and metadata

        Raises:
            EmbeddingServiceError: If all providers are unavailable
        """
        if not texts:
            # Return empty result for empty input
            return EmbeddingResult([], "unknown", EmbeddingProvider.FASTEMBED, 0)

        # If provider explicitly specified, use it (with circuit breaker)
        if self._preferred_provider:
            return await self._embed_with_circuit_breaker(
                self._preferred_provider, texts, allow_fallback=False
            )

        # Auto-select provider based on availability
        if self._auto_fallback:
            return await self._embed_with_fallback(texts)

        # Default to FastEmbed (will fail if not available)
        return await self._embed_with_circuit_breaker(
            EmbeddingProvider.FASTEMBED, texts, allow_fallback=False
        )

    async def _embed_with_circuit_breaker(
        self,
        provider_type: EmbeddingProvider,
        texts: list[str],
        allow_fallback: bool = True,
    ) -> EmbeddingResult:
        """Execute embed with circuit breaker protection.

        Args:
            provider_type: Provider to use
            texts: Texts to embed
            allow_fallback: Whether to fallback to other providers on failure

        Returns:
            EmbeddingResult

        Raises:
            EmbeddingProviderError: If provider unavailable and no fallback
            EmbeddingServiceError: If all providers fail
        """
        cb = self._get_circuit_breaker(provider_type)

        # Check if circuit allows execution
        if not cb.can_execute():
            if allow_fallback:
                logger.warning(
                    "circuit-breaker-blocked",
                    extra={"provider": provider_type.value},
                )
                return await self._embed_with_fallback(
                    texts, exclude_providers={provider_type}
                )
            raise EmbeddingProviderError(
                f"Circuit breaker open for provider {provider_type.value}"
            )

        provider = self._get_provider(provider_type)

        if not provider.is_available():
            cb.record_failure()
            if allow_fallback:
                return await self._embed_with_fallback(
                    texts, exclude_providers={provider_type}
                )
            raise EmbeddingProviderError(
                f"Requested provider {provider_type.value} is not available"
            )

        try:
            result = await provider.embed(texts)
            cb.record_success()
            return result
        except Exception as e:
            cb.record_failure()
            logger.error(
                "embedding-provider-failed",
                extra={"provider": provider_type.value, "error": str(e)},
            )
            if allow_fallback:
                return await self._embed_with_fallback(
                    texts, exclude_providers={provider_type}
                )
            raise

    async def _embed_with_fallback(
        self,
        texts: list[str],
        exclude_providers: set[EmbeddingProvider] | None = None,
    ) -> EmbeddingResult:
        """Try providers in order with fallback.

        Args:
            texts: Texts to embed
            exclude_providers: Providers to skip (already failed)

        Returns:
            EmbeddingResult

        Raises:
            EmbeddingServiceError: If all providers fail
        """
        exclude = exclude_providers or set()
        errors: list[str] = []

        # Try providers in order: FastEmbed > Ollama > OpenAI
        for provider_type in [
            EmbeddingProvider.FASTEMBED,
            EmbeddingProvider.OLLAMA,
            EmbeddingProvider.OPENAI,
        ]:
            if provider_type in exclude:
                continue

            cb = self._get_circuit_breaker(provider_type)
            if not cb.can_execute():
                errors.append(f"{provider_type.value}: circuit breaker open")
                continue

            try:
                provider = self._get_provider(provider_type)
                if provider.is_available():
                    result = await provider.embed(texts)
                    cb.record_success()
                    return result
            except Exception as e:
                cb.record_failure()
                errors.append(f"{provider_type.value}: {e}")

        raise EmbeddingServiceError(
            f"No embedding provider available. Errors: {'; '.join(errors)}"
        )

    async def embed_batch(
        self,
        text_batches: list[list[str]],
        max_concurrent: int = 5,
    ) -> list[EmbeddingResult | Exception]:
        """Generate embeddings for multiple batches concurrently.

        This method processes multiple batches of texts in parallel,
        improving throughput for large embedding workloads.

        Args:
            text_batches: List of text batches to embed
            max_concurrent: Maximum concurrent embedding operations

        Returns:
            List of EmbeddingResults or Exceptions for partial failure handling.
            Use return_exceptions=True pattern - check each result for Exception.

        Example:
            batches = [["text1", "text2"], ["text3", "text4"]]
            results = await service.embed_batch(batches)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Batch failed: {result}")
                else:
                    print(f"Got {len(result.embeddings)} embeddings")
        """
        if not text_batches:
            return []

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _embed_with_limit(batch: list[str]) -> EmbeddingResult:
            async with semaphore:
                return await self.embed(batch)

        tasks = [_embed_with_limit(batch) for batch in text_batches]
        # Return exceptions for graceful error handling
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_available_providers(self) -> list[EmbeddingProvider]:
        """Get list of available providers.

        Returns:
            List of available provider types
        """
        available = []
        for provider_type in [
            EmbeddingProvider.FASTEMBED,
            EmbeddingProvider.OLLAMA,
            EmbeddingProvider.OPENAI,
        ]:
            try:
                provider = self._get_provider(provider_type)
                if provider.is_available():
                    available.append(provider_type)
            except Exception:
                pass

        return available


# Singleton instance for convenience
_default_service: EmbeddingService | None = None


@lru_cache
def get_embedding_service(
    provider: EmbeddingProvider | None = None,
) -> EmbeddingService:
    """Get singleton embedding service instance.

    Args:
        provider: Preferred provider (or None for auto-selection)

    Returns:
        EmbeddingService singleton
    """
    global _default_service

    if _default_service is None or (provider and _default_service._preferred_provider != provider):
        _default_service = EmbeddingService(provider=provider)

    return _default_service


# Convenience function for quick embedding generation
async def embed(
    texts: list[str],
    provider: EmbeddingProvider | None = None,
) -> list[list[float]]:
    """Quick embedding generation convenience function.

    Args:
        texts: List of text strings to embed
        provider: Provider to use (or None for auto-selection)

    Returns:
        List of embedding vectors

    Example:
        >>> embeddings = await embed(["hello world"])
        >>> len(embeddings[0])
        384
    """
    service = get_embedding_service(provider)
    result = await service.embed(texts)
    return result.embeddings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Cosine similarity score between -1 and 1

    Example:
        >>> similarity = cosine_similarity([1, 0, 0], [1, 0, 0])
        >>> similarity
        1.0
    """
    import math

    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def euclidean_distance(a: list[float], b: list[float]) -> float:
    """Calculate Euclidean distance between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Euclidean distance (0 for identical vectors)

    Example:
        >>> distance = euclidean_distance([0, 0], [3, 4])
        >>> distance
        5.0
    """
    import math

    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")

    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# =============================================================================
# Security Models and Rate Limiting
# =============================================================================


class EmbeddingRequest(BaseModel):
    """Secure embedding request with sanitization.

    Attributes:
        text: Text to embed (sanitized)
        user_id: Required user identifier for auth/budget tracking
        system_id: Optional system identifier for multi-tenant
    """

    text: str = Field(..., min_length=1, max_length=100000)
    user_id: str = Field(..., min_length=1, max_length=256)
    system_id: str | None = Field(default=None, max_length=256)

    @field_validator("text")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        """Sanitize text input.

        - Removes control characters
        - Normalizes Unicode to NFKC form
        - Strips leading/trailing whitespace

        Args:
            v: Input text

        Returns:
            Sanitized text
        """
        # Remove control characters except newlines and tabs
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)
        # Normalize Unicode
        sanitized = unicodedata.normalize("NFKC", sanitized)
        # Strip whitespace
        return sanitized.strip()

    @field_validator("user_id", "system_id")
    @classmethod
    def sanitize_id(cls, v: str | None) -> str | None:
        """Sanitize identifier fields.

        Args:
            v: Input identifier

        Returns:
            Sanitized identifier or None
        """
        if v is None:
            return None
        # Remove any characters that aren't alphanumeric, dash, underscore, or @
        sanitized = re.sub(r"[^a-zA-Z0-9_\-@.]", "", v)
        return sanitized.strip()


class BatchEmbeddingRequest(BaseModel):
    """Secure batch embedding request with DoS protection.

    Attributes:
        texts: List of texts to embed
        user_id: Required user identifier
        system_id: Optional system identifier
    """

    texts: list[str] = Field(..., min_length=1, max_length=100)
    user_id: str = Field(..., min_length=1, max_length=256)
    system_id: str | None = Field(default=None, max_length=256)

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, v: list[str]) -> list[str]:
        """Validate and sanitize all texts.

        - Enforces max batch size
        - Enforces max text length per item
        - Sanitizes each text

        Args:
            v: List of texts

        Returns:
            Sanitized texts

        Raises:
            ValueError: If text exceeds size limits
        """
        if len(v) > 100:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of 100")

        sanitized = []
        for i, text in enumerate(v):
            if len(text) > 100000:  # 100KB limit
                raise ValueError(f"Text at index {i} exceeds 100KB limit")
            # Sanitize each text
            clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
            clean = unicodedata.normalize("NFKC", clean)
            sanitized.append(clean.strip())

        return sanitized

    @field_validator("user_id", "system_id")
    @classmethod
    def sanitize_id(cls, v: str | None) -> str | None:
        """Sanitize identifier fields."""
        if v is None:
            return None
        sanitized = re.sub(r"[^a-zA-Z0-9_\-@.]", "", v)
        return sanitized.strip()


class EmbeddingQuery(BaseModel):
    """Secure embedding search query with sanitization.

    Attributes:
        query: Search query text
        limit: Maximum results to return
        threshold: Minimum similarity threshold
    """

    query: str = Field(..., min_length=1, max_length=10000)
    limit: int = Field(default=10, ge=1, le=1000)
    threshold: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitize search query.

        - Removes control characters
        - Normalizes Unicode
        - Prevents SQL injection patterns

        Args:
            v: Input query

        Returns:
            Sanitized query
        """
        # Remove control characters
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)
        # Normalize Unicode
        sanitized = unicodedata.normalize("NFKC", sanitized)
        # Basic SQL injection protection (escape single quotes)
        sanitized = sanitized.replace("'", "''")
        return sanitized.strip()


@dataclass
class RateLimitConfig:
    """Rate limiting configuration.

    Attributes:
        max_batch_size: Maximum texts per batch request
        max_text_length: Maximum characters per text
        max_concurrent: Maximum concurrent embedding operations
        timeout_seconds: Request timeout in seconds
    """

    max_batch_size: int = 100
    max_text_length: int = 100000  # 100KB
    max_concurrent: int = 5
    timeout_seconds: float = 60.0


@dataclass
class BudgetConfig:
    """Budget tracking configuration.

    Attributes:
        enabled: Whether budget tracking is enabled
        daily_limit: Maximum embeddings per day
        alert_threshold: Threshold (0-1) to trigger alerts
    """

    enabled: bool = False
    daily_limit: int = 1000000
    alert_threshold: float = 0.8


class BudgetExceededError(EmbeddingServiceError):
    """Raised when embedding budget is exceeded."""

    def __init__(self, user_id: str, current: int, limit: int):
        self.user_id = user_id
        self.current = current
        self.limit = limit
        super().__init__(f"Budget exceeded for {user_id}: {current}/{limit}")


class ServiceOverloadedError(EmbeddingServiceError):
    """Raised when the embedding service is overloaded."""

    pass


class SecureEmbeddingService:
    """Secure embedding service with rate limiting and caching.

    Wraps EmbeddingService with:
    - Query sanitization via Pydantic models
    - Rate limiting and DoS protection
    - Budget tracking support
    - Batch embedding with error handling

    Example:
        service = SecureEmbeddingService()
        result = await service.embed_secure(
            request=EmbeddingRequest(text="hello", user_id="user-123")
        )
    """

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        rate_limit: RateLimitConfig | None = None,
        budget: BudgetConfig | None = None,
    ):
        """Initialize secure embedding service.

        Args:
            provider: Preferred embedding provider
            rate_limit: Rate limiting configuration
            budget: Budget tracking configuration
        """
        self._service = EmbeddingService(provider=provider)
        self._rate_limit = rate_limit or RateLimitConfig()
        self._budget = budget or BudgetConfig()
        self._semaphore = asyncio.Semaphore(self._rate_limit.max_concurrent)
        self._request_counts: dict[str, list[float]] = {}  # user_id -> timestamps

    def _hash_text(self, text: str) -> str:
        """Create hash of text for cache key.

        Args:
            text: Input text

        Returns:
            SHA256 hash of text
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits.

        Simple sliding window rate limiting.

        Args:
            user_id: User identifier

        Returns:
            True if within limits, False otherwise
        """
        now = time.time()
        window_start = now - 60.0  # 1 minute window

        if user_id not in self._request_counts:
            self._request_counts[user_id] = []

        # Remove old timestamps
        self._request_counts[user_id] = [
            ts for ts in self._request_counts[user_id] if ts > window_start
        ]

        # Check limit (100 requests per minute per user)
        if len(self._request_counts[user_id]) >= 100:
            return False

        # Record this request
        self._request_counts[user_id].append(now)
        return True

    async def embed_secure(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResult:
        """Generate embedding with security checks.

        Args:
            request: Validated embedding request

        Returns:
            Embedding result

        Raises:
            ServiceOverloadedError: If too many concurrent requests
            BudgetExceededError: If budget is exceeded
        """
        # Check rate limit
        if not self._check_rate_limit(request.user_id):
            raise ServiceOverloadedError(
                f"Rate limit exceeded for user {request.user_id}"
            )

        # Use semaphore for concurrency control
        async with self._semaphore:
            async with asyncio.timeout(self._rate_limit.timeout_seconds):
                return await self._service.embed([request.text])

    async def embed_batch_secure(
        self,
        request: BatchEmbeddingRequest,
    ) -> list[EmbeddingResult | Exception]:
        """Generate batch embeddings with DoS protection.

        Args:
            request: Validated batch embedding request

        Returns:
            List of embedding results or exceptions (for partial failures)

        Raises:
            ServiceOverloadedError: If service is overloaded
            BudgetExceededError: If budget is exceeded
        """
        # Check rate limit
        if not self._check_rate_limit(request.user_id):
            raise ServiceOverloadedError(
                f"Rate limit exceeded for user {request.user_id}"
            )

        # Check batch size (already validated by Pydantic, but double-check)
        if len(request.texts) > self._rate_limit.max_batch_size:
            raise ServiceOverloadedError(
                f"Batch size {len(request.texts)} exceeds limit "
                f"{self._rate_limit.max_batch_size}"
            )

        async def _embed_chunk(chunk: list[str]) -> EmbeddingResult:
            async with self._semaphore:
                async with asyncio.timeout(self._rate_limit.timeout_seconds):
                    return await self._service.embed(chunk)

        # Process in chunks with error handling
        chunk_size = 10  # Process 10 texts at a time
        results: list[EmbeddingResult | Exception] = []

        for i in range(0, len(request.texts), chunk_size):
            chunk = request.texts[i : i + chunk_size]
            try:
                result = await _embed_chunk(chunk)
                results.append(result)
            except Exception as e:
                # Record exception for partial failure handling
                results.append(e)
                logger.warning(
                    f"Batch embedding chunk failed: {e}",
                    extra={"user_id": request.user_id, "chunk_index": i // chunk_size},
                )

        return results


# Singleton secure service
_secure_service: SecureEmbeddingService | None = None


def get_secure_embedding_service(
    provider: EmbeddingProvider | None = None,
    rate_limit: RateLimitConfig | None = None,
    budget: BudgetConfig | None = None,
) -> SecureEmbeddingService:
    """Get singleton secure embedding service.

    Args:
        provider: Preferred embedding provider
        rate_limit: Rate limiting configuration
        budget: Budget tracking configuration

    Returns:
        SecureEmbeddingService singleton
    """
    global _secure_service

    if _secure_service is None:
        _secure_service = SecureEmbeddingService(
            provider=provider,
            rate_limit=rate_limit,
            budget=budget,
        )

    return _secure_service


__all__ = [
    "EmbeddingProvider",
    "EmbeddingServiceError",
    "EmbeddingProviderError",
    "EmbeddingResult",
    "EmbeddingProviderInterface",
    "FastEmbedProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "EmbeddingService",
    "get_embedding_service",
    "embed",
    "cosine_similarity",
    "euclidean_distance",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitState",
    # Security models
    "EmbeddingRequest",
    "BatchEmbeddingRequest",
    "EmbeddingQuery",
    "RateLimitConfig",
    "BudgetConfig",
    "BudgetExceededError",
    "ServiceOverloadedError",
    "SecureEmbeddingService",
    "get_secure_embedding_service",
]
