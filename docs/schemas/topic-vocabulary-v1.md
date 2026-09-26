# Topic Vocabulary v1

**Date:** 2026-09-19 (extended)
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
| `oneiric-action-kit-adoption` | Oneiric action-kit promotion design — catalog of common primitives (HMAC, token gen, schema validation, retries, redaction, HTTP probing, serialization, compression, hashing, data transforms) tracked for migration out of project-specific implementations. |
| `oneiric-action-kit-promotion` | Oneiric action-kit promotion implementation — concrete plan to lift the catalog items in `oneiric-action-kit-adoption` into `oneiric.actions` so consumers can stop re-implementing them. |
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
| `bodai-conformance` | Bodai ecosystem conformance — cross-repo consistency checks, naming/port/version invariants across the five components (Mahavishnu, Akosha, Dhara, Session-Buddy, Crackerjack). |
| `bodai-crow-http-server` | Bodai Crow HTTP MCP Server |
| `bodai-observability` | Bodai observability pattern — one subscriber, one bus; cross-component OTel correlation. |
| `claude-env-remediation` | Claude Code environment audit remediation — drift/dead-config/bloat cleanup across `~/.claude/` and per-project `.claude/` (see `docs/plans/2026-08-24-claude-env-audit-remediation.md`). |
| `clone-refactor-wireup` | Clone-refactor MCP tool wireup — replaces aspirational PR-shaped DAG with git-tree DAG; UUID7 `refactor_job_id`; MCPStateBackend persistence (no Dhara); per-step durability + typed `GitCommitTransient`/`GitCommitPermanent` exceptions; cluster-claim semantics; operator-driven revert (no auto-revert) (see `docs/superpowers/plans/2026-09-25-clone-refactor-wireup.md`). |
| `gitignore-conformance` | Shared Bodai `.gitignore` snippet — canonical pattern set covering oneiric caches, `.crackerjack/`, `.bak`, `coverage.json` and other runtime artifacts that should be excluded from every Bodai component. |
| `bodai-mcp-surface-standardization` | Bodai Core MCP Surface Standardization — uniform MCP tool surface across the Mahavishnu core ecosystem. |
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
| `mcp-deps-crackerjack-loop` | `*-mcp` dep refresh + crackerjack loop — refresh `oneiric`/`mcp-common` in `*-mcp` repos via `crackerjack run -p minor`; one-line annotated-tag patch in `publish_manager.py`. |
| `mcp-lifespan-startup-ordering` | Mahavishnu MCP `/health` Lifespan Bypass — `/health` must respond before lifespan startup completes (regression test for ordering). |
| `mcp-routing` | Bodai MCP routing pattern — secrets in shell env, MCP config in per-project `.mcp.json`, agents scoped to project, plugins preferred over bare URL (see `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`). |
| `mcp-stub-activation` | MCP stub activation — turning PyPI name-reservation scaffolds (`archive-org-mcp`, `medium-mcp`, `scapy-mcp`) into working servers, plus the `ecosystem.yaml` registry consolidation that makes registration verifiable. |
| `mcp-tool-profile-adoption` | MCP Tool Profile Adoption Across Bodai Ecosystem — tiered dynamic tool loading in `*-mcp` repos (`full`/`standard`/`minimal`). |
| `mcpbase-migration` | MCP Server Family: MCPBaseSettings → OneiricMCPConfig Migration |
| `mcpretentious-removed` | mcpretentious terminal adapter removed (2026-08-10 wave, commit `34f61672`) — bootstrap followup documenting the fallback chain. *Topic migrated — see `terminal-adapter-architecture` for the live tmux/mock/crow stack.* |
| `mcpretentious-runtime-wiring` | Mcpretentious Runtime Wiring Implementation Plan. *Historical — adapter removed in 2026-08-10 wave; see `terminal-adapter-architecture`.* |
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
| `storage-abstraction` | Worktree + cache storage abstraction (ADR 015 family) — single substrate spanning local FS, Session-Buddy, and S3; supersession chain `015 → v2 → v3 → v4`. |
| `storage-abstraction-review` | Multi-agent review of `storage-abstraction` (ADR 015) — synthesis of findings that informed the v2/v3/v4 supersession chain; historical record only. |
| `streaming-tar-evolution` | Streaming tar.zst bundle format for worktree transfers (ADR 016, Phase 3-4 evolution) — phased rollout of end-to-end streaming serialization replacing the in-memory stopgap path. |
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
| `worktree-autoremove-v4-followup` | Followups from the worktree-prune-merged v4 retrospective — items deferred when the v4 cut landed, tracked separately for the next iteration. |
| `scapy-mcp-integration-review` | Multi-agent review of scapy-mcp integration (ADR 0016 review artifact). |
| `mcp-enrichment-posture` | MCP enrichment posture — how scapy-mcp integrates with the broader Bodai MCP surface (ADR 0016). |
| `bodai-tui-shell-surface` | Bodai admin shell + dashboard TUI surface (AdminShell subclass pattern, monitor --tui, shell polish). |
| `crackerjack-scripts-examples-coverage` | Crackerjack script + example coverage — which scripts/examples have tests, which are missing. |
| `durable-local-workers` | Durable worker lifecycle via tmux/PTY adapters (session persistence across crash/restart). |
| `jot-capture` | Jot subsystem: capture primitive (recording raw input into the jot store). |
| `jot-inbox` | Jot subsystem: inbox primitive (queued items awaiting triage). |
| `jot-read` | Jot subsystem: read primitive (querying captured jot items). |
| `jot-drain` | Jot subsystem: drain operation (moving items from inbox to long-term store). |
| `jot-drain-polish` | Jot subsystem: drain operation polish (edge cases, error paths, idempotency). |
| `mcp-registrar` | MCP registrar subsystem — server-side agent/skill registration catalog (list_agents/get_agent, list_skills/get_skill, ed25519 signature flow). |
| `worker-readiness` | Worker readiness probing — liveness/readiness checks before task dispatch (gates dispatch until the worker reports ready). |
| `agno-memory-field-validator-silent-skip` | Agno memory field validator silently skipping malformed records (defect followup; validation should raise, not skip). |
| `ai-dep-group-transitive-bloat` | `ai` PEP 735 dep group pulling more than declared (transitive bloat audit; tighten `project.optional-dependencies`). |
| `akosha-hnsw-on-duckdb` | Akosha HNSW index creation failing on DuckDB backend (defect followup; needs DuckDB-compatible HNSW or alternative). |
| `audit-orphans-residual-caller-detection` | `scripts/audit_orphans.py` not detecting residual callers of recently-added symbols (false negatives after a feature is wired). |
| `backup-cli-broad-typer-exit` | Backup CLI `typer.Exit` raised too broadly, masking actual errors behind generic exit codes. |
| `beartype-pytest-cov-py314` | beartype + pytest-cov interaction broken on Python 3.14 (decorator interferes with coverage instrumentation). |
| `bodai-openclaw-hermes-inspired-portfolio` | Bodai "OpenClaw / Hermes-inspired" agent portfolio design (cross-cutting AI agent portfolio, post-A2A review). |
| `changepoint-two-stage-polish` | Change-point detection two-stage algorithm polish (edge cases, false-positive suppression). |
| `changepoint-two-stage-warn-confirm` | Change-point detection two-stage warn-then-confirm UX flow (defer destructive action behind explicit confirmation). |
| `crackerjack-c-wire-plan` | Crackerjack C hook execution path wiring plan (low-level integration of the C runner with the hook orchestrator). |
| `d-lock` | D-lock distributed locking primitive (lockfile-based coordination across processes; complementary to `precommitment-hypothesis-lock`). |
| `flowscape` | FlowScape product/feature (workflow landscape visualization — graph of plans/followups/ADRs across repos). |
| `flowscape-v1-bootstrap` | FlowScape v1 bootstrap plan (initial implementation milestone; Phase 1 surface + Phase 2 polish). |
| `mahavishnu-pool-error-code-attribute` | Mahavishnu pool missing `error_code` attribute on result envelopes (downstream consumers can't programmatically distinguish failure modes). |
| `merge-semantic-duration-instrumentation` | Merge semantic duration instrumentation — timing merge operations by semantic phase (base / ours / theirs / result), surfaced as OTel spans. |
| `metrics-schema-confidence-dead-parameter` | Metrics schema `confidence` parameter dead code (unused input; remove from API surface). |
| `metrics-schema-no-input-validation` | Metrics schema missing input validation on metric definitions (negative values, NaN, out-of-range buckets). |
| `metrics-schema-p50-formula` | Metrics schema p50 percentile formula correctness (off-by-one or interpolation bug in the histogram reader). |
| `permissions-accessibility-prompt` | Permissions API accessibility prompt gap (screen reader / keyboard navigation missing on the runtime grant flow). |
| `permissions-dead-cache-fields` | Permissions cache retains fields from removed permission types (stale data outliving its source schema). |
| `permissions-mutable-dataclass` | Permissions dataclass should be immutable (mutable default state; convert to `frozen=True`). |
| `phase3-streaming-tar-plan` | Phase 3 streaming-tar implementation plan — large-archive streaming without full extraction (companion to `streaming-tar-phase3` design). |
| `ruff-cleanup-waves` | Crackerjack ruff cleanup waves — batch lint-fix passes after a rule addition (one wave per rule, gated on green CI). |
| `serverless-readiness-and-substitution` | Bodai serverless readiness assessment + component substitution strategy (which Bodai components can run serverless; which need preconditions). |
| `serverless-readiness-precondition-fixes` | Serverless readiness Phase 1 prerequisite fixes (Python/build/runtime blockers — cold-start, signal handlers, filesystem assumptions). |
| `settle-semantic-merge` | Settle subsystem semantic 3-way merge (worker output vs base vs theirs; `git merge-file`-backed conflict resolution for bindings). |
| `streaming-tar-phase3` | Streaming tar Phase 3 design (large-archive streaming without full extraction; supersedes the in-memory stopgap path from ADR 016). |
| `tier2-hyperbolic-embeddings` | Tier 2 math initiative: hyperbolic-space embeddings for Akosha (negative-curvature representation for hierarchical similarity). |
| `tier2-multi-metric-drift` | Tier 2 math initiative: multi-metric drift detection (Akosha fitness — composite signal across p50, error rate, queue depth). |
| `tier2-optimal-transport` | Tier 2 math initiative: optimal-transport-based similarity (Wasserstein-distance cross-domain comparison). |
| `tier2-phase-d-cross-repo` | Tier 2 Phase D: cross-repo Akosha detector wiring (deferred followup — needs `phase-8-adopted-and-stable` unblock). |
| `tui` | Original TUI design (2026-04-09 pre-Track 3 era) — generic Textual + Rich framework; superseded by `track3-toad-tui`. |
| `websocket-broadcaster-default` | WebSocket broadcaster default config/initialization gap (server should come up broadcasting on standard channels without explicit subscribe calls). |
| `worker-status-isoformat-crash` | Worker status serialization crashes on non-ISO timestamps (e.g., epoch ints, locale-formatted strings) — needs tolerant parsing. |

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
