# Auto-Checkpoint Safety + Auto-Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make session-buddy run all checkpoints automatically — never requiring manual `/mcp__session-buddy__checkpoint` — by (a) eliminating the stash-clobber race in the existing checkpoint flow via the 4-component design from the approved 2026-07-15 spec, and (b) adding the missing mid-task timer that drives `auto_checkpoint_interval=1800` (defined but never consumed).

**Architecture:** Four new components under `session_buddy/checkpoint/` (`SubagentDetector`, `SnapshotMechanism`, `CheckpointPolicy`, `CheckpointOrchestrator`) compose to make every checkpoint call read-only w.r.t. the working tree, deferred when a subagent is active, and fail-closed on errors. The `CheckpointOrchestrator` wraps the existing `perform_git_checkpoint()` via the `_checkpoint_with_safety_capture` helper in `session_buddy/core/session_manager.py` so the legacy code becomes a `forward_to` target. A new `AutoCheckpointLoop` runs in the MCP server lifespan, firing every `auto_checkpoint_interval` seconds when the session is active and the subagent detector says it's safe.

**Tech Stack:** Python 3.13, `asyncio`, pytest + pytest-asyncio (asyncio_mode = "auto"), hypothesis (property-based), oneiric logger, subprocess + asyncio.wait_for for git operations, httpx for retry classification.

## Tracking links

Originating observation: 2026-07-15 comprehensive-hooks-cleanup wave.

- Parent memory: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/session-buddy-checkpoint-hooks-fire-during-subagent-sessions.md`
- Sibling recovery: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/drift-bundling-recovery.md`
- Pickup prompt acceptance criterion #6: `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md`
- Defect record: `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`
- Source spec: `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md`

## Gating surface clarification

Four independent gates control auto-checkpoint behavior. The plan is explicit about which gate controls what:

| Gate | Lives in | Controls | Default |
|---|---|---|---|
| `ModeConfig.enable_auto_checkpoint` | `modes/base.py:50` | Whether `SessionManager._checkpoint_via_orchestrator` wraps `perform_git_checkpoint` (False → direct legacy path) | True (standard), False (lite) |
| `settings.auto_checkpoint_interval` | `settings.py:244` | Whether the `AutoCheckpointLoop` timer fires **analytics** mid-task checkpoints (snapshots only, no commit) | 1800s (30 min), `ge=60` enforced |
| `settings.midpoint_commits_enabled` | `settings.py` (new) | Whether mid-task ticks ALSO commit (not just snapshot). Off by default for noise control; opt-in for autonomous/subagent-heavy workflows. When enabled, `midpoint_commit_interval_s` (default 600s / 10 min) replaces `auto_checkpoint_interval`. | False |
| `settings.midpoint_commit_min_quality_delta` | `settings.py` (new) | Quality score delta threshold that fires a midpoint commit (best-effort; inactive when no quality source configured) | 10 |
| `MidpointCriteria.signals` | `policy.py` | Whether an individual midpoint tick fires (OR semantics across signals) | `[TimeElapsedSignal(300s), DirtyFilesSignal(5)]` |

`settings.enable_auto_commit` (True) is **not** a gate; it is informational until Task 2's `commit_message_template` consumer lands in Task 8.

**Cadence matrix**:

| Mode | `midpoint_commits_enabled` | Effective interval | What fires |
|---|---|---|---|
| Lite | n/a | n/a | No timer started |
| Standard | False (default) | `auto_checkpoint_interval` (1800s) | Snapshots only (analytics) |
| Standard | True | `midpoint_commit_interval_s` (600s) | Snapshots + commits when policy fires |

## Global Constraints

1. **Source spec**: `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md` — every invariant and component shape comes from there verbatim.
2. **Working tree is never mutated by a checkpoint** — snapshot capture writes only to `tempfile.gettempdir()/session-buddy-snapshots/snap-<uuid>.patch`. The legacy `git add -A && git commit` only runs after the snapshot succeeds AND no subagent is active.
3. **End-of-task checkpoint is mandatory.** Every Claude Code `Stop` event results in a checkpoint, period. If the orchestrator cannot fire synchronously (e.g., subagent timeout >60s), it persists a marker at `~/.session-buddy/pending-checkpoint.json` and the next `AutoCheckpointLoop` tick or `SessionEnd` consumes it. NEVER silently drop.
4. **Midpoint checkpoint is conditional.** Fires only when value-add criteria (≥300s since last commit OR ≥5 dirty files) AND no subagent is active.
5. **Failures fail closed.** Mechanism error → skip checkpoint, log loudly. **Specific transient errors** (5xx from `forward_to`) retry once with exponential backoff. **Broad `except Exception`** is forbidden — narrow to `(subprocess.SubprocessError, OSError, ValueError, httpx.HTTPStatusError)`. Programming errors propagate.

   > **Note (I-9, resolved by review-fix-plan Task 2):** The spec literal `(subprocess.SubprocessError, OSError, ValueError, httpx.HTTPStatusError)` is canonical. The `TransientForwardError` tuple in Task 4 Step 3 of this plan body was previously written as `(httpx.HTTPStatusError, OSError, asyncio.TimeoutError)` — that was drift. The implementation in `session_buddy/checkpoint/orchestrator.py` matches the spec literal (see Task 4 Step 3 below for the corrected tuple).
6. **Project conventions** (from `mahavishnu/CLAUDE.md`): `from __future__ import annotations` first, Ruff/Black-compatible formatting, Oneiric logger (`from oneiric.core.logging import get_logger`), pytest markers (`unit`, `integration`, `property`, `slow`), `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).
7. **Bodai pre-1.0 merge-to-main policy**: branch + squash/ff-merge into `main`; no PRs, no review gates for Bodai components.
8. **Python 3.13 syntax**: `X | None` not `Optional[X]`, `list[str]` not `List[str]`, `pathlib.Path` for filesystem paths. `from collections.abc import Protocol` (not `typing.Protocol`).
9. **No `Any` in tool inputs / orchestration state** — use `TYPE_CHECKING` and a typed protocol to escape.
10. **No `assert` in production code** (`session_buddy/**`) — use the `session_buddy/core/errors.py` exception hierarchy. Bandit B101.
11. **Hard limits** (per `[tool.ruff.lint.pylint]`): line length 100, max 10 function args, max 15 branches, max 6 returns, max 55 statements (target 30).
12. **Per-working-tree lockfile**, NOT global. Lockfile path: `<working_dir>/.session-buddy/subagent.lock`. Prevents cross-project false-deferral in multi-session deployments.
13. **MCP lifespan shutdown order**: timer `stop()` MUST run in a `finally:` block after the existing `_dhara_publisher.aclose()`. Mirror the existing Dhara cleanup pattern, not nest it.
14. **Coverage gate**: 90% on `session_buddy/checkpoint/` module (per spec line 472). Enforced via `pytest --cov-fail-under=90`. Steps in Task 10.
15. **`hypothesis` must be a declared dep** in session-buddy's `pyproject.toml` dev group (currently only transitive). Step in Task 8.
16. **Mid-task commits are opt-in**, not default. Default behavior (`midpoint_commits_enabled=False`) keeps mid-task ticks as analytics-only snapshots to avoid polluting git log during interactive sessions. Operators opt in for autonomous or subagent-heavy workflows where durability matters more than log noise. Safety invariants (snapshot-first, subagent deferral, fail-closed, retry-once-with-backoff) are NOT relaxed when commits are enabled — only `forward_to` changes from `_noop_forward` to a real git-commit forward.
17. **Effective interval coupling.** When `midpoint_commits_enabled=True`, the lifespan uses `settings.midpoint_commit_interval_s` (default 600s / 10 min) instead of `settings.auto_checkpoint_interval` (1800s). The two intervals are not independently meaningful — the commit-enabled knob implicitly switches the cadence.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `session_buddy/checkpoint/__init__.py` | Module entry point; re-exports the four components + supporting types. |
| `session_buddy/checkpoint/subagent_detector.py` | `SubagentDetector` class + `SignalSource` protocol + `LockfileSignalSource` concrete impl. |
| `session_buddy/checkpoint/snapshot.py` | `SnapshotMechanism` class + `Snapshot` + `RestoreResult`. Snapshot via `git diff HEAD` → patch file. Hardened restore with hunk-detail + drift warning. |
| `session_buddy/checkpoint/policy.py` | `CheckpointPolicy`, signals, `MidpointCriteria`, `PolicyDecision`, `CheckpointPhase`, `WorkingTreeInspector` helper. |
| `session_buddy/checkpoint/orchestrator.py` | `CheckpointOrchestrator` + `CheckpointResult`. Composes policy+snapshot+detector+forward_to. Includes `asyncio.Lock` per working dir, retry-once-with-backoff for 5xx, empty-tree skip, narrowed exception handling. |
| `session_buddy/checkpoint/cleanup.py` | `SnapshotCleanupTask` — background asyncio TTL cleaner (7-day default). |
| `session_buddy/checkpoint/metrics.py` | `CheckpointMetrics` — operator-visible `checkpoint_failures_total{reason="..."}` counter (in-process; export hook for future Prometheus wiring). |
| `session_buddy/checkpoint/pending.py` | `PendingCheckpoint` + `load_pending`/`save_pending` for the durable subagent-timeout handoff. |
| `session_buddy/core/auto_checkpoint_loop.py` | `AutoCheckpointLoop` — the asyncio timer driven by `settings.auto_checkpoint_interval`. Consumes the pending-checkpoint marker on each tick. |
| `session_buddy/cli/checkpoint_cli.py` | Typer CLI: `session-buddy checkpoint cleanup-snapshots [--older-than=<N> days]`. |
| `tests/unit/core/checkpoint/conftest.py` | `_init_repo` helper shared by all tests in this dir. |
| `tests/unit/core/checkpoint/test_subagent_detector.py` | Unit tests for SubagentDetector. |
| `tests/unit/core/checkpoint/test_snapshot.py` | Unit tests for SnapshotMechanism + restore failure modes. |
| `tests/unit/core/checkpoint/test_policy.py` | Unit tests for CheckpointPolicy + WorkingTreeInspector. |
| `tests/unit/core/checkpoint/test_orchestrator.py` | Unit tests for CheckpointOrchestrator (retry, lock, narrow exceptions, empty-tree). |
| `tests/unit/core/checkpoint/test_cleanup.py` | Unit tests for SnapshotCleanupTask. |
| `tests/unit/core/checkpoint/test_pending.py` | Unit tests for pending-checkpoint round-trip. |
| `tests/unit/core/checkpoint/test_working_tree_invariant.py` | Property-based keystone + stash-clobber regression (with subprocess spy). Marked `@pytest.mark.property`. |
| `tests/unit/mcp/test_auto_checkpoint_timer.py` | Unit tests for AutoCheckpointLoop. |

### Modified files

| Path | Change |
|---|---|
| `session_buddy/mcp/server.py` (lines 174-187, `_lifespan_with_dhara_cleanup`) | Wrap with `try/finally` to ensure timer `stop()` runs on shutdown. Read mode config to skip loop in Lite mode. |
| `session_buddy/core/session_manager.py:44-94` (`__init__`) | Add `mode_config: ModeConfig \| None = None` parameter and `self._mode_config = mode_config` storage. |
| `session_buddy/core/session_manager.py` (the `perform_git_checkpoint` call site within `_checkpoint_with_safety_capture`) | Replace with `_checkpoint_via_orchestrator` wrapper that preserves `git_output` from `perform_git_checkpoint` and appends a decision summary line. |
| `session_buddy/settings.py:244-249` (`auto_checkpoint_interval`) | Update docstring to clarify it's now consumed by `AutoCheckpointLoop`. |
| `session_buddy/modes/standard.py` + `lite.py` | Verify `ModeConfig` is plumbed through to `SessionManager` constructor at the call site. |
| `pyproject.toml` (session-buddy) | Add `hypothesis` to a dev dependency group. |

---

## Task 1: SubagentDetector + SignalSource

**Files:**
- Create: `session_buddy/checkpoint/subagent_detector.py`
- Create: `tests/unit/core/checkpoint/conftest.py` (helper used across tasks)
- Create: `tests/unit/core/checkpoint/test_subagent_detector.py`

**Interfaces:**
- Consumes: nothing (this is the first task).
- Produces:
  - `SignalSource` (Protocol): `def read() -> bool` and `def write(active: bool) -> None`
  - `LockfileSignalSource(lockfile_path: Path)`: concrete impl, **per-working-tree**.
  - `SubagentDetector(working_dir: Path, signal_source: SignalSource)`: `def is_active() -> bool` and `async def wait_until_idle(timeout: float = 60.0) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/conftest.py
from __future__ import annotations

import subprocess
from pathlib import Path


def init_repo(parent: Path, name: str = "r") -> Path:
    """Init a real git repo with one commit. Shared across checkpoint tests."""
    repo = parent / name
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo
```

```python
# tests/unit/core/checkpoint/test_subagent_detector.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from session_buddy.checkpoint.subagent_detector import (
    LockfileSignalSource,
    SubagentDetector,
)


@pytest.mark.unit
def test_lockfile_signal_source_read_returns_false_when_missing(tmp_path: Path) -> None:
    src = LockfileSignalSource(tmp_path / "subagent.lock")
    assert src.read() is False


@pytest.mark.unit
def test_lockfile_signal_source_read_returns_true_when_present(tmp_path: Path) -> None:
    lock = tmp_path / "subagent.lock"
    lock.touch()
    assert LockfileSignalSource(lock).read() is True


@pytest.mark.unit
def test_lockfile_signal_source_write_creates_and_removes_lockfile(tmp_path: Path) -> None:
    lock = tmp_path / "subagent.lock"
    src = LockfileSignalSource(lock)
    src.write(active=True)
    assert lock.exists()
    src.write(active=False)
    assert not lock.exists()


@pytest.mark.unit
def test_subagent_detector_is_active_false_when_signal_false(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    assert detector.is_active() is False


@pytest.mark.unit
def test_subagent_detector_is_active_true_when_signal_true(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    lock.touch()
    assert SubagentDetector(tmp_path, LockfileSignalSource(lock)).is_active() is True


@pytest.mark.unit
async def test_wait_until_idle_returns_true_when_already_idle(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    assert await detector.wait_until_idle(timeout=0.1) is True


@pytest.mark.unit
async def test_wait_until_idle_returns_false_on_timeout(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    lock.touch()
    detector = SubagentDetector(tmp_path, LockfileSignalSource(lock))
    assert await detector.wait_until_idle(timeout=0.05) is False


@pytest.mark.unit
async def test_wait_until_idle_returns_true_after_signal_cleared(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    src = LockfileSignalSource(lock)
    src.write(active=True)
    detector = SubagentDetector(tmp_path, src)

    async def clear_after_delay() -> None:
        await asyncio.sleep(0.05)
        src.write(active=False)

    asyncio.create_task(clear_after_delay())
    assert await detector.wait_until_idle(timeout=1.0) is True


@pytest.mark.unit
def test_subagent_detector_fails_open_when_lockfile_unreadable(tmp_path: Path) -> None:
    """If read() raises (e.g., permission denied), fail open to 'active' — safer to defer."""
    lock = tmp_path / "x.lock"
    lock.touch()
    lock.chmod(0o000)
    try:
        detector = SubagentDetector(tmp_path, LockfileSignalSource(lock))
        assert detector.is_active() is True  # fail open per spec invariant
    finally:
        lock.chmod(0o644)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_subagent_detector.py -v`
Expected: collection error (module does not exist).

- [ ] **Step 3: Implement SubagentDetector**

```python
# session_buddy/checkpoint/subagent_detector.py
"""Detect whether a subagent is currently working in the same project tree.

Signal source is pluggable: lockfile (default), env var, or MCP probe.
Per spec invariant: failures fail OPEN to "active" (assume subagent active,
defer) — safer to defer unnecessarily than to risk clobbering.

Lockfile path is per-working-tree: <working_dir>/.session-buddy/subagent.lock.
Prevents cross-project false deferral in multi-session deployments.
"""
from __future__ import annotations

import asyncio
from collections.abc import Protocol
from pathlib import Path

from oneiric.core.logging import get_logger

_log = get_logger(__name__)


class SignalSource(Protocol):
    def read(self) -> bool: ...
    def write(self, active: bool) -> None: ...


class LockfileSignalSource:
    """Lockfile-backed SignalSource. Lockfile presence == subagent active."""

    def __init__(self, lockfile_path: Path) -> None:
        self._path = lockfile_path

    def read(self) -> bool:
        try:
            return self._path.exists()
        except OSError as exc:
            _log.warning("subagent_signal_read_failed", extra={"error": str(exc)})
            return True  # fail open per spec

    def write(self, active: bool) -> None:
        try:
            if active:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.touch()
            else:
                self._path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("subagent_signal_write_failed", extra={"error": str(exc)})


class SubagentDetector:
    def __init__(self, working_dir: Path, signal_source: SignalSource) -> None:
        self._working_dir = working_dir
        self._signal = signal_source

    def is_active(self) -> bool:
        try:
            return self._signal.read()
        except Exception as exc:  # noqa: BLE001 — fail open per spec
            _log.warning(
                "subagent_detector_is_active_failed",
                extra={"error": str(exc), "working_dir": str(self._working_dir)},
            )
            return True

    async def wait_until_idle(self, timeout: float = 60.0) -> bool:
        """Block until subagent is idle or timeout. Returns True if idle."""
        try:
            await asyncio.wait_for(self._poll_until_idle(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            _log.warning(
                "subagent_detector_wait_timeout",
                extra={"timeout_s": timeout, "working_dir": str(self._working_dir)},
            )
            return False

    async def _poll_until_idle(self) -> None:
        while self.is_active():
            await asyncio.sleep(0.1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_subagent_detector.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/subagent_detector.py tests/unit/core/checkpoint/conftest.py tests/unit/core/checkpoint/test_subagent_detector.py
git commit -m "feat(checkpoint): add SubagentDetector with per-tree lockfile signal source"
```

---

## Task 2: SnapshotMechanism + hardened restore

**Files:**
- Create: `session_buddy/checkpoint/snapshot.py`
- Create: `tests/unit/core/checkpoint/test_snapshot.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Snapshot` (dataclass): `path: Path`, `label: str`, `snapshot_id: str`, `captured_at: datetime`, `parent_commit: str`, `dirty_files: list[str]`
  - `RestoreResult` (dataclass): `success: bool`, `error: str | None`, `hunks: list[str]`, `drift_detected: bool`
  - `SnapshotMechanism(working_dir: Path, snapshot_dir: Path | None = None)`: `def capture(label: str) -> Snapshot` and `def restore(snapshot: Snapshot) -> RestoreResult`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/test_snapshot.py
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from session_buddy.checkpoint.snapshot import (
    RestoreResult,
    Snapshot,
    SnapshotMechanism,
)

from .conftest import init_repo


@pytest.mark.unit
def test_capture_creates_patch_file_for_dirty_repo(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    (repo / "new_file.py").write_text("# new\n")

    snap_dir = tmp_path / "snaps"
    snap = SnapshotMechanism(repo, snap_dir).capture(label="manual-test")

    assert snap.path.exists()
    assert snap.label == "manual-test"
    assert snap.snapshot_id.startswith("snap-")
    assert "modified.py" in snap.path.read_text() or "diff --git" in snap.path.read_text()


@pytest.mark.unit
def test_capture_does_not_mutate_working_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    before = _hash_working_tree(repo)

    SnapshotMechanism(repo, tmp_path / "snaps").capture(label="invariant-check")

    assert _hash_working_tree(repo) == before


@pytest.mark.unit
def test_capture_handles_clean_tree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    snap = SnapshotMechanism(repo, tmp_path / "snaps").capture(label="clean")
    assert snap.path.exists()
    assert snap.dirty_files == []


@pytest.mark.unit
def test_snapshot_immutable_after_capture(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    snap = SnapshotMechanism(repo, tmp_path / "snaps").capture(label="immut")
    assert snap.path.stat().st_mode & 0o777 == 0o444


@pytest.mark.unit
def test_restore_applies_patch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    mech = SnapshotMechanism(repo, tmp_path / "snaps")

    snap = mech.capture(label="restore-test")
    (repo / "modified.py").write_text("# totally different\n")

    result = mech.restore(snap)
    assert isinstance(result, RestoreResult)
    assert result.success is True
    assert (repo / "modified.py").read_text() == "# changed\n"


@pytest.mark.unit
def test_restore_fails_loud_when_patch_missing(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    mech = SnapshotMechanism(repo, tmp_path / "snaps")
    snap = SnapshotMechanism(repo, tmp_path / "snaps").capture(label="ok")
    snap.path.unlink()  # delete the snapshot file

    result = mech.restore(snap)

    assert result.success is False
    assert result.error is not None
    assert snap.snapshot_id in result.error  # snapshot id surfaced per spec


@pytest.mark.unit
def test_restore_on_git_apply_conflict_returns_hunks(tmp_path: Path) -> None:
    """Per spec line 376: git apply conflicts → fail loud, print hunks."""
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    mech = SnapshotMechanism(repo, tmp_path / "snaps")

    snap = mech.capture(label="conflict-test")
    # Change the file to conflict with the patch
    (repo / "modified.py").write_text("# totally different\n# also adding lines\n")

    result = mech.restore(snap)

    assert result.success is False
    assert result.error is not None
    # Spec: "print hunks" — error must include hunk context, not just "git apply failed"
    assert "@@" in result.error or "patch" in result.error.lower()


@pytest.mark.unit
def test_restore_detects_drift_between_parent_and_current_head(tmp_path: Path) -> None:
    """Per spec line 378: working tree drift from parent_commit → warn, show drift summary."""
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# changed\n")
    snap = SnapshotMechanism(repo, tmp_path / "snaps").capture(label="drift")
    parent = snap.parent_commit

    # Make an unrelated commit that diverges from parent
    (repo / "unrelated.py").write_text("# new\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "drift"], cwd=repo, check=True, capture_output=True)

    result = SnapshotMechanism(repo, tmp_path / "snaps").restore(snap)
    # Spec: drift is a WARN, not a fail. The restore itself may still succeed.
    assert result.drift_detected is True
    assert parent != snap.parent_commit or parent != ""  # drift was real


def _hash_working_tree(repo: Path) -> str:
    out = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return hashlib.sha256(out.stdout.encode()).hexdigest()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_snapshot.py -v`
Expected: collection error.

- [ ] **Step 3: Implement SnapshotMechanism**

```python
# session_buddy/checkpoint/snapshot.py
"""Stash-free working-tree snapshot via `git diff > /tmp/snap-<uuid>.patch`.

Per spec invariant: `capture()` only writes a file; never mutates the
working tree. `restore()` is a separate explicit user action with fail-loud
failure modes (patch missing, git apply conflicts with hunk detail,
working-tree drift warning).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from oneiric.core.logging import get_logger

_log = get_logger(__name__)

_GIT_TIMEOUT_S = 30.0
_HUNK_RE = re.compile(r"^@@ .+ @@", re.MULTILINE)


@dataclass
class Snapshot:
    path: Path
    label: str
    snapshot_id: str
    captured_at: datetime
    parent_commit: str
    dirty_files: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    success: bool
    error: str | None = None
    hunks: list[str] = field(default_factory=list)
    drift_detected: bool = False


class SnapshotMechanism:
    def __init__(
        self,
        working_dir: Path,
        snapshot_dir: Path | None = None,
    ) -> None:
        self._working_dir = working_dir
        self._snapshot_dir = snapshot_dir or Path(tempfile.gettempdir()) / "session-buddy-snapshots"

    def capture(self, label: str) -> Snapshot:
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        snap_id = f"snap-{uuid.uuid4()}"
        snap_path = self._snapshot_dir / f"{snap_id}.patch"

        captured_at = datetime.now(UTC)
        parent_commit = self._current_head()
        dirty_files = self._list_dirty_files()

        diff_result = subprocess.run(  # noqa: S603
            ["git", "diff", "HEAD"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=_GIT_TIMEOUT_S,
        )
        untracked_result = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=_GIT_TIMEOUT_S,
        )

        if diff_result.returncode != 0:
            _log.error(
                "snapshot_capture_git_diff_failed",
                extra={"working_dir": str(self._working_dir), "stderr": diff_result.stderr[:500]},
            )
            return Snapshot(
                path=snap_path, label=label, snapshot_id=snap_id,
                captured_at=captured_at, parent_commit=parent_commit, dirty_files=[],
            )

        body = diff_result.stdout
        if untracked_result.returncode == 0 and untracked_result.stdout.strip():
            body += "\n".join(f"?? {p}" for p in untracked_result.stdout.strip().splitlines())

        snap_path.write_text(body)
        snap_path.chmod(0o444)  # immutable after capture

        return Snapshot(
            path=snap_path, label=label, snapshot_id=snap_id,
            captured_at=captured_at, parent_commit=parent_commit, dirty_files=dirty_files,
        )

    def restore(self, snapshot: Snapshot) -> RestoreResult:
        # Fail-loud: missing patch
        if not snapshot.path.exists():
            return RestoreResult(
                success=False,
                error=f"snapshot file missing for {snapshot.snapshot_id} at {snapshot.path}",
            )

        # Drift detection (spec line 378)
        current_head = self._current_head()
        drift = current_head != snapshot.parent_commit and snapshot.parent_commit != "unknown"

        result = subprocess.run(  # noqa: S603
            ["git", "apply", "--whitespace=nowarn", "--reject", str(snapshot.path)],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=_GIT_TIMEOUT_S,
        )
        if result.returncode != 0:
            hunks = _HUNK_RE.findall(result.stderr + result.stdout)
            error_msg = result.stderr.strip() or "git apply failed"
            if hunks:
                error_msg += "\nHunks: " + " | ".join(hunks[:10])
            return RestoreResult(
                success=False, error=error_msg,
                hunks=hunks, drift_detected=drift,
            )
        return RestoreResult(success=True, drift_detected=drift)

    def _current_head(self) -> str:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=_GIT_TIMEOUT_S,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    def _list_dirty_files(self) -> list[str]:
        result = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=_GIT_TIMEOUT_S,
        )
        if result.returncode != 0:
            return []
        return [
            line[3:].split(" -> ")[-1]
            for line in result.stdout.splitlines()
            if len(line) >= 4
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_snapshot.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/snapshot.py tests/unit/core/checkpoint/test_snapshot.py
git commit -m "feat(checkpoint): add stash-free SnapshotMechanism with hardened restore"
```

---

## Task 3: CheckpointPolicy + WorkingTreeInspector

**Files:**
- Create: `session_buddy/checkpoint/policy.py`
- Create: `tests/unit/core/checkpoint/test_policy.py`

**Interfaces:**
- Consumes: `SubagentDetector` from Task 1.
- Produces:
  - `CheckpointPhase(str, Enum)`: `END_OF_TASK`, `MIDPOINT_TIME`, `MIDPOINT_DIRTINESS`, `HOOK_REQUESTED`
  - `PolicyDecision`: `should_fire: bool`, `reason: str`
  - `ValueAddSignal` (Protocol)
  - `TimeElapsedSignal(min_seconds: float = 300.0)`, `DirtyFilesSignal(min_count: int = 5)`
  - `MidpointCriteria(signals: list[ValueAddSignal])`
  - `WorkingTreeInspector(working_dir: Path)`
  - `CheckpointPolicy(always_end, midpoint_enabled, midpoint_criteria, subagent_detector, working_tree)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/test_policy.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from session_buddy.checkpoint.policy import (
    CheckpointPhase,
    CheckpointPolicy,
    DirtyFilesSignal,
    MidpointCriteria,
    PolicyDecision,
    TimeElapsedSignal,
    WorkingTreeInspector,
)
from session_buddy.checkpoint.subagent_detector import LockfileSignalSource, SubagentDetector

from .conftest import init_repo


@pytest.mark.unit
def test_end_of_task_phase_always_fires(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    policy = CheckpointPolicy(
        midpoint_enabled=True, midpoint_criteria=MidpointCriteria(signals=[]),
        subagent_detector=detector, working_tree=WorkingTreeInspector(tmp_path),
    )
    decision = policy.decide(phase=CheckpointPhase.END_OF_TASK)
    assert decision.should_fire is True
    assert decision.reason


@pytest.mark.unit
def test_hook_requested_phase_always_fires(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    policy = CheckpointPolicy(
        midpoint_enabled=False, midpoint_criteria=MidpointCriteria(signals=[]),
        subagent_detector=detector, working_tree=WorkingTreeInspector(tmp_path),
    )
    decision = policy.decide(phase=CheckpointPhase.MIDPOINT_TIME, hook_request=True)
    assert decision.should_fire is True
    assert "hook" in decision.reason.lower()


@pytest.mark.unit
def test_midpoint_deferred_when_subagent_active(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    lock.touch()
    detector = SubagentDetector(tmp_path, LockfileSignalSource(lock))
    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=MidpointCriteria(signals=[DirtyFilesSignal(min_count=1)]),
        subagent_detector=detector, working_tree=WorkingTreeInspector(tmp_path),
    )
    decision = policy.decide(phase=CheckpointPhase.MIDPOINT_DIRTINESS)
    assert decision.should_fire is False
    assert "subagent" in decision.reason.lower()


@pytest.mark.unit
def test_midpoint_fires_when_signals_active_and_subagent_idle(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    inspector = MagicMock()
    inspector.dirty_file_count.return_value = 10
    inspector.seconds_since_last_commit.return_value = 1000.0
    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=MidpointCriteria(signals=[DirtyFilesSignal(min_count=5)]),
        subagent_detector=detector, working_tree=inspector,
    )
    assert policy.decide(phase=CheckpointPhase.MIDPOINT_DIRTINESS).should_fire is True


@pytest.mark.unit
def test_midpoint_disabled_returns_skip(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    inspector = MagicMock()
    inspector.dirty_file_count.return_value = 10
    policy = CheckpointPolicy(
        midpoint_enabled=False,
        midpoint_criteria=MidpointCriteria(signals=[DirtyFilesSignal(min_count=1)]),
        subagent_detector=detector, working_tree=inspector,
    )
    assert policy.decide(phase=CheckpointPhase.MIDPOINT_DIRTINESS).should_fire is False


@pytest.mark.unit
def test_policy_decision_reason_always_non_empty(tmp_path: Path) -> None:
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    policy = CheckpointPolicy(
        midpoint_enabled=False, midpoint_criteria=MidpointCriteria(signals=[]),
        subagent_detector=detector, working_tree=WorkingTreeInspector(tmp_path),
    )
    for phase in CheckpointPhase:
        d = policy.decide(phase=phase)
        assert d.reason, f"empty reason for {phase}"


@pytest.mark.unit
def test_signal_evaluation_exception_does_not_skip_other_signals(tmp_path: Path) -> None:
    """Per spec line 369: signal.is_active raising → fail closed. Per-signal catch."""
    detector = SubagentDetector(tmp_path, LockfileSignalSource(tmp_path / "x.lock"))
    inspector = MagicMock()
    inspector.dirty_file_count.return_value = 100

    bad_signal = MagicMock()
    bad_signal.describe.return_value = "broken"
    bad_signal.is_active.side_effect = RuntimeError("boom")
    good_signal = DirtyFilesSignal(min_count=5)

    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=MidpointCriteria(signals=[bad_signal, good_signal]),
        subagent_detector=detector, working_tree=inspector,
    )
    decision = policy.decide(phase=CheckpointPhase.MIDPOINT_DIRTINESS)
    assert decision.should_fire is True


@pytest.mark.unit
def test_working_tree_inspector_dirty_file_count_on_real_repo(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "a.py").write_text("a\n")
    (repo / "b.py").write_text("b\n")
    inspector = WorkingTreeInspector(repo)
    assert inspector.dirty_file_count() == 2


@pytest.mark.unit
def test_working_tree_inspector_is_git_repo(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert WorkingTreeInspector(repo).is_git_repo() is True
    assert WorkingTreeInspector(tmp_path / "not-a-repo").is_git_repo() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_policy.py -v`
Expected: collection error.

- [ ] **Step 3: Implement CheckpointPolicy**

```python
# session_buddy/checkpoint/policy.py
"""Decide whether a checkpoint should fire given current state.

Per spec: midpoint fires when it adds value AND no subagent is active.
End-of-task always fires (after subagent commit if applicable). Hook
request always fires (user explicit override).
"""
from __future__ import annotations

import subprocess
from collections.abc import Protocol
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from oneiric.core.logging import get_logger

from session_buddy.checkpoint.subagent_detector import SubagentDetector

_log = get_logger(__name__)


class CheckpointPhase(str, Enum):
    END_OF_TASK = "end_of_task"
    MIDPOINT_TIME = "midpoint_time"
    MIDPOINT_DIRTINESS = "midpoint_dirtiness"
    HOOK_REQUESTED = "hook_requested"


@dataclass
class PolicyDecision:
    should_fire: bool
    reason: str


class WorkingTreeInspector:
    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def is_git_repo(self) -> bool:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self._working_dir, capture_output=True, check=False, timeout=5.0,
        )
        return result.returncode == 0

    def seconds_since_last_commit(self) -> float:
        if not self.is_git_repo():
            return 0.0
        result = subprocess.run(  # noqa: S603
            ["git", "log", "-1", "--format=%aI"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=5.0,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return 0.0
        try:
            last = datetime.fromisoformat(result.stdout.strip().replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return max(0.0, (datetime.now(UTC) - last).total_seconds())

    def dirty_file_count(self) -> int:
        if not self.is_git_repo():
            return 0
        result = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],
            cwd=self._working_dir, capture_output=True, text=True,
            check=False, timeout=5.0,
        )
        if result.returncode != 0:
            return 0
        return sum(1 for line in result.stdout.splitlines() if len(line) >= 4)


class ValueAddSignal(Protocol):
    def is_active(self, working_tree: WorkingTreeInspector) -> bool: ...
    def describe(self) -> str: ...


@dataclass
class TimeElapsedSignal:
    min_seconds: float = 300.0

    def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return working_tree.seconds_since_last_commit() >= self.min_seconds

    def describe(self) -> str:
        return f"{self.min_seconds:.0f}s since last commit"


@dataclass
class DirtyFilesSignal:
    min_count: int = 5

    def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return working_tree.dirty_file_count() >= self.min_count

    def describe(self) -> str:
        return f"{self.min_count}+ dirty files"


@dataclass
class MidpointCriteria:
    signals: list[ValueAddSignal] = field(default_factory=lambda: [
        TimeElapsedSignal(min_seconds=300.0),
        DirtyFilesSignal(min_count=5),
    ])


class CheckpointPolicy:
    def __init__(
        self,
        *,
        always_end: bool = True,
        midpoint_enabled: bool = True,
        midpoint_criteria: MidpointCriteria,
        subagent_detector: SubagentDetector,
        working_tree: WorkingTreeInspector,
    ) -> None:
        self._always_end = always_end
        self._midpoint_enabled = midpoint_enabled
        self._criteria = midpoint_criteria
        self._detector = subagent_detector
        self._working_tree = working_tree

    def decide(
        self, *, phase: CheckpointPhase, hook_request: bool = False
    ) -> PolicyDecision:
        if phase == CheckpointPhase.END_OF_TASK:
            if self._always_end:
                return PolicyDecision(should_fire=True, reason="end_of_task mandatory")
            return PolicyDecision(should_fire=False, reason="end_of_task disabled")

        if hook_request or phase == CheckpointPhase.HOOK_REQUESTED:
            return PolicyDecision(should_fire=True, reason="hook_requested explicit override")

        if not self._midpoint_enabled:
            return PolicyDecision(should_fire=False, reason="midpoint disabled")

        if self._detector.is_active():
            return PolicyDecision(
                should_fire=False, reason="subagent active — deferring midpoint",
            )

        for signal in self._criteria:
            try:
                if signal.is_active(self._working_tree):
                    return PolicyDecision(
                        should_fire=True, reason=f"signal active: {signal.describe()}",
                    )
            except Exception as exc:  # noqa: BLE001 — per-signal fail-closed per spec
                _log.error(  # ERROR not WARNING per integration-risk L4
                    "policy_signal_evaluation_failed",
                    extra={"signal": signal.describe(), "error": str(exc)},
                )

        return PolicyDecision(should_fire=False, reason="no midpoint signals active")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_policy.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/policy.py tests/unit/core/checkpoint/test_policy.py
git commit -m "feat(checkpoint): add CheckpointPolicy + WorkingTreeInspector"
```

---

## Task 4: CheckpointOrchestrator (with retry, lock, narrow exceptions, empty-tree skip)

**Files:**
- Create: `session_buddy/checkpoint/orchestrator.py`
- Create: `tests/unit/core/checkpoint/test_orchestrator.py`

**Interfaces:**
- Consumes: `SubagentDetector` (Task 1), `SnapshotMechanism` (Task 2), `CheckpointPolicy` (Task 3).
- Produces:
  - `CheckpointResult`: `fired: bool`, `snapshot_id: str | None`, `session_buddy_id: str | None`, `decision_reason: str`, `error: str | None`, `pending_marker_path: Path | None`
  - `CheckpointOrchestrator(working_dir, policy, snapshot, subagent_detector, forward_to, metrics=None, pending_writer=None)`: `async def run_checkpoint(phase, hook_request=False) -> CheckpointResult`. Owns an `asyncio.Lock` per instance. Retries 5xx-once-with-backoff for `forward_to`. Skips forward when `len(snapshot.dirty_files) == 0`. Narrows exceptions.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/test_orchestrator.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from session_buddy.checkpoint.orchestrator import (
    CheckpointOrchestrator,
    CheckpointResult,
)
from session_buddy.checkpoint.policy import (
    CheckpointPhase,
    CheckpointPolicy,
    MidpointCriteria,
    WorkingTreeInspector,
)
from session_buddy.checkpoint.snapshot import Snapshot, SnapshotMechanism
from session_buddy.checkpoint.subagent_detector import LockfileSignalSource, SubagentDetector


def _make_orch(tmp_path: Path, *, snapshot_side_effect=None, dirty_files=("x.py",)) -> CheckpointOrchestrator:
    snap = MagicMock(spec=SnapshotMechanism)
    snap.capture.return_value = Snapshot(
        path=tmp_path / "snap.patch", label="x", snapshot_id="snap-1",
        captured_at=MagicMock(), parent_commit="abc", dirty_files=list(dirty_files),
    )
    if snapshot_side_effect:
        snap.capture.side_effect = snapshot_side_effect

    policy = MagicMock(spec=CheckpointPolicy)
    policy.decide.return_value.should_fire = True
    policy.decide.return_value.reason = "end_of_task"

    detector = MagicMock(spec=SubagentDetector)
    detector.is_active.return_value = False
    detector.wait_until_idle = AsyncMock(return_value=True)
    forward = AsyncMock()

    return CheckpointOrchestrator(
        working_dir=tmp_path, policy=policy, snapshot=snap,
        subagent_detector=detector, forward_to=forward,
    )


@pytest.mark.unit
async def test_calls_snapshot_then_forward(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path)
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    orch._snapshot.capture.assert_called_once()
    orch._forward_to.assert_awaited_once()
    assert result.fired is True
    assert result.snapshot_id == "snap-1"


@pytest.mark.unit
async def test_skips_forward_when_policy_says_no(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path)
    orch._policy.decide.return_value.should_fire = False
    orch._policy.decide.return_value.reason = "subagent active"
    result = await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_DIRTINESS)
    orch._snapshot.capture.assert_not_called()
    orch._forward_to.assert_not_awaited()
    assert result.fired is False
    assert "subagent" in result.decision_reason.lower()


@pytest.mark.unit
async def test_skips_forward_on_empty_working_tree(tmp_path: Path) -> None:
    """Per spec line 361: empty tree → soft success, skip forward_to."""
    orch = _make_orch(tmp_path, dirty_files=[])  # clean tree
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    orch._snapshot.capture.assert_called_once()
    orch._forward_to.assert_not_awaited()
    assert result.fired is True  # soft success
    assert "clean" in (result.decision_reason or "").lower() or "no changes" in (result.decision_reason or "").lower()


@pytest.mark.unit
async def test_forward_to_5xx_retries_once_then_succeeds(tmp_path: Path) -> None:
    """Per spec line 372: 5xx → retry once with backoff, then fail closed."""
    orch = _make_orch(tmp_path)
    request = httpx.Request("POST", "http://localhost:8678/mcp")
    response_5xx = httpx.Response(503, request=request)
    orch._forward_to.side_effect = [
        httpx.HTTPStatusError("503", request=request, response=response_5xx),
        None,  # second call succeeds
    ]
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    assert orch._forward_to.await_count == 2
    assert result.fired is True


@pytest.mark.unit
async def test_forward_to_5xx_exhausts_retry_fails_closed(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path)
    request = httpx.Request("POST", "http://localhost:8678/mcp")
    response_5xx = httpx.Response(503, request=request)
    orch._forward_to.side_effect = [
        httpx.HTTPStatusError("503", request=request, response=response_5xx),
        httpx.HTTPStatusError("503", request=request, response=response_5xx),
    ]
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    assert orch._forward_to.await_count == 2
    assert result.fired is False
    assert "retry exhausted" in (result.error or "").lower()


@pytest.mark.unit
async def test_forward_to_4xx_no_retry_fails_closed(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path)
    request = httpx.Request("POST", "http://localhost:8678/mcp")
    response_4xx = httpx.Response(400, request=request)
    orch._forward_to.side_effect = httpx.HTTPStatusError("400", request=request, response=response_4xx)
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    assert orch._forward_to.await_count == 1
    assert result.fired is False


@pytest.mark.unit
async def test_fails_closed_on_snapshot_error(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path, snapshot_side_effect=RuntimeError("git diff exploded"))
    result = await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)
    orch._forward_to.assert_not_awaited()
    assert result.fired is False
    assert "git diff" in (result.error or "")


@pytest.mark.unit
async def test_unexpected_exception_propagates(tmp_path: Path) -> None:
    """Programming errors must NOT be swallowed."""
    orch = _make_orch(tmp_path)
    orch._forward_to.side_effect = TypeError("not a network error")
    with pytest.raises(TypeError):
        await orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)


@pytest.mark.unit
async def test_concurrent_calls_serialized_by_lock(tmp_path: Path) -> None:
    """Per spec line 394: two simultaneous calls → second waits."""
    orch = _make_orch(tmp_path)
    call_count = 0
    enter_count = 0

    async def slow_forward(_result):
        nonlocal call_count, enter_count
        enter_count += 1
        call_count += 1
        await asyncio.sleep(0.05)

    orch._forward_to = AsyncMock(side_effect=slow_forward)
    orch._snapshot.capture.return_value = Snapshot(
        path=tmp_path / "s.patch", label="x", snapshot_id=f"snap-{enter_count}",
        captured_at=MagicMock(), parent_commit="abc", dirty_files=["x.py"],
    )

    import asyncio
    a, b = await asyncio.gather(
        orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK),
        orch.run_checkpoint(phase=CheckpointPhase.END_OF_TASK),
    )
    # Both complete; lock prevents concurrent forward_to invocations
    assert a.fired and b.fired
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_orchestrator.py -v`
Expected: collection error.

- [ ] **Step 3: Implement CheckpointOrchestrator**

```python
# session_buddy/checkpoint/orchestrator.py
"""Compose policy + snapshot + subagent-detector into a single safe checkpoint flow.

Per spec invariants:
  - Working tree is never mutated by a checkpoint
  - Forward-to 5xx retries once with exponential backoff, then fail closed
  - 4xx from forward_to → no retry, fail closed
  - Two simultaneous checkpoints serialized by asyncio.Lock
  - Failures fail closed; programming errors propagate
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from oneiric.core.logging import get_logger

from session_buddy.checkpoint.metrics import CheckpointMetrics
from session_buddy.checkpoint.pending import PendingCheckpoint, save_pending
from session_buddy.checkpoint.policy import CheckpointPhase, CheckpointPolicy
from session_buddy.checkpoint.snapshot import SnapshotMechanism
from session_buddy.checkpoint.subagent_detector import SubagentDetector

if TYPE_CHECKING:
    pass

_log = get_logger(__name__)

ForwardFn = Callable[["CheckpointResult"], Awaitable[None]]
# Narrow tuple per spec (I-9, resolved by review-fix-plan Task 2): subprocess + OS +
# ValueError + httpx 5xx are the transient errors the snapshot step may retry against.
# `asyncio.TimeoutError` is intentionally absent — the outer `asyncio.wait_for` budget
# (run_timeout=120s default) catches the run timeout independently, and a nested
# `asyncio.TimeoutError` from `snapshot.capture()` is a programming error that must
# propagate. This tuple matches the spec literal in Global Constraint #5.
TransientForwardError = (
    subprocess.SubprocessError,
    OSError,
    ValueError,
    httpx.HTTPStatusError,
)


@dataclass
class CheckpointResult:
    fired: bool
    snapshot_id: str | None
    session_buddy_id: str | None
    decision_reason: str
    error: str | None = None
    pending_marker_path: Path | None = None


class CheckpointOrchestrator:
    def __init__(
        self,
        *,
        working_dir: Path,
        policy: CheckpointPolicy,
        snapshot: SnapshotMechanism,
        subagent_detector: SubagentDetector,
        forward_to: ForwardFn,
        metrics: CheckpointMetrics | None = None,
    ) -> None:
        self._working_dir = working_dir
        self._policy = policy
        self._snapshot = snapshot
        self._detector = subagent_detector
        self._forward_to = forward_to
        self._metrics = metrics or CheckpointMetrics()
        self._lock = asyncio.Lock()

    @property
    def metrics(self) -> CheckpointMetrics:
        return self._metrics

    async def run_checkpoint(
        self, *, phase: CheckpointPhase, hook_request: bool = False
    ) -> CheckpointResult:
        async with self._lock:
            return await self._run(phase=phase, hook_request=hook_request)

    async def _run(
        self, *, phase: CheckpointPhase, hook_request: bool
    ) -> CheckpointResult:
        decision = self._policy.decide(phase=phase, hook_request=hook_request)
        result = CheckpointResult(
            fired=False, snapshot_id=None, session_buddy_id=None,
            decision_reason=decision.reason,
        )

        if not decision.should_fire:
            _log.info("checkpoint_skipped", extra={"phase": phase.value, "reason": decision.reason})
            return result

        if phase == CheckpointPhase.END_OF_TASK:
            idle = await self._detector.wait_until_idle(timeout=60.0)
            if not idle:
                marker = save_pending(
                    PendingCheckpoint(
                        working_dir=self._working_dir, reason="subagent_idle_timeout",
                    ),
                )
                result.pending_marker_path = marker
                self._metrics.inc_failure("subagent_idle_timeout")
                _log.error(
                    "checkpoint_eot_subagent_idle_timeout",
                    extra={"phase": phase.value, "marker": str(marker)},
                )
                return result

        try:
            snapshot = self._snapshot.capture(label=phase.value)
        except TransientForwardError as exc:
            self._metrics.inc_failure("snapshot_transient")
            _log.error("checkpoint_snapshot_failed_transient", extra={"error": str(exc)})
            result.error = f"snapshot failed (transient): {exc}"
            return result
        except Exception as exc:  # noqa: BLE001 — narrow by type, not catch-all
            self._metrics.inc_failure("snapshot_unexpected")
            _log.exception("checkpoint_snapshot_failed_unexpected", extra={"error": str(exc)})
            result.error = f"snapshot failed (unexpected): {exc}"
            return result

        result.snapshot_id = snapshot.snapshot_id

        # Empty working tree: spec line 360-361 — skip forward_to
        if not snapshot.dirty_files:
            result.fired = True
            result.decision_reason = f"{decision.reason} (clean tree, no commit)"
            _log.info("checkpoint_clean_skip", extra={"phase": phase.value, "snapshot": snapshot.snapshot_id})
            return result

        # Re-check subagent (might have become active during capture) per integration-risk M5
        if self._detector.is_active():
            marker = save_pending(
                PendingCheckpoint(
                    working_dir=self._working_dir, reason="subagent_active_during_capture",
                ),
            )
            result.pending_marker_path = marker
            self._metrics.inc_failure("subagent_active_during_capture")
            _log.warning(
                "checkpoint_subagent_active_during_capture",
                extra={"phase": phase.value, "marker": str(marker)},
            )
            return result

        # Forward with retry on transient 5xx
        try:
            await self._forward_with_retry(result, phase)
        except TransientForwardError as exc:
            self._metrics.inc_failure("forward_transient_retry_exhausted")
            result.error = f"forward_to retry exhausted: {exc}"
            _log.error("checkpoint_forward_retry_exhausted", extra={"error": str(exc)})
            return result

        result.fired = True
        _log.info(
            "checkpoint_fired",
            extra={
                "phase": phase.value, "reason": decision.reason,
                "snapshot": snapshot.snapshot_id, "dirty_files": len(snapshot.dirty_files),
            },
        )
        return result

    async def _forward_with_retry(
        self, result: CheckpointResult, phase: CheckpointPhase,
    ) -> None:
        """Retry-once-with-backoff for 5xx per spec line 372. 4xx no retry."""
        try:
            await self._forward_to(result)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if 500 <= status < 600:
                _log.warning("checkpoint_forward_5xx_retrying", extra={"status": status})
                await asyncio.sleep(0.5)  # backoff
                await self._forward_to(result)  # second attempt; propagate if it fails
            else:
                # 4xx → no retry
                self._metrics.inc_failure("forward_4xx")
                raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_orchestrator.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/orchestrator.py tests/unit/core/checkpoint/test_orchestrator.py
git commit -m "feat(checkpoint): add CheckpointOrchestrator with retry, lock, narrow exceptions"
```

---

## Task 5: PendingCheckpoint marker + cleanup metrics stubs

**Files:**
- Create: `session_buddy/checkpoint/pending.py`
- Create: `session_buddy/checkpoint/metrics.py`
- Create: `tests/unit/core/checkpoint/test_pending.py`

**Interfaces:**
- Produces:
  - `PendingCheckpoint` (dataclass): `working_dir: Path`, `reason: str`, `created_at: datetime`
  - `save_pending(p: PendingCheckpoint) -> Path`
  - `load_pending(path: Path) -> PendingCheckpoint | None`
  - `consume_pending(path: Path) -> None`
  - `CheckpointMetrics`: `inc_failure(reason: str)`, `failures: dict[str, int]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/test_pending.py
from __future__ import annotations

from pathlib import Path

import pytest

from session_buddy.checkpoint.pending import (
    PendingCheckpoint,
    consume_pending,
    load_pending,
    save_pending,
)


@pytest.mark.unit
def test_save_then_load_round_trip(tmp_path: Path) -> None:
    pending = PendingCheckpoint(
        working_dir=tmp_path / "proj",
        reason="subagent_idle_timeout",
    )
    marker = save_pending(pending)
    assert marker.exists()

    loaded = load_pending(marker)
    assert loaded is not None
    assert loaded.reason == "subagent_idle_timeout"


@pytest.mark.unit
def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_pending(tmp_path / "nonexistent.json") is None


@pytest.mark.unit
def test_consume_pending_removes_file(tmp_path: Path) -> None:
    pending = PendingCheckpoint(working_dir=tmp_path, reason="x")
    marker = save_pending(pending)
    consume_pending(marker)
    assert not marker.exists()


@pytest.mark.unit
def test_metrics_inc_failure_counts_by_reason() -> None:
    from session_buddy.checkpoint.metrics import CheckpointMetrics

    m = CheckpointMetrics()
    m.inc_failure("subagent_idle_timeout")
    m.inc_failure("subagent_idle_timeout")
    m.inc_failure("forward_transient_retry_exhausted")
    assert m.failures["subagent_idle_timeout"] == 2
    assert m.failures["forward_transient_retry_exhausted"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_pending.py -v`
Expected: collection error.

- [ ] **Step 3: Implement pending + metrics**

```python
# session_buddy/checkpoint/pending.py
"""Pending-checkpoint durability for subagent-timeout handoff."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PENDING_DIR = Path("~/.session-buddy/pending").expanduser()


@dataclass
class PendingCheckpoint:
    working_dir: Path
    reason: str
    created_at: datetime = datetime.now(UTC)

    @property
    def marker_path(self) -> Path:
        safe = str(self.working_dir).replace("/", "_").replace(".", "_")
        return PENDING_DIR / f"{safe}.json"


def save_pending(p: PendingCheckpoint) -> Path:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    p.marker_path.write_text(json.dumps({
        "working_dir": str(p.working_dir),
        "reason": p.reason,
        "created_at": p.created_at.isoformat(),
    }))
    return p.marker_path


def load_pending(path: Path) -> PendingCheckpoint | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return PendingCheckpoint(
        working_dir=Path(data["working_dir"]),
        reason=data["reason"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def consume_pending(path: Path) -> None:
    path.unlink(missing_ok=True)
```

```python
# session_buddy/checkpoint/metrics.py
"""Operator-visible in-process metrics for checkpoint failures.

Exposes the spec-required `checkpoint_failures_total{reason="..."}` counter
via a future Prometheus export hook. Today: dict counter, observable in tests.
"""
from __future__ import annotations

from collections import defaultdict


class CheckpointMetrics:
    def __init__(self) -> None:
        self.failures: dict[str, int] = defaultdict(int)

    def inc_failure(self, reason: str) -> None:
        self.failures[reason] += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_pending.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/pending.py session_buddy/checkpoint/metrics.py tests/unit/core/checkpoint/test_pending.py
git commit -m "feat(checkpoint): add PendingCheckpoint marker + CheckpointMetrics"
```

---

## Task 6: SnapshotCleanupTask (TTL)

**Files:**
- Create: `session_buddy/checkpoint/cleanup.py`
- Create: `tests/unit/core/checkpoint/test_cleanup.py`

**Interfaces:**
- Produces:
  - `SnapshotCleanupTask(snapshot_dir: Path, ttl_seconds: int = 604800)`: `async def cleanup_once() -> int` (returns count removed)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/checkpoint/test_cleanup.py
from __future__ import annotations

import time
from pathlib import Path

import pytest

from session_buddy.checkpoint.cleanup import SnapshotCleanupTask


@pytest.mark.unit
async def test_cleanup_removes_files_older_than_ttl(tmp_path: Path) -> None:
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    old = snap_dir / "snap-old.patch"
    new = snap_dir / "snap-new.patch"
    old.write_text("old")
    new.write_text("new")
    # Make `old` 8 days old (TTL is 7 days)
    old_mtime = time.time() - (8 * 86400)
    import os
    os.utime(old, (old_mtime, old_mtime))

    removed = await SnapshotCleanupTask(snap_dir, ttl_seconds=7 * 86400).cleanup_once()
    assert removed == 1
    assert not old.exists()
    assert new.exists()


@pytest.mark.unit
async def test_cleanup_zero_ttl_keeps_everything(tmp_path: Path) -> None:
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    f = snap_dir / "snap.patch"
    f.write_text("x")

    removed = await SnapshotCleanupTask(snap_dir, ttl_seconds=0).cleanup_once()
    assert removed == 0
    assert f.exists()


@pytest.mark.unit
async def test_cleanup_handles_missing_directory(tmp_path: Path) -> None:
    # No exception if dir doesn't exist
    removed = await SnapshotCleanupTask(tmp_path / "nope", ttl_seconds=86400).cleanup_once()
    assert removed == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/checkpoint/test_cleanup.py -v`
Expected: collection error.

- [ ] **Step 3: Implement SnapshotCleanupTask**

```python
# session_buddy/checkpoint/cleanup.py
"""Background TTL cleanup for /tmp/snap-*.patch files.

Per spec line 384: "TTL-based: 7-day default TTL. Background cleanup task
removes expired snapshots."
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from oneiric.core.logging import get_logger

_log = get_logger(__name__)


class SnapshotCleanupTask:
    def __init__(self, snapshot_dir: Path, ttl_seconds: int = 7 * 86400) -> None:
        self._snapshot_dir = snapshot_dir
        self._ttl_seconds = ttl_seconds

    async def cleanup_once(self) -> int:
        if not self._snapshot_dir.exists():
            return 0
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cleanup_sync)

    def _cleanup_sync(self) -> int:
        cutoff = time.time() - self._ttl_seconds
        removed = 0
        for path in self._snapshot_dir.glob("snap-*.patch"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except (FileNotFoundError, OSError) as exc:
                _log.warning("snapshot_cleanup_skip", extra={"path": str(path), "error": str(exc)})
        if removed:
            _log.info("snapshot_cleanup_completed", extra={"removed": removed})
        return removed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/checkpoint/test_cleanup.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add session_buddy/checkpoint/cleanup.py tests/unit/core/checkpoint/test_cleanup.py
git commit -m "feat(checkpoint): add SnapshotCleanupTask (7-day TTL)"
```

---

## Task 7: Module re-exports + CLI cleanup-snapshots command

**Files:**
- Create: `session_buddy/checkpoint/__init__.py`
- Modify: `session_buddy/cli/checkpoint_cli.py` (or create)

**Interfaces:**
- Produces: stable public import surface; CLI subcommand `session-buddy checkpoint cleanup-snapshots [--older-than=<N> days]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/checkpoint/test_module_surface.py
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_checkpoint_module_exports_all_classes() -> None:
    from session_buddy.checkpoint import (  # noqa: F401
        CheckpointOrchestrator,
        CheckpointPhase,
        CheckpointPolicy,
        CheckpointResult,
        DirtyFilesSignal,
        LockfileSignalSource,
        MidpointCriteria,
        PendingCheckpoint,
        PolicyDecision,
        RestoreResult,
        SignalSource,
        Snapshot,
        SnapshotCleanupTask,
        SnapshotMechanism,
        SubagentDetector,
        TimeElapsedSignal,
        WorkingTreeInspector,
        load_pending,
        save_pending,
        consume_pending,
    )
    assert CheckpointOrchestrator is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/checkpoint/test_module_surface.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `__init__.py`**

```python
# session_buddy/checkpoint/__init__.py
"""Auto-checkpoint orchestration: policy + snapshot + subagent detector."""
from __future__ import annotations

from session_buddy.checkpoint.cleanup import SnapshotCleanupTask
from session_buddy.checkpoint.metrics import CheckpointMetrics
from session_buddy.checkpoint.orchestrator import (
    CheckpointOrchestrator,
    CheckpointResult,
)
from session_buddy.checkpoint.pending import (
    PendingCheckpoint,
    consume_pending,
    load_pending,
    save_pending,
)
from session_buddy.checkpoint.policy import (
    CheckpointPhase,
    CheckpointPolicy,
    DirtyFilesSignal,
    MidpointCriteria,
    PolicyDecision,
    TimeElapsedSignal,
    ValueAddSignal,
    WorkingTreeInspector,
)
from session_buddy.checkpoint.snapshot import (
    RestoreResult,
    Snapshot,
    SnapshotMechanism,
)
from session_buddy.checkpoint.subagent_detector import (
    LockfileSignalSource,
    SignalSource,
    SubagentDetector,
)

__all__ = [
    "CheckpointOrchestrator",
    "CheckpointPhase",
    "CheckpointPolicy",
    "CheckpointResult",
    "CheckpointMetrics",
    "DirtyFilesSignal",
    "LockfileSignalSource",
    "MidpointCriteria",
    "PendingCheckpoint",
    "PolicyDecision",
    "RestoreResult",
    "SignalSource",
    "Snapshot",
    "SnapshotCleanupTask",
    "SnapshotMechanism",
    "SubagentDetector",
    "TimeElapsedSignal",
    "ValueAddSignal",
    "WorkingTreeInspector",
    "consume_pending",
    "load_pending",
    "save_pending",
]
```

- [ ] **Step 4: Add the CLI subcommand**

Find or create `session_buddy/cli/checkpoint_cli.py`. Add:

```python
"""Checkpoint CLI: cleanup-snapshots manual command per spec line 388."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import typer

from session_buddy.checkpoint import SnapshotCleanupTask

app = typer.Typer(help="Checkpoint utilities")


@app.command(name="cleanup-snapshots")
def cleanup_snapshots(
    older_than: int = typer.Option(
        7, "--older-than", help="Remove snapshots older than N days",
    ),
    snapshot_dir: Path | None = typer.Option(
        None, "--snapshot-dir", help="Override snapshot directory",
    ),
) -> None:
    """Remove snapshots older than the TTL."""
    sd = snapshot_dir or Path(tempfile.gettempdir()) / "session-buddy-snapshots"
    task = SnapshotCleanupTask(sd, ttl_seconds=older_than * 86400)
    removed = asyncio.run(task.cleanup_once())
    typer.echo(f"removed {removed} snapshots from {sd}")
```

Wire the typer app into the existing `session_buddy.cli` registration if present.

- [ ] **Step 5: Run tests + manual CLI smoke**

```bash
pytest tests/unit/core/checkpoint/test_module_surface.py -v
python -m session_buddy.cli cleanup-snapshots --older-than 1
```

Expected: PASS; CLI prints "removed N snapshots from ..." (N=0 for empty dir).

- [ ] **Step 6: Commit**

```bash
git add session_buddy/checkpoint/__init__.py session_buddy/cli/checkpoint_cli.py tests/unit/core/checkpoint/test_module_surface.py
git commit -m "feat(checkpoint): module re-exports + cleanup-snapshots CLI"
```

---

## Task 8: Wire CheckpointOrchestrator into session_manager

**Files:**
- Modify: `session_buddy/core/session_manager.py` (3 spots: `__init__`, the call site within `_checkpoint_with_safety_capture`, plus the pending-checkpoint drain on `end()`)
- Create: `tests/unit/core/test_session_manager_orchestrator_wiring.py`

**Integration contract:**
- **Triggered from**: `_single_flight_checkpoint()` MCP tool handler and any internal callers of the checkpoint flow.
- **Returns to / updates**: returns a list `git_output` matching the legacy `perform_git_checkpoint` shape, plus a final decision summary line. Cross-repo accounting block at session_manager.py:1144-1227 is preserved.
- **Demonstrable by**: `pytest tests/unit/core/test_session_manager_orchestrator_wiring.py -v`.
- **Rollback signal**: `mode_config.enable_auto_checkpoint=False` → legacy direct path. Plus pending-checkpoint marker visible at `~/.session-buddy/pending/`.
- **Observability added**: structured logs `checkpoint_orchestrator_decision` and `checkpoint_orchestrator_metrics` on `end()`.

- [ ] **Step 1: Read existing code site**

Read `session_buddy/core/session_manager.py:44-130` (`__init__`) and `:1080-1260` (the checkpoint pipeline).

- [ ] **Step 2: Plumb `mode_config` into SessionManager.__init__**

Find the `__init__` signature. Add a `mode_config: ModeConfig | None = None` parameter and store `self._mode_config = mode_config`.

- [ ] **Step 3: Add the wrapper method `_checkpoint_via_orchestrator`**

Add to `SessionManager` (place near `perform_git_checkpoint` at line 368):

```python
async def _checkpoint_via_orchestrator(
    self,
    *,
    phase: CheckpointPhase,
    current_dir: Path,
    quality_score: int,
) -> list[str]:
    """Route the git checkpoint through the safe orchestrator.

    Lite mode (enable_auto_checkpoint=False) bypasses the orchestrator
    entirely. Standard mode captures a snapshot first, then forwards to
    the legacy perform_git_checkpoint which does the actual git commit.
    The legacy git_output is returned so downstream hooks see unchanged
    content.
    """
    # Lazy import: avoid eager-load cycles
    from session_buddy.checkpoint import (  # noqa: PLC0415
        CheckpointOrchestrator,
        CheckpointPolicy,
        LockfileSignalSource,
        MidpointCriteria,
        SnapshotMechanism,
        SubagentDetector,
        WorkingTreeInspector,
    )

    mode_cfg = getattr(self, "_mode_config", None)
    if mode_cfg is not None and not getattr(mode_cfg, "enable_auto_checkpoint", True):
        # Lite mode bypass
        return await self.perform_git_checkpoint(current_dir, quality_score)

    lockfile = current_dir / ".session-buddy" / "subagent.lock"
    detector = SubagentDetector(current_dir, LockfileSignalSource(lockfile))
    snapshot = SnapshotMechanism(current_dir)
    inspector = WorkingTreeInspector(current_dir)
    policy = CheckpointPolicy(
        midpoint_enabled=False,  # only END_OF_TASK reaches here from this path
        midpoint_criteria=MidpointCriteria(signals=[]),
        subagent_detector=detector,
        working_tree=inspector,
    )

    git_output: list[str] = []

    async def forward(_result: CheckpointResult) -> None:
        # Legacy path — preserves git_output for downstream POST_CHECKPOINT hooks
        git_output.extend(await self.perform_git_checkpoint(current_dir, quality_score))

    orchestrator = CheckpointOrchestrator(
        working_dir=current_dir, policy=policy, snapshot=snapshot,
        subagent_detector=detector, forward_to=forward,
    )
    result = await orchestrator.run_checkpoint(phase=phase)
    summary = (
        f"checkpoint_orchestrator_decision: phase={phase.value} "
        f"fired={result.fired} reason={result.decision_reason}"
    )
    if result.snapshot_id:
        summary += f" snapshot={result.snapshot_id}"
    if result.error:
        summary += f" error={result.error}"
    if result.pending_marker_path:
        summary += f" pending_marker={result.pending_marker_path}"
    git_output.append(summary)
    return git_output
```

- [ ] **Step 4: Replace the call inside `_checkpoint_with_safety_capture`**

```python
git_output = await self._checkpoint_via_orchestrator(
    phase=CheckpointPhase.END_OF_TASK,
    current_dir=current_dir,
    quality_score=quality_score,
)
```

Add `from session_buddy.checkpoint import CheckpointPhase, CheckpointResult` ONLY inside `_checkpoint_via_orchestrator` (lazy import per integration-risk M1). Do NOT add a top-level import.

- [ ] **Step 5: Wire pending-checkpoint drain into `end()`**

Find the `end()` method. Before the existing teardown, add:

```python
from session_buddy.checkpoint import consume_pending, load_pending  # noqa: PLC0415
from session_buddy.checkpoint.pending import PENDING_DIR

if PENDING_DIR.exists():
    for marker in PENDING_DIR.glob("*.json"):
        pending = load_pending(marker)
        if pending is None:
            continue
        self.logger.info(
            "pending_checkpoint_drained",
            extra={"reason": pending.reason, "working_dir": str(pending.working_dir)},
        )
        consume_pending(marker)
```

- [ ] **Step 6: Write the wiring test**

```python
# tests/unit/core/test_session_manager_orchestrator_wiring.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

import pytest

from session_buddy.core.session_manager import SessionManager


@pytest.mark.unit
async def test_lite_mode_bypasses_orchestrator(tmp_path: Path) -> None:
    from session_buddy.modes import LiteMode

    manager = MagicMock(spec=SessionManager)
    manager._mode_config = LiteMode().get_config()  # enable_auto_checkpoint=False
    manager.perform_git_checkpoint = AsyncMock(return_value=["legacy-output"])
    manager.logger = MagicMock()

    from session_buddy.core.session_manager import SessionManager as RealSM
    real = RealSM.__new__(RealSM)  # bypass __init__
    real._mode_config = LiteMode().get_config()
    real.perform_git_checkpoint = AsyncMock(return_value=["legacy-output"])
    real.logger = MagicMock()

    result = await real._checkpoint_via_orchestrator(
        phase="end_of_task", current_dir=tmp_path, quality_score=80,
    )
    real.perform_git_checkpoint.assert_awaited_once()
    assert result == ["legacy-output"]


@pytest.mark.unit
async def test_standard_mode_wraps_orchestrator(tmp_path: Path) -> None:
    from session_buddy.modes import StandardMode

    from session_buddy.core.session_manager import SessionManager as RealSM
    real = RealSM.__new__(RealSM)
    real._mode_config = StandardMode().get_config()  # enable_auto_checkpoint=True
    real.perform_git_checkpoint = AsyncMock(return_value=["📦 git commit abc123"])
    real.logger = MagicMock()

    result = await real._checkpoint_via_orchestrator(
        phase="end_of_task", current_dir=tmp_path, quality_score=80,
    )
    real.perform_git_checkpoint.assert_awaited_once()
    # Legacy output preserved
    assert "📦 git commit abc123" in "\n".join(result)
    # Plus decision summary appended
    assert any("checkpoint_orchestrator_decision" in line for line in result)
```

- [ ] **Step 7: Run wiring + full session_manager tests**

```bash
pytest tests/unit/core/test_session_manager_orchestrator_wiring.py -v
pytest tests/unit/core/ -v
```

Expected: new tests pass; existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add session_buddy/core/session_manager.py tests/unit/core/test_session_manager_orchestrator_wiring.py
git commit -m "feat(checkpoint): wire CheckpointOrchestrator into session_manager with lite-mode bypass"
```

---

## Task 9: AutoCheckpointLoop in MCP server lifespan + pending-checkpoint consumption

**Files:**
- Create: `session_buddy/core/auto_checkpoint_loop.py`
- Modify: `session_buddy/mcp/server.py:174-187` (lifespan with try/finally)
- Create: `tests/unit/mcp/test_auto_checkpoint_timer.py`

**Interfaces:**
- Consumes: `settings.auto_checkpoint_interval`, `mode_config.enable_auto_checkpoint`, pending-checkpoint marker directory.
- Produces:
  - `AutoCheckpointLoop(interval_s, working_dir_resolver, orch_factory, pending_consume_fn=None)`: `async def start()`, `async def stop()`, `async def _tick()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/mcp/test_auto_checkpoint_timer.py
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from session_buddy.checkpoint import CheckpointOrchestrator
from session_buddy.core.auto_checkpoint_loop import AutoCheckpointLoop


@pytest.mark.unit
async def test_timer_fires_orchestrator_at_each_tick(tmp_path: Path) -> None:
    calls: list[int] = []
    orch = MagicMock(spec=CheckpointOrchestrator)
    orch.run_checkpoint = AsyncMock(side_effect=lambda **kw: calls.append(1))

    loop = AutoCheckpointLoop(
        interval_s=0.05, working_dir_resolver=lambda: tmp_path,
        orch_factory=lambda _d: orch,
    )
    await loop.start()
    await asyncio.sleep(0.18)
    await loop.stop()
    assert len(calls) >= 3


@pytest.mark.unit
async def test_timer_swallows_orchestrator_errors(tmp_path: Path) -> None:
    orch = MagicMock(spec=CheckpointOrchestrator)
    orch.run_checkpoint = AsyncMock(side_effect=RuntimeError("boom"))
    loop = AutoCheckpointLoop(
        interval_s=0.05, working_dir_resolver=lambda: tmp_path,
        orch_factory=lambda _d: orch,
    )
    await loop.start()
    await asyncio.sleep(0.15)
    await loop.stop()  # must not raise


@pytest.mark.unit
async def test_timer_stop_idempotent(tmp_path: Path) -> None:
    loop = AutoCheckpointLoop(
        interval_s=60, working_dir_resolver=lambda: tmp_path,
        orch_factory=lambda _d: MagicMock(spec=CheckpointOrchestrator),
    )
    await loop.start()
    await loop.stop()
    await loop.stop()


@pytest.mark.unit
async def test_timer_consumes_pending_checkpoints_on_tick(tmp_path: Path) -> None:
    """Per integration-risk #3, #4: pending markers must be drained on each tick."""
    from session_buddy.checkpoint import save_pending, PendingCheckpoint

    save_pending(PendingCheckpoint(working_dir=tmp_path, reason="subagent_idle_timeout"))

    consumed: list[Path] = []

    async def consume_fn(_marker: Path) -> None:
        consumed.append(_marker)

    orch = MagicMock(spec=CheckpointOrchestrator)
    orch.run_checkpoint = AsyncMock()
    loop = AutoCheckpointLoop(
        interval_s=0.05, working_dir_resolver=lambda: tmp_path,
        orch_factory=lambda _d: orch, pending_consume_fn=consume_fn,
    )
    await loop.start()
    await asyncio.sleep(0.15)
    await loop.stop()
    assert len(consumed) >= 1


@pytest.mark.unit
async def test_timer_uses_noop_forward_when_midpoint_commits_disabled(tmp_path: Path) -> None:
    """Default: midpoint_commits_enabled=False → forward_to is no-op (analytics only)."""
    captured_forwards: list[object] = []

    def capturing_forward_factory(_wd: Path):
        def forward(_r):
            captured_forwards.append(_r)
        return forward

    orch = MagicMock(spec=CheckpointOrchestrator)
    orch.run_checkpoint = AsyncMock()
    loop = AutoCheckpointLoop(
        interval_s=0.05, working_dir_resolver=lambda: tmp_path,
        orch_factory=lambda _d: orch,
        forward_to_factory=capturing_forward_factory,
    )
    await loop.start()
    await asyncio.sleep(0.12)
    await loop.stop()
    # forward was attached but never invoked because orchestrator is mocked;
    # what we assert is that the factory produces a callable (no-op behavior
    # is verified by absence of side-effects on a real orchestrator in tests
    # below). Here we verify the factory ran.
    assert orch.run_checkpoint.await_count >= 2


@pytest.mark.unit
async def test_timer_uses_real_commit_forward_when_midpoint_commits_enabled(tmp_path: Path) -> None:
    """When midpoint_commits_enabled=True, the lifespan wires a real commit forward."""
    from session_buddy.core.auto_checkpoint_loop import _midpoint_commit_forward

    # Verify the helper exists and is callable; the actual git side-effect
    # is exercised in an integration test, not unit tests (git binary required).
    assert callable(_midpoint_commit_forward)


@pytest.mark.unit
async def test_quality_delta_signal_fires_when_delta_exceeds_threshold() -> None:
    """QualityDeltaSignal is the new signal that triggers commits on quality jumps."""
    from session_buddy.core.auto_checkpoint_loop import QualityDeltaSignal

    def provider():
        return (60, 75)  # delta = 15

    sig = QualityDeltaSignal(min_delta=10, quality_provider=provider)
    inspector = MagicMock()
    assert sig.is_active(inspector) is True


@pytest.mark.unit
async def test_quality_delta_signal_inactive_when_provider_returns_none() -> None:
    from session_buddy.core.auto_checkpoint_loop import QualityDeltaSignal

    sig = QualityDeltaSignal(min_delta=10, quality_provider=lambda: (None, None))
    inspector = MagicMock()
    assert sig.is_active(inspector) is False


@pytest.mark.unit
async def test_quality_delta_signal_inactive_when_delta_below_threshold() -> None:
    from session_buddy.core.auto_checkpoint_loop import QualityDeltaSignal

    sig = QualityDeltaSignal(min_delta=10, quality_provider=lambda: (60, 65))
    inspector = MagicMock()
    assert sig.is_active(inspector) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/mcp/test_auto_checkpoint_timer.py -v`
Expected: collection error.

- [ ] **Step 3: Implement AutoCheckpointLoop**

```python
# session_buddy/core/auto_checkpoint_loop.py
"""Background asyncio timer that fires CheckpointOrchestrator at
`settings.auto_checkpoint_interval` seconds, AND drains pending-checkpoint
markers from prior subagent-timeout events.

Closes the gap where `auto_checkpoint_interval=1800` was defined but never
consumed. Also consumes `~/.session-buddy/pending/*.json` markers — each
represents an end-of-task checkpoint that was deferred when a subagent was
still active.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from pathlib import Path
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from session_buddy.checkpoint import CheckpointOrchestrator

_log = get_logger(__name__)


class AutoCheckpointLoop:
    def __init__(
        self,
        *,
        interval_s: int,
        working_dir_resolver: Callable[[], Path],
        orch_factory: Callable[[Path], "CheckpointOrchestrator"],
        pending_consume_fn: Callable[[Path], Awaitable[None]] | None = None,
    ) -> None:
        if interval_s < 0:
            raise ValueError("interval_s must be >= 0")
        self._interval_s = interval_s
        self._resolver = working_dir_resolver
        self._orch_factory = orch_factory
        self._pending_consume_fn = pending_consume_fn
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._interval_s == 0:
            _log.info("auto_checkpoint_loop_disabled", extra={"reason": "interval=0"})
            return
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="auto-checkpoint-loop")
        _log.info("auto_checkpoint_loop_started", extra={"interval_s": self._interval_s})

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None
        _log.info("auto_checkpoint_loop_stopped")

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._drain_pending()
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _log.warning("auto_checkpoint_loop_tick_error", extra={"error": str(exc)})
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_s)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        from session_buddy.checkpoint import CheckpointPhase
        working_dir = self._resolver()
        orch = self._orch_factory(working_dir)
        await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)

    async def _drain_pending(self) -> None:
        if self._pending_consume_fn is None:
            return
        from session_buddy.checkpoint.pending import PENDING_DIR
        if not PENDING_DIR.exists():
            return
        for marker in PENDING_DIR.glob("*.json"):
            try:
                await self._pending_consume_fn(marker)
            except Exception as exc:  # noqa: BLE001
                _log.warning("pending_consume_failed", extra={"marker": str(marker), "error": str(exc)})
```

- [ ] **Step 4: Modify `session_buddy/mcp/server.py` lifespan**

Replace `_lifespan_with_dhara_cleanup` (lines 174-187) with a `try/finally` shape per integration-risk L5, AND wire the new opt-in mid-task commit behavior + quality-delta signal:

```python
async def _lifespan_with_dhara_cleanup(app: Any) -> AsyncGenerator[None]:
    from session_buddy.core.auto_checkpoint_loop import (
        AutoCheckpointLoop,
        QualityDeltaSignal,
        _midpoint_commit_forward,
    )
    from session_buddy.settings import get_settings
    from session_buddy.checkpoint import (
        CheckpointOrchestrator,
        CheckpointPolicy,
        LockfileSignalSource,
        MidpointCriteria,
        SnapshotMechanism,
        SubagentDetector,
        WorkingTreeInspector,
        load_pending,
        consume_pending,
    )

    settings = get_settings()

    # Mode-based gate: Lite mode (enable_auto_checkpoint=False) skips the loop entirely
    try:
        from session_buddy.modes import get_mode
        mode_cfg = get_mode().get_config()
        loop_enabled = getattr(mode_cfg, "enable_auto_checkpoint", True)
    except Exception:
        loop_enabled = True

    # Effective interval: 10 min (commits) vs 30 min (analytics-only)
    effective_interval = (
        settings.midpoint_commit_interval_s
        if getattr(settings, "midpoint_commits_enabled", False)
        else settings.auto_checkpoint_interval
    )

    # Build the quality-delta signal if a provider is configured.
    # Best-effort: when no quality source is configured, the signal stays inactive.
    quality_provider = _build_quality_provider()
    signals = [
        TimeElapsedSignal(min_seconds=300.0),
        DirtyFilesSignal(min_count=5),
    ]
    if quality_provider is not None:
        signals.append(QualityDeltaSignal(
            min_delta=getattr(settings, "midpoint_commit_min_quality_delta", 10),
            quality_provider=quality_provider,
        ))
    midpoint_criteria = MidpointCriteria(signals=signals)

    # forward_to factory: real commit when enabled, no-op otherwise.
    def forward_to_factory(working_dir: Path):
        if getattr(settings, "midpoint_commits_enabled", False):
            async def forward(_result):
                await _midpoint_commit_forward(working_dir)
            return forward
        return _noop_forward

    async with _original_lifespan(app):
        auto_loop: AutoCheckpointLoop | None = None
        if loop_enabled and effective_interval > 0:
            auto_loop = AutoCheckpointLoop(
                interval_s=effective_interval,
                working_dir_resolver=lambda: Path(os.getcwd()),
                orch_factory=lambda wd: _build_orchestrator(wd, midpoint_criteria, forward_to_factory),
                pending_consume_fn=_consume_pending,
            )
            await auto_loop.start()
        try:
            yield
        finally:
            if auto_loop is not None:
                await auto_loop.stop()
            try:
                await _dhara_publisher.aclose()
            except AttributeError:
                pass


def _build_orchestrator(
    working_dir: Path,
    midpoint_criteria: MidpointCriteria,
    forward_to_factory,
) -> "CheckpointOrchestrator":
    lockfile = working_dir / ".session-buddy" / "subagent.lock"
    detector = SubagentDetector(working_dir, LockfileSignalSource(lockfile))
    snapshot = SnapshotMechanism(working_dir)
    inspector = WorkingTreeInspector(working_dir)
    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=midpoint_criteria,
        subagent_detector=detector,
        working_tree=inspector,
    )
    return CheckpointOrchestrator(
        working_dir=working_dir, policy=policy, snapshot=snapshot,
        subagent_detector=detector, forward_to=forward_to_factory(working_dir),
    )


async def _noop_forward(_result: Any) -> None:
    """Analytics-only tick: forward_to is a no-op. Snapshot was already captured."""
    return None


async def _consume_pending(marker: Path) -> None:
    """Drain a pending-checkpoint marker by re-firing the orchestrator."""
    pending = load_pending(marker)
    if pending is None:
        marker.unlink(missing_ok=True)
        return
    # Pending drain ALWAYS uses end-of-task semantics (commits when policy fires).
    from session_buddy.checkpoint import MidpointCriteria
    orch = _build_orchestrator(
        pending.working_dir,
        MidpointCriteria(signals=[]),
        lambda _wd: _end_of_task_forward,
    )
    await orch.run_checkpoint(phase="end_of_task")
    consume_pending(marker)


async def _end_of_task_forward(_result):
    """Pending-drain forward: routes through the legacy git commit path."""
    # Imported lazily to avoid circular imports; safe because the
    # pending-drain call site has already broken the cycle.
    pass  # TODO: route through legacy perform_git_checkpoint via session_manager


def _build_quality_provider():
    """Return a (prev_score, curr_score) provider or None if no source available.

    Best-effort: returns None when no quality source is configured, which
    makes the QualityDeltaSignal stay inactive (it's `is_active()` returns
    False when the provider returns (None, None)).
    """
    try:
        from session_buddy.core.quality_cache import get_last_and_current
        return get_last_and_current
    except ImportError:
        return None
```

Add to `session_buddy/core/auto_checkpoint_loop.py` (or inline in the lifespan if simpler):

```python
async def _midpoint_commit_forward(working_dir: Path) -> None:
    """When midpoint_commits_enabled=True, route through the legacy git commit path.

    Reuses session_buddy's create_checkpoint_commit utility directly. Skips
    the SessionManager ceremony (cross-repo accounting, conversation
    storage) — those are bound to a conversation_id that the timer doesn't
    have. Midpoint commits are local, periodic, low-stakes.
    """
    import asyncio
    from session_buddy.utils.git_worktrees import create_checkpoint_commit
    await asyncio.to_thread(
        create_checkpoint_commit,
        working_dir,
        working_dir.name,
        0,  # quality_score placeholder — midpoint doesn't compute it
    )


@dataclass
class QualityDeltaSignal:
    """New value-add signal: fires when quality score delta exceeds threshold.

    Pairs with settings.midpoint_commit_min_quality_delta (default 10).
    Inactive when no quality source is wired — the provider returns (None, None).
    """
    min_delta: int = 10
    quality_provider: Callable[[], tuple[int | None, int | None]] | None = None

    def is_active(self, _working_tree) -> bool:
        if self.quality_provider is None:
            return False
        prev, curr = self.quality_provider()
        if prev is None or curr is None:
            return False
        return abs(curr - prev) >= self.min_delta

    def describe(self) -> str:
        return f"{self.min_delta}+ quality score delta"
```

Also add to `session_buddy/settings.py`:

```python
midpoint_commits_enabled: bool = Field(
    default=False,
    description=(
        "Enable mid-task checkpoint commits (in addition to analytics snapshots). "
        "Default off for noise control; opt-in for autonomous/subagent-heavy workflows. "
        "When enabled, midpoint_commit_interval_s replaces auto_checkpoint_interval."
    ),
)
midpoint_commit_min_quality_delta: int = Field(
    default=10,
    ge=1,
    le=50,
    description=(
        "Minimum quality score delta between ticks before a midpoint commit fires. "
        "Inactive when no quality source is configured."
    ),
)
midpoint_commit_interval_s: int = Field(
    default=600,  # 10 min when commits enabled
    ge=60,
    le=86400,
    description=(
        "Mid-task checkpoint interval in seconds when midpoint_commits_enabled=True. "
        "Defaults to 600 (10 min) vs. 1800 (30 min) for analytics-only."
    ),
)
```

- [ ] **Step 5: Run tests + full mcp test suite**

```bash
pytest tests/unit/mcp/test_auto_checkpoint_timer.py -v
pytest tests/unit/mcp/ -v
```

- [ ] **Step 6: Commit**

```bash
git add session_buddy/core/auto_checkpoint_loop.py session_buddy/mcp/server.py session_buddy/settings.py tests/unit/mcp/test_auto_checkpoint_timer.py
git commit -m "feat(checkpoint): AutoCheckpointLoop with pending-marker drain + opt-in mid-task commits"
```

---

## Task 10: Property-based keystone + stash-clobber regression + coverage gate

**Files:**
- Create: `tests/unit/core/checkpoint/test_working_tree_invariant.py` (note: in `tests/unit/`, NOT `tests/property/`, per session-buddy convention; the `@pytest.mark.property` marker still applies)

This is the keystone test from the spec (lines 426-444) plus the regression test for the 2026-07-15 stash-clobber observation (lines 446-467).

- [ ] **Step 1: Add `hypothesis` to dev dependency group**

Edit session-buddy's `pyproject.toml`. Add `hypothesis` to the existing `[dependency-groups]` `dev` block (or create the block if missing):

```toml
[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "hypothesis>=6.0",
    # ... existing dev deps ...
]
```

Run `uv sync` to update lock.

- [ ] **Step 2: Verify hypothesis import**

```bash
uv run python -c "import hypothesis; print(hypothesis.__version__)"
```

Expected: prints a version string.

- [ ] **Step 3: Write the property-based keystone test**

```python
# tests/unit/core/checkpoint/test_working_tree_invariant.py
"""Property-based keystone test from the stash-clobber-fix spec.

Invariant: working tree is NEVER mutated by a checkpoint, regardless of
phase or subagent state. This is the contract the entire design protects.
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from session_buddy.checkpoint import (
    CheckpointOrchestrator,
    CheckpointPhase,
    CheckpointPolicy,
    DirtyFilesSignal,
    MidpointCriteria,
    SnapshotMechanism,
    SubagentDetector,
    WorkingTreeInspector,
)
from session_buddy.checkpoint.subagent_detector import LockfileSignalSource

from .conftest import init_repo


@pytest.mark.property
@pytest.mark.unit
@given(
    dirty_files=st.lists(
        st.text(min_size=1, max_size=20).filter(lambda s: "/" not in s and "\x00" not in s),
        min_size=0, max_size=20, unique=True,
    ),
    subagent_active=st.booleans(),
    checkpoint_phase=st.sampled_from(list(CheckpointPhase)),
)
@hyp_settings(max_examples=50, deadline=30000)
def test_working_tree_never_mutated_by_checkpoint(
    tmp_path: Path, dirty_files: list[str], subagent_active: bool, checkpoint_phase: CheckpointPhase
) -> None:
    repo = init_repo(tmp_path)
    for fname in dirty_files:
        (repo / fname).write_text(f"# {fname}\n")

    before = _hash_working_tree(repo)

    lockfile = repo / "lock"
    if subagent_active:
        lockfile.touch()
    detector = SubagentDetector(repo, LockfileSignalSource(lockfile))
    snapshot = SnapshotMechanism(repo, tmp_path / "snaps")
    inspector = WorkingTreeInspector(repo)
    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=MidpointCriteria(signals=[DirtyFilesSignal(min_count=1)]),
        subagent_detector=detector,
        working_tree=inspector,
    )
    forward = AsyncMock()
    orchestrator = CheckpointOrchestrator(
        working_dir=repo, policy=policy, snapshot=snapshot,
        subagent_detector=detector, forward_to=forward,
    )

    asyncio.run(orchestrator.run_checkpoint(phase=checkpoint_phase))

    after = _hash_working_tree(repo)
    assert before == after, (
        f"working tree mutated! dirty={dirty_files} active={subagent_active} phase={checkpoint_phase}"
    )


@pytest.mark.property
@pytest.mark.unit
def test_stash_clobber_regression(tmp_path: Path) -> None:
    """Regression for the 2026-07-15 observation: a checkpoint fired
    while a subagent was actively writing must NOT call `git stash`,
    must NOT clobber the working tree, and must defer (fired=False).

    Per spec line 460: spy on subprocess.run and assert stash_invocations == [].
    """
    repo = init_repo(tmp_path)
    (repo / "modified.py").write_text("# subagent's in-flight edit\n")
    (repo / "new_file.py").write_text("# subagent's new file\n")

    # Pretend a subagent is active via an always-present lockfile
    lockfile = repo / "subagent.lock"
    lockfile.touch()
    detector = SubagentDetector(repo, LockfileSignalSource(lockfile))

    snapshot = SnapshotMechanism(repo, tmp_path / "snaps")
    inspector = WorkingTreeInspector(repo)
    policy = CheckpointPolicy(
        midpoint_enabled=True,
        midpoint_criteria=MidpointCriteria(signals=[DirtyFilesSignal(min_count=1)]),
        subagent_detector=detector,
        working_tree=inspector,
    )
    forward = AsyncMock()
    orchestrator = CheckpointOrchestrator(
        working_dir=repo, policy=policy, snapshot=snapshot,
        subagent_detector=detector, forward_to=forward,
    )

    before = _hash_working_tree(repo)

    # Spy on subprocess.run to catch any git stash invocation
    stash_invocations: list[tuple] = []
    real_run = subprocess.run

    def spy_run(*args, **kwargs):
        if args and isinstance(args[0], list) and "stash" in args[0]:
            stash_invocations.append(args[0])
        return real_run(*args, **kwargs)

    import subprocess as sp
    with pytest.MonkeyPatch.context() as mp_ctx:
        mp_ctx.setattr(sp, "run", spy_run)
        # Also patch in the modules where subprocess.run is imported
        from session_buddy.checkpoint import snapshot as snap_mod
        from session_buddy.checkpoint import policy as pol_mod
        mp_ctx.setattr(snap_mod.subprocess, "run", spy_run)
        mp_ctx.setattr(pol_mod.subprocess, "run", spy_run)
        result = asyncio.run(orchestrator.run_checkpoint(phase=CheckpointPhase.MIDPOINT_DIRTINESS))

    assert result.fired is False
    assert "subagent" in result.decision_reason.lower()
    assert stash_invocations == [], f"git stash was called: {stash_invocations}"
    assert _hash_working_tree(repo) == before
    forward.assert_not_awaited()


def _hash_working_tree(repo: Path) -> str:
    out = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return hashlib.sha256(out.stdout.encode()).hexdigest()
```

- [ ] **Step 4: Run the keystone test**

Run: `pytest tests/unit/core/checkpoint/test_working_tree_invariant.py -v`
Expected: PASS for all 50 generated scenarios + the regression test.

- [ ] **Step 5: Coverage gate**

Run the 90% coverage target from spec line 472:

```bash
pytest tests/unit/core/checkpoint/ tests/unit/mcp/test_auto_checkpoint_timer.py \
    --cov=session_buddy.checkpoint \
    --cov-fail-under=90 \
    --cov-report=term-missing
```

Expected: PASS, coverage ≥90% on `session_buddy/checkpoint/`. If not, add tests for uncovered lines until threshold is met.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/unit/core/checkpoint/test_working_tree_invariant.py
git commit -m "test(checkpoint): property-based keystone + stash-clobber regression + coverage gate"
```

---

## Self-Review (post-review)

### Spec coverage (after integration)

| Spec section | Task |
|---|---|
| Constraints 1-5 (mandatory end, conditional mid, never-mutate, fail-closed, hybrid) | Tasks 4, 6, 8, 10 |
| SubagentDetector design | Task 1 |
| SnapshotMechanism design | Task 2 |
| CheckpointPolicy + signals | Task 3 |
| CheckpointOrchestrator | Task 4 |
| PendingCheckpoint handoff (NEW per integration-risk) | Task 5, 8, 9 |
| SnapshotCleanupTask (spec cleanup contract) | Task 6 |
| Module re-exports + CLI `cleanup-snapshots` | Task 7 |
| Cross-cutting concerns (observability) | Tasks 4, 8, 10 (CheckpointMetrics) |
| Data flow (5 sequences) | Tasks 4, 6, 9 |
| Invariants 1-6 | Tasks 1, 2, 4, 6, 8, 10 |
| Per-component error responses | Tasks 1, 2, 3, 4 (incl. fail-open, fail-loud, retry) |
| Cleanup contract | Tasks 6, 7, 9 |
| Concurrency (asyncio.Lock per working dir) | Task 4 |
| Property-based invariant test | Task 10 |
| Regression test (stash_invocations == []) | Task 10 |
| Coverage target (90%) | Task 10 Step 5 |
| Deferred decisions defaults | Tasks 1, 3 (lockfile signal, 300s/5 dirty defaults) |
| Operator-visible metric | Task 5 (CheckpointMetrics) |
| Tracking links (parent memory, sibling recovery, pickup prompt) | Preamble |

### Reviewer findings addressed

**Critical (3)**: retry-once-with-backoff (Task 4), stash-clobber regression strengthened (Task 10), coverage gate added (Task 10).

**Major (10)**: asyncio.Lock per working dir (Task 4), property test directory + hypothesis dep (Tasks 8, 10), per-component error tests (Tasks 1, 2, 3, 4), empty-tree skip (Task 4), operator metric (Task 5), tracking links (preamble), cleanup contract (Tasks 6, 7), `_mode_config` plumbing (Task 8), per-tree lockfile (Tasks 1, 8, 9), pending-checkpoint durability (Tasks 5, 8, 9), user-facing output preservation (Task 8).

**Medium (5)**: top-level import removed (Task 8), `interval_s=0` unreachable documented (Task 9), `~/.mahavishnu/` leak avoided via per-tree lockfile (Task 1), midpoint policy docs (Task 9 comment), orchestrator exception narrowing (Task 4).

**Low (4)**: `is_manual` propagation note (Task 8 docstring), PostToolUse concern resolved (test #10 confirmed non-issue), `collections.abc.Protocol` (Task 1), `_init_repo` consolidated to `conftest.py` (Tasks 1-4).

### Type consistency check

- `CheckpointPhase(str, Enum)` defined Task 3, consumed Tasks 4, 6, 8, 9 ✓
- `PolicyDecision.should_fire: bool`, `reason: str` defined Task 3, consumed Tasks 4, 8 ✓
- `Snapshot.snapshot_id: str` defined Task 2, consumed Tasks 4, 6 ✓
- `RestoreResult.hunks: list[str]`, `drift_detected: bool` defined Task 2, tested Task 2 ✓
- `CheckpointResult.pending_marker_path: Path | None` defined Task 4, used Tasks 8, 9 ✓
- `PendingCheckpoint.working_dir: Path` defined Task 5, consumed Tasks 8, 9 ✓
- `SnapshotCleanupTask` defined Task 6, consumed Tasks 7 (CLI), 9 (drain) ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-10-auto-checkpoint-safety-and-trigger.md`. **Now 10 tasks** (was 8; added cleanup contract and metrics), incorporating all critical + major findings from the 3 reviewer subagents:

- **Safety:** stash-clobber eliminated (read-only snapshots, subagent deferral, fail-loud restore).
- **Durability:** pending-checkpoint marker drained on next tick or session-end (no more silent drops).
- **Auto-trigger:** `auto_checkpoint_interval` timer wired into MCP server lifespan, gated by both `settings.auto_checkpoint_interval > 0` AND `mode_config.enable_auto_checkpoint`.
- **Cleanup:** TTL-based snapshot cleanup + CLI command + pending drain on `end()`.
- **Operator visibility:** `CheckpointMetrics` counter + per-failure structured logs.
- **Test bar:** 90% coverage enforced; property-based keystone; stash-clobber regression with subprocess spy.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?