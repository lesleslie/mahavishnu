"""Workflow state tracking for Mahavishnu."""
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import asyncio

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

    def __init__(self, opensearch_client=None):
        self.opensearch = opensearch_client
        self.local_states = {}  # Fallback in-memory storage

    async def create(self, workflow_id: str, task: dict, repos: list[str]) -> dict:
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
            "updated_at": datetime.now().isoformat()
        }
        
        if self.opensearch and OPENSEARCH_AVAILABLE:
            # Store in OpenSearch
            await self.opensearch.index(
                index="mahavishnu_workflows", 
                id=workflow_id, 
                body=state
            )
        else:
            # Store in local memory as fallback
            self.local_states[workflow_id] = state
            
        return state

    async def update(self, workflow_id: str, **updates):
        """Update workflow state"""
        updates['updated_at'] = datetime.now().isoformat()
        
        if self.opensearch and OPENSEARCH_AVAILABLE:
            # Update in OpenSearch
            await self.opensearch.update(
                index="mahavishnu_workflows", 
                id=workflow_id, 
                body={"doc": updates}
            )
        else:
            # Update in local memory as fallback
            if workflow_id in self.local_states:
                self.local_states[workflow_id].update(updates)

    async def get(self, workflow_id: str) -> Optional[dict]:
        """Get workflow state"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                response = await self.opensearch.get(
                    index="mahavishnu_workflows", 
                    id=workflow_id
                )
                return response.get('_source')
            except Exception:
                # If OpenSearch fails, fall back to local storage
                return self.local_states.get(workflow_id)
        else:
            # Use local memory storage
            return self.local_states.get(workflow_id)

    async def list_workflows(self, status: Optional[WorkflowStatus] = None, limit: int = 100) -> List[dict]:
        """List workflows, optionally filtered by status"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                query = {"query": {"match_all": {}}}
                if status:
                    query["query"] = {"term": {"status.keyword": status.value}}
                
                response = await self.opensearch.search(
                    index="mahavishnu_workflows",
                    body=query,
                    size=limit
                )
                
                return [hit["_source"] for hit in response["hits"]["hits"]]
            except Exception:
                # Fall back to local storage
                workflows = list(self.local_states.values())
                if status:
                    workflows = [w for w in workflows if w.get('status') == status.value]
                return workflows[:limit]
        else:
            # Use local memory storage
            workflows = list(self.local_states.values())
            if status:
                workflows = [w for w in workflows if w.get('status') == status.value]
            return workflows[:limit]

    async def delete(self, workflow_id: str):
        """Delete workflow state"""
        if self.opensearch and OPENSEARCH_AVAILABLE:
            try:
                await self.opensearch.delete(
                    index="mahavishnu_workflows",
                    id=workflow_id
                )
            except Exception:
                # If OpenSearch fails, remove from local storage
                self.local_states.pop(workflow_id, None)
        else:
            # Remove from local memory
            self.local_states.pop(workflow_id, None)

    async def update_progress(self, workflow_id: str, completed: int, total: int):
        """Update workflow progress percentage"""
        progress = int((completed / total) * 100) if total > 0 else 0
        await self.update(workflow_id, progress=progress)

    async def add_result(self, workflow_id: str, result: dict):
        """Add a result to the workflow"""
        state = await self.get(workflow_id)
        if state:
            results = state.get('results', [])
            results.append(result)
            await self.update(workflow_id, results=results)

    async def add_error(self, workflow_id: str, error: dict):
        """Add an error to the workflow"""
        state = await self.get(workflow_id)
        if state:
            errors = state.get('errors', [])
            errors.append(error)
            await self.update(workflow_id, errors=errors)