---
status: complete
role: implementation
kind: plan
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by:
topic: quality-gate-complexity
title: "Bring 27 functions under the pyscn cyclomatic ceiling of 15"
requirements:
  - id: REQ-CX2-001
    title: "MCP tool surface functions at or below complexity 15"
  - id: REQ-CX2-002
    title: "Core runtime functions at or below complexity 15"
  - id: REQ-CX2-003
    title: "CLI command functions at or below complexity 15"
  - id: REQ-CX2-004
    title: "Engine, jot, TUI, websocket and bifrost functions at or below complexity 15"
---

# Bring 27 functions under the pyscn cyclomatic ceiling of 15

## 1. Outcome

The `pyscn` comprehensive hook in the mahavishnu repo flips from `failed` to
`passed`. Every function the hook measures above the enforced ceiling of
**15** is measured at **15 or below** by the same tool, with no change to
observable behaviour.

Success signal: `crackerjack run -v` reports the `pyscn` hook as `passed`,
and `pyscn analyze --select complexity --json --min-complexity 5 mahavishnu`
reports **zero** functions with `metrics.complexity > 15`.

## 2. Goals

1. Bring all 27 flagged functions to a measured complexity of **≤ 15**
   (target **≤ 12** for margin against re-measurement drift).
2. Preserve observable behaviour exactly: same return payloads, same log
   lines, same exception semantics, same ordering of side effects.
3. Keep every MCP tool schema byte-identical — FastMCP derives the schema
   from the decorated function's signature, so **signatures must not change**.
4. Leave the other comprehensive hooks (`ruff`, `ty`, `complexipy`) passing
   as they are today.

## 3. Non-Goals

1. **Not** raising the pyscn threshold. `PYSCN_MAX_COMPLEXITY = 15`
   (`crackerjack/models/tool_config.py:25`) was deliberately restored to 15 by
   the ADR-025 amendment of 2026-11-14; changing it is a cross-repo policy
   edit outside this plan.
2. **Not** adding `# noqa: C901` suppressions. `pyscn` does not honour
   `noqa`, and ruff's `C901` is not in this repo's active rule set
   (`I, N, UP, B, C4, SIM, TCH` + the `P` subset).
3. **Not** restructuring the `WORKTREE` / `pool` subsystems beyond the
   named functions.
4. **Not** refactoring functions that already measure at or below 15.

## 4. Current Findings

The gate failure is the *second* half of the metric change recorded in the
ADR-025 amendment of 2026-11-14.

- `crackerjack/models/tool_config.py:25` sets `PYSCN_MAX_COMPLEXITY = 15`.
  The ceiling is applied by `crackerjack/parsers/json_parsers.py:573`, not by
  a pyscn CLI flag — the repo-local `.pyscn.toml` sets `max_complexity = 0`
  ("no limit"), which only affects pyscn's own report and cannot move the
  gate.
- pyscn >= 1.30 changed how complexity is scored: the same function
  measures 13 under pyscn 1.5.0 and 23 under pyscn 1.33.0. The threshold of
  15 had therefore never actually been enforced — pyscn 1.5.0 could not parse
  this repo's PEP 758 `except A, B:` files.
- The 2026-11-07 plan (`docs/plans/2026-11-07-pyscn-complexity-refactor.md`)
  brought four functions under the then-current ceiling of **25**. It
  explicitly deferred `parse_goal` as "measured 19, below threshold" — a
  judgement that was correct at 25 and is wrong at 15. Those deferred
  functions are the ones now failing.
- `uv.lock` carries no pyscn change, so this is not a version-bump
  regression.

Measured baseline (pyscn 1.33.0, threshold 15, whole `mahavishnu` package):

| # | Function | File:line | CC | Cognitive | SLOC |
|---|---|---|---|---|---|
| 1 | `register_tasks_handoff_tools.mahavishnu_tasks_handoff_to_workflow` | `mcp/tools/tasks_handoff.py:505` | 22 | 33 | 130 |
| 2 | `RateLimiter.is_allowed` | `core/rate_limit.py:168` | 21 | 15 | 75 |
| 3 | `health_command._health` | `_main_cli.py:996` | 20 | 27 | 92 |
| 4 | `register_goal_team_tools.mahavishnu_parse_goal` | `mcp/tools/goal_team_tools.py:580` | 19 | 25 | 161 |
| 5 | `register_otel_tools.mahavishnu_ingest_otel_traces` | `mcp/tools/otel_tools.py:44` | 18 | 39 | 99 |
| 6 | `register_treesitter_tools.mahavishnu_treesitter_find_usages` | `mcp/tools/treesitter_tools.py:178` | 18 | 27 | 75 |
| 7 | `audit_health_async` | `mcp/tools/audit_health_tool.py:256` | 18 | 9 | 57 |
| 8 | `CapabilityRouter.route` | `core/task_router.py:464` | 18 | 19 | 89 |
| 9 | `_action_bifrost` | `bifrost/toggles.py:730` | 18 | 37 | 103 |
| 10 | `_format_json` | `core/worktree_scan.py:810` | 18 | 15 | 85 |
| 11 | `build_states` | `jot/fold.py:210` | 17 | 28 | 119 |
| 12 | `register_otel_tools.query_local_traces` | `mcp/tools/otel_tools.py:257` | 17 | 34 | 100 |
| 13 | `surface_relevant` | `jot/drain.py:1167` | 17 | 11 | 71 |
| 14 | `AgnoAdapter._resolve_legacy_llm_config` | `engines/agno_adapter_impl.py:1612` | 17 | 23 | 68 |
| 15 | `start_websocket_server` | `websocket/integration.py:33` | 16 | 28 | 97 |
| 16 | `rg_search` | `mcp/crow/tools/rg_search.py:79` | 16 | 27 | 91 |
| 17 | `SkillSynthesizer._derive_trigger_conditions` | `core/skill_synthesizer.py:119` | 16 | 18 | 41 |
| 18 | `find_merged_worktrees` | `core/worktree_prune_merged.py:192` | 16 | 40 | 67 |
| 19 | `CommandPalette.search` | `tui/command_palette.py:229` | 16 | 29 | 60 |
| 20 | `CredentialRedactor.redact_dict` | `core/secure_logging.py:231` | 16 | 29 | 66 |
| 21 | `CostOptimizer.check_budget_constraints` | `core/cost_optimizer.py:271` | 16 | 33 | 72 |
| 22 | `EcosystemLoader.validate_mcp_servers` | `core/ecosystem.py:277` | 16 | 27 | 42 |
| 23 | `run_validation` | `cli/config_validator.py:314` | 16 | 12 | 74 |
| 24 | `learning_stats` | `cli/team_cli.py:510` | 16 | 27 | 106 |
| 25 | `prune_stale_metadata._run` | `worktree_cli.py:539` | 16 | 20 | 73 |
| 26 | `_render_verification_output` | `metrics_cli.py:1035` | 16 | 25 | 98 |
| 27 | `ObservabilityManager._on_drift_warning` | `core/observability.py:1314` | 16 | 23 | 104 |

All paths are relative to `mahavishnu/`. 27 functions across 26 files.

**Why these functions measure high.** pyscn counts boolean operators and
comprehensions as decision points, not just `if`/`for`/`while`. A function
like `RateLimiter.is_allowed` reads as a short guard-clause chain, but its
`if config and not config.enabled` style conditions each add a point. The
remedy is therefore to *move decision points into helpers*, not merely to
flatten nesting.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-CX2-001
    title: "MCP tool surface functions at or below complexity 15"
  - id: REQ-CX2-002
    title: "Core runtime functions at or below complexity 15"
  - id: REQ-CX2-003
    title: "CLI command functions at or below complexity 15"
  - id: REQ-CX2-004
    title: "Engine, jot, TUI, websocket and bifrost functions at or below complexity 15"
```

## 5. Implementation Phases

Every phase is executed by a Mahavishnu pool worker in its own git worktree
(parallel same-repo dispatch requires worktree isolation — see
`feedback-workflow-parallel-same-repo-no-isolation`). The worker edits only
the files named in its phase and commits them. The orchestrator reviews each
diff, applies it, and verifies the whole package.

### Phase 1: MCP tool surface (REQ-CX2-001)

**Goal:** functions 1, 4, 5, 6, 7, 12, 16 to complexity ≤ 15.

**Files:** `mcp/tools/tasks_handoff.py`, `mcp/tools/goal_team_tools.py`,
`mcp/tools/otel_tools.py`, `mcp/tools/treesitter_tools.py`,
`mcp/tools/audit_health_tool.py`, `mcp/crow/tools/rg_search.py`.

**Tasks:** extract the validation, response-building and dispatch steps of
each tool into module-private helpers. `tasks_handoff_to_workflow` carries 7
exception handlers — each becomes its own response builder. `rg_search`
carries a format dispatch — each format becomes its own handler.
`mahavishnu_parse_goal` carries the mode/goal validation matrix.

**Exit criteria:** pyscn measures each of the seven functions at ≤ 15.

#### Integration Contract

- **Triggered from**: the MCP tools `mahavishnu_tasks_handoff_to_workflow`,
  `mahavishnu_parse_goal`, `mahavishnu_ingest_otel_traces`,
  `mahavishnu_treesitter_find_usages`, `mahavishnu_audit_health`, and
  `query_local_traces`, registered by `register_tasks_handoff_tools`,
  `register_goal_team_tools`, `register_otel_tools`,
  `register_treesitter_tools` and `register_audit_health_tools`.
- **Returns to / updates**: the same `dict[str, Any]` envelopes as today.
  No new state store, no new log key, no new metric.
- **Demonstrable by**: `pyscn analyze --select complexity --json --min-complexity 5`
  reports no function above 15 in these six files; the MCP tool schemas in
  `tests/fixtures/mcp_surface/tools_list.json` are unchanged.
- **Rollback signal**: any of the phase's targeted pytest modules failing,
  or a change in the `tools_list.json` schema fixture — revert the phase.
- **Observability added**: none. Every existing structured log line and
  error envelope is preserved verbatim.

### Phase 2: Core runtime (REQ-CX2-002)

**Goal:** functions 2, 8, 10, 17, 18, 20, 21, 22, 27 to complexity ≤ 15.

**Files:** `core/rate_limit.py`, `core/task_router.py`, `core/worktree_scan.py`,
`core/skill_synthesizer.py`, `core/worktree_prune_merged.py`,
`core/secure_logging.py`, `core/cost_optimizer.py`, `core/ecosystem.py`,
`core/observability.py`.

**Tasks:** split each function along its concern seams. `is_allowed` mixes a
token bucket, a per-minute window and a violation cooldown — each becomes a
helper. `validate_mcp_servers` is a loop over four independent checks — each
check becomes a helper. `_format_json` groups by tier and then formats each
tier — the grouping and the formatting separate.

**Exit criteria:** pyscn measures each of the nine functions at ≤ 15.

#### Integration Contract

- **Triggered from**: `RateLimiter.is_allowed`, `CapabilityRouter.route`,
  `worktree_scan._format_json`, `SkillSynthesizer._derive_trigger_conditions`,
  `worktree_prune_merged.find_merged_worktrees`,
  `CredentialRedactor.redact_dict`, `CostOptimizer.check_budget_constraints`,
  `EcosystemLoader.validate_mcp_servers`,
  `ObservabilityManager._on_drift_warning`.
- **Returns to / updates**: the same return values and the same in-place
  mutations of `self._tokens` / `self._last_update` / `self._requests`.
- **Demonstrable by**: pyscn reports no function above 15 in these nine
  files; the rate-limiter, worktree-scan, secure-logging and ecosystem
  targeted pytest modules pass unchanged.
- **Rollback signal**: a rate-limiter or worktree-prune test failing — the
  token-bucket refill and the prune candidate selection are the two places
  where an off-by-one in a moved branch changes behaviour silently.
- **Observability added**: none.

### Phase 3: CLI commands (REQ-CX2-003)

**Goal:** functions 3, 23, 24, 25, 26 to complexity ≤ 15.

**Files:** `_main_cli.py`, `cli/config_validator.py`, `cli/team_cli.py`,
`metrics_cli.py`, `worktree_cli.py`.

**Tasks:** `health_command._health` (CC 20) aggregates several component
checks — each check becomes a helper returning one report fragment, and
`_health` becomes the assembler. The four CC-16 functions each split along
their render/validate seam.

**Exit criteria:** pyscn measures each of the five functions at ≤ 15.

#### Integration Contract

- **Triggered from**: the `mahavishnu health` command, `mahavishnu config validate`, `mahavishnu team learning-stats`, the metrics verification
  renderer, and `mahavishnu worktree prune-stale-metadata`.
- **Returns to / updates**: the same stdout/stderr text, the same JSON
  payload shapes, and the same process exit codes. Typer's command
  signatures are untouched.
- **Demonstrable by**: pyscn reports no function above 15 in these five
  files; `mahavishnu health --help` and the CLI example doc tests still
  match (`tests/unit/test_acp_docs.py::TestCLIExamplesMatchHelp`).
- **Rollback signal**: a CLI example doc test failing, or a changed exit
  code on `health` — revert the phase.
- **Observability added**: none.

### Phase 4: Engines, jot, TUI, websocket, bifrost (REQ-CX2-004)

**Goal:** functions 9, 11, 13, 14, 15, 19 to complexity ≤ 15.

**Files:** `bifrost/toggles.py`, `engines/agno_adapter_impl.py`,
`jot/fold.py`, `jot/drain.py`, `websocket/integration.py`,
`tui/command_palette.py`.

**Tasks:** `_action_bifrost` (CC 18) dispatches a CLI action across a set of
sub-actions — each sub-action becomes a helper. `_resolve_legacy_llm_config`
reconciles a legacy config shape — the reconciliation steps separate.
`build_states` (CC 17, SLOC 119) is the largest body in the set and splits
along its state-construction stages.

**Exit criteria:** pyscn measures each of the six functions at ≤ 15.

#### Integration Contract

- **Triggered from**: the bifrost toggle CLI action, the Agno adapter's
  legacy LLM config resolution, `jot/fold.py:build_states`,
  `jot/drain.py:surface_relevant`, `websocket/integration.py:start_websocket_server`,
  and `tui/command_palette.py:CommandPalette.search`.
- **Returns to / updates**: the same resolved config objects, the same
  folded jot states, the same websocket server handle, and the same
  palette result list.
- **Demonstrable by**: pyscn reports no function above 15 in these six
  files; the agno adapter and jot targeted pytest modules pass unchanged.
- **Rollback signal**: an agno adapter test failing on the resolved provider
  chain, or a jot fold test failing on the state list — revert the phase.
- **Observability added**: none.

## 6. Required Code Changes

- [ ] `mahavishnu/mcp/tools/tasks_handoff.py` — extract the 7 exception handlers
- [ ] `mahavishnu/mcp/tools/goal_team_tools.py` — extract the validation matrix
- [ ] `mahavishnu/mcp/tools/otel_tools.py` — 2 functions
- [ ] `mahavishnu/mcp/tools/treesitter_tools.py` — extract the usage resolution
- [ ] `mahavishnu/mcp/tools/audit_health_tool.py` — extract the feed checks
- [ ] `mahavishnu/mcp/crow/tools/rg_search.py` — extract the format handlers
- [ ] `mahavishnu/core/rate_limit.py` — split bucket / window / cooldown
- [ ] `mahavishnu/core/task_router.py` — extract the route resolution
- [ ] `mahavishnu/core/worktree_scan.py` — split grouping from formatting
- [ ] `mahavishnu/core/skill_synthesizer.py` — extract the trigger derivation
- [ ] `mahavishnu/core/worktree_prune_merged.py` — extract the candidate scan
- [ ] `mahavishnu/core/secure_logging.py` — extract the redaction passes
- [ ] `mahavishnu/core/cost_optimizer.py` — extract the budget checks
- [ ] `mahavishnu/core/ecosystem.py` — extract the four server checks
- [ ] `mahavishnu/core/observability.py` — extract the drift-warning build
- [ ] `mahavishnu/_main_cli.py` — extract the health check fragments
- [ ] `mahavishnu/cli/config_validator.py` — extract the validation passes
- [ ] `mahavishnu/cli/team_cli.py` — extract the stats assembly
- [ ] `mahavishnu/metrics_cli.py` — extract the verification renderers
- [ ] `mahavishnu/worktree_cli.py` — extract the stale-metadata scan
- [ ] `mahavishnu/bifrost/toggles.py` — extract the sub-actions
- [ ] `mahavishnu/engines/agno_adapter_impl.py` — extract the config reconciliation
- [ ] `mahavishnu/jot/fold.py` — extract the state-construction stages
- [ ] `mahavishnu/jot/drain.py` — extract the relevance scoring
- [ ] `mahavishnu/websocket/integration.py` — extract the server setup
- [ ] `mahavishnu/tui/command_palette.py` — extract the match scoring
- [ ] `docs/plans/2026-11-15-pyscn-complexity-ceiling-15.md` — this plan

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pyscn analyze --select complexity --json --min-complexity 5 mahavishnu` | 0 functions with `metrics.complexity > 15` | `.pyscn/reports/*.json` |
| `ruff check` on the 26 changed files | clean | ruff output |
| `ty check` on the 26 changed files | 0 diagnostics | ty output |
| `pytest --no-cov` on the targeted modules | all pass | pytest summary |
| `crackerjack run -v` | `pyscn` hook reports `passed` | gate summary |
| `python scripts/audit_requirements.py` | 0 orphans for `REQ-CX2-*` | audit output |
| `python scripts/audit_orphans.py` | no newly-added symbol without a caller | audit output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Behaviour drift in an extracted branch | medium | Every helper is a verbatim extraction; the targeted pytest baseline gates each phase |
| A moved branch changes an off-by-one in a silent path | medium | The riskiest seams — token-bucket refill, prune candidate selection, route scoring — get a named targeted test run before the gate |
| MCP tool schema changes because a signature moved | low | The decorated signature is untouched in every phase; `tools_list.json` is diffed |
| A worker edits the shared checkout instead of its worktree | medium | Worktree isolation is verified on a pilot dispatch before the remaining batches are dispatched; the main checkout's `git status` is checked after each batch |
| A worker dispatch exceeds the MCP idle timeout | medium | Batches are sized to complete inside the ~600 s MCP window; the prompt forbids running the test suite, which is the gate's job |
| Complexity measured at 16 after the edit | low | Target is ≤ 12, giving three points of margin against re-measurement drift |

## 9. Decision Rule

The work is done when `crackerjack run -v` reports the `pyscn` hook as
`passed`, pyscn measures zero functions above 15 across the `mahavishnu`
package, and the targeted pytest modules for every changed file still pass.
If a phase cannot be completed without behaviour drift, ship the other
phases and record the drift explicitly rather than suppressing the gate.

## 10. Results (measured 2026-11-15)

All 27 functions are at or below the ceiling of 15. The worst function in
the set moved from **22** to **10**; the whole `mahavishnu` package now
measures **zero** functions above 15.

| Function | Before | After |
|---|---|---|
| `tasks_handoff_to_workflow` | 22 | **2** |
| `RateLimiter.is_allowed` | 21 | **9** |
| `health_command._health` | 20 | **4** |
| `mahavishnu_parse_goal` | 19 | **6** |
| `mahavishnu_ingest_otel_traces` | 18 | **1** |
| `mahavishnu_treesitter_find_usages` | 18 | **4** |
| `audit_health_async` | 18 | **3** |
| `CapabilityRouter.route` | 18 | **6** |
| `_action_bifrost` | 18 | **3** |
| `_format_json` | 18 | **7** |
| `build_states` | 17 | **4** |
| `query_local_traces` | 17 | **7** |
| `surface_relevant` | 17 | **10** |
| `_resolve_legacy_llm_config` | 17 | **6** |
| `start_websocket_server` | 16 | **7** |
| `rg_search` | 16 | **6** |
| `_derive_trigger_conditions` | 16 | **6** |
| `find_merged_worktrees` | 16 | **3** |
| `CommandPalette.search` | 16 | **7** |
| `CredentialRedactor.redact_dict` | 16 | **4** |
| `check_budget_constraints` | 16 | **4** |
| `EcosystemLoader.validate_mcp_servers` | 16 | **2** |
| `run_validation` | 16 | **10** |
| `learning_stats` | 16 | **6** |
| `prune_stale_metadata._run` | 16 | **3** |
| `_render_verification_output` | 16 | **7** |
| `_on_drift_warning` | 16 | **3** |

### Evidence

| Check | Result |
|---|---|
| `pyscn analyze --select complexity --json --min-complexity 5 mahavishnu` | **0 functions** with `metrics.complexity > 15` |
| `ruff check` on all 31 changed source files | clean |
| `ty check` on all 31 changed source files | clean |
| Targeted pytest across every changed module | **772 passed**, 0 failed |
| Batch B module pytest (run separately — that batch used an equivalence harness instead) | **270 passed**, 0 failed |
| `crackerjack run -v` | fast hooks **18/18 passed**, comprehensive hooks **12/12 passed**, 0 issues, exit 0 — `pyscn :: PASSED \| 3.92s \| issues=0` |
| `scripts/audit_requirements.py` | `REQ-CX2-001..004` traced; orphans 1 (pre-existing, `REQ-MCPTD-007`) |

The gate command is `crackerjack run -v`, **not** `crackerjack run -v -f`:
`-f` is fast-only and would skip the comprehensive hooks entirely — which
are the whole point of this plan. A green `-v -f` proves nothing here.

### Notes on the two risky seams

- `RateLimiter.is_allowed` mixes a token bucket, a per-minute window and a
  violation cooldown. The refactor keeps the **token consumption before the
  minute-limit check**, because a request rejected by the minute limit still
  consumes a token in the original — moving that order would change the
  rate-limit envelope. Verified by a differential harness that ran the
  pre-refactor and post-refactor modules side by side under a deterministic
  fake clock across 12 scenarios (burst exhaustion, per-minute/hour/day
  limits, cooldown and its expiry, disabled config, exempt IP, token
  refill, multi-key interleaving, minute-window rollover), comparing
  return values **and** the full internal state (`_requests`, `_tokens`,
  `_last_update`, `_violations`). All 12 matched.
- The CLI batch was checked by byte-diffing 38 CLI invocations
  (`mahavishnu health`, `team learning`, `worktree prune-stale-metadata`,
  `metrics verification`) and 1094 lines of `--help` output against a
  pristine `HEAD` tree: identical.

### Two pre-existing failures surfaced, neither caused by this plan

- `tests/unit/test_mcp/test_pool_tools.py::TestRegistration` expects
  `mahavishnu_budget_enforce` to be registered by `register_pool_tools`.
  Commit `866d681b` moved that surface into `mahavishnu/mcp/tools/budget_tools.py`
  and left the assertion behind.
- `tests/unit/test_main_cli.py::TestPoolSpawn::test_pool_spawn_error` and
  `tests/unit/test_metrics_cli_extended.py::test_fetch_mcp_entries_and_commands`
  fail on `main` as well (an `httpx2` mock-patching issue).

Both are reproduced on a pristine `HEAD` tree and are out of scope here.

### One self-inflicted regression, caught and fixed

The first cut of the worktree-cwd fix added two branches to
`mahavishnu_pool_route_execute`, pushing it from 14 to **16** — over the
ceiling it had just been refactored under on 2026-11-07. The cwd
resolution was extracted into `_worktree_cwd` and the function returned to
zero functions over the ceiling in `pool_tools.py`.

## References

- `crackerjack/models/tool_config.py:25` — `PYSCN_MAX_COMPLEXITY = 15`.
- `crackerjack/parsers/json_parsers.py:573` — the parser that enforces it.
- `crackerjack/docs/adr/ADR-025-complexity-scanning-defaults.md` — the
  2026-11-14 amendment restoring the ceiling to 15.
- `docs/plans/2026-11-07-pyscn-complexity-refactor.md` — the predecessor
  plan that brought four functions under the then-current ceiling of 25.
- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
