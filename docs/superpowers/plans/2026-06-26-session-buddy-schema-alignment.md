# Session-Buddy v2/Legacy Schema Alignment Plan

**Status:** Drafted 2026-06-26, post-Plan-2 work
**Owner:** TBD (subagent-driven-development recommended)
**Trigger:** HANDOFF.md "2026-06-26 follow-up — Session-Buddy v2/legacy schema alignment" section; surfaced while closing Plan 2 quality-gate items.

## Goal

Clear the ~30 remaining session-buddy unit-test failures clustered in
`session_buddy/adapters/reflection_adapter_oneiric.py` and
`session_buddy/memory/schema_v2.py`. The root cause is a v2/legacy schema
interop gap: the v2 rewire routed `store_reflection` and `store_insight`
through `reflections_v2`, but the v2 DDL didn't carry over all legacy
columns, and several edge cases (`:memory:` init, transaction rollback,
reset order) were never wired.

**Scope estimate:** 2-3 days of TDD work. Not promoted to a tracked
HANDOFF.md plan-index row — fits the `superpowers:subagent-driven-development`
pattern better than the multi-phase plan pattern.

**Pre-state (working tree, uncommitted):**

- `metadata JSON` column added to `reflections_v2` in `schema_v2.py` +
  `ALTER TABLE reflections_v2 ADD COLUMN IF NOT EXISTS metadata JSON`
  (DONE — uncommitted)
- `:memory:` early-return removed from `initialize()` so in-memory
  DuckDB connections actually get opened (DONE — uncommitted)
- ROLLBACK guards added after every `with suppress(Exception)` ALTER
  TABLE block in `_create_tables` and `_create_v2_schema` so a single
  failed DDL doesn't poison the rest of the migration (DONE — uncommitted)
- Lazy-init guard added to `store_insight` for tests that bypass
  `__aenter__` (DONE — uncommitted)

**Reduces 73 → ~30 failures** (per 2026-06-26 run). The remaining
~30 cluster as documented below.

## Architecture

Single-repo fix touching two files (`schema_v2.py` +
`reflection_adapter_oneiric.py`). Each task is TDD-red-green: write a
failing test that reproduces the failure, then fix the code, then
re-run the test file to confirm green.

The choice between two architectural directions is open:

**(a) Hybrid alignment (recommended):** Make the legacy CREATE TABLE in
`reflection_adapter_oneiric.py:540-557` include all v2 columns
(`timestamp`, `memory_tier`, `category`, etc.) plus all insight-specific
columns. Then either path produces a compatible schema. Pros: minimal
disruption, both code paths keep working. Cons: schema definition
duplicated between `schema_v2.py` and `reflection_adapter_oneiric.py`.

**(b) Drop legacy path:** Make `_create_v2_schema` the only schema
source. The legacy `CREATE TABLE IF NOT EXISTS {self._table("reflections")}`
becomes a no-op. Pros: single source of truth. Cons: requires
verifying every caller of the legacy path still works (3 reflection
adapter variants, the `Insights` class, the `MemoryGuard` integration).

Decision deferred to the implementer after Tasks 1-3 complete — the
choice becomes clear once the legacy/v2 column gap is quantified.

## Tasks

### Task 1: Add v2 columns to legacy CREATE TABLE (Bug D)

**Symptom (red):** `BinderException: Table "reflections_v2" does not have a column named "timestamp"` at
`test_reflection_adapter_oneiric.py:580` (and several others).

**Root cause:** The legacy CREATE TABLE block at
`reflection_adapter_oneiric.py:540-557` creates a `reflections` table
without v2 columns (`timestamp`, `memory_tier`, `category`,
`related_entities`, `namespace`, `project`, `access_count`,
`last_accessed`, `embedding FLOAT[384]`, `tags TEXT[]`). The
`CREATE INDEX` at line 580 indexes `timestamp` on `reflections_v2`,
which fails when the table was created via the legacy path.

**Fix:** Extend the legacy CREATE TABLE to include v2 columns as
nullable defaults. Run `test_reflection_adapter_oneiric.py` — should
go from 13 failing/errored to 0 failing/errored in this file.

**Acceptance:** `test_reflection_adapter_oneiric.py` reports 0 failed,
0 errored. Indexes that depend on `timestamp` are created without
BinderException.

### Task 2: Fix `_reset_database` table-drop order (Bug E)

**Symptom (red):** `CatalogException: Could not drop the table because this table is main key table of the table "memory_entities"` at
`test_reflection_adapter.py:454` and `test_reflection_adapter_oneiric.py:639,648`.

**Root cause:** `_reset_database` drops `conversations_v2` before
`memory_entities`, but `memory_entities.conversation_id` has a
`FOREIGN KEY` reference to `conversations_v2.id`. DuckDB requires
dependent tables to be dropped before the referenced table.

**Fix:** Reorder `_reset_database` to drop `memory_entities` and
`memory_relationships` first, then `conversations_v2` and
`reflections_v2`. Same for any other FK-referencing tables.

**Acceptance:** `test_reset_database_clears_data` and
`test_reset_recreates_tables` both pass.

### Task 3: Fix health-check re-init after close (Bug F)

**Symptom (red):** `assert False is True` at
`test_reflection_adapter_oneiric.py:392` (test_health_check_initializes_if_uninitialized),
plus `test_health_check_after_close` errors.

**Root cause:** After `await db.close()`, subsequent operations that
try to access `self.conn` raise `'NoneType' object has no attribute 'execute'`
or fail health checks because `self._initialized` is True but `self.conn`
is None.

**Fix:** Either (a) make `close()` reset `self._initialized = False` so
a subsequent operation triggers lazy re-init, or (b) make health checks
lazy-init too. Option (a) is cleaner — single source of truth for
connection lifecycle.

**Acceptance:** `test_health_check_after_close` passes; calling `close()`
then `health_check()` returns the correct status.

### Task 4: Fix `test_worktree_manager.py` and `test_health_checks.py` failures

**Symptom (red):** 5 failures in `test_git_operations.py` (worktree +
prune-delay test setup drift), 4 failures in `test_health_checks.py` +
`test_health_checks_core.py` (dependency-health message mismatch), 2
failures in `test_memory_tools.py` (validation message lower-cased at
assert site + `MemoryGuardBlockedError` UnboundLocalError).

**Root cause:** Three separate test-vs-code mismatches, NOT schema bugs:

1. `test_worktree_manager.py:433,488,897,962,998` — `tmp_git_repo` mock
   ignored; real `git worktree list` returns the main worktree.
1. `test_health_checks.py:562,696,716` and
   `test_health_checks_core.py:312` — dependency-health message format
   changed (added "1 features available, 3 unavailable" format).
1. `test_memory_tools.py:380` — `'validation' not in 'testop failed: bad input'` (message was lower-cased at production site but assert uses
   `'validation'`). `:1340` — `MemoryGuardBlockedError` is imported
   inside an `except` block that's never triggered, so the name is
   unbound at the second `except`.

**Fix:** For each, the test is the source of truth (TDD discipline:
the test tells you what the contract is; update production OR test,
don't update both arbitrarily). Recommendation: update tests to match
the new contract — these are integration tests asserting on
internal-error formats that are allowed to drift.

**Acceptance:** All 11 failures pass.

### Task 5: Final test sweep + coverage

**Action:** Run `uv run pytest tests/unit/ -m unit --tb=short -q 2>&1 | grep -E '(passed|failed)'`. Expect 0 failed.

If coverage gate (`tests/unit/ -m unit --cov=session_buddy`) is part
of CI, confirm coverage stays >= 80%. The schema fixes should not
decrease coverage.

**Acceptance:** 0 failed. Coverage >= 80%.

### Task 6: Commit strategy

Recommend **one PR per task** for clean bisect, OR one consolidated
PR titled "v2/legacy schema alignment" covering Tasks 1-3 + the
working-tree pre-state. Task 4 (test-vs-code mismatches) is unrelated
to schema — separate PR titled "fix: align test fixtures with
current error message contracts".

## Critical files

- `session_buddy/memory/schema_v2.py` — add v2 columns to legacy DDL
  equivalent (if direction (a) chosen)
- `session_buddy/adapters/reflection_adapter_oneiric.py` — schema
  alignment + drop order + health-check lifecycle
- `session_buddy/adapters/reflection_adapter.py` — same fixes apply
  via the legacy `ReflectionDatabaseAdapter` class (verify Task 1 fix
  reaches this adapter too)
- `tests/unit/test_reflection_adapter.py` — Task 1-3 verification
- `tests/unit/test_reflection_adapter_oneiric.py` — Task 1-3 verification
- `tests/unit/test_health_checks.py`, `test_worktree_manager.py`,
  `test_memory_tools.py` — Task 4 fixtures

## Out of scope

- Restructuring the legacy/v2 path into a single source of truth
  (architectural direction (b)) — defer until Tasks 1-3 validate
  direction (a).
- The `MemoryGuard` policy semantics in
  `session_buddy/security/memory_guard_adapter.py` (Plan 2 Task 16
  partial — `exclude_tags` filter on `search_conversations`).
- The `crackerjack` side of the betterleaks / CVE work — already
  shipped in commits `c9d22674` and `b2719121`.

## Execution mode

Recommended: `superpowers:subagent-driven-development` — one subagent
per task with TDD discipline (`superpowers:test-driven-development`
already loaded). Expected wall-clock: 2-3 days for one engineer or one
focused subagent session.

## Acceptance criteria for closing this plan

1. All 5 tasks completed with passing tests
1. Session-buddy unit test sweep: 0 failed, coverage >= 80%
1. PR(s) merged (or stacked commits ready for review)
1. HANDOFF.md updated: this plan file is referenced in the
   "2026-06-26 follow-up" section with a completion note
