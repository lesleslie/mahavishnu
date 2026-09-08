---
status: active
role: implementation
date: 2026-09-07
last_reviewed: 2026-09-07
superseded_by: null
topic: pool-backend-pi
requirements:
  - id: REQ-PI-001
    title: "PiPool npx_command allowlist (rejects arbitrary binaries)"
  - id: REQ-PI-002
    title: "PiPool implements BasePool ABC contract"
  - id: REQ-PI-003
    title: "PiPool subprocess env stripping (sensitive keys never leaked)"
  - id: REQ-PI-004
    title: "PiPool.scale raises NotImplementedError for n>1 (matches SessionBuddyPool)"
  - id: REQ-PI-005
    title: "PiPool.start runs startup_self_test and records version"
  - id: REQ-PI-006
    title: "PiPool.health_check exposes rpc_latency_ms and startup_self_test block"
  - id: REQ-PI-007
    title: "PiPool.execute_task maps RPC errors to pool result shape"
  - id: REQ-PI-008
    title: "PiPool unit tests cover scale, env-stripping, npx-allowlist, and registry"
---

# Pi Pool Backend (D1)

**Date:** 2026-09-07
**Status:** `active`, `implementation`
**Owner:** Core Eng
**Scope:** Mahavishnu (`/Users/les/Projects/mahavishnu`)
**Companion plan:** `/Users/les/.claude/plans/adaptive-hugging-mist.md` — D0 (registry) + D1 + D2 + D3. This plan implements D1 in isolation.

## 1. Outcome

When this plan ships, Mahavishnu gains a fourth pool type (`pi`) that bridges
Python orchestrators with Pi's model-agnostic agent loop via a single
persistent `npx @earendil-works/pi-coding-agent --rpc` subprocess per pool.
Tasks are dispatched through Content-Length framed JSON-RPC 2.0 over stdio
(see BLOCKER #9 in the parent plan). Security primitives are non-negotiable:

1. The `npx_command[0]` MUST be in `{npx, /usr/bin/env, /usr/local/bin/npx}`
   and the command MUST contain `--rpc` and reference
   `@earendil-works/pi-coding-agent`. Verified at `PiPoolSettings` construction
   time. (REQ-PI-001)
2. The subprocess env is **stripped** to the `env_allowlist` keys; parent
   env keys matching `MAHAVISHNU_*`, `MINIMAX_*`, `ZAI_*`, `DHARA_*`,
   `AKOSHA_*`, `SESSION_BUDDY_*` are NEVER forwarded. (REQ-PI-003)

How we know it succeeded:

- `pytest tests/unit/pools/test_pi_pool.py -v --no-cov` passes
- `pytest tests/unit/test_pi_pool_env_stripping.py -v --no-cov` confirms
  `MINIMAX_API_KEY` and `MAHAVISHNU_AUTH_SECRET` are NOT visible to the
  child subprocess
- `pytest tests/unit/test_pi_pool_npx_allowlist.py -v --no-cov` confirms
  `/bin/sh` (or any non-canonical binary) is rejected at construction time
- `mahavishnu pool list` returns `('mahavishnu', 'pi', 'runpod', 'session-buddy')`

## 2. Goals

1. PiPool registered via the D0 registry (`mahavishnu.pools._registry`).
   No three-place edit required (REQ-PI-002).
2. `scale(n>1)` raises `NotImplementedError` matching `SessionBuddyPool`.
   CLI surfaces a clear error instead of misleading "Scaled to N workers"
   (REQ-PI-004).
3. `start()` runs a `_startup_self_test` (probes `--version`) and stores the
   result in `_startup_version` for the health-check payload (REQ-PI-005).
4. `health_check()` returns the canonical shape:
   `{pool_id, pool_type, status, workers_active, worker_health: {rpc_latency_ms, last_ping_at, version, startup_self_test: {passed, version, checked_at}}}`
   (REQ-PI-006).
5. `execute_task()` error mapping centralised in
   `_map_rpc_error_to_pool_error` so the method stays within the
   `max-branches=15` budget (REQ-PI-007).
6. Subprocess env stripping enforced at the JSON-RPC client layer, not
   at the PiPool layer, so any future subprocess-pool backend inherits the
   protection (REQ-PI-003).

## 3. Non-Goals

1. No new MCP tools (existing `pool_*` tools route through the registry).
2. No Prometheus/Grafana dashboard updates (counters go through existing
   OTel emitter).
3. No Docker/Compose changes.
4. No new third-party dependencies (stdlib-only for JSON-RPC stdio client;
   `@earendil-works/pi-coding-agent` is operator-installed, not bundled).
5. No GraphQL/REST surface changes.
6. Goose adapter (D3) is a separate plan; this plan does NOT touch
   `mahavishnu/terminal/`.
7. Multiple subprocesses per PiPool (the registry pattern supports adding
   additional pool instances; PiPool itself is intentionally fixed-count).

## 4. Current Findings

- `mahavishnu/pools/_registry.py` (D0) already provides
  `register_pool_type` / `get_pool_factory` / `list_pool_types`. The
  `pi` entry is added by `mahavishnu/pools/pi_pool.py:PiPool` calling
  `register_pool_type("pi", _build_pi_pool)` at module import.
- `SessionBuddyPool.scale` at `mahavishnu/pools/session_buddy_pool.py:270`
  raises `NotImplementedError` with the wording
  `"SessionBuddyPool has fixed worker count (3). Spawn additional pools for more capacity."`.
  PiPool mirrors this pattern at line ~210 with `"... fixed worker count (1) ..."`.
- `JSONRPCError` / `JSONRPCErrorCode` live in
  `mahavishnu/core/json_rpc_ipc.py` and are exported via `__all__`. The
  stdio client imports them rather than re-defining (per parent plan's
  Mahavishnu reviewer finding #5 — don't lift shared module).

## 4.5 Requirements

(Declared above; consolidated here for the audit script.)

```yaml
requirements:
  - id: REQ-PI-001
    title: "PiPool npx_command allowlist"
  - id: REQ-PI-002
    title: "PiPool implements BasePool ABC contract"
  - id: REQ-PI-003
    title: "PiPool subprocess env stripping"
  - id: REQ-PI-004
    title: "PiPool.scale raises NotImplementedError for n>1"
  - id: REQ-PI-005
    title: "PiPool.start runs startup_self_test"
  - id: REQ-PI-006
    title: "PiPool.health_check canonical shape"
  - id: REQ-PI-007
    title: "PiPool.execute_task error mapping"
  - id: REQ-PI-008
    title: "PiPool unit tests"
```

## 5. Implementation Phases

### Phase 1: Foundation (D0 dependency)

This plan assumes D0 has landed. D0 introduces
`mahavishnu/pools/_registry.py` and the registry-driven dispatch in
`PoolManager.spawn_pool`. **No work in this phase** — D0 is a
prerequisite.

### Phase 2: JSON-RPC stdio client

**Goal:** Asyncio stdio subprocess with Content-Length framing, watchdog,
- stripped env, and a stream_factory test seam.
**Files:** `mahavishnu/core/json_rpc_stdio.py` (new),
`mahavishnu/core/errors.py` (add `PiUnavailable` / `PiRPCTimeout` /
`PiProtocolError`).
**Tasks:**
- Implement `JSONRPCStdioClient` (start, stop, request, notify, ping,
  session).
- Reuse `JSONRPCError` / `JSONRPCErrorCode` from
  `mahavishnu/core/json_rpc_ipc.py`.
- Add `_REQUIRED_PASSTHROUGH_KEYS` = `(PATH, HOME, LANG, NODE_PATH,
  NODE_ENV, TMPDIR)` and `_build_subprocess_env()` that overlays the
  caller's `env_allowlist` on the parent env (REQ-PI-003).
- Spawn a `_watchdog_loop` task at `start()` that fails pending
  requests on heartbeat miss or stdout EOF.
- Add three new error classes with redacted `__repr__` / `__str__` (see
  Phase 3 notes — same pattern as Goose/D3 errors).

**Exit criteria:**
- `JSONRPCStdioClient` imports cleanly and the tests in
  `tests/unit/test_pi_pool_env_stripping.py` pass.

#### Integration Contract (Phase 2)

- **Triggered from**: `PiPool.start()` calling
  `JSONRPCStdioClient(command=…, env=env_allowlist).start()`.
- **Returns to / updates**: Started subprocess with stripped env; pending
  requests queue mapped to per-id futures; watchdog task running in
  background.
- **Demonstrable by**:
  `pytest tests/unit/test_pi_pool_env_stripping.py -v --no-cov` confirms
  `MAHAVISHNU_AUTH_SECRET`, `MINIMAX_API_KEY`, `ZAI_API_KEY`, `DHARA_*`,
  `AKOSHA_*`, `SESSION_BUDDY_*` are NOT in `subprocess_env`; `PATH`
  IS.
- **Rollback signal**: `JSONRPCStdioClient.start()` raises
  `PiProtocolError` for every spawn attempt → indicates `npx` binary
  missing. Operators must install Node.js (bundles `npx`).
- **Observability added**: INFO log `pool.pi.spawned` with
  `pool_id`, `version`, `startup_self_test_version` (REQ-PI-005);
  WARNING log on watchdog heartbeat miss.

### Phase 3: PiPool class

**Goal:** `PiPool(BasePool)` registered via D0 registry.
**Files:** `mahavishnu/pools/pi_pool.py` (new).
**Tasks:**
- Implement 8 abstract methods: `start`, `execute_task`,
  `execute_batch`, `scale`, `health_check`, `get_metrics`,
  `collect_memory`, `stop`.
- `scale(n>1)` raises `NotImplementedError` (REQ-PI-004).
- `execute_task` delegates error mapping to
  `_map_rpc_error_to_pool_error` (REQ-PI-007).
- `health_check` returns the canonical shape (REQ-PI-006).

**Exit criteria:** `pytest tests/unit/pools/test_pi_pool.py -v --no-cov`
passes; `list_pool_types()` includes `"pi"`.

#### Integration Contract (Phase 3)

- **Triggered from**: `PoolManager.spawn_pool("pi", config)` →
  `_build_pi_pool(config)` → `PiPool(config).start()` → executes via
  `pool_execute(pool_id, task)`.
- **Returns to / updates**: Pool registry entry; OTel dot-separated
  metrics `mahavishnu.pi.tasks.executed{status}`,
  `mahavishnu.pi.task.duration`, `mahavishnu.pi.heartbeat.missed_total`
  (per parent plan observability reviewer #1).
- **Demonstrable by**:
  `pytest tests/unit/pools/test_pi_pool.py -v --no-cov` covers scale,
  env-stripping, npx-allowlist, registry, error redaction, happy-path
  `execute_task`, timeout mapping, protocol-error mapping.
- **Rollback signal**: `pool_list` MCP shows no `"pi"` entry after
  deploy; `mahavishnu.pi.tasks.executed` flatlines for >10 min; the
  Crackerjack gate fails on `pools/pi_pool.py` or
  `core/json_rpc_stdio.py`.
- **Observability added**: counters and spans per parent plan; INFO log
  `pool.pi.spawned`; ERROR log `pool.pi.task_failed` (with redacted
  payload via the new error classes); ERROR log
  `pool.pi.subprocess_died` on watchdog EOF.

### Phase 4: Config + settings

**Goal:** `PiPoolSettings` is configurable via Oneiric layered config
+ env vars.
**Files:** `mahavishnu/core/config.py` (add `PiPoolSettings`,
mount as `pi_pool:` sibling on `MahavishnuSettings`),
`settings/mahavishnu.yaml` (append `pi_pool:` block).
**Tasks:**
- Pydantic `BaseModel` with `_npx_command_allowlist` validator
  (REQ-PI-001).
- Mount as `pi_pool: PiPoolSettings = Field(default_factory=…)` on
  `MahavishnuSettings`.
- Append `pi_pool:` block to `settings/mahavishnu.yaml` (after
  `runpod_pool:`).

**Exit criteria:** `PiPoolSettings()` instantiates with default values;
`_npx_command_allowlist` rejects `/bin/sh`.

#### Integration Contract (Phase 4)

- **Triggered from**: Oneiric config load (`MAHAVISHNU_PI_POOL__*` env
  vars override YAML defaults).
- **Returns to / updates**: `MahavishnuSettings.pi_pool` instance
  accessible via the existing settings access pattern.
- **Demonstrable by**: `python -c "from mahavishnu.core.config import
  PiPoolSettings; PiPoolSettings()"` works.
- **Rollback signal**: Config validator failure on startup.
- **Observability added**: Validation errors raise
  `ConfigurationError` with operator-facing messages; logged at
  startup.

### Phase 5: Test coverage

**Goal:** ≥80% line coverage on new files; integration smoke test
optional but recommended.
**Files:** `tests/unit/pools/test_pi_pool.py` (new),
`tests/unit/test_pi_pool_env_stripping.py` (new),
`tests/unit/test_pi_pool_npx_allowlist.py` (new),
`tests/integration/test_pi_pool_smoke.py` (new, optional, opt-in via
`-m integration`).
**Exit criteria:** `pytest tests/unit/pools/test_pi_pool.py
tests/unit/test_pi_pool_env_stripping.py
tests/unit/test_pi_pool_npx_allowlist.py -v --no-cov` passes.

#### Integration Contract (Phase 5)

- **Triggered from**: `pytest` discovery; integration test from
  `pytest -m integration`.
- **Returns to / updates**: Test report; coverage gate.
- **Demonstrable by**: All test files pass.
- **Rollback signal**: Coverage drops below 80% on new files.
- **Observability added**: N/A (test-only).

## 6. Required Code Changes

- [x] `mahavishnu/core/json_rpc_stdio.py` — new file
- [x] `mahavishnu/core/errors.py` — add `PiUnavailable`, `PiRPCTimeout`,
  `PiProtocolError`
- [x] `mahavishnu/pools/pi_pool.py` — new file
- [x] `mahavishnu/core/config.py` — add `PiPoolSettings`, mount as
  `pi_pool:` on `MahavishnuSettings`
- [x] `settings/mahavishnu.yaml` — append `pi_pool:` block
- [x] `mahavishnu/pools/__init__.py` — add `pi_pool` to
  `_load_all_pool_types()`
- [x] `mahavishnu/pools/_registry.py` — add `pi_pool` to
  `_ensure_pool_registry_loaded()`
- [x] `tests/unit/pools/test_pi_pool.py` — new file
- [x] `tests/unit/test_pi_pool_env_stripping.py` — new file
- [x] `tests/unit/test_pi_pool_npx_allowlist.py` — new file
- [ ] `tests/integration/test_pi_pool_smoke.py` — new file (optional;
  spawns real `npx`)

## 7. Validation Matrix

| Check | Expected outcome | Evidence |
|-------|------------------|----------|
| `python -c "from mahavishnu.core.json_rpc_stdio import JSONRPCStdioClient"` | imports cleanly | bash |
| `python -c "from mahavishnu.core.config import PiPoolSettings; PiPoolSettings()"` | instantiates with defaults | bash |
| `python -c "from mahavishnu.pools.pi_pool import PiPool; from mahavishnu.pools._registry import list_pool_types; assert 'pi' in list_pool_types()"` | `pi` is registered | bash |
| `pytest tests/unit/pools/test_pi_pool.py -v --no-cov` | passes | pytest |
| `pytest tests/unit/test_pi_pool_env_stripping.py -v --no-cov` | passes | pytest |
| `pytest tests/unit/test_pi_pool_npx_allowlist.py -v --no-cov` | passes | pytest |
| `pytest tests/unit/pools/ -v --no-cov` | 109+ passed | pytest |
| `python scripts/audit_requirements.py --json` | reports clean (0 orphans, 0 phantoms) | bash |
| `pytest tests/integration/test_audit_requirements.py -v -m integration --no-cov` | passes | pytest |

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `npx` binary not present on operator hosts | Medium | `PiUnavailable` carries `install_hint="install Node.js (https://nodejs.org)"`; `pool spawn --type pi` fails fast |
| Pi package version drift breaks `--rpc` framing | Low | `pinned_version` defaults to `@earendil-works/pi-coding-agent@^1.0.0`; version recorded in health_check for triage |
| Subprocess death silently loses tasks | Low | Watchdog task + EOF detection + PiRPCTimeout propagation |
| Secret env leakage to subprocess | Mitigated | `env_allowlist` excludes every sensitive prefix; `tests/unit/test_pi_pool_env_stripping.py` enforces |
| `--rpc` mode absent in newer Pi versions | Low | `pinned_version` + `frame_excerpt` in `PiProtocolError` for triage |
| Memory coverage regression (Crackerjack gate at 89.02%) | Low | Complexity budgets per parent plan §D1.8 (≤15 branches per method) |

## 9. Decision Rule

This plan is "done enough" when:

1. All REQ-PI-001 through REQ-PI-008 markers are in code, and
   `audit_requirements.py --json` reports zero orphans / zero phantoms.
2. `pytest tests/unit/pools/ -v --no-cov` passes (109+ tests).
3. `pytest tests/unit/test_pi_pool_env_stripping.py -v --no-cov`
   confirms the env-stripping contract.
4. `pytest tests/integration/test_audit_requirements.py -v -m
   integration --no-cov` passes.
5. Crackerjack gate holds at 89.02% on the unchanged code; new files
   hit ≥80% line coverage.

Scope pressure cut (if any): drop `tests/integration/test_pi_pool_smoke.py`
(opt-in integration test) and rely on unit tests + the operator's
`mahavishnu pool spawn --type pi` smoke. The integration smoke is nice-to-have,
not load-bearing for the wiring contract.

## How to save to Session-Buddy

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature pi-pool-backend: state=built, "
        "built=yes, wired=yes, "
        "blocker=none, "
        "next=manual smoke via `mahavishnu pool spawn --type pi` + "
        "`mahavishnu pool execute <id> --prompt hello`"
    ),
    tags=["feature-tracking", "pi-pool-backend", "wire-up-state"],
)
```

## References

- Parent plan: `/Users/les/.claude/plans/adaptive-hugging-mist.md`
  §D1 (this plan implements D1 in isolation).
- `docs/plans/TEMPLATE.md` — Integration Contract template.
- `docs/feature-tracking/TEMPLATE.md` — feature-tracking template.
- `mahavishnu/pools/_registry.py` — D0 registry.
- `mahavishnu/pools/session_buddy_pool.py` — pattern reference for
  `scale()` raising `NotImplementedError`.
- `mahavishnu/core/json_rpc_ipc.py` — JSON-RPC enums reused by the
  stdio client.
- `mahavishnu/workers/apple_container.py:62-69` — subprocess seam
  pattern.
- `scripts/audit_requirements.py` — traceability audit.
- `scripts/audit_orphans.py` — orphan-symbol audit.
