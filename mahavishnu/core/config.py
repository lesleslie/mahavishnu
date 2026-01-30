"""Core configuration module for Mahavishnu using Oneiric patterns.

This module provides type-safe configuration management using Pydantic models,
following Oneiric's configuration loading patterns with layered configuration
support (defaults -> committed YAML -> local YAML -> environment variables).
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

from ..terminal.config import TerminalSettings


class MahavishnuSettings(BaseSettings):
    """Mahavishnu configuration extending MCPServerSettings.

    Configuration loading order (later overrides earlier):
    1. Default values (below)
    2. settings/mahavishnu.yaml (committed to git)
    3. settings/local.yaml (gitignored, for development)
    4. Environment variables: MAHAVISHNU_{FIELD}

    Example YAML (settings/mahavishnu.yaml):
        server_name: "Mahavishnu Orchestrator"
        cache_root: .oneiric_cache
        health_ttl_seconds: 60.0
        log_level: INFO
        repos_path: ~/repos.yaml
        adapters:
            airflow: true
            crewai: true
            langgraph: true
            agno: true
        qc:
            enabled: true
            min_score: 80
            checks:
                - linting
                - type_checking
                - security_scan
    """

    model_config = SettingsConfigDict(
        yaml_files=["settings/mahavishnu.yaml", "settings/local.yaml"],
        env_prefix="MAHAVISHNU_",
        env_nested_delimiter="__",
        extra="allow",
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

    # Adapter configuration
    prefect_enabled: bool = Field(
        default=True,  # Enabled by default - core orchestration
        description="Enable Prefect adapter for high-level orchestration",
    )
    llamaindex_enabled: bool = Field(
        default=True,  # Enabled by default - RAG pipelines
        description="Enable LlamaIndex adapter for RAG and knowledge bases",
    )
    agno_enabled: bool = Field(
        default=True,  # Enabled by default - fast agents
        description="Enable Agno adapter for agent-based workflows",
    )

    # LLM configuration for LlamaIndex and Agno
    llm_model: str = Field(
        default="nomic-embed-text",  # Ollama embedding model
        description="LLM model name for Ollama (e.g., nomic-embed-text, llama2)",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API endpoint for local LLM access",
    )

    # Quality control
    qc_enabled: bool = Field(
        default=True,
        description="Enable Crackerjack QC",
    )
    qc_min_score: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Minimum QC score threshold (0-100)",
    )

    # Session management
    session_enabled: bool = Field(
        default=True,
        description="Enable Session-Buddy checkpoints",
    )
    checkpoint_interval: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Checkpoint interval in seconds (10-600)",
    )

    # Resilience
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

    # Observability
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

    # Authentication (optional)
    auth_enabled: bool = Field(
        default=False,
        description="Enable JWT authentication",
    )
    auth_secret: str | None = Field(
        default=None,
        description="JWT secret (must be set via environment if auth enabled)",
    )
    auth_algorithm: str = Field(
        default="HS256",
        description="JWT algorithm (HS256 or RS256)",
    )
    auth_expire_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="JWT token expiration in minutes (5-1440)",
    )

    # Subscription authentication (for Claude Code, etc.)
    subscription_auth_enabled: bool = Field(
        default=False,
        description="Enable subscription-based authentication (e.g., Claude Code)",
    )
    subscription_auth_secret: str | None = Field(
        default=None,
        description="Subscription auth secret (must be set via environment if subscription auth enabled)",
    )
    subscription_auth_algorithm: str = Field(
        default="HS256",
        description="Subscription auth algorithm (HS256 or RS256)",
    )
    subscription_auth_expire_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Subscription token expiration in minutes (5-1440)",
    )

    # Cross-project authentication (for Session Buddy integration)
    cross_project_auth_secret: str | None = Field(
        default=None,
        description="Cross-project authentication secret (must be set via environment for Session Buddy integration)",
    )

    # OpenSearch configuration for vector storage and observability
    opensearch_endpoint: str = Field(
        default="https://localhost:9200",
        description="OpenSearch endpoint for vector storage and observability",
    )
    opensearch_index_name: str = Field(
        default="mahavishnu_code",
        description="OpenSearch index name for code vectors",
    )
    opensearch_verify_certs: bool = Field(
        default=True,
        description="Verify SSL certificates for OpenSearch connection",
    )
    opensearch_ca_certs: str | None = Field(
        default=None,
        description="Path to CA certificate file for OpenSearch",
    )
    opensearch_use_ssl: bool = Field(
        default=True,
        description="Use SSL for OpenSearch connection",
    )
    opensearch_ssl_assert_hostname: bool = Field(
        default=True,
        description="Assert hostname for OpenSearch SSL connection",
    )
    opensearch_ssl_show_warn: bool = Field(
        default=True,
        description="Show SSL warnings for OpenSearch connection",
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Terminal management
    terminal: TerminalSettings = Field(
        default_factory=TerminalSettings,
        description="Terminal session management settings",
    )

    # Admin shell
    shell_enabled: bool = Field(
        default=True,
        description="Enable admin shell (mahavishnu shell command)",
    )

    @field_validator("auth_secret")
    @classmethod
    def validate_auth_secret(cls, v: str | None, info) -> str | None:
        """Validate auth secret is set if auth is enabled."""
        if info.data.get("auth_enabled") and not v:
            raise ValueError(
                "auth_secret must be set via MAHAVISHNU_AUTH_SECRET "
                "environment variable when auth_enabled is true"
            )
        return v

    @field_validator("subscription_auth_secret")
    @classmethod
    def validate_subscription_auth_secret(cls, v: str | None, info) -> str | None:
        """Validate subscription auth secret is set if subscription auth is enabled."""
        if info.data.get("subscription_auth_enabled") and not v:
            raise ValueError(
                "subscription_auth_secret must be set via MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET "
                "environment variable when subscription_auth_enabled is true"
            )
        return v

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
