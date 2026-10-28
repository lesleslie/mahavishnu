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
    """Minimal stand-in for an OTel counter."""

    def __init__(self) -> None:
        self.total = 0

    def add(self, amount: int, attributes: dict | None = None) -> None:
        self.total += amount


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
