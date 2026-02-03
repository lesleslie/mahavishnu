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

from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

from ..terminal.config import TerminalSettings


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
                f"connection_string must use postgresql:// or postgres:// scheme. "
                f"Got: {v[:30]}..."
            )

        # Basic structure validation (scheme://user:pass@host:port/db)
        if v.count("@") < 1:
            raise ValueError(
                f"connection_string missing '@' separator. "
                f"Expected format: postgresql://user:password@host:port/database"
            )

        if v.count("/") < 3:  # postgresql:// is 2 slashes, need at least one more for database
            raise ValueError(
                f"connection_string missing database name. "
                f"Expected format: postgresql://user:password@host:port/database"
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

    Example Environment Variables:
        MAHAVISHNU_POOLS__ENABLED=true
        MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING=postgresql://...
        MAHAVISHNU_AUTH__SECRET=your-secret-key
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
        default="settings/repos.yaml",
        description="Path to repos.yaml repository manifest",
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
