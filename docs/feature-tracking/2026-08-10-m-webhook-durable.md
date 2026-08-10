---
name: m-webhook-durable
status: built
date: 2026-08-10
last_reviewed: 2026-08-10
owner: mahavishnu core
role: canonical
---

# Feature: webhook durable ingress (validate-on-write + validate-on-read)

**Owner:** mahavishnu core
**Created:** 2026-08-10
**Last updated:** 2026-08-10
**Repo(s):** /Users/les/Projects/mahavishnu
**Plan:** `docs/superpowers/plans/2026-08-10-m-webhook-durable.md`

## State — pick one

- [x] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

`built` was reached when Task 1 produced `mahavishnu/webhooks/receiver.py` (commits `cf188d60` + `9dc547c1`), Task 2 produced `mahavishnu/webhooks/replay.py` (commit `7af40ce6`), and Task 3 produced `tests/unit/test_webhooks_roundtrip.py` + this completion report (commit pending). The producer/consumer contract — `dhara.put("webhook-ingress/{webhook_id}/", WebhookIngress)` on write, `dhara.get("webhook-ingress/{webhook_id}/")` on read, with `from_dict("webhook_ingress", payload)` validation — is verified by 3 round-trip tests.

**`wired` is NOT yet reached.** See "Blocker" below — production webhook ingress traffic still flows through `mahavishnu/webhooks/router.py` (OpenClaw-typed Pydantic surface), not through the new `receiver.py`. The receiver is a sibling leaf module that satisfies the plan's substrate-compat + durable-persistence contract but is not mounted in production. A future wiring plan must thread the durable receiver into the live ingress.

## Wiring checklist

- [x] Entry point registered (`receive_webhook` lives in `mahavishnu/webhooks/receiver.py`; `webhook_replay` lives in `mahavishnu/webhooks/replay.py`; tests cover both)
- [x] Trigger path identified (inbound HTTP `POST /webhook` on the durable receiver constructs a `WebhookIngress` and persists via `dhara.put(f"webhook-ingress/{webhook_id}/", validated)`)
- [x] Returns / state updates land in expected destination (`webhook-ingress/{webhook_id}/` prefix on Dhara, typed `WebhookIngress` struct on read with `from_dict("webhook_ingress", payload)`)
- [x] End-to-end smoke check documented (`.venv/bin/python -m pytest tests/unit/test_webhooks_receiver.py tests/unit/test_webhooks_replay.py tests/unit/test_webhooks_roundtrip.py --no-cov` → 11 passed in 10.35s)
- [x] Observability hook in place (oneiric logger via `oneiric.core.logging.get_logger`; `webhook_ingress_recorded` on success, `webhook_persistence_skipped` with distinct `reason` values for `v1_disabled` vs `dhara.put_unbound`, `invalid_webhook` on validation failure — never carries `str(exception)` in `extra`)
- [x] Rollback signal defined (set `WEBHOOK_DURABLE_V1_ENABLED=false` env var; legacy in-memory fallback returns `{"status": "accepted_in_memory_only"}` with structured warning)

## Built (yes/no)

yes — producer (Task 1), consumer (Task 2), and round-trip test (Task 3) all shipped. Substrate-compat pattern mirrors `decision_writer.py` and `outcome_writer.py` so any future substrate injection lands cleanly.

## Wired (yes/no)

**no** — see Blocker. The receiver module is created and tested but production webhook traffic still flows through `router.py`. This plan's deliverable is `built`; the `wired` transition requires a follow-up plan that mounts `receiver.py` into the live ingress path.

## Trigger path (planned, not yet live)

1. Inbound HTTP `POST /webhook` arrives at `mahavishnu/webhooks/receiver.py:57` (`receive_webhook` handler).
2. Body validated via `dhara.schema.validate("webhook_ingress", payload)` — failure path returns 422 `WEBHOOK_VALIDATION_ERROR` and emits `invalid_webhook` log (no `str(exception)` in `extra`).
3. On validation success: `_webhook_durable_v1_enabled()` flag is consulted. When `false`, the receiver short-circuits to `{"status": "accepted_in_memory_only"}` and emits `webhook_persistence_skipped` with `reason='v1_disabled'`.
4. Substrate-compat gate: `getattr(dhara, "put", None)` — when unbound, the receiver short-circuits to `{"status": "accepted_in_memory_only"}` and emits `webhook_persistence_skipped` with `reason='dhara.put_unbound'` and `v1_enabled=<state>`.
5. Durable path: `dhara.put(f"webhook-ingress/{webhook_id}/", validated)` — record lands at the producer/consumer durability key. `webhook_ingress_recorded` info log emitted with `{webhook_id, source}`.
6. Producer returns 200 with `{"status": "accepted", "webhook_id": ...}` on the durable path; 202 with `{"status": "accepted_in_memory_only"}` on either fallback path.
7. Consumer side: any caller invokes `webhook_replay(webhook_id)` from `mahavishnu/webhooks/replay.py:37`.
8. Substrate-compat gate mirrors the receiver: missing `dhara.get` binding → `None` + `webhook_replay_skipped` warning with `reason='dhara.get_unbound'`. Missing record → `None` (no log, per zero-noise contract).
9. Read path: `dhara.get(f"webhook-ingress/{webhook_id}/")` returns the persisted record; `from_dict("webhook_ingress", payload)` returns the typed `WebhookIngress` struct for the caller.

## Integration point

- Producer (`receive_webhook`): `mahavishnu/webhooks/receiver.py` — FastAPI app, `POST /webhook` endpoint, `response_model=None` so the `JSONResponse | dict[str, str]` union is accepted by Pydantic. Substrate-compat `if not hasattr(dhara, "put"): dhara.put = None` at module top.
- Consumer (`webhook_replay`): `mahavishnu/webhooks/replay.py` — leaf module, no FastAPI app. Substrate-compat `if not hasattr(dhara, "get"): dhara.get = None` at module top.
- Feature flag: `_webhook_durable_v1_enabled()` helper at `mahavishnu/webhooks/receiver.py:36-44` reads `WEBHOOK_DURABLE_V1_ENABLED` env var (default `"true"`, case-insensitive).
- Persistence key: `f"webhook-ingress/{webhook_id}/"` — producer and consumer both pin this format. The round-trip test `test_webhook_round_trip_uses_matching_persistence_keys` locks the contract.

## End-to-end check

```
.venv/bin/python -m pytest \
  tests/unit/test_webhooks_receiver.py \
  tests/unit/test_webhooks_replay.py \
  tests/unit/test_webhooks_roundtrip.py \
  --no-cov
# → 11 passed in 10.35s
```

Tests cover:

| Test | File | Path covered |
|------|------|--------------|
| `test_webhook_round_trip_struct_equality` | `tests/unit/test_webhooks_roundtrip.py` | Producer→consumer struct equality across all 5 `WebhookIngress` fields |
| `test_webhook_round_trip_uses_matching_persistence_keys` | `tests/unit/test_webhooks_roundtrip.py` | Producer write key == consumer read key (key format lock) |
| `test_webhook_round_trip_with_distinct_ids_isolates_records` | `tests/unit/test_webhooks_roundtrip.py` | Per-`webhook_id` substrate-key isolation |
| `test_post_webhook_emits_validated_struct` | `tests/unit/test_webhooks_receiver.py` | Happy path: 202 + validated struct persisted |
| `test_post_webhook_rejects_invalid_payload` | `tests/unit/test_webhooks_receiver.py` | Missing `webhook_id` → 422 + no put |
| `test_post_webhook_emits_warning_when_dhara_put_unbound` | `tests/unit/test_webhooks_receiver.py` | `dhara.put=None` → 202 + structured warn |
| `test_post_webhook_falls_back_to_in_memory_when_v1_disabled` | `tests/unit/test_webhooks_receiver.py` | `WEBHOOK_DURABLE_V1_ENABLED=false` → 202 + warn with `reason='v1_disabled'` |
| `test_webhook_replay_returns_validated_struct` | `tests/unit/test_webhooks_replay.py` | Happy path: typed `WebhookIngress` round-trips |
| `test_webhook_replay_uses_persistence_key_format` | `tests/unit/test_webhooks_replay.py` | Read key format |
| `test_webhook_replay_returns_none_when_record_missing` | `tests/unit/test_webhooks_replay.py` | Missing record → `None` (no spurious struct) |
| `test_webhook_replay_returns_none_when_dhara_unbound` | `tests/unit/test_webhooks_replay.py` | `dhara.get=None` → `None` + warn |

Pre-existing test count summary:

- Task 1: 2 producer tests in `tests/unit/test_webhooks_receiver.py`
- Task 1 fix: 2 additional producer tests (substrate unbound + v1 disabled)
- Task 2: 4 consumer tests in `tests/unit/test_webhooks_replay.py`
- Task 3: 3 round-trip tests in `tests/unit/test_webhooks_roundtrip.py`
- Total new tests across this plan: **11**

## Blocker

**`wired` is not yet reachable — receiver is not mounted in production.**

The plan's stated goal is to "close the durable-ingress gap," but as of this report's last update, production webhook traffic still arrives at `mahavishnu/webhooks/router.py` (`mahavishnu/webhooks/router.py` exposes OpenClaw-typed Pydantic surfaces for the per-endpoint sweep / workflow contracts and does NOT persist anything via the substrate). The `receiver.py` module built in this plan is a sibling leaf — its tests confirm validate-on-write + validate-on-read + round-trip semantics against a substrate-compat gate, but no inbound request from production has ever gone through it.

In other words: the durable substrate writes never happen in production because `router.py` is still the live ingress. The plan delivers the durable receiver module but not the wiring that turns live inbound traffic into durable substrate writes.

This gap was flagged by the Task 1 reviewer (see `task-1-fix-report.md`) and explicitly deferring it was the rationale for marking Task 1 review follow-ups as "Critical but deferrable to a future wiring pass."

## Next action

Owner: mahavishnu core. Target: M-WEBHOOK-DURABLE-WIRED (follow-up plan) before this surface can transition out of `built`.

1. **HIGH `producer-not-mounted-in-production`** — Thread the durable `receiver.py` into the live ingress path. Options:
   - **A.** Replace `router.py`'s per-endpoint handlers with a single dispatch to `receive_webhook` while preserving the OpenClaw-typed contracts (most invasive; preserves typed contracts downstream).
   - **B.** Add `receive_webhook` as an additional route alongside the existing `router.py` (low risk; surfaces both contracts; operators choose which to call).
   - **C.** Add a middleware wrapper in front of the FastAPI app that transparently mirrors every inbound `POST` to `receive_webhook` (lowest risk; transparent to existing callers; subtle caching semantics risk).
   Default recommendation: **Option B** (sidecar route) for the first cut so operators can opt in to durable mode without taking on a typed-rewrite risk.
2. **MEDIUM `cross-portfolio-consistency-drift`** — The `valid_payload` shape and substrate-compat pattern are now repeated across `tests/unit/test_decision_writer.py`, `tests/unit/approval/test_decision_writer.py`, `tests/unit/approval/test_list_history.py`, `tests/unit/workflow/test_outcome_writer.py`, and `tests/unit/webhooks/test_*`. A `tests/conftest.py` factory for substrate-compat fixture + canonical payload builders is overdue (cross-portfolio v1.1 candidate).
3. **MEDIUM `missing-observability-counters`** — Producer uses `logger.info/warn` for v1 visibility; spec calls for `webhook_ingress_recorded_total{source}` and `webhook_replay_total{outcome}` counters. Switch to a metrics sink when one stabilizes.
4. **Minor** — Promote the `webhook-ingress/{webhook_id}/` path prefix to a constant in `receiver.py` so the producer and consumer agree on it without string repetition (mirrors the approval-log follow-up).
5. **Minor** — Persist the receiver's POST body verbatim (not just the `WebhookIngress` projection) so future consumers can re-validate against a different schema without losing data — currently the round-trip preserves the substrate schema only.
6. **Cross-portfolio v1.1 hardening items** (from M-APPROVAL-LOG / M-WORKFLOW-OUTCOME backlog, equally applicable here):
   - HIGH — Add RBAC `user_id` + permission check on the read path (`webhook_replay`)
   - MEDIUM — Tighten `webhook_id` allowlist if `webhook_id` is ever constructed from user input
   - MEDIUM — Never log `str(exception)` in `extra=` payloads (this plan's tests already verify `exc_info is None` for both new warning paths)

## Spec coverage map

| Spec section / requirement | Task(s) |
|---|---|
| Goal — close the durable-ingress gap with validate-on-write + validate-on-read | Tasks 1, 2 |
| Architecture — producer (receiver) + consumer (replay) | Tasks 1, 2 |
| Integration Contract: Triggered from `POST /webhook` | Task 1 |
| Integration Contract: Returns to `webhook-ingress/{webhook_id}/` | Task 1 |
| Integration Contract: Demonstrable by round-trip | Task 3 |
| Rollback signal `WEBHOOK_DURABLE_V1_ENABLED` | Task 1 fix |
| Observability: `webhook_ingress_recorded_total{source}` | Deferred (v1.1 hardening) |

## Related

- Plan: `docs/superpowers/plans/2026-08-10-m-webhook-durable.md`
- Task 1 commit: `cf188d60` — `feat(webhooks): durable webhook receiver (validate-on-write)`
- Task 1 fix commit: `9dc547c1` — `fix(webhooks): add WEBHOOK_DURABLE_V1_ENABLED flag + runtime gate`
- Task 2 commit: `7af40ce6` — `feat(webhooks): webhook_replay MCP tool — read-back via from_dict`
- Task 3 commit: pending — `test(webhooks): round-trip + completion report for M-WEBHOOK-DURABLE`
- Substrate-compat pattern: `dhara.schema` public re-exports (never `_base` / `_registry`)
- Sibling precedent: `2026-08-10-m-workflow-outcome.md` and `2026-08-10-m-approval-log.md` (same validate-on-write + validate-on-read contract, same substrate-compat pattern)
- Rollback: revert the 4 land commits; toggle `WEBHOOK_DURABLE_V1_ENABLED=false` for inline rollback without redeploy
- **Open follow-up**: M-WEBHOOK-DURABLE-WIRED — Thread `receiver.py` into the live ingress path; replace `router.py` or add a sidecar route

## Session-Buddy

- Reflection capture deferred to follow-up — this completion report is the canonical record; reflection capture happens during `built` → `wired` transition (after the receiver gets mounted in production) and again during `wired` → `adopted` transition when a downstream consumer exercises the read path in production.
