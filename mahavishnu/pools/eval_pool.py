"""Eval pool — the pool-type surface for the model-evaluation subsystem.

The eval pool is a **single virtual worker**. It has no substrate to
start, no subprocess to supervise, and nothing to scale: it composes the
four eval extension points (dataset loader, scorer, storage, model
backend) into a scored, persisted run through
:class:`~mahavishnu.core.eval.engine.EvalEngine`.

It exists so that eval is discoverable through the pool machinery —
``mahavishnu pool list`` shows it, ``PoolManager.spawn_pool("eval", ...)``
works, and Phase 2 can route eval work across pools. In Phase 1 the MCP
tools call :class:`EvalEngine` directly and bypass this pool; see the
plan's Task 7 note.

``BasePool`` declares eight abstract methods. A subclass that omits any
one of them cannot be instantiated, so this module implements all eight:
``start``, ``execute_task``, ``execute_batch``, ``scale``,
``health_check``, ``get_metrics``, ``collect_memory``, ``stop``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mahavishnu.core.errors import EvalEngineError
from mahavishnu.core.eval._registry import discover_model_backends, discover_storage
from mahavishnu.core.eval.engine import (
    DEFAULT_MAX_CONCURRENCY,
    CostBudget,
    EvalEngine,
    EvalSuite,
    ModelConfig,
)
from mahavishnu.core.eval.settings import get_eval_settings

from ._registry import register_pool_type
from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

if TYPE_CHECKING:
    from mahavishnu.core.eval.engine import ModelBackend
    from mahavishnu.core.eval.settings import EvalSettings
    from mahavishnu.core.eval.storage import EvalStorage

logger = logging.getLogger(__name__)

# req: REQ-EVAL-004


class EvalPool(BasePool):
    """A pool that runs evaluation suites.

    Args:
        config: The pool configuration.
        storage: Where runs, case results, and scores are written.
        model_backend: The model the suites run against.
        settings: The eval settings (budget, concurrency, defaults).
    """

    def __init__(
        self,
        config: PoolConfig,
        storage: EvalStorage,
        model_backend: ModelBackend,
        settings: EvalSettings,
    ) -> None:
        super().__init__(config)
        self._storage = storage
        self._model_backend = model_backend
        self._settings = settings
        self._engine = EvalEngine(
            storage=storage,
            model_backend=model_backend,
            settings=settings,
        )

    async def start(self) -> str:
        """Mark the pool running.

        Eval has no substrate to start — the model backend and storage are
        injected at construction — so this only flips the status.

        The ``enabled`` flag is re-checked here, not only at construction:
        the pool is a server-reachable surface, and a deployment that
        turns evaluation off must not keep running suites through it.

        Returns:
            The pool id.

        Raises:
            EvalEngineError: If evaluation has been disabled.
        """
        self._require_enabled()
        self._status = PoolStatus.RUNNING
        logger.info("eval pool started pool_id=%s", self.pool_id)
        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run one suite and return its outcome.

        The task carries either a pre-built ``suite`` (``EvalSuite``) or
        a ``dataset_path`` naming a JSONL file to load. The pre-built
        form is what the pool tests use; the path form is what an
        operator-facing caller uses.

        Args:
            task: The task specification.

        Returns:
            The run result, JSON-serialized.

        Raises:
            ValueError: If the task carries neither a suite nor a
                dataset path.
            EvalEngineError: If evaluation has been disabled.
        """
        self._require_enabled()
        suite = await self._resolve_suite(task)
        result = await self._engine.run_suite(suite)
        return result.model_dump(mode="json")

    async def execute_batch(
        self, tasks: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Run several suites.

        Sequential in Phase 1: each suite may spend real budget, and
        running them concurrently would make the per-run budget cap
        meaningless.

        Args:
            tasks: The task specifications.

        Returns:
            A mapping of task key to run result.
        """
        results: dict[str, dict[str, Any]] = {}
        for index, task in enumerate(tasks):
            key = str(task.get("task_id") or f"task-{index}")
            results[key] = await self.execute_task(task)
        return results

    async def scale(self, target_worker_count: int) -> None:
        """Reject a scale request.

        Eval has exactly one virtual worker. Scaling it is a
        configuration change (a different budget), not a runtime
        operation, so this refuses rather than pretending.

        Args:
            target_worker_count: The requested worker count.

        Raises:
            NotImplementedError: Always — eval pools do not scale.
        """
        raise NotImplementedError(
            f"eval pools have a single virtual worker; cannot scale to "
            f"{target_worker_count}. Adjust the eval budget instead."
        )

    async def health_check(self) -> dict[str, Any]:
        """Report the pool's health.

        Returns:
            A health dict in the shape ``BasePool.health_check``
            documents.
        """
        return {
            "pool_id": self.pool_id,
            "pool_type": "eval",
            "status": "healthy" if self._status == PoolStatus.RUNNING else "degraded",
            "workers_active": 1,
            "worker_health": {"virtual": {"status": "ok"}},
        }

    async def get_metrics(self) -> PoolMetrics:
        """Report the pool's metrics.

        Returns:
            The current metrics. Eval has one virtual worker and does
            not count tasks the way a worker pool does.
        """
        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=1,
            total_workers=1,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Return no memory artifacts.

        Eval's durable output is the run store, not a stream of
        per-worker memory dicts.

        Returns:
            An empty list.
        """
        return []

    async def stop(self) -> None:
        """Mark the pool stopped."""
        self._status = PoolStatus.STOPPED
        logger.info("eval pool stopped pool_id=%s", self.pool_id)

    def _require_enabled(self) -> None:
        """Refuse to run when evaluation is disabled.

        The MCP tools and this pool are both server-reachable, so both
        honour the operator's ``enabled`` kill-switch. A deployment that
        turns evaluation off expects no suites to run, whichever path
        asks.

        Raises:
            EvalEngineError: If evaluation has been disabled.
        """
        if not self._settings.enabled:
            raise EvalEngineError(
                "evaluation is disabled; set EvalSettings.enabled to true "
                "to run eval suites"
            )

    async def _resolve_suite(self, task: dict[str, Any]) -> EvalSuite:
        """Build the suite a task asks for.

        Args:
            task: The task specification.

        Returns:
            The suite to run.

        Raises:
            ValueError: If the task carries neither a suite nor a
                dataset path.
        """
        suite = task.get("suite")
        if isinstance(suite, EvalSuite):
            return suite

        dataset_path = task.get("dataset_path")
        if not dataset_path:
            raise ValueError(
                "eval task must carry a 'suite' (EvalSuite) or a "
                "'dataset_path' naming a JSONL dataset"
            )

        from mahavishnu.core.eval._registry import (
            discover_dataset_loaders,
            discover_scorers,
        )
        from mahavishnu.core.eval.paths import resolve_dataset_path

        loader_cls = discover_dataset_loaders()[
            self._settings.default_dataset_loader
        ]
        dataset = await loader_cls().load(
            resolve_dataset_path(
                str(dataset_path), self._settings.dataset_root
            )
        )
        scorer_registry = discover_scorers()
        scorers = []
        for name in self._settings.default_scorers:
            scorer_cls = scorer_registry.get(name)
            if scorer_cls is None:
                raise EvalEngineError(
                    f"unknown scorer {name!r}; available: "
                    f"{', '.join(sorted(scorer_registry)) or '(none registered)'}",
                    details={"name": name},
                )
            scorers.append(scorer_cls())
        return EvalSuite(
            name=str(task.get("name") or dataset.name),
            version=dataset.version,
            dataset=dataset,
            scorers=scorers,
            model=ModelConfig(
                name=str(task.get("model") or self._settings.default_model_backend)
            ),
            cost_budget=CostBudget(
                max_usd=self._settings.cost_budget_per_run,
                max_concurrency=DEFAULT_MAX_CONCURRENCY,
            ),
        )


def _build_eval_pool(
    config: PoolConfig,
    *,
    terminal_manager: Any,
    session_buddy_client: Any,
) -> EvalPool:
    """Build an :class:`EvalPool` from a pool configuration.

    The signature matches what ``PoolManager.spawn_pool`` calls: the
    config plus the manager's terminal manager and Session-Buddy client.
    Eval needs neither — it has no terminal substrate and does not
    aggregate worker memory — but the factory contract requires them.

    Args:
        config: The pool configuration.
        terminal_manager: Unused; required by the factory signature.
        session_buddy_client: Unused; required by the factory signature.

    Returns:
        The constructed pool.
    """
    settings = get_eval_settings()
    if not settings.enabled:
        raise EvalEngineError(
            "evaluation is disabled; set EvalSettings.enabled to true "
            "before spawning an eval pool"
        )
    storage_cls = discover_storage()[settings.default_storage]
    backend_cls = discover_model_backends()[settings.default_model_backend]
    return EvalPool(
        config=config,
        storage=storage_cls(db_path=settings.db_path),
        model_backend=backend_cls(),
        settings=settings,
    )


register_pool_type("eval", _build_eval_pool)


__all__ = ["EvalPool"]
