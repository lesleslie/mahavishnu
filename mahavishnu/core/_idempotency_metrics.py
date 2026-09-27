"""Idempotency-layer observability counters and gauges.

Module-level Prometheus metrics for the C-6 idempotency layer. Mirrors the
producer-side pattern in ``mahavishnu/core/_producer_metrics.py``: lazy
prometheus_client import with a no-op fallback when the library is missing
(e.g. slim build). The fallback swallows ``.labels(...)`` / ``.inc(...)`` /
``.set(...)`` calls without side-effects so callers never crash on missing
metrics.

Implements: REQ-006, REQ-007, REQ-008
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge

    IDEMPOTENCY_HIT_TOTAL: Counter = Counter(
        "idempotency_hit_total",
        "Total idempotent dispatch hits (caller retry detected).",
        labelnames=["source"],
    )

    IDEMPOTENCY_MISS_TOTAL: Counter = Counter(
        "idempotency_miss_total",
        "Total idempotent dispatch misses (fresh work dispatched).",
        labelnames=["source"],
    )

    # Circuit breaker observability. The gauge is 0 when CLOSED, 1 when OPEN.
    # The counter records every state transition for retrospective analysis.
    # Operators alert on ``idempotency_circuit_state == 1 for >5m``.
    IDEMPOTENCY_CIRCUIT_STATE_GAUGE: Gauge = Gauge(
        "idempotency_circuit_state",
        "Idempotency circuit breaker state (0=CLOSED, 1=OPEN).",
    )

    IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL: Counter = Counter(
        "idempotency_circuit_transitions_total",
        "Total idempotency circuit state transitions.",
        labelnames=["transition"],  # "open" | "closed" | "half_open"
    )
except ImportError:
    # Module-level fallbacks so callers can still reference the symbols
    # even if prometheus_client is unavailable. The fallbacks swallow
    # ``.labels(...)`` / ``.inc(...)`` / ``.set(...)`` calls.

    class _NoOpMetric:
        def labels(self, **_kwargs: object) -> _NoOpMetric:
            return self

        def inc(self, *_args: object, **_kwargs: object) -> None:
            return None

        def set(self, *_args: object, **_kwargs: object) -> None:
            return None

    IDEMPOTENCY_HIT_TOTAL = _NoOpMetric()
    IDEMPOTENCY_MISS_TOTAL = _NoOpMetric()
    IDEMPOTENCY_CIRCUIT_STATE_GAUGE = _NoOpMetric()
    IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL = _NoOpMetric()


__all__ = [
    "IDEMPOTENCY_CIRCUIT_STATE_GAUGE",
    "IDEMPOTENCY_CIRCUIT_TRANSITIONS_TOTAL",
    "IDEMPOTENCY_HIT_TOTAL",
    "IDEMPOTENCY_MISS_TOTAL",
]
