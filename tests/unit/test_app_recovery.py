"""Tests for app startup recovery from Dhara."""

from datetime import UTC, datetime, timedelta

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.approval_manager import (
    ApprovalManager,
    ApprovalOption,
    ApprovalRequest,
)


class _FakeDharaRecoveryBackend:
    def __init__(self) -> None:
        self._workflow_entries = [
            {
                "execution_id": "wf-running",
                "status": "running",
                "workflow_name": "sweep",
            },
            {
                "execution_id": "wf-completed",
                "status": "completed",
                "workflow_name": "sweep",
            },
        ]
        self._approval_entries = [
            (
                "approval/v1/approval-001",
                ApprovalRequest(
                    id="approval-001",
                    approval_type="publish",
                    context={"version": "1.0.0"},
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    options=[
                        ApprovalOption(
                            label="Publish to PyPI",
                            description="Publish the new version to PyPI",
                            is_recommended=True,
                        )
                    ],
                ).to_dict(),
            )
        ]
        self._routing_entries = [
            {
                "task_class": "workflow",
                "task_type": "workflow",
                "pool_id": "pool-a",
                "selector": "least_loaded",
            },
            {
                "task_class": "ai_task",
                "task_type": "ai_task",
                "pool_id": "pool-b",
                "selector": "affinity",
            },
        ]

    async def recover_workflows(self) -> list[dict]:
        return list(self._workflow_entries)

    async def recover_routing_decisions(self) -> list[dict]:
        return list(self._routing_entries)

    async def list_prefix(self, prefix: str) -> list[tuple[str, dict]]:
        if prefix == "approval/v1/":
            return list(self._approval_entries)
        return []


@pytest.mark.asyncio
async def test_app_recovers_running_workflows_and_pending_approvals() -> None:
    app = MahavishnuApp.__new__(MahavishnuApp)
    app._dhara_state = _FakeDharaRecoveryBackend()
    app.active_workflows = set()
    app.approval_manager = ApprovalManager()

    await app._recover_workflow_state_from_dhara()
    await app._recover_approvals_from_dhara()

    assert app.active_workflows == {"wf-running"}
    recovered = app.approval_manager.get_request("approval-001")
    assert recovered is not None
    assert recovered.approval_type == "publish"
    assert recovered.context["version"] == "1.0.0"

    routing = await app.get_recovered_routing_decisions()
    assert len(routing) == 2
    workflow_routing = await app.get_recovered_routing_decisions(task_class="workflow")
    assert workflow_routing == [routing[0]]
