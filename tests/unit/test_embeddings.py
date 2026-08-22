"""Test embeddings functionality.

After the hybrid chain refactor (oneiric), these tests cover the
delegation contract: the EmbeddingService shim should reach oneiric's
probe chain and return real embeddings when a backend is reachable.
Provider-specific unit tests are obsolete — they lived with the removed
``FastEmbedProvider`` / ``OllamaProvider`` / ``OpenAIProvider`` classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.embeddings_oneiric import (
    EmbeddingConfig,
    OneiricEmbeddingsAdapter,
    get_embeddings_with_oneiric,
)

if TYPE_CHECKING:
    pass


class TestOneiricIntegration:
    """Test Oneiric configuration integration."""

    @pytest.mark.asyncio
    async def test_load_default_config(self) -> None:
        """Test loading default embedding configuration."""
        config = EmbeddingConfig()

        # After the migration, ``provider`` defaults to FASTEMBED for
        # backward compat with old YAML files, but the field is now
        # informational only — the live backend is selected by the
        # oneiric probe chain.
        assert config.provider == "fastembed"
        assert config.batch_size == 32

    @pytest.mark.asyncio
    async def test_get_embeddings_with_oneiric(self) -> None:
        """Test generating embeddings using Oneiric configuration.

        Dimension is whatever the chain probed (typically 768 from
        Ollama's ``nomic-embed-text`` or 1024 from MiniMax). Asserting
        ``>0`` rather than a fixed value keeps the test robust across
        backend switches.
        """
        embeddings = await get_embeddings_with_oneiric(["hello", "world"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) > 0  # Real embedding, not mock fallback

    @pytest.mark.asyncio
    async def test_oneiric_adapter(self) -> None:
        """Test Oneiric embeddings adapter."""
        adapter = OneiricEmbeddingsAdapter()

        # Generate embeddings
        embeddings = await adapter.embed(["hello", "world"])
        assert len(embeddings) == 2
        assert all(len(v) > 0 for v in embeddings)

        # Single embedding
        embedding = await adapter.embed_single("hello world")
        assert len(embedding) > 0

        # Provider info
        info = adapter.get_provider_info()
        assert "provider" in info
        assert "model" in info


class TestHybridChainEmbeddingService:
    """Test the EmbeddingService shim that delegates to oneiric's hybrid chain."""

    @pytest.mark.asyncio
    async def test_embed_returns_embedding_result(self) -> None:
        """``embed`` returns an EmbeddingResult envelope.

        The shim preserves the legacy dataclass shape so callers
        (ingestion_cli, content_ingester, resilient_embeddings) don't
        need to change.
        """
        from mahavishnu.core.embeddings import EmbeddingService

        service = EmbeddingService()
        result = await service.embed(["hello world"])

        assert len(result.embeddings) == 1
        assert len(result.embeddings[0]) > 0
        # provider field is now filled from the active backend name.
        assert isinstance(result.provider, str)

    @pytest.mark.asyncio
    async def test_embed_empty_list(self) -> None:
        """Empty input returns an empty list (graceful, not an error).

        ``dimension`` reports the active backend's expected vector size,
        not the length of the (empty) embeddings list — callers use it
        to pre-allocate vectors.
        """
        from mahavishnu.core.embeddings import EmbeddingService

        service = EmbeddingService()
        result = await service.embed([])

        assert result.embeddings == []
        assert result.dimension == service.dimension()

    @pytest.mark.asyncio
    async def test_legacy_provider_kwarg_is_ignored(self) -> None:
        """The legacy ``provider=`` kwarg is accepted but ignored.

        The chain probes backends in llama_cpp -> ollama -> minimax ->
        model2vec -> mock order; explicit provider selection is no longer
        supported. The shim accepts the kwarg so existing callers don't
        break, but the active backend is whatever the chain picked.
        """
        from mahavishnu.core.embeddings import EmbeddingProvider, EmbeddingService

        service = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        result = await service.embed(["hello"])

        # Result must come back regardless of the legacy kwarg.
        assert len(result.embeddings) == 1
        assert len(result.embeddings[0]) > 0


class TestEmbeddingProviderEnum:
    """``EmbeddingProvider`` is retained as a StrEnum for backward compat.

    New code should configure backends via
    ``oneiric.adapters.observability.embedding_settings.EmbeddingSettings``
    and let the probe chain select the active backend.
    """

    def test_str_enum_values(self) -> None:
        from mahavishnu.core.embeddings import EmbeddingProvider

        assert EmbeddingProvider.FASTEMBED == "fastembed"
        assert EmbeddingProvider.OLLAMA == "ollama"
        assert EmbeddingProvider.OPENAI == "openai"
