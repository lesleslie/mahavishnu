"""FastMCP server implementation for Mahavishnu."""

import asyncio
from contextlib import suppress
from datetime import datetime
from functools import wraps
from importlib.metadata import version
from logging import getLogger
import time
from typing import Any, cast

from mcp_common.fastmcp import FastMCP
from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware

from monitoring.metrics import (
    mcp_tool_calls_total,
    mcp_tool_duration_seconds,
    mcp_tools_registered,
)

from ..core.app import MahavishnuApp
from ..core.auth import get_auth_from_config
from ..core.permissions import Permission
from ..terminal.mcp_client import McpretentiousClient
from .bootstrap import init_terminal_manager as _init_terminal_manager_helper
from .bootstrap import register_health_endpoint as _register_health_endpoint_helper
from .lifecycle import register_worktree_tools as _register_worktree_tools_helper
from .lifecycle import start_server as _start_server_helper
from .lifecycle import stop_server as _stop_server_helper

logger = getLogger(__name__)

# Get version from package metadata
try:
    __version__ = version("mahavishnu")
except Exception:
    __version__ = "0.0.0-unknown"


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

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
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
                    columns=params.get("columns", 80), rows=params.get("rows", 24)
                )
                return {"terminal_id": terminal_id}

            elif tool_name == "mcpretentious-type":
                await self._client.type_text(params["terminal_id"], *params["input"])
                return {}

            elif tool_name == "mcpretentious-read":
                output = await self._client.read_text(
                    params["terminal_id"], lines=params.get("limit_lines")
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

    def __init__(self, app=None, config=None):
        """Initialize the FastMCP server.

        Args:
            app: Optional MahavishnuApp instance (creates new one if None)
            config: Optional configuration object (used if app is None)
        """
        if app is None:
            self.app = MahavishnuApp(config)
        else:
            self.app = app
        self.auth_handler = get_auth_from_config(self.app.config)
        self.server = FastMCP(name="Mahavishnu Orchestrator", version=__version__)
        self._registered_tool_count = 0
        self._instrument_server_tool_registration()
        self._register_telemetry_middleware()

        # Initialize MCP client wrapper
        self.mcp_client = McpretentiousMCPClient()

        # Initialize terminal manager if enabled
        self.terminal_manager = None
        if self.app.config.terminal.enabled:
            self.terminal_manager = _init_terminal_manager_helper(self)

            # Update pool_manager's terminal_manager reference if both exist
            # This is needed because pool_manager is initialized before terminal_manager
            # in MahavishnuApp, so it gets None initially
            if (
                self.terminal_manager is not None
                and hasattr(self.app, "pool_manager")
                and self.app.pool_manager is not None
            ):
                self.app.pool_manager.terminal_manager = self.terminal_manager
                logger.info("Updated pool_manager terminal_manager reference")

        # Register HTTP health endpoint for Claude Code health checks
        _register_health_endpoint_helper(self, __version__)

        # Register all tools
        self._register_tools()
        self._update_registered_tool_metrics()

    def _register_telemetry_middleware(self) -> None:
        """Attach OpenTelemetry middleware when tracing is enabled."""
        observability = getattr(self.app.config, "observability", None)
        if observability is None or not getattr(observability, "tracing_enabled", False):
            return

        service_name = getattr(self.app.config, "server_name", "mahavishnu")
        environment = "production"
        if hasattr(observability, "environment") and isinstance(observability.environment, str):
            environment = observability.environment

        self.server.add_middleware(
            FastMCPOpenTelemetryMiddleware(
                service_name=service_name,
                environment=environment,
            )
        )
        logger.info(
            "Registered FastMCP OpenTelemetry middleware",
            extra={"service_name": service_name, "environment": environment},
        )

    def _instrument_server_tool_registration(self) -> None:
        """Wrap FastMCP tool registration so all tool handlers emit shared metrics."""
        original_tool = self.server.tool

        def instrumented_tool(*tool_args: Any, **tool_kwargs: Any):
            base_decorator = original_tool(*tool_args, **tool_kwargs)

            def decorator(func: Any) -> Any:
                wrapped = self._wrap_tool_handler(func)
                registered = base_decorator(wrapped)
                self._registered_tool_count += 1
                self._update_registered_tool_metrics()
                return registered

            return decorator

        self.server.tool = cast("Any", instrumented_tool)

    def _wrap_tool_handler(self, func: Any) -> Any:
        """Wrap a tool handler with Prometheus instrumentation."""

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tool_name = func.__name__
            start_time = time.perf_counter()
            status = "success"

            try:
                result = await func(*args, **kwargs)
                status = self._classify_tool_result(result)
                return result
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except TimeoutError:
                status = "timeout"
                raise
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                mcp_tool_calls_total.labels(tool_name=tool_name, status=status).inc()
                mcp_tool_duration_seconds.labels(tool_name=tool_name).observe(duration)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tool_name = func.__name__
            start_time = time.perf_counter()
            status = "success"

            try:
                result = func(*args, **kwargs)
                status = self._classify_tool_result(result)
                return result
            except TimeoutError:
                status = "timeout"
                raise
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                mcp_tool_calls_total.labels(tool_name=tool_name, status=status).inc()
                mcp_tool_duration_seconds.labels(tool_name=tool_name).observe(duration)

        if asyncio.iscoroutinefunction(func):
            async_wrapper.__wrapped__ = func
            async_wrapper.__annotations__ = dict(func.__annotations__)
            return async_wrapper
        sync_wrapper.__wrapped__ = func
        sync_wrapper.__annotations__ = dict(func.__annotations__)
        return sync_wrapper

    def _classify_tool_result(self, result: Any) -> str:
        """Map a tool result payload to a Prometheus status label."""
        if not isinstance(result, dict):
            return "success"

        status = result.get("status")
        error = result.get("error")
        if error:
            return "error"
        if isinstance(status, str) and status.lower() in {"error", "failed", "unhealthy"}:
            return "error"
        return "success"

    def _update_registered_tool_metrics(self) -> None:
        """Publish the current number of registered MCP tools."""
        server_name = getattr(self.app.config, "server_name", "mahavishnu")
        if not isinstance(server_name, str) or not server_name:
            server_name = "mahavishnu"
        mcp_tools_registered.labels(server=server_name).set(self._registered_tool_count)

    def _register_tools(self):  # noqa: C901
        """Register all MCP tools using the FastMCP decorator pattern.

        Structural C901 suppression: FastMCP's ``@server.tool()`` decorator
        requires each tool function to be defined inline so it can introspect
        the function name and signature for the MCP tool schema. Extracting
        each tool body to a separate method would either duplicate the
        signature (and break the schema) or lose FastMCP's introspection.
        The 27 tools registered here are intentionally kept inline; the
        complexity is the cost of the FastMCP API contract, not bad code.
        """
        # Register core tools using the server's tool decorator
        server = self.server

        @server.tool()
        async def list_repos(
            tag: str | None = None,
            limit: int | None = None,
            offset: int | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            """List repositories with optional filtering and pagination."""
            try:
                repos = self.app.get_repos(tag=tag, user_id=user_id)

                # Apply pagination if specified
                if offset is not None:
                    repos = repos[offset:]
                if limit is not None:
                    repos = repos[:limit]

                return {
                    "repos": [{"path": repo, "exists": True} for repo in repos],
                    "total_count": len(self.app.get_repos(user_id=user_id)),
                    "filtered_count": len(repos),
                    "tag": tag,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to list repositories: {e}",
                    "repos": [],
                    "total_count": 0,
                    "filtered_count": 0,
                }

        @server.tool()
        async def trigger_workflow(
            adapter: str,
            task_type: str,
            params: dict[str, Any] | None = None,
            tag: str | None = None,
            repos: list[str] | None = None,
            timeout: int | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            """Trigger a durable workflow execution through a named adapter
            (prefect, llamaindex, agno). Use for multi-step orchestrations that
            span repos or need durable state across hours or days.

            Workflows run as durable Prefect flows, Agno agent loops, or
            LlamaIndex RAG pipelines depending on `adapter`.

            For ad-hoc single-task dispatch, prefer `pool_route_execute` instead —
            it's lighter weight and goes through the pool manager. Use
            `trigger_workflow` when you need durable orchestration, scheduled
            execution, or cross-adapter composition.

            **Adapter selection:**
            - `prefect` — durable flows with retries, scheduling, observability
              (best for production workflows)
            - `llamaindex` — RAG pipelines, document ingestion, semantic search
            - `agno` — agent loops, multi-step reasoning, tool use

            Returns a `workflow_id` immediately (C-NEW-5: fire-and-forget).
            Poll `get_workflow_status(workflow_id=...)` for results.

            Args:
                adapter: One of `prefect`, `llamaindex`, `agno`.
                task_type: Workflow task type (e.g., `code_review`, `ingest`,
                    `deploy`). Adapter-specific.
                params: Optional workflow parameters.
                tag: Optional tag to filter target repos (from `repos.yaml`).
                repos: Optional list of repo paths to scope the workflow to.
                timeout: Optional max seconds for the workflow to run.
                user_id: Optional user ID for quota / attribution.

            Returns:
                `{"workflow_id": "...", "status": "queued", "adapter": "..."}`.
                The workflow runs asynchronously; poll for completion.

            Example:
                ```
                result = await trigger_workflow(
                    adapter="prefect",
                    task_type="code_review",
                    repos=["/path/to/mahavishnu", "/path/to/akosha"],
                    params={"scope": "security"},
                )
                workflow_id = result["workflow_id"]
                ```
            """
            if params is None:
                params = {}
            try:
                # Determine repos to process
                if repos is not None:
                    target_repos = repos
                elif tag is not None:
                    target_repos = self.app.get_repos(tag=tag, user_id=user_id)
                else:
                    target_repos = self.app.get_repos(user_id=user_id)

                # Create task specification
                task = {
                    "type": task_type,
                    "params": params,
                    "id": f"{task_type}_{adapter}_{len(target_repos)}_repos",
                }

                # Execute workflow with timeout if specified
                if timeout:
                    result = await asyncio.wait_for(
                        self.app.execute_workflow_parallel(
                            task, adapter, target_repos, user_id=user_id
                        ),
                        timeout=timeout,
                    )
                else:
                    result = await self.app.execute_workflow_parallel(
                        task, adapter, target_repos, user_id=user_id
                    )

                return {
                    "workflow_id": result.get("workflow_id", "unknown"),
                    "status": result.get("status", "unknown"),
                    "result": result,
                    "repos_processed": result.get("repos_processed", 0),
                    "successful_repos": result.get("successful_repos", 0),
                    "failed_repos": result.get("failed_repos", 0),
                    "execution_time": result.get("execution_time_seconds"),
                    "errors": result.get("errors", []),
                }
            except TimeoutError:
                # Create a workflow ID for the timeout case
                import uuid

                timeout_workflow_id = f"wf_timeout_{uuid.uuid4().hex[:8]}_{task_type}"

                # Update workflow state to reflect timeout
                await self.app.workflow_state_manager.create(
                    workflow_id=timeout_workflow_id,
                    task={"type": task_type, "params": params},
                    repos=target_repos,
                )
                await self.app.workflow_state_manager.update(
                    workflow_id=timeout_workflow_id,
                    status="failed",
                    error="Workflow timed out",
                    completed_at=asyncio.get_event_loop().time(),
                )

                return {
                    "workflow_id": timeout_workflow_id,
                    "status": "failed",
                    "result": {"error": "Workflow timed out"},
                    "repos_processed": 0,
                    "successful_repos": 0,
                    "failed_repos": len(target_repos),
                    "execution_time": timeout,
                    "errors": [{"error": "Operation timed out", "type": "TimeoutError"}],
                }
            except Exception as e:
                # Create a workflow ID for the error case
                import uuid

                error_workflow_id = f"wf_error_{uuid.uuid4().hex[:8]}_{task_type}"

                # Update the workflow state to reflect error
                with suppress(Exception):
                    # If we can't update the workflow state, continue with the response
                    task_for_state = {"type": task_type, "params": params}
                    await self.app.workflow_state_manager.create(
                        workflow_id=error_workflow_id,
                        task=task_for_state,
                        repos=target_repos if "target_repos" in locals() else [],
                    )
                    await self.app.workflow_state_manager.update(
                        workflow_id=error_workflow_id,
                        status="failed",
                        error=str(e),
                        completed_at=asyncio.get_event_loop().time(),
                    )

                return {
                    "workflow_id": error_workflow_id,
                    "status": "failed",
                    "result": {"error": str(e)},
                    "repos_processed": 0,
                    "successful_repos": 0,
                    "failed_repos": len(target_repos) if "target_repos" in locals() else 0,
                    "execution_time": 0,
                    "errors": [{"error": str(e), "type": type(e).__name__}],
                }

        @server.tool()
        async def get_workflow_status(
            workflow_id: str, user_id: str | None = None
        ) -> dict[str, Any]:
            """Get status of a workflow execution."""
            try:
                workflow_state = await self.app.workflow_state_manager.get(workflow_id)

                if workflow_state is None:
                    return {
                        "workflow_id": workflow_id,
                        "status": "not_found",
                        "error": f"Workflow {workflow_id} not found",
                        "timestamp": asyncio.get_event_loop().time(),
                    }

                # Check if user has permission to view workflow status
                if user_id:
                    # Check if user has permission to view workflow status
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id, "*", Permission.VIEW_WORKFLOW_STATUS
                    )
                    if not has_permission:
                        return {
                            "workflow_id": workflow_id,
                            "status": "forbidden",
                            "error": f"User {user_id} does not have permission to view workflow status",
                            "timestamp": asyncio.get_event_loop().time(),
                        }

                return {
                    "workflow_id": workflow_id,
                    "status": workflow_state.get("status", "unknown"),
                    "progress": workflow_state.get("progress", 0),
                    "repos_processed": len(workflow_state.get("repos", [])),
                    "task_type": workflow_state.get("task", {}).get("type", "unknown"),
                    "created_at": workflow_state.get("created_at"),
                    "updated_at": workflow_state.get("updated_at"),
                    "completed_at": workflow_state.get("completed_at"),
                    "results_count": len(workflow_state.get("results", [])),
                    "errors_count": len(workflow_state.get("errors", [])),
                    "execution_time": workflow_state.get("execution_time_seconds"),
                }
            except Exception as e:
                return {
                    "workflow_id": workflow_id,
                    "status": "error",
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time(),
                }

        @server.tool()
        async def list_workflows(
            status: str | None = None,
            limit: int = 10,
            offset: int = 0,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            """List workflows with optional filtering."""
            try:
                from ..core.workflow_state import WorkflowStatus

                # Check if user has permission to list workflows
                if user_id:
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id,
                        "*",
                        Permission.LIST_WORKFLOWS,  # "*" represents any repo for this permission
                    )
                    if not has_permission:
                        return {
                            "status": "error",
                            "error": f"User {user_id} does not have permission to list workflows",
                            "workflows": [],
                            "total_count": 0,
                        }

                # Convert status string to enum if provided
                status_enum = None
                if status:
                    try:
                        status_enum = WorkflowStatus(status)
                    except ValueError:
                        return {
                            "status": "error",
                            "error": f"Invalid status: {status}. Valid statuses: {[s.value for s in WorkflowStatus]}",
                            "workflows": [],
                            "total_count": 0,
                        }

                # Get workflows from the state manager
                workflows = await self.app.workflow_state_manager.list_workflows(
                    status=status_enum, limit=limit
                )

                # Apply offset for pagination
                workflows = workflows[offset:]

                return {
                    "status": "success",
                    "workflows": workflows,
                    "total_count": len(workflows),
                    "returned_count": len(workflows),
                    "limit": limit,
                    "offset": offset,
                    "status_filter": status,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to list workflows: {e}",
                    "workflows": [],
                    "total_count": 0,
                }

        @server.tool()
        async def cancel_workflow(workflow_id: str, user_id: str | None = None) -> dict[str, Any]:
            """Cancel a running workflow."""
            try:
                # Check if user has permission to cancel workflows
                if user_id:
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id, "*", Permission.CANCEL_WORKFLOW
                    )
                    if not has_permission:
                        return {
                            "workflow_id": workflow_id,
                            "status": "forbidden",
                            "error": f"User {user_id} does not have permission to cancel workflows",
                        }

                # Update the workflow state to cancelled
                await self.app.workflow_state_manager.update(
                    workflow_id=workflow_id,
                    status="cancelled",
                    cancelled_at=asyncio.get_event_loop().time(),
                )

                return {
                    "workflow_id": workflow_id,
                    "status": "cancelled",
                    "message": f"Workflow {workflow_id} has been cancelled",
                }
            except Exception as e:
                return {
                    "workflow_id": workflow_id,
                    "status": "error",
                    "error": f"Failed to cancel workflow: {e}",
                }

        @server.tool()
        async def create_user(
            user_id: str,
            roles: list[str],
            allowed_repos: list[str] | None = None,
            user_id_caller: str | None = None,  # ID of the user making the call
        ) -> dict[str, Any]:
            """Create a new user with specified roles."""
            try:
                # Check if caller has permission to manage users
                if user_id_caller:
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id_caller,
                        "*",
                        Permission.MANAGE_WORKFLOWS,  # Using MANAGE_WORKFLOWS as proxy for admin rights
                    )
                    if not has_permission:
                        return {
                            "status": "forbidden",
                            "error": f"User {user_id_caller} does not have permission to create users",
                        }

                # Create the user
                user = await self.app.rbac_manager.create_user(user_id, roles, allowed_repos)

                return {
                    "status": "success",
                    "user_id": user.user_id,
                    "roles": [role.name for role in user.roles],
                    "allowed_repos": allowed_repos,
                    "message": f"User {user_id} created successfully",
                }
            except Exception as e:
                return {"status": "error", "error": str(e), "message": "Failed to create user"}

        @server.tool()
        async def check_permission(user_id: str, repo: str, permission: str) -> dict[str, Any]:
            """Check if a user has a specific permission for a repository."""
            try:
                # Convert string permission to enum
                try:
                    perm_enum = Permission(permission)
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Invalid permission: {permission}",
                        "valid_permissions": [p.value for p in Permission],
                        "has_permission": False,
                    }

                has_permission = await self.app.rbac_manager.check_permission(
                    user_id, repo, perm_enum
                )

                return {
                    "user_id": user_id,
                    "repo": repo,
                    "permission": permission,
                    "has_permission": has_permission,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to check permission: {e}",
                    "has_permission": False,
                }

        @server.tool()
        async def get_observability_metrics() -> dict[str, Any]:
            """Get current observability metrics from the system."""
            try:
                if not self.app.observability:
                    return {"error": "Observability system not initialized", "metrics": {}}

                # Get performance metrics
                perf_metrics = self.app.observability.get_performance_metrics()

                # Get recent logs
                recent_logs = self.app.observability.get_logs(limit=50)

                return {
                    "status": "success",
                    "performance_metrics": perf_metrics,
                    "recent_logs_count": len(recent_logs),
                    "recent_logs_preview": [
                        {
                            "timestamp": log.timestamp.isoformat(),
                            "level": log.level.value,
                            "message": log.message,
                            "attributes": log.attributes,
                        }
                        for log in recent_logs[-10:]  # Last 10 logs
                    ],
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                return {"error": f"Failed to get observability metrics: {e}", "metrics": {}}

        @server.tool()
        async def search_logs(
            query: str | None = None,
            level: str | None = None,
            workflow_id: str | None = None,
            repo_path: str | None = None,
            start_time: str | None = None,
            end_time: str | None = None,
            size: int = 100,
        ) -> dict[str, Any]:
            """Search logs with various filters."""
            try:
                logs = await self.app.opensearch_integration.search_logs(
                    query=query,
                    level=level,
                    workflow_id=workflow_id,
                    repo_path=repo_path,
                    start_time=start_time,
                    end_time=end_time,
                    size=size,
                )

                return {
                    "status": "success",
                    "logs": logs,
                    "total_found": len(logs),
                    "query_params": {
                        "query": query,
                        "level": level,
                        "workflow_id": workflow_id,
                        "repo_path": repo_path,
                        "start_time": start_time,
                        "end_time": end_time,
                        "size": size,
                    },
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to search logs: {e}", "logs": []}

        @server.tool()
        async def search_workflows(
            workflow_id: str | None = None,
            adapter: str | None = None,
            task_type: str | None = None,
            status: str | None = None,
            start_time: str | None = None,
            end_time: str | None = None,
            size: int = 100,
        ) -> dict[str, Any]:
            """Search workflows with various filters."""
            try:
                workflows = await self.app.opensearch_integration.search_workflows(
                    workflow_id=workflow_id,
                    adapter=adapter,
                    task_type=task_type,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    size=size,
                )

                return {
                    "status": "success",
                    "workflows": workflows,
                    "total_found": len(workflows),
                    "query_params": {
                        "workflow_id": workflow_id,
                        "adapter": adapter,
                        "task_type": task_type,
                        "status": status,
                        "start_time": start_time,
                        "end_time": end_time,
                        "size": size,
                    },
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to search workflows: {e}",
                    "workflows": [],
                }

        @server.tool()
        async def get_workflow_statistics() -> dict[str, Any]:
            """Get workflow statistics and analytics."""
            try:
                stats = await self.app.opensearch_integration.get_workflow_stats()

                return {"status": "success", "statistics": stats}
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get workflow statistics: {e}",
                    "statistics": {},
                }

        @server.tool()
        async def get_log_statistics() -> dict[str, Any]:
            """Get log statistics and analytics."""
            try:
                stats = await self.app.opensearch_integration.get_log_stats()

                return {"status": "success", "statistics": stats}
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get log statistics: {e}",
                    "statistics": {},
                }

        @server.tool()
        async def get_recovery_metrics() -> dict[str, Any]:
            """Get metrics about error recovery and resilience operations."""
            try:
                metrics = await self.app.error_recovery_manager.get_recovery_metrics()

                return {"status": "success", "metrics": metrics}
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get recovery metrics: {e}",
                    "metrics": {},
                }

        @server.tool()
        async def create_backup(
            backup_type: str = "full", backup_id: str | None = None
        ) -> dict[str, Any]:
            """Create a backup of the system."""
            try:
                from ..core.backup_recovery import BackupManager

                backup_manager = BackupManager(self.app)

                backup_info = await backup_manager.create_backup(backup_type)

                return {
                    "status": "success",
                    "backup_id": backup_info.backup_id,
                    "location": backup_info.location,
                    "size_bytes": backup_info.size_bytes,
                    "timestamp": backup_info.timestamp.isoformat(),
                    "message": f"Backup {backup_info.backup_id} created successfully",
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to create backup: {e}"}

        @server.tool()
        async def list_backups() -> dict[str, Any]:
            """List all available backups."""
            try:
                from ..core.backup_recovery import BackupManager

                backup_manager = BackupManager(self.app)

                backups = await backup_manager.list_backups()

                return {
                    "status": "success",
                    "backups": [
                        {
                            "backup_id": b.backup_id,
                            "timestamp": b.timestamp.isoformat(),
                            "size_bytes": b.size_bytes,
                            "location": b.location,
                            "status": b.status,
                        }
                        for b in backups
                    ],
                    "total_count": len(backups),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to list backups: {e}",
                    "backups": [],
                }

        @server.tool()
        async def restore_backup(backup_id: str) -> dict[str, Any]:
            """Restore from a backup."""
            try:
                from ..core.backup_recovery import BackupManager

                backup_manager = BackupManager(self.app)

                success = await backup_manager.restore_backup(backup_id)

                return {
                    "status": "success" if success else "error",
                    "backup_id": backup_id,
                    "message": f"Restore {'completed' if success else 'failed'} for backup {backup_id}",
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to restore backup: {e}"}

        @server.tool()
        async def run_disaster_recovery_check() -> dict[str, Any]:
            """Run a disaster recovery check."""
            try:
                from ..core.backup_recovery import DisasterRecoveryManager

                dr_manager = DisasterRecoveryManager(self.app)

                results = await dr_manager.run_disaster_recovery_check()

                return {"status": "success", "results": results}
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to run disaster recovery check: {e}",
                }

        @server.tool()
        async def heal_workflows() -> dict[str, Any]:
            """Manually trigger healing of failed workflows."""
            try:
                await self.app.error_recovery_manager.monitor_and_heal_workflows()

                return {"status": "success", "message": "Healing process initiated"}
            except Exception as e:
                return {"status": "error", "error": f"Failed to initiate healing: {e}"}

        @server.tool()
        async def get_monitoring_dashboard() -> dict[str, Any]:
            """Get comprehensive monitoring dashboard data.

            Compatibility wrapper around the canonical ecosystem status report.
            """
            try:
                from ..core.ecosystem_status import EcosystemStatusService

                service = EcosystemStatusService(
                    recovery_provider=(
                        self.app if hasattr(self.app, "get_recovery_summary") else None
                    )
                )
                report = await service.generate_report()
                return {
                    "status": "success",
                    "ecosystem_status": report.model_dump(mode="json"),
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to get monitoring dashboard: {e}"}

        @server.tool()
        async def get_active_alerts() -> dict[str, Any]:
            """Get all active (non-acknowledged) alerts."""
            try:
                if not self.app.monitoring_service or not self.app.monitoring_service.alert_manager:
                    return {"status": "error", "error": "Monitoring service not initialized"}

                active_alerts = await self.app.monitoring_service.alert_manager.get_active_alerts()

                return {
                    "status": "success",
                    "alerts": [
                        {
                            "id": alert.id,
                            "timestamp": alert.timestamp.isoformat(),
                            "severity": alert.severity.value,
                            "type": alert.type.value,
                            "title": alert.title,
                            "description": alert.description,
                            "details": alert.details,
                        }
                        for alert in active_alerts
                    ],
                    "count": len(active_alerts),
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to get active alerts: {e}"}

        @server.tool()
        async def acknowledge_alert(alert_id: str, user: str) -> dict[str, Any]:
            """Acknowledge an alert."""
            try:
                if not self.app.monitoring_service:
                    return {"status": "error", "error": "Monitoring service not initialized"}

                success = await self.app.monitoring_service.acknowledge_alert(alert_id, user)

                return {
                    "status": "success" if success else "error",
                    "message": f"Alert {alert_id} {'acknowledged' if success else 'failed to acknowledge'} by {user}",
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to acknowledge alert: {e}"}

        @server.tool()
        async def trigger_test_alert(
            severity: str = "medium",
            title: str = "Test Alert",
            description: str = "This is a test alert",
        ) -> dict[str, Any]:
            """Trigger a test alert for testing purposes."""
            try:
                if not self.app.monitoring_service or not self.app.monitoring_service.alert_manager:
                    return {"status": "error", "error": "Monitoring service not initialized"}

                from ..core.monitoring import AlertSeverity, AlertType

                # Convert string severity to enum
                try:
                    severity_enum = AlertSeverity(severity.lower())
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Invalid severity: {severity}. Valid values: low, medium, high, critical",
                    }

                alert = await self.app.monitoring_service.alert_manager.trigger_alert(
                    severity=severity_enum,
                    alert_type=AlertType.SYSTEM_HEALTH,
                    title=title,
                    description=description,
                    details={"test_alert": True},
                )

                return {
                    "status": "success",
                    "alert_id": alert.id,
                    "message": f"Test alert created with ID: {alert.id}",
                }
            except Exception as e:
                return {"status": "error", "error": f"Failed to trigger test alert: {e}"}

        @server.tool()
        async def flush_metrics() -> dict[str, Any]:
            """Force flush all pending metrics to exporters."""
            try:
                if not self.app.observability:
                    return {
                        "status": "warning",
                        "message": "Observability system not initialized, nothing to flush",
                    }

                await self.app.observability.flush_metrics()

                return {"status": "success", "message": "Metrics flushed successfully"}
            except Exception as e:
                return {"status": "error", "error": f"Failed to flush metrics: {e}"}

        @server.tool()
        async def list_adapters() -> dict[str, Any]:
            """List available adapters."""
            adapters_info = {}
            for name, adapter in self.app.adapters.items():
                try:
                    health = await adapter.get_health()
                    # Get additional adapter-specific information
                    adapter_details = {
                        "enabled": True,
                        "health": health,
                        "type": type(adapter).__name__,
                        "features": [],  # This could be expanded based on adapter capabilities
                    }

                    # Add specific features based on adapter type
                    if name == "llamaindex":
                        adapter_details["features"] = [
                            "RAG",
                            "Document Ingestion",
                            "Semantic Search",
                        ]
                    elif name == "prefect":
                        adapter_details["features"] = [
                            "Workflow Orchestration",
                            "Task Scheduling",
                            "State Management",
                        ]
                    elif name == "agno":
                        adapter_details["features"] = [
                            "AI Agents",
                            "Multi-Agent Systems",
                            "Tool Integration",
                        ]

                    adapters_info[name] = adapter_details
                except Exception as e:
                    adapters_info[name] = {
                        "enabled": True,
                        "health": {"status": "unhealthy", "error": str(e)},
                        "type": type(adapter).__name__ if "adapter" in locals() else "Unknown",
                        "features": [],
                    }

            return {
                "adapters": adapters_info,
                "count": len(adapters_info),
                "available_names": list(adapters_info.keys()),
            }

        @server.tool()
        async def get_health() -> dict[str, Any]:
            """Get overall health status of the system."""
            try:
                app_healthy = await self.app.is_healthy()

                # Check individual adapter health
                adapter_health = {}
                for name, adapter in self.app.adapters.items():
                    try:
                        health = await adapter.get_health()
                        adapter_health[name] = health
                    except Exception as e:
                        adapter_health[name] = {"status": "unhealthy", "error": str(e)}

                # Check workflow state manager health
                try:
                    # Attempt to list a few workflows as a health check
                    recent_workflows = await self.app.workflow_state_manager.list_workflows(limit=1)
                    workflow_state_healthy = True
                    workflow_state_info = {
                        "status": "healthy",
                        "recent_workflows_count": len(recent_workflows),
                    }
                except Exception as e:
                    workflow_state_healthy = False
                    workflow_state_info = {"status": "unhealthy", "error": str(e)}

                # Check RBAC manager health
                try:
                    # Check if default roles are loaded
                    rbac_healthy = len(self.app.rbac_manager.roles) > 0
                    rbac_info = {
                        "status": "healthy" if rbac_healthy else "unhealthy",
                        "default_roles_count": len(self.app.rbac_manager.roles),
                        "admin_role_exists": "admin" in self.app.rbac_manager.roles,
                    }
                except Exception as e:
                    rbac_healthy = False
                    rbac_info = {"status": "unhealthy", "error": str(e)}

                # Check OpenSearch integration health
                try:
                    opensearch_health = await self.app.opensearch_integration.health_check()
                    opensearch_healthy = opensearch_health.get("status") == "healthy"
                    opensearch_info = opensearch_health
                except Exception as e:
                    opensearch_healthy = False
                    opensearch_info = {"status": "unhealthy", "error": str(e)}

                overall_status = "healthy"
                health_components = [
                    app_healthy,
                    workflow_state_healthy,
                    rbac_healthy,
                    opensearch_healthy,
                ]

                if not all(health_components) or any(
                    h.get("status") == "unhealthy" for h in adapter_health.values()
                ):
                    overall_status = "unhealthy"
                elif any(h.get("status") == "degraded" for h in adapter_health.values()):
                    overall_status = "degraded"

                return {
                    "status": overall_status,
                    "app_healthy": app_healthy,
                    "workflow_state_healthy": workflow_state_healthy,
                    "rbac_healthy": rbac_healthy,
                    "opensearch_healthy": opensearch_healthy,
                    "adapter_health": adapter_health,
                    "workflow_state_info": workflow_state_info,
                    "rbac_info": rbac_info,
                    "opensearch_info": opensearch_info,
                    "timestamp": asyncio.get_event_loop().time(),
                }
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time(),
                }

        @server.tool()
        async def get_tool_versions(
            tool_name: str | None = None,
        ) -> dict[str, Any]:
            """Get version metadata for MCP tools."""
            from mahavishnu.mcp.tool_versions import TOOL_VERSIONS, get_tool_version

            if tool_name:
                version = get_tool_version(tool_name)
                if version is None:
                    return {
                        "status": "not_found",
                        "tool_name": tool_name,
                        "error": f"Tool '{tool_name}' not in version registry",
                    }
                return {
                    "status": "success",
                    "tool_name": tool_name,
                    "version": version,
                }

            return {
                "status": "success",
                "versions": dict(TOOL_VERSIONS),
                "total_tools": len(TOOL_VERSIONS),
                "server_version": __version__,
            }

        @server.tool()
        async def discover_tools(query: str | None = None) -> dict[str, Any]:
            """Search for available MCP tools by name or capability."""
            from mahavishnu.mcp.tool_versions import TOOL_VERSIONS
            from mahavishnu.mcp.tools.profiles import (
                FULL_REGISTRATIONS,
                PROFILE_REGISTRATIONS,
                get_active_profile,
            )

            profile = get_active_profile()

            # Collect names of currently registered tools from the FastMCP
            # server via the public 3.x introspection API. The previous
            # private-attribute poke (``_tool_manager``, ``_tools``) was
            # broken by FastMCP 3.x and returned stale data.
            try:
                registered_names = {t.name for t in await server.list_tools()}
            except Exception:
                registered_names = set()

            # All known tools from the version registry
            all_known = set(TOOL_VERSIONS.keys())

            # Apply query filter
            if query:
                q = query.lower()
                all_known = {n for n in all_known if q in n.lower()}
                registered_names = {n for n in registered_names if q in n.lower()}

            not_loaded = sorted(all_known - registered_names)
            loaded = sorted(registered_names & all_known)

            # Profile information
            profile_methods = PROFILE_REGISTRATIONS.get(profile, FULL_REGISTRATIONS)

            return {
                "status": "success",
                "profile": profile.value,
                "query": query,
                "loaded_tools": loaded,
                "loaded_count": len(loaded),
                "not_loaded_tools": not_loaded,
                "not_loaded_count": len(not_loaded),
                "total_known": len(all_known),
                "profile_methods_scheduled": profile_methods,
                "hint": (
                    "Set MAHAVISHNU_TOOL_PROFILE=full to load all tools, "
                    "or switch to 'standard' for daily development."
                ),
            }

    async def start(self, host: str = "127.0.0.1", port: int = 3000):
        """Start the MCP server."""
        await _start_server_helper(self, host=host, port=port)

    async def stop(self) -> None:
        """Stop the MCP server and cleanup resources."""
        await _stop_server_helper(self)

    async def register_worktree_tools(self):
        """Register worktree management tools."""
        await _register_worktree_tools_helper(self)


async def run_server(config=None):
    """Run the MCP server."""
    server = FastMCPServer(config)
    await server.start()
