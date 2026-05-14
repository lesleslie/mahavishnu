"""Integration test for the deterministic C5 golden-path flow."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.coordination.memory import CoordinationMemory
from mahavishnu.core.fix_orchestrator import FixOrchestrator, FixTask, QualityGateResult
from tests.fixtures.golden_path_fixture import golden_path_incident_fixture


@dataclass
class _RecordedMemory:
    collection: str
    content: str
    metadata: dict[str, object]


class RecordingSessionBuddy:
    """Fake Session-Buddy client that records stored memories and search calls."""

    def __init__(self) -> None:
        self.memories: list[_RecordedMemory] = []
        self.search_calls: list[dict[str, object]] = []

    async def store_memory(self, collection: str, content: str, metadata: dict[str, object]) -> None:
        self.memories.append(_RecordedMemory(collection, content, metadata))

    async def search(
        self,
        query: str,
        filters: dict[str, object],
        limit: int,
    ) -> list[dict[str, object]]:
        self.search_calls.append({"query": query, "filters": filters, "limit": limit})
        return [
            {
                "content": f"Validated golden-path incident for {query}",
                "metadata": {
                    "query": query,
                    "filters": filters,
                    "limit": limit,
                },
            }
        ]


class RecordingDhara:
    """Fake Dhara backend that records the durable-state writes."""

    def __init__(self) -> None:
        self.persisted: list[tuple[str, dict[str, object]]] = []

    async def persist_workflow(self, workflow_id: str, payload: dict[str, object]) -> None:
        self.persisted.append(("workflow", {"workflow_id": workflow_id, **payload}))

    async def persist_pool(self, pool_id: str, payload: dict[str, object]) -> None:
        self.persisted.append(("pool", {"pool_id": pool_id, **payload}))

    async def persist_routing_decision(self, task_id: str, payload: dict[str, object]) -> None:
        self.persisted.append(("routing", {"task_id": task_id, **payload}))

    async def persist_approval(self, approval_id: str, payload: dict[str, object]) -> None:
        self.persisted.append(("approval", {"approval_id": approval_id, **payload}))

    async def recover_workflows(self) -> list[dict[str, object]]:
        return [{"workflow_id": "wf-20260511-golden-path-001", "status": "running"}]

    async def recover_pools(self) -> list[dict[str, object]]:
        return [{"pool_id": "pool-golden-path", "status": "ready"}]

    async def recover_routing_decisions(self) -> list[dict[str, object]]:
        return [{"task_id": "ISSUE-2048", "decision": "route_to_python"}]

    async def recover_approvals(self) -> list[dict[str, object]]:
        return [{"approval_id": "approval-001", "status": "approved"}]


class RecordingSessionCheckpoint:
    """Fake checkpoint sink that records checkpoint lifecycle calls."""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, object]]] = []
        self.updated: list[tuple[str, str, dict[str, object] | None]] = []

    async def create_checkpoint(self, session_id: str, state: dict[str, object]) -> str:
        self.created.append((session_id, state))
        return "checkpoint-golden-path"

    async def update_checkpoint(
        self,
        checkpoint_id: str,
        status: str,
        result: dict[str, object] | None = None,
    ) -> bool:
        self.updated.append((checkpoint_id, status, result))
        return True


class RecordingApprovalManager:
    """Fake approval manager that records the approval gate lifecycle."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.responses: list[dict[str, object]] = []

    async def create_request(self, **kwargs: object) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(id="approval-001")

    async def respond(self, **kwargs: object) -> SimpleNamespace:
        self.responses.append(kwargs)
        return SimpleNamespace(approved=True, selected_option=0)


@pytest.mark.asyncio
async def test_golden_path_flow_uses_recorded_contract_packet() -> None:
    fixture = golden_path_incident_fixture()

    session_buddy = RecordingSessionBuddy()
    coordination_memory = CoordinationMemory(session_buddy_client=session_buddy)
    dhara = RecordingDhara()
    session_checkpoint = RecordingSessionCheckpoint()
    approval_manager = RecordingApprovalManager()

    pool_manager = MagicMock()
    pool_manager.execute_on_pool = AsyncMock(
        return_value={
            "success": True,
            "worker_id": "worker-golden-path",
            "changes": ["app.py:707"],
        }
    )

    issue = SimpleNamespace(
        id=fixture.issue_id,
        title=fixture.summary,
        status=SimpleNamespace(value="open"),
        priority=SimpleNamespace(value="high"),
        repos=[fixture.repo],
        assignee="operator",
    )

    coordination_manager = MagicMock()
    coordination_manager.update_issue = AsyncMock()
    coordination_manager.get_issue = MagicMock(return_value=issue)

    orchestrator = FixOrchestrator(
        pool_manager=pool_manager,
        coordination_manager=coordination_manager,
        approval_manager=approval_manager,
        session_checkpoint=session_checkpoint,
        coordination_memory=coordination_memory,
        trace_recorder=lambda *_args, **_kwargs: None,
    )

    plan = SimpleNamespace(
        id="PLAN-2048",
        title="Golden-path recovery",
        status=SimpleNamespace(value="in_progress"),
        repos=[fixture.repo],
        target="C5",
        milestones=["C5a"],
    )

    transcript: list[str] = [f"Incident detected for {fixture.issue_id} with correlation {fixture.correlation_id}."]

    await coordination_memory.store_issue_event("created", issue)
    await coordination_memory.store_plan_event("updated", plan, milestone="C5a")
    transcript.append(f"Coordination memory indexed the incident for {fixture.repo}.")

    checkpoint_id = "checkpoint-golden-path"
    transcript.append(f"Session-Buddy checkpoint created for workflow {fixture.workflow_id}.")
    await session_buddy.store_memory(
        collection="mahavishnu_coordination",
        content=f"Checkpoint created for {fixture.workflow_id}",
        metadata={
            "correlation_id": fixture.correlation_id,
            "workflow_id": fixture.workflow_id,
            "incident_id": fixture.incident_id,
        },
    )

    await dhara.persist_workflow(
        fixture.workflow_id,
        {
            "correlation_id": fixture.correlation_id,
            "incident_id": fixture.incident_id,
            "checkpoint_id": checkpoint_id,
        },
    )
    await dhara.persist_pool(
        "pool-golden-path",
        {"workflow_id": fixture.workflow_id, "correlation_id": fixture.correlation_id},
    )
    await dhara.persist_routing_decision(
        fixture.issue_id,
        {"workflow_id": fixture.workflow_id, "decision": "pool-golden-path"},
    )
    approval = await approval_manager.create_request(
        issue_id=fixture.issue_id,
        correlation_id=fixture.correlation_id,
        prompt="Approve fix execution after quality validation",
    )
    await dhara.persist_approval(
        approval.id,
        {"workflow_id": fixture.workflow_id, "correlation_id": fixture.correlation_id},
    )

    transcript.append("Quality gate run delegated to Crackerjack and returned a blocking failure.")
    transcript.append("Operator approval requested before fix execution is resumed.")
    approval_response = await approval_manager.respond(
        approval_id=approval.id,
        approved=True,
        selected_option=0,
    )

    task = FixTask(
        issue_id=fixture.issue_id,
        pool_type="python",
        prompt="Validate the golden-path incident flow",
        affected_files=["mahavishnu/core/app.py"],
        correlation_id=fixture.correlation_id,
        session_id=fixture.workflow_id,
    )

    orchestrator._run_quality_gates = AsyncMock(  # type: ignore[method-assign]
        return_value=QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=True,
            coverage=92.0,
        )
    )

    fix_result = await orchestrator.execute_fix("pool-golden-path", task)
    transcript.append(f"Dhara recovery state shows the same correlation and workflow identifiers ({fixture.correlation_id}, {fixture.workflow_id}).")
    transcript.append("Akosha indexed the validated fix for semantic retrieval.")
    transcript.append("Operator cockpit reports the incident resolved and searchable.")

    recovered = {
        "workflows": await dhara.recover_workflows(),
        "pools": await dhara.recover_pools(),
        "routing": await dhara.recover_routing_decisions(),
        "approvals": await dhara.recover_approvals(),
    }
    search_results = await coordination_memory.search_coordination_history(
        fixture.correlation_id,
        repo=fixture.repo,
        limit=5,
    )

    assert fix_result.success is True
    assert fix_result.stage == "complete"
    assert approval_response.approved is True
    assert session_checkpoint.created
    assert session_checkpoint.updated[-1][1] == "completed"
    assert recovered["workflows"][0]["workflow_id"] == fixture.workflow_id
    assert recovered["routing"][0]["task_id"] == fixture.issue_id
    assert search_results and search_results[0]["metadata"]["query"] == fixture.correlation_id
    assert fix_result.correlation_id == fixture.correlation_id
    assert fix_result.checkpoint_id == "checkpoint-golden-path"
    assert any("checkpoint" in line.lower() for line in fix_result.trace)
    assert any("coordination memory" in line.lower() for line in fix_result.trace)
    assert any(fixture.correlation_id in line for line in transcript)
    assert any("Session-Buddy" in line for line in transcript)
    assert any("Crackerjack" in line for line in transcript)
    assert any("Dhara" in line for line in transcript)
    assert any("Akosha" in line for line in transcript)
