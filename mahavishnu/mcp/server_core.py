"""FastMCP server implementation for Mahavishnu."""
import asyncio
from logging import getLogger
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from ..core.app import MahavishnuApp
from ..core.auth import get_auth_from_config
from ..terminal.mcp_client import McpretentiousClient
from ..terminal.adapters.mcpretentious import McpretentiousAdapter
from ..terminal.adapters.iterm2 import ITerm2Adapter, ITERM2_AVAILABLE
from ..terminal.manager import TerminalManager
from ..terminal.config import TerminalSettings

logger = getLogger(__name__)


class McpretentiousMCPClient:
    """MCP client wrapper for mcpretentious server.

    Wraps the McpretentiousClient to provide the call_tool interface
    expected by the McpretentiousAdapter.
    """

    def __init__(self):
        """Initialize mcpretentious MCP client wrapper."""
        self._client = McpretentiousClient()
        self._started = False

    async def _ensure_started(self) -> None:
        """Ensure the mcpretentious server is started."""
        if not self._started:
            try:
                await self._client.start()
                self._started = True
                logger.info("Started mcpretentious MCP server")
            except Exception as e:
                logger.error(f"Failed to start mcpretentious server: {e}")
                raise RuntimeError(
                    f"Could not start mcpretentious server. "
                    f"Ensure uvx and mcpretentious are installed: {e}"
                ) from e

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Call an mcpretentious MCP tool.

        Args:
            tool_name: Name of the tool (e.g., "mcpretentious-open")
            params: Parameters for the tool

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If tool call fails
        """
        await self._ensure_started()

        try:
            # Map tool names to client methods
            if tool_name == "mcpretentious-open":
                terminal_id = await self._client.open_terminal(
                    columns=params.get("columns", 80),
                    rows=params.get("rows", 24)
                )
                return {"terminal_id": terminal_id}

            elif tool_name == "mcpretentious-type":
                await self._client.type_text(
                    params["terminal_id"],
                    *params["input"]
                )
                return {}

            elif tool_name == "mcpretentious-read":
                output = await self._client.read_text(
                    params["terminal_id"],
                    lines=params.get("limit_lines")
                )
                return {"output": output}

            elif tool_name == "mcpretentious-close":
                await self._client.close_terminal(params["terminal_id"])
                return {}

            elif tool_name == "mcpretentious-list":
                terminals = await self._client.list_terminals()
                return {"terminals": terminals}

            else:
                raise ValueError(f"Unknown tool: {tool_name}")

        except Exception as e:
            logger.error(f"Error calling mcpretentious tool {tool_name}: {e}")
            raise


class FastMCPServer:
    """FastMCP server implementation for Mahavishnu."""

    def __init__(self, config=None):
        """Initialize the FastMCP server.

        Args:
            config: Optional configuration object
        """
        self.app = MahavishnuApp(config)
        self.auth_handler = get_auth_from_config(self.app.config)
        self.server = FastMCP(
            name="Mahavishnu Orchestrator",
            version="1.0.0"
        )

        # Initialize MCP client wrapper
        self.mcp_client = McpretentiousMCPClient()

        # Initialize terminal manager if enabled
        self.terminal_manager = None
        if self.app.config.terminal.enabled:
            self.terminal_manager = self._init_terminal_manager()

        # Register all tools
        self._register_tools()

    def _init_terminal_manager(self) -> TerminalManager | None:
        """Initialize terminal manager with appropriate adapter.

        Selects adapter based on terminal.adapter_preference setting:
        - "iterm2": Use iTerm2 Python API (requires iTerm2 running)
        - "mcpretentious": Use mcpretentious MCP server
        - "auto": Auto-detect (iTerm2 if available, else mcpretentious)

        Returns:
            TerminalManager instance or None if initialization fails
        """
        try:
            config = self.app.config.terminal
            preference = config.adapter_preference.lower()

            # Auto-detect if preference is "auto"
            if preference == "auto":
                if ITERM2_AVAILABLE:
                    preference = "iterm2"
                    logger.info("Auto-detected iTerm2 availability, using iTerm2 adapter")
                else:
                    preference = "mcpretentious"
                    logger.info("iTerm2 not available, using mcpretentious adapter")

            # Initialize selected adapter
            if preference == "iterm2":
                if not ITERM2_AVAILABLE:
                    logger.warning(
                        "iTerm2 adapter requested but not available. "
                        "Install with: pip install iterm2"
                    )
                    logger.info("Falling back to mcpretentious adapter")
                    adapter = McpretentiousAdapter(self.mcp_client)
                else:
                    try:
                        adapter = ITerm2Adapter()
                        logger.info("Initialized iTerm2 adapter")
                    except Exception as e:
                        logger.warning(f"Failed to initialize iTerm2 adapter: {e}")
                        logger.info("Falling back to mcpretentious adapter")
                        adapter = McpretentiousAdapter(self.mcp_client)
            else:
                adapter = McpretentiousAdapter(self.mcp_client)
                logger.info("Initialized mcpretentious adapter")

            manager = TerminalManager(adapter, config)
            logger.info(
                f"Terminal manager initialized with {adapter.adapter_name} adapter "
                f"(max_concurrent={config.max_concurrent_sessions})"
            )
            return manager
        except Exception as e:
            logger.error(f"Failed to initialize terminal manager: {e}")
            return None

    def _register_tools(self):
        """Register all MCP tools using the FastMCP decorator pattern."""
        # Register core tools using the server's tool decorator
        server = self.server

        @server.tool()
        async def list_repos(
            tag: Optional[str] = None,
            limit: Optional[int] = None,
            offset: Optional[int] = None,
        ) -> Dict[str, Any]:
            """List repositories with optional filtering and pagination.

            Args:
                tag: Optional tag to filter repos
                limit: Optional limit on number of results
                offset: Optional offset for pagination

            Returns:
                Dictionary with list of repositories and metadata
            """
            try:
                repos = self.app.get_repos(tag=tag)

                # Apply pagination if specified
                if offset is not None:
                    repos = repos[offset:]
                if limit is not None:
                    repos = repos[:limit]

                return {
                    "repos": [
                        {"path": repo, "exists": True}
                        for repo in repos
                    ],
                    "total_count": len(self.app.get_repos()),
                    "filtered_count": len(repos),
                    "tag": tag
                }
            except Exception as e:
                return {
                    "error": f"Failed to list repositories: {str(e)}",
                    "repos": [],
                    "total_count": 0,
                    "filtered_count": 0
                }

        @server.tool()
        async def trigger_workflow(
            adapter: str,
            task_type: str,
            params: Dict[str, Any] = {},
            tag: Optional[str] = None,
            repos: Optional[List[str]] = None,
            timeout: Optional[int] = None,
        ) -> Dict[str, Any]:
            """Trigger workflow execution.

            Args:
                adapter: Adapter name (langgraph, prefect, agno)
                task_type: Type of workflow (code_sweep, quality_check)
                params: Additional parameters for the task
                tag: Optional tag to filter repos
                repos: Optional explicit repo list (overrides tag)
                timeout: Optional timeout in seconds

            Returns:
                {
                    "workflow_id": "uuid",
                    "status": "running|completed|failed",
                    "result": {...},
                    "repos_processed": 5,
                    "errors": [...]
                }
            """
            try:
                # Determine repos to process
                if repos is not None:
                    target_repos = repos
                elif tag is not None:
                    target_repos = self.app.get_repos(tag=tag)
                else:
                    target_repos = self.app.get_repos()

                # Create task specification
                task = {
                    "type": task_type,
                    "params": params,
                    "id": f"{task_type}_{adapter}_{len(target_repos)}_repos"
                }

                # Execute workflow with timeout if specified
                if timeout:
                    result = await asyncio.wait_for(
                        self.app.execute_workflow_parallel(task, adapter, target_repos),
                        timeout=timeout
                    )
                else:
                    result = await self.app.execute_workflow_parallel(task, adapter, target_repos)

                return {
                    "workflow_id": result.get("task", {}).get("id", "unknown"),
                    "status": result.get("status", "unknown"),
                    "result": result,
                    "repos_processed": result.get("repos_processed", 0),
                    "errors": result.get("errors", [])
                }
            except asyncio.TimeoutError:
                return {
                    "workflow_id": f"{task_type}_{adapter}_timeout",
                    "status": "failed",
                    "result": {"error": "Workflow timed out"},
                    "repos_processed": 0,
                    "errors": [{"error": "Operation timed out", "type": "TimeoutError"}]
                }
            except Exception as e:
                return {
                    "workflow_id": f"{task_type}_{adapter}_error",
                    "status": "failed",
                    "result": {"error": str(e)},
                    "repos_processed": 0,
                    "errors": [{"error": str(e), "type": type(e).__name__}]
                }

        @server.tool()
        async def get_workflow_status(workflow_id: str) -> Dict[str, Any]:
            """Get status of a workflow execution.

            Args:
                workflow_id: ID of the workflow to check

            Returns:
                Status information for the workflow
            """
            return {
                "workflow_id": workflow_id,
                "status": "completed",
                "progress": 100,
                "repos_processed": 0,
                "result_summary": "Mock status for demonstration"
            }

        @server.tool()
        async def cancel_workflow(workflow_id: str) -> Dict[str, Any]:
            """Cancel a running workflow.

            Args:
                workflow_id: ID of the workflow to cancel

            Returns:
                Result of cancellation attempt
            """
            return {
                "workflow_id": workflow_id,
                "status": "cancelled",
                "message": f"Workflow {workflow_id} cancelled (mock implementation)"
            }

        @server.tool()
        async def list_adapters() -> Dict[str, Any]:
            """List available adapters.

            Returns:
                Dictionary with available adapters and their status
            """
            adapters_info = {}
            for name, adapter in self.app.adapters.items():
                try:
                    health = await adapter.get_health()
                    adapters_info[name] = {
                        "enabled": True,
                        "health": health
                    }
                except Exception as e:
                    adapters_info[name] = {
                        "enabled": True,
                        "health": {"status": "unhealthy", "error": str(e)}
                    }

            return {
                "adapters": adapters_info,
                "count": len(adapters_info)
            }

        @server.tool()
        async def get_health() -> Dict[str, Any]:
            """Get overall health status of the system.

            Returns:
                Health status information
            """
            try:
                app_healthy = self.app.is_healthy()

                # Check individual adapter health
                adapter_health = {}
                for name, adapter in self.app.adapters.items():
                    try:
                        health = await adapter.get_health()
                        adapter_health[name] = health
                    except Exception as e:
                        adapter_health[name] = {
                            "status": "unhealthy",
                            "error": str(e)
                        }

                overall_status = "healthy"
                if not app_healthy or any(h.get("status") == "unhealthy" for h in adapter_health.values()):
                    overall_status = "unhealthy"
                elif any(h.get("status") == "degraded" for h in adapter_health.values()):
                    overall_status = "degraded"

                return {
                    "status": overall_status,
                    "app_healthy": app_healthy,
                    "adapter_health": adapter_health,
                    "timestamp": asyncio.get_event_loop().time()
                }
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time()
                }

    async def start(self, host: str = "127.0.0.1", port: int = 3000):
        """Start the MCP server.

        Args:
            host: Host address to bind to
            port: Port to listen on
        """
        # Register terminal management tools if enabled
        if self.terminal_manager is not None:
            self._register_terminal_tools()

        await self.server.run_http_async(host=host, port=port)

    async def stop(self) -> None:
        """Stop the MCP server and cleanup resources.

        Stops the mcpretentious server if it was started.
        """
        # Stop mcpretentious server
        if hasattr(self, 'mcp_client') and hasattr(self.mcp_client, '_client'):
            try:
                await self.mcp_client._client.stop()
                logger.info("Stopped mcpretentious MCP server")
            except Exception as e:
                logger.warning(f"Error stopping mcpretentious server: {e}")

    def _register_terminal_tools(self):
        """Register terminal management tools with MCP server."""
        from ..mcp.tools.terminal_tools import register_terminal_tools

        register_terminal_tools(self.server, self.terminal_manager, self.mcp_client)
        logger.info("Registered 12 terminal management tools with MCP server")


async def run_server(config=None):
    """Run the MCP server."""
    server = FastMCPServer(config)
    await server.start()