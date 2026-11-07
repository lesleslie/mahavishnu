"""Contract tests for the eval engine (REQ-EVAL-003).

Validates:

- a suite produces one case result and one score per case, and the run
  is persisted with a terminal status;
- the run result carries its id, status, finish time, and summary;
- budget arithmetic: landing exactly on the cap completes, spending past
  it is ``budget_exceeded``, and a first case that blows the budget stops
  the run before any other case runs;
- a case whose model call fails is recorded with its error and the run
  continues;
- each score references its own case result row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.errors import EvalEngineError, EvalStorageError
from mahavishnu.core.eval._registry import discover_model_backends
from mahavishnu.core.eval.dataset import Dataset, DatasetCase
from mahavishnu.core.eval.engine import (
    CostBudget,
    EvalEngine,
    EvalSuite,
    ModelConfig,
)
from mahavishnu.core.eval.model_backends.mock import MockModelBackend
from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer
from mahavishnu.core.eval.storage_backends.sqlite import SqliteEvalStorage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mahavishnu.core.eval.engine import ModelBackend, ModelResponse
    from mahavishnu.core.eval.storage import CaseRecord, ScoreRecord

#: At this price a five-character prompt costs exactly 2.00:
#: 1 input token + 1 output token at 1000.00 per 1000 tokens.
PRICE_PER_1K = 1000.0


def _dataset(prompts: list[str]) -> Dataset:
    """Build a dataset whose cases expect their own input."""
    return Dataset(
        name="golden",
        cases=[
            DatasetCase(id=f"case-{index}", input=prompt, expected=prompt, metadata={})
            for index, prompt in enumerate(prompts)
        ],
        content_hash=f"hash-{len(prompts)}",
        version="v0",
    )


def _suite(
    prompts: list[str],
    *,
    max_usd: float = 5.0,
    price_per_1k: float = 0.0,
) -> EvalSuite:
    """Build a suite that scores each case with the exact-match scorer."""
    return EvalSuite(
        name="golden",
        version="v0",
        dataset=_dataset(prompts),
        scorers=[ExactMatchScorer()],
        model=ModelConfig(
            name="mahavishnu.mock",
            input_cost_per_1k_tokens=price_per_1k,
            output_cost_per_1k_tokens=price_per_1k,
        ),
        cost_budget=CostBudget(max_usd=max_usd, max_concurrency=4),
    )


@pytest.mark.req(["REQ-EVAL-003"])
async def test_suite_produces_case_and_score_records(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A two-case suite records two case results and two scores."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)

    result = await engine.run_suite(_suite(["hello", "world"]))
    assert result.status == "completed"

    details = await storage.get_run(result.run_id)
    assert details is not None
    assert len(details.case_results) == 2
    assert len(details.scores) == 2
    assert details.run.status == "completed"
    assert all(record.scored for record in details.case_results)


@pytest.mark.req(["REQ-EVAL-003"])
async def test_result_is_fully_populated(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """The run result carries its id, status, finish time, and summary."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)

    result = await engine.run_suite(_suite(["hello"]))
    assert result.run_id
    assert result.status == "completed"
    assert result.finished_at is not None
    assert result.summary["total_cases"] == 1
    assert result.summary["scored_cases"] == 1
    assert result.summary["mean_score"] == 1.0


@pytest.mark.req(["REQ-EVAL-003"])
async def test_budget_landed_on_exactly_completes(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A run that lands exactly on 100% of its budget completes."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)
    suite = _suite(["hello", "world"], max_usd=4.0, price_per_1k=PRICE_PER_1K)

    result = await engine.run_suite(suite)
    assert result.status == "completed"
    assert result.summary["cost_usd"] == pytest.approx(4.0)


@pytest.mark.req(["REQ-EVAL-003"])
async def test_spending_past_the_budget_is_flagged(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A run that spends past its budget is marked budget_exceeded."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)
    suite = _suite(["hello", "world"], max_usd=3.0, price_per_1k=PRICE_PER_1K)

    result = await engine.run_suite(suite)
    assert result.status == "budget_exceeded"
    assert result.summary["cost_usd"] == pytest.approx(4.0)


@pytest.mark.req(["REQ-EVAL-003"])
async def test_first_case_over_the_whole_budget_stops_the_run(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A first case that blows the budget means no other case runs."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)
    suite = _suite(["hello", "world"], max_usd=1.0, price_per_1k=PRICE_PER_1K)

    result = await engine.run_suite(suite)
    assert result.status == "budget_exceeded"

    details = await storage.get_run(result.run_id)
    assert details is not None
    assert len(details.case_results) == 1


@pytest.mark.req(["REQ-EVAL-003"])
async def test_a_zero_budget_runs_no_case_and_is_not_completed(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A budget of zero executes nothing and says so.

    The caller asked for a zero budget, so the run cannot execute a
    case. Reporting that as ``completed`` would tell the caller the
    suite ran when not one case did -- and, because the MCP tool
    reports the cycle's case count to the health feed, a "successful"
    zero-case run is what a client uses to warm the feed with an
    empty entity count.
    """
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)
    suite = _suite(["hello", "world"], max_usd=0.0)

    result = await engine.run_suite(suite)

    assert result.status == "budget_exceeded"
    assert result.summary["total_cases"] == 0
    assert result.summary["cost_usd"] == 0.0

    details = await storage.get_run(result.run_id)
    assert details is not None
    assert details.run.status == "budget_exceeded"
    assert details.case_results == []


@pytest.mark.req(["REQ-EVAL-003"])
async def test_an_unhandled_failure_marks_the_run_failed(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """A storage failure leaves the run ``failed``, not ``running``.

    Without this the run row keeps ``status="running"`` and a NULL
    ``finished_at`` forever, and the case results already persisted
    are orphaned under a run that looks like it is still going.
    """

    class _FailingStorage(SqliteEvalStorage):
        """A store that fails on the second case result."""

        def __init__(self, db_path: Path) -> None:
            super().__init__(db_path)
            self._seen = 0

        async def add_case_result(
            self,
            case: CaseRecord,
            scores: Sequence[ScoreRecord] = (),
        ) -> None:
            self._seen += 1
            if self._seen == 2:
                raise EvalStorageError("simulated disk failure")
            await super().add_case_result(case, scores)

    storage = _FailingStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)

    with pytest.raises(EvalEngineError):
        await engine.run_suite(_suite(["hello", "world", "again"]))

    runs = await storage.list_runs(limit=10)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].finished_at is not None


@pytest.mark.req(["REQ-EVAL-003"])
async def test_a_failure_does_not_leak_the_cause_into_the_error(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """The raised error carries structure, not the failing layer's text.

    ``MahavishnuError.to_dict()`` serialises ``details`` into API
    responses, and an arbitrary exception's message can carry anything
    the failing layer put in it -- a connection string, a file path, a
    fragment of a credential. The cause belongs in the log; the client
    gets the run id and the counts.
    """

    class _LeakyStorage(SqliteEvalStorage):
        """A store whose failure message looks like a credential."""

        async def add_case_result(
            self,
            case: CaseRecord,
            scores: Sequence[ScoreRecord] = (),
        ) -> None:
            raise EvalStorageError(
                "connection failed: password=hunter2 db=eval-runs"
            )

    storage = _LeakyStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)

    with pytest.raises(EvalEngineError) as excinfo:
        await engine.run_suite(_suite(["hello", "world"]))

    error = excinfo.value
    assert "hunter2" not in str(error)
    assert "hunter2" not in repr(error.details)
    assert error.details["error_type"] == "EvalStorageError"
    assert error.details["run_id"]


@pytest.mark.req(["REQ-EVAL-003"])
async def test_failing_case_does_not_stop_the_run(tmp_path: Path) -> None:
    """A case whose model call fails is recorded and the run continues."""

    class _FailingBackend:
        async def complete(
            self, prompt: str, model_config: ModelConfig
        ) -> ModelResponse:
            if prompt == "boom":
                raise RuntimeError("model exploded")
            return await MockModelBackend().complete(prompt, model_config)

    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=_FailingBackend())

    result = await engine.run_suite(_suite(["hello", "boom", "world"]))
    assert result.status == "completed"

    details = await storage.get_run(result.run_id)
    assert details is not None
    assert len(details.case_results) == 3
    failed = [record for record in details.case_results if record.error]
    assert len(failed) == 1
    assert failed[0].error is not None
    assert "model exploded" in failed[0].error


@pytest.mark.req(["REQ-EVAL-003"])
async def test_scores_reference_their_own_case_result(
    tmp_path: Path,
    mock_model_backend: ModelBackend,
) -> None:
    """Each score's case_id is the id of its own case result row."""
    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=mock_model_backend)

    result = await engine.run_suite(_suite(["hello", "world"]))
    details = await storage.get_run(result.run_id)
    assert details is not None

    case_ids = {record.id for record in details.case_results}
    assert {score.case_id for score in details.scores} <= case_ids
    assert all(
        score.scorer_name == "mahavishnu.exact_match" for score in details.scores
    )


@pytest.mark.req(["REQ-EVAL-002"])
async def test_mock_backend_echoes_the_prompt() -> None:
    """The mock backend echoes the prompt and reports token counts."""
    response = await MockModelBackend().complete("hello", ModelConfig())
    assert response.output == "hello"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 1
    assert response.usage.completion_tokens == 1
    assert response.usage.total_tokens == 2
    assert response.latency_ms == 10.0


@pytest.mark.req(["REQ-EVAL-002"])
def test_mock_backend_is_discoverable() -> None:
    """The mock backend is discoverable through the registry."""
    assert discover_model_backends()["mahavishnu.mock"] is MockModelBackend


@pytest.mark.req(["REQ-EVAL-003"])
async def test_the_operators_budget_caps_a_larger_suite_budget(
    tmp_path: Path,
) -> None:
    """A suite that asks for a bigger budget is held to the operator's.

    The suite's ``CostBudget`` is a request; the operator's
    ``cost_budget_per_run`` is a ceiling. Without the clamp, a caller
    that names a large budget spends money nobody authorised.
    """
    from mahavishnu.core.eval.settings import EvalSettings

    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    settings = EvalSettings(
        enabled=True,
        db_path=str(tmp_path / "runs.sqlite"),
        cost_budget_per_run=2.0,
    )
    engine = EvalEngine(
        storage=storage,
        model_backend=MockModelBackend(),
        settings=settings,
    )
    suite = _suite(["hello", "world", "again", "more"])
    suite.cost_budget = CostBudget(max_usd=1000.0, max_concurrency=4)
    suite.model = ModelConfig(
        name="mahavishnu.mock",
        input_cost_per_1k_tokens=PRICE_PER_1K,
        output_cost_per_1k_tokens=PRICE_PER_1K,
    )

    result = await engine.run_suite(suite)

    # Each case costs 2.00 at this price, so the operator's 2.00 cap
    # stops the run after the first case. Without the clamp all four
    # would run and the run would have cost 8.00.
    assert result.summary["total_cases"] == 1
    assert result.summary["cost_usd"] == pytest.approx(2.0)
    # Landing exactly on the cap is a completed run, not an overrun:
    # the engine only flags `budget_exceeded` when the spend goes
    # strictly past the cap.
    assert result.status == "completed"
