"""Embedding service with multiple provider support.

This module provides a unified interface for text embeddings with support for:
- FastEmbed (production, cross-platform)
- Ollama (development, local privacy)
- OpenAI API (cloud, high quality)
- Future: sentence-transformers (when compatible)

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

from abc import ABC, abstractmethod
import asyncio
from enum import Enum
from functools import lru_cache

import httpx


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
    """Result from embedding generation."""

    def __init__(
        self,
        embeddings: list[list[float]],
        model: str,
        provider: EmbeddingProvider,
        dimension: int | None = None,
    ):
        self.embeddings = embeddings
        self.model = model
        self.provider = provider
        self.dimension = dimension or (len(embeddings[0]) if embeddings else 0)

    def __repr__(self) -> str:
        return f"EmbeddingResult(model={self.model}, provider={self.provider.value}, dimension={self.dimension}, count={len(self.embeddings)})"


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
    """Unified embedding service with provider selection.

    Automatically selects provider based on:
    1. Explicit provider choice
    2. Availability (for automatic selection)
    3. Fallback order: FastEmbed > Ollama > OpenAI > sentence-transformers

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
    ):
        """Initialize embedding service.

        Args:
            provider: Explicit provider to use (or None for auto-selection)
            auto_fallback: Enable automatic fallback if provider unavailable
        """
        self._preferred_provider = provider
        self._auto_fallback = auto_fallback
        self._providers: dict[EmbeddingProvider, EmbeddingProviderInterface] = {}

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

        # If provider explicitly specified, use it
        if self._preferred_provider:
            provider = self._get_provider(self._preferred_provider)

            if not provider.is_available():
                raise EmbeddingProviderError(
                    f"Requested provider {self._preferred_provider.value} is not available"
                )

            return await provider.embed(texts)

        # Auto-select provider based on availability
        if self._auto_fallback:
            # Try providers in order: FastEmbed > Ollama > OpenAI
            for provider_type in [
                EmbeddingProvider.FASTEMBED,
                EmbeddingProvider.OLLAMA,
                EmbeddingProvider.OPENAI,
            ]:
                try:
                    provider = self._get_provider(provider_type)
                    if provider.is_available():
                        return await provider.embed(texts)
                except EmbeddingServiceError:
                    continue

            raise EmbeddingServiceError("No embedding provider available")

        # Default to FastEmbed (will fail if not available)
        provider = self._get_provider(EmbeddingProvider.FASTEMBED)
        return await provider.embed(texts)

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
