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
    await adapter.shutdown()
    ```
"""

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

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
]
