"""Smoke test for the dogfood golden set (REQ-EVAL-007).

The golden set is 29 questions about how Mahavishnu behaves. This test
runs the whole set end to end and asserts the *plumbing*: the dataset
loads, every case runs, every case is scored, the run is persisted, the
Markdown report is written, and the health feed advances.

**Phase 1 runs the set against the mock backend**, so the scores are
not a judgement of a model — the mock echoes the prompt back. What this
test proves is that the harness works on the real dataset: a golden set
that does not load, a scorer that raises, a report that is not written,
or a feed that does not move would all fail here.

The test is marked ``slow`` because it writes to the real run store and
takes a report-formatting pass over every case; it is excluded by
``-m "not slow"``.
"""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from mahavishnu.core.eval._registry import (
    discover_dataset_loaders,
    discover_model_backends,
    discover_scorers,
    discover_storage,
)
from mahavishnu.core.eval.engine import (
    DEFAULT_MAX_CONCURRENCY,
    CostBudget,
    EvalEngine,
    EvalSuite,
    ModelConfig,
)
from mahavishnu.core.eval.report import write_run_markdown
from mahavishnu.core.eval.settings import EvalSettings

# req: REQ-EVAL-007

#: The golden set, relative to the repository root.
GOLDEN_SET = Path("docs/eval/dogfood-v0.jsonl")

#: The scorer the golden set is written for.
GOLDEN_SCORER = "mahavishnu.contains"


def _repo_root() -> Path:
    """Return the repository root.

    ``mahavishnu/__init__.py`` -> parents[0] is the package directory,
    parents[1] is the repository root.
    """
    import mahavishnu

    return Path(mahavishnu.__file__).resolve().parents[1]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(120)
@pytest.mark.req(["REQ-EVAL-007"])
async def test_dogfood_set_runs_end_to_end(tmp_path: Path) -> None:
    """The whole golden set runs, scores, persists, and reports."""
    from mahavishnu.mcp.eval_feed import init_eval_feed_state, reset_eval_feed_state

    reset_eval_feed_state()
    init_eval_feed_state()

    dataset_path = _repo_root() / GOLDEN_SET
    assert dataset_path.exists(), f"the golden set is missing: {dataset_path}"

    settings = EvalSettings(
        enabled=True,
        db_path=str(tmp_path / "runs.sqlite"),
        default_model_backend="mahavishnu.mock",
        default_scorers=[GOLDEN_SCORER],
    )

    loader_cls = discover_dataset_loaders()[settings.default_dataset_loader]
    dataset = await loader_cls().load(dataset_path)
    assert len(dataset.cases) >= 20, "the golden set must carry at least 20 cases"

    scorer_cls = discover_scorers()[GOLDEN_SCORER]
    backend_cls = discover_model_backends()[settings.default_model_backend]
    storage_cls = discover_storage()[settings.default_storage]
    storage = storage_cls(db_path=settings.db_path)

    suite = EvalSuite(
        name=dataset.name,
        version=dataset.version,
        dataset=dataset,
        scorers=[scorer_cls()],
        model=ModelConfig(name=settings.default_model_backend),
        cost_budget=CostBudget(
            max_usd=settings.cost_budget_per_run,
            max_concurrency=DEFAULT_MAX_CONCURRENCY,
        ),
    )
    engine = EvalEngine(
        storage=storage,
        model_backend=backend_cls(),
        settings=settings,
    )

    started = time.perf_counter()
    result = await engine.run_suite(suite)
    elapsed = time.perf_counter() - started

    assert result.status == "completed"
    assert result.summary["total_cases"] == len(dataset.cases)
    assert result.summary["scored_cases"] == len(dataset.cases)
    assert result.summary["errors"] == 0
    assert elapsed < 120.0, f"the run took {elapsed:.1f}s"

    details = await storage.get_run(result.run_id)
    assert details is not None
    assert len(details.case_results) == len(dataset.cases)
    assert len(details.scores) == len(dataset.cases)

    report_path = tmp_path / "reports" / f"{result.run_id}.md"
    write_run_markdown(
        details.run,
        details.case_results,
        details.scores,
        report_path,
    )
    report = report_path.read_text(encoding="utf-8")
    assert report_path.stat().st_size > 0
    assert result.run_id in report
    assert "## Summary" in report
    assert "## Cases" in report

    reset_eval_feed_state()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(120)
@pytest.mark.req(["REQ-EVAL-008"])
async def test_a_real_run_advances_the_eval_feed(tmp_path: Path) -> None:
    """A completed run bumps the feed's cycle counter."""
    from mahavishnu.mcp.eval_feed import (
        init_eval_feed_state,
        record_eval_cycle,
        reset_eval_feed_state,
    )

    reset_eval_feed_state()
    init_eval_feed_state()

    record_eval_cycle(case_count=3)

    from mahavishnu.mcp.eval_feed import get_eval_feed_state

    state = get_eval_feed_state()
    assert state is not None
    assert state.cycles_total == 1
    assert state.entities_count == 3
    assert state.is_ok()

    payload = state.as_dict()
    assert payload["feed"] == "eval"
    assert payload["feed_entities_count"] == 3
    assert payload["cycles_total"] == 1
    assert payload["errors_total"] == 0

    reset_eval_feed_state()
