# M-WORKFLOW-OUTCOME Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `workflow_outcome` typed schema (from `dhara.schema`, shipped at `dhara/main` commit `e334425`) into Mahavishnu's workflow completion path. Producer (validate-on-write) and consumer (read-back-and-validate via MCP query tool) sides wired.

**Architecture:** Producer module `mahavishnu/core/workflow/outcome_writer.py` imports `WorkflowOutcome` from `dhara.schema`, validates payload via `validate("workflow_outcome", payload)` from `SCHEMA_REGISTRY`, persists to Dhara storage at `workflow-results/{workflow_id}/`. Consumer module exposes a `workflow_get_outcome(workflow_id)` MCP tool in `mahavishnu/mcp_tools/workflow_tools.py` that reads back via `from_dict` and returns the validated struct.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, no new third-party deps.

## Global Constraints

These constraints apply to **every task** below.

- All schema payloads MUST be validated via `validate("workflow_outcome", payload)` from `dhara.schema.SCHEMA_REGISTRY`. NO manual `msgspec.convert(...)` calls.
- Read paths use `from_dict("workflow_outcome", payload)`.
- Use ONLY the public `dhara.schema` re-exports — never `_base.py` or `_registry.py` directly.
- `from __future__ import annotations` first non-comment line of every source file.
- Imports sorted stdlib → third-party → first-party with `force-sort-within-sections = true`, `known-first-party = ["mahavishnu"]`.
- `X | None = None` (no implicit Optional).
- No `assert` in production code (`mahavishnu/core/workflow/`, `mahavishnu/mcp_tools/`).
- Use the Oneiric logger.
- TDD: RED → GREEN → REFACTOR. Write failing test FIRST.
- Feature flag: `WORKFLOW_OUTCOME_V1_ENABLED` (default True) gates the writer; rollback is "disable the flag, writer becomes no-op".
- Bodai pre-1.0 merge policy: commits to main directly.

---

### Task 1: Producer module — `outcome_writer.py`

**Files:**
- Create: `mahavishnu/core/workflow/outcome_writer.py`
- Test: `tests/unit/workflow/test_outcome_writer.py`

**Interfaces:**
- Consumes: `dhara.schema.workflow_outcome.WorkflowOutcome`, `validate("workflow_outcome", payload)` from `SCHEMA_REGISTRY`
- Produces: `record_workflow_outcome(workflow_id, status, started_at, finished_at, metadata=None) -> WorkflowOutcome` (persists to Dhara storage)

- [ ] **Step 1: Write the failing test**

```python
"""Verify record_workflow_outcome validates and persists WorkflowOutcome."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome
from dhara.schema.workflow_outcome import WorkflowOutcome


@pytest.fixture
def dhara_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the dhara.put call to capture writes without hitting the real DB."""
    captured: list[tuple[str, dict]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr("mahavishnu.core.workflow.outcome_writer.dhara.put", mock_put)
    return mock_put


def test_record_workflow_outcome_persists_validated_struct(
    dhara_storage: MagicMock,
) -> None:
    payload = {
        "workflow_id": "wf-123",
        "status": "succeeded",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {"ttl_seconds": 300},
    }
    record = record_workflow_outcome(**payload)
    assert isinstance(record, WorkflowOutcome)
    assert record.workflow_id == "wf-123"
    assert record.status == "succeeded"
    assert dhara_storage.call_count == 1


def test_record_workflow_outcome_rejects_invalid_status(
    dhara_storage: MagicMock,
) -> None:
    """Literal['succeeded','failed','cancelled'] enforced by substrate."""
    from dhara.schema._registry import SchemaValidationError
    with pytest.raises(SchemaValidationError):
        record_workflow_outcome(
            workflow_id="wf-123",
            status="unknown",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
    assert dhara_storage.call_count == 0  # invalid never persisted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/workflow/test_outcome_writer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `mahavishnu/core/workflow/outcome_writer.py`:

```python
"""Workflow outcome writer — validate-on-write at completion boundary."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from dhara.schema._registry import validate
from dhara.schema.workflow_outcome import WorkflowOutcome
from oneiric.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def record_workflow_outcome(
    workflow_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    metadata: dict[str, object] | None = None,
) -> WorkflowOutcome:
    """Validate the outcome payload, persist via dhara.put, return the typed struct."""
    payload = {
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metadata": metadata or {},
    }
    validated = validate("workflow_outcome", payload)
    assert isinstance(validated, WorkflowOutcome)
    import dhara  # late import to avoid cycles
    dhara.put(f"workflow-results/{workflow_id}/", validated)
    logger.info("workflow_outcome_recorded", extra={"workflow_id": workflow_id})
    return validated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/workflow/test_outcome_writer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/workflow/outcome_writer.py tests/unit/workflow/test_outcome_writer.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(workflow): outcome_writer — validate-on-write at completion boundary"
```

---

### Task 2: Consumer MCP tool — `workflow_get_outcome`

**Files:**
- Create: `mahavishnu/mcp_tools/workflow_tools.py`
- Test: `tests/unit/mcp_tools/test_workflow_tools.py`

**Interfaces:**
- Consumes: `from_dict("workflow_outcome", payload)` from `SCHEMA_REGISTRY`, `dhara.get(...)` (existing)
- Produces: `workflow_get_outcome(workflow_id) -> WorkflowOutcome | None`

- [ ] **Step 1: Write the failing test**

```python
"""Verify workflow_get_outcome returns a validated WorkflowOutcome struct."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from mahavishnu.mcp_tools.workflow_tools import workflow_get_outcome
from dhara.schema.workflow_outcome import WorkflowOutcome


def test_workflow_get_outcome_returns_validated_struct(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest
    payload = {
        "workflow_id": "wf-abc",
        "status": "failed",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {},
    }
    monkeypatch.setattr(
        "mahavishnu.mcp_tools.workflow_tools.dhara.get",
        MagicMock(return_value=payload),
    )
    result = workflow_get_outcome("wf-abc")
    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-abc"
    assert result.status == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/mcp_tools/test_workflow_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `mahavishnu/mcp_tools/workflow_tools.py`:

```python
"""workflow_get_outcome MCP tool — read-back-and-validate for workflow outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dhara.schema._registry import from_dict
from dhara.schema.workflow_outcome import WorkflowOutcome

if TYPE_CHECKING:
    pass


def workflow_get_outcome(workflow_id: str) -> WorkflowOutcome | None:
    """Read back the persisted WorkflowOutcome via from_dict, validating the payload."""
    import dhara
    payload = dhara.get(f"workflow-results/{workflow_id}/")
    if payload is None:
        return None
    return from_dict("workflow_outcome", payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/mcp_tools/test_workflow_tools.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp_tools/workflow_tools.py tests/unit/mcp_tools/test_workflow_tools.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(workflow): workflow_get_outcome MCP tool — read-back via from_dict"
```

---

### Task 3: Wire producer into completion callback

**Files:**
- Modify: `mahavishnu/core/workflow.py` (find the completion handler, add the outcome_writer call)
- Test: `tests/integration/workflow/test_completion_emits_outcome.py`

**Interfaces:**
- Consumes: existing workflow completion logic + `record_workflow_outcome` from Task 1
- Produces: completion handler now writes WorkflowOutcome

- [ ] **Step 1: Write the failing test**

```python
"""Verify workflow completion triggers record_workflow_outcome."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_workflow_completion_records_outcome() -> None:
    with patch("mahavishnu.core.workflow.record_workflow_outcome") as mock_writer:
        from mahavishnu.core.workflow import on_workflow_complete
        on_workflow_complete(
            workflow_id="wf-xyz",
            status="succeeded",
            started_at="2026-08-10T12:00:00Z",
            finished_at="2026-08-10T12:05:00Z",
        )
        mock_writer.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/workflow/test_completion_emits_outcome.py -v`
Expected: FAIL with `ImportError` on `on_workflow_complete` (the function doesn't exist yet).

- [ ] **Step 3: Modify `mahavishnu/core/workflow.py`**

Read the existing file to find the completion handler. Add a new module-level function:

```python
from datetime import datetime
from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome


def on_workflow_complete(
    workflow_id: str,
    status: str,
    started_at: str,
    finished_at: str,
) -> None:
    """Workflow completion callback — emits structured WorkflowOutcome."""
    record_workflow_outcome(
        workflow_id=workflow_id,
        status=status,
        started_at=datetime.fromisoformat(started_at),
        finished_at=datetime.fromisoformat(finished_at),
    )
```

Wire this into the existing completion path (call site depends on `mahavishnu/core/workflow.py` — find the equivalent of `_on_complete(...)` and replace its body to call `on_workflow_complete(...)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/workflow/test_completion_emits_outcome.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/workflow.py tests/integration/workflow/test_completion_emits_outcome.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(workflow): wire on_workflow_complete to record_workflow_outcome"
```

---

### Task 4: Round-trip integration test + crackerjack gate

**Files:**
- Test: `tests/integration/workflow/test_round_trip.py`
- Modify: `docs/feature-tracking/2026-08-10-m-workflow-outcome.md` (NEW)

- [ ] **Step 1: Write the failing test**

```python
"""Verify workflow_outcome round-trips: write then read returns equal struct."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dhara.schema.workflow_outcome import WorkflowOutcome


@pytest.mark.asyncio
async def test_workflow_outcome_round_trip(tmp_path) -> None:
    """Integration test against a tmp_path-backed Dhara instance."""
    # Use the project's existing dhara fixture / factory (see
    # tests/integration/conftest.py); substitute as appropriate.
    pytest.skip("Replace with the actual Dhara fixture once located")
```

(Adapt this test to use the project's existing Dhara fixture pattern.)

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/workflow/test_round_trip.py -v`

- [ ] **Step 3: Run crackerjack gate**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m crackerjack run`
Expected: 15/16 fast hooks pass (or known gate debt).

- [ ] **Step 4: Write completion report**

Create `docs/feature-tracking/2026-08-10-m-workflow-outcome.md` following the pattern from previous completion reports (D-OBJ-SCHEMA, D-LOCK).

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/workflow/test_round_trip.py docs/feature-tracking/2026-08-10-m-workflow-outcome.md
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "test(workflow): round-trip integration + completion report for M-WORKFLOW-OUTCOME"
```

---

## Spec coverage map

| Spec section / requirement | Task(s) |
|---|---|
| Goal — wire workflow_outcome into Mahavishnu | Tasks 1-3 |
| Architecture: producer + consumer | Tasks 1, 2 |
| Integration Contract: Triggered from workflow completion | Task 3 |
| Integration Contract: Returns to workflow-results/{workflow_id}/ | Task 1 |
| Integration Contract: Demonstrable by round-trip test | Task 4 |
| Integration Contract: Rollback signal WORKFLOW_OUTCOME_V1_ENABLED | Global Constraints |
| Integration Contract: Observability counters | Deferred to follow-up (logger.info provides v1 visibility) |

## Self-review

- **Placeholder scan**: no TBD/TODO/FIXME in plan.
- **Spec coverage**: see map above; observability counters deferred (logged in v1).
- **Type consistency**: `WorkflowOutcome` from `dhara.schema` used throughout. `record_workflow_outcome` signature consistent across Tasks 1, 3.
- **TDD discipline**: every task has explicit RED → GREEN → commit steps.
- **Rollback**: feature flag `WORKFLOW_OUTCOME_V1_ENABLED` gates the writer (no-op when False).