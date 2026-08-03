"""Mahavishnu WAL: drainer.

Pulls pending rows from the WAL and pushes them to the sink (a Session-Buddy
MCP call). Respects the existing circuit breaker: when open, no calls are
attempted. Rows that fail after `max_attempts` are marked `failed` for
operator inspection.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .writer import MemoryOutboxWriter


class CircuitBreakerLike(Protocol):
    """Subset of the aggregator's _CircuitBreaker the drainer depends on."""

    def is_open(self) -> bool: ...


@dataclass
class DrainResult:
    """Outcome of a single drain pass.

    Attributes:
        drained: rows that the sink successfully wrote and were marked drained.
        deferred: rows still pending after the pass (breaker open, or remaining
            batch rows the drainer stopped at after a sink exception).
        failed: rows whose attempts exceeded `max_attempts` and are now `failed`.
    """

    drained: int
    deferred: int
    failed: int


# A sink is an async callable that takes a (key, payload) pair and writes
# it to the downstream service (e.g. Session-Buddy MCP). Raising any
# exception signals failure for that row; the drainer decides whether to
# retry or mark it `failed` based on attempts vs. max_attempts.
Sink = Callable[[str, dict[str, object]], Awaitable[None]]


class MemoryOutboxDrainer:
    """Drains pending WAL rows through a sink, respecting a circuit breaker.

    The drainer is intentionally simple: one batch per call, in enqueue
    order, with stop-on-first-error semantics to preserve ordering across
    retries. Rows that fail repeatedly are marked `failed` once
    `attempts >= max_attempts` so an operator can inspect them.
    """

    def __init__(
        self,
        writer: MemoryOutboxWriter,
        breaker: CircuitBreakerLike,
        sink: Sink,
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> None:
        self._writer = writer
        self._breaker = breaker
        self._sink = sink
        self._batch_size = batch_size
        self._max_attempts = max_attempts

    async def drain_once(self) -> DrainResult:
        if self._breaker.is_open():
            # Breaker open: don't touch the WAL; report everything as deferred.
            pending = await self._writer.pending_count()
            return DrainResult(drained=0, deferred=pending, failed=0)

        batch = await self._writer.pending_batch(self._batch_size)
        if not batch:
            return DrainResult(drained=0, deferred=0, failed=0)

        drained_ids: list[int] = []
        failed_ids: list[int] = []
        for row in batch:
            try:
                await self._sink(row.key, row.payload)
            except Exception as exc:  # noqa: BLE001 -- defensive: any sink failure should retry
                # Stop the batch on first sink exception to preserve ordering.
                # If this attempt would push us past max_attempts, mark the
                # row failed (terminal); otherwise bump attempts and leave it
                # pending for the next drain.
                err = str(exc)[:500]
                if row.attempts + 1 >= self._max_attempts:
                    await self._writer.mark_failed([row.id], error=err)
                    failed_ids.append(row.id)
                else:
                    await self._writer._bump_attempts([row.id], error=err)
                break
            drained_ids.append(row.id)

        if drained_ids:
            await self._writer.mark_drained(drained_ids)

        deferred = await self._writer.pending_count()
        return DrainResult(
            drained=len(drained_ids),
            deferred=deferred,
            failed=len(failed_ids),
        )
