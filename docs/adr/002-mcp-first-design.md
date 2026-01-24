# ADR 002: MCP-First Design with FastMCP + mcp-common

## Status
**Accepted**

## Context
Mahavishnu needs to expose its functionality via MCP (Machine Context Protocol) for integration with AI assistants and other tools. The MCP server is a primary interface, not an afterthought.

### Options Considered

#### Option 1: REST API + MCP Wrapper
- **Pros:** Familiar pattern, flexible
- **Cons:** MCP is secondary concern, additional layer, inconsistent with ecosystem

#### Option 2: Raw MCP SDK
- **Pros:** Direct control, no dependencies
- **Cons:** Reimplementing common patterns, missing best practices, high maintenance

#### Option 3: FastMCP + mcp-common (CHOSEN)
- **Pros:**
  - FastMCP: Declarative MCP server with async support
  - mcp-common: Proven patterns for lifecycle management, configuration, authentication
  - MCPServerCLIFactory: Standardized CLI (start/stop/restart/status/health)
  - MCPServerSettings: Oneiric-native configuration
  - ServerPanels: Consistent error display
  - Rate limiting middleware built-in
  - Alignment with Crackerjack and ecosystem tools
- **Cons:**
  - Additional dependencies
  - Must follow mcp-common patterns

## Decision
Design Mahavishnu as MCP-first using FastMCP + mcp-common patterns.

### Rationale

1. **Ecosystem Alignment:** Crackerjack, Session-Buddy, and other ecosystem tools use this pattern, ensuring consistency.

2. **Proven Patterns:** mcp-common provides battle-tested solutions for authentication, rate limiting, lifecycle management, and health monitoring.

3. **Developer Experience:** Declarative tool registration with `@mcp_app.tool()` decorator is intuitive and maintainable.

4. **Performance:** FastMCP with async/await provides excellent performance for concurrent operations.

5. **Operational Excellence:** MCPServerCLIFactory provides standardized lifecycle management (start/stop/restart/status/health) out of the box.

### Architecture

```python
from fastmcp import FastMCP
from mcp_common.cli import MCPServerCLIFactory, MCPServerSettings
from mcp_common.ui import ServerPanels

class MahavishnuMCPServer:
    """Mahavishnu MCP server using FastMCP + mcp-common patterns."""

    def __init__(self, settings: MahavishnuSettings):
        self.settings = settings
        self.mcp_app = FastMCP(
            "mahavishnu-mcp-server",
            streamable_http_path="/mcp",
        )
        self._setup_middleware()
        self._register_tools()

    def _setup_middleware(self):
        """Setup authentication, rate limiting, and other middleware."""
        # Rate limiting (from mcp-common patterns)
        from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

        rate_limiter = RateLimitingMiddleware(
            max_requests_per_second=100.0 / 60.0,  # 100 req/min
            burst_capacity=20,
            global_limit=True,
        )
        self.mcp_app.add_middleware(rate_limiter)

        # Authentication (if configured)
        if self.settings.auth_enabled:
            from .auth import JWTAuthMiddleware
            auth_middleware = JWTAuthMiddleware(
                secret=self.settings.auth_secret,
                algorithm="HS256",
            )
            self.mcp_app.add_middleware(auth_middleware)

    def _register_tools(self):
        """Register all MCP tools."""
        from .tools.repo_tools import register_repo_tools
        from .tools.workflow_tools import register_workflow_tools

        register_repo_tools(self.mcp_app, self.settings)
        register_workflow_tools(self.mcp_app, self.settings)
```

### Tool Registration Pattern

```python
# mahavishnu/mcp/tools/repo_tools.py
from typing import Any
from fastmcp import FastMCP
from mcp_common.ui import ServerPanels
from ...core.config import MahavishnuSettings
from ...core.app import MahavishnuApp

def register_repo_tools(mcp_app: FastMCP, settings: MahavishnuSettings) -> None:
    """Register repository management tools."""

    @mcp_app.tool()
    async def list_repos(
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """List repositories with optional tag filtering.

        Args:
            tag: Optional tag to filter repositories

        Returns:
            List of repository dictionaries with path, tags, description

        Raises:
            ValueError: If repos.yaml is not found or is invalid
        """
        try:
            app = MahavishnuApp(config=settings)
            repos = app.get_repos_by_tag(tag) if tag else app.get_all_repos()

            return [
                {
                    "path": repo.path,
                    "tags": repo.tags,
                    "description": repo.description,
                }
                for repo in repos
            ]

        except FileNotFoundError as e:
            ServerPanels.error(
                title="Configuration Error",
                message=f"repos.yaml not found",
                suggestion="Create repos.yaml with repository definitions",
                error_type=type(e).__name__,
            )
            raise
        except Exception as e:
            ServerPanels.error(
                title="Repository List Error",
                message=f"Failed to list repositories",
                suggestion="Check repos.yaml configuration",
                error_type=type(e).__name__,
            )
            raise
```

### CLI Integration with MCPServerCLIFactory

```python
# mahavishnu/cli.py
import typer
from mcp_common.cli import MCPServerCLIFactory
from .core.config import MahavishnuSettings
from .mcp.server import MahavishnuMCPServer

mcp_app = typer.Typer()

def _start_mcp_server():
    """Start the MCP server."""
    settings = MahavishnuSettings.load("mahavishnu")
    server = MahavishnuMCPServer(settings)
    server.run()

def _stop_mcp_server(pid: int):
    """Stop the MCP server."""
    # Graceful shutdown handled by MCPServerCLIFactory
    pass

def _health_probe():
    """Health check for the MCP server."""
    from mcp_common.cli import RuntimeHealthSnapshot

    settings = MahavishnuSettings.load("mahavishnu")
    app = MahavishnuApp(config=settings)

    return RuntimeHealthSnapshot(
        orchestrator_pid=None,  # Filled by CLI
        watchers_running=app.is_healthy(),
        remote_enabled=False,
        lifecycle_state={"config_loaded": True},
        activity_state={"active_workflows": len(app.get_active_workflows())},
    )

@mcp_app.command()
def start():
    """Start the MCP server."""
    factory = MCPServerCLIFactory(
        server_name="mahavishnu",
        settings_class=MahavishnuSettings,
        start_handler=_start_mcp_server,
        stop_handler=_stop_mcp_server,
        health_probe_handler=_health_probe,
    )
    factory.start()

@mcp_app.command()
def status():
    """Get MCP server status."""
    factory = MCPServerCLIFactory(
        server_name="mahavishnu",
        settings_class=MahavishnuSettings,
    )
    factory.status()

@mcp_app.command()
def health():
    """Run health probe."""
    factory = MCPServerCLIFactory(
        server_name="mahavishnu",
        settings_class=MahavishnuSettings,
    )
    factory.health()

@mcp_app.command()
def stop():
    """Stop the MCP server."""
    factory = MCPServerCLIFactory(
        server_name="mahavishnu",
        settings_class=MahavishnuSettings,
    )
    factory.stop()
```

## Consequences

### Positive
- MCP is primary interface, not an afterthought
- Consistent with Crackerjack and ecosystem tools
- Standardized lifecycle management (start/stop/restart/status/health)
- Built-in rate limiting and authentication
- Excellent developer experience with declarative tool registration
- Proven patterns from mcp-common

### Negative
- Additional dependencies (FastMCP, mcp-common)
- Must follow mcp-common patterns and conventions
- Learning curve for developers unfamiliar with the stack

### Risks
- **Risk:** FastMCP or mcp-common becomes unmaintained
  **Mitigation:** Both are actively maintained; fastmcp is part of FastAPI ecosystem

- **Risk:** Breaking changes in FastMCP or mcp-common
  **Mitigation:** Pin to specific versions (`fastmcp~=0.1.0`, `mcp-common~=0.3.0`)

## Implementation

### Phase 1: MCP Server Foundation (Week 4, Day 1-2)
- [ ] Create `MahavishnuMCPServer` class
- [ ] Setup FastMCP with HTTP endpoint
- [ ] Implement middleware (rate limiting, authentication)
- [ ] Add CLI integration with MCPServerCLIFactory

### Phase 2: Tool Registration (Week 4, Day 3-4)
- [ ] Implement `register_repo_tools()`
- [ ] Implement `register_workflow_tools()`
- [ ] Implement `register_adapter_tools()`
- [ ] Add comprehensive tool documentation

### Phase 3: Testing (Week 4, Day 5)
- [ ] Test MCP server lifecycle (start/stop/restart)
- [ ] Test tool registration and discovery
- [ ] Test authentication and authorization
- [ ] Test rate limiting
- [ ] Test health probes

## References
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [mcp-common Documentation](https://github.com/example/mcp-common)
- [Crackerjack MCP Server](https://github.com/example/crackerjack/tree/main/crackerjack/mcp)
