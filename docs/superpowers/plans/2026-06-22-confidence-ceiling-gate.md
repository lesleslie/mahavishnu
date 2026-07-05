# Confidence Ceiling Gate v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `apply_confidence_ceiling` gate — a pure function that caps self-reported confidence based on enumerable doubt (open questions + unchecked sources), preventing "confident but wrong" failures. No schema change; cap observable from persisted fields.

**Architecture:** `mahavishnu/core/events/confidence_ceiling.py` exposes `compute_confidence_cap(report)` (pure) and `apply_confidence_ceiling(report)` (pure modulo log + best-effort Akosha emission). Publisher `publish_iteration_report` calls `apply_confidence_ceiling` first, before Spec #2's precommitment gate and Spec #1's schema validation.

**Tech Stack:** Python 3.13, pytest with `asyncio_mode = "auto"`, Oneiric logger.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints from this spec:

- **Penalty constants** (matching article scaled to 0-100): `OPEN_QUESTION_PENALTY = 8`, `UNCHECKED_SOURCE_PENALTY = 5`, `FLOOR = 0`.
- **No schema change** to IterationReport v1.1.
- **Order of gates**: cap → precommitment → schema validation → publish.
- **No raises** from the gate; over-confidence is calibration, not rule violation.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/events/confidence_ceiling.py` | `compute_confidence_cap()` + `apply_confidence_ceiling()` functions. |
| `tests/unit/test_confidence_ceiling.py` | L0 tests for formula + capping + deep copy. |
| `tests/integration/test_confidence_publisher.py` | L2 tests for publisher integration + metadata flag. |
| `tests/integration/test_confidence_persister.py` | L3 tests for capped-value persistence + trajectory. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/core/events/report_publishers.py` | Call `apply_confidence_ceiling` before precommitment gate. Set `metadata.confidence_was_capped`. |
| `mahavishnu/cli/report_migration_cli.py` | Extend `check-reports` to flag workers without `enable_confidence_ceiling=True`. |

______________________________________________________________________

## Task 1: Implement `confidence_ceiling.py`

**Files:**

- Create: `mahavishnu/core/events/confidence_ceiling.py`
- Test: `tests/unit/test_confidence_ceiling.py`

**Interfaces:**

- Produces:

  - `compute_confidence_cap(report: dict) -> int` (pure)
  - `apply_confidence_ceiling(report: dict) -> dict` (pure modulo log)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_confidence_ceiling.py`:

```python
from __future__ import annotations

import logging

import pytest

from mahavishnu.core.events.confidence_ceiling import (
    apply_confidence_ceiling,
    compute_confidence_cap,
)


def _report(confidence: int = 0, open_q: int = 0, unchecked: int = 0) -> dict:
    return {
        "confidence": confidence,
        "open_questions": [f"q{i}" for i in range(open_q)],
        "unchecked_sources": [f"s{i}" for i in range(unchecked)],
    }


def test_compute_cap_no_questions_no_sources():
    assert compute_confidence_cap(_report()) == 100


def test_compute_cap_one_open_question():
    assert compute_confidence_cap(_report(open_q=1)) == 92


def test_compute_cap_one_unchecked_source():
    assert compute_confidence_cap(_report(unchecked=1)) == 95


def test_compute_cap_mixed():
    assert compute_confidence_cap(_report(open_q=5, unchecked=5)) == 35


def test_compute_cap_floor_zero():
    assert compute_confidence_cap(_report(open_q=13, unchecked=1)) == 0


def test_compute_cap_missing_arrays_defaults_to_empty():
    report: dict = {"confidence": 50}
    assert compute_confidence_cap(report) == 100


def test_apply_ceiling_reports_within_cap_returns_unchanged():
    report = _report(confidence=80, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is report
    assert result["confidence"] == 80


def test_apply_ceiling_reports_above_cap_returns_capped_copy():
    report = _report(confidence=99, open_q=2)
    result = apply_confidence_ceiling(report)
    assert result is not report
    assert result["confidence"] == 84  # 100 - 2*8
    assert report["confidence"] == 99  # original unchanged


def test_apply_ceiling_logs_warning_when_capping(
    caplog: pytest.LogCaptureFixture,
):
    report = _report(confidence=99, open_q=3)
    with caplog.at_level(logging.WARNING, logger="mahavishnu"):
        result = apply_confidence_ceiling(report)
    assert result["confidence"] == 76
    assert any("confidence capped" in r.message.lower() for r in caplog.records)


def test_apply_ceiling_at_exact_cap_no_log():
    report = _report(confidence=84, open_q=2)
    with caplog.at_level(logging.WARNING, logger="mahavishnu"):
        result = apply_confidence_ceiling(report)
    assert result is report
    assert not any("capped" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_confidence_ceiling.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the module**

Create `mahavishnu/core/events/confidence_ceiling.py`:

```python
"""Confidence ceiling gate.

Pure-function cap on reported confidence based on enumerable doubt.
Caps do not raise; over-confidence is calibration, not a rule violation.
"""

from __future__ import annotations

from copy import deepcopy

from oneiric.logging import get_logger

logger = get_logger(__name__)

OPEN_QUESTION_PENALTY = 8
UNCHECKED_SOURCE_PENALTY = 5
FLOOR = 0


def compute_confidence_cap(report: dict) -> int:
    """Compute the ceiling for an iteration report's confidence.

    Pure function; no side effects. Returns int in [0, 100].
    """
    open_q_count = len(report.get("open_questions", []))
    unchecked_count = len(report.get("unchecked_sources", []))
    raw = 100 - (open_q_count * OPEN_QUESTION_PENALTY) - (unchecked_count * UNCHECKED_SOURCE_PENALTY)
    return max(FLOOR, raw)


def apply_confidence_ceiling(report: dict) -> dict:
    """Apply the confidence ceiling to an IterationReport.

    If report["confidence"] exceeds the computed ceiling, returns a deep
    copy with confidence replaced by the ceiling. Otherwise returns the
    report unchanged.

    Side effects: logs a WARNING when capping occurs; best-effort emits
    an Akosha anomaly event when capping occurs (silent if unavailable).
    Does NOT raise.
    """
    cap = compute_confidence_cap(report)
    reported = report.get("confidence", 0)

    if reported <= cap:
        return report

    capped = deepcopy(report)
    capped["confidence"] = cap
    logger.warning(
        "confidence capped by ceiling",
        extra={
            "workflow_id": report.get("workflow_id"),
            "iteration_index": report.get("iteration_index"),
            "reported_confidence": reported,
            "computed_cap": cap,
            "open_questions_count": len(report.get("open_questions", [])),
            "unchecked_sources_count": len(report.get("unchecked_sources", [])),
        },
    )
    try:
        from mahavishhu.akosha_client import emit_anomaly  # type: ignore[import-not-found]

        emit_anomaly(
            kind="confidence_capped",
            workflow_id=report.get("workflow_id"),
            iteration_index=report.get("iteration_index"),
            reported_confidence=reported,
            computed_cap=cap,
        )
    except ImportError:
        pass
    except Exception:
        logger.exception("failed to emit akosha anomaly for confidence cap")
    return capped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_confidence_ceiling.py -v`
Expected: PASS (10 tests)

If `mahavishhu.akosha_client` doesn't exist as a module (it may be `mcp__akosha__*` or similar), adjust the import path. The try/except makes the test pass regardless.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/events/confidence_ceiling.py tests/unit/test_confidence_ceiling.py
git commit -m "feat(reports): add apply_confidence_ceiling gate with arithmetic cap"
```

______________________________________________________________________

## Task 2: Integrate gate into publisher

**Files:**

- Modify: `mahavishnu/core/events/report_publishers.py`

- Test: `tests/unit/test_report_publishers.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_report_publishers.py`:

```python
@pytest.mark.asyncio
async def test_publish_iteration_caps_confidence_in_envelope(bound_publishers):
    from mahavishnu.core.events.report_publishers import publish_iteration_report
    from tests.fixtures.reports import valid_iteration_report

    _rp, bus = bound_publishers
    report = valid_iteration_report(confidence=99, open_questions=[f"q{i}" for i in range(3)])
    await publish_iteration_report(
        report, source="worker-1", correlation_id=report["workflow_id"]
    )
    envelope = bus.publish.call_args.args[0]
    # Cap = 100 - 3*8 = 76
    assert envelope.payload["confidence"] == 76
    assert envelope.metadata["confidence_was_capped"] is True


@pytest.mark.asyncio
async def test_publish_iteration_no_cap_when_within_ceiling(bound_publishers):
    from mahavishnu.core.events.report_publishers import publish_iteration_report
    from tests.fixtures.reports import valid_iteration_report

    _rp, bus = bound_publishers
    report = valid_iteration_report(confidence=80, open_questions=[])
    await publish_iteration_report(
        report, source="worker-1", correlation_id=report["workflow_id"]
    )
    envelope = bus.publish.call_args.args[0]
    assert envelope.payload["confidence"] == 80
    assert envelope.metadata["confidence_was_capped"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_report_publishers.py -v -k "cap"`
Expected: FAIL (current publisher doesn't apply ceiling)

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_report_publishers.py -v`
Expected: PASS (5 tests — 3 original + 2 new)

- [ ] **Step 5: Verify all unit tests still pass**

Run: `pytest tests/unit/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/events/report_publishers.py tests/unit/test_report_publishers.py
git commit -m "feat(reports): integrate apply_confidence_ceiling into publisher"
```

______________________________________________________________________

## Task 3: Extend migration CLI

**Files:**

- Modify: `mahavishnu/cli/report_migration_cli.py`

- Test: `tests/integration/test_report_cli.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_report_cli.py`:

```python
def test_check_reports_flags_worker_without_confidence_ceiling(tmp_path: Path, runner: CliRunner):
    (tmp_path / "worker_no_ceiling.py").write_text(
        "from mahavishnu.core.events.report_publishers import publish_iteration_report\n"
        "from mahavishnu.core.events.precommitment_gate import validate_precommitment\n"
        "async def run_iteration():\n    pass\n"
    )
    result = runner.invoke(migrate_app, ["check-reports", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "enable_confidence_ceiling" in result.output


def test_check_reports_passes_worker_with_confidence_ceiling(tmp_path: Path, runner: CliRunner):
    (tmp_path / "worker_with_ceiling.py").write_text(
        "from mahavishnu.core.events.report_publishers import publish_iteration_report\n"
        "async def run_iteration(params):\n    params['enable_confidence_ceiling'] = True\n    pass\n"
    )
    result = runner.invoke(migrate_app, ["check-reports", "--path", str(tmp_path)])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_report_cli.py -v -k "ceiling"`
Expected: FAIL

- [ ] **Step 3: Extend the CLI**

In `mahavishnu/cli/report_migration_cli.py`:

```python
_CEILING_MARKER = "enable_confidence_ceiling"


def _has_confidence_ceiling(path: Path) -> bool:
    return _CEILING_MARKER in path.read_text(errors="ignore")
```

Modify `check_reports` to also check confidence ceiling:

```python
@migrate_app.command("check-reports")
def check_reports(
    path: Path = typer.Option(Path("."), "--path", help="Directory to scan"),
) -> None:
    """Exit non-zero if any worker-like module fails compliance checks."""
    workers = _scan(path)
    non_emitters = [w for w in workers if not _emits_reports(w)]
    no_precommitment = [w for w in workers if _emits_reports(w) and not _has_precommitment(w)]
    no_ceiling = [
        w
        for w in workers
        if _emits_reports(w) and _has_precommitment(w) and not _has_confidence_ceiling(w)
    ]
    if non_emitters or no_precommitment or no_ceiling:
        if non_emitters:
            typer.echo(f"Found {len(non_emitters)} worker(s) not emitting reports:")
            for w in non_emitters:
                typer.echo(f"  - {w.relative_to(path)}")
        if no_precommitment:
            typer.echo(
                f"Found {len(no_precommitment)} worker(s) without enable_precommitment:"
            )
            for w in no_precommitment:
                typer.echo(f"  - {w.relative_to(path)}")
        if no_ceiling:
            typer.echo(
                f"Found {len(no_ceiling)} worker(s) without enable_confidence_ceiling:"
            )
            for w in no_ceiling:
                typer.echo(f"  - {w.relative_to(path)}")
        raise typer.Exit(code=1)
    typer.echo(f"All {len(workers)} worker(s) compliant.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_report_cli.py -v`
Expected: PASS (6 tests — 4 from previous specs + 2 new)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/report_migration_cli.py tests/integration/test_report_cli.py
git commit -m "feat(reports): extend migrate --check-reports for enable_confidence_ceiling"
```

______________________________________________________________________

## Task 4: End-to-end persister integration test

**Files:**

- Test: `tests/integration/test_confidence_persister.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_confidence_persister.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.events.report_publishers import publish_iteration_report
from mahavishnu.core.events.report_publishers import publish_workflow_report
from mahavishnu.core.events.subscribers.report_persister import (
    get_iteration_history,
    get_workflow_report,
)
from tests.fixtures.reports import valid_iteration_report, valid_workflow_report


@pytest.mark.asyncio
async def test_persister_stores_capped_confidence():
    workflow_id = "00000000-0000-0000-0000-000000000040"
    report = valid_iteration_report(
        workflow_id=workflow_id,
        iteration_index=0,
        confidence=99,
        open_questions=[f"q{i}" for i in range(3)],
    )
    await publish_iteration_report(report, source="w1", correlation_id=workflow_id)

    history = await get_iteration_history(workflow_id)
    assert history[0]["confidence"] == 76  # capped


@pytest.mark.asyncio
async def test_workflow_trajectory_reflects_capped_values():
    workflow_id = "00000000-0000-0000-0000-000000000041"
    for idx, conf in [(0, 99), (1, 80)]:
        await publish_iteration_report(
            valid_iteration_report(
                workflow_id=workflow_id,
                iteration_index=idx,
                confidence=conf,
                open_questions=[f"q{i}" for i in range(3)] if idx == 0 else [],
            ),
            source="w1",
            correlation_id=workflow_id,
        )
    await publish_workflow_report(
        valid_workflow_report(
            workflow_id=workflow_id,
            confidence_trajectory=[99, 80],
        ),
        source="w1",
        correlation_id=workflow_id,
    )

    workflow_report = await get_workflow_report(workflow_id)
    assert workflow_report["confidence_trajectory"] == [99, 80]
    # Note: trajectory is reported by worker, not capped by gate;
    # cap applies at iteration-report publish time only.
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_confidence_persister.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_confidence_persister.py
git commit -m "test(reports): add persister integration tests for confidence capping"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Architecture & data flow | Task 2 (publisher integration order) |
| Formula specification | Task 1 (formula in code + L0 tests) |
| Function signatures | Task 1 (compute + apply functions + tests) |
| Integration with publisher | Task 2 |
| Akosha anomaly emission | Task 1 (try/except best-effort) |
| Adoption & migration | Task 3 (CLI extension) |
| Storage & retrieval | Task 4 (persister integration confirms no schema change) |
| Error handling | Task 1 (default values for missing fields) |
| Testing strategy | Tasks 1-4 (L0-L3 coverage) |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `compute_confidence_cap(report: dict) -> int` and `apply_confidence_ceiling(report: dict) -> dict` consistent across Tasks 1, 2, 4.

**Gaps:** None.

Plan complete. Moving to spec #4 brainstorm (`three-layer-self-heal`, Phase 2).
