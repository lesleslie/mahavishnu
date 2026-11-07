---
status: complete
role: implementation
kind: plan
date: 2026-11-07
last_reviewed: 2026-11-07
superseded_by: null
topic: quality-gate-complexity
title: "Reduce pyscn complexity in four MCP/CLI hotspots and clear the redundant-cast ty warning"
requirements:
  - id: REQ-CX-001
    title: "pool_route_execute complexity at or below 25"
    description: "Decompose mahavishnu/mcp/tools/pool_tools.py::register_pool_tools.pool_route_execute (measured 48) into single-concern helpers so the pyscn gate passes."
  - id: REQ-CX-002
    title: "team_from_goal complexity at or below 25"
    description: "Decompose mahavishnu/mcp/tools/goal_team_tools.py::register_goal_team_tools.team_from_goal (measured 35) into single-concern helpers so the pyscn gate passes."
  - id: REQ-CX-003
    title: "prune_merged_worktrees._run complexity at or below 25"
    description: "Decompose mahavishnu/worktree_cli.py::prune_merged_worktrees._run (measured 29) into single-concern helpers so the pyscn gate passes."
  - id: REQ-CX-004
    title: "cross_repo_search complexity at or below 25"
    description: "Decompose mahavishnu/mcp/tools/search_tools.py::register_search_tools.cross_repo_search (measured 28) into single-concern helpers so the pyscn gate passes."
  - id: REQ-CX-005
    title: "No redundant bool cast in repository_surface"
    description: "Remove the redundant cast('bool', ...) at mahavishnu/core/repository_surface.py:191 flagged by ty as redundant-cast."
---

# Reduce pyscn complexity in four MCP/CLI hotspots

## 1. Outcome

`crackerjack run -v` reports **0 pyscn issues** and **0 ty errors** for the
mahavishnu repo, with every currently-passing test still passing.

Success signal: the two failing comprehensive hooks (`pyscn`, `ty`) flip to
`passed`, and the reported total moves from `Total: 11 | Passed: 9 | Failed: 2`
to `Total: 11 | Passed: 11 | Failed: 0`.

## 2. Goals

1. Bring all four flagged functions to a pyscn complexity of **≤ 25**.
1. Clear the single `ty` `redundant-cast` warning.
1. Preserve observable behaviour exactly: same return payloads, same log
   lines, same exception semantics, same ordering of side effects.
1. Keep the MCP tool schemas byte-identical (FastMCP derives them from the
   decorated function's signature, so signatures must not change).

## 3. Non-Goals

1. **Not** raising the pyscn threshold. The threshold lives in a *different
   repo* (`crackerjack/models/tool_config.py:19`) and is a cross-repo policy
   decision — changing it here would be an unrequested, ecosystem-wide edit.
1. **Not** adding `# noqa: C901` suppressions. Ruff's `C901` is not in this
   repo's active rule set (`I, N, UP, B, C4, SIM, TCH` + `P` subset), and pyscn
   does not honour `noqa` anyway — the only mechanism that actually moves the
   gate is lowering the measured complexity.
1. **Not** refactoring `register_goal_team_tools.parse_goal` (measured 19,
   below threshold).
1. **Not** touching any behaviour the 173-test baseline does not cover.

## 4. Current Findings

The gate failure is **not** a threshold regression from 15 → 25. It is a
metric change plus four functions that were never compliant under the
metric actually being enforced.

- Crackerjack enforces `PYSCN_MAX_COMPLEXITY = 25`
  (`crackerjack/models/tool_config.py:19`). The prior value of 15 was
  calibrated against the pre-pyscn-1.30 metric and **was never actually
  enforced** — pyscn 1.5.0 could not parse this repo's PEP 758
  `except A, B:` files and reported no violations at all.
- Local pyscn is **1.33.0** (the post-1.30 metric), under which the same
  function scores roughly 1.8× its pre-1.30 value.
- The repo's own `.pyscn.toml` sets `max_complexity = 0` ("no limit"), but
  that knob only affects pyscn's own report — crackerjack filters the JSON
  with its own hardcoded 25, so the repo-local config cannot move the gate.

Measured with `pyscn analyze --select complexity` (threshold 25):

| Function | File:line | Complexity | Cognitive | SLOC |
|---|---|---|---|---|
| `pool_route_execute` | `mcp/tools/pool_tools.py:757` | **48** | 105 | 309 |
| `team_from_goal` | `mcp/tools/goal_team_tools.py:53` | **35** | 59 | 320 |
| `prune_merged_worktrees._run` | `worktree_cli.py:333` | **29** | 46 | 122 |
| `cross_repo_search` | `mcp/tools/search_tools.py:234` | **28** | 42 | 185 |
| `parse_goal` (not flagged) | `mcp/tools/goal_team_tools.py:444` | 19 | 25 | 159 |

Both offending modules already carry prose claiming "Structural C901
suppression" in their docstrings. Prose is not a suppression — neither ruff
nor pyscn reads it — so the gate correctly still fails.

Baseline: `173 passed` across the seven affected test modules.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-CX-001
    title: "pool_route_execute complexity at or below 25"
  - id: REQ-CX-002
    title: "team_from_goal complexity at or below 25"
  - id: REQ-CX-003
    title: "prune_merged_worktrees._run complexity at or below 25"
  - id: REQ-CX-004
    title: "cross_repo_search complexity at or below 25"
  - id: REQ-CX-005
    title: "No redundant bool cast in repository_surface"
```

## 5. Implementation Phases

### Phase 1: `ty` redundant cast

**Goal:** clear `mahavishnu/core/repository_surface.py:191:20: warning[redundant-cast]`.

**Tasks:**
- `check_user_repo_permission` casts the result of `asyncio.run(...)` to
  `bool`. `rbac_manager.check_permission` already returns `bool`, so the
  cast is a no-op that `ty` flags. Drop both casts (the one at :189 inside
  the thread-pool branch and the one at :191 in the fallback branch) — both
  are equally redundant.

**Exit criteria:** `ty check mahavishnu/core/repository_surface.py` reports
no diagnostics for the file.

#### Integration Contract
- **Triggered from**: `check_user_repo_permission(app, user_id, repo_path)`,
  called from the repository-surface resolution path in the same module.
- **Returns to / updates**: unchanged — a `bool` permission verdict. Only
  the redundant `cast("bool", ...)` wrapper is removed.
- **Demonstrable by**: `ty check mahavishnu/core/repository_surface.py`
  exits clean; `pytest tests/unit -k repository_surface` passes.
- **Rollback signal**: any `repository_surface` test regressing to a
  non-`bool` verdict — revert the cast removal.
- **Observability added**: none. This phase removes a type-checker
  diagnostic, it adds no runtime behaviour.

### Phase 2: `pool_route_execute` decomposition

**Goal:** 48 → ≤ 25 in `mahavishnu/mcp/tools/pool_tools.py`.

**Tasks:** extract twelve module-level helpers, each owning one concern,
and reduce the MCP tool body to a linear orchestration:

| Helper | Concern |
|---|---|
| `_resolve_pool_selector` | wire string → `PoolSelector` enum; invalid-selector + subsystem-unavailable responses |
| `_coerce_caller_kind` | wire string → `CallerKind`, fail-soft to `None` |
| `_classify_prompt` | prompt → `TaskCategory`, fail-soft to `None` |
| `_resolve_auto_spawn` | `None` → config lookup, fail-safe to `False` |
| `_lookup_idempotency` | lookup-or-create the idempotency record; fail-closed store errors; duplicate hit |
| `_acquire_concurrency_slot` | per-category gate acquire; raise `RateLimitError` |
| `_prepare_worktree` | isolated worktree creation; lock-conflict response |
| `_finalize_worktree` | attach diff/merge summary to the result |
| `_cleanup_worktree` | remove the worktree, non-fatal on failure |
| `_mark_idempotency_completed` | record the dispatch result |
| `_mark_idempotency_failed` | record the dispatch failure |
| `_map_dispatch_error` | exception → structured response payload |

**Exit criteria:** `pyscn` measures `pool_route_execute` ≤ 25; the
`pool_tools` tests still pass unchanged.

#### Integration Contract
- **Triggered from**: the `pool_route_execute` MCP tool
  (`mcp__mahavishnu__pool_route_execute`), registered by
  `register_pool_tools` in `mahavishnu/mcp/tools/pool_tools.py`.
- **Returns to / updates**: the same `dict[str, Any]` dispatch envelope the
  tool returns today — `{"status": "duplicate"|"rate_limited"|"timeout"|
  "invalid_selector"|"worktree_conflict"|"failed"}` plus the dispatch
  result. No new state store is introduced.
- **Demonstrable by**: `pytest tests/unit/test_mcp_pool_tools.py
  tests/unit/mcp/test_pool_dispatch_timeout.py` passes, and
  `mcp__mahavishnu__pool_route_execute` returns an unchanged envelope for a
  duplicate idempotency key and for a saturated concurrency gate.
- **Rollback signal**: any pool-dispatch test failing, or the
  `pool_route_execute` status vocabulary changing — revert the phase.
- **Observability added**: none new. Every existing structured log line
  (`IDEMPOTENCY_NOT_CONFIGURED`, `IDEMPOTENCY_STORE_UNAVAILABLE`,
  `IDEMPOTENCY_CIRCUIT_OPEN`, `WORKTREE_LOCK_CONFLICT`,
  `WORKTREE_CREATION_FAILED`, `WORKTREE_COMPLETION_FAILED`,
  `WORKTREE_CLEANUP_FAILED`, `IDEMPOTENCY_MARK_COMPLETED_FAILED`,
  `IDEMPOTENCY_MARK_FAILED_FAILED`) and the `auto_spawn_resolved` /
  `idempotency_key` log fields are preserved verbatim.

### Phase 3: `team_from_goal` decomposition

**Goal:** 35 → ≤ 25 in `mahavishnu/mcp/tools/goal_team_tools.py`.

**Tasks:** extract the four `except` handlers into response builders, and
the repeated `if ws_server: await ws_server.broadcast_team_error(...)`
blocks into a single `_broadcast_team_error` helper; extract goal/mode
validation, the Prometheus metric block, the auto-run execution block, and
the result assembly.

**Exit criteria:** `pyscn` measures `team_from_goal` ≤ 25; the
`goal_team_tools` tests still pass unchanged.

#### Integration Contract
- **Triggered from**: the `team_from_goal` MCP tool
  (`mcp__mahavishnu__team_from_goal`), registered by
  `register_goal_team_tools`.
- **Returns to / updates**: the same `dict[str, Any]` envelope —
  `{"success": True, "team_id": ..., "config": ..., "parsed_goal": ...}` or
  `{"success": False, "error": {"code", "message", "details"}}`. The
  Prometheus counters and the WebSocket `broadcast_team_*` events are
  emitted unchanged.
- **Demonstrable by**: `pytest tests/unit/test_mcp_goal_team_tools.py
  tests/unit/test_goal_team_tools.py` passes — in particular the
  too-short-goal, too-long-goal, missing-task, and invalid-mode cases,
  each of which asserts a specific error code and message.
- **Rollback signal**: a goal-team test failing on error code, message, or
  the presence/absence of the `details` key — revert the phase.
- **Observability added**: none new. `metrics.record_error`,
  `metrics.record_goal_parsed`, `metrics.record_skills_usage`,
  `metrics.record_team_created`, `metrics.increment_active_teams`,
  `metrics.set_team_info`, and `metrics.record_learning_outcome` are all
  called on the same conditions as before.

### Phase 4: `prune_merged_worktrees._run` decomposition

**Goal:** 29 → ≤ 25 in `mahavishnu/mcp/tools/worktree_cli.py`.

**Tasks:** extract repo resolution, candidate scanning, the dry-run
renderer, and the results renderer out of the nested `_run` coroutine.

**Exit criteria:** `pyscn` measures `_run` ≤ 25; the worktree prune tests
still pass unchanged.

#### Integration Contract
- **Triggered from**: `mahavishnu worktree prune-merged` (Typer command in
  `mahavishnu/worktree_cli.py`).
- **Returns to / updates**: the same stdout/stderr text and the same JSON
  payloads (`{"candidates": [...], "would_remove": N}` for `--dry-run
  --json`, and `{"removed_count", "failed_count", "results"}` for `--json`).
  Worktrees are removed by the same `WorktreePruner.remove(...)` call.
- **Demonstrable by**: `pytest tests/unit/test_worktree_prune_merged.py`
  passes, and `mahavishnu worktree prune-merged --dry-run --json` emits
  the same JSON shape.
- **Rollback signal**: a prune test failing on CLI output or on the exit
  code (1 when any removal failed) — revert the phase.
- **Observability added**: none new. The `typer.echo(..., err=True)`
  diagnostics for a missing coordinator, missing repo manager, missing
  `force_reason`, unknown repo, and repo without a canonical nickname are
  preserved.

### Phase 5: `cross_repo_search` decomposition

**Goal:** 28 → ≤ 25 in `mahavishnu/mcp/tools/search_tools.py`.

**Tasks:** extract the Akosha fan-out and the Session-Buddy fan-out into
two helpers, plus the result-unwrapping and de-duplication steps.

**Exit criteria:** `pyscn` measures `cross_repo_search` ≤ 25; the
search tests still pass unchanged.

#### Integration Contract
- **Triggered from**: the `cross_repo_search` MCP tool
  (`mcp__mahavishnu__cross_repo_search`), registered by
  `register_search_tools`.
- **Returns to / updates**: the same envelope — `query`, `scope`,
  `query_hash`, `sources`, `combined`, `total_combined`, `repos_seen`,
  `spans_3_components`, `mode`, and the optional `channel`. The
  `cross-repo:{query_hash}` WebSocket room broadcast is unchanged.
- **Demonstrable by**: `pytest tests/unit/test_mcp_search_tools.py
  tests/unit/test_cross_repo_search.py tests/unit/test_cross_repo_mcp_tool.py`
  passes — in particular the degraded-mode case where one source is
  unreachable.
- **Rollback signal**: a search test failing on the `mode` value
  (`fanout` vs `degraded`), the `sources` entries, or the de-duplication
  order — revert the phase.
- **Observability added**: none new. The `cross_repo_search: <source>
  fan-out failed` warnings and the `websocket broadcast failed` warning are
  preserved.

## 6. Required Code Changes

- [ ] `mahavishnu/core/repository_surface.py` — drop the redundant casts
- [ ] `mahavishnu/mcp/tools/pool_tools.py` — 12 new helpers, slimmed tool body
- [ ] `mahavishnu/mcp/tools/goal_team_tools.py` — validation / broadcast / error-response helpers
- [ ] `mahavishnu/worktree_cli.py` — repo-resolution / scan / render helpers
- [ ] `mahavishnu/mcp/tools/search_tools.py` — per-source fan-out helpers
- [ ] `docs/plans/2026-11-07-pyscn-complexity-refactor.md` — this plan

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `pyscn analyze --select complexity` on the 4 files | no function > 25 | report JSON |
| `ty check` on the 4 files + `repository_surface.py` | 0 errors | `ty` output |
| `pytest --no-cov` on the 7 affected modules | 173 passed | pytest summary |
| `pytest --no-cov` on the full unit suite | no regressions | pytest summary |
| `crackerjack run -v` | `pyscn` and `ty` hooks pass | gate summary |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Behaviour drift in an extracted branch | medium | Every helper is a verbatim extraction; the 173-test baseline gates each phase |
| Helper count grows the module surface | medium | Helpers are module-private (`_`-prefixed) and single-concern |
| FastMCP schema changes because the tool signature moved | low | The decorated signature is untouched; only the body is replaced |
| `except A, B:` (PEP 758) blocks pyscn parsing again | low | Both sites are preserved as-is; pyscn 1.33 parses them today |

## 9. Decision Rule

The work is done when `crackerjack run -v` reports both `pyscn` and `ty` as
passing, the seven affected test modules still report `173 passed`, and the
full unit suite shows no regressions. If a phase cannot be completed
without behaviour drift, ship the other phases and record the drift
explicitly rather than suppressing the gate.

## 10. Results (measured 2026-11-07)

All four target functions now measure below the 25 threshold. No function
in any of the four files exceeds 20.

| Function | Before | After | Requirement |
|---|---|---|---|
| `pool_route_execute` | 48 | **14** | REQ-CX-001 |
| `team_from_goal` | 35 | **14** | REQ-CX-002 |
| `prune_merged_worktrees._run` | 29 | **9** | REQ-CX-003 |
| `cross_repo_search` | 28 | **9** | REQ-CX-004 |

pyscn health score for the four files rose from 70/100 to 85/100, with
**0 high-risk functions** (was 4). `ty` reports 0 diagnostics across all
five changed files (REQ-CX-005 cleared the `redundant-cast` warning);
`ruff check` passes on all five.

### Regression evidence

- The seven directly-affected test modules report **173 passed** — identical
  to the pre-change baseline.
- The **full** unit suite was run twice in the *same* worktree: once with
  the change applied and once with the five files reverted to `HEAD`
  (via `git checkout HEAD --`, with the change preserved in
  `/tmp/refactor-backup/`). Both runs report **184 failed, 19073 passed,
  21 skipped, 17 errors** — the refactor contributes **zero** failures.
- The 184 failures are environmental: the same suite run in the main
  checkout reports only 89 failures, because the worktree lacks the
  git-ignored `docs/plans/.archive/` tree and other checkout-local
  artifacts. They are unrelated to the four refactored modules.
- `scripts/audit_requirements.py` reports **Orphans: 0** — all five
  `REQ-CX-*` declarations are traced to a `# req: REQ-CX-*` marker in
  code. (The worktree scan reports more phantoms than main only because
  `docs/plans/.archive/` is git-ignored and therefore absent from a
  worktree; the same audit in main reports 1 phantom, also pre-existing.)
- `tests/unit/test_acp_docs.py::TestCLIExamplesMatchHelp` is marked
  `xfail` by the repo with the note "CLI hangs on redirected stdio (Typer
  bug)". It is order-sensitive and flips between xpass and xfail between
  runs; it does not touch any of the five changed modules.

## References
- `crackerjack/models/tool_config.py:19` — `PYSCN_MAX_COMPLEXITY = 25` and
  the comment recording the 15 → 25 move and the pyscn 1.30 metric change.
- `crackerjack/parsers/json_parsers.py:573` — the pyscn parser that filters
  the JSON report at 25.
- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
