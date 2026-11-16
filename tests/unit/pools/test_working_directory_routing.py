"""A task that names a working directory must be routed to a pool that can honour it.

Worktree isolation depends on the worker actually running inside the
worktree. A pool whose worker sessions are already running elsewhere
cannot start them in a named directory — and a task handed to such a
pool either fails obscurely or, in the pool types that ignore the
directory, runs in the wrong place with no sign that it did.

So the routing keeps the two apart: a task carrying ``task["cwd"]`` is
routed only to a pool that reports it can honour one, and when no such
pool exists the dispatch fails with an actionable message instead of
running somewhere the caller did not ask for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.manager import PoolManager, PoolSelector


def _pool(
    pool_id: str,
    *,
    workers: int = 1,
    supports_working_directory: bool = False,
    pool_type: str = "mahavishnu",
) -> Any:
    """A pool stand-in with the capability flag the router reads."""
    pool = MagicMock()
    pool.pool_id = pool_id
    pool.config = PoolConfig(name=pool_id, pool_type=pool_type)
    pool._workers = {f"w{i}": f"w{i}" for i in range(workers)}
    pool.supports_working_directory = supports_working_directory

    async def mock_execute(
        task: dict[str, Any], pool_id: str = pool_id
    ) -> dict[str, Any]:
        return {"pool_id": pool_id, "status": "completed"}

    pool.execute_task = mock_execute
    return pool


class _FittedModel:
    """A queueing model stub with a fixed predicted wait."""

    def __init__(self, wait: float) -> None:
        self._wait = wait

    def safe_expected_wait_time(self) -> float:
        return self._wait


class _QueueingBuffer:
    """A queueing buffer stub whose model is already fitted.

    The real buffer needs a hundred observations before it fits; a
    re-rank test only needs the prediction to exist. The rest of the
    surface is what the manager calls around it.
    """

    def __init__(self, wait: float) -> None:
        self.fitted_model = _FittedModel(wait)
        self.arrivals: list[float] = []
        self.services: list[float] = []

    def record_arrival(self) -> None:
        self.arrivals.append(0.0)

    def complete_observation(self, service: float) -> bool:
        self.services.append(service)
        return True

    def ready_to_fit(self) -> bool:
        return False

    def due_for_refit(self) -> bool:
        return False

    def fit(self, num_workers: int) -> None:
        return None


@pytest.fixture
def manager() -> PoolManager:
    return PoolManager(terminal_manager=None, session_buddy_client=None)


class TestAWorkingDirectoryTask:
    @pytest.mark.asyncio
    async def test_it_routes_to_a_pool_that_can_honour_one(
        self, manager: PoolManager
    ) -> None:
        manager._pools["plain"] = _pool("plain", workers=0)
        manager._pools["capable"] = _pool(
            "capable", workers=3, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # The plain pool has fewer workers, but it cannot honour the
        # directory — so it is not a candidate at all.
        assert result["pool_id"] == "capable"

    @pytest.mark.asyncio
    async def test_the_least_loaded_capable_pool_wins(
        self, manager: PoolManager
    ) -> None:
        manager._pools["busy"] = _pool(
            "busy", workers=3, supports_working_directory=True
        )
        manager._pools["idle"] = _pool(
            "idle", workers=0, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "idle"

    @pytest.mark.asyncio
    async def test_it_fails_loud_when_no_pool_can_honour_one(
        self, manager: PoolManager
    ) -> None:
        manager._pools["plain"] = _pool("plain", workers=0)

        with pytest.raises(RuntimeError, match="can honour task"):
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

    @pytest.mark.asyncio
    async def test_a_task_without_a_directory_is_unaffected(
        self, manager: PoolManager
    ) -> None:
        manager._pools["plain"] = _pool("plain", workers=0)
        manager._pools["capable"] = _pool(
            "capable", workers=3, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # The ordinary selector still picks the least-loaded pool; a
        # capable pool is not preferred just because it can do more.
        assert result["pool_id"] == "plain"


class TestTheCallerAllowlist:
    """ADR-014: the allowlist is the authorization boundary.

    A task that names a working directory must not escape the set of
    pools the caller is authorized to use. The capability narrows the
    candidates; the allowlist still bounds them.
    """

    @pytest.mark.asyncio
    async def test_a_capable_pool_outside_the_allowlist_is_not_used(
        self, manager: PoolManager
    ) -> None:
        manager._pools["allowed"] = _pool("allowed", workers=0)
        manager._pools["forbidden"] = _pool(
            "forbidden", workers=0, supports_working_directory=True
        )

        with pytest.raises(RuntimeError, match="can honour task"):
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
                caller_pool_allowlist={"allowed"},
            )

    @pytest.mark.asyncio
    async def test_a_capable_pool_inside_the_allowlist_is_used(
        self, manager: PoolManager
    ) -> None:
        manager._pools["allowed"] = _pool("allowed", workers=0)
        manager._pools["capable-allowed"] = _pool(
            "capable-allowed", workers=2, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.LEAST_LOADED,
            caller_pool_allowlist={"allowed", "capable-allowed"},
        )

        assert result["pool_id"] == "capable-allowed"

    @pytest.mark.asyncio
    async def test_an_explicitly_selected_pool_is_honoured_when_allowed_and_capable(
        self, manager: PoolManager
    ) -> None:
        manager._pools["chosen"] = _pool(
            "chosen", workers=5, supports_working_directory=True
        )
        manager._pools["other"] = _pool(
            "other", workers=0, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="chosen",
            caller_pool_allowlist={"chosen", "other"},
        )

        assert result["pool_id"] == "chosen"

    @pytest.mark.asyncio
    async def test_an_explicitly_selected_pool_that_is_not_capable_is_replaced(
        self, manager: PoolManager
    ) -> None:
        """The explicit pick cannot honour the directory, so it is not used."""
        manager._pools["chosen"] = _pool("chosen", workers=0)
        manager._pools["capable"] = _pool(
            "capable", workers=3, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="chosen",
            caller_pool_allowlist={"chosen", "capable"},
        )

        assert result["pool_id"] == "capable"

    @pytest.mark.asyncio
    async def test_an_explicitly_selected_pool_outside_the_allowlist_is_not_used(
        self, manager: PoolManager
    ) -> None:
        manager._pools["forbidden"] = _pool(
            "forbidden", workers=0, supports_working_directory=True
        )
        manager._pools["allowed"] = _pool(
            "allowed", workers=2, supports_working_directory=True
        )

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="forbidden",
            caller_pool_allowlist={"allowed"},
        )

        assert result["pool_id"] == "allowed"


class TestTheCapabilityDefault:
    def test_a_pool_must_opt_in(self) -> None:
        """The base class says no, so a new pool type is safe by default."""

        class _Pool:
            pass

        from mahavishnu.pools.base import BasePool

        assert BasePool.supports_working_directory.fget(_Pool()) is False


class TestTheReRankCannotMoveADirectoryTask:
    """The re-ranking steps choose a pool too.

    The queueing re-rank picks the pool with the lowest predicted wait
    across the candidate set, and the GPU override prefers a runpod
    pool. Either can move a directory-bearing task onto a pool that
    ignores the directory — and the isolation check still passes,
    because the worktree key says a worktree was *created*, not where
    the worker ran. That is the 2026-11-06 failure, reached through a
    different door, so the capability constraint has to travel with
    the re-rank rather than being checked once and forgotten.
    """

    @pytest.mark.asyncio
    async def test_the_queueing_re_rank_keeps_the_task_on_a_capable_pool(
        self, manager: PoolManager
    ) -> None:
        manager._pools["capable"] = _pool(
            "capable", workers=0, supports_working_directory=True
        )
        manager._pools["busy"] = _pool("busy", workers=5)

        # The incapable pool predicts a much shorter wait, so a
        # re-rank without the capability constraint would pick it.
        manager._queueing_buffers["busy"] = _QueueingBuffer(0.1)
        manager._queueing_buffers["capable"] = _QueueingBuffer(50.0)

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "capable"

    @pytest.mark.asyncio
    async def test_the_gpu_override_yields_to_the_working_directory(
        self, manager: PoolManager
    ) -> None:
        manager._pools["capable"] = _pool(
            "capable", workers=0, supports_working_directory=True
        )
        manager._pools["gpu"] = _pool("gpu", workers=0, pool_type="runpod")

        result = await manager.route_task(
            {"prompt": "review", "cwd": "/tmp/worktree-1", "category": "vision"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # RunPodPool has no working-directory concept, so the GPU
        # preference yields to the isolation guarantee.
        assert result["pool_id"] == "capable"

    @pytest.mark.asyncio
    async def test_a_task_that_cannot_stay_on_a_capable_pool_fails_loud(
        self, manager: PoolManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The backstop: whatever a re-rank does, the task must not land
        on a pool that ignores the directory it named."""
        manager._pools["capable"] = _pool(
            "capable", workers=0, supports_working_directory=True
        )
        manager._pools["incapable"] = _pool("incapable", workers=0)

        def _re_rank_to_an_incapable_pool(*args: Any, **kwargs: Any):
            return "incapable", None, "least_loaded", False

        monkeypatch.setattr(
            manager, "_apply_queueing_penalty", _re_rank_to_an_incapable_pool
        )

        with pytest.raises(RuntimeError, match="cannot honour task"):
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )


class TestTheRealPoolKnowsItsCapability:
    """The capability flag is the real pool's, not a stand-in's.

    The routing tests above pin the *router's* use of the flag, but
    they use a stand-in pool — so they would pass while the real
    ``MahavishnuPool`` reported the wrong thing. The flag comes from
    the worker registry: a one-shot SHELL worker takes its prompt with
    the launch command and can therefore be started in a named
    directory, and a pre-spawned worker cannot — its session already
    exists, and it exists where it was launched.
    """

    @staticmethod
    def _pool(worker_type: str) -> Any:
        from mahavishnu.pools.mahavishnu_pool import MahavishnuPool

        return MahavishnuPool(
            config=PoolConfig(
                name=f"pool-{worker_type}",
                pool_type="mahavishnu",
                worker_type=worker_type,
            ),
            terminal_manager=MagicMock(),
            settings=MagicMock(),
        )

    def test_a_one_shot_worker_can_honour_a_directory(self) -> None:
        assert self._pool("terminal-claude").supports_working_directory is True

    def test_a_pre_spawned_worker_cannot(self) -> None:
        assert self._pool("shepherd").supports_working_directory is False


class TestThePoolListReportsTheCapability:
    """A caller cannot route by a capability it cannot see.

    The merge pipeline needs a pool that can start a session in a
    named directory, and it has to ask the server which pools can. The
    rest of the listing says nothing about it: a pool that reports
    True is the only kind that can honour ``task["cwd"]``, and picking
    any other puts the worker in the shared checkout.
    """

    @pytest.mark.asyncio
    async def test_the_listing_carries_the_capability(self) -> None:
        manager = PoolManager(terminal_manager=MagicMock(), message_bus=MagicMock())
        manager._pools["pool-1"] = MagicMock()
        manager._pools["pool-1"].supports_working_directory = True
        manager._pools["pool-1"].status = AsyncMock(
            return_value=SimpleNamespace(value="running")
        )
        manager._pools["pool-1"]._workers = []

        listed = await manager.list_pools()

        assert listed[0]["supports_working_directory"] is True

    @pytest.mark.asyncio
    async def test_a_pool_without_the_capability_reports_false(self) -> None:
        manager = PoolManager(terminal_manager=MagicMock(), message_bus=MagicMock())
        manager._pools["pool-1"] = MagicMock()
        manager._pools["pool-1"].supports_working_directory = False
        manager._pools["pool-1"].status = AsyncMock(
            return_value=SimpleNamespace(value="running")
        )
        manager._pools["pool-1"]._workers = []

        listed = await manager.list_pools()

        assert listed[0]["supports_working_directory"] is False


class TestEveryRefusalIsCounted:
    """A refusal that only logs is a silence on-call cannot hear.

    There are two ways a directory-bearing task is refused: no
    registered pool can honour the directory, or the re-ranking moved
    the task onto a pool that cannot. Both raise, and both have to
    reach the counter the runbook tells the on-call engineer to read.
    """

    @staticmethod
    def _count(reason: str) -> float:
        from mahavishnu.core._producer_metrics import (
            WORKTREE_ISOLATION_REFUSALS_TOTAL,
        )

        return WORKTREE_ISOLATION_REFUSALS_TOTAL.labels(reason=reason)._value.get()

    @pytest.mark.asyncio
    async def test_the_rerank_refusal_is_counted(
        self, manager: PoolManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager._pools["capable"] = _pool(
            "capable", workers=0, supports_working_directory=True
        )
        manager._pools["incapable"] = _pool("incapable", workers=0)

        def _re_rank_to_an_incapable_pool(*args: Any, **kwargs: Any):
            return "incapable", None, "least_loaded", False

        monkeypatch.setattr(
            manager, "_apply_queueing_penalty", _re_rank_to_an_incapable_pool
        )
        before = self._count("rerank_moved_the_task")

        with pytest.raises(RuntimeError, match="cannot honour task"):
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

        assert self._count("rerank_moved_the_task") == before + 1

    @pytest.mark.asyncio
    async def test_the_no_capable_pool_refusal_is_counted(
        self, manager: PoolManager
    ) -> None:
        """The registry holds a pool, but none of them can honour one."""
        manager._pools["incapable"] = _pool("incapable", workers=0)
        before = self._count("no_capable_pool")

        with pytest.raises(RuntimeError, match="No pool available that can honour"):
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

        assert self._count("no_capable_pool") == before + 1


class TestADirectlyTargetedDirectoryTask:
    """Naming a pool directly must not bypass the directory guarantee.

    ``route_task`` refuses to move a directory-bearing task onto a pool
    that cannot honour the directory. ``execute_on_pool`` is a public
    entry in its own right, though, and it had no such check: a caller
    that named a pool directly had its directory silently ignored, and
    the worker started in the shared checkout while the caller believed
    it was isolated.

    The pools that cannot honour a directory are not misconfigured —
    their workers are already running somewhere else, and there is
    nowhere for them to start. So the task is refused rather than run
    in the wrong place.
    """

    @pytest.mark.asyncio
    async def test_it_refuses_a_directory_a_pool_cannot_honour(
        self, manager: PoolManager
    ) -> None:
        manager._pools["incapable"] = _pool("incapable", workers=0)

        with pytest.raises(RuntimeError, match="cannot honour task"):
            await manager.execute_on_pool(
                "incapable", {"prompt": "review", "cwd": "/tmp/worktree-1"}
            )

    @pytest.mark.asyncio
    async def test_it_runs_the_task_on_a_pool_that_can_honour_it(
        self, manager: PoolManager
    ) -> None:
        manager._pools["capable"] = _pool(
            "capable", workers=0, supports_working_directory=True
        )

        result = await manager.execute_on_pool(
            "capable", {"prompt": "review", "cwd": "/tmp/worktree-1"}
        )

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_a_task_without_a_directory_is_unaffected(
        self, manager: PoolManager
    ) -> None:
        """The refusal is about the directory, not about the pool."""
        manager._pools["incapable"] = _pool("incapable", workers=0)

        result = await manager.execute_on_pool("incapable", {"prompt": "review"})

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_the_refusal_is_counted(self, manager: PoolManager) -> None:
        """A refusal that only raises is still a silence on-call cannot hear."""
        from mahavishnu.core._producer_metrics import (
            WORKTREE_ISOLATION_REFUSALS_TOTAL,
        )

        manager._pools["incapable"] = _pool("incapable", workers=0)
        before = WORKTREE_ISOLATION_REFUSALS_TOTAL.labels(
            reason="pool_cannot_honour_cwd"
        )._value.get()

        with pytest.raises(RuntimeError, match="cannot honour task"):
            await manager.execute_on_pool(
                "incapable", {"prompt": "review", "cwd": "/tmp/worktree-1"}
            )

        after = WORKTREE_ISOLATION_REFUSALS_TOTAL.labels(
            reason="pool_cannot_honour_cwd"
        )._value.get()
        assert after == before + 1


class TestTheRefusalNamesItsRemedy:
    """The remedy has to work.

    The spawn is idempotent by name, so telling an operator to spawn a
    pool named ``merge-review`` when a pool of that name already
    exists in the wrong form changes nothing: the spawn reports
    "exists" and the merge stops the same way it did before.
    """

    @pytest.mark.asyncio
    async def test_the_refusal_says_to_close_the_pool_of_that_name(
        self, manager: PoolManager
    ) -> None:
        manager._pools["incapable"] = _pool("incapable", workers=0)

        with pytest.raises(RuntimeError) as raised:
            await manager.route_task(
                {"prompt": "review", "cwd": "/tmp/worktree-1"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

        message = str(raised.value)
        assert "idempotent by name" in message
        assert "pool close" in message
