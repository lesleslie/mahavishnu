"""Unit tests for ``mahavishnu.pools.pi_observability`` emission.

Each test installs a private ``MeterProvider`` with an
``InMemoryMetricReader`` (session-scoped — OTel rejects provider swaps
within a process), then snapshots the reader's data, runs the helper
or PiPool code path that should emit, then asserts the **delta** over
the snapshot carries the expected counter/histogram increment.

Req: REQ-PI-009
"""  # req: REQ-PI-009

from __future__ import annotations

from collections.abc import (
    Iterator,  # noqa: TC003 — Iterator used in deferred (PEP 563) fixture return annotations
)
from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
import pytest

from mahavishnu.core.errors import PiProtocolError, PiRPCTimeout
from mahavishnu.pools import pi_observability
from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.pi_pool import PiPool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _otel_test_provider() -> Iterator[MeterProvider]:
    """Install a session-wide MeterProvider with InMemoryMetricReader.

    OTel's ``set_meter_provider`` is one-shot per process — once a real
    provider is installed, swapping in another is a silent no-op. So we
    install exactly once for the test session; per-test fixtures reset
    the instrument cache so each test sees fresh instruments bound to
    this same provider.
    """
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create({"service.name": "mahavishnu-pi-test"}),
        metric_readers=[reader],
    )
    metrics.set_meter_provider(provider)
    yield provider


@pytest.fixture
def metric_reader(_otel_test_provider: MeterProvider) -> Iterator[InMemoryMetricReader]:
    """Per-test fixture: yield the shared reader; reset cache on entry.

    Data accumulates across tests (a session-scoped reader does not
    reset), so each test takes a ``before`` snapshot and asserts on
    the delta. The lazy-instrument cache in
    :mod:`mahavishnu.pools.pi_observability` is cleared so the first
    emit in this test rebinds instruments to the test provider (in
    case any other module already triggered lazy resolution against a
    different provider).
    """
    reader = _otel_test_provider._metric_readers[0]  # type: ignore[attr-defined]
    pi_observability._reset_instrument_cache()
    yield reader


def _snapshot(reader: InMemoryMetricReader) -> dict[str, dict[tuple, float]]:
    """Snapshot counter / histogram point values keyed by metric+attributes.

    Returns a dict mapping ``(metric_name, frozenset(attributes.items()))``
    → current value (counter value or histogram count). Tests assert
    deltas against this snapshot.
    """
    snapshot: dict[str, dict[tuple, float]] = {}
    data = reader.get_metrics_data()
    if data is None:
        return snapshot
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                bucket: dict[tuple, float] = snapshot.setdefault(m.name, {})
                for dp in m.data.data_points:
                    key = frozenset(dict(dp.attributes).items())
                    if "Histogram" in type(m.data).__name__:
                        bucket[key] = float(dp.count)
                    else:
                        bucket[key] = float(dp.value)
    return snapshot


def _delta(
    reader: InMemoryMetricReader,
    before: dict[str, dict[tuple, float]],
    metric: str,
    attrs: dict[str, str],
) -> float:
    """Return the delta for ``metric`` at the given attribute set."""
    after = _snapshot(reader)
    key = frozenset(attrs.items())
    after_val = after.get(metric, {}).get(key, 0.0)
    before_val = before.get(metric, {}).get(key, 0.0)
    return after_val - before_val


def _make_pool_with_fake_client(
    *,
    request_return: Any | None = None,
    request_side_effect: Exception | None = None,
    watchdog_failed: bool = False,
) -> tuple[PiPool, Any]:
    """Build a PiPool wired to an AsyncMock client (no real subprocess).

    Returns ``(pool, fake_client)``. The pool is *not* started by this
    helper — tests call ``pool.start()`` themselves when they need the
    client attached.
    """
    if request_return is None:
        request_return = {"ok": True}
    from unittest.mock import AsyncMock, MagicMock

    from mahavishnu.core.json_rpc_stdio import JSONRPCStdioClient

    fake = AsyncMock(spec=JSONRPCStdioClient)
    fake.start = AsyncMock(return_value="1.0.0")
    fake.stop = AsyncMock(return_value=None)
    fake.is_started = True
    fake.is_stopped = False
    fake.startup_version = "1.0.0"
    fake.watchdog_failed = watchdog_failed
    fake.protocol_errors = 0
    if request_side_effect is not None:
        fake.request = AsyncMock(side_effect=request_side_effect)
    else:
        fake.request = AsyncMock(return_value=request_return)
    fake.ping = AsyncMock(return_value=12.3)
    fake._request_timeout = 30.0
    config = PoolConfig(
        name="test-pi",
        pool_type="pi",
        min_workers=1,
        max_workers=1,
        extra_config={"npx_command": ["npx", "@earendil-works/pi-coding-agent", "--rpc"]},
    )
    pool = PiPool(
        config=config,
        rpc_factory=MagicMock(return_value=fake),
        env_allowlist=("PATH",),
    )
    return pool, fake


# --- helper-level tests --------------------------------------------------


def test_record_task_completed_increments_counter_and_records_duration(
    metric_reader: InMemoryMetricReader,
) -> None:
    """``record_task_completed`` fires counter{status=completed}+1, histogram+1."""
    before = _snapshot(metric_reader)
    pi_observability.record_task_completed(0.42)

    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "completed"}) == 1.0
    # Histogram emits to the no-label attribute set.
    assert _delta(metric_reader, before, "mahavishnu.pi.task.duration", {}) == 1.0

    # Verify the duration sum matches.
    hist_points = [
        dp
        for rm in metric_reader.get_metrics_data().resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "mahavishnu.pi.task.duration"
        for dp in m.data.data_points
    ]
    assert hist_points, "Histogram point missing"
    # The most recent observation's sum is what we care about.
    assert hist_points[-1].sum == pytest.approx(0.42, abs=1.0)


def test_record_task_failed_with_error_path_increments_failed_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    """``record_task_failed(timed_out=False)`` fires counter{status=failed}+1."""
    before = _snapshot(metric_reader)
    pi_observability.record_task_failed(0.10, timed_out=False)
    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "failed"}) == 1.0


def test_record_task_failed_with_timeout_path_increments_timeout_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    """``record_task_failed(timed_out=True)`` fires counter{status=timeout}+1."""
    before = _snapshot(metric_reader)
    pi_observability.record_task_failed(5.0, timed_out=True)
    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "timeout"}) == 1.0


def test_record_heartbeat_missed_increments_heartbeat_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    """``record_heartbeat_missed`` fires counter+2 (two calls) with no labels."""
    before = _snapshot(metric_reader)
    pi_observability.record_heartbeat_missed()
    pi_observability.record_heartbeat_missed()
    assert _delta(metric_reader, before, "mahavishnu.pi.heartbeat.missed_total", {}) == 2.0


# --- end-to-end PiPool wire-up -------------------------------------------


@pytest.mark.asyncio
async def test_execute_task_success_emits_completed_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    pool, _ = _make_pool_with_fake_client(request_return={"text": "ok"})
    before = _snapshot(metric_reader)
    await pool.start()
    await pool.execute_task({"prompt": "hello"})
    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "completed"}) == 1.0


@pytest.mark.asyncio
async def test_execute_task_protocol_error_emits_failed_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    pool, _ = _make_pool_with_fake_client(
        request_side_effect=PiProtocolError("bad", frame_excerpt="x"),
    )
    before = _snapshot(metric_reader)
    await pool.start()
    await pool.execute_task({"prompt": "x"})
    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "failed"}) == 1.0


@pytest.mark.asyncio
async def test_execute_task_timeout_emits_timeout_counter(
    metric_reader: InMemoryMetricReader,
) -> None:
    pool, _ = _make_pool_with_fake_client(
        request_side_effect=PiRPCTimeout("slow", method="complete"),
    )
    before = _snapshot(metric_reader)
    await pool.start()
    await pool.execute_task({"prompt": "slow"})
    assert _delta(metric_reader, before, "mahavishnu.pi.tasks.executed", {"status": "timeout"}) == 1.0


@pytest.mark.asyncio
async def test_duration_histogram_records_successful_execution(
    metric_reader: InMemoryMetricReader,
) -> None:
    """A successful execute_task records one duration histogram observation."""
    pool, _ = _make_pool_with_fake_client()
    before = _snapshot(metric_reader)
    await pool.start()
    await pool.execute_task({"prompt": "ok"})
    assert _delta(metric_reader, before, "mahavishnu.pi.task.duration", {}) == 1.0


@pytest.mark.asyncio
async def test_execute_task_watchdog_failure_emits_heartbeat_missed(
    metric_reader: InMemoryMetricReader,
) -> None:
    """When watchdog_failed flips after a failure, heartbeat counter increments."""
    pool, fake = _make_pool_with_fake_client(
        request_side_effect=PiProtocolError("crash", frame_excerpt="x"),
        watchdog_failed=False,
    )
    before = _snapshot(metric_reader)
    await pool.start()
    # Simulate the watchdog failing DURING the failed request.
    fake.watchdog_failed = True
    await pool.execute_task({"prompt": "crash"})
    assert _delta(metric_reader, before, "mahavishnu.pi.heartbeat.missed_total", {}) == 1.0
