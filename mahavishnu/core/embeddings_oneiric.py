"""Oneiric-integrated embeddings configuration and adapter.

This module provides Oneiric-compatible embeddings configuration,
following the Oneiric layered loading pattern:
1. Default values in Pydantic models
2. settings/mahavishnu.yaml (committed)
3. settings/local.yaml (gitignored, local dev)
4. Environment variables MAHAVISHNU_{FIELD}

Usage:
    from mahavishnu.core.embeddings_oneiric import (
        EmbeddingConfig,
        get_embeddings_with_oneiric,
    )

    # Use with Oneiric auto-loading
    config = EmbeddingConfig()  # Loads from env/file/defaults
    embeddings = await get_embeddings_with_oneiric(["text1", "text2"], config)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core.embeddings import (
    EmbeddingProvider,
    EmbeddingService,
    EmbeddingServiceError,
    get_embedding_service,
)

if TYPE_CHECKING:
    pass


class EmbeddingConfig(BaseModel):
    """Embedding configuration following Oneiric patterns.

    Loaded in order:
    1. Default values (in this model)
    2. settings/mahavishnu.yaml (git-tracked)
    3. settings/local.yaml (git-ignored)
    4. Environment variables: MAHAVISHNU_EMBEDDINGS_*
    """

    # Provider selection
    provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.FASTEMBED,
        description="Embedding provider to use",
    )

    # Model configuration
    model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Model name (provider-specific)",
    )

    # Ollama configuration (if provider is OLLAMA)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )

    # OpenAI configuration (if provider is OPENAI)
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (overrides OPENAI_API_KEY env var)",
    )
    openai_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model",
    )

    # Performance settings
    batch_size: int = Field(
        default=32,
        ge=1,
        le=256,
        description="Batch size for embedding generation",
    )

    enable_cache: bool = Field(
        default=True,
        description="Enable embedding cache (reduces API calls)",
    )

    model_config = ConfigDict(use_enum_values=True)

    @classmethod
    def load_from_file(cls, config_path: str | None = None) -> "EmbeddingConfig":
        """Load configuration from YAML file (Oneiric pattern).

        Args:
            config_path: Path to YAML configuration file

        Returns:
            EmbeddingConfig instance
        """
        import yaml

        if config_path and os.path.exists(config_path):
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return cls(**data)

        # Return defaults if file doesn't exist
        return cls()

    @classmethod
    def load_from_env(cls) -> "EmbeddingConfig":
        """Load configuration from environment variables.

        Environment variables (MAHAVISHNU_EMBEDDINGS_ prefix):
        - PROVIDER: fastembed, ollama, openai
        - MODEL: model name
        - OLLAMA_BASE_URL: Ollama API URL
        - OPENAI_API_KEY: OpenAI API key
        - OPENAI_MODEL: OpenAI model name
        - BATCH_SIZE: batch size
        - ENABLE_CACHE: true/false

        Returns:
            EmbeddingConfig instance
        """
        config = cls()

        # Provider
        if provider_env := os.getenv("MAHAVISHNU_EMBEDDINGS_PROVIDER"):
            try:
                config.provider = EmbeddingProvider(provider_env)
            except ValueError:
                pass  # Use default

        # Model
        if model_env := os.getenv("MAHAVISHNU_EMBEDDINGS_MODEL"):
            config.model = model_env

        # Ollama
        if ollama_url := os.getenv("MAHAVISHNU_EMBEDDINGS_OLLAMA_BASE_URL"):
            config.ollama_base_url = ollama_url

        # OpenAI
        if api_key := os.getenv("MAHAVISHNU_EMBEDDINGS_OPENAI_API_KEY"):
            config.openai_api_key = api_key

        if openai_model := os.getenv("MAHAVISHNU_EMBEDDINGS_OPENAI_MODEL"):
            config.openai_model = openai_model

        # Batch size
        if batch_size := os.getenv("MAHAVISHNU_EMBEDDINGS_BATCH_SIZE"):
            try:
                config.batch_size = int(batch_size)
            except ValueError:
                pass  # Use default

        # Cache
        if enable_cache := os.getenv("MAHAVISHNU_EMBEDDINGS_ENABLE_CACHE"):
            config.enable_cache = enable_cache.lower() in ("true", "1", "yes")

        return config

    @classmethod
    def load(cls) -> "EmbeddingConfig":
        """Load configuration using Oneiric layered pattern.

        Order:
        1. Default values (in this model)
        2. settings/mahavishnu.yaml
        3. settings/local.yaml
        4. Environment variables

        Returns:
            EmbeddingConfig instance
        """
        config = cls()

        # Try loading from YAML files
        for yaml_file in [
            "settings/mahavishnu.yaml",
            "settings/local.yaml",
        ]:
            try:
                config = config.load_from_file(yaml_file)
            except Exception:
                pass  # File doesn't exist or has errors

        # Override with environment variables
        config = config.load_from_env()

        return config


# Global configuration singleton (lazy-loaded)
_embedding_config: EmbeddingConfig | None = None


def get_embedding_config() -> EmbeddingConfig:
    """Get global embedding configuration (Oneiric pattern).

    Returns:
        EmbeddingConfig loaded from file/env/defaults
    """
    global _embedding_config

    if _embedding_config is None:
        _embedding_config = EmbeddingConfig.load()

    return _embedding_config


async def get_embeddings_with_oneiric(
    texts: list[str],
    config: EmbeddingConfig | None = None,
) -> list[list[float]]:
    """Generate embeddings using Oneiric configuration.

    This is the main entry point for embeddings in the Mahavishun ecosystem,
    following Oneiric patterns for configuration loading.

    Args:
        texts: List of text strings to embed
        config: Explicit config (or None to auto-load using Oneiric pattern)

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingServiceError: If embedding generation fails

    Example:
        >>> from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric
        >>> embeddings = await get_embeddings_with_oneiric(["hello", "world"])
        >>> len(embeddings)
        2
        >>> len(embeddings[0])
        384
    """
    if config is None:
        config = get_embedding_config()

    # Create service with configured provider
    service = EmbeddingService(provider=config.provider)

    # Generate embeddings
    result = await service.embed(texts)

    return result.embeddings


class OneiricEmbeddingsAdapter:
    """Oneiric-compatible embeddings adapter for MCP integration.

    This adapter provides a Oneiric-integrated interface for embeddings
    that can be exposed as an MCP tool or used in other components.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        """Initialize Oneiric embeddings adapter.

        Args:
            config: Embedding configuration (or None to auto-load)
        """
        self.config = config or get_embedding_config()
        self._service: EmbeddingService | None = None

    async def _get_service(self) -> EmbeddingService:
        """Lazy-load the embedding service."""
        if self._service is None:
            self._service = EmbeddingService(provider=self.config.provider)
        return self._service

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors
        """
        service = await self._get_service()
        result = await service.embed(texts)
        return result.embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text string to embed

        Returns:
            Embedding vector
        """
        embeddings = await self.embed([text])
        return embeddings[0]

    def get_provider_info(self) -> dict[str, str]:
        """Get information about current embedding provider.

        Returns:
            Dictionary with provider info
        """
        return {
            "provider": self.config.provider.value,
            "model": self.config.model,
            "batch_size": str(self.config.batch_size),
            "cache_enabled": str(self.config.enable_cache),
        }

    def is_available(self) -> bool:
        """Check if embeddings are available.

        Returns:
            True if at least one embedding provider is available
        """
        service = EmbeddingService(provider=self.config.provider)
        return service.get_available_providers() != []


# MCP tool integration (optional)
async def mcp_tool_get_embeddings(
    texts: list[str],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, list[list[float]]]:
    """MCP tool for generating embeddings.

    Args:
        texts: List of text strings
        provider: Provider override (fastembed, ollama, openai)
        model: Model name override

    Returns:
        Dictionary with embeddings and metadata

    Example (MCP call):
        {
            "method": "tools/call",
            "params": {
                "name": "get_embeddings",
                "arguments": {
                    "texts": ["hello world"],
                    "provider": "fastembed"
                }
            }
        }
    """
    config = get_embedding_config()

    # Override provider if specified
    if provider:
        try:
            config.provider = EmbeddingProvider(provider)
        except ValueError:
            raise ValueError(f"Invalid provider: {provider}")

    # Override model if specified
    if model:
        config.model = model

    # Generate embeddings
    embeddings = await get_embeddings_with_oneiric(texts, config)

    return {
        "embeddings": embeddings,
        "model": config.model,
        "provider": config.provider.value,
        "dimension": len(embeddings[0]) if embeddings else 0,
    }
