"""OpenTelemetry metric helpers for the worktree storage layer (ADR 015 v4 §17).

Provides module-level histogram/counter instruments + a thin wrapper
API that callers use to emit metrics. The meter is initialized at
import time (NOT lazily) to avoid async-context races when multiple
``WorktreeProvider`` instances call into the helpers concurrently.

Metric surface (ADR §17)
------------------------
Histograms (seconds):
- ``worktree_create_duration_seconds`` labels: backend, status, principal_short
- ``worktree_fetch_duration_seconds``  labels: backend, status, principal_short
- ``worktree_lock_wait_seconds``       labels: repo, branch, acquired
- ``worktree_lock_held_seconds``       labels: repo, branch, principal_short
- ``cache_get_duration_seconds``       labels: backend, hit
- ``cache_set_duration_seconds``       labels: backend

Counters:
- ``worktree_cache_invalidation_total``  labels: backend, reason
- ``cache_fallback_total``              labels: from_tier, to_tier
- ``backend_health_check_failed_total`` labels: backend
- ``bundle_integrity_failure_total``    labels: backend, principal_short
- ``worktree_registry_drift_total``     labels: drift_kind

Histogram (bytes):
- ``bundle_bytes`` labels: repo

Cardinality protection
----------------------
``principal_short`` is computed via ``_short_principal`` which hashes a
full principal name (e.g. ``uid:12345``) to a stable 8-char prefix.
The full name never enters OTel. Per-process cardinality budget:
<50 unique ``(backend, principal_short)`` combos per minute. CI guard
test (``tests/unit/test_observability_metrics.py::test_cardinality_budget``)
enforces the hash is non-empty + stable across calls.

Label allowlist
---------------
Every label key passed via ``**labels`` is checked against
``_ALLOWED_LABEL_KEYS``. Unknown keys raise ``ValueError`` at emit
time so a typo never silently spawns an unbounded label set.
"""

from __future__ import annotations

from hashlib import sha256
import logging
from typing import Final, TYPE_CHECKING

from opentelemetry import metrics

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level meter — init at import, NOT lazily (avoids async-context races)
# ---------------------------------------------------------------------------

_meter = metrics.get_meter("mahavishnu.worktree")


# ---------------------------------------------------------------------------
# Label allowlist — reject unknown keys to prevent cardinality explosion
# ---------------------------------------------------------------------------

_ALLOWED_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "backend",
        "status",
        "principal_short",
        "repo",
        "branch",
        "acquired",
        "hit",
        "reason",
        "from_tier",
        "to_tier",
        "drift_kind",
    }
)


def _validate_labels(labels: dict[str, object]) -> None:
    unknown = set(labels) - _ALLOWED_LABEL_KEYS
    if unknown:
        raise ValueError(
            f"Unknown metric label keys: {sorted(unknown)}. "
            f"Allowed: {sorted(_ALLOWED_LABEL_KEYS)}"
        )


def _short_principal(principal: str | None) -> str:
    """Hash a principal name to a stable 8-char prefix for OTel cardinality.

    Empty / anonymous / None -> ``"anon"`` (single value, no cardinality
    explosion from unknown principals).
    """
    if not principal:
        return "anon"
    return sha256(principal.encode("utf-8")).hexdigest()[:8]


def _short_label(value: str | None, *, default: str = "unknown") -> str:
    """Hash a label value (repo, branch, etc.) to a stable 8-char prefix.

    Returns ``default`` for None / empty so all bucket-affinity is
    captured under a single value (no cardinality explosion from
    unknown labels).
    """
    if not value:
        return default
    return sha256(value.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Instruments — created at import time, shared across the process
# ---------------------------------------------------------------------------

# Seconds histograms (per §17)
_worktree_create_histogram: Histogram = _meter.create_histogram(
    name="worktree_create_duration_seconds",
    unit="s",
    description="Worktree create operation duration (seconds) per backend/status/principal.",
)
_worktree_fetch_histogram: Histogram = _meter.create_histogram(
    name="worktree_fetch_duration_seconds",
    unit="s",
    description="Worktree fetch operation duration (seconds) per backend/status/principal.",
)
_worktree_lock_wait_histogram: Histogram = _meter.create_histogram(
    name="worktree_lock_wait_seconds",
    unit="s",
    description="Worktree distributed-lock acquisition wait time (seconds).",
)
_worktree_lock_held_histogram: Histogram = _meter.create_histogram(
    name="worktree_lock_held_seconds",
    unit="s",
    description="Worktree distributed-lock held time (seconds).",
)
_cache_get_histogram: Histogram = _meter.create_histogram(
    name="cache_get_duration_seconds",
    unit="s",
    description="Cache get operation duration (seconds) per backend/hit.",
)
_cache_set_histogram: Histogram = _meter.create_histogram(
    name="cache_set_duration_seconds",
    unit="s",
    description="Cache set operation duration (seconds) per backend.",
)
_bundle_bytes_histogram: Histogram = _meter.create_histogram(
    name="bundle_bytes",
    unit="By",
    description="Bundle size (bytes) per repo, with exponential buckets to 100MB.",
)

# Counters
_worktree_cache_invalidation_counter: Counter = _meter.create_counter(
    name="worktree_cache_invalidation_total",
    description="Worktree cache invalidation events per backend/reason.",
)
_cache_fallback_counter: Counter = _meter.create_counter(
    name="cache_fallback_total",
    description="Cache tier fallback events (e.g. L1 miss → L2 hit).",
)
_backend_health_check_failed_counter: Counter = _meter.create_counter(
    name="backend_health_check_failed_total",
    description="Backend health-check failures per backend.",
)
_bundle_integrity_failure_counter: Counter = _meter.create_counter(
    name="bundle_integrity_failure_total",
    description="Bundle SHA-256 integrity check failures per backend/principal.",
)
_worktree_registry_drift_counter: Counter = _meter.create_counter(
    name="worktree_registry_drift_total",
    description="Drift between S3 inventory and Dhara registry (orphans / ghosts).",
)


# ---------------------------------------------------------------------------
# Helper API — thin wrappers with label validation
# ---------------------------------------------------------------------------


def record_worktree_op(
    backend: str,
    op: str,
    duration_seconds: float,
    success: bool,
    *,
    principal: str | None = None,
) -> None:
    """Record a worktree create/fetch operation."""
    labels = {
        "backend": backend,
        "status": "ok" if success else "error",
        "principal_short": _short_principal(principal),
    }
    _validate_labels(labels)
    if op == "create":
        _worktree_create_histogram.record(duration_seconds, attributes=labels)
    elif op == "fetch":
        _worktree_fetch_histogram.record(duration_seconds, attributes=labels)
    else:
        # Forward-compat: unknown op names still validate
        _logger.debug("worktree-op-skipped-unknown-op", extra={"op": op})


def record_cache_op(
    backend: str,
    op: str,
    duration_seconds: float,
    hit: bool,
) -> None:
    """Record a cache get/set operation. Delegates to Oneiric's existing
    ``record_adapter_request_metrics`` to avoid histogram duplication."""
    # Reuse Oneiric's OTel infrastructure (already wired to exporter).
    try:
        from oneiric.adapters.metrics import record_adapter_request_metrics

        record_adapter_request_metrics(
            domain="cache",
            adapter="cache",
            provider=backend,
            operation=op,
            duration_ms=duration_seconds * 1000.0,
            success=True,
        )
    except ImportError:  # pragma: no cover - oneiric not installed in unit tests
        pass

    # Still emit our own histogram so the §17 metric surface is satisfied
    # even when oneiric is unavailable.
    if op == "get":
        labels = {"backend": backend, "hit": "true" if hit else "false"}
        _validate_labels(labels)
        _cache_get_histogram.record(duration_seconds, attributes=labels)
    elif op == "set":
        labels = {"backend": backend}
        _validate_labels(labels)
        _cache_set_histogram.record(duration_seconds, attributes=labels)


def record_cache_invalidation(backend: str, reason: str, count: int = 1) -> None:
    """Record a cache invalidation event. ``count`` defaults to 1; bulk
    invalidations (e.g. ``delete_prefix`` removing N keys) pass the
    actual count so dashboards see total invalidated-volume."""
    # Bounded allowlist for ``reason``: callers pass small literal strings
    # like "remove_handle" / "fetch_miss" — cap at 32 chars to prevent
    # caller-supplied data from spawning unbounded label series.
    bounded_reason = (reason or "unknown")[:32]
    labels = {"backend": backend, "reason": bounded_reason}
    _validate_labels(labels)
    _worktree_cache_invalidation_counter.add(count, attributes=labels)


def record_bundle_integrity_failure(
    backend: str,
    principal_short: str | None = None,
) -> None:
    """Record a bundle SHA-256 integrity check failure."""
    labels = {
        "backend": backend,
        "principal_short": _short_principal(principal_short),
    }
    _validate_labels(labels)
    _bundle_integrity_failure_counter.add(1, attributes=labels)


def record_lock_wait(
    repo: str, branch: str, wait_seconds: float, acquired: bool
) -> None:
    """Record a worktree distributed-lock acquisition wait."""
    labels = {
        "repo": _short_label(repo),
        "branch": _short_label(branch),
        "acquired": "true" if acquired else "false",
    }
    _validate_labels(labels)
    _worktree_lock_wait_histogram.record(wait_seconds, attributes=labels)


def record_lock_held(
    repo: str, branch: str, principal: str | None, held_seconds: float
) -> None:
    """Record a worktree distributed-lock held duration on release."""
    labels = {
        "repo": _short_label(repo),
        "branch": _short_label(branch),
        "principal_short": _short_principal(principal),
    }
    _validate_labels(labels)
    _worktree_lock_held_histogram.record(held_seconds, attributes=labels)


def record_registry_drift(
    *, missing_in_s3: int = 0, missing_in_dhara: int = 0
) -> None:
    """Record drift between S3 inventory and Dhara registry.

    Two label dimensions collapse into one counter via a single
    ``drift_kind`` label (``"missing_in_s3"`` or ``"missing_in_dhara"``)
    so the meter doesn't multiply cardinality by 2.
    """
    if missing_in_s3:
        labels = {"drift_kind": "missing_in_s3"}
        _validate_labels(labels)
        _worktree_registry_drift_counter.add(missing_in_s3, attributes=labels)
    if missing_in_dhara:
        labels = {"drift_kind": "missing_in_dhara"}
        _validate_labels(labels)
        _worktree_registry_drift_counter.add(missing_in_dhara, attributes=labels)


def record_cache_fallback(from_tier: str, to_tier: str) -> None:
    """Record a cache tier fallback (e.g. L1 miss → L2 hit).

    Tier labels are bounded to 8 chars (the only legal values are
    "l1", "l2", "redis", "memory", etc. — short literals).
    """
    bounded_from = (from_tier or "unknown")[:8]
    bounded_to = (to_tier or "unknown")[:8]
    labels = {"from_tier": bounded_from, "to_tier": bounded_to}
    _validate_labels(labels)
    _cache_fallback_counter.add(1, attributes=labels)


def record_backend_health_check_failed(backend: str) -> None:
    """Record a backend health-check failure."""
    labels = {"backend": backend}
    _validate_labels(labels)
    _backend_health_check_failed_counter.add(1, attributes=labels)


def record_bundle_bytes(repo: str, byte_size: int) -> None:
    """Record the size of a worktree bundle in bytes (per repo)."""
    labels = {"repo": _short_label(repo)}
    _validate_labels(labels)
    _bundle_bytes_histogram.record(byte_size, attributes=labels)


__all__ = [
    "record_backend_health_check_failed",
    "record_bundle_bytes",
    "record_bundle_integrity_failure",
    "record_cache_fallback",
    "record_cache_invalidation",
    "record_cache_op",
    "record_lock_held",
    "record_lock_wait",
    "record_registry_drift",
    "record_worktree_op",
]
