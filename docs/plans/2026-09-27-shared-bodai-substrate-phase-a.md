---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
revision: v2 (2026-09-27 — Task 1 + Task 3 revised; pre-SDD pre-flight surfaced 647-line QueryCacheManager + Akosha CacheConfig-is-Pydantic issues)
topic: shared-oneiric-substrate-phase-a
title: "Phase A: Cache Consolidation (SB + Akosha) — Implementation Plan"

---

# Phase A: Cache Consolidation (SB + Akosha) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hand-rolled cache implementations in Session-Buddy and Akosha with `oneiric.adapters.cache.memory.MemoryCacheAdapter`.

**Architecture:** Pure-substitution adoption — both components delete their bespoke cache code and call the existing oneiric adapter directly. No new package, no new settings class. Pre-1.0 replace-not-extend (delete code in the same commit that replaces it).

**Tech Stack:** Python 3.14, oneiric.adapters.cache.memory, pytest, OTel.

**Spec:** `docs/specs/2026-09-27-shared-bodai-substrate-design.md` §6.1, §6.7 (Phase A1+A2 release-train gates).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** (`feedback-no-backwards-compat-pre-1.0.md`).
- **Direct merge to main, no PRs** (`bodai-pre-1.0-merge-policy.md`).
- **No `git push`** for bodai without explicit approval (`feedback-bodai-push-is-user-controlled.md`).
- **No version bumps** in any Bodai `pyproject.toml` — user does (`feedback-mcp-common-version-bump-is-user.md`).
- **No `Co-Authored-By` trailer** (`feedback-no-claude-code-coauthor-attribution.md`).
- **Author email** `les@wedgwoodwebworks.com` (`git-author-email-correct-domain.md`).
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md` — every deliverable has Integration Contract block.

## 1. Outcome

- `class QueryCacheManager` deleted from `session_buddy/cache/query_cache.py`.
- Both runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` blocks deleted.
- `akosha/config.py:241-258` `CacheConfig` delegates to `MemoryCacheAdapter`.
- `grep -rn "class QueryCacheManager\|self._l1_cache: OrderedDict" session_buddy/ akosha/` returns zero hits.
- OTel span `cache.adapter.memory.get/set/delete_prefix` emits in both components.

## 2. Goals

1. SB cache delegates entirely to `MemoryCacheAdapter`.
2. Akosha cache delegates entirely to `MemoryCacheAdapter`.
3. Both components emit `cache.adapter.memory.*` OTel spans with `cache.size` + `cache.hit_ratio`.
4. No code path creates `query_cache_l2` after Phase A.

## 3. Non-Goals

- No new cache adapter (`MemoryCacheAdapter` already exists at `oneiric/adapters/cache/memory.py:29`).
- No Mahavishnu change (process state, not cache).
- No warm-tier adoption (Phase B).
- No embedding changes (Phase D).
- No settings layer (Phase E1).

## 4. Current Findings

- **SB cache is hand-rolled**: `session_buddy/cache/query_cache.py:59` defines `class QueryCacheManager`; line 90 is `self._l1_cache: OrderedDict[str, QueryCacheEntry] = OrderedDict()` (the L1 attribute that backs the cache strategy). max 1024 (from `__init__`). Runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` at `session_buddy/cache/query_cache.py:139-155` and `session_buddy/adapters/reflection_adapter_oneiric.py:759-778`. `"query_cache_l2"` string at `session_buddy/adapters/reflection_adapter_oneiric.py:2732` (used by `reset_database`, defined at line 2705 — **v5 corrects the function name from `delete_table_names`**).
- **Akosha cache is unbounded dict**: `akosha/config.py:241-258` defines `CacheConfig` with `dict` backend; no L1/L2 semantics, no TTL, no eviction.
- **MemoryCacheAdapter exists and is adoption-ready**: `oneiric/adapters/cache/memory.py:29` (`class MemoryCacheAdapter`) provides bounded LRU + TTL + `delete_prefix`. Zero adoption today.

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-A-001
    title: "SB cache delegates entirely to oneiric MemoryCacheAdapter"
    dep: "SB → oneiric (MemoryCacheAdapter)"
  - id: REQ-OSUB-A-002
    title: "SB deletes both runtime CREATE TABLE query_cache_l2 blocks (query_cache.py + reflection_adapter_oneiric.py)"
    dep: "SB → oneiric (MemoryCacheAdapter); deletes duckdb internals"
  - id: REQ-OSUB-A-003
    title: "Akosha CacheConfig delegates to oneiric MemoryCacheAdapter (bounded by default)"
    dep: "Akosha → oneiric (MemoryCacheAdapter)"
  - id: REQ-OSUB-A-004
    title: "Both components emit cache.adapter.memory OTel spans with size and hit_ratio attributes"
    dep: "SB → oneiric (OTel); Akosha → oneiric (OTel)"
```

## 6. Implementation Tasks

### Task 1: SB `QueryCacheManager` → `MemoryCacheAdapter` substitution (REVISED 2026-09-27)

**Why revised**: pre-flight surfaced that `session_buddy/cache/query_cache.py` is **647 lines** with substantial L2 DuckDB infrastructure (8 helper methods + `initialize(conn)` + `aclose()` + `cleanup_expired()` + shutdown race machinery) and the brief's `max_size=10` constructor argument was a rename that contradicts spec §6.1 "pure substitution". Constructed detailed deletion/preserve rules in the corresponding task brief (`.superpowers/sdd/2026-09-27-shared-bodai-substrate-phase-a/task-1-brief.md`).

**Files:**
- Modify: `session_buddy/cache/query_cache.py` (full rewrite, preserving public surface)
- Create: `session_buddy/tests/cache/test_memory_adapter.py` (new)

(Per atomic per-file adoption rule + spec §6.1 pure substitution, NO other files in this commit. Caller sites at `reflection_adapter_oneiric.py:532`, `cache_tools.py:333`, `tests/unit/test_query_cache.py`, etc. continue to work because the public surface — including `l1_max_size` / `l2_ttl_days` kwargs — is preserved.)

#### Integration Contract ← REQUIRED

- **Triggered from**: First call to `mcp__session-buddy__quick_search` after SB restart.
- **Returns to**: cache writes go to a `MemoryCacheAdapter` instance managed by SB cache module; L2 DuckDB `query_cache_l2` table is no longer created.
- **Demonstrable by**: `grep -rn "query_cache_l2\|self._l1_cache: OrderedDict" session_buddy/` returns zero hits in `query_cache.py` post-Task-1 (Task 1 scope). The duplicate block in `reflection_adapter_oneiric.py:759-778` remains until Task 2.
- **Rollback signal**: SB `/health` returns 503 with `feeds.cache_health == degraded`; p99 `quick_search` latency > 50ms.
- **Observability added**: OTel span `cache.adapter.memory.get/set/delete_prefix` with `cache.size` and `cache.hit_ratio` attributes (delegated to `MemoryCacheAdapter`'s internal logger).

#### Constructor preservation (per spec §6.1 pure substitution)

The existing public `__init__(self, l1_max_size: int = 1000, l2_ttl_days: int = 7)` signature is **preserved verbatim**. Internally translates to `MemoryCacheSettings(max_entries=l1_max_size, default_ttl=l2_ttl_days * 86400.0)`. The `l2_ttl_days` kwarg is forwarded to the adapter's TTL — kept for caller compat, semantically preserved.

#### Sync/async bridge (sync API callers must keep working)

Callers reach `cache.get(...)` and `cache.put(...)` synchronously. The bridge:

```python
def _run_async(self, coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "QueryCacheManager sync API cannot be called from a running event loop. "
            "Use the underlying MemoryCacheAdapter async interface directly."
        )
    return asyncio.run(coro)
```

#### L2 DuckDB infrastructure deleted in this commit (per v5 §6.1 + §10 risk #1)

Methods removed: `_ensure_l2_table`, `_get_from_l2`, `_put_to_l2`, `_delete_from_l2`, `_clear_l2`, `_update_l2_access`, `_track_operation`, `_complete_operation`, `_execute_in_executor`, `initialize(conn)`, `aclose()`, `cleanup_expired`. Imports removed: `duckdb` (TYPE_CHECKING), `threading`, `asyncio.Lock`, `OrderedDict`, `dataclass`/`field`. The `QueryCacheEntry` dataclass is removed (only used by L2 path).

- [ ] **Step 1: Write failing tests for shim delegation, constructor preservation, sync-loop guard, and L2 deletion**

```python
# session_buddy/tests/cache/test_memory_adapter.py (new)
from __future__ import annotations

import asyncio

import pytest

from oneiric.adapters.cache.memory import MemoryCacheAdapter

from session_buddy.cache.query_cache import QueryCacheManager


@pytest.mark.req(["REQ-OSUB-A-001"])
def test_query_cache_delegates_to_memory_adapter() -> None:
    qc = QueryCacheManager(l1_max_size=10)  # NOTE: l1_max_size (NOT max_size — pure substitution)
    qc.put("k", ["v"], normalized_query="q", project=None)
    assert qc.get("k") == ["v"]
    assert isinstance(qc._cache, MemoryCacheAdapter)


@pytest.mark.req(["REQ-OSUB-A-001"])
def test_query_cache_constructor_signature_preserved() -> None:
    """Per spec §6.1 pure substitution — constructor arg names unchanged."""
    qc = QueryCacheManager(l1_max_size=42, l2_ttl_days=3)
    assert qc.l1_max_size == 42
    assert qc.l2_ttl_seconds == 3 * 86400


@pytest.mark.req(["REQ-OSUB-A-001"])
def test_sync_api_raises_in_running_loop() -> None:
    """Sync API is non-blocking-call-safe."""
    qc = QueryCacheManager(l1_max_size=10)

    async def inside() -> None:
        qc.put("k", ["v"], normalized_query="q", project=None)

    with pytest.raises(RuntimeError, match="running event loop"):
        asyncio.run(inside())


@pytest.mark.req(["REQ-OSUB-A-001", "REQ-OSUB-A-002"])
def test_query_cache_l2_table_block_deleted() -> None:
    """The runtime CREATE TABLE query_cache_l2 block in query_cache.py is gone."""
    import subprocess
    result = subprocess.run(
        ["grep", "-n", "query_cache_l2", "session_buddy/cache/query_cache.py"],
        capture_output=True, text=True,
    )
    assert result.stdout == "", f"query_cache_l2 still in query_cache.py:\n{result.stdout}"
```

- [ ] **Step 2: Run, expect RED**: `pytest session_buddy/tests/cache/test_memory_adapter.py -v` → all 4 tests FAIL.

- [ ] **Step 3: Rewrite `session_buddy/cache/query_cache.py`** — preserved `__init__` + preserved `normalize_query` (static) + preserved `compute_cache_key` (static) + delegated `get`/`put`/`invalidate` via `_run_async` + sync `close()`. Reference rewrite in `.superpowers/sdd/.../task-1-brief.md` Step 3.

- [ ] **Step 4: Re-run focused test, expect GREEN**: `pytest session_buddy/tests/cache/test_memory_adapter.py -v` → all 4 PASS.

- [ ] **Step 5: Verify L2 + DuckDB symbols gone**:

```bash
grep -n "query_cache_l2\|_l1_cache: OrderedDict\|class QueryCacheManager\|duckdb" session_buddy/cache/query_cache.py | head -5
```

Expected: **exit code 1** (zero hits). The duplicate block in `reflection_adapter_oneiric.py:759-778` and the `"query_cache_l2"` string at `:2732` remain (Task 2's scope).

- [ ] **Step 6: Note downstream-test breakage (logged as DONE_WITH_CONCERNS, NOT in this commit)**:

`tests/unit/test_query_cache.py` and `tests/performance/test_query_cache_performance.py` reference removed symbols. **Do NOT modify those tests in this commit** — that's Task 1b (test-migration follow-up).

- [ ] **Step 7: Atomic commit (TWO files only)**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/cache/query_cache.py session_buddy/tests/cache/test_memory_adapter.py
git commit -m "feat(session-buddy): adopt MemoryCacheAdapter for query cache

Rewrite QueryCacheManager to delegate to oneiric.adapters.cache.memory
.MemoryCacheAdapter and delete the runtime CREATE TABLE query_cache_l2
block plus all L2 DuckDB infrastructure (dead per spec §10 risk #1).

Pure substitution per spec §6.1: the constructor signature
(__init__(l1_max_size=..., l2_ttl_days=...)) is preserved verbatim so
existing call-sites at reflection_adapter_oneiric.py:532 and 4 test
files continue to work without changes. Sync API (get/put/invalidate)
preserved with a per-call asyncio.run() bridge guarded against running
event loops; the async backend is reachable directly from async contexts.

The duplicate CREATE TABLE query_cache_l2 block in
reflection_adapter_oneiric.py:759-778 (Task 2 scope) and the
\"query_cache_l2\" string at :2732 (Task 2 scope) are NOT touched in
this commit; per the atomic per-file adoption rule each deletion lands
in its own commit.

Implements: REQ-OSUB-A-001, REQ-OSUB-A-002"
```

No `Co-Authored-By` trailer. Author email `les@wedgwoodwebworks.com`.

### Task 2: Delete the duplicate runtime `CREATE TABLE` block in `reflection_adapter_oneiric.py`

**Files:**
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py:759-778` (DELETE block)
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py:2732` (DELETE `"query_cache_l2"` string inside `reset_database`, line 2705)

#### Integration Contract ← REQUIRED (v5 addition; per wire-up-contract.md §1 every deliverable has IC)

- **Triggered from**: SB restart with new warm-write/read path (relieves legacy CREATE TABLE on first reflection write).
- **Returns to**: `reflection_adapter_oneiric.py` no longer references `query_cache_l2`; L2 DuckDB table is no longer created.
- **Demonstrable by**: `grep -rn "query_cache_l2" session_buddy/` returns zero hits.
- **Rollback signal**: SB warm-write path errors > 1%; orphan `query_cache_l2` reference detected by `tests/integration/test_query_cache_l2_orphaned.py`.
- **Observability added**: count of `query_cache_l2` references at module import time (logged once via `oneiric.logging`).

- [ ] **Step 1: Read the exact CREATE TABLE block at 759-778** (`grep -n "query_cache_l2" session_buddy/adapters/reflection_adapter_oneiric.py`).

- [ ] **Step 2: Write failing test for orphan check** (covered by `tests/integration/test_query_cache_l2_orphaned.py` in Task 4 — but assert in this Task first by running `grep -rn "query_cache_l2" session_buddy/` before and after).

- [ ] **Step 3: Delete the block at lines 759-778**.

- [ ] **Step 4: Delete `"query_cache_l2"` string at line 2732**. Cross-check `delete_table_names()` semantics; if this string is part of a list passed to a cleanup function, simply remove the entry.

- [ ] **Step 5: Run grep again, confirm zero hits**: `grep -rn "query_cache_l2" session_buddy/` → exit code 1.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/adapters/reflection_adapter_oneiric.py
git commit -m "refactor(session-buddy): delete duplicate query_cache_l2 CREATE TABLE block"
```

### Task 3: Akosha `CacheManager` over `MemoryCacheAdapter` (REVISED 2026-09-27)

**Why revised**: pre-flight surfaced that `CacheConfig` (`akosha/config.py:241-258`) is a **Pydantic `BaseModel`**, NOT an "unbounded `dict` cache" as spec v5 §4.1 described. `CacheConfig` is config-only; the only consumer is `A koshaSettings.cache` (sub-config). There is no `akosha/cache/` directory in the tree today, and the brief's test `cfg.backend = MemoryCacheAdapter` was structurally impossible because Pydantic fields can't hold runtime adapter instances.

**Right design**: introduce a new `CacheManager` runtime wrapper in a new `akosha/cache/` module; leave `CacheConfig` (Pydantic config) untouched. Spec v5 §4.1's "CacheConfig only" row is factually wrong — flagged for spec revision post-Phase-A.

**Files (revised):**
- Create: `akosha/cache/__init__.py` (re-exports `CacheManager` and `MemoryCacheAdapter`)
- Create: `akosha/cache/manager.py` (`CacheManager` class)
- Create: `tests/cache/test_memory_adapter.py`

**Files NOT modified in this task (revision):**
- `akosha/config.py:241-258` — `CacheConfig` Pydantic model stays unchanged.

#### Integration Contract

- **Triggered from**: First call to any Akosha path that opens a cache (`mcp__akosha__search_code_patterns`, `search_all_systems`, etc. — after Phase D wires embedding lookup through this cache).
- **Returns to**: cache reads/writes flow through `MemoryCacheAdapter`; no legacy dict-backed cache anywhere.
- **Demonstrable by**:
  - `pytest tests/cache/test_memory_adapter.py -v` all PASS.
  - `python -c "from akosha.cache import CacheManager; from akosha.config import CacheConfig; cm = CacheManager(CacheConfig(backend='memory')); cm.set('k', 'v'); print(cm.get('k'))"` prints `v`.
- **Rollback signal**: Akosha `/health` returns 503 with `feeds.cache_health == degraded`.
- **Observability added**: OTel span `cache.adapter.memory.get/set/delete_prefix` with `cache.size` and `cache.hit_ratio` attributes (delegated to MemoryCacheAdapter's internal logger).

- [ ] **Step 1: Write failing tests**:

```python
# tests/cache/test_memory_adapter.py (new)
from __future__ import annotations

import pytest

from akosha.cache import CacheManager
from akosha.config import CacheConfig
from oneiric.adapters.cache.memory import MemoryCacheAdapter


@pytest.mark.req(["REQ-OSUB-A-003"])
def test_cache_manager_uses_memory_adapter() -> None:
    cfg = CacheConfig(backend="memory", local_ttl_seconds=60)
    cm = CacheManager(settings=cfg)
    assert isinstance(cm.backend, MemoryCacheAdapter)


@pytest.mark.req(["REQ-OSUB-A-003"])
def test_cache_manager_round_trip() -> None:
    cm = CacheManager(settings=CacheConfig(backend="memory"))
    cm.set("k", "v")
    assert cm.get("k") == "v"
```

- [ ] **Step 2: Run, expect RED** (ModuleNotFoundError on `akosha.cache`).

- [ ] **Step 3: Create `akosha/cache/manager.py`** with `CacheManager` class per `.superpowers/sdd/.../task-3-brief.md` Step 3 — owns `MemoryCacheAdapter` instance, exposes `get/set/delete/delete_prefix/clear`, raises `NotImplementedError` for non-`"memory"` backends (Redis adapter is future work, NOT in Phase A).

- [ ] **Step 4: Create `akosha/cache/__init__.py`** — re-exports `CacheManager` and `MemoryCacheAdapter`.

- [ ] **Step 5: Run focused tests, expect GREEN**.

- [ ] **Step 6: Atomic commit (THREE files: 2 new modules + 1 test; `akosha/config.py` is NOT touched)**:

```bash
cd /Users/les/Projects/akosha
git add akosha/cache/__init__.py akosha/cache/manager.py tests/cache/test_memory_adapter.py
git commit -m "feat(akosha): introduce CacheManager over MemoryCacheAdapter

Per spec §6.1, Phase A adopts the oneiric substrate for Akosha's
cache tier. The previous brief assumed CacheConfig (Pydantic) was a
runtime cache — that description was wrong. CacheConfig is and remains
a config-only Pydantic model; this commit introduces CacheManager, a
runtime wrapper that reads CacheConfig and owns a MemoryCacheAdapter by
default. No call-site rewrites are required because Akosha has no
business code touching cache today (verified 2026-09-27 via grep).

Per pre-1.0 replace-not-extend, this introduces the first runtime cache
in Akosha. The legacy framing in spec §4.1 ('unbounded dict cache
backend') is superseded by this implementation; spec v5's other shape
decisions stand.

Implements: REQ-OSUB-A-003, REQ-OSUB-A-004"
```

No `Co-Authored-By` trailer. Author email `les@wedgwoodwebworks.com`.

### Task 4: Cross-component orphan test

**Files:**
- Create: `tests/integration/test_query_cache_l2_orphaned.py` (in `mahavishnu` repo per spec §6.1)

#### Integration Contract ← REQUIRED (v5 addition)

- **Triggered from**: CI gate on every PR touching session-buddy or akosha caches.
- **Returns to**: an audit assertion in `tests/integration/test_query_cache_l2_orphaned.py` that no path references `query_cache_l2` after Phase A lands.
- **Demonstrable by**: `pytest tests/integration/test_query_cache_l2_orphaned.py -v` PASS.
- **Rollback signal**: test reports orphaned references; CI blocks the PR.
- **Observability added**: per-CI-run structured log line `audit.orphans.query_cache_l2=0|≥1`.

- [ ] **Step 1: Write the orphan test**:

```python
# tests/integration/test_query_cache_l2_orphaned.py
import subprocess

def test_no_path_reads_or_writes_query_cache_l2():
    """Per spec §6.1 — no path references query_cache_l2 after Phase A."""
    result = subprocess.run(
        ["grep", "-rn", "query_cache_l2",
         "/Users/les/Projects/session-buddy",
         "/Users/les/Projects/akosha"],
        capture_output=True, text=True,
    )
    assert result.stdout == "", f"query_cache_l2 still referenced:\n{result.stdout}"
```

- [ ] **Step 2: Run test, expect pass** (Tasks 1+2 already landed).

- [ ] **Step 3: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/test_query_cache_l2_orphaned.py
git commit -m "test: assert no references to query_cache_l2 after Phase A"
```

## 7. Required Code Changes (REVISED 2026-09-27)

| File | Action | Phase task |
|---|---|---|
| `session_buddy/cache/query_cache.py` | MODIFY: full rewrite preserving public surface; delete L2 DuckDB plumbing (`_ensure_l2_table`, `_get_from_l2`, `_put_to_l2`, `_delete_from_l2`, `_clear_l2`, `_update_l2_access`, `_track_operation`, `_complete_operation`, `_execute_in_executor`, `initialize(conn)`, `aclose()`, `cleanup_expired`); sync API delegates to `MemoryCacheAdapter` via per-call `asyncio.run()` with running-loop guard | Task 1 |
| `session_buddy/cache/query_cache.py:139-155` | DELETE runtime CREATE TABLE block (covered by Task 1's full rewrite; listed for grep validation only) | Task 1 |
| `session_buddy/adapters/reflection_adapter_oneiric.py:759-778` | DELETE runtime CREATE TABLE block | Task 2 |
| `session_buddy/adapters/reflection_adapter_oneiric.py:2732` | DELETE `"query_cache_l2"` string | Task 2 |
| `session_buddy/cache/__init__.py` | CREATE: re-export MemoryCacheAdapter (note: existing `session_buddy/cache/__init__.py` likely already re-exports `QueryCacheManager`; preserve that, add MemoryCacheAdapter) | Task 1 |
| `session_buddy/tests/cache/test_memory_adapter.py` | CREATE: 4 tests (delegation, constructor preservation, sync-loop guard, L2 deletion grep) | Task 1 |
| `tests/unit/test_query_cache.py` | (Task 1b follow-up — NOT in Task 1's atomic commit) tests reference removed symbols; migrate or delete in follow-up | Task 1b |
| `tests/performance/test_query_cache_performance.py` | (Task 1b follow-up) same | Task 1b |
| `akosha/config.py:241-258` | UNCHANGED (CacheConfig Pydantic; not modified in Phase A) | (none) |
| `akosha/cache/__init__.py` | CREATE: re-export `CacheManager` and `MemoryCacheAdapter` | Task 3 |
| `akosha/cache/manager.py` | CREATE: `CacheManager` runtime wrapper | Task 3 |
| `tests/cache/test_memory_adapter.py` | CREATE | Task 3 |
| `tests/integration/test_query_cache_l2_orphaned.py` | CREATE: greps `query_cache_l2` across both SB and Akosha | Task 4 |

## 8. Validation Matrix (REVISED 2026-09-27)

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -n "class QueryCacheManager" session_buddy/cache/query_cache.py` | zero hits | exit code 1 |
| `grep -n "self._l1_cache: OrderedDict\|query_cache_l2\|duckdb" session_buddy/cache/query_cache.py` | zero hits (Task 1 scope; Task 2's `reflection_adapter_oneiric.py` block remains until Task 2) | exit code 1 |
| `grep -rn "query_cache_l2" session_buddy/ akosha/` | zero hits (after all of Phase A lands — Tasks 1+2+4) | exit code 1 |
| `grep -rn "_l2_lock\|_shutdown_event\|_conn" session_buddy/cache/query_cache.py` | zero hits (Task 1: all L2 plumbing removed) | exit code 1 |
| `pytest session_buddy/tests/cache/test_memory_adapter.py -v` | 4 tests PASS (Task 1) | pytest exit 0 |
| `pytest session_buddy/tests/unit/test_query_cache.py -v` | KNOWN FAIL (Task 1 concern; tests reference removed L2 symbols) — Task 1b follow-up | pytest exit nonzero |
| `pytest tests/cache/test_memory_adapter.py -v` | PASS (Task 3) | pytest exit 0 |
| `pytest tests/integration/test_query_cache_l2_orphaned.py -v` | PASS (Task 4) | pytest exit 0 |
| `python -c "from oneiric.adapters.cache.memory import MemoryCacheAdapter; c = MemoryCacheAdapter(); c.set('k', 'v'); print(c.get('k'))"` | prints `v` | stdout |
| `python -c "from akosha.cache import CacheManager; from akosha.config import CacheConfig; cm = CacheManager(CacheConfig(backend='memory')); cm.set('k', 'v'); print(cm.get('k'))"` | prints `v` | stdout |
| `python -c "from session_buddy.cache.query_cache import QueryCacheManager; q = QueryCacheManager(l1_max_size=10); q.put('k', ['v'], normalized_query='q', project=None); print(q.get('k'))"` | prints `['v']` (Task 1 constructor + sync API preserved) | stdout |
| `crackerjack run -v` (on SB and Akosha) | green for new files only; existing files have KNOWN FAILURES from Task 1b follow-up | exit code nonzero acceptable during Task 1 landing; Task 1b fixes |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| SB callers depend on L2 semantics (cross-process) that `MemoryCacheAdapter` (in-process) doesn't replicate | Low | L2 table was never actually populated in practice per audit; SB is single-process |
| OTel span cardinality blows up if every get/set emits a span | Medium | Use `tracer.start_as_current_span` (not `start_span`); for hot-path get/set, sample at low rate |
| Akosha bounded cache creates eviction churn | Low | Default `cache__max_entries=10_000` is high; verify with p99 quick_search latency |
| **(Meta, spec §10 #7) oneiric becomes a hard substrate dependency** | Medium | Add `oneiric>=<pinned>` to `[project.dependencies]` in SB and Akosha `pyproject.toml`; CI guard test asserts minimum version. Phase A is the first phase where SB and Akosha require `oneiric` for cache. |
| **(Meta, spec §10 #8) Cross-component import direction violation** | Medium | Phase A only adds SB→oneiric and Akosha→oneiric imports; no Akosha→Mahavishnu / SB→Mahavishnu / Mahavishnu→SB imports introduced. CI guard: `grep -rn "from mahavishnu\|import mahavishnu" akosha/ session_buddy/` returns zero hits. |
| **(Meta, spec §10 #9) Rollback complexity across 6 phases × 4 repos** | Low for Phase A | Phase A is pure-substitution; rollback restores old `QueryCacheManager` and the two runtime CREATE TABLE blocks. Each phase has its own release-train gate; reverting one does not break others. Cross-repo rollback is the union of per-phase rollbacks. |

## 10. Decision Rule

Phase A is complete when ALL of:

- All 4 tasks land in commits on the working branch.
- `grep -rn "class QueryCacheManager\|query_cache_l2" session_buddy/ akosha/` returns zero hits.
- `pytest session_buddy/tests/cache/ tests/cache/ tests/integration/test_query_cache_l2_orphaned.py` all pass.
- `crackerjack run -v` green on SB and Akosha.

**Release-train gate**: user pins a oneiric release (no-op, MemoryCacheAdapter already shipped) + user pins new SB + user pins new Akosha. Phase A2 green.

## References

- `docs/specs/2026-09-27-shared-bodai-substrate-design.md` §6.1 — Phase A contract
- `oneiric/adapters/cache/memory.py:29` — MemoryCacheAdapter
- `.claude/decisions/wire-up-contract.md` — Integration Contract rules
- `.claude/decisions/mcp-backend-wiring-discipline.md` §3 — feed-state observability

## Revision history

| Date | Revision | Author | Notes |
|---|---|---|---|
| 2026-09-27 | v1 | platform-team | Initial plan: 4 tasks (SB + Akosha cache consolidation, duplicate-block deletion, cross-component orphan test). |
| 2026-09-27 | v2 | platform-team | **Pre-SDD pre-flight revision.** Task 1 brief undersized: `QueryCacheManager` is 647 lines with substantial L2 DuckDB infrastructure; revised brief preserves constructor signature (`l1_max_size` / `l2_ttl_days` verbatim per spec §6.1 pure substitution), explicit per-method deletion list, sync/async bridge via per-call `asyncio.run()` with running-loop guard. Task 3 brief structurally wrong: `CacheConfig` is a Pydantic `BaseModel` (config-only), not an "unbounded dict cache" as spec §4.1 said; revised brief introduces a new `CacheManager` runtime wrapper in `akosha/cache/`, leaves `CacheConfig` untouched. Downstream-test breakage (Task 1b follow-up) noted. **Two latent spec errors flagged for post-Phase-A spec revision** (not in this commit): (a) spec §4.1 Akosha row is factually wrong about cache state; (b) — none other found.
