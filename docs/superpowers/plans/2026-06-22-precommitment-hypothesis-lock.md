# Precommitment Hypothesis Lock v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1.1 precommitment hypothesis lock — a structural gate that forces every iterative Claude worker to enumerate a hypothesis slate (≥6 candidates, ≥4 evaluation criteria) before iteration 0 and forbids slate presence on later iterations. Consumes Spec #1's `IterationReport` contract.

**Architecture:** Extend Spec #1's JSON Schema with a new optional field `precommitment_slate` (referenced from a separate `precommitment_slate.v1.json`). A pure-function gate `validate_precommitment()` enforces presence/absence and structural validity. The publisher `publish_iteration_report()` runs the gate between Spec #1's schema validation and EventEnvelope creation. Failure propagates as `MahavishnuPrecommitmentViolation`, terminating the worker loop with `exit_reason="blocked"`.

**Tech Stack:** Python 3.13, Pydantic v2, `jsonschema` (Spec #1's dependency), `datamodel-code-generator` (Spec #1's dependency), pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan; not repeated here. New constraints from this spec:

- **Minimum 6 hypotheses** in slate; minimum 4 evaluation criteria.
- **Slate forbidden** at `iteration_index > 0`; enforced by the gate, not by JSON Schema's `required` array.
- **Schema version bump**: `completion_report/v1.json` carries `schema_version` `1.0.0` until workers upgrade; v1.1 schema_version is `1.1.0`.
- **Validation relaxation**: `report_validation.py` accepts-and-warns on unknown fields (OQ1 resolution from spec self-review).

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json` | Canonical JSON Schema for the slate sub-schema. |
| `mahavishnu/core/events/precommitment_gate.py` | `validate_precommitment()` function. Pure; depends only on JSON Schema validator. |
| `tests/fixtures/slates.py` | Reusable valid/invalid slate generators. |
| `tests/unit/test_precommitment_gate.py` | L0 tests (schema + rule enforcement). |
| `tests/integration/test_precommitment_publisher.py` | L2 tests (publisher raises on violation). |
| `tests/integration/test_precommitment_persister.py` | L3 tests (persister round-trip with slate). |
| `tests/integration/test_precommitment_cross_version.py` | L4 tests (v1.0/v1.1 cross-version compatibility). |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/core/errors.py` | Add `MahavishnuPrecommitmentViolation(MahavishnuError)`. |
| `mahavishnu/core/schemas/completion_report/v1.json` | Add `precommitment_slate` property to `iteration_report` (optional, `$ref` to slate schema). |
| `mahavishnu/core/completion_report.py` | Regenerate from updated JSON Schema. |
| `mahavishnu/core/events/report_publishers.py` | Call `validate_precommitment()` before `validate_iteration_report()` in `publish_iteration_report()`. |
| `mahavishnu/core/events/report_validation.py` | Relax strict unknown-field rejection to accept-and-warn. |
| `mahavishnu/cli/report_migration_cli.py` | Extend `check-reports` to also flag workers without `enable_precommitment=True`. |

______________________________________________________________________

## Task 1: Add `MahavishnuPrecommitmentViolation` exception

**Files:**

- Modify: `mahavishnu/core/errors.py` (add after `MahavishnuReportValidationError`)
- Test: `tests/unit/test_errors_report.py` (append)

**Interfaces:**

- Produces: `MahavishnuPrecommitmentViolation(message: str)`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_errors_report.py`:

```python
from mahavishnu.core.errors import MahavishnuPrecommitmentViolation


def test_precommitment_violation_is_mahavishnu_error():
    from mahavishnu.core.errors import MahavishnuError
    err = MahavishnuPrecommitmentViolation("test message")
    assert isinstance(err, MahavishnuError)


def test_precommitment_violation_carries_message():
    err = MahavishnuPrecommitmentViolation("iteration_index=0 requires slate")
    assert "requires slate" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_errors_report.py -v -k precommitment`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add the exception class**

In `mahavishnu/core/errors.py`, after `MahavishnuReportValidationError`:

```python
class MahavishnuPrecommitmentViolation(MahavishnuError):
    """Raised when an IterationReport violates precommitment slate rules.

    Three failure modes:
    - iteration_index=0 lacks precommitment_slate
    - iteration_index=0 has malformed precommitment_slate
    - iteration_index>0 has precommitment_slate (forbidden after iteration 0)
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Precommitment violation: {message}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_errors_report.py -v -k precommitment`
Expected: PASS (2 new tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/errors.py tests/unit/test_errors_report.py
git commit -m "feat(precommitment): add MahavishnuPrecommitmentViolation exception"
```

______________________________________________________________________

## Task 2: Slate JSON Schema

**Files:**

- Create: `mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json`

- Test: `tests/unit/test_precommitment_gate.py` (initial fixture: file existence)

- [ ] **Step 1: Write the failing test for slate schema existence**

Create `tests/unit/test_precommitment_gate.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

SLATE_SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "mahavishnu"
    / "core"
    / "schemas"
    / "completion_report"
    / "precommitment_slate.v1.json"
)


def test_slate_schema_file_exists():
    assert SLATE_SCHEMA_PATH.exists()


def test_slate_schema_is_valid_json():
    data = json.loads(SLATE_SCHEMA_PATH.read_text())
    assert isinstance(data, dict)


def test_slate_schema_has_required_fields():
    data = json.loads(SLATE_SCHEMA_PATH.read_text())
    assert "hypotheses" in data["required"]
    assert "evaluation_criteria" in data["required"]
    assert "frozen_at" in data["required"]


def test_slate_schema_min_items():
    data = json.loads(SLATE_SCHEMA_PATH.read_text())
    assert data["properties"]["hypotheses"]["minItems"] == 6
    assert data["properties"]["evaluation_criteria"]["minItems"] == 4


def test_slate_schema_strict_additional_properties():
    data = json.loads(SLATE_SCHEMA_PATH.read_text())
    assert data["additionalProperties"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_precommitment_gate.py -v`
Expected: FAIL with `assert False` on `test_slate_schema_file_exists`

- [ ] **Step 3: Create the slate schema file**

Create `mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mahavishnu.local/schemas/precommitment_slate/v1.json",
  "title": "Precommitment Slate v1",
  "type": "object",
  "required": ["hypotheses", "evaluation_criteria", "frozen_at"],
  "properties": {
    "hypotheses": {
      "type": "array",
      "minItems": 6,
      "items": {"type": "string", "minLength": 1},
      "uniqueItems": true,
      "description": "Candidate explanations for the problem. Min 6, non-empty, distinct."
    },
    "evaluation_criteria": {
      "type": "array",
      "minItems": 4,
      "items": {"type": "string", "minLength": 1},
      "uniqueItems": true,
      "description": "Criteria for choosing among hypotheses. Min 4, non-empty, distinct."
    },
    "frozen_at": {
      "type": "string",
      "format": "date-time",
      "description": "UTC timestamp when the slate was locked. Immutable after creation."
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_precommitment_gate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json tests/unit/test_precommitment_gate.py
git commit -m "feat(precommitment): add slate JSON Schema"
```

______________________________________________________________________

## Task 3: Update IterationReport schema (v1.0 → v1.1)

**Files:**

- Modify: `mahavishnu/core/schemas/completion_report/v1.json`

- Test: `tests/unit/test_completion_report.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_completion_report.py`:

```python
def test_iteration_report_schema_has_precommitment_slate_property():
    data = json.loads(SCHEMA_PATH.read_text())
    assert "precommitment_slate" in data["iteration_report"]["properties"]


def test_iteration_report_schema_strict_unknown_fields_still_enforced_for_known_fields():
    # The slate is the only new field; additionalProperties: false still applies.
    data = json.loads(SCHEMA_PATH.read_text())
    assert data["iteration_report"]["additionalProperties"] is False


def test_precommitment_slate_is_not_in_required_array():
    # Presence is gate-enforced, not schema-required (field forbidden at iter >0).
    data = json.loads(SCHEMA_PATH.read_text())
    assert "precommitment_slate" not in data["iteration_report"]["required"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_completion_report.py -v -k precommitment`
Expected: FAIL with `KeyError`

- [ ] **Step 3: Add the field to the IterationReport schema**

In `mahavishnu/core/schemas/completion_report/v1.json`, locate `iteration_report.properties` and add at the end (after `draft_response`):

```json
    "precommitment_slate": {
      "$ref": "precommitment_slate.v1.json",
      "description": "Required at iteration_index=0; forbidden at iteration_index>0. Enforced by validate_precommitment()."
    }
```

(Keep `additionalProperties: false` unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_completion_report.py -v`
Expected: PASS (8 tests total — 5 original + 3 new)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/schemas/completion_report/v1.json tests/unit/test_completion_report.py
git commit -m "feat(precommitment): extend IterationReport schema to v1.1 with slate field"
```

______________________________________________________________________

## Task 4: Regenerate Pydantic models

**Files:**

- Regenerate: `mahavishnu/core/completion_report.py`

- [ ] **Step 1: Run codegen**

Run: `python scripts/generate_completion_report_model.py`
Expected: prints "Wrote .../mahavishnu/core/completion_report.py"

- [ ] **Step 2: Verify Spec #1's tests still pass**

Run: `pytest tests/unit/test_completion_report.py tests/unit/test_report_validation.py -v`
Expected: PASS (all previously-passing tests still pass)

- [ ] **Step 3: Add Pydantic test for slate field**

Append to `tests/unit/test_completion_report.py`:

```python
def test_pydantic_iteration_report_accepts_precommitment_slate():
    from mahavishnu.core.completion_report import IterationReport

    sample = {
        "schema_version": "1.1.0",
        "report_kind": "iteration",
        "workflow_id": "00000000-0000-0000-0000-000000000020",
        "iteration_index": 0,
        "iteration_budget": 5,
        "started_at": "2026-06-22T10:00:00Z",
        "completed_at": "2026-06-22T10:00:30Z",
        "duration_ms": 30000,
        "status": "IN_PROGRESS",
        "confidence": 70,
        "open_questions": [],
        "unchecked_sources": [],
        "contradiction_register": [],
        "assumption_register": [],
        "adjacent_problems": [],
        "precommitment_slate": {
            "hypotheses": [f"h{i}" for i in range(6)],
            "evaluation_criteria": [f"c{i}" for i in range(4)],
            "frozen_at": "2026-06-22T10:00:00Z",
        },
    }
    report = IterationReport.model_validate(sample)
    assert report.precommitment_slate is not None
    assert len(report.precommitment_slate.hypotheses) == 6
```

- [ ] **Step 4: Run new test**

Run: `pytest tests/unit/test_completion_report.py::test_pydantic_iteration_report_accepts_precommitment_slate -v`
Expected: PASS

If the codegen produced a model that doesn't expose the slate as a typed field (e.g. it's parsed as an opaque dict because the $ref wasn't followed), inspect the generated model and adjust the codegen flags. The slate must be a typed sub-model with `hypotheses`, `evaluation_criteria`, `frozen_at` fields.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/completion_report.py tests/unit/test_completion_report.py
git commit -m "feat(precommitment): regenerate Pydantic models with slate field"
```

______________________________________________________________________

## Task 5: `validate_precommitment()` gate function

**Files:**

- Create: `mahavishnu/core/events/precommitment_gate.py`

- Test: `tests/unit/test_precommitment_gate.py` (extend with rule tests)

- [ ] **Step 1: Write the failing tests for gate rules**

Append to `tests/unit/test_precommitment_gate.py`:

```python
import pytest

from mahavishnu.core.errors import MahavishnuPrecommitmentViolation
from mahavishnu.core.events.precommitment_gate import validate_precommitment


def _valid_slate():
    return {
        "hypotheses": [f"hypothesis {i}" for i in range(6)],
        "evaluation_criteria": [f"criterion {i}" for i in range(4)],
        "frozen_at": "2026-06-22T10:00:00Z",
    }


def test_iteration_0_with_valid_slate_passes():
    report = {"iteration_index": 0, "precommitment_slate": _valid_slate()}
    validate_precommitment(report)  # no raise


def test_iteration_0_without_slate_raises():
    report = {"iteration_index": 0}
    with pytest.raises(MahavishnuPrecommitmentViolation) as exc:
        validate_precommitment(report)
    assert "requires precommitment_slate" in str(exc.value)


def test_iteration_0_with_too_few_hypotheses_raises():
    slate = _valid_slate()
    slate["hypotheses"] = slate["hypotheses"][:3]
    report = {"iteration_index": 0, "precommitment_slate": slate}
    with pytest.raises(MahavishnuPrecommitmentViolation):
        validate_precommitment(report)


def test_iteration_0_with_too_few_criteria_raises():
    slate = _valid_slate()
    slate["evaluation_criteria"] = slate["evaluation_criteria"][:2]
    report = {"iteration_index": 0, "precommitment_slate": slate}
    with pytest.raises(MahavishnuPrecommitmentViolation):
        validate_precommitment(report)


def test_iteration_0_with_duplicate_hypotheses_raises():
    slate = _valid_slate()
    slate["hypotheses"] = ["same"] * 6
    report = {"iteration_index": 0, "precommitment_slate": slate}
    with pytest.raises(MahavishnuPrecommitmentViolation):
        validate_precommitment(report)


def test_iteration_1_without_slate_passes():
    report = {"iteration_index": 1}
    validate_precommitment(report)  # no raise


def test_iteration_1_with_slate_raises():
    report = {"iteration_index": 1, "precommitment_slate": _valid_slate()}
    with pytest.raises(MahavishnuPrecommitmentViolation) as exc:
        validate_precommitment(report)
    assert "must not include precommitment_slate" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_precommitment_gate.py -v -k "iteration or duplicates or raises" `
Expected: FAIL with `ModuleNotFoundError` on `mahavishnu.core.events.precommitment_gate`

- [ ] **Step 3: Implement the gate function**

Create `mahavishnu/core/events/precommitment_gate.py`:

```python
"""Precommitment hypothesis lock gate.

Pure functions over a JSON Schema validator. Raises
MahavishnuPrecommitmentViolation on rule violation. Used by
publish_iteration_report() between Spec #1's schema validation and
EventEnvelope creation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from mahavishnu.core.errors import MahavishnuPrecommitmentViolation

SLATE_SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "schemas"
    / "completion_report"
    / "precommitment_slate.v1.json"
)


@lru_cache(maxsize=1)
def _slate_validator() -> Draft202012Validator:
    schema = json.loads(SLATE_SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


def validate_precommitment(report: dict) -> None:
    """Validate precommitment slate rules for an IterationReport.

    Rules:
    - iteration_index == 0 → precommitment_slate MUST be present and valid.
    - iteration_index > 0  → precommitment_slate MUST NOT be present.

    Raises:
        MahavishnuPrecommitmentViolation: if any rule is violated.
    """
    iteration_index = report.get("iteration_index")
    slate = report.get("precommitment_slate")

    if iteration_index == 0:
        if slate is None:
            raise MahavishnuPrecommitmentViolation(
                "iteration_index=0 requires precommitment_slate field"
            )
        errors = list(_slate_validator().iter_errors(slate))
        if errors:
            raise MahavishnuPrecommitmentViolation(
                f"precommitment_slate failed validation: "
                + "; ".join(f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors)
            )
        return

    if slate is not None:
        raise MahavishnuPrecommitmentViolation(
            f"iteration_index={iteration_index} must not include precommitment_slate"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_precommitment_gate.py -v`
Expected: PASS (12 tests total — 5 schema-existence + 7 rule tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/events/precommitment_gate.py tests/unit/test_precommitment_gate.py
git commit -m "feat(precommitment): add validate_precommitment gate function"
```

______________________________________________________________________

## Task 6: Integrate gate into `publish_iteration_report()`

**Files:**

- Modify: `mahavishnu/core/events/report_publishers.py`

- Test: `tests/unit/test_report_publishers.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_report_publishers.py`:

```python
@pytest.mark.asyncio
async def test_publish_iteration_runs_precommitment_gate_first(bound_publishers):
    """Iteration 0 without slate must raise before reaching JSON Schema validation."""
    from mahavishnu.core.errors import MahavishnuPrecommitmentViolation

    _rp, bus = bound_publishers
    report = valid_iteration_report(iteration_index=0)  # no slate
    with pytest.raises(MahavishnuPrecommitmentViolation):
        await publish_iteration_report(
            report, source="worker-1", correlation_id=report["workflow_id"]
        )
    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_publish_iteration_0_with_slate_succeeds(bound_publishers):
    _rp, bus = bound_publishers
    slate = {
        "hypotheses": [f"h{i}" for i in range(6)],
        "evaluation_criteria": [f"c{i}" for i in range(4)],
        "frozen_at": "2026-06-22T10:00:00Z",
    }
    report = valid_iteration_report(iteration_index=0, precommitment_slate=slate)
    await publish_iteration_report(
        report, source="worker-1", correlation_id=report["workflow_id"]
    )
    bus.publish.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_report_publishers.py -v -k "precommitment or slate"`
Expected: FAIL (no slate rejection in current implementation)

- [ ] **Step 3: Modify the publisher**

In `mahavishnu/core/events/report_publishers.py`, update `publish_iteration_report`:

```python
async def publish_iteration_report(
    report: dict,
    *,
    source: str,
    correlation_id: str,
) -> None:
    """Validate and publish an IterationReport to the EventBus.

    Validation order:
    1. validate_precommitment (this spec) — slate presence/absence rules
    2. validate_iteration_report (Spec #1) — JSON Schema conformance

    Raises:
        MahavishnuPrecommitmentViolation: if precommitment slate rules violated.
        MahavishnuReportValidationError: if report does not match JSON Schema.
    """
    from mahavishnu.core.events.precommitment_gate import validate_precommitment

    validate_precommitment(report)
    validate_iteration_report(report)
    envelope = EventEnvelope(
        event_type="workflow.iteration.completed",
        source=source,
        correlation_id=correlation_id,
        payload=report,
        metadata={
            "report_kind": "iteration",
            "schema_version": report.get("schema_version", "1.0.0"),
        },
    )
    await event_bus.publish(envelope)
    logger.debug(
        "published iteration report",
        extra={
            "workflow_id": report["workflow_id"],
            "iteration_index": report["iteration_index"],
            "has_precommitment_slate": "precommitment_slate" in report,
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_report_publishers.py -v`
Expected: PASS (5 tests total — 3 original + 2 new)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/events/report_publishers.py tests/unit/test_report_publishers.py
git commit -m "feat(precommitment): integrate validate_precommitment into publisher"
```

______________________________________________________________________

## Task 7: Relax `report_validation.py` to accept-and-warn on unknown fields

**Files:**

- Modify: `mahavishnu/core/events/report_validation.py`

- Test: `tests/unit/test_report_validation.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_report_validation.py`:

```python
def test_validate_iteration_report_accepts_unknown_field_with_warning(
    caplog: pytest.LogCaptureFixture,
):
    """OQ1 resolution: v1.0 consumers accept-and-warn on unknown fields.

    A v1.0 reader (this code) receives a v1.1 report with the
    precommitment_slate field; the slate is unknown to v1.0 strict
    policy. Per spec self-review OQ1, v1.0 relaxes to accept-and-warn.
    """
    import logging

    from mahavishnu.core.events.report_validation import validate_iteration_report

    report_with_slate = valid_iteration_report(
        precommitment_slate={
            "hypotheses": [f"h{i}" for i in range(6)],
            "evaluation_criteria": [f"c{i}" for i in range(4)],
            "frozen_at": "2026-06-22T10:00:00Z",
        }
    )
    with caplog.at_level(logging.WARNING, logger="mahavishnu"):
        validate_iteration_report(report_with_slate)  # no raise
    assert any("unknown field" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_report_validation.py -v -k "unknown_field"`
Expected: FAIL with `MahavishnuReportValidationError` (current behavior rejects unknown fields)

- [ ] **Step 3: Modify validation to accept-and-warn**

In `mahavishnu/core/events/report_validation.py`, modify `_format_errors` and add a helper to skip unknown-field errors with a warning log:

```python
from oneiric.logging import get_logger

logger = get_logger(__name__)


def _iter_errors_with_warning_handling(
    validator: Draft202012Validator, instance: dict
) -> list[JSONSchemaValidationError]:
    """Yield validation errors, demoting unknown-field rejections to warnings.

    OQ1 resolution: v1.0 consumers accept-and-warn on unknown fields so that
    v1.1 reports (with precommitment_slate) can be read without coordination.
    """
    errors = list(validator.iter_errors(instance))
    real_errors: list[JSONSchemaValidationError] = []
    for err in errors:
        if err.validator == "additionalProperties":
            unknown = list(err.message.split("'"))
            if len(unknown) >= 2:
                field = unknown[1]
                logger.warning(
                    "ignoring unknown field in completion report (forward-compat)",
                    extra={"unknown_field": field, "schema_version": instance.get("schema_version")},
                )
                continue
        real_errors.append(err)
    return real_errors
```

Then modify `validate_iteration_report` and `validate_workflow_report` to call this helper instead of `iter_errors` directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_report_validation.py -v`
Expected: PASS (9 tests — 8 original + 1 new)

- [ ] **Step 5: Verify all Spec #1 tests still pass**

Run: `pytest tests/unit/ -v`
Expected: all unit tests pass

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/events/report_validation.py tests/unit/test_report_validation.py
git commit -m "feat(reports): accept-and-warn on unknown fields (OQ1 forward-compat)"
```

______________________________________________________________________

## Task 8: Extend migration CLI to flag missing `enable_precommitment`

**Files:**

- Modify: `mahavishnu/cli/report_migration_cli.py`

- Test: `tests/integration/test_report_cli.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_report_cli.py`:

```python
def test_check_reports_flags_worker_without_precommitment(tmp_path: Path, runner: CliRunner):
    (tmp_path / "worker_old.py").write_text(
        "from mahavishnu.core.events.report_publishers import publish_iteration_report\n"
        "async def run_iteration():\n    pass\n"
    )
    result = runner.invoke(migrate_app, ["check-reports", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "enable_precommitment" in result.output


def test_check_reports_passes_worker_with_precommitment(tmp_path: Path, runner: CliRunner):
    (tmp_path / "worker_new.py").write_text(
        "from mahavishnu.core.events.report_publishers import publish_iteration_report\n"
        "async def run_iteration(params):\n    params['enable_precommitment'] = True\n    pass\n"
    )
    result = runner.invoke(migrate_app, ["check-reports", "--path", str(tmp_path)])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_report_cli.py -v -k "precommitment"`
Expected: FAIL (current CLI doesn't check for enable_precommitment)

- [ ] **Step 3: Extend the CLI**

In `mahavishnu/cli/report_migration_cli.py`, add a function `_has_precommitment` and use it in `check_reports`:

```python
_PRECOMMITMENT_MARKER = "enable_precommitment"


def _has_precommitment(path: Path) -> bool:
    return _PRECOMMITMENT_MARKER in path.read_text(errors="ignore")
```

Modify `check_reports` to also check precommitment:

```python
@migrate_app.command("check-reports")
def check_reports(
    path: Path = typer.Option(Path("."), "--path", help="Directory to scan"),
) -> None:
    """Exit non-zero if any worker-like module does not emit reports
    or does not enable precommitment.
    """
    workers = _scan(path)
    non_emitters = [w for w in workers if not _emits_reports(w)]
    no_precommitment = [w for w in workers if _emits_reports(w) and not _has_precommitment(w)]
    if non_emitters or no_precommitment:
        if non_emitters:
            typer.echo(f"Found {len(non_emitters)} worker(s) not emitting reports:")
            for w in non_emitters:
                typer.echo(f"  - {w.relative_to(path)}")
        if no_precommitment:
            typer.echo(
                f"Found {len(no_precommitment)} worker(s) emitting reports without enable_precommitment:"
            )
            for w in no_precommitment:
                typer.echo(f"  - {w.relative_to(path)}")
        raise typer.Exit(code=1)
    typer.echo(f"All {len(workers)} worker(s) compliant.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_report_cli.py -v`
Expected: PASS (4 tests — 2 original + 2 new)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/report_migration_cli.py tests/integration/test_report_cli.py
git commit -m "feat(precommitment): extend migrate --check-reports to flag missing enable_precommitment"
```

______________________________________________________________________

## Task 9: End-to-end integration test

**Files:**

- Test: `tests/integration/test_precommitment_persister.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_precommitment_persister.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.events.report_publishers import publish_iteration_report
from mahavishnu.core.events.subscribers.report_persister import get_iteration_history
from tests.fixtures.reports import valid_iteration_report
from tests.fixtures.slates import valid_slate


@pytest.mark.asyncio
async def test_persister_stores_iteration_0_with_slate():
    workflow_id = "00000000-0000-0000-0000-000000000030"
    report = valid_iteration_report(
        workflow_id=workflow_id, iteration_index=0, precommitment_slate=valid_slate()
    )
    await publish_iteration_report(report, source="w1", correlation_id=workflow_id)

    history = await get_iteration_history(workflow_id)
    assert len(history) == 1
    assert history[0]["precommitment_slate"]["hypotheses"][0] == "hypothesis 0"


@pytest.mark.asyncio
async def test_persister_stores_iteration_1_without_slate():
    workflow_id = "00000000-0000-0000-0000-000000000031"
    # First, publish iter 0 with slate.
    await publish_iteration_report(
        valid_iteration_report(workflow_id=workflow_id, iteration_index=0, precommitment_slate=valid_slate()),
        source="w1",
        correlation_id=workflow_id,
    )
    # Then publish iter 1 without slate.
    await publish_iteration_report(
        valid_iteration_report(workflow_id=workflow_id, iteration_index=1),
        source="w1",
        correlation_id=workflow_id,
    )

    history = await get_iteration_history(workflow_id)
    assert len(history) == 2
    assert "precommitment_slate" in history[0]
    assert "precommitment_slate" not in history[1]
```

Also create `tests/fixtures/slates.py`:

```python
"""Reusable valid/invalid slate fixtures."""

from __future__ import annotations

from typing import Any


def valid_slate(**overrides: Any) -> dict[str, Any]:
    """Return a valid slate; override any field by keyword."""
    base: dict[str, Any] = {
        "hypotheses": [f"hypothesis {i}" for i in range(6)],
        "evaluation_criteria": [f"criterion {i}" for i in range(4)],
        "frozen_at": "2026-06-22T10:00:00Z",
    }
    base.update(overrides)
    return base
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_precommitment_persister.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_precommitment_persister.py tests/fixtures/slates.py
git commit -m "test(precommitment): add end-to-end persister integration tests"
```

______________________________________________________________________

## Task 10: Cross-version compatibility tests

**Files:**

- Test: `tests/integration/test_precommitment_cross_version.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_precommitment_cross_version.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.errors import MahavishnuPrecommitmentViolation
from mahavishnu.core.events.precommitment_gate import validate_precommitment
from tests.fixtures.reports import valid_iteration_report
from tests.fixtures.slates import valid_slate


def test_v1_1_iteration_0_with_slate_passes():
    report = valid_iteration_report(
        schema_version="1.1.0", iteration_index=0, precommitment_slate=valid_slate()
    )
    validate_precommitment(report)


def test_v1_0_iteration_0_without_slate_passes_v1_gate_strictly():
    """v1.0 reports have no slate field; v1.1 gate still passes (gate allows absence at iter 0 if gate is disabled... actually no — gate requires slate at iter 0 regardless of schema_version).

    Decision: gate is strict — slate required at iter 0 regardless of schema_version. v1.0 workers must upgrade to v1.1 to use the gate. This is the conservative choice; matches 'opt-in v1.1, required v2.0' adoption.
    """
    report = valid_iteration_report(schema_version="1.0.0", iteration_index=0)
    with pytest.raises(MahavishnuPrecommitmentViolation):
        validate_precommitment(report)


def test_v1_1_iteration_1_with_slate_raises():
    report = valid_iteration_report(
        schema_version="1.1.0", iteration_index=1, precommitment_slate=valid_slate()
    )
    with pytest.raises(MahavishnuPrecommitmentViolation):
        validate_precommitment(report)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_precommitment_cross_version.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_precommitment_cross_version.py
git commit -m "test(precommitment): add cross-version compatibility tests"
```

______________________________________________________________________

## Self-Review

After writing, check the plan against the spec.

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Architecture & data flow | Task 5 (gate function), Task 6 (publisher integration) |
| Schema definition | Task 2 (slate JSON Schema), Task 3 (IterationReport extension), Task 4 (Pydantic regen) |
| OQ1 resolution (accept-and-warn) | Task 7 (validation relaxation) |
| Gate function | Task 5 |
| Adoption & migration | Task 8 (CLI extension) |
| Storage & retrieval | Task 9 (persister integration test confirms no schema change) |
| Error handling | Task 1 (exception class), Task 5 (gate raises) |
| Testing strategy | Tasks 1-10 (L0-L4 coverage) |

**2. Placeholder scan:** No `TBD`/`TODO` markers. The "OQ1 resolution" decision is fully specified.

**3. Type consistency:** `validate_precommitment(report: dict) -> None` consistent across Tasks 5, 6, 10. `MahavishnuPrecommitmentViolation(message: str)` constructor used uniformly.

**Gaps:** None. The plan covers the full spec scope.

______________________________________________________________________

Plan complete and saved to `docs/superpowers/plans/2026-06-22-precommitment-hypothesis-lock.md`.

Per the user's earlier scope decision (option A: full brainstorm + plan + commit cycle for each of the 9 remaining specs), this plan is part of spec #2's cycle. Moving on to spec #3 brainstorm (`confidence-ceiling-gate`) next.
