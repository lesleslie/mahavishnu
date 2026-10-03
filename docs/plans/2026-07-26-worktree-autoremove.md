---
date: 2026-07-26
last_reviewed: 2026-07-26
superseded_by: null
topic: worktree-autoremove
status: draft
role: implementation
---

# Worktree Prune-Merged CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicitly invoked `mahavishnu worktree prune-merged` CLI that
removes only worktrees whose changes are already represented on the repository's
main branch.

**Architecture:** A new core module performs fail-closed, multi-signal merge
classification and candidate filtering. The Typer command resolves configured
repository nicknames once, passes the canonical nickname into the core helper,
and delegates every removal to the existing `WorktreeCoordinator`. This tranche
has one trigger only: a user invoking the CLI. SessionEnd and cron automation are
deferred until the CLI passes the Wave 4 manual validation sequence.

**Tech Stack:** Python 3.13, Typer, pytest, Git subprocesses with argv lists,
`WorktreeCoordinator`, `WorktreeBackupManager`, and `WorktreeAuditLogger`.

## Global Constraints

- Active scope is **CLI only**. Do not create or register a SessionEnd hook, cron
  wrapper, settings gate, or MCP tool in this tranche.
- Use the actual coordinator module name:
  `mahavishnu/core/worktree_coordination.py` and class
  `WorktreeCoordinator`.
- Merge and dirty-state uncertainty must fail closed. An `"undetermined"`
  worktree is never a default-scope candidate, even with `--include-dirty`.
- `--repo` is resolved through the repository manager once. Pass the resolved
  `repo_info.nickname` into `find_merged_worktrees(repo_nickname=...)` and from
  there into `coordinator.list_worktrees(repo_nickname=...)`.
- Default merged-clean removals do **not** create backups. The coordinator creates
  a backup only when a dirty worktree is force-removed.
- `--include-dirty` requires `--force-reason` before any removal is attempted.
- A sweep with one or more per-candidate failures must exit non-zero after
  rendering the complete human or JSON result.
- Do not implement anything from the deferred appendix until Wave 4 manual
  testing has validated the CLI.

---

## Scope Reduction — Option 2

### Active deliverable

1. Policy amendment permitting explicit CLI cleanup.
2. Core merge classification, candidate selection, removal orchestration, and
   audit events.
3. `mahavishnu worktree prune-merged` CLI and unit tests.
4. User documentation, feature tracking, validation, and manual testing.

### Explicitly out of active scope

- `.claude/hooks/worktree-autoprune.py`
- the SessionEnd hook entry in `.claude/settings.json`
- `scripts/autoprune-worktrees.sh`
- `tests/integration/test_worktree_autoprune_hook.py`
- active use of `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS`
- a `worktree_prune_merged` MCP tool
- a `worktree_autoprune:` settings section

The automation design is retained only in the final **DEFERRED** appendix.

## Context

The canonical policy in
`.claude/decisions/session-worktree-defaults.md` Rule 2 currently says:

> Never auto-removes worktrees. SessionEnd marks the entry `abandoned` in the
> registry but does NOT delete the git worktree.

A 2026-07-26 audit found 64 worktrees whose changes appeared to be represented
on main: 19 clean and 45 dirty. Those counts are a snapshot, not an acceptance
criterion; repository state may change before implementation. The first release
therefore exposes only an operator-controlled CLI, defaults to a dry-run-friendly
merged-clean scope, and defers all unattended triggers.

The earlier plan relied on `git cherry` alone. That is unsafe because Git's
`cmd_cherry` sets `revs.max_parents = 1`, excluding merge commits. A feature
branch can therefore contain an unmerged conflict-resolution merge commit while
`git cherry` prints no `+` lines. This plan fixes that blocker with ancestry,
merge-commit detection, and patch-equivalence signals in that order.

## Existing Infrastructure — Reuse, Do Not Replace

| Module | File | Reuse |
|---|---|---|
| `WorktreeCoordinator` | `mahavishnu/core/worktree_coordination.py` | Provider-backed listing, safety checks, dependency checks, and removal. |
| `WorktreeBackupManager` | `mahavishnu/core/worktree_backup.py` | Creates a backup only for `force=True` plus uncommitted changes. |
| `WorktreeAuditLogger` | `mahavishnu/core/worktree_audit.py` | Persistent structured audit trail; extend with sweep-level prune events. |
| `SessionWorktreeRegistry` | `mahavishnu/core/worktree_session_registry.py` | Optional `last_seen_at` / `abandoned_at` lookup for manually supplied `--ttl-days`. |
| `RepositoryManager` | `mahavishnu/core/repo_manager.py` | Name, package, and nickname resolution. |
| `worktree_app` | `mahavishnu/worktree_cli.py` | Existing Typer app and async bridge. |
| Direct Git provider | `mahavishnu/core/worktree_providers/direct_git.py` | Coordinator fallback provider. |
| Session-Buddy provider | `mahavishnu/core/worktree_providers/session_buddy.py` | Coordinator primary provider. |

### Backup contract, stated accurately

`WorktreeCoordinator.remove_worktree` initializes `backup_path = None` and calls
`WorktreeBackupManager.create_backup_before_removal` only when both
`has_uncommitted` and `force` are true.

- **Default merged-clean mode:** no backup is created. The branch and Git reflog
  remain the recovery path; a worktree can be recreated with `git worktree add`.
- **`--include-dirty` mode:** the first non-forced attempt detects uncommitted
  changes, the pruner escalates with the required reason, and the coordinator
  creates a backup before forced removal.

Do not claim that every removal has a backup.

## Files Touched by the Active Plan

| Path | Change | Purpose |
|---|---|---|
| `.claude/decisions/worktree-autoremove-policy.md` | Create | Explicitly amend Rule 2 for user-invoked CLI only. |
| `.claude/decisions/README.md` | Edit | Index the new canonical decision. |
| `mahavishnu/core/worktree_prune_merged.py` | Create | Candidate model, fail-closed classifiers, finder, and pruner. |
| `mahavishnu/core/worktree_audit.py` | Edit | Add sweep-level `worktree_prune_merged_*` events required by the manual audit check. |
| `mahavishnu/worktree_cli.py` | Edit | Add the Typer subcommand and repository nickname threading. |
| `tests/unit/test_worktree_prune_merged.py` | Create | Ten core tests plus five CLI tests. |
| `tests/integration/test_worktree_autoprune_hook.py` | Delete if present | Hook is outside active scope. |
| `docs/WORKTREE_AUTOREMOVE.md` | Create | CLI-only operator guide and manual testing sequence. |
| `docs/feature-tracking/worktree-autoremove.yaml` | Create | Track CLI built/wired state and automation deferral. |

No active task modifies `.claude/settings.json`, `settings/mahavishnu.yaml`,
`mahavishnu/mcp/tools/worktree_tools.py`, or any hook/script file.

---

## Wave 1 — Policy Decision (20 minutes)

**Goal:** Amend the existing no-auto-remove rule narrowly enough to permit only
an explicit user-invoked CLI.

**Files:**

- Create: `.claude/decisions/worktree-autoremove-policy.md`
- Edit: `.claude/decisions/README.md`

### Task 1.1: Write the explicit Rule 2 amendment

- [ ] **Step 1: Create the decision file with this content**

```markdown
---
status: active
role: canonical
date: 2026-07-26
last_reviewed: 2026-07-26
superseded_by: null
topic: worktree-autoremove
---

# Worktree prune-merged — explicit CLI exception

## Context

`session-worktree-defaults.md` Rule 2 prohibits automatic removal of
worktrees. Operators nevertheless need a safe, explicit way to remove
worktrees whose changes are already represented on the repository's main
branch.

This decision permits one user-invoked CLI. It does not permit SessionEnd,
cron, or other unattended invocation.

## Amendment to session-worktree-defaults.md Rule 2

The original Rule 2 ("never auto-removes worktrees") is amended to add the
following exception:

> "...EXCEPT via the `mahavishnu worktree prune-merged` CLI, which is
> permitted to remove *merged* worktrees when explicitly invoked by the
> user. SessionEnd hooks and cron automation are NOT permitted under this
> amendment; they require a separate decision."

## Decision rule

1. `mahavishnu worktree prune-merged` may remove only candidates classified
   exactly as `merged` by the multi-signal classifier documented in
   `docs/WORKTREE_AUTOREMOVE.md`.
2. `not_merged` and `undetermined` candidates are never removed.
3. The default scope is merged worktrees whose dirty status is exactly
   `clean`.
4. `--include-dirty` requires an explicit `--force-reason`. Dirty forced
   removals use the coordinator's existing backup path. Clean removals do
   not create backups.
5. SessionEnd hooks, cron wrappers, hidden automated triggers, and the
   `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS` gate are outside this amendment.
   They require a new decision after the CLI passes the plan's Wave 4 manual
   testing sequence.

## Threat model

| Threat | Mitigation |
|---|---|
| An unmerged merge commit is hidden from `git cherry` | Check ancestry, then refuse branches containing merge commits in `main..HEAD`, before using patch equivalence. |
| A Git status command fails and a dirty worktree is treated as clean | Dirty status is tri-state; `undetermined` is always excluded. |
| A nickname differs from the repository folder name | CLI resolves the repository once and passes its canonical nickname through the helper to the coordinator. |
| A partial sweep looks successful to automation or the shell | Any failed result produces CLI exit code 1 after complete output. |
| User expects a backup for a clean removal | Docs state that clean removals use branch/reflog recovery; backups are for forced dirty removal only. |

## Cross-references

- Original rule: `.claude/decisions/session-worktree-defaults.md` Rule 2
- Plan: `docs/superpowers/plans/2026-07-26-worktree-autoremove.md`
- Operator guide: `docs/WORKTREE_AUTOREMOVE.md`
- CLI: `mahavishnu worktree prune-merged`
```

- [ ] **Step 2: Add the decision to `.claude/decisions/README.md`**

Add one newest-first table row:

```markdown
| `worktree-autoremove-policy.md` | Narrow Rule 2 amendment permitting explicitly invoked `worktree prune-merged`; hook and cron remain prohibited. | Active. |
```

- [ ] **Step 3: Review policy wording**

Confirm the decision contains the exact heading
`## Amendment to session-worktree-defaults.md Rule 2`, contains the quoted
exception, and nowhere says the original Rule 2 is merely "preserved".

- [ ] **Step 4: Commit Wave 1**

```bash
git add .claude/decisions/worktree-autoremove-policy.md .claude/decisions/README.md
git commit -m "docs(decisions): permit explicit prune-merged CLI"
```

**Integration Contract (Wave 1):**

- **Triggered from:** the Wave 3 CLI docstring links to this decision.
- **Returns to / updates:** canonical policy under `.claude/decisions/`.
- **Demonstrable by:** a text search finds the explicit Rule 2 amendment and
  the prohibition on SessionEnd/cron automation.
- **Rollback signal:** any implementation trigger other than direct CLI user
  invocation is introduced before a follow-up decision.
- **Observability added:** none; this wave is policy only.

---

## Wave 2 — Core Module and Fail-Closed Classification (2 hours)

**Goal:** Build a core API that classifies merge state using multiple signals,
classifies dirty state using three states, identifies candidates under the
correct repository nickname, and delegates removals safely.

**Files:**

- Create: `mahavishnu/core/worktree_prune_merged.py`
- Edit: `mahavishnu/core/worktree_audit.py`
- Create: `tests/unit/test_worktree_prune_merged.py`

**Interfaces:**

- Produces:
  - `WorktreePruneCandidate`
  - `WorktreePruneResult`
  - `classify_merge_status(worktree_path, *, main_branch="main", master_fallback=True) -> str`
  - `find_merged_worktrees(repo_path, *, repo_nickname=None, ...) -> list[WorktreePruneCandidate]`
  - `WorktreePruner.remove(...) -> list[WorktreePruneResult]`
- Consumes:
  - `WorktreeCoordinator.list_worktrees(repo_nickname=...)`
  - `WorktreeCoordinator.remove_worktree(...)`
  - `WorktreeAuditLogger`

### Task 2.1: Establish the ten-test core matrix

Create `tests/unit/test_worktree_prune_merged.py` with the usual
`from __future__ import annotations` first, then these imports:

```python
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from mahavishnu.core.worktree_prune_merged import (
    WorktreePruneCandidate,
    WorktreePruner,
    classify_merge_status,
    find_merged_worktrees,
)
```

Use this command helper in real-Git fixtures:

```python
def run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
```

The Wave 2 test file must contain exactly these ten named core tests before CLI
tests are appended in Wave 3:

| # | Test | Required behavior |
|---:|---|---|
| 1 | `test_candidate_fields_round_trip` | `dirty_status="clean"` makes `is_clean` true; `merge_status="undetermined"` makes `is_merged` false. |
| 2 | `test_git_dirty_count_is_tristate` | Real clean repo → `clean`, untracked file → `dirty`, non-repo path → `undetermined`. |
| 3 | `test_classify_merge_status_handles_ancestor` | A real feature tip contained in main returns `merged`. |
| 4 | `test_classify_merge_status_handles_squash_merged_branch` | A real squash-merged branch in a real worktree returns `merged`. |
| 5 | `test_classify_merge_status_guards_unmerged_merge_commit` | A feature-only merge commit returns `undetermined`, never `merged`. |
| 6 | `test_classify_merge_status_reports_linear_unmerged_commit` | A linear feature commit absent from main returns `not_merged`. |
| 7 | `test_classify_merge_status_master_fallback_and_missing_refs` | Missing main falls back to master; missing both returns `undetermined`. |
| 8 | `test_find_merged_worktrees_threads_nickname_and_filters_dirty_state` | Coordinator receives the supplied nickname; default excludes dirty and all modes exclude undetermined. |
| 9 | `test_worktree_pruner_uses_two_phase_force_escalation` | Clean success stays `force=False`; `safety_check="uncommitted_changes"` escalates once with the reason. |
| 10 | `test_worktree_pruner_rejects_unmerged_candidate` | Coordinator is never called for a non-merged candidate. |

- [ ] **Step 1: Add the candidate test**

```python
def test_candidate_fields_round_trip():
    candidate = WorktreePruneCandidate(
        repo_path=Path("/Users/les/Projects/mahavishnu"),
        repo_nickname="vishnu",
        worktree_path=Path("/Users/les/Projects/mahavishnu/.claude/worktrees/wf-x"),
        branch="feat/test",
        ahead=0,
        behind=130,
        dirty_status="clean",
        last_touched_at="2026-07-20T00:00:00+00:00",
        merge_status="merged",
    )
    assert candidate.is_merged is True
    assert candidate.is_clean is True

    undetermined = WorktreePruneCandidate(
        repo_path=candidate.repo_path,
        repo_nickname=candidate.repo_nickname,
        worktree_path=candidate.worktree_path,
        branch=candidate.branch,
        ahead=0,
        behind=0,
        dirty_status="undetermined",
        last_touched_at=None,
        merge_status="undetermined",
    )
    assert undetermined.is_merged is False
    assert undetermined.is_clean is False
```

- [ ] **Step 2: Add the real squash fixture exactly as the regression case**

```python
def test_classify_merge_status_handles_squash_merged_branch(tmp_path):
    """Squash-merged branches are detected as merged (the B2 regression case)."""
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    repo.mkdir()
    wt.mkdir()  # Will be turned into a real worktree below

    run = lambda *args, cwd=repo: subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, timeout=10
    )
    run("init", "--initial-branch=main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    # main: commit A
    (repo / "a.txt").write_text("A")
    run("add", "a.txt")
    run("commit", "-m", "A")
    # branch feat: commit B
    run("checkout", "-b", "feat")
    (repo / "b.txt").write_text("B")
    run("add", "b.txt")
    run("commit", "-m", "B")
    # squash-merge feat into main
    run("checkout", "main")
    run("merge", "--squash", "feat")
    run("commit", "-m", "squash feat")
    # Create a real worktree pointing at feat
    run("worktree", "add", str(wt), "feat")

    from mahavishnu.core.worktree_prune_merged import classify_merge_status
    assert classify_merge_status(wt) == "merged"
```

- [ ] **Step 3: Add a real unmerged merge-commit guard fixture**

```python
def test_classify_merge_status_guards_unmerged_merge_commit(tmp_path):
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    repo.mkdir()
    run_git("init", "--initial-branch=main", cwd=repo)
    run_git("config", "user.email", "test@example.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    run_git("add", "base.txt", cwd=repo)
    run_git("commit", "-m", "base", cwd=repo)

    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "-b", "side", cwd=repo)
    (repo / "side.txt").write_text("side\n")
    run_git("add", "side.txt", cwd=repo)
    run_git("commit", "-m", "side", cwd=repo)
    run_git("checkout", "feat", cwd=repo)
    run_git("merge", "--no-ff", "side", "-m", "merge side", cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    assert classify_merge_status(wt) == "undetermined"
```

This is the new security regression test: `git cherry main` is not sufficient
for this history because it excludes the merge commit.

- [ ] **Step 4: Add the remaining real-history classifier tests**

For tests 3, 6, and 7, initialize repositories with explicit
`--initial-branch`, configure the test identity, create commits, and add an
actual worktree with `git worktree add`. Do not call the classifier on an empty
directory. Required assertions are:

```python
assert classify_merge_status(ancestor_worktree) == "merged"
assert classify_merge_status(linear_unmerged_worktree) == "not_merged"
assert classify_merge_status(master_squash_worktree) == "merged"
assert classify_merge_status(no_main_or_master_worktree) == "undetermined"
```

- [ ] **Step 5: Run the classifier subset and verify it fails before implementation**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -k "candidate or dirty or classify" -v
```

Expected: collection/import failure because
`mahavishnu.core.worktree_prune_merged` does not exist yet.

### Task 2.2: Implement tri-state candidate and multi-signal merge detection

- [ ] **Step 1: Create the module header and candidate model**

```python
"""Identify and remove worktrees whose changes are represented on main."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import subprocess  # nosec B404 -- argv lists only
from typing import TYPE_CHECKING

from mahavishnu.core.worktree_audit import WorktreeAuditLogger

if TYPE_CHECKING:
    from mahavishnu.core.worktree_coordination import WorktreeCoordinator


@dataclass(frozen=True)
class WorktreePruneCandidate:
    """A fail-closed candidate for explicit prune-merged removal."""

    repo_path: Path
    repo_nickname: str
    worktree_path: Path
    branch: str
    ahead: int
    behind: int
    dirty_status: str
    last_touched_at: str | None
    merge_status: str = "undetermined"

    @property
    def is_merged(self) -> bool:
        return self.merge_status == "merged"

    @property
    def is_clean(self) -> bool:
        return self.dirty_status == "clean"

    @property
    def age_days(self) -> int | None:
        if not self.last_touched_at:
            return None
        try:
            timestamp = datetime.fromisoformat(
                self.last_touched_at.replace("Z", "+00:00")
            )
        except ValueError:
            return None
        return (datetime.now(UTC) - timestamp).days
```

- [ ] **Step 2: Implement `classify_merge_status` with the required signals**

Use this implementation, not the old cherry-only version:

```python
def classify_merge_status(
    worktree_path: Path,
    *,
    main_branch: str = "main",
    master_fallback: bool = True,
) -> str:
    """Return 'merged' | 'not_merged' | 'undetermined' for HEAD vs main_branch.

    Multi-signal: ancestry first, then patch-equivalence with merge-commit guard.

    Logic:
      1. If main doesn't exist (rev-parse fails) and master_fallback, try master.
      2. If main exists and HEAD is an ancestor of main, return 'merged'.
      3. If main exists and HEAD is NOT an ancestor of main, check for merge
         commits in main..HEAD. If any merge commit exists, return 'undetermined'
         (git cherry excludes merge commits, so we cannot reliably determine).
      4. Otherwise, run `git cherry <main_branch>`. If no '+' lines, return 'merged'.
      5. If '+' lines exist, return 'not_merged'.
      6. On any subprocess failure, return 'undetermined'.
    """
    branches_to_try = [main_branch]
    if master_fallback and main_branch != "master":
        branches_to_try.append("master")

    for branch in branches_to_try:
        # Step 1: verify the branch exists
        try:
            exists = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "--verify",
                 "--quiet", branch],
                capture_output=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "undetermined"
        if exists.returncode != 0:
            continue  # try next branch

        # Step 2: ancestry check (handles linear FF + true merge commits)
        try:
            ancestor = subprocess.run(
                ["git", "-C", str(worktree_path), "merge-base",
                 "--is-ancestor", "HEAD", branch],
                capture_output=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "undetermined"
        if ancestor.returncode == 0:
            return "merged"

        # Step 3: check for merge commits in main..HEAD
        # (git cherry excludes these, so we cannot rely on it alone)
        try:
            merges = subprocess.run(
                ["git", "-C", str(worktree_path), "log",
                 f"{branch}..HEAD", "--merges", "--oneline"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "undetermined"
        if merges.returncode != 0:
            return "undetermined"
        if merges.stdout.strip():
            # Merge commits exist; git cherry alone is unreliable.
            return "undetermined"

        # Step 4: patch-equivalence check (handles squash, rebase, etc.)
        try:
            cherry = subprocess.run(
                ["git", "-C", str(worktree_path), "cherry", branch],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "undetermined"
        if cherry.returncode != 0:
            return "undetermined"

        # Any '+' line means a commit in HEAD whose patch is NOT in <branch>.
        has_unmerged = any(
            line.startswith("+") for line in cherry.stdout.splitlines()
        )
        if not has_unmerged:
            return "merged"
        # This branch has unmerged commits. We are not_merged, not
        # undetermined, because we successfully classified it.
        return "not_merged"

    # No branch found that classifies this worktree.
    return "undetermined"
```

- [ ] **Step 3: Implement the dirty-state helper exactly fail-closed**

```python
def _git_dirty_count(worktree_path: Path) -> str:
    """Return 'clean' | 'dirty' | 'undetermined' for the worktree's status."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--short"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "undetermined"
    if result.returncode != 0:
        return "undetermined"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return "dirty" if lines else "clean"
```

The legacy helper name is retained to minimize churn, but its return value is
now tri-state. Do not compare it numerically.

- [ ] **Step 4: Add reporting helpers**

Implement `_git_current_branch` and `_git_ahead_behind` with 5-second timeouts.
Branch lookup returns `None` on error or detached HEAD. Ahead/behind is reporting
only and may return `(0, 0)` on failure; eligibility must never depend on those
counts.

- [ ] **Step 5: Run the first seven core tests**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -k "candidate or dirty or classify" -v
```

Expected: seven named core tests pass.

### Task 2.3: Implement nickname-aware candidate discovery

- [ ] **Step 1: Add the finder test with a dict-shaped coordinator response**

The fake must match the real `WorktreeCoordinator.list_worktrees` return shape:

```python
class RecordingCoordinator:
    def __init__(self, worktree_path: Path) -> None:
        self.worktree_path = worktree_path
        self.repo_nicknames: list[str | None] = []

    async def list_worktrees(self, repo_nickname):
        self.repo_nicknames.append(repo_nickname)
        return {
            "success": True,
            "worktrees": [{"path": str(self.worktree_path), "branch": "feat"}],
        }
```

Build a real squash-merged or ancestor worktree, call:

```python
candidates = await find_merged_worktrees(
    repo,
    repo_nickname="vishnu",
    coordinator=coordinator,
)
assert coordinator.repo_nicknames == ["vishnu"]
assert candidates[0].repo_nickname == "vishnu"
assert candidates[0].dirty_status == "clean"
```

Then add an untracked file and prove default scope returns `[]`,
`include_dirty=True` returns one `dirty` candidate, and a monkeypatched
`_git_dirty_count` returning `"undetermined"` returns `[]` even when
`include_dirty=True`.

- [ ] **Step 2: Implement the exact finder signature and filtering rules**

```python
async def find_merged_worktrees(
    repo_path: Path,
    *,
    repo_nickname: str | None = None,
    main_branch: str = "main",
    include_dirty: bool = False,
    ttl_days: int = 0,
    registry_lookup: Callable[[str], str | None] | None = None,
    coordinator: WorktreeCoordinator | None = None,
) -> list[WorktreePruneCandidate]:
```

Required coordinator path:

```python
    if coordinator is not None:
        try:
            listed = await coordinator.list_worktrees(
                repo_nickname=repo_nickname,
            )
        except Exception:
            return []
        if not listed.get("success"):
            return []
        paths = [
            Path(entry["path"])
            for entry in listed.get("worktrees", [])
            if isinstance(entry, dict) and entry.get("path")
        ]
    else:
        paths = _direct_worktree_paths(repo_path)
```

`_direct_worktree_paths` exists only for isolated core tests and offline direct
use. It must parse `git worktree list --porcelain` by collecting lines that
start with `worktree ` and return `[]` on timeout, `OSError`, or non-zero exit.
Do not fall back to direct Git after a coordinator call fails: provider failure
is uncertainty and must fail closed.

Required candidate filtering:

```python
    resolved_nickname = repo_nickname or repo_path.name
    candidates: list[WorktreePruneCandidate] = []
    for worktree_path in paths:
        if worktree_path.resolve() == repo_path.resolve():
            continue
        branch = _git_current_branch(worktree_path)
        if branch is None or branch == main_branch:
            continue

        merge_status = classify_merge_status(
            worktree_path,
            main_branch=main_branch,
        )
        if merge_status != "merged":
            continue

        dirty_status = _git_dirty_count(worktree_path)
        if dirty_status == "undetermined":
            continue
        if dirty_status == "dirty" and not include_dirty:
            continue

        ahead, behind = _git_ahead_behind(worktree_path, main_branch)
        last_touched_at = (
            registry_lookup(str(worktree_path)) if registry_lookup else None
        )
        if ttl_days > 0 and last_touched_at:
            try:
                touched = datetime.fromisoformat(
                    last_touched_at.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if (datetime.now(UTC) - touched).days < ttl_days:
                continue

        candidates.append(
            WorktreePruneCandidate(
                repo_path=repo_path,
                repo_nickname=resolved_nickname,
                worktree_path=worktree_path,
                branch=branch,
                ahead=ahead,
                behind=behind,
                dirty_status=dirty_status,
                last_touched_at=last_touched_at,
                merge_status=merge_status,
            )
        )

    return sorted(candidates, key=lambda candidate: str(candidate.worktree_path))
```

- [ ] **Step 3: Run test 8**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py::test_find_merged_worktrees_threads_nickname_and_filters_dirty_state -v
```

Expected: pass, including the captured `"vishnu"` coordinator argument.

### Task 2.4: Implement safe two-phase removal and sweep audit events

- [ ] **Step 1: Extend `WorktreeAuditLogger`**

Add synchronous methods for these event types:

- `worktree_prune_merged_attempt`
- `worktree_prune_merged_success`
- `worktree_prune_merged_failure`

The attempt event records `candidate_count`, `ttl_days`, and `include_dirty`.
The success event records `removed_count`, `failed_paths`, and `backup_paths`,
with `result="partial"` when `failed_paths` is non-empty. The failure event
records the error. Since this tranche has one trigger, record
`trigger="cli"`; do not accept hook/cron trigger values yet.

- [ ] **Step 2: Add result model and forceable safety checks**

```python
@dataclass(frozen=True)
class WorktreePruneResult:
    candidate: WorktreePruneCandidate
    success: bool
    backup_path: str | None
    error: str | None
    escalated: bool = False


_FORCEABLE_SAFETY_CHECKS = frozenset(
    {"uncommitted_changes", "dependency_block"}
)


def _requires_force(result: dict[str, object]) -> bool:
    return bool(result.get("force_required")) or (
        result.get("safety_check") in _FORCEABLE_SAFETY_CHECKS
    ) or result.get("error") == "force-required"
```

Checking `safety_check` is required because the current coordinator returns
`"uncommitted_changes"` or `"dependency_block"`; it does not set
`force_required` in those paths.

- [ ] **Step 3: Implement `WorktreePruner.remove`**

Required behavior:

1. Reject any candidate whose `merge_status != "merged"` or whose
   `dirty_status == "undetermined"` before calling the coordinator.
2. Require `force_reason` when any candidate is dirty.
3. Call `remove_worktree(force=False, force_reason=None)` first.
4. Escalate only when `_requires_force(first_result)` is true.
5. On escalation, pass `force=True` and the operator reason, or
   `"merged worktree dependency cleanup"` for a clean dependency block.
6. Catch per-candidate exceptions and convert them to failed
   `WorktreePruneResult` values so later candidates are still attempted.
7. Log a sweep result after all candidates are processed.

The critical coordinator call shape is:

```python
first_result = await self._coordinator.remove_worktree(
    repo_nickname=candidate.repo_nickname,
    worktree_path=str(candidate.worktree_path),
    force=False,
    force_reason=None,
    user_id=None,
)
```

The escalation call is:

```python
result = await self._coordinator.remove_worktree(
    repo_nickname=candidate.repo_nickname,
    worktree_path=str(candidate.worktree_path),
    force=True,
    force_reason=(
        force_reason or "merged worktree dependency cleanup"
    ),
    user_id=None,
)
```

Do not assert the coordinator is present in production code. Require it in the
constructor or raise a project exception before starting the sweep.

- [ ] **Step 4: Write tests 9 and 10**

For the force-escalation test, return this sequence from the fake coordinator:

```python
{"success": False, "safety_check": "uncommitted_changes", "error": "dirty"}
{"success": True, "backup_path": "/tmp/backup"}
```

Assert the two calls use `force=False` then `force=True`, the second reason is
the supplied reason, and `result.escalated is True`.

For the unmerged test, construct a candidate with
`merge_status="not_merged"`, call `remove`, assert `ValueError`, and assert the
fake coordinator's call list remains empty.

- [ ] **Step 5: Run the Wave 2 matrix**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -v
```

Expected at this checkpoint: **10 core tests pass**.

- [ ] **Step 6: Commit Wave 2**

```bash
git add mahavishnu/core/worktree_prune_merged.py \
  mahavishnu/core/worktree_audit.py \
  tests/unit/test_worktree_prune_merged.py
git commit -m "feat(worktree): add fail-closed merged-worktree pruner"
```

**Integration Contract (Wave 2):**

- **Triggered from:** Wave 3 imports the core finder and pruner at module scope.
- **Returns to / updates:** coordinator provider registry, worktree filesystem,
  conditional dirty-worktree backup storage, and persistent audit log.
- **Demonstrable by:** ten core tests pass, including a real squash merge and a
  real unmerged merge-commit guard.
- **Rollback signal:** any classifier result that removes `not_merged` or
  `undetermined`, any dirty-status failure treated as clean, or any coordinator
  removal call made before the defensive guard.
- **Observability added:** sweep-level `worktree_prune_merged_attempt`,
  `worktree_prune_merged_success`, and `worktree_prune_merged_failure` events.

---

## Wave 3 — CLI Subcommand (1.25 hours)

**Goal:** Expose the core only through `mahavishnu worktree prune-merged`, with
correct nickname resolution, app-loading test seams, clean JSON, and non-zero
partial-failure status.

**Files:**

- Edit: `mahavishnu/worktree_cli.py`
- Edit: `tests/unit/test_worktree_prune_merged.py`

There is no MCP task in this wave.

### Task 3.1: Add FakeApp-backed CLI fixtures

- [ ] **Step 1: Add these fixtures to the unit test file**

```python
class FakeCoordinator:
    async def list_worktrees(self, repo_nickname):
        return {"success": True, "worktrees": []}

    async def remove_worktree(
        self,
        repo_nickname,
        worktree_path,
        force,
        force_reason,
        user_id,
    ):
        return {"success": True, "backup_path": "/tmp/backup"}

    async def get_worktree_safety_status(self, repo_nickname, worktree_path):
        return {
            "uncommitted_changes": False,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": [],
        }


class FakeRepo:
    def __init__(self, path, nickname):
        self.path = Path(path)
        self.nickname = nickname
        self.name = nickname


class FakeRepoManager:
    def __init__(self, repos):
        self._repos = repos

    def get_repo(self, key):
        for repo in self._repos:
            if key in (repo.name, repo.nickname):
                return repo
        return None

    def list_repos(self):
        return self._repos


class FakeApp:
    def __init__(self, repos):
        self.worktree_coordinator = FakeCoordinator()
        self.repo_manager = FakeRepoManager(repos)

    async def initialize_worktree_coordinator(self):
        pass

    @classmethod
    def load(cls):
        return cls([FakeRepo("/tmp/fake", "fake")])
```

Every CLI test must patch the real app loader before invoking Typer:

```python
monkeypatch.setattr(
    "mahavishnu.worktree_cli.MahavishnuApp.load",
    classmethod(lambda cls: FakeApp.load()),
)
```

This prevents each test from loading the real settings, providers, and
repository catalog.

### Task 3.2: Implement the CLI command

- [ ] **Step 1: Add module-level imports**

The finder and pruner must be module-level so tests can monkeypatch them:

```python
from pathlib import Path

from .core.worktree_prune_merged import WorktreePruner, find_merged_worktrees
```

Keep `MahavishnuApp` and `SessionWorktreeRegistry` at module level as they are
used by the command and tests.

- [ ] **Step 2: Add repository-manager compatibility helpers locally**

The current production app exposes its manager through
`app.worktree_coordinator.repo_manager`, while the requested test seam exposes
`app.repo_manager`. Resolve both without modifying `app.py` or
`repo_manager.py`:

```python
def _worktree_repo_manager(app):
    direct = getattr(app, "repo_manager", None)
    if direct is not None:
        return direct
    coordinator = getattr(app, "worktree_coordinator", None)
    return getattr(coordinator, "repo_manager", None)


def _configured_repos(repo_manager):
    list_repos = getattr(repo_manager, "list_repos", None)
    if callable(list_repos):
        return list_repos()
    filter_repos = getattr(repo_manager, "filter", None)
    if callable(filter_repos):
        return filter_repos()
    return []
```

The `list_repos()` path is the canonical requested path and is exercised by
FakeApp. The `filter()` branch is compatibility with the currently checked-in
`RepositoryManager` API.

- [ ] **Step 3: Add the Typer signature**

```python
@worktree_app.command("prune-merged")
def prune_merged_worktrees(
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Limit to one configured repo name or nickname",
    ),
    ttl_days: int = typer.Option(
        0,
        "--ttl-days",
        min=0,
        help="Only include worktrees last touched at least N days ago",
    ),
    include_dirty: bool = typer.Option(
        False,
        "--include-dirty",
        help="Include merged dirty worktrees; requires --force-reason",
    ),
    force_reason: str | None = typer.Option(
        None,
        "--force-reason",
        help="Reason required for forced dirty-worktree removal",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview candidates without removing them",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit one machine-readable JSON document",
    ),
) -> None:
    """Remove worktrees whose changes are already represented on main.

    Explicit CLI invocation is the only permitted trigger. Default clean
    removals do not create backups. Dirty removals require --include-dirty
    plus --force-reason and are backed up by WorktreeCoordinator before its
    forced removal path.
    """
```

Do not add `--trigger` or `--exclude-session`; those exist only in the deferred
automation design.

- [ ] **Step 4: Resolve repositories and pass canonical nicknames**

Inside the async command body:

```python
app = MahavishnuApp.load()
await app.initialize_worktree_coordinator()
coordinator = app.worktree_coordinator
if coordinator is None:
    typer.echo("WorktreeCoordinator not available", err=True)
    raise typer.Exit(code=1)

repo_manager = _worktree_repo_manager(app)
if repo_manager is None:
    typer.echo("Repository manager not available", err=True)
    raise typer.Exit(code=1)

if repo is not None:
    repo_info = repo_manager.get_repo(repo)
    if repo_info is None:
        typer.echo(f"Repo not found: {repo}", err=True)
        raise typer.Exit(code=1)
    repo_infos = [repo_info]
else:
    repo_infos = list(_configured_repos(repo_manager))
```

Before candidate discovery, reject `include_dirty and not force_reason` with
exit code 1.

For every resolved repo, pass both the path and nickname:

```python
candidates = []
for repo_info in repo_infos:
    if not repo_info.nickname:
        typer.echo(
            f"Repo has no canonical nickname: {repo_info.name}",
            err=True,
        )
        raise typer.Exit(code=1)
    candidates.extend(
        await find_merged_worktrees(
            Path(repo_info.path),
            repo_nickname=repo_info.nickname,
            include_dirty=include_dirty,
            ttl_days=ttl_days,
            registry_lookup=registry_lookup,
            coordinator=coordinator,
        )
    )
```

This is the required nickname flow:

`--repo` → `repo_manager.get_repo(repo)` → `repo_info.nickname` →
`find_merged_worktrees(repo_nickname=...)` →
`coordinator.list_worktrees(repo_nickname=...)`.

When `--repo` is omitted, `_configured_repos` calls
`repo_manager.list_repos()` when available and applies the same flow to every
returned repository.

- [ ] **Step 5: Make JSON output exclusive**

For `--dry-run --json`, emit only the JSON document. Do not print a human
heading before it. Candidate JSON uses `dirty_status`, not `dirty_count`:

```python
{
    "branch": candidate.branch,
    "repo_nickname": candidate.repo_nickname,
    "worktree_path": str(candidate.worktree_path),
    "behind": candidate.behind,
    "dirty_status": candidate.dirty_status,
    "last_touched_at": candidate.last_touched_at,
}
```

For a dry run with no candidates, JSON is:

```json
{"candidates": [], "would_remove": 0}
```

Human output remains concise and ends with
`No merged worktrees to remove.` when empty.

- [ ] **Step 6: Apply removals and return failure status correctly**

After rendering all human or JSON results, add:

```python
if any(not result.success for result in results):
    raise typer.Exit(code=1)
```

This line must execute after output so operators receive the complete partial
result while shells and callers receive failure status.

### Task 3.3: Add five CLI tests

Append these five tests, bringing the unit file total to 15:

| # | Test | Assertion |
|---:|---|---|
| 11 | `test_cli_prune_merged_lists_candidates` | FakeApp loader is patched; a single-repo dry run succeeds and prints the branch. |
| 12 | `test_cli_prune_merged_threads_resolved_nickname` | `--repo=fake` causes fake finder to receive `repo_nickname="fake"`, not `Path.name` inference. |
| 13 | `test_cli_prune_merged_without_repo_iterates_all_nicknames` | A two-repo FakeApp causes two finder calls with both canonical nicknames. |
| 14 | `test_cli_prune_merged_json_is_single_document` | `json.loads(result.stdout)` succeeds and uses `dirty_status`. |
| 15 | `test_cli_prune_merged_partial_failure_exits_one` | Fake pruner returns one success and one failure; output includes both and exit code is 1. |

Each test includes the required loader patch:

```python
monkeypatch.setattr(
    "mahavishnu.worktree_cli.MahavishnuApp.load",
    classmethod(lambda cls: FakeApp.load()),
)
```

For test 13, temporarily replace `FakeApp.load` with a classmethod that returns:

```python
FakeApp(
    [
        FakeRepo("/tmp/folder-one", "one"),
        FakeRepo("/tmp/folder-two", "two"),
    ]
)
```

Then retain the required `MahavishnuApp.load` patch and assert the captured
nickname sequence is `["one", "two"]`.

For test 15, monkeypatch the module-level `WorktreePruner` with a fake whose
async `remove` returns two result objects. The failed object has
`success=False`, `error="provider failed"`, and `backup_path=None`. Assert the
CLI prints/serializes both before it exits 1.

- [ ] **Step 1: Run only CLI tests**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -k "cli" -v
```

Expected: five CLI tests pass.

- [ ] **Step 2: Run the full feature unit file**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -v
```

Expected: **15 tests pass**: 10 core tests plus 5 CLI tests.

- [ ] **Step 3: Commit Wave 3**

```bash
git add mahavishnu/worktree_cli.py tests/unit/test_worktree_prune_merged.py
git commit -m "feat(worktree-cli): add explicit prune-merged command"
```

**Integration Contract (Wave 3):**

- **Triggered from:** direct user invocation of
  `mahavishnu worktree prune-merged` only.
- **Returns to / updates:** provider-backed worktree removal, conditional dirty
  backups, structured audit events, stdout/stderr, and process exit status.
- **Demonstrable by:** 15 unit tests pass; `--dry-run --json` is parseable as one
  JSON document; a partial fake result exits 1.
- **Rollback signal:** nickname mismatch, malformed JSON, a partial sweep that
  exits 0, or any automated trigger appearing in the command.
- **Observability added:** human summary, JSON result per candidate, process exit
  code, and sweep audit events with CLI attribution.

---

## Wave 4 — Documentation, Tracking, Validation, and Manual Testing (1 hour)

**Goal:** Document the CLI's real safety contract, remove hook artifacts, run
quality gates, and validate the user path manually before any automation is
considered.

**Files:**

- Create: `docs/WORKTREE_AUTOREMOVE.md`
- Create: `docs/feature-tracking/worktree-autoremove.yaml`
- Delete if present: `tests/integration/test_worktree_autoprune_hook.py`

### Task 4.1: Write the CLI-only operator guide

- [ ] **Step 1: Create `docs/WORKTREE_AUTOREMOVE.md`**

```markdown
---
title: Worktree Prune-Merged CLI
status: active
date: 2026-07-26
audience: operators
---

# Worktree Prune-Merged CLI

`mahavishnu worktree prune-merged` is an explicitly invoked command for
removing worktrees whose changes are already represented on the repository's
main branch. SessionEnd and cron automation are deferred and are not installed
or permitted by the current policy amendment.

## Quick reference

```bash
# Preview all configured repos
mahavishnu worktree prune-merged --dry-run

# Preview one repo by name or nickname
mahavishnu worktree prune-merged --repo=dhara --dry-run

# Remove merged-clean candidates in one repo
mahavishnu worktree prune-merged --repo=dhara

# Include merged dirty candidates; reason is mandatory
mahavishnu worktree prune-merged --repo=dhara --include-dirty \
  --force-reason "reviewed dirty merged worktrees"

# Machine-readable preview
mahavishnu worktree prune-merged --dry-run --json
```

## Classification

The command fails closed and uses these signals in order:

1. Resolve `main`; if absent, try `master`.
2. If `HEAD` is an ancestor of the target branch, classify `merged`.
3. Otherwise inspect `<target>..HEAD` for merge commits. If any exist,
   classify `undetermined`, because `git cherry` excludes merge commits.
4. Only when there are no feature-only merge commits, use `git cherry` for
   patch equivalence. No `+` lines means `merged`; any `+` line means
   `not_merged`.
5. Any subprocess error or timeout means `undetermined`.

Dirty state is also tri-state: `clean`, `dirty`, or `undetermined`.
`undetermined` is never eligible. `dirty` is eligible only with
`--include-dirty`.

## Repository nicknames

`--repo` accepts a configured name, package, or nickname. The CLI resolves the
repository through `RepositoryManager.get_repo`, then passes its canonical
`repo_info.nickname` through candidate discovery and coordinator listing. This
matters for repositories such as `mahavishnu`, whose folder name and nickname
(`vishnu`) differ.

## Removal and backups

Every candidate is first sent to
`WorktreeCoordinator.remove_worktree(force=False)`. The pruner escalates only
when the coordinator reports a forceable safety block.

- **Default merged-clean removal:** no backup is created. The branch remains
  available, and Git reflog can recover commits if needed. Recreate the
  worktree with `git worktree add <path> <branch>`.
- **`--include-dirty` removal:** the coordinator detects uncommitted changes,
  requires the supplied reason, creates a backup under
  `~/.local/share/mahavishnu/worktree_backups/`, and only then performs forced
  removal.

The command does not guarantee a backup for every removal.

## Exit status

- `0`: every candidate succeeded, or the candidate list was empty.
- `1`: setup failed, validation failed, or one or more candidates failed.

On partial failure, the command prints or serializes all candidate results
before exiting 1.

## Audit log

Applied sweeps write `worktree_prune_merged_attempt` followed by
`worktree_prune_merged_success` or `worktree_prune_merged_failure`.
A success event with failed paths is marked partial.

```bash
grep worktree_prune_merged ~/.local/state/mahavishnu/audit.log | tail -10
```

## Manual testing

Run these phases in order. Do not install an automated trigger after only the
unit tests; this sequence is the adoption gate.

```bash
# Phase 1: dry-run preview
mahavishnu worktree prune-merged --dry-run --json

# Phase 2: apply to a single repo
mahavishnu worktree prune-merged --repo=dhara --dry-run
mahavishnu worktree prune-merged --repo=dhara

# Phase 3: verify backups
# Default clean removals do not create a backup; use this after an explicitly
# reviewed --include-dirty test if backup behavior is being validated.
ls -lt ~/.local/share/mahavishnu/worktree_backups/ | head -10

# Phase 4: verify audit log
grep worktree_prune_merged ~/.local/state/mahavishnu/audit.log | tail -10

# Phase 5: spot-check that the correct worktrees were removed
git -C /Users/les/Projects/dhara worktree list

# Phase 6: rerun to confirm idempotency
mahavishnu worktree prune-merged --dry-run
# Expected: "✅ No merged worktrees to remove."
```

Record the exact command output and any unexpected candidate before changing
the feature-tracking state to `wired`.

## Policy

`.claude/decisions/worktree-autoremove-policy.md` explicitly amends
`session-worktree-defaults.md` Rule 2 for this user-invoked CLI. It does not
permit SessionEnd or cron automation.
```

### Task 4.2: Remove hook integration tests and record deferral

- [ ] **Step 1: Delete the hook integration test if it exists**

```bash
rm -f tests/integration/test_worktree_autoprune_hook.py
```

Do not replace it with a skipped file. The hook does not exist in the active
feature, so an active integration test would misstate the product surface.

- [ ] **Step 2: Create the feature-tracking record**

Create `docs/feature-tracking/worktree-autoremove.yaml` as valid YAML:

```yaml
name: worktree-autoremove
owner: mahavishnu
created: 2026-07-26
last_updated: 2026-07-26
state: built
built: true
wired: false
adopted: false
entry_point: mahavishnu.worktree_cli.prune_merged_worktrees
trigger: explicit user CLI invocation only
integration_point: WorktreeCoordinator.remove_worktree
observability:
  - worktree_prune_merged_attempt
  - worktree_prune_merged_success
  - worktree_prune_merged_failure
end_to_end_check: >-
  mahavishnu worktree prune-merged --repo=dhara --dry-run
blocker: >-
  Wave 4 manual testing has not yet validated dry-run, single-repo apply,
  audit output, worktree removal, and idempotency.
next_action: >-
  Operator runs the Wave 4 Manual testing sequence and records the outcome;
  only then change state to wired.
deferred:
  session_end_hook: true
  cron_wrapper: true
  hook_integration_tests: true
  implementation_gate: >-
    Implement only after the CLI is validated by manual testing per the
    Wave 4 Manual testing section and a separate policy decision permits
    unattended execution.
related:
  plan: docs/superpowers/plans/2026-07-26-worktree-autoremove.md
  policy: .claude/decisions/worktree-autoremove-policy.md
  user_docs: docs/WORKTREE_AUTOREMOVE.md
```

After successful manual testing, update only these fields in a follow-up:

```yaml
state: wired
wired: true
blocker: Automation remains deferred; CLI wiring is validated.
next_action: Observe manual use before proposing an automation decision.
```

### Task 4.3: Run automated validation

- [ ] **Step 1: Run the feature unit tests**

```bash
uv run pytest tests/unit/test_worktree_prune_merged.py -v
```

Expected: **15 passed**. There is no hook integration test file and no hook test
count.

- [ ] **Step 2: Run quality checks**

```bash
uv run crackerjack run --no-ai-fix
```

Expected: no new errors.

- [ ] **Step 3: Run the orphan audit**

```bash
uv run python scripts/audit_orphans.py
```

Expected active callers:

| Symbol | Caller |
|---|---|
| `WorktreePruneCandidate` | core finder, CLI serialization, unit tests |
| `classify_merge_status` | core finder, real-Git tests |
| `find_merged_worktrees` | CLI |
| `WorktreePruner` | CLI |
| `prune_merged_worktrees` | Typer command registration |

There should be no hook or cron symbol to audit.

- [ ] **Step 4: Run the six-phase manual testing sequence from the docs**

Do not replace the sequence with a broad all-repo apply. Start with dry-run and
one repository exactly as documented.

- [ ] **Step 5: Update feature state only after evidence exists**

If every manual phase succeeds, update the tracking file from `built` to
`wired` and retain the automation deferral. If any phase fails, leave it
`built`, record the blocker, and do not implement the deferred appendix.

- [ ] **Step 6: Commit Wave 4**

```bash
git add docs/WORKTREE_AUTOREMOVE.md \
  docs/feature-tracking/worktree-autoremove.yaml
git add -u tests/integration/test_worktree_autoprune_hook.py
git commit -m "docs(worktree): document and validate prune-merged CLI"
```

**Integration Contract (Wave 4):**

- **Triggered from:** an operator follows `docs/WORKTREE_AUTOREMOVE.md`.
- **Returns to / updates:** worktree filesystem, audit log, optional dirty
  backup directory, and feature-tracking state.
- **Demonstrable by:** 15 unit tests pass and the six manual phases show correct
  preview, one-repo removal, audit evidence, spot-check, and idempotency.
- **Rollback signal:** an unexpected candidate, missing audit record, partial
  apply, or non-idempotent second dry run; leave tracking at `built` and stop.
- **Observability added:** operator-visible JSON/human output, audit events, and
  a feature-tracking blocker/next action.

---

## DEFERRED — SessionEnd hook + cron wrapper

> **Do not implement this appendix in the active four waves.** Implement only
> after the CLI is validated by manual testing per the Wave 4 **Manual testing**
> section, and only after a separate decision permits unattended execution.

### Deferred items

1. `.claude/hooks/worktree-autoprune.py` SessionEnd hook.
2. SessionEnd registration in `.claude/settings.json`.
3. `scripts/autoprune-worktrees.sh` cron wrapper.
4. `tests/integration/test_worktree_autoprune_hook.py`.
5. Runtime configuration through
   `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS` and optional dirty-mode gates.
6. Any settings schema used solely by those triggers.

### Preserved design intent

- **Hook gate:** default off. A positive
  `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS` would enable a TTL-limited CLI call;
  unset, invalid, or non-positive values would be a no-op.
- **Cron wrapper:** invoke the same CLI rather than duplicate pruning logic,
  export a deterministic PATH such as
  `$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin`, disable
  interactive Git prompts, propagate non-zero CLI status, and write timestamped
  output.
- **Single mechanism:** both future triggers must call the validated CLI/core;
  neither may implement an independent merge classifier or deletion path.
- **Dirty automation:** remain off by default and require a separately reviewed
  force-reason/backup policy.

### Blockers to re-evaluate before reintroduction

1. **Hook payload type mismatch.** Verify the current `_hook_io.read_session_payload`
   return type. The prior design treated it as a `dict`, while the helper may
   return a `HookPayload` object. Tests must use the real API, not a dict-shaped
   assumption.
2. **Same-session self-prune guard.** Define how the SessionEnd payload's full
   session ID maps to `SessionWorktreeRegistry.session_id_short`, and prove the
   hook's own worktree cannot become a candidate during that invocation.
3. **Ordering.** If the existing isolation hook marks a session abandoned first,
   prove hook ordering in `.claude/settings.json` and prove the new sweep cannot
   race that state transition.
4. **Timeout budget.** Reassess whether a cross-repository sweep belongs in a
   SessionEnd hook at all. A hook must not stall session shutdown or outlive its
   caller unexpectedly.
5. **Concurrent sweeps.** Re-evaluate hook/cron overlap, per-worktree races, and
   whether no-candidate idempotency is enough when both processes classify
   before either removes.
6. **Environment and PATH.** Smoke-test the wrapper under a near-empty cron
   environment and the hook under Claude Code's actual environment.
7. **Exit propagation.** Preserve the active CLI's exit-1-on-partial-failure
   contract through hook stderr and cron logging.
8. **Backup semantics.** Do not reintroduce the false claim that every removal is
   backed up; only forced dirty removal gets the current coordinator backup.
9. **Provider listing fidelity.** Validate both Session-Buddy and Direct Git
   provider list shapes before trusting unattended candidate discovery.
10. **Separate policy approval.** Add an explicit amendment permitting each
    automation trigger; the active policy intentionally prohibits both.

### Deferred acceptance gate

Automation may be proposed only when all of the following are true:

- Wave 4 manual testing has been completed and recorded.
- Feature tracking is `wired: true` for the CLI.
- At least one manual applied sweep has correct audit evidence.
- A second dry run proves idempotency.
- The payload, self-prune, concurrency, PATH, and timeout blockers above have
  executable tests.
- A separate decision explicitly permits unattended triggers.

### Resolution of the previously-blocked issues

The deferred work was deferred because of unresolved design issues:

- **HookPayload vs dict mismatch**: the original hook tried to access
  `payload["session_id"]` but `read_session_payload()` returns a `HookPayload`
  object. Resolution: use `payload.session_id` directly.

- **Same-session self-prune**: with a 7-day TTL gate, a SessionEnd event
  firing immediately after `mark_abandoned` would not self-prune. But a
  smaller TTL or future change could. Resolution: the hook must read its own
  session_id from the payload and pass `--exclude-session=<short>` to the CLI.

- **PATH resolution under cron**: cron environments have minimal PATH.
  Resolution: `export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"`
  at the top of the cron wrapper.

- **Provider-registry routing**: the CLI must resolve the repo's nickname
  once and pass it through to `find_merged_worktrees`. The CLI does this
  correctly; the deferred hook must replicate the pattern.

### Why deferred

Two reasons:

1. **Operator agency**: the policy file explicitly excludes automation. The
   CLI is the safe-by-default alternative.

2. **Bug amplification**: when the CLI is wrong, one operator notices. When
   the hook is wrong, every Claude session notices. The CLI gates the trust
   that the hook needs.

---

## Estimate

| Wave | Time | Notes |
|---|---:|---|
| 1 — Policy | 20 min | Narrow Rule 2 amendment and index. |
| 2 — Core | 2 hr | Multi-signal merge detection, tri-state dirty status, nickname-aware finder, pruner, 10 tests. |
| 3 — CLI | 1.25 hr | Typer command, FakeApp seam, nickname threading, 5 CLI tests, partial failure exit. |
| 4 — Docs + validation | 1 hr | CLI-only guide, tracking, hook-test deletion, automated and manual checks. |
| **Active total** | **~4.5 hr** | Excludes deferred automation. |

## Active Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `git cherry` hides an unmerged merge commit | Ancestry first; merge-commit guard before patch equivalence; real regression test. |
| Git status failure appears clean | Tri-state dirty status; `undetermined` always excluded. |
| Squash/rebase/cherry-pick appears unmerged | Patch-equivalence check runs only after the merge-commit guard. |
| Folder name is passed where coordinator expects nickname | CLI resolves once and threads `repo_info.nickname` end to end. |
| Actual coordinator safety response does not set `force_required` | Escalation also recognizes `safety_check` values `uncommitted_changes` and `dependency_block`. |
| Clean removal is advertised as backed up | Policy and docs distinguish branch/reflog recovery from dirty forced backups. |
| Partial sweep exits successfully | Render all results, then raise `typer.Exit(code=1)` if any failed. |
| An automated trigger sneaks into scope | Policy prohibits it; no hook, settings, script, env-var job, or MCP task exists in active waves. |

## Known Follow-ups / Unresolved Findings

1. The checked-in app currently exposes the production manager as
   `app.worktree_coordinator.repo_manager`, and `RepositoryManager` exposes
   `filter()` rather than `list_repos()`. Wave 3 contains a CLI-local compatibility
   shim while still exercising the required `repo_manager.list_repos()` path in
   FakeApp. Unifying the app-level manager API is outside this scope.
2. `WorktreeCoordinator.remove_worktree` creates a dirty backup internally but
   returns the provider payload without explicitly adding its local
   `backup_path`. The backup exists and is auditable, but CLI JSON may show
   `backup_path: null` unless the provider includes it. Updating the coordinator
   return contract is outside this plan and must not be papered over in docs.
3. `DirectGitWorktreeProvider.list_worktrees` should be manually validated
   against real `git worktree list --porcelain` output before unattended use.
   This is not allowed to block the explicit CLI's initial dry-run/manual gate,
   but it is a hard blocker for the deferred automation proposal.
4. `docs/feature-tracking/TEMPLATE.md` is Markdown, while the requested tracking
   path has a `.yaml` suffix. This plan uses valid YAML at the requested path;
   standardizing feature-tracking serialization is a separate repository-wide
   decision.

## Reference Patterns

- `mahavishnu worktree prune-abandoned` — Typer command and registry lookup
  pattern, but it removes registry entries only.
- `mahavishnu/core/worktree_coordination.py` — correct coordinator filename and
  the only filesystem-removal entry point used here.
- `WorktreeBackupManager.create_backup_before_removal` — dirty forced-removal
  backup path, not a universal removal guarantee.
- `WorktreeAuditLogger` — sweep and per-removal audit integration.
- `settings/repos.yaml` — proves nickname/folder-name mismatches such as
  `mahavishnu` → `vishnu` and `session-buddy` → `buddy`.

## Consolidated Active File Count

- **Create (4):** policy decision, core module, unit test file, operator guide.
- **Create tracking (1):** `docs/feature-tracking/worktree-autoremove.yaml`.
- **Edit (3):** decision index, worktree audit logger, worktree CLI.
- **Delete (1):** hook integration test if present.
- **Deferred/not touched:** hook, hook settings, cron wrapper, automation config,
  MCP tool.
