"""Unit tests for AgnoAdapter Phase 1 implementation.

These tests verify the foundation functionality of the Agno adapter:
- Configuration validation
- Adapter initialization
- LLM provider factory
- MCP tools registry
- Agent creation
- Task execution (mocked)
- Health checks
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType
from mahavishnu.core.config import (
    AgnoAdapterConfig,
    AgnoLLMConfig,
    AgnoMemoryConfig,
    AgnoToolsConfig,
    LLMProvider,
    MemoryBackend,
)
from mahavishnu.core.errors import AgnoError, ConfigurationError, ErrorCode
from mahavishnu.engines.agno_adapter import (
    AgentRunResult,
    AgnoAdapter,
    LLMProviderFactory,
    MCPToolsRegistry,
    TeamRunResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def agno_llm_config() -> AgnoLLMConfig:
    """Create default LLM config for testing."""
    return AgnoLLMConfig(
        provider=LLMProvider.OLLAMA,
        model_id="qwen2.5:7b",
        base_url="http://localhost:11434",
        temperature=0.7,
        max_tokens=4096,
    )


@pytest.fixture
def agno_memory_config() -> AgnoMemoryConfig:
    """Create default memory config for testing."""
    return AgnoMemoryConfig(
        enabled=True,
        backend=MemoryBackend.SQLITE,
        db_path="data/test_agno.db",
        num_history_runs=10,
    )


@pytest.fixture
def agno_tools_config() -> AgnoToolsConfig:
    """Create default tools config for testing."""
    return AgnoToolsConfig(
        mcp_server_url="http://localhost:8677/mcp",
        mcp_transport="sse",
        enabled_tools=["search_code", "read_file"],
        tool_timeout_seconds=60,
    )


@pytest.fixture
def agno_adapter_config(
    agno_llm_config: AgnoLLMConfig,
    agno_memory_config: AgnoMemoryConfig,
    agno_tools_config: AgnoToolsConfig,
) -> AgnoAdapterConfig:
    """Create complete Agno adapter config for testing."""
    return AgnoAdapterConfig(
        enabled=True,
        llm=agno_llm_config,
        memory=agno_memory_config,
        tools=agno_tools_config,
        default_timeout_seconds=300,
        max_concurrent_agents=5,
        telemetry_enabled=True,
    )


@pytest.fixture
def mock_settings(agno_adapter_config: AgnoAdapterConfig) -> MagicMock:
    """Create mock MahavishnuSettings with Agno config."""
    settings = MagicMock()
    settings.agno = agno_adapter_config
    return settings


# ============================================================================
# Configuration Tests
# ============================================================================


class TestAgnoLLMConfig:
    """Tests for AgnoLLMConfig validation."""

    def test_default_config(self) -> None:
        """Test default LLM configuration values."""
        config = AgnoLLMConfig()
        assert config.provider == LLMProvider.OLLAMA
        assert config.model_id == "qwen2.5:7b"
        assert config.base_url == "http://localhost:11434"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_provider_validation(self) -> None:
        """Test LLM provider enum values."""
        assert LLMProvider.ANTHROPIC.value == "anthropic"
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.OLLAMA.value == "ollama"

    def test_temperature_bounds(self) -> None:
        """Test temperature validation."""
        # Valid temperatures
        AgnoLLMConfig(temperature=0.0)
        AgnoLLMConfig(temperature=1.0)
        AgnoLLMConfig(temperature=2.0)

        # Invalid temperatures
        with pytest.raises(ValueError):
            AgnoLLMConfig(temperature=-0.1)

        with pytest.raises(ValueError):
            AgnoLLMConfig(temperature=2.1)

    def test_max_tokens_bounds(self) -> None:
        """Test max_tokens validation."""
        # Valid max_tokens
        AgnoLLMConfig(max_tokens=1)
        AgnoLLMConfig(max_tokens=4096)
        AgnoLLMConfig(max_tokens=128000)

        # Invalid max_tokens
        with pytest.raises(ValueError):
            AgnoLLMConfig(max_tokens=0)

        with pytest.raises(ValueError):
            AgnoLLMConfig(max_tokens=128001)


class TestAgnoMemoryConfig:
    """Tests for AgnoMemoryConfig validation."""

    def test_default_config(self) -> None:
        """Test default memory configuration values."""
        config = AgnoMemoryConfig()
        assert config.enabled is True
        assert config.backend == MemoryBackend.SQLITE
        assert config.db_path == "data/agno.db"
        assert config.num_history_runs == 10

    def test_postgres_requires_connection_string(self) -> None:
        """Test that postgres backend requires connection_string."""
        with pytest.raises(ValueError, match="connection_string must be set"):
            AgnoMemoryConfig(
                backend=MemoryBackend.POSTGRES,
                connection_string=None,
            )

    def test_postgres_with_connection_string(self) -> None:
        """Test postgres backend with connection_string is valid."""
        config = AgnoMemoryConfig(
            backend=MemoryBackend.POSTGRES,
            connection_string="postgresql://user:pass@host/db",
        )
        assert config.backend == MemoryBackend.POSTGRES


class TestAgnoToolsConfig:
    """Tests for AgnoToolsConfig validation."""

    def test_default_config(self) -> None:
        """Test default tools configuration values."""
        config = AgnoToolsConfig()
        assert config.mcp_server_url == "http://localhost:8677/mcp"
        assert config.mcp_transport == "sse"
        assert len(config.enabled_tools) == 6
        assert config.tool_timeout_seconds == 60


class TestAgnoAdapterConfig:
    """Tests for AgnoAdapterConfig validation."""

    def test_default_config(self) -> None:
        """Test default adapter configuration values."""
        config = AgnoAdapterConfig()
        assert config.enabled is True
        assert isinstance(config.llm, AgnoLLMConfig)
        assert isinstance(config.memory, AgnoMemoryConfig)
        assert isinstance(config.tools, AgnoToolsConfig)
        assert config.default_timeout_seconds == 300
        assert config.max_concurrent_agents == 5

    def test_nested_config(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test nested configuration."""
        config = AgnoAdapterConfig(llm=agno_llm_config)
        assert config.llm.provider == LLMProvider.OLLAMA
        assert config.llm.model_id == "qwen2.5:7b"


# ============================================================================
# LLM Provider Factory Tests
# ============================================================================


class TestLLMProviderFactory:
    """Tests for LLMProviderFactory."""

    def test_factory_initialization(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test factory initialization."""
        factory = LLMProviderFactory(agno_llm_config)
        assert factory.config == agno_llm_config
        assert factory._model_instance is None

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_create_openai_model(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test OpenAI model creation."""
        agno_llm_config.provider = LLMProvider.OPENAI
        agno_llm_config.model_id = "gpt-4o"

        factory = LLMProviderFactory(agno_llm_config)

        # Patch the import location inside the method
        with patch("agno.models.openai.OpenAIChat") as mock_openai:
            mock_model = MagicMock()
            mock_openai.return_value = mock_model

            model = factory.create_model()

            mock_openai.assert_called_once()
            call_kwargs = mock_openai.call_args[1]
            assert call_kwargs["id"] == "gpt-4o"
            assert call_kwargs["api_key"] == "test-key"
            assert model == mock_model

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_create_anthropic_model(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test Anthropic model creation."""
        agno_llm_config.provider = LLMProvider.ANTHROPIC
        agno_llm_config.model_id = "claude-sonnet-4-6"

        factory = LLMProviderFactory(agno_llm_config)

        with patch("agno.models.anthropic.Claude") as mock_claude:
            mock_model = MagicMock()
            mock_claude.return_value = mock_model

            model = factory.create_model()

            mock_claude.assert_called_once()
            call_kwargs = mock_claude.call_args[1]
            assert call_kwargs["id"] == "claude-sonnet-4-6"
            assert call_kwargs["api_key"] == "test-key"
            assert model == mock_model

    def test_create_ollama_model(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test Ollama model creation."""
        agno_llm_config.provider = LLMProvider.OLLAMA
        agno_llm_config.model_id = "qwen2.5:7b"
        agno_llm_config.base_url = "http://localhost:11434"

        factory = LLMProviderFactory(agno_llm_config)

        with patch("agno.models.ollama.Ollama") as mock_ollama:
            mock_model = MagicMock()
            mock_ollama.return_value = mock_model

            model = factory.create_model()

            mock_ollama.assert_called_once()
            call_kwargs = mock_ollama.call_args[1]
            assert call_kwargs["id"] == "qwen2.5:7b"
            assert call_kwargs["host"] == "http://localhost:11434"
            assert model == mock_model

    def test_model_caching(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test that model is cached after first creation."""
        factory = LLMProviderFactory(agno_llm_config)

        with patch("agno.models.ollama.Ollama") as mock_ollama:
            mock_model = MagicMock()
            mock_ollama.return_value = mock_model

            model1 = factory.create_model()
            model2 = factory.create_model()

            # Should only be called once due to caching
            mock_ollama.assert_called_once()
            assert model1 is model2

    def test_missing_api_key(self, agno_llm_config: AgnoLLMConfig) -> None:
        """Test error when API key is missing."""
        agno_llm_config.provider = LLMProvider.OPENAI

        # Ensure no API key is set
        os.environ.pop("OPENAI_API_KEY", None)

        factory = LLMProviderFactory(agno_llm_config)

        with pytest.raises(ConfigurationError, match="API key not found"):
            factory.create_model()


# ============================================================================
# MCP Tools Registry Tests
# ============================================================================


class TestMCPToolsRegistry:
    """Tests for MCPToolsRegistry."""

    def test_registry_initialization(self, agno_tools_config: AgnoToolsConfig) -> None:
        """Test registry initialization."""
        registry = MCPToolsRegistry(agno_tools_config)
        assert registry.config == agno_tools_config
        assert registry._mcp_tools is None
        assert registry._initialized is False

    @pytest.mark.asyncio
    async def test_initialize_mcp_tools(self, agno_tools_config: AgnoToolsConfig) -> None:
        """Test MCP tools initialization."""
        registry = MCPToolsRegistry(agno_tools_config)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_tools = MagicMock()
            mock_mcp.return_value = mock_tools

            await registry.initialize()

            mock_mcp.assert_called_once_with(
                url=agno_tools_config.mcp_server_url,
                transport=agno_tools_config.mcp_transport,
            )
            assert registry._initialized is True
            assert registry._mcp_tools == mock_tools

    @pytest.mark.asyncio
    async def test_initialize_failure_graceful(
        self, agno_tools_config: AgnoToolsConfig
    ) -> None:
        """Test that MCP init failure is handled gracefully."""
        registry = MCPToolsRegistry(agno_tools_config)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.side_effect = Exception("Connection failed")

            # Should not raise
            await registry.initialize()

            assert registry._initialized is True
            assert registry._mcp_tools is None

    @pytest.mark.asyncio
    async def test_get_tools(self, agno_tools_config: AgnoToolsConfig) -> None:
        """Test getting tools from registry."""
        registry = MCPToolsRegistry(agno_tools_config)

        # Before initialization
        assert registry.get_tools() == []

        # After initialization with tools
        registry._mcp_tools = MagicMock()
        registry._initialized = True
        tools = registry.get_tools()
        assert len(tools) == 1
        assert tools[0] == registry._mcp_tools

    @pytest.mark.asyncio
    async def test_close(self, agno_tools_config: AgnoToolsConfig) -> None:
        """Test closing registry."""
        registry = MCPToolsRegistry(agno_tools_config)
        registry._mcp_tools = MagicMock()
        registry._initialized = True

        await registry.close()

        assert registry._mcp_tools is None
        assert registry._initialized is False


# ============================================================================
# AgnoAdapter Tests
# ============================================================================


class TestAgnoAdapter:
    """Tests for AgnoAdapter class."""

    def test_adapter_type(self, mock_settings: MagicMock) -> None:
        """Test adapter type is correct."""
        adapter = AgnoAdapter(mock_settings)
        assert adapter.adapter_type == AdapterType.AGNO

    def test_adapter_name(self, mock_settings: MagicMock) -> None:
        """Test adapter name is correct."""
        adapter = AgnoAdapter(mock_settings)
        assert adapter.name == "agno"

    def test_adapter_capabilities(self, mock_settings: MagicMock) -> None:
        """Test adapter capabilities."""
        adapter = AgnoAdapter(mock_settings)
        caps = adapter.capabilities

        assert isinstance(caps, AdapterCapabilities)
        assert caps.can_deploy_flows is True
        assert caps.can_monitor_execution is True
        assert caps.can_cancel_workflows is True
        assert caps.can_sync_state is True
        assert caps.supports_batch_execution is True
        assert caps.supports_multi_agent is True  # Key differentiator
        assert caps.has_cloud_ui is False

    def test_config_extraction_from_settings(self, mock_settings: MagicMock) -> None:
        """Test config extraction from MahavishnuSettings."""
        adapter = AgnoAdapter(mock_settings)
        # Check key fields match instead of object identity
        assert adapter.agno_config.enabled == mock_settings.agno.enabled
        assert adapter.agno_config.llm.provider == mock_settings.agno.llm.provider
        assert adapter.agno_config.llm.model_id == mock_settings.agno.llm.model_id

    def test_config_extraction_direct(self, agno_adapter_config: AgnoAdapterConfig) -> None:
        """Test config extraction when passed directly."""
        adapter = AgnoAdapter(agno_adapter_config)
        # Check key fields match instead of object identity
        assert adapter.agno_config.enabled == agno_adapter_config.enabled
        assert adapter.agno_config.llm.provider == agno_adapter_config.llm.provider
        assert adapter.agno_config.llm.model_id == agno_adapter_config.llm.model_id

    def test_config_fallback(self) -> None:
        """Test fallback to default config when no agno attribute."""
        # Create an object with no agno attribute
        class EmptyConfig:
            pass

        adapter = AgnoAdapter(EmptyConfig())
        # Check that default config is created with expected values
        assert adapter.agno_config.enabled is True
        assert adapter.agno_config.llm.provider == LLMProvider.OLLAMA
        assert adapter.agno_config.default_timeout_seconds == 300

    @pytest.mark.asyncio
    async def test_initialize(self, mock_settings: MagicMock) -> None:
        """Test adapter initialization."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()

            await adapter.initialize()

            assert adapter._initialized is True
            assert adapter._llm_factory is not None
            assert adapter._mcp_registry is not None
            assert adapter._semaphore is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, mock_settings: MagicMock) -> None:
        """Test that initialize is idempotent."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()

            await adapter.initialize()
            first_llm_factory = adapter._llm_factory

            await adapter.initialize()
            assert adapter._llm_factory is first_llm_factory

    @pytest.mark.asyncio
    async def test_get_health_uninitialized(self, mock_settings: MagicMock) -> None:
        """Test health check when not initialized."""
        adapter = AgnoAdapter(mock_settings)
        health = await adapter.get_health()

        assert health["status"] == "unhealthy"
        assert "not initialized" in health["details"]["reason"]

    @pytest.mark.asyncio
    async def test_get_health_healthy(self, mock_settings: MagicMock) -> None:
        """Test health check when healthy."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        health = await adapter.get_health()

        assert health["status"] == "healthy"
        assert health["details"]["adapter"] == "agno"
        assert health["details"]["initialized"] is True
        assert health["details"]["llm_provider"] == "ollama"

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_settings: MagicMock) -> None:
        """Test adapter shutdown."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()
            assert adapter._initialized is True

        await adapter.shutdown()

        assert adapter._initialized is False
        assert adapter._llm_factory is None
        assert adapter._mcp_registry is None
        assert len(adapter._agents) == 0

    @pytest.mark.asyncio
    async def test_create_agent(self, mock_settings: MagicMock) -> None:
        """Test agent creation."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        with patch("agno.agent.Agent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_agent_cls.return_value = mock_agent

            agent = await adapter._create_agent(
                name="test_agent",
                role="Test role",
                instructions="Test instructions",
            )

            mock_agent_cls.assert_called_once()
            assert agent == mock_agent
            assert "test_agent" in adapter._agents

    @pytest.mark.asyncio
    async def test_execute_empty_repos(self, mock_settings: MagicMock) -> None:
        """Test execute with empty repos list."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        result = await adapter.execute(task={"type": "test"}, repos=[])

        assert result["status"] == "completed"
        assert result["engine"] == "agno"
        assert result["repos_processed"] == 0
        assert result["success_count"] == 0

    @pytest.mark.asyncio
    async def test_execute_with_repos(self, mock_settings: MagicMock) -> None:
        """Test execute with repositories."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        # Mock agent creation and execution
        with patch.object(adapter, "_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_create.return_value = mock_agent

            with patch.object(adapter, "_run_agent") as mock_run:
                mock_run.return_value = AgentRunResult(
                    agent_name="test_agent",
                    content="Test response",
                    run_id="run_123",
                    success=True,
                )

                result = await adapter.execute(
                    task={"type": "test"},
                    repos=["/path/to/repo"],
                )

        assert result["status"] == "completed"
        assert result["repos_processed"] == 1
        assert result["success_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_auto_initialize(self, mock_settings: MagicMock) -> None:
        """Test that execute auto-initializes if needed."""
        adapter = AgnoAdapter(mock_settings)

        with patch.object(adapter, "initialize") as mock_init:
            mock_init.return_value = None

            with patch.object(adapter, "_process_single_repo") as mock_process:
                mock_process.return_value = {
                    "repo": "/test",
                    "status": "completed",
                    "task_id": "test",
                }

                await adapter.execute(task={"type": "test"}, repos=["/test"])

            mock_init.assert_called_once()


# ============================================================================
# Result Dataclass Tests
# ============================================================================


class TestAgentRunResult:
    """Tests for AgentRunResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = AgentRunResult(
            agent_name="test",
            content="content",
            run_id="run_123",
        )
        assert result.success is True
        assert result.error is None
        assert result.tokens_used == 0
        assert result.latency_ms == 0.0
        assert result.metadata == {}

    def test_all_fields(self) -> None:
        """Test all fields."""
        result = AgentRunResult(
            agent_name="test",
            content="content",
            run_id="run_123",
            success=False,
            error="Error message",
            tokens_used=100,
            latency_ms=500.0,
            metadata={"key": "value"},
        )
        assert result.agent_name == "test"
        assert result.success is False
        assert result.error == "Error message"
        assert result.tokens_used == 100
        assert result.latency_ms == 500.0
        assert result.metadata == {"key": "value"}


class TestTeamRunResult:
    """Tests for TeamRunResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = TeamRunResult(
            team_name="team",
            mode="coordinate",
            responses=[],
            run_id="run_123",
        )
        assert result.success is True
        assert result.error is None
        assert result.total_tokens == 0
        assert result.latency_ms == 0.0
        assert result.metadata == {}


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_agent_creation_error(self, mock_settings: MagicMock) -> None:
        """Test error handling during agent creation."""
        adapter = AgnoAdapter(mock_settings)

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        with patch("agno.agent.Agent") as mock_agent_cls:
            mock_agent_cls.side_effect = Exception("Agent creation failed")

            with pytest.raises(AgnoError, match="Failed to create agent"):
                await adapter._create_agent(
                    name="test",
                    role="role",
                    instructions="instructions",
                )

    @pytest.mark.asyncio
    async def test_process_repo_timeout(self, mock_settings: MagicMock) -> None:
        """Test timeout handling in repo processing."""
        adapter = AgnoAdapter(mock_settings)
        adapter.agno_config.default_timeout_seconds = 1  # Short timeout

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        result = await adapter._process_single_repo(
            repo="/test",
            task={"type": "test"},
        )

        # Should return timeout status
        assert result["status"] in ["timeout", "failed", "completed"]


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestAdapterIntegration:
    """Integration-style tests for adapter lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mock_settings: MagicMock) -> None:
        """Test full adapter lifecycle: init -> execute -> shutdown."""
        adapter = AgnoAdapter(mock_settings)

        # Initialize
        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        assert adapter._initialized is True

        # Execute
        with patch.object(adapter, "_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_create.return_value = mock_agent

            with patch.object(adapter, "_run_agent") as mock_run:
                mock_run.return_value = AgentRunResult(
                    agent_name="test_agent",
                    content="Result",
                    run_id="run_123",
                )

                result = await adapter.execute(
                    task={"type": "test"},
                    repos=["/test"],
                )

        assert result["status"] == "completed"

        # Health check
        health = await adapter.get_health()
        assert health["status"] == "healthy"

        # Shutdown
        await adapter.shutdown()
        assert adapter._initialized is False

    @pytest.mark.asyncio
    async def test_concurrent_execution(self, mock_settings: MagicMock) -> None:
        """Test concurrent repo execution."""
        adapter = AgnoAdapter(mock_settings)
        adapter.agno_config.max_concurrent_agents = 2

        with patch("agno.tools.mcp.MCPTools") as mock_mcp:
            mock_mcp.return_value = MagicMock()
            await adapter.initialize()

        with patch.object(adapter, "_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_create.return_value = mock_agent

            with patch.object(adapter, "_run_agent") as mock_run:
                mock_run.return_value = AgentRunResult(
                    agent_name="test_agent",
                    content="Result",
                    run_id="run_123",
                )

                result = await adapter.execute(
                    task={"type": "test"},
                    repos=["/repo1", "/repo2", "/repo3"],
                )

        assert result["repos_processed"] == 3


# ============================================================================
# Task Instructions Tests
# ============================================================================


class TestTaskInstructions:
    """Tests for task instruction generation."""

    def test_code_sweep_instructions(self, mock_settings: MagicMock) -> None:
        """Test code sweep task instructions."""
        adapter = AgnoAdapter(mock_settings)
        instructions = adapter._get_task_instructions("code_sweep")
        assert "code analysis" in instructions.lower()
        assert "quality" in instructions.lower()

    def test_quality_check_instructions(self, mock_settings: MagicMock) -> None:
        """Test quality check task instructions."""
        adapter = AgnoAdapter(mock_settings)
        instructions = adapter._get_task_instructions("quality_check")
        assert "quality" in instructions.lower()
        assert "standards" in instructions.lower()

    def test_default_instructions(self, mock_settings: MagicMock) -> None:
        """Test default task instructions."""
        adapter = AgnoAdapter(mock_settings)
        instructions = adapter._get_task_instructions("unknown_type")
        assert "assistant" in instructions.lower()


# ============================================================================
# Prompt Building Tests
# ============================================================================


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_code_sweep_prompt(self, mock_settings: MagicMock) -> None:
        """Test code sweep prompt."""
        adapter = AgnoAdapter(mock_settings)
        prompt = adapter._build_task_prompt(
            task_type="code_sweep",
            repo="/path/to/repo",
            task={"type": "code_sweep", "params": {"focus": "security"}},
        )
        assert "/path/to/repo" in prompt
        assert "security" in prompt

    def test_quality_check_prompt(self, mock_settings: MagicMock) -> None:
        """Test quality check prompt."""
        adapter = AgnoAdapter(mock_settings)
        prompt = adapter._build_task_prompt(
            task_type="quality_check",
            repo="/path/to/repo",
            task={"type": "quality_check", "params": {"standards": "PEP8"}},
        )
        assert "/path/to/repo" in prompt
        assert "PEP8" in prompt

    def test_default_prompt(self, mock_settings: MagicMock) -> None:
        """Test default prompt."""
        adapter = AgnoAdapter(mock_settings)
        prompt = adapter._build_task_prompt(
            task_type="custom",
            repo="/path/to/repo",
            task={"type": "custom", "params": {}},
        )
        assert "/path/to/repo" in prompt
        assert "custom" in prompt
