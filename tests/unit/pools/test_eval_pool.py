"""Unit tests for the eval pool (REQ-EVAL-004).

The eval pool implements all eight ``BasePool`` abstract methods. A
subclass that omits any one of them cannot be instantiated, so the
first test here is the load-bearing one: it asserts the class has no
abstract methods left.

The rest cover the pool's contract: one virtual worker, no scaling, no
memory artifacts, and a factory whose signature matches what
``PoolManager.spawn_pool`` actually calls.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.errors import EvalEngineError
from mahavishnu.core.eval.dataset import Dataset, DatasetCase
from mahavishnu.core.eval.engine import EvalSuite, ModelConfig
from mahavishnu.core.eval.model_backends.mock import MockModelBackend
from mahavishnu.core.eval.settings import EvalSettings
from mahavishnu.core.eval.storage_backends.sqlite import SqliteEvalStorage
from mahavishnu.core.status import PoolStatus
from mahavishnu.pools._registry import get_pool_factory, list_pool_types
from mahavishnu.pools.base import PoolConfig, PoolMetrics
from mahavishnu.pools.eval_pool import EvalPool, _build_eval_pool

if TYPE_CHECKING:
    from pathlib import Path

# req: REQ-EVAL-004


def _config() -> PoolConfig:
    """A pool configuration for the eval pool."""
    return PoolConfig(name="eval-test", pool_type="eval", min_workers=1, max_workers=1)


def _suite() -> EvalSuite:
    """A one-case suite scored with the exact-match scorer."""
    from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer

    return EvalSuite(
        name="golden",
        version="v0",
        dataset=Dataset(
            name="golden",
            cases=[
                DatasetCase(id="case-0", input="hello", expected="hello", metadata={})
            ],
            content_hash="hash-1",
            version="v0",
        ),
        scorers=[ExactMatchScorer()],
        model=ModelConfig(name="mahavishnu.mock"),
    )


def _pool(tmp_path: Path) -> EvalPool:
    """Build an eval pool backed by a temporary run store."""
    settings = EvalSettings(
        enabled=True,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
        default_model_backend="mahavishnu.mock",
    )
    return EvalPool(
        config=_config(),
        storage=SqliteEvalStorage(tmp_path / "runs.sqlite"),
        model_backend=MockModelBackend(),
        settings=settings,
    )


@pytest.mark.req(["REQ-EVAL-004"])
def test_pool_implements_every_abstract_method() -> None:
    """The eval pool implements all eight BasePool abstract methods."""
    assert EvalPool.__abstractmethods__ == frozenset()


@pytest.mark.req(["REQ-EVAL-004"])
async def test_start_marks_the_pool_running(tmp_path: Path) -> None:
    """Starting the pool returns its id and flips the status."""
    pool = _pool(tmp_path)
    assert await pool.start() == pool.pool_id
    assert await pool.status() == PoolStatus.RUNNING


@pytest.mark.req(["REQ-EVAL-004"])
async def test_execute_task_runs_a_prebuilt_suite(tmp_path: Path) -> None:
    """A task carrying an EvalSuite runs it and returns the result."""
    pool = _pool(tmp_path)
    await pool.start()

    result = await pool.execute_task({"suite": _suite()})
    assert result["status"] == "completed"
    assert result["summary"]["total_cases"] == 1
    assert result["summary"]["mean_score"] == 1.0


@pytest.mark.req(["REQ-EVAL-004"])
async def test_execute_task_loads_a_dataset_from_a_path(
    tmp_path: Path,
) -> None:
    """A task carrying a dataset path loads it and runs the cases."""
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        '{"id": "c1", "input": "ping", "expected": "ping"}\n',
        encoding="utf-8",
    )
    pool = _pool(tmp_path)
    await pool.start()

    result = await pool.execute_task({"dataset_path": str(dataset_path)})
    assert result["status"] == "completed"
    assert result["summary"]["total_cases"] == 1


@pytest.mark.req(["REQ-EVAL-004"])
async def test_the_pool_scores_with_the_configured_default_scorers(
    tmp_path: Path,
) -> None:
    """The pool honours ``default_scorers`` like every other entry point.

    The mock backend echoes the prompt, so a dataset whose expectation
    is a *substring* of its input is the case that separates the
    scorers: ``contains`` scores it 1.0 and ``exact_match`` scores it
    0.0. Without this test the pool could hard-code the exact-match
    scorer and the whole suite would still pass -- which is what
    happened when this test was added.
    """
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        '{"id": "c1", "input": "ping-pong", "expected": "pong"}\n',
        encoding="utf-8",
    )
    settings = EvalSettings(
        enabled=True,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
        default_model_backend="mahavishnu.mock",
        default_scorers=["mahavishnu.contains"],
    )
    pool = EvalPool(
        config=_config(),
        storage=SqliteEvalStorage(tmp_path / "runs.sqlite"),
        model_backend=MockModelBackend(),
        settings=settings,
    )
    await pool.start()

    result = await pool.execute_task({"dataset_path": str(dataset_path)})
    assert result["status"] == "completed"
    assert result["summary"]["mean_score"] == 1.0


@pytest.mark.req(["REQ-EVAL-004"])
async def test_execute_task_without_a_suite_or_path_raises(tmp_path: Path) -> None:
    """A task with neither a suite nor a dataset path is rejected."""
    pool = _pool(tmp_path)
    await pool.start()

    with pytest.raises(ValueError, match="dataset_path"):
        await pool.execute_task({})


@pytest.mark.req(["REQ-EVAL-004"])
async def test_execute_batch_keys_results_by_task_id(tmp_path: Path) -> None:
    """A batch runs each task and keys the results by task id."""
    pool = _pool(tmp_path)
    await pool.start()

    results = await pool.execute_batch(
        [
            {"task_id": "first", "suite": _suite()},
            {"task_id": "second", "suite": _suite()},
        ]
    )
    assert set(results) == {"first", "second"}
    assert all(result["status"] == "completed" for result in results.values())


@pytest.mark.req(["REQ-EVAL-004"])
async def test_scale_is_refused(tmp_path: Path) -> None:
    """The eval pool has one virtual worker and does not scale."""
    pool = _pool(tmp_path)
    await pool.start()

    with pytest.raises(NotImplementedError, match="single virtual worker"):
        await pool.scale(4)


@pytest.mark.req(["REQ-EVAL-004"])
async def test_health_check_reports_healthy(tmp_path: Path) -> None:
    """A running eval pool reports healthy with one worker."""
    pool = _pool(tmp_path)
    await pool.start()

    health = await pool.health_check()
    assert health["pool_type"] == "eval"
    assert health["status"] == "healthy"
    assert health["workers_active"] == 1


@pytest.mark.req(["REQ-EVAL-004"])
async def test_get_metrics_reports_one_virtual_worker(tmp_path: Path) -> None:
    """The pool metrics report exactly one worker."""
    pool = _pool(tmp_path)
    await pool.start()

    metrics = await pool.get_metrics()
    assert isinstance(metrics, PoolMetrics)
    assert metrics.active_workers == 1
    assert metrics.total_workers == 1
    assert metrics.status == PoolStatus.RUNNING


@pytest.mark.req(["REQ-EVAL-004"])
async def test_collect_memory_is_empty(tmp_path: Path) -> None:
    """Eval produces no per-worker memory artifacts."""
    pool = _pool(tmp_path)
    await pool.start()

    assert await pool.collect_memory() == []


@pytest.mark.req(["REQ-EVAL-004"])
async def test_stop_marks_the_pool_stopped(tmp_path: Path) -> None:
    """Stopping the pool flips the status."""
    pool = _pool(tmp_path)
    await pool.start()
    await pool.stop()

    assert await pool.status() == PoolStatus.STOPPED


@pytest.mark.req(["REQ-EVAL-004"])
def test_pool_type_is_registered() -> None:
    """The eval pool is discoverable through the pool registry."""
    assert "eval" in list_pool_types()
    assert get_pool_factory("eval") is _build_eval_pool


@pytest.mark.req(["REQ-EVAL-004"])
def test_factory_matches_the_spawn_pool_call_signature() -> None:
    """The factory accepts exactly what ``spawn_pool`` passes it.

    ``PoolManager.spawn_pool`` calls
    ``factory(config=..., terminal_manager=..., session_buddy_client=...)``.
    A factory that does not accept those keyword arguments would fail
    at spawn time, not import time.
    """
    parameters = inspect.signature(_build_eval_pool).parameters
    assert set(parameters) == {"config", "terminal_manager", "session_buddy_client"}
    assert parameters["terminal_manager"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["session_buddy_client"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.req(["REQ-EVAL-004"])
async def test_the_pool_refuses_to_run_when_evaluation_is_disabled(
    tmp_path: Path,
) -> None:
    """A disabled evaluation stops the pool from running suites.

    The pool is a server-reachable path: a client can spawn one and
    execute tasks through it. The operator's ``enabled`` kill-switch has
    to hold on that path too, not only on the MCP tools.
    """
    settings = EvalSettings(
        enabled=False,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
    )
    pool = EvalPool(
        config=_config(),
        storage=SqliteEvalStorage(tmp_path / "runs.sqlite"),
        model_backend=MockModelBackend(),
        settings=settings,
    )

    with pytest.raises(EvalEngineError, match="evaluation is disabled"):
        await pool.start()
    with pytest.raises(EvalEngineError, match="evaluation is disabled"):
        await pool.execute_task({"suite": _suite()})


@pytest.mark.req(["REQ-EVAL-004"])
def test_the_factory_refuses_to_build_a_disabled_pool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The factory refuses to construct a pool when eval is off."""
    settings = EvalSettings(
        enabled=False,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
    )
    monkeypatch.setattr(
        "mahavishnu.core.eval.settings.get_eval_settings",
        lambda: settings,
    )

    with pytest.raises(EvalEngineError, match="evaluation is disabled"):
        _build_eval_pool(
            _config(),
            terminal_manager=None,
            session_buddy_client=None,
        )
