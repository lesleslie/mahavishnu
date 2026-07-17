---
status: resolved
role: implementation
date: 2026-07-17
last_reviewed: 2026-07-17
superseded_by: null
topic: session-worktree-isolation
---

# Per-Session Worktree Isolation

## Status

**Resolved.** Implementation landed across two commits:

- `5a7e001c` — Phase 1: registry + CLI (`mahavishnu worktree list-sessions`,
  `mahavishnu worktree prune-abandoned`)
- `ccec4357` — Phase 2: hook wiring (`.claude/hooks/worktree-session-isolation.py`
  + `.claude/settings.json` registration)

Opt-in via `MAHAVISHNU_AUTO_WORKTREE=1`. Default-off — no behavior change
without the env var.

Pickup context: `docs/followups/.archive/2026-07-16-multi-session-mcp-contention.md`
flagged this as a remaining mitigation after the multi-session MCP
contention fix landed.

## What landed

### Registry (`mahavishnu/core/worktree_session_registry.py`)

Single-source-of-truth map from Claude session UUID → git worktree path.
Schema-versioned JSON file at the XDG state path. Hardened with `chmod
0o600` + parent `chmod 0o700`, `O_NOFOLLOW` on open (CWE-59),
`fcntl.flock` for concurrent-safe writes.

CRUD API: `register`, `get`, `mark_abandoned`, `remove`, `list_active`.
18 unit tests + 1 multiprocessing-pool test for flock correctness.

### CLI subcommands (`mahavishnu/worktree_cli.py`)

- `mahavishnu worktree list-sessions [--state active|abandoned|all]
  [--older-than-days N]` — table view of the registry.
- `mahavishnu worktree prune-abandoned [--older-than-days N] [--dry-run]`
  — removes abandoned registry entries older than N days. **NEVER
  removes the actual git worktree** — user must run
  `mahavishnu worktree remove <repo> <path>` for that.

### Hook (`.claude/hooks/worktree-session-isolation.py`)

Registered for `SessionStart` and `SessionEnd` in `.claude/settings.json`,
running alongside the existing `bodai-activity-subscriber` hook.

- **Default-off**: `MAHAVISHNU_AUTO_WORKTREE` unset → returns 0 in `<2ms`,
  zero side effects, no mahavishnu imports.
- **SessionStart** (when opted in): computes short session id, checks
  if cwd is already a worktree, looks up the registry, then runs
  `git -C cwd worktree add -B <branch> <path> <base>` via direct
  subprocess (bypasses `MahavishnuApp.load()` to keep SessionStart
  cost <2s — reviewer explicitly flagged the full mahavishnu stack
  as too heavy for a hook).
- **SessionEnd**: marks the worktree `abandoned` in the registry.
  No auto-removal.

12 unit tests covering the hook's internal helpers and main() flow.

### Documentation

- `docs/CONFIGURATION.md` — adds the per-session worktree env-var
  section with effect descriptions.
- `docs/CLI_REFERENCE.md` — adds a worktree-management section
  including the new `list-sessions` and `prune-abandoned` examples.
- `.claude/decisions/session-worktree-defaults.md` — decision record
  for opt-in default + threat model.

## Why opt-in (not default-on)

Three reasons, in order of weight:

1. **User agency.** A Claude session that auto-creates a worktree on
   its own changes the user's filesystem without explicit consent.
2. **Optics.** First-time users seeing `~/worktrees/agent-a0c5d2a0`
   appear unbidden may not realize what created it.
3. **Escape hatch.** Default-on with a kill-switch is more error-prone
   than default-off with an explicit opt-in.

Full threat model: see `.claude/decisions/session-worktree-defaults.md`.

## Manual smoke (run on the project's own repo)

```bash
# 1. Default-off (no env var) → opens normally
unset MAHAVISHNU_AUTO_WORKTREE
# (run `claude` and confirm no worktree appears, no stderr noise)

# 2. Opt-in → creates per-session worktree at ~/worktrees/agent-XXXXXXXX
export MAHAVISHNU_AUTO_WORKTREE=1
# (run `claude` and watch for "worktree ready: ..." in stderr)

# 3. Verify worktree + branch
cd ~/worktrees/agent-XXXXXXXX
git status           # clean working tree on worktree-agent-XXXXXXXX
git branch --show-current

# 4. Exit Claude → worktree marked abandoned
mahavishnu worktree list-sessions --state abandoned

# 5. Cleanup preview
mahavishnu worktree prune-abandoned --older-than-days 0 --dry-run

# 6. Apply cleanup
mahavishnu worktree prune-abandoned --older-than-days 0

# 7. Remove the git worktree itself (manual, never automatic)
mahavishnu worktree remove mahavishnu ~/worktrees/agent-XXXXXXXX
```

## Out of scope

- **Multi-machine registry coordination**: assumes local FS.
- **Windows support**: `fcntl.flock` is POSIX-only.
- **Per-user ACLs**: assumes single-user dev box.

## Cross-references

- 4-lens plan: `/Users/les/.claude/plans/cheerful-marinating-fountain.md`
- Decision record: `.claude/decisions/session-worktree-defaults.md`
- Pickup context: `docs/followups/.archive/2026-07-16-multi-session-mcp-contention.md`
- Phase 1 commit: `5a7e001c`
- Phase 2 commit: `ccec4357`
