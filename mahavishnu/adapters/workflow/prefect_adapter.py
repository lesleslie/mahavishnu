"""Prefect adapter for Mahavishnu orchestration.

Implements OrchestratorAdapter interface for Prefect workflow orchestration.
Provides workflow deployment, execution monitoring, state synchronization,
and integration with Prefect Cloud/Server.

Prefect: https://www.prefect.io/
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

try:
    from oneiric.core.ulid import generate_config_id
except ImportError:
    def generate_config_id() -> str:
        import uuid
        return uuid.uuid4().hex

from mahavishnu.core.adapters.base import OrchestratorAdapter, AdapterType, AdapterCapabilities
from mahavishnu.core.errors import AdapterInitializationError, WorkflowExecutionError

logger = logging.getLogger(__name__)


class PrefectAdapter(OrchestratorAdapter):
    """Prefect workflow orchestration adapter.

    Features:
    - Flow deployment to Prefect server
    - Execution state monitoring
    - Flow cancellation and cleanup
    - State synchronization (Mahavishnu ↔ Prefect DB)
    - Integration with Prefect Cloud UI

    Architecture:
    ┌──────────────────────────────────┐
    │   Mahavishnu                 │
    │  • Python HTTP Client           │
    │  • Flow Management             │
    │  • State Sync                 │
    └──────────────┬─────────────────┘
                   │
                   ↓
         ┌──────────────────────┐
         │  Prefect Server/API │
         │  • REST API          │
         │  • GraphQL API        │
         │  • PostgreSQL DB        │
         │  • Cloud UI           │
         └──────────────────────┘
    """

    def __init__(
        self,
        api_url: str = "http://localhost:4200",
        api_key: str | None = None,
        timeout_seconds: int = 300,
    ):
        """Initialize PrefectAdapter.

        Args:
            api_url: Prefect server URL (default: localhost:4200)
            api_key: Optional API authentication key
            timeout_seconds: Request timeout (default: 300)
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

        logger.info(f"PrefectAdapter initialized (API: {self.api_url})")

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.PREFECT

    @property
    def name(self) -> str:
        return "prefect"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return supported capabilities."""
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            has_cloud_ui=True,
        )

    async def initialize(self) -> None:
        """Initialize Prefect API client.

        Raises:
            AdapterInitializationError: If client cannot connect to Prefect API
        """
        try:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                timeout=self.timeout,
                headers=self._get_auth_headers(),
            )

            # Test connection
            response = await self._client.get("/api/health")
            if response.status_code != 200:
                raise AdapterInitializationError(
                    f"Prefect API health check failed: {response.status_code}"
                )

            logger.info("PrefectAdapter initialized successfully")

        except httpx.ConnectError as e:
            raise AdapterInitializationError(
                f"Cannot connect to Prefect server at {self.api_url}: {e}"
            )
        except Exception as e:
            raise AdapterInitializationError(
                f"Failed to initialize PrefectAdapter: {e}"
            )

    async def deploy_workflow(
        self,
        workflow_name: str,
        flow_definition: dict[str, Any],
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Deploy workflow to Prefect.

        Args:
            workflow_name: Unique workflow name
            flow_definition: Flow specification (tasks, dependencies, etc.)
            parameters: Optional flow parameters

        Returns:
            execution_id: ULID workflow execution identifier

        Raises:
            WorkflowExecutionError: If deployment fails
        """
        await self._ensure_client()

        deployment_id = generate_config_id()

        deployment_spec = {
            "name": workflow_name,
            "description": f"Mahavishnu workflow: {workflow_name}",
            "flow": flow_definition,
            "parameters": parameters or {},
            "tags": ["mahavishnu", "deployed"],
        }

        try:
            response = await self._client.post(
                "/api/deployments/",
                json=deployment_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 201:
                raise WorkflowExecutionError(
                    f"Failed to deploy workflow {workflow_name}: "
                    f"HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(f"Workflow {workflow_name} deployed: {deployment_id}")

            return deployment_id

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(
                f"HTTP error deploying workflow {workflow_name}: {e}"
            )

    async def deploy_workflow_from_file(
        self,
        file_path: str,
        workflow_name: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Deploy workflow from Python file.

        Args:
            file_path: Path to workflow Python file (.py)
            workflow_name: Optional workflow name (default: filename)
            parameters: Optional flow parameters

        Returns:
            execution_id: ULID workflow execution identifier

        Raises:
            WorkflowExecutionError: If deployment fails
        """
        await self._ensure_client()

        # Read file content
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                flow_code = f.read()

            if not workflow_name:
                # Extract name from filename
                workflow_name = file_path.stem

        except FileNotFoundError:
            raise WorkflowExecutionError(f"Workflow file not found: {file_path}")
        except Exception as e:
            raise WorkflowExecutionError(f"Failed to read workflow file: {e}")

        # Deploy with code
        return await self.deploy_workflow(
            workflow_name=workflow_name,
            flow_definition={"type": "python", "source": flow_code},
            parameters=parameters,
        )

    async def execute_workflow(
        self,
        workflow_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Execute workflow by name.

        Args:
            workflow_name: Name of deployed workflow to run
            parameters: Optional execution parameters

        Returns:
            execution_id: ULID workflow run identifier

        Raises:
            WorkflowExecutionError: If execution fails
        """
        await self._ensure_client()

        execution_id = generate_config_id()

        execution_spec = {
            "workflow_name": workflow_name,
            "parameters": parameters or {},
            "tags": ["mahavishnu", "execution"],
        }

        try:
            response = await self._client.post(
                "/api/executions/",
                json=execution_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 201:
                raise WorkflowExecutionError(
                    f"Failed to execute workflow {workflow_name}: "
                    f"HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(f"Workflow {workflow_name} execution started: {execution_id}")

            return execution_id

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(
                f"HTTP error executing workflow {workflow_name}: {e}"
            )

    async def get_execution_status(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get workflow execution status.

        Args:
            execution_id: ULID execution identifier

        Returns:
            Execution status dictionary with state, result, timestamps
        """
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"/api/executions/{execution_id}",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to get execution status: HTTP {response.status_code}"
                )

            return response.json()

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error getting status: {e}")

    async def cancel_workflow(
        self,
        execution_id: str,
    ) -> bool:
        """Cancel running workflow execution.

        Args:
            execution_id: ULID execution identifier

        Returns:
            True if cancellation succeeded

        Raises:
            WorkflowExecutionError: If cancellation fails
        """
        await self._ensure_client()

        try:
            response = await self._client.post(
                f"/api/executions/{execution_id}/cancel",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to cancel execution {execution_id}: "
                    f"HTTP {response.status_code}"
                )

            logger.info(f"Execution {execution_id} cancelled")
            return True

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error cancelling execution: {e}")

    async def get_workflow_list(self) -> list[dict[str, Any]]:
        """List all deployed workflows.

        Returns:
            List of workflow metadata dictionaries
        """
        await self._ensure_client()

        try:
            response = await self._client.get(
                "/api/workflows/",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to list workflows: HTTP {response.status_code}"
                )

            return response.json()

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error listing workflows: {e}")

    async def cleanup(self, older_than_days: int = 30) -> dict[str, int]:
        """Cleanup old workflow executions and deployments.

        Args:
            older_than_days: Delete executions/deployments older than this many days

        Returns:
            Dictionary with deletion counts
        """
        await self._ensure_client()

        cleanup_spec = {
            "older_than_days": older_than_days,
            "dry_run": False,
        }

        try:
            response = await self._client.post(
                "/api/cleanup/",
                json=cleanup_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Cleanup failed: HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(
                f"Prefect cleanup completed: "
                f"{result.get('executions_deleted', 0)} executions, "
                f"{result.get('deployments_deleted', 0)} deployments"
            )

            return result

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error during cleanup: {e}")

    async def shutdown(self) -> None:
        """Shutdown Prefect adapter and cleanup resources.

        Closes HTTP client and performs cleanup.
        """
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("PrefectAdapter shut down")

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mahavishnu/1.0",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            raise AdapterInitializationError(
                "PrefectAdapter not initialized. Call initialize() first."
            )
