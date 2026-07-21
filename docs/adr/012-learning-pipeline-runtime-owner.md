---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
decision_date: 2026-04-27
topic: learning-pipeline
---

# ADR 012: Learning Pipeline Runtime Owner

**Status:** Accepted

<!-- legacy status: **Status:** Accepted — see YAML frontmatter -->

**Date:** 2026-04-27
**Supersedes:** None

## Context

Phase 1B of the Bodai implementation plan requires a "learning pipeline runtime" — the owning process that executes the observe→store→retrieve→synthesize→review→activate→rollback stages. The plan flagged this as a blocking design decision with three options:

| Option | Description |
|--------|-------------|
| A: Prefect workflow | Learning pipeline as a scheduled Prefect flow |
| B: Mahavishnu worker | Dedicated worker in the existing pool |
| C: Standalone service | New Python process managed by Mahavishnu |

## Decision

**Mahavishnu internal async service** (a variant of Option B that does not use the worker pool).

The pipeline runs as an `asyncio`-based service within the `MahavishnuApp` process, following the same pattern as the existing `MemoryAggregator`:

- `asyncio.create_task` for periodic evidence collection
- `asyncio.gather` for concurrent stage execution
- Circuit breakers for external service calls (Akosha, Session-Buddy, Crackerjack)
- Local buffer fallback when external services are unavailable
- Graceful shutdown via `asyncio.Event`

## Rationale

1. **Prefect is not a runtime dependency.** Zero `@flow`/`@task` decorators, zero Prefect client imports in the codebase. Using Prefect would add a new runtime dependency for a linear pipeline that `asyncio` handles natively.

1. **The established pattern is asyncio, not worker pools.** `MemoryAggregator` demonstrates the exact pattern needed: periodic background tasks, concurrent HTTP calls to MCP services, circuit breakers, graceful degradation. No worker pool required.

1. **The pipeline stages are linear, not a DAG.** Observe→Store→Retrieve→Synthesize→Review→Activate is inherently sequential with I/O boundaries — the pattern `asyncio` was designed for.

1. **All external service access is already via httpx MCP calls.** No Prefect-specific adapter pattern is needed. The pipeline reuses the same HTTP-based MCP protocol used by `MemoryAggregator`, `otel_ingester`, and `content_ingester`.

1. **Worker pool competition (Option B concern) is avoided.** The pipeline does not execute user tasks — it collects evidence, retrieves patterns, and drafts skills. It uses its own async tasks, not pool workers.

## Consequences

- No new runtime dependencies added
- Pipeline lifecycle is tied to `MahavishnuApp` startup/shutdown
- Evidence collection rate is configurable via `learning.collection_interval_seconds`
- Pipeline can be disabled via `learning.enabled: false` in configuration
- Future migration to Prefect or standalone service is possible without changing the stage interfaces (they are protocol-based)
