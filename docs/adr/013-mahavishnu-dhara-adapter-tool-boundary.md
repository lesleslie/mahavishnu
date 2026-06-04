# ADR 013: Adapter Tool Boundary Between Mahavishnu and Dhara

## Status

**Proposed**

**Date:** 2026-06-03

## Context

During the recent agent catalog review, three `.claude/agents/` files were updated to point at Dhara's MCP tools as the canonical surface for adapter lookups:

- `.claude/agents/oneiric-specialist.md` (line 3) now cites `mcp__dhara__list_adapters` and `mcp__dhara__get_adapter` as the adapter catalog/lookup entry points.
- `.claude/agents/database-operations-specialist.md` and `.claude/agents/architecture-council.md` cite other Dhara tools (`mcp__dhara__put`, `mcp__dhara__aggregate_patterns`) consistent with treating Dhara as the curator of persistent state.

However, Mahavishnu's own MCP server still exposes its own `adapter_list` and `adapter_metadata` tools, registered in `mahavishnu/mcp/tools/adapter_registry_tools.py` and version-pinned in `mahavishnu/mcp/tool_versions.py`. Two services now answer overlapping questions, creating drift risk: contributors may pick one or the other based on which they happened to remember, and the two return values can diverge over time without anyone noticing.

This ADR proposes a boundary for the maintainers to ratify. It does not unilaterally remove or deprecate anything.

### What each side actually does

**Mahavishnu side** — `mahavishnu/mcp/tools/adapter_registry_tools.py`:

- `adapter_list(domain, capabilities, healthy_only)` at line 32. Synchronous read from `HybridAdapterRegistry._metadata` (in-memory dict, `RLock`-protected). Returns the orchestrator's live view: registered name, domain, category, provider, capabilities, priority, source, health status, and whether an instance is hydrated. Filters by `domain`, by required `capabilities`, and by `healthy_only`.
- `adapter_metadata(adapter_name)` at line 214. Synchronous read of a single `AdapterMetadata` from the same in-memory dict; returns `metadata.to_dict()`.
- Both are registered at version `1.0.0` in `mahavishnu/mcp/tool_versions.py` (lines 151–152).
- Backed by `HybridAdapterRegistry.list_adapters` at `mahavishnu/core/adapter_registry.py:482` and `HybridAdapterRegistry.get_metadata` at line 470 — both documented "golden path" entry points.

**Dhara side** — `dhara/dhara/mcp/server_core.py`:

- `get_adapter(domain, key, provider, version)` at line 561. Async, delegates to `get_adapter_async_impl` (in `dhara/dhara/mcp/adapter_tools.py:1099`) against `AsyncAdapterRegistry`. Returns the registry record for a `(domain, key, provider, version)` tuple. Provider and version are optional; the registry resolves to "first match" / "latest".
- `list_adapters(domain, category)` at line 590. Async, delegates to `list_adapters_async_impl` (`adapter_tools.py:1134`) against `AsyncAdapterRegistry`. Filters by `domain` and `category` only.
- Dhara also owns `list_adapter_versions`, `validate_adapter`, and `get_adapter_health` in the same tool group, so it already covers the "durable registry" surface area.

### Why this matters

The two tools answer subtly different questions with subtly different signatures and return shapes:

| Aspect | Mahavishnu | Dhara |
|--------|-----------|-------|
| Source of truth | Live `HybridAdapterRegistry` in the running orchestrator | `AsyncAdapterRegistry` backed by the durable Dhara store |
| Latency | Sync, in-memory, sub-millisecond | Async network call |
| Filter axes | `domain`, `capabilities`, `healthy_only` | `domain`, `category` |
| Lookup key | `adapter_name` (single string) | `(domain, key, provider, version)` tuple |
| Includes hydration state | Yes (`has_instance`, `healthy`) | No |
| Includes version history | No | Yes (separate `list_adapter_versions` tool) |
| Tool registration | `mahavishnu/mcp/tools/adapter_registry_tools.py` | `dhara/mcp/server_core.py:561,590` |

This means a caller cannot blindly substitute one for the other — and the agent files now imply that the Dhara surface is canonical. Without an explicit ADR, the Mahavishnu surface will either drift, be silently bypassed, or surprise someone the first time they need a feature only the other side has.

## Decision Drivers

- **Single source of truth.** Two tools answering the same conceptual question is a maintenance hazard.
- **Performance.** Orchestration-time decisions (routing, capability matching) happen on hot paths; an in-memory sync read is meaningfully faster than an async network round-trip to Dhara.
- **Backward compatibility.** The Mahavishnu tools are at version 1.0.0 in `tool_versions.py`; the consumer compatibility contract assumes they will not vanish without warning.
- **Cleanup hygiene.** Duplicate API surface accumulates if not actively pruned.
- **Filter semantics.** `healthy_only` and `capabilities`-based filtering are orchestrator concerns. `version` and `category`-based filtering are registry concerns. The two tools are *not* exact substitutes today.

## Options

### Option A — Deprecate Mahavishnu's, proxy to Dhara

Mahavishnu's `adapter_list` and `adapter_metadata` become thin pass-throughs that forward to `mcp__dhara__list_adapters` / `mcp__dhara__get_adapter`. The Mahavishnu-specific filter axes (`capabilities`, `healthy_only`, hydration state) are layered on top of Dhara's response, or dropped.

- **Pros:** Single source of truth. Zero contributor confusion about which tool to use. Existing callers (CLI, contract checks) continue to work because the tool name does not change.
- **Cons:** Proxying adds an HTTP hop and an extra failure mode (what happens when Dhara is unreachable?). Hot-path orchestration code that uses these tools now pays network cost. The `has_instance` / `healthy` fields require a join against in-memory state, which means the "proxy" is not actually a thin pass-through.
- **Effort:** Medium — fallback semantics for Dhara-unavailable need to be designed, and the response shape needs reconciling.
- **Risk:** Medium — performance regression on the orchestration hot path; tighter runtime coupling between Mahavishnu and Dhara.

### Option B — Document the boundary, keep both

Keep both tools but write the boundary into `docs/MCP_TOOLS_SPECIFICATION.md` and the tool docstrings:

- **Mahavishnu's `adapter_list` / `adapter_metadata`** = orchestration-time queries against the live in-process registry. Use when you need the orchestrator's current view (which adapters are hydrated, which are healthy *right now*, capability-based filtering for routing decisions).
- **Dhara's `list_adapters` / `get_adapter`** = state queries against the durable registry. Use when you need the canonical record, version history, or any adapter that may not be hydrated in the current Mahavishnu process.

- **Pros:** Each tool keeps the shape it was designed for. No performance regression. No new failure modes. Honest about the fact that the two answer different questions.
- **Cons:** Contributors must learn the boundary. Future drift is still possible — nothing structurally prevents the two surfaces from growing incompatible fields. The agent files would also need a small note that `mcp__dhara__list_adapters` is for state, not for orchestration introspection.
- **Effort:** Low — docs + docstrings only.
- **Risk:** Low.

### Option C — Remove Mahavishnu's entirely, update internal callers

The most aggressive cleanup. Delete `adapter_list` and `adapter_metadata` from `mahavishnu/mcp/tools/adapter_registry_tools.py`, remove their version entries from `tool_versions.py`, and rewrite any internal Mahavishnu callers to either call the in-process `HybridAdapterRegistry` methods directly (for hot paths) or call Dhara's tools (for state queries).

- **Pros:** Zero duplication, zero future drift, smallest API surface.
- **Cons:** Breaking change — anything not under our control that calls the Mahavishnu MCP tools breaks. The CLI in `mahavishnu/_main_cli.py:170` (`adapter_list_cmd`) already calls the registry method directly, but `mahavishnu/core/compatibility.py:75,193,211` has an `adapter_metadata_contract` check that needs to be re-pointed or retired. Tests in `tests/unit/test_compatibility.py` would need updating. The `oneiric-specialist.md` already points at Dhara, so the agent side is fine — but any *user* of the Mahavishnu MCP server who memorized the old tool names is broken.
- **Effort:** Medium — code changes are small, but the deprecation cycle is the real cost.
- **Risk:** High for external consumers, low for internal correctness.

## Recommendation

**Option B** ("document the boundary, keep both") is the proposed default, with a path to Option C deferred to a later cleanup pass.

Rationale:

1. The two tools genuinely answer different questions today. Mahavishnu's surface is shaped around orchestration concerns (`capabilities`, `healthy_only`, `has_instance`, in-memory speed). Dhara's surface is shaped around registry concerns (`domain/key/provider/version`, `category`, version history). Forcing a merge means either losing fields or paying a network hop on the orchestration hot path.
2. The cost of Option B is one paragraph of docs and two tool docstrings.
3. Option C remains available if/when the maintainers decide the Mahavishnu surface has no remaining external consumers — at which point we can run a deprecation cycle through `DEPRECATED_TOOLS` in `tool_versions.py` (which already supports this pattern for `health_check_service`, `get_liveness`, etc.).

**This is a proposal.** The maintainers should ratify, modify, or reject it before any code changes land.

## Consequences

If Option B is adopted:

- Update `mahavishnu/mcp/tools/adapter_registry_tools.py` docstrings for `adapter_list` and `adapter_metadata` to state explicitly: "Orchestration-time view of the live in-process registry. For the durable registry record, use `mcp__dhara__list_adapters` / `mcp__dhara__get_adapter`."
- Add a "Boundary with Dhara" subsection to `docs/MCP_TOOLS_SPECIFICATION.md` (or wherever the adapter MCP tools are documented).
- Add a one-line note to `.claude/agents/oneiric-specialist.md` clarifying that `mcp__dhara__*` is for catalog/state queries — for "what's actually running in this Mahavishnu process right now", call the Mahavishnu side.
- No code changes to the tool implementations.
- No version bump in `tool_versions.py`.
- No changes to the CLI (`_main_cli.py:170`) or compatibility checks (`core/compatibility.py:75`), both of which already call the in-process registry method, not the MCP tool.

If Option A is later adopted (proxying):

- The Mahavishnu tools keep their names but their bodies become Dhara calls plus an in-memory join for `has_instance` / `healthy`. Tool version in `tool_versions.py` bumps to `2.0.0` (behavior change). Add a fallback path for Dhara-unavailable that returns a degraded response with `success=False, error="dhara unreachable"`.

If Option C is later adopted (remove):

- Remove the `@mcp.tool() async def adapter_list` and `adapter_metadata` blocks from `mahavishnu/mcp/tools/adapter_registry_tools.py`.
- Remove `"adapter_list"` and `"adapter_metadata"` from `TOOL_VERSIONS` in `tool_versions.py:151-152`.
- Add both to `DEPRECATED_TOOLS` in the same file with replacements pointing at the Dhara tools.
- Re-point or remove `_check_adapter_metadata_contract` in `mahavishnu/core/compatibility.py`.
- Update tests in `tests/unit/test_compatibility.py`, `tests/unit/test_main_cli.py`, and anything else surfaced by `grep -rn adapter_metadata mahavishnu/ tests/`.

## Open Questions

1. **External consumers.** Are there any non-agent callers of `mcp__mahavishnu__adapter_metadata` or `mcp__mahavishnu__adapter_list` that we have not yet found? The search above covered `mahavishnu/`, `tests/`, `docs/`, and `.claude/agents/`. External MCP clients (other Bodai components, ad-hoc scripts, downstream tooling) are not visible from this repo.
2. **Deprecation timeline for Option A or C.** If the maintainers want to converge on a single tool eventually, what's the deprecation window? The existing `DEPRECATED_TOOLS` mechanism in `tool_versions.py` is the natural lever, but no policy is documented for how long a tool stays in that dict before being removed.
3. **Field reconciliation.** Even under Option B, should Dhara's `list_adapters` response grow a `healthy` field, or Mahavishnu's grow a `version` field, to make them easier to compose? Or do we deliberately keep them disjoint to discourage substitution?
4. **`get_adapter_health` parallel.** Dhara also has its own `get_adapter_health` (server_core.py:677), which overlaps with Mahavishnu's `adapter_health` tool. The same boundary question applies; whatever this ADR decides should probably apply there too. Out of scope for this ADR but worth flagging.
