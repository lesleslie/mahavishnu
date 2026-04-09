"""Unit tests for core.workflow_state."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.status import WorkflowStatus
from mahavishnu.core.workflow_state import WorkflowState


@pytest.mark.asyncio
async def test_local_create_update_get_list_delete_flow() -> None:
    manager = WorkflowState(opensearch_client=None)

    created = await manager.create("wf-1", {"task_type": "check"}, ["repo-a", "repo-b"])
    assert created["id"] == "wf-1"
    assert created["status"] == WorkflowStatus.PENDING
    assert created["progress"] == 0

    await manager.update("wf-1", status=WorkflowStatus.RUNNING.value, progress=25)
    current = await manager.get("wf-1")
    assert current is not None
    assert current["status"] == WorkflowStatus.RUNNING.value
    assert current["progress"] == 25

    all_items = await manager.list_workflows()
    assert len(all_items) == 1
    running_items = await manager.list_workflows(status=WorkflowStatus.RUNNING)
    assert len(running_items) == 1
    completed_items = await manager.list_workflows(status=WorkflowStatus.COMPLETED)
    assert completed_items == []

    await manager.delete("wf-1")
    assert await manager.get("wf-1") is None


@pytest.mark.asyncio
async def test_update_nonexistent_local_workflow_is_noop() -> None:
    manager = WorkflowState(opensearch_client=None)
    await manager.update("missing", status=WorkflowStatus.RUNNING.value)
    assert manager.local_states == {}


@pytest.mark.asyncio
async def test_update_progress_handles_zero_total_and_nonzero_total() -> None:
    manager = WorkflowState(opensearch_client=None)
    await manager.create("wf-2", {"task_type": "check"}, ["repo"])

    await manager.update_progress("wf-2", completed=5, total=0)
    state = await manager.get("wf-2")
    assert state is not None
    assert state["progress"] == 0

    await manager.update_progress("wf-2", completed=1, total=4)
    state = await manager.get("wf-2")
    assert state is not None
    assert state["progress"] == 25


@pytest.mark.asyncio
async def test_get_completed_count_add_result_and_add_error() -> None:
    manager = WorkflowState(opensearch_client=None)
    await manager.create("wf-3", {"task_type": "check"}, ["repo"])

    assert await manager.get_completed_count("wf-3") == 0
    assert await manager.get_completed_count("missing") == 0

    await manager.add_result("wf-3", {"repo": "a", "ok": True})
    await manager.add_error("wf-3", {"repo": "b", "error": "boom"})

    state = await manager.get("wf-3")
    assert state is not None
    assert len(state["results"]) == 1
    assert len(state["errors"]) == 1
    assert await manager.get_completed_count("wf-3") == 2

    # Missing workflow should be a no-op
    await manager.add_result("missing", {"repo": "x"})
    await manager.add_error("missing", {"repo": "x", "error": "e"})


@pytest.mark.asyncio
async def test_opensearch_success_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import mahavishnu.core.workflow_state as workflow_state_module

    monkeypatch.setattr(workflow_state_module, "OPENSEARCH_AVAILABLE", True)

    mock_client = AsyncMock()
    mock_client.get.return_value = {"_source": {"id": "wf-os", "status": "running"}}
    mock_client.search.return_value = {
        "hits": {"hits": [{"_source": {"id": "wf-os-1"}}, {"_source": {"id": "wf-os-2"}}]}
    }

    manager = WorkflowState(opensearch_client=mock_client)

    await manager.create("wf-os", {"task_type": "run"}, ["repo"])
    mock_client.index.assert_awaited_once()

    await manager.update("wf-os", status=WorkflowStatus.RUNNING.value)
    mock_client.update.assert_awaited_once()

    fetched = await manager.get("wf-os")
    assert fetched == {"id": "wf-os", "status": "running"}
    mock_client.get.assert_awaited_once()

    listed = await manager.list_workflows(status=WorkflowStatus.RUNNING, limit=2)
    assert listed == [{"id": "wf-os-1"}, {"id": "wf-os-2"}]
    mock_client.search.assert_awaited_once()

    await manager.delete("wf-os")
    mock_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_opensearch_get_falls_back_to_local_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mahavishnu.core.workflow_state as workflow_state_module

    monkeypatch.setattr(workflow_state_module, "OPENSEARCH_AVAILABLE", True)

    mock_client = AsyncMock()
    mock_client.get.side_effect = RuntimeError("opensearch down")
    manager = WorkflowState(opensearch_client=mock_client)
    manager.local_states["wf-local"] = {"id": "wf-local", "status": "pending"}

    result = await manager.get("wf-local")
    assert result == {"id": "wf-local", "status": "pending"}


@pytest.mark.asyncio
async def test_opensearch_list_falls_back_to_local_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mahavishnu.core.workflow_state as workflow_state_module

    monkeypatch.setattr(workflow_state_module, "OPENSEARCH_AVAILABLE", True)

    mock_client = AsyncMock()
    mock_client.search.side_effect = RuntimeError("search failed")
    manager = WorkflowState(opensearch_client=mock_client)
    manager.local_states["wf-1"] = {"id": "wf-1", "status": WorkflowStatus.RUNNING.value}
    manager.local_states["wf-2"] = {"id": "wf-2", "status": WorkflowStatus.COMPLETED.value}

    running = await manager.list_workflows(status=WorkflowStatus.RUNNING, limit=10)
    assert running == [{"id": "wf-1", "status": WorkflowStatus.RUNNING.value}]

    limited = await manager.list_workflows(limit=1)
    assert len(limited) == 1


@pytest.mark.asyncio
async def test_opensearch_delete_falls_back_to_local_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mahavishnu.core.workflow_state as workflow_state_module

    monkeypatch.setattr(workflow_state_module, "OPENSEARCH_AVAILABLE", True)

    mock_client = AsyncMock()
    mock_client.delete.side_effect = RuntimeError("delete failed")
    manager = WorkflowState(opensearch_client=mock_client)
    manager.local_states["wf-to-delete"] = {"id": "wf-to-delete"}

    await manager.delete("wf-to-delete")
    assert "wf-to-delete" not in manager.local_states
