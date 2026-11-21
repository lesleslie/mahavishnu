"""End-to-end Redis round-trip test for :class:`TaskOrphanSweeper`.

Task 12 of the v1.1 Bodai task-system plan. Proves the full recovery
flow against a real local Redis:

    1. Seed a ``task.handoff_orphan`` message into a unique test
       stream on a unique consumer group.
    2. Run :meth:`TaskOrphanSweeper._run_once` against the real
       Redis (one deterministic iteration; no ``asyncio.sleep``
       timing).
    3. Assert the three observable properties:
       (a) ``session_buddy.tasks_link_workflow`` was called with the
           workflow_id from the orphan payload,
       (b) a synthetic ``task.handoff_completed`` entry was emitted
           on the same stream (recovered downstream consumers can
           observe a clean handoff alongside the orphan),
       (c) the consumer group's PEL is empty (the source entry was
           acked — at-most-once replay semantics).

Marker policy: ``integration`` + ``requires_network``. The
``redis_client`` session fixture (in ``tests/integration/conftest.py``)
auto-skips the test on machines where ``127.0.0.1:6379`` is not
reachable, so CI without a Redis sidecar still collects the file
without a hard failure.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]


class _FakeSB:
    """Stand-in for the session-buddy MCP client.

    Records every ``tasks_link_workflow`` invocation so the test can
    assert the sweeper called it with the workflow_id pulled from
    the orphan payload. ``tasks_get`` returns an in-progress task
    so the idempotency guard does NOT short-circuit — the recovery
    side-effects must fire.

    ``tasks_link_workflow`` is the typed channel that is the only
    writer of ``Task.workflow_id``; the generic ``tasks_update``
    metadata bag cannot reach the field, so a sweeper that used it
    re-linked forever without binding anything. This fake therefore
    implements the typed channel, and the test asserts on it.
    """

    def __init__(self) -> None:
        self.updates: list[tuple[str, str]] = []

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        return {"id": task_id, "status": "in_progress"}

    async def tasks_link_workflow(
        self, task_id: str, workflow_id: str
    ) -> dict[str, Any]:
        self.updates.append((task_id, workflow_id))
        return {"id": task_id, "workflow_id": workflow_id}


async def test_sweeper_xreadgroup_recovers_orphan(redis_client: Any) -> None:
    """Real Redis: seed → _run_once → verify all three properties."""
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    # Per-test isolation: a unique stream + group name keeps parallel
    # pytest-xdist workers and repeat runs from clobbering each other.
    # The stream is deleted in the finally block so we never leak.
    stream = f"bodai:events:e2e-{uuid.uuid4().hex[:8]}"
    group = f"e2e-sweeper-{uuid.uuid4().hex[:8]}"
    consumer = "mahavishnu-test"

    # The consumer name MUST match the one we later read with in
    # xreadgroup from "0" — coredis 6.x's xreadgroup from a stream
    # position returns the consumer's own PEL only. We align the
    # sweeper's consumer with the test's read consumer to keep the
    # assertion deterministic without resorting to XRANGE scans.
    sb = _FakeSB()
    sweeper = TaskOrphanSweeper(
        stream=stream,
        consumer_group=group,
        consumer_name=consumer,
        block_ms=500,
        count=10,
        session_buddy_client=sb,
    )
    await sweeper.init()

    try:
        # Step 1 — seed one task.handoff_orphan entry.
        seed_id = await redis_client.xadd(
            stream,
            {
                "channel": "task.handoff_orphan",
                "task_id": "t-x",
                "workflow_id": "w-z",
                "reason": "step_3_update_failed",
                "orphaned_at": "2026-10-02T00:00:00Z",
                "actor": "default",
            },
        )
        assert seed_id  # non-empty message id

        # Step 2 — single deterministic sweep iteration. No
        # asyncio.sleep, no cancellation races.
        await sweeper._run_once()

        # Step 3a — recovery side effect: the typed link channel was
        # called with the workflow_id pulled from the orphan payload.
        assert len(sb.updates) == 1, (
            f"expected one tasks_link_workflow, got {len(sb.updates)}"
        )
        task_id, workflow_id = sb.updates[0]
        assert task_id == "t-x"
        assert workflow_id == "w-z"

        # Counters advanced.
        assert sweeper.entities_count == 1
        assert sweeper.cycles_total >= 1

        # Step 3b — the synthetic handoff_completed emit landed on the
        # same stream. It was *published*, never delivered, so it is in
        # no pending list — the stream itself is where to look for it.
        entries = await redis_client.xrange(stream)
        # coredis 6.x yields StreamEntry(identifier, field_values, ...).
        found_synthetic = False
        for entry in entries or ():
            field_values = getattr(entry, "field_values", None)
            if field_values is None:
                field_values = getattr(entry, "field_values", {}) or {}
            channel = field_values.get(b"channel") or field_values.get("channel")
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            if channel == "task.handoff_completed":
                found_synthetic = True
                break
        assert found_synthetic, (
            f"synthetic task.handoff_completed not found in {entries!r}"
        )

        # Step 3c — PEL must be empty. xpending in coredis 6.x
        # returns a StreamPending namedtuple with .pending set to
        # the integer count.
        pending = await redis_client.xpending(stream, group)
        pending_count = getattr(pending, "pending", None)
        if pending_count is None and isinstance(pending, dict):
            pending_count = pending.get("pending")
        assert pending_count == 0, (
            f"PEL should be empty after ack, got pending={pending_count}"
        )
    finally:
        # Best-effort cleanup so a failed test does not pollute the
        # next run. Swallow delete errors — they are not the
        # assertion under test.
        try:
            await redis_client.delete(stream)
        except Exception:  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
            pass
        await sweeper.cleanup()
