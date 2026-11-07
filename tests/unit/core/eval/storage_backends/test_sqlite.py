"""Contract tests for the SQLite run store (REQ-EVAL-002).

Validates:

- the ``start_run`` / ``add_case_result`` / ``finish_run`` / ``get_run`` /
  ``list_runs`` round-trip;
- a ``db_path`` whose parent directory does not exist is created;
- ten concurrent writes all land rather than locking each other out;
- a corrupt database file raises ``EvalStorageError``, not a raw driver
  exception;
- ``finish_run`` transitions a run out of the ``running`` state;
- ``get_run`` returns the run's case results.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from mahavishnu.core.errors import EvalStorageError
from mahavishnu.core.eval._registry import discover_storage
from mahavishnu.core.eval.storage import (
    CaseRecord,
    EvalSummary,
    RunRecord,
    ScoreRecord,
)
from mahavishnu.core.eval.storage_backends.sqlite import SqliteEvalStorage

if TYPE_CHECKING:
    from pathlib import Path


def _run(run_id: str, suite_name: str = "golden") -> RunRecord:
    """Build a running RunRecord."""
    return RunRecord(
        id=run_id,
        suite_name=suite_name,
        suite_version="v0",
        suite_hash="abc123",
        model_configs={"mahavishnu.mock": {"model": "mock"}},
        started_at=datetime.now(UTC),
    )


def _case(run_id: str, index: int) -> CaseRecord:
    """Build a scored CaseRecord belonging to a run."""
    return CaseRecord(
        id=uuid7().hex,
        run_id=run_id,
        case_id=f"case-{index}",
        case_index=index,
        actual="hello",
        scored=True,
    )


def _score(case: CaseRecord) -> ScoreRecord:
    """Build a ScoreRecord for a case result."""
    return ScoreRecord(
        id=uuid7().hex,
        case_id=case.id,
        scorer_name="mahavishnu.exact_match",
        value=1.0,
        kind="exact_match",
    )


def _summary() -> EvalSummary:
    """A finished run's summary."""
    return EvalSummary(
        total_cases=3,
        scored_cases=3,
        errors=0,
        duration_seconds=1.5,
        cost_usd=0.0,
        mean_score=1.0,
        min_score=1.0,
        max_score=1.0,
    )


@pytest.mark.req(["REQ-EVAL-002"])
async def test_round_trip(tmp_path: Path) -> None:
    """The full write-then-read cycle round-trips through the store."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    run_id = await storage.start_run(_run(uuid7().hex, suite_name="golden"))

    case = _case(run_id, 0)
    await storage.add_case_result(case, [_score(case)])
    await storage.finish_run(run_id, "completed", datetime.now(UTC), _summary())

    details = await storage.get_run(run_id)
    assert details is not None
    assert details.run.suite_name == "golden"
    assert details.run.status == "completed"
    assert len(details.case_results) == 1
    assert len(details.scores) == 1
    assert details.scores[0].scorer_name == "mahavishnu.exact_match"

    runs = await storage.list_runs()
    assert [run.id for run in runs] == [run_id]


@pytest.mark.req(["REQ-EVAL-002"])
async def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    """A db_path whose parent does not exist is created on first use."""
    db_path = tmp_path / "nested" / "deeper" / "runs.sqlite"
    storage = SqliteEvalStorage(db_path)

    await storage.start_run(_run(uuid7().hex))
    assert db_path.exists()


@pytest.mark.req(["REQ-EVAL-002"])
async def test_concurrent_writes_do_not_lock(tmp_path: Path) -> None:
    """Ten concurrent writes all land; WAL mode keeps them from locking."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    run_id = await storage.start_run(_run(uuid7().hex))

    async def write(index: int) -> None:
        case = _case(run_id, index)
        await storage.add_case_result(case, [_score(case)])

    await asyncio.gather(*(write(index) for index in range(10)))

    details = await storage.get_run(run_id)
    assert details is not None
    assert len(details.case_results) == 10
    assert len(details.scores) == 10


@pytest.mark.req(["REQ-EVAL-002"])
async def test_corrupt_database_raises_eval_storage_error(tmp_path: Path) -> None:
    """A corrupt database file raises EvalStorageError, not a driver error."""
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"this is definitely not a sqlite database" * 20)

    storage = SqliteEvalStorage(path)
    with pytest.raises(EvalStorageError):
        await storage.list_runs()


@pytest.mark.req(["REQ-EVAL-002"])
async def test_finish_run_transitions_the_status(tmp_path: Path) -> None:
    """finish_run moves a run from 'running' to its terminal status."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    run_id = await storage.start_run(_run(uuid7().hex))

    before = await storage.get_run(run_id)
    assert before is not None
    assert before.run.status == "running"

    await storage.finish_run(run_id, "completed", datetime.now(UTC), _summary())

    after = await storage.get_run(run_id)
    assert after is not None
    assert after.run.status == "completed"
    assert after.run.finished_at is not None


@pytest.mark.req(["REQ-EVAL-002"])
async def test_get_run_returns_the_case_results(tmp_path: Path) -> None:
    """get_run returns every case result of the run, in order."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    run_id = await storage.start_run(_run(uuid7().hex))
    for index in range(3):
        case = _case(run_id, index)
        await storage.add_case_result(case, [_score(case)])

    details = await storage.get_run(run_id)
    assert details is not None
    assert len(details.case_results) > 0
    assert [case.case_index for case in details.case_results] == [0, 1, 2]


@pytest.mark.req(["REQ-EVAL-002"])
async def test_get_run_returns_none_for_an_unknown_run(tmp_path: Path) -> None:
    """An unknown run id resolves to None."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    assert await storage.get_run(uuid7().hex) is None


@pytest.mark.req(["REQ-EVAL-002"])
async def test_finish_run_on_an_unknown_run_raises(tmp_path: Path) -> None:
    """Finishing a run that does not exist raises EvalStorageError."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    with pytest.raises(EvalStorageError):
        await storage.finish_run(
            uuid7().hex, "completed", datetime.now(UTC), _summary()
        )


@pytest.mark.req(["REQ-EVAL-002"])
def test_backend_is_discoverable() -> None:
    """The SQLite backend is discoverable through the registry."""
    assert discover_storage()["mahavishnu.sqlite"] is SqliteEvalStorage
