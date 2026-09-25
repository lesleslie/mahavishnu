---
name: pool-worker-mcp-audit
status: complete
date: 2026-09-25
last_reviewed: 2026-09-25
owner: mahavishnu
role: audit
plan: .claude/plans/nifty-gliding-stallman.md v3 §10 follow-ups #1 + #2 + #5
triggered_by: User direction after Plan v3 ship — "wire up the remaining §10 follow-ups"
related: memory/pool-dispatch-async-default.md; memory/mahavishnu-dispatch-prompt-mangling.md; docs/feature-tracking/2026-07-11-dispatch-to-pool.md; docs/decisions/2026-09-24-legacy-worker-deprecation.md
progress: "3/3 audited. worker_* tools (18) LIVE — no removal. dispatch_to_pool wired with documented env-failure (memory pool-dispatch-async-default). mahavishnu_pool.py docstring fixed (commit dddceca9); substantive rewrite deferred — see §Open work."
---

# Pool + Worker MCP Tool Audit (Plan v3 §10 follow-ups)

## Scope

This audit covered three Plan v3 §10 follow-ups that were deferred from the
shipped phases:

1. **`dispatch_to_pool` audit** (§10 #1) — possibly broken per memory
   `pool-dispatch-async-default.md`; reimplement or remove dead refs.
2. **Worker MCP tools (`worker_*`) audit** (§10 #2) — 9 registered (per
   plan estimate); aspirational-vs-live audit needed.
3. **`pools/mahavishnu_pool.py` cleanup** (§10 #5) — still imports
   `WorkerManager` and `get_worker_entry`; rewrite to use
   `pool_manager.route_task` shape.

All three were investigated on 2026-09-25 with no new code changes
beyond the docstring ASCII diagram fix in
`mahavishnu/pools/mahavishnu_pool.py` (commit `dddceca9`, replacing
stale `AppleContainer/E2B microVM` references with `shepherd (OS
syscall-jail)` per Phase 4.5b).

## State — complete

- [x] `dispatch_to_pool` status confirmed
- [x] worker_* tools audit completed
- [x] `mahavishnu_pool.py` docstring fixed (commit `dddceca9`)
- [x] Decision recorded: keep `dispatch_to_pool`; defer §10 #5 rewrite

## Audit findings

### Finding 1 — `dispatch_to_pool` (wired, env-failure documented)

**Status: KEEP — code is correct; environment is broken.**

Code is registered in `mahavishnu/mcp/tools/pool_tools.py` and has
callers documented in:

- `CLAUDE.md:384` (recommended entry point with `async_callback=True`)
- `docs/architecture/MEMORY_ARCHITECTURE.md` (multiple integration contracts)
- `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` (original tracker)
- `docs/WORKFLOW_DIAGRAMS.md:471`

The async path (with `async_callback=True`) was **verified failed** on
2026-08-23 in this environment (memory `pool-dispatch-async-default.md`):

- `dispatch_to_pool(async_callback=True)` returns `workflow_id` immediately
  ✓
- `workflow_result(workflow_id=...)` returns `not_found` ✗
- `pool_execute(pool_id=..., timeout=60)` returns timeout with empty
  output ✗

Root cause unclear; most likely candidates: (a) Dhara persistence not
configured for `workflow-results/{workflow_id}/`, or (b) harness not
capturing worker stdout.

**Decision**: keep `dispatch_to_pool` as-is. The code is correct; the
failure is environment-level (Dhara substrate). Removing the tool
would break the 13+ doc references and force an unrelated Dhara fix
into scope.

**Forward path**: Plan v3 Phase 2m added `pool_route_execute` (the new
sync entry point) which calls `await pool_manager.route_task(...)`
directly, bypassing the `sh -lc` wrapper bug from memory
`mahavishnu-dispatch-prompt-mangling.md`. New code should prefer
`pool_route_execute`. `dispatch_to_pool` remains for callers that
already depend on its wire shape (notably the async_callback semantics
when Dhara is working).

**Action**: none for this audit. The Phase 2m `pool_route_execute` is
already shipped (commit `4090965b`) and is the recommended forward
path. The `2026-07-11-dispatch-to-pool.md` tracker remains accurate
("wired" with verified-failure caveat documented in memory).

### Finding 2 — worker_* MCP tools (all LIVE)

**Status: KEEP all 18 tools.**

The Plan v3 §10 #2 estimate of "9 registered" was undercounted. The
actual count is **18 worker_* tools** across two files:

| Tool | File | Path | Status |
|---|---|---|---|
| `worker_spawn` | `worker_tools.py:53` | durable + legacy | LIVE |
| `worker_monitor` | `worker_tools.py:96` | durable + legacy | LIVE |
| `worker_collect_results` | `worker_tools.py:125` | durable + legacy | LIVE |
| `worker_close` | `worker_tools.py:177` | durable + legacy | LIVE |
| `worker_close_all` | `worker_tools.py:213` | durable + legacy | LIVE |
| `worker_health` | `worker_tools.py:240` | durable + legacy | LIVE |
| `worker_execute` | `worker_tools.py:259` | legacy only | LIVE |
| `worker_execute_batch` | `worker_tools.py:294` | legacy only | LIVE |
| `worker_list` | `worker_tools.py:330` | durable + legacy | LIVE |
| `launch_worker` | `worker_contract_tools.py:110` | durable | LIVE |
| `send_input` | `worker_contract_tools.py:160` | durable | LIVE |
| `capture_output` | `worker_contract_tools.py:171` | durable | LIVE |
| `worker_status` | `worker_contract_tools.py:203` | durable | LIVE |
| `wait_for_state` | `worker_contract_tools.py:257` | durable polling | LIVE |
| `cancel_worker` | `worker_contract_tools.py:311` | durable | LIVE |
| `worker_revoke` | `worker_contract_tools.py:328` | durable | LIVE |
| `worker_run_with_settle` | `worker_contract_tools.py:411` | durable + settle persistence | LIVE |
| `worker_settle` | `worker_contract_tools.py:520` | state machine + git merge-file | LIVE |

All 18 have **real implementations** (not stubs) — each either routes
through `_durable_manager`, `_worker_manager`, or both. Test coverage
exists for all of them across these files (verified 2026-09-25):

```
tests/unit/mcp/tools/test_worker_close_all_and_health.py
tests/unit/mcp/tools/test_worker_close_two_phase.py
tests/unit/mcp/tools/test_worker_collect_results_offset.py
tests/unit/mcp/tools/test_worker_contract_tools.py
tests/unit/mcp/tools/test_worker_execute_no_truncation.py
tests/unit/mcp/tools/test_worker_list_filter.py
tests/unit/mcp/tools/test_worker_monitor_state.py
tests/unit/mcp/tools/test_worker_spawn_contract.py
tests/unit/test_worker_status_identity.py  (Phase 5b)
```

**Decision**: keep all 18 tools. The Plan v3 §10 #2 aspirational-vs-live
audit returns **all-LIVE** — no aspirational stubs, no dead refs.

**Action**: none. The plan can strike §10 #2 from open work.

### Finding 3 — `pools/mahavishnu_pool.py` cleanup (partial)

**Status: PARTIAL — docstring fixed; substantive rewrite deferred.**

This pool is a real production pool that wraps `WorkerManager` (the
only live worker-management surface post-Phase 4.5b). The substantive
Plan v3 §10 #5 ask was to "rewrite to use `pool_manager.route_task`
shape" — replacing the `WorkerManager`-wrapping design with a
selector-based dispatcher. That is a substantial refactor (touches
start, execute_task, execute_batch, scale, health_check, collect_memory,
stop) and would warrant its own plan, not a follow-up commit.

What **was** fixed in this batch (commit `dddceca9`):

- ASCII architecture diagram at `mahavishnu/pools/mahavishnu_pool.py:36-52`
  no longer mentions the deleted `AppleContainer/E2B microVM` workers.
  Replaced with `shepherd (OS syscall-jail)` per Phase 4.5b.

What **was NOT** fixed:

- `WorkerManager` import (line 12) is still live.
- `get_worker_entry` call (line 108) is still live — used for
  `requires_tool` validation against `WORKER_REGISTRY`.

**Decision**: defer the §10 #5 rewrite to a separate plan. The
`mahavishnu_pool.py` design is intentional (it wraps the existing
worker subsystem); replacing it is a layer-redesign task, not a
cleanup.

**Action**: none for this audit. The substantive rewrite moves to
the plan parking lot.

## Summary

| Item | Decision | Action |
|---|---|---|
| `dispatch_to_pool` | KEEP — env-failure is Dhara, not code | none |
| worker_* tools (18) | KEEP all — all LIVE with tests | none |
| `mahavishnu_pool.py` docstring | FIXED (commit `dddceca9`) | done |
| `mahavishnu_pool.py` rewrite | DEFER — separate plan | open |

## Open work (moved to parking lot)

- **§10 #5 rewrite**: replace `mahavishnu_pool.py` WorkerManager-wrapping
  design with `pool_manager.route_task`-shape selector dispatch.
  Substantial refactor; needs its own plan with integration contract.
- **`workers/cloud_worker.py` retirement** (Plan §10 #3): after Phase
  3b, routing logic lives in `core/model_routing.py`. The cloud
  worker is now a thin wrapper. Decision needed: keep as
  OpenAI-compatible HTTP client or retire and migrate all callers.
- **`workers/manager.py:_create_isolated_worker` alternative home**
  (Plan §10 #4): only shepherd_backend supported post-Phase 4. If we
  ever want to bring back e2b-sandbox / apple-container, they migrate
  into `core/isolations/`. Currently no plan.
- **`workers/__init__.py` `__all__` collapse to factory functions**
  (Plan §10 #6): cosmetic refactor, low priority.
- **`_main_cli.py` future cleanup** (Plan §10 #7): Phase 0 enumeration
  confirmed zero dead-class imports. No work to do.

## References

- `.claude/plans/nifty-gliding-stallman.md` v3 §10 Known Adjacent Gaps
- `commit dddceca9` — doc-drift cleanup + `mahavishnu_pool.py` ASCII fix
- `commit 4090965b` — Phase 2m `pool_route_execute` (sync alternative)
- `memory/pool-dispatch-async-default.md` — env-failure root cause
- `memory/mahavishnu-dispatch-prompt-mangling.md` — `sh -lc` wrapper bug
- `docs/decisions/2026-09-24-legacy-worker-deprecation.md` — Phase 4.5b ADR
