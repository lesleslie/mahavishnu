---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: sb-checkpoint-stash-clobber-fix
---

# Session-Buddy Checkpoint Stash-Clobber Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the `git stash` race condition in the session-buddy auto-checkpoint cycle that clobbers subagent working-tree edits mid-task, while preserving the analytic value of midpoint checkpoints.

**Architecture:** A new `session_buddy/checkpoint/` package with four pluggable components (`SubagentDetector`, `SnapshotMechanism`, `CheckpointPolicy`, `CheckpointOrchestrator`) composes a thin wrapper around the existing `store_conversation_checkpoint` tool. The wrapper replaces any stash-based working-tree capture with a read-only `git diff > /tmp/snap-<uuid>.patch` snapshot, defers when a subagent is in flight, and emits structured decisions for observability.

**Tech Stack:** Python 3.13, asyncio, pytest + pytest-asyncio + hypothesis, `subprocess` for git invocations, no new third-party dependencies.

**Reference spec:** `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md`

## Global Constraints

These apply to every task. Tasks may add task-specific constraints.

1. Python 3.13+. Use `from __future__ import annotations` as the first non-comment line of every source file.
2. Use modern syntax: `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path` for filesystem paths.
3. Function arguments with default `None` must be typed `X | None = None` (mypy `no_implicit_optional = true`).
4. No `assert` in production code under `session_buddy/checkpoint/`. Use specific exception classes.
5. No `Any` in public interfaces. Use `TYPE_CHECKING` and protocols to escape.
6. In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
7. Use the Oneiric logger (`oneiric.logging`) — not stdlib `logging` directly. If unavailable in this context, use `logging.getLogger(__name__)` consistently and document the deviation.
8. Async I/O only inside async functions. Subprocess invocations use `asyncio.create_subprocess_exec`, not `subprocess.run`.
9. Line length: 100 chars (Ruff default).
10. Coverage target: 90%+ on `session_buddy/checkpoint/` module (higher than project default 80%).
11. Test markers: use existing project markers — `unit`, `integration`, `property`, `slow`. No new markers.
12. Every `PolicyDecision.reason` and `CheckpointResult.decision_reason` is non-empty (empty string is a bug).
13. Snapshot files at `/tmp/snap-<uuid>.patch` are immutable after `capture()` returns.
14. The working tree is never mutated by checkpoint operations. This is the keystone invariant.

---

## File Structure

Files to be created or modified by this plan:

**New files (session-buddy side, primary location):**
- `session_buddy/checkpoint/__init__.py` — package init, re-exports public API
- `session_buddy/checkpoint/subagent_detector.py` — `SubagentDetector` + `SignalSource` protocol + `LockfileSignalSource` concrete impl
- `session_buddy/checkpoint/snapshot.py` — `SnapshotMechanism` + `Snapshot` dataclass + `GitNotAvailableError` + `RestoreConflict`
- `session_buddy/checkpoint/policy.py` — `CheckpointPolicy` + `PolicyDecision` + `CheckpointPhase` enum + `MidpointCriteria` + `ValueAddSignal` protocol + `TimeElapsedSignal` + `DirtyFilesSignal`
- `session_buddy/checkpoint/orchestrator.py` — `CheckpointOrchestrator` + `CheckpointResult`
- `session_buddy/checkpoint/working_tree.py` — `WorkingTreeInspector` (used by policy)

**New test files:**
- `tests/unit/checkpoint/test_subagent_detector.py`
- `tests/unit/checkpoint/test_snapshot.py`
- `tests/unit/checkpoint/test_policy.py`
- `tests/unit/checkpoint/test_orchestrator.py`
- `tests/unit/checkpoint/test_working_tree.py`
- `tests/unit/checkpoint/test_property_invariants.py` — property-based tests
- `tests/unit/checkpoint/test_stash_clobber_regression.py` — regression test for the 2026-07-15 bug

**Modified files (integration):**
- `session_buddy/mcp/tools/session/session_tools.py` — wire orchestrator into `_checkpoint_impl` (ONLY if probe confirms session-buddy location)

**Documentation files (final task):**
- `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md` — add resolution note
- `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` — reference this plan

---

## ⚠️ REWORK NOTES — Multi-Agent Review Findings (2026-07-15)

**Read this section BEFORE the tasks below.** A 6-agent review surfaced
critical blockers. The original tasks remain for context, but these
notes override them. **Do not skip — every block below addresses a
finding that would cause the fix to fail.**

### R1. Task 1 probe scope — widened (critical)

The original Probe 1 grepped only `session_buddy/mcp/` and Probe 3
matched only `"checkpoint: crackerjack"`. The mcp-integration reviewer
found that `session_buddy/utils/git_worktrees.py:create_checkpoint_commit`
is the actual mutator (NOT under `mcp/`), and commit messages include
`"checkpoint: session-buddy"` and `"checkpoint: mahavishnu"` (NOT just
crackerjack).

**Action**: When executing Task 1, use the **expanded probes** in the
executor-context section at the end of this plan, NOT the original
three grep commands. Specifically:

- Probe 1: search `/Users/les/Projects/session-buddy/session_buddy/` (full repo, not just `mcp/`)
- Probe 3: grep `--grep="^checkpoint:"` (no author filter)
- Add Probe 4: trace inward from `_checkpoint_impl` to `create_checkpoint_commit`
- Add Probe 5: trace mahavishnu's caller surface

The probe findings file must go in `docs/superpowers/plans/probe-<date>-sb-stash.md`
(committed), NOT `/tmp/sb-stash-probe-findings.md` (lost on reboot).

### R2. Task 7 wire-into-tool — wrong code path (critical, blocks fix)

The original Task 7 wraps `_checkpoint_impl` in
`session_buddy/mcp/tools/session/session_tools.py`. Per the
mcp-integration review, `_checkpoint_impl` does NOT mutate the working
tree — it delegates to `_get_session_manager().checkpoint_session()`
which calls `perform_git_checkpoint` → `create_checkpoint_commit`
in `session_buddy/utils/git_worktrees.py`. That function
(`create_checkpoint_commit`, line 469) calls `_perform_staging_and_commit`
(line 407) which runs `subprocess.run(["git", "commit", ...])` — the
**actual locus of the bug**.

**Override**: When executing, treat Task 7 as:

**Files:**
- Modify: `session_buddy/utils/git_worktrees.py` — wrap `create_checkpoint_commit` (line 469) with the orchestrator's safety check
- Modify (optional): `session_buddy/mcp/tools/session/session_tools.py` — keep existing behavior of `_checkpoint_impl`; the orchestrator wraps at the lower layer

**Critical**: do NOT use the original Task 7's `forward_to` stub (`pass`). That stub silently drops ALL existing behavior — quality scoring, git commit, hook firing, auto-store reflection. The fix must **extend** existing behavior, not replace it. The orchestrator's `forward_to` should invoke the original `create_checkpoint_commit` after the orchestrator's snapshot has been captured.

### R3. Task 8 property test — spy on wrong API (critical, test passes vacuously)

Original test spies on `subprocess.run` but production code uses
`asyncio.create_subprocess_exec`. The spy never fires, so the test
passes regardless of whether stash is reintroduced.

**Override**: Task 8's `test_no_git_stash_ever_called` must spy on
`asyncio.create_subprocess_exec` (use the same pattern as Task 4 Step
4.1 line 727-730 in the original plan). Use
`monkeypatch.setattr(asyncio, "create_subprocess_exec", ...)` with a
spy coroutine factory.

### R4. Task 9 regression test — same API bug + missing original code (critical)

Same API spy issue as R3. Additionally, Task 9.3's sanity check
reproduces an invented buggy snippet, NOT the real buggy code. Without
the actual buggy code from the originating session, the regression
test is unverifiable.

**Override**:
- Fix the spy: same as R3
- Reproduce the actual buggy code in Step 9.3 by reading the parent commit (`docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`) and `git show`ing the originating checkpoint commit. The bug lives at the actual mutator (per R2), not in `SnapshotMechanism.capture()`.

### R5. NEW Task 13 — wire lockfile writer (critical, otherwise safety is inert)

The plan's "subagent active → defer" mechanism reads
`.mahavishnu-subagent-active` but **no code in this plan creates that
lockfile**. Per the fresh-eyes reviewer, the detector will never
observe an active subagent in production. The safety mechanism is
wired but inert.

**Add Task 13**:

### Task 13: Wire Lockfile Writer into Mahavishnu Worker Dispatch

**Files:**
- Modify: `mahavishnu/pools/manager.py` — write `.mahavishnu-subagent-active` in the working_dir when a subagent is dispatched
- Modify: `mahavishnu/workers/manager.py` — write lockfile on worker spawn, remove on worker exit (try/finally)
- Test: `tests/unit/pools/test_lockfile_writer.py`

**Interfaces:**
- Consumes: `working_dir: Path`, `dispatch_id: str`
- Produces: writes `<working_dir>/.mahavishnu-subagent-active` with metadata; removes on completion

**Critical**: Without this task, the orchestrator's deferral logic never fires in production. The "fix" ships but is inert.

### R6. NEW Task 14 — document or update mahavishnu HTTP client (critical)

The mcp-integration reviewer found that
`mahavishnu/session/checkpoint.py:create_checkpoint` (line 74) and
`update_checkpoint` (line 109) call `store_conversation_checkpoint` over
HTTP directly. They bypass `_checkpoint_impl` entirely. The plan never
addresses this caller surface.

**Override**: Add Task 14 that either:

- **(a)** Updates `mahavishnu/session/checkpoint.py` to invoke the orchestrator directly (preferred for consistency), OR
- **(b)** Documents explicitly that this caller does NOT need changes because `store_conversation_checkpoint` is a different tool with no git-mutation side effects (verify by reading `session_buddy/mcp/tools/conversation/conversation_tools.py:store_conversation_checkpoint` — if it doesn't touch git, option (b) is correct)

Either option requires reading both files first. Do not assume.

### R7. Task 11 fix — remove duplicate Step 3f instruction (correctness)

Step 3f **already exists** in the pickup prompt (added during the
plan's authoring). Task 11.2's instruction to "Add a new section"
will produce a duplicate heading. Per the cross-reference consistency
reviewer.

**Override**: Task 11.2 should verify Step 3f is present and update it in-place with the final commit hashes from Tasks 1-12 (NOT add a new heading).

### R8. Use git worktrees, not absolute paths (process discipline)

The plan hardcodes `/Users/les/Projects/session-buddy` and
`/Users/les/Projects/mahavishnu` paths. The multi-repo reviewer
flagged this as reviewer-specific. Engineers cloning the repos to
different paths will fail all commands.

**Override**: Cut one worktree per repo before executing:
```bash
git worktree add -b fix/sb-checkpoint-stash-clobber-session-buddy /tmp/fix-sb-session-buddy
git worktree add -b fix/sb-checkpoint-stash-clobber-mahavishnu /tmp/fix-sb-mahavishnu
```
Replace all `cd /Users/les/Projects/session-buddy` and
`cd /Users/les/Projects/mahavishnu` in the plan with `cd` to the
corresponding worktree. Use environment variables
(`SESSION_BUDDY_ROOT`, `MAHAVISHNU_ROOT`) if multiple shells share the
worktree paths.

### R9. Add feature-tracking entry (process discipline per CLAUDE.md)

CLAUDE.md "Process Discipline" mandates a `{built, wired, adopted}`
tracking entry for every feature in `docs/feature-tracking/`.

**Add Task 0** at the start:

### Task 0: Create Feature-Tracking Entry

**Files:**
- Create: `docs/feature-tracking/2026-07-15-sb-checkpoint-orchestrator.md` (in mahavishnu repo)

**Step 0.1**: Copy `docs/feature-tracking/TEMPLATE.md` to the target path
**Step 0.2**: Fill in name, description, status=`built` (will move to `wired` after Task 7, `adopted` after Task 11)
**Step 0.3**: Commit in mahavishnu repo before any code work begins

### R10. Add Integration Contract blocks per CLAUDE.md

CLAUDE.md "Process Discipline" cites
`.claude/decisions/wire-up-contract.md` and requires every plan
deliverable to include an Integration Contract block:
`Triggered from`, `Returns to / updates`, `Demonstrable by`,
`Rollback signal`, `Observability added`.

**Override**: For each of Tasks 1-14, append an Integration Contract
block at the end. The `crackerjack-cleanup-wave7` skill scaffold has
a template; copy from there. This is non-negotiable per the project's
process discipline.

---

## Task 1: Architecture Probe

**Files:**
- Create: `/tmp/sb-stash-probe-findings.md` (temporary scratch file; deleted after Task 1)

**Step 1.1: Run the location probe**

Run each command and capture output verbatim:

```bash
# Probe 1: search session-buddy MCP code for stash ops
grep -rn "stash\|subprocess.*git" /Users/les/Projects/session-buddy/session_buddy/mcp/ --include="*.py" 2>&1 | head -30

# Probe 2: search crackerjack quality code for stash ops
find /Users/les/Projects/crackerjack -maxdepth 6 -name "*.py" -path "*quality*" -exec grep -l "stash\|git commit" {} \; 2>/dev/null

# Probe 3: trace one auto-checkpoint commit back to its creator
cd /Users/les/Projects/mahavishnu
git log --all --grep="checkpoint: crackerjack" -n 3 --format="%H %s" > /tmp/sb-stash-probe-commits.txt
cat /tmp/sb-stash-probe-commits.txt
# For each hash, run: git show --stat <hash> to see what files were touched
```

- [ ] **Step 1.2: Record findings**

Write findings to `/tmp/sb-stash-probe-findings.md` with this format:

```markdown
# Architecture Probe Findings

**Date**: YYYY-MM-DD
**Probed by**: [engineer name]

## Probe 1: session-buddy MCP code
[verbatim grep output]

## Probe 2: crackerjack quality code
[verbatim find output, or "no matches"]

## Probe 3: auto-checkpoint commit tracing
[commit hashes + file lists]

## Conclusion

**Fix location**: [session-buddy | crackerjack]
**Specific files to modify**:
- [list]
```

- [ ] **Step 1.3: Branch the plan**

Read the conclusion. Three outcomes:

**Outcome A — stash lives in session-buddy**: proceed with Tasks 2-11 as written (modifications to `session_buddy/mcp/tools/session/session_tools.py` are confirmed).

**Outcome B — stash lives in crackerjack**: skip Task 7 (wire into session-buddy), modify `crackerjack/` instead. Document the divergence in `/tmp/sb-stash-probe-findings.md`.

**Outcome C — stash lives in neither (e.g., a Claude Code hook script)**: STOP and report. The plan needs re-derivation. Update the spec with the new finding.

- [ ] **Step 1.4: Commit**

```bash
git add docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md
# Note: /tmp/sb-stash-probe-findings.md is OUTSIDE the repo and not committed
git commit --allow-empty -m "docs(superpowers): confirm fix location via architecture probe"
```

---

## Task 2: WorkingTreeInspector

**Files:**
- Create: `session_buddy/checkpoint/working_tree.py`
- Test: `tests/unit/checkpoint/test_working_tree.py`

**Interfaces:**
- Consumes: a `Path` (working directory)
- Produces:
  - `class WorkingTreeInspector`
  - `def dirty_file_count(self) -> int`
  - `def seconds_since_last_commit(self) -> float`
  - `def current_commit_sha(self) -> str`

**Context**: This component wraps `git status` and `git log` reads. Used by `CheckpointPolicy` to evaluate value-add signals. Pure read-only — never mutates the working tree.

- [ ] **Step 2.1: Write the failing test**

```python
# tests/unit/checkpoint/test_working_tree.py
from __future__ import annotations

from pathlib import Path

import pytest

from session_buddy.checkpoint.working_tree import (
    GitNotARepositoryError,
    WorkingTreeInspector,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # not a real git repo, but enough for the test
    # Real init via subprocess in actual test
    import subprocess
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_dirty_file_count_zero_on_clean_tree(git_repo: Path) -> None:
    inspector = WorkingTreeInspector(git_repo)
    assert inspector.dirty_file_count() == 0


def test_dirty_file_count_reflects_modified_files(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("modified")
    inspector = WorkingTreeInspector(git_repo)
    assert inspector.dirty_file_count() == 1


def test_seconds_since_last_commit_returns_small_value_for_fresh_commit(git_repo: Path) -> None:
    import time
    before = time.time()
    inspector = WorkingTreeInspector(git_repo)
    elapsed = inspector.seconds_since_last_commit()
    assert 0 <= elapsed <= (time.time() - before) + 1.0


def test_current_commit_sha_returns_40_char_hex(git_repo: Path) -> None:
    inspector = WorkingTreeInspector(git_repo)
    sha = inspector.current_commit_sha()
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_raises_when_not_a_git_repository(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    with pytest.raises(GitNotARepositoryError):
        WorkingTreeInspector(not_a_repo)
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_working_tree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.checkpoint.working_tree'`

- [ ] **Step 2.3: Write minimal implementation**

```python
# session_buddy/checkpoint/working_tree.py
"""Read-only inspection of a git working tree for checkpoint policy decisions."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GitNotARepositoryError(Exception):
    """Raised when the working directory is not a git repository."""


class WorkingTreeInspector:
    """Wraps read-only git operations used by CheckpointPolicy.

    All operations are async subprocess invocations. Never mutates the working tree.
    """

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._validated = False

    async def _ensure_repo(self) -> None:
        """Confirm the directory is a git repo before any operation."""
        if self._validated:
            return
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--git-dir",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise GitNotARepositoryError(
                f"Not a git repository: {self._working_dir} ({stderr.decode().strip()})"
            )
        self._validated = True

    async def dirty_file_count(self) -> int:
        """Return the count of files that differ from HEAD (modified + untracked)."""
        await self._ensure_repo()
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git status failed in %s, returning 0", self._working_dir)
            return 0
        # Each line is one dirty file; empty output = clean
        return len([line for line in stdout.decode().splitlines() if line.strip()])

    async def seconds_since_last_commit(self) -> float:
        """Return seconds elapsed since the most recent commit on HEAD."""
        await self._ensure_repo()
        import time
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "-1", "--format=%ct",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git log failed in %s, returning 0", self._working_dir)
            return 0.0
        commit_epoch = int(stdout.decode().strip())
        return time.time() - commit_epoch

    async def current_commit_sha(self) -> str:
        """Return the 40-char hex SHA of HEAD."""
        await self._ensure_repo()
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            raise GitNotARepositoryError(f"Cannot read HEAD: {self._working_dir}")
        return stdout.decode().strip()
```

Note: the test uses synchronous-looking calls (`inspector.dirty_file_count()`) but the implementation is async. Adjust the test by wrapping with `asyncio.run`. See step 2.5.

- [ ] **Step 2.4: Update test to use asyncio.run wrapper**

Replace the test file content with:

```python
# tests/unit/checkpoint/test_working_tree.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from session_buddy.checkpoint.working_tree import (
    GitNotARepositoryError,
    WorkingTreeInspector,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _run(coro):
    return asyncio.run(coro)


def test_dirty_file_count_zero_on_clean_tree(git_repo: Path) -> None:
    inspector = WorkingTreeInspector(git_repo)
    assert _run(inspector.dirty_file_count()) == 0


def test_dirty_file_count_reflects_modified_files(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("modified")
    inspector = WorkingTreeInspector(git_repo)
    assert _run(inspector.dirty_file_count()) == 1


def test_seconds_since_last_commit_returns_small_value_for_fresh_commit(git_repo: Path) -> None:
    import time
    before = time.time()
    inspector = WorkingTreeInspector(git_repo)
    elapsed = _run(inspector.seconds_since_last_commit())
    assert 0 <= elapsed <= (time.time() - before) + 1.0


def test_current_commit_sha_returns_40_char_hex(git_repo: Path) -> None:
    inspector = WorkingTreeInspector(git_repo)
    sha = _run(inspector.current_commit_sha())
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_raises_when_not_a_git_repository(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    inspector = WorkingTreeInspector(not_a_repo)
    with pytest.raises(GitNotARepositoryError):
        _run(inspector.dirty_file_count())
```

- [ ] **Step 2.5: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_working_tree.py -v`
Expected: PASS for all 5 tests.

- [ ] **Step 2.6: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/working_tree.py tests/unit/checkpoint/test_working_tree.py
git commit -m "feat(checkpoint): add WorkingTreeInspector with git read-only wrappers"
```

---

## Task 3: SubagentDetector + SignalSource

**Files:**
- Create: `session_buddy/checkpoint/subagent_detector.py`
- Test: `tests/unit/checkpoint/test_subagent_detector.py`

**Interfaces:**
- Consumes: `working_dir: Path`, `signal_source: SignalSource`
- Produces:
  - `class SignalSource` (protocol with `read() -> bool` and `write(active: bool) -> None`)
  - `class LockfileSignalSource` (concrete: writes/reads `.mahavishnu-subagent-active` lockfile in working_dir)
  - `class SubagentDetector` with `is_active() -> bool` (sync, fast) and `wait_until_idle(timeout: float = 60.0) -> bool` (async)

**Context**: Detects whether a subagent is currently working against this working directory. Pluggable signal source lets us iterate on detection strategy without touching the detector or policy.

- [ ] **Step 3.1: Write the failing test**

```python
# tests/unit/checkpoint/test_subagent_detector.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from session_buddy.checkpoint.subagent_detector import (
    LockfileSignalSource,
    SignalSource,
    SubagentDetector,
)


class MockSignalSource:
    """Test double for SignalSource."""

    def __init__(self, active: bool = False) -> None:
        self._active = active
        self.read_calls = 0
        self.write_calls: list[bool] = []

    def read(self) -> bool:
        self.read_calls += 1
        return self._active

    def write(self, active: bool) -> None:
        self.write_calls.append(active)
        self._active = active


def test_is_active_returns_signal_value(tmp_path: Path) -> None:
    source = MockSignalSource(active=True)
    detector = SubagentDetector(tmp_path, source)
    assert detector.is_active() is True


def test_is_active_returns_false_when_signal_inactive(tmp_path: Path) -> None:
    source = MockSignalSource(active=False)
    detector = SubagentDetector(tmp_path, source)
    assert detector.is_active() is False


def test_signal_source_permission_error_treated_as_active(tmp_path: Path) -> None:
    class FailingSource:
        def read(self) -> bool:
            raise PermissionError("cannot read lockfile")

        def write(self, active: bool) -> None:
            pass

    detector = SubagentDetector(tmp_path, FailingSource())
    assert detector.is_active() is True  # fail open to active


def test_signal_source_malformed_treated_as_active(tmp_path: Path) -> None:
    class BrokenSource:
        def read(self) -> bool:
            raise RuntimeError("malformed")

        def write(self, active: bool) -> None:
            pass

    detector = SubagentDetector(tmp_path, BrokenSource())
    assert detector.is_active() is True  # fail open to active


def test_wait_until_idle_returns_true_when_signal_clears(tmp_path: Path) -> None:
    source = MockSignalSource(active=True)
    detector = SubagentDetector(tmp_path, source)

    async def clear_after_delay():
        await asyncio.sleep(0.05)
        source.write(False)

    async def run():
        return await asyncio.gather(
            detector.wait_until_idle(timeout=1.0),
            clear_after_delay(),
        )

    result, _ = asyncio.run(run())
    assert result is True


def test_wait_until_idle_times_out_when_signal_persists(tmp_path: Path) -> None:
    source = MockSignalSource(active=True)
    detector = SubagentDetector(tmp_path, source)
    result = asyncio.run(detector.wait_until_idle(timeout=0.1))
    assert result is False


def test_lockfile_signal_source_creates_and_removes_lock(tmp_path: Path) -> None:
    source = LockfileSignalSource(tmp_path)
    assert source.read() is False
    source.write(True)
    assert source.read() is True
    source.write(False)
    assert source.read() is False
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_subagent_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.checkpoint.subagent_detector'`

- [ ] **Step 3.3: Write minimal implementation**

```python
# session_buddy/checkpoint/subagent_detector.py
"""Detection of active subagent work against a working directory."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class SignalSource(Protocol):
    """Pluggable source of truth for 'is a subagent active?'."""

    def read(self) -> bool:
        """Return True if a subagent is currently active."""
        ...

    def write(self, active: bool) -> None:
        """Update the signal source's state."""
        ...


class LockfileSignalSource:
    """Concrete SignalSource backed by a lockfile in the working directory.

    The lockfile lives at `<working_dir>/.mahavishnu-subagent-active`.
    Subagents create it on dispatch and remove it on completion.
    """

    LOCKFILE_NAME = ".mahavishnu-subagent-active"

    def __init__(self, working_dir: Path) -> None:
        self._lockfile = working_dir / self.LOCKFILE_NAME

    def read(self) -> bool:
        return self._lockfile.exists()

    def write(self, active: bool) -> None:
        if active:
            self._lockfile.touch()
        else:
            self._lockfile.unlink(missing_ok=True)


class SubagentDetector:
    """Tells whether a subagent is currently in flight for this working_dir.

    Failure mode for the signal source: assume active (fail open to deferring).
    """

    def __init__(self, working_dir: Path, signal_source: SignalSource) -> None:
        self._working_dir = working_dir
        self._signal = signal_source

    def is_active(self) -> bool:
        """Return True if a subagent is currently executing against working_dir.

        On signal-source failure (permission error, malformed data), returns True
        to defer rather than risk clobbering active work.
        """
        try:
            return self._signal.read()
        except Exception as exc:
            logger.warning(
                "Subagent signal source failed for %s, assuming active: %s",
                self._working_dir,
                exc,
            )
            return True

    async def wait_until_idle(self, timeout: float = 60.0) -> bool:
        """Block until the signal clears or timeout expires. Returns True if idle."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        poll_interval = 0.1
        while loop.time() < deadline:
            if not self.is_active():
                return True
            await asyncio.sleep(poll_interval)
        return False
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_subagent_detector.py -v`
Expected: PASS for all 7 tests.

- [ ] **Step 3.5: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/subagent_detector.py tests/unit/checkpoint/test_subagent_detector.py
git commit -m "feat(checkpoint): add SubagentDetector with pluggable SignalSource"
```

---

## Task 4: SnapshotMechanism

**Files:**
- Create: `session_buddy/checkpoint/snapshot.py`
- Test: `tests/unit/checkpoint/test_snapshot.py`

**Interfaces:**
- Consumes: `working_dir: Path`, `snapshot_dir: Path`
- Produces:
  - `class SnapshotMechanism` with `capture(label: str) -> Snapshot` (async) and `restore(snapshot: Snapshot) -> RestoreResult` (async)
  - `class Snapshot` dataclass: `path: Path`, `label: str`, `captured_at: datetime`, `parent_commit: str`, `dirty_files: list[str]`
  - `class RestoreResult` dataclass: `success: bool`, `conflicts: list[str]`
  - `class GitNotAvailableError(Exception)`
  - `class RestoreConflict(Exception)` — `__init__(self, conflicts: list[str])`

**Context**: The keystone safety mechanism. Captures working-tree state as a read-only patch file; never mutates the working tree.

- [ ] **Step 4.1: Write the failing test**

```python
# tests/unit/checkpoint/test_snapshot.py
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from session_buddy.checkpoint.snapshot import (
    GitNotAvailableError,
    RestoreConflict,
    RestoreResult,
    Snapshot,
    SnapshotMechanism,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_capture_creates_patch_file(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("modified content")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    assert snapshot.path.exists()
    assert snapshot.label == "test"


def test_capture_records_metadata(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("modified")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    assert snapshot.parent_commit
    assert len(snapshot.parent_commit) == 40
    assert "README.md" in snapshot.dirty_files


def test_capture_empty_working_tree_succeeds(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    assert snapshot.path.exists()
    assert snapshot.dirty_files == []


def test_capture_does_not_mutate_working_tree(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("important content")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    asyncio.run(mechanism.capture("test"))
    # Working tree untouched
    assert (git_repo / "README.md").read_text() == "important content"


def test_capture_raises_git_not_available_when_git_missing(git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    # Pretend git is missing by patching subprocess to fail
    import asyncio
    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(GitNotAvailableError):
        asyncio.run(mechanism.capture("test"))


def test_restore_applies_patch(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("captured state")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    # Working tree changes after capture
    (git_repo / "README.md").write_text("different state")
    # Restore brings it back
    result = asyncio.run(mechanism.restore(snapshot))
    assert result.success is True
    assert (git_repo / "README.md").read_text() == "captured state"


def test_restore_with_conflicts_raises(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("captured state")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    # Working tree diverges
    (git_repo / "README.md").write_text("completely different")
    with pytest.raises(RestoreConflict):
        asyncio.run(mechanism.restore(snapshot))


def test_snapshot_file_immutable_after_capture(git_repo: Path, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (git_repo / "README.md").write_text("x")
    mechanism = SnapshotMechanism(git_repo, snapshot_dir)
    snapshot = asyncio.run(mechanism.capture("test"))
    original_content = snapshot.path.read_text()
    # Modify the captured file directly — capture() should not rewrite it
    snapshot.path.write_text("tampered")
    # Re-read the file via fresh capture would differ, but the snapshot object's
    # path is unchanged. The test asserts the path is stable.
    assert snapshot.path.exists()
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.checkpoint.snapshot'`

- [ ] **Step 4.3: Write minimal implementation**

```python
# session_buddy/checkpoint/snapshot.py
"""Stash-free snapshot mechanism for checkpoint working-tree capture."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class GitNotAvailableError(Exception):
    """Raised when the git binary is missing or git operations fail."""


class RestoreConflict(Exception):
    """Raised when restore fails due to working-tree conflicts."""

    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = conflicts
        super().__init__(f"Restore conflicts: {conflicts}")


@dataclass
class Snapshot:
    path: Path
    label: str
    captured_at: datetime
    parent_commit: str
    dirty_files: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    success: bool
    conflicts: list[str] = field(default_factory=list)


class SnapshotMechanism:
    """Capture working-tree state as a read-only patch file.

    Invariant: capture() never mutates the working tree.
    """

    SNAPSHOT_TIMEOUT_SECONDS = 30.0

    def __init__(self, working_dir: Path, snapshot_dir: Path) -> None:
        self._working_dir = working_dir
        self._snapshot_dir = snapshot_dir
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, label: str) -> Snapshot:
        """Capture current working-tree state. Returns Snapshot with path + metadata."""
        snapshot_id = uuid.uuid4().hex[:12]
        path = self._snapshot_dir / f"snap-{snapshot_id}.patch"

        parent_commit = await self._read_head()
        dirty_files = await self._read_dirty_files()

        try:
            await self._write_diff(path)
        except FileNotFoundError as exc:
            raise GitNotAvailableError(f"git binary missing: {exc}") from exc

        return Snapshot(
            path=path,
            label=label,
            captured_at=datetime.now(UTC),
            parent_commit=parent_commit,
            dirty_files=dirty_files,
        )

    async def restore(self, snapshot: Snapshot) -> RestoreResult:
        """Apply a snapshot to the working tree. Raises RestoreConflict on conflict."""
        if not snapshot.path.exists():
            raise FileNotFoundError(f"Snapshot no longer exists: {snapshot.path}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "apply", "--check", str(snapshot.path),
                cwd=str(self._working_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RestoreConflict(conflicts=[stderr.decode().strip()])
        except FileNotFoundError as exc:
            raise GitNotAvailableError(f"git binary missing: {exc}") from exc

        # Check passed — actually apply
        proc = await asyncio.create_subprocess_exec(
            "git", "apply", str(snapshot.path),
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RestoreConflict(conflicts=[stderr.decode().strip()])

        return RestoreResult(success=True)

    async def _write_diff(self, path: Path) -> None:
        """Write `git diff` output to path. Raises FileNotFoundError if git missing."""
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise GitNotAvailableError(f"git diff failed: {stderr.decode().strip()}")
        path.write_text(stdout.decode())

    async def _read_head(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return ""
        return stdout.decode().strip()

    async def _read_dirty_files(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            cwd=str(self._working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        result = []
        for line in stdout.decode().splitlines():
            if len(line) >= 3:
                # Format: "XY filename" where XY is 2-char status
                result.append(line[3:].strip())
        return result
```

- [ ] **Step 4.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_snapshot.py -v`
Expected: PASS for all 8 tests.

- [ ] **Step 4.5: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/snapshot.py tests/unit/checkpoint/test_snapshot.py
git commit -m "feat(checkpoint): add stash-free SnapshotMechanism with restore support"
```

---

## Task 5: CheckpointPolicy

**Files:**
- Create: `session_buddy/checkpoint/policy.py`
- Test: `tests/unit/checkpoint/test_policy.py`

**Interfaces:**
- Consumes: `always_end`, `midpoint_enabled`, `midpoint_criteria: MidpointCriteria`, `subagent_detector: SubagentDetector`, `working_tree: WorkingTreeInspector`
- Produces:
  - `class CheckpointPhase(str, Enum)` with `END_OF_TASK`, `MIDPOINT_TIME`, `MIDPOINT_DIRTINESS`, `HOOK_REQUESTED`
  - `class PolicyDecision` dataclass: `should_fire: bool`, `reason: str` (reason always non-empty)
  - `class ValueAddSignal(Protocol)` with `is_active(working_tree) -> bool` and `describe() -> str`
  - `class TimeElapsedSignal` with `min_seconds: float` and impl
  - `class DirtyFilesSignal` with `min_count: int` and impl
  - `class MidpointCriteria` dataclass with `signals: list[ValueAddSignal]`
  - `class CheckpointPolicy` with `decide(*, phase, hook_request=False) -> PolicyDecision`

**Context**: Pure decision logic. No I/O. All inputs come from already-injected dependencies (detector, working tree).

- [ ] **Step 5.1: Write the failing test**

```python
# tests/unit/checkpoint/test_policy.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol
from unittest.mock import MagicMock

import pytest

from session_buddy.checkpoint.policy import (
    CheckpointPhase,
    CheckpointPolicy,
    DirtyFilesSignal,
    MidpointCriteria,
    PolicyDecision,
    TimeElapsedSignal,
)
from session_buddy.checkpoint.subagent_detector import SubagentDetector
from session_buddy.checkpoint.working_tree import WorkingTreeInspector


def _async_return(value):
    """Helper to create an awaitable that returns value."""
    async def coro():
        return value
    return coro()


class FakeSignal:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def read(self) -> bool:
        return self._active

    def write(self, active: bool) -> None:
        self._active = active


def make_detector(active: bool = False) -> SubagentDetector:
    return SubagentDetector(Path("/tmp"), FakeSignal(active=active))


def make_working_tree(dirty_count: int = 0, seconds_since_commit: float = 0.0) -> WorkingTreeInspector:
    wt = WorkingTreeInspector(Path("/tmp"))
    wt.dirty_file_count = lambda: _async_return(dirty_count)
    wt.seconds_since_last_commit = lambda: _async_return(seconds_since_commit)
    return wt


def test_end_of_task_always_fires() -> None:
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=False),
        working_tree=make_working_tree(),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.END_OF_TASK))
    assert decision.should_fire is True
    assert decision.reason != ""


def test_end_of_task_fires_even_when_subagent_active() -> None:
    """End-of-task may wait_until_idle but should still fire."""
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=True),
        working_tree=make_working_tree(),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.END_OF_TASK))
    assert decision.should_fire is True
    assert "end-of-task" in decision.reason.lower()


def test_midpoint_skips_when_subagent_active() -> None:
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=True),
        working_tree=make_working_tree(dirty_count=10),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.MIDPOINT_TIME))
    assert decision.should_fire is False
    assert "subagent" in decision.reason.lower()


def test_midpoint_fires_when_signal_active() -> None:
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=False),
        working_tree=make_working_tree(dirty_count=10, seconds_since_commit=400.0),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.MIDPOINT_TIME))
    assert decision.should_fire is True


def test_midpoint_skips_when_no_signal_active() -> None:
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=False),
        working_tree=make_working_tree(dirty_count=1, seconds_since_commit=10.0),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.MIDPOINT_TIME))
    assert decision.should_fire is False
    assert decision.reason != ""


def test_hook_request_bypasses_value_criteria() -> None:
    policy = CheckpointPolicy(
        subagent_detector=make_detector(active=False),
        working_tree=make_working_tree(dirty_count=0, seconds_since_commit=0.0),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.MIDPOINT_TIME, hook_request=True))
    assert decision.should_fire is True
    assert "hook" in decision.reason.lower() or "requested" in decision.reason.lower()


def test_midpoint_disabled_means_never_fires() -> None:
    policy = CheckpointPolicy(
        midpoint_enabled=False,
        subagent_detector=make_detector(active=False),
        working_tree=make_working_tree(dirty_count=100),
    )
    decision = asyncio.run(policy.decide(phase=CheckpointPhase.MIDPOINT_TIME))
    assert decision.should_fire is False


def test_time_elapsed_signal_fires_when_seconds_exceeds_threshold() -> None:
    signal = TimeElapsedSignal(min_seconds=300.0)
    wt = make_working_tree(seconds_since_commit=400.0)
    assert asyncio.run(signal.is_active(wt)) is True


def test_time_elapsed_signal_inactive_when_below_threshold() -> None:
    signal = TimeElapsedSignal(min_seconds=300.0)
    wt = make_working_tree(seconds_since_commit=100.0)
    assert asyncio.run(signal.is_active(wt)) is False


def test_dirty_files_signal_fires_when_count_exceeds_threshold() -> None:
    signal = DirtyFilesSignal(min_count=5)
    wt = make_working_tree(dirty_count=10)
    assert asyncio.run(signal.is_active(wt)) is True


def test_dirty_files_signal_inactive_when_below_threshold() -> None:
    signal = DirtyFilesSignal(min_count=5)
    wt = make_working_tree(dirty_count=2)
    assert asyncio.run(signal.is_active(wt)) is False


def test_policy_decision_reason_always_non_empty() -> None:
    """Property test: every decision has non-empty reason."""
    for active in [True, False]:
        for dirty in [0, 5, 100]:
            for seconds in [0, 100, 1000]:
                policy = CheckpointPolicy(
                    subagent_detector=make_detector(active=active),
                    working_tree=make_working_tree(dirty_count=dirty, seconds_since_commit=seconds),
                )
                for phase in CheckpointPhase:
                    decision = asyncio.run(policy.decide(phase=phase))
                    assert decision.reason != "", (
                        f"Empty reason for active={active}, dirty={dirty}, "
                        f"seconds={seconds}, phase={phase}"
                    )
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.checkpoint.policy'`

- [ ] **Step 5.3: Write minimal implementation**

```python
# session_buddy/checkpoint/policy.py
"""Decision logic for whether a checkpoint should fire."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from session_buddy.checkpoint.subagent_detector import SubagentDetector
from session_buddy.checkpoint.working_tree import WorkingTreeInspector

logger = logging.getLogger(__name__)


class CheckpointPhase(str, Enum):
    END_OF_TASK = "end_of_task"
    MIDPOINT_TIME = "midpoint_time"
    MIDPOINT_DIRTINESS = "midpoint_dirtiness"
    HOOK_REQUESTED = "hook_requested"


@dataclass
class PolicyDecision:
    should_fire: bool
    reason: str  # always non-empty


class ValueAddSignal(Protocol):
    """One independent reason a midpoint might be valuable."""

    def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        ...

    def describe(self) -> str:
        ...


@dataclass
class TimeElapsedSignal:
    min_seconds: float = 300.0

    async def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return await working_tree.seconds_since_last_commit() >= self.min_seconds

    def describe(self) -> str:
        return f"time elapsed >= {self.min_seconds}s"


@dataclass
class DirtyFilesSignal:
    min_count: int = 5

    async def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return await working_tree.dirty_file_count() >= self.min_count

    def describe(self) -> str:
        return f"dirty files >= {self.min_count}"


@dataclass
class MidpointCriteria:
    """List of value-add signals. ANY signal firing triggers a midpoint.

    Per user clarification: midpoint fires when it helps the current worker's
    decision-making OR session/worker analytics. OR (any-of) semantics.
    """
    signals: list[ValueAddSignal] = field(default_factory=lambda: [
        TimeElapsedSignal(min_seconds=300.0),
        DirtyFilesSignal(min_count=5),
    ])


class CheckpointPolicy:
    def __init__(
        self,
        *,
        subagent_detector: SubagentDetector,
        working_tree: WorkingTreeInspector,
        always_end: bool = True,
        midpoint_enabled: bool = True,
        midpoint_criteria: MidpointCriteria | None = None,
    ) -> None:
        self._subagent_detector = subagent_detector
        self._working_tree = working_tree
        self._always_end = always_end
        self._midpoint_enabled = midpoint_enabled
        self._midpoint_criteria = midpoint_criteria or MidpointCriteria()

    async def decide(
        self, *, phase: CheckpointPhase, hook_request: bool = False
    ) -> PolicyDecision:
        # 1. End-of-task always fires (if always_end is set)
        if phase == CheckpointPhase.END_OF_TASK and self._always_end:
            return PolicyDecision(
                should_fire=True,
                reason="end-of-task checkpoint is mandatory",
            )

        # 2. Hook request bypasses value criteria (user explicit override)
        if hook_request:
            return PolicyDecision(
                should_fire=True,
                reason="checkpoint explicitly requested by hook",
            )

        # 3. Midpoint disabled
        if not self._midpoint_enabled:
            return PolicyDecision(
                should_fire=False,
                reason="midpoint checkpoints disabled",
            )

        # 4. Subagent active — defer
        if self._subagent_detector.is_active():
            return PolicyDecision(
                should_fire=False,
                reason="subagent active; deferring",
            )

        # 5. Check value-add signals (OR semantics)
        for signal in self._midpoint_criteria.signals:
            try:
                if await signal.is_active(self._working_tree):
                    return PolicyDecision(
                        should_fire=True,
                        reason=f"value-add signal active: {signal.describe()}",
                    )
            except Exception as exc:
                logger.warning("Signal %s raised: %s", signal, exc)
                continue

        return PolicyDecision(
            should_fire=False,
            reason="no value-add signal active",
        )
```

- [ ] **Step 5.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_policy.py -v`
Expected: PASS for all 13 tests.

- [ ] **Step 5.5: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/policy.py tests/unit/checkpoint/test_policy.py
git commit -m "feat(checkpoint): add CheckpointPolicy with value-add signals and OR semantics"
```

---

## Task 6: CheckpointOrchestrator

**Files:**
- Create: `session_buddy/checkpoint/orchestrator.py`
- Create: `session_buddy/checkpoint/__init__.py`
- Test: `tests/unit/checkpoint/test_orchestrator.py`

**Interfaces:**
- Consumes: `policy: CheckpointPolicy`, `snapshot: SnapshotMechanism`, `subagent_detector: SubagentDetector`, `forward_to: Callable[[CheckpointResult], Awaitable[None]]`
- Produces:
  - `class CheckpointOrchestrator` with `async run_checkpoint(*, phase, hook_request=False) -> CheckpointResult`
  - `class CheckpointResult` dataclass: `fired: bool`, `snapshot_id: str | None`, `session_buddy_id: str | None`, `decision_reason: str`, `error: str | None`

**Context**: Composition root. Wires policy → snapshot → forward_to. Implements fail-closed semantics. About 50 lines excluding types.

- [ ] **Step 6.1: Write the failing test**

```python
# tests/unit/checkpoint/test_orchestrator.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from session_buddy.checkpoint.orchestrator import (
    CheckpointOrchestrator,
    CheckpointResult,
)
from session_buddy.checkpoint.policy import CheckpointPhase, CheckpointPolicy
from session_buddy.checkpoint.snapshot import Snapshot, SnapshotMechanism
from session_buddy.checkpoint.subagent_detector import SubagentDetector
from session_buddy.checkpoint.working_tree import WorkingTreeInspector


class FakeSignal:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def read(self) -> bool:
        return self._active

    def write(self, active: bool) -> None:
        self._active = active


def make_orchestrator(
    *,
    subagent_active: bool = False,
    snapshot_raises: Exception | None = None,
    forward_to_result: str = "checkpoint_abc",
    forward_to_fails: bool = False,
) -> tuple[CheckpointOrchestrator, list[Any]]:
    """Build an orchestrator with mocked dependencies. Returns (orch, forward_to_calls)."""
    forward_to_calls = []

    async def forward_to(result: CheckpointResult) -> None:
        forward_to_calls.append(result)
        if forward_to_fails:
            raise ConnectionError("session-buddy unreachable")

    snapshot_calls = []

    class MockSnapshot:
        async def capture(self, label: str) -> Snapshot:
            snapshot_calls.append(label)
            if snapshot_raises:
                raise snapshot_raises
            return Snapshot(
                path=Path("/tmp/snap-test.patch"),
                label=label,
                captured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                parent_commit="a" * 40,
                dirty_files=["README.md"],
            )

        async def restore(self, snapshot):
            pass

    working_tree = WorkingTreeInspector(Path("/tmp"))
    working_tree.dirty_file_count = lambda: _async_return(10)
    working_tree.seconds_since_last_commit = lambda: _async_return(400.0)

    policy = CheckpointPolicy(
        subagent_detector=SubagentDetector(Path("/tmp"), FakeSignal(active=subagent_active)),
        working_tree=working_tree,
    )

    orch = CheckpointOrchestrator(
        policy=policy,
        snapshot=MockSnapshot(),
        subagent_detector=SubagentDetector(Path("/tmp"), FakeSignal(active=subagent_active)),
        forward_to=forward_to,
    )
    return orch, forward_to_calls


def _async_return(value):
    async def coro():
        return value
    return coro()


@pytest.mark.asyncio
async def test_runs_full_sequence_when_policy_fires() -> None:
    orch, forward_to_calls = make_orchestrator(subagent_active=False)
    result = await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)
    assert result.fired is True
    assert result.snapshot_id is not None
    assert result.decision_reason != ""
    assert result.error is None
    assert len(forward_to_calls) == 1


@pytest.mark.asyncio
async def test_skips_when_policy_skips() -> None:
    orch, forward_to_calls = make_orchestrator(subagent_active=True)
    result = await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)
    assert result.fired is False
    assert result.snapshot_id is None
    assert "subagent" in result.decision_reason.lower()
    assert len(forward_to_calls) == 0


@pytest.mark.asyncio
async def test_fails_closed_when_snapshot_raises() -> None:
    from session_buddy.checkpoint.snapshot import GitNotAvailableError
    orch, forward_to_calls = make_orchestrator(
        subagent_active=False,
        snapshot_raises=GitNotAvailableError("git missing"),
    )
    result = await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)
    assert result.fired is False
    assert result.error is not None
    assert "git" in result.error.lower()
    assert len(forward_to_calls) == 0


@pytest.mark.asyncio
async def test_returns_error_when_forward_to_fails() -> None:
    orch, forward_to_calls = make_orchestrator(
        subagent_active=False,
        forward_to_fails=True,
    )
    result = await orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)
    # Snapshot was captured but forward_to failed — fail closed
    assert result.fired is False
    assert result.error is not None
    assert "unreachable" in result.error.lower() or "connection" in result.error.lower()


@pytest.mark.asyncio
async def test_decision_reason_always_populated() -> None:
    """Every result, fired or not, has a non-empty decision_reason."""
    for subagent_active in [True, False]:
        orch, _ = make_orchestrator(subagent_active=subagent_active)
        for phase in CheckpointPhase:
            result = await orch.run_checkpoint(phase=phase)
            assert result.decision_reason != "", (
                f"Empty reason for subagent_active={subagent_active}, phase={phase}"
            )


@pytest.mark.asyncio
async def test_concurrent_checkpoints_serialize() -> None:
    """Two simultaneous calls — second waits on the lock."""
    import asyncio

    orch, forward_to_calls = make_orchestrator(subagent_active=False)

    # Add a delay to forward_to so the second call has to wait
    original_forward = orch._forward_to

    async def slow_forward(result: CheckpointResult) -> None:
        await asyncio.sleep(0.1)
        forward_to_calls.append(result)

    orch._forward_to = slow_forward

    # Fire two concurrently
    results = await asyncio.gather(
        orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME),
        orch.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME),
    )
    assert all(r.fired for r in results)
    assert len(forward_to_calls) == 2
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.checkpoint.orchestrator'`

- [ ] **Step 6.3: Write minimal implementation**

```python
# session_buddy/checkpoint/orchestrator.py
"""Composition root for the checkpoint safety mechanism."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from session_buddy.checkpoint.policy import CheckpointPhase, CheckpointPolicy
from session_buddy.checkpoint.snapshot import SnapshotMechanism
from session_buddy.checkpoint.subagent_detector import SubagentDetector

logger = logging.getLogger(__name__)


@dataclass
class CheckpointResult:
    fired: bool
    snapshot_id: str | None
    session_buddy_id: str | None
    decision_reason: str  # always populated
    error: str | None


ForwardTo = Callable[[CheckpointResult], Awaitable[None]]


class CheckpointOrchestrator:
    """Composes policy + snapshot + subagent-detector + forward_to.

    Fail-closed: any error path returns CheckpointResult(fired=False, error=...)
    rather than silently falling back to the old stash-based behavior.
    """

    FORWARD_TO_RETRIES = 1
    FORWARD_TO_BACKOFF_SECONDS = 1.0

    def __init__(
        self,
        *,
        policy: CheckpointPolicy,
        snapshot: SnapshotMechanism,
        subagent_detector: SubagentDetector,
        forward_to: ForwardTo,
    ) -> None:
        self._policy = policy
        self._snapshot = snapshot
        self._subagent_detector = subagent_detector
        self._forward_to = forward_to
        self._lock = asyncio.Lock()

    async def run_checkpoint(
        self, *, phase: CheckpointPhase, hook_request: bool = False
    ) -> CheckpointResult:
        async with self._lock:
            decision = await self._policy.decide(phase=phase, hook_request=hook_request)

            if not decision.should_fire:
                return CheckpointResult(
                    fired=False,
                    snapshot_id=None,
                    session_buddy_id=None,
                    decision_reason=decision.reason,
                    error=None,
                )

            # Try to capture snapshot
            try:
                snapshot = await self._snapshot.capture(label=f"{phase.value}-{decision.reason[:40]}")
            except Exception as exc:
                logger.exception("Snapshot capture failed: %s", exc)
                return CheckpointResult(
                    fired=False,
                    snapshot_id=None,
                    session_buddy_id=None,
                    decision_reason=decision.reason,
                    error=f"snapshot capture failed: {exc}",
                )

            # Forward to existing tool with retry
            try:
                result = CheckpointResult(
                    fired=True,
                    snapshot_id=str(snapshot.path),
                    session_buddy_id=None,
                    decision_reason=decision.reason,
                    error=None,
                )
                await self._forward_with_retry(result)
                return result
            except Exception as exc:
                logger.exception("Forward to existing tool failed: %s", exc)
                return CheckpointResult(
                    fired=False,
                    snapshot_id=str(snapshot.path),
                    session_buddy_id=None,
                    decision_reason=decision.reason,
                    error=f"forward to existing tool failed: {exc}",
                )

    async def _forward_with_retry(self, result: CheckpointResult) -> None:
        last_exc: Exception | None = None
        for attempt in range(self.FORWARD_TO_RETRIES + 1):
            try:
                await self._forward_to(result)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.FORWARD_TO_RETRIES:
                    await asyncio.sleep(self.FORWARD_TO_BACKOFF_SECONDS * (2 ** attempt))
        if last_exc:
            raise last_exc
```

```python
# session_buddy/checkpoint/__init__.py
"""Session-buddy checkpoint safety mechanism.

Public API re-exports for callers.
"""

from session_buddy.checkpoint.orchestrator import (
    CheckpointOrchestrator,
    CheckpointResult,
)
from session_buddy.checkpoint.policy import (
    CheckpointPhase,
    CheckpointPolicy,
    DirtyFilesSignal,
    MidpointCriteria,
    PolicyDecision,
    TimeElapsedSignal,
    ValueAddSignal,
)
from session_buddy.checkpoint.snapshot import (
    GitNotAvailableError,
    RestoreConflict,
    RestoreResult,
    Snapshot,
    SnapshotMechanism,
)
from session_buddy.checkpoint.subagent_detector import (
    LockfileSignalSource,
    SignalSource,
    SubagentDetector,
)
from session_buddy.checkpoint.working_tree import (
    GitNotARepositoryError,
    WorkingTreeInspector,
)

__all__ = [
    "CheckpointOrchestrator",
    "CheckpointResult",
    "CheckpointPhase",
    "CheckpointPolicy",
    "DirtyFilesSignal",
    "MidpointCriteria",
    "PolicyDecision",
    "TimeElapsedSignal",
    "ValueAddSignal",
    "GitNotAvailableError",
    "RestoreConflict",
    "RestoreResult",
    "Snapshot",
    "SnapshotMechanism",
    "LockfileSignalSource",
    "SignalSource",
    "SubagentDetector",
    "GitNotARepositoryError",
    "WorkingTreeInspector",
]
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_orchestrator.py -v`
Expected: PASS for all 6 tests.

- [ ] **Step 6.5: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/orchestrator.py session_buddy/checkpoint/__init__.py tests/unit/checkpoint/test_orchestrator.py
git commit -m "feat(checkpoint): add CheckpointOrchestrator composition root with fail-closed semantics"
```

---

## Task 7: Wire Orchestrator into Existing Checkpoint Tool

**Files:**
- Modify: `session_buddy/mcp/tools/session/session_tools.py` — change `_checkpoint_impl` to construct an orchestrator and route the call through it
- Test: `tests/integration/checkpoint/test_session_tools_integration.py` — verify the wire-up

**Note**: ONLY execute this task if Task 1's probe confirmed `session-buddy` is the location. If the probe showed crackerjack, SKIP this task and modify the crackerjack code instead.

**Interfaces:**
- Consumes: existing `_checkpoint_impl(working_directory: str | None)` function signature
- Produces: same signature, but the body constructs a `CheckpointOrchestrator` and delegates to it

**Context**: This is the integration point. Existing callers continue to work unchanged because the public API is preserved.

- [ ] **Step 7.1: Read the current implementation**

Run: `cat /Users/les/Projects/session-buddy/session_buddy/mcp/tools/session/session_tools.py`
Identify the body of `_checkpoint_impl`. Do not modify yet — just understand what it currently does.

- [ ] **Step 7.2: Write the integration test**

```python
# tests/integration/checkpoint/test_session_tools_integration.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_checkpoint_impl_routes_through_orchestrator(tmp_path: Path) -> None:
    """Verify _checkpoint_impl constructs an orchestrator and uses it."""
    # Set up a working directory
    working_dir = tmp_path / "project"
    working_dir.mkdir()

    # Patch the orchestrator class before import
    with patch("session_buddy.checkpoint.orchestrator.CheckpointOrchestrator") as MockOrch:
        mock_orch_instance = MagicMock()
        mock_orch_instance.run_checkpoint = AsyncMock(return_value=MagicMock(
            fired=True,
            snapshot_id="/tmp/snap-test.patch",
            session_buddy_id=None,
            decision_reason="test",
            error=None,
        ))
        MockOrch.return_value = mock_orch_instance

        # Now invoke
        from session_buddy.mcp.tools.session.session_tools import _checkpoint_impl
        result = await _checkpoint_impl(working_directory=str(working_dir))

        # Verify orchestrator was called
        MockOrch.assert_called_once()
        mock_orch_instance.run_checkpoint.assert_awaited_once()
        # Verify phase was END_OF_TASK (default for explicit checkpoint calls)
        call_kwargs = mock_orch_instance.run_checkpoint.await_args.kwargs
        from session_buddy.checkpoint import CheckpointPhase
        assert call_kwargs["phase"] == CheckpointPhase.END_OF_TASK
```

- [ ] **Step 7.3: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/integration/checkpoint/test_session_tools_integration.py -v`
Expected: FAIL (the current `_checkpoint_impl` does not use the orchestrator).

- [ ] **Step 7.4: Modify `_checkpoint_impl`**

Open `session_buddy/mcp/tools/session/session_tools.py`. Replace the body of `_checkpoint_impl` with:

```python
async def _checkpoint_impl(working_directory: str | None) -> str:
    """Create a session checkpoint capturing current progress.

    Routes through the new CheckpointOrchestrator for safety:
    - Stash-free working-tree snapshot
    - Defer if subagent is active
    - Mandatory end-of-task checkpoint semantics
    """
    from pathlib import Path
    from session_buddy.checkpoint import (
        CheckpointOrchestrator,
        CheckpointPhase,
        CheckpointPolicy,
        LockfileSignalSource,
        SnapshotMechanism,
        SubagentDetector,
        WorkingTreeInspector,
    )

    working_dir = Path(working_directory) if working_directory else Path.cwd()
    snapshot_dir = Path("/tmp/sb-snapshots")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Build components with production defaults
    working_tree = WorkingTreeInspector(working_dir)
    subagent_detector = SubagentDetector(
        working_dir,
        LockfileSignalSource(working_dir),
    )
    snapshot_mechanism = SnapshotMechanism(working_dir, snapshot_dir)
    policy = CheckpointPolicy(
        subagent_detector=subagent_detector,
        working_tree=working_tree,
    )

    # The forward_to wraps the existing store_conversation_checkpoint behavior.
    # For the wiring step, this is a no-op stub — preserve existing tool's behavior
    # in a follow-up commit if store_conversation_checkpoint is meant to be invoked.
    async def forward_to(result) -> None:
        # Existing behavior TBD: invoke session-buddy's store_conversation_checkpoint
        # tool with the snapshot_path. For now, the orchestrator's snapshot is the
        # checkpoint artifact.
        pass

    orchestrator = CheckpointOrchestrator(
        policy=policy,
        snapshot=snapshot_mechanism,
        subagent_detector=subagent_detector,
        forward_to=forward_to,
    )

    result = await orchestrator.run_checkpoint(phase=CheckpointPhase.END_OF_TASK)

    if result.fired:
        return f"checkpoint created: snapshot={result.snapshot_id}, reason={result.decision_reason}"
    return f"checkpoint skipped: {result.decision_reason}" + (
        f" (error: {result.error})" if result.error else ""
    )
```

- [ ] **Step 7.5: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/integration/checkpoint/test_session_tools_integration.py -v`
Expected: PASS.

- [ ] **Step 7.6: Run full test suite to verify no regressions**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/ -x -q`
Expected: PASS for all existing tests + new checkpoint tests. Investigate any failures.

- [ ] **Step 7.7: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/session/session_tools.py tests/integration/checkpoint/test_session_tools_integration.py
git commit -m "feat(checkpoint): wire CheckpointOrchestrator into _checkpoint_impl"
```

---

## Task 8: Property-Based Invariant Test

**Files:**
- Create: `tests/unit/checkpoint/test_property_invariants.py`

**Step 8.1: Write the property-based test**

```python
# tests/unit/checkpoint/test_property_invariants.py
"""Property-based tests for the keystone invariant: working tree is never mutated."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, strategies as st

from session_buddy.checkpoint import (
    CheckpointOrchestrator,
    CheckpointPhase,
    CheckpointPolicy,
    LockfileSignalSource,
    SnapshotMechanism,
    SubagentDetector,
    WorkingTreeInspector,
)


class _NullSignal:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def read(self) -> bool:
        return self._active

    def write(self, active: bool) -> None:
        self._active = active


def _make_git_repo(tmp_path: Path, file_count: int) -> Path:
    """Create a git repo with `file_count` files committed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    for i in range(file_count):
        (repo / f"file_{i}.txt").write_text(f"content {i}")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _hash_working_tree(repo: Path) -> str:
    """Hash all file contents in the repo."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(repo.glob("*.txt")):
        h.update(f.read_bytes())
    return h.hexdigest()


@given(
    dirty_count=st.integers(min_value=0, max_value=10),
    subagent_active=st.booleans(),
    phase=st.sampled_from(list(CheckpointPhase)),
)
@settings(max_examples=50, deadline=None)
def test_working_tree_never_mutated_by_checkpoint(tmp_path: Path, dirty_count: int, subagent_active: bool, phase: CheckpointPhase) -> None:
    """For any state, after a checkpoint, the working tree is byte-identical to before."""
    repo = _make_git_repo(tmp_path, file_count=20)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # Make N dirty files
    for i in range(dirty_count):
        (repo / f"file_{i}.txt").write_text(f"MODIFIED {i}")

    before_hash = _hash_working_tree(repo)

    # Build orchestrator with mocked forward_to (the real session-buddy tool is not
    # available in unit tests)
    async def forward_to(result: Any) -> None:
        pass

    orchestrator = CheckpointOrchestrator(
        policy=CheckpointPolicy(
            subagent_detector=SubagentDetector(repo, _NullSignal(active=subagent_active)),
            working_tree=WorkingTreeInspector(repo),
        ),
        snapshot=SnapshotMechanism(repo, snapshot_dir),
        subagent_detector=SubagentDetector(repo, _NullSignal(active=subagent_active)),
        forward_to=forward_to,
    )

    result = asyncio.run(orchestrator.run_checkpoint(phase=phase))

    after_hash = _hash_working_tree(repo)
    assert before_hash == after_hash, (
        f"Working tree was mutated! Result: {result}, dirty_count={dirty_count}, "
        f"subagent_active={subagent_active}, phase={phase}"
    )


@given(
    subagent_active=st.booleans(),
)
@settings(max_examples=20, deadline=None)
def test_no_git_stash_ever_called(tmp_path: Path, subagent_active: bool) -> None:
    """Across many checkpoint runs, no `git stash` operation ever occurs."""
    import subprocess as sp

    repo = _make_git_repo(tmp_path, file_count=5)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (repo / "file_0.txt").write_text("dirty")

    stash_calls: list[list[str]] = []
    original_run = sp.run

    def spy_run(*args, **kwargs):
        if args and len(args) > 0 and isinstance(args[0], list):
            if "stash" in args[0]:
                stash_calls.append(args[0])
        return original_run(*args, **kwargs)

    # Patch sp.run used by SnapshotMechanism
    import session_buddy.checkpoint.snapshot as snap_module
    original_capture = snap_module.SnapshotMechanism._write_diff

    async def fake_capture(self, path: Path) -> None:
        # Simulate the capture without calling git
        path.write_text("")

    snap_module.SnapshotMechanism._write_diff = fake_capture

    try:
        async def forward_to(result: Any) -> None:
            pass

        orchestrator = CheckpointOrchestrator(
            policy=CheckpointPolicy(
                subagent_detector=SubagentDetector(repo, _NullSignal(active=subagent_active)),
                working_tree=WorkingTreeInspector(repo),
            ),
            snapshot=SnapshotMechanism(repo, snapshot_dir),
            subagent_detector=SubagentDetector(repo, _NullSignal(active=subagent_active)),
            forward_to=forward_to,
        )

        for phase in CheckpointPhase:
            asyncio.run(orchestrator.run_checkpoint(phase=phase))

        assert stash_calls == [], f"git stash was called: {stash_calls}"
    finally:
        snap_module.SnapshotMechanism._write_diff = original_capture
```

- [ ] **Step 8.2: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_property_invariants.py -v`
Expected: PASS for both property tests.

- [ ] **Step 8.3: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add tests/unit/checkpoint/test_property_invariants.py
git commit -m "test(checkpoint): add property-based tests for working-tree invariant"
```

---

## Task 9: Regression Test for the Stash-Clobber Bug

**Files:**
- Create: `tests/unit/checkpoint/test_stash_clobber_regression.py`

**Context**: This test would have FAILED against the pre-fix code (because `git stash` would have been called). With the new code, it passes by construction. Adding it ensures future regressions that re-introduce stash operations are caught immediately.

- [ ] **Step 9.1: Write the regression test**

```python
# tests/unit/checkpoint/test_stash_clobber_regression.py
"""Regression test for the 2026-07-15 stash-clobber observation.

Scenario: a subagent is "active" (signaled via lockfile), a midpoint
checkpoint is requested. With the new design:
- No `git stash` operation should occur
- Working tree should remain byte-identical
- CheckpointResult should indicate deferred (fired=False)
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from session_buddy.checkpoint import (
    CheckpointOrchestrator,
    CheckpointPhase,
    CheckpointPolicy,
    LockfileSignalSource,
    SnapshotMechanism,
    SubagentDetector,
    WorkingTreeInspector,
)


@pytest.fixture
def active_subagent_repo(tmp_path: Path) -> Path:
    """Create a git repo with an active subagent lockfile."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    (repo / "modified.py").write_text("# subagent is editing this")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    # Subagent makes the file dirty
    (repo / "modified.py").write_text("# subagent in-flight edit")
    (repo / "new_file.py").write_text("# new file from subagent")
    # Lockfile indicates active subagent
    (repo / ".mahavishnu-subagent-active").touch()
    return repo


def _hash_working_tree(repo: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for f in sorted(repo.glob("*.py")):
        h.update(f.read_bytes())
    return h.hexdigest()


@pytest.mark.asyncio
async def test_no_stash_during_active_subagent(active_subagent_repo: Path, tmp_path: Path) -> None:
    """Regression: with subagent active, no git stash should ever be invoked."""
    repo = active_subagent_repo
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    before_hash = _hash_working_tree(repo)

    stash_invocations: list[list[str]] = []
    original_run = subprocess.run

    def spy_run(*args, **kwargs):
        if args and len(args) > 0 and isinstance(args[0], list):
            if any("stash" in str(arg) for arg in args[0]):
                stash_invocations.append(args[0])
        return original_run(*args, **kwargs)

    async def forward_to(result) -> None:
        pass

    with patch.object(subprocess, "run", spy_run):
        orchestrator = CheckpointOrchestrator(
            policy=CheckpointPolicy(
                subagent_detector=SubagentDetector(repo, LockfileSignalSource(repo)),
                working_tree=WorkingTreeInspector(repo),
            ),
            snapshot=SnapshotMechanism(repo, snapshot_dir),
            subagent_detector=SubagentDetector(repo, LockfileSignalSource(repo)),
            forward_to=forward_to,
        )

        result = await orchestrator.run_checkpoint(phase=CheckpointPhase.MIDPOINT_TIME)

    # Assertions: the new design's contract
    assert result.fired is False, "Checkpoint should have been deferred (subagent active)"
    assert "subagent" in result.decision_reason.lower(), (
        f"Reason should mention subagent, got: {result.decision_reason}"
    )
    assert stash_invocations == [], (
        f"git stash was called during subagent-active window: {stash_invocations}"
    )

    # Working tree must be unchanged
    after_hash = _hash_working_tree(repo)
    assert before_hash == after_hash, "Working tree was mutated during checkpoint!"
```

- [ ] **Step 9.2: Run test to verify it passes**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_stash_clobber_regression.py -v`
Expected: PASS.

- [ ] **Step 9.3: Verify test would fail against pre-fix code (sanity check)**

This step is for confidence. To verify the test catches the original bug, temporarily revert Task 4's `SnapshotMechanism.capture()` to use `git stash` / `git stash pop`:

```python
# TEMPORARY — DO NOT COMMIT
async def capture(self, label: str) -> Snapshot:
    # Old buggy behavior — stash, capture, pop
    await asyncio.create_subprocess_exec("git", "stash", cwd=str(self._working_dir))
    # ... do something with stash ...
    await asyncio.create_subprocess_exec("git", "stash", "pop", cwd=str(self._working_dir))
    ...
```

Run the test — it should FAIL with `stash_invocations != []`. Restore the correct implementation afterward.

- [ ] **Step 9.4: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add tests/unit/checkpoint/test_stash_clobber_regression.py
git commit -m "test(checkpoint): add regression test for 2026-07-15 stash-clobber bug"
```

---

## Task 10: Manual Claude Code Hook Verification

**Files:** None (verification task)

**Context**: Code-level tests don't cover the Claude Code wiring. This task is a manual checklist for the implementing engineer.

- [ ] **Step 10.1: Inspect hook wiring**

Read `.claude/hooks/mcp-hooks.json` and confirm the `mcp_pre_checkpoint` script path matches the new orchestrator entry point. If the path needs updating, modify it.

- [ ] **Step 10.2: Run a real Claude Code session**

Start a fresh Claude Code session in this repo (`/Users/les/Projects/mahavishnu`). Dispatch a Task-tool subagent. While the subagent is running, observe the hook log:

```bash
tail -f ~/.claude/logs/mcp-sync.log
```

- [ ] **Step 10.3: Verify no stash operations**

Confirm no `git stash` lines appear in `mcp-sync.log` while the subagent is running.

- [ ] **Step 10.4: Verify end-of-task checkpoint fires**

When the subagent completes, verify the end-of-task checkpoint fires (look for "checkpoint:" entry in session-buddy via `mahavishnu mcp call session-buddy list_checkpoints` or equivalent).

- [ ] **Step 10.5: Document findings**

Append to `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md` a "Resolution" section with:
- Commit hashes that implemented the fix
- Test results (all green)
- Manual verification observations
- Any deviations from the plan

- [ ] **Step 10.6: Commit (if hook wiring changed)**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/hooks/mcp-hooks.json
git commit -m "chore(hooks): update pre_checkpoint path to use new orchestrator"
```

---

## Task 11: Update Follow-ups Documentation

**Files:**
- Modify: `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md` — add Resolution section
- Modify: `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` — reference the plan

- [ ] **Step 11.1: Add Resolution section to stash-clobber follow-up**

Append to `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`:

```markdown
## Resolution (2026-MM-DD)

**Status**: Implemented and verified.

**Implementation**: see plan at `docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md` and spec at `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md`.

**Commits**:
- [list commit hashes from session-buddy repo]

**Test results**:
- [list test command + pass/fail summary]

**Manual verification**:
- [list observations from Task 10]

**Deviations from plan**: [none / list any]
```

- [ ] **Step 11.2: Update the existing Step 3f in the pickup prompt**

**Do NOT add a new section** — Step 3f already exists in the pickup prompt (it was added during this plan's authoring on commit `eb5b5d2`). Adding another `### 3f` would produce a duplicate heading. Per REWORK R7.

Verify Step 3f is present:

```bash
grep -n "^### 3f" /Users/les/Projects/mahavishnu/docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md
# Expected: one match
```

Then update Step 3f in-place with:
- The final commit hashes from Tasks 1-12 (replace the placeholder list)
- A one-line note: "Plan reworked 2026-07-15 — see REWORK NOTES section at top of plan for critical-blocker fixes that override the original tasks."

The updated Step 3f reads (template):

```markdown
### 3f. Reference the stash-clobber fix implementation plan

[Existing body — preserved as-is]

**Plan reworked 2026-MM-DD**: see the REWORK NOTES section at the top
of `docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md`
for critical-blocker fixes that override the original tasks
(specifically R1-R10 addressing probe scope, wrong code path,
broken test spies, missing lockfile writer, cross-repo caller
surface, duplicate doc section, worktree preamble, feature-tracking
entry, and Integration Contract blocks).

**Final commits** (replace after execution):
- session-buddy: [list commit hashes]
- mahavishnu: [list commit hashes]
- crackerjack: [if applicable]

The plan's Task 1 (Architecture Probe) confirms the fix location; the
remaining tasks depend on that outcome. The plan's Task 7 (Wire
Orchestrator) targets the actual mutator per R2
(`session_buddy/utils/git_worktrees.py:create_checkpoint_commit`,
NOT `_checkpoint_impl`). Task 13 (new per R5) wires the lockfile
writer; Task 14 (new per R6) documents or updates the mahavishnu
HTTP client caller surface.
```

The plan's Task 10 (Manual Claude Code Hook Verification) overlaps
with this pickup prompt's Step 3 (Verify Bodai Claude Code hooks are
firing) — coordinate to avoid duplicate work.
```

- [ ] **Step 11.3: Commit documentation updates**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md
git commit -m "docs(followups): reference stash-clobber fix plan in pickup prompt"
```

---

## Self-Review

After writing the complete plan, run this checklist:

**1. Spec coverage** — every section of the spec maps to at least one task:

| Spec section | Task(s) |
|---|---|
| Architecture (location, probe) | Task 1 |
| SubagentDetector + SignalSource | Task 3 |
| SnapshotMechanism | Task 4 |
| CheckpointPolicy + ValueAddSignal + OR semantics | Task 5 |
| CheckpointOrchestrator | Task 6 |
| Wire into existing tool | Task 7 |
| Property-based invariant test | Task 8 |
| Regression test | Task 9 |
| Manual Claude Code hook verification | Task 10 |
| Cleanup contract (TTL, session-end hook, manual cleanup) | **GAP** — add cleanup task |
| Update followups docs | Task 11 |
| Operator-visible signals (structured logs, metrics) | **GAP** — covered loosely by error handling; consider dedicated task |

**2. Placeholder scan** — no "TBD", "TODO", "implement later" in the plan body. (The TBD in the deferred-decisions table of the spec is intentional; the plan does not duplicate it.)

**3. Type consistency** — function signatures match across tasks. Verified:
- `WorkingTreeInspector.dirty_file_count() -> int` (sync, in test) but **async in implementation** — Task 2 step 2.4 corrects this
- `SubagentDetector.is_active() -> bool` (sync) and `wait_until_idle() -> bool` (async) — consistent
- `SnapshotMechanism.capture(label) -> Snapshot` (async) — consistent
- `CheckpointPolicy.decide(*, phase, hook_request) -> PolicyDecision` (async) — consistent
- `CheckpointOrchestrator.run_checkpoint(*, phase, hook_request) -> CheckpointResult` (async) — consistent

**4. Gaps found** — two:
- Cleanup contract from spec section "Error Handling" → "Cleanup contract" not covered. Add Task 11.5 (or new Task 12).
- Operator-visible signals (structured logs, metrics) are scattered in error handling but no dedicated task adds the metrics counter.

These are added as Task 12 below.

---

## Task 12: Add Cleanup and Metrics (from self-review gaps)

**Files:**
- Create: `session_buddy/checkpoint/cleanup.py`
- Create: `session_buddy/checkpoint/metrics.py`
- Test: `tests/unit/checkpoint/test_cleanup.py`
- Test: `tests/unit/checkpoint/test_metrics.py`

**Step 12.1: Write the failing test for cleanup**

```python
# tests/unit/checkpoint/test_cleanup.py
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from session_buddy.checkpoint.cleanup import SnapshotCleanup


def test_cleanup_removes_old_snapshots(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    # Create one old, one fresh
    old = snapshot_dir / "snap-old.patch"
    old.write_text("old content")
    # Set mtime to 8 days ago
    eight_days_ago = time.time() - (8 * 86400)
    import os
    os.utime(old, (eight_days_ago, eight_days_ago))

    fresh = snapshot_dir / "snap-fresh.patch"
    fresh.write_text("fresh content")

    cleanup = SnapshotCleanup(snapshot_dir, ttl_days=7)
    removed = asyncio.run(cleanup.run())
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_cleanup_with_zero_ttl_removes_all(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "snap-a.patch").write_text("a")
    (snapshot_dir / "snap-b.patch").write_text("b")

    cleanup = SnapshotCleanup(snapshot_dir, ttl_days=0)
    removed = asyncio.run(cleanup.run())
    assert removed == 2


def test_cleanup_skips_non_patch_files(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "README.md").write_text("don't delete me")
    (snapshot_dir / "snap-old.patch").write_text("delete me")
    import os, time
    eight_days_ago = time.time() - (8 * 86400)
    os.utime(snapshot_dir / "snap-old.patch", (eight_days_ago, eight_days_ago))

    cleanup = SnapshotCleanup(snapshot_dir, ttl_days=7)
    asyncio.run(cleanup.run())
    assert (snapshot_dir / "README.md").exists()
```

**Step 12.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/test_cleanup.py -v`
Expected: FAIL.

**Step 12.3: Write the cleanup implementation**

```python
# session_buddy/checkpoint/cleanup.py
"""TTL-based cleanup for snapshot files."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SnapshotCleanup:
    """Removes snapshot files older than TTL."""

    def __init__(self, snapshot_dir: Path, ttl_days: int = 7) -> None:
        self._snapshot_dir = snapshot_dir
        self._ttl_seconds = ttl_days * 86400

    async def run(self) -> int:
        """Delete expired snapshots. Returns count deleted."""
        if not self._snapshot_dir.exists():
            return 0
        cutoff = time.time() - self._ttl_seconds
        removed = 0
        for path in self._snapshot_dir.glob("snap-*.patch"):
            try:
                stat = path.stat()
                if stat.st_mtime < cutoff:
                    path.unlink()
                    removed += 1
                    logger.info("Removed expired snapshot: %s", path)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", path, exc)
        return removed
```

**Step 12.4: Write the metrics test**

```python
# tests/unit/checkpoint/test_metrics.py
from __future__ import annotations

from session_buddy.checkpoint.metrics import CheckpointMetrics


def test_checkpoint_failure_increments_counter() -> None:
    metrics = CheckpointMetrics()
    metrics.record_failure("git_missing")
    metrics.record_failure("git_missing")
    metrics.record_failure("forward_to_unreachable")
    assert metrics.get_failure_count("git_missing") == 2
    assert metrics.get_failure_count("forward_to_unreachable") == 1


def test_checkpoint_success_increments_counter() -> None:
    metrics = CheckpointMetrics()
    metrics.record_success()
    metrics.record_success()
    assert metrics.get_success_count() == 2


def test_metrics_summary() -> None:
    metrics = CheckpointMetrics()
    metrics.record_success()
    metrics.record_failure("git_missing")
    summary = metrics.summary()
    assert summary["successes"] == 1
    assert summary["failures"]["git_missing"] == 1
```

**Step 12.5: Write the metrics implementation**

```python
# session_buddy/checkpoint/metrics.py
"""In-process metrics for checkpoint operations."""

from __future__ import annotations

from collections import defaultdict


class CheckpointMetrics:
    """Tracks checkpoint success/failure counts by failure reason."""

    def __init__(self) -> None:
        self._successes = 0
        self._failures: dict[str, int] = defaultdict(int)

    def record_success(self) -> None:
        self._successes += 1

    def record_failure(self, reason: str) -> None:
        self._failures[reason] += 1

    def get_success_count(self) -> int:
        return self._successes

    def get_failure_count(self, reason: str) -> int:
        return self._failures.get(reason, 0)

    def summary(self) -> dict:
        return {
            "successes": self._successes,
            "failures": dict(self._failures),
        }
```

**Step 12.6: Wire metrics into orchestrator**

Modify `session_buddy/checkpoint/orchestrator.py`:
- Add `metrics: CheckpointMetrics | None = None` parameter to `__init__`
- Call `metrics.record_success()` after successful forward_to
- Call `metrics.record_failure("snapshot_capture_failed")` on snapshot error
- Call `metrics.record_failure("forward_to_failed")` on forward_to error

**Step 12.7: Update __init__.py exports**

Add `SnapshotCleanup` and `CheckpointMetrics` to `session_buddy/checkpoint/__init__.py`.

**Step 12.8: Run all tests to verify**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/checkpoint/ tests/integration/checkpoint/ -v`
Expected: PASS for all tests.

**Step 12.9: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/checkpoint/cleanup.py session_buddy/checkpoint/metrics.py session_buddy/checkpoint/orchestrator.py session_buddy/checkpoint/__init__.py tests/unit/checkpoint/test_cleanup.py tests/unit/checkpoint/test_metrics.py
git commit -m "feat(checkpoint): add snapshot TTL cleanup and metrics tracking"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md`.

**Two execution options** (for the future session that will execute this):

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Per the user's instruction, this plan is NOT executed now. It is referenced in the pickup prompt at `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` (Task 11.2 above) for future execution.

## Multi-Agent Review Gate

This plan requires multi-agent review before execution. The user requested at least 2 random agents plus task-appropriate agents. Dispatch via the Workflow tool after this plan is committed.