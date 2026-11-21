"""Unit tests for ``mahavishnu.mcp.sweepers.task_orphan_sweeper``.

Pins the public contract of :class:`TaskOrphanSweeper`:

* settings shape (``group`` / ``stream``) is
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


class _FakeStreamGroup:
    """Stand-in for ``mahavishnu.core.events.redis_stream_group.RedisStreamGroup``.

    Mirrors the real shape returned by ``read()``:
    ``[{"message_id": ..., "payload": <XADD-fields-dict>}]``.
    """

    def __init__(
        self,
        entries: list[dict[str, Any]] | None = None,
        reclaimed: list[dict[str, Any]] | None = None,
        purged: list[str] | None = None,
        pruned: list[str] | None = None,
    ) -> None:
        self.entries = list(entries or [])
        self.reclaimed_entries = list(reclaimed or [])
        self.purged_ids = list(purged or [])
        self.pruned = list(pruned or [])
        self.acked: list[str] = []
        self.xadds: list[dict[str, Any]] = []
        self.init_calls = 0
        self.cleanup_calls = 0
        self.read_block_ms: int | None = None
        self.reclaim_calls = 0
        self.prune_calls = 0
        self.reclaim_kwargs: dict[str, Any] = {}
        self.prune_kwargs: dict[str, Any] = {}

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

    async def reclaim(self, **kwargs: Any) -> Any:
        from mahavishnu.core.events.redis_stream_group import ReclaimResult

        self.reclaim_calls += 1
        self.reclaim_kwargs = kwargs
        return ReclaimResult(
            entries=self.reclaimed_entries,
            deleted_ids=self.purged_ids,
        )

    async def prune_consumers(self, **kwargs: Any) -> list[str]:
        self.prune_calls += 1
        self.prune_kwargs = kwargs
        return list(self.pruned)

    async def group_state(self) -> Any:
        from mahavishnu.core.events.redis_stream_group import GroupState

        return GroupState(pending=len(self.purged_ids), consumers=1 + len(self.pruned))


class _FakeSB:
    """Stand-in for the session-buddy client. Records every update."""

    def __init__(self, task_payloads: dict[str, dict[str, Any]] | None = None) -> None:
        self._payloads = dict(task_payloads or {})
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        return dict(self._payloads.get(task_id, {"status": "in_progress"}))

    async def tasks_link_workflow(
        self,
        task_id: str,
        workflow_id: str,
    ) -> dict[str, Any]:
        """The typed channel — the only writer of ``Task.workflow_id``.

        The sweeper used to call ``tasks_update(metadata={...})``, which
        wrote into the caller's metadata bag and never reached the
        server-set field. The sweeper therefore re-linked forever and
        the task's ``workflow_id`` stayed ``None``.
        """
        self.updates.append((task_id, {"workflow_id": workflow_id}))
        return {"id": task_id, "workflow_id": workflow_id}


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
    assert sweeper.group == "bodai-task-orphan-sweeper"
    assert sweeper.stream == "bodai:events"


def test_consumer_group_and_stream_overrides_take_effect() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    sweeper = TaskOrphanSweeper(
        stream="custom:events",
        consumer_group="custom-sweeper",
    )
    assert sweeper.stream == "custom:events"
    assert sweeper.group == "custom-sweeper"


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

    adapter = _FakeStreamGroup(entries=[_orphan_entry()])
    sb = _FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

    results = await sweeper._run_once()

    # Recovery call side effects.
    assert len(sb.updates) == 1
    task_id, update_kw = sb.updates[0]
    assert task_id == "t-x"
    # The link goes through the typed channel, with the workflow id as
    # a first-class argument — not through the generic metadata bag.
    assert update_kw["workflow_id"] == "w-z"
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

    adapter = _FakeStreamGroup(entries=[_orphan_entry()])
    sb = _FakeSB(
        task_payloads={"t-x": {"status": "in_progress", "workflow_id": "w-existing"}}
    )
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

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

    adapter = _FakeStreamGroup(entries=[_orphan_entry()])
    sb = _FakeSB(task_payloads={"t-x": {"status": "done"}})
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

    results = await sweeper._run_once()

    assert sb.updates == []
    assert adapter.xadds == []
    assert adapter.acked == ["1-0"]
    assert results == [(adapter.entries[0], "skipped")]


async def test_sweeper_skips_if_status_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    adapter = _FakeStreamGroup(entries=[_orphan_entry(task_id="t-c")])
    sb = _FakeSB(task_payloads={"t-c": {"status": "cancelled"}})
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

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

    adapter = _FakeStreamGroup(entries=[_orphan_entry()])
    sb = _FakeSB()
    sweeper = mod.TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

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

    monkeypatch.setattr(sweeper._stream_group, "init", boom)

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
    adapter = _FakeStreamGroup(entries=[other_entry, orphan])
    sb = _FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

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

    class _FailingAdapter(_FakeStreamGroup):
        def __init__(self) -> None:
            super().__init__()
            self.read_calls = 0

        async def read(self, *, count: int, block_ms: int) -> list[dict[str, Any]]:
            self.read_calls += 1
            raise ConnectionError("redis is down")

    adapter = _FailingAdapter()
    sweeper = TaskOrphanSweeper()
    monkeypatch.setattr(sweeper, "_stream_group", adapter)

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
        "_stream_group",
        _FakeStreamGroup(entries=[_orphan_entry()]),
    )
    sweeper._session_buddy = _FakeSB()
    await sweeper._run_once()
    assert sweeper._consecutive_read_failures == 0
    assert await sweeper.health() is True


# ---------------------------------------------------------------------------
# Step 10 — group hygiene: reclaim, purge, prune
# ---------------------------------------------------------------------------


class TestTheGroupHygiene:
    """The sweeper owns a consumer group, so it maintains it.

    Without this, the group accumulates a zombie pending entry for
    every message the stream trimmed away, and a stale consumer for
    every process start — both of which are invisible to a read.
    """

    async def test_init_runs_a_hygiene_pass(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup()
        sweeper = TaskOrphanSweeper(stream_group=fake)

        await sweeper.init()

        assert fake.reclaim_calls == 1
        assert fake.prune_calls == 1

    async def test_a_reclaimed_orphan_is_recovered_and_acked(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup(reclaimed=[_orphan_entry(message_id="9-0")])
        sb = _FakeSB()
        sweeper = TaskOrphanSweeper(session_buddy_client=sb, stream_group=fake)

        await sweeper.init()

        assert len(sb.updates) == 1
        assert sb.updates[0][0] == "t-x"
        assert "9-0" in fake.acked
        assert sweeper.reclaimed_total == 1

    async def test_purged_zombies_are_counted(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup(purged=["1-0", "2-0"])
        sweeper = TaskOrphanSweeper(stream_group=fake)

        await sweeper.init()

        assert sweeper.purged_total == 2

    async def test_pruned_consumers_are_counted(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup(pruned=["mahavishnu-111", "mahavishnu-222"])
        sweeper = TaskOrphanSweeper(stream_group=fake)

        await sweeper.init()

        assert sweeper.pruned_consumers_total == 2

    async def test_the_group_state_is_recorded(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup(purged=["1-0"], pruned=["mahavishnu-111"])
        sweeper = TaskOrphanSweeper(stream_group=fake)

        await sweeper.init()

        assert sweeper.pending_last == 1
        assert sweeper.consumers_last == 2

    async def test_the_prune_keeps_this_sweeper_own_consumer(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup()
        sweeper = TaskOrphanSweeper(stream_group=fake)

        await sweeper.init()

        assert fake.prune_kwargs["keep"] == sweeper.consumer
        assert fake.prune_kwargs["prefix"] == "mahavishnu-"

    async def test_a_failing_hygiene_pass_does_not_raise(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        class _FailingHygiene(_FakeStreamGroup):
            async def reclaim(self, **kwargs: Any) -> Any:
                raise ConnectionError("redis is down")

        sweeper = TaskOrphanSweeper(stream_group=_FailingHygiene())

        await sweeper.init()

        assert sweeper._consecutive_hygiene_failures == 1

    async def test_health_degrades_after_three_hygiene_failures(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        class _FailingHygiene(_FakeStreamGroup):
            async def reclaim(self, **kwargs: Any) -> Any:
                raise ConnectionError("redis is down")

        sweeper = TaskOrphanSweeper(stream_group=_FailingHygiene())

        assert await sweeper.health() is True
        for _ in range(3):
            await sweeper._run_hygiene()
        assert await sweeper.health() is False

    async def test_health_recovers_after_a_successful_hygiene_pass(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        class _FlakyHygiene(_FakeStreamGroup):
            def __init__(self) -> None:
                super().__init__()
                self.fail = True

            async def reclaim(self, **kwargs: Any) -> Any:
                if self.fail:
                    raise ConnectionError("redis is down")
                return await super().reclaim(**kwargs)

        fake = _FlakyHygiene()
        sweeper = TaskOrphanSweeper(stream_group=fake)

        for _ in range(3):
            await sweeper._run_hygiene()
        assert await sweeper.health() is False

        fake.fail = False
        await sweeper._run_hygiene()
        assert await sweeper.health() is True

    async def test_the_hygiene_pass_repeats_on_the_configured_interval(self) -> None:
        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        fake = _FakeStreamGroup()
        sweeper = TaskOrphanSweeper(stream_group=fake, hygiene_interval_cycles=2)

        await sweeper._run_once()
        assert fake.reclaim_calls == 0

        await sweeper._run_once()
        assert fake.reclaim_calls == 1

    async def test_the_consumer_name_carries_the_process_id(self) -> None:
        import os

        from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

        sweeper = TaskOrphanSweeper()

        assert sweeper.consumer == f"mahavishnu-{os.getpid()}"
        assert sweeper.group == "bodai-task-orphan-sweeper"
        assert sweeper.stream == "bodai:events"
