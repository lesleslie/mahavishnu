"""Task orphan sweeper — recovers from task.handoff_orphan events.

The sweeper is the recovery half of the v1.1 Bodai task-system
handoff:

* :func:`mahavishnu.mcp.tools.tasks_handoff.tasks_handoff_to_workflow`
  emits a ``task.handoff_orphan`` event on the ``bodai:events`` Redis
  Stream whenever a dispatch succeeds but the back-link to
  session-buddy's task record fails (or the caller disconnects).
* This sweeper consumes that stream, looks up the task in
  session-buddy, and re-links the ``workflow_id`` so the task
  finishes in a consistent state.

Idempotency is provided by the ``_is_already_handed_off`` guard: if
session-buddy already has a ``workflow_id`` on the task, or its
status is ``done``/``cancelled``, the recovery is a no-op. At-most-
once ack semantics (ack after both success AND failure) prevent the
stream from replaying the same orphan forever.

The sweeper is wired into the MCP server's start/stop hooks by T10
and exercised end-to-end by T12.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import os
import time
from typing import Any

from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from opentelemetry import trace
from pydantic import BaseModel

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# The exact channel string emitted by session-buddy's
# ``publish_task_event_raw`` for handoff orphans. Keep this in lockstep
# with ``session_buddy.mcp.tools.tasks_events._ENVELOPE_BY_EVENT_TYPE``.
_HANDSHAKE_ORPHAN_CHANNEL = "task.handoff_orphan"
_HANDSHAKE_COMPLETED_CHANNEL = "task.handoff_completed"


class TaskHandoffOrphan(BaseModel):
    """Sweeper's view of an orphan event payload.

    Mirrors :class:`session_buddy.mcp.tools.tasks_models.TaskHandoffOrphanPayload`
    in shape (the sweeper does not import the upstream model to keep
    the import surface narrow and to avoid a hard dep on session-buddy
    being importable at module load time).
    """

    task_id: str
    workflow_id: str = ""
    reason: str = ""
    orphaned_at: str = ""
    actor: str = "default"


class TaskOrphanSweeper:
    """Subscribes to ``bodai:events`` Redis Stream (consumer group
    ``bodai-task-orphan-sweeper``), filters on payload channel=task.handoff_orphan,
    and re-links tasks via session-buddy's ``tasks_update``.

    Adapter entry shape (per oneiric RedisStreamsQueueAdapter._format_entries):
    each entry returned by read() is ``[{"message_id": message_id, "payload":
    <XADD-fields-dict>}]``. The channel filter reads ``entry["payload"]["channel"]`` —
    never from the entry root.

    Recovery loop per orphan entry:
      1. ``_is_already_handed_off(task)`` check (uses session_buddy.tasks_get).
      2. If not handed off: ``session_buddy.tasks_update(task_id, metadata={...})``.
      3. Emit synthetic ``task.handoff_completed`` event on the same stream.
      4. ``ack([entry["message_id"]])`` AFTER the recovery attempt (success
         or fail) so the stream cannot replay the entry twice.

    Heartbeat: :meth:`health` returns False after 3 consecutive ``read()``
    failures; resets to True on the first successful read.
    Backoff: 1, 2, 4, 8, 16, 32 s, then capped at 60 s — applied inside
    :meth:`_run_once` so :meth:`run_forever` does not need its own sleep.

    §3 counters: ``entities_count``, ``cycles_total``, ``errors_total``,
    ``last_updated_timestamp`` — same surface as BodaiEventsPublisher so
    the master health aggregator can union them.
    OTel span: ``task_orphan_sweeper.recover`` with task_id, workflow_id,
    outcome ∈ {success, skipped, failed}.
    """

    def __init__(
        self,
        *,
        stream: str = "bodai:events",
        consumer_group: str = "bodai-task-orphan-sweeper",
        consumer_name: str | None = None,
        enabled: bool = True,
        block_ms: int = 5000,
        count: int = 10,
        session_buddy_client: Any = None,
    ) -> None:
        self._settings = RedisStreamsQueueSettings(
            stream=stream,
            group=consumer_group,
            consumer=consumer_name or f"mahavishnu-{os.getpid()}",
        )
        self._adapter = RedisStreamsQueueAdapter(settings=self._settings)
        self.enabled = enabled
        self.block_ms = block_ms
        self.count = count
        self._session_buddy = session_buddy_client
        # §3 counters (mirrors BodaiEventsPublisher).
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0
        # Read-failure streak (separate signal from init success).
        self._consecutive_read_failures: int = 0

    async def init(self) -> None:
        """Initialise the Redis adapter.

        Failures are swallowed + logged so a Redis outage at MCP-server
        startup does not crash the server. The degraded state is picked up
        by :meth:`health` and surfaces on the master ``/health`` endpoint.
        """
        if not self.enabled:
            return
        try:
            await self._adapter.init()
        except Exception as exc:  # noqa: BLE001 - sweeper degrades to no-op on transport init failure
            logger.warning(
                "task_orphan_sweeper: init failed (degraded to no-op): %s",
                exc,
            )

    async def cleanup(self) -> None:
        try:
            await self._adapter.cleanup()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup, server is shutting down
            logger.warning("task_orphan_sweeper: cleanup failed: %s", exc)

    async def health(self) -> bool:
        """True when fewer than 3 consecutive ``read()`` calls have failed.

        A single transport hiccup is tolerable; a sustained failure
        streak flips the sweeper to degraded so monitoring surfaces it
        without requiring the operator to inspect logs.
        """
        return self._consecutive_read_failures < 3

    def _backoff_seconds(self) -> int:
        """Exponential backoff: 1, 2, 4, 8, 16, 32 s, capped at 60 s.

        Applied inside :meth:`_run_once` so the caller does not have to
        manage a separate sleep loop. ``_consecutive_read_failures=0`` still
        returns 1 s — the block_ms on the underlying ``xreadgroup`` already
        covers the no-entries case, so the backoff only fires on a real
        read error.
        """
        return min(60, 2 ** max(0, self._consecutive_read_failures - 1))

    async def _is_already_handed_off(self, task: dict[str, Any]) -> bool:
        """True when session-buddy already records the task as handed off.

        Two signals trigger the skip:
          * ``workflow_id`` present on the task metadata — the original
            dispatch step 3 succeeded, so the orphan is stale.
          * ``status`` ∈ {``done``, ``cancelled``} — the task is terminal,
            re-linking the workflow_id is no longer meaningful.
        """
        return bool(task.get("workflow_id") or task.get("status") in {"done", "cancelled"})

    async def _recover_orphan(self, entry: dict[str, Any]) -> str:
        """Process one orphan entry: idempotency check → tasks_update →
        synthetic emit → return outcome string for the OTel span.

        Acking the source entry is the caller's responsibility (so a
        transport failure between recovery and ack can be retried as a
        whole).
        """
        # Adapter entry shape: {"message_id": ..., "payload": <XADD-fields-dict>}.
        payload = entry.get("payload", {})
        # Defensive field filter — the orphan envelope may grow new fields
        # upstream without breaking this sweeper.
        orphan = TaskHandoffOrphan(
            **{k: v for k, v in payload.items() if k in TaskHandoffOrphan.model_fields}
        )
        if self._session_buddy is None:
            logger.warning(
                "task_orphan_sweeper: no session_buddy client bound; skipping recovery for %s",
                orphan.task_id,
            )
            return "skipped"
        task = await self._session_buddy.tasks_get(orphan.task_id)
        if await self._is_already_handed_off(task):
            return "skipped"
        await self._session_buddy.tasks_update(
            orphan.task_id,
            metadata={
                "workflow_id": orphan.workflow_id,
                "re_linked_at": datetime.now(UTC).isoformat(),
                "re_link_reason": orphan.reason,
            },
        )
        # Synthetic emit on the same stream so downstream consumers
        # observe a clean handoff_completed alongside the orphan.
        await self._adapter.enqueue(
            {
                "channel": _HANDSHAKE_COMPLETED_CHANNEL,
                "task_id": orphan.task_id,
                "workflow_id": orphan.workflow_id,
                "actor": "task_orphan_sweeper",
            }
        )
        self.entities_count += 1
        self.last_updated_timestamp = time.time()
        return "success"

    async def _run_once(self) -> list[tuple[dict[str, Any], str]]:
        """Run exactly one read iteration.

        Returns one ``(entry, outcome)`` tuple per orphan that was
        processed (skipped or recovered). Non-orphan entries are
        consumed and acked but do not appear in the return list.
        The OTel span ``task_orphan_sweeper.recover`` is emitted for
        every orphan entry — outcome reflects the recovery decision.

        Public testability helper: tests call this directly without
        needing to manage ``asyncio`` cancellation timing.
        """
        self.cycles_total += 1
        try:
            entries = await self._adapter.read(
                count=self.count,
                block_ms=self.block_ms,
            )
            # Reset the failure streak on any successful read — even one
            # that returns zero entries.
            self._consecutive_read_failures = 0
        except Exception as exc:  # noqa: BLE001 - any transport error must increment the failure streak
            self.errors_total += 1
            self._consecutive_read_failures += 1
            logger.warning(
                "task_orphan_sweeper: read failed (consecutive=%d): %s",
                self._consecutive_read_failures,
                exc,
            )
            await asyncio.sleep(self._backoff_seconds())
            return []

        results: list[tuple[dict[str, Any], str]] = []
        for entry in entries:
            payload = entry.get("payload", {})
            if payload.get("channel") != _HANDSHAKE_ORPHAN_CHANNEL:
                # Non-orphan entry on the same stream — ack and move on.
                await self._adapter.ack([entry["message_id"]])
                continue
            try:
                with _tracer.start_as_current_span("task_orphan_sweeper.recover") as span:
                    span.set_attribute("task_id", str(payload.get("task_id", "unknown")))
                    span.set_attribute("workflow_id", str(payload.get("workflow_id", "unknown")))
                    outcome = await self._recover_orphan(entry)
                    span.set_attribute("outcome", outcome)
                    results.append((entry, outcome))
            except Exception as exc:  # noqa: BLE001 - any per-entry failure must surface as a failed span
                self.errors_total += 1
                # Emit a failed-outcome span so the failure is observable
                # in the same trace tree as a successful sibling would be.
                with _tracer.start_as_current_span("task_orphan_sweeper.recover") as span:
                    span.set_attribute("task_id", str(payload.get("task_id", "unknown")))
                    span.set_attribute("workflow_id", str(payload.get("workflow_id", "unknown")))
                    span.set_attribute("outcome", "failed")
                logger.warning(
                    "task_orphan_sweeper: recover failed for %s: %s",
                    payload.get("task_id"),
                    exc,
                )
            # Ack AFTER the recovery attempt (success or fail) so the
            # entry cannot be replayed twice — at-most-once semantics.
            await self._adapter.ack([entry["message_id"]])
        return results

    async def run_forever(self) -> None:
        """Main loop. The natural per-iteration sleep happens inside
        :meth:`_run_once` (block_ms on the read, or backoff_seconds after
        a transport failure); no asyncio.sleep needed here.
        """
        while True:
            await self._run_once()
