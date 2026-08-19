"""Capability transition observability."""

from __future__ import annotations

import asyncio

from oneiric.core.logging import get_logger
from prometheus_client import Counter, Histogram

from ._safe import safe_error_for_user
from ._states import WorkerCapabilityReport, WorkerCapabilityState

logger = get_logger(__name__)

# Resolve the websocket broadcast helper at import time so wiring bugs surface.
# Unit tests that don't need websocket broadcasting can monkeypatch
# `_broadcast_event` to a mock (or set it to None) before calling _publish_event.
_broadcast_event = None
try:
    from ...websocket.server import broadcast_event as _broadcast_event
except ImportError:
    logger.warning(
        "websocket_broadcast_unavailable",
        extra={
            "component": "mahavishnu.websocket.server",
            "reason": (
                "broadcast_event could not be imported; capability transitions "
                "will not be broadcast to the adapters room"
            ),
        },
    )


_TRANSITIONS = Counter(
    "mahavishnu_worker_capability_transitions_total",
    "Worker capability state transitions",
    ("worker_type", "from_state", "to_state"),
)
_PROBE_DURATION = Histogram(
    "mahavishnu_worker_capability_probe_duration_seconds",
    "Worker capability probe duration",
    ("worker_type", "check_kind", "result"),
)
_CACHE_TOTAL = Counter(
    "mahavishnu_worker_capability_cache_total",
    "Worker capability cache hits and misses",
    ("worker_type", "result"),
)

_last_state: dict[str, WorkerCapabilityState] = {}


def emit_transition(report: WorkerCapabilityReport) -> None:
    previous = _last_state.get(report.worker_type)
    if previous is report.state:
        return
    _TRANSITIONS.labels(report.worker_type, str(previous), str(report.state)).inc()
    _last_state[report.worker_type] = report.state
    logger.info(
        "worker_capability_transition",
        extra={
            "worker_type": report.worker_type,
            "from_state": str(previous),
            "to_state": str(report.state),
        },
    )
    _publish_event(report)


def record_probe(worker_type: str, kind: str, duration: float, result: str) -> None:
    _PROBE_DURATION.labels(worker_type, kind, result).observe(duration)


def record_probe_failure(report: WorkerCapabilityReport, kind: str, reason: str) -> None:
    logger.warning(
        "worker_capability_probe_failed",
        extra={
            "worker_type": report.worker_type,
            "check_kind": kind,
            "safe_reason": safe_error_for_user(reason),
        },
    )


def record_cache(worker_type: str, result: str) -> None:
    _CACHE_TOTAL.labels(worker_type, result).inc()


def _bucket(report: WorkerCapabilityReport) -> str:
    """Coarse reason bucket for safe broadcast over the global adapters room.

    Maps the report's state plus missing_requirements plus check results into
    a single string that is safe to broadcast to every subscriber. Subscribers
    learn only the high-level readiness reason; never the specific env-var
    name, tool name, or config key that is missing.

    Buckets:
        ready                 - worker is fully usable
        missing_tool          - a required CLI binary is absent
        missing_settings      - a required settings key is missing
        missing_credentials   - an env-var credential is missing
        service_unreachable   - a live probe failed against the upstream
        unknown               - worker type is not registered
    """
    state = report.state
    missing = list(report.missing_requirements or [])
    has_failed_check = any(check.status == "fail" for check in report.checks)
    if state is WorkerCapabilityState.READY:
        return "ready"
    if state is WorkerCapabilityState.CONFIGURED:
        if any("tool:" in m for m in missing):
            return "missing_tool"
        if any("setting:" in m for m in missing):
            return "missing_settings"
        return "missing_credentials"
    if state is WorkerCapabilityState.AVAILABLE:
        if has_failed_check:
            return "service_unreachable"
        return "ready"
    return "unknown"


def _publish_event(report: WorkerCapabilityReport) -> None:
    """Publish a coarsened payload to the adapters websocket room.

    The payload intentionally omits ``safe_reason`` and
    ``missing_requirements`` so that subscribers do not learn which
    third-party services the operator configures. Every string field still
    passes through ``safe_error_for_user`` as defense in depth.
    """
    if _broadcast_event is None:
        return
    payload = {
        "worker_type": safe_error_for_user(report.worker_type),
        "state": safe_error_for_user(str(report.state.value)),
        "reason_bucket": safe_error_for_user(_bucket(report)),
        "probe_at": safe_error_for_user(report.probe_at.isoformat()),
    }
    # ``_publish_event`` is synchronous; the websocket broadcast may be async
    # (production) or sync (tests that monkeypatch a synchronous stub). Detect
    # the result shape before scheduling so tests with sync stubs do not trip
    # on ``coro.close()`` against a ``None`` return value.
    result = _broadcast_event("worker.availability_changed", payload, room="adapters")
    if not asyncio.iscoroutine(result):
        return
    # Async path: schedule the coroutine on the running loop so we never block
    # capability evaluation on a websocket round-trip. When no loop is running
    # (sync context, no event loop available), close the coroutine cleanly.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(result)
    except RuntimeError:
        result.close()


def reset_for_tests() -> None:
    _last_state.clear()
