"""Pydantic-AI adapter for structured AI agent orchestration.

Implements OrchestratorAdapter interface for Pydantic-AI integration,
providing type-safe agent execution with structured outputs, native MCP
tool integration, and fallback model support.

Pydantic-AI: https://ai.pydantic.dev/
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import Enum
import logging
import re
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from oneiric.core.ulid import generate_config_id
except ImportError:

    def generate_config_id() -> str:
        import uuid

        return uuid.uuid4().hex


from mahavishnu.core.adapters.base import (
    AdapterCapabilities,
    AdapterType,
    OrchestratorAdapter,
)
from mahavishnu.core.errors import (
    AdapterInitializationError,
    ErrorCode,
    MahavishnuError,
)

# Type variables for structured output
OutputT = TypeVar("OutputT", bound=BaseModel)

logger = logging.getLogger(__name__)

# Type variables for structured output
OutputT = TypeVar("OutputT", bound=BaseModel)

# Constants
MAX_AGENTS = 100
MAX_PROMPT_LENGTH = 100000
MCP_SHUTDOWN_TIMEOUT = 10


class AgentStatus(str, Enum):
    """Agent execution status."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FallbackStrategy(str, Enum):
    """Fallback model strategy."""

    DISABLED = "disabled"  # No fallback
    SEQUENTIAL = "sequential"  # Try next model on failure
    PARALLEL = "parallel"  # Race multiple models (not yet implemented)


class ModelConfig(BaseModel):
    """Configuration for an LLM model.

    Uses Pydantic BaseModel for validation and safe serialization.
    API keys are protected from accidental logging.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="LLM provider (openai, anthropic, ollama, etc.)")
    model_name: str = Field(description="Model identifier (gpt-4, claude-sonnet-4-5, etc.)")
    api_key: str | None = Field(default=None, description="API key (use env var instead)")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int = Field(default=4096, ge=1, le=128000, description="Max output tokens")
    timeout: int = Field(default=300, ge=10, le=3600, description="Request timeout in seconds")

    def to_model_string(self) -> str:
        """Convert to Pydantic-AI model string format."""
        provider_prefixes = {
            "openai": "openai",
            "anthropic": "anthropic",
            "ollama": "ollama",
            "google": "google",
            "groq": "groq",
            "litellm": "litellm",
        }
        prefix = provider_prefixes.get(self.provider, self.provider)
        return f"{prefix}:{self.model_name}"

    def safe_string(self) -> str:
        """Return safe string for logging (no secrets)."""
        return f"{self.provider}:{self.model_name}"

    def __repr__(self) -> str:
        """Safe representation that hides API key."""
        api_key_display = "***" if self.api_key else "None"
        return (
            f"ModelConfig(provider={self.provider!r}, model_name={self.model_name!r}, "
            f"api_key={api_key_display}, temperature={self.temperature}, "
            f"max_tokens={self.max_tokens}, timeout={self.timeout})"
        )


class MCPToolConfig(BaseModel):
    """Configuration for an MCP tool integration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Tool name for reference")
    command: str = Field(description="Command to execute")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables (may contain secrets)",
    )
    enabled: bool = Field(default=True, description="Whether tool is enabled")

    def __repr__(self) -> str:
        """Safe representation that hides env secrets."""
        env_display = f"{{{len(self.env)} vars}}" if self.env else "{}"
        return (
            f"MCPToolConfig(name={self.name!r}, command={self.command!r}, "
            f"args={self.args!r}, env={env_display}, enabled={self.enabled})"
        )


class AgentResult(BaseModel):
    """Standard result from Pydantic-AI agent execution."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(description="ULID execution identifier")
    status: AgentStatus = Field(description="Execution status")
    output: str | None = Field(default=None, description="Agent output text")
    structured_output: dict[str, Any] | None = Field(
        default=None, description="Structured Pydantic model output"
    )
    model_used: str = Field(description="Model that produced the output")
    tokens_used: int | None = Field(default=None, description="Total tokens consumed")
    latency_ms: int = Field(default=0, description="Execution latency in milliseconds")
    error: str | None = Field(default=None, description="Error message if failed")
    fallback_triggered: bool = Field(
        default=False, description="Whether fallback model was used"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Execution timestamp",
    )


class PydanticAISettings(BaseModel):
    """Settings for Pydantic-AI adapter."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable Pydantic-AI adapter")
    primary_model: ModelConfig | None = Field(
        default=None, description="Primary LLM model configuration"
    )
    fallback_models: list[ModelConfig] = Field(
        default_factory=list, description="Fallback model configurations"
    )
    fallback_strategy: FallbackStrategy = Field(
        default=FallbackStrategy.SEQUENTIAL, description="Fallback strategy"
    )
    mcp_tools: list[MCPToolConfig] = Field(
        default_factory=list, description="MCP tool configurations"
    )
    max_concurrent_agents: int = Field(
        default=5, ge=1, le=50, description="Maximum concurrent agent executions"
    )
    default_timeout: int = Field(
        default=300, ge=30, le=3600, description="Default execution timeout"
    )
    enable_structured_output: bool = Field(
        default=True, description="Enable structured Pydantic output"
    )
    enable_streaming: bool = Field(
        default=False, description="Enable streaming responses (not yet implemented)"
    )

    @field_validator("fallback_strategy")
    @classmethod
    def validate_fallback_strategy(cls, v: FallbackStrategy) -> FallbackStrategy:
        """Warn if PARALLEL strategy selected (not yet implemented)."""
        if v == FallbackStrategy.PARALLEL:
            logger.warning(
                "PARALLEL fallback strategy not yet implemented, falling back to SEQUENTIAL"
            )
            return FallbackStrategy.SEQUENTIAL
        return v


class PydanticAIAdapterError(MahavishnuError):
    """Pydantic-AI adapter specific errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, code, recovery=None, details=details)

    @property
    def code(self) -> ErrorCode:
        """Alias for error_code for test compatibility."""
        return self.error_code


class PydanticAIAdapter(OrchestratorAdapter, Generic[OutputT]):
    """Pydantic-AI orchestration adapter.

    Provides type-safe agent execution with:
    - Structured outputs via Pydantic models
    - Native MCP tool integration
    - Fallback model support with configurable strategies
    - Agent chaining and hand-off patterns
    - Thread-safe initialization and execution

    Architecture:
    ┌──────────────────────────────────┐
    │   Mahavishnu                     │
    │  • Agent Manager                 │
    │  • Fallback Coordinator          │
    │  • MCP Tool Registry             │
    └──────────────┬───────────────────┘
                   │
                   ↓
         ┌──────────────────────┐
         │   Pydantic-AI        │
         │  • Agent Execution   │
         │  • Structured Output │
         │  • Tool Calling      │
         │  • Model Fallbacks   │
         └──────────────────────┘
                   │
                   ↓
        ┌────────────────────┐
        │   LLM Providers    │
        │  • OpenAI          │
        │  • Anthropic       │
        │  • Ollama          │
        │  • LiteLLM         │
        └────────────────────┘

    Example:
        >>> from mahavishnu.adapters.ai.pydantic_ai_adapter import (
        ...     PydanticAIAdapter, PydanticAISettings, ModelConfig
        ... )
        >>> from pydantic import BaseModel
        >>>
        >>> class TaskResult(BaseModel):
        ...     summary: str
        ...     confidence: float
        >>>
        >>> settings = PydanticAISettings(
        ...     primary_model=ModelConfig(provider="openai", model_name="gpt-4"),
        ...     fallback_models=[
        ...         ModelConfig(provider="anthropic", model_name="claude-sonnet-4-5")
        ...     ]
        ... )
        >>> adapter = PydanticAIAdapter[TaskResult](settings)
        >>> await adapter.initialize()
        >>> result = await adapter.execute(
        ...     task={"prompt": "Analyze this code", "context": "..."},
        ...     repos=["/path/to/repo"]
        ... )
    """

    def __init__(
        self,
        settings: PydanticAISettings | None = None,
        output_type: type[OutputT] | None = None,
    ):
        """Initialize Pydantic-AI adapter.

        Args:
            settings: Adapter configuration (uses defaults if None)
            output_type: Optional Pydantic model for structured output
        """
        self.settings = settings or PydanticAISettings()
        self.output_type = output_type
        self._agents: dict[str, Any] = {}  # Agent cache
        self._mcp_servers: dict[str, Any] = {}  # MCP server instances
        self._failed_mcp_servers: list[str] = []  # Track failed MCP initializations
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_agents)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._pydantic_ai_available = False

        # Check if pydantic-ai is available
        try:
            import pydantic_ai  # noqa: F401

            self._pydantic_ai_available = True
        except ImportError:
            logger.warning(
                "pydantic-ai not installed. Install with: pip install pydantic-ai"
            )
            self._pydantic_ai_available = False

        primary_model_str = (
            self.settings.primary_model.safe_string()
            if self.settings.primary_model
            else "None"
        )
        logger.info(
            "PydanticAIAdapter created (available=%s, primary_model=%s)",
            self._pydantic_ai_available,
            primary_model_str,
        )

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.PYDANTIC_AI

    @property
    def name(self) -> str:
        return "pydantic_ai"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return supported capabilities.

        Note: can_cancel_workflows is False until cancellation is implemented.
        """
        return AdapterCapabilities(
            can_deploy_flows=True,  # Can create agents
            can_monitor_execution=True,  # Execution tracking
            can_cancel_workflows=False,  # Not yet implemented
            can_sync_state=True,  # State management via RunContext
            supports_batch_execution=True,  # Multiple agent executions
            supports_multi_agent=True,  # Agent chaining/hand-offs
            has_cloud_ui=False,  # No cloud UI
        )

    async def _ensure_initialized(self) -> None:
        """Ensure adapter is initialized before operations.

        Raises:
            PydanticAIAdapterError: If adapter not initialized
        """
        async with self._init_lock:
            if not self._initialized:
                raise PydanticAIAdapterError(
                    "PydanticAIAdapter not initialized. Call initialize() first.",
                    code=ErrorCode.CONFIGURATION_ERROR,
                )

    async def _ensure_pydantic_ai_available(self) -> None:
        """Ensure pydantic-ai package is available.

        Raises:
            PydanticAIAdapterError: If pydantic-ai not installed
        """
        if not self._pydantic_ai_available:
            raise PydanticAIAdapterError(
                "pydantic-ai package not installed. Install with: pip install pydantic-ai",
                code=ErrorCode.CONFIGURATION_ERROR,
            )

    def _validate_task_input(self, task: dict[str, Any]) -> str:
        """Validate task input parameters.

        Args:
            task: Task specification to validate

        Returns:
            Validated prompt string

        Raises:
            PydanticAIAdapterError: If validation fails
        """
        prompt = task.get("prompt", "")

        if not prompt or not prompt.strip():
            raise PydanticAIAdapterError(
                "Task prompt cannot be empty",
                code=ErrorCode.VALIDATION_ERROR,
                details={"field": "prompt"},
            )

        if len(prompt) > MAX_PROMPT_LENGTH:
            raise PydanticAIAdapterError(
                f"Prompt exceeds maximum length ({MAX_PROMPT_LENGTH} chars)",
                code=ErrorCode.VALIDATION_ERROR,
                details={"max_length": MAX_PROMPT_LENGTH, "actual_length": len(prompt)},
            )

        return prompt

    def _sanitize_error_message(self, error: Exception) -> str:
        """Sanitize error message for safe external consumption.

        Removes potentially sensitive information like file paths.

        Args:
            error: Exception to sanitize

        Returns:
            Sanitized error message
        """
        msg = str(error)
        # Remove absolute file paths
        msg = re.sub(r"/[\w/.-]+", "[PATH]", msg)
        # Truncate long messages
        return msg[:500] if len(msg) > 500 else msg

    async def initialize(self) -> None:
        """Initialize Pydantic-AI adapter.

        Sets up:
        - Primary and fallback model clients
        - MCP tool servers
        - Agent registry

        Raises:
            AdapterInitializationError: If initialization fails
        """
        async with self._init_lock:
            if self._initialized:
                logger.warning("PydanticAIAdapter already initialized")
                return

            if not self._pydantic_ai_available:
                raise AdapterInitializationError(
                    adapter_name="pydantic_ai",
                    message="pydantic-ai package not installed. "
                    "Install with: pip install pydantic-ai",
                )

            try:
                # Initialize MCP servers if configured
                await self._initialize_mcp_servers()

                # Validate model configurations
                if self.settings.primary_model:
                    await self._validate_model_config(self.settings.primary_model)

                for model in self.settings.fallback_models:
                    await self._validate_model_config(model)

                self._initialized = True
                logger.info("PydanticAIAdapter initialized successfully")

            except AdapterInitializationError:
                raise
            except Exception as e:
                # Cleanup any partially initialized resources
                await self._cleanup_mcp_servers()
                raise AdapterInitializationError(
                    adapter_name="pydantic_ai",
                    message=f"Failed to initialize PydanticAIAdapter: {e}",
                ) from e

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> dict[str, Any]:
        """Execute an agent task.

        Args:
            task: Task specification with keys:
                - prompt: str - User prompt/instruction (required)
                - system_prompt: str | None - System instructions
                - context: dict | None - Additional context
                - output_type: type[BaseModel] | None - Override output type
                - tools: list[str] | None - Tool names to enable
                - model: str | None - Override model
            repos: List of repository paths (passed as context)

        Returns:
            Execution result with AgentResult structure

        Raises:
            PydanticAIAdapterError: If not initialized or validation fails
        """
        await self._ensure_initialized()

        # Validate input
        self._validate_task_input(task)

        async with self._semaphore:
            execution_id = generate_config_id()
            start_time = datetime.now(UTC)

            try:
                result = await self._execute_with_fallback(
                    execution_id=execution_id,
                    task=task,
                    repos=repos,
                )

                latency_ms = int(
                    (datetime.now(UTC) - start_time).total_seconds() * 1000
                )
                result.latency_ms = latency_ms

                return result.model_dump()

            except PydanticAIAdapterError:
                raise
            except Exception as e:
                logger.error("Agent execution failed: %s", self._sanitize_error_message(e))
                return AgentResult(
                    execution_id=execution_id,
                    status=AgentStatus.FAILED,
                    output=None,
                    model_used=self.settings.primary_model.safe_string()
                    if self.settings.primary_model
                    else "unknown",
                    error=self._sanitize_error_message(e),
                ).model_dump()

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key and health details
        """
        if not self._pydantic_ai_available:
            return {
                "status": "unhealthy",
                "details": {
                    "reason": "pydantic-ai package not installed",
                    "install_command": "pip install pydantic-ai",
                },
            }

        async with self._init_lock:
            if not self._initialized:
                return {
                    "status": "degraded",
                    "details": {
                        "reason": "Adapter not initialized",
                        "action": "Call initialize() before use",
                    },
                }

        health_details = {
            "primary_model": self.settings.primary_model.safe_string()
            if self.settings.primary_model
            else None,
            "fallback_models": len(self.settings.fallback_models),
            "mcp_tools": len(self.settings.mcp_tools),
            "mcp_servers_active": len(self._mcp_servers),
            "mcp_servers_failed": len(self._failed_mcp_servers),
            "agents_cached": len(self._agents),
            "max_concurrent_agents": self.settings.max_concurrent_agents,
            "structured_output_enabled": self.settings.enable_structured_output,
        }

        # Check primary model health
        model_healthy = self.settings.primary_model is not None

        # Determine overall status
        if not model_healthy or self._failed_mcp_servers:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "details": health_details,
        }

    async def create_agent(
        self,
        name: str,
        instructions: str,
        output_type: type[BaseModel] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
    ) -> str:
        """Create a named agent with configuration.

        Args:
            name: Agent name for reference
            instructions: System instructions for the agent
            output_type: Optional Pydantic model for structured output
            tools: List of tool names to enable
            model: Override model string

        Returns:
            Agent ID (ULID)

        Raises:
            PydanticAIAdapterError: If not initialized, rate limit exceeded, or creation fails
        """
        await self._ensure_initialized()
        await self._ensure_pydantic_ai_available()

        # Rate limiting
        if len(self._agents) >= MAX_AGENTS:
            raise PydanticAIAdapterError(
                f"Maximum agent limit ({MAX_AGENTS}) reached",
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                details={"max_agents": MAX_AGENTS, "current_count": len(self._agents)},
            )

        from pydantic_ai import Agent

        agent_id = generate_config_id()
        model_str = model or (
            self.settings.primary_model.to_model_string()
            if self.settings.primary_model
            else "openai:gpt-4"
        )

        # Build tool list
        agent_tools = []
        if tools:
            for tool_name in tools:
                if tool_name in self._mcp_servers:
                    agent_tools.append(self._mcp_servers[tool_name])

        try:
            agent = Agent(
                model=model_str,
                system_prompt=instructions,
                output_type=output_type or self.output_type,
                toolsets=agent_tools if agent_tools else None,
            )

            self._agents[agent_id] = {
                "name": name,
                "agent": agent,
                "instructions": instructions,
                "output_type": output_type,
                "model": model_str,
                "created_at": datetime.now(UTC).isoformat(),
            }

            logger.info("Created agent '%s' with ID: %s", name, agent_id)
            return agent_id

        except Exception as e:
            raise PydanticAIAdapterError(
                f"Failed to create agent: {self._sanitize_error_message(e)}",
                code=ErrorCode.INTERNAL_ERROR,
            ) from e

    async def execute_agent(
        self,
        agent_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a pre-configured agent.

        Args:
            agent_id: Agent ID from create_agent()
            prompt: User prompt
            context: Optional execution context (reserved for future use)

        Returns:
            AgentResult with execution details

        Raises:
            PydanticAIAdapterError: If agent not found or execution fails
        """
        await self._ensure_initialized()

        if agent_id not in self._agents:
            raise PydanticAIAdapterError(
                f"Agent not found: {agent_id}",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                details={"agent_id": agent_id, "available_agents": list(self._agents.keys())},
            )

        # Validate prompt
        if not prompt or not prompt.strip():
            raise PydanticAIAdapterError(
                "Prompt cannot be empty",
                code=ErrorCode.VALIDATION_ERROR,
            )

        execution_id = generate_config_id()
        start_time = datetime.now(UTC)
        agent_info = self._agents[agent_id]
        agent = agent_info["agent"]

        async with self._semaphore:
            try:
                # Execute agent
                result = await agent.run(prompt)

                latency_ms = int(
                    (datetime.now(UTC) - start_time).total_seconds() * 1000
                )

                # Extract output
                output = result.output
                structured_output = None

                if isinstance(output, BaseModel):
                    structured_output = output.model_dump()
                    output_str = str(output)
                else:
                    output_str = str(output)

                return AgentResult(
                    execution_id=execution_id,
                    status=AgentStatus.COMPLETED,
                    output=output_str,
                    structured_output=structured_output,
                    model_used=agent_info["model"],
                    latency_ms=latency_ms,
                    tokens_used=getattr(result, "usage", {}).get("total_tokens"),
                )

            except Exception as e:
                logger.error("Agent execution failed: %s", self._sanitize_error_message(e))
                return AgentResult(
                    execution_id=execution_id,
                    status=AgentStatus.FAILED,
                    model_used=agent_info["model"],
                    error=self._sanitize_error_message(e),
                )

    async def chain_agents(
        self,
        agent_ids: list[str],
        initial_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> list[AgentResult]:
        """Chain multiple agents in sequence.

        Each agent receives the output of the previous agent.

        Args:
            agent_ids: List of agent IDs to chain
            initial_prompt: Starting prompt
            context: Optional shared context (reserved for future use)

        Returns:
            List of AgentResult for each agent

        Raises:
            PydanticAIAdapterError: If validation fails
        """
        await self._ensure_initialized()

        if not agent_ids:
            raise PydanticAIAdapterError(
                "Agent IDs list cannot be empty",
                code=ErrorCode.VALIDATION_ERROR,
            )

        if not initial_prompt or not initial_prompt.strip():
            raise PydanticAIAdapterError(
                "Initial prompt cannot be empty",
                code=ErrorCode.VALIDATION_ERROR,
            )

        results = []
        current_prompt = initial_prompt

        for agent_id in agent_ids:
            result = await self.execute_agent(
                agent_id=agent_id,
                prompt=current_prompt,
                context=context,
            )
            results.append(result)

            if result.status == AgentStatus.FAILED:
                logger.warning(
                    "Agent chain stopped at %s: %s",
                    agent_id,
                    result.error,
                )
                break

            # Pass output to next agent
            current_prompt = result.output or ""

        return results

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all cached agents.

        Returns:
            List of agent metadata dictionaries
        """
        await self._ensure_initialized()

        return [
            {
                "agent_id": agent_id,
                "name": info["name"],
                "model": info["model"],
                "created_at": info["created_at"],
                "has_output_type": info["output_type"] is not None,
            }
            for agent_id, info in self._agents.items()
        ]

    async def shutdown(self) -> None:
        """Shutdown adapter and cleanup resources.

        Closes MCP servers with timeout protection and clears agent cache.
        """
        async with self._init_lock:
            await self._cleanup_mcp_servers()

            self._agents.clear()
            self._initialized = False

            logger.info("PydanticAIAdapter shut down")

    async def _cleanup_mcp_servers(self) -> None:
        """Cleanup MCP servers with timeout protection."""
        failed_servers = []

        for name, server in list(self._mcp_servers.items()):
            try:
                async with asyncio.timeout(MCP_SHUTDOWN_TIMEOUT):
                    if hasattr(server, "close"):
                        await server.close()
                    elif hasattr(server, "cleanup"):
                        await server.cleanup()
                logger.info("Closed MCP server: %s", name)
            except TimeoutError:
                logger.error("MCP server %s cleanup timed out", name)
                failed_servers.append(name)
            except Exception as e:
                logger.warning("Error closing MCP server %s: %s", name, e)
                failed_servers.append(name)

        if failed_servers:
            logger.warning("Servers with cleanup issues: %s", failed_servers)

        self._mcp_servers.clear()
        self._failed_mcp_servers.clear()

    # Private methods

    async def _initialize_mcp_servers(self) -> None:
        """Initialize configured MCP tool servers."""
        if not self.settings.mcp_tools:
            return

        from pydantic_ai.mcp import MCPServerStdio

        for tool_config in self.settings.mcp_tools:
            if not tool_config.enabled:
                continue

            try:
                server = MCPServerStdio(
                    command=tool_config.command,
                    args=tool_config.args,
                    env=tool_config.env if tool_config.env else None,
                )

                self._mcp_servers[tool_config.name] = server
                logger.info("Initialized MCP server: %s", tool_config.name)

            except Exception as e:
                logger.warning(
                    "Failed to initialize MCP server %s: %s",
                    tool_config.name,
                    self._sanitize_error_message(e),
                )
                self._failed_mcp_servers.append(tool_config.name)

    async def _validate_model_config(self, config: ModelConfig) -> bool:
        """Validate model configuration.

        Args:
            config: Model configuration to validate

        Returns:
            True if valid

        Raises:
            AdapterInitializationError: If configuration is invalid
        """
        # Check for required API keys based on provider
        if config.provider in ("openai", "anthropic", "google"):
            import os

            key_env = f"{config.provider.upper()}_API_KEY"
            if not config.api_key and not os.getenv(key_env):
                logger.warning(
                    "No API key configured for %s. Set %s environment variable.",
                    config.provider,
                    key_env,
                )

        return True

    async def _execute_with_fallback(
        self,
        execution_id: str,
        task: dict[str, Any],
        repos: list[str],
    ) -> AgentResult:
        """Execute task with fallback model support.

        Args:
            execution_id: Execution identifier
            task: Task specification
            repos: Repository paths

        Returns:
            AgentResult from execution

        Raises:
            PydanticAIAdapterError: If no models configured
        """
        from pydantic_ai import Agent

        # Build model list based on fallback strategy
        models = []
        if self.settings.primary_model:
            models.append(self.settings.primary_model)

        if self.settings.fallback_strategy != FallbackStrategy.DISABLED:
            models.extend(self.settings.fallback_models)

        if not models:
            raise PydanticAIAdapterError(
                "No models configured",
                code=ErrorCode.CONFIGURATION_ERROR,
            )

        # Get task configuration
        prompt = task.get("prompt", "")
        system_prompt = task.get("system_prompt")
        output_type = task.get("output_type", self.output_type)
        tool_names = task.get("tools", [])

        # Build tool list
        tools = []
        for tool_name in tool_names:
            if tool_name in self._mcp_servers:
                tools.append(self._mcp_servers[tool_name])

        last_error: Exception | None = None

        for i, model_config in enumerate(models):
            try:
                agent = Agent(
                    model=model_config.to_model_string(),
                    system_prompt=system_prompt,
                    output_type=output_type,
                    toolsets=tools if tools else None,
                )

                # Build context with repos
                full_prompt = prompt
                if repos:
                    repo_context = f"\n\nWorking directories: {', '.join(repos)}"
                    full_prompt = f"{prompt}{repo_context}"

                result = await agent.run(full_prompt)

                # Extract output
                output = result.output
                structured_output = None

                if isinstance(output, BaseModel):
                    structured_output = output.model_dump()
                    output_str = str(output)
                else:
                    output_str = str(output)

                return AgentResult(
                    execution_id=execution_id,
                    status=AgentStatus.COMPLETED,
                    output=output_str,
                    structured_output=structured_output,
                    model_used=model_config.safe_string(),
                    fallback_triggered=i > 0,
                    tokens_used=getattr(result, "usage", {}).get(
                        "total_tokens"
                    ),
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    "Model %s failed: %s",
                    model_config.safe_string(),
                    self._sanitize_error_message(e),
                )

                # If not the last model, continue to fallback
                if i < len(models) - 1:
                    continue

        # All models failed
        error_msg = self._sanitize_error_message(last_error) if last_error else "Unknown error"
        return AgentResult(
            execution_id=execution_id,
            status=AgentStatus.FAILED,
            model_used=models[0].safe_string() if models else "unknown",
            error=error_msg,
        )


__all__ = [
    "AgentResult",
    "AgentStatus",
    "FallbackStrategy",
    "MCPToolConfig",
    "ModelConfig",
    "PydanticAIAdapter",
    "PydanticAIAdapterError",
    "PydanticAISettings",
]
