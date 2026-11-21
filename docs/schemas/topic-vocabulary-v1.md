---
title: Oneiric Topic Vocabulary
status: active
role: canonical
topic: lifecycle
last_reviewed: 2026-11-02
---

# Topic Vocabulary v1

**Date:** 2026-07-16
**Status:** accepted <!-- legacy status — see YAML frontmatter -->

## Goal

This document provides a curated seed list of topic slugs used in
the `topic:` field of YAML frontmatter across Bodai documentation. The
vocabulary is intentionally small and opinionated: it exists to keep the most
common documentation areas consistently labeled so they can be grouped,
filtered, and cross-referenced. Free-form values are **allowed** — a document
may use a `topic:` slug that is not in this seed list — but the frontmatter
validator will emit a **warning** for any slug it does not recognize, nudging
authors either to reuse an existing slug or to add a new one here via the
contribution workflow below. The validator loads the packaged oneiric seed
list and unions it with this repo-local file, so this file acts as the
supplemental additions layer for Mahavishnu-specific topics.

## Seed List

| Slug | Definition |
|------|------------|
| `oneiric-config` | Oneiric layered configuration (defaults, settings/*.yaml, MAHAVISHNU\_* env vars). |
| `mcp-design` | MCP-first architecture, tool registration, server design. |
| `error-handling` | Exception hierarchy, retry, circuit breaker, dead-letter queue (ADR 003). |
| `storage-consolidation` | Akosha/Oneiric/Session-Buddy storage ownership. |
| `memory-architecture` | Unified memory layer across Bodai components (ADR 005). |
| `adapter-architecture` | Engine adapter (Prefect/LlamaIndex/Agno/Pydantic-AI) patterns. |
| `adapter-registry` | Hybrid adapter registry with dynamic discovery (ADR 009). |
| `adapter-security` | Adapter security specification (ADR 010). |
| `adapter-tool-boundary` | Mahavishnu ↔ adapter-registry tool boundary (ADR 013). |
| `saga-pattern` | Saga coordinator for distributed transactions (ADR 007). |
| `zero-downtime-migration` | Zero-downtime SQLite-to-PostgreSQL migration (ADR 008). |
| `terminal` | iTerm2, MockTerminal, CrowTerminal, GenericShellWorker, workers/protocol.py. |
| `worker-output-compaction` | Tool-output compaction for LLM worker sessions — RTK-style output filters, the context-composition measurement that sizes the lever, and the agent hook seam that keeps compacted bytes in the cached request prefix. |
| `routing-composition` | Two-router composition, fitness feedback loop, peer affinity (ADR 011 / ADR 014). |
| `honcho-routing` | Honcho peer-model routing precedence (ADR 014). |
| `learning-pipeline` | Skill distillation, conscious agent, pattern library (ADR 012). |
| `observability` | Bodai observability surface, EventBridge subscriber pattern, Phase 6. |
| `auth` | Auth standardization (Bodai auth spec), JWT, multi-provider. |
| `convergence-control-plane` | Convergence program C0-C7, umbrella plans. |
| `worktree-management` | Worktree MCP dispatcher, isolation, planning. |
| `persistence` | State persistence across checkpoints, session restarts, and subagent dispatch windows (covers git stash/rebase cycles, auto-checkpoint hooks, durable storage paths). |
| `lifecycle` | Wiring lifecycle for components, plans, and followups — drafted/active/partial/shipped/complete transitions, completion reports, plan-to-followup handoffs. |
| `plugin-standardization` | Claude Code plugin manifest, marketplace layout, slash command namespace, plugin validation scaffold (introduced for Bodai plugin rollout 2026-07-16). |
| `resolver` | Oneiric candidate discovery, precedence, explainability, and universal component resolution. |
| `lifecycle-hooks` | Oneiric activation, health-check, hot-swap, rollback, and cleanup hook contracts. |
| `decision-index` | `.claude/decisions/` README index file (canonical decision inventory). |
| `deployability-discipline` | Bodai deployability rule: standalone-by-default, harness-agnostic interface, serverless-deployable runtime. See `oneiric/docs/adr/0001-deployability-discipline.md` (proposed 2026-09-26). |
| `acp-v15-followups` | Mahavishnu topic: acp-v15-followups. |
| `adapter-composition` | Mahavishnu topic: adapter-composition. |
| `agno-failover-gateway` | Mahavishnu topic: agno-failover-gateway. |
| `agno-llm-routing` | Mahavishnu topic: agno-llm-routing. |
| `agno-memory-field-validator-silent-skip` | Mahavishnu topic: agno-memory-field-validator-silent-skip. |
| `ai-dep-group-transitive-bloat` | Mahavishnu topic: ai-dep-group-transitive-bloat. |
| `archived-requirements-registry` | Mahavishnu topic: archived-requirements-registry. |
| `backup-cli-broad-typer-exit` | Mahavishnu topic: backup-cli-broad-typer-exit. |
| `beartype-pytest-cov-py314` | Mahavishnu topic: beartype-pytest-cov-py314. |
| `bifrost-anthropic-baseurl-cutover` | Mahavishnu topic: bifrost-anthropic-baseurl-cutover. |
| `bifrost-cache-eviction-and-threshold` | Mahavishnu topic: bifrost-cache-eviction-and-threshold. |
| `bifrost-cache-wiring` | Mahavishnu topic: bifrost-cache-wiring. |
| `bifrost-cli-consolidation` | Mahavishnu topic: bifrost-cli-consolidation. |
| `bifrost-complexity-accounting` | Mahavishnu topic: bifrost-complexity-accounting. |
| `bifrost-gateway-wiring` | Mahavishnu topic: bifrost-gateway-wiring. |
| `bifrost-mcp-skills-aggregation` | Mahavishnu topic: bifrost-mcp-skills-aggregation. |
| `bifrost-minimax-routing` | Mahavishnu topic: bifrost-minimax-routing. |
| `bifrost-oneiric-gateway-adapter` | Mahavishnu topic: bifrost-oneiric-gateway-adapter. |
| `bifrost-readiness-budget` | Mahavishnu topic: bifrost-readiness-budget. |
| `bodai-ecosystem-candidates` | Mahavishnu topic: bodai-ecosystem-candidates. |
| `bodai-task-system-v1-1` | Mahavishnu topic: bodai-task-system-v1-1. |
| `bodai-tui-shell-surface` | Mahavishnu topic: bodai-tui-shell-surface. |
| `changepoint-two-stage-polish` | Mahavishnu topic: changepoint-two-stage-polish. |
| `cli-deprecation-drift` | Mahavishnu topic: cli-deprecation-drift. |
| `clone-refactor-wireup` | Mahavishnu topic: clone-refactor-wireup. |
| `config-consolidation` | Mahavishnu topic: config-consolidation. |
| `config-that-nobody-reads` | Mahavishnu topic: config-that-nobody-reads. |
| `content-quality` | Mahavishnu topic: content-quality. |
| `control-plane-consolidation` | Mahavishnu topic: control-plane-consolidation. |
| `crow-mcp-client` | Mahavishnu topic: crow-mcp-client. |
| `decision-adapter-category` | Mahavishnu topic: decision-adapter-category. |
| `delete-all-legacy-named-code` | Mahavishnu topic: delete-all-legacy-named-code. |
| `demo-surface` | Mahavishnu topic: demo-surface. |
| `event-sourced-otel` | Mahavishnu topic: event-sourced-otel. |
| `followups-index` | Mahavishnu topic: followups-index. |
| `jot-read` | Mahavishnu topic: jot-read. |
| `legacy-mcp-server-decommissioning` | Mahavishnu topic: legacy-mcp-server-decommissioning. |
| `lint-coverage-gap` | Mahavishnu topic: lint-coverage-gap. |
| `mahavishnu-niche` | Mahavishnu topic: mahavishnu-niche. |
| `mahavishnu-pool-error-code-attribute` | Mahavishnu topic: mahavishnu-pool-error-code-attribute. |
| `mcp-dispatch-liveness` | Mahavishnu topic: mcp-dispatch-liveness. |
| `mcp-enrichment-posture` | Mahavishnu topic: mcp-enrichment-posture. |
| `mcp-profile-groups` | Mahavishnu topic: mcp-profile-groups. |
| `mcp-stub-activation` | Mahavishnu topic: mcp-stub-activation. |
| `mcp-substrate-implementation` | Mahavishnu topic: mcp-substrate-implementation. |
| `mcp-substrate-rewire` | Mahavishnu topic: mcp-substrate-rewire. |
| `mcp-tool-disambiguation` | Mahavishnu topic: mcp-tool-disambiguation. |
| `mcpretentious-removed` | Mahavishnu topic: mcpretentious-removed. |
| `mcpserver-settings-convention` | Mahavishnu topic: mcpserver-settings-convention. |
| `merge-semantic-duration-instrumentation` | Mahavishnu topic: merge-semantic-duration-instrumentation. |
| `metrics-schema` | Mahavishnu topic: metrics-schema. |
| `model-evaluation` | Mahavishnu topic: model-evaluation. |
| `opensearch-diverged-flags` | Mahavishnu topic: opensearch-diverged-flags. |
| `otel-producer-reporting` | Mahavishnu topic: otel-producer-reporting. |
| `permissions` | Mahavishnu topic: permissions. |
| `quality-gate-complexity` | Mahavishnu topic: quality-gate-complexity. |
| `registry-paths` | Mahavishnu topic: registry-paths. |
| `ruff-cleanup-post-regrowth` | Mahavishnu topic: ruff-cleanup-post-regrowth. |
| `scapy-mcp-integration-review` | Mahavishnu topic: scapy-mcp-integration-review. |
| `shared-frontmatter-validator` | Mahavishnu topic: shared-frontmatter-validator. |
| `shared-oneiric-substrate` | Mahavishnu topic: shared-oneiric-substrate. |
| `storage-abstraction-review` | Mahavishnu topic: storage-abstraction-review. |
| `streaming-tar-evolution` | Mahavishnu topic: streaming-tar-evolution. |
| `substrate-calltime-rewire` | Mahavishnu topic: substrate-calltime-rewire. |
| `substrate-otel` | Mahavishnu topic: substrate-otel. |
| `task-workflow-backlink` | Mahavishnu topic: task-workflow-backlink. |
| `tier2-hyperbolic-embeddings` | Mahavishnu topic: tier2-hyperbolic-embeddings. |
| `tier2-multi-metric-drift` | Mahavishnu topic: tier2-multi-metric-drift. |
| `tier2-optimal-transport` | Mahavishnu topic: tier2-optimal-transport. |
| `tier2-phase-d-cross-repo` | Mahavishnu topic: tier2-phase-d-cross-repo. |
| `ty-only-migration` | Mahavishnu topic: ty-only-migration. |
| `type-checking` | Mahavishnu topic: type-checking. |
| `websocket-broadcaster-default` | Mahavishnu topic: websocket-broadcaster-default. |
| `worker-dispatch-trustworthiness` | Mahavishnu topic: worker-dispatch-trustworthiness. |
| `worker-status-isoformat-crash` | Mahavishnu topic: worker-status-isoformat-crash. |
| `yaml-backed-model-routing` | Mahavishnu topic: yaml-backed-model-routing. |

## Contribution Workflow

Anyone can add a topic to this list via a normal documentation PR — **no schema
amendment is needed**. To add a topic, edit this file's seed list table in a PR
that includes:

- **Slug** — kebab-case, matching `^[a-z][a-z0-9-]{2,40}$`.
- **One-line definition** — a concise description of what the topic covers.
- **Area association** — the ecosystem area, component, or ADR the topic maps to.

The validator rejects malformed slugs (see the validation rules below), so a PR
that introduces a slug not matching the pattern will fail validation before it
can be merged.

## Validation Rules

- Slug is **kebab-case**.
- Slug **length is 3-40 characters**.
- Slug **starts with a letter** (matches `^[a-z][a-z0-9-]{2,40}$`).
- Slugs **must be unique** within this file.
- Slug **must not be a reserved word**. The reserved words are:
  `draft`, `active`, `partial`, `shipped`, `complete`, `canonical`,
  `implementation`, `umbrella`, `historical`, `superseded`.

## Cross-Reference

See [document-frontmatter-v1.md](document-frontmatter-v1.md) for the frontmatter
contract that consumes this vocabulary.
