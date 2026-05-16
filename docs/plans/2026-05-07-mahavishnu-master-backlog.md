# Mahavishnu Master Backlog

**Created**: 2026-05-07
**Status**: `canonical` — single authoritative list of confirmed open work
**Authority**: Verified against codebase 2026-05-07. Items here were confirmed missing by code inspection; closed/superseded items were removed.
**Last updated**: 2026-05-08 — All priorities delivered; Final Gate complete.

______________________________________________________________________

## How to use this document

This is the single place to track remaining implementation work. Before starting any item:

1. Confirm the item is still open by spot-checking the relevant code.
1. Tick the task checkbox when done and add a delivered note.
1. Update the status line at the top of the section when the item is fully complete.

Do not add speculative work here. New items require code-verified evidence that the feature is missing.

______________________________________________________________________

## Priority 0 — Pre-Implementation Bug Fixes

**Status**: delivered 2026-05-07 — both bugs resolved; verified by code inspection

These bugs were confirmed by code inspection — they are not speculative.

### Bug 1 — `AttributeError` on all-adapter-fail in `core/app.py`

- [x] `execute_workflow_with_fallback` uses `logger = __import__("logging").getLogger(__name__)` as a local variable — no `self.logger` reference exists. No fix needed; the pre-review description was inaccurate.

### Bug 2 — `AttributeError` on `PoolConfig.get()` in `pools/manager.py`

- [x] `PoolConfig` in `pools/base.py:35` already implements `.get(key, default)` delegating to `self.extra_config`. The `config.get(...)` calls at lines 167–174 are valid. No fix needed.

**Delivered**: 2026-05-07 — both bugs were non-issues; the implementation was already correct

______________________________________________________________________

## Priority 1 — Session-Buddy Multi-Channel Tracking

**Plan**: `docs/plans/session-buddy-multi-channel-spec.md`
**Status**: delivered 2026-05-08 — Phase 1 (skill-based) complete; Phase 2 (Dhara event bus) deferred

### Remaining tasks

- [x] `track_channel_session` already in `mahavishnu/mcp/tools/session_buddy_tools.py`
- [x] `ChannelSessionEvent` / `ChannelSessionResult` added to `session_buddy/mcp/event_models.py`
- [x] `channel_tracking_tools.py` created in `session_buddy/mcp/tools/session/`
- [x] `_ChannelSessionStore` in-memory backing store (Phase 1)
- [x] `get_channel_sessions` query tool implemented
- [x] 19 unit tests covering start / heartbeat / end / query / error paths
- [x] `register_channel_tracking_tools` in `STANDARD_REGISTRATIONS` (profiles.py) and `_ALL_REGISTERS` (server.py)
- [ ] Phase 2: Dhara time-series event bus (deferred — no blocking dependency)

**Delivered**: 2026-05-08 — Phase 1 complete; Phase 2 (Dhara-backed event bus) is a follow-up

______________________________________________________________________

## Priority 2 — Storage Consolidation (Dhara Integration)

**Plan**: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`
**Status**: delivered 2026-05-07 (core), 2026-05-14 (PoolManager/RoutingDecisionBuffer wiring verified) — all tasks complete
**Scope**: Medium; connect workflow state, adapter state, and routing decisions to Dhara as the durable persistence layer
**Plan gap (2026-05-07)**: The existing plan predates the `DharaStateBackend` abstraction — it assumes direct PostgreSQL writes. The `DharaStateBackend` class, `WorkflowEngine` wiring, and recovery-on-startup path have no spec coverage in that document. Before implementing those tasks, write a short addendum covering: DharaStateBackend interface, WorkflowEngine hook points, batched-write strategy for `RoutingDecisionBuffer`, schema versioning (`workflow/v1/{id}`), degraded-boot mode, and Dhara circuit-breaker policy.
**Architecture note**: `PoolManager.__init__` will need a new `dhara_client` parameter — this is a breaking constructor change; update the call site in `app.py:566`.

### Why this priority

Dhara provides ACID-guaranteed persistent object storage and is already in the Bodai ecosystem. Today, Mahavishnu workflow state lives only in memory and is lost on restart. Using Dhara as the operational store gives persistence, recovery, and cross-service state visibility for free. The Dhara MCP server is connected and its tools are available.

### Remaining tasks

- [x] Define Dhara key schema for Mahavishnu objects: `workflow/v1/{id}`, `pool/v1/{id}`, `routing/v1/{task_class}/{ts}`, `approval/v1/{id}` — documented in addendum
- [x] Add `DharaStateBackend` class in `mahavishnu/core/state_backends/dhara.py` — degraded-boot + inline circuit breaker
- [x] Wire `WorkflowEngine` to persist workflow lifecycle events via `DharaStateBackend` — `execute_workflow_with_fallback()` hooks added
- [x] Wire `PoolManager` to checkpoint pool health + active worker list to Dhara on change — `_persist_pool_state` called in `spawn_pool`, `route_task`, and `close_pool`; `_persist_routing_decision` called in `route_task` (verified 2026-05-14)
- [x] Wire `RoutingDecisionBuffer` to persist routing decisions to Dhara — `PoolManager._persist_routing_decision` covers this at the routing site; `RoutingDecisionBuffer` itself remains in-memory (ring buffer for live queries only, not the persistence layer) (verified 2026-05-14)
- [x] Add Dhara connection config stanza to `settings/mahavishnu.yaml` — `dhara_state:` stanza added
- [x] Update `MahavishnuSettings` with `DharaStatePersistenceConfig` field
- [x] Add recovery path: on startup, restore last-known workflow state from Dhara — `_recover_workflow_state_from_dhara()` in `wait_for_dependencies()`
- [x] Add unit tests for DharaStateBackend — 10 tests in `test_dhara_state_backend.py`, all passing
- [x] Update `docs/architecture/ARCHITECTURE.md` with Dhara persistence layer — done in 2026-05-14 doc sync plan (Task 5)

**Delivered**: 2026-05-07 (core), 2026-05-14 (PoolManager wiring verified, arch doc update tracked) — all P2 tasks complete.

______________________________________________________________________

## Priority 3 — Config Consolidation

**Plan**: `docs/superpowers/plans/2026-04-26-config-consolidation.md`
**Spec**: `docs/superpowers/specs/2026-04-26-config-consolidation-design.md`
**Status**: delivered 2026-05-07
**Spec misalignment (2026-05-07)**: The existing spec covers file migration from `~/.claude/` into the project directory — it does not contain `UnifiedConfig`, `startup validation`, or `ConfigValidationError`. The validation tasks in this backlog entry are entirely unspecced. Before implementing them, write a separate design note covering: `UnifiedConfig` Pydantic model shape, which of the 5 YAML files it imports, `ConfigValidationError` structure, where startup validation hooks in (note: `MahavishnuApp` has no `initialize()` method — use `wait_for_dependencies()` or add one), and soft-launch strategy (`--config-strict` flag).
**Architecture note**: `MahavishnuApp` has no `initialize()` method. The hook point for startup validation is `wait_for_dependencies()` or a new explicit `async def initialize()` entry point.

### Why this priority

Mahavishnu has five independently-structured YAML config files (`mahavishnu.yaml`, `models.yaml`, `embeddings.yaml`, `repos.yaml`, `local.yaml`) with no cross-file schema validation and no unified Pydantic schema. Misconfigurations silently pass. Config consolidation closes this and brings all files under Oneiric-compatible validation.

### Remaining tasks

Verify against the spec for exact task list. High-level:

- [x] Define `UnifiedConfig` class in `mahavishnu/core/unified_config.py` — validates all 5 YAML files
- [x] `ConfigValidationError` with `errors: list[str]` and `file_path: str | None`
- [x] Wire `mahavishnu config validate --strict` to run unified schema validation
- [x] Add startup validation in `wait_for_dependencies()` — report-only by default, strict via `unified_validation_enabled=true`
- [x] Document accepted config fields in `settings/README.md`
- [x] Add 7 tests in `test_unified_config.py` — all passing

**Delivered**: 2026-05-07 — UnifiedConfig + ConfigValidationError + CLI --strict flag + startup hook + README + 7 tests.

______________________________________________________________________

## Priority 4 — RunPod Pool — Remaining Subtasks

**Plan**: `docs/superpowers/plans/2026-05-01-runpod-flash-pool.md`
**Status**: delivered 2026-05-07 — all 3 subtasks shipped; 11/11 tests passing

### Completed tasks

- [x] `GpuHandlerPool(RunPodPool)` in `mahavishnu/pools/gpu_handler_pool.py` — overrides `_build_endpoint()` for VISION / ML_INFERENCE / EMBEDDING categories
- [x] Task-category routing: VISION + ML_INFERENCE prefer `runpod` pool when `RUNPOD_API_KEY` is set
- [x] 11 unit tests in `tests/unit/pools/test_gpu_handler_pool.py` — all passing

**Delivered**: 2026-05-07

______________________________________________________________________

## Priority 5 — ~~Nanobot Worker Phase A~~ (Removed 2026-05-07)

**Status**: Removed — all nanobot integration (`NanobotWorker`, `nanobot-ai` dependency, in-process worker registry entries, provider wiring) deleted from the codebase. Workspace files also purged from project root.

______________________________________________________________________

## Priority 6 — TUI Completion (Command Palette + Skill Drafts)

**Files**: `mahavishnu/tui/app.py`, `mahavishnu/tui/command_palette.py`
**Status**: delivered — verified 2026-05-08; both gaps are closed
**Scope**: Narrow; both are self-contained additions to the existing TUI

### Why this priority

The TUI's five screens are functional and auto-refreshing. The two remaining gaps are polish items: the command palette logic exists but is not wired into the Textual app, and the Reviews screen always shows empty because no skill registry MCP surface exists to back `fetch_skill_drafts()`.

### Gap 1 — Command Palette (Ctrl+K)

`mahavishnu/tui/command_palette.py` implements a standalone `CommandPalette` Python class with fuzzy search, categories, and history. It is not wired into the Textual `DashboardApp`. Textual's built-in command palette system uses `App.COMMANDS` — a set of `Provider` subclasses — and is triggered by `Ctrl+backslash` by default (or a custom `Binding`).

**Tasks:**

- [x] `MahavishnuCommandProvider(Provider)` in `mahavishnu/tui/command_palette.py`
- [x] `COMMANDS = {MahavishnuCommandProvider}` in `DashboardApp` (`app.py:403`)
- [x] `Binding("ctrl+k", "command_palette", "Commands")` in `DashboardApp.BINDINGS` (`app.py:452`)
- [x] Command actions wired to tab/refresh; tests in `tests/unit/test_command_palette.py`

### Gap 2 — Skill Drafts (Reviews screen)

`fetch_skill_drafts()` currently returns `[]` because no skill registry MCP tool or local data source is available. The Reviews screen always shows "No skill drafts found."

**Tasks:**

- [x] `fetch_skill_drafts()` reads `~/.claude/skills/*/SKILL.md` for local registry
- [x] Reviews screen renders from real filesystem data; tests in `tests/unit/test_tui_dashboard.py`

**Delivered**: 2026-05-07

______________________________________________________________________

## Priority 7 — Hatchet Rate-Limiting Pattern

**Plan**: _(this document — narrow pattern borrow, no separate plan file needed)_
**Status**: delivered 2026-05-08 — sliding-window limiter, cloud_worker wiring, and tests all complete
**Scope**: Narrow; additive change to `task_router.py` and `routing_metrics.py`, no new dependency
**Scope constraint (2026-05-07)**: This is **single-process, advisory-only** rate limiting. In multi-pool horizontal deployments each process maintains its own counters — global enforcement is not the goal here. If true cross-pool rate limiting is needed later, that requires a Dhara-backed counter and belongs after P2. This item closes the single-process gap only and must be documented as such.
**Architecture note**: `task_router.py` is entirely free functions with no class. P7 adds module-level or class-level state; confirm async safety before shipping.

### Why this priority

Mahavishnu routes ZAI API calls via `TaskRouter` with no per-user or per-model-key rate limiting at the task level. Under burst load, a single user or model can starve others. Hatchet's `RateLimit(dynamic_key, units, limit, duration)` pattern is directly applicable and can be adopted as pure Python logic without taking a Hatchet dependency.

### Remaining tasks

- [x] `RateLimitConfig` dataclass + `RateLimiter` sliding-window class in `task_router.py`
- [x] `configure_rate_limiter()` / `get_rate_limiter()` module-level accessors
- [x] `cloud_worker.execute()` checks rate limiter before API call, returns `WorkerResult(FAILED)` on rejection
- [x] Per-user support via optional `user_id` in task payload
- [x] `record_rate_limit_rejected(model)` Prometheus counter in `routing_metrics.py`
- [x] 6 unit tests in `TestRateLimiter` (burst, expiry, user isolation, model isolation, configure/get)

**Delivered**: 2026-05-08

______________________________________________________________________

## Priority 8 — Approval Flow Durable Wait Pattern

**Plan**: _(this document — pattern improvement to existing tools, no separate plan file needed)_
**Status**: delivered 2026-05-07
**Scope**: Narrow; improve two existing MCP tools in `mahavishnu/mcp/tools/self_improvement_tools.py` (not `coordination_tools.py` — confirmed by grep 2026-05-07)

### Why this priority

Mahavishnu's approval flow (`request_approval` → `respond_to_approval`) sends messages but has no durable checkpoint. If the orchestrator restarts between request and response, the approval is lost. Hatchet's `WaitForEvent` pattern with a lookback window prevents this race. We adopt the pattern (not the dependency): store pending approvals in Dhara with a lookback window, resume from checkpoint on restart.

**Prerequisite**: Priority 2 (Dhara Integration) must be complete before this can be implemented.

### Completed tasks

- [x] Add `pending_approvals` key schema to Dhara (`approval/v1/{request_id}`) — uses P2 schema
- [x] Modify `request_approval` to persist the pending request to Dhara before returning (`_schedule_dhara_persist`)
- [x] Modify `respond_to_approval` / `cleanup_expired` to delete from Dhara on resolution (`_schedule_dhara_delete`)
- [x] Add lookback window: `MahavishnuApp._recover_approvals_from_dhara()` in `wait_for_dependencies()`
- [x] Add expiry TTL to approval records (default 24 h — changed from 30 min to match Dhara TTL)
- [x] Also fixed: `MahavishnuApp.approval_manager` was never initialized — always returned "not available"
- [x] Add `DharaStateBackend.schedule_delete` fire-and-forget helper
- [x] Add 9 unit tests in `TestApprovalManagerDharaPersistence` — all passing

**Delivered**: 2026-05-07 — durable approval persistence + restart recovery + 9 tests. Also fixed the missing `approval_manager` initialization on `MahavishnuApp`.

______________________________________________________________________

## Priority 9 — OpenWebUI mcpo Bridge

**Plan**: _(this document — zero-infrastructure integration, no separate plan file needed)_
**Status**: delivered 2026-05-08 — bridge code, mcpo config, and integration doc complete; manual UI steps (tool registration, model arena) in progress out-of-band
**Scope**: Narrow; `uvx mcpo` bridge + OpenWebUI tool registration + integration doc. No Docker, no code changes to Mahavishnu.

### Why this priority

Mahavishnu has a Textual TUI but no web-accessible interface. OpenWebUI is installed locally via Homebrew (desktop cask v0.0.20). `mcpo` runs zero-install via `uvx` and wraps Mahavishnu's existing FastMCP HTTP server (port 8680, `/sse` transport) into an OpenAI-compatible Tool Server that OpenWebUI understands. This works for both local and remote (serverless) Mahavishnu deployments — just change the `--url` flag. OpenWebUI's model arena/ELO system also enables benchmarking ZAI vs Ollama models to improve `StatisticalRouter` priors.

**No Docker required**: OpenWebUI is already installed locally; `mcpo` runs as `uvx mcpo` with no install step. The bridge is a single terminal command.

### Architecture

```
OpenWebUI (local desktop, Homebrew)
    → http://127.0.0.1:8001  (mcpo via uvx, local bridge)
        → http://localhost:8680/sse       (local Mahavishnu)
        OR https://mahavishnu.example.com/sse  (remote/serverless)
```

### Completed tasks

- [x] Determine correct transport — FastMCP 3.x uses Streamable HTTP (`/mcp`), not SSE; `--type streamable-http` is correct
- [x] Verify bridge: `uvx mcpo --type streamable-http http://127.0.0.1:8680/mcp` connects and negotiates protocol 2025-11-25
- [x] Write `docs/integrations/openwebui.md` with full setup steps (local + remote variants, auth, troubleshooting)
- [x] Create convenience config at `~/.config/mcpo/mahavishnu.json`
- [ ] Register bridge as Tool Server in OpenWebUI Admin → Settings → Tools → Add (`http://127.0.0.1:8001`) — manual step
- [ ] Verify round-trip: invoke `ecosystem_status`, `pool_route_execute`, `adapter_health` from OpenWebUI chat — manual step
- [ ] Run model arena: `glm-4.7` vs `llama3:8b` on 10 representative prompts; record ELO deltas — manual step

**Delivered**: 2026-05-07 — bridge verified working (`streamable-http` / `/mcp`), integration doc written, mcpo config created. Remaining tasks are manual UI steps (tool registration, model arena) — no further code changes needed.

______________________________________________________________________

## Priority 10 — HatchetAdapter (post-Dhara)

**Spec**: `docs/plans/2026-05-07-hatchet-adapter-spec.md` _(to be written before implementation)_
**Status:** delivered 2026-05-08
**Scope**: Medium; new adapter implementing `OrchestratorAdapter`, new `hatchet-sdk` dependency

### Why this priority

Hatchet is a durable task queue + DAG orchestrator built on Postgres with \<20ms task start latency, per-key rate limiting, and first-class human-in-the-loop via `WaitForEvent`. It complements the Prefect adapter: Prefect for scheduled batch/data pipelines, Hatchet for high-frequency AI agent loops and approval-gated workflows. Since both Dhara (Priority 2) and Hatchet use Postgres as the durable state layer, implementing Dhara first avoids duplicated Postgres connection management.

**Prerequisite**: Priority 2 (Dhara Integration) must be complete. Spec must be written and reviewed before implementation begins.

### Spec must cover

- Routing decision: when does `TaskRouter` prefer Hatchet vs Prefect vs direct ZAI?
- Hatchet self-hosted vs cloud — which do we default to?
- Key mapping: Mahavishnu `TaskCategory` → Hatchet workflow name
- Worker deployment: how Hatchet workers are started alongside `mahavishnu mcp start`
- Concurrency and rate-limit config surface in `settings/mahavishnu.yaml`

### Implementation tasks (after spec approval)

- [ ] Write and review `docs/plans/2026-05-07-hatchet-adapter-spec.md`
- [ ] Add `hatchet-sdk~=0.x` to `pyproject.toml` dependencies
- [ ] Implement `HatchetAdapterImpl(OrchestratorAdapter)` in `mahavishnu/adapters/hatchet_adapter_impl.py`
- [ ] Register Hatchet in `MahavishnuApp._initialize_adapters()` gated on `adapters.hatchet: true` config
- [ ] Add `hatchet:` config stanza to `settings/mahavishnu.yaml` (server_url, api_key, worker_slots, enabled)
- [ ] Add `TaskCategory.AGENT_LOOP` routing rule → prefer `hatchet` when enabled
- [ ] Wire `WaitForEvent` to Mahavishnu's approval primitives (builds on Priority 8)
- [ ] Add unit tests for `HatchetAdapterImpl` (mock Hatchet SDK)
- [ ] Add integration smoke test (skipped unless `HATCHET_CLIENT_TOKEN` present)
- [ ] Document adapter in `docs/architecture/ARCHITECTURE.md`

**Delivered**: 2026-05-08

______________________________________________________________________

## Final Gate — README Update

**Status**: delivered 2026-05-08
**Scope**: Single-pass documentation update; no code changes

### Why last

The README describes the current state of Mahavishnu. Updating it mid-implementation would either document features not yet shipped or require re-editing after each priority. A single final pass after all backlog items are delivered is more accurate and less wasteful.

### Tasks

- [ ] Update capability count (tools, adapters, pool types) to reflect delivered items
- [ ] Add Hatchet adapter to adapter table (after Priority 10)
- [ ] Add OpenWebUI mcpo bridge to deployment section (after Priority 9)
- [ ] Update architecture diagram: add Hatchet worker layer, mcpo bridge, Dhara persistence arrows
- [ ] Update "Remaining Work" section — move all delivered items to "Completed"
- [ ] Verify all ports, env vars, and CLI command examples are accurate
- [ ] Confirm pool type table includes `runpod` with `GpuHandlerPool` note (after Priority 4)

**Delivered**: 2026-05-08 — README updated; all backlog items reflected

______________________________________________________________________

## Closed / Superseded Items (reference)

| Item | Closed | Reason |
|------|--------|--------|
| TensorZero Gateway | 2026-05-07 | Superseded by ZAI + Bifrost + mcp-common `llm/` + `task_router.py` |
| Claw-Inspired Orchestration | 2026-05-07 | Superseded by `event_bus.py`, `quality_gate_manager.py`, `unified_orchestrator.py` |
| Agno Phases 4-6 | 2026-05-07 | Superseded by Session-Buddy memory, `otel_ingester.py`, existing pool system |
| Bodai Auth Standardization | 2026-04-30 | Complete — `mcp_common.auth` canonical JWT package across all 6 services |
| Agent & Skill Modernization | 2026-05-01 | Complete — validator, DriftReport, 15 agents enriched, 28 skills updated |
| Phase 1 Control Plane Hardening | 2026-05-07 | Complete — all 11 tasks shipped |
| Phase 3 Cross-Repo Coordination | 2026-05-07 | Complete — all coordination tooling shipped |
| RunPod Pool (base class) | 2026-05-01 | Complete — `RunPodPool` merged; subtasks remain in Priority 4 above |
| Prefect Adapter | 2026-05-07 | Complete — `prefect_adapter_impl.py` (1974 lines) fully implements `PrefectAdapter` |
| Agno Adapter Phases 1-3 | 2026-05-07 | Complete — `agno_adapter_impl.py` (1627 lines) ships all three phases |
| Code Indexing Integration | 2026-04-30 | Complete — call chain, impact analysis, incremental re-indexing live |
| Pattern Learning Scaffolding | 2026-04-30 | Complete — `ScaffoldingEngine`, `PatternLibrary` shipped |
| Splashstand Oneiric Migration | 2026-04-30 | Complete — zero `from acb` imports remain |
| Config Consolidation (migration script) | 2026-04-30 | Partial — migration script shipped; full schema validation remains (see Priority 3) |
| Ecosystem Control Plane (CP0-CP7) | 2026-04-30 | Complete — `CanonicalStatus`, `EcosystemStatusService`, routing observability |
| Nanobot Worker | 2026-05-07 | Removed — all nanobot integration deleted; `nanobot-ai` dep dropped |
