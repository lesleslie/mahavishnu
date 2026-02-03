"""Test embeddings functionality."""

import pytest
import asyncio
from mahavishnu.core.embeddings import EmbeddingProvider
from mahavishnu.core.embeddings_oneiric import (
    EmbeddingConfig,
    OneiricEmbeddingsAdapter,
    get_embeddings_with_oneiric,
)


class TestFastEmbedProvider:
    """Test FastEmbed provider (production)."""

    @pytest.mark.asyncio
    async def test_fastembed_available(self):
        """Test that FastEmbed is available."""
        from mahavishnu.core.embeddings import FastEmbedProvider

        provider = FastEmbedProvider()
        assert provider.is_available(), "FastEmbed should be available"

    @pytest.mark.asyncio
    async def test_fastembed_generate_embeddings(self):
        """Test generating embeddings with FastEmbed."""
        from mahavishnu.core.embeddings import FastEmbedProvider

        provider = FastEmbedProvider()
        result = await provider.embed(["hello world", "test text"])

        assert len(result.embeddings) == 2
        assert result.dimension == 384  # bge-small-en-v1.5 dimension
        assert result.provider == EmbeddingProvider.FASTEMBED

    @pytest.mark.asyncio
    async def test_fastembed_empty_input(self):
        """Test FastEmbed with empty input."""
        from mahavishnu.core.embeddings import FastEmbedProvider

        provider = FastEmbedProvider()
        result = await provider.embed([])

        assert len(result.embeddings) == 0
        assert result.dimension == 0


class TestOllamaProvider:
    """Test Ollama provider (development)."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not __import__("socket").socket().connect_ex(("localhost", 11434)) == 0,
        reason="Ollama not running"
    )
    async def test_ollama_available(self):
        """Test that Ollama is available if service is running."""
        from mahavishnu.core.embeddings import OllamaProvider

        provider = OllamaProvider()
        assert provider.is_available(), "Ollama should be available"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not __import__("socket").socket().connect_ex(("localhost", 11434)) == 0,
        reason="Ollama not running"
    )
    async def test_ollama_generate_embeddings(self):
        """Test generating embeddings with Ollama."""
        from mahavishnu.core.embeddings import OllamaProvider

        provider = OllamaProvider()
        result = await provider.embed(["hello world"])

        assert len(result.embeddings) == 1
        assert result.dimension == 768  # nomic-embed-text dimension
        assert result.provider == EmbeddingProvider.OLLAMA


class TestOneiricIntegration:
    """Test Oneiric configuration integration."""

    @pytest.mark.asyncio
    async def test_load_default_config(self):
        """Test loading default embedding configuration."""
        config = EmbeddingConfig()

        assert config.provider == EmbeddingProvider.FASTEMBED
        assert config.model == "BAAI/bge-small-en-v1.5"
        assert config.batch_size == 32

    @pytest.mark.asyncio
    async def test_get_embeddings_with_oneiric(self):
        """Test generating embeddings using Oneiric configuration."""
        embeddings = await get_embeddings_with_oneiric(["hello", "world"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 384  # FastEmbed default dimension

    @pytest.mark.asyncio
    async def test_oneiric_adapter(self):
        """Test Oneiric embeddings adapter."""
        adapter = OneiricEmbeddingsAdapter()

        # Generate embeddings
        embeddings = await adapter.embed(["hello", "world"])

        assert len(embeddings) == 2

        # Single embedding
        embedding = await adapter.embed_single("hello world")
        assert len(embedding) == 384

        # Provider info
        info = adapter.get_provider_info()
        assert "provider" in info
        assert "model" in info


class TestProviderFallback:
    """Test automatic provider fallback."""

    @pytest.mark.asyncio
    async def test_auto_fallback_to_available_provider(self):
        """Test automatic fallback to available provider."""
        from mahavishnu.core.embeddings import EmbeddingService

        service = EmbeddingService(auto_fallback=True)

        # Should auto-select FastEmbed
        embeddings = await service.embed(["hello world"])

        assert len(embeddings) == 1
        assert len(embeddings[0]) > 0  # Has embeddings


@pytest.mark.asyncio
async def test_embedding_service_explicit_provider():
    """Test embedding service with explicit provider selection."""
    from mahavishnu.core.embeddings import EmbeddingService

    service = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
    result = await service.embed(["hello"])

    assert result.provider == EmbeddingProvider.FASTEMBED
    assert len(result.embeddings) == 1
    assert result.dimension == 384
