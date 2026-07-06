"""Bootstrap helpers for the MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger
from starlette.responses import JSONResponse

from ..terminal.adapters.iterm2 import ITERM2_AVAILABLE, ITerm2Adapter
from ..terminal.adapters.mcpretentious import McpretentiousAdapter
from ..terminal.manager import TerminalManager

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from .server_core import FastMCPServer

logger = get_logger(__name__)


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
    async def health_check(request=None) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mahavishnu", "version": version})

    @server.server.custom_route("/healthz", methods=["GET"])  # type: ignore[arg-type]
    async def healthz_check(request=None) -> JSONResponse:
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
    """Coordinate registration of the worker/pool/OTel tool groups.

    Each sub-registration is its own function so this dispatcher stays
    flat (C901). Returning early on "name not in methods_set" is a
    precondition guard, not a domain branch.
    """
    if "_register_worker_tools" in methods_set:
        _register_worker_block(server)
    if "_register_pool_tools" in methods_set:
        _register_pool_block(server)
    if "_register_otel_tools" in methods_set:
        _register_otel_block(server)


def _register_worker_block(server: FastMCPServer) -> None:
    """Register ``register_worker_tools`` if enabled and a manager is present."""
    if not getattr(server.app.config, "workers_enabled", True):
        logger.info("Worker orchestration disabled, skipping tool registration")
        return
    worker_manager = getattr(server.app, "_worker_manager", None)
    if worker_manager is None:
        logger.warning("Worker manager not initialized, skipping worker tools")
        return
    from ..mcp.tools.worker_tools import register_worker_tools

    register_worker_tools(server.server, worker_manager)
    logger.info("Registered 9 worker orchestration tools with MCP server")


def _register_pool_block(server: FastMCPServer) -> None:
    """Register ``register_pool_tools`` if enabled and a manager is present."""
    if not getattr(server.app.config, "pools_enabled", True):
        logger.info("Pool management disabled, skipping tool registration")
        return
    pool_manager = getattr(server.app, "pool_manager", None)
    if pool_manager is None:
        logger.warning("Pool manager not initialized, skipping pool tools")
        return
    from ..mcp.tools.pool_tools import register_pool_tools

    register_pool_tools(server.server, pool_manager)
    logger.info("Registered 10 pool management tools with MCP server")


def _register_otel_block(server: FastMCPServer) -> None:
    """Register OTel tools when Akosha's storage layer is importable.

    Wrapped to remain robust against upstream Akosha import failures
    (e.g. broken Pydantic forward references) so the MCP server can still
    start with the rest of the tool profile intact.
    """
    import importlib.util

    try:
        akosha_spec = importlib.util.find_spec("akosha.storage")
    except Exception as exc:  # noqa: BLE001 - defensive: any import-time error
        logger.warning("Skipping OTel tool registration: akosha import failed: %s", exc)
        return

    if akosha_spec is None:
        logger.info("HotStore not available, skipping OTel tool registration")
        return

    try:
        from ..mcp.tools.otel_tools import register_otel_tools

        register_otel_tools(server.server, server.app, server.mcp_client)
        logger.info("Registered 4 OTel trace management tools with MCP server")
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("Skipping OTel tool registration after spec found: %s", exc)


async def _register_optional_tools(server: FastMCPServer, methods_set: set[str]) -> None:
    """Register optional tool groups gated by ``methods_set`` plus the A2A routes.

    Each gated registration is its own function so this dispatcher stays
    flat (C901). A2A is not gated by ``methods_set``; it's gated by
    ``a2a.enabled`` in app config.
    """
    for tool_name, registrar in _OPTIONAL_TOOL_BLOCKS:
        if tool_name in methods_set:
            registrar(server)
    _register_a2a_routes_block(server)


def _register_self_improvement_block(server: FastMCPServer) -> None:
    from ..mcp.tools.self_improvement_tools import register_self_improvement_tools

    register_self_improvement_tools(server.server, server.app)


def _register_clone_block(server: FastMCPServer) -> None:
    from ..mcp.tools.clone_tools import register_clone_tools

    register_clone_tools(server.server, server.app)
    logger.info("Registered 3 clone detection and refactoring tools with MCP server")


def _register_goal_team_block(server: FastMCPServer) -> None:
    from ..core.feature_flags import is_feature_enabled

    if not (is_feature_enabled("enabled") and is_feature_enabled("mcp_tools_enabled")):
        logger.info("Goal-Driven Teams tools disabled, skipping tool registration")
        return
    from ..mcp.tools.goal_team_tools import register_goal_team_tools

    register_goal_team_tools(server.server)
    logger.info("Registered 3 goal-driven team tools with MCP server")


def _register_treesitter_block(server: FastMCPServer) -> None:
    try:
        from ..mcp.tools.treesitter_tools import register_treesitter_tools

        register_treesitter_tools(server.server)
        logger.info("Registered 7 tree-sitter code analysis tools with MCP server")
    except ImportError as exc:
        logger.info("Tree-sitter tools not available: %s", exc)


def _register_adapter_registry_block(server: FastMCPServer) -> None:
    adapter_registry_config = getattr(server.app.config, "adapter_registry", None)
    if adapter_registry_config and not adapter_registry_config.enabled:
        logger.info("Adapter registry disabled, skipping tool registration")
        return
    try:
        from ..mcp.tools.adapter_registry_tools import register_adapter_registry_tools

        register_adapter_registry_tools(server.server)
        logger.info("Registered 7 adapter registry management tools with MCP server")
    except ImportError as exc:
        logger.warning("Adapter registry tools not available: %s", exc)


def _register_pycharm_block(server: FastMCPServer) -> None:
    try:
        from ..mcp.tools.pycharm_tools import register_pycharm_tools

        register_pycharm_tools(server.server, server.app)
        logger.info("Registered 8 PyCharm IDE tools with MCP server")
    except ImportError as exc:
        logger.warning("PyCharm tools not available: %s", exc)


def _register_primitive_block(server: FastMCPServer) -> None:
    try:
        from ..mcp.tools.primitive_tools import register_primitive_tools

        register_primitive_tools(server.server)
        logger.info(
            "Registered 2 primitive introspection tools (list_primitives, show_primitive) with MCP server"
        )
    except ImportError as exc:
        logger.warning("Primitive tools not available: %s", exc)


def _register_openhands_block(server: FastMCPServer) -> None:
    try:
        from ..mcp.tools.openhands_tools import mcp as openhands_mcp

        server.server.mount(openhands_mcp, "openhands")
        logger.info("Registered 4 OpenHands integration tools with MCP server")
    except Exception as exc:  # noqa: BLE001 - defensive: service may be unavailable
        logger.warning("OpenHands tools not available: %s", exc)


def _register_a2a_routes_block(server: FastMCPServer) -> None:
    """Mount the A2A server routes on the Starlette app when enabled.

    A2A is gated by ``a2a.enabled`` in app config (not by ``methods_set``),
    since it's a route mount rather than a tool registration.
    """
    a2a_config = getattr(server.app.config, "a2a", None)
    if not (a2a_config and a2a_config.enabled):
        return
    try:
        from ..a2a.server import build_a2a_router

        worker_manager = getattr(server.app, "_worker_manager", None)
        a2a_app = build_a2a_router(
            a2a_config,
            _make_a2a_execute_fn(worker_manager),
            auth_token=_resolve_a2a_auth_token(server),
        )

        _orig_http_app = server.server.http_app

        def _a2a_patched_http_app(*args: object, **kwargs: object) -> object:
            app = _orig_http_app(*args, **kwargs)  # type: ignore[arg-type]
            app.mount("/", a2a_app)
            return app

        server.server.http_app = _a2a_patched_http_app  # type: ignore[assignment]
        logger.info(
            "Mounted A2A server routes (/.well-known/agent.json, /tasks/send, /tasks/sendSubscribe)"
        )
    except Exception as exc:  # noqa: BLE001 - defensive: A2A may be unavailable
        logger.warning("A2A server routes not mounted: %s", exc)


def _resolve_a2a_auth_token(server: FastMCPServer) -> str | None:
    """Return the shared secret if auth is enabled and configured, else ``None``."""
    auth_config = getattr(server.app.config, "auth", None)
    if auth_config and auth_config.enabled and auth_config.secret:
        return auth_config.secret
    return None


def _make_a2a_execute_fn(
    worker_manager: Any,
) -> Callable[[dict[str, Any]], Any]:
    """Build the A2A execute callback that fans out to the first worker."""
    from ..core.status import WorkerStatus
    from ..workers.base import WorkerResult

    async def _a2a_execute_fn(task: dict[str, Any]) -> Any:
        """Route inbound A2A task to the first available worker."""
        if worker_manager is None:
            return WorkerResult(
                worker_id="none",
                status=WorkerStatus.FAILED,
                error="No worker manager available",
            )
        worker_ids = worker_manager.list_worker_ids()
        if not worker_ids:
            return WorkerResult(
                worker_id="none",
                status=WorkerStatus.FAILED,
                error="No workers registered",
            )
        return await worker_manager.execute_task(worker_ids[0], task)

    return _a2a_execute_fn


# Mapping of ``methods_set`` keys to their per-block registrars. Defined
# after the block functions so static analyzers (ruff) can see all names
# resolved. The dispatcher iterates this at call time; Python resolves the
# registrar names lazily when the module body finishes loading.
_OPTIONAL_TOOL_BLOCKS: tuple[tuple[str, Callable[[FastMCPServer], None]], ...] = (
    ("_register_self_improvement_tools", _register_self_improvement_block),
    ("_register_clone_tools", _register_clone_block),
    ("_register_goal_team_tools", _register_goal_team_block),
    ("_register_treesitter_tools", _register_treesitter_block),
    ("_register_adapter_registry_tools", _register_adapter_registry_block),
    ("_register_pycharm_tools", _register_pycharm_block),
    ("_register_primitive_tools", _register_primitive_block),
    ("_register_openhands_tools", _register_openhands_block),
)


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
