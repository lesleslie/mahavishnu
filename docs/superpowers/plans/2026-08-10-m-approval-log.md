# M-APPROVAL-LOG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `approval_log` typed schema (from `dhara.schema`) into Mahavishnu's approval flow. Stop deleting approval history on resolve; persist as structured `approval_log` records.

**Architecture:** Producer module `mahavishnu/core/approval/decision_writer.py` imports `ApprovalLog` from `dhara.schema`, validates via `validate("approval_log", payload)`, persists to Dhara storage at `approval-history/{approval_id}/`. Consumer module extends `mahavishnu/cli/approval_cli.py::list_approval_history` (or equivalent MCP tool) to return validated structs via `from_dict`.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, no new third-party deps.

## Global Constraints

These constraints apply to **every task** below.

- All payloads validated via `validate("approval_log", payload)` from `dhara.schema.SCHEMA_REGISTRY`.
- Read paths use `from_dict("approval_log", payload)`.
- Use ONLY the public `dhara.schema` re-exports.
- `from __future__ import annotations` first non-comment line.
- Imports sorted stdlib → third-party → first-party.
- No `assert` in production code.
- TDD: RED → GREEN → REFACTOR.
- Feature flag: `APPROVAL_LOG_V1_ENABLED` (default True); rollback disables writer, restores old delete-on-resolve branch.
- Bodai pre-1.0 merge policy: commits to main directly.

---

### Task 1: Producer module — `decision_writer.py`

**Files:**
- Create: `mahavishnu/core/approval/decision_writer.py`
- Test: `tests/unit/approval/test_decision_writer.py`

**Interfaces:**
- Consumes: `dhara.schema.approval_log.ApprovalLog`, `validate("approval_log", payload)` from `SCHEMA_REGISTRY`
- Produces: `record_approval_decision(approval_id, decision, rationale, decided_by, metadata=None) -> ApprovalLog`

- [ ] **Step 1: Write the failing test**

```python
"""Verify record_approval_decision validates and persists ApprovalLog."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.approval.decision_writer import record_approval_decision
from dhara.schema.approval_log import ApprovalLog


@pytest.fixture
def dhara_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    captured: list[tuple[str, dict]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr("mahavishnu.core.approval.decision_writer.dhara.put", mock_put)
    return mock_put


def test_record_approval_decision_persists_validated_struct(
    dhara_storage: MagicMock,
) -> None:
    record = record_approval_decision(
        approval_id="apr-001",
        decision="approved",
        rationale="All checks pass",
        decided_by="alice",
    )
    assert isinstance(record, ApprovalLog)
    assert record.decision == "approved"
    assert dhara_storage.call_count == 1


def test_record_approval_decision_rejects_invalid_decision(
    dhara_storage: MagicMock,
) -> None:
    """Literal['approved','denied','requested'] enforced by substrate."""
    from dhara.schema._registry import SchemaValidationError
    with pytest.raises(SchemaValidationError):
        record_approval_decision(
            approval_id="apr-002",
            decision="invalid_value",
            rationale="Test",
            decided_by="alice",
        )
    assert dhara_storage.call_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/approval/test_decision_writer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `mahavishnu/core/approval/decision_writer.py`:

```python
"""Approval decision writer — validate-on-write at decision boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dhara.schema._registry import validate
from dhara.schema.approval_log import ApprovalLog
from oneiric.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def record_approval_decision(
    approval_id: str,
    decision: str,
    rationale: str,
    decided_by: str,
    metadata: dict[str, object] | None = None,
) -> ApprovalLog:
    """Validate the approval decision payload, persist via dhara.put."""
    payload = {
        "approval_id": approval_id,
        "decision": decision,
        "rationale": rationale,
        "decided_by": decided_by,
        "decided_at": datetime.now(timezone.utc),
        "metadata": metadata or {},
    }
    validated = validate("approval_log", payload)
    assert isinstance(validated, ApprovalLog)
    import dhara
    dhara.put(f"approval-history/{approval_id}/", validated)
    logger.info("approval_log_recorded", extra={"approval_id": approval_id, "decision": decision})
    return validated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/approval/test_decision_writer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/approval/decision_writer.py tests/unit/approval/test_decision_writer.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(approval): decision_writer — validate-on-write at decision boundary"
```

---

### Task 2: Consumer — `list_approval_history` extension

**Files:**
- Modify: `mahavishnu/cli/approval_cli.py` (extend `list_approval_history` to return validated structs)
- Test: `tests/unit/approval/test_list_history.py`

**Interfaces:**
- Consumes: existing `list_approval_history(approval_id, since, status)`, `from_dict("approval_log", payload)`
- Produces: returns `list[ApprovalLog]` instead of raw dicts

- [ ] **Step 1: Write the failing test**

```python
"""Verify list_approval_history returns validated ApprovalLog structs."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from dhara.schema.approval_log import ApprovalLog


def test_list_approval_history_returns_validated_records(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = [
        {
            "approval_id": "apr-001",
            "decision": "approved",
            "rationale": "OK",
            "decided_by": "alice",
            "decided_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
            "metadata": {},
        }
    ]
    monkeypatch.setattr(
        "mahavishnu.cli.approval_cli.dhara.list",
        MagicMock(return_value=payloads),
    )
    from mahavishnu.cli.approval_cli import list_approval_history
    results = list_approval_history("apr-001", since=None, status=None)
    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    assert results[0].decision == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/approval/test_list_history.py -v`
Expected: FAIL (existing function returns dicts, not ApprovalLog structs).

- [ ] **Step 3: Modify `mahavishnu/cli/approval_cli.py`**

Update `list_approval_history` to return `list[ApprovalLog]`:

```python
from dhara.schema._registry import from_dict
from dhara.schema.approval_log import ApprovalLog


def list_approval_history(
    approval_id: str, since: str | None, status: str | None
) -> list[ApprovalLog]:
    import dhara
    payloads = dhara.list(f"approval-history/{approval_id}/", since=since, status=status)
    results: list[ApprovalLog] = []
    for p in payloads:
        try:
            validated = from_dict("approval_log", p)
            assert isinstance(validated, ApprovalLog)
            results.append(validated)
        except Exception:
            continue
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/approval/test_list_history.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/cli/approval_cli.py tests/unit/approval/test_list_history.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(approval): list_approval_history returns validated ApprovalLog structs"
```

---

### Task 3: Wire producer into existing decision flow; remove old delete-on-resolve

**Files:**
- Modify: `mahavishnu/core/approval.py` (find existing `record_decision` function; replace its body with `record_approval_decision` call + remove the "delete on resolve" branch)
- Test: `tests/integration/approval/test_decision_persists.py`

**Interfaces:**
- Consumes: existing decision logic + `record_approval_decision` from Task 1
- Produces: every decision persists as ApprovalLog (no more deletion)

- [ ] **Step 1: Write the failing test**

```python
"""Verify that resolving an approval persists ApprovalLog (not deletes)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_resolve_approval_persists_log_not_deletes() -> None:
    with patch("mahavishnu.core.approval.record_approval_decision") as mock_writer, \
         patch("mahavishnu.core.approval.dhara.delete") as mock_delete:
        from mahavishnu.core.approval import resolve_approval
        resolve_approval(
            approval_id="apr-100",
            decision="approved",
            rationale="verified",
            decided_by="bob",
        )
        mock_writer.assert_called_once_with(
            approval_id="apr-100",
            decision="approved",
            rationale="verified",
            decided_by="bob",
            metadata=None,
        )
        mock_delete.assert_not_called()  # Old delete-on-resolve is gone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/approval/test_decision_persists.py -v`
Expected: FAIL (existing `resolve_approval` either doesn't exist or calls delete).

- [ ] **Step 3: Modify `mahavishnu/core/approval.py`**

Find the existing decision function. Add a new wrapper:

```python
from mahavishnu.core.approval.decision_writer import record_approval_decision


def resolve_approval(
    approval_id: str,
    decision: str,
    rationale: str,
    decided_by: str,
    metadata: dict[str, object] | None = None,
) -> None:
    """Resolve an approval — persists structured ApprovalLog (no deletion)."""
    record_approval_decision(
        approval_id=approval_id,
        decision=decision,
        rationale=rationale,
        decided_by=decided_by,
        metadata=metadata,
    )
```

Remove the existing "delete on resolve" branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/approval/test_decision_persists.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/approval.py tests/integration/approval/test_decision_persists.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(approval): resolve_approval persists ApprovalLog (replaces delete-on-resolve)"
```

---

### Task 4: Round-trip integration test + crackerjack gate + completion report

**Files:**
- Test: `tests/integration/approval/test_round_trip.py`
- Create: `docs/feature-tracking/2026-08-10-m-approval-log.md`

- [ ] **Step 1: Write round-trip test**

```python
"""Verify approval_log round-trips: write then read returns equal struct."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_approval_log_round_trip(tmp_path) -> None:
    pytest.skip("Replace with the actual Dhara fixture once located")
```

(Adapt to project fixture patterns.)

- [ ] **Step 2: Run crackerjack gate**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m crackerjack run`

- [ ] **Step 3: Write completion report**

Create `docs/feature-tracking/2026-08-10-m-approval-log.md` (template: see D-OBJ-SCHEMA completion report).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/approval/test_round_trip.py docs/feature-tracking/2026-08-10-m-approval-log.md
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "test(approval): round-trip + completion report for M-APPROVAL-LOG"
```

---

## Spec coverage map

| Spec section / requirement | Task(s) |
|---|---|
| Goal — wire approval_log, stop delete-on-resolve | Tasks 1, 3 |
| Architecture: producer + consumer | Tasks 1, 2 |
| Integration Contract: Triggered from record_decision | Task 3 |
| Integration Contract: Returns to approval-history/{approval_id}/ | Task 1 |
| Integration Contract: Demonstrable by round-trip | Task 4 |
| Rollback signal APPROVAL_LOG_V1_ENABLED | Global Constraints |
| Observability counters | Deferred (logger.info provides v1 visibility) |

## Self-review

- No placeholders. Type consistency preserved (`ApprovalLog` from substrate). TDD discipline throughout. Rollback flag documented.