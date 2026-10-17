---
status: complete
role: implementation
topic: cli-deprecation-drift
date: 2026-10-09
last_reviewed: 2026-10-17
superseded_by: null
blocks_on: []
---

# `mahavishnu pool spawn` — Stale Worker-Type Allowlist (post 2026-09-24 deprecation)

**Resolved 2026-10-17** (commit `7b66eb1b`): the orphan commit
`7949887b` (the original 2026-10-09 demo-session fix) was sitting
in git history on no current branch. The diff was manually applied
to main and committed. All 3 proposed fix items landed:

1. `SPAWN_WORKER_TYPE_ALLOWLIST` collapsed from 5 entries to 2
   (`{"shepherd", "gateway-openclaw"}`); `SPAWN_WORKER_TYPE_ERROR_HINT`
   rewritten to point at the decision doc + the followup itself.
2. The `worker_type not in {set literal}` inline check replaced with
   `worker_type not in SPAWN_WORKER_TYPE_ALLOWLIST` + the new error
   hint echo.
3. `tests/unit/cli/test_spawn_allowlist.py` (151 LOC) pins the
   allowlist shape so this drift cannot recur silently.

Bonus (also landed in the same commit): `WorkerManager._validate_required_tool`
now enriches the error envelope with the current `PATH` and a
`fix_hint` recommending `MAHAVISHNU_NO_EXTRA_PATH=1` or the
`scripts/launch_mcp.py` PATH bootstrap. Pinned by
`tests/unit/workers/test_manager_validate_tool.py` (130 LOC).

**Test run:** `12 passed` across the two new test files
(`test_spawn_allowlist.py` 7 tests + `test_manager_validate_tool.py` 5 tests).
The orphan's full diff was applied with two targeted edits instead
of a 3-way cherry-pick because the conflict against the
post-orphan `reap_cli` changes was non-trivial to resolve.

Refs: `docs/decisions/2026-09-24-legacy-worker-deprecation.md`,
`docs/plans/2026-09-10-bodai-serverless-readiness-phase-1-fixes.md` (sibling fix pattern),
`feedback-cli-flag-consumer-wiring.md` (related: CLI surface drift).

## Problem

`mahavishnu pool spawn --worker-type terminal-claude` — the **documented
default** per `pool spawn --help` — fails immediately because
`terminal-claude` was retired on 2026-09-24
(`docs/decisions/2026-09-24-legacy-worker-deprecation.md`). The CLI
allowlist at `mahavishnu/_main_cli.py:1803-1811` still names the five
retired types and gates the spawn call on membership. Operators who
follow the help text hit a confusing failure: the help promises one
behavior, the code refuses the request.

The retirement decision says "for new isolated workloads use
`worker_type='shepherd'`, for non-isolated workloads use
`mahavishnu/pools/`" — but neither is in the CLI allowlist, so the
recommended path is *unreachable* through the CLI. The registry
(`mahavishnu/workers/registry.py:114`) lists 14+ `terminal-*` worker
types (`terminal-shell`, `terminal-python`, `terminal-qwen`,
`terminal-codex`, `terminal-deepagents`, `terminal-clai`,
`terminal-crow`, `terminal-ipython`, `terminal-node`, `terminal-ssh`,
`terminal-mysql`, `terminal-psql`) — most of which are also unreachable
through the CLI.

## Reproduction

```bash
$ export PATH="/Users/les/.local/bin:$PATH"   # claude on PATH for spawn
$ mahavishnu pool spawn --type mahavishnu --name demo-tmux-pool \
    --min 1 --max 3 --worker-type terminal-claude
2026-10-09 19:40:48,408 | INFO | Using tmux terminal adapter
2026-10-09 19:40:48,408 | INFO | Initialized TerminalManager with tmux adapter (max_concurrent=20)
...
2026-10-09 19:40:48,430 | ERROR | Failed to spawn pool: worker_type='terminal-claude' is no longer supported.
❌ Failed to spawn pool: worker_type='terminal-claude' is no longer supported.
   The legacy isolated-worker surface has been retired — see
   docs/decisions/2026-09-24-legacy-worker-deprecation.md.
   For new isolated workloads use worker_type='shepherd'.
   For non-isolated workloads use mahavishnu/pools/.
```

## Surface

- `mahavishnu/_main_cli.py:1803-1811` — allowlist check (root cause)
- `mahavishnu/_main_cli.py:1810` — error message names the retired types
  (also stale)
- `mahavishnu/workers/registry.py:114` — registry still lists retired
  types (intentional, per the decision: registry stays for type
  resolution; deprecation just blocks spawn)
- `docs/decisions/2026-09-24-legacy-worker-deprecation.md` — the
  authoritative "what to do instead" doc; CLI surface drifted away

## Proposed Fix (3 layered changes)

1. **Update the allowlist** at `mahavishnu/_main_cli.py:1803-1811` to
   include `shepherd` (and document the post-deprecation intent).
   Allowlist should narrow to **currently supported** worker types per
   the decision doc: `shepherd`, and the post-deprecation workflow-engine
   path is `mahavishnu/pools/` (handled by `mahavishnu pool execute` /
   `mcp__mahavishnu__pool_route_execute`, not by `pool spawn`).
2. **Refresh the error message** at `_main_cli.py:1810` to point at the
   decision doc and the recommended workflow-engine path, instead of
   re-stating the deprecated allowlist.
3. **Add a smoke test** `tests/unit/cli/test_spawn_allowlist.py` that
   imports the allowlist set, asserts `shepherd in it`, and asserts each
   member points at a real `WORKER_REGISTRY` entry. This is a 5-min
   one-time integration guard that catches the same class of drift.

## Discovered During

Demo of Mahavishnu tmux workers (session 2026-10-09). The follow-up
itself took three attempts to surface: (a) `_validate_required_tool`
rejected `terminal-claude` from the MCP layer because `claude` wasn't on
the launchd-inherited `PATH`; (b) once PATH was fixed, the CLI allowlist
rejected the same retired type; (c) the *registry* still has `terminal-cl`
as an entry — which would mislead anyone reading `registry.py` to think
`terminal-cl` is reachable through the spawn CLI. The 3-failure cascade
is why this note was filed; a single point of failure would have been a
bug fix, but the drift across three surfaces indicates a missing
verification hook.

## Cross-Reference

- `feedback-mahavishnu-c1-plan-index-circular-dep.md` (sibling fix pattern)
- `feedback-cli-flag-consumer-wiring.md` (related: CLI surface drift)
- `docs/decisions/2026-09-24-legacy-worker-deprecation.md` (decision)
