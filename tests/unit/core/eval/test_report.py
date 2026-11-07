"""Contract tests for the Markdown report writer (REQ-EVAL-009).

The report is the run's human-readable face. These tests pin the
sections it carries, the per-case detail, and the failure mode where
the file cannot be written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mahavishnu.core.errors import EvalStorageError
from mahavishnu.core.eval.report import (
    default_report_path,
    render_run_markdown,
    write_run_markdown,
)
from mahavishnu.core.eval.storage import (
    CaseRecord,
    RunRecord,
    ScoreRecord,
)

# req: REQ-EVAL-009


def _run() -> RunRecord:
    """A finished run with one case."""
    return RunRecord(
        id="run-1",
        suite_name="golden",
        suite_version="v0",
        suite_hash="hash-1",
        model_configs={"mahavishnu.mock": {"name": "mahavishnu.mock"}},
        started_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 11, 6, 12, 0, 5, tzinfo=UTC),
        status="completed",
        summary={
            "total_cases": 1,
            "scored_cases": 1,
            "errors": 0,
            "duration_seconds": 5.0,
            "cost_usd": 0.25,
            "mean_score": 1.0,
            "min_score": 1.0,
            "max_score": 1.0,
        },
    )


def _case() -> CaseRecord:
    """One scored case result."""
    return CaseRecord(
        id="case-row-1",
        run_id="run-1",
        case_id="dataset-case-1",
        case_index=0,
        actual="the answer",
        scored=True,
    )


def _score() -> ScoreRecord:
    """One score for the case."""
    return ScoreRecord(
        id="score-1",
        case_id="case-row-1",
        scorer_name="mahavishnu.contains",
        value=1.0,
        kind="contains",
        reasoning=None,
    )


@pytest.mark.req(["REQ-EVAL-009"])
def test_the_report_carries_every_section() -> None:
    """The report has a header, a summary, the cases, and a footer."""
    document = render_run_markdown(_run(), [_case()], [_score()])
    assert "# Eval run `run-1`" in document
    assert "## Header" in document
    assert "## Summary" in document
    assert "## Cases" in document
    assert "## Footer" in document


@pytest.mark.req(["REQ-EVAL-009"])
def test_the_report_carries_the_summary_numbers() -> None:
    """The summary section carries the run's aggregate statistics."""
    document = render_run_markdown(_run(), [_case()], [_score()])
    assert "**Cases**: 1" in document
    assert "**Mean score**: 1.000" in document
    assert "**Cost**: $0.2500" in document
    assert "**Status**: `completed`" in document


@pytest.mark.req(["REQ-EVAL-009"])
def test_the_report_carries_the_case_detail_and_its_scores() -> None:
    """Each case section carries the output and the scorer's verdict."""
    document = render_run_markdown(_run(), [_case()], [_score()])
    assert "### Case 1 — `dataset-case-1`" in document
    assert "the answer" in document
    assert "`mahavishnu.contains`" in document
    assert "**1.000**" in document


@pytest.mark.req(["REQ-EVAL-009"])
def test_a_failing_case_shows_its_error() -> None:
    """A case that errored shows the error in its section."""
    case = _case().model_copy(update={"error": "model exploded", "scored": False})
    document = render_run_markdown(_run(), [case], [])
    assert "model exploded" in document
    assert "_no scores recorded_" in document


@pytest.mark.req(["REQ-EVAL-009"])
def test_a_run_with_no_cases_still_renders() -> None:
    """A run with no case results renders a report that says so."""
    document = render_run_markdown(_run(), [], [])
    assert "_No case results were recorded._" in document
    assert "**Case results**: 0" in document


@pytest.mark.req(["REQ-EVAL-009"])
def test_the_writer_creates_parent_directories(tmp_path: Path) -> None:
    """Writing the report creates the directories it needs."""
    path = tmp_path / "nested" / "reports" / "run-1.md"
    written = write_run_markdown(_run(), [_case()], [_score()], path)
    assert written == path
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# Eval run")


@pytest.mark.req(["REQ-EVAL-009"])
def test_an_unwritable_path_raises_an_eval_storage_error(
    tmp_path: Path,
) -> None:
    """A report that cannot be written raises the typed error."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(EvalStorageError):
        write_run_markdown(_run(), [_case()], [_score()], blocker / "run-1.md")


@pytest.mark.req(["REQ-EVAL-009"])
def test_the_default_report_path_sits_beside_the_run_store() -> None:
    """The default report path is derived from the store's location."""
    path = default_report_path("~/.local/state/mahavishnu/eval/runs.sqlite", "run-1")
    assert path.name == "run-1.md"
    assert path.parent.name == "reports"
    assert path.parent.parent == Path("~/.local/state/mahavishnu/eval").expanduser()
