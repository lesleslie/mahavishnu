"""Markdown report writer for evaluation runs (REQ-EVAL-009).

A run's durable output is the SQLite store; this module renders the
same data as a Markdown file an operator can read, diff, and paste into
a review.

**No template engine.** The report is a table of sections built from
lists of lines. Jinja2 is not a dependency of this project, and adding
one to render four sections would be a worse trade than the twenty
lines it replaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mahavishnu.core.errors import EvalStorageError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from mahavishnu.core.eval.storage import CaseRecord, RunRecord, ScoreRecord

# req: REQ-EVAL-009


def _fmt_time(value: datetime | None) -> str:
    """Format a timestamp for the report.

    Args:
        value: The timestamp, or ``None``.

    Returns:
        An ISO-8601 string, or ``"-"`` when there is no timestamp.
    """
    return value.isoformat() if value is not None else "-"


def _fmt_optional(value: str | None) -> str:
    """Format an optional string for the report.

    Args:
        value: The string, or ``None``.

    Returns:
        The string, or ``"-"`` when it is absent.
    """
    return value if value else "-"


def _score_lines(
    case: CaseRecord,
    scores: Sequence[ScoreRecord],
) -> list[str]:
    """Render one case's scores as report lines.

    Args:
        case: The case result the scores belong to.
        scores: The scores, in the order they were produced.

    Returns:
        The report lines for the case's score block.
    """
    if not scores:
        return ["  - _no scores recorded_"]
    lines: list[str] = []
    for score in scores:
        reasoning = f" — {score.reasoning}" if score.reasoning else ""
        lines.append(f"  - `{score.scorer_name}` **{score.value:.3f}**{reasoning}")
    return lines


def _case_lines(
    case: CaseRecord,
    scores_by_case: dict[str, list[ScoreRecord]],
) -> list[str]:
    """Render one case result as report lines.

    Args:
        case: The case result.
        scores_by_case: The scores, keyed by ``CaseRecord.id``.

    Returns:
        The report lines for the case.
    """
    lines = [
        f"### Case {case.case_index + 1} — `{case.case_id}`",
        "",
        f"- **Result id**: `{case.id}`",
        f"- **Scored**: {'yes' if case.scored else 'no'}",
    ]
    if case.error:
        lines.append(f"- **Error**: `{case.error}`")
    lines.append("")
    lines.append("**Output**")
    lines.append("")
    lines.append("```text")
    lines.append(case.actual if case.actual else "(empty output)")
    lines.append("```")
    lines.append("")
    lines.append("**Scores**")
    lines.append("")
    lines.extend(_score_lines(case, scores_by_case.get(case.id, [])))
    lines.append("")
    return lines


def default_report_path(db_path: str | Path, run_id: str) -> Path:
    """Return the default path for a run's Markdown report.

    The report lives beside the run store, in a ``reports`` directory:
    ``<store dir>/reports/{run_id}.md``. Deriving it from the store's
    location keeps the two from drifting apart -- an operator who
    points ``db_path`` somewhere else gets their reports there too,
    not in the default location as well.

    Args:
        db_path: The run store's path.
        run_id: The run's id.

    Returns:
        The path the report belongs at.
    """
    return Path(db_path).expanduser().parent / "reports" / f"{run_id}.md"


def render_run_markdown(
    run: RunRecord,
    cases: Sequence[CaseRecord],
    scores: Sequence[ScoreRecord],
) -> str:
    """Render a run as Markdown.

    Args:
        run: The run record.
        cases: The run's case results.
        scores: The run's scores.

    Returns:
        The Markdown document.
    """
    summary = run.summary
    model_names = ", ".join(sorted(run.model_configs)) or "-"

    scores_by_case: dict[str, list[ScoreRecord]] = {}
    for score in scores:
        scores_by_case.setdefault(score.case_id, []).append(score)

    lines: list[str] = [
        f"# Eval run `{run.id}`",
        "",
        "## Header",
        "",
        f"- **Suite**: `{run.suite_name}` (version `{run.suite_version}`)",
        f"- **Dataset hash**: `{run.suite_hash}`",
        f"- **Model**: `{model_names}`",
        f"- **Status**: `{run.status}`",
        f"- **Started**: {_fmt_time(run.started_at)}",
        f"- **Finished**: {_fmt_time(run.finished_at)}",
        f"- **Duration**: {summary['duration_seconds']:.2f}s",
        "",
        "## Summary",
        "",
        f"- **Cases**: {summary['total_cases']}",
        f"- **Scored cases**: {summary['scored_cases']}",
        f"- **Errors**: {summary['errors']}",
        f"- **Mean score**: {summary['mean_score']:.3f}",
        f"- **Min score**: {summary['min_score']:.3f}",
        f"- **Max score**: {summary['max_score']:.3f}",
        f"- **Cost**: ${summary['cost_usd']:.4f}",
        "",
        "## Cases",
        "",
    ]

    if not cases:
        lines.extend(["_No case results were recorded._", ""])
    for case in sorted(cases, key=lambda item: item.case_index):
        lines.extend(_case_lines(case, scores_by_case))

    lines.extend(
        [
            "## Footer",
            "",
            f"- **Run id**: `{run.id}`",
            f"- **Case results**: {len(cases)}",
            f"- **Scores**: {len(scores)}",
            "",
        ]
    )
    return "\n".join(lines)


def write_run_markdown(
    run: RunRecord,
    cases: Sequence[CaseRecord],
    scores: Sequence[ScoreRecord],
    path: Path,
) -> Path:
    """Write a run's Markdown report to disk.

    Args:
        run: The run record.
        cases: The run's case results.
        scores: The run's scores.
        path: Where to write the report. Parent directories are created.

    Returns:
        The path written.

    Raises:
        EvalStorageError: If the report cannot be written.
    """
    document = render_run_markdown(run, cases, scores)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding="utf-8")
    except OSError as exc:
        raise EvalStorageError(
            f"cannot write eval report at {path}: {exc}",
            details={"path": str(path)},
        ) from exc
    return path


__all__ = [
    "default_report_path",
    "render_run_markdown",
    "write_run_markdown",
]
