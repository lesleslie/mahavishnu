"""Coverage-push tests for pools.MahavishnuPool local-worker wrapper; exercises execute/scale/list_pools/health branches via AsyncMock of WorkerManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import PoolStatus, WorkerStatus
from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
from mahavishnu.workers.base import WorkerResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["general", "one-shot"])
def pool_config(request: pytest.FixtureRequest) -> PoolConfig:
    """PoolConfig with non-trivial min/max so scale() can exercise both branches.

    Parametrized over the two pool shapes a SHELL worker type can take:

    - ``general`` -- a worker that keeps its session, so the pool holds a
      set of idle workers and dispatches into one of them.
    - ``one-shot`` -- a CLI harness (``terminal-claude``) that reads its
      prompt from the launch command and exits when it is done, so the
      pool launches one session per task instead.
    """
    worker_type = "terminal-claude" if request.param == "one-shot" else "terminal-shell"
    return PoolConfig(
        name="coverage-mahavishnu",
        pool_type="mahavishnu",
        min_workers=2,
        max_workers=6,
        worker_type=worker_type,
    )


@pytest.fixture
def mock_terminal_manager() -> MagicMock:
    return MagicMock()


def _build_mock_worker_manager(
    *,
    spawn_workers: list[str] | None = None,
    health: dict[str, object] | None = None,
) -> MagicMock:
    """Construct a MagicMock WorkerManager whose async methods are AsyncMock.

    Args:
        spawn_workers: Return value for spawn_workers(). Defaults to two ids.
        health: Return value for health_check(). Defaults to "healthy".
    """
    mock = MagicMock()
    mock.spawn_workers = AsyncMock(return_value=spawn_workers or ["worker-1", "worker-2"])
    mock.execute_task = AsyncMock()
    mock.execute_batch = AsyncMock(return_value={})
    mock.submit_workers = AsyncMock(return_value=["worker-1"])
    mock.close_worker = AsyncMock()
    mock.close_all = AsyncMock()
    mock.collect_results = AsyncMock(return_value={})
    mock.health_check = AsyncMock(
        return_value=health
        if health is not None
        else {
            "status": "healthy",
            "workers_active": 2,
            "workers": [],
        }
    )
    return mock


def _make_pool(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    mock_wm: MagicMock,
) -> MahavishnuPool:
    """Build a MahavishnuPool whose WorkerManager is fully AsyncMock-backed."""
    with patch(
        "mahavishnu.pools.mahavishnu_pool.WorkerManager",
        return_value=mock_wm,
    ):
        return MahavishnuPool(
            config=pool_config,
            terminal_manager=mock_terminal_manager,
        )


def _seed_workers(pool: MahavishnuPool, ids: list[str]) -> None:
    """Pretend ``start()`` already ran: populate _workers directly."""
    pool._workers = {wid: f"worker_{wid}" for wid in ids}


# ---------------------------------------------------------------------------
# execute_task: success, failure-status, raised exceptions, timeout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expect_completed", "expect_failed"),
    [
        (WorkerStatus.COMPLETED, 1, 0),
        (WorkerStatus.FAILED, 0, 1),
        (WorkerStatus.TIMEOUT, 0, 1),
    ],
    ids=["completed", "failed", "timeout-status"],
)
async def test_execute_task_status_outcomes(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    status: WorkerStatus,
    expect_completed: int,
    expect_failed: int,
) -> None:
    """execute_task records completed vs. failed counters for each terminal status."""
    mock_wm = _build_mock_worker_manager()
    worker_result = WorkerResult(
        worker_id="worker-1",
        status=status,
        output="ok",
        error=None,
        exit_code=0 if status is WorkerStatus.COMPLETED else 1,
        duration_seconds=0.25,
    )
    mock_wm.execute_task.return_value = worker_result
    mock_wm.execute_batch.return_value = {"worker-1": worker_result}
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, ["worker-1"])

    result = await pool.execute_task({"prompt": "p"})

    assert result["status"] == status.value
    assert result["worker_id"] == "worker-1"
    assert pool._tasks_completed == expect_completed
    assert pool._tasks_failed == expect_failed
    assert pool._task_durations and pool._task_durations[-1] >= 0.0


@pytest.mark.parametrize(
    "side_effect",
    [TimeoutError("worker stalled"), RuntimeError("boom")],
    ids=["timeout-exception", "runtime-exception"],
)
async def test_execute_task_propagates_worker_manager_exceptions(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    side_effect: Exception,
) -> None:
    """execute_task does NOT swallow WorkerManager exceptions; it lets them bubble."""
    mock_wm = _build_mock_worker_manager()
    mock_wm.execute_task.side_effect = side_effect
    mock_wm.execute_batch.side_effect = side_effect
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, ["worker-1"])

    with pytest.raises(type(side_effect), match=str(side_effect)):
        await pool.execute_task({"prompt": "p"})

    # Stats unchanged — only terminal WorkerResult updates counters
    assert pool._tasks_completed == 0
    assert pool._tasks_failed == 0


# ---------------------------------------------------------------------------
# scale: happy path up, happy path down, rejection at the boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "expected_workers", "expect_spawn_calls"),
    [
        (2, 4, 4, 1),  # scale up: spawn 2
        (4, 6, 6, 1),  # scale up at the max boundary
        (4, 2, 2, 0),  # scale down: close 2
        (3, 3, 3, 0),  # no-op within range
    ],
    ids=["scale-up", "scale-up-to-max", "scale-down", "no-op"],
)
async def test_scale_within_range(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    current: int,
    target: int,
    expected_workers: int,
    expect_spawn_calls: int,
) -> None:
    """scale() moves the worker pool to the requested count and restores RUNNING."""
    new_ids = [f"worker-{i}" for i in range(current + 1, target + 1)]
    mock_wm = _build_mock_worker_manager(spawn_workers=new_ids)
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, [f"worker-{i}" for i in range(1, current + 1)])

    await pool.scale(target)

    assert pool._status == PoolStatus.RUNNING
    assert len(pool._workers) == expected_workers
    assert mock_wm.spawn_workers.await_count == expect_spawn_calls
    if expect_spawn_calls:
        # spawn_workers invoked with the delta, not the absolute target
        spawn_kwargs = mock_wm.spawn_workers.await_args
        assert spawn_kwargs.kwargs["count"] == target - current


@pytest.mark.parametrize("bad_target", [0, 1, 7, 100])
async def test_scale_rejects_target_outside_range(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    bad_target: int,
) -> None:
    """scale() raises ValueError when target is below min or above max."""
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, ["worker-1", "worker-2"])

    with pytest.raises(ValueError, match="outside range"):
        await pool.scale(bad_target)

    assert len(pool._workers) == 2  # unchanged


# ---------------------------------------------------------------------------
# health_check: healthy, degraded (workers below min), unhealthy (no workers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("workers", "worker_health_status", "expected_pool_status"),
    [
        (["w1", "w2"], "healthy", "healthy"),
        (["w1"], "healthy", "degraded"),  # 1 < min_workers(2)
        ([], "healthy", "unhealthy"),
    ],
    ids=["healthy", "degraded-below-min", "unhealthy-no-workers"],
)
async def test_health_check_branches(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
    workers: list[str],
    worker_health_status: str,
    expected_pool_status: str,
) -> None:
    """health_check() classifies the pool from (worker count, WorkerManager health)."""
    mock_wm = _build_mock_worker_manager(
        health={"status": worker_health_status, "workers": []},
    )
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, workers)

    health = await pool.health_check()

    assert health["status"] == expected_pool_status
    assert health["pool_type"] == "mahavishnu"
    assert health["workers_active"] == len(workers)
    assert health["worker_health"]["status"] == worker_health_status


# ---------------------------------------------------------------------------
# execute_batch: empty workers rejection, round-robin assignment
# ---------------------------------------------------------------------------


async def test_execute_batch_raises_without_workers(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """execute_batch raises RuntimeError when no workers are registered."""
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    # Deliberately leave _workers empty

    with pytest.raises(RuntimeError, match="No workers available"):
        await pool.execute_batch([{"prompt": "p"}])

    # Underlying WorkerManager must not be called when there's nothing to dispatch
    mock_wm.execute_batch.assert_not_called()


async def test_execute_batch_round_robin_assignment(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """execute_batch round-robins tasks across worker_ids and counts outcomes per result."""
    mock_wm = _build_mock_worker_manager()
    mock_wm.execute_batch.return_value = {
        "worker-1": WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="r1",
            duration_seconds=0.1,
        ),
        "worker-2": WorkerResult(
            worker_id="worker-2",
            status=WorkerStatus.FAILED,
            output=None,
            error="nope",
            duration_seconds=0.2,
        ),
        "worker-1-dup": WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="r3",
            duration_seconds=0.3,
        ),
    }
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, ["worker-1", "worker-2"])

    results = await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}])

    assert set(results.keys()) == {"0", "1", "2"}
    assert pool._tasks_completed == 2
    assert pool._tasks_failed == 1
    assert pool._task_durations == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# get_metrics: with and without recorded durations
# ---------------------------------------------------------------------------


async def test_get_metrics_with_durations(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """get_metrics reports avg duration over the recorded samples."""
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)
    _seed_workers(pool, ["worker-1", "worker-2"])
    pool._task_durations = [1.0, 2.0, 3.0]
    pool._tasks_completed = 3
    pool._status = PoolStatus.RUNNING

    metrics = await pool.get_metrics()

    assert metrics.pool_id == pool.pool_id
    assert metrics.active_workers == 2
    assert metrics.total_workers == 2
    assert metrics.tasks_completed == 3
    assert metrics.avg_task_duration == pytest.approx(2.0)
    assert metrics.memory_usage_mb == 0.0


# ---------------------------------------------------------------------------
# one-shot CLI pools: one session per task, launched with the prompt
# ---------------------------------------------------------------------------
#
# A one-shot CLI harness (terminal-claude and friends) reads its prompt
# from the launch command and exits when it is done, so the pool cannot
# pre-spawn a set of idle sessions and type into them later. Each task
# gets its own session, launched with the prompt already in place.


@pytest.fixture
def one_shot_pool_config() -> PoolConfig:
    """A pool over a CLI harness, which is one-shot."""
    return PoolConfig(
        name="coverage-one-shot",
        pool_type="mahavishnu",
        min_workers=1,
        max_workers=2,
        worker_type="terminal-claude",
    )


async def test_one_shot_pool_launches_a_session_per_task(
    one_shot_pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """The prompt is handed to the launch, not typed into a live session."""
    mock_wm = _build_mock_worker_manager()
    mock_wm.execute_batch.return_value = {
        "worker-1": WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="done",
            error=None,
            exit_code=0,
            duration_seconds=0.1,
        )
    }
    pool = _make_pool(one_shot_pool_config, mock_terminal_manager, mock_wm)

    result = await pool.execute_task({"prompt": "do the thing"})

    mock_wm.submit_workers.assert_awaited_once_with(
        "terminal-claude",
        ["do the thing"],
    )
    mock_wm.execute_batch.assert_awaited_once()
    # The session exists to run one prompt; it is torn down after.
    mock_wm.close_worker.assert_awaited_once_with("worker-1")
    assert result["status"] == "completed"
    assert result["output"] == "done"


async def test_one_shot_pool_requires_a_prompt(
    one_shot_pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """A one-shot launch with no prompt would start a CLI that exits at once."""
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(one_shot_pool_config, mock_terminal_manager, mock_wm)

    with pytest.raises(ValueError, match="prompt"):
        await pool.execute_task({})

    mock_wm.submit_workers.assert_not_awaited()


async def test_one_shot_pool_closes_the_session_even_when_the_run_fails(
    one_shot_pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """A failed run must not leak the session it launched."""
    mock_wm = _build_mock_worker_manager()
    mock_wm.execute_batch.side_effect = RuntimeError("boom")
    pool = _make_pool(one_shot_pool_config, mock_terminal_manager, mock_wm)

    with pytest.raises(RuntimeError, match="boom"):
        await pool.execute_task({"prompt": "do the thing"})

    mock_wm.close_worker.assert_awaited_once_with("worker-1")


async def test_one_shot_pool_start_pre_spawns_nothing(
    one_shot_pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """A one-shot CLI launched without a prompt exits at once.

    So the pool must not hold idle sessions for it: every session is
    launched per task, with the prompt already in place.
    """
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(one_shot_pool_config, mock_terminal_manager, mock_wm)

    await pool.start()

    mock_wm.spawn_workers.assert_not_awaited()
    assert pool._workers == {}
    assert pool._status == PoolStatus.RUNNING


async def test_general_pool_start_pre_spawns_its_workers(
    pool_config: PoolConfig,
    mock_terminal_manager: MagicMock,
) -> None:
    """A worker that keeps its session is spawned once, at pool start."""
    mock_wm = _build_mock_worker_manager()
    pool = _make_pool(pool_config, mock_terminal_manager, mock_wm)

    await pool.start()

    if pool._is_one_shot:
        mock_wm.spawn_workers.assert_not_awaited()
    else:
        mock_wm.spawn_workers.assert_awaited_once()
        assert len(pool._workers) == 2


# ---------------------------------------------------------------------------
# the capability check needs settings
# ---------------------------------------------------------------------------
#
# WorkerManager evaluates a worker's capability before spawning it, and
# the first thing it reads is ``workers.enabled``. With no settings
# object at all that lookup resolves to None, which reads as False --
# so EVERY dispatch was refused with "workers disabled by config" and
# "missing_requirements: workers.enabled", whatever the YAML said.


def test_the_pool_resolves_settings_for_the_capability_check() -> None:
    """The pool must hand its WorkerManager a usable settings object."""
    from mahavishnu.pools import mahavishnu_pool

    settings = mahavishnu_pool._resolve_settings()

    assert settings is not None, "the pool could not load the project settings"
    assert settings.workers.enabled is True


def test_a_terminal_claude_worker_is_ready_once_settings_are_wired() -> None:
    """With settings, the CLI harness passes the capability check."""
    from mahavishnu.pools import mahavishnu_pool
    from mahavishnu.workers.capabilities import evaluate_worker_capabilities
    from mahavishnu.workers.capabilities._states import WorkerCapabilityState

    report = evaluate_worker_capabilities(
        "terminal-claude",
        settings=mahavishnu_pool._resolve_settings(),
    )

    assert report.state is WorkerCapabilityState.READY, (
        f"terminal-claude is not routable: {report.safe_reason}"
    )


def test_without_settings_the_capability_check_refuses_everything() -> None:
    """The trap this pins: no settings reads as 'workers disabled'."""
    from mahavishnu.workers.capabilities import evaluate_worker_capabilities
    from mahavishnu.workers.capabilities._states import WorkerCapabilityState

    report = evaluate_worker_capabilities("terminal-claude", settings=None)

    assert report.state is WorkerCapabilityState.CONFIGURED
    assert report.missing_requirements == ["workers.enabled"]
