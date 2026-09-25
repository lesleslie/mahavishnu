---
status: deferred
date: 2026-09-25
updated: 2026-09-25
supersedes: (none)
related: docs/decisions/2026-08-29-settle-vs-langgraph.md (predecessor); .claude/plans/nifty-gliding-stallman.md v3 (planning context); docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md (same-day audit refresh)
---

# 2026-09-25 — Re-evaluation of LangGraph as a Bodai engine adapter

# DO NOT IMPLEMENT

> **STOP — implementation is OUT OF SCOPE for this decision record.**
> This ADR documents the decision to **NOT** implement LangGraph now.
> Future agents / sub-plans MUST:
> 1. Read this ADR in full before any `mahavishnu/adapters/langgraph_adapter.py`
>    or `mahavishnu/adapters/langgraph_*` work.
> 2. Confirm with the user (per `feedback-bodai-push-is-user-controlled.md`)
>    before adding the `langgraph`/`langchain-core` dependency.
> 3. Open a separate plan that scopes the multi-node Bodai workflow
>    (clone-refactor DAG, parallel-bindings settle, etc.) explicitly.
>
> **WARNING**: This banner is the first 5 lines of the file per Plan v3
> Phase 6 Integration Contract. Removing or hiding it is a wire-up-
> contract violation.

## Status

Deferred, 2026-09-25. This is a research artifact only.

## Context

The predecessor ADR `docs/decisions/2026-08-29-settle-vs-langgraph.md`
explicitly rejected LangGraph as a primitive for the **Settle** machinery
on two grounds:

1. **Heavyweight dependency.** LangGraph pulls in `langchain-core`,
   `langgraph`, `pydantic` v2, async runtime support — a 5-10x cost
   increase for one feature surface.
2. **Second persistence substrate alongside Dhara.** LangGraph's
   ``MemorySaver`` / ``PostgresSaver`` introduce a checkpoint storage
   layer parallel to Dhara, which the Bodai control plane already uses
   for state.

This re-evaluation is triggered by the user signal this conversation
turn: **Dhara is no longer part of the Bodai core components or
ecosystem.** That changes the architectural context materially — the
"second persistence substrate" objection is **obsolete**.

## What's still true (and what changed)

**Still applicable:**

- **Heavyweight dependency** is still a real cost. LangGraph + the
  LangChain dependency tree is genuinely heavy for one feature. Any
  future Mahavishnu plan that adds LangGraph MUST justify the import
  cost relative to the workflow complexity it serves.
- **State-machine overkill for Settle.** The Settle primitive in
  ``mahavishnu/settle/`` is a hand-rolled 5-state / 4-transition machine
  in ~300 lines. LangGraph's graph primitives don't add value at
  that scale — the predecessor ADR's "overkill" objection survives.
- **Persistence substrate is still an open question** _(strengthened
  2026-09-25)_. The same-day pool/worker MCP audit
  (`docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md`,
  commit `ca1cad18`) confirmed that `dispatch_to_pool(async_callback=True)`
  returns a `workflow_id` immediately but the corresponding
  `workflow_result` lookup returns `not_found` — root cause most likely
  is the absence of a working Dhara (or alternative) persistence layer
  for `workflow-results/{workflow_id}/`. Any LangGraph adapter would
  face the same substrate gap. Prerequisite #2 below is therefore more
  load-bearing than it appeared at Phase 6 ship time.

**No longer applicable:**

- **Second persistence substrate.** With Dhara out of the Bodai core,
  Mahavishnu has no canonical persistence substrate of its own.
  LangGraph's `PostgresSaver` (or any future storage layer) would be
  the *first* substrate in a renewed architecture, not a duplicate.
  This objection is void.

## What's attractive about LangGraph NOW (the new case)

LangGraph's graph primitives — nodes, edges, conditional branches,
dynamic fan-out — become attractive for Bodai workflows that the
predecessor ADR identified as out-of-Settle-scope:

- **Clone-refactor DAG** (`mahavishnu/workflows/clone_refactor_workflow.py`).
  Multi-node routing with conditional branches on capability state,
  test outcome, and gate metrics. Hand-rolled versions of this are
  the canonical example of "graph-shaped problem in sequence-shaped
  infrastructure" — the same pattern the predecessor ADR warned
  against for Settle, but at a different scale.
- **Parallel-bindings settle.** If Settle grows past its current
  5-state shape (e.g. retry-with-feedback, fan-out per binding), the
  graph primitives would amortize across N bindings. The predecessor
  ADR explicitly noted this as a future consideration.
- **Multi-engine fan-out.** When a task legitimately needs
  LlamaIndex + Prefect + Agno coordination with state, LangGraph's
  conditional edge semantics are a clean fit. Hand-rolled equivalents
  (per-engine conditional checks) become brittle as engine count
  grows.

## When NOT to implement

LangGraph is **not** attractive when:

- The task is single-node (one dispatch, one result) — that's
  Mahavishnu's existing `pool_manager.route_task`.
- The state machine is small (≤ 5 states, ≤ 4 transitions) — that's
  Settle's hand-rolled table.
- The persistence substrate already lives elsewhere — currently Bodai
  storage is the open question (see §Followups).

## What's required before any implementation lands

For any future plan that wants to add LangGraph, the following must
hold (none currently do):

1. **User approval on dependency bump.** Per
   `feedback-mcp-common-version-bump-is-user.md` (the spirit), any
   new Python dep with a non-trivial transitive closure requires
   explicit user approval. LangGraph + LangChain is a multi-package
   addition.
2. **Persistence substrate decision.** With Dhara gone, the plan must
   specify what storage layer backs `PostgresSaver` (or alternative).
   Without a chosen substrate, the implementation has no durability.
3. **Scope definition.** Per Plan v3 §6 Integration Contract, this
   ADR explicitly defers implementation. A separate plan must scope
   which workflow(s) the LangGraph adapter serves — likely the clone-
   refactor DAG as the first adopter.
4. **Test parity.** The new adapter must match existing adapter
   conventions (Prefect, LlamaIndex, Agno are all in production).
   Specifically: `tests/unit/test_hatchet_adapter.py` style — model
   router, quota attribution via `coerce_caller_kind`, audit-trail
   storage, Integration Contract from the wire-up-contract policy.

## Consequences of NOT implementing

- Settle continues to use its hand-rolled state machine (300 lines).
- Workflows requiring graph semantics are built by hand or not at all.
- The Bodai adoption of LangGraph is deferred to v-next (post-Cracker
  pub, or any future major-version spike).

## Consequences of implementing (when approved)

- New dependency footprint: `langgraph`, `langchain-core`, transitive
  ~10-30 packages.
- A storage-substrate commitment for `PostgresSaver`-style
  checkpointing.
- An adapter file at `mahavishnu/adapters/langgraph_adapter.py` plus
  registration in `adapters/__init__.py`.
- Replacement (not addition) of certain workflow primitives where
  graph semantics are a cleaner fit. This is a per-workflow decision.

## Follow-ups

- **Phase 6 of this plan exists.** We refresh this ADR when the
  user signals interest; for now, this is the document of record.
- **Existing 2026-08-29 ADR is NOT invalidated.** Its Settle-specific
  reasoning (overkill, dependency cost) remains true. This ADR ADDS the
  context that the *second-substrate* objection is now obsolete; it
  does not retract the Settle rejection.
- **Cross-link from the predecessor ADR is on the file system
  (see References).** Future reviewers reading either ADR see both.

## New evidence since Phase 6 ship (same-day refresh, 2026-09-25)

This section captures the §10 follow-up batch from Plan v3 that landed
in the same conversation turn as the Phase 6 ADR. None of these
findings flip the decision (status remains **deferred**); they
strengthen the prerequisites and reduce the future work scope.

- **Doc-drift cleanup** (commit `dddceca9`): 10 doc references to
  `mahavishnu/workers/task_router.py` migrated to
  `mahavishnu/core/model_routing.py`. Plus 4 bonus cleanup sites
  (`SHEPHERD_BACKEND.md`, two `feature-tracking/*.md` files now
  RETIRED, `mahavishnu/pools/mahavishnu_pool.py` ASCII diagram). The
  canonical model-routing path is now consistent across docs, code,
  and CLI references — **a LangGraph adapter has a clean
  integration target, not a documentation migration to also
  perform.**

- **Worker_* MCP tools audit** (commit `ca1cad18`,
  `docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md`): all
  18 `worker_*` tools are LIVE with real dual-path implementations
  (durable-manager + legacy fallback) and dedicated test coverage.
  Plan §10 #2 estimated "9 registered"; actual count is **18** (9 in
  `worker_tools.py` + 9 in `worker_contract_tools.py`). There is no
  aspirational surface to worry about — **a LangGraph adapter would
  not need to "work around" half-built MCP tooling.**

- **`dispatch_to_pool` env-failure** (per memory
  `pool-dispatch-async-default.md`, confirmed by audit commit
  `ca1cad18`): async-callback path returns `workflow_id` immediately
  but the corresponding `workflow_result` returns `not_found`. Root
  cause is most likely Dhara (or alternative) persistence substrate
  not configured for `workflow-results/{workflow_id}/`. **This is the
  same substrate gap any LangGraph `PostgresSaver` (or equivalent)
  would face — prerequisite #2 below is more load-bearing than at
  Phase 6 ship time.**

- **Phase 4.5b legacy worker deletions complete** (commit `7d68bff2`,
  `docs/decisions/2026-09-24-legacy-worker-deprecation.md`): only
  `shepherd_backend.py` remains as an isolated-worker backend. **A
  LangGraph adapter has less breakable surface area to integrate
  with**, but it does not change the cost calculus on its own.

- **Open work parked** (from audit commit `ca1cad18`):
  - `mahavishnu_pool.py` §10 #5 rewrite (WorkerManager → route_task
    shape) — substantial refactor; needs its own plan.
  - `workers/cloud_worker.py` retirement — now a thin wrapper post
    Phase 3b; decision needed (keep as OpenAI-compatible HTTP client
    or retire).
  - `workers/__init__.py` factory-function collapse — cosmetic.

  None of these affect the LangGraph calculus. They are flagged here
  so a future LangGraph plan can sequence around them.

## References

- `docs/decisions/2026-08-29-settle-vs-langgraph.md` — predecessor ADR,
  Settle-specific rejection, still in force.
- `.claude/plans/nifty-gliding-stallman.md` v3 Phase 6 — planning
  context for this refresh.
- `mahavishnu/settle/state_machine.py` — the hand-rolled primitive
  LangGraph could in principle replace, but doesn't yet.
- `mahavishnu/workflows/clone_refactor_workflow.py` — the canonical
  workflow that would benefit most from graph primitives.
- `memories/bodai-auth-standardization.md` (cross-reference) — the
  Bodai auth substrate question LangGraph adapters would need to
  integrate with.
- `feedback-bodai-push-is-user-controlled.md`, `feedback-mcp-common-
  version-bump-is-user.md` — guardrails on adding dependencies and
  publishing without user consent.
- **Same-day refinement (2026-09-25):**
  - `commit dddceca9` — doc-drift cleanup (10 task_router refs +
    bonus Phase 4.5b cleanup + `mahavishnu_pool.py` ASCII fix)
  - `commit ca1cad18` — pool/worker MCP audit
    (`docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md`):
    18 worker_* tools LIVE; dispatch_to_pool env-failure
    documented; §10 #5 rewrite deferred to separate plan
  - `commit 7d68bff2` — Phase 4.5b legacy worker deletions
    (`docs/decisions/2026-09-24-legacy-worker-deprecation.md`):
    reduces breakable surface area for any future LangGraph
    integration
  - `memory/pool-dispatch-async-default.md` — env-failure root
    cause (Dhara substrate missing for async workflow_results); the
    same gap LangGraph adapters would face
  - `memory/mahavishnu-dispatch-prompt-mangling.md` — `sh -lc`
    wrapper bug, motivates direct `route_task` calls (relevant
    if LangGraph adapter design mirrors `dispatch_to_pool`'s path)
