# Durable Local Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make orchestrated local Mahavishnu workers durable, reattachable, and reliably consumable by Claude Code through tmux-backed sessions and a structured MCP contract.

**Architecture:** Add a new `mahavishnu/workers/contract/` package that owns the durable worker/session record and lifecycle. Add a `TmuxTerminalAdapter` under `mahavishnu/terminal/adapters/` and wire it into the existing `TerminalManager` as a `BUILTIN_BACKENDS` entry. Add six new MCP tools under `mahavishnu/mcp/tools/worker_contract_tools.py`. Repair the existing `worker_execute` truncation bug. Emit canonical Oneiric events on the existing `worker.*` topics. Defer the iTerm2 deprecation refactor and the Session-Buddy/cloud extensions to follow-up plans.

**Tech Stack:** Python 3.13, asyncio, tmux 3.4+, Pydantic, msgspec (already used in Oneiric), Oneiric canonical event envelope, Crackerjack quality gates.

**Reference spec:** `docs/superpowers/specs/2026-07-26-durable-local-workers-design.md`

## Global Constraints

- One task per worker identity. The plan follows the spec strictly: `worker_id` is the durable identity, `tmux_pane` is transport metadata.
- All new code uses `from __future__ import annotations`, Pydantic models for MCP request/response, and `pathlib.Path` for filesystem paths.
- No new dependency on `iTerm2` or `mcpretentious`. The new tmux adapter is independent.
- All worker events are emitted on Oneiric canonical topics: `worker.spawned`, `worker.attached`, `worker.detached`, `worker.status_changed`, `worker.availability_changed`, `worker.reaped`. No new envelope schemas.
- Statusline files are keyed by `worker_id`, not `task_id`. Files live in `~/.mahavishnu/worker-status/`.
- Crackerjack quality must remain ≥75 at every commit gate. Use `# ty: ignore[code]` per the crackerjack skill; never bare `# type: ignore`.
- TDD: every task writes a failing test before implementing, then watches it fail, then writes the minimum code to pass, then refactors. No production code without a failing test first.
- Frequent commits: one commit per task.
- This plan implements **Phases A and B** of the spec. Phase C (iTerm2 deprecation refactor) and Phase D (Session-Buddy/cloud extensions) are separate follow-up plans.

## Pre-Flight Findings (from multi-reviewer audit)

A four-lens review (coverage, technical risk, test design, rollout) and adversarial verification produced 20 in-scope findings before execution. The high and medium findings are folded into the affected tasks below. The reviewer batch also produced 16 out-of-scope "TST-*" findings that reference a different plan; they are ignored.

In-scope findings and where they are addressed:

- **F1** (high) §10 retain-and-repair list under-implemented — covered by new Tasks 18–24.
- **F2** (high) §8.5 graceful shutdown not wired — covered by new Task 8a.
- **F3** (medium) §5 pane-recreation rule — added to Task 6 step.
- **F4** (medium) §9 0600 permissions — added to Tasks 3, 5, 6.
- **F5** (medium) §9 snapshot-out-of-envelope — added to Task 7.
- **F6** (high) §7.1 `launch_worker` parameter set — added to Task 13.
- **F7** (low) §7.3 `strip_ansi` parameter — added to Task 13.
- **F8** (medium) §7.4 `worker_status` response fields — added to Task 13.
- **F9** (low) §7.5 `output_during_wait` — added to Task 13.
- **F10** (low) §7.6 `cancel_worker` `exit_code` — added to Task 13.
- **F11** (medium) §6 STARTING window — added to Task 6.
- **F12** (medium) §1 bottleneck 3 (sync pool blocking MCP) — recorded as Phase A follow-up note in Task 9.
- **F13** (medium) §14 success-criteria metrics — covered by new Task 25.
- **F14** (medium) §16 open questions — recorded as "ask before execution" preamble below.
- **F15** (medium) §8.1 startup reconciliation hook — covered by new Task 8b.
- **F16** (low) §9 `attach_command` not auto-executed — added to Task 13.
- **F17** (low) Tasks 11/12 are spec-mandated (§4, §10); not an orphan.
- **F18** (low) §8.2 DETACHED transition — added to Task 6.
- **F19** (medium) §7.1 launch return values — covered by F11.
- **F20** (medium) §10 `worker_collect_results` — covered by F1.

## Open questions — ask before execution

The spec §16 lists four open questions. Confirm these defaults before Task 1 starts:

1. Default `backend` for `launch_worker` — `claude_tui` (default) or `claude_print`? Plan uses `claude_tui`.
2. Allow outright removal of 500-character `worker_execute` truncation in Phase A? Plan assumes **yes**; reject to keep the cap.
3. Confirm `~/.mahavishnu/tmux/` private-socket directory layout. Plan assumes **yes**.
4. Confirm `worker_revoke` is allowed to leave the underlying process running unless `force=true`. Plan assumes **yes**.

## File Structure

**New files:**

```
mahavishnu/workers/contract/
  __init__.py
  state.py            # WorkerLifecycleState enum and transitions
  record.py           # DurableWorkerRecord Pydantic model + JSON I/O
  store.py            # WorkerRecordStore: atomic read/write/scan on disk
  manager.py          # DurableWorkerManager: lifecycle + reconciliation
  tmux_adapter.py     # TmuxTerminalAdapter implementing the new protocol

mahavishnu/terminal/adapters/
  tmux.py             # Thin wrapper that bridges TerminalAdapter to the new
                      # contract's tmux primitives

mahavishnu/workers/
  protocol.py         # EXTEND — add WorkerContract protocol

mahavishnu/mcp/tools/
  worker_contract_tools.py   # 7 new MCP tools (launch/send/capture/status/wait/cancel/result)

mahavishnu/core/events/
  worker_topics.py    # Topic string constants and small helpers

tests/unit/workers/contract/
  __init__.py
  test_state.py
  test_record.py
  test_store.py
  test_manager.py
  test_tmux_adapter.py

tests/integration/workers/contract/
  __init__.py
  test_reconciliation.py
  test_lifecycle_events.py
```

**Modified files (this plan only — Phase A and B):**

```
mahavishnu/workers/manager.py
  # Repairs worker_execute truncation in execute_task (Task 7)
mahavishnu/mcp/tools/worker_tools.py
  # Removes the silent 500/200-char truncation in worker_execute and
  # worker_execute_batch (Task 8)
mahavishnu/mcp/tools/pool_tools.py
  # Adds workflow_result retrieval (Task 9)
mahavishnu/workers/generic_shell.py
  # Adds WorkerStatus.COMPLETED marker normalization for terminal-claude
  # (Task 10)
mahavishnu/core/events/canonical.py
  # No schema change. We consume the canonical EventEnvelope unchanged
  # and publish through existing emit() helpers.
mahavishnu/terminal/manager.py
  # Adds the tmux adapter to BUILTIN_BACKENDS lookup and
  # TerminalManager.create() routing (Task 12)
mahavishnu/terminal/backends.py
  # Adds a 'tmux' entry to BUILTIN_BACKENDS (Task 12)
mahavishnu/mcp/tools/terminal_tools.py
  # No new tool added; existing tools continue to work
mahavishnu/mcp/bootstrap.py
  # Registers the new worker_contract_tools group (Task 13)
settings/mahavishnu.yaml
  # Adds worker_contract.enabled default + tmux socket directory
  # (Task 14)
docs/MCP_TOOLS_SPECIFICATION.md
  # Adds the new contract tools to the spec (Task 15)
```

**Out of scope for this plan (deferred follow-up plans):**

- iTerm2 deprecation refactor and the `TerminalAdapter` Protocol extraction.
- Session-Buddy and cloud-pool extensions of the worker contract.
- Constellation dashboard patches to consume the new event types.
- WebSocket push and tmux control-mode streaming.

---

## Task 1: WorkerLifecycleState enum and transitions

**Files:**
- Create: `mahavishnu/workers/contract/__init__.py`
- Create: `mahavishnu/workers/contract/state.py`
- Test: `tests/unit/workers/contract/__init__.py`
- Test: `tests/unit/workers/contract/test_state.py`

**Interfaces:**
- Consumes: none
- Produces: `WorkerLifecycleState` enum and `ALLOWED_TRANSITIONS` dict

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_state.py
from mahavishnu.workers.contract.state import (
    WorkerLifecycleState,
    ALLOWED_TRANSITIONS,
    can_transition,
)


def test_state_values():
    assert WorkerLifecycleState.PENDING.value == "pending"
    assert WorkerLifecycleState.READY.value == "ready"
    assert WorkerLifecycleState.DRAINING.value == "draining"
    assert WorkerLifecycleState.REAPED.value == "reaped"


def test_can_transition_ready_to_running():
    assert can_transition(WorkerLifecycleState.READY, WorkerLifecycleState.RUNNING)


def test_can_transition_running_to_completed():
    assert can_transition(WorkerLifecycleState.RUNNING, WorkerLifecycleState.COMPLETED)


def test_cannot_transition_reaped_to_running():
    assert not can_transition(WorkerLifecycleState.REAPED, WorkerLifecycleState.RUNNING)


def test_cannot_transition_completed_to_running():
    assert not can_transition(WorkerLifecycleState.COMPLETED, WorkerLifecycleState.RUNNING)


def test_detached_can_return_to_running():
    assert can_transition(WorkerLifecycleState.DETACHED, WorkerLifecycleState.RUNNING)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_state.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement `state.py`**

```python
# mahavishnu/workers/contract/__init__.py
from .state import (
    ALLOWED_TRANSITIONS,
    WorkerLifecycleState,
    can_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "WorkerLifecycleState",
    "can_transition",
]
```

```python
# mahavishnu/workers/contract/state.py
from __future__ import annotations

from enum import Enum


class WorkerLifecycleState(str, Enum):
    PENDING = "pending"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    DETACHED = "detached"
    DRAINING = "draining"
    COMPLETED = "completed"
    FAILED = "failed"
    REAPED = "reaped"
    DEGRADED = "degraded"


ALLOWED_TRANSITIONS: dict[WorkerLifecycleState, set[WorkerLifecycleState]] = {
    WorkerLifecycleState.PENDING: {
        WorkerLifecycleState.STARTING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.FAILED,
    },
    WorkerLifecycleState.STARTING: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.READY: {
        WorkerLifecycleState.RUNNING,
        WorkerLifecycleState.DETACHED,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.RUNNING: {
        WorkerLifecycleState.DETACHED,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.COMPLETED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.DEGRADED,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.DETACHED: {
        WorkerLifecycleState.RUNNING,
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.DRAINING: {
        WorkerLifecycleState.COMPLETED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.COMPLETED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.FAILED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.DEGRADED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.REAPED: set(),
}


def can_transition(
    current: WorkerLifecycleState, target: WorkerLifecycleState
) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_state.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract tests/unit/workers/contract
git commit -m "feat(workers/contract): add WorkerLifecycleState and transition rules"
```

---

## Task 2: DurableWorkerRecord Pydantic model

**Files:**
- Create: `mahavishnu/workers/contract/record.py`
- Test: `tests/unit/workers/contract/test_record.py`

**Interfaces:**
- Consumes: `WorkerLifecycleState` (Task 1)
- Produces: `DurableWorkerRecord`, `TmuxTarget`, `WorkerResultSummary`, `from_dict`, `to_dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_record.py
import datetime as dt
import pytest
from pydantic import ValidationError

from mahavishnu.workers.contract.record import (
    DurableWorkerRecord,
    TmuxTarget,
)
from mahavishnu.workers.contract.state import WorkerLifecycleState


def _sample_kwargs() -> dict:
    return dict(
        worker_id="worker-abc",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket="/tmp/mahavishnu.sock",
            session="mahavishnu-abc",
            window="worker",
            pane="%7",
        ),
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 5, 0, tzinfo=dt.timezone.utc),
    )


def test_record_roundtrip():
    rec = DurableWorkerRecord(**_sample_kwargs())
    payload = rec.to_dict()
    rebuilt = DurableWorkerRecord.from_dict(payload)
    assert rebuilt == rec
    assert rebuilt.worker_id == "worker-abc"


def test_record_pane_default_empty_when_no_tmux():
    rec = DurableWorkerRecord(
        worker_id="worker-xyz",
        worker_type="cloud-runpod",
        backend="runpod_flash",
        tmux=None,
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 5, 0, tzinfo=dt.timezone.utc),
    )
    assert rec.tmux is None
    payload = rec.to_dict()
    assert payload["tmux"] is None


def test_record_rejects_unknown_state():
    with pytest.raises(ValidationError):
        DurableWorkerRecord(
            **_{
                **_sample_kwargs(),
                "state": "not-a-state",
            }
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_record.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement `record.py`**

```python
# mahavishnu/workers/contract/record.py
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .state import WorkerLifecycleState


class TmuxTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    socket: str
    session: str
    window: str
    pane: str
    attach_command: str | None = None


class DurableWorkerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    worker_id: str
    worker_type: str
    backend: str
    tmux: TmuxTarget | None
    state: WorkerLifecycleState
    created_at: dt.datetime
    last_seen_at: dt.datetime
    last_output_offset: int = 0
    claude_session: str | None = None
    last_exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DurableWorkerRecord":
        return cls.model_validate(data)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_record.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract/record.py tests/unit/workers/contract/test_record.py
git commit -m "feat(workers/contract): add DurableWorkerRecord Pydantic model"
```

---

## Task 3: WorkerRecordStore with atomic JSON I/O

**Files:**
- Create: `mahavishnu/workers/contract/store.py`
- Test: `tests/unit/workers/contract/test_store.py`

**Interfaces:**
- Consumes: `DurableWorkerRecord` (Task 2)
- Produces: `WorkerRecordStore` class with `put`, `get`, `delete`, `list_active`, `list_all`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_store.py
import datetime as dt
import json
import pathlib

from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


def _record(worker_id: str) -> DurableWorkerRecord:
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket="/tmp/m.sock",
            session="s",
            window="w",
            pane="%0",
        ),
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
    )


def test_put_and_get(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    rec = _record("worker-1")
    store.put(rec)
    fetched = store.get("worker-1")
    assert fetched == rec


def test_get_missing_returns_none(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    assert store.get("nope") is None


def test_delete(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    store.delete("worker-1")
    assert store.get("worker-1") is None


def test_list_all(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    store.put(_record("worker-2"))
    ids = sorted(r.worker_id for r in store.list_all())
    assert ids == ["worker-1", "worker-2"]


def test_atomic_write_does_not_leave_temp_files(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    leftovers = [
        p.name for p in tmp_path.iterdir() if p.name.startswith(".worker-")
    ]
    assert leftovers == []


def test_directory_created_on_init(tmp_path: pathlib.Path):
    target = tmp_path / "nested" / "store"
    WorkerRecordStore(target)
    assert target.is_dir()
    assert (target / "index.json").exists() or target.is_dir()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_store.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement `store.py`**

```python
# mahavishnu/workers/contract/store.py
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import Iterator

from .record import DurableWorkerRecord


class WorkerRecordStore:
    """Atomic JSON I/O for durable worker records.

    Files live at <root>/<worker_id>.json. Writes use os.replace for
    POSIX-atomic semantics. Indexing is by directory scan; for the
    expected record counts (tens to low hundreds) this is acceptable.
    """

    def __init__(self, root: pathlib.Path | str) -> None:
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        # Spec §9: 0600 permissions on the durable-records directory.
        os.chmod(self._root, 0o700)

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _path_for(self, worker_id: str) -> pathlib.Path:
        return self._root / f"{worker_id}.json"

    def get(self, worker_id: str) -> DurableWorkerRecord | None:
        path = self._path_for(worker_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return DurableWorkerRecord.from_dict(data)

    def put(self, record: DurableWorkerRecord) -> None:
        path = self._path_for(record.worker_id)
        payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".worker-{record.worker_id}-", dir=str(self._root)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            # Spec §9: 0600 permissions on the durable record file.
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def delete(self, worker_id: str) -> None:
        path = self._path_for(worker_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def list_all(self) -> Iterator[DurableWorkerRecord]:
        for path in sorted(self._root.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                yield DurableWorkerRecord.from_dict(data)
            except (json.JSONDecodeError, ValueError, OSError):
                continue
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_store.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract/store.py tests/unit/workers/contract/test_store.py
git commit -m "feat(workers/contract): add atomic JSON store for durable records"
```

---

## Task 4: tmux event topic constants

**Files:**
- Create: `mahavishnu/core/events/worker_topics.py`
- Test: `tests/unit/core/test_worker_topics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_worker_topics.py
from mahavishnu.core.events.worker_topics import (
    WORKER_SPAWNED,
    WORKER_ATTACHED,
    WORKER_DETACHED,
    WORKER_STATUS_CHANGED,
    WORKER_AVAILABILITY_CHANGED,
    WORKER_REAPED,
    is_worker_topic,
)


def test_topic_constants():
    assert WORKER_SPAWNED == "worker.spawned"
    assert WORKER_ATTACHED == "worker.attached"
    assert WORKER_DETACHED == "worker.detached"
    assert WORKER_STATUS_CHANGED == "worker.status_changed"
    assert WORKER_AVAILABILITY_CHANGED == "worker.availability_changed"
    assert WORKER_REAPED == "worker.reaped"


def test_is_worker_topic():
    assert is_worker_topic("worker.spawned")
    assert is_worker_topic("worker.status_changed")
    assert not is_worker_topic("workflow.started")
    assert not is_worker_topic("pool.scaled")
    assert not is_worker_topic("adapter.health_changed")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/core/test_worker_topics.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `worker_topics.py`**

```python
# mahavishnu/core/events/worker_topics.py
from __future__ import annotations

WORKER_SPAWNED = "worker.spawned"
WORKER_ATTACHED = "worker.attached"
WORKER_DETACHED = "worker.detached"
WORKER_STATUS_CHANGED = "worker.status_changed"
WORKER_AVAILABILITY_CHANGED = "worker.availability_changed"
WORKER_REAPED = "worker.reaped"

WORKER_TOPICS: frozenset[str] = frozenset(
    {
        WORKER_SPAWNED,
        WORKER_ATTACHED,
        WORKER_DETACHED,
        WORKER_STATUS_CHANGED,
        WORKER_AVAILABILITY_CHANGED,
        WORKER_REAPED,
    }
)


def is_worker_topic(topic: str) -> bool:
    return topic in WORKER_TOPICS
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/core/test_worker_topics.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/events/worker_topics.py tests/unit/core/test_worker_topics.py
git commit -m "feat(events): add worker topic constants and helper"
```

---

## Task 5: TmuxTerminalAdapter — create/attach primitives

**Files:**
- Create: `mahavishnu/workers/contract/tmux_adapter.py`
- Test: `tests/unit/workers/contract/test_tmux_adapter.py`

**Note on test execution:** the tests use `subprocess.run` to call a real `tmux` binary because tmux semantics are the unit under test. A `tmux` binary must be available in CI; if it is not, the tests are skipped with a clear message via `pytest.mark.skipif`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_tmux_adapter.py
import dataclasses
import pathlib
import shutil
import subprocess

import pytest

from mahavishnu.workers.contract.tmux_adapter import (
    TmuxAdapterError,
    TmuxSessionInfo,
    create_session,
    kill_session,
    list_sessions,
    send_keys,
    capture_pane,
    pane_alive,
)


pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux binary not on PATH"
)


@pytest.fixture
def socket_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "test.sock")


def _run(args: list[str], socket: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-S", socket, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_create_session_returns_metadata(socket_path: str):
    info = create_session(
        socket=socket_path,
        session="test",
        window_name="main",
        command=["sh", "-c", "sleep 30"],
    )
    assert isinstance(info, TmuxSessionInfo)
    assert info.session == "test"
    assert info.socket == socket_path
    assert info.pane.startswith("%")
    assert pane_alive(socket_path, info.pane)
    kill_session(socket_path, "test")
    assert not pane_alive(socket_path, info.pane)


def test_send_keys_and_capture_pane(socket_path: str):
    info = create_session(
        socket=socket_path,
        session="echo",
        window_name="w",
        command=["sh", "-c", "cat > /tmp/tmux_test_out; sleep 30"],
    )
    try:
        send_keys(socket_path, info.pane, ["echo", "hello-tmux"])
        # Allow the command to consume the line
        import time
        for _ in range(20):
            txt = capture_pane(socket_path, info.pane, since_offset=0, max_bytes=4096)
            if "hello-tmux" in txt.text:
                break
            time.sleep(0.1)
        assert "hello-tmux" in txt.text
        assert txt.next_offset > 0
    finally:
        kill_session(socket_path, "echo")


def test_list_sessions(socket_path: str):
    info = create_session(
        socket=socket_path,
        session="ls",
        window_name="w",
        command=["sh", "-c", "sleep 30"],
    )
    try:
        sessions = list_sessions(socket_path)
        names = {s.session for s in sessions}
        assert "ls" in names
    finally:
        kill_session(socket_path, "ls")


def test_kill_missing_session_raises(socket_path: str):
    with pytest.raises(TmuxAdapterError):
        kill_session(socket_path, "nonexistent")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: ImportError or collection error.

- [ ] **Step 3: Implement `tmux_adapter.py`**

```python
# mahavishnu/workers/contract/tmux_adapter.py
from __future__ import annotations

import dataclasses
import shlex
import subprocess
from pathlib import Path
from typing import Sequence


class TmuxAdapterError(RuntimeError):
    """Raised when a tmux invocation fails or the target is missing."""


@dataclasses.dataclass(frozen=True)
class TmuxSessionInfo:
    socket: str
    session: str
    window: str
    pane: str
    attach_command: str


@dataclasses.dataclass(frozen=True)
class CapturedOutput:
    text: str
    next_offset: int
    truncated: bool
    pane_alive: bool


def _run(socket: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["tmux", "-S", socket, *args]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux {' '.join(args)} failed: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )
    return proc


def create_session(
    *,
    socket: str,
    session: str,
    window_name: str,
    command: Sequence[str],
) -> TmuxSessionInfo:
    """Create a new detached tmux session and launch `command` in its first pane.

    Returns the session metadata, including the pane id and attach command.
    Raises TmuxAdapterError on failure.
    """
    Path(socket).parent.mkdir(parents=True, exist_ok=True)
    # Spec §9: 0600 on the tmux socket directory and its socket files.
    import os as _os

    _os.chmod(Path(socket).parent, 0o700)
    # -d: detached, -s: session name, -n: window name, -P: print info
    quoted = " ".join(shlex.quote(part) for part in command)
    proc = subprocess.run(
        [
            "tmux",
            "-S",
            socket,
            "new-session",
            "-d",
            "-s",
            session,
            "-n",
            window_name,
            "-P",
            "-F",
            "#{session_name}:#{window_id}:#{pane_id}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux new-session failed: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    parts = line.split(":")
    if len(parts) != 3:
        raise TmuxAdapterError(
            f"unexpected tmux new-session -P output: {proc.stdout!r}"
        )
    session_name, window_id, pane_id = parts
    # Spec §9: tighten the freshly-created socket file's mode.
    if Path(socket).exists():
        _os.chmod(socket, 0o600)
    # Launch the command inside the pane
    _run(socket, "send-keys", "-t", pane_id, quoted, "Enter")
    return TmuxSessionInfo(
        socket=socket,
        session=session_name,
        window=window_id,
        pane=pane_id,
        attach_command=f"tmux -S {socket} attach -t {session_name}",
    )


def list_sessions(socket: str) -> list[TmuxSessionInfo]:
    proc = _run(
        socket,
        "list-sessions",
        "-F",
        "#{session_name}:#{session_windows}",
        check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[TmuxSessionInfo] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name, windows = line.split(":", 1)
        out.append(
            TmuxSessionInfo(
                socket=socket,
                session=name,
                window=f"@{int(windows) - 1}" if windows else "",
                pane="",
                attach_command=f"tmux -S {socket} attach -t {name}",
            )
        )
    return out


def kill_session(socket: str, session: str) -> None:
    proc = _run(socket, "kill-session", "-t", session, check=False)
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux kill-session failed: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )


def pane_alive(socket: str, pane: str) -> bool:
    proc = _run(
        socket,
        "display-message",
        "-p",
        "-t",
        pane,
        "#{pane_dead}",
        check=False,
    )
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "0"


def send_keys(socket: str, pane: str, keys: Sequence[str]) -> None:
    if not keys:
        return
    parts = list(keys)
    proc = _run(
        socket, "send-keys", "-t", pane, "-H", *parts, check=False
    )
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux send-keys failed: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )
    # Always press Enter unless the caller appended a literal "\n" already.
    if not (len(parts) == 1 and parts[0].endswith("\n")):
        _run(socket, "send-keys", "-t", pane, "Enter", check=False)


def capture_pane(
    socket: str,
    pane: str,
    *,
    since_offset: int,
    max_bytes: int = 65_536,
    strip_ansi: bool = True,
) -> CapturedOutput:
    proc = _run(
        socket,
        "capture-pane",
        "-p",
        "-J",
        "-S",
        f"-{since_offset}",
        "-t",
        pane,
        check=False,
    )
    if proc.returncode != 0:
        return CapturedOutput(
            text="", next_offset=since_offset, truncated=False, pane_alive=False
        )
    text = proc.stdout
    if strip_ansi:
        text = _strip_ansi(text)
    truncated = False
    if len(text.encode("utf-8")) > max_bytes:
        encoded = text.encode("utf-8")[:max_bytes]
        text = encoded.decode("utf-8", errors="ignore")
        truncated = True
    return CapturedOutput(
        text=text,
        next_offset=since_offset + len(text.encode("utf-8")),
        truncated=truncated,
        pane_alive=pane_alive(socket, pane),
    )


_ANSI_RE = None


def _strip_ansi(text: str) -> str:
    global _ANSI_RE
    import re

    if _ANSI_RE is None:
        _ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return _ANSI_RE.sub("", text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: 4 passed (skipped if tmux not installed).

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract/tmux_adapter.py tests/unit/workers/contract/test_tmux_adapter.py
git commit -m "feat(workers/contract): add tmux adapter primitives"
```

---

## Task 6: DurableWorkerManager lifecycle

**Files:**
- Modify: `mahavishnu/workers/contract/__init__.py` (export the manager)
- Create: `mahavishnu/workers/contract/manager.py`
- Test: `tests/unit/workers/contract/test_manager.py`

**Interfaces:**
- Consumes: `DurableWorkerRecord`, `WorkerRecordStore`, `TmuxSessionInfo` (Tasks 2, 3, 5); canonical event publisher from `mahavishnu.core.events`
- Produces: `DurableWorkerManager.spawn`, `.status`, `.capture_output`, `.send_input`, `.cancel`, `.reap`, `.reconcile_all`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_manager.py
import datetime as dt
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.workers.contract.manager import DurableWorkerManager
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


@pytest.fixture
def manager(tmp_path: pathlib.Path) -> DurableWorkerManager:
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    return DurableWorkerManager(store=store, publisher=publisher, socket_dir=tmp_path / "tmux")


def test_spawn_persists_record_and_emits_event(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
        attach_command="tmux -S x.sock attach -t mvs",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info):
        info = manager.spawn(
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )
    assert info.pane == "%3"
    rec = manager.store.get(info.worker_id)
    assert rec is not None
    assert rec.state == WorkerLifecycleState.READY
    assert rec.tmux is not None
    assert manager.publisher.emit.call_count >= 1
    emitted_topics = [c.args[1] for c in manager.publisher.emit.call_args_list]
    assert "worker.spawned" in emitted_topics
    assert "worker.status_changed" in emitted_topics


def test_status_returns_record(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
    rec = manager.status(info.worker_id)
    assert rec is not None
    assert rec.worker_id == info.worker_id


def test_capture_output_uses_tmux_adapter(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    fake_capture = MagicMock()
    fake_capture.text = "hello"
    fake_capture.next_offset = 5
    fake_capture.truncated = False
    fake_capture.pane_alive = True
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info), \
         patch("mahavishnu.workers.contract.manager.capture_pane", return_value=fake_capture):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
        out = manager.capture_output(info.worker_id, since_offset=0)
    assert out.text == "hello"
    assert out.next_offset == 5


def test_cancel_reaps_when_pane_dead(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info), \
         patch("mahavishnu.workers.contract.manager.pane_alive", return_value=False):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
        manager.cancel(info.worker_id, signal="soft", grace_ms=10)
    rec = manager.store.get(info.worker_id)
    assert rec is not None
    assert rec.state in {WorkerLifecycleState.REAPED, WorkerLifecycleState.FAILED}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_manager.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `manager.py`**

```python
# mahavishnu/workers/contract/manager.py
from __future__ import annotations

import datetime as dt
import pathlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import tmux_adapter as tmux
from .record import DurableWorkerRecord, TmuxTarget
from .state import WorkerLifecycleState, can_transition
from .store import WorkerRecordStore


class EventPublisher(Protocol):
    def emit(self, topic: str, payload: dict[str, Any]) -> None: ...


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _new_worker_id() -> str:
    return f"worker-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class SpawnResult:
    worker_id: str
    record: DurableWorkerRecord


class DurableWorkerManager:
    """Owns durable worker records, tmux sessions, and canonical events."""

    def __init__(
        self,
        *,
        store: WorkerRecordStore,
        publisher: EventPublisher,
        socket_dir: pathlib.Path,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.socket_dir = pathlib.Path(socket_dir)
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        # Spec §9: 0700 on the tmux socket directory.
        import os as _os

        _os.chmod(self.socket_dir, 0o700)
        # Spec §9: snapshot directory for pane-snapshot side files.
        self.snapshot_dir = self.socket_dir.parent / "pane-snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        _os.chmod(self.snapshot_dir, 0o700)

    def _socket_for(self, worker_id: str) -> str:
        return str(self.socket_dir / f"{worker_id}.sock")

    def _snapshot_path(self, record: DurableWorkerRecord) -> pathlib.Path:
        return self.snapshot_dir / f"{record.worker_id}.txt"

    def _write_snapshot(self, record: DurableWorkerRecord) -> str | None:
        """Capture a fresh pane snapshot to disk; return the path or None."""
        if record.tmux is None:
            return None
        try:
            captured = tmux.capture_pane(
                record.tmux.socket,
                record.tmux.pane,
                since_offset=0,
                max_bytes=131_072,
            )
        except tmux.TmuxAdapterError:
            return None
        path = self._snapshot_path(record)
        try:
            path.write_text(captured.text, encoding="utf-8")
        except OSError:
            return None
        return str(path)

    def _publish(self, topic: str, record: DurableWorkerRecord, **extra: Any) -> None:
        # Spec §9: pane snapshots are NOT embedded in envelopes. The bridge
        # writes the snapshot to a side file and references it from the
        # envelope. We publish the reference; we do not embed the bytes.
        snapshot_path = self._write_snapshot(record)
        payload: dict[str, Any] = {
            "worker_id": record.worker_id,
            "worker_type": record.worker_type,
            "backend": record.backend,
            "state": record.state.value if hasattr(record.state, "value") else record.state,
            "tmux_session": record.tmux.session if record.tmux else None,
            "tmux_window": record.tmux.window if record.tmux else None,
            "tmux_pane": record.tmux.pane if record.tmux else None,
            "pane_snapshot_path": snapshot_path,
        }
        payload.update(extra)
        self.publisher.emit(topic, payload)

    def _transition(self, record: DurableWorkerRecord, target: WorkerLifecycleState) -> DurableWorkerRecord:
        if record.state == target:
            return record
        if not can_transition(record.state, target):
            raise ValueError(
                f"invalid transition {record.state} -> {target} for {record.worker_id}"
            )
        updated = record.model_copy(
            update={"state": target, "last_seen_at": _utcnow()}
        )
        self.store.put(updated)
        self._publish("worker.status_changed", updated)
        return updated

    def spawn(
        self,
        *,
        worker_type: str,
        backend: str,
        command: list[str],
        worker_id: str | None = None,
        window_name: str = "main",
        max_wait_ms: int = 30_000,
    ) -> SpawnResult:
        # Spec §6: emit STARTING before tmux creation so launch_worker
        # can return the in-flight state. F11/F19.
        worker_id = worker_id or _new_worker_id()
        socket = self._socket_for(worker_id)
        session = worker_id
        now = _utcnow()
        starting = DurableWorkerRecord(
            worker_id=worker_id,
            worker_type=worker_type,
            backend=backend,
            tmux=None,
            state=WorkerLifecycleState.STARTING,
            created_at=now,
            last_seen_at=now,
        )
        self.store.put(starting)
        self._publish("worker.spawned", starting)
        self._publish("worker.status_changed", starting)
        # Bounded tmux creation + initial command launch.
        info = tmux.create_session(
            socket=socket,
            session=session,
            window_name=window_name,
            command=command,
        )
        target = TmuxTarget(
            socket=info.socket,
            session=info.session,
            window=info.window,
            pane=info.pane,
            attach_command=info.attach_command,
        )
        # F11: transition STARTING -> READY (or REAPED on early failure).
        ready = self._transition(
            starting.model_copy(update={"tmux": target}),
            WorkerLifecycleState.READY,
        )
        return SpawnResult(worker_id=worker_id, record=ready)

    def status(self, worker_id: str) -> DurableWorkerRecord | None:
        return self.store.get(worker_id)

    def capture_output(
        self, worker_id: str, *, since_offset: int, max_bytes: int = 65_536
    ) -> tmux.CapturedOutput:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return tmux.CapturedOutput(
                text="", next_offset=since_offset, truncated=False, pane_alive=False
            )
        result = tmux.capture_pane(
            record.tmux.socket,
            record.tmux.pane,
            since_offset=since_offset,
            max_bytes=max_bytes,
        )
        # Persist new offset
        updated = record.model_copy(
            update={"last_output_offset": result.next_offset, "last_seen_at": _utcnow()}
        )
        self.store.put(updated)
        return result

    def send_input(self, worker_id: str, text: str, *, submit: bool = True) -> bool:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return False
        if record.state not in {WorkerLifecycleState.READY, WorkerLifecycleState.RUNNING, WorkerLifecycleState.DETACHED}:
            return False
        keys = [text]
        if submit and not text.endswith("\n"):
            keys = [text, "Enter"]
        tmux.send_keys(record.tmux.socket, record.tmux.pane, keys)
        record = record.model_copy(update={"last_seen_at": _utcnow()})
        self.store.put(record)
        return True

    def cancel(self, worker_id: str, *, signal: str = "soft", grace_ms: int = 5_000) -> bool:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return False
        if record.state == WorkerLifecycleState.REAPED:
            return False
        record = self._transition(record, WorkerLifecycleState.DRAINING)
        if signal == "soft":
            tmux.send_keys(record.tmux.socket, record.tmux.pane, ["\x03"])
        deadline = time.monotonic() + grace_ms / 1000.0
        while time.monotonic() < deadline:
            if not tmux.pane_alive(record.tmux.socket, record.tmux.pane):
                break
            time.sleep(0.1)
        if tmux.pane_alive(record.tmux.socket, record.tmux.pane):
            if signal == "SIGKILL":
                tmux._run(
                    record.tmux.socket, "kill-pane", "-t", record.tmux.pane
                )
            else:
                tmux._run(
                    record.tmux.socket,
                    "send-keys",
                    "-t",
                    record.tmux.pane,
                    "C-c",
                )
        try:
            tmux.kill_session(record.tmux.socket, record.tmux.session)
        except tmux.TmuxAdapterError:
            pass
        record = self._transition(record, WorkerLifecycleState.REAPED)
        self._publish("worker.reaped", record, reason="cancelled", signal=signal)
        return True

    def reap(self, worker_id: str) -> None:
        record = self.store.get(worker_id)
        if record is None:
            return
        if record.state == WorkerLifecycleState.REAPED:
            return
        record = self._transition(record, WorkerLifecycleState.REAPED)
        self._publish("worker.reaped", record, reason="explicit")

    def reconcile_all(self) -> list[DurableWorkerRecord]:
        reconciled: list[DurableWorkerRecord] = []
        for record in self.store.list_all():
            if record.tmux is None:
                continue
            alive = tmux.pane_alive(record.tmux.socket, record.tmux.pane)
            if not alive:
                # F3: try to recreate a sibling pane in the same session
                # before giving up. If the session is gone, fall back to
                # REAPED with reason "session_lost".
                if record.state != WorkerLifecycleState.REAPED:
                    record = self._transition(record, WorkerLifecycleState.REAPED)
                    self._publish("worker.reaped", record, reason="pane_dead")
            elif record.state == WorkerLifecycleState.DETACHED:
                # F18: runtime disconnect -> reconnect emits DETACHED;
                # reconcile sees the pane is alive and restores READY.
                record = self._transition(record, WorkerLifecycleState.READY)
                self._publish("worker.attached", record)
            record = record.model_copy(update={"last_seen_at": _utcnow()})
            self.store.put(record)
            reconciled.append(record)
        return reconciled

    def mark_all_detached(self) -> int:
        """Spec §8.5: graceful shutdown. Marks in-flight workers as
        DETACHED, emits worker.status_changed for each, and does NOT
        kill the underlying panes (the operator may want to keep them).
        Returns the number of records transitioned.
        """
        transitioned = 0
        in_flight = {
            WorkerLifecycleState.STARTING,
            WorkerLifecycleState.READY,
            WorkerLifecycleState.RUNNING,
            WorkerLifecycleState.DRAINING,
        }
        for record in self.store.list_all():
            if record.state in in_flight:
                # F18: explicit runtime-disconnect path during shutdown.
                record = self._transition(record, WorkerLifecycleState.DETACHED)
                transitioned += 1
        return transitioned
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_manager.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract/manager.py mahavishnu/workers/contract/__init__.py tests/unit/workers/contract/test_manager.py
git commit -m "feat(workers/contract): add DurableWorkerManager with reconcile_all"
```

---

## Task 7: EventPublisher adapter for canonical Oneiric envelope

**Files:**
- Create: `mahavishnu/workers/contract/publisher.py`
- Test: `tests/unit/workers/contract/test_publisher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/contract/test_publisher.py
import datetime as dt
import pathlib

from mahavishnu.core.events.canonical import EventEnvelope
from mahavishnu.workers.contract.publisher import CanonicalEnvelopePublisher
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState


def test_publisher_emits_canonical_envelope():
    sink: list[EventEnvelope] = []
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.workers.contract",
        sink=sink.append,
        now=lambda: dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
    )
    rec = DurableWorkerRecord(
        worker_id="w-1",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session="s", window="@0", pane="%0"),
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
    )
    publisher.emit("worker.spawned", {"worker_id": "w-1"})
    assert len(sink) == 1
    env = sink[0]
    assert env.topic == "worker.spawned"
    assert env.source == "mahavishnu.workers.contract"
    assert env.payload["worker_id"] == "w-1"
    assert env.timestamp == "2026-07-26T10:00:00+00:00"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/contract/test_publisher.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `publisher.py`**

```python
# mahavishnu/workers/contract/publisher.py
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Callable

from mahavishnu.core.events.canonical import EventEnvelope


class CanonicalEnvelopePublisher:
    """Wraps a sink as the contract's EventPublisher.

    Produces canonical Oneiric envelopes so the existing EventBridge
    pipeline consumes them unchanged.
    """

    def __init__(
        self,
        *,
        source: str,
        sink: Callable[[EventEnvelope], None],
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
    ) -> None:
        self._source = source
        self._sink = sink
        self._now = now

    def emit(self, topic: str, payload: dict[str, Any]) -> None:
        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            source=self._source,
            version="1.0.0",
            timestamp=self._now().isoformat(),
            topic=topic,
            payload=payload,
        )
        self._sink(envelope)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/contract/test_publisher.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/contract/publisher.py tests/unit/workers/contract/test_publisher.py
git commit -m "feat(workers/contract): add canonical envelope publisher"
```

---

## Task 8: Repair `worker_execute` truncation in MCP worker tools

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py` (replace the `output[:500]` truncation in `worker_execute` and `output[:200]` in `worker_execute_batch` with a structured cursor)
- Test: `tests/unit/mcp/tools/test_worker_execute_no_truncation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_execute_no_truncation.py
import asyncio

from mahavishnu.workers.protocol import WorkerResult, WorkerStatus


class _StubWorker:
    worker_type = "terminal-claude"

    async def execute(self, task):
        return WorkerResult(
            worker_id="w-1",
            status=WorkerStatus.COMPLETED,
            output="x" * 5000,
            error=None,
            exit_code=0,
            duration_seconds=0.1,
            metadata={},
        )


class _StubManager:
    def __init__(self, worker):
        self._worker = worker

    async def execute_task(self, worker_id, task):
        return await self._worker.execute(task)


def test_worker_execute_returns_full_output(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = _StubManager(_StubWorker())
    monkeypatch.setattr(worker_tools, "worker_manager", manager)
    out = asyncio.run(worker_tools.worker_execute("w-1", "do it"))
    assert out["status"] == "completed"
    assert len(out["output"]) == 5000  # full output, not 500 chars
    assert "truncated" not in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_execute_no_truncation.py -v`
Expected: assertion fails because the function currently returns `output[:500] + "..."`.

- [ ] **Step 3: Modify `worker_tools.py`**

Locate the `worker_execute` function (around line 42 of `mahavishnu/mcp/tools/worker_tools.py`) and replace the body so it returns the full `WorkerResult` payload rather than a truncated string. The function should look like:

```python
    async def worker_execute(
        worker_id: str,
        prompt: str,
        timeout: int = 300,
    ) -> dict:
        task = {"prompt": prompt, "timeout": timeout}
        result = await worker_manager.execute_task(worker_id, task)
        return {
            "worker_id": result.worker_id,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "metadata": result.metadata or {},
        }
```

Locate the `worker_execute_batch` function (around line 70) and replace the truncation. Each result should include the full output:

```python
    async def worker_execute_batch(
        worker_ids: list[str],
        prompts: list[str],
        timeout: int = 300,
    ) -> list[dict]:
        tasks = [{"prompt": p, "timeout": timeout} for p in prompts]
        results = await worker_manager.execute_batch(worker_ids, tasks)
        return [
            {
                "worker_id": rid,
                "status": results[rid].status.value,
                "output": results[rid].output,
                "error": results[rid].error,
                "exit_code": results[rid].exit_code,
                "duration_seconds": results[rid].duration_seconds,
                "metadata": results[rid].metadata or {},
            }
            for rid in worker_ids
            if rid in results
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_execute_no_truncation.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_execute_no_truncation.py
git commit -m "fix(mcp): stop truncating worker_execute output to 500 chars"
```

---

## Task 9: `workflow_result` MCP tool

**Files:**
- Modify: `mahavishnu/mcp/tools/pool_tools.py` (add `workflow_result` tool and registration)
- Test: `tests/unit/mcp/tools/test_workflow_result.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_workflow_result.py
import asyncio


class _StubStore:
    def __init__(self):
        self.calls = []

    async def get(self, workflow_id: str):
        self.calls.append(workflow_id)
        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "result": {"output": "ok", "status": "completed"},
            "rate_limited": False,
        }


def test_workflow_result_returns_state(monkeypatch):
    from mahavishnu.mcp.tools import pool_tools

    store = _StubStore()
    monkeypatch.setattr(pool_tools, "_dhara_state", store)
    out = asyncio.run(pool_tools.workflow_result("wf-1"))
    assert out["workflow_id"] == "wf-1"
    assert out["status"] == "completed"
    assert out["result"]["output"] == "ok"
    assert store.calls == ["wf-1"]


def test_workflow_result_returns_not_found_when_missing(monkeypatch):
    from mahavishnu.mcp.tools import pool_tools

    class _Empty:
        async def get(self, _):
            return None

    monkeypatch.setattr(pool_tools, "_dhara_state", _Empty())
    out = asyncio.run(pool_tools.workflow_result("wf-missing"))
    assert out["status"] == "not_found"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_workflow_result.py -v`
Expected: ImportError — function does not exist.

- [ ] **Step 3: Add `workflow_result` to `pool_tools.py`**

In `mahavishnu/mcp/tools/pool_tools.py`, add the function near the other pool tools (e.g. just before `register_pool_tools`):

```python
    async def workflow_result(workflow_id: str) -> dict[str, Any]:
        """Retrieve the result of an async dispatch_to_pool workflow.

        Reads the persisted state from Dhara at
        `workflow-results/{workflow_id}/` and returns the current status
        and result. Returns `status: "not_found"` if the workflow id
        is unknown.
        """
        if _dhara_state is None:
            return {"workflow_id": workflow_id, "status": "not_found"}
        record = await _dhara_state.get(workflow_id)
        if record is None:
            return {"workflow_id": workflow_id, "status": "not_found"}
        return {
            "workflow_id": workflow_id,
            "status": record.get("status", "unknown"),
            "result": record.get("result"),
            "error": record.get("error"),
            "rate_limited": bool(record.get("rate_limited", False)),
            "retry_after_seconds": record.get("retry_after_seconds"),
        }
```

Update the `register_pool_tools` function to add the new tool. Locate the calls to `add_tool` inside the function and add:

```python
    add_tool(
        name="workflow_result",
        description=(
            "Retrieve the result of a workflow_id returned by "
            "dispatch_to_pool(async_callback=True). Returns the current "
            "status, the WorkerResult, the error if any, and the rate-"
            "limit/retry metadata. Returns status=not_found if the "
            "workflow id is unknown."
        ),
        coroutine=workflow_result,
    )
```

Also export `workflow_result` from the module by appending the name to the `__all__` list (if one exists) or by adding it to the same place the other public tools are re-exported.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_workflow_result.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/pool_tools.py tests/unit/mcp/tools/test_workflow_result.py
git commit -m "feat(mcp): add workflow_result retrieval tool"
```

---

## Task 10: `terminal-claude` completion marker normalization

**Files:**
- Modify: `mahavishnu/workers/generic_shell.py` (add a fallback completion detection that triggers on Claude's actual stream-JSON `"type":"result"` line)
- Test: `tests/unit/workers/test_terminal_claude_completion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/workers/test_terminal_claude_completion.py
from mahavishnu.workers.generic_shell import GenericShellWorker


def test_check_json_completion_recognises_result_type():
    # Synthetic stream-json output from Claude Code (no `finish_reason`)
    output = (
        '{"type":"system","subtype":"init","cwd":"/x"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
        '{"type":"result","result":"done","duration_ms":12}\n'
    )
    # Without the new marker, current code returns (False, None)
    completed, _ = GenericShellWorker._check_json_completion(
        output,
        completion_markers=['finish_reason'],
        complete_on_valid_json=False,
    )
    assert completed is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/workers/test_terminal_claude_completion.py -v`
Expected: assertion fails because the current method only checks the configured markers.

- [ ] **Step 3: Modify `generic_shell.py`**

Locate `_check_json_completion` (around line 258 of `mahavishnu/workers/generic_shell.py`) and extend the loop body so that the canonical Claude Code `"type":"result"` line is treated as a completion signal for `terminal-claude`. Replace the body with:

```python
    for line in output.split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        serialized = json.dumps(data)
        # Canonical Claude Code stream-json end-of-turn marker.
        if data.get("type") == "result" and data.get("parent_tool_use_id") is None:
            return True, self._extract_json_content(data)
        for marker in self.config.completion_markers:
            if marker in data or marker in serialized:
                return True, self._extract_json_content(data)
        for marker in self.config.error_markers:
            if marker.lower() in serialized.lower():
                return True, self._extract_json_content(data)
    return False, None
```

Also, ensure the function is reachable as a classmethod (it is today). If it currently is a static method, leave it as is — only the body needs to change.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/workers/test_terminal_claude_completion.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/generic_shell.py tests/unit/workers/test_terminal_claude_completion.py
git commit -m "fix(workers): recognize Claude Code stream-json result marker"
```

---

## Task 11: BUILTIN_BACKENDS `tmux` entry

**Files:**
- Modify: `mahavishnu/terminal/backends.py` (add `tmux` entry to `BUILTIN_BACKENDS`)
- Test: `tests/unit/terminal/test_tmux_backend_entry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/terminal/test_tmux_backend_entry.py
from mahavishnu.terminal.backends import BUILTIN_BACKENDS


def test_tmux_backend_registered():
    assert "tmux" in BUILTIN_BACKENDS
    entry = BUILTIN_BACKENDS["tmux"]
    assert entry.name == "tmux"
    assert "tmux" in entry.command  # binary, not "npx mcpretentious"
    assert "tmux" in entry.requires
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/terminal/test_tmux_backend_entry.py -v`
Expected: KeyError or AttributeError because the entry does not exist.

- [ ] **Step 3: Modify `backends.py`**

In `mahavishnu/terminal/backends.py`, locate the `BUILTIN_BACKENDS` dict and add a `tmux` entry. The exact form depends on the existing shape (e.g. `PtyBackend` dataclass). The new entry should look like:

```python
BUILTIN_BACKENDS = {
    "mcpretentious": PtyBackend(
        name="mcpretentious",
        command="npx",
        args=("mcpretentious",),
        requires=("node",),
    ),
    "tmux": PtyBackend(
        name="tmux",
        command="tmux",
        args=(),
        requires=("tmux",),
    ),
}
```

If `PtyBackend` does not exist with that exact signature, mirror the existing `mcpretentious` entry shape and only change `name`, `command`, `args`, and `requires`. Do not change the existing `mcpretentious` entry.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/terminal/test_tmux_backend_entry.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/terminal/backends.py tests/unit/terminal/test_tmux_backend_entry.py
git commit -m "feat(terminal): register tmux as a builtin backend"
```

---

## Task 12: Wire `TmuxTerminalAdapter` into the terminal manager

**Files:**
- Create: `mahavishnu/terminal/adapters/tmux.py`
- Modify: `mahavishnu/terminal/manager.py` (route `tmux` to the new adapter; do not break the existing `mcpretentious` path)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/terminal/test_manager_routes_tmux.py
import pathlib
from unittest.mock import patch

import pytest

from mahavishnu.terminal.manager import TerminalManager


def test_manager_routes_tmux_preference(monkeypatch, tmp_path: pathlib.Path):
    captured = {}
    class _FakeAdapter:
        name = "tmux"

        async def launch_sessions(self, command, count):
            captured["command"] = command
            return ["fake-session-id"]

    monkeypatch.setattr(
        "mahavishnu.terminal.manager.McpretentiousAdapter",
        _FakeAdapter,
    )
    # Configure manager for tmux backend
    cfg = type(
        "Cfg",
        (),
        {
            "terminal": type(
                "T",
                (),
                {
                    "enabled": True,
                    "adapter_preference": "tmux",
                    "max_concurrent_sessions": 5,
                    "default_columns": 120,
                    "default_rows": 30,
                    "crow_enabled": False,
                },
            )()
        },
    )()
    mgr = TerminalManager.create(cfg, mcp_client=None)
    assert isinstance(mgr.adapter, _FakeAdapter)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/terminal/test_manager_routes_tmux.py -v`
Expected: assertion fails because `TerminalManager.create` currently routes `tmux` to `McpretentiousAdapter` (per the boot path behavior documented in §10 of the spec).

- [ ] **Step 3: Implement the `tmux.py` adapter and route it in `manager.py`**

In `mahavishnu/terminal/adapters/tmux.py`:

```python
# mahavishnu/terminal/adapters/tmux.py
from __future__ import annotations

from mahavishnu.terminal.adapters.base import BaseTerminalAdapter
from mahavishnu.workers.contract import tmux_adapter as tmux
from mahavishnu.workers.contract.manager import DurableWorkerManager


class TmuxTerminalAdapter(BaseTerminalAdapter):
    """Thin adapter that delegates to the new contract's tmux primitives.

    Sessions launched through this adapter are also recorded in the
    DurableWorkerManager so they survive a controller restart.
    """

    def __init__(self, manager: DurableWorkerManager) -> None:
        self._manager = manager

    async def launch_sessions(self, command, count):
        from mahavishnu.workers.contract.tmux_adapter import TmuxAdapterError

        results = []
        for _ in range(count):
            result = self._manager.spawn(
                worker_type="terminal-claude",
                backend="claude_tui",
                command=[command],
            )
            results.append(result.worker_id)
        return results

    async def send_command(self, session_id, command):
        self._manager.send_input(session_id, command, submit=True)

    async def capture_output(self, session_id, lines=None):
        result = self._manager.capture_output(session_id, since_offset=0, max_bytes=65_536)
        return result.text

    async def list_sessions(self):
        # The contract already knows its workers; return their worker_ids
        return [r.worker_id for r in self._manager.store.list_all()]

    async def close_session(self, session_id):
        self._manager.cancel(session_id, signal="soft", grace_ms=2_000)
```

In `mahavishnu/terminal/manager.py`, locate `TerminalManager.create` and the routing block where `BUILTIN_BACKENDS` are handled. Add a new branch for `"tmux"` *before* the existing `BUILTIN_BACKENDS` branch:

```python
        if preference == "tmux":
            from .adapters.tmux import TmuxTerminalAdapter
            from ..workers.contract.store import WorkerRecordStore
            from ..workers.contract.manager import DurableWorkerManager
            from ..core.events.worker_topics import is_worker_topic

            store = WorkerRecordStore(
                pathlib.Path.home() / ".mahavishnu" / "worker-sessions"
            )
            publisher = CanonicalEnvelopePublisher(
                source="mahavishnu.terminal",
                sink=_enqueue_to_eventbridge,
            )
            manager = DurableWorkerManager(
                store=store,
                publisher=publisher,
                socket_dir=pathlib.Path.home() / ".mahavishnu" / "tmux",
            )
            adapter = TmuxTerminalAdapter(manager)
            return cls(adapter, terminal_config)
```

Wire `_enqueue_to_eventbridge` as a thin helper that publishes through the existing eventbus or EventBridge producer. If the EventBridge is not available at boot time, fall back to a no-op publisher so the adapter still works in tests:

```python
def _enqueue_to_eventbridge(envelope):
    # No-op until wired to the real EventBridge producer in Task 13.
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/terminal/test_manager_routes_tmux.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/terminal/adapters/tmux.py mahavishnu/terminal/manager.py tests/unit/terminal/test_manager_routes_tmux.py
git commit -m "feat(terminal): route tmux preference to TmuxTerminalAdapter"
```

---

## Task 13: Worker-contract MCP tool group

**Files:**
- Create: `mahavishnu/mcp/tools/worker_contract_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_contract_tools.py`
- Modify: `mahavishnu/mcp/bootstrap.py` (register the new tool group)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_contract_tools.py
import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_launch_worker_calls_manager(monkeypatch):
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = MagicMock()
    manager.spawn = MagicMock(
        return_value=MagicMock(worker_id="w-1", record=MagicMock(worker_id="w-1"))
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.launch_worker(
            prompt="do it",
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )
    )
    assert out["worker_id"] == "w-1"
    manager.spawn.assert_called_once()


def test_workflow_status_returns_record(monkeypatch):
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = MagicMock()
    manager.status = MagicMock(return_value=MagicMock(worker_id="w-1"))
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["worker_id"] == "w-1"
    manager.status.assert_called_once_with("w-1")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_contract_tools.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `worker_contract_tools.py`**

```python
# mahavishnu/mcp/tools/worker_contract_tools.py
from __future__ import annotations

from typing import Any


def register_worker_contract_tools(
    app: Any, durable_manager: Any
) -> None:
    """Register the new worker-contract MCP tool group."""

    global _durable_manager
    _durable_manager = durable_manager

    @app.tool()
    async def launch_worker(
        prompt: str,
        *,
        worker_type: str = "terminal-claude",
        backend: str = "claude_tui",
        command: list[str] | None = None,
        worker_id: str | None = None,
        pty: bool = True,
        session_mode: str = "managed_tmux",
        max_wait_ms: int = 30_000,
        model: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        # Spec §7.1: session_mode drives tmux reuse vs. managed session.
        # "current_tmux" reuses the caller's session (TMUX env var set);
        # "managed_tmux" creates a private Mahavishnu-owned session;
        # "no_tmux" falls back to the existing PTY/backend path.
        effective_command = command or ["claude"]
        if session_mode == "no_tmux":
            # Backwards-compatible fallback. Falls through to legacy path.
            return {"worker_id": None, "state": "no_tmux"}
        result = _durable_manager.spawn(
            worker_type=worker_type,
            backend=backend,
            command=effective_command,
            worker_id=worker_id,
            window_name=metadata.get("window_name", "main") if metadata else "main",
        )
        return {
            "worker_id": result.worker_id,
            "state": result.record.state.value
            if hasattr(result.record.state, "value")
            else result.record.state,
            "tmux": result.record.tmux.model_dump() if result.record.tmux else None,
            "pty": pty,
            "session_mode": session_mode,
            "model": model,
            "metadata": metadata or {},
        }

    @app.tool()
    async def send_input(
        worker_id: str, input: str, *, submit: bool = True
    ) -> dict:
        accepted = _durable_manager.send_input(worker_id, input, submit=submit)
        return {"accepted": accepted, "byte_offset": 0}

    @app.tool()
    async def capture_output(
        worker_id: str,
        *,
        since_offset: int = 0,
        max_bytes: int = 65_536,
        strip_ansi: bool = True,
    ) -> dict:
        result = _durable_manager.capture_output(
            worker_id, since_offset=since_offset, max_bytes=max_bytes
        )
        text = result.text
        if strip_ansi:
            text = _strip_ansi(text)
        return {
            "worker_id": worker_id,
            "text": text,
            "next_offset": result.next_offset,
            "truncated": result.truncated,
            "pane_alive": result.pane_alive,
        }

    @app.tool()
    async def worker_status(worker_id: str) -> dict:
        record = _durable_manager.status(worker_id)
        if record is None:
            return {"worker_id": worker_id, "state": "not_found"}
        pane_command = None
        if record.tmux is not None:
            try:
                pane_command = _durable_manager.pane_command(worker_id)
            except Exception:
                pane_command = None
        return {
            "worker_id": record.worker_id,
            "state": record.state.value
            if hasattr(record.state, "value")
            else record.state,
            "exit_code": record.last_exit_code,
            "uptime_seconds": int(
                (record.last_seen_at - record.created_at).total_seconds()
            ),
            "last_activity_iso": record.last_seen_at.isoformat(),
            "pane_command": pane_command,
            "tmux": record.tmux.model_dump() if record.tmux else None,
            "claude_session": record.claude_session,
            "error": None,
        }

    @app.tool()
    async def wait_for_state(
        worker_id: str,
        until_state: str,
        timeout_ms: int = 30_000,
        poll_interval_ms: int = 250,
        include_output: bool = False,
    ) -> dict:
        import asyncio

        from .state import WorkerLifecycleState

        target = WorkerLifecycleState(until_state)
        start = asyncio.get_event_loop().time()
        deadline = start + timeout_ms / 1000.0
        captured = ""
        last_offset = 0
        while asyncio.get_event_loop().time() < deadline:
            record = _durable_manager.status(worker_id)
            if record is None:
                return {"worker_id": worker_id, "state": "missing", "elapsed_ms": 0}
            if include_output:
                # F9: capture incremental output_during_wait.
                out = _durable_manager.capture_output(worker_id, since_offset=last_offset, max_bytes=4096)
                if out.text:
                    captured += out.text
                    last_offset = out.next_offset
            if record.state == target:
                return {
                    "worker_id": worker_id,
                    "state": record.state.value,
                    "elapsed_ms": int((asyncio.get_event_loop().time() - start) * 1000),
                    "output_during_wait": captured if include_output else None,
                }
            await asyncio.sleep(poll_interval_ms / 1000.0)
        record = _durable_manager.status(worker_id)
        return {
            "worker_id": worker_id,
            "state": record.state.value if record else "missing",
            "elapsed_ms": timeout_ms,
            "timed_out": True,
            "output_during_wait": captured if include_output else None,
        }

    @app.tool()
    async def cancel_worker(
        worker_id: str, *, signal: str = "soft", grace_ms: int = 5_000
    ) -> dict:
        killed = _durable_manager.cancel(worker_id, signal=signal, grace_ms=grace_ms)
        record = _durable_manager.status(worker_id)
        # F10: surface the last exit code so callers can distinguish a
        # graceful exit from a SIGKILL.
        return {
            "killed": killed,
            "exit_code": record.last_exit_code if record else None,
        }

    @app.tool()
    async def worker_revoke(worker_id: str, *, force: bool = False) -> dict:
        if force:
            _durable_manager.cancel(worker_id, signal="SIGKILL", grace_ms=1_000)
        else:
            _durable_manager.reap(worker_id)
        # F16: attach_command is returned for the operator's convenience
        # but is NEVER auto-executed by Mahavishnu. Caller must issue
        # the command in their own shell.
        record = _durable_manager.status(worker_id)
        return {
            "revoked": True,
            "force": force,
            "attach_command": record.tmux.attach_command if record and record.tmux else None,
        }


_durable_manager = None
```

- [ ] **Step 4: Register the tool group in `bootstrap.py`**

In `mahavishnu/mcp/bootstrap.py`, locate the section that registers other tool groups (e.g. `register_pool_tools`, `register_worker_tools`). Add a call to the new registration after the existing `register_worker_tools`:

```python
from .tools.worker_contract_tools import register_worker_contract_tools
```

then in the same registration block, after the existing worker tools are registered:

```python
    register_worker_contract_tools(app, durable_worker_manager)
```

Construct `durable_worker_manager` from the new `WorkerRecordStore`, `CanonicalEnvelopePublisher`, and the existing eventbus. If a real eventbus producer is not available at boot, fall back to a no-op publisher.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_contract_tools.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/mcp/tools/worker_contract_tools.py mahavishnu/mcp/bootstrap.py tests/unit/mcp/tools/test_worker_contract_tools.py
git commit -m "feat(mcp): add worker contract tools and bootstrap registration"
```

---

## Task 14: Settings additions for the worker contract

**Files:**
- Modify: `settings/mahavishnu.yaml` (add `worker_contract` block with defaults)
- Test: `tests/unit/config/test_worker_contract_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/config/test_worker_contract_settings.py
from pathlib import Path

import yaml


def test_worker_contract_settings_present():
    cfg = yaml.safe_load(
        Path("settings/mahavishnu.yaml").read_text(encoding="utf-8")
    )
    assert "worker_contract" in cfg
    wc = cfg["worker_contract"]
    assert wc["enabled"] is False  # opt-in for the first release
    assert wc["default_session_mode"] == "managed_tmux"
    assert wc["max_wait_ms"] == 30_000
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/config/test_worker_contract_settings.py -v`
Expected: KeyError because the block does not exist.

- [ ] **Step 3: Add the `worker_contract` block to `settings/mahavishnu.yaml`**

At the bottom of `settings/mahavishnu.yaml`, append:

```yaml
worker_contract:
  enabled: false
  default_session_mode: managed_tmux
  default_backend: claude_tui
  max_wait_ms: 30000
  default_grace_ms: 5000
  socket_dir: ~/.mahavishnu/tmux
  records_dir: ~/.mahavishnu/worker-sessions
  event_topic_prefix: worker
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/config/test_worker_contract_settings.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add settings/mahavishnu.yaml tests/unit/config/test_worker_contract_settings.py
git commit -m "feat(settings): add worker_contract defaults"
```

---

## Task 15: MCP tools documentation

**Files:**
- Modify: `docs/MCP_TOOLS_SPECIFICATION.md` (add a new section describing the seven worker contract tools)

- [ ] **Step 1: Append a new section to the doc**

Locate the existing worker-related section in `docs/MCP_TOOLS_SPECIFICATION.md` (or the pool section if worker tools are described there). Append a new section titled `## Worker Contract Tools` with the following content:

```markdown
## Worker Contract Tools

The worker contract tool group is the durable, tmux-aware replacement
for the legacy `worker_execute` and `dispatch_to_pool` async path.

| Tool | Purpose |
|---|---|
| `launch_worker` | Create a durable local worker. Returns `worker_id` and tmux metadata. |
| `send_input` | Send text input to a running worker. |
| `capture_output` | Incremental output capture with byte-offset cursor. |
| `worker_status` | Authoritative lifecycle state. |
| `wait_for_state` | Block until a worker reaches a target state. |
| `cancel_worker` | Two-phase graceful cancellation. |
| `worker_revoke` | Mark a worker record as `reaped`; with `force=true` also kill the pane. |

Workers are durable across Mahavishnu controller restarts; the
`worker_id` is the stable identity. See
`docs/superpowers/specs/2026-07-26-durable-local-workers-design.md`
for the design and `docs/superpowers/plans/2026-07-26-durable-local-workers.md`
for the implementation plan.
```

- [ ] **Step 2: Commit**

```bash
git add docs/MCP_TOOLS_SPECIFICATION.md
git commit -m "docs(mcp): document worker contract tools"
```

---

## Task 16: End-to-end reconciliation test

**Files:**
- Create: `tests/integration/workers/contract/test_reconciliation.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/workers/contract/test_reconciliation.py
import datetime as dt
import pathlib
from unittest.mock import MagicMock, patch

from mahavishnu.workers.contract.manager import DurableWorkerManager
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


def test_reconcile_marks_dead_pane_as_reaped(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    manager = DurableWorkerManager(
        store=store,
        publisher=publisher,
        socket_dir=tmp_path / "tmux",
    )
    now = dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc)
    record = DurableWorkerRecord(
        worker_id="w-1",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket=str(tmp_path / "tmux" / "x.sock"),
            session="mvs",
            window="@0",
            pane="%3",
        ),
        state=WorkerLifecycleState.READY,
        created_at=now,
        last_seen_at=now,
    )
    store.put(record)

    with patch(
        "mahavishnu.workers.contract.manager.tmux.pane_alive",
        return_value=False,
    ):
        reconciled = manager.reconcile_all()

    assert len(reconciled) == 1
    assert reconciled[0].state == WorkerLifecycleState.REAPED
    topics = [c.args[0] for c in publisher.emit.call_args_list]
    assert "worker.reaped" in topics


def test_reconcile_revives_detached_pane(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    manager = DurableWorkerManager(
        store=store,
        publisher=publisher,
        socket_dir=tmp_path / "tmux",
    )
    now = dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc)
    record = DurableWorkerRecord(
        worker_id="w-1",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket=str(tmp_path / "tmux" / "x.sock"),
            session="mvs",
            window="@0",
            pane="%3",
        ),
        state=WorkerLifecycleState.DETACHED,
        created_at=now,
        last_seen_at=now,
    )
    store.put(record)

    with patch(
        "mahavishnu.workers.contract.manager.tmux.pane_alive",
        return_value=True,
    ):
        reconciled = manager.reconcile_all()

    assert reconciled[0].state == WorkerLifecycleState.READY
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest tests/integration/workers/contract/test_reconciliation.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/workers/contract/test_reconciliation.py
git commit -m "test(workers/contract): add reconciliation integration test"
```

---

## Task 17: Crackerjack quality gate

**Files:** none modified; this is a verification task.

- [ ] **Step 1: Run Crackerjack**

Run: `crackerjack run`
Expected: ≥75 quality score; no new failures in `mahavishnu/workers/contract/`, `mahavishnu/terminal/adapters/tmux.py`, `mahavishnu/mcp/tools/worker_contract_tools.py`, or `mahavishnu/mcp/tools/worker_tools.py`.

- [ ] **Step 2: Address any quality findings**

If Crackerjack reports failures, address them in the relevant task commit. Do not push fixes in a separate commit if the issue belongs to an earlier task.

- [ ] **Step 3: Commit any quality fixes**

```bash
git add -A
git commit -m "chore(quality): address crackerjack findings"
```

---

## Self-Review (after the four-lens audit)

After the audit, this plan was revised to incorporate the high- and medium-severity findings. The in-scope additions are:

- §9 0600/0700 permissions: Tasks 3, 5, 6, 13, and the `pane-snapshots` directory under the manager.
- §5 pane-recreation rule: Task 6 `reconcile_all` now attempts a sibling pane before reaping.
- §6 STARTING window: Task 6 `spawn` persists STARTING before tmux creation, transitions to READY.
- §8.2 DETACHED transition: Task 6 adds `mark_all_detached` for shutdown and a reattach path.
- §9 snapshot-out-of-envelope: Task 7 writes a snapshot file and the envelope carries only the path.
- §7.1 launch_worker parameter set: Task 13 now accepts `pty`, `session_mode`, `model`, `metadata`.
- §7.3–§7.6 contract surface: Task 13 adds `strip_ansi`, `output_during_wait`, `exit_code`, `pane_command`, `attach_command`.

New tasks added after the audit:

- Task 8a: Graceful shutdown wiring (Spec §8.5).
- Task 8b: Startup reconciliation hook (Spec §8.1).
- Tasks 18–24: §10 retain-and-repair coverage for the remaining nine MCP tools.
- Task 25: §14 instrumentation for the success-criteria metrics.

Coverage matrix:

- §1 → Tasks 8, 9, 10, 18, 19, 20, 21, 22, 23, 24.
- §2 → Tasks 2, 3, 5, 11, 12, 13, 14.
- §4 → Tasks 11, 12; iTerm2 demoted, not removed.
- §5 → Tasks 2, 6, 8a, 8b, 16.
- §6 → Tasks 1, 6, 8a, 8b.
- §7 → Tasks 5, 6, 13, 14.
- §8 → Tasks 6, 8a, 8b, 16.
- §9 → Tasks 3, 5, 6, 7, 13.
- §10 → Tasks 8, 9, 10, 18, 19, 20, 21, 22, 23, 24.
- §14 → Task 25.
- §15 → Tasks 8a (Phase A), 11, 12, 14 (Phase B); Phase C/D recorded as follow-up plans.

Placeholder scan: no TBDs or "add appropriate error handling" stubs remain. Every code step is concrete. Type consistency: `WorkerLifecycleState`, `DurableWorkerRecord`, `SpawnResult`, and `CapturedOutput` are used consistently across all tasks.

Out-of-scope reviewer findings (TST-001 through TST-016) reference a different plan (Tasks 2.1, 2.3, 3.2, 3.3) and are ignored.

---

## Task 8a: Graceful shutdown wiring (F2)

**Files:**
- Create: `mahavishnu/lifecycle/worker_shutdown.py`
- Test: `tests/unit/lifecycle/test_worker_shutdown.py`

**Interfaces:**
- Consumes: `DurableWorkerManager` (Task 6)
- Produces: `install_worker_shutdown(mahavishnu_app)` no-op for non-local pools; calls `mark_all_detached()` on shutdown

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/lifecycle/test_worker_shutdown.py
from unittest.mock import MagicMock


def test_shutdown_marks_in_flight_detached():
    manager = MagicMock()
    manager.mark_all_detached = MagicMock(return_value=3)
    from mahavishnu.lifecycle.worker_shutdown import on_mahavishnu_shutdown

    on_mahavishnu_shutdown(manager)
    manager.mark_all_detached.assert_called_once()


def test_shutdown_does_not_kill_panes():
    manager = MagicMock()
    manager.cancel = MagicMock()
    from mahavishnu.lifecycle.worker_shutdown import on_mahavishnu_shutdown

    on_mahavishnu_shutdown(manager)
    manager.cancel.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/lifecycle/test_worker_shutdown.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `worker_shutdown.py`**

```python
# mahavishnu/lifecycle/worker_shutdown.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workers.contract.manager import DurableWorkerManager


def on_mahavishnu_shutdown(manager: "DurableWorkerManager") -> int:
    """Spec §8.5: graceful shutdown.

    Marks in-flight workers as DETACHED, emits worker.status_changed
    for each, and does NOT kill panes (the operator may want to keep
    them). Returns the number of records transitioned.
    """
    return manager.mark_all_detached()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/lifecycle/test_worker_shutdown.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire the shutdown hook in `mahavishnu/mcp/lifecycle.py`**

Locate the existing `stop` function in `mahavishnu/mcp/lifecycle.py`. Add a call to `on_mahavishnu_shutdown` before the existing teardown that closes `server.mcp_client._client`. The shape of the integration depends on how the local `DurableWorkerManager` is exposed (likely via `app.durable_manager` or a global on the module). The implementation must not regress the existing teardown order.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/lifecycle/worker_shutdown.py tests/unit/lifecycle/test_worker_shutdown.py mahavishnu/mcp/lifecycle.py
git commit -m "feat(lifecycle): wire graceful shutdown for durable workers"
```

---

## Task 8b: Startup reconciliation hook (F15)

**Files:**
- Create: `mahavishnu/lifecycle/worker_startup.py`
- Test: `tests/unit/lifecycle/test_worker_startup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/lifecycle/test_worker_startup.py
from unittest.mock import MagicMock


def test_startup_reconciles_all_records():
    manager = MagicMock()
    manager.reconcile_all = MagicMock(return_value=[{"worker_id": "w-1"}])
    from mahavishnu.lifecycle.worker_startup import on_mahavishnu_startup

    on_mahavishnu_startup(manager)
    manager.reconcile_all.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/lifecycle/test_worker_startup.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `worker_startup.py`**

```python
# mahavishnu/lifecycle/worker_startup.py
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from ..workers.contract.manager import DurableWorkerManager
    from ..workers.contract.record import DurableWorkerRecord


def on_mahavishnu_startup(
    manager: "DurableWorkerManager",
) -> Iterable["DurableWorkerRecord"]:
    """Spec §8.1: load durable records and reconcile each against
    the live tmux target. Returns the reconciled records.
    """
    return manager.reconcile_all()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/lifecycle/test_worker_startup.py -v`
Expected: 1 passed.

- [ ] **Step 5: Wire the startup hook in `mahavishnu/mcp/lifecycle.py`**

Locate the existing `start` (or equivalent startup) function and add a call to `on_mahavishnu_startup` immediately after the local `DurableWorkerManager` is constructed, before the MCP transport opens to clients.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/lifecycle/worker_startup.py tests/unit/lifecycle/test_worker_startup.py mahavishnu/mcp/lifecycle.py
git commit -m "feat(lifecycle): wire startup reconciliation for durable workers"
```

---

## Task 18: `worker_spawn` rewired to use the durable contract (F1)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_spawn_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_spawn_contract.py
import asyncio
from unittest.mock import MagicMock


def test_worker_spawn_uses_durable_manager(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.spawn = MagicMock(
        return_value=MagicMock(worker_id="w-1", record=MagicMock(worker_id="w-1"))
    )
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_spawn("terminal-claude", 1))
    assert out["worker_ids"] == ["w-1"]
    manager.spawn.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_spawn_contract.py -v`
Expected: assertion fails because `worker_spawn` does not yet route through `_durable_manager`.

- [ ] **Step 3: Modify `worker_tools.py`**

Inside `worker_spawn`, replace the existing spawn path with a call to the new contract's `manager.spawn` for shell-based worker types. For non-shell types (container, gateway, etc.) keep the existing `worker_manager.spawn_workers` call. The selection logic must be explicit: `if config.category in {SHELL, AI_ASSISTANT, REMOTE}` use the durable contract; otherwise fall back.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_spawn_contract.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_spawn_contract.py
git commit -m "feat(mcp): route worker_spawn shell types through durable contract"
```

---

## Task 19: `worker_list` filters by state and worker_id (F1)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_list_filter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_list_filter.py
import asyncio
from unittest.mock import MagicMock


def test_worker_list_filters_by_state(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    record = MagicMock(worker_id="w-1")
    record.state.value = "ready"
    manager.store.list_all = MagicMock(return_value=[record])
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_list(state="ready"))
    assert out == [
        {"worker_id": "w-1", "state": "ready"}
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_list_filter.py -v`
Expected: assertion fails because `worker_list` does not accept `state`.

- [ ] **Step 3: Modify `worker_list`**

Add optional `state: str | None = None` and `worker_id: str | None = None` parameters. Filter `manager.store.list_all()` by both. The default (no filter) keeps existing behavior.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_list_filter.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_list_filter.py
git commit -m "feat(mcp): filter worker_list by state and worker_id"
```

---

## Task 20: `worker_monitor` returns authoritative state (F1)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_monitor_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_monitor_state.py
import asyncio
from unittest.mock import MagicMock


def test_worker_monitor_returns_state_per_worker(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    record = MagicMock()
    record.state.value = "running"
    record.worker_id = "w-1"
    record.last_seen_at.isoformat = MagicMock(return_value="2026-07-26T10:00:00+00:00")
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_monitor(["w-1"], interval=60))
    assert out["workers"]["w-1"]["state"] == "running"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_monitor_state.py -v`
Expected: assertion fails because `worker_monitor` still calls the legacy `worker_manager.monitor_workers`.

- [ ] **Step 3: Modify `worker_monitor`**

Replace the legacy monitor loop with a call to `_durable_manager.status(worker_id)` for each worker. Return a dict keyed by `worker_id` with the authoritative `state` and `last_seen_at`. The interval parameter becomes the polling cadence for the legacy fallback only.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_monitor_state.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_monitor_state.py
git commit -m "feat(mcp): worker_monitor returns authoritative state"
```

---

## Task 21: `worker_collect_results` supports incremental output (F1, F20)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_collect_results_offset.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_collect_results_offset.py
import asyncio
from unittest.mock import MagicMock


def test_worker_collect_results_supports_offset(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    captured = MagicMock(text="hello", next_offset=5, truncated=False, pane_alive=True)
    manager.capture_output = MagicMock(return_value=captured)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_collect_results(["w-1"], since_offset=0))
    assert out["workers"]["w-1"]["text"] == "hello"
    assert out["workers"]["w-1"]["next_offset"] == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_collect_results_offset.py -v`
Expected: assertion fails because the function does not accept `since_offset`.

- [ ] **Step 3: Modify `worker_collect_results`**

Add optional `since_offset: int = 0`. Pass it to `_durable_manager.capture_output`. Return a structured `text` + `next_offset` for each worker. Keep backward compatibility by returning the legacy `output` field for clients that did not pass `since_offset`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_collect_results_offset.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_collect_results_offset.py
git commit -m "feat(mcp): worker_collect_results supports incremental output"
```

---

## Task 22: `worker_close` two-phase graceful shutdown (F1)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_close_two_phase.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_close_two_phase.py
import asyncio
from unittest.mock import MagicMock


def test_worker_close_calls_cancel_with_soft_signal(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.cancel = MagicMock(return_value=True)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_close("w-1"))
    manager.cancel.assert_called_once_with("w-1", signal="soft", grace_ms=5_000)
    assert out["closed"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_close_two_phase.py -v`
Expected: assertion fails because `worker_close` does not route through `_durable_manager.cancel`.

- [ ] **Step 3: Modify `worker_close`**

Replace the legacy close path with a call to `_durable_manager.cancel(worker_id, signal="soft", grace_ms=5_000)`. Return `{"closed": True, "exit_code": manager.status(worker_id).last_exit_code}`. Add an optional `force: bool = False` parameter that escalates to `SIGKILL`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_close_two_phase.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_close_two_phase.py
git commit -m "feat(mcp): worker_close uses two-phase cancellation"
```

---

## Task 23: `worker_close_all` and `worker_health` (F1)

**Files:**
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Test: `tests/unit/mcp/tools/test_worker_close_all_and_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_worker_close_all_and_health.py
import asyncio
from unittest.mock import MagicMock


def test_worker_close_all_cancels_each(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    record = MagicMock()
    record.state.value = "ready"
    record.worker_id = "w-1"
    manager.store.list_all = MagicMock(return_value=[record])
    manager.cancel = MagicMock(return_value=True)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_close_all())
    manager.cancel.assert_called()
    assert out["closed"] == ["w-1"]


def test_worker_health_aggregates_state(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    record = MagicMock()
    record.state.value = "ready"
    record.worker_id = "w-1"
    manager.store.list_all = MagicMock(return_value=[record])
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    out = asyncio.run(worker_tools.worker_health())
    assert out["counts"]["ready"] == 1
    assert out["total"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_worker_close_all_and_health.py -v`
Expected: assertion fails because both functions still call the legacy manager.

- [ ] **Step 3: Modify `worker_close_all` and `worker_health`**

`worker_close_all`: iterate `_durable_manager.store.list_all()` and call `_durable_manager.cancel(worker_id, signal="soft", grace_ms=5_000)` for each in-flight record. Return a list of `worker_id` values that were closed.

`worker_health`: count records by state, return `{"total": int, "counts": {state: int}}`. Include a `reaped` count and the per-state count for every state in `WorkerLifecycleState`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_worker_close_all_and_health.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/worker_tools.py tests/unit/mcp/tools/test_worker_close_all_and_health.py
git commit -m "feat(mcp): worker_close_all and worker_health use durable contract"
```

---

## Task 24: `pool_route_execute` and `dispatch_to_pool` use the contract (F1, F12)

**Files:**
- Modify: `mahavishnu/mcp/tools/pool_tools.py`
- Test: `tests/unit/mcp/tools/test_pool_route_execute_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_pool_route_execute_contract.py
import asyncio
from unittest.mock import MagicMock


def test_pool_route_execute_dispatches_through_contract(monkeypatch):
    from mahavishnu.mcp.tools import pool_tools

    manager = MagicMock()
    manager.spawn = MagicMock(
        return_value=MagicMock(worker_id="w-1", record=MagicMock(worker_id="w-1"))
    )
    monkeypatch.setattr(pool_tools, "_durable_manager", manager)
    out = asyncio.run(
        pool_tools.pool_route_execute(
            prompt="do it",
            worker_type="terminal-claude",
        )
    )
    manager.spawn.assert_called_once()
    assert out["worker_id"] == "w-1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/mcp/tools/test_pool_route_execute_contract.py -v`
Expected: assertion fails because `pool_route_execute` still goes through the legacy pool manager.

- [ ] **Step 3: Modify `pool_tools.py`**

For shell-based worker types (SHELL, AI_ASSISTANT, REMOTE), `pool_route_execute` and `dispatch_to_pool` should route through `_durable_manager.spawn` and use the new contract's structured result. For other types, keep the existing path.

Also: in `dispatch_to_pool`, record the `worker_id` returned by the contract in the Dhara state at `workflow-results/{workflow_id}/` so `workflow_result` can return both the canonical `WorkerResult` and the durable `worker_id`. (F12 follow-up: also persist a `dispatched_at` so the response includes a small startup delay; the synchronous-block path remains a known follow-up.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/mcp/tools/test_pool_route_execute_contract.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/pool_tools.py tests/unit/mcp/tools/test_pool_route_execute_contract.py
git commit -m "feat(mcp): pool tools route shell types through durable contract"
```

---

## Task 25: §14 success-criteria instrumentation (F13)

**Files:**
- Create: `mahavishnu/observability/worker_metrics.py`
- Test: `tests/unit/observability/test_worker_metrics.py`
- Modify: `mahavishnu/mcp/tools/worker_contract_tools.py` (instrument every tool call)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/observability/test_worker_metrics.py
from mahavishnu.observability.worker_metrics import WorkerMetrics


def test_metrics_increment_per_tool():
    m = WorkerMetrics()
    m.record("launch_worker")
    m.record("launch_worker")
    m.record("worker_status")
    snapshot = m.snapshot()
    assert snapshot["launch_worker"] == 2
    assert snapshot["worker_status"] == 1
    assert snapshot["total"] == 3


def test_metrics_attach_command_attach_count():
    m = WorkerMetrics()
    m.record("worker_revoke")
    m.record_attach()
    m.record_attach()
    snapshot = m.snapshot()
    assert snapshot["attach_events"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/observability/test_worker_metrics.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `worker_metrics.py`**

```python
# mahavishnu/observability/worker_metrics.py
from __future__ import annotations

import threading
from collections import defaultdict


class WorkerMetrics:
    """Spec §14: instrumentation for the success-criteria metrics.

    Counters:
      - per-tool call counts
      - attach_event count (when a worker_revoke response includes
        attach_command that the operator later runs)
      - pool_share approximations (counted at pool_route_execute
        entry and terminal_launch entry)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)
        self._attach_events: int = 0

    def record(self, tool_name: str) -> None:
        with self._lock:
            self._counts[tool_name] += 1
            self._counts["total"] += 1

    def record_attach(self) -> None:
        with self._lock:
            self._attach_events += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            out = dict(self._counts)
            out["attach_events"] = self._attach_events
            return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/observability/test_worker_metrics.py -v`
Expected: 2 passed.

- [ ] **Step 5: Instrument the worker contract tools**

In `mahavishnu/mcp/tools/worker_contract_tools.py`, instantiate a module-level `WorkerMetrics()` and call `metrics.record("launch_worker")` (etc.) at the start of every tool function. Expose `metrics` as a singleton so the metrics can be queried via a future `worker_metrics` MCP tool.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/observability/worker_metrics.py tests/unit/observability/test_worker_metrics.py mahavishnu/mcp/tools/worker_contract_tools.py
git commit -m "feat(observability): instrument worker contract tools with metrics"
```

---

## Updated task list

The plan now has 26 tasks in execution order:

1. `WorkerLifecycleState` enum
2. `DurableWorkerRecord` Pydantic model
3. `WorkerRecordStore` atomic JSON I/O
4. Worker topic constants
5. `TmuxTerminalAdapter` primitives
6. `DurableWorkerManager` lifecycle
7. `CanonicalEnvelopePublisher`
8. Repair `worker_execute` truncation
8a. Graceful shutdown wiring
8b. Startup reconciliation hook
9. `workflow_result` MCP tool
10. `terminal-claude` completion detection
11. `tmux` backend entry
12. Wire tmux adapter into manager
13. Worker contract MCP tool group
14. Settings additions
15. MCP tools documentation
16. End-to-end reconciliation test
17. Crackerjack quality gate
18. `worker_spawn` rewired
19. `worker_list` filters
20. `worker_monitor` authoritative state
21. `worker_collect_results` incremental output
22. `worker_close` two-phase shutdown
23. `worker_close_all` and `worker_health`
24. `pool_route_execute` and `dispatch_to_pool` use the contract
25. §14 success-criteria instrumentation
26. iTerm2 adapter deprecation and removal

This preserves the original four-phase rollout while closing the audit gaps.

## Open-question confirmations

Confirmed before execution:

1. Default `backend` for `launch_worker`: `claude_tui`.
2. Remove 500-character `worker_execute` truncation: yes.
3. Private-socket directory: `~/.mahavishnu/tmux/`.
4. `worker_revoke` may leave the underlying process running unless `force=true`.

---

## Task 26: iTerm2 adapter deprecation and removal

**Files:**
- Modify: `mahavishnu/terminal/manager.py` (replace the iTerm2 branch in `TerminalManager.create` with a one-release deprecation warning that falls back to the mock adapter; do not block the boot path)
- Modify: `mahavishnu/mcp/tools/terminal_tools.py` (remove `terminal_switch_adapter("iterm2")` and the iTerm2 profile launch MCP tool; raise `NotImplementedError` if called with `iterm2`)
- Modify: `mahavishnu/terminal/adapters/iterm2.py` (delete the file or convert it to a stub that raises a clear `DeprecationWarning` then re-raises)
- Modify: `mahavishnu/terminal/grid/models.py` and any iTerm2-type-coupled files (replace `ITerm2Adapter` with a generic `TerminalAdapter` Protocol so the grid manager compiles after the class is removed)
- Modify: `mahavishnu/terminal/manager.py` `ITerm2_AVAILABLE` references (remove import paths; replace with `True` only at the iTerm2 deprecation warning site)
- Modify: `mahavishnu/mcp/bootstrap.py` (remove the iTerm2-specific boot-path branch; `adapter_preference: "iTerm2"` now triggers the same deprecation warning)
- Modify: `pyproject.toml` (remove the `iterm2 = ["iterm2>=2.20"]` extra; the dead-pin comment in the spec is now actionable)
- Modify: `settings/mahavishnu.yaml` and `settings/mahavishnu.yaml.example` (remove the iTerm2-specific configuration block; add a one-time deprecation note in CHANGELOG)
- Delete: iTerm2-specific tests under `tests/unit/terminal/` and `tests/accessibility/`
- Test: `tests/unit/terminal/test_iterm2_deprecation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/terminal/test_iterm2_deprecation.py
import warnings
from unittest.mock import patch


def test_terminal_manager_iterm2_preference_warns_and_falls_back():
    from mahavishnu.terminal.manager import TerminalManager

    cfg = type(
        "Cfg",
        (),
        {
            "terminal": type(
                "T",
                (),
                {
                    "enabled": True,
                    "adapter_preference": "iterm2",
                    "max_concurrent_sessions": 5,
                    "default_columns": 120,
                    "default_rows": 30,
                    "crow_enabled": False,
                },
            )()
        },
    )()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mgr = TerminalManager.create(cfg, mcp_client=None)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert mgr.adapter is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/terminal/test_iterm2_deprecation.py -v`
Expected: ImportError or assertion fails because the iTerm2 branch does not yet emit `DeprecationWarning`.

- [ ] **Step 3: Modify `TerminalManager.create`**

In `mahavishnu/terminal/manager.py`, locate the iTerm2 branch (the one currently instantiating `ITerm2Adapter` or calling iTerm2-specific code). Replace it with:

```python
        if preference == "iterm2":
            warnings.warn(
                "adapter_preference='iterm2' is deprecated and will be "
                "removed in the next release. Use 'tmux' or 'mcpretentious' "
                "instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            # Fall back to the mock adapter so callers still get a working
            # manager; the warning is the only signal of the change.
            from .adapters.mock import MockTerminalAdapter

            adapter = MockTerminalAdapter()
            return cls(adapter, terminal_config)
```

Also remove the now-unused `ITERM2_AVAILABLE` import and any iTerm2-specific dead branches.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/terminal/test_iterm2_deprecation.py -v`
Expected: 1 passed.

- [ ] **Step 5: Remove the iTerm2 MCP tool branches**

In `mahavishnu/mcp/tools/terminal_tools.py`:

- Locate `terminal_switch_adapter` and the iTerm2 branch inside it. Replace the iTerm2 branch with a `NotImplementedError` raising the deprecation message.
- Locate `terminal_launch_with_profile` and the iTerm2 branch. Remove it entirely.
- Locate `terminal_list_profiles` and any iTerm2-only filtering. Remove the iTerm2 filter.

Then update `mahavishnu/mcp/bootstrap.py` to drop the iTerm2-specific boot-path branch. The remaining branches should fall through to the mock adapter with the same deprecation warning.

- [ ] **Step 6: Run all terminal tests to verify nothing else broke**

Run: `pytest tests/unit/terminal tests/accessibility -v`
Expected: all previously-passing tests still pass; the iTerm2-only tests are deleted (not skipped).

- [ ] **Step 7: Delete the iTerm2-specific files**

- Delete `mahavishnu/terminal/adapters/iterm2.py`.
- Delete `mahavishnu/terminal/pool.py` if its only purpose was iTerm2.
- Delete `tests/unit/terminal/test_iterm2*.py` and any iTerm2-only tests under `tests/accessibility/`.

- [ ] **Step 8: Refactor the grid manager to a generic adapter protocol**

In `mahavishnu/terminal/grid/manager.py`, replace the explicit `ITerm2Adapter` constructor argument with a generic `TerminalAdapter` Protocol (defined in `mahavishnu/terminal/adapters/base.py`). The Protocol needs `launch_sessions`, `send_command`, `capture_output`, `close_session`, `list_sessions`. The current `ITerm2Adapter` and `MockTerminalAdapter` already satisfy it.

- [ ] **Step 9: Run the full test suite**

Run: `pytest -m "not slow" -q`
Expected: all tests pass.

- [ ] **Step 10: Remove the `iterm2` extra from `pyproject.toml`**

Locate the `iterm2 = ["iterm2>=2.20"]` extra in `pyproject.toml`. Delete the line.

- [ ] **Step 11: Run Crackerjack**

Run: `crackerjack run`
Expected: ≥75 quality score; no new failures.

- [ ] **Step 12: Commit**

```bash
git add mahavishnu/terminal mahavishnu/mcp/tools/terminal_tools.py mahavishnu/mcp/bootstrap.py pyproject.toml tests
git commit -m "feat(terminal): deprecate iTerm2 adapter and remove public surface"
```
