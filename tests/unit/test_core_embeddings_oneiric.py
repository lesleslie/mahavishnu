"""Unit tests for mahavishnu/core/embeddings_oneiric.py.

The underlying EmbeddingService is mocked so these tests don't require
fastembed / Ollama / OpenAI to be installed.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.embeddings import EmbeddingProvider
from mahavishnu.core.embeddings_oneiric import (
    EmbeddingConfig,
    OneiricEmbeddingsAdapter,
    get_embedding_config,
    get_embeddings_with_oneiric,
    mcp_tool_get_embeddings,
)

pytestmark = pytest.mark.unit


# ============================== Fixtures ==============================


@pytest.fixture
def reset_global_config():
    """Reset the lazily-cached global config before & after each test."""
    import mahavishnu.core.embeddings_oneiric as mod

    mod._embedding_config = None
    yield
    mod._embedding_config = None


@pytest.fixture
def clean_env(monkeypatch):
    """Wipe MAHAVISHNU_EMBEDDINGS_* env vars."""
    for key in list(os.environ):
        if key.startswith("MAHAVISHNU_EMBEDDINGS_"):
            monkeypatch.delenv(key, raising=False)
    yield monkeypatch


@pytest.fixture
def mock_embedding_service():
    """Mock the EmbeddingService class used by embeddings_oneiric."""
    service_instance = MagicMock()
    result = MagicMock()
    result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    service_instance.embed = AsyncMock(return_value=result)
    service_instance.get_available_providers = MagicMock(return_value=[EmbeddingProvider.FASTEMBED])

    with patch(
        "mahavishnu.core.embeddings_oneiric.EmbeddingService",
        return_value=service_instance,
    ) as mock_cls:
        yield mock_cls, service_instance


# ============================== EmbeddingConfig ==============================


class TestEmbeddingConfigDefaults:
    """Default values for EmbeddingConfig."""

    def test_defaults(self):
        cfg = EmbeddingConfig()
        # use_enum_values=True → enum becomes string after model_dump
        assert cfg.provider in (
            EmbeddingProvider.FASTEMBED.value,
            EmbeddingProvider.FASTEMBED,
        )
        assert cfg.model == "BAAI/bge-small-en-v1.5"
        assert cfg.ollama_base_url == "http://localhost:11434"
        assert cfg.openai_api_key is None
        assert cfg.openai_model == "text-embedding-3-small"
        assert cfg.batch_size == 32
        assert cfg.enable_cache is True

    def test_custom_values(self):
        cfg = EmbeddingConfig(
            provider=EmbeddingProvider.OPENAI,
            model="custom-model",
            batch_size=64,
            enable_cache=False,
        )
        assert cfg.batch_size == 64
        assert cfg.model == "custom-model"
        assert cfg.enable_cache is False

    def test_batch_size_range_validated(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            EmbeddingConfig(batch_size=0)
        with pytest.raises(Exception):
            EmbeddingConfig(batch_size=999)


# ============================== load_from_file ==============================


class TestLoadFromFile:
    """Coverage for EmbeddingConfig.load_from_file."""

    def test_returns_defaults_when_no_path(self):
        cfg = EmbeddingConfig.load_from_file(None)
        assert cfg.model == "BAAI/bge-small-en-v1.5"

    def test_returns_defaults_when_path_missing(self, tmp_path):
        nonexistent = tmp_path / "missing.yaml"
        cfg = EmbeddingConfig.load_from_file(str(nonexistent))
        assert cfg.batch_size == 32

    def test_loads_yaml_file(self, tmp_path):
        yaml_file = tmp_path / "embeddings.yaml"
        yaml_file.write_text("model: bge-large\nbatch_size: 64\nenable_cache: false\n")
        cfg = EmbeddingConfig.load_from_file(str(yaml_file))
        assert cfg.model == "bge-large"
        assert cfg.batch_size == 64
        assert cfg.enable_cache is False

    def test_loads_empty_yaml(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        cfg = EmbeddingConfig.load_from_file(str(yaml_file))
        # Defaults
        assert cfg.batch_size == 32


# ============================== load_from_env ==============================


class TestLoadFromEnv:
    """Coverage for EmbeddingConfig.load_from_env."""

    def test_no_env_returns_defaults(self, clean_env):
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.batch_size == 32

    def test_provider_env_valid(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_PROVIDER", "openai")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.provider in (
            EmbeddingProvider.OPENAI,
            EmbeddingProvider.OPENAI.value,
        )

    def test_provider_env_invalid_falls_back_to_default(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_PROVIDER", "garbage")
        cfg = EmbeddingConfig.load_from_env()
        # Default preserved
        assert cfg.provider in (
            EmbeddingProvider.FASTEMBED,
            EmbeddingProvider.FASTEMBED.value,
        )

    def test_model_env_override(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_MODEL", "custom-model")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.model == "custom-model"

    def test_openai_api_key_env(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_OPENAI_API_KEY", "sk-xyz")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.openai_api_key == "sk-xyz"

    def test_openai_model_env(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_OPENAI_MODEL", "text-embedding-3-large")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.openai_model == "text-embedding-3-large"

    def test_batch_size_env(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_BATCH_SIZE", "64")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.batch_size == 64

    def test_batch_size_env_invalid_keeps_default(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_BATCH_SIZE", "notanumber")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.batch_size == 32

    def test_enable_cache_env_truthy(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_ENABLE_CACHE", "true")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.enable_cache is True

    def test_enable_cache_env_falsy(self, clean_env):
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_ENABLE_CACHE", "false")
        cfg = EmbeddingConfig.load_from_env()
        assert cfg.enable_cache is False


# ============================== load (layered) ==============================


class TestLayeredLoad:
    """The composite `load` method should not crash even with missing files."""

    def test_load_returns_config_when_no_files(self, clean_env, tmp_path, monkeypatch):
        # Run from a temp dir so settings/*.yaml resolves to nothing
        monkeypatch.chdir(tmp_path)
        cfg = EmbeddingConfig.load()
        assert isinstance(cfg, EmbeddingConfig)

    def test_load_env_overrides_yaml(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clean_env.setenv("MAHAVISHNU_EMBEDDINGS_MODEL", "from-env")
        cfg = EmbeddingConfig.load()
        assert cfg.model == "from-env"


# ============================== get_embedding_config (singleton) ==============================


class TestGetEmbeddingConfig:
    """Lazy singleton caching."""

    def test_first_call_creates_config(self, reset_global_config, clean_env, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = get_embedding_config()
        assert isinstance(cfg, EmbeddingConfig)

    def test_second_call_returns_same_instance(
        self, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        a = get_embedding_config()
        b = get_embedding_config()
        assert a is b


# ============================== get_embeddings_with_oneiric ==============================


class TestGetEmbeddingsWithOneiric:
    """The high-level helper that delegates to EmbeddingService."""

    async def test_uses_provided_config(self, mock_embedding_service):
        mock_cls, service = mock_embedding_service
        cfg = EmbeddingConfig(provider=EmbeddingProvider.FASTEMBED)
        result = await get_embeddings_with_oneiric(["hello", "world"], cfg)
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        service.embed.assert_awaited_once_with(["hello", "world"])

    async def test_falls_back_to_default_config(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        await get_embeddings_with_oneiric(["x"])
        mock_cls, service = mock_embedding_service
        service.embed.assert_awaited_once()


# ============================== OneiricEmbeddingsAdapter ==============================


class TestOneiricEmbeddingsAdapter:
    """The Oneiric-compatible adapter wrapper."""

    async def test_embed(self, mock_embedding_service):
        cfg = EmbeddingConfig()
        adapter = OneiricEmbeddingsAdapter(cfg)
        result = await adapter.embed(["foo", "bar"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    async def test_embed_single(self, mock_embedding_service):
        cfg = EmbeddingConfig()
        adapter = OneiricEmbeddingsAdapter(cfg)
        out = await adapter.embed_single("only")
        # First vector of mocked result
        assert out == [0.1, 0.2, 0.3]

    async def test_get_service_caches_instance(self, mock_embedding_service):
        cfg = EmbeddingConfig()
        adapter = OneiricEmbeddingsAdapter(cfg)
        s1 = await adapter._get_service()
        s2 = await adapter._get_service()
        assert s1 is s2

    def test_get_provider_info_keys(self, mock_embedding_service):
        cfg = EmbeddingConfig()
        adapter = OneiricEmbeddingsAdapter(cfg)
        info = adapter.get_provider_info()
        assert "provider" in info
        assert "model" in info
        assert "batch_size" in info
        assert "cache_enabled" in info

    def test_is_available_true(self, mock_embedding_service):
        cfg = EmbeddingConfig()
        adapter = OneiricEmbeddingsAdapter(cfg)
        assert adapter.is_available() is True

    def test_is_available_false_when_no_providers(self):
        service_instance = MagicMock()
        service_instance.get_available_providers = MagicMock(return_value=[])
        with patch(
            "mahavishnu.core.embeddings_oneiric.EmbeddingService",
            return_value=service_instance,
        ):
            cfg = EmbeddingConfig()
            adapter = OneiricEmbeddingsAdapter(cfg)
            assert adapter.is_available() is False

    def test_default_config_loaded_when_none_provided(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        adapter = OneiricEmbeddingsAdapter()
        assert isinstance(adapter.config, EmbeddingConfig)


# ============================== mcp_tool_get_embeddings ==============================


class TestMCPToolGetEmbeddings:
    """The MCP-facing wrapper."""

    async def test_basic_call(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        result = await mcp_tool_get_embeddings(["hello"])
        assert result["embeddings"] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert "model" in result
        assert "provider" in result
        assert result["dimension"] == 3

    async def test_provider_override(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        result = await mcp_tool_get_embeddings(["hello"], provider="openai")
        # provider was changed on cached config object
        assert result["provider"] in ("openai", EmbeddingProvider.OPENAI.value)

    async def test_invalid_provider_raises(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="Invalid provider"):
            await mcp_tool_get_embeddings(["hello"], provider="bogus")

    async def test_model_override(
        self, mock_embedding_service, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        result = await mcp_tool_get_embeddings(["hello"], model="my-model")
        assert result["model"] == "my-model"

    async def test_empty_texts_returns_zero_dimension(
        self, reset_global_config, clean_env, tmp_path, monkeypatch
    ):
        # Override the global service to return zero embeddings
        service_instance = MagicMock()
        result = MagicMock()
        result.embeddings = []
        service_instance.embed = AsyncMock(return_value=result)

        monkeypatch.chdir(tmp_path)
        with patch(
            "mahavishnu.core.embeddings_oneiric.EmbeddingService",
            return_value=service_instance,
        ):
            out = await mcp_tool_get_embeddings([])
            assert out["dimension"] == 0
            assert out["embeddings"] == []
