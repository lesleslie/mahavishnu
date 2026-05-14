# Bodai Deletion And Adoption Ledger

**Date:** 2026-05-11
**Status:** `draft`, `ledger`
**Owner:** Core Eng
**Purpose:** Track the first cross-repo deletion/adoption candidates that should only be removed after a canonical replacement, import audit, parity tests, and a Crackerjack validation artifact exist.

This is the seed ledger for C6a. Rows are intentionally explicit about audit inputs and disposition criteria so later deletion batches can be executed without re-deriving ownership.

## Entry Format

Each row should capture:

- owner repo
- candidate file/module
- canonical replacement
- preserved public API/CLI/MCP surfaces
- docs/config references
- exact import/call-site audit command
- hit disposition
- risk level
- migration/deprecation decision
- parity tests
- Crackerjack quality-gate artifact
- rollback plan
- release note requirement
- validation command
- removal target date

## Seed Ledger

| Owner repo | Candidate file/module | Canonical replacement | Preserved public API/CLI/MCP surfaces | Docs/config refs | Exact import/call-site audit command | Hit disposition | Risk | Migration/deprecation decision | Parity tests | Crackerjack quality-gate artifact | Rollback plan | Release note requirement | Validation command | Removal target date | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `mahavishnu` | `cli/team_cli.py`, `mcp/tools/team_learning_tools.py`, `mcp/tools/goal_team_tools.py` | `core/skill_governance.py`, `core/learning_pipeline.py`, `core/skill_registry.py` | `mahavishnu team skills`, team-learning MCP query surfaces, review-gated skill lifecycle | `docs/policies/worker-classification-policy.md`, `docs/TERMINAL_MANAGEMENT.md`, `docs/src/index.md` | `rg -n "team_learning|list_team_skills|goal_team|learning_pipeline" /Users/les/Projects/mahavishnu` | `compatibility wrapper`, `migrated`, `historical docs` | medium | Defer deletion until review-gated skill lifecycle parity tests and canonical skill registry coverage are complete. | `tests/unit/test_skill_governance.py`, `tests/unit/test_learning_pipeline.py`, `tests/unit/test_team_learning_tools.py` | `docs/reports/c6a-mahavishnu-adoption-audit.md` | Keep current wrappers and feature flags until parity passes. | yes | `uv run pytest --no-cov tests/unit/test_skill_governance.py tests/unit/test_learning_pipeline.py tests/unit/test_team_learning_tools.py` | TBD | audit-backed |
| `mahavishnu` | `core/app.py`, `mcp/server_core.py`, `core/config.py` | Smaller service wiring modules and adapter factories | CLI/MCP startup entry points, app bootstrap, config loading | `docs/architecture/ARCHITECTURE.md`, `docs/src/configuration.md` | `rg -n "pool_manager|coordination_manager|approval_manager|skill_registry|session_buddy" /Users/les/Projects/mahavishnu` | `refactor`, `migrated`, `blocker` if a call site still owns domain logic | high | Refactor before any deletion; do not remove entry points until wiring is extracted and contract tests pass. | `tests/unit/test_config.py`, `tests/unit/test_app_recovery.py`, `tests/unit/test_fix_orchestrator.py` | `docs/reports/c6a-mahavishnu-adoption-audit.md` | Preserve current entry points and route through extracted wiring modules first. | yes | `uv run pytest --no-cov tests/unit/test_config.py tests/unit/test_app_recovery.py tests/unit/test_fix_orchestrator.py` | TBD | audit-backed |
| `crackerjack` | CLI alias/options layer and old service roots under `services/*` (exact modules pending audit) | Canonical validation pipeline and shared provider registry | Existing CLI commands, provider selection, quality-gate outputs | `docs/API_KEY_SETUP.md`, `settings/minimax.example.yaml` | `rg -n "provider|alias|services|quality gate|validation" /Users/les/Projects/crackerjack` | `compatibility wrapper`, `migrated`, `historical docs` | medium | Defer deletion until provider/report parity tests and result-schema adoption are complete. | `tests/adapters/test_provider_chain.py`, repo-local service contract tests | pending | Keep alias layer until canonical validation contracts are adopted. | yes | `uv run pytest --no-cov tests/adapters/test_provider_chain.py` | TBD | seed |
| `session-buddy` | Health/MCP monitoring helpers and realtime fan-out modules (exact modules pending audit) | EventBridge subscriptions plus shared MCP primitives | Session-local context persistence and checkpoint history | `docs/API_KEY_SETUP.md`, `settings/session-buddy.yaml` | `rg -n "health|mcp|websocket|event|fan[- ]?out" /Users/les/Projects/session-buddy` | `compatibility wrapper`, `migrated`, `blocker` if live fan-out still depends on local code | medium | Preserve session persistence; delete only adapters that duplicate canonical operational-checkpoint behavior. | session/recovery contract tests, MCP registration tests | pending | Keep current adapters until EventBridge subscription parity is proven. | yes | `uv run pytest --no-cov` | TBD | seed |
| `mcp-common` | Local service copies of settings/auth/health/telemetry/WebSocket primitives (exact modules pending audit) | Shared MCP server/session primitives and WebSocket protocol/server helpers | Existing MCP entry points and shared service settings | repo-local docs in consumer repos | `rg -n "auth|health|telemetry|websocket|settings" /Users/les/Projects/mcp-common` | `compatibility wrapper`, `migrated`, `blocker` if adoption is incomplete | high | Do not delete local copies until shared primitives are adopted by all active consumers. | shared-contract tests for auth, health, telemetry, and WebSocket behavior | pending | Keep local copies and import wrappers until adoption is complete. | yes | `uv run pytest --no-cov` | TBD | seed |
| `akosha` | Primary-storage assumptions and duplicate platform primitives (exact modules pending audit) | Derived intelligence and semantic search only | Search/index APIs and derived-memory writes | repo-local docs and consumer references | `rg -n "storage|primary|health|websocket|auth" /Users/les/Projects/akosha` | `migrated`, `compatibility wrapper`, `blocker` if primary-storage assumptions remain | medium | Defer deletion until all writes carry source correlation IDs and shared adoption is complete. | search/index contract tests and correlation-ID assertions | pending | Keep current storage assumptions until correlation-aware writes are live everywhere. | yes | `uv run pytest --no-cov` | TBD | seed |
| `dhara` | `file_storage`, `file_storage2`, `storage_server`, backup storage, MCP storage APIs | One operational state contract and one object/blob contract | Durable-state APIs and recovery checkpoints | `docs/plans/2026-05-07-dhara-state-backend-addendum.md` | `rg -n "file_storage|file_storage2|storage_server|backup|mcp storage" /Users/les/Projects/dhara` | `compatibility wrapper`, `migrated`, `blocker` if overlapping storage paths remain | high | Audit and consolidate before any deletion batch. | durable-state recovery and storage contract tests | pending | Keep adapter shims until a single operational-state contract is proven. | yes | `uv run pytest --no-cov` | TBD | seed |
| `mdinject` | Direct event/session/memory/orchestration/storage dependencies (exact modules pending audit) | Bodai MCP APIs | Client-side app flows only | repo-local docs and integration notes | `rg -n "event|session|memory|orchestration|storage" /Users/les/Projects/mdinject` | `migrated` or `historical docs` | low | Likely no deletion; confirm with audit and leave as no-op unless a direct dependency is found. | audit-only regression checks | pending | No rollback expected unless audit reveals a direct dependency. | no | `uv run pytest --no-cov` | TBD | seed |
