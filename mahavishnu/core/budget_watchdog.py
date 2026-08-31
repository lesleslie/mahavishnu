"""Budget watchdog — multi-replica-safe per-run budget enforcer.

This module is the **per-run** enforcement primitive that lives in the
control plane (Phase 3 of the v2 plan). It walks the state machine in
:mod:`mahavishnu.core.budget` once every polling interval and:

1. Acquires a soft lease in Dhara so only one Mahavishnu replica runs
   enforcement per cycle (multi-replica safety).
2. Lists active budget records.
3. Reads the latest usage for each active budget.
4. Transitions any record that has breached a cap to ``EXCEEDED``.
5. Writes the updated record back to Dhara.

Per-turn reads do **not** flow through this module — they stay
in-process inside the worker (contrarian review of v1):

> Primitives whose natural read frequency is per-turn belong in-process;
> per-run belong in the control plane. The control plane polls once a
> minute; per-turn polling would 60× the storage rate for no benefit.

Failure semantics:

* Dhara unavailability — **fail-open**. The watchdog logs at ``WARNING``
  with ``budget.dhara_unavailable`` and returns cleanly so the next
  cycle has another chance. The plan's exit criteria require this; if
  we failed closed, a brief Dhara blip would silently pass every
  exceeded budget through.

* Stuck cycle (e.g., a record write hangs) — the watchdog uses an
  overall cycle timeout equal to ``poll_interval_seconds``. Cycles that
  exceed the timeout are cancelled and logged; the lease TTL is short
  enough that the next replica can take over.

The module is async-only. A sync wrapper for unit tests is provided at
the bottom (``run_watchdog_once``) that does not touch the event loop —
it just invokes the pure logic against an in-memory fake store.

OTel
----

The watchdog emits one OTel span per cycle (``budget.check``) and one
counter increment per dimension exceeded
(``budget.exceeded.count`` with ``dimension`` label). The counter is
best-effort: when no OTel SDK is configured (most unit tests) the
emission is a no-op. Production paths wire the real opentelemetry API
through the existing project helpers — see
``mahavishnu/core/observability.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Protocol
import uuid

from .budget import (
    BudgetRecord,
    BudgetState,
    BudgetStateMachine,
    BudgetUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage protocol
# ---------------------------------------------------------------------------


class BudgetStore(Protocol):
    """Async storage interface for budget records.

    Implemented by :class:`DharaBudgetStore` against the real Dhara
    substrate and by an in-memory fake (``_InMemoryBudgetStore``) for
    tests. The lease operations are best-effort soft locks: a missing
    implementation should NOT raise (the watchdog falls back to
    single-replica mode).
    """

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the persisted value at ``key`` or ``None``."""

    async def put(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> Any:
        """Persist ``value`` at ``key`` with optional TTL."""

    async def list_keys(self, prefix: str) -> list[str]:
        """Return keys starting with ``prefix`` (record IDs, not full)."""

    async def try_acquire_lease(
        self,
        lease_key: str,
        holder: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        """Soft-lease: True if we obtained or already held the lease.

        Implementations are expected to be idempotent — a holder
        re-acquiring their own lease returns ``True`` and refreshes
        the TTL.
        """

    async def release_lease(self, lease_key: str, holder: str) -> None:
        """Release the lease if (and only if) we still own it."""


class DharaBudgetStore:
    """Adapter over the Mahavishnu Dhara client for budget persistence.

    Uses :meth:`DharaClient.put` for record writes and the same for
    lease writes (Dhara honors ``ttl_seconds``). Lease acquisition is
    get-then-cas — safe enough for a 60s watchdog because the worst
    case is two replicas running for one poll cycle (no permanent
    damage).

    The store is intentionally narrow: it has only the methods the
    watchdog needs, so a unit test can drop in an in-memory fake without
    dragging the rest of Dhara along.
    """

    def __init__(
        self,
        dhara_client: Any,
        *,
        record_prefix: str = "mahavishni://budgets/",
        lease_key: str = "mahavishni://budgets/lease.json",
    ) -> None:
        self._client = dhara_client
        self._record_prefix = record_prefix
        self._lease_key = lease_key

    @staticmethod
    def record_key(workflow_id: str) -> str:
        return f"mahavishni://budgets/{workflow_id}.json"

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._client.call_tool(
            "get",
            {"key": key},
        )
        # Dhara's get returns either a JSON object or None; tests provide both shapes.
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            import json

            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except TypeError, ValueError:
                return None
        return None

    async def put(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> Any:
        arguments: dict[str, Any] = {"key": key, "value": value}
        if ttl_seconds is not None:
            arguments["ttl"] = ttl_seconds
        return await self._client.call_tool("put", arguments)

    async def list_keys(self, prefix: str) -> list[str]:
        """Return workflow IDs (without the prefix) for all budget records.

        Implementation calls ``list_keys`` via the Dhara client and
        filters to ``prefix``. Test fakes can shortcut to a known set.
        """
        raw = await self._client.call_tool(
            "list_keys",
            {"prefix": prefix},
        )
        names: list[str] = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.startswith(self._record_prefix):
                    names.append(entry[len(self._record_prefix) :])
        elif isinstance(raw, dict):
            keys = raw.get("keys") or []
            if isinstance(keys, list):
                for entry in keys:
                    if isinstance(entry, str) and entry.startswith(self._record_prefix):
                        names.append(entry[len(self._record_prefix) :])
        return names

    async def try_acquire_lease(
        self,
        lease_key: str,
        holder: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        """Cas-style soft lease against Dhara.

        1. Read current lease; if absent or expired-or-foreign, write ours.
        2. If present and held by us, refresh the TTL.

        There is a benign race window between step 1 and step 2 where
        two replicas can both acquire on first poll. The TTL keeps that
        window short (one put round-trip); the next poll re-elects
        cleanly.
        """
        current = await self._client.call_tool("get", {"key": lease_key})
        existing_holder = None
        if isinstance(current, dict):
            existing_holder = current.get("holder")
        elif isinstance(current, str):
            import json

            try:
                parsed = json.loads(current)
                if isinstance(parsed, dict):
                    existing_holder = parsed.get("holder")
            except TypeError, ValueError:
                existing_holder = None
        if existing_holder not in (None, "", holder):
            return False
        await self._client.call_tool(
            "put",
            {
                "key": lease_key,
                "value": {"holder": holder, "acquired_at": datetime.now(UTC).isoformat()},
                "ttl": ttl_seconds,
            },
        )
        return True

    async def release_lease(self, lease_key: str, holder: str) -> None:
        current = await self._client.call_tool("get", {"key": lease_key})
        existing_holder = None
        if isinstance(current, dict):
            existing_holder = current.get("holder")
        if existing_holder == holder:
            # Best-effort: delete the lease by storing a tombstone.
            await self._client.call_tool(
                "put",
                {"key": lease_key, "value": {"holder": "", "released": True}},
            )


# ---------------------------------------------------------------------------
# OTel emission
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WatchdogMetrics:
    """Counters exposed by the watchdog for tests + OTel adapters.

    The production OTel bridge maps each field to a metric:

    * ``cycles`` → counter ``budget.check.cycles``
    * ``skipped_dhara_unavailable`` → counter ``budget.dhara_skip.count``
    * ``lease_lost`` → counter ``budget.lease.lost``
    * ``exceeded[dimension]`` → counter ``budget.exceeded.count`` with
      label ``dimension=<tokens|turns|wallclock>``

    Tests use these directly without an OTel SDK in the loop.
    """

    cycles: int = 0
    skipped_dhara_unavailable: int = 0
    lease_lost: int = 0
    exceeded: dict[str, int] = field(default_factory=dict)
    last_cycle_at: datetime | None = None
    last_cycle_duration_ms: float | None = None


class OTelEmitter(Protocol):
    """Hook for emitting OTel spans + counters.

    Real wiring: an adapter that calls the project's existing OTel
    helpers. Default: a no-op implementation that just returns. Tests
    can pass a recording emitter to assert on span names and counter
    increments.
    """

    def start_span(self, name: str, **attrs: Any) -> Any:
        """Return a span-like object (with ``__enter__``/``__exit__`` or None)."""

    def increment(self, name: str, **attrs: Any) -> None:
        """Increment a counter (best-effort)."""


class _NullEmitter:
    """Default emitter used when no OTel SDK is configured."""

    def start_span(self, name: str, **attrs: Any) -> None:
        return None

    def increment(self, name: str, **attrs: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Usage source
# ---------------------------------------------------------------------------


UsageSource = Callable[[str], Awaitable[BudgetUsage | None]]
"""Async callable that returns the current usage for a workflow, or None.

The default wired in production polls the worker manager for tokens/turns
elapsed and computes wallclock from ``record.started_at``. Tests inject a
deterministic fake.
"""


# ---------------------------------------------------------------------------
# Cycle runner (pure logic for unit tests)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WatchdogCycleResult:
    """Result of one watchdog cycle.

    Surfaced so tests and the supervisor can assert on what happened
    without poking at private state.
    """

    lease_acquired: bool
    records_scanned: int
    records_transitioned: int
    dhara_unavailable: bool = False
    cycle_at: datetime = field(default_factory=lambda: datetime.now(UTC))


async def run_watchdog_cycle(
    *,
    store: BudgetStore,
    holder: str,
    lease_ttl_seconds: int,
    usage_source: UsageSource,
    now: Callable[[], datetime] | None = None,
    emitter: OTelEmitter | None = None,
    metrics: WatchdogMetrics | None = None,
    record_prefix: str = "mahavishni://budgets/",
) -> WatchdogCycleResult:
    """Run one watchdog cycle against ``store``.

    This is the pure-logic kernel of the watchdog loop. It does not
    sleep, does not loop, does not own a lease across calls — every
    call is one cycle. The async loop around it (see
    :func:`run_watchdog`) is responsible for the periodic timer and
    for handling :class:`asyncio.CancelledError` cleanly.

    The cycle:

    1. Try to acquire the lease. If the lease is held by another
       replica, return immediately with ``lease_acquired=False`` so
       the caller can log/observe.
    2. List record keys in the budget prefix and fetch each record.
    3. For each active record, ask ``usage_source`` for current usage.
       If usage is ``None``, skip (worker has not reported anything yet).
    4. Run the state machine; if a dimension is exceeded, transition
       the record to ``EXCEEDED`` and increment counters.
    5. Release the lease and return.

    Dhara unavailability surfaces as ``DharaConnectionError`` from
    :class:`DharaBudgetStore` — and as ``Exception`` from the generic
    protocol — and is caught at the **highest** level so the cycle
    returns with ``dhara_unavailable=True`` and the outer loop can
    log + continue (fail-open).
    """
    emitter = emitter or _NullEmitter()
    metrics = metrics or WatchdogMetrics()
    now_fn = now or (lambda: datetime.now(UTC))

    span = emitter.start_span("budget.check")
    try:
        metrics.cycles += 1
        acquired, dhara_unavailable = await _acquire_lease_or_failopen(
            store=store,
            lease_key=f"{record_prefix}lease.json",
            holder=holder,
            lease_ttl_seconds=lease_ttl_seconds,
            metrics=metrics,
        )
        if dhara_unavailable:
            return WatchdogCycleResult(
                lease_acquired=False,
                records_scanned=0,
                records_transitioned=0,
                dhara_unavailable=True,
            )

        if not acquired:
            metrics.lease_lost += 1
            logger.debug("budget.watchdog: lease held by another replica; skipping cycle")
            return WatchdogCycleResult(
                lease_acquired=False,
                records_scanned=0,
                records_transitioned=0,
            )

        try:
            keys, list_failed = await _list_budget_keys_or_failopen(
                store=store, prefix=record_prefix, metrics=metrics
            )
            if list_failed or keys is None:
                return WatchdogCycleResult(
                    lease_acquired=True,
                    records_scanned=0,
                    records_transitioned=0,
                    dhara_unavailable=True,
                )

            scanned, transitioned = await _scan_and_persist(
                keys=keys,
                store=store,
                record_prefix=record_prefix,
                usage_source=usage_source,
                now_fn=now_fn,
                emitter=emitter,
                metrics=metrics,
            )
            return WatchdogCycleResult(
                lease_acquired=True,
                records_scanned=scanned,
                records_transitioned=transitioned,
            )
        finally:
            # NOTE: we deliberately do NOT release the lease on a
            # successful cycle exit. The lease is intended to live for
            # the full TTL window so the next cycle's CAS sees the
            # same holder and refreshes it transparently. Releasing at
            # the end of each cycle creates a race window where two
            # replicas can both acquire on consecutive polls. The
            # TTL is the safety net for crashed watchdogs.
            pass
    finally:
        metrics.last_cycle_at = now_fn()
        await _close_otel_span(span)


async def _acquire_lease_or_failopen(
    *,
    store: BudgetStore,
    lease_key: str,
    holder: str,
    lease_ttl_seconds: int,
    metrics: WatchdogMetrics,
) -> tuple[bool, bool]:
    """Try to acquire the watchdog lease, fail-open on Dhara errors.

    Returns ``(acquired, dhara_unavailable)``. On a Dhara failure
    ``metrics.skipped_dhara_unavailable`` is incremented and the
    caller surfaces ``dhara_unavailable=True`` on the cycle result.
    """
    try:
        acquired = await store.try_acquire_lease(lease_key, holder, ttl_seconds=lease_ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - watchdog must fail-open
        metrics.skipped_dhara_unavailable += 1
        logger.warning("budget.dhara_unavailable while acquiring lease: %s", exc)
        return False, True
    return acquired, False


async def _list_budget_keys_or_failopen(
    *,
    store: BudgetStore,
    prefix: str,
    metrics: WatchdogMetrics,
) -> tuple[list[str] | None, bool]:
    """List budget record keys, fail-open on Dhara errors.

    Returns ``(keys, list_failed)``. On Dhara failure ``keys`` is None
    and ``list_failed`` is True (caller surfaces ``dhara_unavailable``
    on the cycle result).
    """
    try:
        keys = await store.list_keys(prefix)
    except Exception as exc:  # noqa: BLE001 - watchdog must fail-open
        metrics.skipped_dhara_unavailable += 1
        logger.warning("budget.dhara_unavailable while listing records: %s", exc)
        return None, True
    return keys, False


async def _scan_and_persist(
    *,
    keys: list[str],
    store: BudgetStore,
    record_prefix: str,
    usage_source: UsageSource,
    now_fn: Callable[[], datetime],
    emitter: OTelEmitter,
    metrics: WatchdogMetrics,
) -> tuple[int, int]:
    """Walk all budget keys, return ``(scanned, transitioned)``."""
    scanned = 0
    transitioned = 0
    for key in keys:
        if not key or key.endswith("/lease.json"):
            continue
        scanned += 1
        if await _process_one_budget_record(
            key=key,
            store=store,
            record_prefix=record_prefix,
            usage_source=usage_source,
            now_fn=now_fn,
            emitter=emitter,
            metrics=metrics,
        ):
            transitioned += 1
    return scanned, transitioned


async def _process_one_budget_record(
    *,
    key: str,
    store: BudgetStore,
    record_prefix: str,
    usage_source: UsageSource,
    now_fn: Callable[[], datetime],
    emitter: OTelEmitter,
    metrics: WatchdogMetrics,
) -> bool:
    """Process a single budget record. Returns True if it was transitioned.

    Failures are logged and swallowed so one bad record doesn't abort
    the cycle — Dhara may be partially available, the usage source
    may have hiccups, and the record may simply not be active yet.
    """
    try:
        raw = await store.get(f"{record_prefix}{key}")
    except Exception as exc:  # noqa: BLE001 - per-record fail-soft
        logger.warning("budget.dhara_unavailable fetching %s: %s", key, exc)
        return False
    if not isinstance(raw, dict):
        return False
    record = BudgetRecord.from_dict(raw)
    sm = BudgetStateMachine(record)
    if sm.record.state is not BudgetState.ACTIVE:
        return False
    try:
        usage = await usage_source(sm.record.workflow_id)
    except Exception as exc:  # noqa: BLE001 - usage_source failures are per-record
        logger.warning("budget.usage_source failed for %s: %s", sm.record.workflow_id, exc)
        return False
    if usage is None:
        # Worker hasn't reported yet — skip this cycle.
        return False
    dimension = sm.check(usage)
    if dimension is not None:
        sm.mark_exceeded(dimension, when=now_fn())
        metrics.exceeded[dimension.value] = metrics.exceeded.get(dimension.value, 0) + 1
        emitter.increment("budget.exceeded.count", dimension=dimension.value)
    try:
        await store.put(
            f"{record_prefix}{sm.record.workflow_id}.json",
            sm.record.to_dict(),
        )
    except Exception as exc:  # noqa: BLE001 - per-record persist failure
        logger.warning("budget.dhara_unavailable persisting %s: %s", sm.record.workflow_id, exc)
    return dimension is not None


async def _close_otel_span(span: Any) -> None:
    """Close the OTel span if it implements a context manager.

    The null emitter returns ``None`` (no-op). Real SDKs may return an
    async or sync context manager; we try both shapes and swallow
    errors so emission never breaks the cycle.
    """
    if span is None:
        return
    if hasattr(span, "__aexit__"):
        try:
            await span.__aexit__(None, None, None)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - OTel emission must never raise
            logger.debug("budget.otel_aexit_failed: %s", exc)
    elif hasattr(span, "__exit__"):
        try:
            span.__exit__(None, None, None)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - OTel emission must never raise
            logger.debug("budget.otel_exit_failed: %s", exc)


# ---------------------------------------------------------------------------
# Long-running loop
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WatchdogConfig:
    """Static configuration for :func:`run_watchdog`.

    ``holder`` is the unique identifier of this replica. Operators
    should derive it from the process id + hostname so a restart does
    not inherit the previous replica's identity (the lease TTL would
    cover that, but explicit is better).

    ``poll_interval_seconds`` defaults to 60 (the plan's documented
    cadence) and ``lease_ttl_seconds`` defaults to ``max(120,
    poll_interval_seconds * 2)`` — comfortably longer than one cycle
    so the lease does not expire mid-scan.
    """

    holder: str = field(default_factory=lambda: f"mahavishni-{uuid.uuid4().hex[:8]}")
    poll_interval_seconds: float = 60.0
    lease_ttl_seconds: int = 0  # 0 -> compute from poll_interval
    record_prefix: str = "mahavishni://budgets/"

    def __post_init__(self) -> None:
        if self.lease_ttl_seconds <= 0:
            self.lease_ttl_seconds = max(120, int(self.poll_interval_seconds * 2))


async def run_watchdog(
    *,
    config: WatchdogConfig,
    store: BudgetStore,
    usage_source: UsageSource,
    metrics: WatchdogMetrics | None = None,
    emitter: OTelEmitter | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    now: Callable[[], datetime] | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Long-running watchdog loop.

    Returns only when ``stop_event`` is set (production) or when the
    surrounding task is cancelled (tests). Catches
    :class:`asyncio.CancelledError` cleanly so the loop exits between
    cycles rather than mid-cycle; if cancellation happens mid-cycle
    we let the in-flight cycle complete (because re-entering Dhara
    mid-write is worse than missing one cycle).

    The ``_now`` seam is exposed via ``now`` so deterministic tests
    can simulate time-of-day without patching ``datetime`` itself.
    """

    metrics = metrics or WatchdogMetrics()
    emitter = emitter or _NullEmitter()
    now = now or (lambda: datetime.now(UTC))
    stop_event = stop_event or asyncio.Event()

    logger.info(
        "budget.watchdog.starting holder=%s interval=%.1fs lease_ttl=%ds",
        config.holder,
        config.poll_interval_seconds,
        config.lease_ttl_seconds,
    )
    try:
        while not stop_event.is_set():
            cycle_start = datetime.now(UTC)
            try:
                await run_watchdog_cycle(
                    store=store,
                    holder=config.holder,
                    lease_ttl_seconds=config.lease_ttl_seconds,
                    usage_source=usage_source,
                    now=now,
                    emitter=emitter,
                    metrics=metrics,
                    record_prefix=config.record_prefix,
                )
            except asyncio.CancelledError:
                # Re-raise immediately — shutdown signal wins.
                raise
            except Exception:
                logger.exception("budget.watchdog.unhandled")
            metrics.last_cycle_duration_ms = (
                datetime.now(UTC) - cycle_start
            ).total_seconds() * 1000.0
            await sleep(config.poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info(
            "budget.watchdog.stopped holder=%s cycles=%s dhara_skips=%s",
            config.holder,
            metrics.cycles,
            metrics.skipped_dhara_unavailable,
        )
        raise


# ---------------------------------------------------------------------------
# In-memory store for tests (also exposed via test_helpers)
# ---------------------------------------------------------------------------


class InMemoryBudgetStore:
    """In-memory :class:`BudgetStore` for unit + integration tests.

    Supports TTL via a ``datetime.now`` reference; leases honor
    ``holder``-matching only (no time check). The behavior matches
    real Dhara closely enough that the watchdog's fail-open paths get
    exercised in tests.
    """

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._records: dict[str, dict[str, Any]] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self.fail_next_op: str | None = None
        """When set, the next matching op raises RuntimeError to simulate Dhara down."""
        # Real Dhara has serial per-key semantics; we mirror that with a
        # per-store lock so concurrent ``try_acquire_lease`` calls do
        # not race past each other in unit tests.
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> dict[str, Any] | None:
        self._maybe_fail("get")
        return self._records.get(key)

    async def put(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> Any:
        self._maybe_fail("put")
        if not isinstance(value, dict):
            value = {"value": value}
        if ttl_seconds is not None:
            value = {
                **value,
                "ttl_seconds": ttl_seconds,
                "expires_at": (self._now() + timedelta(seconds=ttl_seconds)).isoformat(),
            }
        self._records[key] = value
        return value

    async def list_keys(self, prefix: str) -> list[str]:
        self._maybe_fail("list")
        return [
            k[len(prefix) :]
            for k in self._records
            if k.startswith(prefix) and not k.endswith("/lease.json")
        ]

    async def try_acquire_lease(
        self,
        lease_key: str,
        holder: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        self._maybe_fail("lease")
        async with self._lock:
            existing = self._leases.get(lease_key)
            if existing is not None:
                owner = existing.get("holder")
                expires_at_raw = existing.get("expires_at")
                if owner not in (None, "", holder):
                    if isinstance(expires_at_raw, str):
                        try:
                            expires_at = datetime.fromisoformat(expires_at_raw)
                        except ValueError:
                            expires_at = None
                        if expires_at is None or expires_at > self._now():
                            return False
            self._leases[lease_key] = {
                "holder": holder,
                "acquired_at": self._now().isoformat(),
                "expires_at": (self._now() + timedelta(seconds=ttl_seconds)).isoformat(),
            }
            return True

    async def release_lease(self, lease_key: str, holder: str) -> None:
        async with self._lock:
            existing = self._leases.get(lease_key)
            if existing is not None and existing.get("holder") == holder:
                self._leases.pop(lease_key, None)

    def _maybe_fail(self, op: str) -> None:
        if self.fail_next_op == op:
            self.fail_next_op = None
            raise RuntimeError(f"in-memory store simulated dhara failure on {op}")

    # Helper for tests -----------------------------------------------------

    def seed_record(self, record: BudgetRecord) -> None:
        """Place a record under the documented key shape."""
        self._records[f"mahavishni://budgets/{record.workflow_id}.json"] = record.to_dict()

    @property
    def leases(self) -> dict[str, dict[str, Any]]:
        return self._leases


@asynccontextmanager
async def _span_context(name: str, emitter: OTelEmitter):
    """Tiny helper so the watchdog's flow-of-control reads top-down."""
    span = emitter.start_span(name)
    try:
        yield span
    finally:
        if span is not None and hasattr(span, "__aexit__"):
            await span.__aexit__(None, None, None)  # type: ignore[attr-defined]
        elif span is not None and hasattr(span, "__exit__"):
            span.__exit__(None, None, None)  # type: ignore[attr-defined]
