# Topic Vocabulary v1

**Date:** 2026-07-16
**Status:** accepted

## Goal

This document provides a curated seed list of roughly ten topic slugs used in
the `topic:` field of YAML frontmatter across Bodai documentation. The
vocabulary is intentionally small and opinionated: it exists to keep the most
common documentation areas consistently labeled so they can be grouped,
filtered, and cross-referenced. Free-form values are **allowed** — a document
may use a `topic:` slug that is not in this seed list — but the frontmatter
validator will emit a **warning** for any slug it does not recognize, nudging
authors either to reuse an existing slug or to add a new one here via the
contribution workflow below.

## Seed List

| Slug | Definition |
|------|------------|
| `oneiric-config` | Oneiric layered configuration (defaults, settings/*.yaml, MAHAVISHNU\_* env vars). |
| `mcp-design` | MCP-first architecture, tool registration, server design. |
| `error-handling` | Exception hierarchy, retry, circuit breaker, dead-letter queue (ADR 003). |
| `storage-consolidation` | Akosha/Dhara/Session-Buddy storage ownership. |
| `memory-architecture` | Unified memory layer across Bodai components (ADR 005). |
| `adapter-architecture` | Engine adapter (Prefect/LlamaIndex/Agno/Pydantic-AI) patterns. |
| `adapter-registry` | Hybrid adapter registry with dynamic discovery (ADR 009). |
| `adapter-security` | Adapter security specification (ADR 010). |
| `adapter-tool-boundary` | Mahavishnu ↔ Dhara adapter-tool boundary (ADR 013). |
| `saga-pattern` | Saga coordinator for distributed transactions (ADR 007). |
| `zero-downtime-migration` | Zero-downtime SQLite-to-PostgreSQL migration (ADR 008). |
| `terminal` | iTerm2, MockTerminal, CrowTerminal, GenericShellWorker, workers/protocol.py. |
| `routing-composition` | Two-router composition, fitness feedback loop, peer affinity (ADR 011 / ADR 014). |
| `honcho-routing` | Honcho peer-model routing precedence (ADR 014). |
| `akosha-skills` | Akosha skill distillation system — pattern detection, conscious-agent skill library, skill embedding storage. |
| `learning-pipeline` | Skill distillation, conscious agent, pattern library (ADR 012). |
| `bodai-radar` | Bodai radar — cross-repo anomaly detection, OTel trace correlation, fitness feedback signals across the ecosystem. |
| `observability` | Bodai observability surface, EventBridge subscriber pattern, Phase 6. |
| `auth` | Auth standardization (Bodai auth spec), JWT, multi-provider. |
| `crackerjack-publish-auth` | PyPI publishing authentication layer for crackerjack — TrustedPublishingProvider (OIDC), EnvVarAuthProvider, KeyringAuthProvider. Part of the PyPIAuth abstraction. |
| `convergence-control-plane` | Convergence program C0-C7, umbrella plans. |
| `followups-index` | Index or summary of the docs/followups/ store — readme/README pages that aggregate session-buddy followup topics. |
| `worktree-management` | Worktree MCP dispatcher, isolation, planning. |
| `session-worktree-isolation` | Worktree-based session isolation pattern — concurrent Claude Code sessions running in separate git worktrees with bounded blast radius. |
| `persistence` | State persistence across checkpoints, session restarts, and subagent dispatch windows (covers git stash/rebase cycles, auto-checkpoint hooks, durable storage paths). |
| `lifecycle` | Wiring lifecycle for components, plans, and followups — drafted/active/partial/shipped/complete transitions, completion reports, plan-to-followup handoffs. |
| `plugin-standardization` | Claude Code plugin manifest, marketplace layout, slash command namespace, plugin validation scaffold (introduced for Bodai plugin rollout 2026-07-16). |
| `acp-server` | Mahavishnu ACP Server |
| `acp-v15-followups` | ACP v1.5 followups — items deferred from the v1.0 ACP server build plan. |
| `adapter-runtime-observability` | Adapter Runtime Observability v1.0 Implementation Plan |
| `agent-curation` | Agent curation strategy — rules for adding/archiving agents in the curated catalog (mycelium-core dedup, Bodai-stack relevance). |
| `agent-skill-modernization` | Agent & Skill Modernization Implementation Plan |
| `bodai-auth` | Bodai Inter-Service Authentication Standardization |
| `bodai-crow-http-server` | Bodai Crow HTTP MCP Server |
| `bodai-observability` | Bodai observability pattern — one subscriber, one bus; cross-component OTel correlation. |
| `code-indexing-integration` | Code Indexing Integration Plan |
| `completion-report-schema` | Completion Report Schema v1 Implementation Plan |
| `component-health` | Component-health CLI gap — overlap between ecosystem_status and per-component CLI probes. |
| `confidence-ceiling-gate` | Confidence Ceiling Gate v1.1 Implementation Plan |
| `config-consolidation` | Config Consolidation: Mahavishnu as Self-Contained Dev Environment |
| `constellation-tui` | Constellation TUI Implementation Plan |
| `crow-mcp-client` | Crow Adapter `mcp_client=None` Wiring — Bootstrap Followup |
| `decision-index` | Index of `.claude/decisions/` (repo-local decisions and follow-up trackers). |
| `dhara-crackerjack-bug-fixes` | Dhara-Crackerjack Critical Bug Fixes Implementation Plan |
| `dhara-key-prefixes` | Dhara key prefixes for ultracode integration — isolated top-level prefixes per persistence domain. |
| `dhara-serverless` | Dhara Serverless Implementation Plan |
| `dhara-substrate-extension` | Dhara Substrate Extension Plan |
| `dhara-substrate-implementation` | Dhara Substrate Implementation Plan |
| `fastmcp-3-upgrade` | FastMCP 3.x Ecosystem Inventory (2026-06-26) |
| `followups-lifecycle` | `docs/followups/` lifecycle — index, archive-on-completion, verified Status field. |
| `hatchet-adapter` | HatchetAdapter (P10) Implementation Plan |
| `license-false-intent-postmortem` | 2026-07-20 LICENSE False-Intent Incident: Postmortem and Forward Rules |
| `live-observe-presence` | Live Observe (Presence Over Gate) v1.0 Implementation Plan |
| `llm-routing-plan1` | LLM Routing Standardization — Plan 1: mcp-common LLM Module |
| `llm-routing-plan2` | LLM Routing Standardization — Plan 2: Downstream Migration |
| `m-approval-log` | M-APPROVAL-LOG Design Spec |
| `m-webhook-durable` | M-WEBHOOK-DURABLE Design Spec |
| `m-workflow-outcome` | M-WORKFLOW-OUTCOME Design Spec |
| `mcp-common-http-health-route-helper` | mcp-common `register_http_health_route` Helper |
| `mcpbase-migration` | MCP Server Family: MCPBaseSettings → OneiricMCPConfig Migration |
| `mcpretentious-removed` | mcpretentious terminal adapter removed — bootstrap followup documenting the fallback chain. |
| `mcpretentious-runtime-wiring` | Mcpretentious Runtime Wiring Implementation Plan |
| `mcpserver-settings-convention` | MCP Server Settings Convention — `OneiricMCPConfig` + `mcp-common` |
| `multi-backend-pty` | Multi-Backend PTY Implementation Plan |
| `multi-tenant-context-packs` | Multi-Tenant Context Packs v1.0 Implementation Plan |
| `opensearch-diverged-flags` | Diverged `OPENSEARCH_AVAILABLE` Flags — Architecture Followup |
| `pattern-learning-scaffolding` | Pattern Learning & Scaffolding Implementation Plan |
| `precommitment-hypothesis-lock` | Precommitment Hypothesis Lock v1.1 Implementation Plan |
| `project-scoped-sop-evolution` | Project-Scoped SOP Evolution v1.0 Implementation Plan |
| `quality-gate-repair` | Pyscn and Ty Quality Gate Repair Implementation Plan |
| `removed-scripts` | Removed scripts — policy for `required_scripts:` references that point at intentionally-uncommitted files. |
| `runpod-flash-pool` | RunPod Flash Pool Implementation Plan |
| `sb-checkpoint-stash-clobber-fix` | Session-Buddy Checkpoint Stash-Clobber Fix Implementation Plan |
| `session-archaeologist` | Session Archaeologist Implementation Plan |
| `session-buddy-extension` | Session-Buddy Extension Implementation Plan (Mahavishnu seam hardening) |
| `session-buddy-schema-alignment` | Session-Buddy v2/Legacy Schema Alignment Plan |
| `session-buddy-worktree-tools` | Session-Buddy MCP worktree tools |
| `session-worktree-defaults` | Per-session worktree isolation — defaults (off) and threat model. |
| `shared-frontmatter-validator` | Shared Frontmatter Validator |
| `skill-vs-agent` | Skill vs. agent strategy — when to write a skill, an agent, or neither. |
| `splashstand-oneiric` | Splashstand ACB → Oneiric Migration Plan |
| `style-sop` | Anti-AI-Flavor Style SOP v1.0 Implementation Plan |
| `technical-debt` | Technical debt roadmap — consolidated multi-PR-horizon items not tied to a single review. |
| `terminal-grid` | Terminal Grid Orchestration Implementation Plan |
| `test-matrix-followups` | Deferred MEDIUM/LOW findings from the `scripts/test_matrix.py` review. |
| `three-layer-self-heal` | Three-Layer Self-Heal v1.0 Implementation Plan |
| `three-zone-skill-pipeline` | Three-Zone Skill Pipeline v1.0 Implementation Plan |
| `tool-preference` | Mahavishnu tool preference policy — where tool-selection steering may live. |
| `track1-terminal-gap` | Track 1 — Terminal Gap Implementation Plan |
| `track2-openhands` | Track 2 — OpenHands Integration Implementation Plan |
| `track3-toad-tui` | Track 3 — Toad TUI (Textual + Rich) Implementation Plan |
| `track4-turbovec` | Track 4 — TurboVec Integration Implementation Plan |
| `ty-ignore-codes` | ty diagnostic codes for `# ty: ignore[...]` — rules for which code fits which boundary. |
| `unified-iterm2-applescript` | Unified iTerm2 AppleScript Integration |
| `vestigial-bs4-removal` | Remove Vestigial beautifulsoup4 from Mahavishnu Implementation Plan |
| `wave2b-a2a-worker` | Wave 2b: A2A Worker & Server Implementation Plan |
| `wire-up-contract` | Wire-up contract — process rule for ensuring built features are wired into apps and workflows. |
| `workflows` | Crackerjack coverage fan-out workflow — assign parallel test writers to independent packages. |
| `worktree-autoremove` | Worktree Prune-Merged CLI |

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
