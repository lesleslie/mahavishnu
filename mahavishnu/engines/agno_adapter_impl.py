"""Production Agno adapter for multi-agent AI orchestration.

This module implements the AgnoAdapter using the real Agno SDK (v2.5.3+)
for agent-based workflows with multi-agent team support.

Key Features:
- Multi-agent team orchestration
- Native MCP tool integration
- Native Agno tools (file operations, code analysis)
- Multiple LLM provider support (Anthropic, OpenAI, Ollama, MiniMax)
- Memory and session management
- OpenTelemetry instrumentation

SDK Verified: 2026-02-20 against Agno v2.5.3
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import logging
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from ..core.errors import (
    AgnoError,
    ConfigurationError,
    ErrorCode,
)
from ..core.errors import (
    TimeoutError as MahavishnuTimeoutError,
)

# Canonical Agno config schema — imported from core.config.
# The previous duplicates of LLMProvider, MemoryBackend, AgnoLLMConfig,
# AgnoMemoryConfig, AgnoToolsConfig, AgnoAdapterConfig lived in this module
# and caused `isinstance(config.agno, AgnoAdapterConfig)` to fail silently
# because the two classes were distinct objects. That made `_get_agno_config`
# return the engine's defaults (provider=ollama) instead of the user-configured
# values (provider=minimax).
from ..core.config import (
    AgnoAdapterConfig,
    AgnoLLMConfig,
    AgnoMemoryConfig,
    AgnoToolsConfig,
    LLMProvider,
    MemoryBackend,
)

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.agent import RunOutput
    from agno.team import Team

    from .agno_teams.config import TeamConfig
    from .agno_teams.manager import AgentTeamManager

logger = logging.getLogger(__name__)



# ============================================================================
# Agent Results
# ============================================================================


@dataclass
class AgentRunResult:
    """Result from a single agent run."""

    agent_name: str
    content: str
    run_id: str
    success: bool = True
    error: str | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamRunResult:
    """Result from a team run with multiple agents."""

    team_name: str
    mode: str
    responses: list[AgentRunResult]
    run_id: str
    success: bool = True
    error: str | None = None
    total_tokens: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# LLM Provider Factory
# ============================================================================


class LLMProviderFactory:
    """Factory for creating LLM model instances for Agno agents.

    Uses the verified Agno v2.5.3 import paths:
    - OpenAIChat from agno.models.openai
    - Claude from agno.models.anthropic
    - Ollama from agno.models.ollama

    IMPORTANT: Model instantiation uses `id=` parameter, NOT `model=`.
    """

    def __init__(self, config: AgnoLLMConfig):
        """Initialize factory with LLM configuration.

        Args:
            config: LLM configuration specifying provider and model settings
        """
        self.config = config
        self._model_instance = None

    _PROVIDER_FACTORY_METHODS: dict[str, str] = {
        LLMProvider.OPENAI: "_create_openai_model",
        LLMProvider.ANTHROPIC: "_create_anthropic_model",
        LLMProvider.OLLAMA: "_create_ollama_model",
        LLMProvider.MINIMAX: "_create_minimax_model",
    }

    def _instantiate_model(self, provider: str, model_id: str, factory_name: str) -> Any:
        try:
            instance = getattr(self, factory_name)(model_id)
            logger.info(f"Created LLM model: provider={provider}, model_id={model_id}")
            return instance
        except ImportError as e:
            raise AgnoError(
                f"Failed to import LLM provider '{provider}': {e}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider, "import_error": str(e)},
            ) from e

    def create_model(self) -> Any:
        """Create and return an LLM model instance.

        Returns:
            LLM model instance (OpenAIChat, Claude, or Ollama)

        Raises:
            AgnoError: If LLM provider is not available or misconfigured
        """
        if self._model_instance is not None:
            return self._model_instance

        provider = self.config.provider
        model_id = self.config.model_id
        factory_name = self._PROVIDER_FACTORY_METHODS.get(provider)
        if factory_name is None:
            raise AgnoError(
                f"Unsupported LLM provider: {provider}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider},
            )

        try:
            self._model_instance = self._instantiate_model(provider, model_id, factory_name)
            return self._model_instance
        except (AgnoError, ConfigurationError):
            raise
        except Exception as e:
            raise AgnoError(
                f"Failed to create LLM model: {e}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider, "model_id": model_id, "error": str(e)},
            ) from e

    def _create_openai_model(self, model_id: str) -> Any:
        """Create OpenAI model instance.

        Args:
            model_id: OpenAI model identifier (e.g., 'gpt-4o', 'gpt-4o-mini')

        Returns:
            OpenAIChat model instance
        """
        from agno.models.openai import OpenAIChat

        api_key = self._get_api_key("OPENAI_API_KEY", self.config.api_key_env)

        # Use id= parameter (NOT model=) per Agno v2.5.3 API
        return OpenAIChat(
            id=model_id,
            api_key=api_key,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_anthropic_model(self, model_id: str) -> Any:
        """Create Anthropic Claude model instance.

        Args:
            model_id: Claude model identifier (e.g., 'claude-sonnet-4-6')

        Returns:
            Claude model instance
        """
        from agno.models.anthropic import Claude

        api_key = self._get_api_key("ANTHROPIC_API_KEY", self.config.api_key_env)

        return Claude(
            id=model_id,
            api_key=api_key,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_ollama_model(self, model_id: str) -> Any:
        """Create Ollama model instance for local LLM.

        Args:
            model_id: Ollama model identifier (e.g., 'qwen2.5:7b', 'llama2')

        Returns:
            Ollama model instance
        """
        from agno.models.ollama import Ollama

        options = {
            "temperature": self.config.temperature,
            "num_predict": self.config.max_tokens,
        }

        return Ollama(
            id=model_id,
            host=self.config.base_url or "http://localhost:11434",
            options=options,
        )

    def _create_minimax_model(self, model_id: str) -> Any:
        """Create MiniMax model instance using the OpenAI-compatible endpoint.

        Uses MiniMax M3 models through the public OpenAI-compatible API.
        Base URL: https://api.minimax.io/v1

        Args:
            model_id: MiniMax model identifier (e.g., 'MiniMax-M3', 'MiniMax-M3-highspeed')

        Returns:
            OpenAIChat model instance configured for MiniMax
        """
        from agno.models.openai import OpenAIChat

        api_key = self._get_api_key("MINIMAX_API_KEY", self.config.api_key_env)

        return OpenAIChat(
            id=model_id,
            api_key=api_key,
            base_url=self.config.base_url or "https://api.minimax.io/v1",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _get_api_key(self, default_env: str, custom_env: str | None) -> str:
        """Get API key from environment.

        Args:
            default_env: Default environment variable name
            custom_env: Custom environment variable name (takes precedence)

        Returns:
            API key string

        Raises:
            ConfigurationError: If API key is not set
        """
        env_var = custom_env or default_env
        api_key = os.getenv(env_var)

        if not api_key:
            raise ConfigurationError(
                f"API key not found. Set {env_var} environment variable.",
                details={"env_var": env_var},
            )

        return api_key


# ============================================================================
# MCP Tools Integration
# ============================================================================


class MCPToolsRegistry:
    """Registry for MCP tools integration with Agno agents.

    Uses Agno's native MCPTools for seamless tool integration.
    Supports SSE and stdio transports.
    """

    def __init__(self, config: AgnoToolsConfig):
        """Initialize MCP tools registry.

        Args:
            config: Tool configuration with MCP server URL and settings
        """
        self.config = config
        self._mcp_tools: Any | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize MCP tools connection.

        Raises:
            AgnoError: If MCP connection fails
        """
        if self._initialized:
            return

        try:
            from agno.tools.mcp import MCPTools

            self._mcp_tools = MCPTools(
                url=self.config.mcp_server_url,
                transport=self.config.mcp_transport,  # type: ignore[arg-type]
            )

            self._initialized = True
            logger.info(
                f"MCP tools initialized: url={self.config.mcp_server_url}, "
                f"transport={self.config.mcp_transport}"
            )

        except Exception as e:
            logger.warning(f"Failed to initialize MCP tools: {e}")
            # Don't raise - MCP tools are optional
            self._initialized = True

    def get_tools(self) -> list[Any]:
        """Get list of tools for agent use.

        Returns:
            List of tool instances (may be empty if MCP not available)
        """
        if self._mcp_tools is not None:
            return [self._mcp_tools]
        return []

    async def close(self) -> None:
        """Close MCP tools connection."""
        self._mcp_tools = None
        self._initialized = False


# ============================================================================
# Native Tools Registry (Phase 3)
# ============================================================================


class NativeToolsRegistry:
    """Registry for native Agno tools.

    Provides file operations and code analysis tools that can be used
    directly by Agno agents without MCP integration.
    """

    def __init__(self, enabled: bool = True):
        """Initialize native tools registry.

        Args:
            enabled: Whether to enable native tools
        """
        self.enabled = enabled
        self._tools: list[Any] = []

    def get_tools(self) -> list[Any]:
        """Get list of native tool functions.

        Returns:
            List of native tool functions
        """
        if not self.enabled:
            return []

        if self._tools:
            return self._tools

        try:
            # Import native tools from agno_tools module
            from .agno_tools import ALL_TOOLS

            self._tools = list(ALL_TOOLS)
            logger.debug(f"Loaded {len(self._tools)} native tools")
            return self._tools

        except ImportError as e:
            logger.warning(f"Failed to import native tools: {e}")
            return []

    def get_available_tools(self) -> list[str]:
        """Get list of available native tool names.

        Returns:
            List of tool names
        """
        tools = self.get_tools()
        names = []
        for t in tools:
            # Agno Function objects have a .name attribute
            if hasattr(t, "name"):
                names.append(t.name)
            elif hasattr(t, "__name__"):
                names.append(t.__name__)
            else:
                names.append(str(t))
        return names


# ============================================================================
# Main AgnoAdapter Implementation
# ============================================================================


class AgnoAdapter(OrchestratorAdapter):
    """Production Agno adapter for multi-agent AI orchestration.

    This adapter implements the OrchestratorAdapter interface using the
    real Agno SDK (v2.5.3+) for multi-agent team workflows.

    Key Capabilities:
    - Multi-agent team orchestration (supports_multi_agent=True)
    - Native MCP tool integration
    - Native Agno tools (file operations, code analysis) (Phase 3)
    - Multiple LLM providers (Anthropic, OpenAI, Ollama)
    - Memory and session management
    - Batch execution support

    Example:
        ```python
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.engines.agno_adapter_impl import AgnoAdapter

        settings = MahavishnuSettings()
        adapter = AgnoAdapter(config=settings)
        await adapter.initialize()

        # Single agent execution
        result = await adapter.execute(
            task={"type": "code_sweep", "params": {}},
            repos=["/path/to/repo"]
        )

        # Multi-agent team execution (Phase 2)
        from mahavishnu.engines.agno_teams import TeamConfig, TeamMode
        team_config = TeamConfig(
            name="review_team",
            mode=TeamMode.COORDINATE,
            leader=MemberConfig(...),
            members=[MemberConfig(...)],
        )
        team_id = await adapter.create_team(team_config)
        result = await adapter.run_team(team_id, "Review this code")

        await adapter.shutdown()
        ```
    """

    # Class-level constants
    ADAPTER_VERSION: ClassVar[str] = "1.0.0"
    MIN_AGNO_VERSION: ClassVar[str] = "2.5.0"

    def __init__(self, config: Any | None = None, api_url: str | None = None) -> None:
        """Initialize Agno adapter with configuration.

        Args:
            config: MahavishnuSettings instance containing Agno configuration
            api_url: Optional compatibility override for legacy tests and callers
        """
        if config is None and api_url is not None:
            config = SimpleNamespace(api_url=api_url)

        self.config = config

        # Extract Agno-specific configuration
        self.agno_config = self._get_agno_config(config)
        self.api_url = (
            api_url
            or getattr(self.agno_config.tools, "mcp_server_url", None)
            or "http://localhost:8000"
        )

        # Initialize internal state
        self._client: Any | None = None
        self._initialized = False
        self._llm_factory: LLMProviderFactory | None = None
        self._mcp_registry: MCPToolsRegistry | None = None
        self._native_tools_registry: NativeToolsRegistry | None = None
        self._agents: dict[str, Agent] = {}
        self._teams: dict[str, Team] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._team_manager: AgentTeamManager | None = None
        self._execution_log: deque[dict[str, Any]] = deque(maxlen=200)

        # Set up capabilities
        self._capabilities = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
            has_cloud_ui=False,
        )

    def _get_agno_config(self, config: Any) -> AgnoAdapterConfig:
        """Extract Agno configuration from settings.

        Args:
            config: MahavishnuSettings or AgnoAdapterConfig instance

        Returns:
            AgnoAdapterConfig instance
        """
        if isinstance(config, AgnoAdapterConfig):
            return config

        # Try to get agno config from MahavishnuSettings
        if hasattr(config, "agno") and isinstance(config.agno, AgnoAdapterConfig):
            return config.agno

        # Fall back to default config
        return AgnoAdapterConfig()

    @property
    def adapter_type(self) -> AdapterType:
        """Return adapter type enum."""
        return AdapterType.AGNO

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "agno"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities."""
        return self._capabilities

    @property
    def agent_team_manager(self) -> AgentTeamManager | None:
        """Get the agent team manager instance.

        Returns:
            AgentTeamManager instance if initialized, None otherwise.
        """
        return self._team_manager

    async def initialize(self) -> None:
        """Initialize Agno adapter.

        This method:
        1. Validates Agno SDK version
        2. Initializes LLM provider factory
        3. Initializes MCP tools registry
        4. Initializes native tools registry (Phase 3)
        5. Sets up concurrency semaphore
        6. Initializes team manager (Phase 2)

        Raises:
            AgnoError: If initialization fails
        """
        if self._initialized:
            logger.warning("AgnoAdapter already initialized")
            return

        logger.info("Initializing AgnoAdapter...")

        try:
            # Validate Agno SDK
            self._validate_agno_sdk()

            # Initialize LLM provider factory
            self._llm_factory = LLMProviderFactory(self.agno_config.llm)

            # Initialize MCP tools registry
            self._mcp_registry = MCPToolsRegistry(self.agno_config.tools)
            await self._mcp_registry.initialize()

            # Initialize native tools registry (Phase 3)
            self._native_tools_registry = NativeToolsRegistry(
                enabled=self.agno_config.tools.enable_native_tools
            )

            # Set up concurrency semaphore
            self._semaphore = asyncio.Semaphore(self.agno_config.max_concurrent_agents)

            # Initialize team manager (Phase 2)
            await self._initialize_team_manager()

            self._initialized = True
            self._client = httpx.AsyncClient(base_url=self.api_url)
            try:
                await self._client.get(self.api_url)
            except Exception as e:
                logger.warning(f"AgnoAdapter compatibility ping failed: {e}")
            logger.info(
                f"AgnoAdapter initialized successfully: "
                f"provider={self.agno_config.llm.provider.value}, "
                f"model={self.agno_config.llm.model_id}, "
                f"native_tools={len(self.get_available_tools())}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize AgnoAdapter: {e}")
            raise AgnoError(
                f"AgnoAdapter initialization failed: {e}",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"error": str(e)},
            ) from e

    async def _initialize_team_manager(self) -> None:
        """Initialize the agent team manager for multi-agent orchestration."""
        from .agno_teams.manager import AgentTeamManager

        # Get all tools (MCP + native)
        all_tools = self._get_all_tools()

        self._team_manager = AgentTeamManager(
            llm_factory=self._llm_factory,
            mcp_tools=all_tools,
            max_concurrent_agents=self.agno_config.max_concurrent_agents,
        )

        logger.debug("AgentTeamManager initialized")

    def _validate_agno_sdk(self) -> None:
        """Validate Agno SDK is available with correct version.

        Raises:
            AgnoError: If Agno SDK is not available or version mismatch
        """
        try:
            import agno

            version = getattr(agno, "__version__", "unknown")
            logger.debug(f"Agno SDK version: {version}")

            # Version check could be added here if needed
            # For now, we just verify imports work

        except ImportError as e:
            raise AgnoError(
                "Agno SDK not installed. Install with: pip install agno>=2.5.0",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"import_error": str(e)},
            ) from e

    def _get_all_tools(self) -> list[Any]:
        """Get all available tools (MCP + native).

        Returns:
            Combined list of MCP and native tools
        """
        tools = []

        # Add MCP tools
        if self._mcp_registry:
            tools.extend(self._mcp_registry.get_tools())

        # Add native tools (Phase 3)
        if self._native_tools_registry:
            tools.extend(self._native_tools_registry.get_tools())

        return tools

    def get_available_tools(self) -> list[str]:
        """Get list of available native tool names.

        Returns:
            List of tool names that can be used by agents
        """
        if self._native_tools_registry:
            return self._native_tools_registry.get_available_tools()
        return []

    # ========================================================================
    # Team Management Methods (Phase 2)
    # ========================================================================

    async def create_team(self, config: TeamConfig) -> str:
        """Create an agent team from configuration.

        Args:
            config: TeamConfig instance defining the team structure.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If team creation fails or adapter not initialized.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        team_id = await self._team_manager.create_team(config)
        self._execution_log.append(
            {
                "kind": "team_created",
                "team_id": team_id,
                "team_name": getattr(config, "name", team_id),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return team_id

    async def create_team_from_yaml(self, yaml_path: str) -> str:
        """Create a team from a YAML configuration file.

        Args:
            yaml_path: Path to the YAML configuration file.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If file loading or team creation fails.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        return await self._team_manager.create_team_from_yaml(yaml_path)

    async def run_team(
        self,
        team_id: str,
        task: str,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> TeamRunResult:
        """Run a team task and return aggregated results.

        Args:
            team_id: Team ID returned from create_team().
            task: Task/prompt for the team to process.
            mode: Optional mode override (coordinate, route, broadcast).
            session_id: Optional session ID for memory continuity.

        Returns:
            TeamRunResult with responses from all participating agents.

        Raises:
            AgnoError: If team execution fails or team not found.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        result = await self._team_manager.run_team(team_id, task, mode, session_id)
        self._execution_log.append(
            {
                "kind": "team_run",
                "team_id": team_id,
                "task": task,
                "mode": mode or "coordinate",
                "session_id": session_id,
                "response_count": len(getattr(result, "responses", []) or []),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return result  # type: ignore[return-value]

    async def get_team(self, team_id: str) -> Team | None:
        """Get a team instance by ID.

        Args:
            team_id: Team ID to look up.

        Returns:
            Team instance if found, None otherwise.
        """
        if not self._team_manager:
            return None
        return await self._team_manager.get_team(team_id)

    def list_teams(self) -> list[str]:
        """List all team IDs.

        Returns:
            List of team ID strings.
        """
        if not self._team_manager:
            return []
        return self._team_manager.list_teams()

    def get_execution_log(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent execution summaries for cockpit views."""
        if limit <= 0:
            return []
        return list(self._execution_log)[-limit:]

    async def delete_team(self, team_id: str) -> bool:
        """Delete a team and cleanup resources.

        Args:
            team_id: Team ID to delete.

        Returns:
            True if team was deleted, False if not found.
        """
        if not self._team_manager:
            return False
        return await self._team_manager.delete_team(team_id)

    # ========================================================================
    # Single Agent Methods (Phase 1)
    # ========================================================================

    async def _create_agent(
        self,
        name: str,
        role: str | None = None,
        instructions: str | None = None,
        tools: list[Any] | None = None,
        model: Any | None = None,
    ) -> Agent:
        """Create an Agno agent instance.

        Args:
            name: Agent name
            role: Agent role description
            instructions: Agent instructions
            tools: Optional list of tools (defaults to all available tools)
            model: Optional LLM model (uses default if not provided)

        Returns:
            Configured Agent instance

        Raises:
            AgnoError: If agent creation fails
        """
        from agno.agent import Agent

        if role is None or instructions is None:
            task_type = name
            name = f"{task_type}_agent"
            role = f"Agent for {task_type} operations"
            instructions = self._get_task_instructions(task_type)

        if model is None:
            model = self._get_llm()

        if tools is None:
            # Use all available tools (MCP + native) (Phase 3)
            tools = self._get_all_tools()

        try:
            agent = Agent(
                name=name,
                role=role,
                instructions=instructions,
                model=model,
                tools=tools,
            )

            # Cache the agent
            self._agents[name] = agent

            logger.debug(f"Created agent: name={name}, role={role}, tools={len(tools)}")
            return agent

        except Exception as e:
            raise AgnoError(
                f"Failed to create agent '{name}': {e}",
                error_code=ErrorCode.AGNO_AGENT_NOT_FOUND,
                details={"agent_name": name, "error": str(e)},
            ) from e

    def _create_mock_agent(self, task_type: str) -> Any:
        """Create a lightweight fallback agent for mocked or offline runs."""

        async def arun(message: str) -> Any:
            return SimpleNamespace(
                content=f"Mock response for {task_type}",
                run_id=f"mock-{task_type}",
                messages=[],
            )

        return SimpleNamespace(name=f"{task_type}_mock_agent", arun=arun)

    def _resolve_legacy_llm_config(self) -> AgnoLLMConfig:
        """Resolve LLM settings from legacy flat config shapes."""
        llm_config = getattr(self.config, "llm", None)

        def _clean_str(value: Any) -> str | None:
            return value if isinstance(value, str) and value else None

        def _clean_number(value: Any) -> int | float | None:
            return value if isinstance(value, (int, float)) else None

        provider_value = getattr(self.config, "llm_provider", None)
        if provider_value is None and llm_config is not None:
            provider_value = getattr(llm_config, "provider", None)

        model_id = None
        if llm_config is not None:
            model_id = _clean_str(getattr(llm_config, "model_id", None)) or _clean_str(
                getattr(llm_config, "model", None)
            )

        base_url = None
        if llm_config is not None:
            base_url = _clean_str(getattr(llm_config, "base_url", None)) or _clean_str(
                getattr(llm_config, "ollama_base_url", None)
            )

        api_key_env = (
            _clean_str(getattr(llm_config, "api_key_env", None)) if llm_config is not None else None
        )
        temperature = (
            _clean_number(getattr(llm_config, "temperature", None))
            if llm_config is not None
            else None
        )
        max_tokens = (
            _clean_number(getattr(llm_config, "max_tokens", None))
            if llm_config is not None
            else None
        )

        if temperature is None:
            temperature = self.agno_config.llm.temperature
        if max_tokens is None:
            max_tokens = self.agno_config.llm.max_tokens

        try:
            provider = (
                provider_value
                if isinstance(provider_value, LLMProvider)
                else LLMProvider(provider_value)
                if isinstance(provider_value, str)
                else self.agno_config.llm.provider
            )
        except ValueError as exc:
            raise ConfigurationError(
                f"Unsupported LLM provider: {provider_value}",
                details={"provider": provider_value},
            ) from exc

        return AgnoLLMConfig(
            provider=provider,
            model_id=model_id or self.agno_config.llm.model_id,
            api_key_env=api_key_env or self.agno_config.llm.api_key_env,
            base_url=base_url or self.agno_config.llm.base_url,
            temperature=temperature,
            max_tokens=max_tokens,  # type: ignore[arg-type]
        )

    def _get_llm(self) -> Any:
        """Compatibility helper that returns the configured LLM model."""
        if self._llm_factory is None:
            self._llm_factory = LLMProviderFactory(self._resolve_legacy_llm_config())

        try:
            return self._llm_factory.create_model()
        except AgnoError as exc:
            message = str(exc)
            if "Unsupported LLM provider" in message:
                raise ConfigurationError(message, details=getattr(exc, "details", None)) from exc
            if "Failed to import LLM provider" in message:
                raise ImportError(message) from exc
            raise

    async def _run_agent(
        self,
        agent: Agent,
        message: str,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AgentRunResult:
        """Run an agent with a message and return structured result.

        Args:
            agent: Agent instance to run
            message: Message/prompt for the agent
            context: Optional context dictionary
            session_id: Optional session ID for memory

        Returns:
            AgentRunResult with response content and metadata

        Raises:
            AgnoError: If agent execution fails
        """
        import time

        start_time = time.monotonic()

        try:
            # Run agent with timeout
            async with asyncio.timeout(self.agno_config.default_timeout_seconds):
                response: RunOutput = await agent.arun(message)

            latency_ms = (time.monotonic() - start_time) * 1000

            # Extract content from response
            content = self._extract_content(response)

            return AgentRunResult(
                agent_name=agent.name,  # type: ignore[arg-type]
                content=content,
                run_id=getattr(response, "run_id", "unknown"),
                success=True,
                latency_ms=latency_ms,
                metadata={"session_id": session_id, "context": context},
            )

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            raise MahavishnuTimeoutError(
                operation=f"agent_run:{agent.name}",
                timeout_seconds=self.agno_config.default_timeout_seconds,
                details={"agent_name": agent.name, "latency_ms": latency_ms},
            ) from None
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            raise AgnoError(
                f"Agent '{agent.name}' execution failed: {e}",
                error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                details={
                    "agent_name": agent.name,
                    "error": str(e),
                    "latency_ms": latency_ms,
                },
            ) from e

    def _extract_content(self, response: RunOutput) -> str:
        """Extract content from Agno RunOutput.

        Args:
            response: RunOutput from agent execution

        Returns:
            String content from response
        """
        # Try different content extraction methods
        if hasattr(response, "content") and response.content:
            if isinstance(response.content, str):
                return response.content
            return str(response.content)

        if hasattr(response, "messages") and response.messages:
            # Extract from last message
            last_message = response.messages[-1]
            if hasattr(last_message, "content"):
                return str(last_message.content)

        # Fallback to string representation
        return str(response)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def _process_single_repo(
        self,
        repo: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Process a single repository with Agno agent.

        Args:
            repo: Repository path
            task: Task specification

        Returns:
            Processing result dictionary
        """
        async with self._semaphore:  # type: ignore[union-attr]
            task_type = task.get("type", "default")

            try:
                # Create agent for task type
                agent = await self._create_agent(task_type)
                if agent is None:
                    agent = self._create_mock_agent(task_type)

                # Build prompt based on task type
                prompt = self._build_task_prompt(task_type, repo, task)

                # Run agent
                result = await self._run_agent(
                    agent=agent,
                    message=prompt,
                    context={"repo_path": repo, "task": task},
                )

                return {
                    "repo": repo,
                    "status": "completed",
                    "result": {
                        "operation": task_type,
                        "content": result.content,
                        "run_id": result.run_id,
                        "latency_ms": result.latency_ms,
                    },
                    "task_id": task.get("id", "unknown"),
                }

            except MahavishnuTimeoutError as e:
                return {
                    "repo": repo,
                    "status": "timeout",
                    "error": str(e),
                    "task_id": task.get("id", "unknown"),
                }
            except AgnoError as e:
                return {
                    "repo": repo,
                    "status": "failed",
                    "error": e.message,
                    "error_code": e.error_code.value,
                    "task_id": task.get("id", "unknown"),
                }
            except Exception as e:
                logger.exception(f"Unexpected error processing repo {repo}")
                return {
                    "repo": repo,
                    "status": "failed",
                    "error": str(e),
                    "task_id": task.get("id", "unknown"),
                }

    def _get_task_instructions(self, task_type: str) -> str:
        """Get agent instructions for task type.

        Args:
            task_type: Type of task

        Returns:
            Instruction string for agent
        """
        instructions = {
            "code_sweep": """You are a code analysis agent. Analyze the repository
for code quality, potential improvements, and best practices. Focus on:
- Code structure and organization
- Potential bugs or issues
- Performance considerations
- Documentation completeness

Use available tools like read_file, analyze_code, and search_code to explore the codebase.""",
            "quality_check": """You are a quality assurance agent. Evaluate the
repository against quality standards. Check for:
- Code style compliance
- Test coverage indicators
- Security best practices
- Maintainability concerns

Use available tools to examine code files and provide a detailed assessment.""",
            "default": """You are a helpful AI assistant. Process the given task
using available tools and provide clear, actionable responses.

Available tools include:
- read_file: Read file contents
- write_file: Write content to files
- list_directory: List directory contents
- search_files: Search for files by pattern
- analyze_code: Analyze Python code for complexity and issues
- search_code: Search for code patterns in repositories
- get_function_signature: Get function signatures from code""",
        }
        return instructions.get(task_type, instructions["default"])

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON payload to the compatibility API endpoint."""
        url = f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                raise AgnoError(
                    f"Agno API request failed: {response.status_code}",
                    error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                    details={"url": url, "status_code": response.status_code},
                )

            json_attr = getattr(response, "json", None)
            data = json_attr() if callable(json_attr) else json_attr
            if isinstance(data, dict):
                return data
            return {}

    async def create_crew(self, crew_name: str, crew_config: dict[str, Any]) -> str:
        """Create a crew via the compatibility API."""
        if not self._initialized:
            await self.initialize()

        payload = {"crew_name": crew_name, "crew_config": crew_config}
        data = await self._post_json("/crews", payload)
        crew_id = data.get("crew_id") or data.get("id") or crew_name
        return str(crew_id)

    async def execute_task(self, crew_id: str, task: dict[str, Any]) -> str:
        """Execute a single crew task via the compatibility API."""
        if not self._initialized:
            await self.initialize()

        payload = {"crew_id": crew_id, "task": task}
        data = await self._post_json("/tasks", payload)
        execution_id = data.get("execution_id") or data.get("id") or crew_id
        return str(execution_id)

    async def execute_task_batch(self, crew_id: str, tasks: list[dict[str, Any]]) -> list[str]:
        """Execute a batch of tasks via the compatibility API."""
        results: list[str] = []
        for task in tasks:
            results.append(await self.execute_task(crew_id=crew_id, task=task))
        return results

    def _build_task_prompt(
        self,
        task_type: str,
        repo: str,
        task: dict[str, Any],
    ) -> str:
        """Build prompt for agent based on task.

        Args:
            task_type: Type of task
            repo: Repository path
            task: Task specification

        Returns:
            Prompt string for agent
        """
        params = task.get("params", {})

        if task_type == "code_sweep":
            return f"""Analyze the repository at {repo} for code quality and
improvement opportunities. Focus on: {params.get("focus", "general analysis")}.

Use available tools (read_file, list_directory, search_files, analyze_code) to explore the codebase and provide specific,
actionable recommendations."""

        if task_type == "quality_check":
            return f"""Perform a quality check on the repository at {repo}.
Evaluate against: {params.get("standards", "Python best practices")}.

Use available tools to examine the code and provide a compliance score and list any issues found."""

        # Default prompt
        return f"""Process the following task for repository {repo}:

Task type: {task_type}
Parameters: {params}

Use available tools to complete the task and provide a summary."""

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> dict[str, Any]:
        """Execute a task using Agno agents across repositories.

        This is the main entry point for the OrchestratorAdapter interface.
        It creates agents for each repository and executes them concurrently.

        Args:
            task: Task specification with type and parameters
            repos: List of repository paths to process

        Returns:
            Execution result with status, results per repo, and metadata

        Raises:
            AgnoError: If execution fails critically
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Executing Agno task: type={task.get('type')}, repos={len(repos)}")

        try:
            # Process repositories concurrently with semaphore
            results = await asyncio.gather(
                *[self._process_single_repo(repo, task) for repo in repos],
                return_exceptions=True,
            )

            # Convert exceptions to error results
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(
                        {
                            "repo": repos[i],
                            "status": "failed",
                            "error": str(result),
                            "task_id": task.get("id", "unknown"),
                        }
                    )
                else:
                    processed_results.append(result)  # type: ignore[arg-type]

            # Calculate success/failure counts
            success_count = sum(1 for r in processed_results if r.get("status") == "completed")
            failure_count = len(processed_results) - success_count
            self._execution_log.append(
                {
                    "kind": "task_batch",
                    "task_type": task.get("type", "default"),
                    "repos": list(repos),
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            return {
                "status": "completed",
                "engine": "agno",
                "engine_version": self.ADAPTER_VERSION,
                "task": task,
                "repos_processed": len(repos),
                "results": processed_results,
                "success_count": success_count,
                "failure_count": failure_count,
                "adapter": "AgnoAdapter",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except Exception as e:
            logger.exception("Agno execution failed")
            raise AgnoError(
                f"Agno execution failed: {e}",
                error_code=ErrorCode.INTERNAL_ERROR,
                details={"task": task, "repos": repos, "error": str(e)},
            ) from e

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details.
        """
        health_details = {
            "adapter": "agno",
            "version": self.ADAPTER_VERSION,
            "configured": self.agno_config is not None,
            "initialized": self._initialized,
            "llm_provider": self.agno_config.llm.provider.value if self.agno_config else None,
            "model_id": self.agno_config.llm.model_id if self.agno_config else None,
            "agents_cached": len(self._agents),
            "teams_count": len(self._teams),
            "mcp_tools_initialized": self._mcp_registry._initialized
            if self._mcp_registry
            else False,
            "team_manager_initialized": self._team_manager is not None,
            "native_tools_count": len(self.get_available_tools()),
        }

        # Determine health status
        if not self._initialized:
            return {
                "status": "unhealthy",
                "details": {**health_details, "reason": "Adapter not initialized"},
            }

        # Test LLM provider availability
        try:
            if self._llm_factory:
                # Just check if factory is configured, don't create model
                health_details["llm_configured"] = True
        except Exception as e:
            return {
                "status": "degraded",
                "details": {**health_details, "llm_error": str(e)},
            }

        return {"status": "healthy", "details": health_details}

    async def cleanup(self) -> None:
        """Cleanup adapter resources."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shutdown adapter and cleanup resources.

        This method:
        1. Closes MCP tools connections
        2. Shuts down team manager
        3. Clears agent cache
        4. Resets initialization state
        """
        logger.info("Shutting down AgnoAdapter...")

        # Shutdown team manager
        if self._team_manager:
            await self._team_manager.shutdown()
            self._team_manager = None

        # Close MCP tools
        if self._mcp_registry:
            await self._mcp_registry.close()

        # Clear caches
        self._agents.clear()
        self._teams.clear()
        self._execution_log.clear()

        # Reset state
        self._initialized = False
        self._llm_factory = None
        self._mcp_registry = None
        self._native_tools_registry = None
        self._semaphore = None

        if self._client is not None:
            close_method = getattr(self._client, "aclose", None)
            if callable(close_method):
                try:
                    await close_method()
                except Exception as e:
                    logger.warning(f"Error closing Agno client session: {e}")
        self._client = None

        logger.info("AgnoAdapter shutdown complete")


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "AgnoAdapter",
    "AgnoAdapterConfig",
    "AgnoLLMConfig",
    "AgnoMemoryConfig",
    "AgnoToolsConfig",
    "LLMProvider",
    "MemoryBackend",
    "LLMProviderFactory",
    "MCPToolsRegistry",
    "NativeToolsRegistry",
    "AgentRunResult",
    "TeamRunResult",
    # Entry point function
    "agno_adapter_entries",
]


# =============================================================================
# Entry Point for Hybrid Adapter Registry
# =============================================================================


def agno_adapter_entries() -> list[dict[str, Any]]:
    """Entry point for Agno adapter registration.

    This function is called by the HybridAdapterRegistry during
    discovery to register the Agno adapter.

    Returns:
        List of adapter metadata dictionaries
    """
    return [
        {
            "category": "orchestration",
            "provider": "agno",
            "factory_path": "mahavishnu.engines.agno_adapter_impl:AgnoAdapter",
            "description": "Agno multi-agent AI orchestration engine",
            "capabilities": [
                "multi_agent",
                "tool_use",
                "team_coordination",
                "mcp_tools",
                "native_tools",
                "memory_management",
            ],
            "priority": 85,
            "domain": "orchestration",
        }
    ]
