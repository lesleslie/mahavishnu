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

Design constraints (per ``docs/decisions/mcp-backend-wiring-discipline.md``):

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
    "bifrost_dispatch_failures_total",
    "bifrost_dispatch_latency_seconds",
    "bifrost_dispatch_total",
    "bifrost_local_dispatch_total",
    "get_health_metrics_registry",
    "reset_health_metrics_for_tests",
    "update_health_feed_status_metrics",
]


# ============================================================================
# Bifrost dispatch metrics — Phase A (master counters) + Phase G (local)
# ----------------------------------------------------------------------------
# Phase A (v1.5 Bifrost spec §5.5) registers three bifrost-wide series
# (master counter, latency histogram, failures counter). Phase G
# (REQ-007) adds the local-dispatch counter that the
# ``_bifrost_dispatch_heartbeat`` wrapper in
# ``mahavishnu/engines/agno_adapter_impl.py`` increments on local-target
# dispatches. All four series register against the per-server
# ``CollectorRegistry`` (the discipline from
# ``docs/decisions/mcp-backend-wiring-discipline.md``: no allowlist
# gate, the per-server registry is the registration surface).
#
# Label set bound (per the v1.5 amendment): {outcome, provider,
# route_class, reason, model} — 5 total. The local counter uses
# {outcome, provider, route_class} (3 labels) to match the master
# counter's shape for dashboard tier uniformity.
# ============================================================================

# Per-bifrost metrics registry. Distinct from the per-server M2 gauge
# registry (above) so the two metric families don't collide on the
# ``Duplicated timeseries in CollectorRegistry`` error. Lazy-initialised
# on first call to keep import-time work bounded.
_bifrost_metrics_registry: prometheus_client.CollectorRegistry | None = None


def get_bifrost_metrics_registry() -> prometheus_client.CollectorRegistry:
    """Return the per-server ``CollectorRegistry`` for the bifrost counters.

    Lazy-initialised on first call so the prometheus_client
    metric registration happens at first emit (avoids
    ImportError-on-import when the cluster is read-only).
    """
    global _bifrost_metrics_registry
    if _bifrost_metrics_registry is None:
        _bifrost_metrics_registry = prometheus_client.CollectorRegistry()
    return _bifrost_metrics_registry


# Module-level lazy counters. The cache is module-level; tests
# invalidate via ``reset_bifrost_metrics_for_tests``.
_bifrost_dispatch_total: prometheus_client.Counter | None = None
_bifrost_dispatch_latency_seconds: prometheus_client.Histogram | None = None
_bifrost_dispatch_failures_total: prometheus_client.Counter | None = None
_bifrost_local_dispatch_total: prometheus_client.Counter | None = None


def _get_or_create_bifrost_counter(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...],
    registry: prometheus_client.CollectorRegistry,
) -> prometheus_client.Counter:
    """Return the cached counter for ``name``, creating it on first call."""
    if name == "mahavishnu_bifrost_dispatch_total":
        global _bifrost_dispatch_total
        if _bifrost_dispatch_total is None:
            _bifrost_dispatch_total = prometheus_client.Counter(
                name,
                documentation,
                labelnames=labelnames,
                registry=registry,
            )
        return _bifrost_dispatch_total
    if name == "mahavishnu_bifrost_dispatch_failures_total":
        global _bifrost_dispatch_failures_total
        if _bifrost_dispatch_failures_total is None:
            _bifrost_dispatch_failures_total = prometheus_client.Counter(
                name,
                documentation,
                labelnames=labelnames,
                registry=registry,
            )
        return _bifrost_dispatch_failures_total
    if name == "mahavishnu_bifrost_local_dispatch_total":
        global _bifrost_local_dispatch_total
        if _bifrost_local_dispatch_total is None:
            _bifrost_local_dispatch_total = prometheus_client.Counter(
                name,
                documentation,
                labelnames=labelnames,
                registry=registry,
            )
        return _bifrost_local_dispatch_total
    raise ValueError(f"unknown bifrost counter name: {name!r}")


def _get_or_create_bifrost_histogram(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...],
    registry: prometheus_client.CollectorRegistry,
) -> prometheus_client.Histogram:
    """Return the cached histogram for ``name``, creating it on first call."""
    global _bifrost_dispatch_latency_seconds
    if _bifrost_dispatch_latency_seconds is None:
        _bifrost_dispatch_latency_seconds = prometheus_client.Histogram(
            name,
            documentation,
            labelnames=labelnames,
            registry=registry,
        )
    return _bifrost_dispatch_latency_seconds


def reset_bifrost_metrics_for_tests() -> None:  # pragma: no cover - test seam
    """Clear the cached bifrost counters so tests can re-initialise cleanly."""
    global _bifrost_dispatch_total, _bifrost_dispatch_latency_seconds
    global _bifrost_dispatch_failures_total, _bifrost_local_dispatch_total
    _bifrost_dispatch_total = None
    _bifrost_dispatch_latency_seconds = None
    _bifrost_dispatch_failures_total = None
    _bifrost_local_dispatch_total = None


def reset_bifrost_metrics_registry_for_tests() -> None:  # pragma: no cover - test seam
    """Drop the cached per-server ``CollectorRegistry`` so the next
    emit creates a fresh one.

    :func:`reset_bifrost_metrics_for_tests` only clears the
    module-level counter cache. The registry itself (a singleton
    ``_bifrost_metrics_registry``) holds the previously-registered
    Counter instances; re-registering a Counter with the same name
    on the same registry raises ``prometheus_client.registry.
    DuplicateTimeseries``. Tests that exercise multiple counter
    emits in sequence (e.g. ``test_heartbeat_increments_master_counter``
    then ``test_heartbeat_failure_path_increments_failures_counter``)
    need a fresh registry between tests so each one starts clean.

    Mirrors :func:`mahavishnu.core.health_aggregator.
    reset_health_metrics_registry_for_tests`, the established
    registry-reset pattern for the M2 health gauges.
    """
    global _bifrost_metrics_registry
    _bifrost_metrics_registry = None


def bifrost_dispatch_total(*, outcome: str, provider: str, route_class: str) -> None:
    """Increment the master bifrost dispatch counter.

    Phase A (v1.5 Bifrost spec §5.5). Called from the
    ``_bifrost_dispatch_heartbeat`` wrapper in
    ``mahavishnu/engines/agno_adapter_impl.py`` on every Bifrost
    dispatch (both success and failure paths).
    """
    registry = get_bifrost_metrics_registry()
    counter = _get_or_create_bifrost_counter(
        "mahavishnu_bifrost_dispatch_total",
        "Bifrost dispatch total (Phase A master counter; outcome / provider / route_class).",
        ("outcome", "provider", "route_class"),
        registry,
    )
    counter.labels(outcome=outcome, provider=provider, route_class=route_class).inc()


def bifrost_dispatch_latency_seconds(*, provider: str, route_class: str, seconds: float) -> None:
    """Record a Bifrost dispatch latency sample.

    Phase A (v1.5 Bifrost spec §5.5). Default buckets match the
    mcp-common convention (5ms-10s) — same shape as the per-server
    M2 latency histogram. Buckets are bounded to 11 entries to
    keep the per-server time series count under the 200/metric
    ceiling.
    """
    registry = get_bifrost_metrics_registry()
    histogram = _get_or_create_bifrost_histogram(
        "mahavishnu_bifrost_dispatch_latency_seconds",
        "Bifrost dispatch latency in seconds (Phase A; provider / route_class).",
        ("provider", "route_class"),
        registry,
    )
    histogram.labels(provider=provider, route_class=route_class).observe(seconds)


def bifrost_dispatch_failures_total(*, provider: str, reason: str) -> None:
    """Increment the Bifrost dispatch failures counter.

    Phase A (v1.5 Bifrost spec §5.5). ``reason`` is one of:
    ``"timeout"``, ``"http_error"``, ``"bifrost_unreachable"``,
    ``"auth_error"``, ``"other"``. The counter is used by the
    ``MahavishnuBifrostErrorRateHigh`` alert rule in
    ``config/prometheus/bifrost_alerts.yml``.
    """
    registry = get_bifrost_metrics_registry()
    counter = _get_or_create_bifrost_counter(
        "mahavishnu_bifrost_dispatch_failures_total",
        "Bifrost dispatch failures total (Phase A; provider / reason).",
        ("provider", "reason"),
        registry,
    )
    counter.labels(provider=provider, reason=reason).inc()


def bifrost_local_dispatch_total(*, outcome: str, provider: str, route_class: str) -> None:
    """Increment the local-target Bifrost dispatch counter.

    Phase G (REQ-007). Called from the
    ``_bifrost_dispatch_heartbeat`` wrapper in
    ``mahavishnu/engines/agno_adapter_impl.py`` when the
    dispatch's resolved base_url matches
    ``settings.bifrost.local_provider_url`` (i.e. the
    llama-server target). The label set is normalized to match
    the master counter (``outcome, provider, route_class``) so
    dashboards and alert rules can group by either counter
    interchangeably. The local counter is registered even when
    ``bifrost.local_provider_enabled: false`` (so dashboards
    don't 404); it is simply not incremented in that case.
    """
    registry = get_bifrost_metrics_registry()
    counter = _get_or_create_bifrost_counter(
        "mahavishnu_bifrost_local_dispatch_total",
        "Bifrost local-target dispatch total (Phase G; outcome / provider / route_class).",
        ("outcome", "provider", "route_class"),
        registry,
    )
    counter.labels(outcome=outcome, provider=provider, route_class=route_class).inc()
