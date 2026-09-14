---
status: active
role: implementation
kind: plan
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on: []
topic: audit-orphans-residual-caller-detection
---

# Followup — `audit_orphans.py` residual caller-detection coverage

**Date:** 2026-09-14
**Originating plan:** `docs/plans/2026-09-12-finish-partial-implementations.md` (Phase 5 OTel counter liveness check, Decision Rule condition 2)
**Status:** OPEN — surfaces during Phase 5 audit gate. The `__all__`-aware reference-collection fix already shipped this session (loop 1 of audit cycle). Remaining items listed below.

## What the residual gap is

`scripts/audit_orphans.py --root . --include-tests --exclude scripts`
still exits 1 after the `__all__`-aware reference collector shipped
this session. Per-dir breakdown of orphan-row files after the fix:

| Directory | Files with orphan rows | Nature |
|---|---|---|
| `mahavishnu/` | 11 | Production-code methods/classes. Some are truly orphan (no callers); some are intra-class dispatch (`self.method()`) or instance-method call (`app.method()`) that the audit's intra-file search whiffs on because the regex shape looks for top-level call sites, not arbitrary expression receivers. |
| `tests/` | 293 | Test functions whose only caller is pytest. The audit's notion of "caller" doesn't recognize pytest test discovery. |
| `examples/` | 3 | Demo modules with helper methods; same instance-method pattern as `mahavishnu/`. |

True-orphan candidates spotted in the Phase 5 audit (these are the
ones with no callers at all, intra-module or inter-module):

| File | Symbol | Date | Status |
|---|---|---|---|
| `mahavishnu/auth.py` | `has_scope` | 2026-08-25 | method |
| `mahavishnu/core/app.py` | `start_budget_watchdog` | 2026-09-10 | method |
| `mahavishnu/core/app.py` | `stop_budget_watchdog` | 2026-09-10 | method |
| `mahavishnu/core/budget_watchdog.py` | `record_key` | 2026-08-30 | method |
| `mahavishnu/core/cross_repo_aggregator.py` | `get_repos_needing_attention` | 2026-08-19 | method |
| `mahavishnu/core/ecosystem_status.py` | `AdapterProvider` | 2026-08-31 | class |
| `mahavishnu/core/evidence_store.py` | `store_evidence` | 2026-08-31 | method |
| `mahavishnu/core/worktree_coordination.py` | `start_health_check_loop` | 2026-09-04 | method |
| `mahavishnu/core/worktree_coordination.py` | `fetch_worktree_handle` | 2026-09-04 | method |
| `mahavishnu/jot/drain.py` | `DispatchCtx` + 5 more event-payload dataclasses | 2026-09-10 | class |
| `mahavishnu/mcp/tools/capability_tools.py` | (one symbol, see audit dump) | recent | method |
| `mahavishnu/pools/manager.py` | (one symbol, see audit dump) | recent | method |
| `mahavishnu/websocket/server.py` | (one symbol, see audit dump) | recent | method |

## Proposed fixes (acceptance criteria)

1. **Audit script improvements** — make `audit_orphans.py` recognize:
   - **Pytest test functions** — every `test_*` function in `tests/` should be treated as having pytest as an implicit caller. Easiest mechanism: a `--treat-tests-as-wired` flag (default `True` for `tests/` paths), or a `pytest.discover` AST walk that detects classes/functions whose name matches pytest's collection rules.
   - **Typed-discriminator forward-references** — Pydantic `Literal["a", "b"]` and `Field(discriminator=...)` arguments reference classes by string name; the audit should skip those classes from the orphan count. (The script already has `--include-stub-check` for Pydantic discriminated unions; widen it to cover more cases.)
   - **Methods called only via attribute dispatch** — for symbols where the audit can't find any caller, attempt to recognize `method(...)` patterns inside class bodies and trace them up to the class hierarchy. This is the most invasive change and may not be worth it; a `--treat-intra-class-dispatch-as-wired` opt-in flag is the safer scope.
   - **MCP tool/CLI decorator variants** the existing regex misses — `app.command`, `cli.command`, `mcp.tool`, etc. (the audit already has `DECORATOR_REGISTRATION_PATTERN`; audit whether it actually catches all variants in production usage).
2. **Production-code orphan wiring OR removal** — for each of the 11 `mahavishnu/` orphans listed above, decide:
   - Wire it (add a real caller — likely in `app.py` or a CLI subcommand).
   - Remove it (delete the symbol + its tests).
   - Mark deferred (file `docs/followups/<date>-<symbol>-deferred.md` with a concrete re-evaluation trigger).
3. **Test-folder-only audit mode** — the `tests/` orphans aren't real orphans (pytest calls them). Add a `--exclude-tests-default` mode that the meta-plan's audit invocation can opt into, so a "production orphan sweep" doesn't drown in test scaffolding.

## Estimated size

- Audit script improvements: 50-200 lines depending on scope. The
  pytest-as-caller flag is the single highest-leverage change.
- Production wiring: 1-3 lines per orphan (or deletion). 11 orphans
  × ~5 lines = ~55 lines + tests.
- The audit script fix is reviewable as a single PR; the production
  wiring may cluster by file.

## Why this is a followup, not part of Phase 5

Phase 5 is the post-close audit. Its deliverable is decision-rule
verification + audit-summary commit + filing of followups for any
non-closing gaps. Filing this followup IS the deliverable. The
meta-plan can flip to `complete` once (a) the audit improvement lands
+ (b) the production orphans are wired/removed + (c) the audit
re-runs exit 0.

## Why not just delete the missing callers

Several of these (especially the `jot/drain.py` dataclasses and
the `start_budget_watchdog` / `stop_budget_watchdog` methods) are
intentional API surfaces awaiting one of:
- The next CLI command that calls them
- The MCP tool registration that wires them
- The CLI command that wires them (e.g. `mahavishnu monitor
  budget` if it doesn't exist yet)

Deletion without confirming the API surface intent risks
re-introducing the methods in the next sprint. Wire-first or
deferred-with-trigger is safer than delete.

______________________________________________________________________
