# Worktree Manage Consolidation Plan

**Date:** 2026-05-11
**Status:** `complete`, `historical`
**Owner:** Core Eng
**Purpose:** Consolidate the deprecated `worktree_tools.py` MCP surface into a single `worktree_manage` tool with subcommands, preserving behavior while reducing duplicated tool entry points.

## 1. Outcome

The current worktree MCP surface exposes six thin wrappers around `WorktreeCoordinator`. That is easy to call, but it expands the MCP surface and keeps six separate tool registrations alive for one domain.

This plan replaces that fan-out with a single consolidated tool:

1. `worktree_manage(action=...)`
1. keep existing behavior available during the transition
1. add error handling around coordinator delegation
1. migrate registration and tests to the consolidated tool before removing the old entry points

## 2. Relationship To Existing Plans

| Area | Existing plan/spec | Current status | This plan's role |
|---|---|---:|---|
| MCP tool retirement | `2026-04-05-low-value-tool-retirement.md` and `docs/reports/deprecation-migration.md` | active / historical mix | Use as retirement context; this plan owns the concrete consolidation work |
| Convergence umbrella | `2026-05-10-bodai-control-plane-convergence-plan.md` | active, umbrella | Track the docs/retirement slice and any cross-cutting reductions that depend on worktree consolidation |
| Worktree coordination | `worktree_tools.py` and `WorktreeCoordinator` runtime behavior | live, deprecated surface | Replace six tool entry points with one consolidated dispatcher |

## 3. Non-Goals

1. Do not delete `WorktreeCoordinator`.
1. Do not change the underlying worktree safety semantics without a separate review.
1. Do not remove the worktree MCP surface until the consolidated replacement is implemented, registered, and tested.
1. Do not add new worktree subcommands beyond the existing behaviors during this consolidation.

## 4. Program Tracker

| Phase | Name | Status | Blocking dependency | Primary deliverable |
|---|---|---:|---|---|
| W0 | Audit and replacement contract | `completed` | none | consolidated action schema, current call-site audit, migration map |
| W1 | Consolidated tool implementation | `completed` | W0 complete | `worktree_manage` tool with subcommand dispatch and error handling |
| W2 | Registration and tests | `completed` | W1 complete | MCP registration, regression tests, updated fixtures |
| W3 | Retirement and deletion | `completed` | W2 complete | remove individual worktree tool entry points and update docs |

## 5. Phase W0: Audit And Replacement Contract

**Goal:** Define the `worktree_manage` action contract and confirm the existing live call sites that need to move.

Tasks:

- [x] Audit current `worktree_tools.py` call sites in code, tests, and docs.
- [x] Define a single `worktree_manage` action enum or string contract covering create, remove, list, prune, safety_status, and provider_health.
- [x] Identify any context that needs to be preserved during the migration, especially user_id, repo_nickname, and worktree_path handling.
- [x] Add a migration note to the deprecation guide and convergence log.

Acceptance criteria:

- A single replacement contract exists for the six worktree actions.
- Live usage is inventoried with exact call sites and documentation references.
- The new contract is suitable for MCP registration without breaking current coordinator behavior.

Validation:

- `rg -n "worktree_tools|create_ecosystem_worktree|remove_ecosystem_worktree|list_ecosystem_worktrees|prune_ecosystem_worktrees|get_worktree_safety_status|get_worktree_provider_health" /Users/les/Projects/mahavishnu`
- `git diff --check`

## 6. Phase W1: Consolidated Tool Implementation

**Goal:** Add `worktree_manage` while preserving existing behavior.

Tasks:

- [x] Implement `worktree_manage(action=...)` in `mahavishnu/mcp/tools/worktree_tools.py` or a successor module.
- [x] Route each action through `WorktreeCoordinator`.
- [x] Add explicit error handling and structured failure payloads.
- [x] Keep existing tools callable as wrappers during the transition if needed.

Acceptance criteria:

- `worktree_manage` can perform all current worktree actions.
- The consolidated tool returns the same outcomes as the current individual tools.
- Errors are structured and do not leak raw coordinator exceptions.

Validation:

- Targeted unit tests for each action.
- `uv run ruff check` on the new/updated module and tests.

## 7. Phase W2: Registration And Tests

**Goal:** Make the consolidated tool the preferred registration path and keep tests green.

Tasks:

- [x] Register `worktree_manage` in MCP server wiring.
- [x] Update tests to cover the consolidated dispatch path.
- [x] Keep compatibility tests for old tool names until retirement.

Acceptance criteria:

- MCP registration exposes the consolidated tool.
- Tests cover create/remove/list/prune/safety/provider-health dispatch.

Validation:

- `uv run pytest --no-cov tests/unit/test_worktree_tools.py tests/integration/test_worktree_mcp_tools.py`
- `uv run ruff check` on touched MCP server/tool/test files

## 8. Phase W3: Retirement And Deletion

**Goal:** Remove the individual worktree tools once the consolidated replacement is adopted.

Tasks:

- [x] Remove individual worktree MCP tool entry points.
- [x] Update docs and deprecation notes to point at `worktree_manage`.
- [x] Update tool version/deprecation registries if they reference the old actions.

Acceptance criteria:

- The old worktree tool names no longer need to be registered.
- Documentation reflects the new consolidated interface.
- Any remaining references are archival only.

Validation:

- Search for the old tool names across active code and docs.
- Run the worktree tool test suite and MCP registration tests.

## 9. Progress Log

- 2026-05-11: Plan created as a separate consolidation track for the deprecated worktree MCP surface.
- 2026-05-11: W0 audit backed by `docs/reports/worktree-manage-audit.md`; replacement contract and field-preservation rules defined.
- 2026-05-11: W1 landed `worktree_manage(...)` plus compatibility wrappers and MCP registration.
- 2026-05-11: Docs and deprecation notes now point at `worktree_manage` as the preferred MCP entry point, closing the registration/test slice and opening W3 for wrapper retirement.
- 2026-05-11: W2 completed; W3 opened for wrapper retirement and any final registry cleanup.
- 2026-05-11: W3 completed; the worktree MCP surface now exposes only `worktree_manage`, and the retired wrapper names have been removed from active code, tests, docs, and registries.
