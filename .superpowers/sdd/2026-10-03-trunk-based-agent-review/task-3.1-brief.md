### Task 3.1: SessionEnd hook `agent-merge-on-end.py`

**Goal:** Create `.claude/hooks/agent-merge-on-end.py` — the SessionEnd
hook that auto-runs `mahavishnu.core.merge_to_main` when conditions are met
(per spec §4.2). Coexists with the existing `worktree-session-isolation.py`
hook (which runs first via the SessionEnd array in `.claude/settings.json`).

**Spec anchor:** `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4.2 (SessionEnd hook).

**Implements:** REQ-005.

**Public API (module-level functions):**

- `is_worktree(worktree_path: str) -> bool` — True iff `git rev-parse --git-dir`
  from `worktree_path` returns a path containing `/worktrees/`. Returns False
  on any git failure (fail-closed; never raises).
- `is_sticky_failed(worktree_path: str) -> bool` — True iff
  `<worktree_path>/.review-state.json` exists, parses, and
  `stage_failed` is non-null.
- `run_hook(*, worktree_path: str, payload: dict) -> int` — applies skip
  conditions; on eligibility, runs `python -m mahavishnu.core.merge_to_main`
  via subprocess. Returns 0 on skip, or the subprocess returncode.

**Skip conditions (in order, all checked before any subprocess call):**

1. `MAHAVISHNU_AUTO_MERGE` env var set to a falsy value (`=0`, `=false`,
   `=no`, `=off`). Unset defaults to "auto-merge on" per spec §4.2 — the
   user has explicitly chosen default-on for this workflow.
1. `worktree_path` is empty / unresolvable.
1. `is_worktree(worktree_path)` returns False (not inside a git worktree).
1. `is_sticky_failed(worktree_path)` returns True.

**Constants:**

- `AUTO_MERGE_ENV = "MAHAVISHNU_AUTO_MERGE"`
- `REVIEW_STATE_FILENAME = ".review-state.json"` (imported from
  `mahavishnu.core.merge_to_main` for symmetry; falls back to the literal
  if the import fails to keep the hook stdlib-only when mahavishnu is
  not installed).

**Module structure:**

- `from __future__ import annotations` as the first non-comment line.
- Module load must be stdlib-only (no `import mahavishnu` at module level;
  the import is gated behind the elibility check, mirroring the
  `worktree-session-isolation.py` pattern).
- All code paths return an int (the spec says exit-0-always is fine for
  skip conditions; failure of the subprocess propagates its rc).
- `_log(msg: str)` writes to stderr with `merge-to-main-hook: ` prefix
  (Claude Code surfaces stderr as Hook output).

**Tests:** Create `tests/unit/hooks/test_agent_merge_on_end.py` with 2 tests:

1. `test_is_sticky_failed_true_when_stage_failed_set` — write a temp dir
   with a `.review-state.json` containing `"stage_failed": "stage_6_cleanup"`
   (and required schema keys), call `is_sticky_failed(tmp_path)`, assert True.
1. `test_is_sticky_failed_false_when_marker_absent_or_clean` — call
   `is_sticky_failed(tmp_path)` on a dir with no `.review-state.json`,
   assert False.

These cover the spec's only "sticky failure" branch (the
".review-state.json marks the worktree as 'stage 6 cleanup failed; user must resolve'"
skip condition). Skipping tests for `is_worktree` (already tested in
`tests/unit/test_worktree_session_isolation_hook.py` — same
`git rev-parse --git-dir` pattern) and `run_hook` (would require mocking
the subprocess invocation; the existing test pattern in
`tests/unit/test_worktree_session_isolation_hook.py` tests helpers, not
end-to-end lifecycle paths through `run_hook`, per the multi-agent review
of 2026-07-20).

**Commit message:**

```
feat(mahavishnu): SessionEnd hook for merge-to-main (REQ-005)

Per spec §4.2: fires only on MAHAVISHNU_AUTO_MERGE=1, skips when
not in a worktree or .review-state.json marks sticky failure.
Coexists with worktree-session-isolation.py (existing SessionEnd
handler runs first, this hook runs second).

Co-Authored-By: Claude Code <noreply@anthropic.com>
```
