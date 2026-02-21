"""Prefect 3.x adapter implementation for Mahavishnu orchestration.

This module provides a production-ready Prefect adapter that implements
the OrchestratorAdapter interface for workflow orchestration.

Features:
    - Full Prefect 3.x SDK integration
    - Async client lifecycle management
    - Connection verification and health checks
    - Comprehensive error handling with PrefectError
    - Support for Prefect Server and Prefect Cloud
    - Configurable retries with exponential backoff
    - Deployment CRUD operations (Phase 2)
    - Schedule management (Phase 3)
    - Flow registry integration (Phase 3)

Configuration (settings/mahavishnu.yaml):
    prefect:
      enabled: true
      api_url: "http://localhost:4200"
      work_pool: "default"
      timeout_seconds: 300
      max_retries: 3

Example:
    ```python
    from mahavishnu.engines.prefect_adapter import PrefectAdapter
    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200")
    adapter = PrefectAdapter(config)

    await adapter.initialize()
    result = await adapter.execute({"type": "code_sweep"}, ["/path/to/repo"])
    health = await adapter.get_health()

    # Phase 2: Deployment management
    deployment = await adapter.create_deployment(
        flow_name="my-flow",
        deployment_name="production",
        schedule=CronSchedule(cron="0 9 * * *"),
    )

    # Phase 3: Schedule management
    await adapter.set_deployment_schedule(deployment.id, schedule)

    # Phase 3: Flow registry
    flow_id = adapter.register_flow(my_flow_func, "my-flow", tags=["etl"])

    await adapter.shutdown()
    ```
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Callable

import httpx
from mcp_common.code_graph import CodeGraphAnalyzer
from prefect import flow, task
from prefect.client.orchestration import get_client
from prefect.exceptions import (
    ObjectNotFound,
    PrefectHTTPStatusError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..core.adapters.base import (
    AdapterCapabilities,
    AdapterType,
    OrchestratorAdapter,
)
from ..core.config import PrefectConfig
from ..core.errors import (
    ErrorCode,
    ErrorTemplates,
    PrefectError,
)
from .prefect_models import (
    DeploymentResponse,
    FlowRunResponse,
    WorkPoolResponse,
)
from .prefect_registry import FlowRegistry, get_flow_registry
from .prefect_schedules import (
    CronSchedule,
    IntervalSchedule,
    RRuleSchedule,
    ScheduleConfig,
    schedule_to_prefect_dict,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Prefect Tasks and Flows
# =============================================================================


@task
async def process_repository(repo_path: str, task_spec: dict[str, Any]) -> dict[str, Any]:
    """Process a single repository as a Prefect task - REAL IMPLEMENTATION.

    This task is executed by Prefect workers and performs the actual
    repository processing work.

    Args:
        repo_path: Path to the repository to process
        task_spec: Task specification with type and parameters

    Returns:
        Processing result with status and details
    """
    try:
        task_type = task_spec.get("type", "default")

        if task_type == "code_sweep":
            # Use code graph for intelligent analysis
            graph_analyzer = CodeGraphAnalyzer(Path(repo_path))
            analysis_result = await graph_analyzer.analyze_repository(repo_path)

            # Find complex functions (more than 10 lines or with many calls)
            from mcp_common.code_graph.analyzer import FunctionNode

            complex_funcs = []
            for _node_id, node in graph_analyzer.nodes.items():
                if (
                    isinstance(node, FunctionNode)
                    and hasattr(node, "end_line")
                    and hasattr(node, "start_line")
                ):
                    func_length = node.end_line - node.start_line
                    if func_length > 10 or len(node.calls) > 5:
                        complex_funcs.append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "length": func_length,
                                "calls_count": len(node.calls),
                                "is_export": node.is_export,
                            }
                        )

            # Calculate dynamic quality score based on actual analysis
            quality_factors = {
                "total_functions": analysis_result.get("functions_indexed", 0),
                "complex_functions_count": len(complex_funcs),
                "avg_function_length": sum(f["length"] for f in complex_funcs) / len(complex_funcs)
                if complex_funcs
                else 0,
                "max_complexity": max((f["calls_count"] for f in complex_funcs), default=0),
            }

            # Calculate quality score (0-100)
            quality_score = 100
            quality_score -= min(
                quality_factors["complex_functions_count"] * 2, 20
            )
            quality_score -= min(
                quality_factors["avg_function_length"] / 2, 15
            )
            quality_score -= min(
                quality_factors["max_complexity"], 10
            )
            quality_score = max(quality_score, 0)

            result = {
                "operation": "code_sweep",
                "repo": repo_path,
                "changes_identified": analysis_result["functions_indexed"],
                "recommendations": complex_funcs,
                "quality_score": round(quality_score, 2),
                "quality_factors": quality_factors,
                "analysis_details": analysis_result,
            }

        elif task_type == "quality_check":
            # Use Crackerjack integration
            from ..qc.checker import QualityControl

            qc = QualityControl()
            result = await qc.check_repository(repo_path)

        else:
            # Default operation
            result = {
                "operation": task_type,
                "repo": repo_path,
                "status": "processed",
                "details": f"Executed {task_type} on {repo_path}",
            }

        return {
            "repo": repo_path,
            "status": "completed",
            "result": result,
            "task_id": task_spec.get("id", "unknown"),
        }
    except Exception as e:
        return {
            "repo": repo_path,
            "status": "failed",
            "error": str(e),
            "task_id": task_spec.get("id", "unknown"),
        }


@flow(name="mahavishnu-repo-processing-flow")
async def process_repositories_flow(
    repos: list[str], task_spec: dict[str, Any]
) -> list[dict[str, Any]]:
    """Prefect flow to process multiple repositories.

    This flow coordinates parallel repository processing using Prefect's
    task scheduling capabilities.

    Args:
        repos: List of repository paths to process
        task_spec: Task specification passed to each repository

    Returns:
        List of results from each repository processing task
    """
    # Process all repositories in parallel using Prefect's task scheduling
    results = await asyncio.gather(*[process_repository(repo, task_spec) for repo in repos])

    return results


# =============================================================================
# Exception Mapping
# =============================================================================


def _map_prefect_exception(exc: Exception, operation: str, api_url: str = "unknown") -> PrefectError:
    """Map Prefect exceptions to Mahavishnu PrefectError.

    Args:
        exc: The original exception from Prefect
        operation: Description of the operation that failed
        api_url: The API URL being connected to (for connection errors)

    Returns:
        PrefectError with appropriate error code and context
    """
    if isinstance(exc, ObjectNotFound):
        # Determine if it's a deployment or flow based on context
        return PrefectError(
            message=f"{operation}: Resource not found - {exc}",
            error_code=ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND,
            details={"original_error": str(exc), "operation": operation},
        )
    elif isinstance(exc, PrefectHTTPStatusError):
        # Map HTTP status codes to appropriate errors
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 401:
            return PrefectError(
                message=f"{operation}: Authentication failed",
                error_code=ErrorCode.PREFECT_AUTHENTICATION_ERROR,
                details={"status_code": status_code, "original_error": str(exc)},
            )
        elif status_code == 429:
            return PrefectError(
                message=f"{operation}: Rate limit exceeded",
                error_code=ErrorCode.PREFECT_RATE_LIMITED,
                details={"status_code": status_code, "original_error": str(exc)},
            )
        elif status_code == 404:
            return PrefectError(
                message=f"{operation}: Resource not found",
                error_code=ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND,
                details={"status_code": status_code, "original_error": str(exc)},
            )
        elif status_code and status_code >= 500:
            return PrefectError(
                message=f"{operation}: Prefect server error",
                error_code=ErrorCode.PREFECT_API_ERROR,
                details={"status_code": status_code, "original_error": str(exc)},
            )
        else:
            return PrefectError(
                message=f"{operation}: API error - {exc}",
                error_code=ErrorCode.PREFECT_API_ERROR,
                details={"status_code": status_code, "original_error": str(exc)},
            )
    elif isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        # Connection errors from httpx (used by Prefect client)
        return ErrorTemplates.prefect_connection_failed(
            api_url=api_url,
            original_error=str(exc),
        )
    else:
        # Generic Prefect error for unknown exceptions
        return PrefectError(
            message=f"{operation}: {exc}",
            error_code=ErrorCode.PREFECT_API_ERROR,
            details={"original_type": type(exc).__name__, "original_error": str(exc)},
        )


def _deployment_to_response(deployment: Any) -> DeploymentResponse:
    """Convert Prefect deployment object to DeploymentResponse.

    Args:
        deployment: Prefect deployment object from the SDK

    Returns:
        DeploymentResponse model instance
    """
    return DeploymentResponse(
        id=str(deployment.id),
        name=deployment.name,
        flow_name=getattr(deployment, "flow_name", "") or "",
        flow_id=str(getattr(deployment, "flow_id", "")),
        schedule=getattr(deployment, "schedule", None),
        parameters=getattr(deployment, "parameters", {}) or {},
        work_pool_name=getattr(deployment, "work_pool_name", None),
        work_queue_name=getattr(deployment, "work_queue_name", None),
        paused=getattr(deployment, "paused", False) or False,
        tags=getattr(deployment, "tags", []) or [],
        description=getattr(deployment, "description", None),
        version=getattr(deployment, "version", None),
        created_at=getattr(deployment, "created", datetime.now()) or datetime.now(),
        updated_at=getattr(deployment, "updated", None),
    )


def _flow_run_to_response(flow_run: Any) -> FlowRunResponse:
    """Convert Prefect flow run object to FlowRunResponse.

    Args:
        flow_run: Prefect flow run object from the SDK

    Returns:
        FlowRunResponse model instance
    """
    state = getattr(flow_run, "state", None)
    return FlowRunResponse(
        id=str(flow_run.id),
        name=flow_run.name,
        flow_id=str(getattr(flow_run, "flow_id", "")),
        deployment_id=str(getattr(flow_run, "deployment_id", "")) if hasattr(flow_run, "deployment_id") and flow_run.deployment_id else None,
        state_type=getattr(state, "type", "UNKNOWN") if state else "UNKNOWN",
        state_name=getattr(state, "name", "Unknown") if state else "Unknown",
        parameters=getattr(flow_run, "parameters", {}) or {},
        tags=getattr(flow_run, "tags", []) or [],
        created_at=getattr(flow_run, "created", datetime.now()) or datetime.now(),
        updated_at=getattr(flow_run, "updated", None),
        start_time=getattr(flow_run, "start_time", None),
        end_time=getattr(flow_run, "end_time", None),
        total_run_time_seconds=getattr(flow_run, "total_run_time", None),
        estimated_run_time_seconds=getattr(flow_run, "estimated_run_time", None),
        work_queue_name=getattr(flow_run, "work_queue_name", None),
    )


def _work_pool_to_response(work_pool: Any) -> WorkPoolResponse:
    """Convert Prefect work pool object to WorkPoolResponse.

    Args:
        work_pool: Prefect work pool object from the SDK

    Returns:
        WorkPoolResponse model instance
    """
    return WorkPoolResponse(
        name=work_pool.name,
        type=getattr(work_pool, "type", "unknown"),
        description=getattr(work_pool, "description", None),
        is_paused=getattr(work_pool, "is_paused", False) or False,
        concurrency_limit=getattr(work_pool, "concurrency_limit", None),
        created_at=getattr(work_pool, "created", datetime.now()) or datetime.now(),
        updated_at=getattr(work_pool, "updated", None),
    )


# =============================================================================
# PrefectAdapter Class
# =============================================================================


class PrefectAdapter(OrchestratorAdapter):
    """Production-ready Prefect 3.x adapter for workflow orchestration.

    This adapter implements the OrchestratorAdapter interface and provides
    comprehensive Prefect integration including:

    - Async client lifecycle management
    - Connection verification and health checks
    - Retry logic with exponential backoff
    - Error mapping to Mahavishnu error hierarchy
    - Support for both Prefect Server and Prefect Cloud
    - Deployment CRUD operations (Phase 2)
    - Schedule management (Phase 3)
    - Flow registry integration (Phase 3)

    Attributes:
        config: PrefectConfig instance with adapter settings
        _client: Prefect orchestration client (lazy initialization)
        _initialized: Whether the adapter has been initialized

    Example:
        ```python
        from mahavishnu.engines.prefect_adapter import PrefectAdapter
        from mahavishnu.core.config import PrefectConfig

        # Create adapter with configuration
        config = PrefectConfig(api_url="http://localhost:4200")
        adapter = PrefectAdapter(config)

        # Initialize and use
        await adapter.initialize()
        result = await adapter.execute({"type": "sweep"}, ["/repo"])

        # Phase 2: Deployment management
        deployment = await adapter.create_deployment(
            flow_name="my-flow",
            deployment_name="production",
            schedule=CronSchedule(cron="0 9 * * *"),
        )

        # Phase 3: Schedule management
        from mahavishnu.engines.prefect_schedules import create_daily_schedule
        schedule = create_daily_schedule(hour=9)
        await adapter.set_deployment_schedule(deployment.id, schedule)

        # Phase 3: Flow registry
        flow_id = adapter.register_flow(my_flow, "my-flow", tags=["etl"])

        await adapter.shutdown()
        ```
    """

    def __init__(self, config: PrefectConfig | None = None) -> None:
        """Initialize the Prefect adapter with configuration.

        Args:
            config: PrefectConfig instance. If None, uses default configuration.
        """
        self.config = config or PrefectConfig()
        self._client: Any = None
        self._initialized = False
        self._client_context: Any = None
        self._flow_registry: FlowRegistry | None = None

    # =========================================================================
    # OrchestratorAdapter Interface Properties
    # =========================================================================

    @property
    def adapter_type(self) -> AdapterType:
        """Return the adapter type enum.

        Returns:
            AdapterType.PREFECT for this adapter
        """
        return AdapterType.PREFECT

    @property
    def name(self) -> str:
        """Return the adapter name.

        Returns:
            "prefect" as the adapter name
        """
        return "prefect"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities.

        Prefect provides:
        - Flow deployment and management
        - Execution monitoring
        - Workflow cancellation
        - State synchronization
        - Batch execution
        - Cloud UI (Prefect Cloud)

        Note: Prefect does not support multi-agent orchestration natively.
        Use the Agno adapter for multi-agent workflows.

        Returns:
            AdapterCapabilities with Prefect's supported features
        """
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            has_cloud_ui=True,
            supports_multi_agent=False,  # Prefect is not an agent framework
        )

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the Prefect client and verify connectivity.

        This method:
        1. Creates the Prefect orchestration client
        2. Verifies connection to Prefect server/cloud
        3. Marks the adapter as initialized
        4. Initializes the flow registry

        Raises:
            PrefectError: If connection cannot be established
        """
        if self._initialized:
            logger.debug("PrefectAdapter already initialized")
            return

        try:
            # Test connectivity by creating a client and checking health
            async with self._get_client_context() as client:
                # Verify connection by reading server info
                await client.read_health()

            # Initialize flow registry
            self._flow_registry = get_flow_registry()

            self._initialized = True
            logger.info(
                "PrefectAdapter initialized successfully",
                extra={"api_url": self.config.api_url},
            )

        except Exception as exc:
            error = _map_prefect_exception(exc, "initialize", self.config.api_url)
            logger.error(
                "Failed to initialize PrefectAdapter",
                extra={"error": str(error), "api_url": self.config.api_url},
            )
            raise error from exc

    async def shutdown(self) -> None:
        """Shutdown the Prefect client and cleanup resources.

        This method:
        1. Closes any active client connections
        2. Resets initialization state
        """
        if self._client_context is not None:
            try:
                await self._client_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Prefect client: {e}")
            finally:
                self._client_context = None

        self._client = None
        self._initialized = False
        self._flow_registry = None
        logger.info("PrefectAdapter shutdown complete")

    @asynccontextmanager
    async def _get_client_context(self):
        """Get Prefect client as async context manager.

        Yields:
            Prefect orchestration client
        """
        # Configure client for Prefect Cloud if workspace is specified
        if self.config.api_key:
            import os
            old_api_key = os.environ.get("PREFECT_API_KEY")
            old_api_url = os.environ.get("PREFECT_API_URL")
            try:
                os.environ["PREFECT_API_KEY"] = self.config.api_key
                if self.config.api_url:
                    os.environ["PREFECT_API_URL"] = self.config.api_url
                async with get_client() as client:
                    yield client
            finally:
                if old_api_key is not None:
                    os.environ["PREFECT_API_KEY"] = old_api_key
                elif "PREFECT_API_KEY" in os.environ:
                    del os.environ["PREFECT_API_KEY"]
                if old_api_url is not None:
                    os.environ["PREFECT_API_URL"] = old_api_url
                elif "PREFECT_API_URL" in os.environ:
                    del os.environ["PREFECT_API_URL"]
        else:
            # Use default client for local Prefect server
            async with get_client() as client:
                yield client

    # =========================================================================
    # OrchestratorAdapter Interface Methods
    # =========================================================================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(PrefectError),
        reraise=True,
    )
    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute a task using Prefect across multiple repositories.

        This method deploys and runs a Prefect flow to process the specified
        repositories with the given task specification.

        Args:
            task: Task specification with type and parameters
                - type: Task type (e.g., "code_sweep", "quality_check")
                - id: Optional task identifier
                - Additional task-specific parameters
            repos: List of repository paths to operate on

        Returns:
            Execution result containing:
                - status: "completed" or "failed"
                - engine: "prefect"
                - task: Original task specification
                - repos_processed: Number of repositories
                - results: List of per-repository results
                - success_count: Number of successful executions
                - failure_count: Number of failed executions
                - flow_run_id: Prefect flow run ID (if successful)
                - flow_run_url: URL to view in Prefect UI (if successful)
                - error: Error message (if failed)

        Raises:
            PrefectError: If execution fails after retries
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Deploy and run the Prefect flow
                flow_run = await client.create_flow_run(
                    flow=process_repositories_flow,
                    parameters={"repos": repos, "task_spec": task},
                    name=f"mahavishnu-task-{task.get('id', 'unknown')}",
                )

                # Wait for flow completion and get results
                flow_run_id = flow_run.id
                state = await client.wait_for_flow_run(
                    flow_run_id,
                    timeout=self.config.timeout_seconds,
                )

                # Get actual results from flow run
                results = state.result() if state.is_completed() else []

                # Build response
                response = {
                    "status": "completed" if state.is_completed() else "failed",
                    "engine": "prefect",
                    "task": task,
                    "repos_processed": len(repos),
                    "results": results,
                    "success_count": len([r for r in results if r.get("status") == "completed"]),
                    "failure_count": len([r for r in results if r.get("status") == "failed"]),
                    "flow_run_id": str(flow_run_id),
                    "flow_run_url": f"{client.api_url}/flows/flow-run/{flow_run_id}",
                }

                logger.info(
                    "Prefect flow execution completed",
                    extra={
                        "flow_run_id": str(flow_run_id),
                        "status": response["status"],
                        "success_count": response["success_count"],
                        "failure_count": response["failure_count"],
                    },
                )

                return response

        except PrefectError:
            # Re-raise PrefectError without wrapping
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, "execute", self.config.api_url)
            logger.error(
                "Prefect flow execution failed",
                extra={"error": str(error), "task": task.get("type", "unknown")},
            )
            raise error from exc

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Performs a connectivity check to the Prefect server/cloud and
        returns a structured health status.

        Returns:
            Dict with:
                - status: "healthy", "degraded", or "unhealthy"
                - details: Dict with health check details including:
                    - prefect_version: Server version info
                    - configured: Whether adapter is configured
                    - connection: Connection status
                    - api_url: Configured API URL
                    - latency_ms: Health check latency (if healthy)
        """
        try:
            import time

            start_time = time.monotonic()

            async with self._get_client_context() as client:
                # Test connectivity
                health_info = await client.read_health()
                latency_ms = (time.monotonic() - start_time) * 1000

            health_details = {
                "prefect_version": getattr(health_info, "version", "3.x"),
                "configured": True,
                "connection": "available",
                "api_url": self.config.api_url,
                "latency_ms": round(latency_ms, 2),
                "initialized": self._initialized,
            }

            # Determine health status based on latency
            if latency_ms < 1000:
                status = "healthy"
            elif latency_ms < 5000:
                status = "degraded"
            else:
                status = "degraded"  # Still available but slow

            return {"status": status, "details": health_details}

        except PrefectError as exc:
            logger.warning(
                "Prefect health check failed",
                extra={"error": str(exc)},
            )
            return {
                "status": "unhealthy",
                "details": {
                    "error": str(exc),
                    "error_code": exc.error_code.value,
                    "configured": True,
                    "connection": "failed",
                    "api_url": self.config.api_url,
                },
            }
        except Exception as exc:
            logger.warning(
                "Prefect health check failed with unexpected error",
                extra={"error": str(exc)},
            )
            return {
                "status": "unhealthy",
                "details": {
                    "error": str(exc),
                    "configured": True,
                    "connection": "failed",
                    "api_url": self.config.api_url,
                },
            }

    # =========================================================================
    # Phase 2: Deployment Management
    # =========================================================================

    async def create_deployment(
        self,
        flow_name: str,
        deployment_name: str,
        schedule: ScheduleConfig | None = None,
        parameters: dict[str, Any] | None = None,
        work_pool_name: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        version: str | None = None,
    ) -> DeploymentResponse:
        """Create a new Prefect deployment.

        A deployment represents a configured flow with optional schedule,
        parameters, and work pool assignment. Deployments can be triggered
        manually or automatically via schedules.

        Args:
            flow_name: Name of the flow to deploy
            deployment_name: Unique name for this deployment
            schedule: Optional schedule configuration (CronSchedule, IntervalSchedule, RRuleSchedule)
            parameters: Default parameters for flow runs from this deployment
            work_pool_name: Name of the work pool for execution (default from config)
            tags: List of tags for organization and filtering
            description: Human-readable description of the deployment
            version: Version string for the deployment

        Returns:
            DeploymentResponse with created deployment details

        Raises:
            PrefectError: If deployment creation fails

        Example:
            ```python
            from mahavishnu.engines.prefect_schedules import CronSchedule

            deployment = await adapter.create_deployment(
                flow_name="my-etl-flow",
                deployment_name="production-daily",
                schedule=CronSchedule(cron="0 9 * * *"),  # Daily at 9 AM
                parameters={"environment": "production"},
                work_pool_name="kubernetes-pool",
                tags=["etl", "production"],
            )
            print(f"Created deployment: {deployment.id}")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Resolve the flow to get its ID
                flow = await client.read_flow_by_name(flow_name)

                # Build deployment configuration
                deployment_config: dict[str, Any] = {
                    "flow_id": flow.id,
                    "name": deployment_name,
                    "parameters": parameters or {},
                    "tags": tags or [],
                }

                # Add optional fields
                if schedule:
                    deployment_config["schedule"] = schedule_to_prefect_dict(schedule)
                if work_pool_name:
                    deployment_config["work_pool_name"] = work_pool_name
                elif self.config.work_pool:
                    deployment_config["work_pool_name"] = self.config.work_pool
                if description:
                    deployment_config["description"] = description
                if version:
                    deployment_config["version"] = version

                # Create the deployment
                deployment = await client.create_deployment(**deployment_config)

                logger.info(
                    "Created Prefect deployment",
                    extra={
                        "deployment_id": str(deployment.id),
                        "deployment_name": deployment_name,
                        "flow_name": flow_name,
                    },
                )

                return _deployment_to_response(deployment)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"create_deployment({flow_name}/{deployment_name})", self.config.api_url)
            logger.error(
                "Failed to create deployment",
                extra={"error": str(error), "flow_name": flow_name, "deployment_name": deployment_name},
            )
            raise error from exc

    async def update_deployment(
        self,
        deployment_id: str,
        schedule: ScheduleConfig | None = None,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        paused: bool | None = None,
        work_pool_name: str | None = None,
    ) -> DeploymentResponse:
        """Update an existing Prefect deployment.

        Allows updating deployment configuration including schedule, parameters,
        and work pool assignment without recreating the deployment.

        Args:
            deployment_id: UUID of the deployment to update
            schedule: New schedule configuration (CronSchedule, IntervalSchedule, RRuleSchedule)
            parameters: Updated default parameters (merged with existing)
            tags: Updated list of tags
            description: Updated description
            paused: Pause or unpause the deployment
            work_pool_name: New work pool assignment

        Returns:
            DeploymentResponse with updated deployment details

        Raises:
            PrefectError: If deployment update fails or deployment not found

        Example:
            ```python
            # Pause a deployment
            await adapter.update_deployment("dep-123", paused=True)

            # Update schedule
            from mahavishnu.engines.prefect_schedules import IntervalSchedule
            await adapter.update_deployment(
                "dep-123",
                schedule=IntervalSchedule(interval_seconds=3600),
            )
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Build update payload (only include non-None values)
                updates: dict[str, Any] = {}

                if schedule is not None:
                    updates["schedule"] = schedule_to_prefect_dict(schedule)
                if parameters is not None:
                    updates["parameters"] = parameters
                if tags is not None:
                    updates["tags"] = tags
                if description is not None:
                    updates["description"] = description
                if paused is not None:
                    updates["paused"] = paused
                if work_pool_name is not None:
                    updates["work_pool_name"] = work_pool_name

                # Update the deployment
                deployment = await client.update_deployment(
                    deployment_id,
                    **updates,
                )

                logger.info(
                    "Updated Prefect deployment",
                    extra={
                        "deployment_id": deployment_id,
                        "updates": list(updates.keys()),
                    },
                )

                return _deployment_to_response(deployment)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"update_deployment({deployment_id})", self.config.api_url)
            logger.error(
                "Failed to update deployment",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a Prefect deployment.

        Permanently removes a deployment and its associated schedule.
        Flow runs already in progress will continue to completion.

        Args:
            deployment_id: UUID of the deployment to delete

        Returns:
            True if deletion was successful

        Raises:
            PrefectError: If deletion fails or deployment not found

        Example:
            ```python
            success = await adapter.delete_deployment("dep-123")
            if success:
                print("Deployment deleted")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                await client.delete_deployment(deployment_id)

                logger.info(
                    "Deleted Prefect deployment",
                    extra={"deployment_id": deployment_id},
                )

                return True

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"delete_deployment({deployment_id})", self.config.api_url)
            logger.error(
                "Failed to delete deployment",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def get_deployment(self, deployment_id: str) -> DeploymentResponse:
        """Get a specific Prefect deployment by ID.

        Retrieves detailed information about a deployment including its
        schedule, parameters, and work pool assignment.

        Args:
            deployment_id: UUID of the deployment to retrieve

        Returns:
            DeploymentResponse with deployment details

        Raises:
            PrefectError: If retrieval fails or deployment not found

        Example:
            ```python
            deployment = await adapter.get_deployment("dep-123")
            print(f"Deployment: {deployment.name}")
            print(f"Paused: {deployment.paused}")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                deployment = await client.read_deployment(deployment_id)
                return _deployment_to_response(deployment)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"get_deployment({deployment_id})", self.config.api_url)
            logger.error(
                "Failed to get deployment",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def get_deployment_by_name(
        self,
        flow_name: str,
        deployment_name: str,
    ) -> DeploymentResponse:
        """Get a specific Prefect deployment by flow and deployment name.

        Alternative to get_deployment() that uses names instead of UUID.
        Useful when you know the flow and deployment names but not the ID.

        Args:
            flow_name: Name of the flow
            deployment_name: Name of the deployment

        Returns:
            DeploymentResponse with deployment details

        Raises:
            PrefectError: If retrieval fails or deployment not found

        Example:
            ```python
            deployment = await adapter.get_deployment_by_name(
                "my-etl-flow",
                "production-daily",
            )
            print(f"Deployment ID: {deployment.id}")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                deployment = await client.read_deployment_by_name(
                    f"{flow_name}/{deployment_name}",
                )
                return _deployment_to_response(deployment)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(
                exc,
                f"get_deployment_by_name({flow_name}/{deployment_name})",
                self.config.api_url,
            )
            logger.error(
                "Failed to get deployment by name",
                extra={"error": str(error), "flow_name": flow_name, "deployment_name": deployment_name},
            )
            raise error from exc

    async def list_deployments(
        self,
        flow_name: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeploymentResponse]:
        """List Prefect deployments with optional filtering.

        Retrieves a list of deployments, optionally filtered by flow name
        and/or tags.

        Args:
            flow_name: Filter by flow name (optional)
            tags: Filter by tags (deployments must have ALL specified tags)
            limit: Maximum number of deployments to return (default: 100)
            offset: Number of deployments to skip for pagination

        Returns:
            List of DeploymentResponse objects

        Raises:
            PrefectError: If listing fails

        Example:
            ```python
            # List all deployments
            all_deployments = await adapter.list_deployments()

            # Filter by flow
            etl_deployments = await adapter.list_deployments(flow_name="my-etl-flow")

            # Filter by tags
            prod_deployments = await adapter.list_deployments(tags=["production"])
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Build filter arguments
                filter_kwargs: dict[str, Any] = {
                    "limit": limit,
                    "offset": offset,
                }

                if flow_name:
                    filter_kwargs["flow_name"] = flow_name
                if tags:
                    filter_kwargs["tags"] = tags

                deployments = await client.read_deployments(**filter_kwargs)

                return [_deployment_to_response(d) for d in deployments]

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, "list_deployments", self.config.api_url)
            logger.error(
                "Failed to list deployments",
                extra={"error": str(error), "flow_name": flow_name, "tags": tags},
            )
            raise error from exc

    # =========================================================================
    # Phase 2: Flow Run Management
    # =========================================================================

    async def trigger_flow_run(
        self,
        deployment_id: str,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> FlowRunResponse:
        """Trigger a new flow run from a deployment.

        Creates and starts a new flow run using the deployment's configuration.
        The flow will execute on the configured work pool.

        Args:
            deployment_id: UUID of the deployment to run
            parameters: Parameters to override/extend deployment defaults
            tags: Additional tags for this specific run
            idempotency_key: Optional key to prevent duplicate runs

        Returns:
            FlowRunResponse with created flow run details

        Raises:
            PrefectError: If flow run creation fails

        Example:
            ```python
            flow_run = await adapter.trigger_flow_run(
                "dep-123",
                parameters={"batch_size": 1000},
                tags=["manual-trigger"],
            )
            print(f"Started flow run: {flow_run.id}")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                flow_run = await client.create_flow_run_from_deployment(
                    deployment_id=deployment_id,
                    parameters=parameters,
                    tags=tags,
                    idempotency_key=idempotency_key,
                )

                logger.info(
                    "Triggered Prefect flow run",
                    extra={
                        "flow_run_id": str(flow_run.id),
                        "deployment_id": deployment_id,
                    },
                )

                return _flow_run_to_response(flow_run)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"trigger_flow_run({deployment_id})", self.config.api_url)
            logger.error(
                "Failed to trigger flow run",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def get_flow_run(self, flow_run_id: str) -> FlowRunResponse:
        """Get details of a specific flow run.

        Retrieves current state and metadata for a flow run.

        Args:
            flow_run_id: UUID of the flow run

        Returns:
            FlowRunResponse with flow run details

        Raises:
            PrefectError: If retrieval fails or flow run not found

        Example:
            ```python
            flow_run = await adapter.get_flow_run("run-123")
            print(f"Status: {flow_run.state_type}")
            print(f"Duration: {flow_run.total_run_time_seconds}s")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                flow_run = await client.read_flow_run(flow_run_id)
                return _flow_run_to_response(flow_run)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"get_flow_run({flow_run_id})", self.config.api_url)
            logger.error(
                "Failed to get flow run",
                extra={"error": str(error), "flow_run_id": flow_run_id},
            )
            raise error from exc

    async def list_flow_runs(
        self,
        deployment_id: str | None = None,
        state: list[str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FlowRunResponse]:
        """List flow runs with optional filtering.

        Retrieves a list of flow runs, optionally filtered by deployment,
        state, and/or tags.

        Args:
            deployment_id: Filter by deployment ID (optional)
            state: Filter by state types (e.g., ["COMPLETED", "FAILED"])
            tags: Filter by tags
            limit: Maximum number of flow runs to return (default: 100)
            offset: Number of flow runs to skip for pagination

        Returns:
            List of FlowRunResponse objects

        Raises:
            PrefectError: If listing fails

        Example:
            ```python
            # List recent failed runs
            failed_runs = await adapter.list_flow_runs(
                state=["FAILED"],
                limit=10,
            )

            # List runs for a specific deployment
            deployment_runs = await adapter.list_flow_runs(
                deployment_id="dep-123",
            )
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Build filter arguments
                filter_kwargs: dict[str, Any] = {
                    "limit": limit,
                    "offset": offset,
                }

                if deployment_id:
                    filter_kwargs["deployment_id"] = deployment_id
                if state:
                    filter_kwargs["state"] = state
                if tags:
                    filter_kwargs["tags"] = tags

                flow_runs = await client.read_flow_runs(**filter_kwargs)

                return [_flow_run_to_response(fr) for fr in flow_runs]

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, "list_flow_runs", self.config.api_url)
            logger.error(
                "Failed to list flow runs",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def cancel_flow_run(self, flow_run_id: str) -> bool:
        """Cancel a running flow run.

        Sends a cancellation signal to the flow run. The flow will
        transition to CANCELLED state once the cancellation is processed.

        Args:
            flow_run_id: UUID of the flow run to cancel

        Returns:
            True if cancellation was initiated successfully

        Raises:
            PrefectError: If cancellation fails or flow run not found

        Example:
            ```python
            success = await adapter.cancel_flow_run("run-123")
            if success:
                print("Flow run cancelled")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                await client.set_flow_run_state(
                    flow_run_id,
                    state="CANCELLED",
                )

                logger.info(
                    "Cancelled Prefect flow run",
                    extra={"flow_run_id": flow_run_id},
                )

                return True

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"cancel_flow_run({flow_run_id})", self.config.api_url)
            logger.error(
                "Failed to cancel flow run",
                extra={"error": str(error), "flow_run_id": flow_run_id},
            )
            raise error from exc

    # =========================================================================
    # Phase 2: Work Pool Management
    # =========================================================================

    async def list_work_pools(self) -> list[WorkPoolResponse]:
        """List all available work pools.

        Work pools are groups of workers that can execute flow runs.
        Each pool has a type (process, kubernetes, etc.) and optional
        concurrency limits.

        Returns:
            List of WorkPoolResponse objects

        Raises:
            PrefectError: If listing fails

        Example:
            ```python
            pools = await adapter.list_work_pools()
            for pool in pools:
                print(f"{pool.name}: {pool.type} (paused={pool.is_paused})")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                work_pools = await client.read_work_pools()
                return [_work_pool_to_response(wp) for wp in work_pools]

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, "list_work_pools", self.config.api_url)
            logger.error(
                "Failed to list work pools",
                extra={"error": str(error)},
            )
            raise error from exc

    async def get_work_pool(self, work_pool_name: str) -> WorkPoolResponse:
        """Get details of a specific work pool.

        Args:
            work_pool_name: Name of the work pool

        Returns:
            WorkPoolResponse with work pool details

        Raises:
            PrefectError: If retrieval fails or work pool not found

        Example:
            ```python
            pool = await adapter.get_work_pool("kubernetes-pool")
            print(f"Type: {pool.type}")
            print(f"Concurrency: {pool.concurrency_limit}")
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                work_pool = await client.read_work_pool(work_pool_name)
                return _work_pool_to_response(work_pool)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(exc, f"get_work_pool({work_pool_name})", self.config.api_url)
            logger.error(
                "Failed to get work pool",
                extra={"error": str(error), "work_pool_name": work_pool_name},
            )
            raise error from exc

    # =========================================================================
    # Phase 3: Schedule Management
    # =========================================================================

    async def set_deployment_schedule(
        self,
        deployment_id: str,
        schedule: ScheduleConfig,
    ) -> DeploymentResponse:
        """Set or update a deployment's schedule.

        This method sets a new schedule for an existing deployment.
        Any existing schedule will be replaced.

        Args:
            deployment_id: UUID of the deployment
            schedule: Schedule configuration (CronSchedule, IntervalSchedule, or RRuleSchedule)

        Returns:
            DeploymentResponse with updated deployment details

        Raises:
            PrefectError: If schedule update fails or deployment not found

        Example:
            ```python
            from mahavishnu.engines.prefect_schedules import create_daily_schedule

            # Set a daily schedule
            schedule = create_daily_schedule(hour=9, minute=30)
            deployment = await adapter.set_deployment_schedule("dep-123", schedule)

            # Set a cron schedule
            from mahavishnu.engines.prefect_schedules import CronSchedule
            schedule = CronSchedule(cron="0 */6 * * *")  # Every 6 hours
            deployment = await adapter.set_deployment_schedule("dep-123", schedule)
            ```
        """
        return await self.update_deployment(deployment_id, schedule=schedule)

    async def clear_deployment_schedule(self, deployment_id: str) -> DeploymentResponse:
        """Clear a deployment's schedule.

        Removes the schedule from a deployment, making it only triggerable
        manually via trigger_flow_run().

        Args:
            deployment_id: UUID of the deployment

        Returns:
            DeploymentResponse with updated deployment details

        Raises:
            PrefectError: If schedule clear fails or deployment not found

        Example:
            ```python
            # Remove schedule from deployment
            deployment = await adapter.clear_deployment_schedule("dep-123")
            assert deployment.schedule is None
            ```
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._get_client_context() as client:
                # Set schedule to None to clear it
                deployment = await client.update_deployment(
                    deployment_id,
                    schedule=None,
                )

                logger.info(
                    "Cleared deployment schedule",
                    extra={"deployment_id": deployment_id},
                )

                return _deployment_to_response(deployment)

        except PrefectError:
            raise
        except Exception as exc:
            error = _map_prefect_exception(
                exc,
                f"clear_deployment_schedule({deployment_id})",
                self.config.api_url,
            )
            logger.error(
                "Failed to clear deployment schedule",
                extra={"error": str(error), "deployment_id": deployment_id},
            )
            raise error from exc

    async def get_deployment_schedule(
        self,
        deployment_id: str,
    ) -> ScheduleConfig | None:
        """Get a deployment's current schedule.

        Retrieves the schedule configuration from a deployment.

        Args:
            deployment_id: UUID of the deployment

        Returns:
            ScheduleConfig if schedule exists, None otherwise

        Raises:
            PrefectError: If retrieval fails or deployment not found

        Example:
            ```python
            schedule = await adapter.get_deployment_schedule("dep-123")
            if schedule:
                print(f"Schedule type: {schedule.type}")
                if isinstance(schedule, CronSchedule):
                    print(f"Cron: {schedule.cron}")
            ```
        """
        deployment = await self.get_deployment(deployment_id)

        if not deployment.schedule:
            return None

        # Convert dict schedule back to ScheduleConfig
        schedule_dict = deployment.schedule

        if "cron" in schedule_dict:
            return CronSchedule(
                cron=schedule_dict["cron"],
                timezone=schedule_dict.get("timezone", "UTC"),
                day_or=schedule_dict.get("day_or", True),
            )
        elif "interval" in schedule_dict:
            anchor = None
            if "anchor_date" in schedule_dict:
                anchor = datetime.fromisoformat(schedule_dict["anchor_date"])
            return IntervalSchedule(
                interval_seconds=schedule_dict["interval"],
                anchor_date=anchor,
            )
        elif "rrule" in schedule_dict:
            return RRuleSchedule(
                rrule=schedule_dict["rrule"],
                timezone=schedule_dict.get("timezone", "UTC"),
            )

        return None

    # =========================================================================
    # Phase 3: Flow Registry Integration
    # =========================================================================

    def register_flow(
        self,
        flow_func: Callable,
        name: str,
        tags: list[str] | None = None,
    ) -> str:
        """Register a flow function in the flow registry.

        The flow registry maintains an in-memory collection of flows
        that can be deployed and executed.

        Args:
            flow_func: The Prefect flow function (decorated with @flow)
            name: Human-readable name for the flow
            tags: Optional list of tags for categorization

        Returns:
            Unique flow ID string

        Example:
            ```python
            from prefect import flow

            @flow(name="data-pipeline")
            async def my_data_pipeline():
                pass

            # Register with adapter
            flow_id = adapter.register_flow(
                my_data_pipeline,
                name="data-pipeline",
                tags=["etl", "production"],
            )
            ```
        """
        if self._flow_registry is None:
            self._flow_registry = get_flow_registry()

        return self._flow_registry.register_flow(flow_func, name, tags)

    def list_registered_flows(
        self,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List registered flows from the flow registry.

        Args:
            tags: Optional list of tags to filter by (AND logic)

        Returns:
            List of flow metadata dictionaries

        Example:
            ```python
            # List all registered flows
            all_flows = adapter.list_registered_flows()

            # List flows with specific tag
            prod_flows = adapter.list_registered_flows(tags=["production"])
            ```
        """
        if self._flow_registry is None:
            self._flow_registry = get_flow_registry()

        return self._flow_registry.list_flows(tags)

    def get_registered_flow(self, flow_id: str) -> Callable | None:
        """Get a registered flow function by ID.

        Args:
            flow_id: The unique flow identifier

        Returns:
            Flow function if found, None otherwise

        Example:
            ```python
            flow_func = adapter.get_registered_flow("abc-123")
            if flow_func:
                result = await flow_func()
            ```
        """
        if self._flow_registry is None:
            self._flow_registry = get_flow_registry()

        return self._flow_registry.get_flow(flow_id)

    def unregister_flow(self, flow_id: str) -> bool:
        """Remove a flow from the registry.

        Args:
            flow_id: The unique flow identifier

        Returns:
            True if removed, False if not found

        Example:
            ```python
            success = adapter.unregister_flow("abc-123")
            if success:
                print("Flow removed from registry")
            ```
        """
        if self._flow_registry is None:
            self._flow_registry = get_flow_registry()

        return self._flow_registry.unregister_flow(flow_id)

    # =========================================================================
    # Additional Utility Methods
    # =========================================================================

    def __repr__(self) -> str:
        """Return string representation of the adapter."""
        return (
            f"PrefectAdapter("
            f"api_url={self.config.api_url!r}, "
            f"initialized={self._initialized})"
        )

    def __str__(self) -> str:
        """Human-readable string of the adapter."""
        status = "initialized" if self._initialized else "not initialized"
        return f"PrefectAdapter ({self.config.api_url}) - {status}"


__all__ = [
    "PrefectAdapter",
    "process_repository",
    "process_repositories_flow",
    # Re-export schedule types for convenience
    "CronSchedule",
    "IntervalSchedule",
    "RRuleSchedule",
    # Re-export response types for convenience
    "DeploymentResponse",
    "FlowRunResponse",
    "WorkPoolResponse",
    # Re-export registry for convenience
    "FlowRegistry",
    "get_flow_registry",
]
