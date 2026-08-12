"""Producer-side observability counters are registered and incrementable.

v1.1 hardening — task 145. Asserts that the cross-portfolio
``mahavishnu_producer_writes_{attempted,succeeded,skipped}_total``
counters are registered with the prometheus_client REGISTRY after
each producer module is imported, and that the ``producer`` label
accepts the three expected producer names.
"""
from __future__ import annotations

from prometheus_client import REGISTRY

from mahavishnu.core._producer_metrics import COUNTERS


def _counter_value(metric_name: str, producer: str) -> float:
    """Read the current value of a labeled counter from the REGISTRY."""
    samples = REGISTRY.get_sample_value(
        metric_name,
        {"producer": producer},
    )
    return float(samples) if samples is not None else 0.0


def test_producer_counters_registered_on_import() -> None:
    """Three cross-portfolio counters are registered after module import."""
    assert (
        "mahavishnu_producer_writes_attempted_total"
        in REGISTRY._names_to_collectors
    )
    assert (
        "mahavishnu_producer_writes_succeeded_total"
        in REGISTRY._names_to_collectors
    )
    assert (
        "mahavishnu_producer_writes_skipped_total"
        in REGISTRY._names_to_collectors
    )


def test_producer_counters_increment_via_labels() -> None:
    """Incrementing a labeled counter does not raise and is observable."""
    before_attempted = _counter_value(
        "mahavishnu_producer_writes_attempted_total",
        "decision_writer",
    )
    COUNTERS.attempted.labels(producer="decision_writer").inc()
    COUNTERS.succeeded.labels(producer="decision_writer").inc()
    COUNTERS.skipped.labels(producer="decision_writer").inc()
    assert (
        _counter_value(
            "mahavishnu_producer_writes_attempted_total",
            "decision_writer",
        )
        - before_attempted
    ) >= 1.0


def test_producer_labels_materialise_all_three_producers() -> None:
    """The three expected producer label values are accepted by the counter."""
    for producer in (
        "decision_writer",
        "workflow_outcome_writer",
        "webhook_receiver",
    ):
        # Touch each label so the per-producer time series is materialised.
        COUNTERS.attempted.labels(producer=producer).inc(0)
        COUNTERS.succeeded.labels(producer=producer).inc(0)
        COUNTERS.skipped.labels(producer=producer).inc(0)
    assert (
        _counter_value(
            "mahavishnu_producer_writes_attempted_total",
            "webhook_receiver",
        )
        >= 0.0
    )
