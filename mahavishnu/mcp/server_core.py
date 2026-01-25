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
            user_id: Optional[str] = None
        ) -> Dict[str, Any]:
            """List repositories with optional filtering and pagination.

            Args:
                tag: Optional tag to filter repos
                limit: Optional limit on number of results
                offset: Optional offset for pagination
                user_id: Optional user ID for permission checking

            Returns:
                Dictionary with list of repositories and metadata
            """
            try:
                repos = self.app.get_repos(tag=tag, user_id=user_id)

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
                    "total_count": len(self.app.get_repos(user_id=user_id)),
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
            user_id: Optional[str] = None
        ) -> Dict[str, Any]:
            """Trigger workflow execution.

            Args:
                adapter: Adapter name (langgraph, prefect, agno)
                task_type: Type of workflow (code_sweep, quality_check)
                params: Additional parameters for the task
                tag: Optional tag to filter repos
                repos: Optional explicit repo list (overrides tag)
                timeout: Optional timeout in seconds
                user_id: Optional user ID for permission checking

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
                    target_repos = self.app.get_repos(tag=tag, user_id=user_id)
                else:
                    target_repos = self.app.get_repos(user_id=user_id)

                # Create task specification
                task = {
                    "type": task_type,
                    "params": params,
                    "id": f"{task_type}_{adapter}_{len(target_repos)}_repos"
                }

                # Execute workflow with timeout if specified
                if timeout:
                    result = await asyncio.wait_for(
                        self.app.execute_workflow_parallel(task, adapter, target_repos, user_id=user_id),
                        timeout=timeout
                    )
                else:
                    result = await self.app.execute_workflow_parallel(task, adapter, target_repos, user_id=user_id)

                return {
                    "workflow_id": result.get("workflow_id", "unknown"),
                    "status": result.get("status", "unknown"),
                    "result": result,
                    "repos_processed": result.get("repos_processed", 0),
                    "successful_repos": result.get("successful_repos", 0),
                    "failed_repos": result.get("failed_repos", 0),
                    "execution_time": result.get("execution_time_seconds"),
                    "errors": result.get("errors", [])
                }
            except asyncio.TimeoutError:
                # Create a workflow ID for the timeout case
                import uuid
                timeout_workflow_id = f"wf_timeout_{uuid.uuid4().hex[:8]}_{task_type}"

                # Update workflow state to reflect timeout
                await self.app.workflow_state_manager.create(
                    workflow_id=timeout_workflow_id,
                    task={"type": task_type, "params": params},
                    repos=target_repos
                )
                await self.app.workflow_state_manager.update(
                    workflow_id=timeout_workflow_id,
                    status="failed",
                    error="Workflow timed out",
                    completed_at=asyncio.get_event_loop().time()
                )

                return {
                    "workflow_id": timeout_workflow_id,
                    "status": "failed",
                    "result": {"error": "Workflow timed out"},
                    "repos_processed": 0,
                    "successful_repos": 0,
                    "failed_repos": len(target_repos),
                    "execution_time": timeout,
                    "errors": [{"error": "Operation timed out", "type": "TimeoutError"}]
                }
            except Exception as e:
                # Create a workflow ID for the error case
                import uuid
                error_workflow_id = f"wf_error_{uuid.uuid4().hex[:8]}_{task_type}"

                # Update workflow state to reflect error
                try:
                    task_for_state = {"type": task_type, "params": params}
                    await self.app.workflow_state_manager.create(
                        workflow_id=error_workflow_id,
                        task=task_for_state,
                        repos=target_repos if 'target_repos' in locals() else []
                    )
                    await self.app.workflow_state_manager.update(
                        workflow_id=error_workflow_id,
                        status="failed",
                        error=str(e),
                        completed_at=asyncio.get_event_loop().time()
                    )
                except Exception:
                    # If we can't update the workflow state, continue with the response
                    pass

                return {
                    "workflow_id": error_workflow_id,
                    "status": "failed",
                    "result": {"error": str(e)},
                    "repos_processed": 0,
                    "successful_repos": 0,
                    "failed_repos": len(target_repos) if 'target_repos' in locals() else 0,
                    "execution_time": 0,
                    "errors": [{"error": str(e), "type": type(e).__name__}]
                }

        @server.tool()
        async def get_workflow_status(workflow_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
            """Get status of a workflow execution.

            Args:
                workflow_id: ID of the workflow to check
                user_id: Optional user ID for permission checking

            Returns:
                Status information for the workflow
            """
            try:
                workflow_state = await self.app.workflow_state_manager.get(workflow_id)

                if workflow_state is None:
                    return {
                        "workflow_id": workflow_id,
                        "status": "not_found",
                        "error": f"Workflow {workflow_id} not found",
                        "timestamp": asyncio.get_event_loop().time()
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
                            "timestamp": asyncio.get_event_loop().time()
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
                    "execution_time": workflow_state.get("execution_time_seconds")
                }
            except Exception as e:
                return {
                    "workflow_id": workflow_id,
                    "status": "error",
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time()
                }

        @server.tool()
        async def list_workflows(
            status: Optional[str] = None,
            limit: int = 10,
            offset: int = 0,
            user_id: Optional[str] = None
        ) -> Dict[str, Any]:
            """List workflows with optional filtering.

            Args:
                status: Optional status to filter workflows (pending, running, completed, failed)
                limit: Maximum number of workflows to return
                offset: Offset for pagination
                user_id: Optional user ID for permission checking

            Returns:
                List of workflow information
            """
            try:
                from ..core.workflow_state import WorkflowStatus

                # Check if user has permission to list workflows
                if user_id:
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id, "*", Permission.LIST_WORKFLOWS  # "*" represents any repo for this permission
                    )
                    if not has_permission:
                        return {
                            "error": f"User {user_id} does not have permission to list workflows",
                            "workflows": [],
                            "total_count": 0
                        }

                # Convert status string to enum if provided
                status_enum = None
                if status:
                    try:
                        status_enum = WorkflowStatus(status)
                    except ValueError:
                        return {
                            "error": f"Invalid status: {status}. Valid statuses: {[s.value for s in WorkflowStatus]}",
                            "workflows": [],
                            "total_count": 0
                        }

                # Get workflows from the state manager
                workflows = await self.app.workflow_state_manager.list_workflows(
                    status=status_enum,
                    limit=limit
                )

                # Apply offset for pagination
                workflows = workflows[offset:]

                return {
                    "workflows": workflows,
                    "total_count": len(workflows),
                    "returned_count": len(workflows),
                    "limit": limit,
                    "offset": offset,
                    "status_filter": status
                }
            except Exception as e:
                return {
                    "error": f"Failed to list workflows: {str(e)}",
                    "workflows": [],
                    "total_count": 0
                }

        @server.tool()
        async def cancel_workflow(workflow_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
            """Cancel a running workflow.

            Args:
                workflow_id: ID of the workflow to cancel
                user_id: Optional user ID for permission checking

            Returns:
                Result of cancellation attempt
            """
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
                            "error": f"User {user_id} does not have permission to cancel workflows"
                        }

                # Update the workflow state to cancelled
                await self.app.workflow_state_manager.update(
                    workflow_id=workflow_id,
                    status="cancelled",
                    cancelled_at=asyncio.get_event_loop().time()
                )

                return {
                    "workflow_id": workflow_id,
                    "status": "cancelled",
                    "message": f"Workflow {workflow_id} has been cancelled"
                }
            except Exception as e:
                return {
                    "workflow_id": workflow_id,
                    "status": "error",
                    "error": f"Failed to cancel workflow: {str(e)}"
                }

        @server.tool()
        async def create_user(
            user_id: str,
            roles: List[str],
            allowed_repos: Optional[List[str]] = None,
            user_id_caller: Optional[str] = None  # ID of the user making the call
        ) -> Dict[str, Any]:
            """Create a new user with specified roles.

            Args:
                user_id: Unique identifier for the new user
                roles: List of role names to assign to the user
                allowed_repos: Optional list of repositories the user can access
                user_id_caller: ID of the user making this request (for permission check)

            Returns:
                Result of the user creation operation
            """
            try:
                # Check if caller has permission to manage users
                if user_id_caller:
                    has_permission = await self.app.rbac_manager.check_permission(
                        user_id_caller, "*", Permission.MANAGE_WORKFLOWS  # Using MANAGE_WORKFLOWS as proxy for admin rights
                    )
                    if not has_permission:
                        return {
                            "status": "forbidden",
                            "error": f"User {user_id_caller} does not have permission to create users"
                        }

                # Create the user
                user = await self.app.rbac_manager.create_user(user_id, roles, allowed_repos)

                return {
                    "status": "success",
                    "user_id": user.user_id,
                    "roles": [role.name for role in user.roles],
                    "allowed_repos": allowed_repos,
                    "message": f"User {user_id} created successfully"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to create user"
                }

        @server.tool()
        async def check_permission(
            user_id: str,
            repo: str,
            permission: str
        ) -> Dict[str, Any]:
            """Check if a user has a specific permission for a repository.

            Args:
                user_id: ID of the user to check
                repo: Repository path to check permission for
                permission: Permission to check (READ_REPO, EXECUTE_WORKFLOW, etc.)

            Returns:
                Boolean result of the permission check
            """
            try:
                # Convert string permission to enum
                try:
                    perm_enum = Permission(permission)
                except ValueError:
                    return {
                        "error": f"Invalid permission: {permission}",
                        "valid_permissions": [p.value for p in Permission],
                        "has_permission": False
                    }

                has_permission = await self.app.rbac_manager.check_permission(user_id, repo, perm_enum)

                return {
                    "user_id": user_id,
                    "repo": repo,
                    "permission": permission,
                    "has_permission": has_permission
                }
            except Exception as e:
                return {
                    "error": f"Failed to check permission: {str(e)}",
                    "has_permission": False
                }

        @server.tool()
        async def get_observability_metrics() -> Dict[str, Any]:
            """Get current observability metrics from the system.

            Returns:
                Dictionary with current metrics and performance data
            """
            try:
                if not self.app.observability:
                    return {
                        "error": "Observability system not initialized",
                        "metrics": {}
                    }

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
                            "attributes": log.attributes
                        }
                        for log in recent_logs[-10:]  # Last 10 logs
                    ],
                    "timestamp": datetime.now().isoformat()
                }
            except Exception as e:
                return {
                    "error": f"Failed to get observability metrics: {str(e)}",
                    "metrics": {}
                }

        @server.tool()
        async def search_logs(
            query: Optional[str] = None,
            level: Optional[str] = None,
            workflow_id: Optional[str] = None,
            repo_path: Optional[str] = None,
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            size: int = 100
        ) -> Dict[str, Any]:
            """Search logs with various filters.

            Args:
                query: Text query to search for
                level: Log level filter (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                workflow_id: Filter by workflow ID
                repo_path: Filter by repository path
                start_time: Filter logs after this time (ISO format)
                end_time: Filter logs before this time (ISO format)
                size: Maximum number of results to return

            Returns:
                List of matching log entries
            """
            try:
                logs = await self.app.opensearch_integration.search_logs(
                    query=query,
                    level=level,
                    workflow_id=workflow_id,
                    repo_path=repo_path,
                    start_time=start_time,
                    end_time=end_time,
                    size=size
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
                        "size": size
                    }
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to search logs: {str(e)}",
                    "logs": []
                }

        @server.tool()
        async def search_workflows(
            workflow_id: Optional[str] = None,
            adapter: Optional[str] = None,
            task_type: Optional[str] = None,
            status: Optional[str] = None,
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            size: int = 100
        ) -> Dict[str, Any]:
            """Search workflows with various filters.

            Args:
                workflow_id: Specific workflow ID to search for
                adapter: Filter by adapter (prefect, agno, llamaindex)
                task_type: Filter by task type
                status: Filter by workflow status (pending, running, completed, failed)
                start_time: Filter workflows after this time (ISO format)
                end_time: Filter workflows before this time (ISO format)
                size: Maximum number of results to return

            Returns:
                List of matching workflow entries
            """
            try:
                workflows = await self.app.opensearch_integration.search_workflows(
                    workflow_id=workflow_id,
                    adapter=adapter,
                    task_type=task_type,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    size=size
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
                        "size": size
                    }
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to search workflows: {str(e)}",
                    "workflows": []
                }

        @server.tool()
        async def get_workflow_statistics() -> Dict[str, Any]:
            """Get workflow statistics and analytics.

            Returns:
                Statistics about workflow execution
            """
            try:
                stats = await self.app.opensearch_integration.get_workflow_stats()

                return {
                    "status": "success",
                    "statistics": stats
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get workflow statistics: {str(e)}",
                    "statistics": {}
                }

        @server.tool()
        async def get_log_statistics() -> Dict[str, Any]:
            """Get log statistics and analytics.

            Returns:
                Statistics about logged events
            """
            try:
                stats = await self.app.opensearch_integration.get_log_stats()

                return {
                    "status": "success",
                    "statistics": stats
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get log statistics: {str(e)}",
                    "statistics": {}
                }

        @server.tool()
        async def get_recovery_metrics() -> Dict[str, Any]:
            """Get metrics about error recovery and resilience operations.

            Returns:
                Statistics about recovery operations
            """
            try:
                metrics = await self.app.error_recovery_manager.get_recovery_metrics()

                return {
                    "status": "success",
                    "metrics": metrics
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get recovery metrics: {str(e)}",
                    "metrics": {}
                }

        @server.tool()
        async def create_backup(
            backup_type: str = "full",
            backup_id: Optional[str] = None
        ) -> Dict[str, Any]:
            """Create a backup of the system.

            Args:
                backup_type: Type of backup (full, incremental, config)
                backup_id: Optional custom backup ID

            Returns:
                Status of the backup operation
            """
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
                    "message": f"Backup {backup_info.backup_id} created successfully"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to create backup: {str(e)}"
                }

        @server.tool()
        async def list_backups() -> Dict[str, Any]:
            """List all available backups.

            Returns:
                List of available backups
            """
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
                            "status": b.status
                        }
                        for b in backups
                    ],
                    "total_count": len(backups)
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to list backups: {str(e)}",
                    "backups": []
                }

        @server.tool()
        async def restore_backup(backup_id: str) -> Dict[str, Any]:
            """Restore from a backup.

            Args:
                backup_id: ID of the backup to restore

            Returns:
                Status of the restore operation
            """
            try:
                from ..core.backup_recovery import BackupManager
                backup_manager = BackupManager(self.app)

                success = await backup_manager.restore_backup(backup_id)

                return {
                    "status": "success" if success else "error",
                    "backup_id": backup_id,
                    "message": f"Restore {'completed' if success else 'failed'} for backup {backup_id}"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to restore backup: {str(e)}"
                }

        @server.tool()
        async def run_disaster_recovery_check() -> Dict[str, Any]:
            """Run a disaster recovery check.

            Returns:
                Results of the disaster recovery check
            """
            try:
                from ..core.backup_recovery import DisasterRecoveryManager
                dr_manager = DisasterRecoveryManager(self.app)

                results = await dr_manager.run_disaster_recovery_check()

                return {
                    "status": "success",
                    "results": results
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to run disaster recovery check: {str(e)}"
                }

        @server.tool()
        async def heal_workflows() -> Dict[str, Any]:
            """Manually trigger healing of failed workflows.

            Returns:
                Status of the healing operation
            """
            try:
                await self.app.error_recovery_manager.monitor_and_heal_workflows()

                return {
                    "status": "success",
                    "message": "Healing process initiated"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to initiate healing: {str(e)}"
                }

        @server.tool()
        async def get_monitoring_dashboard() -> Dict[str, Any]:
            """Get comprehensive monitoring dashboard data.

            Returns:
                System metrics, workflow stats, and alert information
            """
            try:
                if not self.app.monitoring_service:
                    return {
                        "status": "error",
                        "error": "Monitoring service not initialized"
                    }

                dashboard_data = await self.app.monitoring_service.get_dashboard_data()

                return {
                    "status": "success",
                    "dashboard": dashboard_data
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get monitoring dashboard: {str(e)}"
                }

        @server.tool()
        async def get_active_alerts() -> Dict[str, Any]:
            """Get all active (non-acknowledged) alerts.

            Returns:
                List of active alerts
            """
            try:
                if not self.app.monitoring_service or not self.app.monitoring_service.alert_manager:
                    return {
                        "status": "error",
                        "error": "Monitoring service not initialized"
                    }

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
                            "details": alert.details
                        }
                        for alert in active_alerts
                    ],
                    "count": len(active_alerts)
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to get active alerts: {str(e)}"
                }

        @server.tool()
        async def acknowledge_alert(alert_id: str, user: str) -> Dict[str, Any]:
            """Acknowledge an alert.

            Args:
                alert_id: ID of the alert to acknowledge
                user: User acknowledging the alert

            Returns:
                Status of the acknowledgment
            """
            try:
                if not self.app.monitoring_service:
                    return {
                        "status": "error",
                        "error": "Monitoring service not initialized"
                    }

                success = await self.app.monitoring_service.acknowledge_alert(alert_id, user)

                return {
                    "status": "success" if success else "error",
                    "message": f"Alert {alert_id} {'acknowledged' if success else 'failed to acknowledge'} by {user}"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to acknowledge alert: {str(e)}"
                }

        @server.tool()
        async def trigger_test_alert(
            severity: str = "medium",
            title: str = "Test Alert",
            description: str = "This is a test alert"
        ) -> Dict[str, Any]:
            """Trigger a test alert for testing purposes.

            Args:
                severity: Severity level (low, medium, high, critical)
                title: Title of the alert
                description: Description of the alert

            Returns:
                Status of the alert triggering
            """
            try:
                if not self.app.monitoring_service or not self.app.monitoring_service.alert_manager:
                    return {
                        "status": "error",
                        "error": "Monitoring service not initialized"
                    }

                from ..core.monitoring import AlertSeverity, AlertType

                # Convert string severity to enum
                try:
                    severity_enum = AlertSeverity(severity.lower())
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Invalid severity: {severity}. Valid values: low, medium, high, critical"
                    }

                alert = await self.app.monitoring_service.alert_manager.trigger_alert(
                    severity=severity_enum,
                    alert_type=AlertType.SYSTEM_HEALTH,
                    title=title,
                    description=description,
                    details={"test_alert": True}
                )

                return {
                    "status": "success",
                    "alert_id": alert.id,
                    "message": f"Test alert created with ID: {alert.id}"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to trigger test alert: {str(e)}"
                }

        @server.tool()
        async def flush_metrics() -> Dict[str, Any]:
            """Force flush all pending metrics to exporters.

            Returns:
                Status of the flush operation
            """
            try:
                if not self.app.observability:
                    return {
                        "status": "warning",
                        "message": "Observability system not initialized, nothing to flush"
                    }

                await self.app.observability.flush_metrics()

                return {
                    "status": "success",
                    "message": "Metrics flushed successfully"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to flush metrics: {str(e)}"
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
                    # Get additional adapter-specific information
                    adapter_details = {
                        "enabled": True,
                        "health": health,
                        "type": type(adapter).__name__,
                        "features": []  # This could be expanded based on adapter capabilities
                    }

                    # Add specific features based on adapter type
                    if name == "llamaindex":
                        adapter_details["features"] = ["RAG", "Document Ingestion", "Semantic Search"]
                    elif name == "prefect":
                        adapter_details["features"] = ["Workflow Orchestration", "Task Scheduling", "State Management"]
                    elif name == "agno":
                        adapter_details["features"] = ["AI Agents", "Multi-Agent Systems", "Tool Integration"]

                    adapters_info[name] = adapter_details
                except Exception as e:
                    adapters_info[name] = {
                        "enabled": True,
                        "health": {"status": "unhealthy", "error": str(e)},
                        "type": type(adapter).__name__ if 'adapter' in locals() else "Unknown",
                        "features": []
                    }

            return {
                "adapters": adapters_info,
                "count": len(adapters_info),
                "available_names": list(adapters_info.keys())
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

                # Check workflow state manager health
                try:
                    # Attempt to list a few workflows as a health check
                    recent_workflows = await self.app.workflow_state_manager.list_workflows(limit=1)
                    workflow_state_healthy = True
                    workflow_state_info = {
                        "status": "healthy",
                        "recent_workflows_count": len(recent_workflows)
                    }
                except Exception as e:
                    workflow_state_healthy = False
                    workflow_state_info = {
                        "status": "unhealthy",
                        "error": str(e)
                    }

                # Check RBAC manager health
                try:
                    # Check if default roles are loaded
                    rbac_healthy = len(self.app.rbac_manager.roles) > 0
                    rbac_info = {
                        "status": "healthy" if rbac_healthy else "unhealthy",
                        "default_roles_count": len(self.app.rbac_manager.roles),
                        "admin_role_exists": "admin" in self.app.rbac_manager.roles
                    }
                except Exception as e:
                    rbac_healthy = False
                    rbac_info = {
                        "status": "unhealthy",
                        "error": str(e)
                    }

                # Check OpenSearch integration health
                try:
                    opensearch_health = await self.app.opensearch_integration.health_check()
                    opensearch_healthy = opensearch_health.get("status") == "healthy"
                    opensearch_info = opensearch_health
                except Exception as e:
                    opensearch_healthy = False
                    opensearch_info = {
                        "status": "unhealthy",
                        "error": str(e)
                    }

                overall_status = "healthy"
                health_components = [app_healthy, workflow_state_healthy, rbac_healthy, opensearch_healthy]

                if not all(health_components) or any(h.get("status") == "unhealthy" for h in adapter_health.values()):
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

        # Register Session Buddy integration tools
        self._register_session_buddy_tools()

        # Register repository messaging tools
        self._register_repository_messaging_tools()

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

    def _register_session_buddy_tools(self):
        """Register Session Buddy integration tools with MCP server."""
        from ..mcp.tools.session_buddy_tools import register_session_buddy_tools

        register_session_buddy_tools(self.server, self.app, self.mcp_client)
        logger.info("Registered Session Buddy integration tools with MCP server")

    def _register_repository_messaging_tools(self):
        """Register repository messaging tools with MCP server."""
        from ..mcp.tools.repository_messaging_tools import register_repository_messaging_tools

        register_repository_messaging_tools(self.server, self.app, self.mcp_client)
        logger.info("Registered repository messaging tools with MCP server")


async def run_server(config=None):
    """Run the MCP server."""
    server = FastMCPServer(config)
    await server.start()