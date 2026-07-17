---
status: complete
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: convergence-control-plane
---

# Remaining Work Execution Order

**Date:** 2026-05-11
**Status:** `completed`  <!-- legacy status: completed — see YAML frontmatter -->
**Owner:** Core Eng
**Purpose:** Ordered queue for the remaining implementation and cleanup work after plan reconciliation. This tracker only includes tasks that are still genuinely open.

## Ordering Rules

1. Finish the remaining shared-contract work in C6a before starting any new deletion batch.
1. Run C6b deletions in dependency order: smallest, safest removals first, then broader refactors, then cross-repo cleanup.
1. Finish C7 documentation and retirement cleanup after the code reductions land so docs match reality.
1. Keep terminal unification separate from the convergence deletion batches; finish the remaining terminal protocol work after the convergence blockers are cleared.
1. External repo plans that are not present in this workspace are listed only as notes, not as tracked implementation items.

## Current Execution Queue

| Order | Track | Task | Source plan | Status | Dependency / note |
|---|---|---|---|---|---|
| 1 | T1 | Terminal worker shared protocol extraction | [terminal-unification](./2026-05-10-terminal-worker-unification-plan.md) | completed | `TerminalWorkerProtocol` (typing.Protocol, @runtime_checkable) created in `workers/protocol.py` and exported from `workers/__init__.py`. |
| 2 | T4 | Terminal legacy branch retirement | [terminal-unification](./2026-05-10-terminal-worker-unification-plan.md) | completed | `TerminalAIWorker` collapsed to a 65-line shim over `GenericShellWorker`; private impl methods removed; tests updated; 104 tests pass, lint clean. |

## Already Resolved

- `Crackerjack validation result schemas and quality-gate report contracts` are published, wired into the Crackerjack websocket quality-gate surface, and bridged into Mahavishnu's fix-orchestrator consumer.
- C7 documentation and retirement cleanup is complete; the remaining references are in historical plans and archive docs, not active operator guidance.
- The monitoring dashboard MCP tool is now a compatibility wrapper over `ecosystem_status`; the canonical status payload is the single source of truth.
- The learning/team-learning surface is currently an audit-backed compatibility hold: wrappers remain in place, and the canonical review-gated learning pipeline is the source of truth until parity exists.
- `core/app.py` has started shedding control-surface helpers into `core/control_surface.py` so the composition root can stay focused on wiring.
- `core/app.py` has also started shedding bootstrap helpers into `core/bootstrap.py` for Dhara resolution, pool setup, memory aggregation, and learning-pipeline setup.
- `core/app.py` now delegates config and repo loading to `core/bootstrap.py` as well, keeping the constructor-path focused on orchestration wiring.
- `core/app.py` now delegates adapter initialization and application context setup to `core/bootstrap.py`, so the remaining file is mostly lifecycle and behavior plumbing.
- `core/app.py` now delegates terminal-manager initialization to `core/bootstrap.py` as well, keeping the app bootstrap path thin and explicit.
- `core/app.py` now delegates observability and health endpoint initialization to `core/bootstrap.py` too, removing more direct service construction from the app constructor.
- `core/app.py` now delegates the remaining runtime-service construction to `core/bootstrap.py`, leaving the composition root focused on top-level wiring and lifecycle.
- `core/app.py` no longer carries a dedicated Session-Buddy poller initializer; that setup now lives in `core/bootstrap.py` with the other runtime-service wiring.
- `core/app.py` now delegates repo, role, permission, health, workflow-gauge, and workflow persistence helpers to `core/repository_surface.py`, trimming more non-composition concerns out of the application root.
- `core/app.py` now delegates workflow initialization, QC gating, session checkpointing, parallel repo processing, workflow finalization, and workflow error handling to focused helper methods, continuing the composition-root split.
- `core/app.py` now delegates poller, learning-pipeline, and worktree-coordinator lifecycle helpers to `core/lifecycle.py`, keeping the composition-root split moving without changing the public API.
- `core/app.py` now delegates dependency waiting and Dhara recovery gating to `core/dependency_waiter.py`, keeping the startup gate readable without changing the public API.
- `mcp/server_core.py` now delegates MCP server start/stop and worktree-tool registration to `mcp/lifecycle.py`, leaving the server class focused on composition and registration wiring.
- Session-Buddy storage ownership has taken another step toward the canonical Oneiric module: the remaining storage adapter test and doc examples now import direct module paths instead of the package re-export surface.
- Akosha standard-mode wording now describes cold storage as optional, keeping the mode docs aligned with the actual fallback behavior.
- Dhara migration/compatibility docs now distinguish the canonical `dhara.storage.file.FileStorage` path from the legacy `dhara.file_storage2` file-format helper.
- `mcp/server_core.py` now delegates terminal-manager initialization to `mcp/bootstrap.py`, trimming server startup wiring without changing registration behavior.
- `mcp/server_core.py` now delegates HTTP health-route registration to `mcp/bootstrap.py`, keeping the server constructor focused on composition rather than route plumbing.
- `mcp/server_core.py` no longer keeps a redundant health-route wrapper; the constructor calls the shared bootstrap helper directly.
- `mcp/server_core.py` now delegates the profile-gated tool-registration orchestration to `mcp/bootstrap.py`, leaving `start()` responsible for startup sequencing instead of registration policy.
- The remaining `_register_*` wrapper methods in `mcp/server_core.py` are now compatibility-only stubs or removed, and the registration policy lives in `mcp/bootstrap.py`.
- The legacy `EventBus` path is retired; the remaining `MessageBus` and `EventStore` surfaces are canonical and stay in use.
- `WorkflowState` is no longer the live workflow authority; `TaskRouter.StateManager` now owns the live workflow coordination surface and the deprecated module remains only for compatibility tests.
- The monitoring dashboard MCP tool now acts as a compatibility wrapper over `ecosystem_status`; the canonical status payload is the single source of truth.
- `Nanobot Worker Integration` is historical and no longer part of the active execution queue.
- `MiniMax 2.7 Provider Migration` is complete/historical.
- `Worktree Manage Consolidation` is complete/historical.
- `Bodai Unified Event Bus` is complete/historical.
- The live cockpit slice from `Bodai Agent Platform and Agno/Textual TUI` is already implemented through convergence phases C3a/C3b.

## External Active Plan

- `Config Consolidation` remains active in the external `superpowers` repo.
- It is not tracked further in this workspace because the plan file is outside the local repo tree.
- If you want that work sequenced here, the next step is to mirror its current state into a local tracking note or update it directly in the `superpowers` workspace.

## Resolved

- C7 documentation and retirement cleanup is complete; the remaining historical references are preserved only in archived plans and design notes.
- C6b complexity reduction and deletion pass is complete. Remaining Session-Buddy, Akosha, and Dhara surfaces are now classified as compatibility holds or non-targeted canonical paths rather than open deletion targets.

## Progress Log

Use this log for changes that materially affect the execution order or task status.

| Date | Change | Validation |
|---|---|---|
| 2026-05-11 | Initial priority-ordered execution queue created from the reconciled active plans | `git diff --check` |
| 2026-05-12 | C7 | Reworded `docs/ECOSYSTEM.md` so `ecosystem.yaml` is the canonical repository manifest, `repos.yaml` is legacy compatibility only, and Session-Buddy code-intel helpers are explicitly shims | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Updated the LLM inventory, gateway resume prompt, and Bifrost reactivation runbook so Nanobot is documented as retired historical state rather than an active client | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Marked the migration-note task complete after aligning the live docs and runbook with canonical vs compatibility surfaces for repos, session tooling, and retired Nanobot references | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Closed the documentation and retirement cleanup phase; only terminal unification remains in the active queue | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C6b | Closed the remaining-work C6b queue by reclassifying the Session-Buddy, Akosha, and Dhara storage/monitoring items as resolved or compatibility-held and leaving C7/T1/T4 as the only open work | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-11 | C6a | Started the Crackerjack validation-result and quality-gate report contract implementation, plus the Mahavishnu consumer bridge for the new report shape | `git diff --check` |
| 2026-05-11 | C6a | Published the Crackerjack validation-result and quality-gate report contract module, and validated the Mahavishnu consumer bridge with contract-shaped payloads | `uv run pytest --no-cov tests/unit/test_validation_contracts.py`, `uv run pytest --no-cov tests/unit/test_fix_orchestrator.py`, `uv run ruff check crackerjack/models/validation_contracts.py crackerjack/models/__init__.py tests/unit/test_validation_contracts.py mahavishnu/core/fix_orchestrator.py tests/unit/test_fix_orchestrator.py`, `git diff --check` |
| 2026-05-11 | C6a | Closed the Crackerjack validation-result and quality-gate report contract work by wiring the Crackerjack websocket quality-gate surface to the new report shape and validating the updated producer/test surface | `uv run pytest --no-cov tests/unit/test_validation_contracts.py tests/unit/test_websocket_server.py`, `uv run ruff check crackerjack/websocket/server.py crackerjack/models/validation_contracts.py crackerjack/models/__init__.py tests/unit/test_validation_contracts.py tests/unit/test_websocket_server.py`, `git diff --check` |
| 2026-05-11 | C6b | Collapsed the monitoring dashboard MCP tool into a compatibility wrapper over `ecosystem_status`, and marked the tool-version registry as deprecated in favor of the canonical status payload | `uv run pytest --no-cov tests/integration/test_mcp_tools.py tests/integration/test_ecosystem_contracts.py tests/unit/test_utility_modules.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/tool_versions.py tests/integration/test_mcp_tools.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Verified that no live Mahavishnu code or tests reference the retired `EventBus` path; remaining `MessageBus` and `EventStore` hits are canonical uses, so the legacy event/store/message-bus cleanup row moved to resolved | `rg -n "core/event_bus|EventBus\\(" /Users/les/Projects/mahavishnu/mahavishnu /Users/les/Projects/mahavishnu/tests -g '!**/__pycache__/**'`, `rg -n "event_store|message_bus" /Users/les/Projects/mahavishnu/mahavishnu/core /Users/les/Projects/mahavishnu/mahavishnu/mcp /Users/les/Projects/mahavishnu/tests/unit /Users/les/Projects/mahavishnu/tests/integration -g '!**/__pycache__/**'`, `git diff --check` |
| 2026-05-11 | C6b | Switched the live workflow authority from the deprecated `WorkflowState` module to `TaskRouter.StateManager`, kept the deprecated module only for compatibility tests, and validated the workflow-state state-manager CRUD path | `uv run pytest --no-cov tests/unit/test_task_router_core.py tests/unit/test_workflow_state.py tests/unit/test_task_router_and_auth.py -k 'WorkflowState or workflow_state or adapter_manager_and_state_manager_basics'`, `uv run ruff check mahavishnu/core/task_router.py tests/unit/test_task_router_core.py mahavishnu/core/app.py`, `git diff --check` |
| 2026-05-12 | C6b | Removed deprecated Crackerjack CLI alias options (`show_progress`, `advanced_monitor`, `coverage_report`, `clean_releases`) and rewired the canonical `track_progress` / `cleanup_pypi` flags | `uv run pytest --no-cov tests/unit/cli/test_cli_options.py tests/test_cli_entry_point.py tests/unit/cli/test_facade.py`, `git diff --check` |
| 2026-05-13 | T1 | Created `TerminalWorkerProtocol` in `workers/protocol.py` (typing.Protocol, @runtime_checkable); exported from `workers/__init__.py` | `uv run ruff check mahavishnu/workers/protocol.py mahavishnu/workers/__init__.py` |
| 2026-05-13 | T4 | Collapsed `TerminalAIWorker` to 65-line shim over `GenericShellWorker`; added `worker_name` to GenericShellWorker metadata; removed retired private-method tests; 104 tests pass, lint clean | `uv run pytest --no-cov tests/unit/test_terminal_worker.py tests/unit/test_workers.py -q`, `uv run ruff check mahavishnu tests` |
