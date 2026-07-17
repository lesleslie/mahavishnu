"""Unit tests for ``mahavishnu.core.dlq_metrics``.

Verifies the three fixed outcomes of ``mahavishnu_dlq_fallback_total``
increment correctly. The no-op fallback path is exercised automatically
when ``prometheus_client`` is not installed.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core import dlq_metrics

if TYPE_CHECKING:
    from mahavishnu.core.dlq_metrics import DLQMetrics

pytestmark = pytest.mark.asyncio


@pytest.fixture
def metrics() -> DLQMetrics:
    """Module-level singleton (Counter registration is global)."""
    return dlq_metrics.get_dlq_metrics()  # type: ignore[return-value]


def _prometheus_installed() -> bool:
    return importlib.util.find_spec("prometheus_client") is not None


async def test_record_persisted_does_not_raise(metrics: DLQMetrics) -> None:
    """Each record_* method must be a callable increment even under no-op."""
    metrics.record_persisted()  # no-op if prometheus_client missing
    metrics.record_persisted()


async def test_record_in_memory_fallback_does_not_raise(metrics: DLQMetrics) -> None:
    metrics.record_in_memory_fallback()
    metrics.record_in_memory_fallback()
    metrics.record_in_memory_fallback()


async def test_record_rejected_does_not_raise(metrics: DLQMetrics) -> None:
    metrics.record_rejected()


async def test_get_dlq_metrics_returns_singleton() -> None:
    """The getter is a lazy singleton — two calls return the same instance."""
    a = dlq_metrics.get_dlq_metrics()
    b = dlq_metrics.get_dlq_metrics()
    assert a is b


@pytest.mark.skipif(
    not _prometheus_installed(),
    reason="prometheus_client not installed — counter value check is a no-op",
)
async def test_persisted_counter_increments(metrics: DLQMetrics) -> None:
    """When prometheus_client is available, record_persisted() increments
    the persisted-label counter. This is the only place the test actually
    asserts a numeric value (vs. no-op smoke checks).

    Note on prometheus_client's API: ``Counter._value`` is not on the
    Counter itself — it lives on each label child. To read the current
    value for a label combination, use
    ``counter.labels(outcome="persisted")._value.get()``.
    """
    counter = metrics.dlq_fallback_total
    persisted = counter.labels(outcome="persisted")
    in_memory = counter.labels(outcome="in_memory")
    rejected = counter.labels(outcome="rejected")

    # Capture starting state for the three labels.
    before_p = persisted._value.get()  # type: ignore[attr-defined]
    before_m = in_memory._value.get()  # type: ignore[attr-defined]
    before_r = rejected._value.get()  # type: ignore[attr-defined]

    metrics.record_persisted()
    assert persisted._value.get() == before_p + 1  # type: ignore[attr-defined]
    # The other two labels are untouched.
    assert in_memory._value.get() == before_m  # type: ignore[attr-defined]
    assert rejected._value.get() == before_r  # type: ignore[attr-defined]

    metrics.record_in_memory_fallback()
    assert in_memory._value.get() == before_m + 1  # type: ignore[attr-defined]
    assert persisted._value.get() == before_p + 1  # type: ignore[attr-defined]

    metrics.record_rejected()
    assert rejected._value.get() == before_r + 1  # type: ignore[attr-defined]
    assert persisted._value.get() == before_p + 1  # type: ignore[attr-defined]
    assert in_memory._value.get() == before_m + 1  # type: ignore[attr-defined]
