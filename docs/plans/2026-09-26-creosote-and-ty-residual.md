---
status: draft
role: implementation
date: 2026-09-26
last_reviewed: 2026-09-26
topic: creosote-and-ty-residual
revision: v1
plan_status: ready-for-execution
---

# Plan C: creosote `e2b` Audit + ty `RateLimitError` Catch Fix

> **Origin**: surfaced by comprehensive-hook failure 2026-09-26.
> - `creosote` flagged `e2b` as unused; also flagged `coredis` exclusion as redundant.
> - `ty` flagged `pool_tools.py:351` — "Invalid object caught in an exception handler: Object has type `<class 'RateLimitError'> | None`".

## Headline finding

Three findings; the right call differs per finding:

| Finding | Real or false positive? | Action |
|---|---|---|
| `creosote`: `coredis` exclusion redundant | **False positive** — `bodai_hook_bridge.py:55` does `import coredis  # noqa: F401` as a runtime probe; exclusion is load-bearing (see pyproject.toml:612-620 for documented reason) | **Skip** |
| `creosote`: `e2b` unused | **Likely real** — `e2b_sandbox.py` was removed (Phase 4.5b per `docs/decisions/2026-09-24-legacy-worker-deprecation.md`), but `WorkerCategory.E2B = "e2b"` and `WorkerConfig("e2b-sandbox", ...)` entries remain in `workers/registry.py` for migration/documentation purposes. Removing the package dep is safe IF no source code imports `e2b` directly. | **Audit + remove if clean** |
| `ty`: `RateLimitError \| None` caught | **Real bug** — the variable being caught is sometimes `None` due to import-time conditional logic, so the `except` block can never fire even when a rate limit is hit | **Fix the catch** |

## 1. Outcome

After this plan ships:

- `creosote` reports no `e2b` unused-dep finding (assuming the audit confirms no source uses it).
- `ty check mahavishnu/mcp/tools/pool_tools.py` reports 0 errors.
- The `coredis` exclusion is preserved (no false-positive fix).
- All existing tests pass.

**Proof it worked**:

- `creosote .` — 0 findings (or only known-false-positives).
- `ty check mahavishnu/mcp/tools/pool_tools.py` — 0 errors.
- `pytest tests/unit/test_mcp_pool_tools.py -v` — all green.

## 2. Goals

1. Drop the `e2b` dependency if no source imports it (audit-driven).
2. Fix the `RateLimitError | None` catch so rate-limit errors are actually caught.
3. Do not touch `coredis` (false positive — exclusion is correct).

## 3. Non-Goals

- Plan A (`workers/manager.py` dead dispatch removal) — separate.
- Plan B (pyscn complexity reduction) — separate.
- Removing `WorkerCategory.E2B` enum entry (deferred; might still be valid for routing/migration tooling).
- Removing `WorkerConfig("e2b-sandbox", ...)` entry in `workers/registry.py` (might still be referenced by docs or migration tooling — out of scope).

## 4. The two fixes

### Fix 1: ty `RateLimitError | None` catch in `pool_tools.py:351`

**Read first**: the current code at `mahavishnu/mcp/tools/pool_tools.py:351`. The variable being caught is `rate_limit_error_class` (or similar). Inspect why it's `None`:

- If it's `None` because the import failed (e.g., `slowapi` is an optional dep): the right fix is to **not catch `None`** — make the import required, or guard the entire rate-limit block with `if rate_limit_error_class is not None:`.
- If it's `None` because the variable is conditionally bound: trace why, and either bind it unconditionally or restructure the except.

The fix is mechanical once the root cause is known. The change is ≤5 lines in `pool_tools.py`.

### Fix 2: `e2b` dependency audit + removal

**Discovery** (Task 1 of execution):

```bash
grep -rn "import e2b\|from e2b\|e2b\." mahavishnu/ tests/ docs/ 2>&1 | head -50
```

If grep returns **only** the entries already known (worker registry enum + `WorkerConfig` + `mahavishnu_pool.py:64` docstring comment + `mahavishnu_publisher.py:181` docstring + `shepherd_backend.py:186,445` docstrings + `workers/__init__.py:7` retired list + `workers/manager.py:72,77,117` comments), then:

- Source code does NOT import `e2b` directly.
- The `e2b` package is pulled in only because something declared it as a dep and it transitively dragged in the package.
- Removing `e2b` from `pyproject.toml:240` is safe.

If grep returns ANY actual `import e2b` or `from e2b import ...` line in `mahavishnu/` or `tests/`, **stop** — the dep is in use and the audit needs to extend to figure out what pulls it (the orchestrator-side worker factory that Plan A will delete, perhaps).

**Removal**:

1. Edit `pyproject.toml:240` — drop the `e2b` line and its leading comment block.
2. Run `uv lock --no-update` to refresh `uv.lock` without upgrading other packages.
3. Run `uv sync` to refresh the venv.
4. Re-run creosote: `creosote .` — `e2b` finding gone.

## 5. Required changes

### Change 1 — Fix the `RateLimitError | None` catch

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/pool_tools.py:351`

Read the surrounding 30 lines. Determine why the variable is `None`. Apply the appropriate fix (most likely: restructure to not bind to `None`; or add a guard `if rate_limit_error_class is not None: try: ... except rate_limit_error_class: ...`).

### Change 2 — Audit `e2b` usage

**Command**: `grep -rn "import e2b\|from e2b\|e2b\." mahavishnu/ tests/ docs/`

**Decision**: if only docstrings + registry entries (no real imports), proceed with Change 3. Otherwise stop and surface to user.

### Change 3 — Remove `e2b` from `pyproject.toml`

**File**: `/Users/les/Projects/mahavishnu/pyproject.toml` (around line 240, the `e2b` comment + dep line)

Remove the comment block + dep line.

### Change 4 — Refresh lockfile and venv

```bash
uv lock --no-update
uv sync
```

**Note**: per `feedback-bodai-venv-target-with-both-flags.md` and `uv-active-and-virtual-env-cross-repo.md`, if `VIRTUAL_ENV` is set from a different repo, strip it first.

### Change 5 — Add a regression test for the rate-limit catch (if practical)

If the fix involves restructuring, the existing tests should already cover the happy path. If the existing tests don't cover the rate-limit catch (likely, since it was never firing), add one test that asserts rate-limit errors are *actually caught* (not silently propagated or missed).

## 6. Validation

| Check | Command | Expected |
|---|---|---|
| ty clean | `ty check mahavishnu/mcp/tools/pool_tools.py` | 0 errors |
| creosote clean | `creosote .` | No `e2b` finding |
| Pool tests pass | `pytest tests/unit/test_mcp_pool_tools.py -v` | All green |
| Lockfile consistency | `uv lock --check` | No drift |
| Diff scope | `git diff --stat` | ≤4 files, ≤30 lines |

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `e2b` IS imported somewhere we didn't grep | Low | Discovery step runs the grep with `-rn` recursively |
| Removing `e2b` breaks a transitive dep that uses it | Low | `uv lock` will fail if any other declared dep requires it; if so, halt and surface |
| The `RateLimitError` fix changes behavior subtly | Medium | Existing tests should catch it; add regression test if not |
| `uv lock --no-update` still drags in unrelated bumps | Low | `--no-update` flag preserves versions for packages not in the changed set |

## 8. Decision Rule

This plan is "done enough" when:

1. `ty check mahavishnu/mcp/tools/pool_tools.py` reports 0 errors.
2. `creosote .` does NOT report `e2b` as unused.
3. `pytest tests/unit/test_mcp_pool_tools.py` passes.
4. `uv lock --check` passes (lockfile consistent with pyproject.toml).

**Universal invariants** (per CLAUDE.md / memory):

5. No `git push`.
6. No version bump.
7. Pre-commit bypass via `git -c core.hooksPath=/dev/null commit`.
8. Git author `les@wedgwoodwebworks.com`.
9. `coredis` exclusion is NOT touched (false positive — exclusion is correct).

## 9. Critical files

- `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/pool_tools.py` — fix `RateLimitError | None` catch (around line 351).
- `/Users/les/Projects/mahavishnu/pyproject.toml` — drop `e2b` line + comment.
- `/Users/les/Projects/mahavishnu/uv.lock` — refreshed by `uv lock --no-update`.
- `/Users/les/Projects/mahavishnu/tests/unit/test_mcp_pool_tools.py` — add regression test if applicable.

## 10. What I'm NOT doing (and why)

- **Touching the `coredis` exclusion** — verified false positive (`bodai_hook_bridge.py:55` does `import coredis` as a runtime probe; pyproject.toml:612-620 documents why the exclusion exists).
- **Plan A** (workers/manager.py dead dispatch removal) — separate.
- **Plan B** (pyscn complexity reduction) — separate.
- **Removing `WorkerCategory.E2B` or `WorkerConfig("e2b-sandbox", ...)` entries** — separate audit.

## Revision history

- **v1** (2026-09-26) — initial draft based on comprehensive-hook output 2026-09-26.
