"""Unit tests for mahavishnu's task-event publisher.

The handoff's orphan event is what the sweeper consumes to recover a
task whose binding was lost. It used to be published through
session-buddy's ``publish_task_event_raw``, which writes through a
module-level publisher singleton that is assigned in EXACTLY one place
in the fleet — inside the session-buddy server process. From
mahavishnu it was therefore a silent no-op: the orphan event was never
written, so the sweeper had nothing to consume and the v1.1
error-handling matrix never ran.

Mahavishnu now publishes onto ``bodai:events`` itself.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools import tasks_handoff as th


class _FakeAdapter:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    async def enqueue(self, payload: dict[str, Any]) -> Any:
        self.enqueued.append(payload)
        return "1-0"


@pytest.mark.unit
async def test_the_publisher_writes_onto_bodai_events() -> None:
    """The event lands on the stream the sweeper consumes."""
    adapter = _FakeAdapter()
    with patch.object(th, "_get_publisher_adapter", return_value=adapter):
        await th._publish_task_event("task.handoff_orphan", {"task_id": "t-1"})

    assert len(adapter.enqueued) == 1
    entry = adapter.enqueued[0]
    # The channel is a FIELD in the payload — the sweeper filters on
    # ``entry["payload"]["channel"]``, never on the entry root.
    assert entry["channel"] == "task.handoff_orphan"
    assert entry["task_id"] == "t-1"


@pytest.mark.unit
async def test_a_publish_failure_never_blocks_the_caller() -> None:
    """A failed audit publish must not fail the handoff."""
    adapter = MagicMock()
    adapter.enqueue = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch.object(th, "_get_publisher_adapter", return_value=adapter):
        await th._publish_task_event("task.handoff_orphan", {"task_id": "t-1"})


@pytest.mark.unit
async def test_a_missing_publisher_never_blocks_the_caller() -> None:
    with patch.object(
        th,
        "_get_publisher_adapter",
        side_effect=RuntimeError("no adapter"),
    ):
        await th._publish_task_event("task.handoff_orphan", {"task_id": "t-1"})


@pytest.mark.unit
async def test_the_orphan_event_carries_the_fields_the_sweeper_reads() -> None:
    """The sweeper's ``TaskHandoffOrphan`` filters the payload by field
    name, so the names must match exactly."""
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskHandoffOrphan

    adapter = _FakeAdapter()
    with patch.object(th, "_get_publisher_adapter", return_value=adapter):
        await th._publish_task_event(
            "task.handoff_orphan",
            {
                "task_id": "t-1",
                "workflow_id": "wf-1",
                "reason": "step_3_update_failed",
                "orphaned_at": "2026-10-30T00:00:00+00:00",
                "actor": "default",
            },
        )

    entry = adapter.enqueued[0]
    parsed = TaskHandoffOrphan(
        **{k: v for k, v in entry.items() if k in TaskHandoffOrphan.model_fields}
    )
    assert parsed.task_id == "t-1"
    assert parsed.workflow_id == "wf-1"
    assert parsed.reason == "step_3_update_failed"


@pytest.mark.unit
async def test_the_handoff_started_event_is_published() -> None:
    adapter = _FakeAdapter()
    with patch.object(th, "_get_publisher_adapter", return_value=adapter):
        th._publish_task_handoff_started(task_id="t-1", actor="default")
        # The helper schedules the publish on the loop.
        await _drain()

    assert any(e.get("channel") == "task.handoff_started" for e in adapter.enqueued)


@pytest.mark.unit
async def test_the_handoff_completed_event_is_published() -> None:
    adapter = _FakeAdapter()
    with patch.object(th, "_get_publisher_adapter", return_value=adapter):
        th._publish_task_handoff_completed(
            task_id="t-1",
            workflow_id="wf-1",
            adapter="prefect",
            actor="default",
        )
        await _drain()

    completed = [e for e in adapter.enqueued if e.get("channel") == "task.handoff_completed"]
    assert completed, adapter.enqueued
    assert completed[0]["workflow_id"] == "wf-1"


async def _drain() -> None:
    """Let the scheduled publish tasks run."""
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)
