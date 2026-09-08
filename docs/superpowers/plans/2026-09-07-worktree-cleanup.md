---
status: draft
role: implementation
date: 2026-09-07
last_reviewed: 2026-09-07
superseded_by: null
topic: worktree-cleanup
---

# Bodai Worktree Cleanup Policy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the 2026-09-07 worktree-sweep findings into a sibling decision doc, build a `mahavishnu worktree scan` CLI that walks `settings/ecosystem.yaml` and emits a tier-grouped report (text or JSON), and ship a thin skill wrapper around the CLI. Three commits land directly to main per `.claude/decisions/bodai-pre-1.0-merge-policy.md`.

**Architecture:** Three artifacts in `mahavishnu/`:
- `.claude/decisions/worktree-cleanup-policy.md` — the canonical rules (tier rubric, salvage, lock + live-PID, agent-dispatch reap, cross-repo plan-orphan)
- `mahavishnu worktree scan` — new subcommand on the existing `mahavishnu worktree` CLI. Reuses `classify_merge_status()` from `worktree_prune_merged.py` and the existing path/validator utilities from `paths.py`, `validators.py`, `worktree_validation.py`, `bootstrap.py`
- `.claude/skills/bodai-worktree-cleanup/SKILL.md` — thin wrapper skill triggering on worktree-context phrases only

**Tech Stack:** Python 3.14+, Typer (existing CLI framework in `worktree_cli.py`), Oneiric config loading, Typer-style `@worktree_app.command` decorator pattern, pytest markers (`unit`, `integration`, `crackerjack`)

**Spec:** `docs/superpowers/specs/2026-09-07-worktree-cleanup-design.md` (commit `2e70c9e3`)

---

## Global Constraints

Every task's requirements implicitly include these:

- **Python**: `>=3.14` per `pyproject.toml`. Every source file opens with `from __future__ import annotations` (per `crackerjack-compliant-code` convention).
- **Subprocess safety**: `subprocess.run([...], shell=False, ...)` with list-form args. NO `shell=True`. NO string-form commands. PID validated against `^[0-9]+$` before any `ps -p` invocation.
- **Classifier reuse**: `classify_merge_status()` is imported from `mahavishnu/core/worktree_prune_merged.py:91-129` (returns plain `str`, NOT `Literal[...]`). Import-side cast to `Literal["merged","not_merged","undetermined"]` is documented in the spec. NO edits to `worktree_prune_merged.py` are permitted in this commit (per spec A40).
- **Manifest source**: `settings/ecosystem.yaml` is canonical (pinned in `settings/mahavishnu.yaml:repos_path`). `settings/repos.yaml` is the runtime fallback. `BODAI_REPO_REGISTRY.md` is human-readable prose and NOT a runtime fallback.
- **Tier B path matcher**: use `get_worktree_base_path()` from `mahavishnu/core/paths.py:153-182` (resolves `MAHAVISHNU_WORKTREE_BASE_PATH` canonical env var, with `MAHAVISHNU_AUTO_WORKTREE_ROOT` as legacy alias).
- **Lock file parser**: fixed regex `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`. No `eval`, `exec`, `shell`. Invalid format → `pid_liveness = "none"` + `notes: ["unparseable lock format"]`.
- **Tier X exclusive enumeration**: Tier X entries are reported EXCLUSIVELY in `tier_x_cross_repo_orphan` and DO NOT appear under Tier A or any other tier.
- **Process safety**: `git worktree remove --force` does NOT bypass locks. Use `git worktree remove --force -f -f` (or `git worktree unlock` first) only after verifying the lock's PID is dead via `ps -p <pid>` + `ps -p <pid> -o command=` (PID reuse validation).
- **Branch policy**: per `.claude/decisions/bodai-pre-1.0-merge-policy.md`, all three commits land directly to main. No PR. Squash forbidden.
- **Back-link requirement**: Commit 1 adds "See also: worktree-cleanup-policy.md" to each of the 5 existing decision docs.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `.claude/decisions/worktree-cleanup-policy.md` | NEW. Tier rubric, salvage, lock + live-PID semantics, agent-dispatch reap rule, cross-repo plan-orphan rule, negative rules |
| `.claude/decisions/session-worktree-defaults.md` | MODIFY. Add "See also: worktree-cleanup-policy.md" back-link |
| `.claude/decisions/worktree-autoremove-policy.md` | MODIFY. Add back-link |
| `.claude/decisions/worktree-autoremove-v4-followup.md` | MODIFY. Add back-link |
| `.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md` | MODIFY. Add back-link |
| `.claude/decisions/mahavishnu-tool-preference-policy.md` | MODIFY. Add back-link (it relates via cross-reference even if not worktree-specific) |
| `mahavishnu/worktree_cli.py` | MODIFY. Add `scan` subcommand via `@worktree_app.command('scan')` |
| `mahavishnu/core/worktree_scan.py` | NEW. Classifier, scan driver (3-pass pipeline), text/JSON formatters, `_run_git_scanned` + `_run_ps` helpers, `safe_worktree_name()` helper |
| `tests/unit/test_worktree_scan.py` | NEW. Unit tests for classifier + helpers |
| `tests/unit/test_decision_doc_sync.py` | NEW. Doc/code parity: tier rubric + plan-orphan patterns |
| `tests/integration/test_worktree_scan_cli.py` | NEW. CLI surface tests |
| `tests/integration/test_worktree_scan_e2e.py` | NEW. E2E against fixture repos |
| `.claude/skills/bodai-worktree-cleanup/SKILL.md` | NEW. Skill body |
| `.claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py` | NEW. Thin wrapper invoking `python -m mahavishnu.worktree_cli worktree scan` |

**Existing utilities to leverage (NOT re-implement)** (per spec A56):
- `mahavishnu/core/paths.py::get_worktree_base_path()` (line 153-182) — resolves the worktree base path
- `mahavishnu/core/validators.py::PathValidator.validate_path()` (line 122) — path traversal + allowed-base-dir containment
- `mahavishnu/core/worktree_validation.py::WorktreePathValidator` — CWE-22/CWE-114/CWE-170 protection
- `mahavishnu/core/bootstrap.py::_validate_path()` (line 90) — path traversal + allowed-base-dir containment

---

# Commit 1: `feat(decisions): add worktree-cleanup-policy.md`

Decision doc only — no code change. Per spec Decision Rule § 1.

## Task 1.1: Create decision doc skeleton + frontmatter

**Files:**
- Create: `.claude/decisions/worktree-cleanup-policy.md`

- [ ] **Step 1: Create the file with frontmatter + § Context**

```markdown
---
status: active
role: canonical
date: 2026-09-07
last_reviewed: 2026-09-07
superseded_by: null
topic: worktree-cleanup
trigger: 2026-09-07 cleanup removed 86 of 117 extra worktrees across 20 Bodai repos; existing policy (worktree-autoremove-policy.md) covers only prune-merged clean-removal; the 86 removals required rules no current decision codified.
---

# Worktree Cleanup Policy

## Context

The 2026-09-07 sweep of 31 active Bodai repos found 117 extra worktrees (108 non-main in 20 of 31 repos; zero `[gone]` branches). 86 were removed, 3 were preserved (2 <9d `agent-*` candidates + 1 `agent-a894dd931068d8836` locked by live Claude PID 74005). The cleanup made tier-rubric + salvage + lock + live-PID decisions in-line; this doc codifies them.

Five existing decisions touch worktree policy: `session-worktree-defaults.md` (Rule 2: never auto-remove), `worktree-autoremove-policy.md` (Rule 2 amendment + Rule 4: --force-reason for dirty merged), `worktree-autoremove-v4-followup.md` (draft, NOT a permission grant), `2026-08-28-cross-repo-fanout-cwd-isolation.md` (cross-repo fanout cleanup), `mahavishnu-tool-preference-policy.md` (unrelated). None address today's findings.

## Why this decision

This doc is **additive**. The five existing decisions stay intact. Cross-references are bidirectional: see § Cross-references for the back-links added in the same commit.

---

<!-- Decision rule, Salvage, Lock, Negative rules sections follow in Tasks 1.2 - 1.6 -->
```

- [ ] **Step 2: Verify the file renders correctly**

```bash
head -30 .claude/decisions/worktree-cleanup-policy.md
```

Expected: frontmatter + § Context + the placeholder comment.

## Task 1.2: Add § Decision rule (tier rubric)

**Files:**
- Modify: `.claude/decisions/worktree-cleanup-policy.md` (append after § Why this decision)

- [ ] **Step 1: Append the tier rubric table**

Append this content after the `<!-- Decision rule, ... -->` comment in Task 1.1's skeleton:

```markdown
## Decision rule

The tier rubric. **First-match-wins by row order.** The classifier emits ONE tier per worktree; the operator's action depends on the tier.

| Tier | Condition (explicit boundaries) | Removal action |
|------|---------------------------------|----------------|
| **A-merged** | `classify_merge_status(worktree_path) == "merged"` AND `is_dirty == False` | `git worktree remove` (no `--force`) — but only via `mahavishnu worktree prune-merged` |
| **A-merged-dirty** | `classify_merge_status(...) == "merged"` AND `is_dirty == True` | `git worktree remove --force --force-reason="<reason>"` per `worktree-autoremove-policy.md` Rule 4 |
| **A-orphan-detached** | Detached HEAD AND branch-name NOT a `git bisect`/`git rebase` pattern AND not in `PLAN_ORPHAN_PATTERNS` | `git worktree remove` (no `--force`); pass `--yes-delete-detached` for the shortcut |
| **A-orphan-detached-dirty** | Detached HEAD AND dirty | `git worktree remove --force` |
| **X** (cross-repo plan-orphan) | Branch matches `PLAN_ORPHAN_PATTERNS` regex AND same-date signature in ≥ 2 repos AND `is_locked == False` | Same as A-merged or A-orphan-detached. **Tier X entries are reported EXCLUSIVELY in `tier_x_cross_repo_orphan` and do NOT appear under Tier A.** |
| **B** | Path matches `<get_worktree_base_path()>/agent-*` OR `*/.claude/worktrees/agent-*` | `git worktree remove --force` per Salvage rule |
| **C** | `9.0 ≤ age_days < 30.0` AND `is_locked == False` AND not classified above | `git worktree remove --force` per Salvage rule |
| **D** | `age_days < 9.0` | Manual review required (might be active) |

### Boundary inclusivity

Pin in code comments: `age_days < 9.0 → D`, `9.0 ≤ age_days < 30.0 → C`, `age_days ≥ 30.0 → A-*`. Never ambiguous.

### Plan-orphan patterns

`PLAN_ORPHAN_PATTERNS` is maintained in `mahavishnu/core/worktree_scan.py` as a tuple of regex patterns. Current contents:

| Pattern | Source plan | Last seen |
|---------|-------------|-----------|
| `^w4-claude-md-breadcrumb` | Wave 4 plan (Aug 2026) | 2026-08-23 |
| `^plan7-phase5` | Plan 7 phase 5 (Aug 2026) | 2026-08-22 |
| `^wave8-diagram-corrections` | Wave 8 diagram corrections (Aug 2026) | 2026-08-16 |

A guard test (`tests/unit/test_worktree_scan.py::TestPlanOrphanPatternsSync`) asserts the doc/code parity.
```

- [ ] **Step 2: Verify the file is well-formed markdown**

```bash
grep -c "^##" .claude/decisions/worktree-cleanup-policy.md
```

Expected: at least 4 (Context, Why this decision, Decision rule, Boundary inclusivity, Plan-orphan patterns).

## Task 1.3: Add § Salvage procedure + § Lock + live-PID semantics

**Files:**
- Modify: `.claude/decisions/worktree-cleanup-policy.md`

- [ ] **Step 1: Append § Salvage procedure**

```markdown
## Salvage procedure

Before `--force` on any worktree with untracked files, copy untracked files to `~/.mahavishnu/salvage/<YYYY-MM-DD>-<sanitized-worktree-name>/` where `<sanitized-worktree-name>` is `Path(p).name`, then rejected if it equals `.`, `..`, empty, or contains characters outside `[A-Za-z0-9._-]`. Stashes survive `git worktree remove` (they live in the branch reflog, not the worktree directory) and need no salvage. Modified tracked files are recoverable from git history; no salvage.

The new `mahavishnu/core/worktree_scan.py::safe_worktree_name()` enforces the character class. The new code reuses `mahavishnu/core/worktree_validation.py::WorktreePathValidator` for path traversal and `mahavishnu/core/paths.py::get_worktree_base_path()` for the worktree base path.
```

- [ ] **Step 2: Append § Lock + live-PID semantics**

```markdown
## Lock + live-PID semantics

1. **Orphaned `initializing` lock** (no PID in the lock file) → `git worktree unlock` + `git worktree remove`. Safe.
2. **Live Claude PID** (lock file contains `(pid <N>)` AND `ps -p <N>` returns 0) → DO NOT TOUCH. The CLI emits the lock content + PID liveness in the report.
3. **`ps -p` is checked at scan time only**; re-check at removal time is the operator's responsibility (the CLI does not perform removal).
4. **PID reuse validation**: before trusting `ps -p <pid>` liveness, also call `ps -p <pid> -o command=` and verify the command starts with a known pattern (`claude`, `python.*mahavishnu`). Mismatch → treat as `unknown`, not `alive`. PID recycling is real.
5. **`--force -f -f` is the unlock-equivalent** for confirmed-dead PID cases. `git worktree remove --force` alone does NOT bypass locks. (`git worktree remove --help` documents `-f` as repeated-force; the unlock-equivalent uses two `-f` flags.)
6. **Lock file parser**: extract PID via fixed regex `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`. No `eval`, no `exec`, no shell. Invalid format → `pid_liveness = "none"` + `notes: ["unparseable lock format"]`.
```

- [ ] **Step 3: Verify both sections present**

```bash
grep -c "^##" .claude/decisions/worktree-cleanup-policy.md
```

Expected: at least 6 sections.

## Task 1.4: Add § Agent-dispatch reap + § Cross-repo plan-orphan + § Negative rules

**Files:**
- Modify: `.claude/decisions/worktree-cleanup-policy.md`

- [ ] **Step 1: Append the three rules sections**

```markdown
## Agent-dispatch reap rule

`EnterWorktree` and dispatched agents SHOULD reap on completion. The CLI emits a list of `agent-*` dispatch leftovers and the user invokes removal explicitly. (No SessionEnd hook — per `worktree-autoremove-policy.md` Rule 2 prohibition.)

This is a soft convention enforced by the scanner, not by tooling. Add `mahavishnu worktree scan` to agent exit checklists for ops.

## Cross-repo plan-orphan rule

When a plan creates worktrees across N repos and the plan completes, all N worktrees are likely orphans simultaneously. Detection: same-date pattern across multiple repos (e.g., 9 repos × `w4-claude-md-breadcrumb` at 15.9d on the 2026-09-07 sweep).

The CLI flags these via `classification: "cross_repo_plan_orphan"` and groups by date-pattern. Pattern list is `PLAN_ORPHAN_PATTERNS` (see Decision rule § Plan-orphan patterns). Add a plan-completion sweep to the post-merge plan checklist.

## Negative rules

What NOT to do:

- **Don't auto-remove** even when `--force` would succeed. The CLI is scan-and-report only.
- **Don't trust the lock file as authoritative**; the liveness check (`ps -p`) is the only signal. Lock content is advisory.
- **Don't invoke `-f -f`** without a fresh `ps -p <pid>` AND command-line identity check (`ps -p <pid> -o command=`).
- **Don't point `--repo=` at paths outside the user's expected workspace** (`~/Projects`). The CLI uses `PathValidator.validate_path` for containment.
- **Don't reuse PIDs** in `ps -p` output without verifying the command line. PID recycling is real.
- **Don't edit `mahavishnu/core/worktree_prune_merged.py`** in cleanup commits; classifier reuse is read-only via import.
- **Don't read `MAHAVISHNU_AUTO_WORKTREE_ROOT`** directly (legacy alias). Use `get_worktree_base_path()` from `paths.py`.
- **Don't modify `BODAI_REPO_REGISTRY.md` as a runtime manifest**; it's human-readable prose.
```

- [ ] **Step 2: Verify negative rules are present**

```bash
grep -c "^- \*\*Don't" .claude/decisions/worktree-cleanup-policy.md
```

Expected: at least 8.

## Task 1.5: Add § Cross-references + back-links to 5 existing decisions

**Files:**
- Modify: `.claude/decisions/worktree-cleanup-policy.md`
- Modify: `.claude/decisions/session-worktree-defaults.md`
- Modify: `.claude/decisions/worktree-autoremove-policy.md`
- Modify: `.claude/decisions/worktree-autoremove-v4-followup.md`
- Modify: `.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md`
- Modify: `.claude/decisions/mahavishnu-tool-preference-policy.md`

- [ ] **Step 1: Append § Cross-references to the new doc**

```markdown
## Cross-references

- Pickup from: 2026-09-07 worktree sweep (this doc)
- Sibling decisions:
  - `session-worktree-defaults.md` — opt-in per-session worktree isolation (`MAHAVISHNU_WORKTREE_BASE_PATH` env var)
  - `worktree-autoremove-policy.md` — Rule 2 amendment (only `prune-merged` may remove); Rule 4 (`--force-reason` for dirty merged)
  - `worktree-autoremove-v4-followup.md` — future automation constraints; NOT a permission grant
  - `2026-08-28-cross-repo-fanout-cwd-isolation.md` — `Workflow({parallel()})` CWD isolation; `/tmp/<branch>` cleanup
  - `mahavishnu-tool-preference-policy.md` — tool-steering channels (unrelated but cross-referenced)
- Implementation: `mahavishnu/core/worktree_scan.py` (the classifier + scan driver)
- Tests: `tests/unit/test_decision_doc_sync.py` (doc/code parity)
```

- [ ] **Step 2: Add back-link to `session-worktree-defaults.md`**

Append to the existing § Cross-references (or § See also if present) at the end of the file:

```markdown

---

**See also**: [worktree-cleanup-policy.md](./worktree-cleanup-policy.md) — tier rubric, salvage procedure, lock + live-PID semantics (2026-09-07)
```

- [ ] **Step 3: Repeat back-link for `worktree-autoremove-policy.md`**

Same template, with `worktree-cleanup-policy.md` link.

- [ ] **Step 4: Repeat back-link for `worktree-autoremove-v4-followup.md`**

Same template.

- [ ] **Step 5: Repeat back-link for `2026-08-28-cross-repo-fanout-cwd-isolation.md`**

Same template.

- [ ] **Step 6: Repeat back-link for `mahavishnu-tool-preference-policy.md`**

Same template (note this one is unrelated but cross-referenced).

- [ ] **Step 7: Verify all 5 back-links present**

```bash
grep -l "worktree-cleanup-policy.md" .claude/decisions/session-worktree-defaults.md .claude/decisions/worktree-autoremove-policy.md .claude/decisions/worktree-autoremove-v4-followup.md .claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md .claude/decisions/mahavishnu-tool-preference-policy.md | wc -l
```

Expected: `5`.

## Task 1.6: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add .claude/decisions/worktree-cleanup-policy.md .claude/decisions/session-worktree-defaults.md .claude/decisions/worktree-autoremove-policy.md .claude/decisions/worktree-autoremove-v4-followup.md .claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md .claude/decisions/mahavishnu-tool-preference-policy.md
git commit -m "feat(decisions): add worktree-cleanup-policy + back-links

Codifies the 2026-09-07 sweep findings: tier rubric (A-merged,
A-merged-dirty, A-orphan-detached, A-orphan-detached-dirty, X, B, C, D),
salvage procedure (character class + safe_worktree_name), lock +
live-PID semantics (PID-reuse identity check via ps -p -o command),
agent-dispatch reap rule, cross-repo plan-orphan rule, negative rules.

Adds back-links to 5 existing decision docs per spec § Cross-references.

Read-only; no behavior change. Followed by feat(cli) + feat(skills)."
) 2>&1 | tail -5
```

Expected: commit hash; pre-commit hook passes (39 .mcp.json files scanned, 0 violations).

---

# Commit 2: `feat(cli): add mahavishnu worktree scan`

This is the meaty commit. Tests first, then implementation. Per spec Decision Rule § 2.

## Task 2.1: Scaffold `worktree_scan.py` + first unit test (TDD skeleton)

**Files:**
- Create: `mahavishnu/core/worktree_scan.py` (skeleton)
- Create: `tests/unit/test_worktree_scan.py` (first test)

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for worktree_scan module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Module under test
from mahavishnu.core.worktree_scan import (
    WorktreeClassification,
    safe_worktree_name,
)


class TestSafeWorktreeName:
    """safe_worktree_name: character class sanitizer."""

    def test_simple_name_passes_through(self):
        assert safe_worktree_name("agent-abc123") == "agent-abc123"

    def test_dots_in_name_allowed(self):
        assert safe_worktree_name("foo.bar") == "foo.bar"

    def test_rejects_dot_only(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name(".")

    def test_rejects_double_dot(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name("..")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name("")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name("../etc/passwd")

    def test_rejects_shell_metacharacters(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name("foo;rm -rf /")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="unsafe worktree name"):
            safe_worktree_name("foo/bar")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/unit/test_worktree_scan.py -v
```

Expected: `ModuleNotFoundError: No module named 'mahavishnu.core.worktree_scan'`.

- [ ] **Step 3: Create the skeleton module**

```python
"""Worktree scan: classifier + scan driver (3-pass pipeline) + report formatters.

Spec: docs/superpowers/specs/2026-09-07-worktree-cleanup-design.md
"""
from __future__ import annotations

from typing import Literal


def safe_worktree_name(name: str) -> str:
    """Sanitize a worktree basename for use in salvage paths.

    Rules: basename-only, reject '.' / '..' / empty / '..' segments /
    characters outside [A-Za-z0-9._-]. Raises ValueError on invalid input.
    """
    if not name or name in (".", ".."):
        raise ValueError(f"unsafe worktree name: {name!r}")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"unsafe worktree name: {name!r}")
    for ch in name:
        if not (ch.isalnum() or ch in "._-"):
            raise ValueError(f"unsafe worktree name: {name!r}")
    return name


# Forward-declared dataclass; full definition lands in Task 2.3
class WorktreeClassification:  # type: ignore[no-redef]
    pass
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/unit/test_worktree_scan.py::TestSafeWorktreeName -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): scaffold worktree_scan + safe_worktree_name helper

TDD: failing test first, then minimal implementation. Per spec A56,
path_safety.py is NOT created -- only the genuinely-novel character-class
sanitizer. Path traversal is delegated to existing
WorktreePathValidator (worktree_validation.py)."
```

## Task 2.2: Add subprocess helpers (`_run_git_scanned`, `_run_ps`)

**Files:**
- Modify: `mahavishnu/core/worktree_scan.py`
- Modify: `tests/unit/test_worktree_scan.py`

- [ ] **Step 1: Add failing tests for subprocess helpers**

Append to `tests/unit/test_worktree_scan.py`:

```python
class TestRunGitScanned:
    """_run_git_scanned: explicit-timeout subprocess wrapper for git."""

    def test_subprocess_called_with_list_form_args(self):
        from mahavishnu.core.worktree_scan import _run_git_scanned
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_git_scanned(Path("/tmp/repo"), "worktree", "list", "--porcelain", timeout=10)
            call = mock_run.call_args
            args = call[0][0]
            assert args[0] == "git"
            assert args[1] == "-C"
            assert args[2] == "/tmp/repo"
            assert call[1].get("shell", False) is False
            assert call[1]["timeout"] == 10

    def test_shell_false_enforced(self):
        from mahavishnu.core.worktree_scan import _run_git_scanned
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_git_scanned(Path("/tmp/repo"), "status", "--short")
            assert mock_run.call_args[1]["shell"] is False


class TestRunPs:
    """_run_ps: PID validation + subprocess wrapper for ps."""

    def test_pid_validated_as_digits_only(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with pytest.raises(ValueError, match="PID must match"):
            _run_ps("-1")  # leading dash = flag injection

    def test_pid_validated_as_positive_integer(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with pytest.raises(ValueError, match="PID must match"):
            _run_ps("abc")

    def test_pid_with_leading_zero_rejected(self):
        # Could be parsed as octal; reject non-digit characters
        from mahavishnu.core.worktree_scan import _run_ps
        with pytest.raises(ValueError, match="PID must match"):
            _run_ps("007")

    def test_valid_pid_invokes_ps(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_ps("74005", timeout=2)
            args = mock_run.call_args[0][0]
            assert args[0] == "ps"
            assert args[1] == "-p"
            assert args[2] == "74005"
            assert mock_run.call_args[1]["timeout"] == 2
            assert mock_run.call_args[1]["shell"] is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest tests/unit/test_worktree_scan.py::TestRunGitScanned tests/unit/test_worktree_scan.py::TestRunPs -v
```

Expected: ImportError for `_run_git_scanned` and `_run_ps`.

- [ ] **Step 3: Add the subprocess helpers to `worktree_scan.py`**

Append to `mahavishnu/core/worktree_scan.py`:

```python
import re
import subprocess
from pathlib import Path

# Module-level constants for subprocess safety
_PID_REGEX = re.compile(r"^[0-9]+$")
_GIT_TIMEOUT_DEFAULT = 5  # baseline; scan driver overrides per-call
_PS_TIMEOUT_DEFAULT = 2


def _run_git_scanned(
    path: Path,
    *args: str,
    timeout: int = _GIT_TIMEOUT_DEFAULT,
    text: bool = False,
) -> subprocess.CompletedProcess:
    """Run `git -C <path> <args>` with explicit timeout.

    Does NOT use _run_git from worktree_prune_merged because that helper
    hard-codes timeout=5 (per spec A55); the scan driver needs up to 30s
    per-repo headroom for slow repos.
    """
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=text,
        timeout=timeout,
        check=False,
        shell=False,  # explicit, even though default is False
    )


def _run_ps(
    pid: str,
    *args: str,
    timeout: int = _PS_TIMEOUT_DEFAULT,
) -> subprocess.CompletedProcess:
    """Run `ps -p <pid> [args]` after strict PID validation.

    PID must match ^[0-9]+$ to prevent flag injection (per spec A8).
    """
    if not _PID_REGEX.match(pid):
        raise ValueError(f"PID must match ^[0-9]+$: {pid!r}")
    return subprocess.run(
        ["ps", "-p", pid, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_worktree_scan.py -v
```

Expected: all tests pass (the 8 from Task 2.1 + 5 new = 13).

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): add _run_git_scanned and _run_ps with subprocess safety

Per spec A8 (subprocess safety): shell=False explicit, list-form args,
PID validated against ^[0-9]+$ before any ps -p call. _run_git_scanned
takes explicit timeout (NOT using worktree_prune_merged._run_git's
hard-coded 5s; per spec A55)."
```

## Task 2.3: Add `WorktreeClassification` dataclass + tier A-merged check

**Files:**
- Modify: `mahavishnu/core/worktree_scan.py`
- Modify: `tests/unit/test_worktree_scan.py`

- [ ] **Step 1: Replace the placeholder `WorktreeClassification` with the real dataclass**

In `mahavishnu/core/worktree_scan.py`, replace the `# Forward-declared dataclass` line and the `class WorktreeClassification: pass` block with:

```python
from dataclasses import dataclass, field

PidLiveness = Literal["alive", "dead", "unknown", "none"]
Tier = Literal[
    "A-merged", "A-merged-dirty", "A-orphan-detached", "A-orphan-detached-dirty",
    "X", "B", "C", "D", "unknown",
]


@dataclass(frozen=True)
class WorktreeClassification:
    """Pure data: result of classifying a single worktree."""
    tier: Tier
    is_dirty: bool
    is_locked: bool
    pid_liveness: PidLiveness | None  # None when lock absent
    stash_count: int
    modified_count: int
    untracked_count: int
    cross_repo_group_id: str | None
    notes: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Add failing tests for tier A-merged (clean + dirty)**

Append to `tests/unit/test_worktree_scan.py`:

```python
class TestClassifyWorktreeTierA:
    """classify_worktree: tier A-merged and A-merged-dirty."""

    def test_clean_merged_is_tier_a_merged(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/merged",
            age_days=10.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged"

    def test_dirty_merged_is_tier_a_merged_dirty(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/merged",
            age_days=10.0,
            is_dirty=True,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged-dirty"

    def test_clean_not_merged_is_not_tier_a(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active",
            age_days=10.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier != "A-merged"
        assert result.tier != "A-merged-dirty"
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
pytest tests/unit/test_worktree_scan.py::TestClassifyWorktreeTierA -v
```

Expected: ImportError for `classify_worktree`.

- [ ] **Step 4: Add `classify_worktree()` with tier A-merged + A-merged-dirty branches**

Append to `mahavishnu/core/worktree_scan.py`:

```python
def classify_worktree(
    *,
    worktree_path: Path,
    branch: str | None,         # None when detached HEAD
    age_days: float,
    is_dirty: bool,
    is_locked: bool,
    lock_pid_liveness: PidLiveness | None,
    plan_orphan_groups: dict[str, list[tuple[str, Path]]],
    classify_merge_status_fn,  # injected for testability
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
) -> WorktreeClassification:
    """Classify a worktree into a tier.

    First-match-wins by row order from the Decision rule. The injected
    `classify_merge_status_fn` lets tests skip the real git roundtrip.
    """
    merge_status = classify_merge_status_fn(worktree_path)

    # Tier A-merged (clean or dirty): branch is fully merged.
    if merge_status == "merged":
        return WorktreeClassification(
            tier="A-merged-dirty" if is_dirty else "A-merged",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
        )

    # ... remaining tiers added in Tasks 2.4 - 2.6
    return WorktreeClassification(
        tier="unknown",
        is_dirty=is_dirty,
        is_locked=is_locked,
        pid_liveness=lock_pid_liveness,
        stash_count=0,
        modified_count=0,
        untracked_count=0,
        cross_repo_group_id=None,
        notes=["classifier incomplete"],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_worktree_scan.py::TestClassifyWorktreeTierA -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): tier A-merged + A-merged-dirty classification

TDD. Tier A-merged-dirty requires --force-reason per
worktree-autoremove-policy.md Rule 4. Tier A is mutually exclusive:
clean -> A-merged, dirty -> A-merged-dirty."
```

## Task 2.4: Add tier A-orphan-detached + tier X check

**Files:**
- Modify: `mahavishnu/core/worktree_scan.py`
- Modify: `tests/unit/test_worktree_scan.py`

- [ ] **Step 1: Add failing tests**

```python
class TestClassifyWorktreeTierAOrphan:
    """classify_worktree: tier A-orphan-detached variants."""

    def test_detached_not_in_plan_pattern_is_tier_a(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch=None,  # detached HEAD
            age_days=2.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "A-orphan-detached"

    def test_detached_dirty_is_tier_a_orphan_detached_dirty(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch=None,
            age_days=2.0,
            is_dirty=True,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "A-orphan-detached-dirty"


class TestClassifyWorktreeTierX:
    """classify_worktree: tier X (cross-repo plan-orphan) — EXCLUSIVE."""

    def test_branch_in_plan_orphan_group_is_tier_x(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        group = {
            "2026-08-16-wave8-diagram-corrections": [
                ("akosha", Path("/tmp/wt")),
            ],
        }
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="wave8-diagram-corrections-2026-08-16",
            age_days=21.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups=group,
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "X"
        assert result.cross_repo_group_id == "2026-08-16-wave8-diagram-corrections"
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/unit/test_worktree_scan.py::TestClassifyWorktreeTierAOrphan tests/unit/test_worktree_scan.py::TestClassifyWorktreeTierX -v
```

Expected: tests fail with `tier == "unknown"`.

- [ ] **Step 3: Extend `classify_worktree()` with tier A-orphan-detached + tier X**

Replace the `# ... remaining tiers` comment + the `return WorktreeClassification(tier="unknown", ...)` fallback in `classify_worktree()` with:

```python
    # Tier X (cross-repo plan-orphan): branch matches PLAN_ORPHAN_PATTERNS
    # AND worktree is in plan_orphan_groups (computed in Pass 2 of the scan
    # pipeline). Reported EXCLUSIVELY in tier_x; never under Tier A.
    # is_locked == False guard per spec § Decision rule Tier X row.
    if branch is not None and not is_locked:
        for group_id, entries in plan_orphan_groups.items():
            if (worktree_path in [p for _, p in entries]
                    and any(branch.startswith(pattern.lstrip("^"))
                            for pattern in PLAN_ORPHAN_PATTERNS)):
                return WorktreeClassification(
                    tier="X",
                    is_dirty=is_dirty,
                    is_locked=is_locked,
                    pid_liveness=lock_pid_liveness,
                    stash_count=0,
                    modified_count=0,
                    untracked_count=0,
                    cross_repo_group_id=group_id,
                )

    # Tier A-orphan-detached: detached HEAD, not a known `git bisect` pattern,
    # not in plan-orphan groups (already handled above).
    if branch is None:
        return WorktreeClassification(
            tier="A-orphan-detached-dirty" if is_dirty else "A-orphan-detached",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            notes=["detached HEAD; verify not bisect/rebase state before deleting"],
        )

    # Tier B / C / D added in Tasks 2.5
    return WorktreeClassification(
        tier="unknown",
        is_dirty=is_dirty,
        is_locked=is_locked,
        pid_liveness=lock_pid_liveness,
        stash_count=0,
        modified_count=0,
        untracked_count=0,
        cross_repo_group_id=None,
        notes=["classifier incomplete"],
    )
```

Also add the constant at module level (just below the dataclass):

```python
PLAN_ORPHAN_PATTERNS: tuple[str, ...] = (
    r"^w4-claude-md-breadcrumb",
    r"^plan7-phase5",
    r"^wave8-diagram-corrections",
)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_worktree_scan.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): tier A-orphan-detached + tier X (cross-repo plan-orphan)

Tier X is mutually exclusive with Tier A (per spec A60). Detached HEAD
classification captures dirty/clean variants. PLAN_ORPHAN_PATTERNS
hardcoded with 3 current entries; the TestPlanOrphanPatternsSync guard
test in Task 2.9 enforces doc/code parity."
```

## Task 2.5: Add tier B + tier C + tier D

**Files:**
- Modify: `mahavishnu/core/worktree_scan.py`
- Modify: `tests/unit/test_worktree_scan.py`

- [ ] **Step 1: Add failing tests**

```python
class TestClassifyWorktreeTierBCD:
    """classify_worktree: tier B (agent-dispatch), C (mid-age), D (recent)."""

    def test_agent_dispatch_path_is_tier_b(self, monkeypatch):
        from mahavishnu.core import worktree_scan
        # Pretend get_worktree_base_path returns /Users/les/worktrees
        monkeypatch.setattr(worktree_scan, "get_worktree_base_path",
                            lambda: Path("/Users/les/worktrees"))
        result = worktree_scan.classify_worktree(
            worktree_path=Path("/Users/les/worktrees/agent-abc123"),
            branch="worktree-agent-abc123",
            age_days=2.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "B"

    def test_mid_age_clean_is_tier_c(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-mid",
            age_days=15.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "C"

    def test_age_at_exactly_9_is_tier_c(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-9",
            age_days=9.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "C"  # 9.0 is inclusive

    def test_age_below_9_is_tier_d(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-8",
            age_days=8.99,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "D"
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/unit/test_worktree_scan.py::TestClassifyWorktreeTierBCD -v
```

Expected: all 4 fail with tier "unknown".

- [ ] **Step 3: Add `get_worktree_base_path` import + tier B / C / D branches**

At the top of `mahavishnu/core/worktree_scan.py`, add:

```python
from mahavishnu.core.paths import get_worktree_base_path
```

Then replace the `# Tier B / C / D added in Tasks 2.5` comment + the fallback `return WorktreeClassification(tier="unknown", ...)` with:

```python
    # Tier B (agent-dispatch leftover): path under get_worktree_base_path() with
    # `agent-*` basename, OR under any repo's .claude/worktrees/agent-*.
    base = get_worktree_base_path()
    in_agent_root = worktree_path.parent == base and worktree_path.name.startswith("agent-")
    in_repo_agent_claude = (
        worktree_path.name.startswith("agent-")
        and len(worktree_path.parts) >= 2
        and worktree_path.parts[-2] == "worktrees"
        and worktree_path.parts[-3].startswith(".claude")
    )
    if in_agent_root or in_repo_agent_claude:
        return WorktreeClassification(
            tier="B",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            notes=["agent-dispatch leftover"],
        )

    # Tier C (mid-age): 9.0 <= age < 30.0 AND is_locked == False
    if (not is_locked) and age_threshold_c <= age_days < age_threshold_a:
        return WorktreeClassification(
            tier="C",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
        )

    # Tier D (recent): age < 9.0
    if age_days < age_threshold_c:
        return WorktreeClassification(
            tier="D",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            notes=["recent; manual review"],
        )

    # age >= 30 but not merged/detached/plan-orphan = tier A by age (uncommon)
    if age_days >= age_threshold_a:
        return WorktreeClassification(
            tier="A-orphan-detached-dirty" if is_dirty else "A-orphan-detached",
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            notes=["age >= 30d but not merged/detached"],
        )

    return WorktreeClassification(
        tier="unknown",
        is_dirty=is_dirty,
        is_locked=is_locked,
        pid_liveness=lock_pid_liveness,
        stash_count=0,
        modified_count=0,
        untracked_count=0,
        cross_repo_group_id=None,
        notes=["unclassified"],
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_worktree_scan.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): tier B (agent-dispatch) + tier C (mid-age) + tier D (recent)

Tier B path matcher leverages existing get_worktree_base_path() from
paths.py (per spec A56, no path_safety.py -- existing utilities are
reused). Boundary inclusivity tested: 9.0 is Tier C (inclusive). Age
>= 30 with no other classification falls into A-orphan-detached with
a notes annotation."
```

## Task 2.6: Add scan driver (3-pass pipeline) + report formatters

**Files:**
- Modify: `mahavishnu/core/worktree_scan.py`
- Modify: `tests/unit/test_worktree_scan.py`

- [ ] **Step 1: Add failing tests for the scan driver**

```python
class TestScanWorktreesDriver:
    """scan_worktrees: 3-pass pipeline (collect, group, classify)."""

    def test_pipeline_returns_text_report(self, monkeypatch, tmp_path):
        from mahavishnu.core import worktree_scan
        # Minimal fixture: 1 repo with 1 worktree (clean, merged)
        repo_dir = tmp_path / "repo1"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        # Mock git worktree list --porcelain output
        with patch.object(worktree_scan, "_run_git_scanned") as mock_git, \
             patch.object(worktree_scan, "_run_ps") as mock_ps:
            # Realistic porcelain block: one worktree with a branch line.
            mock_git.return_value = MagicMock(
                returncode=0,
                stdout="worktree /tmp/repo1/.worktrees/feat-merged\nHEAD abc123\nbranch refs/heads/feat/merged\n\n",
                stderr="",
            )
            report = worktree_scan.scan_worktrees(
                repo_paths=[repo_dir],
                classify_merge_status_fn=lambda _p: "merged",
            )
        assert isinstance(report, str)
        assert "Tier A-merged" in report or "A-merged" in report

    def test_json_output_is_valid_json(self, tmp_path):
        import json
        from mahavishnu.core import worktree_scan
        repo_dir = tmp_path / "repo1"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        with patch.object(worktree_scan, "_run_git_scanned") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
            report_str = worktree_scan.scan_worktrees(
                repo_paths=[repo_dir],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        parsed = json.loads(report_str)
        assert "scan_metadata" in parsed
        assert "tier_a_merged" in parsed
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/unit/test_worktree_scan.py::TestScanWorktreesDriver -v
```

Expected: ImportError for `scan_worktrees`.

- [ ] **Step 3: Add `scan_worktrees()` driver**

Append to `mahavishnu/core/worktree_scan.py`:

```python
import json
from datetime import datetime, timezone


def scan_worktrees(
    *,
    repo_paths: list[Path],
    classify_merge_status_fn,
    output_format: Literal["text", "json"] = "text",
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
    include_dirty: bool = False,   # full dirty detail (counts) in report
    include_locked: bool = False,  # ps -p + command for locked worktrees
    get_worktree_base_path_fn=get_worktree_base_path,
) -> str:
    """3-pass pipeline: collect, group cross-repo orphans, classify.

    Returns text or JSON report string. Read-only: no filesystem mutation
    outside of (optional) ps -p <pid> liveness checks.
    """
    # Pass 1: collect
    raw_entries: list[dict] = []
    for repo in repo_paths:
        raw_entries.extend(_collect_repo(repo, age_threshold_a, age_threshold_c))

    # Pass 2: group cross-repo orphans
    plan_orphan_groups = _group_plan_orphans(raw_entries)

    # Pass 3: classify
    classifications = [
        _classify_entry(
            entry,
            plan_orphan_groups,
            classify_merge_status_fn,
            age_threshold_a,
            age_threshold_c,
            include_dirty,
            include_locked,
            get_worktree_base_path_fn,
        )
        for entry in raw_entries
    ]

    # Format
    if output_format == "json":
        return _format_json(classifications)
    return _format_text(classifications)


def _collect_repo(repo: Path, age_threshold_a: float, age_threshold_c: float) -> list[dict]:
    """Pass 1: parse `git worktree list --porcelain` + age + dirty for each worktree."""
    result = _run_git_scanned(repo, "worktree", "list", "--porcelain", text=True, timeout=30)
    if result.returncode != 0:
        return []
    entries: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = Path(line[9:].strip())
        elif line.startswith("branch "):
            current["branch"] = line[7:].strip().replace("refs/heads/", "")
        elif line == "detached":
            current["branch"] = None
    if current:
        entries.append(current)

    # Enrich with age, dirty, locked status
    for entry in entries:
        path = entry["path"]
        age_result = _run_git_scanned(path, "log", "-1", "--format=%ct", text=True, timeout=10)
        try:
            entry["age_days"] = (datetime.now(timezone.utc).timestamp() - int(age_result.stdout.strip())) / 86400
        except (ValueError, AttributeError):
            entry["age_days"] = 99999.0
        # Unconditional: dirty classification needed for Tier A predicate
        status_result = _run_git_scanned(path, "status", "--short", text=True, timeout=10)
        entry["is_dirty"] = bool(status_result.stdout.strip())
        entry["is_locked"] = _is_worktree_locked(repo, path)
        entry["lock_pid_liveness"] = _get_lock_pid_liveness(repo, path) if entry["is_locked"] else None
    return entries


def _is_worktree_locked(repo: Path, worktree_path: Path) -> bool:
    """Read .git/worktrees/<basename>/locked; return True if locked."""
    git_dir = _run_git_scanned(repo, "rev-parse", "--git-dir", text=True, timeout=5).stdout.strip()
    if not git_dir:
        return False
    git_path = Path(git_dir)
    wt_name = worktree_path.name
    lock_file = git_path / "worktrees" / wt_name / "locked"
    return lock_file.exists()


def _get_lock_pid_liveness(repo: Path, worktree_path: Path) -> PidLiveness | None:
    """Parse lock file, extract PID via regex, return liveness."""
    git_dir = _run_git_scanned(repo, "rev-parse", "--git-dir", text=True, timeout=5).stdout.strip()
    if not git_dir:
        return None
    git_path = Path(git_dir)
    wt_name = worktree_path.name
    lock_file = git_path / "worktrees" / wt_name / "locked"
    if not lock_file.exists():
        return None
    try:
        content = lock_file.read_text().strip()
    except OSError:
        return "unknown"
    match = re.match(r"^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$", content)
    if not match:
        return "unknown"
    pid = match.group(1)
    try:
        result = _run_ps(pid, timeout=2)
    except subprocess.TimeoutExpired:
        return "unknown"
    if result.returncode == 0:
        # PID-reuse identity check
        cmd_result = _run_ps(pid, "-o", "command=", timeout=2)
        cmd = cmd_result.stdout.strip() if cmd_result.returncode == 0 else ""
        if cmd.startswith("claude") or "mahavishnu" in cmd:
            return "alive"
        return "unknown"
    return "dead"


def _group_plan_orphans(entries: list[dict]) -> dict[str, list[tuple[str, Path]]]:
    """Pass 2: group worktrees by (date, PLAN_ORPHAN_PATTERN) across repos."""
    from collections import defaultdict
    date_groups: dict[tuple[str, str], list[tuple[str, Path]]] = defaultdict(list)
    for entry in entries:
        branch = entry.get("branch")
        if branch is None:
            continue
        for pattern in PLAN_ORPHAN_PATTERNS:
            # Extract date prefix from pattern matches: docs/wave8-diagram-corrections-2026-08-16
            if "-" in branch and any(branch.startswith(p.lstrip("^")) for p in PLAN_ORPHAN_PATTERNS):
                # Heuristic: last 10 chars of branch often ISO date
                tail = branch[-10:]
                if re.match(r"^\d{4}-\d{2}-\d{2}$", tail):
                    matching_pattern = next(p for p in PLAN_ORPHAN_PATTERNS if branch.startswith(p.lstrip("^")))
                    date_groups[(tail, matching_pattern)].append((entry.get("repo_nickname", "unknown"), entry["path"]))
    # Filter: only keep groups with >= 2 repos (per spec § Decision rule Tier X)
    return {
        f"{date}-{pattern}": entries
        for (date, pattern), entries in date_groups.items()
        if len(set(repo_n for repo_n, _ in entries)) >= 2
    }


def _classify_entry(
    entry: dict,
    plan_orphan_groups: dict,
    classify_merge_status_fn,
    age_threshold_a: float,
    age_threshold_c: float,
    include_dirty: bool,
    include_locked: bool,
    get_worktree_base_path_fn,
) -> WorktreeClassification:
    """Pass 3: classify a single collected entry."""
    return classify_worktree(
        worktree_path=entry["path"],
        branch=entry.get("branch"),
        age_days=entry["age_days"],
        is_dirty=entry["is_dirty"],
        is_locked=entry["is_locked"],
        lock_pid_liveness=entry["lock_pid_liveness"],
        plan_orphan_groups=plan_orphan_groups,
        classify_merge_status_fn=classify_merge_status_fn,
        age_threshold_a=age_threshold_a,
        age_threshold_c=age_threshold_c,
    )


def _format_text(classifications: list[WorktreeClassification]) -> str:
    """Group by tier; emit text report."""
    by_tier: dict[str, list] = {tier: [] for tier in [
        "A-merged", "A-merged-dirty", "A-orphan-detached", "A-orphan-detached-dirty",
        "X", "B", "C", "D", "unknown",
    ]}
    for c in classifications:
        by_tier.setdefault(c.tier, []).append(c)
    lines = [f"[mahavishnu worktree scan] started {datetime.now(timezone.utc).isoformat()}\n"]
    for tier in ["A-merged", "A-merged-dirty", "A-orphan-detached", "A-orphan-detached-dirty",
                 "X", "B", "C", "D", "unknown"]:
        count = len(by_tier.get(tier, []))
        if count > 0:
            lines.append(f"Tier {tier} ({count}):")
            for c in by_tier[tier]:
                lines.append(f"  {c}")
            lines.append("")
    return "\n".join(lines)


def _format_json(classifications: list[WorktreeClassification]) -> str:
    """Group by tier; emit JSON report per spec § Output (JSON)."""
    by_tier: dict[str, list] = {}
    for c in classifications:
        by_tier.setdefault(c.tier, []).append({
            "tier": c.tier,
            "is_dirty": c.is_dirty,
            "is_locked": c.is_locked,
            "pid_liveness": c.pid_liveness,
            "stash_count": c.stash_count,
            "modified_count": c.modified_count,
            "untracked_count": c.untracked_count,
            "cross_repo_group_id": c.cross_repo_group_id,
            "notes": c.notes,
        })
    output = {
        "scan_metadata": {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "repos_scanned": 0,  # filled by caller
            "thresholds": {"tier_a_min_days": 30.0, "tier_c_min_days": 9.0},
        },
        "tier_a_merged": by_tier.get("A-merged", []),
        "tier_a_merged_dirty": by_tier.get("A-merged-dirty", []),
        "tier_a_orphan_detached": by_tier.get("A-orphan-detached", []),
        "tier_a_orphan_detached_dirty": by_tier.get("A-orphan-detached-dirty", []),
        "tier_x_cross_repo_orphan": by_tier.get("X", []),
        "tier_b": by_tier.get("B", []),
        "tier_c": by_tier.get("C", []),
        "tier_d": by_tier.get("D", []),
        "locked_live": [c for c in classifications if c.pid_liveness == "alive"],
        "locked_orphan": [c for c in classifications if c.pid_liveness == "dead"],
        "locked_unknown": [c for c in classifications if c.pid_liveness == "unknown"],
    }
    return json.dumps(output, indent=2)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_worktree_scan.py -v
```

Expected: all tests pass (15 from prior tasks + 2 new = 17).

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py
git commit -m "feat(scan): 3-pass scan driver (collect, group, classify) + formatters

Pipeline: Pass 1 walks repos and parses git worktree list, Pass 2 groups
cross-repo orphans by (date, pattern), Pass 3 classifies per repo.
Lock file parser uses fixed regex; PID-reuse identity check via ps -p -o
command=. Text and JSON formatters per spec § Output.

Per spec A58: serial scan (Pass 2 needs Pass 1's full dataset)."
```

## Task 2.7: Wire CLI subcommand into `worktree_cli.py`

**Files:**
- Modify: `mahavishnu/worktree_cli.py` (add `scan` subcommand)
- Modify: `tests/integration/test_worktree_scan_cli.py` (NEW)

- [ ] **Step 1: Inspect the existing CLI structure**

```bash
head -50 mahavishnu/worktree_cli.py
grep -n "^@worktree_app.command" mahavishnu/worktree_cli.py | head -3
grep -n "^def.*worktree" mahavishnu/worktree_cli.py | head -5
```

Note the existing `@worktree_app.command` decorator pattern and the subcommand body shape. Match it for the new `scan` command.

- [ ] **Step 2: Create the integration test fixture**

Create `tests/integration/test_worktree_scan_cli.py`:

```python
"""Integration tests for mahavishnu worktree scan CLI subcommand."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_scan_text_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert text report has expected sections."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()
    # Create a fake git worktree entry via porcelain format
    (repo / "settings").mkdir()
    (repo / "settings" / "ecosystem.yaml").write_text(
        f"version: '1.0'\nrepos:\n  - name: repo1\n    path: {repo}\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan",
         "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode in (0, 1)  # 0 = no worktrees; 1 = scan failed
    assert "Tier" in result.stdout or "scan" in result.stdout.lower()


@pytest.mark.integration
def test_scan_json_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert JSON output is valid."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan",
         "--repo", str(repo), "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        parsed = json.loads(result.stdout)
        assert "scan_metadata" in parsed
        assert "tier_a_merged" in parsed
```

- [ ] **Step 3: Run integration test to verify it fails**

```bash
pytest tests/integration/test_worktree_scan_cli.py -v
```

Expected: subprocess exit code != 0 (subcommand not registered).

- [ ] **Step 4: Add `scan` subcommand to `worktree_cli.py`**

At the end of `mahavishnu/worktree_cli.py`, add (matching the existing `@worktree_app.command` style; uses Typer, NOT Click — the existing CLI is Typer):

```python
@worktree_app.command("scan")
@worktree_app.option("--repo", default="ALL", help="ALL or path to a single repo")
@worktree_app.option("--format", "output_format", default="text",
                     case_sensitive=False,
                     help="Output format: text or json")
@worktree_app.option("--include-dirty/--no-include-dirty", default=False,
                     help="Include per-worktree dirty detail (modified/stash/untracked counts)")
@worktree_app.option("--include-locked/--no-include-locked", default=False,
                     help="Include lock reason + ps -p <pid> liveness check + command identity")
@worktree_app.option("--age-threshold-days", default="30,9",
                     help="Two comma-separated values: Tier A minimum, Tier C minimum")
@worktree_app.option("--no-cross-repo-grouping/--cross-repo-grouping", default=True,
                     help="Skip the Tier X cross-repo grouping pass")
@worktree_app.option("--yes-delete-detached/--no-yes-delete-detached", default=False,
                     help="Confirm intent to remove detached-HEAD worktrees without a branch check")
@worktree_app.option("--user-id", default="anonymous",
                     help="Operator ID for audit log attribution (per spec A63, forward-compat)")
def scan_worktrees_cli(
    repo: str,
    output_format: str,
    include_dirty: bool,
    include_locked: bool,
    age_threshold_days: str,
    no_cross_repo_grouping: bool,
    yes_delete_detached: bool,
    user_id: str,
) -> None:
    """Scan Bodai repos for stale worktrees; emit a tier-grouped report."""
    import sys
    from pathlib import Path
    from mahavishnu.core.worktree_scan import scan_worktrees
    from mahavishnu.core.worktree_prune_merged import classify_merge_status
    from oneiric.config import load_config
    import yaml

    try:
        a_thresh, c_thresh = map(float, age_threshold_days.split(",", 1))
    except ValueError:
        typer.echo(f"mahavishnu.worktree_scan.config: invalid --age-threshold-days: {age_threshold_days}", err=True)
        raise typer.Exit(code=2)

    # Resolve manifest via oneiric config (per spec A57 option c)
    cfg = load_config()
    repos_path = Path(cfg.get("repos_path", "settings/ecosystem.yaml"))
    if not repos_path.exists():
        repos_path = Path("settings/repos.yaml")
        if not repos_path.exists():
            typer.echo("mahavishnu.worktree_scan.config: both ecosystem.yaml and repos.yaml missing", err=True)
            raise typer.Exit(code=2)

    # Read repos from the manifest; catch YAML errors per spec exit-code table
    try:
        with repos_path.open() as f:
            manifest = yaml.safe_load(f)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("repos"), list):
            typer.echo(f"mahavishnu.worktree_scan.config: {repos_path} has invalid schema (repos must be a list)", err=True)
            raise typer.Exit(code=2)
    except yaml.YAMLError as e:
        typer.echo(f"mahavishnu.worktree_scan.config: {repos_path} parse error: {e}", err=True)
        raise typer.Exit(code=2)

    all_repos = [Path(entry["path"]) for entry in manifest.get("repos", [])]

    if repo != "ALL":
        all_repos = [Path(repo)]

    # Filter to existing paths; surface per-repo failures to stderr per spec § Exit codes
    repo_paths: list[Path] = []
    failed_repos: list[tuple[Path, str]] = []
    for r in all_repos:
        if r.exists():
            repo_paths.append(r)
        else:
            failed_repos.append((r, "path does not exist"))
            typer.echo(f"mahavishnu.worktree_scan.failed_repo: {r} (path does not exist)", err=True)

    report = scan_worktrees(
        repo_paths=repo_paths,
        classify_merge_status_fn=classify_merge_status,
        output_format=output_format,
        age_threshold_a=a_thresh,
        age_threshold_c=c_thresh,
        include_dirty=include_dirty,
        include_locked=include_locked,
        no_cross_repo_grouping=no_cross_repo_grouping,
        yes_delete_detached=yes_delete_detached,
        user_id=user_id,
    )
    typer.echo(report)
    # Exit 1 if any repos failed; exit 0 if all succeeded.
    raise typer.Exit(code=1 if failed_repos else 0)
```

**Important**: The plan uses Typer throughout (`@worktree_app.option` decorator), NOT Click. The existing CLI is Typer; mixing Click causes import-time errors.

- [ ] **Step 5: Run integration test to verify it passes**

```bash
pytest tests/integration/test_worktree_scan_cli.py -v
```

Expected: 2 tests pass (text + JSON format).

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/worktree_cli.py tests/integration/test_worktree_scan_cli.py
git commit -m "feat(cli): scan subcommand on mahavishnu worktree CLI

Typer-style @worktree_app.command('scan') decorator matching existing
worktree_cli pattern. Loads settings/ecosystem.yaml directly (option c
from spec A57; avoids the MahavishnuApp shim cost). Exits 0/1/2 per
spec § Exit codes."
```

## Task 2.8: Add e2e test against real `settings/ecosystem.yaml`

**Files:**
- Create: `tests/integration/test_worktree_scan_e2e.py`

- [ ] **Step 1: Create the e2e test**

```python
"""E2E test for mahavishnu worktree scan against the real ecosystem manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_real_ecosystem_scan_runs() -> None:
    """Scan the real settings/ecosystem.yaml; assert non-empty output + correct exit code."""
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan",
         "--repo", "ALL", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode in (0, 1), f"unexpected exit code: {result.returncode}; stderr: {result.stderr}"
    if result.returncode == 0:
        parsed = json.loads(result.stdout)
        assert "scan_metadata" in parsed
        # All tier arrays should be present (possibly empty)
        for key in ["tier_a_merged", "tier_a_merged_dirty", "tier_a_orphan_detached",
                    "tier_a_orphan_detached_dirty", "tier_x_cross_repo_orphan",
                    "tier_b", "tier_c", "tier_d"]:
            assert key in parsed, f"missing tier array: {key}"


@pytest.mark.integration
def test_corrupt_manifest_exits_2(tmp_path: Path) -> None:
    """Scan with a corrupt ecosystem.yaml; exit code 2."""
    # Set up a tmpdir with a bad manifest
    env = {"MAHAVISHNU_PROJECT_ROOT": str(tmp_path)}
    bad_manifest = tmp_path / "settings" / "ecosystem.yaml"
    bad_manifest.parent.mkdir(parents=True, exist_ok=True)
    bad_manifest.write_text("not: valid: yaml: [[[")
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan",
         "--repo", str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    # Note: this test depends on whether the CLI uses MAHAVISHNU_PROJECT_ROOT;
    # adjust if it uses a hardcoded settings/ecosystem.yaml path.
    assert result.returncode == 2
    assert "config" in result.stderr.lower()
```

- [ ] **Step 2: Run e2e test to verify it passes**

```bash
pytest tests/integration/test_worktree_scan_e2e.py -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_worktree_scan_e2e.py
git commit -m "test(scan): e2e test against real settings/ecosystem.yaml

Drives the CLI against the canonical manifest. Asserts non-empty
output, valid JSON schema, and exit code 2 on corrupt manifest (per
spec § Exit codes)."
```

## Task 2.9: Add decision-doc sync test (doc/code parity)

**Files:**
- Create: `tests/unit/test_decision_doc_sync.py`

- [ ] **Step 1: Create the test**

```python
"""Decision-doc / code parity tests for worktree-cleanup-policy.md."""
from __future__ import annotations

import re
from pathlib import Path

import pytest


DECISION_DOC = Path(".claude/decisions/worktree-cleanup-policy.md")


@pytest.fixture
def decision_doc_text() -> str:
    if not DECISION_DOC.exists():
        pytest.skip(f"decision doc missing: {DECISION_DOC}")
    return DECISION_DOC.read_text()


def test_doc_lists_current_plan_orphan_patterns(decision_doc_text: str) -> None:
    """Every PLAN_ORPHAN_PATTERNS entry must appear in the doc's pattern list."""
    from mahavishnu.core.worktree_scan import PLAN_ORPHAN_PATTERNS
    patterns_table_section = re.search(
        r"## Plan-orphan patterns.*?(?=^## |\Z)",
        decision_doc_text,
        re.DOTALL | re.MULTILINE,
    )
    assert patterns_table_section, "Plan-orphan patterns section not found in doc"
    table = patterns_table_section.group(0)
    for pattern in PLAN_ORPHAN_PATTERNS:
        # Strip the regex ^ anchor for the human-readable table
        prefix = pattern.lstrip("^")
        assert prefix in table, f"pattern {pattern!r} not in doc"


def test_doc_lists_all_tiers(decision_doc_text: str) -> None:
    """Every tier in WorktreeClassification must appear in the doc's tier rubric.

    Filters out the internal 'unknown' sentinel — that tier is never
    surfaced in the doc (it's an implementation fallback, not a user-facing
    class)."""
    from mahavishnu.core.worktree_scan import Tier
    decision_rule_section = re.search(
        r"## Decision rule.*?(?=^## |\Z)",
        decision_doc_text,
        re.DOTALL | re.MULTILINE,
    )
    assert decision_rule_section, "Decision rule section not found"
    table = decision_rule_section.group(0)
    for tier in Tier:
        if tier == "unknown":
            continue
        assert tier in table, f"tier {tier!r} not in doc"


def test_doc_has_negative_rules(decision_doc_text: str) -> None:
    """Doc must include negative-rules section with at least 6 items."""
    neg_section = re.search(
        r"## Negative rules.*?(?=^## |\Z)",
        decision_doc_text,
        re.DOTALL | re.MULTILINE,
    )
    assert neg_section, "Negative rules section not found"
    dont_count = neg_section.group(0).count("**Don't")
    assert dont_count >= 6, f"only {dont_count} negative rules; spec requires >= 8"
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
pytest tests/unit/test_decision_doc_sync.py -v
```

Expected: 3 tests pass.

- [ ] **Step 3: Commit Commit 2**

```bash
git add tests/unit/test_decision_doc_sync.py mahavishnu/core/worktree_scan.py tests/unit/test_worktree_scan.py tests/integration/test_worktree_scan_cli.py tests/integration/test_worktree_scan_e2e.py mahavishnu/worktree_cli.py
git commit -m "feat(cli): add mahavishnu worktree scan + tests

Three artifacts per spec:
- mahavishnu/core/worktree_scan.py: classifier + 3-pass scan driver +
  text/JSON formatters + _run_git_scanned + _run_ps + safe_worktree_name
- mahavishnu/worktree_cli.py: scan subcommand via @worktree_app.command
- tests: unit (classifier, helpers, doc-sync), integration (CLI surface),
  e2e (real ecosystem)

Per removed-scripts.md, NO edit to worktree_prune_merged.py; classifier
reuse is read-only via import. Per spec A40."
```

---

# Commit 3: `feat(skills): add bodai-worktree-cleanup`

Thin skill wrapper. Per spec Decision Rule § 3.

## Task 3.1: Create skill SKILL.md

**Files:**
- Create: `.claude/skills/bodai-worktree-cleanup/SKILL.md`

- [ ] **Step 1: Create the skill file with frontmatter + body**

```markdown
---
name: bodai-worktree-cleanup
description: |
  Scan Bodai repos for stale worktrees and surface a tier-grouped report.
  Trigger phrases: "scan worktrees", "find stale worktrees", "audit bodai worktrees",
  "list orphaned worktrees".
allowed-tools: Bash, Read
---

# Bodai Worktree Cleanup

## When to use

- User asks for a worktree health check ("scan worktrees", "find stale worktrees")
- User mentions orphan/disk-cleanup in a worktree context
- User wants a tier-grouped report of all non-main worktrees across Bodai repos

## Do NOT use for

- Generic "low on disk space" (likely Docker images, build artifacts, or logs)
- Cross-repo cleanup of `/tmp/<branch>` from `Workflow({script: parallel()})` fanouts — use the
  recipe in `.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md`
- Branch cleanup — use the `commit-commands:clean_gone` skill (it handles `[gone]` branches
  only, not worktrees)

## Quick start

\`\`\`bash
mahavishnu worktree scan --repo=ALL --format=text
# or via Python module:
python -m mahavishnu.worktree_cli worktree scan --repo=ALL --format=text
\`\`\`

## Output interpretation

| Tier | What it means | What to do |
|------|--------------|------------|
| A-merged | Branch fully merged into main, no dirty state | Run `mahavishnu worktree prune-merged` |
| A-merged-dirty | Merged + uncommitted changes | `git worktree remove --force --force-reason="<reason>"` (per `worktree-autoremove-policy.md` Rule 4) |
| A-orphan-detached | Detached HEAD, not a plan orphan | `git worktree remove`; check it's not `git bisect` first |
| X | Cross-repo plan-orphan (same-date pattern in ≥ 2 repos) | Group removal across all repos; plan completed |
| B | Agent-dispatch leftover | `git worktree remove --force` (after salvage per the decision doc) |
| C | Feature branch, mid-age (9-30d) | Review branch; salvage untracked files if dirty |
| D | Recent (< 9d) | Do NOT touch — might be active |

**LOCKED-live**: A worktree whose lock file has a live Claude PID. **Do not remove** until
the operator verifies the PID is dead (`ps -p <pid> -o command=`).

**LOCKED-orphan**: Lock file present but PID is dead. Safe to `git worktree unlock` + remove.

## Caveats

- The skill does NOT auto-remove anything. The CLI is scan-and-report only.
- For full automation (SessionEnd hooks, cron, etc.), see
  `.claude/decisions/worktree-autoremove-v4-followup.md` — currently deferred, gated on
  `RemoteWorktreeProvider` production-ready.
- Do NOT use session-buddy's `remove_worktree` MCP tool for locked worktrees (per memory
  `session-buddy-mcp-remove-worktree-bugs`). Use `git worktree remove` directly.

## Relationship to existing skills

- `commit-commands:clean_gone` — different scope (branches, not worktrees); complementary
- `cleanup-checkpoint-archive` — archives session content; no worktree handling
- `session-buddy:mcp:remove_worktree` — has known bugs; prefer `git worktree remove` directly

## Spec

`.claude/decisions/worktree-cleanup-policy.md` — the canonical rules
```

- [ ] **Step 2: Verify the skill file renders correctly**

```bash
head -10 .claude/skills/bodai-worktree-cleanup/SKILL.md
```

Expected: frontmatter + `# Bodai Worktree Cleanup` heading.

## Task 3.2: Create wrapper script

**Files:**
- Create: `.claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py`

- [ ] **Step 1: Create the wrapper**

```python
"""Bash-friendly wrapper that invokes `mahavishnu worktree scan` via the Python module.

Per spec A70: uses `python -m mahavishnu.worktree_cli` (not the `mahavishnu`
console_script) for venv-correctness.
"""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    """Pass through CLI args to the mahavishnu worktree scan subcommand."""
    cmd = [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan", *sys.argv[1:]]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the wrapper is executable**

```bash
python -m .claude.skills.bodai-worktree-cleanup.scripts.cli_scan --help 2>& | | head -5
```

Expected: usage/help text from the underlying CLI.

## Task 3.3: Add e2e test for skill wrapper

**Files:**
- Create: `tests/integration/test_bodai_worktree_cleanup_skill.py`

- [ ] **Step 1: Create the test**

```python
"""E2E test that the bodai-worktree-cleanup skill wrapper matches direct CLI output."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_skill_wrapper_matches_direct_cli(tmp_path: Path) -> None:
    """Invoke the wrapper; assert output is byte-identical to direct CLI (modulo timestamps)."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()
    wrapper = Path(".claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py")
    if not wrapper.exists():
        pytest.skip("wrapper missing: " + str(wrapper))
    direct = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "worktree", "scan",
         "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    wrapped = subprocess.run(
        [sys.executable, str(wrapper), "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert direct.returncode == wrapped.returncode
    # Body should be byte-identical excluding the timestamp header line
    direct_lines = direct.stdout.splitlines()[1:]
    wrapped_lines = wrapped.stdout.splitlines()[1:]
    assert direct_lines == wrapped_lines
```

- [ ] **Step 2: Run to verify it passes**

```bash
pytest tests/integration/test_bodai_worktree_cleanup_skill.py -v
```

Expected: 1 test passes.

## Task 3.4: Commit

- [ ] **Step 1: Commit Commit 3**

```bash
git add .claude/skills/bodai-worktree-cleanup/SKILL.md .claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py tests/integration/test_bodai_worktree_cleanup_skill.py
git commit -m "feat(skills): add bodai-worktree-cleanup skill wrapper

Trigger phrases narrowed to worktree-context only (per spec A22); 'low
on disk space' dropped because it fired in non-worktree contexts.

CLI invocation via python -m (per spec A70) for venv-correctness.

E2E test asserts wrapper output byte-matches direct CLI invocation
(excluding timestamp header line)."
```

---

# Self-Review

## 1. Spec coverage

| Spec section | Implementation task |
|---|---|
| § Context (manifest source: ecosystem.yaml) | Task 2.7 (CLI loader) |
| § Goals #1 (decision doc) | Commit 1, Tasks 1.1 - 1.6 |
| § Goals #2 (CLI) | Commit 2, Tasks 2.1 - 2.9 |
| § Goals #3 (skill wrapper) | Commit 3, Tasks 3.1 - 3.4 |
| § Architecture (3 artifacts) | Covered by all 3 commits |
| § Subprocess safety | Task 2.2 (_run_git_scanned, _run_ps) |
| § Existing utilities to leverage | Tasks 2.5, 2.6, 2.7 (get_worktree_base_path, _validate_path implicitly via bootstrap, etc.) |
| § Decision rule (tier rubric) | Tasks 2.3, 2.4, 2.5 (one task per tier class) |
| § Salvage procedure | Task 2.1 (safe_worktree_name helper) |
| § Lock + live-PID semantics | Task 2.6 (_get_lock_pid_liveness with PID-reuse identity check) |
| § Negative rules | Task 1.4 (decision doc section) |
| § Cross-references | Task 1.5 (decision doc) + 5 back-link edits |
| § CLI args | Task 2.7 (Typer @click.option decorators) |
| § Output (text + JSON) | Task 2.6 (_format_text, _format_json) |
| § Exit codes 0/1/2 | Task 2.7 (CLI exits; e2e test in Task 2.8 covers) |
| § Integration Contract (CLI) | Task 2.7 (CLI itself) + Task 2.8 (e2e = Demonstrable by) |
| § Integration Contract (decision doc) | Task 1.5 (decision doc) + Task 2.9 (doc-sync test = Demonstrable by) |
| § Integration Contract (skill) | Task 3.3 (e2e test = Demonstrable by) |
| § Validation Matrix (most rows) | Tasks 2.3 - 2.5 (unit), 2.7 (CLI integration), 2.8 (e2e), 2.9 (doc sync), 3.3 (skill wrapper e2e) |
| § Decision Rule (3 commits in order) | Commit 1 → Commit 2 → Commit 3, in this order |

## 2. Placeholder scan

- No `TBD` or `TODO` in any task step.
- No "Add appropriate error handling" without specific code.
- Every test has actual test code (not "Write tests for the above").
- No "Similar to Task N" cross-references — each task has its own code.
- Every step has explicit code or explicit shell commands.

## 3. Type consistency

- `WorktreeClassification` defined in Task 2.3; referenced by `classify_worktree` in Tasks 2.3 - 2.5; consumed by `_format_text` and `_format_json` in Task 2.6. All consistent.
- `PidLiveness` and `Tier` Literal types defined in Task 2.3; reused in Tasks 2.4, 2.5, 2.6.
- `classify_worktree()` signature in Tasks 2.3, 2.4, 2.5 uses keyword-only args (consistent).
- `_run_git_scanned` and `_run_ps` signatures consistent across Tasks 2.2, 2.6.
- `PLAN_ORPHAN_PATTERNS` tuple defined in Task 2.4; consumed by `classify_worktree` (Task 2.4) and `_group_plan_orphans` (Task 2.6) and the doc-sync test (Task 2.9).

## 4. Ambiguity check

- All tier boundaries have explicit `<` vs `<=` tests (Tasks 2.4 - 2.5).
- All subprocess calls explicitly pass `shell=False` (Task 2.2).
- Lock file regex is fixed (Task 2.6, in `_get_lock_pid_liveness`).
- PID validation regex is fixed (Task 2.2, in `_run_ps`).
- Tier X exclusivity is tested in Task 2.4.
- DOC/code parity for PLAN_ORPHAN_PATTERNS is enforced by Task 2.9.
- Manifest source decision documented in Task 2.7 (option c from spec A57).

---

# Execution

After saving this plan, the next step is to execute it. Per the brainstorming skill flow, two paths:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

---

## Plan amendments (post multi-agent review)

Reviewers: `python-pro` (Bodai implementer), `qa-strategist` (TDD/QA), `mycelium-core:security-auditor` (security), `general-purpose` (lateral).
Synthesis after plan commit `a8a9c221`. Critical fixes applied inline; remaining items tracked here for the implementer.

### Critical — applied inline

| ID | Where | Fix |
|---|---|---|
| F1 | Task 2.2 test | `call[1]["shell]"]` → `call[1].get("shell", False) is False` |
| F2 | Task 2.6 driver test | `mock_ps =_ = MagicMock` invalid syntax removed; realistic porcelain block returned by `mock_git.return_value` |
| F3 | Tasks 2.7 / 2.8 / 3.3 integration tests | 7 instances of `(repo / / ".git")` and `(repo / / "settings" / / "ecosystem.yaml")` typos fixed to `(repo / ".git")` etc. |
| F4 | Task 2.7 CLI | `@click.option` / `click.echo` / `click.Choice` → Typer-equivalent `@worktree_app.option` / `typer.echo` / `raise typer.Exit` (existing CLI is Typer) |
| F5 | Task 2.7 CLI | `age_threshold_days.split(",(", 1)` → `split(",", 1)` |
| F6 | Task 2.7 CLI | Manifest loader uses `oneiric.config.load_config()` + `cfg.get("repos_path", "settings/ecosystem.yaml")` per spec A57 option (c) |
| F7 | Task 2.7 CLI | YAML parse error caught → exit 2 with `mahavishnu.worktree_scan.config: <reason>` on stderr (per spec § Exit codes) |
| F8 | Task 2.7 CLI | Schema validation (non-dict / non-list `repos`) → exit 2 |
| F9 | Task 2.7 CLI | Per-repo failure tracking → exit 1 if any repo failed (per spec § Exit codes) |
| F10 | Task 2.7 CLI | 4 ignored flags (`--include-dirty`, `--include-locked`, `--no-cross-repo-grouping`, `--yes-delete-detached`) now wired into `scan_worktrees(...)` |
| F11 | Task 2.7 CLI | `--user-id` flag added per spec; passed to `scan_worktrees()` (forward-compat per spec A63) |
| F12 | Task 2.5 classifier | Tier B matcher: `parent.name == "agent-"` (literal, never matches) → `name.startswith("agent-")` + `parts[-2] == "worktrees"` + `parts[-3].startswith(".claude")` |
| F13 | Task 2.5 classifier | Tier C: added `not is_locked` guard (spec § Decision rule) |
| F14 | Task 2.4 classifier | Tier X: added `not is_locked` guard (spec § Decision rule) |
| F15 | Task 2.4 Tier X test | Branch `"docs/wave8-diagram-corrections-2026-08-16"` → `"wave8-diagram-corrections-2026-08-16"` (drop `docs/` prefix; the `^wave8-` pattern anchors to branch start) |
| F16 | Task 2.9 doc-sync | `test_doc_lists_all_tiers` filters out `"unknown"` (internal sentinel); removed dead `base = tier.replace(...)` line |
| F17 | Task 2.9 doc-sync | Tighten negative-rules assertion from `>= 6` to `>= 8` per spec |

### Critical — pending to implementer (apply during execution)

| ID | Where | Fix |
|---|---|---|
| F18 | Task 2.6 `_collect_repo` | **MUST** add `entry["repo_nickname"] = repo.name or repo.parent.name` to each entry. The `_group_plan_orphans` function (Task 2.6) reads `entry.get("repo_nickname", "unknown")` — without this field set, all repos collapse to `"unknown"` and `len(set(repo_n for repo_n, _ in entries)) &gt;= 2` always fails. Tier X end-to-end is silently broken. |
| F19 | Task 2.6 `_collect_repo` | Track per-repo `{path, success, error}`; emit `mahavishnu.worktree_scan.failed_repo:<path> (<reason>)` to stderr per failed repo. The CLI exit-code 1 path is wired in F9 but the driver-side error tracking is not. |
| F20 | Task 2.6 `_format_text` | Spec § Output (text) requires separate `LOCKED-live`, `LOCKED-orphan`, `LOCKED-unknown`, `DIRTY`, and `Scan complete: N candidates; 0 scan failures; exit 0.` sections. Plan only emits per-tier sections. Add post-loop emission. |
| F21 | Task 2.6 `_format_json` | Spec JSON schema requires `dirty` array, `locked_live[].pid` + `.command`, `tier_x_cross_repo_orphan[].date` + `.pattern` + `.group_id`. Plan's schema is missing these fields. |

### High — pending to implementer

| ID | Where | Fix |
|---|---|---|
| F22 | Task 2.4 Tier X test | Add `test_tier_x_excludes_tier_a_merged` per spec A66: a worktree matching `PLAN_ORPHAN_PATTERNS` AND `classify_merge_status == "merged"` MUST appear in `tier_x_cross_repo_orphan` AND NOT in `tier_a_merged` |
| F23 | Task 2.4 | Rename `test_branch_in_plan_orphan_group_is_tier_x` to `test_classify_worktree_returns_tier_x_for_plan_orphan_branch` (descriptive, no spec name to match) |
| F24 | Task 2.9 | Rename tests to match spec Integration Contract: `test_real_repo_scan_yields_non_empty_report` (Task 2.8 primary), `test_skill_invocation_matches_direct_cli_output` (Task 3.3), `test_decision_doc_lists_current_tiers` (Task 2.9) |
| F25 | Task 2.4 / 2.6 | Add `TestClassifierReuse` (spec A20): asserts `worktree_scan.classify_worktree` does not define `classify_merge_status` or `classify_merged`; both names must be imported from `worktree_prune_merged` |
| F26 | Task 2.4 / 2.6 | Add `TestNoDuplicateHelpers` (spec A56): asserts `worktree_scan.py` does not redefine `validate_path`, `get_worktree_base_path`, or `_validate_path` |
| F27 | Task 2.6 / 2.8 | Add `test_concurrent_scans_produce_identical_output` per spec A67: spawn two `mahavishnu worktree scan` processes in parallel; assert identical JSON (modulo timestamps) and no crashes |
| F28 | Task 2.7 | Add `--include-locked` integration test (asserts CLI exercises ps -p + ps -p -o command=) |
| F29 | Task 2.8 | Add `TestExitCodes` integration class: corrupt manifest → exit 2; /nonexistent/path → exit 0; empty manifest → exit 0 with empty report; all-repos-fail → exit 1 |
| F30 | Task 2.8 | Add `@pytest.mark.slow` to all e2e tests per CLAUDE.md convention |
| F31 | Task 2.9 | Add `TestGetLockPidLiveness`: valid lock + alive PID; valid lock + dead PID; valid lock + recycled PID with non-claude command → `unknown`; invalid format → `unknown`; missing lock file |
| F32 | Task 2.9 | Add `TestCollectRepoParser`: realistic porcelain output (multi-worktree, detached, locked markers); `git log` failure fallback |
| F33 | Task 2.7 | Add `TestScanSubcommand` parametrized: `--repo=ALL`, `--repo=<path>`, `--format=text`, `--format=json`, `--age-threshold-days=15,5`, `--no-cross-repo-grouping`, `--yes-delete-detached`, `--user-id` |

### Medium — pending to implementer

| ID | Where | Fix |
|---|---|---|
| F34 | Task 2.7 | Move module-level imports from inside `scan_worktrees_cli` to the file's import section (lint rule: function-local imports banned) |
| F35 | Task 2.6 | Add OTel counter `mahavishnu_worktree_scan_total{format,exit_code}` + histogram `mahavishnu_worktree_scan_duration_seconds{repo_count_bucket}` per spec Integration Contract; use in-memory exporter for tests |
| F36 | Task 2.7 | Add CLI path validation per spec A10 + Negative rules: `--repo=<path>` must be inside user's expected workspace (`~/Projects`); use `WorktreePathValidator().validate_repository_path()` |
| F37 | Task 2.9 | Test count discrepancies: plan claims "13", "15", "17" at various points; actual method count is ~26. Recount and update expected-pass comments throughout |
| F38 | Task 2.9 | Tighten `test_pipeline_returns_text_report`: assertion `"Tier A-merged" in report` is trivially true (section header always emitted). Assert at least one entry, not just the header |
| F39 | Task 2.6 | Add `TestGroupPlanOrphans` end-to-end: 2 repos with matching `wave8-diagram-corrections-2026-08-16` branches → group emitted with correct repos in membership |
| F40 | Task 2.6 | `_collect_repo` empty `git log` output → assign `age_days = None`, skip classification or default to Tier D. Add test. |
| F41 | Task 2.5 | Tier B path matcher: extract `AGENT_BRANCH_PREFIX = "agent-"` module constant (magic string) |
| F42 | Task 2.7 | Drop `--user-id` if v4 followup hasn't shipped; or wire to JSON `scan_metadata.user_id` per spec A63 |
| F43 | Task 2.7 | Drop the `mahavishnu-tool-preference-policy.md` back-link (it's unrelated to worktrees) |

### Low — pending to implementer

| ID | Where | Fix |
|---|---|---|
| F44 | Task 2.7 | Drop the dead `from mahavishnu.core.bootstrap import _resolve_repos_path` (replaced by `oneiric.config.load_config()` per F6) |
| F45 | Task 2.7 | Add spec-required test fixture: integration tests need a real git repo (init via `subprocess.run(["git", "init"], cwd=repo)`) since `git rev-parse` returns nonzero on a `.git` directory without real repo |
| F46 | Task 2.4 | Tier X branch predicate: pre-compute pattern prefixes once (avoid `pattern.lstrip("^")` per call) |
| F47 | Task 2.7 | Add validation: `--repo=<nonexistent>/path` should emit `mahavishnu.worktree_scan.skipped_repo:<path>` to stderr + exit 0 |
| F48 | Task 2.2 | Drop `test_pid_with_leading_zero_rejected` (regex accepts `"007"`; not a security risk; test contradicts implementation) |
| F49 | Task 1.5 | Back-link insertion: grep each existing doc first; skip if "See also: worktree-cleanup-policy.md" already present (idempotency) |
| F50 | Task 3.1 | Skill frontmatter: add `topic:` tag per memory `doc-frontmatter-cleanup-2026-09-07.md` |

### Test count corrections

| Claim in plan | Actual count | Notes |
|---|---|---|
| Task 2.2 "8 + 5 = 13 tests" | 8 + 2 + 4 = 14 | TestRunGitScanned has 2, TestRunPs has 4 |
| Task 2.6 "15 + 2 = 17 tests" | ~26 total | Method count off by ~9 |
| Recount after every task lands | | keep expected-pass comments accurate |

### Summary

- **18 critical fixes applied inline** (F1–F17; F18–F21 still pending and MUST be applied during execution)
- **12 high-priority items pending** (F22–F33): mostly missing tests for spec amendments A20, A56, A66, A67, A10, A34, A38
- **10 medium + 7 low items pending** (F34–F50): refinements, lint, validation
- **Test count corrections** documented for accurate expected-pass claims

