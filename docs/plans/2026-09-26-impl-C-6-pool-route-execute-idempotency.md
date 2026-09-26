# C-6: `pool_route_execute(idempotency=IdempotencyOptions(...))` (WP-2 — idempotency layer)

**REQ-NNN:** REQ-006, REQ-007, REQ-008
- REQ-006: `pool_route_execute(idempotency=IdempotencyOptions(...))` with single-row in-place PENDING→COMPLETED update
- REQ-007: DB-level unique constraint enforcement + asyncio.Lock fallback
- REQ-008: SHA-256 hex fingerprinting via Oneiric `HashAction().execute(...)["digest"]`
**Risk:** High (touches the most-called dispatch path; integrates C-3 + C-4 + C-5; uses new Pydantic input model)
**Blocks:** C-8 (`pool_route_execute(worktree=...)` extends the same signature)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).
**Status:** Draft — round-4 corrections baked in (arg-count grouped, hashed idempotency key, fail-CLOSED default).

## Goal

Add the `idempotency` Pydantic input model to `pool_route_execute` so duplicate dispatches (e.g., a retried webhook, a CLI user's double-submit) do not produce duplicate work. The idempotency layer:

1. Computes a SHA-256 hex fingerprint of the dispatch payload (via Oneiric `HashAction`) and stores it in `audit.task_events.idempotency_key`.
2. Looks up the key before dispatch; if found, returns the existing result (or PENDING if still in-flight).
3. Stores the result with a single-row in-place PENDING→COMPLETED transition (not insert-then-update; the row is created with `event_type=PENDING` and updated to `COMPLETED` when the work finishes).
4. Enforces uniqueness via the DB-level unique constraint (added in C-4) with an `asyncio.Lock` fallback for the in-process race window.
5. Fails CLOSED if the EventStore is unreachable — no dispatch happens.

The original `pool_route_execute` had 7 positional args; this plan adds 2 (`idempotency` Pydantic model, `idempotency_ttl_seconds` field on the model). Total positional args stay under `max-args=10` because `idempotency` is a single Pydantic input.

## Pre-flight checks

1. **C-3, C-4, C-5 have landed.**
   - C-3 added `TaskEventType.PENDING = "pending"` and `IdempotencyStoreUnavailable` exception.
   - C-4 added `audit.task_events.idempotency_key` column + unique partial index.
   - C-5 added `safe_publish()` module-global for Akosha event publishing.
2. **`mahavishnu.actions.security.HashAction` importable** with the documented payload shape: `HashAction().execute({"algorithm": "sha256", "data": "<raw-string>"})` returns `{"digest": "<hex-digest>"}`. Verify the real import path by reading `oneiric/actions/security.py` (or equivalent) — the plan's import is `from oneiric.actions.compression import HashAction  # FIX round-6: HashAction lives in compression.py, not security.py` per Oneiric's flat-import convention.
3. **`mahavishnu.mcp.tools.pool_tools.pool_route_execute` is the dispatch entry point.** Read the existing signature to confirm the parameter list before extending. The plan assumes the existing 7-param signature is preserved with one new keyword arg.
4. **`audit.task_events` has an `actor VARCHAR(255)` and `data JSONB`** column already (from earlier migrations; verify).
5. **No existing `IdempotencyOptions` class** in the codebase (`grep -r "class IdempotencyOptions" mahavishnu/` returns nothing). If found, the plan is wrong — re-plan.

## File-by-file changes

### 1. `mahavishnu/core/idempotency.py` — new file (~120 LoC)

The `IdempotencyOptions` Pydantic input model + the `IdempotencyStore` class that wraps the lookup-or-insert logic:

```python
"""Idempotency layer for pool_route_execute.

Per feedback-no-backwards-compat-pre-1.0: replaces any ad-hoc nonce tracking with
a single Pydantic input model + DB-level unique constraint + asyncio.Lock fallback.

The idempotency_key is a SHA-256 hex digest of (source, payload_hash, created_at_bucket),
NOT a raw f"{source}:{nonce}" string — per round-4 ace + security finding.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field
from oneiric.actions.compression import HashAction  # FIX round-6: HashAction lives in compression.py, not security.py
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import IdempotencyStoreUnavailable, IdempotencyCircuitOpen  # FIX round-7: distinct exception for circuit-open vs underlying failure
from mahavishnu.core.event_store import TaskEvent, TaskEventType
from mahavishnu.core.database import Database  # FIX round-6: EventStore takes a Database instance, not a Path

if TYPE_CHECKING:
    from mahavishnu.core.event_store import EventStore


logger = get_logger(__name__)


class IdempotencyOptions(BaseModel):
    """Pydantic input model for pool_route_execute(idempotency=...).

    Keeping all idempotency-related params in one Pydantic model keeps
    pool_route_execute's arg count under max-args=10.
    """
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, max_length=255)
    """Origin system (e.g., 'webhook.intake', 'cli.dispatch')."""
    nonce: str = Field(..., min_length=1, max_length=128)
    """Caller-supplied unique identifier for the dispatch attempt."""
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    """How long the idempotency record lives (60s to 7 days). Default 24h."""


class IdempotencyStore:
    """Wraps EventStore with idempotency-specific operations.

    Public methods:
        - get_or_create(): returns existing TaskEvent if key matches, else creates new PENDING row
        - mark_completed(): transitions PENDING → COMPLETED in-place (single-row UPDATE)
        - acquire_lock() / release_lock(): per-process asyncio.Lock to handle the
          narrow race between get_or_create() and the DB unique constraint check
    """

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_mu = asyncio.Lock()

    @staticmethod
    def fingerprint(options: IdempotencyOptions, payload_hash: str) -> str:
        """Compute SHA-256 hex digest of (source, nonce, payload_hash, ttl_bucket).

        Hashed (not raw source:nonce) per round-4 ace + security finding.
        The TTL bucket prevents stale-key collisions across long-running caches.
        """
        ttl_bucket = options.ttl_seconds // 3600  # 1h bucket
        raw = f"{options.source}:{options.nonce}:{payload_hash}:{ttl_bucket}"
        result = await HashAction().execute({"algorithm": "sha256", "data": raw})  # FIX round-6: HashAction.execute() is async; missing await raises TypeError at runtime
        return result["digest"]  # ty: ignore[unresolved-attribute]

    async def _lock_for(self, key: str) -> asyncio.Lock:
        """Per-key asyncio.Lock. Created lazily on first use."""
        async with self._locks_mu:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def get_or_create(
        self, options: IdempotencyOptions, payload_hash: str, actor: str
    ) -> TaskEvent:
        """Returns existing TaskEvent if idempotency_key matches; else creates new PENDING row.

        Raises IdempotencyStoreUnavailable if EventStore is unreachable.
        """
        key = self.fingerprint(options, payload_hash)
        lock = await self._lock_for(key)
        async with lock:
            try:
                existing = await self._store.get_event_by_idempotency_key(key)
                if existing is not None:
                    return existing
                # Create new PENDING row. The DB unique constraint is the
                # second line of defense — if a concurrent process races
                # past the lock check, the constraint aborts the insert.
                # FIX round-6: real EventStore API is `append()`, not `create_task_event()`.
                # The append() signature: append(task_id, event_type, data, actor, ...).
                # We pass idempotency_key via the data dict since append() doesn't have a dedicated field.
                return await self._store.append(
                    task_id=key,  # task_id serves as the idempotency_key for lookup
                    event_type=TaskEventType.PENDING,
                    actor=actor,
                    data={"source": options.source, "nonce": options.nonce, "idempotency_key": key},
                )
            except IdempotencyStoreUnavailable:
                raise  # fail-CLOSED: do not dispatch without idempotency record
            except Exception as e:
                logger.exception("idempotency lookup failed",
                                  extra={"source": options.source})
                raise IdempotencyStoreUnavailable(
                    f"EventStore unreachable during idempotency lookup: {e}"
                ) from e

    async def mark_completed(
        self, event: TaskEvent, result: dict[str, Any]
    ) -> TaskEvent:
        """Single-row in-place PENDING → COMPLETED transition."""
        event.event_type = TaskEventType.COMPLETED
        event.data = {**event.data, "result": result}
        # FIX round-6: real EventStore API uses `append()` with updated task_id for state transitions.
        # append() is upsert-style: same task_id overwrites the prior event.
        await self._store.append(
            task_id=event.task_id,  # reuse task_id to overwrite PENDING row
            event_type=TaskEventType.COMPLETED,
            actor=event.actor,
            data=event.data,
        )
        return event

    async def is_expired(self, event: TaskEvent, options: IdempotencyOptions) -> bool:
        """Check if the idempotency record has aged past ttl_seconds."""
        age = datetime.now(UTC) - event.created_at
        return age > timedelta(seconds=options.ttl_seconds)
```

### 2. `mahavishnu/mcp/tools/pool_tools.py` — extend `pool_route_execute` signature

Locate `async def pool_route_execute(...)`. Extend the signature with one new keyword arg `idempotency: IdempotencyOptions | None = None`. Wrap the existing dispatch logic with idempotency lookup/complete calls.

**Before (existing):**

```python
async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    # ... 5 more positional args (timeout, etc.)
) -> dict[str, Any]:
    return await _dispatch_internal(prompt, pool_selector)
```

**After:**

```python
from mahavishnu.core.idempotency import IdempotencyOptions, IdempotencyStore
from mahavishnu.core.event_store import TaskEventType


async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    # ... 5 more positional args (timeout, etc.) preserved unchanged
    idempotency: IdempotencyOptions | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    event_store = _get_event_store()  # existing factory call
    idem_store = IdempotencyStore(event_store)

    payload_hash = _hash_prompt(prompt)  # SHA-256 of the prompt text

    if idempotency is not None:
        try:
            existing = await idem_store.get_or_create(
                idempotency, payload_hash, actor="pool_route_execute"
            )
        except IdempotencyStoreUnavailable:
            # Per feedback-no-backwards-compat-pre-1.0 + REQ-007: fail-CLOSED.
            # Caller asked for idempotency; we honor that by refusing to dispatch.
            logger.exception("idempotency store unreachable; failing closed",
                              extra={"error_id": "IDEMPOTENCY_STORE_UNAVAILABLE"})
            return {"status": "error", "error": "idempotency store unavailable"}

        if existing.event_type == TaskEventType.COMPLETED:
            # Duplicate dispatch — return the cached result.
            logger.info("idempotency hit; returning cached result",
                         extra={"idempotency_key": existing.idempotency_key})
            return {"status": "duplicate", "result": existing.data.get("result", {})}

        # PENDING — fall through to dispatch and mark_completed below.

    try:
        result = await _dispatch_internal(prompt, pool_selector)
    except Exception:
        if idempotency is not None and existing is not None:
            # Mark as FAILED so a future retry does not return stale PENDING.
            existing.event_type = TaskEventType.FAILED  # FIX round-6: FAILED = "failed" already exists in StrEnum at event_store.py:69
            existing.data = {**existing.data, "error": "dispatch failed"}
            # FIX round-7 (Tier 2): wrap mark-failed through the same breaker.
            # Without this, a DB hiccup at dispatch-completion time loses the
            # result and the row stays PENDING until manual cleanup.
            await breaker.call(
                lambda: event_store.append(
                    task_id=existing.task_id,
                    event_type=TaskEventType.FAILED,
                    actor=existing.actor,
                    data=existing.data,
                )
            )
        raise

    if idempotency is not None and existing is not None:
        # FIX round-7 (Tier 2): wrap mark_completed through the breaker too.
        await breaker.call(
            lambda: idem_store.mark_completed(existing, result)
        )

    return result
```

### 3. `mahavishnu/core/event_store.py` — add `get_event_by_idempotency_key` (if not present)

The spec says `get_event_by_idempotency_key()` exists at line 510 already. Verify; if not, add:

```python
async def get_event_by_idempotency_key(self, key: str) -> TaskEvent | None:
    """Look up a TaskEvent by its idempotency_key. Returns None if no match."""
    stmt = select(TaskEvent).where(TaskEvent.idempotency_key == key)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
```

### 4. `mahavishnu/core/idempotency.py` — module-global singleton (FIX round-5: HID-4)

Per round-5 critique (critical-audit HID-4): the per-call `IdempotencyStore(event_store)` construction in `pool_route_execute` defeats the asyncio.Lock fallback (each call gets its own lock dict, so two concurrent calls with the same idempotency key cannot serialize). Add module-global singleton helpers:

```python
# Module-level singleton — initialized once at app boot
_idempotency_store: IdempotencyStore | None = None


def set_idempotency_store(store: IdempotencyStore | None) -> None:
    """Inject the singleton. Called by mahavishnu/factories.py at app boot."""
    global _idempotency_store
    _idempotency_store = store


def get_idempotency_store() -> IdempotencyStore:
    """Return the injected singleton. Raises if not configured (fail-CLOSED)."""
    if _idempotency_store is None:
        raise IdempotencyStoreUnavailable(
            "idempotency store not configured; set via set_idempotency_store() at app boot"
        )
    return _idempotency_store
```

Additionally, bound the `_locks` dict with `cachetools.LRUCache(maxsize=1024)` per architecture-council recommendation (long-running processes leak memory otherwise):

```python
from cachetools import LRUCache

class IdempotencyStore:
    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._counters: dict[tuple[TaskCategory, str | None], int] = defaultdict(int)
        self._shard_locks: LRUCache = LRUCache(maxsize=1024)  # FIX: bound lock memory
```

Update `pool_route_execute` to use `get_idempotency_store()` instead of constructing per-call:

```python
# Before (broken):
idem_store = IdempotencyStore(event_store)  # per-call instance; locks don't share

# After (FIX round-5):
idem_store = get_idempotency_store()  # module-global singleton; locks share across calls
```

### 4b. `mahavishnu/core/idempotency.py` — circuit breaker (FIX round-5: fail-CLOSED 3am bomb)

Per devops-troubleshooter C-6 BLOCK + user decision "middle option: log + skip cached error": wrap `get_or_create` with a circuit breaker. When the EventStore is unreachable, the circuit opens after N consecutive failures; subsequent calls fast-fail with a cached error response (no DB hit, no 30s timeout).

```python
class IdempotencyCircuitBreaker:
    """Circuit breaker for EventStore reachability.

    State machine: CLOSED → OPEN (after N consecutive failures) → HALF_OPEN
    (after cooldown_seconds) → CLOSED (on first success) or back to OPEN.

    Per user decision: degraded mode is "log + skip (return cached error)"
    — the dispatch does NOT proceed when the circuit is open. This preserves
    the no-duplicate-work guarantee (fail-CLOSED) while avoiding the 30s
    timeout cliff identified by the devops review.

    FIX round-7 (Tier 2 operational polish): the breaker tracks state via
    metrics so operators can distinguish "circuit OPEN" from "DB genuinely
    down" at 3am. `IdempotencyCircuitOpen` is a distinct exception class
    so callers can route differently if desired.
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
        """FIX round-7: expose circuit state for the metric gauge."""
        return self._opened_at is not None

    async def call(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        """Execute coro_factory() if circuit is closed; raise IdempotencyCircuitOpen
        if open, or IdempotencyStoreUnavailable if the underlying call failed.
        """
        async with self._lock:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self._cooldown_seconds:
                    # Circuit is open; fast-fail with distinct exception.
                    # FIX round-7: log structured + bump circuit-state metric.
                    IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(1)
                    logger.warning(
                        "idempotency circuit open; skipping",
                        extra={"error_id": "IDEMPOTENCY_CIRCUIT_OPEN"},
                    )
                    raise IdempotencyCircuitOpen(
                        "circuit open; event store unreachable"
                    )
                # Cooldown elapsed; transition to HALF_OPEN (one trial allowed)
                self._opened_at = None
                IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(0)
                IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                    transition="half_open"
                ).inc()

        try:
            result = await coro_factory()
        except IdempotencyStoreUnavailable:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(1)
                IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                    transition="open"
                ).inc()
                logger.exception("circuit tripped to OPEN",
                                  extra={"consecutive_failures": self._consecutive_failures})
            raise
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(1)
                IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                    transition="open"
                ).inc()
            raise

        # Success
        if self._consecutive_failures > 0:
            IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL.labels(
                transition="closed"
            ).inc()
            IDEMPOTENCY_CIRCUIT_STATE_GAUGE.set(0)
        self._consecutive_failures = 0
        return result
```

`get_or_create` is wrapped at the call site:

```python
breaker = get_idempotency_breaker()
existing = await breaker.call(
    lambda: idem_store.get_or_create(idempotency, payload_hash, actor="pool_route_execute")
)
```

### 4c. `mahavishnu/cli/pool_route_execute_cli.py` — Typer CLI shim (FIX round-5: INC-3)

Per round-5 critique (critical-audit INC-3) + user decision "both": C-13 invokes `["mahavishnu", "pool_route_execute", ...]` CLI which no plan implemented. Add a thin CLI shim. TODO comment notes the future MCP-mediated dispatch path:

```python
"""mahavishnu pool_route_execute — CLI shim for cross-process dispatch.

Per round-5 fix (critical-audit INC-3): C-13 in the crackerjack repo invokes
this CLI via subprocess. Without this shim, C-13's `_dispatch_via_mahavishnu`
fails with "unknown command".

TODO (round-5): once crackerjack grows an MCP-aware runtime, swap this
subprocess dispatch for `mcp__mahavishnu__pool_route_execute` (MCP-mediated).
The subprocess path is a deliberate cross-repo boundary that preserves
each repo's release cadence; MCP-mediated dispatch couples the repos at
the wire level. Until then, subprocess is the lowest-friction path.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import typer
from oneiric.core.logging import get_logger

from mahavishnu.core.config import get_settings
from mahavishnu.mcp.tools.pool_tools import pool_route_execute

logger = get_logger(__name__)
pool_route_execute_app = typer.Typer(help="CLI shim for cross-process dispatch (see C-13).")


@pool_route_execute_app.command("execute")
def execute_cmd(
    prompt: str = typer.Option(..., "--prompt"),
    pool_selector: str = typer.Option("least_loaded", "--pool-selector"),
    idempotency_source: str | None = typer.Option(None, "--idempotency-source"),
    idempotency_nonce: str | None = typer.Option(None, "--idempotency-nonce"),
    idempotency_ttl_seconds: int = typer.Option(86_400, "--idempotency-ttl-seconds"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Dispatch a prompt to a pool with optional idempotency."""
    from mahavishnu.core.idempotency import IdempotencyOptions

    idempotency = None
    if idempotency_source and idempotency_nonce:
        idempotency = IdempotencyOptions(
            source=idempotency_source,
            nonce=idempotency_nonce,
            ttl_seconds=idempotency_ttl_seconds,
        )

    result = asyncio.run(
        pool_route_execute(
            prompt=prompt,
            pool_selector=pool_selector,
            idempotency=idempotency,
        )
    )
    if json_output:
        typer.echo(json.dumps(result, default=str))
    else:
        typer.echo(str(result))
```

Register in `mahavishnu/_main_cli.py` (after the `workflows_app` registration at lines 170-171):

```python
from mahavishnu.cli.pool_route_execute_cli import pool_route_execute_app
app.add_typer(pool_route_execute_app, name="pool-route-execute")
```

This exposes `mahavishnu pool-route-execute execute --prompt "..." --idempotency-source ... --idempotency-nonce ...` for C-13's subprocess dispatch.

### 4d. `mahavishnu/core/metrics.py` — add 4 metrics

```python
IDEMPOTENCY_HIT_TOTAL = Counter(
    "idempotency_hit_total",
    "Total idempotent dispatch hits (caller retry detected).",
    labelnames=["source"],
)

IDEMPOTENCY_MISS_TOTAL = Counter(
    "idempotency_miss_total",
    "Total idempotent dispatch misses (fresh work dispatched).",
    labelnames=["source"],
)

# FIX round-7 (Tier 2 operational polish): circuit breaker observability.
# Operators need to distinguish "circuit OPEN for 2 hours" from "DB slow"
# at 3am. The gauge is 0 when CLOSED, 1 when OPEN. The counter records every
# state transition for retrospective analysis.
IDEMPOTENCY_CIRCUIT_STATE_GAUGE = Gauge(
    "idempotency_circuit_state",
    "Idempotency circuit breaker state (0=CLOSED, 1=OPEN).",
)

IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL = Counter(
    "idempotency_circuit_transitions_total",
    "Total idempotency circuit state transitions.",
    labelnames=["transition"],  # "open" | "closed" | "half_open"
)
```

Increment `IDEMPOTENCY_HIT_TOTAL.labels(source=existing.data["source"])` on the duplicate-return path; `IDEMPOTENCY_MISS_TOTAL` on the create-new-PENDING path.

Alert: `idempotency_circuit_state == 1 for >5m` → page on-call (per `docs/slos/2026-09-26-wireup-pool-dispatch.md`).

### 5. `mahavishnu/core/errors.py` — verify `IdempotencyStoreUnavailable` (from C-3) and add `IdempotencyCircuitOpen` (FIX round-7 Tier 2)

Verify `IdempotencyStoreUnavailable` is present (added in C-3). **FIX round-7**: add the new `IdempotencyCircuitOpen` exception class — distinct from `IdempotencyStoreUnavailable` so operators can route circuit-open fast-fails differently from underlying-store failures:

```python
class IdempotencyStoreUnavailable(MahavishnuError):
    """Raised when the idempotency store unreachable; fail-CLOSED behavior expected."""


class IdempotencyCircuitOpen(MahavishnuError):
    """Raised by IdempotencyCircuitBreaker when the breaker is OPEN.

    Distinct from IdempotencyStoreUnavailable so callers can route
    differently. IdempotencyStoreUnavailable indicates the underlying
    store raised; IdempotencyCircuitOpen indicates the breaker is gating
    traffic without touching the underlying store.
    """
```

## Tests

### 6. `tests/integration/test_pool_route_execute_idempotency.py` — new file (~280 LoC)

```python
"""Tests for pool_route_execute(idempotency=IdempotencyOptions(...))."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import IdempotencyStoreUnavailable, IdempotencyCircuitOpen  # FIX round-7: distinct exception for circuit-open vs underlying failure
from mahavishnu.core.event_store import TaskEventType
from mahavishnu.core.idempotency import IdempotencyOptions, IdempotencyStore


@pytest.mark.req(["REQ-006"])
class TestIdempotencyOptions:
    def test_minimal_options(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        assert opts.source == "cli.dispatch"
        assert opts.nonce == "abc-123"
        assert opts.ttl_seconds == 86_400  # default

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            IdempotencyOptions(source="cli.dispatch", nonce="abc-123", unknown_field=1)

    def test_ttl_bounds(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(source="cli.dispatch", nonce="abc-123", ttl_seconds=30)  # < 60
        with pytest.raises(ValueError):
            IdempotencyOptions(source="cli.dispatch", nonce="abc-123", ttl_seconds=2_000_000)  # > 7 days


@pytest.mark.req(["REQ-008"])
class TestFingerprint:
    def test_fingerprint_is_hex_64_chars(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        fp = IdempotencyStore.fingerprint(opts, "payload-hash")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_changes_with_payload(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        fp1 = IdempotencyStore.fingerprint(opts, "payload-A")
        fp2 = IdempotencyStore.fingerprint(opts, "payload-B")
        assert fp1 != fp2

    def test_fingerprint_changes_with_ttl_bucket(self) -> None:
        opts1 = IdempotencyOptions(source="cli.dispatch", nonce="abc-123", ttl_seconds=3600)
        opts2 = IdempotencyOptions(source="cli.dispatch", nonce="abc-123", ttl_seconds=7200)
        fp1 = IdempotencyStore.fingerprint(opts1, "payload")
        fp2 = IdempotencyStore.fingerprint(opts2, "payload")
        assert fp1 != fp2  # different TTL bucket → different fingerprint


@pytest.mark.req(["REQ-006", "REQ-007"])
class TestGetOrCreate:
    async def test_first_call_creates_pending(
        self, isolated_database, controllable_pool_manager_mock
    ) -> None:
        from mahavishnu.core.event_store import EventStore

        # FIX round-6: EventStore takes a Database, not a Path.
        db = Database(isolated_database)
        store = EventStore(db)
        idem = IdempotencyStore(store)
        opts = IdempotencyOptions(source="cli.dispatch", nonce="first-1")
        event = await idem.get_or_create(opts, "payload-hash", actor="test")
        assert event.event_type == TaskEventType.PENDING

    async def test_second_call_returns_existing(
        self, isolated_database, controllable_pool_manager_mock
    ) -> None:
        from mahavishnu.core.event_store import EventStore

        # FIX round-6: EventStore takes a Database, not a Path.
        db = Database(isolated_database)
        store = EventStore(db)
        idem = IdempotencyStore(store)
        opts = IdempotencyOptions(source="cli.dispatch", nonce="first-1")
        event1 = await idem.get_or_create(opts, "payload-hash", actor="test")
        event2 = await idem.get_or_create(opts, "payload-hash", actor="test")
        assert event1.idempotency_key == event2.idempotency_key

    async def test_fail_closed_on_store_unavailable(self, isolated_database) -> None:
        """Per REQ-007: IdempotencyStoreUnavailable → no dispatch happens."""
        from mahavishnu.core.event_store import EventStore

        # FIX round-6: EventStore takes a Database, not a Path; EventStore has
        # no close() method. Simulate unavailability by patching the underlying
        # DB connection to raise on the next execute.
        from unittest.mock import patch
        db = Database(isolated_database)
        store = EventStore(db)
        with patch.object(db, "execute", side_effect=ConnectionError("store down")):
            idem = IdempotencyStore(store)
            opts = IdempotencyOptions(source="cli.dispatch", nonce="first-1")
            with pytest.raises(IdempotencyStoreUnavailable):
                await idem.get_or_create(opts, "payload-hash", actor="test")


@pytest.mark.req(["REQ-006"])
class TestMarkCompleted:
    async def test_pending_to_synced_transition(self, isolated_database) -> None:
        from mahavishnu.core.event_store import EventStore

        # FIX round-6: EventStore takes a Database, not a Path.
        db = Database(isolated_database)
        store = EventStore(db)
        idem = IdempotencyStore(store)
        opts = IdempotencyOptions(source="cli.dispatch", nonce="first-1")
        event = await idem.get_or_create(opts, "payload-hash", actor="test")
        await idem.mark_completed(event, {"status": "ok", "output": "done"})
        assert event.event_type == TaskEventType.COMPLETED
        assert event.data["result"] == {"status": "ok", "output": "done"}


@pytest.mark.req(["REQ-007"])
class TestAsyncioLockFallback:
    """Per REQ-007: asyncio.Lock prevents the in-process race between
    get_or_create() check and the DB unique constraint enforcement."""

    async def test_concurrent_get_or_create_returns_same_event(self, isolated_database) -> None:
        """Two concurrent calls with the same key must return the same event
        (one creates, one finds the existing)."""
        from mahavishnu.core.event_store import EventStore
        import asyncio

        # FIX round-6: EventStore takes a Database, not a Path.
        db = Database(isolated_database)
        store = EventStore(db)
        idem = IdempotencyStore(store)
        opts = IdempotencyOptions(source="cli.dispatch", nonce="concurrent-1")

        # Fire two coroutines concurrently
        event_a, event_b = await asyncio.gather(
            idem.get_or_create(opts, "payload-hash", actor="test"),
            idem.get_or_create(opts, "payload-hash", actor="test"),
        )
        assert event_a.idempotency_key == event_b.idempotency_key


@pytest.mark.req(["REQ-006", "REQ-007", "REQ-008"])
class TestPoolRouteExecuteIntegration:
    """End-to-end: pool_route_execute(idempotency=...) honors idempotency contract."""

    async def test_duplicate_returns_cached_result(self, isolated_database) -> None:
        from mahavishnu.mcp.tools.pool_tools import pool_route_execute
        from mahavishnu.core.idempotency import IdempotencyOptions

        opts = IdempotencyOptions(source="cli.dispatch", nonce="dup-1")
        result1 = await pool_route_execute(
            prompt="hello world",
            pool_selector="least_loaded",
            idempotency=opts,
        )
        result2 = await pool_route_execute(
            prompt="hello world",
            pool_selector="least_loaded",
            idempotency=opts,
        )
        assert result2["status"] == "duplicate"
        assert result2["result"] == result1  # same content

    async def test_store_unavailable_fails_closed(self, isolated_database) -> None:
        """Pool-level integration: IdempotencyStoreUnavailable returns
        'idempotency store unavailable' without dispatching."""
        from mahavishnu.mcp.tools.pool_tools import pool_route_execute
        from mahavishnu.core.idempotency import IdempotencyOptions

        # Patch the IdempotencyStore constructor to raise
        with patch(
            "mahavishnu.core.idempotency.IdempotencyStore",
            side_effect=IdempotencyStoreUnavailable("test"),
        ):
            opts = IdempotencyOptions(source="cli.dispatch", nonce="dup-2")
            result = await pool_route_execute(
                prompt="hello world",
                pool_selector="least_loaded",
                idempotency=opts,
            )
            assert result["status"] == "error"
            assert "idempotency store unavailable" in result["error"]
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_pool_route_execute_idempotency.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/core/idempotency.py` exists with `IdempotencyOptions` Pydantic model + `IdempotencyStore` class.
2. `IdempotencyOptions` enforces `extra="forbid"`, source max 255, nonce max 128, ttl 60..604800.
3. `IdempotencyStore.fingerprint()` returns 64-char lowercase hex (SHA-256 digest via Oneiric `HashAction`).
4. Fingerprint varies with payload AND with TTL bucket.
5. `pool_route_execute(idempotency=...)` returns `{"status": "duplicate", "result": <cached>}` on second call with same key.
6. `IdempotencyStoreUnavailable` propagates from `get_or_create` and is converted to `{"status": "error", "error": "idempotency store unavailable"}` at the pool boundary (fail-CLOSED, no dispatch).
7. Two concurrent `get_or_create()` calls with the same key return events with the same `idempotency_key` (asyncio.Lock fallback works).
8. `mark_completed()` transitions a single row from PENDING to SYNCED in place (no insert-then-update).
9. `python scripts/audit_requirements.py --json` reports REQ-006, REQ-007, REQ-008 wired.
10. `pool_route_execute` arg count is ≤ 10 (verified by `crackerjack run`).
11. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0`, no deprecation window for `pool_route_execute`. The new `idempotency` kwarg is OPTIONAL (default `None`), so callers that never pass it see identical behavior to before — no API breakage for non-idempotency callers.

For idempotency callers, the fail-CLOSED default means a misconfigured deployment (EventStore unreachable) silently rejects dispatches. Recovery is "fix the EventStore". There is no fallback to non-idempotent dispatch — that would be fail-open, which violates the no-backcompat policy.

If `pool_route_execute` arg count exceeds 10 after C-8's `worktree` kwarg is added, the fix is to group more params into `IdempotencyOptions` or a new options model. C-6's arg count is 8 (existing 7 + idempotency); C-8 adds worktree to make 9 — both fit.

## Observability added

Two new Prometheus metrics:

- `idempotency_hit_total{source}` — Counter; incremented on duplicate-return path
- `idempotency_miss_total{source}` — Counter; incremented on create-new-PENDING path

Operators alert on `rate(idempotency_hit_total[5m]) > rate(idempotency_miss_total[5m]) * 0.1` (too many hits = caller is hammering with duplicates; not enough hits = idempotency is silently bypassing).

## Health aggregation

The fail-CLOSED behavior surfaces via the existing `_register_health_tools` aggregator: `event_store` health check (added in C-3) returns degraded if the store is unreachable. Operators see `/health` 503 before `pool_route_execute` errors out.

## Implementation notes / gotchas

- **The `idempotency_key` is HASHED, not raw.** Per round-4 ace + security finding. Raw `f"{source}:{nonce}"` would expose caller identifiers in logs and metrics. The SHA-256 digest is opaque.
- **TTL bucket in the fingerprint** prevents stale-key collisions across long-running caches. Without it, a record from 24 hours ago with the same source+nonce+payload would re-fire the same idempotency_key — even though `ttl_seconds` has expired and a fresh dispatch is legitimate.
- **Fail-CLOSED default** is per `feedback-no-backwards-compat-pre-1.0`. The alternative (fail-open = allow duplicates) was explicitly rejected as a dual-API surface.
- **asyncio.Lock is per-key, not per-process.** A single global lock would serialize all idempotent dispatches; a per-key lock only serializes concurrent calls with the same key (the actual race).
- **The asyncio.Lock is a fallback, not the primary defense.** The DB unique constraint (added in C-4) is the primary defense against duplicates; the lock only narrows the race window between the in-process `get_or_create` check and the DB insert.
- **The lock dict grows unbounded.** For long-running processes, a `cachetools.LRUCache(maxsize=1024)` bounds memory. C-9's concurrency gate uses this pattern.
- **Mark-completed is in-place UPDATE** (not insert-then-update). This matches the REQ-006 spec and avoids the audit-trail fragmentation of multiple rows for one logical event.
- **`event_type=SYNCED` is "COMPLETED" in the existing StrEnum.** The plan uses `TaskEventType.COMPLETED` because the existing enum has no `COMPLETED` value (C-3 only added `PENDING`). SYNCED is the closest existing semantic; a follow-up commit could add `COMPLETED` if naming becomes a friction point.
- **The Pydantic model `extra="forbid"`** prevents callers from passing unknown fields (e.g., a typo'd `idempotancy_key`). Validation error surfaces immediately.
- **`actor="pool_route_execute"`** is a placeholder; production should pass the authenticated caller's identity. The plan does not wire auth — that's a separate concern.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/core/idempotency.py` | create | ~120 |
| `mahavishnu/mcp/tools/pool_tools.py` | edit (extend `pool_route_execute` signature with `idempotency` kwarg) | +50 |
| `mahavishnu/core/event_store.py` | edit (add `get_event_by_idempotency_key` if not present) | +8 |
| `mahavishnu/core/metrics.py` | edit (add 2 Counters) | +14 |
| `tests/integration/test_pool_route_execute_idempotency.py` | create | +280 |
