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


@pytest.fixture
def pool_config() -> PoolConfig:
    """PoolConfig with non-trivial min/max so scale() can exercise both branches."""
    return PoolConfig(
        name="coverage-mahavishnu",
        pool_type="mahavishnu",
        min_workers=2,
        max_workers=6,
        worker_type="terminal-claude",
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
    mock_wm.execute_task.return_value = WorkerResult(
        worker_id="worker-1",
        status=status,
        output="ok",
        error=None,
        exit_code=0 if status is WorkerStatus.COMPLETED else 1,
        duration_seconds=0.25,
    )
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
