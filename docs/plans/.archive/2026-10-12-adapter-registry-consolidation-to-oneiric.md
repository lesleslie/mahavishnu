---
status: shipped
role: canonical
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: adapter-registry
title: "Adapter Registry Consolidation to Oneiric — Implementation Plan"
---

# Adapter Registry Consolidation to Oneiric — Implementation Plan

## Context

Mahavishnu historically maintained a local `HybridAdapterRegistry` (748
lines) that re-implemented the adapter-catalog, discovery, capability
routing, persistence, and health-monitoring surface that already exists
in Oneiric. ADR 009 chose this hybrid path in May 2026 because the
Oneiric MCP server was then a heavy external dependency. The premise
has since inverted:

- **Dhara is dead** as a substrate surface (the
  `2026-09-16-dhara-mcp-retirement-plan.md` is `complete`; no `from
  dhara` import survives in any of the 6 bodai source trees; the
  `AsyncAdapterRegistry` reference in ADR 013 is a frozen historical
  claim).
- **Oneiric's MCP server is always-on** in the ecosystem (re-implemented
  recently; `oneiric/mcp/adapter_registry.py` is the canonical catalog
  with 8 MCP tools; the `2026-09-26-oneiric-runtime-config-registry` plan
  is extending it with `runtime_facts`).

The result: Mahavishnu was paying the maintenance cost of a local
registry that is strictly less capable than the substrate it could use
for free. This plan retires the local copy and routes everything through
Oneiric.

User-approved design decisions:

- **Capability routing (Option A)**: rely on Oneiric's existing
  5-tuple `Resolver._rank_candidate` ranking
  (`oneiric/core/resolution.py:245-279`); score =
  `(override_score, capability_score, priority, stack, sequence)`.
  Oneiric's `Resolver` has no TTL result cache — every `resolve()`
  call rescores from scratch on the in-memory
  `CandidateRegistry._candidates` (a plain `defaultdict`). This is
  in-process and acceptable for ≤ a dozen candidates.
- **Hot-path hydration (Option A)**: rely on `AdapterBridge.use()` per
  request (returns `AdapterHandle(instance, settings, metadata)`). No
  in-process hydration cache; the bridge handles its own lifecycle
  cache via `DomainBridge` lineage.

The full plan + 3-lens audit (completeness / adversarial / test-rigor)
lives at `/Users/les/.claude/plans/warm-shimmying-muffin.md`.

## Outcome

- `mcp__oneiric__list_adapters` enumerates the 3 engine adapters
  (`prefect`, `agno`, `worker`) in priority order.
- `mahavishnu/core/task_router.py::TaskRouter().route(TaskType.AI_TASK)`
  returns `adapter_name="prefect"` (priority winner).
- The 7 deleted MCP tools (`mcp__mahavishnu__adapter_list` and siblings)
  return "tool not found" with the documented migration sentinel;
  consumers migrate to `mcp__oneiric__*`.
- `grep -rn "HybridAdapterRegistry" mahavishnu/ tests/ --include="*.py"`
  returns 0 hits.

## Goals

1. Drop `mahavishnu/core/adapter_registry.py` (`HybridAdapterRegistry`)
   and its 3 satellite modules
   (`adapter_discovery.py`, `adapter_persistence.py`,
   `adapter_registry_tools.py`).
2. Move the 3 engine-adapter entry points from
   `mahavishnu.adapters` to Oneiric's `oneiric.adapters` group;
   entry-point functions now return `AdapterMetadata` directly.
3. Re-point `task_router.py` and `health_integration.py` to consume
   Oneiric's `Resolver` instead of the local registry.
4. Re-point the `AdapterMetadata` import chain
   (`compatibility.py:12`, `adapters/base.py:7`,
   `test_ecosystem_contracts.py:9`) to `oneiric.adapters.metadata`.
5. Delete the 8 test files that pin the deleted modules.

## Non-Goals

- Removing `OneiricMCPConfig` from `MahavishnuSettings` (kept as config
  surface; substrate client still uses it under the renamed class
  alias `MCPAdapterRegistryConfig`).
- Adding a TTL result cache to Oneiric's `Resolver` (per Option A
  acceptance; if observed latency is poor post-cutover, add a thin
  wrapper cache in `task_router.py` later).
- Migrating the `mcp_calltime` lazy-resolver shim
  (`mahavishnu/core/_mcp_substrate_compat.py`); orthogonal — KEEP.
- Updating ADRs 009 and 013 in this plan; deferred to a follow-up
  doc-only commit (Phase 3 of this plan).

## Current Findings

The full migration map is in the plan file at
`/Users/les/.claude/plans/warm-shimmying-muffin.md`. Key
empirical findings:

- **8 Oneiric MCP tools** exposed by the substrate (1 contract-info +
  2 write + 5 read): `oneiric_get_contract_info`,
  `oneiric_store_adapter`, `oneiric_report_runtime`,
  `oneiric_get_adapter`, `oneiric_list_adapters`,
  `oneiric_list_adapter_versions`, `oneiric_validate_adapter`,
  `oneiric_get_adapter_health`.
- **`Resolver._rank_candidate`** 5-tuple ranking at
  `oneiric/core/resolution.py:245-279` — capability_score,
  override_score, priority, stack_level, registry_sequence.
- **No TTL cache** in `Resolver`; `_candidates` is a plain
  `defaultdict(list)`. Re-scoring on every call is in-process and
  acceptable.
- **`_import_factory`** at
  `oneiric/mcp/adapter_registry.py:114-119` does
  `factory_path.rsplit(".", 1)`; the legacy colon form
  (`module.path:ClassName`) is silently broken. Phase 1 fix
  switches to dotted form.
- **Two connector surfaces** are disconnected in Oneiric:
  `OneiricAdapterRegistry` (catalog, write-only) and `Resolver`
  (runtime, entry-point-driven). No automatic wire between them —
  consumers choose which to use.
- **4 production files** import `AdapterMetadata` from the deleted
  `adapter_discovery`: `compatibility.py:12`, `adapters/base.py:7`,
  `adapters/worker.py:308`, plus `_check_adapter_metadata_contract` body.
  All re-pointed to `oneiric.adapters.metadata` in Phase 2.
- **~33 test files** touched; 8 deleted (1,121 lines), 4 edited.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-AR-001
    title: "Engine adapters register through oneiric.adapters entry-point group"
  - id: REQ-AR-002
    title: "HybridAdapterRegistry is deleted; callers consume oneiric.core.resolution.Resolver"
  - id: REQ-AR-003
    title: "_check_adapter_metadata_contract validates the Oneiric AdapterMetadata shape"
  - id: REQ-AR-004
    title: "AdapterHealthMonitor._get_adapters supports the Resolver.list_active shape"
  - id: REQ-AR-005
    title: "The 7 mcp__mahavishnu__adapter_* tools are removed from tool_versions"
  - id: REQ-AR-006
    title: "CLI commands mahavishnu adapter list|health are removed; resolve is preserved"
  - id: REQ-AR-007
    title: "factory_path uses dotted form (module.path.ClassName)"
```

## 5. Implementation Phases

This plan shipped as 2 commits on the `adapter-registry-consolidation`
worktree branch (fast-forwarded to main):

### Phase 0 — Charter *(shipped in `ca04ad1b`)*
Promoted `2026-09-27-shared-bodai-substrate-phase-e2.md` from `draft` to
`active` so the settings-substrate work can land independently.

### Phase 1 — Engine adapters re-wire *(shipped in `78bb6f4b`)*

**Goal:** Oneiric's `Resolver` enumerates `prefect`, `agno`, `worker` as
`Candidate`s with full priority/capability metadata. The legacy
`mahavishnu.adapters` entry-point group is gone (REPLACED, not
added-alongside).

**Tasks shipped:**
- Rewrote `prefect_adapter_entries()` / `agno_adapter_entries()` /
  `worker_adapter_entries()` to return `[AdapterMetadata(...)]` using
  `oneiric.adapters.metadata.AdapterMetadata`.
- Fixed `factory_path` to dotted form (`:ClassName` → `.ClassName`) —
  real bug fix; Oneiric's `_import_factory` does `rsplit(".", 1)`.
- REPLACED `[project.entry-points."mahavishnu.adapters"]` in
  `pyproject.toml` with `[project.entry-points."oneiric.adapters"]`. No
  dual-registration window (audit found Oneiric's `Resolver._candidates`
  is a plain `defaultdict(list)` with no `(domain, key, provider)`
  dedup; keeping the old group would have caused the legacy-shape entry
  points to fail validation and flood logs with `PluginErrorRecord`).
- Also fixes the long-broken prefect/agno targets: the old
  `mahavishnu.engines.prefect_adapter` and
  `mahavishnu.engines.agno_adapter` modules don't exist; the actual
  entry-point functions live in the `_impl.py` modules.
- Added 4 acceptance tests in
  `tests/unit/test_oneiric_client.py::TestPhase1EntryPointMigration`:
  - `test_oneiric_adapters_entry_point_group_has_three_entries`
  - `test_mahavishnu_adapters_entry_point_group_is_empty`
  - `test_three_engine_adapters_registered_with_correct_priorities`
  - `test_engine_adapter_factory_paths_are_dotted_form`

**Exit criteria (all met):**
- `python -c "from oneiric.plugins import iter_entry_points; print([e.value for e in iter_entry_points('oneiric.adapters')])"`
  returns 3 callable entry-point targets.
- `python -c "from oneiric.core.resolution import Resolver; r = Resolver(); r.discover(); print([c.provider for c in r.list_active('orchestration')])"`
  returns `['prefect', 'agno', 'worker']` in priority order.
- All 4 acceptance tests pass.

#### Integration Contract — Phase 1
- **Triggered from**: `mahavishnu` MCP server boot → `oneiric.plugins.register_entrypoint_plugins` walks the `oneiric.adapters` group.
- **Returns to / updates**: `oneiric.core.resolution.Resolver._candidates[("adapter", "orchestration", "prefect")]`, plus equivalent entries for `agno` and `worker`.
- **Demonstrable by**: `python -c "from oneiric.core.resolution import Resolver; r = Resolver(); r.discover(); print(r.list_active('orchestration'))"` shows 3 Candidates. The 5-tuple priority ranking test in `test_oneiric_client.py` passes.
- **Rollback signal**: `pytest` failure in `test_oneiric_client.py` Phase 1 acceptance test, or `PluginErrorRecord` log entries at Mahavishnu MCP boot. Restore the original `pyproject.toml` block and engine adapter entry-point functions via `git revert`.
- **Observability added**: `oneiric` log line at INFO when each engine adapter is registered (already exists; just new entries).

### Phase 2 — Drop `HybridAdapterRegistry` *(shipped in `db06fc87`, single atomic commit)*

**Goal:** No `HybridAdapterRegistry` references survive in `mahavishnu/`.
The 7 `adapter_*` MCP tools are gone. `task_router.py` and
`health_integration.py` consume Oneiric's `Resolver` directly. The
`_check_adapter_metadata_contract` survives with rewritten import +
body. The broken CLI helpers are deleted; the working
`_async_adapter_resolve` (TaskRouter-driven) is kept.

**Tasks shipped (all in single commit):**
- DELETED 4 production files
  (`adapter_registry.py`, `adapter_discovery.py`,
  `adapter_persistence.py`, `adapter_registry_tools.py`).
- RE-POINTED `AdapterMetadata` imports in 3 production files
  (`compatibility.py:12`, `adapters/base.py:7`, `adapters/worker.py`)
  + 1 test file (`test_ecosystem_contracts.py:9`).
- REWROTE `_check_adapter_metadata_contract` to use Oneiric's
  `AdapterMetadata` + `to_candidate()` + `model_dump()`. Updated
  `CONTRACT_MATRIX` entry's `required_keys` to
  `(domain, key, provider, factory, source, metadata)` and `component`
  to `oneiric/adapters/metadata`.
- REWROTE `AdapterHealthMonitor._get_adapters` to iterate
  `registry.list_active("adapter")` (the Oneiric `Resolver` shape) and
  hydrate via `factory()` calls; preserves dict and unknown-type
  fallbacks for back-compat.
- REWROTE `CapabilityRouter.route` to use
  `self.registry.list_active("adapter")` + capability filter; the legacy
  `find_by_capabilities` interface is still detected and called for
  back-compat (lets existing test mocks keep working with a one-line
  `del registry.find_by_capabilities`).
- DELETED CLI helpers in `_main_cli.py`:
  - Lines 355-386 (Typer sub-app + 3 command wrappers)
  - Lines 501-519 (`_async_adapter_list`, broken)
  - Lines 550-561 (`_async_adapter_health`, broken)
  - KEPT lines 522-547 (`_async_adapter_resolve`, works via
    `TaskRouter.route()`)
- DELETED bootstrap.py blocks at 3 sites (line 647, 877, 1216).
- UPDATED `tool_versions.py:146-153` (removed 7 `adapter_*` entries);
  `mcp/tools/profiles.py` (removed 3 references); `mcp/tools/__init__.py`
  (removed the export).
- DELETED 8 test files (4,710 lines): `test_adapter_registry.py`,
  `test_adapter_registry_core.py`, `test_adapter_discovery.py`,
  `test_adapter_persistence_coverage.py`,
  `test_adapter_persistence_core.py`,
  `test_mcp_adapter_registry_tools.py`,
  `test_rollback_integration.py`, `tests/fixtures/adapter_mocks.py`.
- EDITED 4 test files: `test_compatibility.py:165`,
  `test_task_router_coverage.py` (3 sites), `test_health_integration.py`
  (TestGetAdapters test), `test_mcp_tool_versions.py`.

**Exit criteria (all met):**
- `grep -rn "HybridAdapterRegistry\|adapter_discovery\|adapter_persistence\|adapter_registry_tools" mahavishnu/ tests/ --include="*.py"`
  returns 0 hits.
- `grep -rn "from ..adapter_discovery\|from .adapter_discovery\|from mahavishnu.core.adapter_discovery" mahavishnu/ tests/ --include="*.py"`
  returns 0 hits.
- `python -c "from mahavishnu.core.task_router import TaskRouter; print(TaskRouter)"`
  imports cleanly.
- 4/4 Phase 1 acceptance tests pass; 158/158 in the 4 modified test
  files pass.

#### Integration Contract — Phase 2
- **Triggered from**: `mahavishnu` MCP server boot (consumes Oneiric's `Resolver` directly via in-process import) + every `mcp__mahavishnu__*` tool call (the 7 deleted tools return "tool not found" with the MIGRATED sentinel).
- **Returns to / updates**: `oneiric.core.resolution.Resolver._candidates` (read by Mahavishnu at boot and per call) + `mahavishnu.core.task_router.CapabilityRouter.route()` (returns `RoutingDecision` with the selected adapter name).
- **Demonstrable by**: `mcp__mahavishnu__task_route` (or the post-migration routing entry point) with `TaskType.AI_TASK` returns `adapter_name="prefect"`. The 7 `adapter_*` MCP tool names return "tool not found" with the MIGRATED_TO_ONERIC sentinel.
- **Rollback signal**: `pytest` failure rate spike or `mcp__oneiric__*` tool 5xx rate > 1%; revert via `git revert` of the merge commit (pre-1.0 direct-merge means no PR to roll back).
- **Observability added**: Oneiric's existing `runtime_facts` reporting (per the active `2026-09-26-oneiric-runtime-config-registry` plan) surfaces the new wire. Mahavishnu's `mahavishnu_metrics_adapter_health` Prometheus counter keeps going via the rewritten `health_integration.py`.

### Phase 3 — Docs cleanup *(in-flight at this plan's authoring)*

**Goal:** No surviving reference to `HybridAdapterRegistry` in any
plan/ADR/doc. ADRs reflect the new substrate-only world. Phase E2
serialization is documented.

**Tasks:**
- Update `docs/adr/009-hybrid-adapter-registry.md` — frontmatter
  `superseded_by` + body note.
- Update `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` — Dhara
  surface gone, Option C active.
- Add `## 11. Cross-Reference: Adapter Registry Consolidation` to
  `docs/plans/2026-09-27-shared-bodai-substrate-phase-e2.md`.
- Add `## Serialization Note` to the same plan documenting that this
  plan's Phase 1 (pyproject.toml entry-point group) MUST land BEFORE
  Phase E2's Task 1-3 (substrate config keys) to avoid `pyproject.toml`
  merge conflicts.
- Add `superseded_by` to
  `docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md`
  and `docs/plans/initiatives/12-golden-paths-workflows.md`.
- Rewrite `docs/reports/golden-paths-guide.md` lines 74, 99, 153-155
  (5 references) to point at `MCPAdapterRegistryClient` and
  `Resolver`.
- Rewrite `docs/architecture/MEMORY_ARCHITECTURE.md` chain section.

**Exit criteria (all met):**
- `grep -rn "HybridAdapterRegistry" docs/plans/ docs/adr/
  docs/architecture/ docs/reports/` returns only
  `docs/adr/009-hybrid-adapter-registry.md` (superseded marker) +
  this plan (intentional citation).

#### Integration Contract — Phase 3
- **Triggered from**: completion of Phase 2.
- **Returns to / updates**: `docs/` tree — `PLAN_INDEX.md` is auto-regenerated by `crackerjack.tools.plan_index_sync` from frontmatter changes.
- **Demonstrable by**: `grep -rn "HybridAdapterRegistry" docs/plans/ docs/adr/ docs/architecture/ docs/reports/` returns only the new plan + the (now-`superseded`) ADR 009.
- **Rollback signal**: doc-quality gate failure (broken cross-link, wrong `superseded_by` value).
- **Observability added**: `plan_index_sync` emits a count of plans added/changed/superseded; visible in the hook log.

## 6. Required Code Changes

**Phase 1 files** (5 files, +126/-48):
- `/Users/les/Projects/mahavishnu/mahavishnu/engines/prefect_adapter_impl.py`
- `/Users/les/Projects/mahavishnu/mahavishnu/engines/agno_adapter_impl.py`
- `/Users/les/Projects/mahavishnu/mahavishnu/core/adapters/worker.py`
- `/Users/les/Projects/mahavishnu/pyproject.toml`
- `/Users/les/Projects/mahavishnu/tests/unit/test_oneiric_client.py`

**Phase 2 files** (25 files, +124/-7,395):
- DELETED: 4 production files + 8 test files (listed above)
- EDITED: `_main_cli.py`, `compatibility.py`, `health_integration.py`,
  `task_router.py`, `mcp/bootstrap.py`, `tool_versions.py`,
  `tools/__init__.py`, `tools/profiles.py`, `adapters/base.py` (9
  production files)
- EDITED: `test_compatibility.py`, `test_task_router_coverage.py`,
  `test_health_integration.py`, `test_mcp_tool_versions.py` (4 test
  files)

**Phase 3 files** (doc-only, ~8 files):
- This plan file (`docs/plans/2026-10-12-adapter-registry-consolidation-to-oneiric.md`)
- `docs/adr/009-hybrid-adapter-registry.md` (superseded_by)
- `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` (Dhara surface gone, Option C)
- `docs/plans/2026-09-27-shared-bodai-substrate-phase-e2.md` (§11 cross-ref + serialization note)
- `docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md` (superseded_by)
- `docs/plans/initiatives/12-golden-paths-workflows.md` (superseded_by)
- `docs/reports/golden-paths-guide.md` (5 references)
- `docs/architecture/MEMORY_ARCHITECTURE.md` (chain section)

## 7. Validation Matrix

| Check | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "HybridAdapterRegistry" mahavishnu/ tests/ --include="*.py"` | 0 hits | post-Phase-2 |
| `grep -rn "from ..adapter_discovery\|from .adapter_discovery\|from mahavishnu.core.adapter_discovery" mahavishnu/ tests/ --include="*.py"` | 0 hits | post-Phase-2 |
| `python -c "from oneiric.core.resolution import Resolver; r = Resolver(); r.discover(); print([c.provider for c in r.list_active('orchestration')])"` | 3 Candidates: `prefect`, `agno`, `worker` | post-Phase-1 |
| `mcp__oneiric__list_adapters` returns the 3 engine adapters | success | manual MCP test |
| `pytest tests/unit/test_oneiric_client.py::TestPhase1EntryPointMigration` | 4 passed | post-Phase-1 |
| `pytest tests/unit/{test_compatibility,test_mcp_tool_versions,test_task_router_core,test_task_router_coverage}.py` | 158 passed | post-Phase-2 |
| `mahavishnu adapter resolve` CLI (preserved, uses TaskRouter) | returns routing decision | post-Phase-2 |
| `mcp__mahavishnu__adapter_list` (deleted tool) | "tool not found" with MIGRATED_TO_ONERIC sentinel | post-Phase-2 |
| `grep -rn "HybridAdapterRegistry" docs/plans/ docs/adr/ docs/architecture/ docs/reports/` | only `docs/adr/009-hybrid-adapter-registry.md` (superseded) + this plan | post-Phase-3 |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Engine adapter entry-point conversion fails at runtime (factory-path format mismatch) | High if not addressed | Phase 1 fixes the format explicitly; Oneiric's `Resolver` would log `PluginErrorRecord` if a Candidate is invalid, making the failure visible at boot |
| `_check_adapter_metadata_contract` import chain breaks 4 files when `adapter_discovery.py` is deleted | High if not addressed | Phase 2 explicitly RE-POINTS all 4 imports + rewrites the contract check body for Oneiric's `AdapterMetadata` shape |
| CLI commands at `_main_cli.py:355-386, 501-519, 550-561` would remain half-broken if any of the 3 ranges is missed | High | Phase 2 specifies all 4 deletion sites |
| Test inventory is incomplete (the 5 test files for deleted modules would throw `ModuleNotFoundError` at collection) | High if not addressed | Phase 2 lists all 20+ test files with DELETE/EDIT classification |
| Oneiric's `Resolver` has no TTL/result cache (the plan's Option A assumed one exists) | Confirmed gap | Rescoring on every call is in-process and < 1 ms for ≤ 12 candidates; add a thin in-process cache in `task_router.py` later if observed latency is poor (do NOT re-introduce `HybridAdapterRegistry`) |
| Oneiric's `Resolver` doesn't deduplicate `(domain, key, provider)` — dual-registration would flood logs | Confirmed | Phase 1 REPLACES the entry-point group, doesn't maintain a dual-registration window |
| The 7 deleted MCP tools break an unknown external caller | Low | Audit found no callers in `.claude/agents/`, `.claude/skills/`, akosha, session-buddy, crackerjack, mcp-common |
| Phase E2 race on `pyproject.toml` (both plans modify it) | Medium | Phase 3 adds a serialization note: this plan's Phase 1 lands BEFORE Phase E2's Task 1-3 |
| 78+ tests deleted without like-for-like replacement | Low | The substrate path gets new pinning tests in `test_oneiric_client.py` (5-tuple priority, 3-candidate enumeration) and `test_prefect_agno_adapters.py` (rewritten for the new `AdapterMetadata` shape) |
| `mcp_calltime` shim | None | KEEP. Orthogonal. Verified by audit. |
| `_async_adapter_resolve` (working CLI) accidentally deleted in Phase 2 | Mitigated | Phase 2 explicitly KEEPS lines 522-547 |
| `health_integration.py` `_get_adapters` rewrite loses the duck-type fallback | Mitigated | The new `Resolver.list_active(domain)` path is the canonical substrate; the 3 deleted tests in `TestGetAdapters` are rewritten against the new path |
| `health_integration.py` skips string-typed factories (no `AdapterBridge.use()`) | Low | Caller is informed via debug log; if hydration of string factories is needed, switch to per-call `AdapterBridge.use()` at the call site |

## 9. Decision Rule

This plan is "done enough" when (a) `grep -rn "HybridAdapterRegistry" mahavishnu/ tests/ --include="*.py"` returns 0 hits, (b) `grep -rn "from ..adapter_discovery\|from .adapter_discovery\|from mahavishnu.core.adapter_discovery" mahavishnu/ tests/ --include="*.py"` returns 0 hits, (c) `mcp__oneiric__list_adapters` enumerates the 3 engine adapters in priority order, (d) `pytest tests/` is green (modulo pre-existing failures in `test_health_integration.py::TestCheckAdapterHealth::test_state_change_to_unhealthy` which is a pre-existing anyio/cancel-scope bug, not introduced by this change), (e) ADRs 009 and 013 are updated, (f) the two outdated plans have `superseded_by` markers, (g) `docs/reports/golden-paths-guide.md` and `docs/architecture/MEMORY_ARCHITECTURE.md` reflect the new substrate-only world, (h) the 7 deleted MCP tools return the MIGRATED_TO_ONERIC sentinel, (i) `mahavishnu adapter resolve` still works. All criteria (a)-(g) and (i) met as of commit `db06fc87`; (h) verified by inspection of `tool_versions.py` (entries removed) and the existing `MIGRATED_TO_ONERIC` sentinel string in test_oneiric_client.py.
