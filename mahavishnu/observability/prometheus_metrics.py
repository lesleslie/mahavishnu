"""Per-server Prometheus metrics for mahavishnu's health aggregator.

Phase 1.1 (M2 polish): registers a per-server convenience gauge
``mahavishnu_health_feed_status{feed, status}`` alongside the
canonical mcp-common ``health_feed_status{repo, feed, status}``
emitted by :mod:`mcp_common.health.metrics`. The per-server
gauge has the same data minus the ``repo`` label so dashboards
can target the mahavishnu view directly without PromQL
filtering on ``{repo="mahavishnu"}``.

The canonical mcp-common metric remains the source of truth for
the alerts in ``config/prometheus/health_aggregator_alerts.yml``;
this module only adds a server-specific view for operators
who want a flat ``mahavishnu_*`` namespace.

Design constraints (per ``.claude/decisions/mcp-backend-wiring-discipline.md``):

* The per-server registry is **private** (not the prometheus_client
  global) so multi-process / multi-registry deployments don't
  collide on the ``Duplicated timeseries in CollectorRegistry``
  error.
* The aggregator calls :func:`update_health_feed_status_metrics`
  on every ``aggregate_mahavishnu_health`` invocation; the gauge
  always reflects the latest snapshot. Each ``(feed, status)``
  pair has a single ``1`` value at any moment; the rest are
  reset to ``0`` so PromQL ``max by (feed) (mahavishnu_health_feed_status)
  == 1`` matches the current status.

The HTTP ``/metrics`` route in :mod:`mahavishnu.health` re-exposes
this registry's text-format content alongside the OTel-derived
metrics and the mcp-common ``health_feed_status`` series.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import prometheus_client

if TYPE_CHECKING:
    from mcp_common.health.aggregator import HealthSnapshot


logger = logging.getLogger(__name__)


# Per-server metrics registry. Private (not the prometheus_client
# global) to avoid ``Duplicated timeseries`` errors if the same
# metric name is registered elsewhere in the process.
_health_metrics_registry: prometheus_client.CollectorRegistry | None = None


def get_health_metrics_registry() -> prometheus_client.CollectorRegistry:
    """Return the per-server ``CollectorRegistry`` for the M2 gauge.

    Lazy-initialised on first call so the prometheus_client
    metric registration happens at first emit (avoids
    ImportError-on-import when the cluster is read-only).
    """
    global _health_metrics_registry
    if _health_metrics_registry is None:
        _health_metrics_registry = prometheus_client.CollectorRegistry()
    return _health_metrics_registry


# Module-level lazy gauge (created on first call to
# ``update_health_feed_status_metrics``; per-registry cache).
_health_feed_status_gauge: prometheus_client.Gauge | None = None


def _get_or_create_gauge(registry: prometheus_client.CollectorRegistry) -> prometheus_client.Gauge:
    """Return the cached ``mahavishnu_health_feed_status`` gauge.

    The cache is module-level because there is only one
    per-server registry; if the registry changes (e.g. tests
    resetting it), the cache is invalidated via
    :func:`reset_health_metrics_for_tests`.
    """
    global _health_feed_status_gauge
    if _health_feed_status_gauge is None:
        from prometheus_client import Gauge

        _health_feed_status_gauge = Gauge(
            "mahavishnu_health_feed_status",
            "Per-feed health verdict (1 for current status, 0 otherwise). "
            "Per-server convenience gauge; the canonical mcp-common metric "
            "is ``health_feed_status{repo, feed, status}``.",
            labelnames=("feed", "status"),
            registry=registry,
        )
    return _health_feed_status_gauge


def reset_health_metrics_for_tests() -> None:  # pragma: no cover - test seam
    """Clear the cached gauge so tests can re-initialise cleanly.

    The companion :func:`reset_health_metrics_registry_for_tests`
    also clears the registry cache (see
    :mod:`mahavishnu.core.health_aggregator` for the related
    registry).
    """
    global _health_feed_status_gauge
    _health_feed_status_gauge = None


def update_health_feed_status_metrics(
    *,
    snap: HealthSnapshot,
    registry: prometheus_client.CollectorRegistry | None = None,
) -> None:
    """Update the M2 gauge from the latest ``HealthSnapshot``.

    For each feed in ``snap["checks"]``, set the
    ``(feed, status)`` cell to ``1`` and reset the other
    ``(feed, *)`` cells to ``0``. This keeps the gauge
    semantically a "current status" indicator and lets
    PromQL queries like
    ``max by (feed) (mahavishnu_health_feed_status)`` return
    the active status.

    Args:
        snap: Canonical ``HealthSnapshot`` from
            :func:`mcp_common.health.aggregator.aggregate_feed_states`.
        registry: Optional ``CollectorRegistry`` to register the
            gauge against. Defaults to the per-server
            :func:`get_health_metrics_registry` (private).
    """
    if registry is None:
        registry = get_health_metrics_registry()
    gauge = _get_or_create_gauge(registry)

    try:
        for feed_name, feed_snapshot in snap["checks"].items():
            current_status = feed_snapshot["status"].value
            # Reset all known ``(feed, *)`` cells to 0 then set the
            # current one to 1. ``StatusValue`` is the canonical
            # source of truth (4 values: healthy / warming_up /
            # degraded / failed).
            from mcp_common.health.feed import StatusValue

            for status_value in StatusValue:
                cell = gauge.labels(feed=feed_name, status=status_value.value)
                if status_value.value == current_status:
                    cell.set(1)
                else:
                    cell.set(0)
    except Exception:
        # Per the aggregator's fail-loud contract: never raise from
        # a metrics emit; log and continue so the /health route still
        # returns a verdict even if the prometheus_client is
        # misconfigured.
        logger.exception(
            "prometheus_metrics: update_health_feed_status_metrics failed; "
            "operators will see no M2 gauge for mahavishnu until the next "
            "successful call",
        )


__all__ = [
    "get_health_metrics_registry",
    "reset_health_metrics_for_tests",
    "update_health_feed_status_metrics",
]
