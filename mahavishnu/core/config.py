"""Core configuration module for Mahavishnu using Oneiric patterns.

This module provides type-safe configuration management using Pydantic models,
following Oneiric's configuration loading patterns with layered configuration
support (defaults -> committed YAML -> local YAML -> environment variables).

Architecture:
    - Nested Pydantic models group related configuration
    - Each config group is a separate BaseModel with `extra = "forbid"`
    - Environment variables use MAHAVISHNU_{GROUP}__{FIELD} format
    - YAML files use nested structure matching the model hierarchy
"""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

from ..terminal.config import TerminalSettings

# ============================================================================
# Agno Adapter Configuration (Phase 1)
# ============================================================================


class LLMProvider(str, Enum):
    """Supported LLM providers for Agno agents."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class MemoryBackend(str, Enum):
    """Memory backend storage types for Agno agents."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"
    NONE = "none"


class AgnoLLMConfig(BaseModel):
    """LLM provider configuration for Agno agents.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under agno.llm
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_AGNO__LLM__PROVIDER, etc.

    Example YAML:
        agno:
          llm:
            provider: ollama
            model_id: qwen2.5:7b
            base_url: http://localhost:11434
            temperature: 0.7
    """

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
    """Memory and storage configuration for Agno agents.

    Memory allows agents to retain context across conversations.

    Example YAML:
        agno:
          memory:
            enabled: true
            backend: sqlite
            db_path: data/agno.db
            num_history_runs: 10
    """

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
    """Tool integration configuration for Agno agents.

    Tools allow agents to interact with external systems via MCP.

    Example YAML:
        agno:
          tools:
            mcp_server_url: http://localhost:8677/mcp
            mcp_transport: sse
            enabled_tools:
              - search_code
              - read_file
              - write_file
    """

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

    Agno provides multi-agent AI orchestration capabilities.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under agno:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_AGNO__ENABLED, etc.

    Example YAML:
        agno:
          enabled: true
          llm:
            provider: ollama
            model_id: qwen2.5:7b
          memory:
            enabled: true
            backend: sqlite
          tools:
            mcp_server_url: http://localhost:8677/mcp
          default_timeout_seconds: 300
          max_concurrent_agents: 5

    Example Environment Variables:
        MAHAVISHNU_AGNO__ENABLED=true
        MAHAVISHNU_AGNO__LLM__PROVIDER=anthropic
        MAHAVISHNU_AGNO__LLM__MODEL_ID=claude-sonnet-4-6
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
# Existing Configuration Classes
# ============================================================================


class PrefectConfig(BaseModel):
    """Prefect adapter configuration for workflow orchestration.

    Configuration can be set via:
    1. settings/mahavishnu.yaml (committed)
    2. settings/local.yaml (gitignored, local dev)
    3. Environment variables: MAHAVISHNU_PREFECT__API_URL, etc.

    Example YAML:
        prefect:
          enabled: true
          api_url: "http://localhost:4200"
          work_pool: "default"
          timeout_seconds: 300

    Example Environment Variables:
        MAHAVISHNU_PREFECT__API_URL="http://localhost:4200"
        MAHAVISHNU_PREFECT__API_KEY="pnu_xxxxxxxxxxxxx"
    """

    enabled: bool = Field(
        default=True,
        description="Enable Prefect adapter for workflow orchestration",
    )
    api_url: str = Field(
        default="http://localhost:4200",
        description="Prefect API URL (Server or Cloud)",
    )
    api_key: str | None = Field(
        default=None,
        description="Prefect API key (required for Prefect Cloud)",
    )
    workspace: str | None = Field(
        default=None,
        description="Prefect Cloud workspace (format: account/workspace)",
    )
    work_pool: str = Field(
        default="default",
        description="Default work pool for flow execution",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Default timeout for API operations (10-3600)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed operations",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Base delay between retries (exponential backoff)",
    )
    enable_telemetry: bool = Field(
        default=True,
        description="Enable OpenTelemetry instrumentation",
    )
    sync_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Interval for state synchronization (10-600)",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Secret for validating Prefect webhooks",
    )

    @model_validator(mode="after")
    def validate_cloud_config(self) -> "PrefectConfig":
        """Validate configuration for Prefect Cloud.

        Ensures API key is provided when workspace is specified,
        as Prefect Cloud requires authentication.

        Returns:
            Validated PrefectConfig instance

        Raises:
            ValueError: If workspace is set but api_key is missing
        """
        if self.workspace and not self.api_key:
            raise ValueError(
                "api_key must be set when workspace is specified. "
                "Set via MAHAVISHNU_PREFECT__API_KEY environment variable."
            )
        return self

    model_config = {"extra": "forbid"}


class PoolConfig(BaseModel):
    """Pool management configuration for multi-pool orchestration."""

    enabled: bool = Field(
        default=True,
        description="Enable pool management for multi-pool orchestration",
    )
    default_type: str = Field(
        default="mahavishnu",
        description="Default pool type (mahavishnu, session-buddy, kubernetes)",
    )
    routing_strategy: str = Field(
        default="least_loaded",
        description="Pool selection strategy (round_robin, least_loaded, random, affinity)",
    )
    min_workers: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Default minimum workers per pool",
    )
    max_workers: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Default maximum workers per pool",
    )
    memory_aggregation_enabled: bool = Field(
        default=True,
        description="Enable memory aggregation across pools",
    )
    memory_sync_interval: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Memory sync interval in seconds (10-600)",
    )
    session_buddy_url: str = Field(
        default="http://localhost:8678/mcp",
        description="Session-Buddy MCP server URL for delegated pools",
    )
    akosha_url: str = Field(
        default="http://localhost:8682/mcp",
        description="Akosha MCP server URL for cross-pool analytics",
    )

    model_config = {"extra": "forbid"}


class OTelStorageConfig(BaseModel):
    """OpenTelemetry trace storage with PostgreSQL + pgvector."""

    enabled: bool = Field(
        default=False,
        description="Enable OTel trace storage with PostgreSQL + pgvector",
    )
    connection_string: str = Field(
        default="",
        description="PostgreSQL connection string for OTel trace storage (required if enabled, set via MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING)",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence transformer model for semantic search",
    )
    embedding_dimension: int = Field(
        default=384,
        ge=128,
        le=1024,
        description="Vector dimension for embeddings (128-1024)",
    )
    cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum number of embeddings to cache in memory",
    )
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for semantic search (0.0-1.0)",
    )
    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of traces to batch in single write operation",
    )
    batch_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Seconds between batch flushes",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed operations",
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=3,
        le=20,
        description="Failures before circuit breaker opens",
    )

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str, info) -> str:
        """Validate OTel storage connection string for security and format.

        SECURITY CHECKS:
        - Requires non-empty connection string when enabled=True
        - Rejects default credentials (e.g., "password@", "postgres:postgres@")
        - Validates postgresql:// or postgres:// scheme

        Args:
            v: Connection string value
            info: Field validation info

        Returns:
            Validated connection string

        Raises:
            ValueError: If validation fails
        """
        storage_enabled = info.data.get("enabled", False)

        # Require connection string when storage is enabled
        if storage_enabled and not v:
            raise ValueError(
                "connection_string must be set via MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING "
                "environment variable when enabled is true"
            )

        # Allow empty when disabled
        if not v:
            return v

        # Check for default/insecure credentials
        insecure_patterns = [
            "password@",  # Default password
            "postgres:postgres@",  # Username=password
            "postgres:password@",  # Explicit default
            "admin:admin@",  # Another common default
            "root:root@",  # Common default
            "test:test@",  # Test credentials
        ]

        v_lower = v.lower()
        for pattern in insecure_patterns:
            if pattern in v_lower:
                raise ValueError(
                    f"connection_string contains insecure default credentials: '{pattern}'. "
                    f"Please use a strong, unique password. Set via MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING "
                    f"environment variable."
                )

        # Validate connection string format
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                f"connection_string must use postgresql:// or postgres:// scheme. Got: {v[:30]}..."
            )

        # Basic structure validation (scheme://user:pass@host:port/db)
        if v.count("@") < 1:
            raise ValueError(
                "connection_string missing '@' separator. "
                "Expected format: postgresql://user:password@host:port/database"
            )

        if v.count("/") < 3:  # postgresql:// is 2 slashes, need at least one more for database
            raise ValueError(
                "connection_string missing database name. "
                "Expected format: postgresql://user:password@host:port/database"
            )

        return v

    model_config = {"extra": "forbid"}


class OTelIngesterConfig(BaseModel):
    """OpenTelemetry trace ingester using Akosha HotStore (DuckDB)."""

    enabled: bool = Field(
        default=False,
        description="Enable OTel trace ingester with Akosha HotStore (DuckDB)",
    )
    hot_store_path: str = Field(
        default=":memory:",
        description="DuckDB database path for OTel ingester (':memory:' for in-memory)",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence transformer model for OTel ingester embeddings",
    )
    cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum number of embeddings to cache in memory",
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for semantic search",
    )

    model_config = {"extra": "forbid"}


class OpenSearchConfig(BaseModel):
    """OpenSearch configuration for vector storage and observability."""

    endpoint: str = Field(
        default="https://localhost:9200",
        description="OpenSearch endpoint for vector storage and observability",
    )
    index_name: str = Field(
        default="mahavishnu_code",
        description="OpenSearch index name for code vectors",
    )
    verify_certs: bool = Field(
        default=True,
        description="Verify SSL certificates for OpenSearch connection",
    )
    ca_certs: str | None = Field(
        default=None,
        description="Path to CA certificate file for OpenSearch",
    )
    use_ssl: bool = Field(
        default=True,
        description="Use SSL for OpenSearch connection",
    )
    ssl_assert_hostname: bool = Field(
        default=True,
        description="Assert hostname for OpenSearch SSL connection",
    )
    ssl_show_warn: bool = Field(
        default=True,
        description="Show SSL warnings for OpenSearch connection",
    )

    model_config = {"extra": "forbid"}


class AuthConfig(BaseModel):
    """Authentication configuration for JWT tokens."""

    enabled: bool = Field(
        default=False,
        description="Enable JWT authentication",
    )
    secret: str | None = Field(
        default=None,
        description="JWT secret (must be set via environment if auth enabled)",
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT algorithm (HS256 or RS256)",
    )
    expire_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="JWT token expiration in minutes (5-1440)",
    )

    @model_validator(mode="after")
    def validate_secret(self) -> "AuthConfig":
        """Validate auth secret is set if auth is enabled."""
        if self.enabled and not self.secret:
            raise ValueError(
                "secret must be set via MAHAVISHNU_AUTH__SECRET "
                "environment variable when enabled is true"
            )
        return self

    model_config = {"extra": "forbid"}


class SubscriptionAuthConfig(BaseModel):
    """Subscription-based authentication configuration (e.g., Claude Code)."""

    enabled: bool = Field(
        default=False,
        description="Enable subscription-based authentication",
    )
    secret: str | None = Field(
        default=None,
        description="Subscription auth secret (must be set via environment if enabled)",
    )
    algorithm: str = Field(
        default="HS256",
        description="Subscription auth algorithm (HS256 or RS256)",
    )
    expire_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Subscription token expiration in minutes (5-1440)",
    )

    @model_validator(mode="after")
    def validate_secret(self) -> "SubscriptionAuthConfig":
        """Validate subscription auth secret is set if enabled."""
        if self.enabled and not self.secret:
            raise ValueError(
                "secret must be set via MAHAVISHNU_SUBSCRIPTION_AUTH__SECRET "
                "environment variable when enabled is true"
            )
        return self

    model_config = {"extra": "forbid"}


class SessionBuddyPollingConfig(BaseModel):
    """Session-Buddy telemetry polling configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable Session-Buddy telemetry polling",
    )
    endpoint: str = Field(
        default="http://localhost:8678/mcp",
        description="Session-Buddy MCP server URL for polling",
    )
    interval_seconds: int = Field(
        default=30,
        ge=5,
        le=600,
        description="Polling interval in seconds (5-600)",
    )
    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="HTTP timeout for MCP calls in seconds (1-60)",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed MCP calls (1-10)",
    )
    retry_delay_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Base retry delay in seconds (1-60)",
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Consecutive failures before circuit breaker opens (1-20)",
    )
    metrics_to_collect: list[str] = Field(
        default_factory=lambda: [
            "get_activity_summary",
            "get_workflow_metrics",
            "get_session_analytics",
            "get_performance_metrics",
        ],
        description="List of MCP tools to poll for metrics",
    )

    model_config = {"extra": "forbid"}


class QualityControlConfig(BaseModel):
    """Quality control configuration for Crackerjack QC."""

    enabled: bool = Field(
        default=True,
        description="Enable Crackerjack QC",
    )
    min_score: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Minimum QC score threshold (0-100)",
    )
    checks: list[str] = Field(
        default_factory=lambda: ["linting", "type_checking", "security_scan"],
        description="List of QC checks to perform",
    )

    model_config = {"extra": "forbid"}


class SessionConfig(BaseModel):
    """Session management configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable Session-Buddy checkpoints",
    )
    checkpoint_interval: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Checkpoint interval in seconds (10-600)",
    )

    model_config = {"extra": "forbid"}


class ResilienceConfig(BaseModel):
    """Resilience configuration for retries and circuit breakers."""

    retry_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts (1-10)",
    )
    retry_base_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Base retry delay in seconds (0.1-60)",
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Consecutive failures before circuit opens (1-100)",
    )
    timeout_per_repo: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Timeout per repo in seconds (30-3600)",
    )

    model_config = {"extra": "forbid"}


class ObservabilityConfig(BaseModel):
    """Observability configuration for metrics and tracing."""

    metrics_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry metrics",
    )
    tracing_enabled: bool = Field(
        default=True,
        description="Enable distributed tracing",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP endpoint for metrics/traces",
    )

    model_config = {"extra": "forbid"}


class WorkerConfig(BaseModel):
    """Worker orchestration configuration for headless AI execution."""

    enabled: bool = Field(
        default=True,
        description="Enable worker orchestration for headless AI execution",
    )
    max_concurrent: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of concurrent workers (1-100)",
    )
    default_type: str = Field(
        default="terminal-qwen",
        description="Default worker type (terminal-qwen, terminal-claude, container-executor)",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Default worker timeout in seconds (30-3600)",
    )
    session_buddy_integration: bool = Field(
        default=True,
        description="Enable Session-Buddy result storage for workers",
    )

    model_config = {"extra": "forbid"}


class AdapterConfig(BaseModel):
    """Orchestration adapter configuration."""

    prefect_enabled: bool = Field(
        default=True,
        description="Enable Prefect adapter for high-level orchestration",
    )
    llamaindex_enabled: bool = Field(
        default=True,
        description="Enable LlamaIndex adapter for RAG and knowledge bases",
    )
    agno_enabled: bool = Field(
        default=True,
        description="Enable Agno adapter for agent-based workflows",
    )

    model_config = {"extra": "forbid"}


class LLMConfig(BaseModel):
    """LLM configuration for LlamaIndex and Agno."""

    model: str = Field(
        default="nomic-embed-text",
        description="LLM model name for Ollama (e.g., nomic-embed-text, llama2)",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API endpoint for local LLM access",
    )

    model_config = {"extra": "forbid"}


class OneiricMCPConfig(BaseModel):
    """Oneiric MCP integration configuration for adapter discovery."""

    enabled: bool = Field(
        default=False,
        description="Enable Oneiric MCP integration for dynamic adapter discovery",
    )
    grpc_host: str = Field(
        default="localhost",
        description="Oneiric MCP gRPC server host",
    )
    grpc_port: int = Field(
        default=8679,
        ge=1,
        le=65535,
        description="Oneiric MCP gRPC server port (8679 for insecure dev, 8680 for TLS)",
    )
    use_tls: bool = Field(
        default=False,
        description="Use TLS/mTLS for gRPC connection (production mode)",
    )
    timeout_sec: int = Field(
        default=30,
        ge=5,
        le=120,
        description="gRPC request timeout in seconds (5-120)",
    )
    cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Adapter list cache TTL in seconds (0 to disable, default: 300)",
    )
    jwt_enabled: bool = Field(
        default=False,
        description="Enable JWT authentication for Oneiric MCP (production mode)",
    )
    jwt_secret: str | None = Field(
        default=None,
        description="JWT secret key for Oneiric MCP authentication (set via MAHAVISHNU_ONEIRIC_MCP__JWT_SECRET)",
    )
    jwt_project: str = Field(
        default="mahavishnu",
        description="Project name for JWT token scoping",
    )
    tls_cert_path: str | None = Field(
        default=None,
        description="Path to TLS client certificate (required for TLS/mTLS)",
    )
    tls_key_path: str | None = Field(
        default=None,
        description="Path to TLS client private key (required for TLS/mTLS)",
    )
    tls_ca_path: str | None = Field(
        default=None,
        description="Path to TLS CA certificate (required for mTLS)",
    )
    circuit_breaker_threshold: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Adapter failures before circuit breaker opens (1-10)",
    )
    circuit_breaker_duration_sec: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Seconds to block adapter after circuit breaker opens (60-3600)",
    )

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str | None, info) -> str | None:
        """Validate JWT secret configuration.

        Args:
            v: JWT secret value
            info: Field validation info

        Returns:
            Validated JWT secret

        Raises:
            ValueError: If JWT enabled but secret not provided
        """
        jwt_enabled = info.data.get("jwt_enabled", False)

        if jwt_enabled and not v:
            raise ValueError(
                "jwt_secret must be set via MAHAVISHNU_ONEIRIC_MCP__JWT_SECRET "
                "environment variable when jwt_enabled is true"
            )

        return v

    @field_validator("use_tls")
    @classmethod
    def validate_tls_config(cls, v: bool, info) -> bool:
        """Validate TLS configuration.

        Args:
            v: use_tls value
            info: Field validation info

        Returns:
            Validated use_tls value

        Raises:
            ValueError: If TLS enabled but certificates not configured
        """
        if v:
            cert_path = info.data.get("tls_cert_path")
            key_path = info.data.get("tls_key_path")

            if not cert_path or not key_path:
                raise ValueError(
                    "tls_cert_path and tls_key_path must be provided when use_tls is true. "
                    "Set via MAHAVISHNU_ONEIRIC_MCP__TLS_CERT_PATH and "
                    "MAHAVISHNU_ONEIRIC_MCP__TLS_KEY_PATH environment variables."
                )

        return v

    model_config = {"extra": "forbid"}


# ============================================================================
# Goal-Driven Teams Configuration
# ============================================================================


class FallbackStrategy(str, Enum):
    """Fallback strategy when goal parsing fails."""

    SIMPLE = "simple"  # Use simple keyword extraction
    REJECT = "reject"  # Reject the goal with error
    DEFAULT_TEAM = "default_team"  # Use a default team configuration


class GoalParsingConfig(BaseModel):
    """Goal parsing configuration for Goal-Driven Teams.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under goal_teams.goal_parsing
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__MIN_LENGTH, etc.

    Example YAML:
        goal_teams:
          goal_parsing:
            min_length: 10
            max_length: 2000
            fallback_strategy: simple
    """

    min_length: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Minimum goal length in characters",
    )
    max_length: int = Field(
        default=2000,
        ge=100,
        le=10000,
        description="Maximum goal length in characters",
    )
    fallback_strategy: FallbackStrategy = Field(
        default=FallbackStrategy.SIMPLE,
        description="Fallback strategy when goal parsing fails",
    )

    model_config = {"extra": "forbid"}


class GoalTeamsLimitsConfig(BaseModel):
    """Limits configuration for Goal-Driven Teams.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under goal_teams.limits
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_GOAL_TEAMS__LIMITS__MAX_TEAMS_PER_USER, etc.

    Example YAML:
        goal_teams:
          limits:
            max_teams_per_user: 10
            team_ttl_hours: 24
            max_concurrent_executions: 5
    """

    max_teams_per_user: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum active teams per user",
    )
    team_ttl_hours: int = Field(
        default=24,
        ge=0,
        le=168,
        description="Team time-to-live in hours (0 for no expiry, max 1 week)",
    )
    max_concurrent_executions: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum concurrent team executions",
    )

    model_config = {"extra": "forbid"}


class GoalTeamsConfig(BaseModel):
    """Goal-Driven Teams configuration.

    Goal-Driven Teams allow users to specify natural language goals
    that are automatically parsed and routed to appropriate teams.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under goal_teams:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_GOAL_TEAMS__ENABLED, etc.

    Example YAML:
        goal_teams:
          enabled: true
          goal_parsing:
            min_length: 10
            max_length: 2000
            fallback_strategy: simple
          limits:
            max_teams_per_user: 10
            team_ttl_hours: 24
            max_concurrent_executions: 5

    Example Environment Variables:
        MAHAVISHNU_GOAL_TEAMS__ENABLED=true
        MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__MIN_LENGTH=20
        MAHAVISHNU_GOAL_TEAMS__LIMITS__MAX_TEAMS_PER_USER=20
    """

    enabled: bool = Field(
        default=False,
        description="Enable Goal-Driven Teams feature",
    )

    goal_parsing: GoalParsingConfig = Field(
        default_factory=GoalParsingConfig,
        description="Goal parsing configuration",
    )

    limits: GoalTeamsLimitsConfig = Field(
        default_factory=GoalTeamsLimitsConfig,
        description="Limits and quotas configuration",
    )

    model_config = {"extra": "forbid"}



class MahavishnuSettings(BaseSettings):
    """Mahavishnu configuration extending MCPServerSettings.

    Configuration loading order (later overrides earlier):
    1. Default values (below)
    2. settings/mahavishnu.yaml (committed to git)
    3. settings/local.yaml (gitignored, for development)
    4. Environment variables: MAHAVISHNU_{GROUP}__{FIELD}

    Example YAML (settings/mahavishnu.yaml):
        server_name: "Mahavishnu Orchestrator"
        log_level: INFO
        repos_path: ~/repos.yaml
        pools:
            enabled: true
            default_type: mahavishnu
        otel_storage:
            enabled: true
            connection_string: postgresql://user:pass@host/db
        auth:
            enabled: true
            secret: your-secret-key
        agno:
            enabled: true
            llm:
                provider: ollama
                model_id: qwen2.5:7b

    Example Environment Variables:
        MAHAVISHNU_POOLS__ENABLED=true
        MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING=postgresql://...
        MAHAVISHNU_AUTH__SECRET=your-secret-key
        MAHAVISHNU_AGNO__LLM__PROVIDER=anthropic
    """

    model_config = SettingsConfigDict(
        yaml_files=["settings/mahavishnu.yaml", "settings/local.yaml"],
        env_prefix="MAHAVISHNU_",
        env_nested_delimiter="__",
        extra="allow",
    )

    # ===== Top-Level Configuration =====

    # Application settings
    server_name: str = Field(
        default="Mahavishnu Orchestrator",
        description="Application server name",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Repository configuration
    repos_path: str = Field(
        default="settings/ecosystem.yaml",
        description="Path to ecosystem.yaml configuration file",
    )
    allowed_repo_paths: list[str] = Field(
        default_factory=lambda: ["/Users/les/Projects"],
        description="List of allowed base paths for repositories (for security)",
    )

    # Concurrency configuration
    max_concurrent_workflows: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of concurrent workflows (1-100)",
    )

    # Admin shell
    shell_enabled: bool = Field(
        default=True,
        description="Enable admin shell (mahavishnu shell command)",
    )

    # Cross-project authentication (for Session Buddy integration)
    cross_project_auth_secret: str | None = Field(
        default=None,
        description="Cross-project authentication secret (must be set via environment for Session Buddy integration)",
    )

    # Terminal management (already a nested config from terminal module)
    terminal: TerminalSettings = Field(
        default_factory=TerminalSettings,
        description="Terminal session management settings",
    )

    # ===== Grouped Configuration =====

    # Prefect adapter configuration
    prefect: PrefectConfig = Field(
        default_factory=PrefectConfig,
        description="Prefect adapter configuration",
    )

    # Pool management
    pools: PoolConfig = Field(
        default_factory=PoolConfig,
        description="Pool management configuration",
    )

    # OpenTelemetry storage
    otel_storage: OTelStorageConfig = Field(
        default_factory=OTelStorageConfig,
        description="OpenTelemetry trace storage configuration",
    )

    # OpenTelemetry ingester
    otel_ingester: OTelIngesterConfig = Field(
        default_factory=OTelIngesterConfig,
        description="OpenTelemetry trace ingester configuration",
    )

    # OpenSearch
    opensearch: OpenSearchConfig = Field(
        default_factory=OpenSearchConfig,
        description="OpenSearch configuration",
    )

    # Authentication
    auth: AuthConfig = Field(
        default_factory=AuthConfig,
        description="JWT authentication configuration",
    )

    # Subscription authentication
    subscription_auth: SubscriptionAuthConfig = Field(
        default_factory=SubscriptionAuthConfig,
        description="Subscription-based authentication configuration",
    )

    # Session-Buddy polling
    session_buddy_polling: SessionBuddyPollingConfig = Field(
        default_factory=SessionBuddyPollingConfig,
        description="Session-Buddy telemetry polling configuration",
    )

    # Quality control
    qc: QualityControlConfig = Field(
        default_factory=QualityControlConfig,
        description="Quality control configuration",
    )

    # Session management
    session: SessionConfig = Field(
        default_factory=SessionConfig,
        description="Session management configuration",
    )

    # Resilience
    resilience: ResilienceConfig = Field(
        default_factory=ResilienceConfig,
        description="Resilience configuration",
    )

    # Observability
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig,
        description="Observability configuration",
    )

    # Worker orchestration
    workers: WorkerConfig = Field(
        default_factory=WorkerConfig,
        description="Worker orchestration configuration",
    )

    # Adapters
    adapters: AdapterConfig = Field(
        default_factory=AdapterConfig,
        description="Orchestration adapter configuration",
    )

    # LLM configuration
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM configuration for LlamaIndex and Agno",
    )

    # Agno adapter configuration (Phase 1)
    agno: AgnoAdapterConfig = Field(
        default_factory=AgnoAdapterConfig,
        description="Agno multi-agent adapter configuration",
    )

    # Oneiric MCP integration
    oneiric_mcp: OneiricMCPConfig = Field(
        default_factory=OneiricMCPConfig,
        description="Oneiric MCP integration for dynamic adapter discovery",
    )

    # Goal-Driven Teams configuration
    goal_teams: GoalTeamsConfig = Field(
        default_factory=GoalTeamsConfig,
        description="Goal-Driven Teams configuration",
    )


    @field_validator("repos_path")
    @classmethod
    def validate_repos_path(cls, v: str) -> str:
        """Expand user path (~) in repos_path."""
        return str(Path(v).expanduser())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Customize settings sources to include YAML files."""
        # Add YAML configuration sources
        yaml_sources = []
        for yaml_file in ("settings/mahavishnu.yaml", "settings/local.yaml"):
            yaml_path = Path(yaml_file)
            if yaml_path.exists():
                yaml_sources.append(YamlConfigSettingsSource(settings_cls, yaml_path))

        return (
            init_settings,
            *yaml_sources,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Enums
    "LLMProvider",
    "MemoryBackend",
    "FallbackStrategy",
    # Agno configuration
    "AgnoAdapterConfig",
    "AgnoLLMConfig",
    "AgnoMemoryConfig",
    "AgnoToolsConfig",
    # Other configurations
    "PrefectConfig",
    "PoolConfig",
    "OTelStorageConfig",
    "OTelIngesterConfig",
    "OpenSearchConfig",
    "AuthConfig",
    "SubscriptionAuthConfig",
    "SessionBuddyPollingConfig",
    "QualityControlConfig",
    "SessionConfig",
    "ResilienceConfig",
    "ObservabilityConfig",
    "WorkerConfig",
    "AdapterConfig",
    "LLMConfig",
    "OneiricMCPConfig",
    # Goal-Driven Teams configuration
    "GoalParsingConfig",
    "GoalTeamsLimitsConfig",
    "GoalTeamsConfig",
    "MahavishnuSettings",
]
