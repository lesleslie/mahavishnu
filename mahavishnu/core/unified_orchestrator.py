"""Unified workflow orchestrator.

Coordinates Prefect, Agno, and LlamaIndex adapters through intelligent task routing
and cross-adapter state synchronization. Enables complex multi-adapter
workflows rather than isolated adapter execution.

Architecture:
    User Request → TaskRouter → Adapter Selection → Execution
    TaskRouter coordinates with StateManager for unified context
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from mahavishnu.core.task_router import TaskRouter, AdapterManager, StateManager
from mahavishnu.core.adapters.base import AdapterType

try:
    from oneiric.core.ulid import generate_config_id
except ImportError:
    def generate_config_id() -> str:
        import uuid
        return uuid.uuid4().hex

from mahavishnu.core.errors import (
    MahavishnuError,
    ConfigurationError,
)


class UnifiedOrchestrator:
    """Unified workflow orchestrator using TaskRouter.

    Replaces direct adapter usage with intelligent routing:
    - Automatic adapter selection based on task requirements
    - Cross-adapter state synchronization
    - Unified workflow context across all adapters
    - Graceful degradation and failover
    """

    def __init__(
        self,
        task_router: TaskRouter | None = None,
    ):
        """Initialize unified orchestrator.

        Args:
            task_router: Optional TaskRouter instance. If None, creates a default TaskRouter
            with sensible defaults for optional components.
        """
        # Use TaskRouter or create default with optional components
        if task_router is None:
            from mahavishnu.core.task_router import TaskRouter
            self.task_router = TaskRouter()
        else:
            self.task_router = task_router

        self.task_router = task_router or TaskRouter()

    async def execute_workflow(
        self,
        workflow_name: str,
        workflow_type: str = "workflow",  # workflow, ai_task, rag_query
        tasks: list[dict[str, Any]] = None,  # Default to empty list
        repos: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute unified workflow with intelligent adapter routing.

        Args:
            workflow_name: Unique workflow identifier
            workflow_type: Type of workflow (workflow, ai_task, rag_query)
            tasks: List of task specifications
            repos: Optional list of repository paths
            metadata: Optional workflow metadata

        Returns:
            workflow_id: ULID workflow identifier

        Raises:
            ConfigurationError: If workflow configuration is invalid
        """
        workflow_id = generate_config_id()

        # Create workflow state
        await self.task_router.state_manager.create_workflow_state(
            workflow_id=workflow_id,
            adapter_type="task_router",  # Unified orchestrator
            initial_state={
                "workflow_name": workflow_name,
                "workflow_type": workflow_type,
                "status": "initializing",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

        try:
            # Execute tasks with graceful fallback across adapters
            results = []
            preference_order = [
                AdapterType.PREFECT,
                AdapterType.AGNO,
                AdapterType.LLAMAINDEX,
            ]

            for task in tasks:
                # Execute with automatic fallback
                execution_result = await self.task_router.execute_with_fallback(
                    task=task,
                    preference_order=preference_order,
                    max_retries=3,
                    retry_delay_base=0.1,
                )

                if execution_result["success"]:
                    # Task succeeded on some adapter
                    adapter_type = execution_result["adapter"]
                    execution_id = execution_result["result"]

                    # Update workflow state with successful execution
                    await self.task_router.state_manager.update_adapter_state(
                        workflow_id=workflow_id,
                        adapter_type=adapter_type,
                        state={
                            "status": "running",
                            "execution_id": execution_id,
                            "started_at": datetime.now(UTC).isoformat(),
                            "fallback_chain": execution_result["fallback_chain"],
                            "total_attempts": execution_result["total_attempts"],
                        },
                    )

                    results.append({
                        "task": task,
                        "adapter": adapter_type.value,
                        "execution_id": execution_id,
                        "fallback_used": len(execution_result["fallback_chain"]) > 1,
                    })

                else:
                    # All adapters failed for this task
                    raise ConfigurationError(
                        f"All adapters failed for task: {task.get('task_type', 'unknown')}. "
                        f"Attempted: {execution_result['fallback_chain']}. "
                        f"Error: {execution_result.get('error', 'Unknown')}"
                    )

            # Update workflow state to completed
            await self.task_router.state_manager.update_adapter_state(
                workflow_id=workflow_id,
                adapter_type="task_router",
                state={
                    "status": "completed",
                    "results": results,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

            return workflow_id

        except Exception as e:
            # Log error and update state
            await self.task_router.state_manager.update_adapter_state(
                workflow_id=workflow_id,
                adapter_type="task_router",
                state={
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

            raise MahavishnuError(f"Workflow execution failed: {e}")

    async def get_workflow_status(
        self,
        workflow_id: str,
    ) -> dict[str, Any]:
        """Get status of unified workflow.

        Args:
            workflow_id: ULID workflow identifier

        Returns:
            Complete workflow state with all adapter statuses
        """
        state = await self.task_router.state_manager.get_workflow_state(workflow_id)

        if not state:
            raise MahavishnuError(f"Workflow {workflow_id} not found")

        return state

    async def cancel_workflow(
        self,
        workflow_id: str,
    ) -> bool:
        """Cancel running workflow.

        Args:
            workflow_id: ULID workflow identifier

        Returns:
            True if cancellation successful
        """
        state = await self.task_router.state_manager.get_workflow_state(workflow_id)

        if not state:
            raise MahavishnuError(f"Workflow {workflow_id} not found")

        # Cancel with all adapters
        for adapter_name in state.get("adapter_states", {}):
            if adapter_name == "task_router":
                continue  # Task router doesn't execute

            try:
                adapter = self.task_router.adapter_manager.get_adapter(adapter_name)
                if adapter and hasattr(adapter, "cancel_workflow"):
                    await adapter.cancel_workflow(workflow_id)
                    logger.info(f"Cancelled {adapter_name} workflow: {workflow_id}")
            except Exception as e:
                logger.error(f"Failed to cancel with {adapter_name}: {e}")

        await self.task_router.state_manager.update_adapter_state(
            workflow_id=workflow_id,
            adapter_type="task_router",
            state={
                "status": "cancelled",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

        return True

    async def get_adapter_health(self) -> dict[str, Any]:
        """Get health status of all adapters in unified system.

        Returns:
            Health status for TaskRouter and all registered adapters
        """
        router_health = await self.task_router.get_health()

        adapter_health = {}
        for adapter_name, adapter in self.task_router.adapter_manager.adapters.items():
            if adapter and hasattr(adapter, "get_health"):
                try:
                    adapter_health[adapter_name] = await adapter.get_health()
                except Exception as e:
                    adapter_health[adapter_name] = {
                        "status": "error",
                        "error": str(e),
                    }

        return {
            "task_router": router_health,
            "adapters": adapter_health,
        }
