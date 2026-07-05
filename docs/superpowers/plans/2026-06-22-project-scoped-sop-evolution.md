# Project-Scoped SOP Evolution v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship per-deployment SOP evolution — per-case retrospectives record fired failure modes; weekly cron aggregates, surfaces SOP suggestions when threshold crossed; operators review via CLI.

**Architecture:** `mahavishnu/core/retrospective.py` catalogs fired modes from Spec #1 reports. `mahavishnu/core/sop_synthesizer.py` aggregates retrospectives and generates suggestion text. CLI surfaces suggestions. SOP file at `~/.mahavishnu/sop.md` is read by agents (Spec #1-3 prompt injection) and Spec #6 fallback.

**Tech Stack:** Python 3.13, Dhara (existing), `pathlib`, typer, pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **Threshold**: 3/10 → suggestion, 6/10 → alert (article-calibrated).
- **Failure modes** derived from Phase 1-3 gate outputs.
- **Cron cadence**: weekly (configurable in v1.1).
- **No autonomous SOP mutation** — operator reviews before changes apply.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/retrospective.py` | `_catalog_fired_modes`, `record_retrospective`. |
| `mahavishnu/core/sop_synthesizer.py` | `_recent_retrospectives`, `_frequency_counts`, `_generate_suggestion_text`, `synthesize_sop_suggestions`. |
| `mahavishnu/core/dhara_migrations/case_retrospectives.sql` | DDL for retrospectives table. |
| `mahavishnu/cli/sop_synthesizer_cli.py` | `mahavishnu sop {show-suggestions, review-suggestion, record-retrospective}` CLI. |
| `mahavishnu/templates/sop.md` | Default SOP template. |
| `tests/unit/test_retrospective.py` | L0 tests. |
| `tests/unit/test_sop_synthesizer.py` | L0 tests. |
| `tests/integration/test_sop_evolution.py` | L3 tests. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/cli/__init__.py` | Register `sop_app`. |

______________________________________________________________________

## Task 1: Dhara migration for `case_retrospectives` table

**Files:**

- Create: `mahavishnu/core/dhara_migrations/case_retrospectives.sql`

- [ ] **Step 1: Write the DDL**

Create `mahavishnu/core/dhara_migrations/case_retrospectives.sql`:

```sql
CREATE TABLE IF NOT EXISTS case_retrospectives (
    retrospective_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    fired_modes TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    recorded_by TEXT NOT NULL DEFAULT 'system:cron'
);

CREATE INDEX IF NOT EXISTS idx_case_retrospectives_time
    ON case_retrospectives (recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_case_retrospectives_workflow
    ON case_retrospectives (workflow_id);
```

- [ ] **Step 2: Apply the migration**

Run the project's Dhara migration runner (or `execute()` the SQL directly):

```python
from mahavishnu.core.dhara_client import execute
with open("mahavishnu/core/dhara_migrations/case_retrospectives.sql") as f:
    execute(f.read())
```

Expected: table and indexes created.

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/core/dhara_migrations/case_retrospectives.sql
git commit -m "feat(sop): add case_retrospectives audit table migration"
```

______________________________________________________________________

## Task 2: Implement retrospective module

**Files:**

- Create: `mahavishnu/core/retrospective.py`

- Test: `tests/unit/test_retrospective.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_retrospective.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from mahavishnu.core.retrospective import _catalog_fired_modes


def _iter_report(idx: int, **overrides) -> dict:
    base = {
        "iteration_index": idx,
        "precommitment_slate": None,
        "confidence_was_capped": False,
        "unchecked_sources": [],
        "adjacent_problems": [],
    }
    base.update(overrides)
    return base


def _workflow_report(**overrides) -> dict:
    base = {
        "workflow_id": "wf-1",
        "exit_reason": "complete",
        "iteration_count": 1,
    }
    base.update(overrides)
    return base


def test_catalogs_schema_violation_exit_reason():
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report(exit_reason="schema_violation")),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "schema_validation" in fired


def test_catalogs_precommitment_violation_at_iter_nonzero():
    iter_report = _iter_report(1, precommitment_slate={"hypotheses": ["h"] * 6, "evaluation_criteria": ["c"] * 4, "frozen_at": "2026-06-22T10:00:00Z"})
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[iter_report]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report()),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "precommitment_violation" in fired


def test_catalogs_confidence_capped():
    iter_report = _iter_report(0, confidence_was_capped=True)
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[iter_report]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report()),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "confidence_capped" in fired


def test_catalogs_data_gathering_skipped():
    iter_report = _iter_report(0, unchecked_sources=[{"name": "x", "access_status": "skipped_inferred"}])
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[iter_report]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report()),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "data_gathering_skipped" in fired


def test_catalogs_analysis_completeness():
    iter_report = _iter_report(0, adjacent_problems=[{"summary": "x", "status": "open"}])
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[iter_report]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report()),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "analysis_completeness" in fired


def test_catalogs_self_heal_exhausted():
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[]),
        patch("mahavishnu.core.retrospective.get_workflow_report",
              return_value=_workflow_report(exit_reason="heal_exhausted")),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert "self_heal_exhausted" in fired


def test_empty_when_no_reports():
    with (
        patch("mahavishnu.core.retrospective.get_iteration_history", return_value=[]),
        patch("mahavishnu.core.retrospective.get_workflow_report", return_value=None),
    ):
        fired = _catalog_fired_modes("wf-1")
    assert fired == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_retrospective.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the retrospective module**

Create `mahavishnu/core/retrospective.py`:

```python
"""Per-case retrospective: catalogs which failure modes fired in a workflow."""

from __future__ import annotations

import uuid

from mahavishnu.core.dhara_client import execute
from mahavishnu.core.events.subscribers.report_persister import (
    get_iteration_history,
    get_workflow_report,
)


def _catalog_fired_modes(workflow_id: str) -> list[str]:
    """Inspect persisted reports to determine which failure modes fired."""
    fired: list[str] = []
    history = get_iteration_history(workflow_id)
    workflow_report = get_workflow_report(workflow_id)
    if not history or not workflow_report:
        return fired

    if workflow_report.get("exit_reason") == "schema_violation":
        fired.append("schema_validation")

    if any(
        it.get("precommitment_slate") and it.get("iteration_index", 0) > 0
        for it in history
    ):
        fired.append("precommitment_violation")

    if any(it.get("confidence_was_capped") for it in history):
        fired.append("confidence_capped")

    if workflow_report.get("exit_reason") == "heal_exhausted":
        fired.append("self_heal_exhausted")

    if any(
        s.get("access_status") == "skipped_inferred"
        for it in history
        for s in it.get("unchecked_sources", [])
    ):
        fired.append("data_gathering_skipped")

    if any(
        p.get("status") == "open"
        for it in history
        for p in it.get("adjacent_problems", [])
    ):
        fired.append("analysis_completeness")

    return fired


def record_retrospective(workflow_id: str, *, operator: str = "system:cron") -> None:
    """Record this case's retrospective in Dhara."""
    fired = _catalog_fired_modes(workflow_id)
    execute(
        "INSERT INTO case_retrospectives "
        "(retrospective_id, workflow_id, fired_modes, recorded_at, recorded_by) "
        "VALUES (?, ?, ?, datetime('now'), ?)",
        (str(uuid.uuid4()), workflow_id, ",".join(fired), operator),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_retrospective.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/retrospective.py tests/unit/test_retrospective.py
git commit -m "feat(sop): add per-case retrospective recording fired failure modes"
```

______________________________________________________________________

## Task 3: Implement SOP synthesizer

**Files:**

- Create: `mahavishnu/core/sop_synthesizer.py`

- Test: `tests/unit/test_sop_synthesizer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sop_synthesizer.py`:

```python
from __future__ import annotations

from collections import Counter
from unittest.mock import patch

import pytest

from mahavishnu.core.sop_synthesizer import (
    _frequency_counts,
    _generate_suggestion_text,
    _recent_retrospectives,
    synthesize_sop_suggestions,
    WINDOW,
)


def test_frequency_counts_aggregates_modes():
    retros = [
        {"workflow_id": "1", "modes": ["schema_validation", "confidence_capped"]},
        {"workflow_id": "2", "modes": ["schema_validation"]},
        {"workflow_id": "3", "modes": ["confidence_capped", "analysis_completeness"]},
    ]
    counts = _frequency_counts(retros)
    assert counts["schema_validation"] == 2
    assert counts["confidence_capped"] == 2
    assert counts["analysis_completeness"] == 1


def test_suggestion_text_for_known_mode():
    text = _generate_suggestion_text("schema_validation", 4)
    assert "schema_validation" in text
    assert "4/10" in text


def test_suggestion_text_for_unknown_mode_falls_back():
    text = _generate_suggestion_text("unknown_mode_xyz", 5)
    assert "unknown_mode_xyz" in text


def test_synthesize_no_suggestions_below_threshold():
    retros = [
        {"workflow_id": str(i), "modes": ["schema_validation"]}
        for i in range(WINDOW)
    ]
    with patch("mahavishnu.core.sop_synthesizer._recent_retrospectives", return_value=retros):
        suggestions = synthesize_sop_suggestions()
    # 10/10 = above alert threshold
    assert any(s["severity"] == "alert" and s["mode"] == "schema_validation" for s in suggestions)


def test_synthesize_filters_below_threshold():
    retros = [{"workflow_id": str(i), "modes": []} for i in range(WINDOW)]
    with patch("mahavishnu.core.sop_synthesizer._recent_retrospectives", return_value=retros):
        suggestions = synthesize_sop_suggestions()
    assert suggestions == []


def test_synthesize_severity_at_suggestion_threshold():
    retros = [
        {"workflow_id": str(i), "modes": ["confidence_capped"] if i < 3 else []}
        for i in range(WINDOW)
    ]
    with patch("mahavishnu.core.sop_synthesizer._recent_retrospectives", return_value=retros):
        suggestions = synthesize_sop_suggestions()
    conf_suggestions = [s for s in suggestions if s["mode"] == "confidence_capped"]
    assert len(conf_suggestions) == 1
    assert conf_suggestions[0]["severity"] == "suggestion"


def test_synthesize_severity_at_alert_threshold():
    retros = [
        {"workflow_id": str(i), "modes": ["confidence_capped"] if i < 6 else []}
        for i in range(WINDOW)
    ]
    with patch("mahavishnu.core.sop_synthesizer._recent_retrospectives", return_value=retros):
        suggestions = synthesize_sop_suggestions()
    conf_suggestions = [s for s in suggestions if s["mode"] == "confidence_capped"]
    assert len(conf_suggestions) == 1
    assert conf_suggestions[0]["severity"] == "alert"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_sop_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the synthesizer**

Create `mahavishnu/core/sop_synthesizer.py`:

```python
"""SOP synthesizer: aggregates retrospectives and generates suggestions."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from mahavishnu.core.dhara_client import query


SOP_PATH = Path.home() / ".mahavishnu" / "sop.md"
SOP_STAGING_PATH = Path.home() / ".mahavishnu" / "sop.staging.md"
SUGGESTION_THRESHOLD = 3
ALERT_THRESHOLD = 6
WINDOW = 10


def _recent_retrospectives(limit: int = WINDOW) -> list[dict]:
    rows = query(
        "SELECT workflow_id, fired_modes FROM case_retrospectives "
        "ORDER BY recorded_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {"workflow_id": row["workflow_id"], "modes": row["fired_modes"].split(",")}
        for row in rows
    ]


def _frequency_counts(retrospectives: list[dict]) -> Counter:
    counts: Counter = Counter()
    for r in retrospectives:
        for mode in r["modes"]:
            if mode:
                counts[mode] += 1
    return counts


def _generate_suggestion_text(mode: str, count: int) -> str:
    templates = {
        "schema_validation": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Always validate report structure against the canonical JSON Schema "
            "before publish_iteration_report."
        ),
        "precommitment_violation": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Always populate precommitment_slate at iteration_index=0 with "
            "≥6 hypotheses and ≥4 evaluation criteria."
        ),
        "confidence_capped": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Report confidence should account for open_questions and "
            "unchecked_sources before declaring high confidence."
        ),
        "self_heal_exhausted": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Pre-validate the operation's preconditions before invoking L1/L2 self-heal."
        ),
        "data_gathering_skipped": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Always run the direct query before marking sources as skipped_inferred."
        ),
        "analysis_completeness": (
            f"Mode `{mode}` fired {count}/{WINDOW} times. "
            "Trace root causes all the way through before declaring investigation "
            "complete; resolve or wont_fix all adjacent_problems."
        ),
    }
    return templates.get(mode, f"Mode `{mode}` fired {count}/{WINDOW} times.")


def synthesize_sop_suggestions() -> list[dict]:
    retrospectives = _recent_retrospectives(WINDOW)
    counts = _frequency_counts(retrospectives)
    suggestions: list[dict] = []

    for mode, count in counts.items():
        if count < SUGGESTION_THRESHOLD:
            continue
        severity = "alert" if count >= ALERT_THRESHOLD else "suggestion"
        suggestions.append({
            "mode": mode,
            "count": count,
            "severity": severity,
            "suggested_text": _generate_suggestion_text(mode, count),
            "window_size": len(retrospectives),
        })
    return suggestions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_sop_synthesizer.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/sop_synthesizer.py tests/unit/test_sop_synthesizer.py
git commit -m "feat(sop): add SOP synthesizer with threshold-based suggestion generation"
```

______________________________________________________________________

## Task 4: CLI commands

**Files:**

- Create: `mahavishnu/cli/sop_synthesizer_cli.py`

- Modify: `mahavishnu/cli/__init__.py`

- Test: `tests/integration/test_sop_evolution.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_sop_evolution.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from mahavishnu.cli.sop_synthesizer_cli import sop_app


def test_show_suggestions_no_suggestions():
    with patch("mahavishnu.cli.sop_synthesizer_cli.synthesize_sop_suggestions", return_value=[]):
        result = CliRunner().invoke(sop_app, ["show-suggestions"])
    assert result.exit_code == 0
    assert "No SOP suggestions" in result.output


def test_show_suggestions_outputs_suggestions():
    suggestions = [
        {
            "mode": "schema_validation",
            "count": 5,
            "severity": "suggestion",
            "suggested_text": "Always validate report structure",
            "window_size": 10,
        }
    ]
    with patch("mahavishnu.cli.sop_synthesizer_cli.synthesize_sop_suggestions", return_value=suggestions):
        result = CliRunner().invoke(sop_app, ["show-suggestions"])
    assert result.exit_code == 0
    assert "schema_validation" in result.output
    assert "5/10" in result.output


def test_record_retrospective_invokes_function():
    with patch("mahavishnu.cli.sop_synthesizer_cli.record_retrospective") as mock:
        result = CliRunner().invoke(sop_app, ["record-retrospective", "wf-123"])
    assert result.exit_code == 0
    mock.assert_called_once_with("wf-123", operator="system:cli")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sop_evolution.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the CLI**

Create `mahavishnu/cli/sop_synthesizer_cli.py`:

```python
"""Project SOP evolution CLI."""

from __future__ import annotations

import typer

from mahavishnu.core.sop_synthesizer import synthesize_sop_suggestions


sop_app = typer.Typer(help="Project SOP evolution")


@sop_app.command("show-suggestions")
def show_suggestions(
    window: int = typer.Option(10, "--window", help="Cases to consider"),
) -> None:
    """Show current SOP suggestions based on recent retrospectives."""
    suggestions = synthesize_sop_suggestions()
    if not suggestions:
        typer.echo("No SOP suggestions.")
        return
    for s in suggestions:
        typer.echo(
            f"[{s['severity'].upper()}] {s['mode']}: "
            f"{s['count']}/{s['window_size']} ({s['suggested_text']})"
        )


@sop_app.command("review-suggestion")
def review_suggestion(
    mode: str = typer.Argument(help="Failure mode to review"),
    decision: str = typer.Option(..., "--decision", help="accept|reject|hold"),
) -> None:
    """Operator decision on a SOP suggestion. Stages the change via Spec #5."""
    if decision not in ("accept", "reject", "hold"):
        typer.echo(f"Invalid decision: {decision}")
        raise typer.Exit(code=1)
    typer.echo(f"Recorded decision '{decision}' for mode '{mode}'.")
    # v1.0: just log. v1.1: integrate with Spec #5 three-zone pipeline.


@sop_app.command("record-retrospective")
def record_retrospective(
    workflow_id: str = typer.Argument(help="Workflow ID to record retrospective for"),
) -> None:
    """Manually trigger retrospective recording for a workflow."""
    from mahavishnu.core.retrospective import record_retrospective
    record_retrospective(workflow_id, operator="system:cli")
    typer.echo(f"Recorded retrospective for {workflow_id}")
```

Register in `mahavishnu/cli/__init__.py`:

```python
from mahavishnu.cli.sop_synthesizer_cli import sop_app

main_app.add_typer(sop_app, name="sop")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_sop_evolution.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/sop_synthesizer_cli.py mahavishnu/cli/__init__.py tests/integration/test_sop_evolution.py
git commit -m "feat(sop): add CLI for SOP evolution (show-suggestions, review-suggestion, record-retrospective)"
```

______________________________________________________________________

## Task 5: Default SOP template

**Files:**

- Create: `mahavishnu/templates/sop.md`

- [ ] **Step 1: Create the template**

Create `mahavishnu/templates/sop.md`:

```markdown
---
failure_modes:
  schema_validation:
    description: "IterationReport or WorkflowReport failed JSON Schema validation"
    category: quality_gate
  precommitment_violation:
    description: "IterationReport at iter 0 missing/invalid slate, or iter >0 has slate"
    category: quality_gate
  confidence_capped:
    description: "Self-reported confidence exceeded computed ceiling"
    category: quality_gate
  self_heal_exhausted:
    description: "L2 bounded agentic heal exhausted without success"
    category: quality_gate
  data_gathering_skipped:
    description: "Investigation skipped accessible data sources"
    category: data_gathering
  analysis_completeness:
    description: "Root cause not traced all the way through"
    category: analysis_completeness
---

# Project SOP — Mahavishnu default

This SOP is loaded by Spec #1-3 paths and Spec #6 default fallback.
The cron-based synthesizer (mahavishnu.core.sop_synthesizer) generates
suggestions based on per-case retrospectives; operators review via
`mahavishnu sop show-suggestions` and apply changes.

## Investigation patterns

When investigating support tickets or operational issues, always:

1. Check the relevant data sources directly before inferring schema.
2. Trace root causes all the way through (no symptom-level findings).
3. Resolve or wont_fix all adjacent problems before declaring complete.

## Quality gates

When producing reports:

1. Populate precommitment_slate at iteration_index=0 with ≥6 hypotheses
   and ≥4 evaluation criteria.
2. Report confidence should account for open_questions and unchecked_sources.
3. Validate report structure against the canonical JSON Schema before publish.

## Editing this SOP

Operators can edit this file directly at `~/.mahavishnu/sop.md`.
The cron synthesizer writes suggestions to `~/.mahavishnu/sop.staging.md`;
review with `mahavishnu sop show-suggestions` and apply changes manually
(v1.0) or via `mahavishnu sop review-suggestion --decision accept` (v1.1+).
```

- [ ] **Step 2: Commit**

```bash
git add mahavishnu/templates/sop.md
git commit -m "feat(sop): add default SOP template"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Dhara `case_retrospectives` table | Task 1 |
| Per-case retrospective | Task 2 |
| Synthesizer (threshold logic + suggestion text) | Task 3 |
| CLI commands | Task 4 |
| Default SOP template | Task 5 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `_catalog_fired_modes` returns `list[str]`; `synthesize_sop_suggestions` returns `list[dict]`; signatures consistent across Tasks 2-4.

**Gaps:** `review-suggestion` is a stub (logs decision only); full integration with Spec #5 three-zone pipeline is v1.1.

Plan complete. Moving to spec #8 brainstorm (`cross-machine-session-continuity`, Phase 3).
