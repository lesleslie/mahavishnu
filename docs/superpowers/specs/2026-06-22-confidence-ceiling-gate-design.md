# Confidence Ceiling Gate v1.1 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 1 (Foundational)
**Source:** `Building a Production Agent Harness` — the article's A1 gate computes a hard confidence ceiling as `1.0 − (open_questions × 0.08) − (unchecked_sources × 0.05)`. Whatever the agent self-reports, the gate caps it arithmetically. This prevents "confident but wrong" failures without blocking iteration progress.

**Depends on:** `completion-report-schema-v1` (report contract), `precommitment-hypothesis-lock` (sister Phase 1 gate).

______________________________________________________________________

## Overview

This spec defines `apply_confidence_ceiling(report: dict) -> dict` — a pure-function gate that caps an IterationReport's `confidence` field based on the report's `open_questions` and `unchecked_sources` arrays. The cap is **arithmetic, not procedural**: even if Claude writes `confidence: 99`, the gate computes the ceiling from the structural state of the report and replaces the value if it exceeds.

The gate **caps and continues** — it does not block iteration. Over-confidence is treated as a calibration error, not a rule violation. When capping occurs, the gate logs a WARNING and (best-effort) emits an Akosha anomaly event so operators can track over-confidence rates across workers.

This spec introduces **no schema change**. The cap is observable from persisted history: anyone reading a report can recompute the ceiling from `len(open_questions)` and `len(unchecked_sources)` and verify the stored confidence respects it.

______________________________________________________________________

## Goals

- **G1.** Eliminate "confident but wrong" failures by structurally capping reported confidence based on enumerable doubt (open questions, unchecked sources).
- **G2.** Compose with Spec #2 (precommitment) and Spec #1 (persister): all three gates run in a defined order at publish time.
- **G3.** Pure-function design for testability and isolation. The cap computation has no IO, no shared state.
- **G4.** Observability without schema change: capping is detectable from persisted fields; warning log + optional Akosha anomaly event provide real-time signal.

## Non-Goals

- **N1.** Blocking iteration when confidence exceeds the ceiling. The gate caps; downstream consumers may use the trajectory or capped values as blocking signals.
- **N2.** Per-worker configurable penalty constants. v1.1 uses module-level defaults; per-worker override is v1.1.1.
- **N3.** Mandatory Akosha anomaly emission. v1.1 is best-effort; v2.0 makes it mandatory once Akosha is always configured.

______________________________________________________________________

## Architecture & Data Flow

```
Worker loop, iteration N:
  1. Worker builds IterationReport with self-reported confidence
  2. apply_confidence_ceiling(report)         ← gate (this spec)
     - Computes cap = 100 - (|open_questions| × 8) - (|unchecked_sources| × 5)
     - If report.confidence > cap: cap it, log warning, emit Akosha anomaly
     - Returns possibly-modified copy
  3. validate_precommitment(capped_report)    ← Spec #2
  4. validate_iteration_report(capped_report) ← Spec #1
  5. publish_iteration_report(capped_report, ...)
```

**Key property:** The cap is a *calibration correction*, not a *rule*. Iteration continues with the capped value; consumers downstream may interpret the gap between reported and capped as a confidence-calibration signal.

______________________________________________________________________

## Formula Specification

### Constants

```python
OPEN_QUESTION_PENALTY = 8       # article's 0.08 × 100
UNCHECKED_SOURCE_PENALTY = 5    # article's 0.05 × 100
FLOOR = 0                       # never below 0
```

### Formula

```
cap = max(FLOOR, 100 - (len(open_questions) × OPEN_QUESTION_PENALTY)
                     - (len(unchecked_sources) × UNCHECKED_SOURCE_PENALTY))
```

### Edge cases

| `open_questions` | `unchecked_sources` | `cap` | Behavior |
|---|---|---|---|
| empty | empty | 100 | No ceiling; any reported value passes |
| 1 | 0 | 92 | Reported > 92 capped |
| 0 | 1 | 95 | Reported > 95 capped |
| 5 | 5 | 35 | Reported > 35 capped |
| 13 | 1 | 0 | Floor: cap = 0; reported > 0 capped to 0 |

The formula is *enumerable*: given any persisted report, the cap is computable from `len(open_questions) + len(unchecked_sources)` alone. No hidden state.

______________________________________________________________________

## Function Signature

### `compute_confidence_cap(report: dict) -> int`

Pure function. Returns `int` in `[0, 100]`. No side effects.

```python
def compute_confidence_cap(report: dict) -> int:
    """Compute the ceiling for an iteration report's confidence.

    Pure function; no side effects. Returns int in [0, 100].
    """
    open_q_count = len(report.get("open_questions", []))
    unchecked_count = len(report.get("unchecked_sources", []))
    raw = 100 - (open_q_count * OPEN_QUESTION_PENALTY) - (unchecked_count * UNCHECKED_SOURCE_PENALTY)
    return max(FLOOR, raw)
```

### `apply_confidence_ceiling(report: dict) -> dict`

Pure function modulo log + best-effort Akosha emission. Returns a possibly-modified copy of the report.

```python
def apply_confidence_ceiling(report: dict) -> dict:
    """Apply the confidence ceiling to an IterationReport.

    If report["confidence"] exceeds the computed ceiling, the report is
    returned with confidence replaced by the ceiling (and a copy is made
    so the caller's report is not mutated). If confidence is already
    within the ceiling, the report is returned unchanged.

    Side effects:
    - Logs a WARNING when capping occurs.
    - Best-effort emits an Akosha anomaly event when capping occurs.
      Failure to emit (e.g. Akosha not configured) is silent.

    Does NOT raise; over-confidence is calibration, not a rule violation.
    """
```

______________________________________________________________________

## Integration with Publisher

In `mahavishnu/core/events/report_publishers.py`, modify `publish_iteration_report`:

```python
async def publish_iteration_report(
    report: dict,
    *,
    source: str,
    correlation_id: str,
) -> None:
    """Validate and publish an IterationReport to the EventBus.

    Validation order:
    1. apply_confidence_ceiling (this spec) — cap reported confidence
    2. validate_precommitment (Spec #2) — slate rules
    3. validate_iteration_report (Spec #1) — JSON Schema conformance

    Raises:
        MahavishnuPrecommitmentViolation: if precommitment slate rules violated.
        MahavishnuReportValidationError: if report does not match JSON Schema.
    """
    from mahavishnu.core.events.confidence_ceiling import apply_confidence_ceiling
    from mahavishnu.core.events.precommitment_gate import validate_precommitment

    capped_report = apply_confidence_ceiling(report)
    validate_precommitment(capped_report)
    validate_iteration_report(capped_report)
    envelope = EventEnvelope(
        event_type="workflow.iteration.completed",
        source=source,
        correlation_id=correlation_id,
        payload=capped_report,
        metadata={
            "report_kind": "iteration",
            "schema_version": capped_report.get("schema_version", "1.0.0"),
            "confidence_was_capped": capped_report["confidence"] != report["confidence"],
        },
    )
    await event_bus.publish(envelope)
```

**Why `metadata.confidence_was_capped` rather than a payload field:** Persister (Spec #1) writes the payload column as-is; metadata is queryable separately and doesn't require a schema change. Observability is preserved without polluting the report's content with calibration internals.

______________________________________________________________________

## Akosha Anomaly Emission

Best-effort, never raises:

```python
try:
    from mahavishnu.akosha_client import emit_anomaly
    emit_anomaly(
        kind="confidence_capped",
        workflow_id=report.get("workflow_id"),
        iteration_index=report.get("iteration_index"),
        reported_confidence=reported,
        computed_cap=cap,
    )
except ImportError:
    pass  # Akosha not configured; warning log suffices
except Exception:
    logger.exception("failed to emit akosha anomaly for confidence cap")
```

**v2.0 upgrade path:** When Akosha is always configured, drop the `ImportError` exception and treat Akosha unavailability as a hard error.

______________________________________________________________________

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.1** | Gate shipped; opt-in via `params.enable_confidence_ceiling=true`. Default off. |
| **v1.2** | New iterative workers SHOULD enable; existing workers log deprecation warning once per process. |
| **v2.0** | Every iterative worker MUST enable. The publisher always calls `apply_confidence_ceiling`; the `enable_confidence_ceiling` parameter is removed. |

**CLI extension:** Extend Spec #2's `mahavishnu migrate --check-reports` to also flag workers without `enable_confidence_ceiling=True`.

______________________________________________________________________

## Storage & Retrieval

**No schema change.** Spec #1's persister stores reports as-is; capped values land in the `payload` column. `confidence_trajectory` in WorkflowReport stores effective (capped) values per iteration, preserving consistency with persisted iteration reports.

**Query:** A future `get_workflow_calibration(workflow_id)` helper may return `(reported_trajectory, capped_trajectory)` by reading each iteration's stored `confidence` and recomputing the cap. Out of scope for v1.1.

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| `open_questions` missing from report | `report.get("open_questions", [])` | Defaults to `[]`; cap unaffected. |
| `unchecked_sources` missing from report | `report.get("unchecked_sources", [])` | Defaults to `[]`; cap unaffected. |
| `confidence` missing from report | `report.get("confidence", 0)` | Defaults to `0`; no capping needed. |
| Akosha import fails | `ImportError` in `emit_anomaly` | Silent; warning log only. |
| Akosha call raises | Catch-all `Exception` | Log exception; do not propagate. |
| Cap computation produces negative | `max(FLOOR, raw)` clamps to 0 | Floor; reported > 0 capped to 0. |

______________________________________________________________________

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | Formula: empty arrays → cap=100. One open question → cap=92. One unchecked → cap=95. Many → floor 0. Capping: reported > cap → returns capped copy. Reported ≤ cap → returns same reference (no copy). Deep copy: caller's report unchanged after cap. |
| **L1 (file isolation)** | Pure function over dicts; no IO. |
| **L2 (service isolation)** | Publisher with mocked EventBus: high reported → envelope payload has capped value + `metadata.confidence_was_capped=true`. Reported within cap → no metadata flag. |
| **L3 (sandbox)** | Real EventBus + Spec #1 persister. Capped reports persist correctly. WorkflowReport trajectory reflects capped values. |
| **L4 (integration matrix)** | Cross-spec: Spec #2 (precommitment) + this spec + Spec #1 (persister) compose without conflict. Iteration 0 with capped confidence and valid slate is persisted; trajectory shows capped value. |

**Coverage target:** `tests/unit/test_confidence_ceiling.py` ≥ 95% line coverage.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| Gate functions | `mahavishnu/core/events/confidence_ceiling.py` |
| Publisher integration | `mahavishnu/core/events/report_publishers.py` (one-line addition in `publish_iteration_report`) |
| CLI extension | `mahavishnu/cli/report_migration_cli.py` (extend `check-reports` for `enable_confidence_ceiling`) |
| L0 tests | `tests/unit/test_confidence_ceiling.py` |
| L2 tests | `tests/integration/test_confidence_publisher.py` |
| L3 tests | `tests/integration/test_confidence_persister.py` |
| L4 tests | `tests/integration/test_confidence_cross_spec.py` |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Cap + warn (not block) | Article-faithful; over-confidence is calibration, not rule violation | Block on cap — too strict; loses cap-as-correction pattern |
| Pure function returning modified copy | Testable in isolation; no global state | Mutate in place — harder to test; mutation is surprise |
| No schema change | Spec #1 stays untouched; cap observable by recomputing from persisted fields | New `confidence_cap` field — explicit but verbose; requires v1.2 schema bump |
| Order: cap → precommitment → schema | Schema validation runs on capped report; persisted data consistent | Cap after schema — wasted validation if cap applies |
| Metadata flag, not payload field | Observability without polluting report content | New payload field — explicit but bloats the report |
| Best-effort Akosha anomaly | Works whether Akosha is configured or not | Mandatory Akosha — premature coupling |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Configurable penalty constants per worker. Deferred to v1.1.1; v1.1 uses module-level defaults matching article (8 and 5).
- **OQ2.** `confidence_trajectory` in WorkflowReport stores effective (capped) values per iteration. Decision: yes, for consistency with persisted iteration reports. Could revisit if trajectory comparison becomes a debugging need.
- **OQ3.** Akosha anomaly emission becomes mandatory in v2.0 when Akosha is always configured.
- **OQ4.** Per-worker calibration drift report (Akosha aggregation): how often does this worker over-report? v1.2+ candidate.

______________________________________________________________________

## Success Criteria

- **SC1.** `apply_confidence_ceiling` and `compute_confidence_cap` implemented as pure functions; tests cover formula edge cases.
- **SC2.** Publisher integrates the gate; envelope metadata includes `confidence_was_capped` when capping occurs.
- **SC3.** Capped reports persist correctly; trajectory reflects effective values.
- **SC4.** Best-effort Akosha anomaly emission works when Akosha is configured; silent no-op when not.
- **SC5.** L0–L3 tests green; ≥ 95% line coverage on the new module.
- **SC6.** Spec #2's precommitment gate + this spec's ceiling + Spec #1's schema validation compose cleanly at publish time.
