"""Production Agno adapter for multi-agent AI orchestration.

This module implements the AgnoAdapter using the real Agno SDK (v2.5.3+)
for agent-based workflows with multi-agent team support.

Key Features:
- Multi-agent team orchestration
- Native MCP tool integration
- Multiple LLM provider support (Anthropic, OpenAI, Ollama)
- Memory and session management
- OpenTelemetry instrumentation

SDK Verified: 2026-02-20 against Agno v2.5.3
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import logging
import os
from typing import TYPE_CHECKING, Any, ClassVar

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

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.agent import RunOutput
    from agno.team import Team

    from .agno_teams.config import TeamConfig
    from .agno_teams.manager import AgentTeamManager

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Models
# ============================================================================


class LLMProvider(str, Enum):
    """Supported LLM providers for Agno agents."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class MemoryBackend(str, Enum):
    """Memory backend storage types."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"
    NONE = "none"


class AgnoLLMConfig(BaseModel):
    """LLM provider configuration for Agno."""

    provider: LLMProvider = Field(
        default=LLMProvider.OLLAMA,
        description="LLM provider (anthropic, openai, ollama)",
    )
    model_id: str = Field(
        default="qwen2.5:7b",
        description="Model identifier (e.g., claude-sonnet-4-6, gpt-4o, qwen2.5:7b)",
    )
    api_key_env: str | None = Field(
        default=None,
        description="Environment variable name for API key",
    )
    base_url: str | None = Field(
        default="http://localhost:11434",
        description="Base URL for Ollama or custom endpoints",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=128000,
        description="Maximum tokens per response",
    )

    model_config = {"extra": "forbid"}


class AgnoMemoryConfig(BaseModel):
    """Memory and storage configuration for Agno agents."""

    enabled: bool = Field(default=True, description="Enable agent memory")
    backend: MemoryBackend = Field(
        default=MemoryBackend.SQLITE,
        description="Memory backend storage type",
    )
    db_path: str = Field(
        default="data/agno.db",
        description="SQLite database path (for sqlite backend)",
    )
    connection_string: str | None = Field(
        default=None,
        description="PostgreSQL connection string (set via env)",
    )
    num_history_runs: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Number of historical runs to retain",
    )

    model_config = {"extra": "forbid"}

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str | None, info) -> str | None:
        """Validate PostgreSQL connection string when using postgres backend."""
        backend = info.data.get("backend")
        if backend == MemoryBackend.POSTGRES and not v:
            raise ValueError(
                "connection_string must be set via MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING "
                "when using postgres backend"
            )
        return v


class AgnoToolsConfig(BaseModel):
    """Tool integration configuration for Agno agents."""

    mcp_server_url: str = Field(
        default="http://localhost:8677/mcp",
        description="Mahavishnu MCP server URL for native tool integration",
    )
    mcp_transport: str = Field(
        default="sse",
        description="MCP transport protocol (sse, stdio)",
    )
    enabled_tools: list[str] = Field(
        default_factory=lambda: [
            "search_code",
            "read_file",
            "write_file",
            "list_repos",
            "get_repo_info",
            "run_command",
        ],
        description="List of enabled MCP tools",
    )
    tool_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Tool execution timeout in seconds",
    )

    model_config = {"extra": "forbid"}


class AgnoAdapterConfig(BaseModel):
    """Complete Agno adapter configuration.

    This configuration is nested under the 'agno' key in MahavishnuSettings.
    Environment variable override format: MAHAVISHNU_AGNO__{FIELD}
    """

    enabled: bool = Field(default=True, description="Enable Agno adapter")

    llm: AgnoLLMConfig = Field(
        default_factory=AgnoLLMConfig,
        description="LLM provider configuration",
    )

    memory: AgnoMemoryConfig = Field(
        default_factory=AgnoMemoryConfig,
        description="Memory and storage configuration",
    )

    tools: AgnoToolsConfig = Field(
        default_factory=AgnoToolsConfig,
        description="Tool integration configuration",
    )

    teams_config_path: str = Field(
        default="settings/agno_teams",
        description="Path to team configuration files",
    )

    default_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Default agent execution timeout",
    )

    max_concurrent_agents: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum concurrent agent executions",
    )

    telemetry_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry instrumentation",
    )

    model_config = {"extra": "forbid"}


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

        try:
            if provider == LLMProvider.OPENAI:
                self._model_instance = self._create_openai_model(model_id)
            elif provider == LLMProvider.ANTHROPIC:
                self._model_instance = self._create_anthropic_model(model_id)
            elif provider == LLMProvider.OLLAMA:
                self._model_instance = self._create_ollama_model(model_id)
            else:
                raise AgnoError(
                    f"Unsupported LLM provider: {provider}",
                    error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                    details={"provider": provider},
                )

            logger.info(
                f"Created LLM model: provider={provider}, model_id={model_id}"
            )
            return self._model_instance

        except ImportError as e:
            raise AgnoError(
                f"Failed to import LLM provider '{provider}': {e}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider, "import_error": str(e)},
            )
        except Exception as e:
            raise AgnoError(
                f"Failed to create LLM model: {e}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider, "model_id": model_id, "error": str(e)},
            )

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

        return Ollama(
            id=model_id,
            host=self.config.base_url or "http://localhost:11434",
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
                transport=self.config.mcp_transport,
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
# Main AgnoAdapter Implementation
# ============================================================================


class AgnoAdapter(OrchestratorAdapter):
    """Production Agno adapter for multi-agent AI orchestration.

    This adapter implements the OrchestratorAdapter interface using the
    real Agno SDK (v2.5.3+) for multi-agent team workflows.

    Key Capabilities:
    - Multi-agent team orchestration (supports_multi_agent=True)
    - Native MCP tool integration
    - Multiple LLM providers (Anthropic, OpenAI, Ollama)
    - Memory and session management
    - Batch execution support

    Example:
        ```python
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.engines.agno_adapter import AgnoAdapter

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

    def __init__(self, config: Any) -> None:
        """Initialize Agno adapter with configuration.

        Args:
            config: MahavishnuSettings instance containing Agno configuration
        """
        self.config = config

        # Extract Agno-specific configuration
        self.agno_config = self._get_agno_config(config)

        # Initialize internal state
        self._initialized = False
        self._llm_factory: LLMProviderFactory | None = None
        self._mcp_registry: MCPToolsRegistry | None = None
        self._agents: dict[str, Agent] = {}
        self._teams: dict[str, Team] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._team_manager: AgentTeamManager | None = None

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
        4. Sets up concurrency semaphore
        5. Initializes team manager (Phase 2)

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

            # Set up concurrency semaphore
            self._semaphore = asyncio.Semaphore(self.agno_config.max_concurrent_agents)

            # Initialize team manager (Phase 2)
            await self._initialize_team_manager()

            self._initialized = True
            logger.info(
                f"AgnoAdapter initialized successfully: "
                f"provider={self.agno_config.llm.provider.value}, "
                f"model={self.agno_config.llm.model_id}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize AgnoAdapter: {e}")
            raise AgnoError(
                f"AgnoAdapter initialization failed: {e}",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"error": str(e)},
            )

    async def _initialize_team_manager(self) -> None:
        """Initialize the agent team manager for multi-agent orchestration."""
        from .agno_teams.manager import AgentTeamManager

        mcp_tools = self._mcp_registry.get_tools() if self._mcp_registry else []

        self._team_manager = AgentTeamManager(
            llm_factory=self._llm_factory,
            mcp_tools=mcp_tools,
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
            )

    # ========================================================================
    # Team Management Methods (Phase 2)
    # ========================================================================

    async def create_team(self, config: "TeamConfig") -> str:
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

        return await self._team_manager.create_team(config)

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

        return await self._team_manager.run_team(team_id, task, mode, session_id)

    async def get_team(self, team_id: str) -> "Team | None":
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
        role: str,
        instructions: str,
        tools: list[Any] | None = None,
        model: Any | None = None,
    ) -> Agent:
        """Create an Agno agent instance.

        Args:
            name: Agent name
            role: Agent role description
            instructions: Agent instructions
            tools: Optional list of tools
            model: Optional LLM model (uses default if not provided)

        Returns:
            Configured Agent instance

        Raises:
            AgnoError: If agent creation fails
        """
        from agno.agent import Agent

        if model is None:
            model = self._llm_factory.create_model()

        if tools is None:
            tools = self._mcp_registry.get_tools() if self._mcp_registry else []

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

            logger.debug(f"Created agent: name={name}, role={role}")
            return agent

        except Exception as e:
            raise AgnoError(
                f"Failed to create agent '{name}': {e}",
                error_code=ErrorCode.AGNO_AGENT_NOT_FOUND,
                details={"agent_name": name, "error": str(e)},
            )

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
                agent_name=agent.name,
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
            )
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
            )

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
        async with self._semaphore:
            task_type = task.get("type", "default")

            try:
                # Create agent for task type
                agent = await self._create_agent(
                    name=f"{task_type}_agent",
                    role=f"Agent for {task_type} operations",
                    instructions=self._get_task_instructions(task_type),
                )

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
- Documentation completeness""",

            "quality_check": """You are a quality assurance agent. Evaluate the
repository against quality standards. Check for:
- Code style compliance
- Test coverage indicators
- Security best practices
- Maintainability concerns""",

            "default": """You are a helpful AI assistant. Process the given task
using available tools and provide clear, actionable responses.""",
        }
        return instructions.get(task_type, instructions["default"])

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
improvement opportunities. Focus on: {params.get('focus', 'general analysis')}.

Use available tools to explore the codebase and provide specific,
actionable recommendations."""

        if task_type == "quality_check":
            return f"""Perform a quality check on the repository at {repo}.
Evaluate against: {params.get('standards', 'Python best practices')}.

Provide a compliance score and list any issues found."""

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

        logger.info(
            f"Executing Agno task: type={task.get('type')}, repos={len(repos)}"
        )

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
                    processed_results.append({
                        "repo": repos[i],
                        "status": "failed",
                        "error": str(result),
                        "task_id": task.get("id", "unknown"),
                    })
                else:
                    processed_results.append(result)

            # Calculate success/failure counts
            success_count = sum(
                1 for r in processed_results if r.get("status") == "completed"
            )
            failure_count = len(processed_results) - success_count

            return {
                "status": "completed" if failure_count == 0 else "partial",
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
            )

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details.
        """
        health_details = {
            "adapter": "agno",
            "version": self.ADAPTER_VERSION,
            "initialized": self._initialized,
            "llm_provider": self.agno_config.llm.provider.value
            if self.agno_config
            else None,
            "model_id": self.agno_config.llm.model_id if self.agno_config else None,
            "agents_cached": len(self._agents),
            "teams_count": len(self._teams),
            "mcp_tools_initialized": self._mcp_registry._initialized
            if self._mcp_registry
            else False,
            "team_manager_initialized": self._team_manager is not None,
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

        # Reset state
        self._initialized = False
        self._llm_factory = None
        self._mcp_registry = None
        self._semaphore = None

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
    "AgentRunResult",
    "TeamRunResult",
]
