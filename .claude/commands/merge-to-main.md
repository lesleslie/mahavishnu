title: Merge To Main
owner: Operations Enablement Guild
last_reviewed: 2026-10-03
risk: high
status: active
id: 01K6EEXD5RD0SRFRY8NA5PZX17
category: workflow
description: >-
  Orchestrate the per-worktree merge cycle for the trunk-based
  agent-review workflow (ensemble review → crackerjack gate →
  squash-merge → auto-push → cleanup).
supported_platforms:
  - macOS
  - Linux
required_scripts: []
allowed-tools:
  - Bash
  - Read
required_tools:
  - mahavishnu:merge-to-main
  - crackerjack:run

______________________________________________________________________

## /merge-to-main

**Trunk-based agent-review merge cycle — REVIEW → GATE → SQUASH → PUSH → CLEANUP.**

This slash command orchestrates the per-worktree merge cycle for the trunk-based
agent-review workflow (per spec §4.1). The shared orchestration logic lives in
the Python module `mahavishnu.core.merge_to_main`; the markdown file is the
user-facing entry point.

## MiniMax compatibility note

This slash command is **disabled on MiniMax-modeled sessions**: the upstream
proxy at `https://api.minimax.io/anthropic` does not advertise `SlashCommand`
in its tool schema, so typing `/merge-to-main` produces a no-op from MiniMax.

**Workaround on MiniMax:** invoke the same logic via the `Skill` tool:

```
Skill(skill="merge-to-main", args="--review quick")
```

The `Skill` surface works on every model (native Anthropic, MiniMax, etc.).
The SessionEnd hook (`.claude/hooks/agent-merge-on-end.py`) is the primary
in-session surface and fires regardless of model.

## Usage

```
/merge-to-main [--branch <name>] [--review <mode>] [--no-push] [--no-cleanup] [--from <base>]
```

### Arguments (all optional)

- `--branch <name>` — the ephemeral branch to merge (default: current branch of cwd)
- `--review <mode>` — `quick` (skip ensemble), `default` (3-agent ensemble),
  `none` (user responsibility; explicit user opt-in required)
- `--no-push` — skip stage 5 (default: push to `origin/main`)
- `--no-cleanup` — skip stage 6 (default: prune the merged worktree)
- `--from <base>` — override rebase base (default: `origin/main` if remote
  exists, else `main`)

### Exit codes (spec §4.1)

| Code | Meaning |
|------|---------|
| `0` | Full success — review passed, gate passed, squash-merged, pushed, cleanup complete |
| `1` | Review failure — at least one ensemble verdict was `block`; merge aborted |
| `2` | Crackerjack failure — `crackerjack run -v` exited non-zero; merge aborted |
| `3` | Rebase conflict — `git rebase <base>` failed; user must resolve |
| `4` | Push divergence — `origin/main` moved during the brief; non-FF push refused |
| `5` | Cleanup failure — worktree pruned but post-merge state inconsistent; user must verify |

The command **never force-pushes**. Exit code 4 (push divergence) is the
fail-loud signal that the local `main` is no longer a fast-forward of
`origin/main`; the operator must resolve the divergence before retrying.

## What it does

The shared Python module orchestrates the 5-stage per-worktree cycle:

1. **Stage 2 — Ensemble review** (skippable via `--review quick` / `--review none`).
   Dispatches 3 agents (domain specialist + code-quality specialist +
   random generalist) via `mcp__mahavishnu__pool_route_execute`, parses
   each `<verdict>decision: …</verdict>` block, and aggregates via the
   spec §4.4 rule order (any block → block; ≥2 pass → proceed; else iterate).
2. **Stage 3 — Crackerjack gate**. Invokes `crackerjack run -v` (NEVER
   `-p`; the publish stage must never fire on the merge path — see
   REQ-013). Any non-zero exit blocks the merge with exit code 2.
3. **Stage 4 — Squash-merge**. The worktree's branch is never pushed;
   only the squashed result lands on `main`.
4. **Stage 5 — Auto-push** (skippable via `--no-push`). `git push origin main`,
   only on `main`, only after a successful squash-merge in stages 2–4.
5. **Stage 6 — Cleanup** (skippable via `--no-cleanup`). Routes through the
   existing `prune-merged` classifier to remove the ephemeral worktree.

**Idempotent and resumeable:** if a `.review-state.json` exists at the
worktree root, the module resumes from the current stage (schema version 1,
see `mahavishnu/core/merge_to_main.py`). Otherwise it starts at stage 2.

**Audit:** every merge writes a YAML frontmatter entry to the dev log
(`get_dev_log_path()` from `mahavishnu/core/paths.py`), with optional
session-buddy `store_reflection` mirror (best-effort; local file is canonical).

## Requirements

This command must be invoked from inside a worktree whose branch has
commits not yet merged into `<base>`. From a clean `main` checkout the
SessionEnd hook no-ops; from a worktree the slash command picks up
wherever `.review-state.json` left off.

## Environment variables

- `MAHAVISHNU_AUTO_MERGE=0` — explicit opt-out. The SessionEnd hook no-ops
  and the user must invoke `/merge-to-main` (or `Skill(skill="merge-to-main")`)
  manually. The slash command itself always runs regardless.

## See also

- Spec: `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4.1
- Module: `mahavishnu/core/merge_to_main.py`
- Tests: `tests/unit/core/test_merge_to_main.py`
- SessionEnd hook: `.claude/hooks/agent-merge-on-end.py`
- Dev-log writer: `mahavishnu/core/dev_log.py`
