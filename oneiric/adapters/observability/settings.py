"""OpenTelemetry storage adapter settings."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class OTelStorageSettings(BaseSettings):
    """Settings for OpenTelemetry trace storage.

    Attributes:
        connection_string: PostgreSQL connection string for trace storage
        embedding_model: Sentence transformer model for semantic search
        embedding_dimension: Vector dimension for embeddings (128-1024)
        cache_size: Maximum number of embeddings to cache in memory
        similarity_threshold: Minimum similarity score for semantic search (0.0-1.0)
        batch_size: Number of traces to batch in single write operation
        batch_interval_seconds: Seconds between batch flushes
        max_retries: Maximum retry attempts for failed operations
        circuit_breaker_threshold: Failures before circuit breaker opens
    """

    connection_string: str = Field(
        default="postgresql://localhost:5432/otel",
        description="PostgreSQL connection string for trace storage",
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
    def validate_connection_string(cls, v: str) -> str:
        """Ensure connection string uses postgresql:// scheme."""
        if not v.startswith("postgresql://"):
            raise ValueError(
                f"Connection string must start with 'postgresql://', got: {v[:20]}..."
            )
        return v

    class Config:
        """Pydantic model configuration."""

        env_prefix = "OTEL_STORAGE_"
        extra = "ignore"
