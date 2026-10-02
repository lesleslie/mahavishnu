"""End-to-end Redis round-trip test for :class:`TaskOrphanSweeper`.

Task 12 of the v1.1 Bodai task-system plan. Proves the full recovery
flow against a real local Redis:

    1. Seed a ``task.handoff_orphan`` message into a unique test
       stream on a unique consumer group.
    2. Run :meth:`TaskOrphanSweeper._run_once` against the real
       Redis (one deterministic iteration; no ``asyncio.sleep``
       timing).
    3. Assert the three observable properties:
       (a) ``session_buddy.tasks_update`` was called with the
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

    Records every ``tasks_update`` invocation so the test can
    assert the sweeper called it with the workflow_id pulled from
    the orphan payload. ``tasks_get`` returns an in-progress task
    so the idempotency guard does NOT short-circuit — the recovery
    side-effects must fire.
    """

    def __init__(self) -> None:
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        return {"id": task_id, "status": "in_progress"}

    async def tasks_update(
        self, task_id: str, **kw: Any
    ) -> dict[str, Any]:
        self.updates.append((task_id, kw))
        return {"id": task_id, **kw}


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

        # Step 3a — recovery side effect: tasks_update was called.
        assert len(sb.updates) == 1, (
            f"expected one tasks_update, got {len(sb.updates)}"
        )
        task_id, update_kw = sb.updates[0]
        assert task_id == "t-x"
        assert update_kw["metadata"]["workflow_id"] == "w-z"

        # Counters advanced.
        assert sweeper.entities_count == 1
        assert sweeper.cycles_total >= 1

        # Step 3b — synthetic handoff_completed emit landed on the
        # same stream. Reading from "0" returns the consumer's own
        # PEL — the sweeper's consumer IS this test's consumer, so
        # the entry should be visible there.
        entries = await redis_client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: "0"},
            count=10,
            block=100,
        )
        # coredis 6.x returns a dict keyed by stream name; values
        # are tuples of StreamEntry(identifier, field_values, ...).
        found_synthetic = False
        if isinstance(entries, dict):
            for _stream_key, stream_entries in entries.items():
                for entry in stream_entries or ():
                    field_values = getattr(entry, "field_values", {}) or {}
                    channel = field_values.get(b"channel") or field_values.get(
                        "channel"
                    )
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8")
                    if channel == "task.handoff_completed":
                        found_synthetic = True
                        break
                if found_synthetic:
                    break
        else:
            # Defensive: legacy coredis shape (list of (stream, msgs))
            for _stream_key, msgs in entries or []:
                for entry in msgs or []:
                    raw_id, raw_fields = entry[0], entry[1]
                    if (
                        isinstance(raw_fields, dict)
                        and raw_fields.get(b"channel") == b"task.handoff_completed"
                    ):
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
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            pass
        await sweeper.cleanup()
