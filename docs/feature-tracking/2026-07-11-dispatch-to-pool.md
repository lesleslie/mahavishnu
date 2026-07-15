# Feature: dispatch-to-pool

**Owner:** mahavishnu core
**Created:** 2026-07-11
**Last updated:** 2026-07-11
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [ ] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [ ] Trigger path identified (who calls this, and from where)
- [ ] Returns / state updates land in expected destination
- [ ] End-to-end smoke check documented (one command that proves it works)
- [ ] Observability hook in place (log/metric/trace)
- [ ] Rollback signal defined

## Built (yes/no)

no

## Wired (yes/no)

no

## Trigger path

New `mcp__mahavishnu__dispatch_to_pool(prompt=..., caller_kind="ultracode", parent_session_id="ses_abc", async_callback=True)` MCP tool (registered in `mahavishnu/mcp/tools/pool_tools.py`). Also extended on existing `pool_route_execute` to forward `caller_kind` and `parent_session_id`.

## Integration point

Extends `PoolManager.route_task` (`mahavishnu/pools/manager.py:460-512`) with `caller_kind` and `parent_session_id` parameters. New per-caller quota tracking via `_caller_quota: dict[str, _QuotaState]` in `PoolManager.__init__`. New Dhara prefix `workflow-results/{workflow_id}/` for async-callback results.

## End-to-end check

`pytest tests/unit/test_pool_tools.py::test_dispatch_to_pool_async_callback_returns_workflow_id -v` — assert that calling `dispatch_to_pool(..., async_callback=True)` returns `{"workflow_id": "...", "status": "queued"}` immediately and that Dhara has a corresponding record.

Plus integration: from an ultracode subagent, call `dispatch_to_pool(prompt="...", caller_kind="ultracode", parent_session_id="ses_abc", async_callback=True)` and verify the response contains `workflow_id` and that Dhara has a `routing-decisions/{workflow_id}/` record with `caller_kind=ultracode`, `parent_session_id=ses_abc`.

## Blocker

None — implementation pending Phase 3 of `docs/plans/2026-07-11-ultracode-integration-wiring.md`.

## Next action

Execute Phase 3, Tasks 3.1–3.7 of the source plan. Owner: mahavishnu core. Target: end of week 2026-07-18.

## Related

- Plan: `docs/plans/2026-07-11-ultracode-integration-wiring.md` (Phase 3)
- ADR-014: caller-side authorization for pool selection (foundation for `caller_pool_allowlist`)
- `mahavishnu/pools/manager.py::PoolManager.route_task` (the extended method)
- `mahavishnu/mcp/tools/pool_tools.py::pool_route_execute` (the extended sibling)
- Parking lot: `docs/feature-tracking/2026-07-11-ultracode-tier2-parking-lot.md` (entry 2.2 — token-budget caps — extends this with budget-side rate limiting)

## Session-Buddy

- Reflection ID: <to be filled>
- Saved at: <ISO timestamp>
