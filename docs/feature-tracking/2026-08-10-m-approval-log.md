---
name: m-approval-log
status: wired
date: 2026-08-10
last_reviewed: 2026-08-10
owner: mahavishnu core
role: canonical
---

# Feature: approval-log pipeline (validate-on-write + validate-on-read)

**Owner:** mahavishnu core
**Created:** 2026-08-10
**Last updated:** 2026-08-10
**Repo(s):** /Users/les/Projects/mahavishnu
**Plan:** `docs/superpowers/plans/2026-08-10-m-approval-log.md`
**Spec:** `docs/superpowers/specs/2026-08-10-m-approval-log-design.md`

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

`wired` was reached when Task 3 production-gated `record_approval_decision()` inside `ApprovalManager.respond()` (`mahavishnu/core/approval_manager.py:261`) and the legacy delete-on-resolve branch was demoted to a feature-flag rollback path (`APPROVAL_LOG_V1_ENABLED=false`). Task 4 round-trip integration test (4 passing tests) proves the end-to-end contract between producer and consumer.

## Wiring checklist

- [x] Entry point registered (`record_approval_decision` lives in `mahavishnu/core/approval/decision_writer.py`; called by `ApprovalManager.respond()` under the flag; `list_approval_history` lives in `mahavishnu/cli/approval_cli.py` reachable as `mahavishnu approvals list-history`)
- [x] Trigger path identified (decision flow boundary in `ApprovalManager.respond()` invokes `record_approval_decision()`; `list_approval_history` reads back from any CLI caller)
- [x] Returns / state updates land in expected destination (`approval-history/{approval_id}/` prefix on Dhara, typed `ApprovalLog` struct on read with `Literal["approved","denied","requested"]` action)
- [x] End-to-end smoke check documented (`.venv/bin/python -m pytest tests/integration/approval/test_round_trip.py --no-cov` → 4 passed in 5.43s)
- [x] Observability hook in place (oneiric logger via `oneiric.core.logging.get_logger`; producer emits `warn` log when persistence is skipped per `3fe46719` cross-portfolio consistency fix; skip-bad path in consumer emits `warn` on `SchemaValidationError`)
- [x] Rollback signal defined (revert the 4 land commits; legacy `_schedule_dhara_delete` available via `APPROVAL_LOG_V1_ENABLED=false` with no redeploy)

## Built (yes/no)

yes — producer (Task 1), consumer (Task 2), and wiring (Task 3) all shipped. Task 4 round-trip integration test locks the end-to-end contract.

## Wired (yes/no)

yes — Task 4 round-trip test locks the validate-on-write + validate-on-read contract; integration path is exercised end-to-end through real producer/consumer modules with the substrate-compat pattern substituted via `monkeypatch`. The plan's "Demonstrable by round-trip" acceptance criterion is satisfied.

## Trigger path

1. Operator approves/denies an approval request via `ApprovalManager.respond()` at `mahavishnu/core/approval_manager.py:261`.
2. Boundary call to `record_approval_decision(approval_id, decision, rationale, decided_by, metadata)` constructs an `ApprovalLog` msgspec Struct, validates via `dhara.schema.validate("approval_log", payload)`, and persists via `dhara.put(f"approval-history/{approval_id}/", validated)`.
3. Field mapping at the boundary (in `ApprovalManager._persist_approval_decision`, `mahavishnu/core/approval_manager.py:188-225`):
   - `request.id` → `approval_id`
   - `approved` (bool) → `decision` ("approved" / "denied")
   - `rejection_reason or ""` → `rationale`
   - `request.context["decided_by"]` (fallback `"system"`) → `decided_by`
   - `selected_option` / `approval_type` → `metadata` dict
4. Producer auto-generates `at: datetime.now(UTC)` so callers don't need to pass `decided_at`.
5. Consumer side: any operator invokes `list_approval_history(approval_id, since, status)` via `mahavishnu approvals list-history`.
6. `dhara.list(f"approval-history/{approval_id}/", since=..., status=...)` reads back the persisted records; per-payload `from_dict("approval_log", payload)` returns typed `ApprovalLog` structs (skip-bad partial-failure resilience on `SchemaValidationError`).
7. Legacy delete-on-resolve path remains available via `APPROVAL_LOG_V1_ENABLED=false` flag read at module level via `_approval_log_v1_enabled()` helper.

## Integration point

- Producer (`record_approval_decision`): `mahavishnu/core/approval/decision_writer.py` — substrate-compat `if not hasattr(dhara, "put"): dhara.put = None` so test `monkeypatch` lands without a real Dhara binding.
- Boundary call site: `mahavishnu/core/approval_manager.py:261` (`ApprovalManager.respond`) — gated behind `APPROVAL_LOG_V1_ENABLED` feature flag.
- Consumer (`list_approval_history`): `mahavishnu/cli/approval_cli.py` — substrate-compat `if not hasattr(dhara, "list"): dhara.list = None`; per-payload `from_dict("approval_log", payload)` validation inside try/except `SchemaValidationError` for partial-failure resilience.
- Feature flag: `_approval_log_v1_enabled()` helper at `mahavishnu/core/approval_manager.py:42-45` reads `APPROVAL_LOG_V1_ENABLED` env var (default `"true"`).
- Rollback primitive: `_schedule_dhara_delete(request_id)` retained at `mahavishnu/core/approval_manager.py:228-235` (legacy always-delete-when-called; call sites choose between legacy delete and producer persistence).

## End-to-end check

```
.venv/bin/python -m pytest tests/integration/approval/test_round_trip.py --no-cov
# → 4 passed in 5.43s
```

Tests cover:

1. `test_approval_log_round_trips_with_struct_equality` — Producer writes a struct; consumer reads it back; `msgspec.Struct` equality holds across all 5 fields (`approval_id`, `actor`, `action`, `at`, `metadata`).
2. `test_approval_log_round_trip_with_status_filter` — Two records (approved, denied) under the same `approval_id`; `status` arg partitions the read-back correctly.
3. `test_approval_log_round_trip_isolates_per_approval_id` — Two distinct `approval_id`s produce two distinct substrate prefix keys; read-back is scoped to the requested ID.
4. `test_approval_log_round_trip_default_metadata_round_trips` — When the caller omits `metadata`, the producer defaults to an empty dict and the round-trip preserves it.

Pre-existing test count summary:

- Task 1: 2 producer tests in `tests/unit/approval/test_decision_writer.py`
- Task 2: 2 consumer tests in `tests/unit/approval/test_list_history.py`
- Task 3: 7 wiring tests in `tests/unit/approval/test_decision_wiring.py` + 1 flip in `tests/unit/test_approval_manager.py`
- Task 4: 4 round-trip integration tests in `tests/integration/approval/test_round_trip.py`
- Total new tests across this plan: **15**

## Blocker

None blocking. Two follow-up items from spec section "Observability added" remain as `wired`-state follow-ups (see Deferred items).

## Next action

Owner: mahavishnu core. Target: v1.1 hardening cycle.

1. **MEDIUM `async-passthrough-not-verified`** — Task 3 reviewer flagged that `record_approval_decision` calls `dhara.put(...)` sync, but substrate binding may be async-only in production. Task 4 round-trip test uses sync monkeypatches, not the real async binding. Validate against the real substrate under load — if a hang/coroutine warning surfaces, convert `record_approval_decision` to `async def` (mirrors M-WORKFLOW-OUTCOME Task 3 fix).
2. **MEDIUM `missing-observability-counters`** — Spec calls for `approval_log_recorded_total{decision}` and `approval_log_invalid_total{reason}` counters. Currently producer uses `logger.info/warn` for v1 visibility; switch to a metrics sink when one stabilizes.
3. **MEDIUM `missing-migration`** — Pre-v1 approvals remain in `approval/v1/`; new v1 records land in `approval-history/`. The two paths coexist; cleanup is not in scope but a backfill migration is a v1.1 candidate.
4. **Minor** — Pull the `ApprovalLog` schema test fixture (used in `test_decision_wiring.py` for the `selected_option` carrying test) out of the test file into a shared fixture if a third writer-adjacent test lands.
5. **Minor** — Promote the `approval-history/{approval_id}/` path prefix to a constant in `decision_writer.py` so the producer and consumer agree on it without string repetition.
6. **Cross-portfolio v1.1 hardening items** (from M-WORKFLOW-OUTCOME backlog, equally applicable here):
   - HIGH — Add RBAC `user_id` + permission check on the read path (CLI: `list_approval_history`)
   - MEDIUM — Tighten `approval_id` allowlist if `approval_id` is ever constructed from user input
   - MEDIUM — Never log `str(exception)` in `extra=` payloads (producer's `approval_log_persistence_skipped` already does this correctly per commit `3fe46719`)

## Spec coverage map

| Spec section / requirement | Task(s) |
|---|---|
| Goal — wire `approval_log` typed schema, stop delete-on-resolve | Tasks 1, 3 |
| Architecture — producer + consumer | Tasks 1, 2 |
| Integration Contract: Triggered from `record_decision` | Task 3 |
| Integration Contract: Returns to `approval-history/{approval_id}/` | Task 1 |
| Integration Contract: Demonstrable by round-trip | Task 4 |
| Rollback signal `APPROVAL_LOG_V1_ENABLED` | Task 3 (call-site gate, not producer body) |
| Observability: `approval_log_recorded_total{decision}` counters | Deferred (v1.1 hardening) |
| Observability: `approval_log_invalid_total{reason}` counters | Deferred (v1.1 hardening) |

## Related

- Plan: `docs/superpowers/plans/2026-08-10-m-approval-log.md`
- Spec: `docs/superpowers/specs/2026-08-10-m-approval-log-design.md`
- Task 1 commits: `c8cec717` (producer) → `3fe46719` (cross-portfolio log warn consistency)
- Task 2 commits: `d4c0937d` (log error type not str(err)) → `136df375` (consumer)
- Task 3 commit: `b28ac619` (wire record_approval_decision into decision flow)
- Task 4 commit: `e091ecea` — round-trip integration test + this completion report
- Substrate-compat pattern: `dhara.schema` public re-exports (never `_base` / `_registry`)
- Sibling precedent: `2026-08-10-m-workflow-outcome.md` (same validate-on-write + validate-on-read contract, same substrate-compat pattern)
- Rollback: revert the 4 land commits; toggle `APPROVAL_LOG_V1_ENABLED=false` for inline rollback without redeploy

## Session-Buddy

- Reflection capture deferred to follow-up — this completion report is the canonical record; reflection capture happens during `wired` → `adopted` transition when a downstream consumer exercises the read path in production.
