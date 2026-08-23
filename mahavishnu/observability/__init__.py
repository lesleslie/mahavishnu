"""Mahavishnu observability — worktree storage layer (ADR 015 v4 §17).

Public re-exports for the worktree storage metrics + bundle integrity
helpers. Imported by ``LocalWorktreeProvider`` / ``RemoteWorktreeProvider``
to emit the §17 OTel surface.
"""

from __future__ import annotations

from mahavishnu.observability.bundle_integrity import (
    ALLOWED_BACKEND_KINDS,
    compute_sha256,
    verify_sha256,
)
from mahavishnu.observability.metrics import (
    record_backend_health_check_failed,
    record_bundle_bytes,
    record_bundle_integrity_failure,
    record_cache_fallback,
    record_cache_invalidation,
    record_cache_op,
    record_lock_held,
    record_lock_wait,
    record_registry_drift,
    record_worktree_op,
)

__all__ = [
    "ALLOWED_BACKEND_KINDS",
    "compute_sha256",
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
    "verify_sha256",
]
