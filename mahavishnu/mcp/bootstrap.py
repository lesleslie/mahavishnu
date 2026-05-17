"""Bootstrap helpers for the MCP server."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from ..terminal.adapters.iterm2 import ITERM2_AVAILABLE, ITerm2Adapter
from ..terminal.adapters.mcpretentious import McpretentiousAdapter
from ..terminal.manager import TerminalManager

if TYPE_CHECKING:
    from .server_core import FastMCPServer

logger = getLogger(__name__)


def init_terminal_manager(server: FastMCPServer) -> TerminalManager | None:
    """Initialize the terminal manager using the server's MCP client."""
    try:
        config = server.app.config.terminal
        preference = config.adapter_preference.lower()

        if preference == "auto":
            if ITERM2_AVAILABLE:
                preference = "iterm2"
                logger.info("Auto-detected iTerm2 availability, using iTerm2 adapter")
            else:
                preference = "mcpretentious"
                logger.info("iTerm2 not available, using mcpretentious adapter")

        if preference == "iterm2":
            if not ITERM2_AVAILABLE:
                logger.warning(
                    "iTerm2 adapter requested but not available. Install with: pip install iterm2"
                )
                logger.info("Falling back to mcpretentious adapter")
                adapter = McpretentiousAdapter(server.mcp_client)
            else:
                try:
                    adapter = ITerm2Adapter()  # type: ignore[assignment]
                    logger.info("Initialized iTerm2 adapter")
                except Exception as exc:
                    logger.warning("Failed to initialize iTerm2 adapter: %s", exc)
                    logger.info("Falling back to mcpretentious adapter")
                    adapter = McpretentiousAdapter(server.mcp_client)
        else:
            adapter = McpretentiousAdapter(server.mcp_client)
            logger.info("Initialized mcpretentious adapter")

        manager = TerminalManager(adapter, config)
        logger.info(
            "Terminal manager initialized with %s adapter (max_concurrent=%s)",
            adapter.adapter_name,
            config.max_concurrent_sessions,
        )
        return manager
    except Exception as exc:
        logger.error("Failed to initialize terminal manager: %s", exc)
        return None


def register_health_endpoint(server: FastMCPServer, version: str) -> None:
    """Register HTTP health endpoints on the FastMCP server."""

    @server.server.custom_route("/health", methods=["GET"])  # type: ignore[arg-type]
    async def health_check() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mahavishnu", "version": version})

    @server.server.custom_route("/healthz", methods=["GET"])  # type: ignore[arg-type]
    async def healthz_check() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @server.server.custom_route("/metrics", methods=["GET"])  # type: ignore[arg-type]
    async def metrics_endpoint():
        from monitoring.metrics import metrics_endpoint as prometheus_metrics_endpoint

        return await prometheus_metrics_endpoint()


async def _register_core_integration_tools(server: FastMCPServer, methods_set: set[str]) -> None:
    if server.terminal_manager is not None and "_register_terminal_tools" in methods_set:
        from ..mcp.tools.terminal_tools import register_terminal_tools

        register_terminal_tools(server.server, server.terminal_manager, server.mcp_client)
        logger.info("Registered 12 terminal management tools with MCP server")

    if "_register_session_buddy_tools" in methods_set:
        from ..mcp.tools.session_buddy_tools import register_session_buddy_tools

        register_session_buddy_tools(server.server, server.app, server.mcp_client)
        logger.info("Registered Session Buddy integration tools with MCP server")

    if "_register_git_analytics_tools" in methods_set:
        from ..mcp.tools.git_analytics import register_git_analytics_tools

        register_git_analytics_tools(server.server, server.mcp_client)
        logger.info("Registered 3 Git analytics tools with MCP server")

    if "_register_repository_messaging_tools" in methods_set:
        from ..mcp.tools.repository_messaging_tools import register_repository_messaging_tools

        register_repository_messaging_tools(server.server, server.app, server.mcp_client)
        logger.info("Registered repository messaging tools with MCP server")


async def _register_worker_pool_tools(server: FastMCPServer, methods_set: set[str]) -> None:
    if "_register_worker_tools" in methods_set:
        if not getattr(server.app.config, "workers_enabled", True):
            logger.info("Worker orchestration disabled, skipping tool registration")
        else:
            worker_manager = getattr(server.app, "_worker_manager", None)
            if worker_manager is None:
                logger.warning("Worker manager not initialized, skipping worker tools")
            else:
                from ..mcp.tools.worker_tools import register_worker_tools

                register_worker_tools(server.server, worker_manager)
                logger.info("Registered 9 worker orchestration tools with MCP server")

    if "_register_pool_tools" in methods_set:
        if not getattr(server.app.config, "pools_enabled", True):
            logger.info("Pool management disabled, skipping tool registration")
        else:
            pool_manager = getattr(server.app, "pool_manager", None)
            if pool_manager is None:
                logger.warning("Pool manager not initialized, skipping pool tools")
            else:
                from ..mcp.tools.pool_tools import register_pool_tools

                register_pool_tools(server.server, pool_manager)
                logger.info("Registered 10 pool management tools with MCP server")

    if "_register_otel_tools" in methods_set:
        if not getattr(server.app.config, "otel_storage_enabled", False):
            logger.info("OTel storage disabled, skipping tool registration")
        else:
            from ..mcp.tools.otel_tools import register_otel_tools

            register_otel_tools(server.server, server.app, server.mcp_client)
            logger.info("Registered 4 OTel trace management tools with MCP server")


async def _register_optional_tools(server: FastMCPServer, methods_set: set[str]) -> None:
    if "_register_self_improvement_tools" in methods_set:
        from ..mcp.tools.self_improvement_tools import register_self_improvement_tools

        register_self_improvement_tools(server.server, server.app)

    if "_register_goal_team_tools" in methods_set:
        from ..core.feature_flags import is_feature_enabled

        if is_feature_enabled("enabled") and is_feature_enabled("mcp_tools_enabled"):
            from ..mcp.tools.goal_team_tools import register_goal_team_tools

            register_goal_team_tools(server.server)
            logger.info("Registered 3 goal-driven team tools with MCP server")
        else:
            logger.info("Goal-Driven Teams tools disabled, skipping tool registration")

    if "_register_treesitter_tools" in methods_set:
        try:
            from ..mcp.tools.treesitter_tools import register_treesitter_tools

            register_treesitter_tools(server.server)
            logger.info("Registered 7 tree-sitter code analysis tools with MCP server")
        except ImportError as exc:
            logger.info("Tree-sitter tools not available: %s", exc)

    if "_register_adapter_registry_tools" in methods_set:
        adapter_registry_config = getattr(server.app.config, "adapter_registry", None)
        if adapter_registry_config and not adapter_registry_config.enabled:
            logger.info("Adapter registry disabled, skipping tool registration")
        else:
            try:
                from ..mcp.tools.adapter_registry_tools import register_adapter_registry_tools

                register_adapter_registry_tools(server.server)
                logger.info("Registered 7 adapter registry management tools with MCP server")
            except ImportError as exc:
                logger.warning("Adapter registry tools not available: %s", exc)

    if "_register_pycharm_tools" in methods_set:
        try:
            from ..mcp.tools.pycharm_tools import register_pycharm_tools

            register_pycharm_tools(server.server, server.app)
            logger.info("Registered 8 PyCharm IDE tools with MCP server")
        except ImportError as exc:
            logger.warning("PyCharm tools not available: %s", exc)


async def register_profile_tools(server: FastMCPServer, methods_set: set[str]) -> None:
    """Register the profile-gated MCP tool groups on the server."""
    await _register_core_integration_tools(server, methods_set)
    await _register_worker_pool_tools(server, methods_set)
    await server.register_worktree_tools()
    await _register_optional_tools(server, methods_set)

    from ..mcp.tools.ecosystem_tools import register_ecosystem_tools
    from ..mcp.tools.health_tools import register_health_tools

    register_health_tools(server.server, server.app)
    logger.info("Registered health check tools with MCP server")
    register_ecosystem_tools(server.server)
    logger.info("Registered 3 canonical ecosystem status tools with MCP server")
