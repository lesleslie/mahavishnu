"""Core configuration module for Mahavishnu using Oneiric patterns.

This module provides type-safe configuration management using Pydantic models,
following Oneiric's configuration loading patterns with layered Configuration
support (defaults -> committed YAML -> local YAML -> environment variables).

Architecture:
    - Nested Pydantic models group related configuration
    - Each config group is a separate BaseModel with `extra = "forbid"`
    - Environment variables use MAHAVISHNU_{GROUP}__{FIELD} format
    - YAML files use nested structure matching the model hierarchy
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic._internal._utils import deep_update
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

from ..terminal.config import TerminalSettings

# ============================================================================
# Agno Adapter Configuration (Phase 1)
# ============================================================================


class LLMProvider(StrEnum):
    """Supported LLM providers for Agno agents."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MINIMAX = "minimax"
    OLLAMA = "ollama"


class MemoryBackend(StrEnum):
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
        description="LLM provider (anthropic, openai, minimax, ollama)",
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
        default=MemoryBackend.NONE,
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
    enable_native_tools: bool = Field(
        default=True,
        description="Enable native Agno tools (file operations, code analysis)",
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
    def validate_cloud_config(self) -> PrefectConfig:
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
        description="Default pool type (mahavishnu, session-buddy, runpod)",
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


class HNSWIndexConfig(BaseModel):
    """HNSW index configuration for high-performance vector search.

    HNSW (Hierarchical Navigable Small World) is an approximate nearest
    neighbor search algorithm optimized for high-dimensional vectors.

    Performance Targets:
    - 10K+ queries per second with proper tuning
    - ~10-20ms query latency (vs ~100ms for exact search)

    Configuration can be set via:
    1. settings/mahavishnu.yaml under otel_storage.hnsw
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_OTEL_STORAGE__HNSW__M, etc.

    Example YAML:
        otel_storage:
          enabled: true
          hnsw:
            m: 16
            ef_construction: 64
            ef_search: 40
    """

    m: int = Field(
        default=16,
        ge=4,
        le=48,
        description="Number of bi-directional links per node (4-48, higher = better recall, more memory)",
    )
    ef_construction: int = Field(
        default=64,
        ge=16,
        le=256,
        description="Search depth during index construction (16-256, higher = better index quality, slower build)",
    )
    ef_search: int = Field(
        default=40,
        ge=10,
        le=200,
        description="Search depth during queries (10-200, higher = better recall, slower search)",
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
        default=10000,
        ge=100,
        le=100000,
        description="Maximum number of embeddings to cache in memory (increased from 1000)",
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

    # HNSW index configuration for 10K+ QPS
    hnsw: HNSWIndexConfig = Field(
        default_factory=HNSWIndexConfig,
        description="HNSW index configuration for high-performance vector search",
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
    """OpenTelemetry trace ingester using Akosha HotStore (DuckDB) or pgvector.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under otel_ingester
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE, etc.
    """

    enabled: bool = Field(
        default=False,
        description="Enable OTel trace ingester with Akosha HotStore (DuckDB)",
    )
    hot_store_path: str | None = Field(
        default=None,
        description=(
            "DuckDB database path for OTel ingester. "
            "Uses XDG-compliant path under user data dir by default (~/.local/share/mahavishnu/). "
            "Set ':memory:' for in-memory storage, or an explicit path for a specific location."
        ),
    )
    storage_type: str = Field(
        default="duckdb",
        description=(
            "Storage backend type: 'duckdb' (default, :memory: or file) or 'postgresql' (pgvector). "
            "Set via MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE"
        ),
    )
    storage_pg_url: str = Field(
        default="",
        description=(
            "PostgreSQL connection string for pgvector-backed OTel storage. "
            "Required when storage_type='postgresql'. "
            "Set via MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL"
        ),
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
    turboquant_bits: int | None = Field(
        default=4,
        description=(
            "TurboQuant embedding cache compression bits (3 or 4). "
            "4 gives 8x RAM reduction with 0.978 cosine similarity. "
            "Set to null to disable. Requires turboquant-pro package."
        ),
    )

    @field_validator("turboquant_bits")
    @classmethod
    def _validate_turboquant_bits(cls, v: int | None) -> int | None:
        if v is not None and v not in (3, 4):
            raise ValueError(f"turboquant_bits must be 3 or 4, got {v}")
        return v

    @field_validator("storage_type")
    @classmethod
    def _validate_storage_type(cls, v: str) -> str:
        if v not in ("duckdb", "postgresql"):
            raise ValueError(f"storage_type must be 'duckdb' or 'postgresql', got {v}")
        return v

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


class DLQConfig(BaseModel):
    """Dead Letter Queue configuration.

    Controls fail-closed behavior for the DLQ when OpenSearch is unreachable.
    By default, the DLQ silently falls back to a per-process in-memory queue
    (preserves the original back-compat behavior).
    """

    fail_on_opensearch_unavailable: bool = Field(
        default=False,
        description=(
            "When True, the DLQ raises instead of silently dropping tasks "
            "to in-memory storage when OpenSearch is unreachable. Recommended "
            "for multi-node production deployments."
        ),
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
    def validate_secret(self) -> AuthConfig:
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
    def validate_secret(self) -> SubscriptionAuthConfig:
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
    crackerjack_url: str = Field(
        default="http://localhost:8676/mcp",
        description="Crackerjack MCP server URL",
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


class MonitoringConfig(BaseModel):
    """Monitoring configuration for routing metrics and alerting."""

    routing_metrics_port: int = Field(
        default=9091,
        ge=1024,
        le=65535,
        description="Deprecated dedicated routing metrics port kept for compatibility during migration",
    )
    routing_metrics_enabled: bool = Field(
        default=True,
        description="Enable routing metrics registration on the shared /metrics endpoint",
    )

    model_config = {"extra": "forbid"}


# ============================================================================
# A2A (Agent-to-Agent) Protocol Configuration
# ============================================================================


class A2ACapabilitiesSettings(BaseModel):
    """Capabilities advertised in our outbound A2A agent card."""

    model_config = {"extra": "forbid"}

    streaming: bool = True
    pushNotifications: bool = False  # noqa: N815


class A2ACardSettings(BaseModel):
    """Fields used to build the /.well-known/agent.json response."""

    model_config = {"extra": "forbid"}

    name: str = "Mahavishnu"
    description: str = "Bodai ecosystem orchestrator"
    version: str = ""  # empty → _get_version() consulted at request time
    capabilities: A2ACapabilitiesSettings = A2ACapabilitiesSettings()
    skills: list[dict[str, str]] = []

    @field_validator("skills")
    @classmethod
    def _validate_skills(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        required = {"id", "name", "description"}
        for i, skill in enumerate(v):
            missing = required - set(skill.keys())
            if missing:
                raise ValueError(f"skill[{i}] missing required keys: {missing}")
        return v


class A2AAgentEntry(BaseModel):
    """One entry in the outbound agent registry (from settings/mahavishnu.yaml)."""

    model_config = {"extra": "forbid"}

    name: str
    url: str
    description: str = ""
    api_key_env: str | None = None  # env var name; resolved to actual value at runtime

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, v: str) -> str:
        from urllib.parse import urlparse

        scheme = urlparse(v).scheme
        if scheme not in ("http", "https"):
            raise ValueError(f"A2A agent URL must use http or https, got scheme {scheme!r}")
        return v


class A2ASettings(BaseModel):
    """Top-level A2A configuration block."""

    model_config = {"extra": "forbid"}

    enabled: bool = False
    require_auth: bool = Field(
        default=True,
        description=(
            "Require Bearer token on /tasks/send and /tasks/sendSubscribe. "
            "Token is sourced from auth.secret. Set False only for trusted-network deployments."
        ),
    )
    task_timeout_seconds: float = Field(
        default=600.0,
        ge=5.0,
        le=3600.0,
        description="Maximum seconds to wait for execute_fn on /tasks/sendSubscribe before timing out.",
    )
    card: A2ACardSettings = A2ACardSettings()
    agents: list[A2AAgentEntry] = []


class OpenHandsSettings(BaseModel):
    """Configuration for the OpenHands autonomous agent integration."""

    base_url: str = "http://localhost:3000"
    workspace_dir: Path = Path("/tmp/openhands-workspace")  # noqa: S108
    workspace_root: Path = Path("/tmp")  # noqa: S108
    timeout_seconds: int = Field(600, ge=30, le=3600)
    poll_interval_seconds: float = Field(3.0, ge=0.5, le=30.0)
    enabled: bool = True

    @field_validator("workspace_dir", "workspace_root")
    @classmethod
    def _validate_path_is_absolute(cls, v: Path) -> Path:
        return Path(v).resolve()

    @model_validator(mode="after")
    def _workspace_dir_inside_root(self) -> OpenHandsSettings:
        if not self.workspace_dir.is_relative_to(self.workspace_root):
            raise ValueError(
                f"workspace_dir ({self.workspace_dir}) must be "
                f"inside workspace_root ({self.workspace_root})"
            )
        return self


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
        default="terminal-claude",
        description="Default worker type (terminal-claude, terminal-qwen [legacy], terminal-codex, container-executor)",
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
    hatchet_enabled: bool = Field(
        default=False,
        description="Enable Hatchet adapter for durable event-driven agent loops",
    )

    model_config = {"extra": "forbid"}


class HatchetConfig(BaseModel):
    """Hatchet workflow engine configuration.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under hatchet:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_HATCHET__SERVER_URL, etc.

    Example YAML:
        hatchet:
          server_url: "localhost:7077"
          namespace: "mahavishnu"
          max_runs: 10
          poll_interval_seconds: 2.0
          task_timeout_seconds: 300
    """

    server_url: str = Field(
        default="localhost:7077",
        description="Hatchet gRPC server address (host:port)",
    )
    namespace: str = Field(
        default="mahavishnu",
        description="Hatchet namespace for workflow isolation",
    )
    max_runs: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent Hatchet workflow runs",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=60.0,
        description="Polling interval when waiting for run completion",
    )
    task_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Maximum seconds to wait for a single Hatchet task",
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


class AdapterRegistryConfig(BaseModel):
    """Adapter registry configuration for security and discovery control.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under adapter_registry:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_ADAPTER_REGISTRY__ENABLED, etc.

    Example YAML:
        adapter_registry:
          enabled: true
          allowlist_patterns:
            - "mahavishnu.adapters.*"
            - "mahavishnu.engines.*"
          verify_signatures: false
          reject_unsigned: false
    """

    enabled: bool = Field(
        default=True,
        description="Enable hybrid adapter registry with Oneiric discovery",
    )
    allowlist_patterns: list[str] = Field(
        default_factory=lambda: [
            "mahavishnu.adapters.*",
            "mahavishnu.engines.*",
        ],
        description="Allowed adapter module patterns (security filter)",
    )
    verify_signatures: bool = Field(
        default=False,
        description="Verify adapter signatures (future security feature)",
    )
    reject_unsigned: bool = Field(
        default=False,
        description="Reject unsigned adapters in production mode",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Adapter metadata cache TTL (0 to disable)",
    )
    discovery_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout for adapter discovery operations",
    )

    model_config = {"extra": "forbid"}


class OneiricMCPConfig(BaseModel):
    """Dhara adapter registry integration configuration.

    The old Oneiric MCP gRPC registry was absorbed into Dhara's canonical
    FastMCP adapter-registry tools. The class name is retained for settings
    compatibility with existing ``oneiric_mcp`` config blocks.
    """

    enabled: bool = Field(
        default=False,
        description="Enable Dhara adapter registry discovery",
    )
    base_url: str = Field(
        default="http://localhost:8683/mcp",
        description="Dhara MCP base URL for adapter registry tools",
    )
    timeout_sec: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Dhara MCP request timeout in seconds (5-120)",
    )
    cache_ttl_sec: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Adapter list cache TTL in seconds (0 to disable, default: 300)",
    )
    token: str | None = Field(
        default=None,
        description="Optional bearer token for Dhara MCP when authentication is enabled",
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

    model_config = {"extra": "forbid"}


# ============================================================================
# Goal-Driven Teams Configuration
# ============================================================================


class FallbackStrategy(StrEnum):
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


class EventBridgeConfig(BaseModel):
    """Operator toggle for the Oneiric EventBridge publisher.

    The publisher module (``mahavishnu.core.events.mahavishnu_publisher``)
    accepts an injected ``publisher``. This settings class controls
    whether a publisher is constructed at app startup and wired into
    the WebSocketServer's ``_event_publisher`` slot.

    Mirrors ``akosha.config.EventBridgeConfig`` and
    ``crackerjack.config.EventBridgeSettings``. Defaults are conservative
    (enabled=False, dry_run=True) so existing installs see no behavior
    change until operators opt in.

    Production wiring is opt-in: the publisher is constructed only when
    ``enabled=True``. With ``dry_run=True``, the envelope is logged but
    not transmitted; set ``dry_run=False`` to actually emit events.
    """

    enabled: bool = Field(
        default=False,
        description="Master toggle for the Mahavishnu-side EventBridge publisher.",
    )
    endpoint: str = Field(
        default="",
        description=(
            "Optional: external EventBridge ingestion URL. Empty means use "
            "the in-process Oneiric EventBridge default transport."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "When True, envelopes are logged but not transmitted. Operators "
            "must explicitly set dry_run=False to actually emit events."
        ),
    )


class GoalTeamsFeatureFlags(BaseModel):
    """Feature flags for Goal-Driven Teams.

    These flags control access to various Goal-Driven Teams features
    and can be configured via settings/mahavishnu.yaml.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under goal_teams.feature_flags
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED, etc.

    Example YAML:
        goal_teams:
          enabled: true  # Master switch
          feature_flags:
            mcp_tools_enabled: true
            cli_commands_enabled: true
            llm_fallback_enabled: true
            websocket_broadcasts_enabled: true
            prometheus_metrics_enabled: true
            learning_system_enabled: false
            auto_mode_selection_enabled: true
            custom_skills_enabled: false
    """

    # Core feature flags
    mcp_tools_enabled: bool = Field(
        default=True,
        description="Enable MCP tools for goal-driven teams",
    )
    cli_commands_enabled: bool = Field(
        default=True,
        description="Enable CLI commands for goal-driven teams",
    )

    # Advanced feature flags
    llm_fallback_enabled: bool = Field(
        default=True,
        description="Enable LLM fallback for goal parsing when pattern matching fails",
    )
    websocket_broadcasts_enabled: bool = Field(
        default=True,
        description="Enable WebSocket broadcasts for team events",
    )
    eventbridge: EventBridgeConfig = Field(
        default_factory=EventBridgeConfig,
        description=(
            "Oneiric EventBridge publisher settings. When enabled=True "
            "and dry_run=False, an EventBridgePublisher is constructed "
            "at app startup and wired into the workflow broadcast path."
        ),
    )
    prometheus_metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics for team monitoring",
    )

    # Experimental features
    learning_system_enabled: bool = Field(
        default=False,
        description="Enable learning system (Phase 3 feature)",
    )
    auto_mode_selection_enabled: bool = Field(
        default=True,
        description="Enable automatic mode selection based on goal analysis",
    )
    custom_skills_enabled: bool = Field(
        default=False,
        description="Enable custom skills for team creation",
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
          feature_flags:
            mcp_tools_enabled: true
            cli_commands_enabled: true
            llm_fallback_enabled: true

    Example Environment Variables:
        MAHAVISHNU_GOAL_TEAMS__ENABLED=true
        MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__MIN_LENGTH=20
        MAHAVISHNU_GOAL_TEAMS__LIMITS__MAX_TEAMS_PER_USER=20
        MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED=true
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

    feature_flags: GoalTeamsFeatureFlags = Field(
        default_factory=GoalTeamsFeatureFlags,
        description="Feature flags for controlling access to Goal-Driven Teams features",
    )

    model_config = {"extra": "forbid"}


# ============================================================================
# Learning Pipeline Configuration (Phase 1B)
# ============================================================================


class LearningConfig(BaseModel):
    """Review-gated learning pipeline configuration.

    Controls the observe→store→retrieve→synthesize→review→activate pipeline
    that enables Mahavishnu to learn from successful task executions.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under learning:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_LEARNING__ENABLED, etc.

    Example YAML:
        learning:
          enabled: true
          collection_interval_seconds: 300
          max_evidence_per_cycle: 50
          synthesis_min_evidence: 5
          retention_days: 90
    """

    enabled: bool = Field(
        default=False,
        description="Enable the review-gated learning pipeline",
    )
    collection_interval_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Seconds between evidence collection cycles (60-3600)",
    )
    max_evidence_per_cycle: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum evidence items collected per cycle (rate limiting)",
    )
    synthesis_min_evidence: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Minimum evidence count before attempting skill synthesis",
    )
    retention_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Days to retain raw evidence before cleanup (1-365)",
    )
    max_drafts_per_cycle: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum skill drafts synthesized per cycle",
    )
    store_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Timeout for Session-Buddy evidence storage calls",
    )
    retrieve_timeout_seconds: int = Field(
        default=15,
        ge=1,
        le=60,
        description="Timeout for Akosha evidence retrieval calls",
    )

    model_config = {"extra": "forbid"}


# ============================================================================
# Health Check Configuration
# ============================================================================


class DependencyConfig(BaseModel):
    """Configuration for a service dependency.

    Dependencies are checked on startup using health endpoints.
    The system uses exponential backoff for retries.

    Example YAML:
        dependencies:
          session_buddy:
            host: "localhost"
            port: 8678
            required: true
            timeout_seconds: 30
          dhara:
            host: "localhost"
            port: 8683
            required: false
            timeout_seconds: 10

    Example Environment Variables:
        MAHAVISHNU_HEALTH__DEPENDENCIES__SESSION_BUDDY__HOST=localhost
        MAHAVISHNU_HEALTH__DEPENDENCIES__SESSION_BUDDY__PORT=8678
    """

    host: str = Field(
        default="localhost",
        description="Hostname or IP address of the dependency",
    )
    port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Port number for the health endpoint",
    )
    required: bool = Field(
        default=True,
        description="Whether startup should fail if this dependency is unavailable",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Maximum time to wait for this dependency (1-300 seconds)",
    )
    use_tls: bool = Field(
        default=False,
        description="Use HTTPS for health checks",
    )

    model_config = {"extra": "forbid"}


class HealthConfig(BaseModel):
    """Health check system configuration.

    Provides configuration for health endpoints and dependency waiting.

    Example YAML:
        health:
          enabled: true
          check_timeout_seconds: 5
          retry_base_delay_seconds: 1.0
          retry_max_delay_seconds: 16.0
          dependencies:
            session_buddy:
              host: "localhost"
              port: 8678
              required: true
            akosha:
              host: "localhost"
              port: 8682
              required: false
            dhara:
              host: "localhost"
              port: 8683
              required: false

    Example Environment Variables:
        MAHAVISHNU_HEALTH__ENABLED=true
        MAHAVISHNU_HEALTH__CHECK_TIMEOUT_SECONDS=5
    """

    enabled: bool = Field(
        default=True,
        description="Enable health check system",
    )
    check_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Timeout for individual health check requests (1-60 seconds)",
    )
    retry_base_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Base delay for exponential backoff retries",
    )
    retry_max_delay_seconds: float = Field(
        default=16.0,
        ge=1.0,
        le=60.0,
        description="Maximum delay between retries",
    )
    dependencies: dict[str, DependencyConfig] = Field(
        default_factory=dict,
        description="Service dependencies to check on startup",
    )

    model_config = {"extra": "forbid"}


class DharaStatePersistenceConfig(BaseModel):
    """Configuration for Dhara-backed durable state persistence.

    Controls whether workflow lifecycle events, pool state, and routing
    decisions are persisted to Dhara for recovery after restart.

    Example YAML:
        dhara_state:
          enabled: true
          flush_interval_seconds: 60
          max_routing_buffer_age_seconds: 3600

    Example Environment Variables:
        MAHAVISHNU_DHARA_STATE__ENABLED=true
        MAHAVISHNU_DHARA_STATE__FLUSH_INTERVAL_SECONDS=30
    """

    enabled: bool = Field(
        default=True,
        description="Enable Dhara state persistence (no-op if Dhara is unreachable)",
    )
    flush_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Interval between periodic routing buffer flushes to Dhara",
    )
    max_routing_buffer_age_seconds: int = Field(
        default=3600,
        ge=60,
        description="Maximum age of routing decisions retained in Dhara",
    )

    model_config = {"extra": "forbid"}


class IntegrationConfig(BaseModel):
    """Feature flags for external platform integrations.

    These flags control whether specific integration features are enabled,
    allowing for safe rollout and easy rollback without code changes.

    Example YAML:
        integrations:
          pydantic_ai_enabled: true
          openclaw_webhooks_enabled: true
          omo_enabled: false
          cross_platform_memory_enabled: true

    Example Environment Variables:
        MAHAVISHNU_INTEGRATIONS__PYDANTIC_AI_ENABLED=true
        MAHAVISHNU_INTEGRATIONS__OPENCLAW_WEBHOOKS_ENABLED=false

    Created: 2026-04-02
    Related: docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P1-8)
    """

    pydantic_ai_enabled: bool = Field(
        default=False,
        description="Enable Pydantic AI integration for structured agent outputs",
    )
    openclaw_webhooks_enabled: bool = Field(
        default=True,
        description="Enable OpenClaw webhook endpoints for external triggers",
    )
    omo_enabled: bool = Field(
        default=False,
        description="Enable OMO (Orchestration Multi-Objective) integration",
    )
    cross_platform_memory_enabled: bool = Field(
        default=True,
        description="Enable cross-platform memory sharing via Session-Buddy/Akosha",
    )

    model_config = {"extra": "forbid"}


class DistillSettings(BaseModel):
    """Distilled Workflows pipeline configuration (Plan 5).

    Plan 5 audit H4 introduced a source provenance gate that runs
    before the synthesizer. The gate requires a configured
    MAHAVISHNU_PUBLISHER_ALLOWLIST so the distiller can reject
    sessions whose originating run record is either external or
    unattributed. Without this configuration the distiller falls
    back to bootstrap mode (warn + audit; allow any reviewer
    identity on a trusted-source record).

    Attributes:
        publisher_allowlist: Path to a newline-delimited allowlist
            file, OR an inline comma-separated list. Read at distiller
            invocation time. None triggers bootstrap mode.
        evidence_threshold: Minimum tool-call count to admit a
            candidate session.
        require_reviewer: When True (default), a session without a
            reviewer identity is rejected regardless of bootstrap mode.
            Production deployments should leave this on.

    Example YAML (settings/mahavishnu.yaml):

        distill:
            publisher_allowlist: settings/distill_publishers.txt
            evidence_threshold: 3
            require_reviewer: true

    Example Environment Variables:

        MAHAVISHNU_DISTILL__PUBLISHER_ALLOWLIST=/etc/mahavishnu/publishers.txt
        MAHAVISHNU_DISTILL__EVIDENCE_THRESHOLD=5
        MAHAVISHNU_DISTILL__REQUIRE_REVIEWER=true

    The ``MAHAVISHNU_PUBLISHER_ALLOWLIST`` environment variable is
    also accepted directly (read by ``ReviewerIdentity.from_env`` in
    ``mahavishnu.distill.reviewer``). When both are configured the
    env var wins; the YAML entry is a convenience for ops.
    """

    publisher_allowlist: str | None = Field(
        default=None,
        description=(
            "Path to a newline-delimited allowlist file, OR an inline "
            "comma-separated list. None triggers bootstrap mode (any "
            "reviewer identity on a trusted-source record is accepted, "
            "with a WARNING + audit log entry)."
        ),
    )
    evidence_threshold: int = Field(
        default=3,
        ge=1,
        description="Minimum tool-call count to admit a candidate session.",
    )
    require_reviewer: bool = Field(
        default=True,
        description=(
            "When True (default), a session without a reviewer identity "
            "is rejected regardless of bootstrap mode. Production "
            "deployments should leave this on."
        ),
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
        repos_path: settings/ecosystem.yaml
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
        yaml_file=["settings/mahavishnu.yaml", "settings/local.yaml"],
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
    eventbridge: EventBridgeConfig = Field(
        default_factory=EventBridgeConfig,
        description=(
            "Oneiric EventBridge publisher settings. When enabled=True "
            "and dry_run=False, an EventBridgePublisher is constructed "
            "at app startup and wired into the workflow broadcast path."
        ),
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

    # OpenHands autonomous agent integration (optional)
    openhands: OpenHandsSettings | None = None

    # A2A (Agent-to-Agent) protocol configuration (optional)
    a2a: A2ASettings | None = None

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

    # Dead Letter Queue
    dlq: DLQConfig = Field(
        default_factory=DLQConfig,
        description="Dead Letter Queue configuration",
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

    # Distilled Workflows (Plan 5)
    distill: DistillSettings = Field(
        default_factory=DistillSettings,
        description=(
            "Distilled Workflows pipeline configuration (Plan 5). "
            "Controls the H4 source provenance gate (publisher "
            "allowlist) and the H6 reviewer identity gate."
        ),
    )

    # Observability
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig,
        description="Observability configuration",
    )

    # Monitoring (routing metrics, alerting)
    monitoring: MonitoringConfig = Field(
        default_factory=MonitoringConfig,
        description="Monitoring configuration for routing metrics and alerting",
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

    # Hatchet workflow engine configuration (P10)
    hatchet: HatchetConfig = Field(
        default_factory=HatchetConfig,
        description="Hatchet workflow engine configuration",
    )

    # Dhara adapter registry integration (legacy oneiric_mcp settings key)
    oneiric_mcp: OneiricMCPConfig = Field(
        default_factory=OneiricMCPConfig,
        description="Dhara adapter registry integration for dynamic adapter discovery",
    )

    # Adapter registry configuration
    adapter_registry: AdapterRegistryConfig = Field(
        default_factory=AdapterRegistryConfig,
        description="Hybrid adapter registry configuration",
    )

    # Goal-Driven Teams configuration
    goal_teams: GoalTeamsConfig = Field(
        default_factory=GoalTeamsConfig,
        description="Goal-Driven Teams configuration",
    )

    # Health check configuration
    health: HealthConfig = Field(
        default_factory=HealthConfig,
        description="Health check and dependency waiting configuration",
    )

    # Integration feature flags
    integrations: IntegrationConfig = Field(
        default_factory=IntegrationConfig,
        description="Feature flags for external platform integrations",
    )

    # Dhara state persistence
    dhara_state: DharaStatePersistenceConfig = Field(
        default_factory=DharaStatePersistenceConfig,
        description="Dhara-backed durable state persistence configuration",
    )

    # Unified config validation (soft-launch — off by default)
    unified_validation_enabled: bool = Field(
        default=False,
        description=(
            "Enable strict cross-file config validation on startup. "
            "Override via MAHAVISHNU_UNIFIED_VALIDATION_ENABLED=true or --config-strict CLI flag."
        ),
    )

    # Learning pipeline (Phase 1B)
    learning: LearningConfig = Field(
        default_factory=LearningConfig,
        description="Review-gated learning pipeline configuration",
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

    @classmethod
    def _settings_build_values(cls, sources, init_kwargs):
        """Override pydantic-settings merge order so later sources win.

        pydantic-settings' default ``_settings_build_values`` calls
        ``state = deep_update(source_state, state)`` on every iteration.
        ``deep_update(mapping, *updating)`` copies ``mapping`` and overlays
        the ``updating`` dicts onto it, so the *older* accumulated state
        wins over the newer ``source_state``. That makes earlier sources
        (init_settings) override later sources (env), which is the opposite
        of the documented precedence: defaults -> YAML -> env -> init.

        For nested subtrees that appear in ``settings/mahavishnu.yaml``
        (e.g. ``opensearch``) the bug masked env var and
        ``settings/local.yaml`` overrides. For subtrees absent from
        ``mahavishnu.yaml`` (e.g. ``agno``) the bug was invisible because
        the upstream YAML state was empty for that subtree.

        We fix this by:
        1. Reordering sources so ``init_settings`` is processed LAST
           (init kwargs are documented as the highest-precedence source).
        2. Merging with the correct direction: ``deep_update(state, source_state)``
           so the *newer* source overlays the older accumulated state.

        Net result: init_settings > env_settings > dotenv_settings >
        file_secret_settings > local.yaml > mahavishnu.yaml > defaults.
        See docs/followups/2026-06-29-pydantic-settings-source-resolution.md.
        """
        if not sources:
            return {}

        from pydantic_settings.sources import (
            DefaultSettingsSource,
            InitSettingsSource,
            PydanticBaseSettingsSource,
        )

        # Reorder so init_settings is last (highest precedence). Other
        # sources keep their relative order from the customiser.
        # NOTE: YamlConfigSettingsSource subclasses InitSettingsSource, so
        # we use type() to avoid misidentifying YAML sources as init.
        init_source = None
        ordered = []
        for source in sources:
            if type(source) is InitSettingsSource:
                init_source = source
            else:
                ordered.append(source)
        if init_source is not None:
            ordered.append(init_source)

        state: dict = {}
        defaults: dict = {}
        for source in ordered:
            if isinstance(source, PydanticBaseSettingsSource):
                source._set_current_state(state)
                # _set_settings_sources_data accepts a states dict; some
                # pydantic-settings versions track sibling source state
                # for alias resolution. Provide the running state so any
                # lookup inside the source sees the accumulated values.
                source._set_settings_sources_data({"__running__": state})
            source_state = source()
            if isinstance(source, DefaultSettingsSource):
                defaults = source_state
            # Later sources must win: keep `state` as the base and apply
            # the new source_state on top. This is the inverse of
            # pydantic-settings' default `deep_update(source_state, state)`.
            state = deep_update(state, source_state)

        # Strip defaults that ended up matching the field default — they
        # are not "set" by any source.
        state = {
            key: val for key, val in state.items() if key not in defaults or defaults[key] != val
        }
        cls._settings_restore_init_kwarg_names(cls, init_kwargs, state)
        return state


# ============================================================================
# Settings factory
# ============================================================================


_settings_cache: MahavishnuSettings | None = None


def get_settings() -> MahavishnuSettings:
    """Return the process-wide ``MahavishnuSettings`` (lazy module-level cache).

    The first call instantiates ``MahavishnuSettings()`` (which reads from
    environment variables and the Oneiric YAML files in ``settings/``).
    Subsequent calls return the cached instance.

    Stateless callers (e.g. FastAPI routers, MCP tool decorators) use this to
    obtain a configured ``MahavishnuSettings`` without depending on a
    particular app instance being available in their scope.

    For tests and app-init code that need a pre-configured settings object,
    use :func:`set_settings` to override the cache, or :func:`reset_settings`
    to clear it.
    """
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = MahavishnuSettings()
    return _settings_cache


def set_settings(settings: MahavishnuSettings) -> None:
    """Override the cached settings (for app-init and test setup)."""
    global _settings_cache
    _settings_cache = settings


def reset_settings() -> None:
    """Clear the cached settings (for tests that need to re-read env / YAML)."""
    global _settings_cache
    _settings_cache = None


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
    "HNSWIndexConfig",
    "OTelStorageConfig",
    "OTelIngesterConfig",
    "OpenSearchConfig",
    "DLQConfig",
    "AuthConfig",
    "SubscriptionAuthConfig",
    "SessionBuddyPollingConfig",
    "QualityControlConfig",
    "SessionConfig",
    "ResilienceConfig",
    "ObservabilityConfig",
    "WorkerConfig",
    "AdapterConfig",
    "HatchetConfig",
    "LLMConfig",
    "OneiricMCPConfig",
    "AdapterRegistryConfig",
    # Goal-Driven Teams configuration
    "GoalParsingConfig",
    "GoalTeamsLimitsConfig",
    "GoalTeamsFeatureFlags",
    "GoalTeamsConfig",
    # Health check configuration
    "DependencyConfig",
    "HealthConfig",
    # Learning pipeline configuration
    "LearningConfig",
    # Dhara state persistence
    "DharaStatePersistenceConfig",
    "MahavishnuSettings",
    # Settings factory
    "get_settings",
    "set_settings",
    "reset_settings",
]
