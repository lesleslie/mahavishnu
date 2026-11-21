"""Task orphan sweeper — recovers from task.handoff_orphan events.

The sweeper is the recovery half of the v1.1 Bodai task-system
handoff:

* :func:`mahavishnu.mcp.tools.tasks_handoff.mahavishnu_tasks_handoff_to_workflow`
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

Group maintenance
-----------------

Owning a consumer group means owning its maintenance too. Three things
accumulate without it, all measured on the live system on 2026-11-21:

* **Zombie pending entries.** Redis does not trim a group's pending
  list when the stream is trimmed, so every trimmed message leaves a
  pending entry pointing at an id that no longer exists — permanently
  un-ackable and invisible to a read. The stream had been trimmed
  from 18,203 entries to 14,399; the group still listed 18,198 pending.
* **Stale consumers.** The consumer name carries the process id, so
  every restart registers a new consumer and Redis never expires the
  old one: 437 of them, 357 holding nothing.
* **Lost handoffs.** ``XREADGROUP`` with ``>`` delivers only *new*
  messages, so anything handed to a consumer that died before
  acknowledging it was never re-read.

The sweeper therefore runs a hygiene pass on start and periodically
after that: ``XAUTOCLAIM`` reclaims the stale entries and purges the
zombies, and ``XGROUP DELCONSUMER`` removes consumers that are gone.
Reclaim runs first, so a message that could still be recovered is
recovered before any consumer is deleted.

Heartbeat: :meth:`health` returns False after 3 consecutive ``read()``
failures, or after 3 consecutive failed hygiene passes; it resets to
True on the first success of either.
Backoff: 1, 2, 4, 8, 16, 32 s, then capped at 60 s — applied inside
:meth:`_run_once` so :meth:`run_forever` does not need its own sleep.

§3 counters: ``entities_count``, ``cycles_total``, ``errors_total``,
``last_updated_timestamp`` — same surface as BodaiEventsPublisher so
the master health aggregator can union them — plus the group counters
``reclaimed_total``, ``purged_total``, ``pruned_consumers_total``,
``pending_last`` and ``consumers_last``.
OTel span: ``task_orphan_sweeper.recover`` with task_id, workflow_id,
outcome ∈ {success, skipped, failed}.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from mahavishnu.core.events.redis_stream_group import (
    DEFAULT_PRUNE_STALE_AFTER_MS,
    DEFAULT_RECLAIM_MIN_IDLE_MS,
    DEFAULT_REDIS_URL,
    RedisStreamGroup,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# The exact channel string emitted by session-buddy's
# ``publish_task_event_raw`` for handoff orphans. Keep this in lockstep
# with ``session_buddy.mcp.tools.tasks_events._ENVELOPE_BY_EVENT_TYPE``.
_HANDSHAKE_ORPHAN_CHANNEL = "task.handoff_orphan"
_HANDSHAKE_COMPLETED_CHANNEL = "task.handoff_completed"

#: Prefix shared by every consumer this sweeper registers. Used to
#: recognise its own past consumers — and only its own — when pruning.
_CONSUMER_PREFIX = "mahavishnu-"


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

    Entry shape (per ``RedisStreamGroup.read``): each entry is
    ``{"message_id": message_id, "payload": <XADD-fields-dict>}``. The
    channel filter reads ``entry["payload"]["channel"]`` — never from
    the entry root.

    Recovery loop per orphan entry:
      1. ``_is_already_handed_off(task)`` check (uses session_buddy.tasks_get).
      2. If not handed off: ``session_buddy.tasks_update(task_id, metadata={...})``.
      3. Emit synthetic ``task.handoff_completed`` event on the same stream.
      4. ``ack([entry["message_id"]])`` AFTER the recovery attempt (success
         or fail) so the stream cannot replay the entry twice.

    Heartbeat: :meth:`health` returns False after 3 consecutive ``read()``
    failures, or after 3 consecutive failed hygiene passes; resets to
    True on the first success of either.
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
        redis_url: str = DEFAULT_REDIS_URL,
        stream_group: Any | None = None,
        hygiene_interval_cycles: int = 60,
        reclaim_min_idle_ms: int = DEFAULT_RECLAIM_MIN_IDLE_MS,
        prune_stale_after_ms: int = DEFAULT_PRUNE_STALE_AFTER_MS,
    ) -> None:
        self._stream_name = stream
        self._group_name = consumer_group
        self._consumer_name = consumer_name or f"{_CONSUMER_PREFIX}{os.getpid()}"
        self._stream_group = stream_group or RedisStreamGroup(
            stream=stream,
            group=consumer_group,
            consumer=self._consumer_name,
            redis_url=redis_url,
        )
        self.enabled = enabled
        self.block_ms = block_ms
        self.count = count
        self._session_buddy = session_buddy_client
        self._hygiene_interval_cycles = max(1, hygiene_interval_cycles)
        self._reclaim_min_idle_ms = reclaim_min_idle_ms
        self._prune_stale_after_ms = prune_stale_after_ms
        # §3 counters (mirrors BodaiEventsPublisher).
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0
        # Group-maintenance counters.
        self.reclaimed_total = 0
        self.purged_total = 0
        self.pruned_consumers_total = 0
        self.destroyed_messages_total = 0
        self.pending_last = 0
        self.consumers_last = 0
        # False when the last hygiene pass could not measure the group.
        # A probe that failed did not measure zero, and the health body
        # must not say it did.
        self._group_state_ok = True
        # Read-failure streak (separate signal from init success).
        self._consecutive_read_failures: int = 0
        # Hygiene-failure streak (separate signal from read failures).
        self._consecutive_hygiene_failures: int = 0

    # -- properties ------------------------------------------------------

    @property
    def stream(self) -> str:
        """Name of the stream this sweeper consumes."""
        return self._stream_name

    @property
    def group(self) -> str:
        """Name of the consumer group this sweeper maintains."""
        return self._group_name

    @property
    def consumer(self) -> str:
        """Name this sweeper reads under."""
        return self._consumer_name

    # -- lifecycle -------------------------------------------------------

    async def init(self) -> None:
        """Initialise the stream handle and run the first hygiene pass.

        Failures are swallowed + logged so a Redis outage at MCP-server
        startup does not crash the server. The degraded state is picked up
        by :meth:`health` and surfaces on the master ``/health`` endpoint.
        """
        if not self.enabled:
            return
        try:
            await self._stream_group.init()
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(
                "task_orphan_sweeper: init failed (degraded to no-op): %s",
                exc,
            )
            return
        await self._run_hygiene()

    async def cleanup(self) -> None:
        try:
            await self._stream_group.cleanup()
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning("task_orphan_sweeper: cleanup failed: %s", exc)

    async def health(self) -> bool:
        """True while the sweeper is both reading and maintaining its group.

        A single transport hiccup is tolerable; a sustained failure
        streak flips the sweeper to degraded so monitoring surfaces it
        without requiring the operator to inspect logs. Read failures
        and hygiene failures are counted separately — a group that
        cannot be maintained is broken even when reads succeed.
        """
        return (
            self._consecutive_read_failures < 3
            and self._consecutive_hygiene_failures < 3
        )

    def _backoff_seconds(self) -> int:
        """Exponential backoff: 1, 2, 4, 8, 16, 32 s, capped at 60 s.

        Applied inside :meth:`_run_once` so the caller does not have to
        manage its own sleep loop. ``_consecutive_read_failures=0`` still
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
        return bool(
            task.get("workflow_id") or task.get("status") in {"done", "cancelled"}
        )

    def feed_state(self) -> dict[str, Any]:
        """Return this sweeper's counters for the ``/health`` payload.

        Mirrors ``plan_index``'s ``as_dict()``: the feed owns the shape
        of its own numbers, so the health endpoint never has to know
        which attribute holds which counter — and a counter that is
        added here cannot be silently left at zero on the far side.
        # req: REQ-SWEEPERHYGIENE-006
        """
        return {
            "entities_count": self.entities_count,
            "cycles_total": self.cycles_total,
            "errors_total": self.errors_total,
            "last_updated_timestamp": self.last_updated_timestamp,
            # ``None`` means "could not be determined". Publishing 0
            # there would make a group that could not be inspected read
            # as pristine.
            "pending_total": self.pending_last if self._group_state_ok else None,
            "consumers_total": self.consumers_last if self._group_state_ok else None,
            "group_state_ok": self._group_state_ok,
            "reclaimed_total": self.reclaimed_total,
            "purged_total": self.purged_total,
            "pruned_consumers_total": self.pruned_consumers_total,
            "destroyed_messages_total": self.destroyed_messages_total,
            "hygiene_failures": self._consecutive_hygiene_failures,
        }

    async def _recover_orphan(self, entry: dict[str, Any]) -> str:
        """Process one orphan entry: idempotency check → link →
        synthetic emit → return outcome string for the OTel span.

        The link goes through session-buddy's ``tasks_link_workflow`` —
        the typed channel that is the only writer of ``Task.workflow_id``.
        The generic ``tasks_update`` metadata bag cannot reach the field,
        so the previous ``tasks_update(metadata={"workflow_id": ...})``
        shape never actually bound anything; the sweeper re-linked
        forever and the task's ``workflow_id`` stayed ``None``.

        Acking the source entry is the caller's responsibility (so a
        transport failure between recovery and ack can be retried as a
        whole).

        Implements: REQ-009, REQ-006
        """
        # Entry shape: {"message_id": ..., "payload": <XADD-fields-dict>}.
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
        if not orphan.workflow_id:
            # A step-2 orphan has no workflow to re-link -- the dispatch
            # never produced one. Re-linking would bind the task to
            # nothing.
            logger.warning(
                "task_orphan_sweeper: orphan %s carries no workflow_id; nothing to re-link",
                orphan.task_id,
            )
            return "skipped"
        task = await self._session_buddy.tasks_get(orphan.task_id)
        if await self._is_already_handed_off(task):
            return "skipped"
        await self._session_buddy.tasks_link_workflow(
            orphan.task_id,
            orphan.workflow_id,
        )
        # Synthetic emit on the same stream so downstream consumers
        # observe a clean handoff_completed alongside the orphan.
        await self._stream_group.enqueue(
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

    async def _handle_entries(
        self, entries: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        """Process every entry: recover the orphans, ack the rest.

        Non-orphan entries are consumed and acked but do not appear in
        the return list. The OTel span ``task_orphan_sweeper.recover`` is
        emitted for every orphan entry — outcome reflects the recovery
        decision.
        # req: REQ-SWEEPERHYGIENE-005
        """
        results: list[tuple[dict[str, Any], str]] = []
        for entry in entries:
            payload = entry.get("payload", {})
            if payload.get("channel") != _HANDSHAKE_ORPHAN_CHANNEL:
                # Non-orphan entry on the same stream — ack and move on.
                await self._stream_group.ack([entry["message_id"]])
                continue
            try:
                with _tracer.start_as_current_span(
                    "task_orphan_sweeper.recover"
                ) as span:
                    span.set_attribute(
                        "task_id", str(payload.get("task_id", "unknown"))
                    )
                    span.set_attribute(
                        "workflow_id", str(payload.get("workflow_id", "unknown"))
                    )
                    outcome = await self._recover_orphan(entry)
                    span.set_attribute("outcome", outcome)
                    results.append((entry, outcome))
            except ValidationError as exc:
                # A payload that can never be recovered is PERMANENT.
                # Ack it so the entry does not loop forever, and say so
                # loudly: this is data the sweeper could not act on.
                self.errors_total += 1
                self._emit_failed_span(payload)
                logger.error(
                    "task_orphan_sweeper: orphan payload is malformed for %s: %s",
                    payload.get("task_id"),
                    exc,
                )
                await self._stream_group.ack([entry["message_id"]])
                continue
            except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                # A TRANSIENT failure — session-buddy unreachable, a
                # timeout, a dropped connection. The handoff is not
                # lost: leave the entry pending and it is reclaimed and
                # retried once it has been idle long enough. Acking it
                # would drop the recovery permanently, which is the one
                # thing this sweeper exists to prevent.
                self.errors_total += 1
                self._emit_failed_span(payload)
                logger.warning(
                    "task_orphan_sweeper: recover failed for %s (leaving it "
                    "pending for retry): %s",
                    payload.get("task_id"),
                    exc,
                )
                continue
            # Ack AFTER a successful recovery so the entry cannot be
            # replayed twice.
            await self._stream_group.ack([entry["message_id"]])
            # Yield between entries: a large reclaimed batch must not
            # monopolise the event loop.
            await asyncio.sleep(0)
        return results

    @staticmethod
    def _emit_failed_span(payload: dict[str, Any]) -> None:
        """Emit a failed-outcome span so the failure is observable.

        The failure is observable in the same trace tree as a
        successful sibling would be.
        """
        with _tracer.start_as_current_span("task_orphan_sweeper.recover") as span:
            span.set_attribute("task_id", str(payload.get("task_id", "unknown")))
            span.set_attribute(
                "workflow_id", str(payload.get("workflow_id", "unknown"))
            )
            span.set_attribute("outcome", "failed")

    async def _run_hygiene(self) -> list[tuple[dict[str, Any], str]]:
        """Maintain the consumer group: reclaim, purge, prune.

        Reclaim runs first, so a message that could still be recovered
        is recovered before any consumer is deleted. A failure is
        counted, not raised — the read path is independent of it.
        # req: REQ-SWEEPERHYGIENE-002, REQ-SWEEPERHYGIENE-003, REQ-SWEEPERHYGIENE-004
        """
        try:
            result = await self._stream_group.reclaim(
                min_idle_ms=self._reclaim_min_idle_ms,
            )
            prune = await self._stream_group.prune_consumers(
                keep=self._consumer_name,
                prefix=_CONSUMER_PREFIX,
                stale_after_ms=self._prune_stale_after_ms,
            )
            state = await self._stream_group.group_state()
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            self._consecutive_hygiene_failures += 1
            self._group_state_ok = False
            logger.warning(
                "task_orphan_sweeper: hygiene pass failed (consecutive=%d): %s",
                self._consecutive_hygiene_failures,
                exc,
            )
            return []
        self._consecutive_hygiene_failures = 0
        self._group_state_ok = True
        self.reclaimed_total += result.claimed_count
        self.purged_total += result.purged_count
        self.pruned_consumers_total += len(prune.removed)
        self.destroyed_messages_total += prune.destroyed_messages
        self.pending_last = state.pending
        self.consumers_last = state.consumers
        if result.purged_count or prune.removed or prune.destroyed_messages:
            logger.info(
                "task_orphan_sweeper: hygiene purged=%d reclaimed=%d pruned=%d "
                "destroyed=%d pending=%d consumers=%d",
                result.purged_count,
                result.claimed_count,
                len(prune.removed),
                prune.destroyed_messages,
                state.pending,
                state.consumers,
            )
        # A reclaimed entry is an orphan this sweeper already took
        # delivery of and never acknowledged. It goes through the same
        # recovery path as a fresh one.
        return await self._handle_entries(result.entries)

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
        results: list[tuple[dict[str, Any], str]] = []
        if self.cycles_total % self._hygiene_interval_cycles == 0:
            results.extend(await self._run_hygiene())
        try:
            entries = await self._stream_group.read(
                count=self.count,
                block_ms=self.block_ms,
            )
            # Reset the failure streak on any successful read — even one
            # that returns zero entries.
            self._consecutive_read_failures = 0
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            self.errors_total += 1
            self._consecutive_read_failures += 1
            logger.warning(
                "task_orphan_sweeper: read failed (consecutive=%d): %s",
                self._consecutive_read_failures,
                exc,
            )
            await asyncio.sleep(self._backoff_seconds())
            return results

        results.extend(await self._handle_entries(entries))
        return results

    async def run_forever(self) -> None:
        """Main loop. The natural per-iteration sleep happens inside
        :meth:`_run_once` (block_ms on the read, or backoff_seconds after
        a transport failure); no asyncio.sleep needed here.

        A sweeper constructed with ``enabled=False`` returns
        immediately. ``init()`` skips opening the Redis handle when the
        sweeper is disabled, so without this guard the loop kept
        calling ``_run_once``, every read raised "client not
        initialised", and the sweeper spun on errors forever. The
        ``enabled`` key was dead config until 2026-11-21, so the guard
        was never exercised.
        """
        if not self.enabled:
            logger.info("task_orphan_sweeper disabled by configuration")
            return
        while True:
            await self._run_once()
