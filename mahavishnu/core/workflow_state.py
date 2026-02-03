"""Workflow state tracking for Mahavishnu."""

from datetime import datetime
from enum import Enum
from typing import Any

# Try to import OpenSearch, with fallback if not available
try:
    from opensearchpy import AsyncOpenSearch

    OPENSEARCH_AVAILABLE = True
except ImportError:
    OPENSEARCH_AVAILABLE = False
    AsyncOpenSearch = None


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class WorkflowState:
    """Track workflow execution state"""

    def __init__(self, opensearch_client=None) -> None:
        self.opensearch = opensearch_client
        self.local_states: dict = {}  # Fallback in-memory storage

    async def create(self, workflow_id: str, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Create new workflow state"""
        state = {
            "id": workflow_id,
            "status": WorkflowStatus.PENDING,
            "task": task,
            "repos": repos,
            "created_at": datetime.now().isoformat(),
            "progress": 0,
            "results": [],
            "errors": [],
            "updated_at": datetime.now().isoformat(),
        }

        if self.opensearch and OPENSEARCH_AVAILABLE:
            # Store in OpenSearch
            await self.opensearch.index(index="mahavishnu_workflows", id=workflow_id, body=state)
        else:
            # Store in local memory as fallback
            self.local_states[workflow_id] = state

        return state

    async def update(self, workflow_id: str, **updates: Any) -> None:
        """Update workflow state"""
        updates["updated_at"] = datetime.now().isoformat()

        if self.opensearch and OPENSEARCH_AVAILABLE:
            # Update in OpenSearch
            await self.opensearch.update(
                index="mahavishnu_workflows", id=workflow_id, body={"doc": updates}
            )
        else:
            # Update in local memory as fallback
            if workflow_id in self.local_states:
                self.local_states[workflow_id].update(updates)

    async def get(self, workflow_id: str) -> dict | None:
        """Get workflow state"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                response = await self.opensearch.get(index="mahavishnu_workflows", id=workflow_id)
                source = response.get("_source")
                return source if isinstance(source, dict) else None
            except Exception:
                # If OpenSearch fails, fall back to local storage
                return self.local_states.get(workflow_id)
        else:
            # Use local memory storage
            return self.local_states.get(workflow_id)

    async def list_workflows(
        self, status: WorkflowStatus | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List workflows, optionally filtered by status"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                query = {"query": {"match_all": {}}}
                if status:
                    query["query"] = {"term": {"status.keyword": status.value}}

                response = await self.opensearch.search(
                    index="mahavishnu_workflows", body=query, size=limit
                )

                return [hit["_source"] for hit in response["hits"]["hits"]]
            except Exception:
                # Fall back to local storage
                workflows = list(self.local_states.values())
                if status:
                    workflows = [w for w in workflows if w.get("status") == status.value]
                return workflows[:limit]
        else:
            # Use local memory storage
            workflows = list(self.local_states.values())
            if status:
                workflows = [w for w in workflows if w.get("status") == status.value]
            return workflows[:limit]

    async def delete(self, workflow_id: str) -> None:
        """Delete workflow state"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                await self.opensearch.delete(index="mahavishnu_workflows", id=workflow_id)
            except Exception:
                # If OpenSearch fails, remove from local storage
                self.local_states.pop(workflow_id, None)
        else:
            # Remove from local memory
            self.local_states.pop(workflow_id, None)

    async def update_progress(self, workflow_id: str, completed: int, total: int) -> None:
        """Update workflow progress percentage"""
        progress = int((completed / total) * 100) if total > 0 else 0
        await self.update(workflow_id, progress=progress)

    async def get_completed_count(self, workflow_id: str) -> int:
        """Get the count of completed repos for a workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Count of completed repos (results + errors)
        """
        state = await self.get(workflow_id)
        if not state:
            return 0

        results_count = len(state.get("results", []))
        errors_count = len(state.get("errors", []))

        return results_count + errors_count

    async def add_result(self, workflow_id: str, result: dict[str, Any]) -> None:
        """Add a result to the workflow"""
        state = await self.get(workflow_id)
        if state:
            results = state.get("results", [])
            results.append(result)
            await self.update(workflow_id, results=results)

    async def add_error(self, workflow_id: str, error: dict[str, Any]) -> None:
        """Add an error to the workflow"""
        state = await self.get(workflow_id)
        if state:
            errors = state.get("errors", [])
            errors.append(error)
            await self.update(workflow_id, errors=errors)
