## name: bodai-worktree-cleanup description: "Scan Bodai repos for stale worktrees and surface a tier-grouped report. Triggers on 'scan worktrees', 'find stale worktrees', 'audit bodai worktrees', 'list orphaned worktrees' (worktree-context-only — does NOT fire on generic 'low on disk space' or non-worktree cleanup)."

# Bodai Worktree Cleanup

Scoped worktree health-check for the Bodai ecosystem. Produces a
tier-grouped report of every non-main worktree across Bodai repos so the
operator can decide what to remove — the skill itself does NOT auto-remove.

## When to use

- The user asks for a worktree health check ("scan worktrees", "find stale
  worktrees", "audit bodai worktrees", "list orphaned worktrees").
- The user mentions orphan cleanup in an explicit worktree context.
- The user wants a tier-grouped report of all non-main worktrees across
  every Bodai repo registered in `repos.yaml` / `ecosystem.yaml`.

## Do NOT use for

- **Generic "low on disk space"** — likely Docker images, build artifacts,
  caches, or logs. Not in scope for the worktree scanner.
- **Cross-repo cleanup of `/tmp/<branch>` from `Workflow({script: parallel()})`
  fanouts** — use the recipe in
  `.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md`.
- **Branch cleanup** — use `commit-commands:clean_gone`. It handles
  `[gone]` branches only; worktrees are a separate axis.

## Quick start

```bash
# Direct CLI invocation
python -m mahavishnu.worktree_cli scan --repo=ALL --format=text

# Or via the Bash-friendly wrapper (recommended for skill invocations)
python /Users/les/Projects/mahavishnu/.claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py --repo=ALL --format=text
```

Add `--include-dirty` and/or `--include-locked` for per-worktree detail.
Add `--format=json` for machine-readable output. The default
`--age-threshold-days 30,9` matches the v4 rubric (Tier A ≥ 30d,
Tier C 9-30d, Tier D < 9d).

## Output interpretation

The CLI emits one line per worktree with a tier letter. Tier assignment
is first-match-wins (see `worktree-cleanup-policy.md` § Decision rule):

| Tier | Meaning | What to do |
|------|---------|------------|
| **A-merged** | Branch fully merged into main, no dirty state | `mahavishnu worktree prune-merged` |
| **A-merged-dirty** | Merged + uncommitted changes | `git worktree remove --force --force-reason="<reason>"` (per `worktree-autoremove-policy.md` Rule 4) |
| **A-orphan-detached** | Detached HEAD, NOT a plan orphan | `git worktree remove`; check it is not `git bisect` first |
| **X** | Cross-repo plan-orphan (same-date pattern in ≥ 2 repos) | Group removal across all repos; plan completed |
| **B** | Agent-dispatch leftover (`agent-*`) | `git worktree remove --force` (after salvage per the decision doc) |
| **C** | Feature branch, mid-age (9-30d) | Review branch; salvage untracked files if dirty |
| **D** | Recent (< 9d) | **Do NOT touch** — might be active |

**LOCKED-live**: A worktree whose lock file has a live Claude PID. **DO
NOT remove** until the operator verifies the PID is dead
(`ps -p <pid> -o command=` and confirm the command starts with `claude`
or `python.*mahavishnu` — PID recycling is real).

**LOCKED-orphan**: Lock file present but PID is dead. Safe to
`git worktree unlock` + remove.

## Caveats

- **The skill does NOT auto-remove anything.** The CLI is scan-and-report
  only. Removal is always an explicit operator action.
- For full automation (SessionEnd hooks, cron), see
  `.claude/decisions/worktree-autoremove-v4-followup.md` — currently
  deferred, gated on `RemoteWorktreeProvider` production-ready.
- **Do NOT use session-buddy's `remove_worktree` MCP tool for locked
  worktrees** (per memory `session-buddy-mcp-remove-worktree-bugs`). Use
  `git worktree remove` directly.
- **Never bypass the v4 prohibition** on auto-removal. Even when
  `--force -f -f` would unlock-and-remove, the CLI does not perform it.

## Relationship to existing skills

- `commit-commands:clean_gone` — different scope (branches, not
  worktrees); complementary.
- `cleanup-checkpoint-archive` — archives session content; no worktree
  handling.
- `session-buddy:mcp:remove_worktree` — has known bugs; prefer
  `git worktree remove` directly (see cited memory).

## Spec

- Canonical rules: `.claude/decisions/worktree-cleanup-policy.md`
- Tier rubric and lock + live-PID semantics: same doc, § Decision rule
  and § Lock + live-PID semantics
- Origin plan: `docs/superpowers/plans/2026-09-07-worktree-cleanup.md`
- Implementation:
  - `mahavishnu/core/worktree_scan.py` (classifier)
  - `mahavishnu/worktree_cli.py` (CLI)
