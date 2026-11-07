"""The change-point tick loop must actually run.

Regression tests for the 2026-10-24 defect. The manager's
``start_change_point_tick_loop`` was ``async def`` and BOTH of its
call sites invoked it WITHOUT ``await``::

    task = manager.start_change_point_tick_loop(...)   # a coroutine!

The task slot therefore held a *coroutine object* rather than an
``asyncio.Task``, which meant three things at once:

- the loop body never ran, so ``asyncio.create_task`` was never
  reached and the change-point and 3-sigma detectors were silently
  dead in production;
- the coroutine was garbage-collected unawaited, emitting
  ``RuntimeWarning: coroutine '...' was never awaited`` on every CLI
  invocation;
- ``stop_change_point_tick_loop(task=coroutine)`` called
  ``coroutine.cancel()``, which does not exist — the AttributeError
  was swallowed by the broad handler and nothing was ever cancelled.

These tests pin the observable contract: a real Task comes back, the
loop drives the detector on its cadence, the stop path cancels
cleanly, and no "never awaited" warning is emitted.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import warnings

import pytest

from mahavishnu.core import observability as obs


def _config(cadence: float = 0.01) -> SimpleNamespace:
    """A config with the change-point block enabled and a fast cadence."""
    return SimpleNamespace(
        observability=SimpleNamespace(metrics_enabled=False, otlp_endpoint="http://otel"),
        changepoint=SimpleNamespace(
            enabled=True,
            sampler_cadence_seconds=cadence,
            target_metric="pool_queue_depth",
            reference_detector="none",
            detector="cusum",
        ),
        log_level="INFO",
    )


# ---------------------------------------------------------------------------
# The start path returns a real Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_starting_the_loop_returns_a_task_not_a_coroutine() -> None:
    """The handle must be cancelable — a coroutine has no .cancel()."""
    manager = obs.ObservabilityManager(_config())
    task = manager.start_change_point_tick_loop()
    try:
        assert isinstance(task, asyncio.Task)
        assert not asyncio.iscoroutine(task)
        assert hasattr(task, "cancel")
    finally:
        await manager.stop_change_point_tick_loop(task=task)


@pytest.mark.asyncio
async def test_the_loop_actually_drives_the_detector() -> None:
    """The whole point: the loop must call _evaluate_change_point."""
    manager = obs.ObservabilityManager(_config())
    seen: list[tuple[str, float]] = []

    def _record(metric_name: str, value: float) -> None:
        seen.append((metric_name, value))

    manager._evaluate_change_point = _record  # type: ignore[method-assign]
    task = manager.start_change_point_tick_loop(
        metric_source=lambda: {"pool_queue_depth": 7.5},
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.01)
            if seen:
                break
        assert seen, "the tick loop never called _evaluate_change_point"
        assert seen[0] == ("pool_queue_depth", 7.5)
    finally:
        await manager.stop_change_point_tick_loop(task=task)


@pytest.mark.asyncio
async def test_starting_the_loop_emits_no_never_awaited_warning() -> None:
    """The symptom that made this visible: a RuntimeWarning per CLI run."""
    manager = obs.ObservabilityManager(_config())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        task = manager.start_change_point_tick_loop()
        await asyncio.sleep(0)
        await manager.stop_change_point_tick_loop(task=task)
        del task
        import gc

        gc.collect()

    messages = [str(w.message) for w in caught]
    assert not any("never awaited" in m for m in messages), messages


# ---------------------------------------------------------------------------
# The stop path cancels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stopping_cancels_the_task() -> None:
    """The task must not outlive the loop that started it."""
    manager = obs.ObservabilityManager(_config())
    task = manager.start_change_point_tick_loop()
    await asyncio.sleep(0)

    await manager.stop_change_point_tick_loop(task=task)

    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_stopping_with_a_coroutine_closes_it_instead_of_raising() -> None:
    """A pre-fix handle must not blow up the shutdown path."""

    async def _never_awaited() -> None:
        return None

    manager = obs.ObservabilityManager(_config())
    coro = _never_awaited()

    await manager.stop_change_point_tick_loop(task=coro)

    # A closed coroutine cannot be awaited again.
    with pytest.raises(RuntimeError):
        await coro


@pytest.mark.asyncio
async def test_stopping_a_task_that_already_finished_is_harmless() -> None:
    """Shutdown races are normal; they must not raise."""
    manager = obs.ObservabilityManager(_config())
    task = manager.start_change_point_tick_loop()
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await manager.stop_change_point_tick_loop(task=task)


# ---------------------------------------------------------------------------
# The app lifecycle method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_app_lifecycle_method_returns_a_task() -> None:
    """``MahavishnuApp.start_change_point_tick_loop`` must hand back a Task."""
    from mahavishnu.core.app import MahavishnuApp

    manager = obs.ObservabilityManager(_config())
    fake_self = SimpleNamespace(observability=manager, pool_manager=None)

    task = await MahavishnuApp.start_change_point_tick_loop(fake_self)
    try:
        assert isinstance(task, asyncio.Task)
    finally:
        await manager.stop_change_point_tick_loop(task=task)


@pytest.mark.asyncio
async def test_the_pool_depth_source_speaks_the_detector_metric_namespace() -> None:
    """The metric source must publish under the configured metric NAME.

    ``PoolManager.get_pool_queue_depths`` returns a snapshot keyed by
    POOL ID, but the tick loop reads ``snapshot.get(target_metric)``
    where ``target_metric`` is a metric name ("pool_queue_depth" by
    default) and never a pool id. Passing the pool-id snapshot
    straight through therefore evaluated a constant ``0.0`` on every
    tick: the CUSUM accumulator could never cross its threshold, so
    the §7 stage-1 gate was vacuously green -- the detector was blind,
    not calm.
    """
    from mahavishnu.core.app import MahavishnuApp

    # One config, as in production: ``init_observability(app.config)``
    # hands the APP's config to the manager, so the source and the
    # detector always agree on the metric name.
    cfg = _config()

    manager = obs.ObservabilityManager(cfg)
    seen: list[tuple[str, float]] = []

    def _record(metric_name: str, value: float) -> None:
        seen.append((metric_name, value))

    manager._evaluate_change_point = _record  # type: ignore[method-assign]

    class _PoolManager:
        def get_pool_queue_depths(self) -> dict[str, float]:
            return {"pool_a": 3.0, "pool_b": 2.0}

    fake_self = SimpleNamespace(
        observability=manager,
        pool_manager=_PoolManager(),
        config=cfg,
    )

    task = await MahavishnuApp.start_change_point_tick_loop(fake_self)
    try:
        await asyncio.sleep(0.05)
    finally:
        await manager.stop_change_point_tick_loop(task=task)

    assert seen, "the tick loop never evaluated the detector"
    assert all(name == "pool_queue_depth" for name, _ in seen), (
        "the source published pool ids, not the metric name the "
        "detector reads -- the detector saw a constant 0.0"
    )
    assert all(value == 5.0 for _, value in seen), (
        "the source published a constant 0.0 instead of the aggregate "
        "pool depth the detector needs to see real traffic"
    )


@pytest.mark.asyncio
async def test_the_pool_depth_source_honours_a_renamed_target_metric() -> None:
    """The published name follows ``changepoint.target_metric``.

    The metric name is operator-configurable, so the source cannot
    hard-code it. A deployment that renames the target must not
    silently fall back to the default name -- that is the same blind
    detector under a different label.
    """
    from mahavishnu.core.app import MahavishnuApp

    # One config, as in production: ``init_observability(app.config)``
    # hands the APP's config to the manager, so the source and the
    # detector always agree on the metric name.
    cfg = _config()
    cfg.changepoint.target_metric = "fleet_queue_depth"

    manager = obs.ObservabilityManager(cfg)
    seen: list[tuple[str, float]] = []

    def _record(metric_name: str, value: float) -> None:
        seen.append((metric_name, value))

    manager._evaluate_change_point = _record  # type: ignore[method-assign]

    class _PoolManager:
        def get_pool_queue_depths(self) -> dict[str, float]:
            return {"pool_a": 7.0}

    fake_self = SimpleNamespace(
        observability=manager,
        pool_manager=_PoolManager(),
        config=cfg,
    )

    task = await MahavishnuApp.start_change_point_tick_loop(fake_self)
    try:
        await asyncio.sleep(0.05)
    finally:
        await manager.stop_change_point_tick_loop(task=task)

    assert seen, "the tick loop never evaluated the detector"
    assert all(name == "fleet_queue_depth" for name, _ in seen)
    assert all(value == 7.0 for _, value in seen)


# ---------------------------------------------------------------------------
# The MCP server lifespan is the production owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_mcp_lifecycle_starts_and_stops_the_tick_loop() -> None:
    """The loop is started and stopped by the server's async lifespan."""
    from mahavishnu.mcp import lifecycle as mcp_lifecycle

    started: list[bool] = []
    stopped: list[bool] = []

    class _App:
        async def start_change_point_tick_loop(self) -> str:
            started.append(True)
            return "task"

        async def stop_change_point_tick_loop(self) -> None:
            stopped.append(True)

    class _Server:
        app = _App()

    await mcp_lifecycle.start_change_point_tick_loop(_Server())
    assert started == [True]

    await mcp_lifecycle.stop_change_point_tick_loop(_Server())
    assert stopped == [True]


@pytest.mark.asyncio
async def test_the_mcp_lifecycle_survives_a_server_without_an_app() -> None:
    """A missing app is a degraded subsystem, not a crash."""
    from mahavishnu.mcp import lifecycle as mcp_lifecycle

    class _Server:
        app = None

    await mcp_lifecycle.start_change_point_tick_loop(_Server())
    await mcp_lifecycle.stop_change_point_tick_loop(_Server())


# ---------------------------------------------------------------------------
# Detector liveness -- "no drift" must be distinguishable from "never wired"
# ---------------------------------------------------------------------------


class _RecordingCounter:
    """Minimal stand-in for an OTel counter.

    ``total`` is the cumulative value the counter would report and
    ``calls`` is how many times it was written to -- the difference
    matters for an UpDownCounter used as a liveness flag, where the
    value must stay at 1 while the number of writes keeps growing.
    """

    def __init__(self) -> None:
        self.total = 0
        self.calls = 0

    def add(self, amount: int, attributes: dict | None = None) -> None:
        self.total += amount
        self.calls += 1


@pytest.mark.asyncio
async def test_each_tick_records_a_evaluation_even_when_no_drift_fires() -> None:
    """The liveness counter rises on every tick, drift or no drift.

    The drift counters carry {metric_name, detector, severity}
    attributes, so their series only exist after a drift fires. A query
    that finds no drift_detected_total therefore cannot tell "the
    detector ran and found nothing" from "the detector was never
    wired". The evaluation counter is what makes the difference
    visible.
    """
    manager = obs.ObservabilityManager(_config(cadence=0.01))
    evaluations = _RecordingCounter()
    active = _RecordingCounter()
    manager.changepoint_evaluations_counter = evaluations
    manager.changepoint_active_counter = active

    task = manager.start_change_point_tick_loop()
    try:
        await asyncio.sleep(0.1)
    finally:
        await manager.stop_change_point_tick_loop(task=task)

    assert evaluations.total > 0, "no evaluation was recorded -- detector liveness is invisible"
    assert active.total > 0, "the active flag was never set"


@pytest.mark.asyncio
async def test_the_active_gauge_reads_one_while_ticking_not_the_tick_count() -> None:
    """``changepoint_detector_active`` must match its own HELP text.

    The instrument is documented as "1 while the change-point detector
    tick loop is running, 0 when it is not", and the plan's §7 gate
    names it as one of the gate's two instruments. It used to
    ``add(1)`` on every tick, so it grew with the tick count (44 after
    44 ticks) and an operator querying ``== 1`` matched nothing. The
    series must still be re-emitted on later ticks so it goes stale
    when the process dies.
    """
    manager = obs.ObservabilityManager(_config(cadence=0.01))
    active = _RecordingCounter()
    manager.changepoint_active_counter = active

    task = manager.start_change_point_tick_loop()
    try:
        await asyncio.sleep(0.1)
    finally:
        await manager.stop_change_point_tick_loop(task=task)

    assert active.calls > 1, "the loop did not tick more than once"
    assert active.total == 1, (
        f"the active gauge reported {active.total} instead of 1 -- it is "
        "counting ticks, not reporting liveness"
    )


@pytest.mark.asyncio
async def test_the_evaluation_counter_survives_a_failing_instrument() -> None:
    """A broken instrument must not kill the tick loop."""

    class _Exploding:
        def add(self, amount: int, attributes: dict | None = None) -> None:
            raise RuntimeError("instrument is broken")

    manager = obs.ObservabilityManager(_config(cadence=0.01))
    manager.changepoint_evaluations_counter = _Exploding()
    manager.changepoint_active_counter = _Exploding()

    task = manager.start_change_point_tick_loop()
    try:
        await asyncio.sleep(0.05)
        assert not task.done(), "the tick loop died when an instrument raised"
    finally:
        await manager.stop_change_point_tick_loop(task=task)
