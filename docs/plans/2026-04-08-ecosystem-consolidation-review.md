# Ecosystem Consolidation Review

Date: 2026-04-08
Revised: 2026-04-13

This document is a consolidation review for the Bodai ecosystem centered on Mahavishnu.
It is written for third-party review and should be treated as an architecture assessment,
not as usage telemetry.

The April 13 revision adds five additional consolidation areas discovered during a
systematic file-by-file audit, corrects adapter implementation status in the component
matrix, adds risk ratings and acceptance criteria, and restructures the execution phases
to begin with zero-risk quick wins.

## Scope

This review covers:

- Mahavishnu core orchestration
- Configuration and repository inventory
- CLI surfaces
- Monitoring, dashboard, and health check code
- Search and storage paths
- Adapter wrapping and re-export layers
- Routing and metrics persistence
- Quality evaluation modules
- Pool and terminal management overlap
- Ecosystem component boundaries for Akosha, Session-Buddy, Dhara, Oneiric, Crackerjack, Prefect, and Agno
- Low-value tools and legacy artifacts

## Short Answer

The ecosystem can be simplified by enforcing one canonical path per concern:

- One editable inventory/config source
- One canonical CLI tree
- One monitoring and health model
- One primary storage/search path
- One quality gate
- One adapter import path per engine (no re-export wrappers)
- Thin adapters for optional ecosystem components

The repo already contains roadmap items that point in this direction, especially:

- `docs/plans/2026-04-04-ecosystem-execution-board.md`
- `docs/plans/initiatives/10-low-value-tool-retirement.md`
- `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`
- `docs/FEATURE_ROADMAP_NEXT_STEPS.md`

## Execution Order

0. Delete dead files with zero importers (`.bak` files, unused `cli/` variants).
1. Add deprecation warnings to adapter re-export wrappers.
2. Make `settings/ecosystem.yaml` the only editable inventory source and treat `settings/repos.yaml` as legacy or generated output.
3. Collapse the CLI tree into one canonical surface and leave compatibility shims only where needed.
4. Merge monitoring, dashboard, and health check code into fewer module paths.
5. Choose one primary storage and search path, with PostgreSQL + pgvector as the default.
6. Unify quality evaluation into one canonical module.
7. Assess routing metrics persistence against Dhara's time-series storage.
8. Freeze Akosha, Session-Buddy, Oneiric, and Dhara integration layers as thin adapters unless they are on the critical path.
9. Remove deprecated wrappers and low-value tools after canonical paths are stable.

## Risk Ratings

| Level | Definition | Validation required |
|-------|-----------|-------------------|
| **Low** | Zero or confirmed-zero importers; deletion does not affect any active code path | Grep for importers, run test suite |
| **Medium** | Known importers exist; merge requires updating import paths and possibly test files | Import graph analysis, full test suite, manual verification |
| **High** | Multiple consumers across subsystems; merge changes public API or affects downstream repos | Import graph, test suite, integration testing, compatibility window |

## File-By-File Consolidation Plan

### Delete Immediately (Low Risk)

- `mahavishnu/mcp/tools/session_buddy_tools.py.bak4`
  - Accumulated backup snapshot. Git history preserves all prior versions.
  - **Acceptance**: `grep -r session_buddy_tools.py.bak mahavishnu/` returns zero results; tests pass.

- `mahavishnu/mcp/tools/session_buddy_tools.py.bak5`
  - Same as above.
  - **Acceptance**: Same as above.

- `mahavishnu/mcp/tools/session_buddy_tools.py.bak6`
  - Same as above.
  - **Acceptance**: Same as above.

- `mahavishnu/cli/backup_cli.py`
  - Zero importers confirmed. `_main_cli.py` imports from root-level `backup_cli.py` only.
  - **Acceptance**: `grep -r "cli\.backup_cli\|cli/backup_cli" mahavishnu/` returns zero results; tests pass.

- `mahavishnu/cli/production_cli.py`
  - Zero importers confirmed. `_main_cli.py` imports from root-level `production_cli.py` only.
  - **Acceptance**: `grep -r "cli\.production_cli\|cli/production_cli" mahavishnu/` returns zero results; tests pass.

### Canonicalize

- `settings/ecosystem.yaml`
  - Make this the editable source of truth for repo inventory, roles, and component topology.
  - Do not keep a separate user-editable inventory file unless there is a proven external consumer.
  - **Acceptance**: All inventory tools read from `ecosystem.yaml`; `repos.yaml` emits deprecation warning on access.

- `core/ecosystem.py`
  - Keep this as the parser and validator for `ecosystem.yaml`.
  - Avoid turning it into a second configuration system.
  - **Acceptance**: No new configuration keys added outside `ecosystem.yaml`.

- `core/monitoring.py`
  - Keep the main monitoring model here if Mahavishnu retains local monitoring.
  - This should be the canonical location for alerting and dashboard logic.
  - **Acceptance**: All monitoring queries route through this module.

- `core/search/hybrid_search.py`
  - Keep this as the canonical search path.
  - Treat it as the main implementation for hybrid lexical plus vector search.
  - **Acceptance**: All search surfaces delegate to this module.

- `README.md`
  - Update the documentation to match the canonical config and component story.
  - **Acceptance**: No references to `repos.yaml` as primary; all paths point to `ecosystem.yaml`.

- `docs/ECOSYSTEM.md`
  - Keep this aligned with the canonical inventory story. Currently describes `repos.yaml` as "legacy, being migrated" which is correct but incomplete.
  - Complete the migration checklist items marked with in-progress markers.
  - **Acceptance**: All migration checklist items resolved; `repos.yaml` references removed or marked deprecated.

- `ingesters/quality_scorer.py`
  - Make this the canonical quality evaluation module. It already contains the real implementation (469 lines vs the 84-line stub evaluator).
  - Merge the type definitions from `quality_evaluator.py` into this module.
  - **Acceptance**: `quality_scorer.py` is the sole import target; `quality_evaluator.py` only re-exports with deprecation warning.

### Merge Or Dedupe

- `_main_cli.py` (1,673 lines)
  - This is the biggest overlap surface.
  - Normalize duplicate command families and reduce command fan-in.
  - **Acceptance**: Each command family appears once; no duplicate registrations.
  - **Risk**: Medium -- many consumers import from this file.

- `mahavishnu/backup_cli.py` (152 lines)
  - Keep as canonical after `cli/backup_cli.py` is deleted.
  - **Acceptance**: All backup commands work; tests pass.

- `mahavishnu/production_cli.py` (97 lines)
  - Keep as canonical after `cli/production_cli.py` is deleted.
  - **Acceptance**: All production readiness commands work; tests pass.

- `core/monitoring_infra.py` (233 lines)
  - Provides MetricsExporter and AlertManager. Merge into `core/monitoring.py`.
  - Preserve the alerting rule logic -- it is complementary, not redundant.
  - **Acceptance**: `monitoring.py` exports all symbols from both modules; no import breakage.
  - **Risk**: Medium -- verify all importers of `monitoring_infra` are updated.

- `core/dashboard_config.py` (77 lines)
  - Pure data model for Grafana JSON generation. Fold into `core/monitoring.py` directly.
  - **Acceptance**: `DashboardPanel` and `DashboardConfig` importable from `monitoring.py`.
  - **Risk**: Low -- small dataclass module with few consumers.

- `core/health_schemas.py` (128 lines)
  - Pydantic models for health checking. Fold into `core/health.py`.
  - **Acceptance**: All health schema types importable from `health.py`.
  - **Risk**: Low -- pure data models.

- `core/opensearch_integration.py` (515 lines)
  - Narrow to a distinct workload or retire if pgvector covers the use case.
  - **Acceptance**: If retired, all search paths route through `hybrid_search.py`; if kept, it has a clear separate responsibility documented in module docstring.
  - **Risk**: Medium -- verify LlamaIndex adapter does not depend on this directly.

- `core/embeddings_oneiric.py` (366 lines)
  - Fold into `core/config.py` if it is only another configuration layer.
  - **Acceptance**: Embedding configuration is part of main config; no separate module needed.
  - **Risk**: Medium -- check for Oneiric-specific consumers.

- `ingesters/quality_evaluator.py` (84 lines)
  - Stub module. `quality_scorer.py` already imports types from it and provides the real implementation.
  - After merging types into `quality_scorer.py`, convert to a thin deprecation re-export.
  - **Acceptance**: `quality_scorer.py` is self-contained; `quality_evaluator.py` emits `DeprecationWarning`.

### Add Deprecation Warnings (Medium Risk)

- `mahavishnu/engines/agno_adapter.py` (7 lines)
  - Re-export wrapper using wildcard imports (`from .agno_adapter_impl import *`).
  - Add deprecation warning directing consumers to `engines.agno_adapter_impl`.
  - **Acceptance**: Import from this path still works but emits warning.

- `mahavishnu/engines/prefect_adapter.py` (7 lines)
  - Same pattern as above.
  - **Acceptance**: Same as above.

- `mahavishnu/engines/llamaindex_adapter.py` (7 lines)
  - Same pattern as above.
  - **Acceptance**: Same as above.

- `mahavishnu/adapters/rag/llamaindex_adapter.py` (34 lines)
  - Silent re-export wrapper without deprecation warning (unlike the Prefect one).
  - Add deprecation warning matching the pattern in `adapters/workflow/prefect_adapter.py`.
  - **Acceptance**: Import from this path still works but emits warning.

- `mahavishnu/adapters/workflow/prefect_adapter.py` (66 lines)
  - Already has deprecation warning. No action needed beyond eventual removal.
  - **Acceptance**: N/A -- already deprecated.

### Assess For Overlap

- `core/routing_metrics_persistence.py` (628 lines)
  - Nearly as large as the core routing logic (`routing.py` at 524 lines).
  - May duplicate Dhara's time-series storage capability.
  - **Action**: Compare storage operations against `mcp__dhara__record_time_series` and `mcp__dhara__query_time_series`. If Dhara covers the use case, make persistence a thin Dhara delegate.
  - **Acceptance**: Documented decision on whether to keep, replace, or delegate.

- `core/routing_alerts.py` (538 lines) vs `core/monitoring_infra.py` (233 lines)
  - Both define alerting systems. `routing_alerts.py` handles adapter degradation and cost spikes. `monitoring_infra.py` provides a general AlertManager.
  - **Action**: Determine if these can share a common alert rule engine, or if their responsibilities are genuinely distinct.
  - **Acceptance**: Documented decision with rationale.

- `health.py` (root, 208 lines) vs `core/health.py` (549 lines) vs `core/health_integration.py` (759 lines)
  - Three files for health checking plus schemas (128 lines) and MCP tools (518 lines).
  - **Action**: Map importers for the root-level `health.py` and `health_integration.py`. Determine if they duplicate what `health_tools.py` provides via MCP.
  - **Acceptance**: Clear ownership of each health check path documented.

- `terminal/pool.py` (480 lines) vs `pools/` directory
  - Two pool abstractions. Terminal pool is iTerm2-specific (AppleScript-based). Pools directory handles multi-pool orchestration.
  - **Action**: Document which abstraction handles which use case. Assess whether `core/process_pool_executor.py` (240 lines) is related or independent.
  - **Acceptance**: Clear ownership documented; no conceptual overlap in pool lifecycle management.

### Freeze As Optional

- `integrations/session_buddy_poller.py`
  - Keep only if OTel bridging is still needed.
  - Otherwise this is likely optional infrastructure.

- `session_buddy/integration.py`
  - Keep as a narrow bridge, not a separate product surface.

- `pools/session_buddy_pool.py`
  - Keep only for delegation.
  - Do not let it become a second orchestration model.

- `core/oneiric_client.py`
  - Keep library-shaped.
  - Do not expand it into a service-like subsystem.

- `core/dhara_adapter.py`
  - Keep as a thin adapter unless Dhara becomes first-class storage.

- `mcp/tools/git_analytics.py`
  - Keep secondary to orchestration and quality gating.

### Retire

- `.bak` files in `mahavishnu/mcp/tools/`
  - `session_buddy_tools.py.bak4`, `.bak5`, `.bak6` -- accumulated incremental backups.
  - Remove once no code path depends on them (confirmed: zero importers).

- Dead `cli/` variants
  - `mahavishnu/cli/backup_cli.py` and `mahavishnu/cli/production_cli.py` -- zero importers.
  - Remove immediately.

- Deprecated adapter re-export wrappers (after compatibility window)
  - `engines/agno_adapter.py`, `engines/prefect_adapter.py`, `engines/llamaindex_adapter.py` -- 7-line wildcard imports.
  - `adapters/rag/llamaindex_adapter.py`, `adapters/workflow/prefect_adapter.py` -- backward-compat re-exports.
  - Remove after deprecation warnings have been in place for at least one release cycle.

- Low-value MCP tools identified in the retirement initiative
  - Remove or hide behind explicit opt-in.

- Legacy docs and commands that still present `repos.yaml` as the main path
  - Update after `ecosystem.yaml` becomes canonical.

- Wrapper commands that only preserve historical names
  - Remove after a compatibility window.

## Component Consolidation Matrix

| Component | Current overlap | Recommendation | What to keep |
|-----------|----------------|----------------|--------------|
| Mahavishnu core | CLI fragmentation, monitoring split, health check fragmentation, storage and search overlap, adapter re-export layer | Consolidate aggressively | Orchestration, adapters, health, validation, canonical config |
| Akosha | Storage, telemetry, intelligence, derived analytics | Make optional and non-critical | Derived analysis, reranking, secondary intelligence only |
| Session-Buddy | Memory, telemetry, worker delegation, analytics bridges | Keep, but trim duplication | Polling, memory, delegation, best-effort integration |
| Dhara | Persistence and analytics adapter overlap | Keep thin | Health and persistence bridge only |
| Oneiric | Platform foundation -- resolution, lifecycle, adapters, actions, runtime | Keep as shared platform library | Resolution, config, lifecycle, adapters, actions, runtime orchestration |
| Crackerjack | Quality gate and readiness overlap | Keep as the gate | CI and quality checks, not duplicate UI |
| OpenSearch | Search overlap with pgvector | Secondary or retire if redundant | Only if it serves a distinct log or search workload |
| Prefect | **Fully implemented** adapter (1,832 lines, 39 methods) | Keep as maintained adapter | Full Prefect SDK integration with deployments, schedules, flow registry |
| LlamaIndex | **Fully implemented** adapter (1,149 lines, full OrchestratorAdapter) | Keep as maintained adapter | RAG pipelines with Ollama embeddings, OpenSearch vector store, query engine |
| Agno | **Fully implemented** adapter (1,451 lines) | Keep as maintained adapter | Multi-agent teams with MCP tools, multi-provider LLM support |

Note: The original review incorrectly listed Prefect, LlamaIndex, and Agno as "Partial workflow integration." All three are fully implemented production-ready adapters. CLAUDE.md correctly states "All adapters are production-ready."

## Overlap Findings

### Inventory And Config

The strongest config overlap is between:

- `settings/ecosystem.yaml`
- `settings/repos.yaml`
- the documentation that still describes `repos.yaml` as primary

The right simplification is to make `ecosystem.yaml` canonical and demote `repos.yaml` to legacy or generated status.

### CLI Surfaces

There are duplicate or overlapping CLI surfaces for:

- sweep
- health
- backup
- production/readiness

This suggests the CLI should be normalized around one canonical command tree with compatibility shims only where necessary.

### Monitoring And Dashboard

The monitoring overlap appears in:

- `core/monitoring.py` (800 lines)
- `core/monitoring_infra.py` (233 lines)
- `core/dashboard_config.py` (77 lines)

This should become one module path, not three partially overlapping layers.

### Health Check Fragmentation

The health check system is spread across five files (2,162 lines total):

- `core/health.py` (549 lines) -- core health checking
- `core/health_schemas.py` (128 lines) -- Pydantic models
- `core/health_integration.py` (759 lines) -- integration helpers
- `health.py` (208 lines) -- root-level module
- `mcp/tools/health_tools.py` (518 lines) -- MCP tool surface

The schemas should fold into `health.py`. The root-level module and integration file need assessment for overlap with the MCP tool surface.

### Adapter Re-Export Layer

Each engine adapter has three layers of indirection:

```
engines/agno_adapter.py (7 lines, wildcard re-export)
  -> engines/agno_adapter_impl.py (1,451 lines, actual implementation)

adapters/__init__.py (re-exports from engines/*)
  -> adapters/rag/llamaindex_adapter.py (34 lines, silent re-export)
  -> adapters/workflow/prefect_adapter.py (66 lines, deprecated re-export)
```

Five files totaling approximately 115 lines serve as pure re-export wrappers. The `engines/*_adapter.py` files use wildcard imports (`from .xxx_adapter_impl import *` with `noqa: F401,F403`) which hide namespace pollution.

### Quality Evaluation Duplication

Two modules handle content quality:

- `ingesters/quality_evaluator.py` (84 lines) -- stub with data classes and factory function
- `ingesters/quality_scorer.py` (469 lines) -- real implementation that "replaces the stub QualityEvaluator"

The scorer already imports types from the evaluator and provides the actual scoring logic. The evaluator should become a thin deprecation wrapper.

### Search And Storage

The current overlap is between:

- `core/search/hybrid_search.py`
- `core/opensearch_integration.py`
- `core/embeddings_oneiric.py`
- the storage-related settings in `settings/mahavishnu.yaml`

The simplest stable model is PostgreSQL + pgvector as the primary operational path, with other systems only where they add distinct value.

### Routing And Metrics Persistence

The routing layer is five files totaling 2,324 lines:

- `core/routing.py` (524 lines) -- StatisticalRouter, CostOptimizer
- `core/routing_metrics.py` (584 lines) -- Prometheus metrics
- `core/routing_metrics_persistence.py` (628 lines) -- storage adapter for metrics
- `core/routing_alerts.py` (538 lines) -- alerting rules
- `routing_cli.py` (50 lines) -- CLI surface

The persistence layer (628 lines) may duplicate Dhara's time-series capability. The alerts system (538 lines) may overlap with `monitoring_infra.py`'s AlertManager.

### Pool And Terminal Overlap

Two separate pool implementations exist:

- `terminal/pool.py` (480 lines) -- iTerm2 session pooling (AppleScript-based)
- `pools/` directory (5+ files) -- multi-pool orchestration (mahavishnu, session_buddy, k8s)
- `core/process_pool_executor.py` (240 lines) -- generic process pool wrapper

These serve different audiences but share conceptual overlap in session lifecycle management.

### Ecosystem Bridges

The ecosystem has several bridge layers that are useful but should remain narrow:

- Session-Buddy polling and integration
- Oneiric client and embeddings helpers
- Dhara adapter
- Akosha-derived analytics path

These should not become parallel product surfaces.

## What Is Probably Rarely Used

This is an inference based on structure and roadmap, not on usage metrics.

- Per-component dashboards and interactive CLIs are probably overrepresented relative to actual day-to-day use.
- Production/readiness commands in Mahavishnu are probably low value if Crackerjack remains the standard quality gate.
- Session-Buddy and Akosha bridge code likely exists more for completeness than for frequent direct use.
- Extra storage/search surfaces are likely redundant if PostgreSQL + pgvector covers the main workloads.
- Wrapper commands kept only for historical names are likely maintenance debt.
- The adapter re-export wrappers (`engines/*_adapter.py`, `adapters/rag/*`, `adapters/workflow/*`) are maintenance debt with zero functional value.

## Suggested Review Questions For A Third Party Agent

1. Which modules are genuinely canonical versus compatibility shims?
2. Which overlaps are required for compatibility and which are pure duplication?
3. Which optional ecosystem components should remain explicit dependencies versus passive integrations?
4. Which wrappers can be removed without breaking the main operator workflow?
5. Which low-value tools have no measurable value and can be retired first?
6. Does `routing_metrics_persistence.py` duplicate what Dhara already provides?
7. Can `routing_alerts.py` and `monitoring_infra.py` share a common alert engine?
8. What is the real responsibility split between `health.py` (root), `core/health.py`, and `health_integration.py`?

## Proposed Backlog Shape

### Phase 0: Immediate Wins (Low Risk, Zero Dependencies)

Delete files with confirmed zero importers:

- `mahavishnu/mcp/tools/session_buddy_tools.py.bak4`
- `mahavishnu/mcp/tools/session_buddy_tools.py.bak5`
- `mahavishnu/mcp/tools/session_buddy_tools.py.bak6`
- `mahavishnu/cli/backup_cli.py`
- `mahavishnu/cli/production_cli.py`

Validation: Full test suite passes after deletion.

### Phase 1: Config And CLI Consolidation (Low-Medium Risk)

- Add deprecation warning to `repos.yaml` access paths.
- Complete `ecosystem.yaml` migration checklist in `docs/ECOSYSTEM.md`.
- Normalize `_main_cli.py` command registrations.
- Update remaining docs that reference `repos.yaml` as primary.

### Phase 2: Adapter Layer Cleanup (Medium Risk) -- COMPLETED

- [x] Add deprecation warnings to `engines/*_adapter.py` wildcard re-export wrappers.
- [x] Add deprecation warning to `adapters/rag/llamaindex_adapter.py`.
- [x] Map all consumers of `adapters/workflow/prefect_adapter.py` and confirm migration (already deprecated in prior work).
- [x] Update component matrix to reflect full implementation status of Prefect, LlamaIndex, Agno.

**Import graph summary** (consumers of wrapper modules):
- `engines/agno_adapter.py`: 15+ consumers (tests, adapters/__init__.py, examples, docs)
- `engines/prefect_adapter.py`: 12+ consumers (tests, adapters/__init__.py, docs)
- `engines/llamaindex_adapter.py`: 5 consumers (tests, adapters/rag/llamaindex_adapter.py)
- `adapters/rag/llamaindex_adapter.py`: 3 consumers (adapters/rag/__init__.py, adapters/__init__.py, tests)
- `adapters/workflow/prefect_adapter.py`: Already had deprecation warning from prior work

All wrappers now emit `DeprecationWarning` at import time directing to the `*_impl` modules (engines) or `engines.*` (adapters).

### Phase 3: Monitoring And Health Consolidation (Medium Risk)

- Merge `dashboard_config.py` into `monitoring.py`.
- Merge `health_schemas.py` into `health.py`.
- Merge `monitoring_infra.py` into `monitoring.py`.
- Assess `health_integration.py` for overlap with `health_tools.py` MCP surface.
- Assess `routing_alerts.py` for overlap with consolidated alerting in `monitoring.py`.

### Phase 4: Search And Ingestion Cleanup (Medium Risk)

- Merge `quality_evaluator.py` types into `quality_scorer.py`; convert evaluator to deprecation wrapper.
- Assess `opensearch_integration.py` vs pgvector coverage.
- Assess `routing_metrics_persistence.py` vs Dhara time-series storage.
- Assess `embeddings_oneiric.py` for folding into `core/config.py`.

### Phase 5: Retirement (Low Risk, After Phases 0-4 Are Stable)

- Remove deprecated adapter re-export wrappers (after compatibility window).
- Remove legacy docs references to `repos.yaml` as primary.
- Remove wrapper commands kept only for historical names.
- Document pool/terminal ownership split clearly.

## Prerequisites For Execution

Before any phase beyond Phase 0 begins:

1. **Import graph**: Run a complete import graph for each file targeted for merge or deletion. Confirm all downstream consumers are identified.
2. **Test mapping**: Identify test files associated with each target module. Ensure tests are updated or merged alongside the modules they test.
3. **Rollback plan**: Each phase should be a separate commit (or PR) so it can be reverted independently if it introduces regressions.
4. **Compatibility window**: Phases that change public import paths must include deprecation warnings for at least one release cycle before the import path is removed.
5. **Validation gate**: After each phase, run the full test suite plus `ruff check` plus `mypy` to confirm no regressions.

## Final Recommendation

The ecosystem is not overbuilt in every area, but it does contain multiple parallel surfaces for the same responsibilities. The highest leverage move is to collapse those parallel surfaces into one canonical path per concern and make everything else an explicit adapter, shim, or optional integration.

The original review correctly identified the core diagnosis but missed five additional consolidation areas (adapter re-export layer, health fragmentation, quality evaluation duplication, routing persistence overlap, and pool/terminal overlap) and incorrectly assessed three adapters as "partial" when they are fully implemented. This revised plan addresses those gaps, adds risk ratings and acceptance criteria, and structures execution to begin with zero-risk deletions before progressing to higher-risk merges.
