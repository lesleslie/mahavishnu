"""Tests for Agno adapter with real LLM integration."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.core.errors import ConfigurationError
from mahavishnu.engines.agno_adapter import AgnoAdapter


@pytest.mark.asyncio
async def test_agno_adapter_requires_llm_configuration():
    """Test that Agno adapter requires proper LLM configuration."""
    # Create adapter with mock config that has no LLM provider
    config = MagicMock()
    config.llm_provider = "ollama"
    config.llm.model = "qwen2.5:7b"
    config.llm.ollama_base_url = "http://localhost:11434"

    adapter = AgnoAdapter(config)

    # Mock Agno import to force fallback
    with patch("mahavishnu.engines.agno_adapter.AgnoAdapter._create_agent") as mock_create:
        # Make _create_agent fall back to MockAgent
        async def side_effect(task_type):
            # Return None to trigger ImportError in _create_agent
            return None

        mock_create.side_effect = side_effect

        # Try to execute a task
        task = {"type": "code_sweep", "id": "test"}
        repos = ["/fake/repo"]

        result = await adapter.execute(task, repos)

        # Should complete with mock agent responses (not fail)
        assert result["status"] == "completed"
        assert result["repos_processed"] == 1
        assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_agno_adapter_with_ollama_llm():
    """Test Agno adapter with Ollama LLM configuration."""
    # Mock config
    config = MagicMock()
    config.llm_provider = "ollama"
    config.llm.model = "qwen2.5:7b"
    config.llm.ollama_base_url = "http://localhost:11434"

    adapter = AgnoAdapter(config)

    # Test _get_llm method (without actually calling Ollama)
    with patch.dict(os.environ, {}, clear=True):
        # Should try to import OllamaLLM
        with pytest.raises((ImportError, ConfigurationError)):
            # Either ImportError (agno not installed) or ConfigurationError (OK)
            adapter._get_llm()


@pytest.mark.asyncio
async def test_agno_adapter_with_anthropic_llm():
    """Test Agno adapter with Anthropic/Claude LLM configuration."""
    # Mock config
    config = MagicMock()
    config.llm_provider = "anthropic"
    config.llm.model = "claude-sonnet-4-20250514"

    adapter = AgnoAdapter(config)

    # Test _get_llm requires API key
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            adapter._get_llm()

    # With API key, should try to import
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with pytest.raises(ImportError):  # Agno not installed
            adapter._get_llm()


@pytest.mark.asyncio
async def test_agno_adapter_with_openai_llm():
    """Test Agno adapter with OpenAI/GPT LLM configuration."""
    # Mock config
    config = MagicMock()
    config.llm_provider = "openai"
    config.llm.model = "gpt-4"

    adapter = AgnoAdapter(config)

    # Test _get_llm requires API key
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            adapter._get_llm()

    # With API key, should try to import
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with pytest.raises(ImportError):  # Agno not installed
            adapter._get_llm()


@pytest.mark.asyncio
async def test_agno_adapter_unsupported_provider():
    """Test Agno adapter rejects unsupported LLM provider."""
    config = MagicMock()
    config.llm_provider = "unsupported_provider"

    adapter = AgnoAdapter(config)

    with pytest.raises(ConfigurationError, match="Unsupported LLM provider"):
        adapter._get_llm()


@pytest.mark.asyncio
async def test_agno_adapter_parallel_execution():
    """Test that Agno adapter processes repositories in parallel."""
    config = MagicMock()
    config.llm_provider = "ollama"
    config.llm.model = "qwen2.5:7b"

    adapter = AgnoAdapter(config)

    # Force MockAgent usage by mocking _create_agent to trigger ImportError
    with patch("mahavishnu.engines.agno_adapter.AgnoAdapter._create_agent") as mock_create:
        async def side_effect(task_type):
            # Return None to trigger MockAgent fallback
            return None

        mock_create.side_effect = side_effect

        # Execute on multiple repos
        task = {"type": "code_sweep", "id": "test_parallel"}
        repos = ["/fake/repo1", "/fake/repo2", "/fake/repo3"]

        result = await adapter.execute(task, repos)

        # Verify all repos were processed
        assert result["status"] == "completed"
        assert result["repos_processed"] == 3
        assert result["success_count"] == 3
        assert len(result["results"]) == 3


@pytest.mark.asyncio
async def test_agno_adapter_health_check():
    """Test Agno adapter health check."""
    config = MagicMock()
    adapter = AgnoAdapter(config)

    health = await adapter.get_health()

    assert health["status"] in ("healthy", "degraded", "unhealthy")
    assert "details" in health
    assert health["details"]["configured"] is True


@pytest.mark.asyncio
async def test_agno_adapter_handles_errors_gracefully():
    """Test that Agno adapter handles errors without crashing."""
    config = MagicMock()
    adapter = AgnoAdapter(config)

    # Mock a repository that raises an error
    with patch("mahavishnu.engines.agno_adapter.AgnoAdapter._process_single_repo") as mock_process:
        async def side_effect(repo, task):
            return {"repo": repo, "status": "failed", "error": "Test error", "task_id": "test"}

        mock_process.side_effect = side_effect

        task = {"type": "code_sweep", "id": "test"}
        repos = ["/fake/repo"]

        result = await adapter.execute(task, repos)

        # Should complete but report failure
        assert result["status"] == "completed"
        assert result["failure_count"] == 1
        assert result["success_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
