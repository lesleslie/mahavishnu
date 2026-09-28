---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-e1
---

# Phase E1: Settings Substrate + Feed-State Methods — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `OneiricSettings` with a `SubstrateSettings` nested field that resolves `ONEIRIC__SUBSTRATE__*` env vars, and add `get_feed_state()` to every substrate adapter (cache, vector, storage, embedding).

**Architecture:** Pure-additive changes inside oneiric. No new class at top level — `SubstrateSettings` is nested inside `OneiricSettings` (pydantic-settings nested env-prefix already supported because `env_nested_delimiter="__"`). Oneiric layer reads `ONEIRIC__SUBSTRATE__*` env vars above the `_env_overrides` mechanism so per-component overrides via `{PROJECT_NAME}__*` continue to win. Each substrate adapter gains a `get_feed_state() -> FeedState` method that returns `{entities_count, last_updated_timestamp, errors_total, cycles_total}` per `mcp-backend-wiring-discipline.md §3`.

**Tech Stack:** Python 3.14, pydantic-settings, OpenTelemetry, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.5, §6.7 (Phase E1).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** — additive phase, but new code replaces any existing dead `BODAI__*` paths in `OneiricSettings` if they exist.
- **Direct merge to main, no PRs**.
- **No `git push`** for bodai without explicit approval.
- **No version bumps** in any Bodai `pyproject.toml` — user does.
- **No `Co-Authored-By` trailer**.
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md`.
- **MCP backend wiring discipline** per `.claude/decisions/mcp-backend-wiring-discipline.md` §3.

## 1. Outcome

- `OneiricSettings.substrate: SubstrateSettings` resolves from `ONEIRIC__SUBSTRATE__*` env vars.
- Each component's override via `{PROJECT_NAME}__*` (e.g., `MAHAVISHNU__POOL__WORKERS_PER_INSTANCE`) wins over substrate defaults.
- Every substrate adapter exposes `get_feed_state() -> FeedState`.
- `oneiric/docs/substrate.md` documents the resolution order.
- `grep -rn "class SubstrateSettings" .` returns exactly one hit (`oneiric/core/config.py` nested definition).
- `pytest oneiric/tests/test_substrate_settings.py oneiric/tests/test_get_feed_state.py oneiric/tests/test_acl_enforced.py -v` all PASS.

## 2. Goals

1. `SubstrateSettings` nested in `OneiricSettings` with all 30+ fields from spec §5.3.
2. `ONEIRIC__SUBSTRATE__*` env var scan in `_env_overrides` (already supports `{PROJECT}__*`; need to add `ONEIRIC_SUBSTRATE_` as a third tier).
3. `MemoryCacheAdapter.get_feed_state()` returns valid `FeedState`.
4. `PgvectorAdapter.get_feed_state()` returns valid `FeedState`.
5. `HotStore` Protocol gains `get_feed_state`.
6. `EmbeddingBase` gains `get_feed_state`.
7. `oneiric/docs/substrate.md` usage guide authored.

## 3. Non-Goals

- No component-specific adoption (Phase E2).
- No new top-level `SubstrateSettings` class exported via `oneiric.config` API.
- No MCP server `/health` aggregator wiring (Phase E2 consumes these methods).
- No new adapter packages.
- No production R2/S3/GCS policy YAML (deployment-time concern).

## 4. Current Findings

- **`OneiricSettings` exists**: `oneiric/core/config.py:246` (`class OneiricSettings(BaseModel)`).
- **`env_prefix="ONEIRIC_"`** + **`env_nested_delimiter="__"`** already set; `extra="allow"` permits additional fields.
- **`_env_overrides` mechanism**: `oneiric/core/config.py:678-745` honors `{PROJECT_NAME}_*` env vars only. No `ONEIRIC_SUBSTRATE_*` prefix support today.
- **`FeedState` schema defined in spec** §5.6; not yet a shared type.
- **Adapters needing `get_feed_state`**: `MemoryCacheAdapter`, `PgvectorAdapter`, `HotStore` (Protocol), `EmbeddingBase`.
- **No `oneiric/docs/substrate.md`** today.

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-E1-001
    title: "SubstrateSettings nested in OneiricSettings with 30+ fields from spec §5.3"
  - id: REQ-OSUB-E1-002
    title: "ONEIRIC__SUBSTRATE__* env var resolution in _env_overrides layer"
  - id: REQ-OSUB-E1-003
    title: "Per-component override {PROJECT}__* beats substrate defaults"
  - id: REQ-OSUB-E1-004
    title: "MemoryCacheAdapter.get_feed_state returns valid FeedState (4 keys)"
  - id: REQ-OSUB-E1-005
    title: "PgvectorAdapter.get_feed_state returns valid FeedState"
  - id: REQ-OSUB-E1-006
    title: "HotStore Protocol gains get_feed_state method"
  - id: REQ-OSUB-E1-007
    title: "EmbeddingBase gets get_feed_state default implementation"
  - id: REQ-OSUB-E1-008
    title: "oneiric/docs/substrate.md documents resolution order and adapter adoption"
```

## 6. Implementation Tasks

### Task 1: `SubstrateSettings` nested class + `oneiric_settings.substrate` field

**Files:**
- Modify: `oneiric/core/config.py:246` (extend `OneiricSettings`)
- Create: `oneiric/core/substrate_settings.py` (new module containing `SubstrateSettings`)
- Test: `oneiric/tests/test_substrate_settings.py` (new)

#### Integration Contract ← REQUIRED

- **Triggered from**: `load_settings(project_name=...)` call from any component.
- **Returns to**: `oneiric_settings.substrate.*` populated from `ONEIRIC__SUBSTRATE__*` env vars; per-component overrides via `{PROJECT}__*` win.
- **Demonstrable by**: `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5 python -c "from oneiric.core.config import load_settings; s = load_settings(); print(s.substrate.cache__max_entries)"` prints `5`; `pytest oneiric/tests/test_substrate_settings.py -v` PASS.
- **Rollback signal**: any component fails to load settings (`load_settings` raises); `substrate` field missing on returned instance.
- **Observability added**: OTel span `settings.load` with `project_name`, `overrides_applied` count.

- [ ] **Step 1: Write failing test**:

```python
# oneiric/tests/test_substrate_settings.py
import os
import pytest
from oneiric.core.config import load_settings

def test_substrate_field_resolves_from_env(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES", "5")
    s = load_settings(project_name="akosha")
    assert s.substrate.cache__max_entries == 5

def test_per_component_override_beats_substrate(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE", "3")
    monkeypatch.setenv("AKOSHA__POOL__WORKERS_PER_INSTANCE", "7")
    s = load_settings(project_name="akosha")
    assert s.substrate.pool__workers_per_instance == 7

def test_substrate_default_when_no_override(monkeypatch):
    monkeypatch.delenv("ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES", raising=False)
    s = load_settings(project_name="akosha")
    assert s.substrate.cache__max_entries == 10_000  # code default
```

- [ ] **Step 2: Run, expect failure** (currently `substrate` does not exist on `OneiricSettings`).

- [ ] **Step 3: Create `oneiric/core/substrate_settings.py`** with the `SubstrateSettings` class — exactly the field set from spec §5.3 (T0 cache, T1 warm, T2 cold, embedding, pool, retry, circuit_breaker, telemetry, backup, auth).

- [ ] **Step 4: Add `substrate: "SubstrateSettings" = Field(default_factory=lambda: SubstrateSettings())` to `OneiricSettings`**.

- [ ] **Step 5: Extend `_env_overrides` to scan `ONEIRIC_SUBSTRATE_*` env vars** — load as `SubstrateSettings`, overlay onto `oneiric_settings.substrate`. **Resolution order**: `{PROJECT}__*` > `ONEIRIC__SUBSTRATE__*` > code defaults (audit finding B1).

- [ ] **Step 6: Re-run tests, expect pass**.

- [ ] **Step 7: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/core/substrate_settings.py oneiric/core/config.py oneiric/tests/test_substrate_settings.py
git commit -m "feat(oneiric): SubstrateSettings nested in OneiricSettings"
```

### Task 2: `get_feed_state()` on `MemoryCacheAdapter`

**Files:**
- Modify: `oneiric/adapters/cache/memory.py`
- Test: `oneiric/tests/test_get_feed_state.py` (combined for all adapters)

#### Integration Contract

- **Triggered from**: Any component's `/health` aggregator.
- **Returns to**: `FeedState` dict with 4 keys (entities_count, last_updated_timestamp, errors_total, cycles_total).
- **Demonstrable by**: `python -c "from oneiric.adapters.cache.memory import MemoryCacheAdapter; a = MemoryCacheAdapter(); print(a.get_feed_state())"` returns dict with all 4 keys; `pytest oneiric/tests/test_get_feed_state.py -v` PASS.
- **Rollback signal**: `get_feed_state()` raises (e.g., missing counters).
- **Observability added**: per spec §5.6 — counters are themselves observable via OTel.

- [ ] **Step 1: Write failing test**:

```python
from oneiric.adapters.cache.memory import MemoryCacheAdapter
from oneiric.adapters.feed_state import FeedState  # typed dict

def test_memory_cache_feed_state():
    a = MemoryCacheAdapter(name="t", backend="memory")
    a.set("k", "v")
    state = a.get_feed_state()
    assert "entities_count" in state
    assert "last_updated_timestamp" in state
    assert "errors_total" in state
    assert "cycles_total" in state
    assert state["entities_count"] == 1
```

- [ ] **Step 2: Run, expect failure** (`get_feed_state` does not exist on `MemoryCacheAdapter`).

- [ ] **Step 3: Add private counters to `MemoryCacheAdapter`** — `_last_op_ts`, `_ops_count`.

- [ ] **Step 4: Add `get_feed_state()` method** returning the dict per spec §5.6.

- [ ] **Step 5: Re-run test, expect pass**.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/cache/memory.py oneiric/tests/test_get_feed_state.py
git commit -m "feat(oneiric): get_feed_state on MemoryCacheAdapter"
```

### Task 3: `get_feed_state()` on `PgvectorAdapter`

**Files:**
- Modify: `oneiric/adapters/vector/pgvector.py`
- Test: `oneiric/tests/test_get_feed_state.py` (extend combined test file)

- [ ] **Step 1: Write failing test** (mirrors Task 2 for pgvector — counts from `SELECT COUNT(*) FROM <namespace>.reflections`).

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Implement `get_feed_state()`** using a lightweight `SELECT COUNT(*), MAX(updated_at)` against the namespace table.

- [ ] **Step 4: Run tests, expect pass**.

- [ ] **Step 5: Commit**.

### Task 4: `get_feed_state()` on `HotStore` Protocol

**Files:**
- Modify: `oneiric/adapters/vector/hot_store.py:40`

- [ ] **Step 1: Add `get_feed_state()` to the `HotStore` Protocol** (abstract method declaration).

- [ ] **Step 2: Update concrete adapters implementing `HotStore`** (`DuckdbHotStore` etc.) to implement the method.

- [ ] **Step 3: Verify Mahavishnu's `otel_ingester.py:605` still type-checks** (it uses `DuckdbHotStore` in dev mode).

- [ ] **Step 4: Commit**.

### Task 5: `get_feed_state()` on `EmbeddingBase`

**Files:**
- Modify: `oneiric/adapters/embedding/embedding_interface.py:81`

- [ ] **Step 1: Add abstract `get_feed_state()` to `EmbeddingBase`**; concrete adapters (`fastembed.py`, `llama_server.py`, `ollama.py`, `openai.py`) implement it.

- [ ] **Step 2: Counters per adapter** — `_calls_count`, `_last_call_ts`, `_error_count`.

- [ ] **Step 3: Commit**.

### Task 6: `oneiric/docs/substrate.md` usage guide

**Files:**
- Create: `oneiric/docs/substrate.md`

#### Integration Contract

- **Triggered from**: Component authors reading `oneiric/docs/substrate.md` to understand adoption.
- **Returns to**: Resolution order documented; per-component override pattern shown.
- **Demonstrable by**: `cat oneiric/docs/substrate.md` shows resolution diagram, env var convention, adapter adoption checklist.
- **Rollback signal**: N/A (documentation).
- **Observability added**: N/A.

- [ ] **Step 1: Draft the doc** — sections: (1) Overview, (2) Resolution order, (3) `SubstrateSettings` field reference, (4) Adapter adoption checklist, (5) `get_feed_state` per adapter, (6) Cross-component invocation rules.

- [ ] **Step 2: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/docs/substrate.md
git commit -m "docs(oneiric): substrate adoption guide"
```

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `oneiric/core/substrate_settings.py` | CREATE: `SubstrateSettings` | Task 1 |
| `oneiric/core/config.py:246` | MODIFY: extend `OneiricSettings.substrate` | Task 1 |
| `oneiric/core/config.py:678-745` | MODIFY: `_env_overrides` scans `ONEIRIC__SUBSTRATE__*` | Task 1 |
| `oneiric/tests/test_substrate_settings.py` | CREATE | Task 1 |
| `oneiric/adapters/cache/memory.py` | MODIFY: add `get_feed_state` | Task 2 |
| `oneiric/adapters/vector/pgvector.py` | MODIFY: add `get_feed_state` | Task 3 |
| `oneiric/adapters/vector/hot_store.py:40` | MODIFY: Protocol gains `get_feed_state` | Task 4 |
| `oneiric/adapters/embedding/embedding_interface.py:81` | MODIFY: add `get_feed_state` | Task 5 |
| `oneiric/adapters/embedding/{fastembed,llama_server,ollama,openai}.py` | MODIFY: implement concrete `get_feed_state` | Task 5 |
| `oneiric/tests/test_get_feed_state.py` | CREATE | Tasks 2-5 |
| `oneiric/docs/substrate.md` | CREATE | Task 6 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "class SubstrateSettings" .` | exactly 1 hit in `oneiric/core/substrate_settings.py` | shell grep |
| `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5 python -c "from oneiric.core.config import load_settings; s = load_settings(); print(s.substrate.cache__max_entries)"` | prints `5` | stdout |
| `python -c "from oneiric.adapters.vector.pgvector import PgvectorAdapter; print(PgvectorAdapter().get_feed_state())"` | dict with 4 keys (may raise without DB; integration test) | stdout |
| `pytest oneiric/tests/test_substrate_settings.py oneiric/tests/test_get_feed_state.py -v` | all green | pytest exit 0 |
| `pytest oneiric/tests/test_acl_enforced.py -v` (Phase C added) | green | pytest exit 0 |
| `crackerjack run -v` (oneiric) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Resolution order misordered (`{PROJECT}__*` should win) | Medium | Step 5 enforces triple-tier ordering; per-component test (step 1 Task 1) explicitly asserts this |
| `pydantic-settings` nested env-prefix breaks for `__SUBSTRATE__` because env-var names have 3 segments | Low | `env_nested_delimiter="__"` already configured; substrate uses `__` to mean nested field separator |
| Existing `OneiricSettings` consumers break because `substrate` is new | Low | New field is additive; `extra="allow"` already set; existing callers ignore it |
| `get_feed_state` raises on adapters without backing DB | Medium | Wrap in try/except; on failure return stale-but-valid dict so `/health` aggregator can flag degraded but not crash |

## 10. Decision Rule

Phase E1 is complete when ALL of:

- All 6 tasks land as commits.
- `pytest oneiric/tests/test_substrate_settings.py oneiric/tests/test_get_feed_state.py oneiric/tests/test_acl_enforced.py -v` all PASS.
- `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5` correctly resolves via `load_settings(...).substrate`.
- Per-component override (e.g., `AKOSHA__POOL__WORKERS_PER_INSTANCE=7`) wins over substrate default.
- `crackerjack run -v` green on oneiric.

**Release-train gate**: oneiric green + feed-state aggregation tested + `ONEIRIC__SUBSTRATE__*` env var resolution tested.

## References

- `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.5 — Phase E1 contract
- `oneiric/core/config.py:246` — `OneiricSettings` canonical
- `oneiric/core/config.py:678-745` — `_env_overrides` mechanism
- `.claude/decisions/mcp-backend-wiring-discipline.md` §3 — feed-state observability requirements
- `.claude/decisions/wire-up-contract.md` — Integration Contract rules
