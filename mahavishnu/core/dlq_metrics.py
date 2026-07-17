"""Prometheus metrics for the Dead Letter Queue.

Mirrors the pattern in ``mahavishnu.core.task_metrics``:

- Lazy import of ``prometheus_client``; no-op fallback when the library
  is unavailable so the rest of the codebase is not coupled to it.
- Singleton getter (``get_dlq_metrics``) for module-level access.
- Per-operation ``record_*`` methods that increment a single counter
  with fixed-enum labels (no unbounded cardinality).

Metrics exposed:
    mahavishnu_dlq_fallback_total{outcome=persisted|in_memory|rejected}

The counter is the single source of truth for "DLQ is OK" vs
"DLQ is silently dropping" — see
``docs/runbooks/dead-letter-queue.md`` for the operational procedure.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Lazy initialization flag
_metrics_initialized = False
_metrics_lock = threading.Lock()

# Global metrics instance (lazy singleton)
_dlq_metrics: DLQMetrics | None = None


def _ensure_prometheus_available() -> bool:
    """Check if prometheus_client is available."""
    try:
        import prometheus_client  # noqa: F401

        return True
    except ImportError:
        return False


class DLQMetrics:
    """Prometheus metrics for Dead Letter Queue operations.

    Metrics Categories:
        - mahavishnu_dlq_fallback_total: Counter of DLQ enqueue outcomes
          (persisted, in_memory, or rejected). The ``in_memory`` and
          ``rejected`` outcomes are the ones operators care about.

    Example:
        >>> metrics = get_dlq_metrics()
        >>> metrics.record_persisted()
        >>> metrics.record_in_memory_fallback()
    """

    def __init__(self) -> None:
        """Initialize DLQ metrics."""
        self._prometheus_available = _ensure_prometheus_available()

        if self._prometheus_available:
            self._init_prometheus_metrics()
        else:
            logger.warning(
                "prometheus_client not available. DLQ metrics will be no-ops. "
                "Install with: pip install prometheus-client"
            )
            self._init_noop_metrics()

        logger.debug("DLQMetrics initialized")

    def _init_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        from prometheus_client import Counter

        # Single counter, three fixed outcomes. Bounded cardinality —
        # never add a label sourced from a task_id or other user input.
        self.dlq_fallback_total = Counter(
            "mahavishnu_dlq_fallback_total",
            "Total count of DLQ enqueue outcomes",
            ["outcome"],  # persisted | in_memory | rejected
        )

    def _init_noop_metrics(self) -> None:
        """Initialize no-op metrics for when Prometheus is not available."""

        class NoOpMetric:
            """No-op metric that does nothing."""

            def labels(self, *args: Any, **kwargs: Any) -> NoOpMetric:  # type: ignore[name-defined]
                return self

            def inc(self, *args: Any, **kwargs: Any) -> None:
                pass

        noop = NoOpMetric()
        self.dlq_fallback_total = noop

    # ---------------------------------------------------------------------------
    # Recording methods (one per fixed outcome).
    # ---------------------------------------------------------------------------

    def record_persisted(self) -> None:
        """Task successfully written to OpenSearch."""
        self.dlq_fallback_total.labels(outcome="persisted").inc()

    def record_in_memory_fallback(self) -> None:
        """Task dropped into the in-memory fallback (legacy silent path or
        ``_assert_opensearch_or_fail_closed`` short-circuit when flag is on
        but OpenSearch is unavailable). The metric label is the same on
        both paths — operators only care that a fallback occurred.
        """
        self.dlq_fallback_total.labels(outcome="in_memory").inc()

    def record_rejected(self) -> None:
        """Task refused because fail-closed is on and the write could not
        be confirmed in OpenSearch.
        """
        self.dlq_fallback_total.labels(outcome="rejected").inc()


def get_dlq_metrics() -> DLQMetrics:
    """Get the global DLQMetrics singleton (lazy-initialized)."""
    global _dlq_metrics, _metrics_initialized
    with _metrics_lock:
        if _dlq_metrics is None:
            _dlq_metrics = DLQMetrics()
            _metrics_initialized = True
    return _dlq_metrics
