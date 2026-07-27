"""Tests for mahavishnu.observability.worker_metrics.WorkerMetrics.

Spec §14 success-criteria metrics:
- per-tool call counts (drives the Crackerjack quality dashboard)
- attach_event count (when worker_revoke includes attach_command)
- pool_share approximations (pool_route_execute vs terminal_launch)

The metrics class uses ``threading.Lock``; a concurrent-thread test
exercises that contract.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from mahavishnu.observability.worker_metrics import WorkerMetrics

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture
def metrics() -> Iterator[WorkerMetrics]:
    m = WorkerMetrics()
    yield m


def test_metrics_increment_per_tool(metrics: WorkerMetrics) -> None:
    metrics.record("launch_worker")
    metrics.record("launch_worker")
    metrics.record("worker_status")
    snapshot = metrics.snapshot()
    assert snapshot["launch_worker"] == 2
    assert snapshot["worker_status"] == 1
    assert snapshot["total"] == 3


def test_metrics_attach_command_attach_count(metrics: WorkerMetrics) -> None:
    metrics.record("worker_revoke")
    metrics.record_attach()
    metrics.record_attach()
    snapshot = metrics.snapshot()
    assert snapshot["attach_events"] == 2


def test_metrics_pool_share_exposes_ratio(metrics: WorkerMetrics) -> None:
    """pool_share ratio = pool_calls / (pool_calls + terminal_calls)."""
    metrics.record_pool_share(pool_calls=9, terminal_calls=1)
    snapshot = metrics.snapshot()
    assert snapshot["pool_share_numerator"] == 9
    assert snapshot["pool_share_denominator"] == 10
    assert snapshot["pool_share_ratio"] == 0.9  # §14 target ≥0.45


def test_metrics_thread_safe_under_concurrent_records() -> None:
    """100 threads each calling record() 10 times must yield 1000 total."""
    m = WorkerMetrics()

    def hammer() -> None:
        for _ in range(10):
            m.record("hammer")

    with ThreadPoolExecutor(max_workers=100) as pool:
        list(pool.map(lambda _: hammer(), range(100)))

    snapshot = m.snapshot()
    assert snapshot["hammer"] == 1000
    assert snapshot["total"] == 1000
