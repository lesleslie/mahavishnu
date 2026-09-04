"""Terminal management configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TerminalSettings(BaseModel):
    """Terminal manager settings.

    Configuration for terminal session management including
    concurrency limits, output capture settings, adapter
    preferences, and connection pooling.
    """

    enabled: bool = Field(
        default=False,
        description="Enable terminal management features",
    )
    default_columns: int = Field(
        default=120,
        ge=40,
        le=300,
        description="Default terminal width in characters",
    )
    default_rows: int = Field(
        default=40,
        ge=10,
        le=200,
        description="Default terminal height in lines",
    )
    capture_lines: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Default number of lines to capture from output",
    )
    poll_interval: float = Field(
        default=0.5,
        ge=0.1,
        le=10.0,
        description="Polling interval in seconds for output capture",
    )
    max_concurrent_sessions: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of concurrent terminal sessions",
    )
    adapter_preference: str = Field(
        default="mock",
        description="Preferred adapter: mock, tmux, crow, or auto. Default mock is safe — no external dependencies until iTerm2/tmux/crow is explicitly configured.",
    )
    fallback_on_probe_failure: bool = Field(
        default=False,
        description="Fall back to mock adapter if probe fails; True = fallback, False = fail startup",
    )
    # Crow adapter (bundled bodai-crow HTTP server). Defaults to disabled because
    # the default settings/mahavishnu.yaml sets adapter_preference="crow" but the
    # CLI callers don't yet construct an mcp_client. Operators opt in by setting
    # crow_enabled=true (and providing an mcp_client at the CLI layer).
    # See: docs/followups/2026-06-29-crow-mcp-client-wiring.md
    crow_enabled: bool = Field(
        default=False,
        description=(
            "Enable the bundled crow terminal adapter. When false and "
            "adapter_preference='crow', the manager falls through to the mock "
            "adapter rather than crashing with ConfigurationError. Requires "
            "mcp_client construction at the CLI layer when set to true."
        ),
    )
    crow_http_host: str = Field(
        default="127.0.0.1",
        description="Hostname for the bundled crow HTTP server (used when crow_enabled is true)",
    )
    crow_http_port: int = Field(
        default=8693,
        ge=1,
        le=65535,
        description=(
            "Port for the bundled crow HTTP server (used when crow_enabled is "
            "true). 8693 is reserved in CLAUDE.md portmap; 8675 is occupied by "
            "Prefect's local uvicorn."
        ),
    )
