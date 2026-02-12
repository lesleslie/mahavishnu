"""Agno adapter for multi-agent AI task orchestration.

Implements OrchestratorAdapter interface for Agno crew management
and task execution. Provides crew creation, task distribution,
result aggregation, and agent collaboration patterns.

Agno: https://github.com/extendedmind/eb
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

from mahavishnu.core.adapters.base import (
    OrchestratorAdapter,
    AdapterType,
    AdapterCapabilities,
)
from mahavishnu.core.errors import AdapterInitializationError, WorkflowExecutionError

logger = logging.getLogger(__name__)


class AgnoAdapter(OrchestratorAdapter):
    """Agno multi-agent orchestration adapter.

    Features:
    - Crew creation and management
    - Task execution and batching
    - Result aggregation from multiple agents
    - Crew status monitoring
    - Agent collaboration patterns

    Architecture:
    ┌──────────────────────────────────┐
    │   Mahavishnu                 │
    │  • HTTP Client                │
    │  • Crew Manager             │
    │  • Task Distributor           │
    └──────────────┬─────────────────┘
                   │
                   ↓
         ┌──────────────────────┐
         │   Agno Server/API  │
         │  • Crew Management    │
         │  • Task Execution     │
         │  • Result Aggregation  │
         │  • Agent Collaboration │
         └──────────────────────┘
                   │
                   ↓
        ┌────────────────────┐
        │   AI Agents         │
        │  • Crew 1          │
        │  • Crew 2          │
        │  • Crew 3          │
        │  • Parallel Tasks   │
        └────────────────────┘
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str | None = None,
        timeout_seconds: int = 600,
        max_concurrent_tasks: int = 10,
    ):
        """Initialize AgnoAdapter.

        Args:
            api_url: Agno server URL (default: localhost:8000)
            api_key: Optional API authentication key
            timeout_seconds: Request timeout (default: 600 for AI tasks)
            max_concurrent_tasks: Maximum concurrent tasks (default: 10)
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout_seconds
        self.max_concurrent_tasks = max_concurrent_tasks
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

        logger.info(f"AgnoAdapter initialized (API: {self.api_url})")

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.AGNO

    @property
    def name(self) -> str:
        return "agno"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return supported capabilities."""
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
            has_cloud_ui=False,
        )

    async def initialize(self) -> None:
        """Initialize Agno API client.

        Raises:
            AdapterInitializationError: If client cannot connect to Agno API
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
                    f"Agno API health check failed: {response.status_code}"
                )

            logger.info("AgnoAdapter initialized successfully")

        except httpx.ConnectError as e:
            raise AdapterInitializationError(
                f"Cannot connect to Agno server at {self.api_url}: {e}"
            )
        except Exception as e:
            raise AdapterInitializationError(
                f"Failed to initialize AgnoAdapter: {e}"
            )

    async def create_crew(
        self,
        crew_name: str,
        crew_config: dict[str, Any],
    ) -> str:
        """Create Agno crew.

        Args:
            crew_name: Unique crew name
            crew_config: Crew configuration (agents, tasks, memory)

        Returns:
            crew_id: ULID crew identifier

        Raises:
            WorkflowExecutionError: If crew creation fails
        """
        await self._ensure_client()

        crew_id = generate_config_id()

        crew_spec = {
            "name": crew_name,
            "description": f"Mahavishnu crew: {crew_name}",
            "config": crew_config,
            "tags": ["mahavishnu", "crew"],
        }

        try:
            response = await self._client.post(
                "/api/crews/",
                json=crew_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 201:
                raise WorkflowExecutionError(
                    f"Failed to create crew {crew_name}: HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(f"Crew {crew_name} created: {crew_id}")

            return crew_id

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error creating crew: {e}")

    async def create_crew_from_config(
        self,
        config_path: str,
        crew_name: str | None = None,
    ) -> str:
        """Create crew from configuration file.

        Args:
            config_path: Path to crew configuration YAML/JSON
            crew_name: Optional crew name (default: filename)

        Returns:
            crew_id: ULID crew identifier

        Raises:
            WorkflowExecutionError: If crew creation fails
        """
        import json

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                crew_config = json.load(f)

            if not crew_name:
                crew_name = config_path.stem

        except FileNotFoundError:
            raise WorkflowExecutionError(f"Crew config not found: {config_path}")
        except Exception as e:
            raise WorkflowExecutionError(f"Failed to read crew config: {e}")

        return await self.create_crew(
            crew_name=crew_name,
            crew_config=crew_config,
        )

    async def execute_task(
        self,
        crew_id: str,
        task: dict[str, Any],
    ) -> str:
        """Execute task on crew.

        Args:
            crew_id: ULID crew identifier
            task: Task specification (prompt, context, etc.)

        Returns:
            execution_id: ULID task execution identifier

        Raises:
            WorkflowExecutionError: If task execution fails
        """
        await self._ensure_client()

        execution_id = generate_config_id()

        execution_spec = {
            "crew_id": crew_id,
            "task": task,
            "tags": ["mahavishnu", "task_execution"],
        }

        try:
            response = await self._client.post(
                "/api/tasks/execute",
                json=execution_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 201:
                raise WorkflowExecutionError(
                    f"Failed to execute task: HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(f"Task execution started: {execution_id}")

            return execution_id

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error executing task: {e}")

    async def execute_task_batch(
        self,
        crew_id: str,
        tasks: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Execute multiple tasks in parallel.

        Args:
            crew_id: ULID crew identifier
            tasks: List of task specifications

        Returns:
            Dictionary mapping task index -> execution_id

        Raises:
            WorkflowExecutionError: If batch execution fails
        """
        await self._ensure_client()

        batch_spec = {
            "crew_id": crew_id,
            "tasks": tasks,
            "tags": ["mahavishnu", "batch_execution"],
        }

        try:
            response = await self._client.post(
                "/api/tasks/batch",
                json=batch_spec,
                headers=self._get_auth_headers(),
            )

            if response.status_code != 201:
                raise WorkflowExecutionError(
                    f"Failed to execute batch: HTTP {response.status_code}"
                )

            result = response.json()
            logger.info(f"Batch execution started with {len(tasks)} tasks")

            return result

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error executing batch: {e}")

    async def get_crew_status(
        self,
        crew_id: str,
    ) -> dict[str, Any]:
        """Get crew execution status.

        Args:
            crew_id: ULID crew identifier

        Returns:
            Crew status with active tasks, completed tasks, etc.
        """
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"/api/crews/{crew_id}",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to get crew status: HTTP {response.status_code}"
                )

            return response.json()

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error getting crew status: {e}")

    async def get_crew_results(
        self,
        crew_id: str,
    ) -> list[dict[str, Any]]:
        """Get aggregated results from crew execution.

        Args:
            crew_id: ULID crew identifier

        Returns:
            List of task result dictionaries
        """
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"/api/crews/{crew_id}/results",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to get crew results: HTTP {response.status_code}"
                )

            return response.json()

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error getting results: {e}")

    async def list_crews(self) -> list[dict[str, Any]]:
        """List all Agno crews.

        Returns:
            List of crew metadata dictionaries
        """
        await self._ensure_client()

        try:
            response = await self._client.get(
                "/api/crews/",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to list crews: HTTP {response.status_code}"
                )

            return response.json()

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error listing crews: {e}")

    async def cancel_crew(
        self,
        crew_id: str,
    ) -> bool:
        """Cancel running crew execution.

        Args:
            crew_id: ULID crew identifier

        Returns:
            True if cancellation succeeded

        Raises:
            WorkflowExecutionError: If cancellation fails
        """
        await self._ensure_client()

        try:
            response = await self._client.post(
                f"/api/crews/{crew_id}/cancel",
                headers=self._get_auth_headers(),
            )

            if response.status_code != 200:
                raise WorkflowExecutionError(
                    f"Failed to cancel crew {crew_id}: HTTP {response.status_code}"
                )

            logger.info(f"Crew {crew_id} cancelled")
            return True

        except httpx.HTTPError as e:
            raise WorkflowExecutionError(f"HTTP error cancelling crew: {e}")

    async def shutdown(self) -> None:
        """Shutdown Agno adapter and cleanup resources.

        Closes HTTP client and performs cleanup.
        """
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("AgnoAdapter shut down")

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mahavishnu-Agno/1.0",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            raise AdapterInitializationError(
                "AgnoAdapter not initialized. Call initialize() first."
            )
