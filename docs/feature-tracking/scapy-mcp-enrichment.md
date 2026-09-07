---
name: scapy-mcp-enrichment
status: built
date: 2026-09-06
last_reviewed: 2026-09-06
owner: mahavishnu-orchestrator
role: canonical
---

# Feature: scapy-mcp-enrichment

**Owner:** mahavishnu-orchestrator
**Created:** 2026-09-06
**Last updated:** 2026-09-06
**Repo(s):** `/Users/les/Projects/flowscape/`, `/Users/les/Projects/scapy-mcp/`, `/Users/les/Projects/mahavishnu/`

## State — pick one

- [x] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

> Filed per `wire-up-contract.md` after L6 B2 finding in `docs/adr/0016-multi-agent-review.md`. The Flowscape plan (`docs/superpowers/plans/2026-08-31-flowscape.md` rev 5) ships the `EnrichmentRegistry` plumbing but with `enrichment.scapy_mcp_enabled = false` default, so the production code path does not exercise the hook. Per the contract, this is `built, not wired` — adoption requires flipping the default AND proving an end-to-end smoke check.

## Wiring checklist

- [ ] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [x] Trigger path identified (who calls this, and from where)
- [ ] Returns / state updates land in expected destination
- [ ] End-to-end smoke check documented (one command that proves it works)
- [ ] Observability hook in place (log/metric/trace)
- [ ] Rollback signal defined

## Built (yes/no)

yes — code merged to `docs/superpowers/plans/2026-08-31-flowscape.md` rev 5 and `docs/superpowers/specs/2026-08-31-flowscape-design.md` rev 3 (2026-09-06). Hook scaffolding specified; scapy-mcp server work pending in `docs/superpowers/plans/2026-09-06-scapy-mcp.md`.

## Wired (yes/no)

no — `enrichment.scapy_mcp_enabled = false` default means no production code path exercises the hook.

## Trigger path

`src/flowscape/graph.py:derive_snapshot()` calls `EnrichmentRegistry.default().enrich_edge(edge)` per `FlowEdge` at the 10Hz publish cadence (plan line 197-198, plan line 430). `src/flowscape/heuristics.py:BeaconingDetector.__init__` / `PortScanDetector.__init__` accept `EnrichmentHook | None` via DI for confidence boost (plan line 832). Both call sites default to no-op when `scapy_mcp_enabled = false`.

## Integration point

scapy-mcp enrichment metadata merges into the `FlowEdge` proto published over the Swift↔Python `data.sock` (SOCK_SEQPACKET, spec lines 234-249). The no-payload guarantee (spec line 29) is preserved because the hook receives `(FlowEdge, HeuristicEvent)` metadata, never packet bytes. **Note:** `GraphEdge` and `HeuristicEvent` types referenced by ADR 0016 do not exist in `proto/flowscape.proto` today (L2 B1 finding) — proto edit is a v2 follow-up.

## End-to-end check

> **Cannot be named until v2 fixes ship.** Required pieces (per L5 BLOCKERs):
> 1. Add 4 mandatory feed observability metrics to `EnrichmentRegistry` (`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`)
> 2. Specify `flowscape doctor --enrichment` output envelope
> 3. Define SLO targets (latency p99, availability, error rate)
> 4. Fix the 100ms × 5000-edges-per-tick math (batch per-tick OR document drop policy)
>
> Once those are in place, the canonical end-to-end check will be: a FastMCP in-memory mock scapy-mcp server + a Flowscape integration test asserting `enrich_edge()` round-trips and the feed-state signals increment correctly.

## Blocker

Five BLOCKERs from the 6-agent review of ADR 0016 must close before state transitions to `wired`. Four are deferred to a v2 revision (GDPR reframe, timeout batching math, phantom APIs/types, observability/SLO/rollback); one is closed by this file (built-not-wired declaration). The scapy-mcp server itself (`docs/superpowers/plans/2026-09-06-scapy-mcp.md`) is also not yet built — it's a sibling dependency on the critical path.

## Next action

**Phase 0a (immediate, prerequisite for `wired`)**: Plan 0a Task 1 from `docs/superpowers/plans/2026-09-06-registry-manifest-migration.md` — register `scapy-mcp` in `settings/ecosystem.yaml`. Unblocks archive-org-mcp Tasks 5+, medium-mcp, and scapy-mcp Phase 0a.

**Phase 1 (after Plan 0a + scapy-mcp Task 1 lands, owner: mahavishnu-orchestrator, target: 2026-09-13)**: Ship the 5 BLOCKERs in `docs/adr/0016-multi-agent-review.md` §"Recommended path forward" items 3-7 (feed observability, SLOs, doctor envelope, timeout batching, registry realignment). Re-run the integration test as the canonical "wired" smoke check.

## Related

- Plan: `docs/superpowers/plans/2026-08-31-flowscape.md` (revision 5, 2026-09-06)
- Spec: `docs/superpowers/specs/2026-08-31-flowscape-design.md` (revision 3, 2026-09-06)
- ADR: `docs/adr/0016-scapy-mcp-integration.md` (companion review at `docs/adr/0016-multi-agent-review.md`)
- Sibling plans: `docs/superpowers/plans/2026-09-06-scapy-mcp.md`, `docs/superpowers/plans/2026-09-06-registry-manifest-migration.md`, `docs/superpowers/plans/2026-09-06-port-bodai-reconciliation.md`
- Precedent: `docs/adr/0015-multi-agent-review.md` (multi-agent review pattern)
- Policy: `.claude/decisions/wire-up-contract.md` (built/wired/adopted states)
- Policy: `.claude/decisions/mcp-backend-wiring-discipline.md` (§3 feed observability requirements)

## How to save to Session-Buddy

After completing this file, persist a one-line summary to Session-Buddy
for cross-session retrieval by calling the Session-Buddy MCP tool
`store_reflection` with the following shape (replace the `<…>` values
from the fields above):

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature scapy-mcp-enrichment: state=built, "
        "built=yes, wired=no, "
        "blocker=5 BLOCKERs from ADR 0016 6-agent review must close before wired (feed observability, SLOs, doctor envelope, timeout batching, registry realignment), "
        "next=ship Plan 0a Task 1 (registry migration), then close BLOCKERs in 0016-multi-agent-review.md §Path Forward items 3-7 by 2026-09-13"
    ),
    tags=["feature-tracking", "scapy-mcp-enrichment", "wire-up-state", "built-not-wired"],
)
```

That call returns a reflection ID; paste that ID into the section below
so the long-form record and the searchable reflection stay linked.

## Session-Buddy

- Reflection ID: \<returned by store_reflection, e.g. "r_abc123…">
- Saved at: \<ISO timestamp from the call's response>
