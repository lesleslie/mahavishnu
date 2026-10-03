---
status: draft
role: implementation
date: 2026-09-26
last_reviewed: 2026-09-26
topic: workers-manager-dead-dispatch-removal
revision: v1
plan_status: ready-for-execution
---

# Plan A: Remove dead non-isolated dispatch factory in `workers/manager.py`

> **Origin**: surfaced by comprehensive-hook failure 2026-09-26 — `ty` reports 6× `Cannot resolve imported module` against `mahavishnu/workers/manager.py` lines 399/413/417/429/448/489, all referring to sibling modules (`.generic_shell`, `.crow`, `.application`, `.openclaw_gateway`, `.a2a`) that no longer exist.

## Headline finding

`WorkerManager` contains a **second worker factory** alongside the already-clean `_create_isolated_worker` (lines 64-113). That second factory — a chain of `elif config.category in (...)` branches starting around line 350 — dispatches to six sibling modules that no longer exist:

| Line | Import | Target module | Status |
|------|--------|---------------|--------|
| 399 | `from .generic_shell import GenericShellWorker` | `workers/generic_shell.py` | **REMOVED** (per `workers/__init__.py:7`) |
| 413 | `from .crow import CrowWorker` | `workers/crow.py` | **REMOVED** |
| 417 | `from .generic_shell import GenericShellWorker` | (same as above) | **REMOVED** |
| 429 | `from .application import ApplicationWorker` | `workers/application.py` | **REMOVED** |
| 448 | `from .openclaw_gateway import (...)` | `workers/openclaw_gateway.py` | **REMOVED** |
| 489 | `from .a2a import A2AAgentConfig, A2AWorker` | `workers/a2a.py` | **REMOVED** |

The first factory (`_create_isolated_worker`) already replaced Apple/E2B with `shepherd`. **The second factory is the leftover non-isolated dispatch surface** from before the pivot to `shepherd` + `mahavishnu/pools/`. Every branch in it raises `ModuleNotFoundError` at runtime if reached.

## 1. Outcome

After this plan ships:

- `ty` reports 0 errors for `workers/manager.py`.
- `WorkerManager.create_worker` either (a) delegates everything to `_create_isolated_worker` (which only accepts `"shepherd"`), OR (b) is renamed/restructured so the dead dispatch chain is gone.
- `workers/__init__.py:7` retired-worker list and the manager's dispatch surface are consistent (single source of truth: "use shepherd for isolated, use pools for non-isolated").
- All existing tests pass; tests covering retired worker types are updated or removed.
- `pyscn` complexity for `clone_tools.py:245` is **not** in this plan's scope (covered by Plan B).

**Proof it worked**:

- `pytest tests/unit/test_worker_manager.py tests/integration/test_worker_manager_e2e.py` — passes.
- `ty check mahavishnu/workers/manager.py` — 0 errors.
- `git grep -nE "from \.generic_shell|generic_shell_worker|crow_worker|application_worker|a2a_worker|openclaw_gateway" mahavishnu/ workers/` — 0 hits in source.

## 2. Goals

1. Remove the dead non-isolated dispatch factory so `ty` and runtime both agree about which workers exist.
2. Establish a clear single dispatch rule: isolated = `shepherd` via `_create_isolated_worker`; everything else = route via `mahavishnu/pools/` (no `WorkerManager` dispatch for non-isolated).
3. Make the manager surface small enough that no future contributor re-adds a dead dispatch branch.

## 3. Non-Goals

- pyscn complexity reduction (`clone_tools.py:245`, `session_buddy_pool.py:281`) — Plan B.
- Removing `WorkerCategory` enum entries for retired categories (separate audit, possibly its own plan).
- Removing `WorkerConfig` entries from `workers/registry.py` (separate audit; might still be used by documentation or migration tooling).
- Touching `docs/decisions/2026-09-24-legacy-worker-deprecation.md` (already exists, already correct).

## 4. The shape of the fix

### Decision: route through `_create_isolated_worker` only

The cleanest design is to **delete the entire `elif`-chain dispatch** in the second factory and have `WorkerManager.create_worker` route *every* request through `_create_isolated_worker`. This means:

- A `WorkerManager` instantiation can only produce `ShepherdBackendWorker`.
- Non-isolated workloads go through pools, not through `WorkerManager` — that's already the documented posture (`docs/POOL_ARCHITECTURE.md` §2, just landed in commit `688aeece`).

### What this means for callers

| Call site | Current behavior | After fix |
|-----------|------------------|-----------|
| `WorkerManager.create_worker("shepherd", ...)` | Returns `ShepherdBackendWorker` | Same ✅ |
| `WorkerManager.create_worker("e2b-sandbox", ...)` | `ModuleNotFoundError` at line 489 | Clean `ValueError` from `_create_isolated_worker` pointing at the migration ADR ✅ |
| `WorkerManager.create_worker("crow", ...)` | `ModuleNotFoundError` at line 413 | Same clean `ValueError` ✅ |
| `WorkerManager.create_worker("a2a", ...)` | `ModuleNotFoundError` at line 489 | Same ✅ |
| `WorkerManager.create_worker("openclaw", ...)` | `ModuleNotFoundError` at line 448 | Same ✅ |
| `WorkerManager.create_worker("generic-shell", ...)` | `ModuleNotFoundError` at line 399 | Same ✅ |
| `WorkerManager.create_worker("application", ...)` | `ModuleNotFoundError` at line 429 | Same ✅ |

**Every retired worker_type now raises the same helpful `ValueError` from one place.** That's an improvement over today's mix of clean-raise and `ModuleNotFoundError`.

### Why NOT auto-migrate to shepherd

We considered silently redirecting "e2b-sandbox" → "shepherd" but rejected it:

- Shepherd and E2B have **different security models**: shepherd is an OS-level syscall-jail (fail-closed), E2B was a Firecracker microVM. A silent migration would change the isolation guarantee the caller asked for.
- Shepherd requires `writable_root` (per `_create_isolated_worker:84-91`); E2B callers wouldn't have it.
- Better to fail loud with a clear migration message.

## 5. Required changes

### Change 1 — Delete the dead dispatch chain in `WorkerManager.create_worker`

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/workers/manager.py`

**Lines to remove**: the entire `elif` chain from the first `elif config.category in (WorkerCategory.SHELL, WorkerCategory.REMOTE):` (around line 394) through the end of the dispatch function. Replace with a single call to `_create_isolated_worker(worker_type, ...)`.

**Approach**:

1. Add a private `_create_isolated_worker_from_config(config, kwargs)` helper that adapts a `WorkerConfig` to the kwargs shape `_create_isolated_worker` already accepts.
2. `WorkerManager.create_worker` becomes:

   ```python
   def create_worker(self, config: WorkerConfig, **kwargs: Any) -> BaseWorker:
       return _create_isolated_worker_from_config(config, kwargs)
   ```

3. The `_require_ready` + `_validate_required_env` + `_validate_required_tool` methods stay (they use the new registry, not the dead dispatch chain).

### Change 2 — Update `WorkerManager` docstring

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/workers/manager.py` (lines 122-138)

Replace the multi-bullet Feature list (lines 125-131) with a short statement: "Manages isolated-execution workers (`worker_type == "shepherd"` only). Non-isolated workloads route through `mahavishnu/pools/`."

### Change 3 — Audit tests for retired worker types

**Files**: `tests/unit/test_worker_manager.py`, `tests/integration/test_worker_manager_e2e.py`, `tests/unit/test_worker_capabilities.py` (anywhere that constructs `WorkerConfig` with a retired `worker_type`).

For each test:

- If it tests retired dispatch behavior → update to assert the new clean `ValueError` from `_create_isolated_worker` (using `pytest.raises(ValueError, match="legacy isolated-worker surface has been retired")`).
- If it tests the `_validate_*` methods → keep, those still work.
- If it tests happy-path shepherd creation → keep, no change.

### Change 4 — Add a regression test

**File**: `tests/unit/test_worker_manager.py`

Add `test_create_worker_retired_types_raise_value_error` that asserts every retired `worker_type` (`"e2b-sandbox"`, `"apple-container"`, `"terminal-crow"`, `"a2a"`, `"openclaw"`, `"openhands"`, `"generic-shell"`, `"application"`) raises the documented `ValueError` from one place (not `ModuleNotFoundError`).

### Change 5 — Update CLAUDE.md if needed

**File**: `/Users/les/Projects/mahavishnu/CLAUDE.md` (workers/manager.py section)

If the CLAUDE.md description of `WorkerManager` mentions terminal/container/application workers (it does — line 125 in the docstring currently does), update it to reflect the post-fix reality: only shepherd, plus the existing pointer to `mahavishnu/pools/`.

## 6. Validation

| Check | Command | Expected |
|---|---|---|
| Type check passes | `ty check mahavishnu/workers/manager.py` | 0 errors |
| Unit tests pass | `pytest tests/unit/test_worker_manager.py -v` | All green |
| Integration tests pass | `pytest tests/integration/test_worker_manager_e2e.py -v` | All green |
| No stale imports | `git grep -nE "from \.generic_shell|from \.crow|from \.application|from \.openclaw_gateway|from \.a2a" mahavishnu/workers/` | 0 hits |
| No dead worker types referenced in source | `git grep -nE "generic_shell_worker|crow_worker|application_worker|a2a_worker|openclaw_gateway_worker" mahavishnu/` | 0 hits |
| pyscn complexity (out of scope, but no regression) | `pyscn mahavishnu/workers/manager.py` | No new functions over threshold |
| Diff scope | `git diff --stat` | ≤5 files, ≤200 lines removed (mostly negative diff) |

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Test suite has 100+ tests parametrized over retired worker types | Medium | Discovery step (Task 1) maps every test first; we adapt, not rewrite |
| A non-Bodai consumer of `WorkerManager` exists and relies on retired types | Low | `WorkerManager` is in the `mahavishnu.workers` package — internal. CLAUDE.md posture already says non-isolated = pools |
| Removing the dispatch factory breaks a transitive caller that bypasses `create_worker` | Medium | Discovery step greps every callsite; the `_create_isolated_worker` is the only valid entry point post-fix |
| Coverage drops below `--cov-fail-under=89.02` | Low | Removing dead code that wasn't covered anyway shouldn't move coverage; if it does, the test additions in Change 4 compensate |

## 8. Decision Rule

This plan is "done enough" when:

1. `ty check mahavishnu/workers/manager.py` reports 0 errors.
2. `pytest tests/unit/test_worker_manager.py tests/integration/test_worker_manager_e2e.py` passes.
3. `git grep` for the 6 stale-import patterns returns 0 hits in `mahavishnu/`.
4. The new regression test (`test_create_worker_retired_types_raise_value_error`) passes.
5. `pyscn` reports no NEW functions over the complexity threshold (existing-threshold functions are out of scope).
6. Working tree diff is ≤5 files and net-negative (mostly deletions).

**Universal invariants** (per CLAUDE.md / memory):

7. No `git push` (per `feedback-bodai-push-is-user-controlled.md`).
8. No version bump (per `feedback-mcp-common-version-bump-is-user.md`).
9. Pre-commit bypass via `git -c core.hooksPath=/dev/null commit` (per `mahavishnu-worktree-precommit-blocks-workers.md`).
10. Git author `les@wedgwoodwebworks.com` (per `git-author-email-correct-domain.md`).

## 9. Critical files

- `/Users/les/Projects/mahavishnu/mahavishnu/workers/manager.py` — delete dead dispatch chain (lines ~350-490).
- `/Users/les/Projects/mahavishnu/tests/unit/test_worker_manager.py` — update tests for retired types, add regression test.
- `/Users/les/Projects/mahavishnu/tests/integration/test_worker_manager_e2e.py` — same.
- `/Users/les/Projects/mahavishnu/CLAUDE.md` — update `WorkerManager` description if it lists retired categories.

## 10. What I'm NOT doing (and why)

- **Removing `WorkerCategory` enum entries** — that's a separate audit; some retired categories might still be valid identifiers for routing/migration tooling even though no live dispatch consumes them. Out of scope here.
- **Removing `WorkerConfig` entries from `workers/registry.py`** — same reason; out of scope.
- **Renaming `WorkerManager`** — the class still has a valid role (shepherd lifecycle); renaming is bikeshedding.
- **pyscn complexity fixes** — Plan B.

## Revision history

- **v1** (2026-09-26) — initial draft based on comprehensive-hook output 2026-09-26.
