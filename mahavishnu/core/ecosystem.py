"""Ecosystem configuration loader and manager.

This module provides utilities to:
- Load ecosystem.yaml (single source of truth)
- Validate MCP server configurations
- Generate ~/.claude.json MCP server configs
- Handle dependency-ordered startup
- Manage audit timestamps
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
import yaml

from .errors import ConfigurationError


class RepositoryConfig(BaseModel):
    """Configuration for a single repository."""

    name: str
    package: str | None = None
    path: str
    nickname: str | None = None
    role: str
    tags: list[str] = Field(default_factory=list)
    description: str
    mcp: str | None = Field(
        default=None, description="MCP server type: 'native', '3rd-party', or null"
    )
    audit: dict[str, Any] = Field(default_factory=dict)

    # URL fields for quick access to resources
    repo_url: str | None = Field(
        default=None, description="Source code repository URL (GitHub, GitLab, etc.)"
    )
    homepage_url: str | None = Field(default=None, description="Project homepage URL")
    docs_url: str | None = Field(default=None, description="Documentation URL")
    urls: dict[str, str] = Field(
        default_factory=dict,
        description="Additional categorized URLs (e.g., issues, wiki, releases)",
    )


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    type: str = Field(pattern="^(http|stdio)$")
    port: int | None = None
    path: str | None = None
    package: str | None = None
    category: str
    function: str
    command: str | None = None
    description: str
    health_check: str | None = None
    status: str = Field(default="enabled", pattern="^(enabled|disabled)$")
    tags: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    maintainer: str = "les"
    audit: dict[str, Any] = Field(default_factory=dict)

    # URL fields for quick access to resources
    repo_url: str | None = Field(default=None, description="Source code repository URL")
    homepage_url: str | None = Field(default=None, description="Project homepage URL")
    docs_url: str | None = Field(default=None, description="Documentation URL")
    urls: dict[str, str] = Field(
        default_factory=dict,
        description="Additional categorized URLs (e.g., issues, examples, api)",
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int | None, info: Any) -> int | None:
        """Validate port configuration."""
        # Skip validation for IDE-managed servers (no command or path)
        if info.data.get("command") is info.data.get("path") is None:
            return v
        if info.data.get("type") == "http" and v is None:
            raise ValueError("HTTP servers must have a port")
        if info.data.get("type") == "stdio" and v is not None:
            raise ValueError("STDIO servers cannot have a port")
        return v

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str | None, info: Any) -> str | None:
        """Validate command has port placeholder for HTTP servers."""
        if v is None:
            return v
        if info.data.get("type") == "http" and "{port}" not in v:
            raise ValueError("HTTP server commands must include {{port}} placeholder")
        return v

    def get_rendered_command(self) -> str | None:
        """Get command with port placeholder rendered."""
        if self.command is None:
            return None
        if self.type == "http" and self.port:
            return self.command.format(port=self.port)
        return self.command


class EcosystemConfig(BaseModel):
    """Complete ecosystem configuration."""

    version: str = "1.0"
    last_updated: str
    maintainer: str
    description: str

    portmap: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    lsp_servers: list[dict[str, Any]] = Field(default_factory=list)
    repos: list[RepositoryConfig] = Field(default_factory=list)
    claude_agents: dict[str, Any] = Field(default_factory=dict)
    workflows: dict[str, Any] = Field(default_factory=dict)
    skills: dict[str, Any] = Field(default_factory=dict)
    tools: dict[str, Any] = Field(default_factory=dict)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    backup: dict[str, Any] = Field(default_factory=dict)
    maintenance: dict[str, Any] = Field(default_factory=dict)
    claude_settings: dict[str, Any] = Field(default_factory=dict)


class EcosystemLoader:
    """Load and manage ecosystem configuration."""

    def __init__(self, config_path: Path | None = None):
        """Initialize the ecosystem loader.

        Args:
            config_path: Path to ecosystem.yaml. Defaults to settings/ecosystem.yaml
                         in the project root directory.
        """
        if config_path is None:
            # Find ecosystem.yaml relative to this file
            # This file is in mahavishnu/core/, so go up 3 levels to reach project root
            current_file = Path(__file__)
            config_path = current_file.parent.parent.parent / "settings" / "ecosystem.yaml"

        self.config_path = config_path
        self._config: EcosystemConfig | None = None

    def load(self) -> EcosystemConfig:
        """Load ecosystem configuration from YAML file.

        Returns:
            EcosystemConfig: Loaded and validated configuration

        Raises:
            ConfigurationError: If configuration file cannot be loaded or validated
        """
        if not self.config_path.exists():
            raise ConfigurationError(
                message=f"Ecosystem configuration file not found: {self.config_path}",
                details={"suggestion": "Create ecosystem.yaml with MCP server configurations"},
            )

        try:
            with self.config_path.open() as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ConfigurationError(
                message=f"Failed to load ecosystem configuration: {e}",
                details={"path": str(self.config_path)},
            ) from e

        try:
            self._config = EcosystemConfig(**data)
        except Exception as e:
            raise ConfigurationError(
                message=f"Failed to validate ecosystem configuration: {e}",
                details={"path": str(self.config_path)},
            ) from e

        return self._config

    @property
    def config(self) -> EcosystemConfig:
        """Get loaded configuration.

        Returns:
            EcosystemConfig: The loaded configuration

        Raises:
            ConfigurationError: If configuration has not been loaded yet
        """
        if self._config is None:
            raise ConfigurationError(
                message="Configuration not loaded. Call load() first.",
                details={"suggestion": "Call ecosystem_loader.load() before accessing config"},
            )
        return self._config

    def get_enabled_mcp_servers(self) -> list[MCPServerConfig]:
        """Get all enabled MCP servers in dependency order.

        Returns:
            List of enabled MCP servers sorted by dependency order
        """
        servers = [s for s in self.config.mcp_servers if s.status == "enabled"]

        # Topological sort by dependencies
        ordered = []
        remaining = {s.name: s for s in servers}
        resolved = set()

        while remaining:
            # Find servers with no unresolved dependencies
            ready = [
                s for s in remaining.values() if all(dep in resolved for dep in s.dependencies)
            ]

            if not ready:
                # Circular dependency - just add remaining servers
                ready = list(remaining.values())

            for server in ready:
                ordered.append(server)
                resolved.add(server.name)
                del remaining[server.name]

        return ordered

    def generate_claude_mcp_config(self) -> dict[str, Any]:
        """Generate mcpServers section for ~/.claude.json.

        Returns:
            Dictionary suitable for ~/.claude.json mcpServers section
        """
        mcp_config = {}

        for server in self.get_enabled_mcp_servers():
            if server.type == "http":
                # IDE-managed servers use /stream endpoint
                if server.command is None:
                    mcp_config[server.name] = {
                        "type": "http",
                        "url": f"http://127.0.0.1:{server.port}/stream",
                    }
                else:
                    mcp_config[server.name] = {
                        "type": "http",
                        "url": f"http://localhost:{server.port}/mcp",
                    }
            else:  # stdio
                mcp_config[server.name] = {
                    "type": "stdio",
                    "command": server.command,
                }

        return mcp_config

    def validate_mcp_servers(self) -> dict[str, list[str]]:
        """Validate all MCP server configurations.

        Returns:
            Dictionary with 'errors' and 'warnings' keys containing lists of messages
        """
        errors = []
        warnings = []

        for server in self.config.mcp_servers:
            # Check if path exists
            if server.path and server.path != "npx":
                path = Path(server.path)
                if not path.exists():
                    errors.append(f"{server.name}: Path does not exist: {server.path}")

                # Check if package is installed (for local projects)
                if server.package and path.is_dir():
                    # Try to import the package
                    try:
                        __import__(server.package)
                    except ImportError:
                        errors.append(
                            f"{server.name}: Package '{server.package}' not installed or not importable"
                        )

            # Check for port conflicts
            if server.port:
                conflicting = [
                    s
                    for s in self.config.mcp_servers
                    if s.name != server.name
                    and s.port == server.port
                    and s.status == server.status == "enabled"
                ]
                if conflicting:
                    errors.append(
                        f"{server.name}: Port {server.port} conflicts with: "
                        f"{', '.join(s.name for s in conflicting)}"
                    )

            # Check if dependencies exist
            for dep in server.dependencies:
                dep_server = next((s for s in self.config.mcp_servers if s.name == dep), None)
                if not dep_server:
                    errors.append(f"{server.name}: Dependency '{dep}' not found in MCP servers")
                elif dep_server.status != "enabled":
                    warnings.append(
                        f"{server.name}: Dependency '{dep}' is disabled, "
                        f"server may not function correctly"
                    )

        return {"errors": errors, "warnings": warnings}

    def get_startup_commands(self) -> list[tuple[str, str, str]]:
        """Get startup commands for auto-start script.

        Returns:
            List of (server_name, port, command) tuples
        """
        commands = []

        for server in self.get_enabled_mcp_servers():
            # Skip IDE-managed servers (no command)
            if server.command is None:
                continue
            if server.type == "http":
                cmd = server.get_rendered_command()
                commands.append((server.name, str(server.port), cmd))

        return commands

    def update_audit_timestamp(
        self,
        server_name: str,
        field: str,
        value: str,
        notes: str | None = None,
    ) -> None:
        """Update audit timestamp for an MCP server.

        Args:
            server_name: Name of the MCP server
            field: Audit field to update (e.g., 'last_validated', 'last_tested')
            value: New timestamp value
            notes: Optional notes to add/update
        """
        for server in self.config.mcp_servers:
            if server.name == server_name:
                server.audit[field] = value
                if notes:
                    server.audit["notes"] = notes
                return

        raise ConfigurationError(
            message=f"MCP server not found: {server_name}",
            details={"server_name": server_name},
        )

    def save(self) -> None:
        """Save current configuration back to YAML file.

        Raises:
            ConfigurationError: If configuration cannot be saved
        """
        try:
            with self.config_path.open("w") as f:
                yaml.dump(self._config.model_dump(mode="yaml"), f, default_flow_style=False)
        except Exception as e:
            raise ConfigurationError(
                message=f"Failed to save ecosystem configuration: {e}",
                details={"path": str(self.config_path)},
            ) from e


# Singleton instance for easy access
_loader: EcosystemLoader | None = None


def get_ecosystem_loader(config_path: Path | None = None) -> EcosystemLoader:
    """Get or create the ecosystem loader singleton.

    Args:
        config_path: Optional path to ecosystem.yaml

    Returns:
        EcosystemLoader: The loader instance
    """
    global _loader
    if _loader is None:
        _loader = EcosystemLoader(config_path)
        _loader.load()
    return _loader
