# Ecosystem Consolidation Review

Date: 2026-04-08

This document is a consolidation review for the Bodai ecosystem centered on Mahavishnu.
It is written for third-party review and should be treated as an architecture assessment,
not as usage telemetry.

## Scope

This review covers:

- Mahavishnu core orchestration
- configuration and repository inventory
- CLI surfaces
- monitoring and dashboard code
- search and storage paths
- ecosystem component boundaries for Akosha, Session-Buddy, Dhara, Oneiric, Crackerjack, Prefect, and Agno
- low-value tools and legacy artifacts

## Short Answer

The ecosystem can be simplified by enforcing one canonical path per concern:

- one editable inventory/config source
- one canonical CLI tree
- one monitoring model
- one primary storage/search path
- one quality gate
- thin adapters for optional ecosystem components

The repo already contains roadmap items that point in this direction, especially:

- `docs/plans/2026-04-04-ecosystem-execution-board.md`
- `docs/plans/initiatives/10-low-value-tool-retirement.md`
- `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`
- `docs/FEATURE_ROADMAP_NEXT_STEPS.md`

## Execution Order

1. Make `settings/ecosystem.yaml` the only editable inventory source and treat `settings/repos.yaml` as legacy or generated output.
2. Collapse the CLI tree into one canonical surface and leave compatibility shims only where needed.
3. Merge monitoring and dashboard code into one module path.
4. Choose one primary storage and search path, with PostgreSQL + pgvector as the default.
5. Freeze Akosha, Session-Buddy, Oneiric, and Dhara integration layers as thin adapters unless they are on the critical path.
6. Remove `.bak` files and low-value tools after the canonical paths are stable.

## File-By-File Consolidation Plan

### Canonicalize

- `settings/ecosystem.yaml`
  - Make this the editable source of truth for repo inventory, roles, and component topology.
  - Do not keep a separate user-editable inventory file unless there is a proven external consumer.

- `core/ecosystem.py`
  - Keep this as the parser and validator for `ecosystem.yaml`.
  - Avoid turning it into a second configuration system.

- `core/monitoring.py`
  - Keep the main monitoring model here if Mahavishnu retains local monitoring.
  - This should be the canonical location for alerting and dashboard logic.

- `core/search/hybrid_search.py`
  - Keep this as the canonical search path.
  - Treat it as the main implementation for hybrid lexical plus vector search.

- `README.md`
  - Update the documentation to match the canonical config and component story.

- `docs/ECOSYSTEM.md`
  - Keep this aligned with the canonical inventory story and remove contradictions around `repos.yaml`.

### Merge Or Dedupe

- `_main_cli.py`
  - This is the biggest overlap surface.
  - Normalize duplicate command families and reduce command fan-in.

- `mahavishnu/backup_cli.py`
  - Merge into one canonical backup command family.

- `mahavishnu/cli/backup_cli.py`
  - Collapse with the root-level backup CLI path or make it a thin shim.

- `mahavishnu/production_cli.py`
  - Merge with the other production/readiness path instead of maintaining two surfaces.

- `mahavishnu/cli/production_cli.py`
  - Collapse with the root-level production CLI path or make it a thin shim.

- `core/monitoring_infra.py`
  - This appears to be a wrapper around the real monitoring path.
  - Keep only if compatibility is necessary.

- `core/dashboard_config.py`
  - Fold into the main monitoring config path.

- `core/opensearch_integration.py`
  - Narrow to a distinct workload or retire if pgvector covers the use case.

- `core/embeddings_oneiric.py`
  - Fold into `core/config.py` if it is only another configuration layer.

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
  - Remove once no code path depends on them.

- Low-value MCP tools identified in the retirement initiative
  - Remove or hide behind explicit opt-in.

- Legacy docs and commands that still present `repos.yaml` as the main path
  - Update after `ecosystem.yaml` becomes canonical.

- Wrapper commands that only preserve historical names
  - Remove after a compatibility window.

## Component Consolidation Matrix

| Component | Current overlap | Recommendation | What to keep |
|---|---|---|---|
| Mahavishnu core | CLI fragmentation, monitoring split, storage and search overlap | Consolidate aggressively | Orchestration, adapters, health, validation, canonical config |
| Akosha | Storage, telemetry, intelligence, derived analytics | Make optional and non-critical | Derived analysis, reranking, secondary intelligence only |
| Session-Buddy | Memory, telemetry, worker delegation, analytics bridges | Keep, but trim duplication | Polling, memory, delegation, best-effort integration |
| Dhara | Persistence and analytics adapter overlap | Keep thin | Health and persistence bridge only |
| Oneiric | Resolver, embeddings, and config overlap | Keep as library or resolver only | Resolution logic, no service-like expansion |
| Crackerjack | Quality gate and readiness overlap | Keep as the gate | CI and quality checks, not duplicate UI |
| OpenSearch | Search overlap with pgvector | Secondary or retire if redundant | Only if it serves a distinct log or search workload |
| Prefect | Partial workflow integration | Optional | Only the minimum needed integration |
| Agno | Partial workflow integration | Optional | Only the minimum needed integration |

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

- `core/monitoring.py`
- `core/monitoring_infra.py`
- `core/dashboard_config.py`

This should become one module path, not three partially overlapping layers.

### Search And Storage

The current overlap is between:

- `core/search/hybrid_search.py`
- `core/opensearch_integration.py`
- `core/embeddings_oneiric.py`
- the storage-related settings in `settings/mahavishnu.yaml`

The simplest stable model is PostgreSQL + pgvector as the primary operational path, with other systems only where they add distinct value.

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

## Suggested Review Questions For A Third Party Agent

1. Which modules are genuinely canonical versus compatibility shims?
2. Which overlaps are required for compatibility and which are pure duplication?
3. Which optional ecosystem components should remain explicit dependencies versus passive integrations?
4. Which wrappers can be removed without breaking the main operator workflow?
5. Which low-value tools have no measurable value and can be retired first?

## Proposed Backlog Shape

If this review is accepted, the work should be split into four phases:

1. Config and CLI consolidation
2. Monitoring and search deduplication
3. Optional component boundary cleanup
4. Retirement of stale wrappers, `.bak` files, and low-value tools

## Final Recommendation

The ecosystem is not overbuilt in every area, but it does contain multiple parallel surfaces for the same responsibilities.
The highest leverage move is to collapse those parallel surfaces into one canonical path per concern and make everything else an explicit adapter, shim, or optional integration.
