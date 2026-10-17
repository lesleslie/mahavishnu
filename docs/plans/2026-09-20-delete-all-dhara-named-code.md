---
date: 2026-09-20
status: complete
role: implementation
topic: delete-all-dhara-named-code
last_reviewed: 2026-10-17
superseded_by: null

# Verified complete 2026-10-17 (crackerjack repo):
# - `crackerjack/integration/dhara_mcp_client.py` deleted
# - `DharaMCPSettings` class gone from `crackerjack/config/settings.py`
# - `DharaSOPPersister` class gone from `crackerjack/sop/persisters.py`
# - Zero `DharaMCPSettings|DharaMCPConfig|DharaMCPClient|DharaAdapterLearner|
#   DharaMCPAdapterLearner|DharaSOPPersister` references in crackerjack/ or tests/
# - The `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md`
#   followup still needs its status flipped to complete (Phase 5 of the plan)
---

# Plan: Delete all remaining Dhara-named code

## Context

The previous rename plan (`dhara_integration.py` → `adapter_learning.py`) cleaned up the main integration module, but left four Dhara-named surfaces behind because their right answer was **deletion**, not rename. The user has now asked for those deletions to happen:

1. `crackerjack/integration/dhara_mcp_client.py` — Dhara MCP transport wrapper
2. `crackerjack/config/settings.py:366 DharaMCPSettings` — orphan settings class
3. `crackerjack/sop/persisters.py:32 DharaSOPPersister` — unimplemented stub
4. Stale tests that reference symbols removed during the 2026-09-20 Dhara decommissioning

**Verdict from evidence (per Explore agent's mapping)**:
- **All three modules/classes have ZERO production consumers.** `DharaMCPConfig` / `DharaMCPClient` has no internal callers (the docstring's claimed consumers — `failure_metrics_repository.py`, `dhara_integration.py` — have already been gutted). `DharaMCPSettings` is not referenced anywhere except its own definition; not wired into `CrackerjackSettings` root model. `DharaSOPPersister` is a stub where every method raises `NotImplementedError` (Dhara's `project_sops` collection will never land).
- **All stale tests have ZERO surviving test cases.** `test_aio_thread_leak_regression.py`, `dhara_mcp_adapter_learner_test.py`, `dhara_mcp_client_test.py` are 100% obsolete (every test in them dies when the corresponding code is gone).
- **Zero cross-repo blast radius.** Grep across `mahavishnu`, `session-buddy`, `akosha`, `mcp-common`, `oneiric` shows no source-code importers of any of these symbols. Markdown mentions in those repos are historical artifacts.

**Intended outcome**: crackerjack no longer contains a single `Dhara*` symbol. New readers land on the current state (SQLite-only adapter learner, in-memory SOP persister, settings without Dhara MCP) without having to learn what Dhara was or why it's gone.

**Out of scope (intentional non-changes)**:
- `crackerjack/services/failure_metrics_repository.py` — flagged by the Explore agent as a related "silent no-op wrapper" left over from the same decommissioning, but the user did not ask for it and it has live consumers (`failure_recorder.py:14,93`, `improvement_generator.py:12,39`). Cleaning it up would require migrating those callers to Mahavishnu's `mcp__mahavishnu__upsert_service` / `mcp__mahavishnu__record_event` per `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` § "What to delete" #2a. That's a separate Mahavishnu-tools migration, not a Dhara-cleanup task.
- Cross-repo markdown artifacts referencing Dhara (`mahavishnu/reports/`, `mahavishnu/docs/superpowers/plans/`, etc.) — historical only; the docs-audit convention is to leave historical mentions in place.
- `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` — keep the followup document itself but flip its `status: draft` → `status: complete` (or similar) once the deletion lands. This signals to future readers that the work is done.

## Approach

### Phase 1 — delete the three modules/classes

**1a. `crackerjack/integration/dhara_mcp_client.py`**: `git rm`.

**1b. `crackerjack/config/settings.py:366`** — delete the `DharaMCPSettings` class. Open the file, identify the exact class block (it's 5 lines: class header + 4 field assignments), and remove it. Check whether the file imports `OneiricMCPConfig` *only* for this class — if removing the class leaves `OneiricMCPConfig` unused, remove that import too.

**1c. `crackerjack/sop/persisters.py:32`** — delete the `DharaSOPPersister` class (all three methods raise `NotImplementedError`; the class is documented as a stub awaiting a never-implementing Dhara feature). Remove from the same file's import block if it references any now-unused module imports.

**1d. `crackerjack/sop/__init__.py:14,20`** — remove `DharaSOPPersister` from the `from … import …` block and from the `__all__` list.

### Phase 2 — delete three entirely-obsolete test files

All three files contain only tests for symbols being deleted in Phase 1; no test cases survive:

- `git rm tests/integration/dhara_mcp_client_test.py` — 286 lines, all `DharaMCPClient` / `DharaMCPConfig` tests
- `git rm tests/integration/dhara_mcp_adapter_learner_test.py` — 204 lines, all `DharaMCPAdapterLearner` tests
- `git rm tests/integration/test_aio_thread_leak_regression.py` — regression test specifically for the now-deleted `DharaAdapterLearner`; even its docstring names the regression target

### Phase 3 — trim `tests/integration/test_adapter_learning.py`

The file has ~250 lines of dead tests that pass via `import crackerjack.integration.dhara_integration as mod` (a module that no longer exists). They fail at collection time, blocking the alive tests from being collected.

Delete in order:

- **Line 18**: `from crackerjack.integration.dhara_mcp_client import DharaMCPConfig` — import is gone with the module
- **Lines 20-32**: `_DHARA_HAS_ASYNC_CONNECTION` block + `requires_dhara_async_connection` decorator — only used by the dead `TestDharaAdapterLearner`
- **`TestDharaAdapterLearner` class** (around lines 364-422, gated by `requires_dhara_async_connection`)
- **`TestFactoryBackendSelection` class** (around lines 460-660, mostly dead — but `test_sqlite_backend_explicit` at lines 416-423 is alive; **lift that one test out** into a new top-level class or append it to an existing alive class like `TestCreateAdapterLearner` before deleting `TestFactoryBackendSelection`)
- **Three module-level tests at the end** (~lines 688-760) — `test_factory_prefers_mcp_when_server_reachable`, `test_factory_falls_back_to_noop_when_everything_fails`, `test_factory_respects_dhara_mcp_disabled_flag` — all monkeypatch `_load_dhara_mcp_config` on a gone module

Keep the alive classes verbatim: `TestAdapterAttemptRecord`, `TestNoOpAdapterLearner`, `TestCreateAdapterLearner` (with my 4 quarantine tests), `TestSQLiteAdapterLearner`, `TestAdapterLearningIntegration`. The lifted `test_sqlite_backend_explicit` test joins the survivors.

### Phase 4 — trim `tests/unit/test_sop_evolution.py`

The `DharaSOPPersister` is deleted in 1c, so its two tests must go too:

- **Import block** (line 34): drop `DharaSOPPersister`
- **Class `TestDharaSOPPersister`** (lines 256-280) — two tests, both stub-validation. `test_stub_raises_not_implemented` and `test_stub_is_sop_persister`. Delete the whole class.
- **Module docstring** (line 13): drop the line "``DharaSOPPersister`` stub raises ``NotImplementedError`` (documented stub)"

### Phase 5 — mark the decomp followup done

Open `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` and update the front-matter:
- `status: draft` → `status: complete`
- `last_reviewed: 2026-09-14` → `last_reviewed: 2026-09-20`

This is a low-stakes metadata update so future readers see the work is done. The body stays as historical context.

## Files to modify (summary)

| File | Change |
|---|---|
| `crackerjack/integration/dhara_mcp_client.py` | **delete** |
| `crackerjack/config/settings.py` | remove `DharaMCPSettings` class (+ clean up `OneiricMCPConfig` import if now unused) |
| `crackerjack/sop/persisters.py` | remove `DharaSOPPersister` class |
| `crackerjack/sop/__init__.py` | remove `DharaSOPPersister` from imports + `__all__` |
| `tests/integration/dhara_mcp_client_test.py` | **delete** |
| `tests/integration/dhara_mcp_adapter_learner_test.py` | **delete** |
| `tests/integration/test_aio_thread_leak_regression.py` | **delete** |
| `tests/integration/test_adapter_learning.py` | trim ~250 lines of dead tests; lift alive `test_sqlite_backend_explicit` test |
| `tests/unit/test_sop_evolution.py` | drop `TestDharaSOPPersister` class + import |
| `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` | update `status` to `complete`, `last_reviewed` to today |

## Verification

1. **Zero Dhara references survive in production code**:
   ```bash
   rg -l "DharaMCPSettings|DharaMCPConfig|DharaMCPClient|DharaAdapterLearner|DharaMCPAdapterLearner|DharaSOPPersister" \
      --type py /Users/les/Projects/crackerjack/crackerjack/
   ```
   Expected: zero hits.

2. **Zero Dhara references in intact tests**:
   ```bash
   rg -l "DharaMCPSettings|DharaMCPConfig|DharaMCPClient|DharaAdapterLearner|DharaMCPAdapterLearner|DharaSOPPersister|dhara_mcp_client|crackerjack\.integration\.dhara_integration" \
      --type py /Users/les/Projects/crackerjack/tests/
   ```
   Expected: zero hits (only historical CHANGELOG.md / docs/ matches remain).

3. **Tests pass** (the same set that passed before this plan):
   ```bash
   cd /Users/les/Projects/crackerjack && .venv/bin/pytest \
     tests/integration/test_adapter_learning.py \
     tests/unit/core/test_adapter_learning_integration.py \
     tests/unit/test_sop_evolution.py \
     --no-cov -v
   ```
   Expected: all in-scope tests pass. No Dhara-related failures or skips (since the dead tests are now deleted, not skipped).

4. **Type check + refurb**:
   ```bash
   cd /Users/les/Projects/crackerjack && .venv/bin/ty check crackerjack/
   .venv/bin/refurb crackerjack/
   ```
   Expected: All checks passed! / exit 0.

5. **End-to-end smoke test** (the renamed factory still works in mahavishnu):
   ```bash
   cd /Users/les/Projects/mahavishnu && /Users/les/Projects/crackerjack/.venv/bin/python -c "
   from pathlib import Path
   from crackerjack.integration.adapter_learning import (
       AdapterLearningIntegration,
       SQLiteAdapterLearner,
       create_adapter_learner,
   )
   learner = create_adapter_learner(
       enabled=True,
       db_path=Path('.crackerjack/adapter_learning.db'),
       min_attempts=5,
   )
   print(f'{type(learner).__name__} enabled={learner.is_enabled()}')
   "
   ```
   Expected: `SQLiteAdapterLearner enabled=True`. (The renamed module from the prior plan still imports cleanly with the surrounding Dhara code gone.)

6. **Cross-repo blast radius check**:
   ```bash
   rg "from crackerjack.integration.dhara_mcp_client|from crackerjack.config.settings.*DharaMCPSettings|DharaSOPPersister" \
      /Users/les/Projects/mahavishnu /Users/les/Projects/session-buddy \
      /Users/les/Projects/akosha /Users/les/Projects/mcp-common /Users/les/Projects/oneiric
   ```
   Expected: zero hits.

## Precedent

- `docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` — the existing followup already prescribes Phase 1a and the test-file deletions from this plan; we're executing it. Phases 1b-1d extend scope to cover settings and SOP, which the existing followup did not.
- Bodai pre-1.0 policy (`docs/followups/2026-09-14-delete-dhara-mcp-client-after-decomposition.md` § "Risks"): "default to 'no alias' per Bodai pre-1.0 policy" — no deprecation shim, no backward-compat re-export. Hard delete.
- `crackerjack/integration/__init__.py` re-export from the prior rename — already clean (verified by the rename plan's verification step).
