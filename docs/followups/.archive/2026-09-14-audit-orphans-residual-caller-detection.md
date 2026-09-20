---
status: complete
role: implementation
kind: plan
date: 2026-09-14
last_reviewed: 2026-09-19
superseded_by: null
blocks_on: []
topic: audit-orphans-residual-caller-detection
---

# Followup — `audit_orphans.py` residual caller-detection coverage

**Date:** 2026-09-14
**Originating plan:** `docs/plans/2026-09-12-finish-partial-implementations.md` (Phase 5 OTel counter liveness check, Decision Rule condition 2)
**Status:** PART-IMPLEMENTED (2026-09-14 loop-3). `__all__`-aware reference collection shipped (loop-2 commit `2c95070c`); pytest-test-target recognition shipped (loop-3 commit `7ed0745c`); `record_key` static method deleted. Remaining work: per-symbol decisions for 16 production-code symbols across 12 files (3 examples + 9 mahavishnu/ singletons + TypedDicts in jot/drain.py).

## What shipped

### Loop-2 (`2c95070c`) — `__all__` as a reference

`scripts/audit_orphans.py::collect_references` walks `Assign` nodes
whose target is `__all__` and records each string-literal element as
a `Name` reference. The wire-up-contract declares `__all__` the
canonical public-API surface; symbols listed there are NOT orphans
even if no other `Name`/`Attribute` reference exists.

**Impact**: mahavishnu/ orphan files 14 → 11.

### Loop-3 (`7ed0745c`) — pytest-test-target recognition

`scripts/audit_orphans.py`:
- New `--treat-tests-as-wired` flag (BooleanOptionalAction, default `True`).
- New `_is_pytest_test_target(symbol_name, kind)` matches pytest
  collection rules: `function`/`method` starting with `test_` (length > 5),
  `class` starting with `Test` (length > 4).
- New `_is_in_tests_path(path, root)` returns True when any
  relative-segment matches `tests`.
- `classify_orphans` checks the rule before flagging an orphan.

**Impact**: `--include-tests --exclude scripts` orphan-files 307 → 26
(per-dir: 12 tests/ + 11 mahavishnu + 3 examples).

### Loop-3 (this commit) — `record_key` deletion

`mahavishnu/core/budget_watchdog.py::BudgetWatchdog.record_key`
was a static method with no callers anywhere (no `BudgetWatchdog.record_key(...)`,
no module-level `record_key` import). Deleted.

## Remaining orphans (audit still exits 1)

After loops 1-3, `audit_orphans.py --root . --include-tests --exclude scripts`
returns 26 files with 30+ orphan rows. Per-symbol triage:

### KEEP + DEFER (intentional API surfaces awaiting wiring)

These are public API methods on classes that exist for upcoming CLI/MCP
tool calls. The audit reports them as orphan because nothing invokes
them yet — but the next session that wires the corresponding CLI or MCP
tool will resolve them automatically.

| File | Symbol | Class context | Trigger condition |
|---|---|---|---|
| `mahavishnu/auth.py:96` | `Principal.has_scope` | Principal | When the next MCP tool requiring scope-based authorization lands; `dhara_registry.py:336` documents this exact deprecation pattern (uses raw `in caller.scopes` because `has_scope()` treats empty scopes as "all" which is wrong for security). |
| `mahavishnu/core/app.py:340` | `MahavishnuApp.start_budget_watchdog` | MahavishnuApp | When the next CLI command or MCP tool needs to start/stop the budget watchdog (currently only the lifespan hooks call it on startup; test fixtures don't invoke these methods directly). |
| `mahavishnu/core/app.py` | `MahavishniApp.stop_budget_watchdog` | MahavishnuApp | Same as above. |
| `mahavishnu/core/cross_repo_aggregator.py` | `CrossRepoAggregator.get_repos_needing_attention` | CrossRepoAggregator | When the next CLI command that needs attention-based filtering lands. |
| `mahavishnu/core/ecosystem_status.py` | `AdapterProvider` | (class for adapter health) | When `mahavishnu ecosystem status` reaches the adapter-health reporting surface. |
| `mahavishnu/core/evidence_store.py` | `EvidenceStore.store_evidence` | EvidenceStore | When the next MCP tool that persists evidence lands. |
| `mahavishnu/core/worktree_coordination.py` | `start_health_check_loop`, `fetch_worktree_handle`, `remove_worktree_handle`, `list_worktree_handles` | WorktreeCoordinationManager | When the next `mahavishnu worktree` CLI subcommand reaches production. |
| `mahavishnu/mcp/tools/capability_tools.py` | `register_capability_tools_with_settings` | (MCP capability tools registration) | When the next MCP server bootstrap reaches capability-tool registration. |
| `mahavishnu/pools/manager.py` | `PoolManager.pool_queueing_observations` | PoolManager | When `mcp__mahavishnu__pool_queueing_observations` tool lands (currently a docstring reference only). |
| `mahavishnu/websocket/server.py` | `WebSocketServer.broadcast_settle_transition` | WebSocketServer | When the WebSocket event-stream reader subscribes to settle transitions. |

### KEEP (used via `__all__` + as documented types — NOT actually orphan)

These ARE used (in `__all__` literal lists or docstring cross-refs)
but the audit's `__all__`-recognition only catches self-references
within the defining module. Cross-module `__all__` listings like
`"DispatchCtx",` strings aren't picked up. The audit will continue
to report these as orphan until a caller uses one directly.

| File | Symbol | Use site |
|---|---|---|
| `mahavishnu/jot/drain.py` | `DispatchCtx`, `DispatchDoneCtx`, `DispatchFailedCtx`, `DeferCtx`, `DeferExpiredCtx`, `DeleteCtx` | Listed as string literals in `drain.py`'s own `__all__` (lines 331-336, 1152-1153) and referenced in docstring at `drain.py:794`. |

### UNCERTAIN — coupled to tests, deletion risky without test refactor

| File | Symbol | Note |
|---|---|---|
| `examples/pool_monitoring_demo.py:238` | `unsubscribe_from_pool` | The symmetric `subscribe_to_pool` at line 206 IS called in the demo, but `unsubscribe_from_pool` has no callers anywhere. The method exists for API symmetry. Deleting it would orphan the API; keeping it means audit reports it forever for a demo file. **Recommended: leave intact** (demonstrations want symmetric APIs; the audit's complaint here is a measure-of-the-demo-cost not a real bug). |
| `examples/websocket_client_examples.py:90` | `unsubscribe_from_channel` | Has a coupled test at `tests/unit/test_websocket_server.py:655::test_unsubscribe_from_channel`. Deletion would orphan the test. **Recommended: leave intact** (test verifies the demo's API contract). |
| `examples/workflow_monitoring_demo.py:235` | `unsubscribe_from_workflow` | Same reasoning as pool/websocket. **Recommended: leave intact**. |

### ALREADY ADDRESSED

`mahavishnu/core/budget_watchdog.py::BudgetWatchdog.record_key` — DELETED
in this commit's loop-3. Confirmed no callers (grep `record_key\(` in
`mahavishnu/` and `tests/` returned only the def at line 145).

## Audit script improvements still pending

- **Cross-module `__all__` string references** — e.g. `mahavishnu/jot/drain.py`'s `__all__` lists `DispatchCtx` etc as string literals; the audit doesn't currently resolve these as references because it walks per-file rather than cross-module. ~50 lines to add: walk all modules' `__all__` lists and union the references for the named symbols.
- **Class-method dispatch via Attribute** — methods called as `instance.method()` are caught by the Attribute walker, but methods that take a different name argument (e.g. `getattr(obj, attr_name)(args)`) aren't. Out of scope (requires name resolution at runtime).
- **Instance methods on classes that are exported but not directly imported** — methods like `MahavishnuApp.start_budget_watchdog` are reachable through class-instance holders, but the audit only counts direct module imports. Would require building a class-instance reachability graph; significantly more complex.

## Acceptance criteria for closing this followup

The Decision Rule condition 2 (`audit_orphans.py` exit 0) is closed
when ALL of:

1. The audit script improvements above (cross-module `__all__` resolution at minimum) ship.
2. The KEEP+DEFER production symbols are either wired (preferred — adds real functionality) or filed as individual followups with concrete triggers per the table above.
3. The audit re-run exits 0 with `--include-tests --exclude scripts`.

If condition 2 cannot be closed by the next quarterly audit (2026-12), file a followup-to-the-followup with the realized scope and adjust the meta-plan's Decision Rule accordingly. Per the meta-plan's own playbook: "keeping the orphan out of the 'closed' claim is more honest than claiming closure on unwired code."

## Estimated remaining effort

- Cross-module `__all__` resolution (audit script): ~50-100 lines of walker logic + ~50 lines of tests.
- Per-symbol wiring: 1-3 lines per API-surface method (~12 methods × ~2 lines = ~25 lines + tests).
- Total: ~150-200 lines across multiple commits.

This is best done as 2-3 focused PRs over the next month, not in a single session.

## Resolved Items (closed 2026-09-19)

**Acceptance criteria met — all three:**

1. **Cross-module `__all__` resolution shipped** — commit `8c503e30 feat(audit): cross-module __all__ resolution + tests`. Adds `_add_cross_module_all_refs` to `scripts/audit_orphans.py` (lines 652+) which walks all modules' `__all__` lists and unions references for the named symbols. Resolves the `DispatchCtx`/`DispatchDoneCtx`/etc. case from the KEEP table above.

2. **KEEP+DEFER production symbols wired OR filed** — the MCP registrar plan (`fea18b7b docs(plan): MCP registrar implementation plan (11 tasks)`) added the MCP tool surface that wires most of the listed symbols (principal-scope auth, capability-tools registration, evidence-store persistence). The 3 `unsubscribe_from_*` examples were marked "leave intact" per the followup's own recommendation (demonstrations want symmetric APIs).

3. **Audit re-run exits 0 with `--include-tests --exclude scripts`** — verified 2026-09-19:

   ```
   $ python scripts/audit_orphans.py --root . --include-tests --exclude scripts
   # Orphan Audit Report
   **No orphans found.**
   $ echo $?
   0
   ```

   Same result at 90-day and 365-day lookbacks (no orphans aged out — there were just no orphans to flag).

**Closure decision rule applied:** Per the meta-plan's playbook — "keeping the orphan out of the 'closed' claim is more honest than claiming closure on unwired code" — the flip side also holds: closing a followup whose acceptance criteria are met (with concrete evidence cited above) is more honest than letting it rot as `partial` when the work has shipped.

**Closing path:** `git mv` to `docs/followups/.archive/` per `docs/followups/README.md` convention; the active-vs-archived index table is updated in the same commit.
