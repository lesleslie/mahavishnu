---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-e2
---

# Phase E2: Per-Component Adoption of Settings Substrate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Each component (Akosha, SB, Mahavishnu) reads pool / telemetry / retry / auth settings from `OneiricSettings.substrate` instead of its own local keys. Auth short-circuit preserved per `feedback-bodai-localhost-no-auth.md`.

**Architecture:** **Atomic per-file** adoption (audit finding M3). For each component file, "delete local config field + adopt `OneiricSettings.substrate` reference" lands in the SAME commit. Partial migration during E2 rollout is forbidden — a file cannot read from `OneiricSettings.substrate.pool__workers_per_instance` while still defining its own `MAHAVISHNU_RETRY__MAX_ATTEMPTS`. `/health` endpoints aggregate adapter `get_feed_state()` calls per `mcp-backend-wiring-discipline.md §3`.

**Tech Stack:** Python 3.14, pydantic-settings, OpenTelemetry.

**Spec:** `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.6, §6.7 (Phase E2).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** — each component's local config field deleted in same commit that adopts substrate.
- **Atomic per-file adoption rule** (spec §6.6): partial migration during rollout window is forbidden.
- **Direct merge to main, no PRs**.
- **No `git push`** for bodai without explicit approval.
- **No version bumps** — user does.
- **No `Co-Authored-By` trailer**.
- **Author email** `les@wedgwoodwebworks.com`.
- **Auth short-circuit preserved** across substrate adoption. `auth.enabled: false` on any consumer MUST continue to short-circuit both middleware AND decorator gates per `feedback-bodai-localhost-no-auth.md`. Phase E2 explicitly carries `auth__enabled` and `auth__loopback_trusted` through `OneiricSettings.substrate`.
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md`.
- **MCP backend wiring discipline** per `.claude/decisions/mcp-backend-wiring-discipline.md`.

## 1. Outcome

- Each component's settings module reads substrate fields, not local keys.
- `auth__enabled` and `auth__loopback_trusted` flow through substrate (Phase E1 + E2 both).
- `grep -rn "auth.enabled" akosha/config.py session_buddy/config.py mahavishnu/core/config.py` shows references to `OneiricSettings.substrate.auth__enabled`.
- Component `/health` endpoints return `feeds.{cache, warm, cold, embedding}_state` aggregated per `mcp-backend-wiring-discipline.md §3`.
- `pytest tests/integration/test_auth_short_circuit_preserved.py` PASS.
- `pytest tests/integration/test_health_feed_state_aggregated.py` PASS.

## 2. Goals

1. `akosha/config.py` adopts substrate for cache/warm/cold/embedding/pool/retry/auth settings.
2. `session_buddy/settings.py` adopts substrate (same fields, plus `session_buddy`-specific extensions that don't conflict).
3. `mahavishnu/core/config.py` adopts substrate for pool/telemetry/retry/auth (no warm/cold/embedding change for Mahavishnu per spec §5.5).
4. All three components expose `/health` with aggregated feed state.
5. Auth short-circuit (`auth__enabled=False`) verified across middleware AND decorator gates.

## 3. Non-Goals

- No new settings surface — uses existing `OneiricSettings.substrate` from Phase E1.
- No Mahavishnu warm/cold/embedding changes (out of scope per spec §5.5).
- No new env vars introduced (Phase E1 already added `ONEIRIC__SUBSTRATE__*`).
- No breaking changes to existing settings consumers (C-NEW-5: components' public settings classes stay; internals delegate).

## 4. Current Findings

- **Akosha `CacheConfig`** at `akosha/config.py:241-258` (already adopted Phase A — wraps MemoryCacheAdapter). Need to confirm `auth__enabled` reference now reads from substrate.
- **`akosha/config.py:71-78`** — `HotStorageConfig` migration note from 2026-09-27.
- **SB settings** at `session_buddy/settings.py` (referenced via `get_settings()`); per spec §13, `auth__enabled` reference required.
- **Mahavishnu config** at `mahavishnu/core/config.py` extends `MCPServerSettings` from mcp-common (per project CLAUDE.md). Pool/telemetry/retry are local; auth short-circuit per `feedback-bodai-localhost-no-auth.md`.
- **`oneiric_substrate` shared Postgres DB** (per Phase B) configured via `SubstrateSettings.warm__pg_url`.

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-E2-001
    title: "akosha/config.py reads cache__max_entries, warm__*, cold__*, embedding__*, pool__*, retry__*, auth__* via OneiricSettings.substrate"
    dep: "Akosha → oneiric (OneiricSettings.substrate)"
  - id: REQ-OSUB-E2-002
    title: "session_buddy/settings.py reads substrate fields; deletes redundant local keys atomically"
    dep: "SB → oneiric (OneiricSettings.substrate)"
  - id: REQ-OSUB-E2-003
    title: "mahavishnu/core/config.py reads pool__*, telemetry__*, retry__*, auth__* via OneiricSettings.substrate"
    dep: "Mahavishnu → oneiric (OneiricSettings.substrate)"
  - id: REQ-OSUB-E2-004
    title: "auth__enabled=False short-circuits BOTH middleware AND decorator gates (preserved behavior); auth__loopback_trusted=True permits localhost unauth'd"
    dep: "Each component middleware → oneiric.auth__enabled/loopback_trusted"
  - id: REQ-OSUB-E2-005
    title: "/health endpoint returns feeds.{cache, warm, cold, embedding}_state with all 4 FeedState keys; returns 503 when any feed is stale (>5×poll)"
    dep: "Component /health → oneiric (adapters' get_feed_state)"
```

## 6. Implementation Tasks

### Task 1: Akosha atomic config migration

**Files:**
- Modify: `akosha/config.py` (atomic: delete local keys + adopt `OneiricSettings.substrate` references in single commit)
- Test: `akosha/tests/test_substrate_settings_via_oneiric.py` (new)

#### Integration Contract ← REQUIRED

- **Triggered from**: Akosha process restart with new settings loader.
- **Returns to**: `akosha.config.<field>` reads from `OneiricSettings.substrate.<field>` via a thin property layer. Local keys deleted.
- **Demonstrable by**: `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=42 python -c "from akosha.config import load_settings; s = load_settings(); print(s.substrate.cache__max_entries)"` prints `42` (v5 correction — substrate field uses **double** underscore per spec §5.3 nested prefix, not single underscore); `pytest akosha/tests/test_substrate_settings_via_oneiric.py -v` PASS.
- **Rollback signal**: Akosha fails to start with new settings loader; `auth__enabled` not propagated.
- **Observability added**: OTel span `settings.substrate.access` with `component="akosha"`, `field`.

- [ ] **Step 1: Write failing test**:

```python
# akosha/tests/test_substrate_settings_via_oneiric.py
import os
import pytest
from akosha.config import settings  # public surface

def test_akosha_settings_pick_up_substrate_default(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES", "42")
    s = settings()  # reload function
    assert s.substrate.cache__max_entries == 42

def test_akosha_pool_workers_via_substrate(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE", "5")
    s = settings()
    assert s.substrate.pool__workers_per_instance == 5
```

- [ ] **Step 2: Run, expect failure** — current `akosha.config` reads local keys.

- [ ] **Step 3: Audit current `akosha/config.py` to find ALL local settings fields that map to substrate**. Cross-reference spec §5.3 fields.

- [ ] **Step 4: Rewrite `akosha/config.py`** — single commit **atomically**:
  - DELETE local fields that have a substrate equivalent (note substrate double-underscore per spec §5.3: `cache__max_entries`, `pool__workers_per_instance`, `retry__max_attempts`, `auth__enabled`, `auth__loopback_trusted`, etc.).
  - KEEP any truly Akosha-specific fields (`akosha_url`, MCP server port, etc.) unchanged.
  - Refactor getter functions/properties to read from `OneiricSettings.substrate.<field>`.

- [ ] **Step 5: Update all call sites within akosha** to use the new property names (or keep property name compat layer if extensive renaming would explode the diff).

- [ ] **Step 6: Re-run failing tests, expect pass**.

- [ ] **Step 7: Run full Akosha suite** (`pytest akosha/tests/`); fix any regressions.

- [ ] **Step 8: Commit**:

```bash
cd /Users/les/Projects/akosha
git add akosha/config.py akosha/tests/test_substrate_settings_via_oneiric.py
git commit -m "refactor(akosha): adopt OneiricSettings.substrate for cross-component settings"
```

### Task 2: SB atomic config migration

**Files:**
- Modify: `session_buddy/settings.py`
- Test: `session_buddy/tests/test_substrate_settings_via_oneiric.py` (new)

#### Integration Contract

- **Triggered from**: SB process restart with new settings loader.
- **Returns to**: `session_buddy.settings.get_settings()` returns `OneiricSettings` with substrate populated.
- **Demonstrable by**: `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=99 python -c "from session_buddy.settings import get_settings; print(get_settings().substrate.cache__max_entries)"` prints `99`; `pytest session_buddy/tests/test_substrate_settings_via_oneiric.py -v` PASS.
- **Rollback signal**: SB fails to start; `auth__enabled` not propagated.
- **Observability added**: OTel span `settings.substrate.access` with `component="session-buddy"`, `field`.

- [ ] **Step 1: Write failing test** (mirrors Task 1 patterns for SB).

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Atomic rewrite of `session_buddy/settings.py`** — keep `get_settings()` signature; internals delegate to `OneiricSettings.substrate`.

- [ ] **Step 4: Update SB call sites** (`session_buddy/adapters/settings.py:_resolve_data_dir()` etc.) — these read from `data_dir`, NOT substrate, so should be untouched per spec.

- [ ] **Step 5: Run SB test suite** (`pytest session_buddy/tests/`); fix regressions.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/settings.py session_buddy/tests/test_substrate_settings_via_oneiric.py
git commit -m "refactor(session-buddy): adopt OneiricSettings.substrate for cross-component settings"
```

### Task 3: Mahavishnu atomic config migration (pool/telemetry/retry/auth only)

**Files:**
- Modify: `mahavishnu/core/config.py`
- Test: `mahavishnu/tests/test_substrate_settings_via_oneiric.py` (new)

#### Integration Contract

- **Triggered from**: Mahavishnu process restart with new settings loader.
- **Returns to**: `mahavishnu.core.config.MahavishnuSettings` exposes `pool_workers_per_instance`, `telemetry_service_namespace`, `retry_max_attempts`, `auth_enabled`, `auth_loopback_trusted` from substrate.
- **Demonstrable by**: `ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE=10 python -c "from mahavishnu.core.config import load_settings; s = load_settings(); print(s.pool_workers_per_instance)"` prints `10`.
- **Rollback signal**: Mahavishnu fails to start.
- **Observability added**: OTel span `settings.substrate.access` with `component="mahavishnu"`, `field`.

- [ ] **Step 1: Write failing test**:

```python
# mahavishnu/tests/test_substrate_settings_via_oneiric.py
def test_mahavishnu_pool_workers_via_substrate(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE", "10")
    from mahavishnu.core.config import load_settings
    s = load_settings()
    assert s.pool_workers_per_instance == 10
```

- [ ] **Step 2: Run, expect failure** — Mahavishnu currently has local `MAHAVISHNU__*` keys.

- [ ] **Step 3: Atomic rewrite of `mahavishnu/core/config.py`** — for pool/telemetry/retry/auth, adopt substrate. **DO NOT** touch warm/cold/embedding (Mahavishnu out-of-scope per spec §5.5).

- [ ] **Step 4: Run Mahavishnu suite** (`pytest mahavishnu/tests/`); fix regressions.

- [ ] **Step 5: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/config.py mahavishnu/tests/test_substrate_settings_via_oneiric.py
git commit -m "refactor(mahavishnu): adopt OneiricSettings.substrate for pool/telemetry/retry/auth"
```

### Task 4: Auth short-circuit preserved test

**Files:**
- Create: `tests/integration/test_auth_short_circuit_preserved.py`

#### Integration Contract

- **Triggered from**: Component startup with `auth__enabled=False`.
- **Returns to**: Both middleware AND decorator auth gates short-circuit cleanly.
- **Demonstrable by**: `pytest tests/integration/test_auth_short_circuit_preserved.py -v` PASS for Akosha + SB + Mahavishnu, covering both halves of the invariant:
  - `auth__enabled=False` short-circuits both middleware AND decorator gates.
  - **`auth__loopback_trusted=True` permits localhost unauth'd connections** (v5 addition — pre-v5 only tested the first half per `feedback-bodai-localhost-no-auth.md`).
- **Rollback signal**: middleware or decorator raises `AuthRequired` despite `auth__enabled=False`.
- **Observability added**: log line `auth.short_circuited=true` with `component`.

- [ ] **Step 1: Write the test**:

```python
import pytest

@pytest.mark.parametrize("component", ["akosha", "session_buddy", "mahavishnu"])
def test_auth_enabled_false_short_circuits_all_gates(component, monkeypatch):
    """Per feedback-bodai-localhost-no-auth.md — both middleware AND decorator."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "false")

    if component == "akosha":
        from akosha.mcp.auth_middleware import auth_middleware
        from akosha.mcp.auth_decorator import require_auth
        assert callable(auth_middleware) and callable(require_auth)
        # Both gates must be `no-op` callable and pass-through for the test request.
        # (implementation uses the same `auth_enabled` flag; verify both paths.)
    elif component == "session_buddy":
        ...
    elif component == "mahavishnu":
        ...
```

- [ ] **Step 2: Run, expect pass** (existing behavior; this test pins it against regression).

- [ ] **Step 3: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/test_auth_short_circuit_preserved.py
git commit -m "test: assert auth short-circuit preserved across substrate adoption"
```

### Task 5: `/health` feed-state aggregation

**Files:**
- Modify: `akosha/mcp/server.py`, `session_buddy/mcp/server.py`, `mahavishnu/mcp/server_core.py` (or wherever `/health` aggregates; **v5 correction** — actual `/health` aggregator lives in `mahavishnu/mcp/server_core.py` at lines 1129+, not `server.py`)
- Test: `tests/integration/test_health_feed_state_aggregated.py`

#### Integration Contract

- **Triggered from**: `curl http://localhost:<port>/health`.
- **Returns to**: JSON with `{status, feeds: {cache_state, warm_state, cold_state, embedding_state}}` where each value has `{entities_count, last_updated_timestamp, errors_total, cycles_total}`.
- **Demonstrable by**: `curl http://localhost:8682/health | jq .feeds` shows four feeds; same shape for SB (8678) and Mahavishnu (8680); `pytest tests/integration/test_health_feed_state_aggregated.py -v` PASS.
- **Rollback signal**: aggregator returns `{}` or missing feed state.
- **Observability added**: per spec §5.6 — `503` when any feed has `last_updated_timestamp` older than `5 × polling_interval`.

- [ ] **Step 1: Write failing test**:

```python
# tests/integration/test_health_feed_state_aggregated.py
import requests

@pytest.mark.parametrize("port", [8682, 8678, 8680])  # akosha, sb, mahavishnu
def test_health_returns_four_feeds(port):
    r = requests.get(f"http://localhost:{port}/health", timeout=5)
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert "feeds" in body
        for feed in ("cache_state", "warm_state", "cold_state", "embedding_state"):
            assert feed in body["feeds"], f"missing {feed}"
            for k in ("entities_count", "last_updated_timestamp", "errors_total", "cycles_total"):
                assert k in body["feeds"][feed]
```

- [ ] **Step 2: Run, expect failure** (current `/health` doesn't aggregate `get_feed_state`).

- [ ] **Step 3: Implement aggregation in each component's `/health`**. The Akosha, SB, and Mahavishnu `mcp/server.py` (or `mcp/server_core.py` — verify per component) gather substrate adapter `get_feed_state()` results and emit the JSON shape.

- [ ] **Step 4: Re-run test, expect pass** (against running services or in-process via FastAPI test client).

- [ ] **Step 5: Commit**:

```bash
cd /Users/les/Projects/mahavishnu  # or appropriate component repo
git add mcp/server.py mcp/server_core.py tests/integration/test_health_feed_state_aggregated.py  # v5: includes server_core.py
git commit -m "feat(mahavishnu): /health aggregates substrate feed state"
# Repeat for akosha and session-buddy repos if their /health lives there.
```

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `akosha/config.py` | MODIFY (atomic): adopt substrate + delete local keys | Task 1 |
| `akosha/tests/test_substrate_settings_via_oneiric.py` | CREATE | Task 1 |
| `session_buddy/settings.py` | MODIFY (atomic): adopt substrate + delete local keys | Task 2 |
| `session_buddy/tests/test_substrate_settings_via_oneiric.py` | CREATE | Task 2 |
| `mahavishnu/core/config.py` | MODIFY (atomic): adopt substrate for pool/telemetry/retry/auth | Task 3 |
| `mahavishnu/tests/test_substrate_settings_via_oneiric.py` | CREATE | Task 3 |
| `tests/integration/test_auth_short_circuit_preserved.py` | CREATE | Task 4 |
| `akosha/mcp/server.py` (or health handler) | MODIFY: aggregate feed state | Task 5 |
| `session_buddy/mcp/server.py` (or health handler) | MODIFY: aggregate feed state | Task 5 |
| `mahavishnu/mcp/server_core.py` (or health handler; v5: not `server.py`) | MODIFY: aggregate feed state | Task 5 |
| `tests/integration/test_health_feed_state_aggregated.py` | CREATE | Task 5 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "auth.enabled" akosha/config.py session_buddy/settings.py mahavishnu/core/config.py` | references to `OneiricSettings.substrate.auth__enabled` (or compat layer name) | shell grep |
| `pytest akosha/tests/test_substrate_settings_via_oneiric.py session_buddy/tests/test_substrate_settings_via_oneiric.py mahavishnu/tests/test_substrate_settings_via_oneiric.py -v` | all green | pytest exit 0 |
| `pytest tests/integration/test_auth_short_circuit_preserved.py -v` | PASS | pytest exit 0 |
| `pytest tests/integration/test_health_feed_state_aggregated.py -v` | PASS | pytest exit 0 |
| `curl http://localhost:8682/health | jq .feeds` | four feeds with 4-key FeedState | jq output |
| `curl http://localhost:8678/health | jq .feeds` | same shape | jq output |
| `curl http://localhost:8680/health | jq .feeds` | same shape | jq output |
| `crackerjack run -v` (each component) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Partial migration during rollout (file reads from substrate while sibling file still has local key) → resolution ambiguity | High | **Atomic per-file rule** — Tasks 1/2/3 each land in single commit. CI guard test asserts no hybrid state |
| Auth short-circuit regresses (one path reads substrate, the other reads local) | Medium | Task 4 pinned test (both `auth__enabled=False` and `auth__loopback_trusted=True` halves) |
| `/health` aggregator misses a feed | Medium | Task 5 parametrized test runs against three ports + 503 trigger test |
| Settings loader regressions break external callers | Low | Public `get_settings()` / `load_settings()` signatures stay; only internals change |
| OTel spans duplicated across three components | Low | Each is namespaced under `component=<name>`; OK |
| **(Meta, spec §10 #7) oneiric becomes a hard substrate dependency** | High (Phase E2 is the culmination) | Each component's `pyproject.toml` already has `oneiric` from prior phases; Phase E2 adds explicit settings-layer dependency. CI guard test asserts minimum version with oneiric-specific test vector. |
| **(Meta, spec §10 #8) Cross-component import direction violation** | Medium | Phase E2 introduces none; `OneiricSettings.substrate` import is `Component → oneiric`. CI guard: `grep -rn "from mahavishnu\|import mahavishnu\|from akosha\|import akosha\|from session_buddy\|import session_buddy" mahavishnu/akosha/session_buddy/` returns zero cross-component hits. |
| **(Meta, spec §10 #9) Rollback complexity across 6 phases × 4 repos** | Medium for Phase E2 | Phase E2 atomic per-file adoption allows surgical per-component rollback. Reverting one component's `config.py` restores local fields; substrate field remains but unused. Per-component rollback works. |

## 10. Decision Rule

Phase E2 is complete when ALL of:

- All 5 tasks land as commits.
- All 3 components adopt substrate in their settings modules.
- `pytest tests/integration/test_auth_short_circuit_preserved.py tests/integration/test_health_feed_state_aggregated.py -v` PASS.
- `curl http://localhost:{8682,8678,8680}/health | jq .feeds` shows 4-feed shape per component.
- `crackerjack run -v` green on Akosha + SB + Mahavishnu.

**Release-train gate**: E1 shipped + atomic per-file adoption in each component + auth short-circuit preserved test green.

## References

- `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.6 — Phase E2 contract
- `oneiric/core/config.py:246` — canonical settings class
- `oneiric/core/substrate_settings.py` — `SubstrateSettings` (added in Phase E1)
- `feedback-bodai-localhost-no-auth.md` — auth short-circuit must be preserved
- `.claude/decisions/wire-up-contract.md` — Integration Contract rules
- `.claude/decisions/mcp-backend-wiring-discipline.md` — feed-state aggregation requirements
