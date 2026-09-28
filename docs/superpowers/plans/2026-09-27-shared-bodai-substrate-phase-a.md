---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-a
---

# Phase A: Cache Consolidation (SB + Akosha) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hand-rolled cache implementations in Session-Buddy and Akosha with `oneiric.adapters.cache.memory.MemoryCacheAdapter`.

**Architecture:** Pure-substitution adoption — both components delete their bespoke cache code and call the existing oneiric adapter directly. No new package, no new settings class. Pre-1.0 replace-not-extend (delete code in the same commit that replaces it).

**Tech Stack:** Python 3.14, oneiric.adapters.cache.memory, pytest, OTel.

**Spec:** `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.1, §6.7 (Phase A1+A2 release-train gates).

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

- **SB cache is hand-rolled**: `session_buddy/cache/query_cache.py:90` defines `class QueryCacheManager` (L1 OrderedDict, max 1024). Runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` at `session_buddy/cache/query_cache.py:139-155` and `session_buddy/adapters/reflection_adapter_oneiric.py:759-778`. `"query_cache_l2"` string at `session_buddy/adapters/reflection_adapter_oneiric.py:2732` (used by `delete_table_names`).
- **Akosha cache is unbounded dict**: `akosha/config.py:241-258` defines `CacheConfig` with `dict` backend; no L1/L2 semantics, no TTL, no eviction.
- **MemoryCacheAdapter exists and is adoption-ready**: `oneiric/adapters/cache/memory.py:29` (`class MemoryCacheAdapter`) provides bounded LRU + TTL + `delete_prefix`. Zero adoption today.

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-A-001
    title: "SB cache delegates entirely to oneiric MemoryCacheAdapter"
  - id: REQ-OSUB-A-002
    title: "SB deletes both runtime CREATE TABLE query_cache_l2 blocks (query_cache.py + reflection_adapter_oneiric.py)"
  - id: REQ-OSUB-A-003
    title: "Akosha CacheConfig delegates to oneiric MemoryCacheAdapter (bounded by default)"
  - id: REQ-OSUB-A-004
    title: "Both components emit cache.adapter.memory OTel spans with size and hit_ratio attributes"
```

## 6. Implementation Tasks

### Task 1: SB QueryCacheManager → MemoryCacheAdapter shim

**Files:**
- Modify: `session_buddy/cache/query_cache.py` (rewrite body of `QueryCacheManager` to delegate)
- Test: `session_buddy/tests/cache/test_memory_adapter.py` (new)

#### Integration Contract ← REQUIRED

- **Triggered from**: First call to `mcp__session-buddy__quick_search` after SB restart.
- **Returns to**: cache writes go to a `MemoryCacheAdapter` instance managed by SB cache module; L2 DuckDB `query_cache_l2` table is no longer created.
- **Demonstrable by**: `grep -rn "query_cache_l2" session_buddy/` returns zero hits after Task 2 lands.
- **Rollback signal**: SB `/health` returns 503 with `feeds.cache_health == degraded`; p99 `quick_search` latency > 50ms.
- **Observability added**: OTel span `cache.adapter.memory.get/set/delete_prefix` with `cache.size` and `cache.hit_ratio` attributes.

- [ ] **Step 1: Write failing test for shim delegation**

```python
# session_buddy/tests/cache/test_memory_adapter.py
from session_buddy.cache import QueryCacheManager
from oneiric.adapters.cache.memory import MemoryCacheAdapter

def test_query_cache_delegates_to_memory_adapter():
    qc = QueryCacheManager(max_size=10)
    qc.set("k", "v")
    assert qc.get("k") == "v"
    assert isinstance(qc._cache, MemoryCacheAdapter)
```

- [ ] **Step 2: Run, expect failure**: `pytest session_buddy/tests/cache/test_memory_adapter.py -v` → FAIL (current QueryCacheManager has OrderedDict backend).

- [ ] **Step 3: Replace `QueryCacheManager` body with delegation** (delete the OrderedDict code; constructor accepts `max_size` + `default_ttl_seconds` and instantiates `MemoryCacheAdapter(...)`).

- [ ] **Step 4: Re-run test, expect pass**.

- [ ] **Step 5: Delete runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` block at `query_cache.py:139-155`**.

- [ ] **Step 6: Commit (atomic — Task 1 lands as one commit)**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/cache/query_cache.py session_buddy/tests/cache/test_memory_adapter.py
git commit -m "feat(session-buddy): adopt MemoryCacheAdapter for query cache"
```

### Task 2: Delete the duplicate runtime `CREATE TABLE` block in `reflection_adapter_oneiric.py`

**Files:**
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py:759-778` (DELETE block)
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py:2732` (DELETE `"query_cache_l2"` string)

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

### Task 3: Akosha CacheConfig delegates to MemoryCacheAdapter

**Files:**
- Modify: `akosha/config.py:241-258`
- Create: `akosha/cache/__init__.py`
- Test: `akosha/tests/cache/test_memory_adapter.py` (new)

#### Integration Contract

- **Triggered from**: First call to `mcp__akosha__search_code_patterns` after Akosha restart.
- **Returns to**: cache writes go to `MemoryCacheAdapter` instance managed by Akosha config.
- **Demonstrable by**: `grep -rn "CacheConfig.*dict\|self.cache: dict" akosha/` returns zero hits; `pytest akosha/tests/cache/test_memory_adapter.py -v` PASS.
- **Rollback signal**: Akosha `/health` returns 503 with `feeds.cache_health == degraded`.
- **Observability added**: OTel span `cache.adapter.memory.get/set/delete_prefix` with `cache.size` and `cache.hit_ratio`.

- [ ] **Step 1: Write failing tests**:

```python
# akosha/tests/cache/test_memory_adapter.py
from akosha.config import CacheConfig
from oneiric.adapters.cache.memory import MemoryCacheAdapter

def test_cache_config_uses_memory_adapter():
    cfg = CacheConfig(max_size=10)
    assert isinstance(cfg.backend, MemoryCacheAdapter)

def test_cache_config_round_trip():
    cfg = CacheConfig(max_size=10)
    cfg.set("k", "v")
    assert cfg.get("k") == "v"
```

- [ ] **Step 2: Run, expect failure** (current `CacheConfig` is dict-based).

- [ ] **Step 3: Replace CacheConfig body** — replace `dict` storage with a private `MemoryCacheAdapter` instance. Public surface stays (`get/set/...`) so callers don't break.

- [ ] **Step 4: Wrap get/set in OTel spans** per Integration Contract Observability row.

- [ ] **Step 5: Run tests, expect pass**.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/akosha
git add akosha/config.py akosha/cache/__init__.py akosha/tests/cache/test_memory_adapter.py
git commit -m "feat(akosha): adopt MemoryCacheAdapter for cache"
```

### Task 4: Cross-component orphan test

**Files:**
- Create: `tests/integration/test_query_cache_l2_orphaned.py` (in `mahavishnu` repo per spec §6.1)

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

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `session_buddy/cache/query_cache.py` | MODIFY: rewrite body of `QueryCacheManager` to delegate | Task 1 |
| `session_buddy/cache/query_cache.py:139-155` | DELETE runtime CREATE TABLE block | Task 1 |
| `session_buddy/adapters/reflection_adapter_oneiric.py:759-778` | DELETE runtime CREATE TABLE block | Task 2 |
| `session_buddy/adapters/reflection_adapter_oneiric.py:2732` | DELETE `"query_cache_l2"` string | Task 2 |
| `session_buddy/cache/__init__.py` | CREATE: re-export MemoryCacheAdapter | Task 1 |
| `session_buddy/tests/cache/test_memory_adapter.py` | CREATE | Task 1 |
| `akosha/config.py:241-258` | MODIFY: CacheConfig delegates | Task 3 |
| `akosha/cache/__init__.py` | CREATE: re-export MemoryCacheAdapter | Task 3 |
| `akosha/tests/cache/test_memory_adapter.py` | CREATE | Task 3 |
| `tests/integration/test_query_cache_l2_orphaned.py` | CREATE | Task 4 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "class QueryCacheManager" session_buddy/ akosha/` | zero hits | exit code 1 |
| `grep -rn "self._l1_cache: OrderedDict" session_buddy/ akosha/` | zero hits | exit code 1 |
| `grep -rn "query_cache_l2" session_buddy/ akosha/` | zero hits | exit code 1 |
| `pytest session_buddy/tests/cache/ akosha/tests/cache/ -v` | all green | pytest exit 0 |
| `pytest tests/integration/test_query_cache_l2_orphaned.py -v` | PASS | pytest exit 0 |
| `python -c "from oneiric.adapters.cache.memory import MemoryCacheAdapter; c = MemoryCacheAdapter(); c.set('k', 'v'); print(c.get('k'))"` | prints `v` | stdout |
| `crackerjack run -v` (on SB and Akosha) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| SB callers depend on L2 semantics (cross-process) that `MemoryCacheAdapter` (in-process) doesn't replicate | Low | L2 table was never actually populated in practice per audit; SB is single-process |
| OTel span cardinality blows up if every get/set emits a span | Medium | Use `tracer.start_as_current_span` (not `start_span`); for hot-path get/set, sample at low rate |
| Akosha bounded cache creates eviction churn | Low | Default `cache__max_entries=10_000` is high; verify with p99 quick_search latency |

## 10. Decision Rule

Phase A is complete when ALL of:

- All 4 tasks land in commits on the working branch.
- `grep -rn "class QueryCacheManager\|query_cache_l2" session_buddy/ akosha/` returns zero hits.
- `pytest session_buddy/tests/cache/ akosha/tests/cache/ tests/integration/test_query_cache_l2_orphaned.py` all pass.
- `crackerjack run -v` green on SB and Akosha.

**Release-train gate**: user pins a oneiric release (no-op, MemoryCacheAdapter already shipped) + user pins new SB + user pins new Akosha. Phase A2 green.

## References

- `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.1 — Phase A contract
- `oneiric/adapters/cache/memory.py:29` — MemoryCacheAdapter
- `.claude/decisions/wire-up-contract.md` — Integration Contract rules
- `.claude/decisions/mcp-backend-wiring-discipline.md` §3 — feed-state observability
