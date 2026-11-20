---
status: active
role: canonical
date: 2026-11-15
last_reviewed: 2026-11-15
topic: git-hooks
---

# Git hooks live in `<repo>/.git/hooks` — one location, no global dir

## Context

The fleet carried three separate git-hook systems, and a **global**
`core.hooksPath` that made them invisible:

1. **System A — the canonical one.**
   `mahavishnu/core/code_index/git_hooks.py` holds the hook templates;
   `mahavishnu index install-hooks <repo>` writes them into
   `<repo>/.git/hooks`. `_HOOK_NAMES` is
   `("post-commit", "post-merge", "post-rewrite", "pre-commit")`.
   The pre-commit template runs cheap repo-scoped gates: the
   `.mcp.json` secrets audit, the TYPE_CHECKING runtime-reference
   audit, the doc-frontmatter audit, and the `findings.md` 250-line
   budget.

2. **System B — deleted.**
   `scripts/install-bodai-git-hooks.sh` wrote a *different* pre-commit
   wrapper that ended in `exec uv run … mahavishnu git-hook pre-commit`, plus post-\* wrappers that published to the Oneiric
   bus. It was installed in **no** repo, and it was **broken**: its
   post-\* hooks ran `mahavishnu jot capture`, a command that never
   shipped (`mahavishnu jot` has no `capture` sub-command), so every
   post-commit it installed would print `No such command 'capture'`
   and exit non-zero. Removed 2026-11-15 along with the whole
   `mahavishnu git-hook` path it was the sole caller of.

3. **The global directory.**
   `~/.git-hooks/pre-commit` held a license-deletion guard, selected
   fleet-wide by `core.hooksPath=/Users/les/.git-hooks` in
   `~/.gitconfig`.

The global setting had two consequences nobody intended:

- **It shadowed every repo's own `.git/hooks/pre-commit`.** Only
  mahavishnu and crackerjack had a repo-local `core.hooksPath`
  override, so those two bypassed the global and the other 44 repos
  used it. Two repos had `pre-commit`-framework hooks that had been
  dead the whole time — and `jinja2-async-environment`'s referenced a
  `.pre-commit-config-fast.yaml` that no longer existed, so it would
  have failed the moment it was un-shadowed.
- **It hid a third-party dependency.** `akosha` and `mdinject` carried
  a `pre-commit` library dependency for configs that no longer ran.

A prior memory asserted "no pre-commit hook exists in any bodai repo"
and reached for `git commit --no-verify` on a misdiagnosis. The hook
existed the whole time.

Two commit-path costs were also hiding behind the same arrangement:

- `scripts/audit_no_secrets_in_mcp.py` was called with **no arguments**,
  and its default root is `/Users/les/Projects` — so every commit in
  every repo recursively globbed the entire `~/Projects` tree.
  `Path.rglob` cannot prune directories, so the walk descended into
  every `.venv` and `node_modules` tree: **103 s per commit**.
- `scripts/audit_type_checking_runtime_refs.py` had the same shape:
  it excluded `.venv` *after* the walk, discarding **28 575** files
  under this repo's `.venv` on every commit.

## Decision rule

- **One hook location per repo: `<repo>/.git/hooks`.** The global
  `~/.git-hooks` directory and the global `core.hooksPath` are gone
  (2026-11-15). The license-deletion guard they carried lives in the
  canonical template, so every repo has the same protection.
- **Do not set `core.hooksPath`.** Git resolves the `hooks` path in the
  *common* git dir, so a linked worktree already runs the main
  checkout's hooks (verified empirically 2026-11-15). A local
  `core.hooksPath` pointing at an absolute path also works but is not
  required — and pinning it breaks as soon as the repo moves.
- **The commit path is cheap. Crackerjack is the merge gate.**
  `CRACKERJACK_INVOCATION = "crackerjack run -v -f "` in
  `mahavishnu/core/merge_to_main.py:69`, at stage 3 of the
  squash-merge to `main`. No crackerjack invocation runs at commit
  time, in any hook.
- **The `pre-commit` framework is retired.** No `.pre-commit-config.yaml`
  in the fleet; crackerjack is the quality runner. The `pre-commit`
  library dependency is dropped from `akosha` and `mdinject`.
  (`[tool.creosote]` blocks containing `pre-commit = true` are
  creosote's own setting, not the library — leave them.)
- **Audit scripts are repo-scoped and prune while walking.** The
  secrets audit is invoked as `audit_no_secrets_in_mcp.py "$(pwd)"`;
  both audit scripts use `os.walk` with in-place pruning instead of
  `Path.rglob`.

## Status

Active — applied 2026-11-15.

- Global `~/.git-hooks` removed (backed up at
  `~/.local/state/mahavishnu/git-hooks-backup/`); global and
  repo-local `core.hooksPath` unset.
- 46 repos swept: the canonical pre-commit hook installed in each;
  `raindropio-mcp`'s own Bearer-token guard preserved with the
  license guard prepended; the two `pre-commit`-framework hooks
  backed up and replaced.
- Commit path: **~133 s → ~29 s** (secrets audit 103 s → 0.05 s;
  TYPE_CHECKING audit 30 s → 28 s — the remainder is the AST parse of
  1 793 sources, not traversal).
- `.pre-commit-config.yaml` removed from `mailgun-mcp`, `splashstand`,
  `mdinject`, `jinja2-inflection`; `pre-commit` dropped from
  `akosha` (dev group) and `mdinject` (dev extra), both re-locked.
  Archived repos under `ARCHIVED/` were skipped by operator instruction.
- Known gap: `scripts/install-bodai-git-hooks.sh` (System B) is still
  in the tree and still installs a *different* pre-commit wrapper than
  System A. It is installed nowhere, and its crackerjack dispatch is
  now inert, but the two installers should be reconciled so one
  canonical template serves the fleet.
- **Resolved later the same day (2026-11-15):** System B and the
  whole `mahavishnu git-hook` path it was the sole caller of were
  deleted — the script, `mahavishnu/git_hook_handlers.py`, the
  `git-hook` CLI sub-app, and both test modules. Git lifecycle events
  no longer reach the Oneiric bus; they did not reach it before
  either, because nothing called the dispatch. The bridge itself is
  unaffected — five Claude Code hooks call `bodai_hook_bridge.handle`
  directly.
