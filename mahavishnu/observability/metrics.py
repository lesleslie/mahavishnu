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

from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
import logging
from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import (  # noqa: TC002 — Counter/Histogram used as module-level variable annotations (deferred by __future__ annotations) + as counter_fn/counter_holder factories
    Counter,
    Histogram,
)

logger = logging.getLogger(__name__)


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
        # Phase 3 PR-C — streaming_op_duration_seconds{op,backend}
        # and streaming_op_total{op,backend,success}.
        "op",
        "success",
    }
)


def _validate_labels(labels: Mapping[str, object]) -> None:
    """Reject unknown label keys to prevent OTel cardinality explosion.

    ``Mapping[str, object]`` is covariant on the value type, so callers
    passing ``dict[str, str]`` (the common case for metric labels)
    satisfy the bound without an explicit ``cast``.
    """
    unknown = set(labels) - _ALLOWED_LABEL_KEYS
    if unknown:
        raise ValueError(
            f"Unknown metric label keys: {sorted(unknown)}. Allowed: {sorted(_ALLOWED_LABEL_KEYS)}"
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
    description=(
        "Bundle size (bytes) per repo. Phase 3 PR-C (B-DI-05) extended "
        "buckets up to 1 GB so streaming-enabled size classes get "
        "dedicated percentiles."
    ),
    explicit_bucket_boundaries_advisory=[
        1024,  # 1 KB
        10240,  # 10 KB
        102400,  # 100 KB
        1048576,  # 1 MB
        10485760,  # 10 MB
        52428800,  # 50 MB
        104857600,  # 100 MB
        134217728,  # 128 MB (Phase 3 — streaming midpoint)
        209715200,  # 200 MB
        524288000,  # 500 MB
        1073741824,  # 1 GB
    ],
)

# Streaming op histogram (Phase 3 PR-C) — duration per op/backend.
_streaming_op_histogram: Histogram = _meter.create_histogram(
    name="streaming_op_duration_seconds",
    unit="s",
    description=(
        "Streaming tar.zst pipeline op duration (seconds) per op/backend. "
        "Phase 3 PR-C: covers SERIALIZE / DESERIALIZE / COMPRESS / "
        "DECOMPRESS / HASH / UPLOAD / DOWNLOAD ops from the streaming "
        "bundle lifecycle (ADR 015 v4)."
    ),
    explicit_bucket_boundaries_advisory=[
        0.001,  # 1 ms
        0.005,  # 5 ms
        0.01,  # 10 ms
        0.05,  # 50 ms
        0.1,  # 100 ms
        0.5,  # 500 ms
        1.0,  # 1 s
        5.0,  # 5 s
        30.0,  # 30 s
        120.0,  # 2 min
    ],
)

# Streaming op counter (Phase 3 PR-C) — total ops per op/backend/success.
_streaming_op_counter: Counter = _meter.create_counter(
    name="streaming_op_total",
    description=(
        "Streaming tar.zst pipeline op counter per op/backend/success. "
        "Tracks both completed and failed streaming ops so dashboards "
        "can compute success ratios per op kind."
    ),
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


# Phase 3 op enum (added with streaming tar support):
#   SERIALIZE, DESERIALIZE, COMPRESS, DECOMPRESS, HASH, UPLOAD, DOWNLOAD
# Phase 2 ops preserved: lock, unlock, health
# Phase 3 PR-C sub-ops (create, create_stopgap, create_s3_multipart_aborted,
#   create_codec_unavailable, fetch, fetch_legacy_guard_hit,
#   fetch_sha_mismatch, remove_handle, invalidate_handle) documented for
#   dashboard operators.


class StreamingOp(StrEnum):
    """Phase 3 streaming tar.zst pipeline operations.

    Used by ``record_streaming_op`` to emit the
    ``streaming_op_duration_seconds{op,backend}`` histogram and
    ``streaming_op_total{op,backend,success}`` counter pair. Each
    value is bounded to 16 chars to prevent caller-supplied data from
    spawning unbounded label series on the ``op`` label.

    The string values are intentionally short and stable so dashboard
    queries can reference them without translation tables.
    """

    SERIALIZE = "serialize"
    DESERIALIZE = "deserialize"
    COMPRESS = "compress"
    DECOMPRESS = "decompress"
    HASH = "hash"
    UPLOAD = "upload"
    DOWNLOAD = "download"


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
        logger.debug("worktree-op-skipped-unknown-op", extra={"op": op})


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


def record_lock_wait(repo: str, branch: str, wait_seconds: float, acquired: bool) -> None:
    """Record a worktree distributed-lock acquisition wait."""
    labels = {
        "repo": _short_label(repo),
        "branch": _short_label(branch),
        "acquired": "true" if acquired else "false",
    }
    _validate_labels(labels)
    _worktree_lock_wait_histogram.record(wait_seconds, attributes=labels)


def record_lock_held(repo: str, branch: str, principal: str | None, held_seconds: float) -> None:
    """Record a worktree distributed-lock held duration on release."""
    labels = {
        "repo": _short_label(repo),
        "branch": _short_label(branch),
        "principal_short": _short_principal(principal),
    }
    _validate_labels(labels)
    _worktree_lock_held_histogram.record(held_seconds, attributes=labels)


def record_registry_drift(*, missing_in_s3: int = 0, missing_in_dhara: int = 0) -> None:
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


def record_streaming_op(
    op: StreamingOp,
    backend: str,
    duration_ms: float,
    bytes_processed: int,
    *,
    success: bool,
) -> None:
    """Record a streaming tar.zst pipeline op (Phase 3 PR-C).

    Emits two instruments:

    - ``streaming_op_duration_seconds{op,backend}`` histogram with
      ``duration_ms / 1000`` (seconds).
    - ``streaming_op_total{op,backend,success}`` counter, incremented
      by 1.

    ``op`` is constrained to the :class:`StreamingOp` enum (7 values,
    all <=10 chars) so the ``op`` label set is bounded. ``backend``
    is not validated against ``ALLOWED_BACKEND_KINDS`` here because
    the streaming path emits under the same ``backend`` label as
    Phase 1/2 helpers; we rely on ``_validate_labels`` (which only
    checks key names) for cardinality protection. Unknown ``backend``
    values still emit — typos surface as dashboard anomalies rather
    than hard failures, matching the Phase 1/2 helper pattern.

    ``bytes_processed`` is currently informational (recorded in the
    call site's audit log, not in OTel) and is preserved on the
    signature so callers don't need a separate histogram-emit for
    bundle-bytes-per-op. Phase 4 may promote it to its own histogram
    if dashboards start asking for bytes/op distributions.
    """
    op_value = op.value if isinstance(op, StreamingOp) else str(op)
    duration_seconds = duration_ms / 1000.0

    # Histogram — duration
    duration_labels = {"op": op_value, "backend": backend}
    _validate_labels(duration_labels)
    _streaming_op_histogram.record(duration_seconds, attributes=duration_labels)

    # Counter — total ops
    success_label = "true" if success else "false"
    counter_labels = {
        "op": op_value,
        "backend": backend,
        "success": success_label,
    }
    _validate_labels(counter_labels)
    _streaming_op_counter.add(1, attributes=counter_labels)


__all__ = [
    "StreamingOp",
    "record_backend_health_check_failed",
    "record_bundle_bytes",
    "record_bundle_integrity_failure",
    "record_cache_fallback",
    "record_cache_invalidation",
    "record_cache_op",
    "record_lock_held",
    "record_lock_wait",
    "record_registry_drift",
    "record_streaming_op",
    "record_worktree_op",
]
