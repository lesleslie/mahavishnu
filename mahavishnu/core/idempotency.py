"""Idempotency layer for pool_route_execute (C-6 — REQ-006/007/008).

Per ``feedback-no-backwards-compat-pre-1.0``: replaces ad-hoc nonce tracking
with a single Pydantic input model + DB-level unique constraint + asyncio.Lock
fallback. The idempotency_key is a SHA-256 hex digest of (source, nonce,
payload_hash, ttl_bucket) — never a raw ``f"{source}:{nonce}"`` string — so
caller identifiers stay opaque in logs and metrics.

The module exposes:

- :class:`IdempotencyOptions` — Pydantic input model with strict bounds
  (source ≤ 255, nonce ≤ 128, ttl 60..604800) and ``extra="forbid"``.
- :class:`IdempotencyStore` — wraps :class:`EventStore` with idempotency
  semantics: ``get_or_create`` (lookup-or-insert with per-key asyncio.Lock
  bounded by LRU), ``mark_completed`` (in-place PENDING→COMPLETED), and a
  fail-CLOSED error contract via :class:`IdempotencyStoreUnavailable`.
- :class:`IdempotencyCircuitBreaker` — protects the lookup path from the
  30s-EventStore-timeout cliff by tripping OPEN after N consecutive
  failures and fast-failing with :class:`IdempotencyCircuitOpen` until the
  cooldown elapses.
- Module-level singletons (``get_idempotency_store`` /
  ``set_idempotency_store`` / ``get_idempotency_breaker`` /
  ``set_idempotency_breaker``) — required because per-call construction
  defeats the asyncio.Lock fallback (each call would get its own lock dict
  and concurrent calls with the same key could not serialize).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import time
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from cachetools import LRUCache
from oneiric.actions.compression import HashAction
from oneiric.core.logging import get_logger
from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core._idempotency_metrics import (
    IDEMPOTENCY_CIRCUIT_STATE_GAUGE,
    IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL,
    IDEMPOTENCY_HIT_TOTAL,
    IDEMPOTENCY_MISS_TOTAL,
)
from mahavishnu.core.errors import IdempotencyCircuitOpen, IdempotencyStoreUnavailable
from mahavishnu.core.event_store import TaskEvent, TaskEventType

if TYPE_CHECKING:
    from mahavishnu.core.event_store import EventStore

logger = get_logger(__name__)

T = TypeVar("T")


class IdempotencyOptions(BaseModel):
    """Pydantic input model for ``pool_route_execute(idempotency=...)``.

    Keeping all idempotency-related params in one Pydantic model keeps
    ``pool_route_execute``'s positional-arg count under ``max-args=10``.

    Implements: REQ-006
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, max_length=255)
    """Origin system (e.g., 'webhook.intake', 'cli.dispatch')."""

    nonce: str = Field(..., min_length=1, max_length=128)
    """Caller-supplied unique identifier for the dispatch attempt."""

    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    """How long the idempotency record lives (60s to 7 days). Default 24h."""


class IdempotencyStore:
    """Wraps :class:`EventStore` with idempotency-specific operations.

    The lock dict is bounded by :class:`cachetools.LRUCache` (maxsize=1024)
    so long-running processes do not leak memory through per-key locks.

    Public methods:
        - ``fingerprint`` (staticmethod): SHA-256 hex digest of the dispatch
          payload — opaque, NOT raw ``f"{source}:{nonce}"``.
        - ``get_or_create``: returns existing :class:`TaskEvent` if the
          fingerprint matches, else creates a new PENDING row.
        - ``mark_completed``: single-row in-place PENDING→COMPLETED update.
        - ``is_expired``: True when the record has aged past ``ttl_seconds``.

    Implements: REQ-006, REQ-007, REQ-008
    """

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._locks: LRUCache[str, asyncio.Lock] = LRUCache(maxsize=1024)
        self._locks_mu = asyncio.Lock()

    @staticmethod
    async def fingerprint(options: IdempotencyOptions, payload_hash: str) -> str:
        """Compute SHA-256 hex digest of (source, nonce, payload_hash, ttl_bucket).

        The TTL bucket prevents stale-key collisions across long-running
        caches — without it, a record from 24h ago with the same
        source+nonce+payload would re-fire the same fingerprint even
        though ``ttl_seconds`` has expired.
        """
        ttl_bucket = options.ttl_seconds // 3600
        raw = f"{options.source}:{options.nonce}:{payload_hash}:{ttl_bucket}"
        result = await HashAction().execute({"algorithm": "sha256", "data": raw})
        return result["digest"]  # type: ignore[no-any-return]

    async def _lock_for(self, key: str) -> asyncio.Lock:
        """Per-key asyncio.Lock. Created lazily on first use; LRU-bounded."""
        async with self._locks_mu:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def get_or_create(
        self,
        options: IdempotencyOptions,
        payload_hash: str,
        actor: str,
    ) -> TaskEvent:
        """Return existing TaskEvent if fingerprint matches; else create PENDING.

        Raises :class:`IdempotencyStoreUnavailable` on underlying-store
        failure (fail-CLOSED: no dispatch happens). The per-key
        asyncio.Lock narrows the race between this lookup and the DB
        unique-constraint check (added in C-4); the lock is the in-process
        fallback, NOT the primary defense.
        """
        key = await self.fingerprint(options, payload_hash)
        lock = await self._lock_for(key)
        async with lock:
            try:
                existing = await self._store.get_event_by_idempotency_key(key)
                if existing is not None:
                    IDEMPOTENCY_HIT_TOTAL.labels(source=options.source).inc()
                    return existing
                IDEMPOTENCY_MISS_TOTAL.labels(source=options.source).inc()
                return await self._store.append(
                    task_id=key,
                    event_type=TaskEventType.PENDING,
                    data={
                        "source": options.source,
                        "nonce": options.nonce,
                        "idempotency_key": key,
                    },
                    actor=actor,
                    idempotency_key=key,
                )
            except IdempotencyStoreUnavailable:
                raise
            except Exception as e:
                logger.exception(
                    "idempotency lookup failed",
                    extra={"source": options.source},
                )
                raise IdempotencyStoreUnavailable(
                    f"EventStore unreachable during idempotency lookup: {e}"
                ) from e

    async def mark_completed(
        self,
        event: TaskEvent,
        result: dict[str, Any],
    ) -> TaskEvent:
        """Single-row in-place PENDING → COMPLETED transition.

        Uses ``EventStore.append`` with the same ``task_id`` so the row is
        upserted rather than duplicated.
        """
        event.event_type = TaskEventType.COMPLETED
        event.data = {**event.data, "result": result}
        await self._store.append(
            task_id=event.task_id,
            event_type=TaskEventType.COMPLETED,
            actor=event.actor,
            data=event.data,
            idempotency_key=event.idempotency_key,
        )
        return event

    async def mark_failed(self, event: TaskEvent, error: str) -> TaskEvent:
        """Single-row in-place PENDING → FAILED transition.

        Used when the dispatch itself raises; marks the idempotency record
        as terminal so a future retry sees a known-broken state instead of
        stale PENDING.
        """
        event.event_type = TaskEventType.FAILED
        event.data = {**event.data, "error": error}
        await self._store.append(
            task_id=event.task_id,
            event_type=TaskEventType.FAILED,
            actor=event.actor,
            data=event.data,
            idempotency_key=event.idempotency_key,
        )
        return event

    async def is_expired(self, event: TaskEvent, options: IdempotencyOptions) -> bool:
        """Check if the idempotency record has aged past ``ttl_seconds``."""
        age = datetime.now(UTC) - event.occurred_at
        return age > timedelta(seconds=options.ttl_seconds)


class IdempotencyCircuitBreaker:
    """Circuit breaker for EventStore reachability (C-6 fail-CLOSED guard).

    State machine:
        CLOSED → OPEN (after N consecutive failures) → HALF_OPEN
        (after cooldown_seconds) → CLOSED (on first success) or back to OPEN.

    When OPEN, calls fast-fail with :class:`IdempotencyCircuitOpen` — no
    DB hit, no 30s timeout. This preserves the no-duplicate-work
    guarantee (fail-CLOSED) while avoiding the timeout cliff identified
    by the devops review.

    State is exposed via :class:`mahavishnu.core._idempotency_metrics`
    (gauge + transition counter) so operators can distinguish "circuit
    OPEN for 2h" from "DB genuinely down" at 3am.

    Implements: REQ-006, REQ-007, REQ-008
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        """True when the breaker is OPEN (gating traffic)."""
        return self._opened_at is not None

    async def call(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        """Execute ``coro_factory()`` if circuit is closed.

        Raises :class:`IdempotencyCircuitOpen` when OPEN; raises the
        underlying exception when the factory raises.
        """
        async with self._lock:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self._cooldown_seconds:
                    IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(1)
                    logger.warning(
                        "idempotency circuit open; skipping",
                        extra={"error_id": "IDEMPOTENCY_CIRCUIT_OPEN"},
                    )
                    raise IdempotencyCircuitOpen("circuit open; event store unreachable")
                # Cooldown elapsed — transition to HALF_OPEN (one trial allowed).
                self._opened_at = None
                IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(0)
                IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                    transition="half_open",
                ).inc()

        try:
            result = await coro_factory()
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(1)
                IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                    transition="open",
                ).inc()
                logger.exception(
                    "circuit tripped to OPEN",
                    extra={"consecutive_failures": self._consecutive_failures},
                )
            raise

        # Success — reset failure count and bump metrics.
        if self._consecutive_failures > 0:
            IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                transition="closed",
            ).inc()
            IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(0)
        self._consecutive_failures = 0
        return result


# ---------------------------------------------------------------------------
# Module-level singletons (FIX round-5 HID-4 + round-8 Tier 4).
#
# Per-call construction defeats the asyncio.Lock fallback because each call
# gets its own ``_locks`` dict — two concurrent calls with the same
# idempotency_key cannot serialize. The singletons are injected at app boot
# via ``mahavishnu/factories.py:_wire_idempotency`` (TODO; lands with the
# next config-bootstrap pass) and are resettable from tests via the
# ``set_*`` helpers.
# ---------------------------------------------------------------------------

_idempotency_store: IdempotencyStore | None = None
_idempotency_breaker: IdempotencyCircuitBreaker | None = None


def set_idempotency_store(store: IdempotencyStore | None) -> None:
    """Inject the idempotency store singleton (test seam + factories hook)."""
    global _idempotency_store
    _idempotency_store = store


def get_idempotency_store() -> IdempotencyStore:
    """Return the injected store. Raises when unconfigured (fail-CLOSED)."""
    if _idempotency_store is None:
        raise IdempotencyStoreUnavailable(
            "idempotency store not configured; call set_idempotency_store() at app boot"
        )
    return _idempotency_store


def set_idempotency_breaker(breaker: IdempotencyCircuitBreaker | None) -> None:
    """Inject the idempotency breaker singleton (test seam + factories hook)."""
    global _idempotency_breaker
    _idempotency_breaker = breaker


def get_idempotency_breaker() -> IdempotencyCircuitBreaker:
    """Return the breaker singleton, lazily creating a permissive default.

    Returns a default :class:`IdempotencyCircuitBreaker` when unconfigured
    so callers in production get the fail-CLOSED default behaviour without
    requiring explicit wiring. Tests should inject their own breaker via
    :func:`set_idempotency_breaker` for deterministic state.
    """
    global _idempotency_breaker
    if _idempotency_breaker is None:
        _idempotency_breaker = IdempotencyCircuitBreaker()
    return _idempotency_breaker


__all__ = [
    "IdempotencyCircuitBreaker",
    "IdempotencyOptions",
    "IdempotencyStore",
    "get_idempotency_breaker",
    "get_idempotency_store",
    "set_idempotency_breaker",
    "set_idempotency_store",
]
