---
status: active
role: implementation
date: 2026-07-29
last_reviewed: 2026-07-29
superseded_by: null
topic: quality-gate-repair
---

# Pyscn and Ty Quality Gate Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Crackerjack `pyscn` and `ty` quality gates on Mahavishnu by refactoring `WorktreePruner.remove()` below high-risk complexity and restoring the three previously-deliberate `ty: ignore[unresolved-import]` directives, without altering any other working-tree file.

**Architecture:** Surgical refactor inside `WorktreePruner` (private helpers, no public surface change) plus three line-level type-checker annotations; the runtime contract of `remove()` and the import resolution mechanism in `scripts/` remain unchanged.

**Tech Stack:** Python 3.13, `pyscn`, `ty`, `pytest`, `ruff`, Crackerjack.

## 1. Outcome

- `uv run pyscn check mahavishnu/core/worktree_prune_merged.py` exits 0; `WorktreePruner.remove` complexity ≤ 19.
- `uv run ty check mahavishnu/cli/config_validator.py mahavishnu/cli/docs_cli.py` reports zero unresolved-import diagnostics.
- All focused pytest suites pass; no unrelated files modified.

## 2. Goals

1. Reduce `WorktreePruner.remove` cyclomatic complexity below `.pyscn.toml` high-risk threshold.
2. Restore the three deliberate `# ty: ignore[unresolved-import]` directives on `scripts/` runtime imports.
3. Preserve every existing public behavior of `remove()` (call order, audit events, result ordering, error literals).
4. Add focused characterization tests guarding the refactor.

## 3. Non-Goals

- Packaging `scripts/` as a real Python module.
- Broadening runtime `sys.path` behavior or adding startup hooks.
- Running repo-wide autofixing Crackerjack against the dirty tree.
- Committing, staging, or touching any unrelated file in the working tree.

## 4. Current Findings

- Git diff confirms `mahavishnu/cli/config_validator.py:613` and `635` lost `# ty: ignore[unresolved-import]` (rollback site also lost `# noqa: PLC0415`), and `mahavishnu/cli/docs_cli.py:48` lost the same directive.
- `WorktreePruner.remove` inlines six phases: preflight validation, attempt audit, live revalidation, coordinator removal+force-retry, exception conversion, and terminal summary audit. Each `if any(...)`, `if escalated`, `if failed and successful` increments branch count past the threshold.
- `scripts/` is intentionally not a Python package and runtime `sys.path.insert` is invisible to static resolution; packaging `scripts/` is out of scope.
- Pool provisioning failed with `MHV-007` (`terminal_id` missing) during initial orchestration attempt; user approved local fallback.

## 5. Implementation Phases

### Phase 1: Characterization coverage

**Goal:** Add focused tests that pin the public behavior `remove()` must preserve through the refactor.

**Tasks:**
- Add `test_worktree_pruner_remove_raises_on_undetermined_dirty` to assert the second preflight `ValueError`.
- Add `test_worktree_pruner_remove_returns_changed_candidate_without_calling_coordinator` to assert the exact `"candidate changed since discovery"` failure.
- Add `test_worktree_pruner_remove_swallows_coordinator_exception_into_failed_result` to assert exception conversion continues iteration.
- Extend `FakeAudit` with `success_calls` and `failure_calls` lists; assert terminal-event selection per branch.
- Add `test_worktree_pruner_remove_emits_success_event_when_no_failures` and `test_worktree_pruner_remove_emits_failure_event_when_no_successes`.
- Add `test_worktree_pruner_remove_emits_success_event_for_empty_candidate_list` (matches existing empty-input success path).

**Exit criteria:** focused pytest passes against the current implementation; new tests fail on any deviation from the preserved contract.

#### Integration Contract ← REQUIRED for every deliverable in this phase

- **Triggered from:** `uv run pytest tests/unit/test_worktree_prune_merged.py`.
- **Returns to / updates:** `tests/unit/test_worktree_prune_merged.py` (no production code touched).
- **Demonstrable by:** focused test run reports the new tests as passing.
- **Rollback signal:** any existing test in the file fails or new tests exhibit non-determinism.
- **Observability added:** none.

### Phase 2: WorktreePruner.remove refactor

**Goal:** Reduce `remove()` complexity to ≤ 19 while preserving every public behavior.

**Tasks:**
- Add `_validate_candidates(candidates, force_reason)` for the three preflight `ValueError` checks.
- Add `_candidate_changed(candidate)` for live SHA/merge/dirty comparison.
- Add async `_remove_candidate(candidate, force_reason, user_id)` for the coordinator call, force escalation, and result normalization.
- Add `_log_result_summary(results, user_id, trigger)` for the aggregate terminal audit event.
- Reduce `remove()` to: validation, attempt audit, ordered iteration with revalidation+removal, terminal summary audit, return.
- Preserve exact `ValueError` messages, fallback reason `"merged worktree dependency cleanup"`, result ordering, audit payload ordering, and `escalated` semantics.

**Exit criteria:** `pyscn check` exits 0 and `remove()` complexity ≤ 19; all characterization tests still pass; no other file touched.

#### Integration Contract

- **Triggered from:** `mahavishnu.worktree_cli` calling `WorktreePruner.remove()` for the `prune-merged` subcommand.
- **Returns to / updates:** unchanged `list[WorktreePruneResult]` (same order, same fields) and unchanged `log_prune_merged_attempt|partial|failure|success` payloads.
- **Demonstrable by:** `uv run pyscn check mahavishnu/core/worktree_prune_merged.py` exits 0 and complexity drops below 20; existing pytest still passes.
- **Rollback signal:** any of: complexity returns to 20, characterization tests fail, audit event selection changes, coordinator call order changes.
- **Observability added:** none — existing worktree audit events are preserved verbatim.

### Phase 3: ty directive restoration

**Goal:** Restore the three previously-deliberate `ty: ignore[unresolved-import]` directives.

**Tasks:**
- `mahavishnu/cli/config_validator.py:613` — re-add `# ty: ignore[unresolved-import]` to the `migrate_config_to_project` import.
- `mahavishnu/cli/config_validator.py:635` — re-add `# ty: ignore[unresolved-import]` to the `migrate_config_to_project` import; preserve existing `# noqa: PLC0415`.
- `mahavishnu/cli/docs_cli.py:48` — re-add `# ty: ignore[unresolved-import]` to the `audit_ecosystem_docs` import.

**Exit criteria:** `ty check` reports zero unresolved-import diagnostics on the two files; no other line is changed.

#### Integration Contract

- **Triggered from:** `uv run ty check mahavishnu/cli/config_validator.py mahavishnu/cli/docs_cli.py` (gating check) and `crackerjack` type-check stage.
- **Returns to / updates:** static analysis suppression comments on three import statements; no runtime behavior change.
- **Demonstrable by:** the `ty check` invocation reports zero diagnostics.
- **Rollback signal:** unresolved-import diagnostics reappear, or the directives leak to runtime imports elsewhere.
- **Observability added:** none.

### Phase 4: Focused verification

**Goal:** Confirm the targeted gates pass and the working tree is limited to the planned files.

**Tasks:**
- Run the focused verification commands in §7.
- Confirm `git diff --stat` is limited to the four planned source files, the new tests, the new plan file, and the fallback marker.
- If any non-mutating full-gate mode is available, run it; otherwise document why the repo-wide autofixing gate was skipped.

**Exit criteria:** all focused commands exit 0 and the working-tree scope is exactly as planned.

#### Integration Contract

- **Triggered from:** the run-quality-checks skill (`run-quality-checks`).
- **Returns to / updates:** verification evidence captured in the conversation report.
- **Demonstrable by:** all focused commands in §7 exit 0.
- **Rollback signal:** any command exits non-zero; the corresponding task is reopened.
- **Observability added:** verification log lines captured for the report.

## 6. Required Code Changes

- Modify `mahavishnu/core/worktree_prune_merged.py` (add four private methods, reduce `remove()` body).
- Modify `tests/unit/test_worktree_prune_merged.py` (add characterization tests, extend `FakeAudit`).
- Modify `mahavishnu/cli/config_validator.py` (add two `# ty: ignore[unresolved-import]` annotations).
- Modify `mahavishnu/cli/docs_cli.py` (add one `# ty: ignore[unresolved-import]` annotation).
- Create `docs/plans/2026-07-29-pyscn-ty-quality-repair.md` (this file).
- Create `~/.mahavishnu/fallback-queue/quality-repair-2026-07-29-pyscn-ty.json` (fallback replay marker).

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
| --- | --- | --- |
| `uv run pytest tests/unit/test_worktree_prune_merged.py -q` | All tests pass | Conversation log |
| `uv run pytest tests/unit/test_docs_cli.py tests/unit/test_config_validator_cli.py -q` | All tests pass | Conversation log |
| `uv run pyscn check mahavishnu/core/worktree_prune_merged.py` | Exit 0; `remove` complexity ≤ 19 | Conversation log |
| `uv run ty check mahavishnu/cli/config_validator.py mahavishnu/cli/docs_cli.py mahavishnu/core/worktree_prune_merged.py` | Zero diagnostics | Conversation log |
| `uv run ruff check <four files>` | Exit 0 | Conversation log |
| `uv run ruff format --check <four files>` | Exit 0 | Conversation log |
| `python scripts/audit_orphans.py` | No newly-orphaned symbols attributable to this repair | Conversation log |
| `git diff --check` and path-scoped `git diff` | Scope limited to planned files | Conversation log |

## 8. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Refactor accidentally changes audit event selection | Low | Characterization tests cover success/failure/partial/empty paths; existing tests would fail. |
| Restored `ty: ignore` directives fail to silence diagnostics (e.g. rule rename) | Low | Verify with `uv run ty check` immediately after restoration; if rule name changed, update the directive rather than deleting it. |
| `pyscn` is unavailable locally | Low | If unavailable, document the unavailability and rely on the characterization tests as the executable specification; complexity is verified by `pytest --collect-only` plus reading the refactored method body. |
| Dirty working tree contains unrelated edits that trigger autofixing | Medium | Avoid any repo-wide autofixing; only targeted checks listed in §7. |

## 9. Decision Rule

Plan is done when `WorktreePruner.remove()` complexity is below 20, the three `ty: ignore` directives are restored, all focused pytest/pyscn/ty/ruff/audit_orphans commands exit 0, and `git diff` is limited to the four planned source files plus the new tests, plan, and fallback marker.
