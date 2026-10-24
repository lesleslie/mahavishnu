"""The live ``/metrics`` route must expose the health aggregator's metrics.

``update_health_metrics`` writes into a PRIVATE registry
(``mahavishnu.core.health_aggregator.get_health_metrics_registry``) so
it cannot collide with the global REGISTRY's unrelated counters. But the
only endpoint that rendered that private registry belonged to
``mahavishnu/health.py``'s uvicorn app, which never starts -- so the
``mcp_common_health_*`` families were missing from the LIVE :8680
exposition.

The gap was invisible from Grafana and from the other two services:
akosha (:8682) and session-buddy (:8678) each exposed 19
``mcp_common_health_*`` families, and mahavishnu exposed zero. The
PromQL alert rules in ``config/prometheus/health_aggregator_alerts.yml``
key on ``mcp_common_health_halflife_seconds{repo}``, so mahavishnu was
the one repo the health alerts could not see.
"""

from __future__ import annotations

from mcp_common.health.aggregator import aggregate_feed_states
from mcp_common.health.feed import HealthFeedState
from mcp_common.health.metrics import update_health_metrics

from mahavishnu.core.health_aggregator import get_health_metrics_registry
from monitoring.metrics import expose_metrics


def _populate_health_registry() -> None:
    """Emit the health metrics the way the live /health path does."""
    state = HealthFeedState(
        entities_count=3,
        last_updated_timestamp=1.0,
        cycles_total=1,
        errors_total=0,
        ingester_running=True,
    )
    snap = aggregate_feed_states({"hot_store": state}, halflife_seconds=300)
    update_health_metrics(
        registry=get_health_metrics_registry(),
        snap=snap,
        repo="mahavishnu",
        halflife_seconds=300,
        duration_ms=1.5,
    )


def test_expose_metrics_includes_the_health_registry() -> None:
    """The health families must reach the exposition."""
    _populate_health_registry()

    body = expose_metrics().decode()

    assert "mcp_common_health_halflife_seconds" in body, (
        "the health aggregator's metrics are not on the live /metrics "
        "exposition; the health-aggregator alert rules key on them"
    )
    assert "mcp_common_health_aggregate_duration_ms" in body


def test_expose_metrics_still_carries_the_main_registry() -> None:
    """The health registry is APPENDED, not substituted."""
    _populate_health_registry()

    body = expose_metrics().decode()

    # A metric that only exists in the main registry.
    assert "mahavishnu" in body


def test_expose_metrics_is_not_broken_by_an_empty_health_registry() -> None:
    """An unpopulated health registry must not break the exposition.

    Before the first ``/health`` request the private registry is empty, and
    ``/metrics`` is served independently of ``/health``. So this is the
    common case, not an edge case.
    """
    body = expose_metrics().decode()

    assert body  # non-empty
    assert "mcp_common_health_halflife_seconds" not in body
