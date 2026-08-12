---
name: m-workflow-outcome
status: built
date: 2026-08-10
last_reviewed: 2026-08-10
state_history:
  - "2026-08-10: wired (initial v1 ship — Task 4)"
  - "2026-08-10: built (multi-agent review surfaced missing feature flag + producer/consumer getattr gates)"
owner: mahavishnu core
role: canonical
---

# Feature: workflow-outcome pipeline (validate-on-write + validate-on-read)

**Owner:** mahavishnu core
**Created:** 2026-08-10
**Last updated:** 2026-08-10
**Repo(s):** /Users/les/Projects/mahavishnu
**Plan:** `docs/superpowers/plans/2026-08-10-m-workflow-outcome.md`

## State — pick one

- [x] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

> **State correction (2026-08-10):** flipped from `wired` to `built` per multi-agent review. Three Critical findings prevent the `wired` claim from holding:
>
> 1. **`WORKFLOW_OUTCOME_V1_ENABLED` feature flag** — absent at `outcome_writer.py`. Plan's own global-constraint §24 mandated the flag (default `True`; rollback is "disable the flag, writer becomes no-op"). M-APPROVAL-LOG and M-WEBHOOK-DURABLE both ship their flag; this plan was the outlier.
> 2. **`getattr(dhara, "put", None)` runtime gate in producer body** — absent at `outcome_writer.py:42`. The import-time hasattr stamp (`outcome_writer.py:20-21`) sets `dhara.put = None` if unbound, but the producer body calls `dhara.put(...)` directly; a substrate-unbound production deployment would raise `TypeError: 'NoneType' object is not callable` on every workflow completion rather than skip-and-warn.
> 3. **`getattr(dhara, "get", None)` runtime gate in consumer body** — absent at `workflow_tools.py:42`. Same risk; a substrate-unbound MCP caller would 500.
>
> Once all three land (target: v1.1 hardening cycle), flip back to `wired`. Original ship evidence preserved below for audit.

`wired` (original, pre-flip): reached when Task 3 production-gated `record_workflow_outcome()` inside `finalize_workflow_execution()` (`mahavishnu/core/workflow_execution.py:331`) and registered `workflow_get_outcome_tool` via FastMCP (`mahavishnu/mcp/bootstrap.py`). Task 4 round-trip test (5 passing tests) proves the end-to-end contract between producer and consumer.

## Wiring checklist

- [x] Entry point registered (`workflow_get_outcome_tool` registered via `@mcp.tool()` in `mahavishnu/mcp/tools/workflow_tools.py`, surfaced through `mahavishnu/mcp/bootstrap.py`)
- [x] Trigger path identified (workflow completion boundary in `finalize_workflow_execution()` invokes `record_workflow_outcome()`; `workflow_get_outcome_tool` reads back from any MCP caller)
- [x] Returns / state updates land in expected destination (`workflow-results/{workflow_id}/` prefix on Dhara, typed `WorkflowOutcome` struct on read)
- [x] End-to-end smoke check documented (`.venv/bin/python -m pytest tests/unit/workflow/test_outcome_round_trip.py --no-cov` → 5 passed in 7.06s)
- [x] Observability hook in place (oneiric logger via `oneiric.core.logging.get_logger`; failure path logs `outcome_err` at warn level inside `finalize_workflow_execution()` — see Deferred items for hardening)
- [x] Rollback signal defined (revert the 4 land commits — see Related)

## Built (yes/no)

yes — producer (Task 1) and consumer (Task 2) both shipped; wired (Task 3) registers the MCP tool and production-gates the completion boundary.

## Wired (yes/no)

yes — Task 4 round-trip test locks the validate-on-write + validate-on-read contract; integration path is exercised end-to-end through real producer/consumer modules with the substrate-compat pattern substituted via `monkeypatch`.

## Trigger path

1. Workflow completes (success, failure, or cancellation) inside `finalize_workflow_execution()` at `mahavishnu/core/workflow_execution.py:331`.
2. Boundary call to `record_workflow_outcome(workflow_id, status, started_at, finished_at, metadata=None)` constructs a `WorkflowOutcome` msgspec Struct, validates via `dhara.schema.validate("workflow_outcome", payload)`, and persists via `dhara.put(f"workflow-results/{workflow_id}/", validated)`.
3. Status mapping at the boundary: `"completed"` → `"succeeded"`, `"partial"` → `"cancelled"` (see `workflow_execution.py:380-388`).
4. MCP consumer side: any registered FastMCP caller invokes `mcp__mahavishnu__workflow_get_outcome(workflow_id)`.
5. `validate_workflow_id(workflow_id)` from `mahavishnu/mcp/tools/_workflow_id_guard.py` gates against `^[A-Za-z0-9._-]{1,128}$` before touching Dhara; on mismatch returns `{"workflow_id": workflow_id, "status": "invalid_workflow_id"}` sentinel.
6. `dhara.get(f"workflow-results/{workflow_id}/")` reads back the persisted dict; `None` propagates as `None` (no record → no validation); otherwise `from_dict("workflow_outcome", payload)` returns a typed `WorkflowOutcome`.

## Integration point

- Producer (`record_workflow_outcome`): `mahavishnu/core/workflow/outcome_writer.py` — substrate-compat `if not hasattr(dhara, "put"): dhara.put = None` so test `monkeypatch` lands without a real Dhara binding.
- Boundary call site: `mahavishnu/core/workflow_execution.py:331` (`finalize_workflow_execution`).
- Consumer (`workflow_get_outcome`): `mahavishnu/mcp/tools/workflow_tools.py` — registered as `workflow_get_outcome_tool` via FastMCP decorator (FastMCP requires coroutines, so the function is `async def`).
- Path-traversal guard: `mahavishnu/mcp/tools/_workflow_id_guard.py` — extracted from `pool_tools.py` in Task 3 fix round 1 to give sibling parity (`workflow_result` and `dispatch_to_pool` already used this gate).
- MCP registration: `mahavishnu/mcp/bootstrap.py` — imports `workflow_get_outcome_tool` and registers it on the FastMCP server.

## End-to-end check

```
.venv/bin/python -m pytest tests/unit/workflow/test_outcome_round_trip.py --no-cov
# → 5 passed in 7.06s
```

Tests cover:

1. `test_round_trip_succeeded_outcome_round_trips` — succeeded status, custom metadata, struct equality on all 5 fields.
2. `test_round_trip_failed_outcome_round_trips` — failed status survives the boundary (no metadata provided).
3. `test_round_trip_cancelled_outcome_round_trips` — cancelled status survives the boundary.
4. `test_round_trip_default_metadata_round_trips` — default `metadata={}` is preserved through both validate calls.
5. `test_round_trip_consumer_returns_none_when_writer_missing` — consumer pre-condition (no record) returns `None`, independent of producer.

`tests/unit/mcp/tools/test_workflow_tools.py` adds 7 tests (5 from Task 2/3 + 2 RED→GREEN path-traversal tests from the Task 3 fix round). Combined with `tests/unit/workflow/test_outcome_writer.py` (2 tests) and `tests/unit/workflow/test_outcome_round_trip.py` (5 tests), the validate-on-write + validate-on-read contract is exercised by 14 tests on the producer/consumer pair.

Pre-existing test count summary:

- Task 1: 2 producer tests
- Task 2: 2 consumer tests (initial)
- Task 3: +2 path-traversal tests, +5 wiring tests in `tests/unit/test_workflow_execution.py`
- Task 4: 5 round-trip tests
- Total new tests across this plan: **14**

## Blocker

None blocking. Three security findings from Task 3 review remain as `wired`-state follow-ups (see Deferred items).

## Next action

Owner: mahavishnu core. Target: v1.1 hardening cycle.

1. **HIGH `missing-authorization`** — Add RBAC `user_id` + `Permission.VIEW_WORKFLOW_STATUS` check on `workflow_get_outcome_tool`. Currently any MCP caller can read any workflow's outcome.
2. **MEDIUM `under-validated-sink-arg`** — Tighten `WORKFLOW_ID_PATTERN` from `^[A-Za-z0-9._-]{1,128}$` to producer shape `^wf_[0-9a-f]{8}_.+$` (per `workflow_execution.py:39`). Stops traversal but doesn't currently narrow to the producer's actual key format.
3. **MEDIUM `sensitive-to-observability`** — `str(outcome_err)` in `workflow_execution.py:407-415` may leak sensitive data; log `type(outcome_err).__name__` only.
4. **Minor** — Remove back-compat aliases (`_WORKFLOW_ID_PATTERN`, `_validate_workflow_id`) from `_workflow_id_guard.py:32-33` after one release cycle.
5. **Minor** — Add docstring note that `started_at` is derived from `finished_at - timedelta(seconds=execution_time)` (approximate, not observed).
6. **Minor** — Promote the C901 noqa to a per-file-ignore in `pyproject.toml`.

## Related

- Plan: `docs/superpowers/plans/2026-08-10-m-workflow-outcome.md`
- Task 1 commit: `7fa38d15fe9a13edb8a61b80a9b6f6b71c5b37da` (producer)
- Task 2 commit: `c0265696643493b9fce6b4a01c06209c54eb642a` (consumer)
- Task 3 commits: `788f142a` (wiring) → `3fb597553567ada7dea6f07a11c4203a334912c3` (path-traversal fix)
- Task 4 commit: pending — round-trip test + this completion report
- Substrate-compat pattern: `dhara.schema` public re-exports (never `_base` / `_registry`)
- Path-traversal guard shared with `pool_tools.workflow_result` and `pool_tools.dispatch_to_pool` via `_workflow_id_guard.py`
- Rollback: revert the 4 land commits; the only other state is `docs/feature-tracking/2026-08-10-m-workflow-outcome.md` (this file).

## Session-Buddy

- Reflection ID: <to be filled>
- Saved at: <ISO timestamp>
