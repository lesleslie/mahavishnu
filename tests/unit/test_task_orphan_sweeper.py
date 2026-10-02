"""Unit tests for ``mahavishnu.mcp.sweepers.task_orphan_sweeper``.

Pins the public contract of :class:`TaskOrphanSweeper`:

* settings shape (``_settings.group`` / ``_settings.stream``) is
  forwarded from the constructor kwargs;
* backoff doubles (1, 2, 4, 8, 16, 32) and caps at 60 s;
* the idempotency guard short-circuits when session-buddy already
  reports the task as handed-off (workflow_id set OR status
  done/cancelled);
* ``health()`` flips to False after 3 consecutive read failures and
  back to True when the run recovers;
* the recovery loop consumes ``task.handoff_orphan`` entries, calls
  ``session_buddy.tasks_update`` to re-link the workflow_id, emits a
  synthetic ``task.handoff_completed`` event, and acks the source
  entry — with at-most-once ack semantics across success/failure;
* OTel span ``task_orphan_sweeper.recover`` carries task_id,
  workflow_id, and ``outcome ∈ {success, skipped, failed}``;
* ``init()`` swallows transport failures (Redis unreachable) and
  surfaces them via ``health()`` instead of crashing the MCP server.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Stand-in for ``oneiric.adapters.queue.redis_streams.RedisStreamsQueueAdapter``.

    Mirrors the real shape returned by ``_format_entries``:
    ``read()`` returns ``[{"message_id": ..., "payload": <XADD-fields-dict>}]``.
    """

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self.entries = list(entries or [])
        self.acked: list[str] = []
        self.xadds: list[dict[str, Any]] = []
        self.init_calls = 0
        self.cleanup_calls = 0
        self.read_block_ms: int | None = None

    async def read(self, *, count: int, block_ms: int) -> list[dict[str, Any]]:
        self.read_block_ms = block_ms
        return self.entries

    async def ack(self, ids: list[str]) -> int:
        self.acked.extend(ids)
        return len(ids)

    async def enqueue(self, data: dict[str, Any]) -> str:
        self.xadds.append(data)
        return f"x-{len(self.xadds)}"

    async def init(self) -> None:
        self.init_calls += 1

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeSB:
    """Stand-in for the session-buddy client. Records every update."""

    def __init__(self, task_payloads: dict[str, dict[str, Any]] | None = None) -> None:
        self._payloads = dict(task_payloads or {})
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        return dict(self._payloads.get(task_id, {"status": "in_progress"}))

    async def tasks_update(
        self,
        task_id: str,
        **kw: Any,
    ) -> dict[str, Any]:
        self.updates.append((task_id, kw))
        return {"id": task_id, **kw}


def _orphan_entry(
    *,
    task_id: str = "t-x",
    workflow_id: str = "w-z",
    reason: str = "step_3_update_failed",
    message_id: str = "1-0",
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "payload": {
            "channel": "task.handoff_orphan",
            "task_id": task_id,
            "workflow_id": workflow_id,
            "reason": reason,
            "orphaned_at": "2026-10-02T00:00:00Z",
            "actor": "default",
        },
    }


# ---------------------------------------------------------------------------
# Step 1 — settings mapping
# ---------------------------------------------------------------------------


def test_consumer_group_maps_to_group_in_settings() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    assert sweeper._settings.group == "bodai-task-orphan-sweeper"
    assert sweeper._settings.stream == "bodai:events"


def test_consumer_group_and_stream_overrides_take_effect() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper(
        stream="custom:events",
        consumer_group="custom-sweeper",
    )
    assert sweeper._settings.stream == "custom:events"
    assert sweeper._settings.group == "custom-sweeper"


# ---------------------------------------------------------------------------
# Step 2 — backoff doubles capped at 60s
# ---------------------------------------------------------------------------


def test_backoff_doubles_capped_at_60s() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    expected = [1, 2, 4, 8, 16, 32, 60, 60]
    for i, exp in enumerate(expected, start=1):
        sweeper._consecutive_read_failures = i
        assert sweeper._backoff_seconds() == exp, f"at consecutive={i}"


def test_backoff_at_zero_failures_is_one_second() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    sweeper._consecutive_read_failures = 0
    assert sweeper._backoff_seconds() == 1


# ---------------------------------------------------------------------------
# Step 3 — idempotency guard
# ---------------------------------------------------------------------------


async def test_is_already_handed_off_returns_true_when_workflow_id_set() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    task = {"workflow_id": "w-1", "status": "in_progress"}
    assert await sweeper._is_already_handed_off(task) is True


async def test_is_already_handed_off_returns_true_when_done() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    assert await sweeper._is_already_handed_off({"status": "done"}) is True
    assert await sweeper._is_already_handed_off({"status": "cancelled"}) is True


async def test_is_already_handed_off_returns_false_when_pending() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    assert await sweeper._is_already_handed_off({"status": "in_progress"}) is False
    # Empty task (no workflow_id, no status) is also not-handed-off.
    assert await sweeper._is_already_handed_off({}) is False


# ---------------------------------------------------------------------------
# Step 4 — health flips after three failures
# ---------------------------------------------------------------------------


async def test_sweeper_health_false_after_three_failures() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()
    assert await sweeper.health() is True
    sweeper._consecutive_read_failures = 3
    assert await sweeper.health() is False
    sweeper._consecutive_read_failures = 0
    assert await sweeper.health() is True


# ---------------------------------------------------------------------------
# Step 5 — happy path: process orphan event
# ---------------------------------------------------------------------------


async def test_sweeper_processes_orphan_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    adapter = _FakeAdapter(entries=[_orphan_entry()])
    sb = _FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    results = await sweeper._run_once()

    # Recovery call side effects.
    assert len(sb.updates) == 1
    task_id, update_kw = sb.updates[0]
    assert task_id == "t-x"
    assert update_kw["metadata"]["workflow_id"] == "w-z"
    # Synthetic handoff_completed event was emitted.
    assert len(adapter.xadds) == 1
    assert adapter.xadds[0]["channel"] == "task.handoff_completed"
    # Source entry was acked.
    assert adapter.acked == ["1-0"]
    # Counters advanced.
    assert sweeper.entities_count == 1
    assert sweeper.cycles_total >= 1
    # The run_once return shape: one (entry, outcome="success") tuple.
    assert len(results) == 1
    assert results[0][0]["message_id"] == "1-0"
    assert results[0][1] == "success"


# ---------------------------------------------------------------------------
# Step 6 — skip when workflow_id is already set on the task
# ---------------------------------------------------------------------------


async def test_sweeper_skips_if_workflow_id_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    adapter = _FakeAdapter(entries=[_orphan_entry()])
    sb = _FakeSB(task_payloads={"t-x": {"status": "in_progress", "workflow_id": "w-existing"}})
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    results = await sweeper._run_once()

    # No recovery side effects on the wire, but the entry is still acked.
    assert sb.updates == []
    assert adapter.xadds == []
    assert adapter.acked == ["1-0"]
    assert sweeper.entities_count == 0
    # Outcome is recorded as "skipped" for the OTel span.
    assert results == [(adapter.entries[0], "skipped")]


# ---------------------------------------------------------------------------
# Step 7 — skip when status is done or cancelled
# ---------------------------------------------------------------------------


async def test_sweeper_skips_if_status_done(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    adapter = _FakeAdapter(entries=[_orphan_entry()])
    sb = _FakeSB(task_payloads={"t-x": {"status": "done"}})
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    results = await sweeper._run_once()

    assert sb.updates == []
    assert adapter.xadds == []
    assert adapter.acked == ["1-0"]
    assert results == [(adapter.entries[0], "skipped")]


async def test_sweeper_skips_if_status_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    adapter = _FakeAdapter(entries=[_orphan_entry(task_id="t-c")])
    sb = _FakeSB(task_payloads={"t-c": {"status": "cancelled"}})
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    results = await sweeper._run_once()

    assert sb.updates == []
    assert adapter.acked == ["1-0"]
    assert results == [(adapter.entries[0], "skipped")]


# ---------------------------------------------------------------------------
# Step 8 — OTel span on recovery
# ---------------------------------------------------------------------------


async def test_sweeper_emits_otel_span_on_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    # Stand up a fresh in-memory exporter; the global tracer is captured at
    # import time so we re-import the module under a primed provider.
    from mahavishnu.mcp.sweepers import task_orphan_sweeper as mod

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Monkeypatch the module-level _tracer to use the new provider.
    monkeypatch.setattr(mod, "_tracer", provider.get_tracer(__name__))

    adapter = _FakeAdapter(entries=[_orphan_entry()])
    sb = _FakeSB()
    sweeper = mod.TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    await sweeper._run_once()

    spans = exporter.get_finished_spans()
    recover = [s for s in spans if s.name == "task_orphan_sweeper.recover"]
    assert len(recover) == 1
    assert recover[0].attributes["task_id"] == "t-x"
    assert recover[0].attributes["workflow_id"] == "w-z"
    assert recover[0].attributes["outcome"] == "success"


# ---------------------------------------------------------------------------
# Step 9 — init failure is swallowed
# ---------------------------------------------------------------------------


async def test_sweeper_init_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper()

    async def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(sweeper._adapter, "init", boom)

    # init() does not raise even though the adapter init blew up — a Redis
    # outage at MCP-server startup must not crash the server. The degraded
    # state surfaces through the read-failure counter (health() flips
    # only after 3 consecutive read() failures, which is a different signal
    # from a one-shot init failure).
    await sweeper.init()


# ---------------------------------------------------------------------------
# Bonus — non-matching channel entries are filtered out and acked
# ---------------------------------------------------------------------------


async def test_sweeper_filters_out_non_orphan_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    other_entry = {
        "message_id": "2-0",
        "payload": {"channel": "task.handoff_completed", "task_id": "t-other"},
    }
    orphan = _orphan_entry(message_id="3-0")
    adapter = _FakeAdapter(entries=[other_entry, orphan])
    sb = _FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    await sweeper._run_once()

    # Only the orphan triggered recovery side effects.
    assert len(sb.updates) == 1
    assert sb.updates[0][0] == "t-x"
    # But both entries were acked.
    assert adapter.acked == ["2-0", "3-0"]


# ---------------------------------------------------------------------------
# Bonus — read failure increments error counters and recovers on next call
# ---------------------------------------------------------------------------


async def test_sweeper_read_failure_increments_failure_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    class _FailingAdapter(_FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.read_calls = 0

        async def read(self, *, count: int, block_ms: int) -> list[dict[str, Any]]:
            self.read_calls += 1
            raise ConnectionError("redis is down")

    adapter = _FailingAdapter()
    sweeper = TaskOrphanSweeper()
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    # First failure — health is still True (only 1 consecutive failure).
    await sweeper._run_once()
    assert sweeper._consecutive_read_failures == 1
    assert sweeper.errors_total == 1
    assert await sweeper.health() is True

    # Three more failures push the count to 4 — past the degraded threshold.
    for _ in range(3):
        await sweeper._run_once()
    assert sweeper._consecutive_read_failures == 4
    assert sweeper.errors_total == 4
    assert await sweeper.health() is False

    # Recovery — successful read resets the consecutive counter.
    monkeypatch.setattr(
        sweeper,
        "_adapter",
        _FakeAdapter(entries=[_orphan_entry()]),
    )
    sweeper._session_buddy = _FakeSB()
    await sweeper._run_once()
    assert sweeper._consecutive_read_failures == 0
    assert await sweeper.health() is True
