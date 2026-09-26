---
status: draft
role: implementation
date: 2026-09-26
last_reviewed: 2026-09-26
topic: pyscn-complexity-reduction
revision: v1
plan_status: ready-for-execution
---

# Plan B: pyscn Cyclomatic Complexity Reduction

> **Origin**: surfaced by comprehensive-hook failure 2026-09-26 — `pyscn` flagged 2 functions over threshold:
> - `mahavishnu/mcp/tools/clone_tools.py:245` — `CloneTools.clone_refactor_group` cyclomatic complexity 30 (gate threshold ~15).
> - `mahavishnu/pools/session_buddy_pool.py:281` — `SessionBuddyPool.execute_batch` cyclomatic complexity 19.

## Headline finding

Two functions in two unrelated subsystems (the clone-refactor MCP tool surface, and the Session-Buddy pool's batch executor) each grew past the project's complexity gate. The causes are likely different, so the refactors are split into **two independent tasks**:

- **Task 1**: Reduce `clone_tools.py:clone_refactor_group` complexity from 30 → ≤15.
- **Task 2**: Reduce `session_buddy_pool.py:execute_batch` complexity from 19 → ≤15.

## 1. Outcome

After this plan ships:

- `pyscn mahavishnu/mcp/tools/clone_tools.py mahavishnu/pools/session_buddy_pool.py` reports no functions above the gate threshold.
- Each refactored function has a focused single responsibility, expressed via extracted helpers.
- All existing tests pass; coverage does not regress.
- No behavior change (refactors only).

**Proof it worked**:

- `pyscn mahavishnu/mcp/tools/clone_tools.py mahavishnu/pools/session_buddy_pool.py` — no findings.
- `pytest tests/unit/test_clone_refactor_workflow.py tests/unit/test_mcp_pool_tools.py tests/unit/test_session_buddy_pool.py -v` — all green.
- `git diff --stat` — net additive (helpers extracted, original function shrinks).

## 2. Goals

1. Eliminate the pyscn gate failures.
2. Improve readability of both functions — making the *intent* of each branch visible without scrolling through nested conditionals.
3. Preserve every existing test (no behavior change).

## 3. Non-Goals

- Adding new features to either function.
- Changing the public API of either class.
- Removing dead dispatch code in `workers/manager.py` (Plan A).
- Touching `creosote` / `refurb` / `ty` findings (Plan C).

## 4. The two refactors

### Task 1: `CloneTools.clone_refactor_group` (complexity 30 → ≤15)

The function name suggests it does ONE thing — kick off a clone-refactor group job — but the cyclomatic complexity (30) hints that it's accumulated validation, state-machine transitions, error recovery, and dispatching.

> **Decomposition is illustrative**: the table below is a hypothesis. Task 1 of execution (the discovery step) reads the function end-to-end and replaces this hypothesis with a concrete extraction plan grounded in what the function actually does.

*Illustrative decomposition (replace during discovery)*:

| Concern | Extract to | Why |
|---|---|---|
| Argument validation | `_validate_cluster_inputs(...)` | Pure validation; ~5-8 branches |
| State lookup | `_load_cluster_state(...)` | Hit MCP backend, return current state |
| State-machine transitions | `_transition_cluster_state(...)` | Pure transition logic, no I/O |
| Refute-check coordination | `_run_refute_check(...)` | Wrap the diverse-refuter flow |
| Operator-notification side effect | `_notify_operators(...)` | Pure side effect, easy to mock |

Each helper is ≤10 branches; the top-level `clone_refactor_group` becomes a linear flow: validate → load state → transition → refute → notify.

### Task 2: `SessionBuddyPool.execute_batch` (complexity 19 → ≤15)

Same illustrative-not-prescriptive note applies.

*Illustrative decomposition (replace during discovery)*:

| Concern | Extract to | Why |
|---|---|---|
| Per-task retry policy | `_compute_task_backoff(...)` | Pure function on retry settings |
| Per-task result aggregation | `_aggregate_batch_results(...)` | Reduces nested if/else accumulation |
| Per-task error handling | `_handle_batch_task_error(...)` | Single point that decides retry-vs-give-up |

The top-level `execute_batch` becomes: fan-out tasks → for each task, await result + `_handle_batch_task_error` → `_aggregate_batch_results`.

> **Note**: the *actual* decomposition depends on what the function does today. Task 1 of execution (the discovery step) is to read the function end-to-end and propose the *specific* extract-helper list, not guess it from the project overview.

## 5. Required changes

### Change 1 — Discovery + per-function complexity map (Task 1 of execution)

**Action**: Read both functions end-to-end. Produce a complexity map per function (which lines add the most branches, which are pure validation vs. side effects, which share a common shape that could be table-driven).

**Output**: A short markdown note in the plan's workspace (`<workspace>/complexity-map.md`) listing the proposed helper extractions and their branch counts. This is what the implementer dispatches against.

### Change 2 — Extract helpers (Tasks 2-3 of execution)

For each function:

1. Write a failing test that exercises one of the new helpers' behavior (TDD discipline).
2. Implement the helper.
3. Replace the original branch with a call to the helper.
4. Re-run the original function's tests to confirm no behavior change.
5. Commit.

### Change 3 — Update docstrings

Each extracted helper gets a one-line docstring. The original function's docstring gains a "Composition" section listing the helper calls in order.

## 6. Validation

| Check | Command | Expected |
|---|---|---|
| pyscn clean | `pyscn mahavishnu/mcp/tools/clone_tools.py mahavishnu/pools/session_buddy_pool.py` | 0 findings |
| Unit tests pass | `pytest tests/unit/test_clone_refactor_workflow.py tests/unit/test_mcp_pool_tools.py tests/unit/test_session_buddy_pool.py -v` | All green |
| Coverage | `pytest --cov=mahavishnu/mcp/tools/clone_tools --cov=mahavishnu/pools/session_buddy_pool --cov-report=term-missing` | No drop vs baseline |
| Diff scope | `git diff --stat` | Net additive; original functions smaller |

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Refactor accidentally changes behavior | Medium | Run full test suite per commit; gate on `git diff` review |
| Helper extraction creates a new public surface | Low | All helpers are `_underscore_prefix` private; original function remains the only public entry |
| Complexity gate moves (config change makes ≤15 invalid) | Very low | Gate is set in pyproject.toml; check first before refactoring |
| Coverage drops on extracted branches | Low | Each helper gets at least one unit test in Change 2 |

## 8. Decision Rule

This plan is "done enough" when:

1. `pyscn` reports 0 findings for both files.
2. All unit + integration tests for both subsystems pass unchanged.
3. Coverage does not regress.
4. Each extracted helper has its own focused unit test.
5. Original function sizes shrink by ≥30% each.

**Universal invariants** (per CLAUDE.md / memory):

6. No `git push`.
7. No version bump.
8. Pre-commit bypass via `git -c core.hooksPath=/dev/null commit`.
9. Git author `les@wedgwoodwebworks.com`.

## 9. Critical files

- `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py` — extract helpers, shrink `clone_refactor_group` to ≤15.
- `/Users/les/Projects/mahavishnu/mahavishnu/pools/session_buddy_pool.py` — extract helpers, shrink `execute_batch` to ≤15.
- `/Users/les/Projects/mahavishnu/tests/unit/test_clone_refactor_workflow.py` — add unit tests for new helpers (if not covered).
- `/Users/les/Projects/mahavishnu/tests/unit/test_session_buddy_pool.py` — same.

## 10. What I'm NOT doing (and why)

- **Refactoring `cluster_state_claim` in `clone_claims.py`** — pyscn did not flag it; leave it.
- **Renaming either function** — public API preservation.
- **Adding new dispatch modes** — feature work, not refactor.
- **Plan A** (workers/manager.py dead dispatch removal).

## Revision history

- **v1** (2026-09-26) — initial draft based on comprehensive-hook output 2026-09-26.
