---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on:
  - ext:dhara-sql-execute-query
topic: convergence-control-plane
---

# Project-Scoped SOP Evolution v1.0 — Design

**Status:** **DEFERRED** — blocked on Dhara SQL `execute()` / `query()` surface (this spec imports `from mahavishnu.core.dhara_client import execute, query` for `skill_transitions` table inserts and reads; see `mahavishnu/core/dhara_adapter.py` for the current key-value-only surface). Spec 1-3 gate persistence (C3 outstanding) is the additional dependency: failure-mode catalog can't fire without `exit_reason`, `precommitment_slate`, `confidence_was_capped`, `unchecked_sources[].access_status`, `adjacent_problems[].status` being persisted by Specs #1-3.  <!-- legacy status: DEFERRED — see YAML frontmatter -->
**Phase:** 3 (Adjacent)
**Source:** `Building a Production Agent Harness` — "Loop 2 — Cross-case behavioral reinforcement." Per-project SOP that evolves based on the team's specific failure-mode frequencies. Each project's SOP teaches the next case what the previous cases failed at.

______________________________________________________________________

## Overview

This spec defines a per-deployment SOP file (`~/.mahavishnu/sop.md`) that is **auto-evolved** based on aggregated failure modes from recent workflow retrospectives. Per-case retrospectives catalog which failure modes fired; a weekly cron aggregates, generates SOP suggestions when a mode crosses threshold, and stages changes for operator review.

**Architectural property:** Each Mahavishnu deployment learns its own patterns. Team A's failures teach Team A's SOP; they don't contaminate Team B's. The SOP is the *cumulative memory* of failure patterns.

______________________________________________________________________

## Goals

- **G1.** Auto-evolve the SOP based on observed failure patterns, not operator guesswork.
- **G2.** Threshold-based signal: 3/10 → suggestion, 6/10 → alert. Calibrated to balance noise and signal.
- **G3.** Per-deployment isolation: each Mahavishnu instance has its own SOP file.
- **G4.** Operator review of all auto-generated changes (no autonomous SOP mutation).
- **G5.** Failure-mode taxonomy derived from existing gates (Spec #1-3, Phase 2 self-heal); extensible via SOP frontmatter.

## Non-Goals

- **N1.** LLM-generated suggestion text. v1.0 uses templates; v1.1+ may extend.
- **N2.** Multi-tenant SOP scoping. v1.0 single deployment path; v2.0 may extend.
- **N3.** Real-time SOP updates. v1.0 weekly cron cadence.
- **N4.** Cross-deployment SOP sharing. Each deployment independent.

______________________________________________________________________

## Architecture & Data Flow

```
Per-deployment SOP file:
  ~/.mahavishnu/sop.md
  ├── YAML frontmatter
  │     failure_modes:
  │       schema_validation: ...
  │       precommitment_violation: ...
  │       confidence_capped: ...
  │       self_heal_exhausted: ...
  │       data_gathering_skipped: ...
  │       analysis_completeness: ...
  └── Markdown body (operator's investigation patterns)

Per-case retrospective (after each workflow completes):
  1. Read final WorkflowReport from persister (Spec #1)
  2. Read iteration history (Spec #1)
  3. Catalog fired failure modes:
     - exit_reason → schema_validation, self_heal_exhausted
     - precommitment_slate at iter>0 → precommitment_violation
     - metadata.confidence_was_capped=True → confidence_capped
     - unchecked_sources.skipped_inferred → data_gathering_skipped
     - adjacent_problems.open at completion → analysis_completeness
  4. Write to Dhara: case_retrospectives(workflow_id, fired_modes, ...)

Weekly cron (knowledge-updater):
  1. Query last 10 (or 20-30 per article) retrospectives from Dhara
  2. Count failure-mode frequencies
  3. For each mode crossing threshold:
     - 3/10 → generate SOP suggestion; write to ~/.mahavishnu/sop.staging.md
     - 6/10 → alert (operator notification) + stronger suggestion
  4. Operator reviews via CLI; approves → SOP updated

Operator workflow:
  1. Notification: "3 SOP suggestions pending review"
  2. Run: `mahavishnu sop show-suggestions`
  3. Run: `mahavishnu sop review-suggestion <mode> --decision accept`
  4. On accept: spec #5 three-zone pipeline promotes the change
```

______________________________________________________________________

## Failure-Mode Taxonomy

```yaml
# In ~/.mahavishnu/sop.md frontmatter
failure_modes:
  schema_validation:
    description: "IterationReport or WorkflowReport failed JSON Schema validation"
    category: quality_gate
    detection: "validation_error in retrospect"
  precommitment_violation:
    description: "IterationReport at iter 0 missing/invalid slate, or iter >0 has slate"
    category: quality_gate
    detection: "precommitment_violation in retrospect"
  confidence_capped:
    description: "Self-reported confidence exceeded computed ceiling"
    category: quality_gate
    detection: "metadata.confidence_was_capped=True"
  self_heal_exhausted:
    description: "L2 bounded agentic heal exhausted without success"
    category: quality_gate
    detection: "L2Exhausted exception in retrospect"
  data_gathering_skipped:
    description: "Investigation skipped accessible data sources"
    category: data_gathering
    detection: "unchecked_sources has skipped_inferred entries"
  analysis_completeness:
    description: "Root cause not traced all the way through"
    category: analysis_completeness
    detection: "adjacent_problems has open entries at workflow completion"
```

Categories come from the article (data_gathering, quality_gate, analysis_completeness). Specific failure modes within each category are detected via Spec #1-3 gate outputs.

______________________________________________________________________

## Per-Case Retrospective

```python
# mahavishnu/core/retrospective.py

import uuid

from mahavishnu.core.dhara_client import execute
from mahavishnu.core.events.subscribers.report_persister import (
    get_iteration_history,
    get_workflow_report,
)


def _catalog_fired_modes(workflow_id: str) -> list[str]:
    fired: list[str] = []
    history = get_iteration_history(workflow_id)
    workflow_report = get_workflow_report(workflow_id)
    if not history or not workflow_report:
        return fired

    if workflow_report.get("exit_reason") == "schema_violation":
        fired.append("schema_validation")

    if any(it.get("precommitment_slate") and it.get("iteration_index", 0) > 0 for it in history):
        fired.append("precommitment_violation")

    if any(it.get("confidence_was_capped") for it in history):
        fired.append("confidence_capped")

    if workflow_report.get("exit_reason") == "heal_exhausted":
        fired.append("self_heal_exhausted")

    if any(s.get("access_status") == "skipped_inferred"
           for it in history for s in it.get("unchecked_sources", [])):
        fired.append("data_gathering_skipped")

    if any(p.get("status") == "open"
           for it in history for p in it.get("adjacent_problems", [])):
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

______________________________________________________________________

## Weekly Cron (knowledge-updater)

```python
# mahavishnu/core/sop_synthesizer.py

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

______________________________________________________________________

## CLI Commands

```python
# mahavishnu/cli/sop_synthesizer_cli.py

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
    # Implementation: route through Spec #5 three-zone pipeline.
    # For v1.0, write directly to SOP file after approval; v1.1 uses staging.
    raise NotImplementedError("Integrate with Spec #5 three-zone pipeline")


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

______________________________________________________________________

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.0** | Per-case retrospective shipped; weekly cron aggregation shipped; CLI surface shipped. SOP file at `~/.mahavishnu/sop.md` is read-only. Cron writes suggestions to `~/.mahavishnu/sop.staging.md` for review. Operator manually edits or accepts via CLI. |
| **v1.1** | Auto-application of accepted suggestions via Spec #5 three-zone pipeline. Suggestion text generation may use LLM (template fallback). |
| **v2.0** | Per-tenant SOP scoping; multi-deployment rollouts. |

______________________________________________________________________

## Storage & Retrieval

**Dhara table `case_retrospectives`:**

| Column | Type | Description |
|---|---|---|
| `retrospective_id` | UUID | primary key |
| `workflow_id` | string | — |
| `fired_modes` | string | comma-separated failure mode names |
| `recorded_at` | timestamp | UTC |
| `recorded_by` | string | `system:cron`, `system:cli`, or user_id |

Indexes: `(recorded_at DESC)`, `(workflow_id)`.

**Filesystem:**

- `~/.mahavishnu/sop.md` — current SOP. Read by agents (Spec #1-3 prompt injection), Spec #6 default fallback.
- `~/.mahavishnu/sop.staging.md` — pending SOP changes from cron. Reviewed via CLI.

**No new event schema.** Retrospective is internal; only the SOP file is operator-facing.

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| WorkflowReport missing | `_catalog_fired_modes` returns `[]` | Retrospective records empty fired_modes; cron ignores. |
| Dhara write fails | Exception in `record_retrospective` | Logged; retrospective skipped. (Retrospective is observational, not blocking.) |
| Cron aggregation fails | Exception in `synthesize_sop_suggestions` | Logged; suggestions skipped for this week. |
| SOP file missing | `SOP_PATH.exists()` returns False | Cron creates with default content from packaged template. |
| Staging SOP file corrupt | YAML parse fails | Cron logs error; writes to a separate file (`sop.staging.errors.log`). |

______________________________________________________________________

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | `_catalog_fired_modes` correctly detects each failure mode from fixture reports. `_frequency_counts` returns correct counts. `synthesize_sop_suggestions` generates suggestions at threshold. Suggestion text matches template. |
| **L1 (file isolation)** | SOP staging write produces correct content. Default SOP template loads. |
| **L2 (service isolation)** | CLI commands with mocked synthesis; correct output format. |
| **L3 (sandbox)** | Real Dhara; insert retrospectives; run synthesis; verify suggestions. |
| **L4 (integration)** | End-to-end: workflow runs → retrospective records → cron aggregates → CLI surfaces suggestions → operator accepts → SOP updated. |

**Coverage target:** `tests/unit/test_retrospective.py`, `tests/unit/test_sop_synthesizer.py` ≥ 95% line coverage.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| Retrospective | `mahavishnu/core/retrospective.py` |
| Synthesizer | `mahavishnu/core/sop_synthesizer.py` |
| Dhara migration | `mahavishnu/core/dhara_migrations/case_retrospectives.sql` |
| CLI | `mahavishnu/cli/sop_synthesizer_cli.py` |
| Default SOP template | `mahavishnu/templates/sop.md` |
| L0 tests | `tests/unit/test_retrospective.py` |
| L0 tests | `tests/unit/test_sop_synthesizer.py` |
| L3 tests | `tests/integration/test_sop_evolution.py` |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Project SOP per-deployment | Per-deployment behavior; team-specific failure patterns | Per-repo — too narrow; tenant confusion |
| Failure modes derived from Phase 1-3 gates | Automatic; gates already produce signal | Hardcoded — misses new gates; freeform — operators must define |
| Threshold 3/10 suggestion, 6/10 alert | Article-calibrated; balances noise and signal | 1/N — too noisy; 10/N — too slow |
| Cron writes to staging file (not direct edit) | Operator reviews before applying | Direct edit — no review; loss of audit trail |
| SOP file at `~/.mahavishnu/sop.md` (filesystem) | Easy to read/edit; operator-friendly | Dhara only — requires tool to view |
| Template-based suggestion text | Deterministic; fast | LLM-based — slower; non-deterministic |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Per-tenant SOP scoping. v1.0 single deployment path; v2.0 may extend.
- **OQ2.** Cron schedule (weekly) configurable per deployment. v1.0 hardcoded; v1.1 configurable.
- **OQ3.** Suggestion text generation: template-based (current) vs LLM-synthesized. v1.0 templates; v1.1+ LLM with templates as fallback.
- **OQ4.** Rollback: when SOP change is rejected, log for analysis. v1.0 logs to Dhara; v1.1 may add explicit rollback audit.
- **OQ5.** Integration with Spec #5 (three-zone skill pipeline): treat SOP mutations like skill promotions. v1.1 work.

______________________________________________________________________

## Success Criteria

- **SC1.** Per-case retrospective records fired failure modes correctly based on Spec #1-3 outputs.
- **SC2.** Weekly cron aggregation surfaces suggestions at 3/10 and alerts at 6/10.
- **SC3.** CLI commands (`show-suggestions`, `review-suggestion`, `record-retrospective`) shipped.
- **SC4.** SOP file at `~/.mahavishnu/sop.md` is loaded by agents (Spec #1-3 prompt injection) and Spec #6 fallback.
- **SC5.** L0–L3 tests green; ≥ 95% line coverage on new modules.
- **SC6.** Operator can review and accept a suggestion; SOP file updated; audit trail preserved.
