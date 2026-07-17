---
status: complete
role: historical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: convergence-control-plane
---

# Plan Coherence Review

**Plan**: `docs/plans/2026-05-23-bodai-routing-feedback-loop-v3.md`
**Reviewer**: general | plan-coherence-review
**Date**: 2026-05-23

______________________________________________________________________

## Summary

The plan is well-structured and the v3 fixes (pgvector backend strategy, env-var-driven detection, serverless story) are solid improvements over v2. However, three coherence issues prevent it from being implementation-ready as written.

______________________________________________________________________

## Issue 1 — Phase Ordering: Phase 2 is a prerequisite for Phase 4, but they're presented as parallelizable

**Severity**: Medium

The plan states:

> "Phase 3 and Phase 4 are largely independent and can proceed in parallel once Phase 2 is done."

But Phase 4 (`mahavishnu/pools/routing_fitness.py`) calls `query_local_traces` on Mahavishnu — which is added in Phase 2.3. Phase 4 also wires Dhara's component endpoint registry (Phase 4.3), which Akosha populates via the MCP client (Phase 2.1). Phase 4 cannot run before Phase 2.

**Fix**: Clarify that Phase 4 depends on Phase 2 being complete, not just Phase 1. Reorder the phases so the dependency is explicit:

```
Phase 1 — Storage Backend Foundation
Phase 2 — MCP Client & Trace Query  (query_local_traces on all components)
Phase 3 — Fitness Analytics (Akosha)   [can run after Phase 2]
Phase 4 — Routing Integration (Mahavishnu)  [requires Phase 2 complete]
Phase 5 — Integration & Polish
```

______________________________________________________________________

## Issue 2 — Component Endpoint Self-Registration is Missing

**Severity**: High

Phase 2.1 builds `Akosha/mcp/client.py` to poll component endpoints. Phase 4.3 wires Dhara's component endpoint registry. But **no phase covers how each component learns and registers its own URL to Dhara**.

Akosha needs to know Mahavishnu's MCP URL, Mahavishnu's URL, Session-Buddy's URL, etc. to poll them. The plan says endpoints are stored in Dhara as `component_endpoint/{component_name}` → URL, but:

- Who writes those keys? Each component should register on startup.
- How does Akosha discover new components (not just the initial set)?
- What happens when a component's URL changes?

**Fix**: Add a Phase 0 (implicit but must be explicit) or a sub-step in Phase 2: "Each Bodai component registers its own MCP endpoint URL to Dhara on startup via a `register_component_endpoint(url)` internal call." This could use the existing Dhara MCP tools.

______________________________________________________________________

## Issue 3 — Standalone Operation Matrix Missing Hybrid Deployment Scenario

**Severity**: Low-Medium

The matrix covers "single component alone (local dev)", "single component alone (deployed)", and all-chain combinations. But it misses the realistic serverless migration scenario:

**Scenario**: Akosha deployed with pgvector (serverless), Mahavishnu still local with `:memory:` DuckDB.

In this hybrid state:

- Akosha polls Mahavishnu's `query_local_traces` → works, returns local traces
- Akosha writes fitness signals to Dhara (pgvector) → works
- Mahavishnu reads from Dhara → works, gets fitness signals
- **But**: The "shared pgvector hot store" story from the Architecture section is misleading — Akosha's hot store and Mahavishnu's OtelIngester are writing to *different* backends (Akosha pgvector vs Mahavishnu :memory:). The matrix row "Akosha + Dhara | Buffers in-memory. No trace source → idles." is incorrect for this scenario.

**Fix**: Add a row to the Standalone Operation Matrix:

| Akosha (pgvector/deployed) + Mahavishnu (local/DuckDB) | Akosha polls Mahavishnu, gets traces. Mahavishnu writes locally only. | Limited trace set; fitness signals biased toward Akosha's history |
|---|---|---|

______________________________________________________________________

## Additional Notes

### "What This Plan Does NOT Cover" items are correctly out of scope

- Redis L2 cache: already works, no change needed ✓
- Dhara cloud storage: already compatible, separate concern ✓
- Horizontal scaling of Akosha: single-instance explicitly acknowledged ✓
- Real-time WebSocket selector switching: correctly deferred ✓
- Akosha cold/warm tier migration: unchanged ✓

No items in the NOT-cover list are dependencies that would block the plan.

### Phase 1 dependencies are correct

Phase 1 (storage backend) does not need to precede Phase 2 in terms of code — the MCP client and `query_local_traces` work with any backend. But the **deployment** story requires Phase 1 env vars to be set before serverless deployment. This should be noted: Phase 1 env vars must be configured before Phase 5 (end-to-end serverless test).

### Fitness signal TTL self-healing is correctly scoped

The 2× window TTL for signals is an internal mechanism, not a plan requirement. This is implementation detail — correctly in the NOT-cover zone or at least not a phase dependency.

______________________________________________________________________

## Verdict

**Actionable with fixes above.** The plan is close to implementation-ready. Issue 2 (missing endpoint self-registration) is the most critical — without it, the feedback loop cannot bootstrap. Issues 1 and 3 are documentation/ordering issues that are straightforward to fix.
