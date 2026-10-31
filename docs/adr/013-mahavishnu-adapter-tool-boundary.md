---
status: complete
role: superseded
kind: decision
date: 2026-07-16
last_reviewed: 2026-10-12
superseded_by: docs/plans/.archive/2026-10-12-adapter-registry-consolidation-to-oneiric.md
blocks_on: []
decision_date: 2026-06-03
topic: adapter-tool-boundary
---

# ADR 013: Adapter Tool Boundary Between Mahavishnu and the Adapter Registry

## Status

<!-- legacy status: **Proposed** — see YAML frontmatter -->

**Accepted** on 2026-09-09 (ratified retroactively after SLA expiry; rationale below).

The 2026-06-03 proposal recommended **Option B** ("document the boundary, keep both"). The maintainer follow-up SLA was 2026-06-17; no objection was raised during that window or afterwards. The de facto boundary has held in practice for the intervening three months: the adapter-registry MCP tool namespace is used for catalog/state queries (per the agent catalog and ADR-015 v4 storage story), while `mcp__mahavishnu__adapter_list` / `adapter_metadata` continue to serve orchestration-time queries against the live `HybridAdapterRegistry` in-process. The four Open Questions in the proposal are noted as low-impact:

1. **External consumers** — none surfaced; the only known callers are internal CLI, compatibility contract checks, and the agent catalog.
2. **Deprecation timeline** — no deprecation needed under Option B (both surfaces remain).
3. **Field reconciliation** — deferred (deliberately disjoint shapes preserve intent).
4. **`get_adapter_health` parallel** — same boundary applies; treated consistently.

This ratification does not change code or tool versions.

**Date:** 2026-06-03

## Context

During the recent agent catalog review, three `.claude/agents/` files were updated to point at the adapter-registry MCP tools as the canonical surface for adapter lookups:

- `.claude/agents/oneiric-specialist.md` (line 3) now cites `mcp__oneiric__oneiric_list_adapters` and `mcp__oneiric__oneiric_get_adapter` as the adapter catalog/lookup entry points.
- `.claude/agents/database-operations-specialist.md` and `.claude/agents/architecture-council.md` cite other tools (`mcp__mahavishnu__mahavishnu_kv_put`, `mcp__mahavishnu__aggregate_patterns`) consistent with treating the durable key-value store as the curator of persistent state.

However, Mahavishnu's own MCP server still exposes its own `adapter_list` and `adapter_metadata` tools, registered in `mahavishnu/mcp/tools/adapter_registry_tools.py` and version-pinned in `mahavishnu/mcp/tool_versions.py`. Two services now answer overlapping questions, creating drift risk: contributors may pick one or the other based on which they happened to remember, and the two return values can diverge over time without anyone noticing.

This ADR proposes a boundary for the maintainers to ratify. It does not unilaterally remove or deprecate anything.

### What each side actually does

**Mahavishnu side** — `mahavishnu/mcp/tools/adapter_registry_tools.py`:

- `adapter_list(domain, capabilities, healthy_only)` at line 32. Synchronous read from `HybridAdapterRegistry._metadata` (in-memory dict, `RLock`-protected). Returns the orchestrator's live view: registered name, domain, category, provider, capabilities, priority, source, health status, and whether an instance is hydrated. Filters by `domain`, by required `capabilities`, and by `healthy_only`.
- `adapter_metadata(adapter_name)` at line 214. Synchronous read of a single `AdapterMetadata` from the same in-memory dict; returns `metadata.to_dict()`.
- Both are registered at version `1.0.0` in `mahavishnu/mcp/tool_versions.py` (lines 151–152).
- Backed by `HybridAdapterRegistry.list_adapters` at `mahavishnu/core/adapter_registry.py:482` and `HybridAdapterRegistry.get_metadata` at line 470 — both documented "golden path" entry points.

**Adapter-registry side** — the Oneiric MCP server (`oneiric/oneiric/mcp/server.py`):

- `oneiric_get_adapter(domain, key, provider, version)` at line 866. Async, delegates to the registry's `get_adapter_async` against the durable `AsyncAdapterRegistry`. Returns the registry record for a `(domain, key, provider, version)` tuple. Provider and version are optional; the registry resolves to "first match" / "latest".
- `oneiric_list_adapters(domain, category)` at line 899. Async, delegates to `list_adapters_async` against `AsyncAdapterRegistry`. Filters by `domain` and `category` only.
- The adapter-registry tool group also owns `oneiric_list_adapter_versions`, `oneiric_validate_adapter`, and `oneiric_get_adapter_health`, so it already covers the "durable registry" surface area.

### Why this matters

The two tools answer subtly different questions with subtly different signatures and return shapes:

| Aspect | Mahavishnu | Adapter registry |
|--------|-----------|-------|
| Source of truth | Live `HybridAdapterRegistry` in the running orchestrator | `AsyncAdapterRegistry` backed by the durable registry store |
| Latency | Sync, in-memory, sub-millisecond | Async network call |
| Filter axes | `domain`, `capabilities`, `healthy_only` | `domain`, `category` |
| Lookup key | `adapter_name` (single string) | `(domain, key, provider, version)` tuple |
| Includes hydration state | Yes (`has_instance`, `healthy`) | No |
| Includes version history | No | Yes (separate `oneiric_list_adapter_versions` tool) |
| Tool registration | `mahavishnu/mcp/tools/adapter_registry_tools.py` | `oneiric/oneiric/mcp/server.py:866,899` |

This means a caller cannot blindly substitute one for the other — and the agent files now imply that the adapter-registry surface is canonical. Without an explicit ADR, the Mahavishnu surface will either drift, be silently bypassed, or surprise someone the first time they need a feature only the other side has.

## Decision Drivers

- **Single source of truth.** Two tools answering the same conceptual question is a maintenance hazard.
- **Performance.** Orchestration-time decisions (routing, capability matching) happen on hot paths; an in-memory sync read is meaningfully faster than an async network round-trip to the adapter registry.
- **Backward compatibility.** The Mahavishnu tools are at version 1.0.0 in `tool_versions.py`; the consumer compatibility contract assumes they will not vanish without warning.
- **Cleanup hygiene.** Duplicate API surface accumulates if not actively pruned.
- **Filter semantics.** `healthy_only` and `capabilities`-based filtering are orchestrator concerns. `version` and `category`-based filtering are registry concerns. The two tools are *not* exact substitutes today.

## Options

### Option A — Deprecate Mahavishnu's, proxy to the adapter registry

Mahavishnu's `adapter_list` and `adapter_metadata` become thin pass-throughs that forward to `mcp__oneiric__oneiric_list_adapters` / `mcp__oneiric__oneiric_get_adapter`. The Mahavishnu-specific filter axes (`capabilities`, `healthy_only`, hydration state) are layered on top of the registry's response, or dropped.

- **Pros:** Single source of truth. Zero contributor confusion about which tool to use. Existing callers (CLI, contract checks) continue to work because the tool name does not change.
- **Cons:** Proxying adds an HTTP hop and an extra failure mode (what happens when the adapter registry is unreachable?). Hot-path orchestration code that uses these tools now pays network cost. The `has_instance` / `healthy` fields require a join against in-memory state, which means the "proxy" is not actually a thin pass-through.
- **Effort:** Medium — fallback semantics for registry-unavailable need to be designed, and the response shape needs reconciling.
- **Risk:** Medium — performance regression on the orchestration hot path; tighter runtime coupling between Mahavishnu and the adapter registry.

### Option B — Document the boundary, keep both

Keep both tools but write the boundary into `docs/mcp/MCP_TOOLS_SPECIFICATION.md` and the tool docstrings:

- **Mahavishnu's `adapter_list` / `adapter_metadata`** = orchestration-time queries against the live in-process registry. Use when you need the orchestrator's current view (which adapters are hydrated, which are healthy *right now*, capability-based filtering for routing decisions).

- **The adapter registry's `oneiric_list_adapters` / `oneiric_get_adapter`** = state queries against the durable registry. Use when you need the canonical record, version history, or any adapter that may not be hydrated in the current Mahavishnu process.

- **Pros:** Each tool keeps the shape it was designed for. No performance regression. No new failure modes. Honest about the fact that the two answer different questions.

- **Cons:** Contributors must learn the boundary. Future drift is still possible — nothing structurally prevents the two surfaces from growing incompatible fields. The agent files would also need a small note that `mcp__oneiric__oneiric_list_adapters` is for state, not for orchestration introspection.

- **Effort:** Low — docs + docstrings only.

- **Risk:** Low.

### Option C — Remove Mahavishnu's entirely, update internal callers

The most aggressive cleanup. Delete `adapter_list` and `adapter_metadata` from `mahavishnu/mcp/tools/adapter_registry_tools.py`, remove their version entries from `tool_versions.py`, and rewrite any internal Mahavishnu callers to either call the in-process `HybridAdapterRegistry` methods directly (for hot paths) or call the adapter-registry tools (for state queries).

- **Pros:** Zero duplication, zero future drift, smallest API surface.
- **Cons:** Breaking change — anything not under our control that calls the Mahavishnu MCP tools breaks. The CLI in `mahavishnu/_main_cli.py:170` (`adapter_list_cmd`) already calls the registry method directly, but `mahavishnu/core/compatibility.py:75,193,211` has an `adapter_metadata_contract` check that needs to be re-pointed or retired. Tests in `tests/unit/test_compatibility.py` would need updating. The `oneiric-specialist.md` already points at the adapter registry, so the agent side is fine — but any *user* of the Mahavishnu MCP server who memorized the old tool names is broken.
- **Effort:** Medium — code changes are small, but the deprecation cycle is the real cost.
- **Risk:** High for external consumers, low for internal correctness.

## Recommendation

**Option B** ("document the boundary, keep both") is the proposed default, with a path to Option C deferred to a later cleanup pass.

Rationale:

1. The two tools genuinely answer different questions today. Mahavishnu's surface is shaped around orchestration concerns (`capabilities`, `healthy_only`, `has_instance`, in-memory speed). The adapter-registry surface is shaped around registry concerns (`domain/key/provider/version`, `category`, version history). Forcing a merge means either losing fields or paying a network hop on the orchestration hot path.
1. The cost of Option B is one paragraph of docs and two tool docstrings.
1. Option C remains available if/when the maintainers decide the Mahavishnu surface has no remaining external consumers — at which point we can run a deprecation cycle through `DEPRECATED_TOOLS` in `tool_versions.py` (which already supports this pattern for `health_check_service`, `get_liveness`, etc.).

**This is a proposal.** The maintainers should ratify, modify, or reject it before any code changes land.

## Consequences

If Option B is adopted:

- Update `mahavishnu/mcp/tools/adapter_registry_tools.py` docstrings for `adapter_list` and `adapter_metadata` to state explicitly: "Orchestration-time view of the live in-process registry. For the durable registry record, use `mcp__oneiric__oneiric_list_adapters` / `mcp__oneiric__oneiric_get_adapter`."
- Add a "Boundary with the Adapter Registry" subsection to `docs/mcp/MCP_TOOLS_SPECIFICATION.md` (or wherever the adapter MCP tools are documented).
- Add a one-line note to `.claude/agents/oneiric-specialist.md` clarifying that `mcp__oneiric__*` is for catalog/state queries — for "what's actually running in this Mahavishnu process right now", call the Mahavishnu side.
- No code changes to the tool implementations.
- No version bump in `tool_versions.py`.
- No changes to the CLI (`_main_cli.py:170`) or compatibility checks (`core/compatibility.py:75`), both of which already call the in-process registry method, not the MCP tool.

If Option A is later adopted (proxying):

- The Mahavishnu tools keep their names but their bodies become adapter-registry calls plus an in-memory join for `has_instance` / `healthy`. Tool version in `tool_versions.py` bumps to `2.0.0` (behavior change). Add a fallback path for registry-unavailable that returns a degraded response with `success=False, error="adapter registry unreachable"`.

If Option C is later adopted (remove):

- Remove the `@mcp.tool() async def adapter_list` and `adapter_metadata` blocks from `mahavishnu/mcp/tools/adapter_registry_tools.py`.
- Remove `"adapter_list"` and `"adapter_metadata"` from `TOOL_VERSIONS` in `tool_versions.py:151-152`.
- Add both to `DEPRECATED_TOOLS` in the same file with replacements pointing at the adapter-registry tools.
- Re-point or remove `_check_adapter_metadata_contract` in `mahavishnu/core/compatibility.py`.
- Update tests in `tests/unit/test_compatibility.py`, `tests/unit/test_main_cli.py`, and anything else surfaced by `grep -rn adapter_metadata mahavishnu/ tests/`.

## Open Questions

1. **External consumers.** Are there any non-agent callers of `mcp__mahavishnu__adapter_metadata` or `mcp__mahavishnu__adapter_list` that we have not yet found? The search above covered `mahavishnu/`, `tests/`, `docs/`, and `.claude/agents/`. External MCP clients (other Bodai components, ad-hoc scripts, downstream tooling) are not visible from this repo.
1. **Deprecation timeline for Option A or C.** If the maintainers want to converge on a single tool eventually, what's the deprecation window? The existing `DEPRECATED_TOOLS` mechanism in `tool_versions.py` is the natural lever, but no policy is documented for how long a tool stays in that dict before being removed.
1. **Field reconciliation.** Even under Option B, should the adapter registry's `list_adapters` response grow a `healthy` field, or Mahavishnu's grow a `version` field, to make them easier to compose? Or do we deliberately keep them disjoint to discourage substitution?
1. **`get_adapter_health` parallel.** The adapter registry also has its own `oneiric_get_adapter_health` (`oneiric/oneiric/mcp/server.py:1004`), which overlaps with Mahavishnu's `adapter_health` tool. The same boundary question applies; whatever this ADR decides should probably apply there too. Out of scope for this ADR but worth flagging.

## Decision Review

**Status: Proposed, awaiting maintainer review.**

- **Reviewer:** the project maintainer(s) of Mahavishnu.
- **SLA:** maintainer follow-up within 14 days of the proposal date. If there is no objection, the ADR moves to **Accepted**; if objections are raised, the proposal is revised or moved to **Rejected** with rationale recorded in the *Open Questions* section above.
- **Action requested:** maintainer to address the four *Open Questions* (external consumers, deprecation timeline, field reconciliation, `get_adapter_health` parallel) before ratifying this ADR.
- **This section is a process artifact, not a re-litigation of the decision.** Do not re-debate the options here — use the *Open Questions* list above for that.

## Amendment (2026-09-14)

The serverless-readiness plan (`docs/plans/.archive/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`, active status) extends the storage substrate with Oneiric
adapter-based selection. ADR-013's "Option B keeps both surfaces,
each answers a different question" framing is preserved, but the
underlying persistence substrate assumed by Option B (Mahavishnu's
in-process `HybridAdapterRegistry` + the durable
`AsyncAdapterRegistry`) is now wrapped by Oneiric's
`adapters.registry` / `adapters.storage` / `adapters.queue` layers.

**Specifically:**
- The cross-component import direction (`Mahavishnu → Oneiric` for
  state) is preserved. Option C (remove Mahavishnu's surface) is
  not chosen by this amendment.
- The "boundary" now sits between Mahavishnu and Oneiric (which
  owns the durable registry state), not directly between
  Mahavishnu and the adapter registry.
- A future amendment will document the Oneiric-mediated path in a
  follow-up ADR; ADR-013 is left as-is for the audit trail.

**No code changes are required by this amendment.** The amendment
extends the decision's *context* without changing the *decision*.
The two surfaces (Mahavishnu's `adapter_list` / `adapter_metadata`
+ the registry's `oneiric_list_adapters` / `oneiric_get_adapter`)
continue to coexist under Option B. The Oneiric layer is additive
infrastructure, not a replacement.

See ADR 017 (proposed, `docs/adr/017-oneiric-shared-persistence-substrate.md`)
for the cross-substrate persistence architecture this amendment
anticipates.
