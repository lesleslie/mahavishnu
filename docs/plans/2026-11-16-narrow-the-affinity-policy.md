---
status: complete
role: implementation
kind: plan
date: 2026-11-16
last_reviewed: 2026-11-16
superseded_by: null
topic: pool-routing-affinity
title: "Narrow the shipped affinity policy to the deployment's pinnable pools"
requirements:
- id: REQ-POLICY-001
  title: "The operator's policy gates pinning, not server-chosen routing"
- id: REQ-POLICY-002
  title: "Both sides of the authorization test speak in canonical pool ids"
- id: REQ-POLICY-003
  title: "The shipped policy names the deployment's pinnable pools"
---

# Narrow the shipped affinity policy to the deployment's pinnable pools

## 1. Outcome

`settings/mahavishnu.yaml` stops shipping `caller_pool_allowlist: ["*"]` and
names the pools this deployment may be pinned to instead.

**Success signal:** a dispatch that names a pool outside the policy is refused
and falls back to the server's own choice; a dispatch that names a pool inside
it lands on that pool; and ordinary load-balanced routing still reaches every
registered pool, including one an operator spawned by hand.

## 2. Goals

1. Replace the wildcard with an explicit list of the deployment's pinnable
   pools.
1. Make a name-based policy actually satisfiable by a name-based request.
1. Keep ordinary routing working for pools the policy does not name.

## 3. Non-Goals

1. Not changing the pool selection *order* — only the authorization gate.
1. Not adding a per-caller dimension to the policy (ADR-014 forbids it).
1. Not changing what a caller-supplied `caller_pool_allowlist` means for an
   internal caller that declares one.

## 4. Current Findings

1. **The allowlist does two jobs, and the operator policy inherited both.**
   ADR-014 (`docs/adr/014-honcho-peer-model-routing-precedence.md`) defines
   `caller_pool_allowlist` as the gate for AFFINITY and PEER_AFFINITY — the
   pools a caller may *pin*. But S-4
   (`mahavishnu/pools/manager.py:1280`) also filters the queueing re-rank's
   candidate set by it, and `_apply_gpu_category_override`
   (`mahavishnu/pools/manager.py:1621`) and the working-directory candidate
   set use it too. No production caller supplies the parameter — it is
   always `None` — so the operator's policy always landed in the dispatch
   slot.

1. **So a narrow policy breaks ordinary routing.** Measured 2026-11-16 with
   one registered pool named `operator-pool`:

   ```
   policy=['*']              least_loaded -> proceeds
   policy=['merge-review']   least_loaded -> RuntimeError: Queueing fallback
                              would route to pool 'mahavishnu_9999' which is
                              not in caller_pool_allowlist ['merge-review']
   ```

   The policy would have to name every pool the deployment will ever use.
   Pools here are spawned on demand by name (`auto-spawned`,
   `mahavishnu/core/merge_review_dispatcher.py:297`, the agent doc's
   `claude-pool`), so no fixed list satisfies that — the wildcard is not a
   policy choice so much as the only one the current semantics permit.

1. **A name-based policy cannot be pinned by name.** The policy's tokens
   resolve name→id (`_server_pool_allowlist`,
   `mahavishnu/pools/manager.py:697`), but the caller's reference is
   compared verbatim. Measured 2026-11-16:

   ```
   POLICY ['beta'] RESOLVED TO : {'pool_b'}
   REQUEST 'beta'   (name)    -> ('pool_b', 'affinity_allowlist_filtered_fallback')
   REQUEST 'pool_b' (id)      -> ('pool_b', 'affinity')
   ```

   The only reference a name-based policy accepts is a per-spawn id — the
   one form a config file cannot contain. The wildcard is affected too:
   `"*" in allowlist` tests `pool_id in self._pools`, and `self._pools` is
   keyed by id, so a name-based request is refused even under the wildcard.

## 4.5 Requirements

- **REQ-POLICY-001** — the operator's policy gates *pinning*. A pool the
  server chose is not the caller's choice, so the policy does not restrict
  it. A caller that supplies its own allowlist is bound by it everywhere.
- **REQ-POLICY-002** — both sides of the authorization test speak in
  canonical pool ids, so a name-based request matches a name-based policy.
- **REQ-POLICY-003** — the shipped policy names the deployment's pinnable
  pools rather than the wildcard.

## 5. Phases

### Phase 1 — Resolve pool references canonically

Add `PoolManager._canonical_pool_ref` and use it in
`PoolManager._is_pool_in_allowlist`, so the reference under test is
resolved to the pool's id before it is compared with the allowlist.

**Integration Contract**

- Triggered from: `PoolManager._is_pool_in_allowlist`, on every
  authorization test.
- Returns to / updates: the authorization decision; nothing persistent.
- Demonstrable by: `tests/unit/pools/test_caller_pool_allowlist.py::
  test_a_name_request_matches_a_name_policy`.
- Rollback signal: an affinity dispatch that lands on the wrong pool.
- Observability added: none — the decision is already logged by
  `_route_by_affinity` (`affinity_not_in_allowlist`).
- Requirements: REQ-POLICY-002.

### Phase 2 — Separate the pin gate from the dispatch restriction

`PoolManager.route_task` derives two values from the one parameter: the pin
gate (the operator's policy, or a caller's own set) and the dispatch
restriction (`None` when the policy supplied it, the caller's own set
otherwise). The pinning paths — `_route_by_affinity`,
`_route_by_peer_affinity`, and the explicit-selection branch of
`_get_pool_for_working_directory` — take the pin gate; the dispatch paths —
the queueing re-rank, the GPU override, and the working-directory candidate
set — take the dispatch restriction.

A **refused** pin falls back through the dispatch restriction, not the pin
gate. A refusal discards the caller's choice; what replaces it is the
server's choice, and the server's choice is not a caller's choice. The
same rule applies to the queueing re-rank's defensive check, which now
applies to a pin that was *honoured* (`reason` in
`_HONORED_PIN_REASONS`) rather than to a fallback the server chose.

**Integration Contract**

- Triggered from: `PoolManager.route_task`, on every dispatch.
- Returns to / updates: the pool selection decision; the routing-decision
  audit record.
- Demonstrable by:
  `tests/unit/pools/test_caller_pool_allowlist.py::
  test_the_operator_policy_does_not_gate_server_chosen_routing`.
- Rollback signal: an ordinary dispatch that raises
  `RuntimeError: Queueing fallback would route to pool ... which is not in
  caller_pool_allowlist`.
- Observability added: the effective policy log line now distinguishes the
  pin gate from the dispatch restriction.
- Requirements: REQ-POLICY-001.

### Phase 3 — Narrow the shipped policy

`settings/mahavishnu.yaml` ships `["merge-review", "claude-pool"]` — the
two pools this deployment names in its own code and agent documentation.

**Integration Contract**

- Triggered from: the settings load at MCP server startup.
- Returns to / updates: `PoolConfig.caller_pool_allowlist`.
- Demonstrable by: `mahavishnu pool route --prompt "x" --selector affinity
  --pool-affinity merge-review` lands on the `merge-review` pool.
- Rollback signal: a dispatch naming a pool in the policy is refused.
- Observability added: the effective-policy log line names the pools.
- Requirements: REQ-POLICY-003.

### Phase 4 — Correct the documentation

`docs/pools/POOL_ARCHITECTURE.md` and the ADR describe the policy as a
dispatch restriction. Correct them to describe a pin gate.

**Integration Contract**

- Triggered from: a reader following the policy documentation.
- Returns to / updates: the docs.
- Demonstrable by: no doc says the policy restricts ordinary routing.
- Rollback signal: n/a — prose.
- Observability added: n/a — prose.
- Requirements: REQ-POLICY-001.

## 6. Verification

1. `pytest tests/unit/pools/ tests/unit/test_pool_manager.py -q`
1. `pytest tests/unit/test_mcp/ tests/unit/test_mcp_pool_tools.py -q`
1. `ty check` on every touched file.
1. A live dispatch naming a registered pool lands on that pool.
1. `python scripts/audit_requirements.py` exits 0.
1. `python scripts/audit_orphans.py` exits 0.

### Results (2026-11-16)

- 892 passed across every unit test file that touches `route_task` or the
  allowlist. One pre-existing failure,
  `tests/unit/pools/test_pool_registry.py::test_list_pool_types_contains_expected_entries`
  — order-dependent (`runpod_public` is not imported by
  `_load_all_pool_types()`), fails identically in isolation, and is
  untouched by this change.
- The integration pool suite has 2 failures
  (`TestSessionBuddyDelegation`), both from a Session-Buddy MCP server that
  refuses `create_pool`. A pristine-HEAD worktree fails 10 of that file's
  tests — a superset — so these are environmental.
- `ty check` on the touched files: clean. The 9 diagnostics it reports are
  on lines this change does not touch, and the test-file ratchet does not
  gate them.
- `ruff check` / `ruff format --check`: clean on the touched files. The one
  `S110` is byte-identical at HEAD and fires 17 times across the untouched
  tests tree.
- `scripts/audit_requirements.py`: Orphans 0, Phantoms 0, exit 0.
- `scripts/audit_orphans.py`: exit 0.
