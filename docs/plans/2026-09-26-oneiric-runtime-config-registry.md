---
status: active
role: implementation
date: 2026-09-26
last_reviewed: 2026-10-12
last_revised_note: "Phase 2 corrected (v3) — list_adapters is at line 1225, not 1037-1084; SettingsWatcher.on_change does not exist; reconfigure trigger is oneiric.runtime.watchers.SelectionWatcher. Wire contract preservation rule added."
superseded_by: 2026-10-15-oneiric-substrate-rollout.md
topic: oneiric-runtime-config-registry
kind: plan
title: "Oneiric Runtime Config Registry — Implementation Plan (v3)"

---

# Oneiric Runtime Config Registry — Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Each Phase's Integration Contract block is REQUIRED for completion certification.
>
> **Status:** Awaiting multi-agent plan sign-off (Phase 0). v2 incorporates feedback from 5 reviewers (architecture, codebase, MCP integration, oneiric-specialist, security). Code edits begin only after sign-off.

**Goal:** Make "what's actually loaded right now?" a first-class, single-source-of-truth query for every Bodai component, by extending Oneiric's existing `OneiricAdapterRegistry` with a namespaced `runtime_facts` field. Each component pushes its own runtime facts on boot + on reconfigure via the new `oneiric_report_runtime` MCP tool; the canonical query becomes `oneiric_get_adapter_health(domain, key, provider)`, which returns `{registry: {…}, runtime: {…}|null, health: {…}}` — additive-only shape change that preserves the existing factory-import probe.

**Architecture:** Extend `OneiricAdapterRegistry` (`oneiric/mcp/adapter_registry.py`) in place — add `runtime_facts: RuntimeFacts | None = None` to `AdapterRecord`, add `set_runtime_facts_async(...)` method to the registry, thread through both `to_dict()` and `_save()` (which are non-symmetric today). Add the new `oneiric_report_runtime` tool to the existing `_register_adapter_tools` function (NOT a sibling `_register_runtime_registry_tools`). Wrap the new tool with server-side secret sanitization (`_SECRET_KEY_NAMES` denylist + URL-userinfo parsing). `runtime_facts` payload uses a namespaced schema `{config, capabilities, redacted_secrets, health_reserved}` for forward compat. Mahavishnu's existing `mcp__mahavishnu__list_adapters` stays as-is (faster, in-process).

**Tech Stack:** Oneiric (foundation, FastMCP server), Bodai components (Mahavishnu, Akosha, Crackerjack, Session-Buddy), `mcp-common` (auth decorators, permission enum), `oneiric.mcp.adapter_registry` (extended in place).

**Spec:** This plan is its own spec.

---

## 1. Outcome

- **User-observable change:** `oneiric_get_adapter_health(domain="adapter", key="prefect", provider="mahavishnu")` returns `{registry: {…catalog…}, runtime: {…config + capabilities + redacted_secrets…} | null, health: {…probe…}}`. Each non-Oneiric component's boot path contributes its facts once and forgets — no per-tool polling. Any push containing secret-shaped keys is sanitized server-side before persistence; the persisted value is `"<redacted>"` and the original key is recorded in `runtime_facts.redacted_secrets`.
- **Success metric:** Within 30 seconds of any Bodai component boot, `oneiric_get_adapter_health` for any adapter owned by that component returns a non-null `runtime` block matching the in-process config (verified by e2e test that boots the server, makes the call, and compares). Zero secrets persist to disk (verified by e2e test that pushes `{api_key: "sk-abc"}` and asserts the value on disk is `"<redacted>"`).

## 2. Goals

1. Operators have ONE query path for "what's actually running" — `oneiric_get_adapter_health`.
2. Each Bodai component's runtime facts reach Oneiric within 30s of boot or reconfigure.
3. The catalog-vs-runtime gap is closed in Oneiric, not replicated per-component.
4. **Server-side** secret sanitization — secrets never reach disk even if a caller forgets to redact.
5. The new write tool (`oneiric_report_runtime`) requires auth even on loopback (write tools are NOT loopback-trusted per R5).
6. File permissions on `~/.oneiric/adapter_registry.json` are `0600`; directory `~/.oneiric/` is `0700`.
7. Per-call audit record for every `oneiric_report_runtime` (caller PID, component name, payload sha256).
8. Wire-up-contract compliance: `audit_orphans.py` clean; `tests/integration/test_<tool>_e2e.py` for every new tool; `/health` aggregator includes the new feed.

## 3. Non-Goals

1. Replicating `list_adapters` per-component (Oneiric owns the catalog).
2. Real-time health signals (workers_active, connection liveness) — separate, bigger problem.
3. Refactoring Mahavishnu's existing `mcp__mahavishnu__list_adapters` to delegate to Oneiric.
4. Replacing the file-backed registry with a Dhara-backed one (catalog + runtime facts both stay JSON in Phase 1; future phases may move runtime to Dhara — but not this plan).
5. Dhara participation in this plan (Dhara has no MCP server per the CLAUDE.md port map).
6. Polling for staleness (push-on-event is enough; 30s staleness is acceptable).
7. Backward compatibility for the `{success, health}` shape (pre-1.0: replace not extend).
8. Tool profile gating for Oneiric (Oneiric has no `ToolProfile` system per R3 — registered unconditionally).

## 4. Current Findings

- **Oneiric's adapter registry** (`oneiric/mcp/adapter_registry.py`) stores `(domain, key, provider, version, factory_path, config, dependencies, capabilities, metadata, health_status, last_health_check)`. No runtime-facts field. 7 tools: `store_adapter`, `get_adapter`, `list_adapters`, `list_adapter_versions`, `validate_adapter`, `get_adapter_health`, `get_contract_info`.
- **`_save()` non-symmetric serialization (R4 BLOCKER).** `AdapterRecord.to_dict()` (`adapter_registry.py:116`) and `_save()` (line 197-220) are not mirror images — `to_dict()` includes `schema_version: 1` while `_save()` silently drops it. Adding `runtime_facts` to both sides is REQUIRED; missing either breaks persistence.
- **`_load()` constructor site (R4).** `AdapterRecord(...)` calls inside `_load()` (line 174-190) do not pass `runtime_facts`. New field defaults to `None` correctly via dataclass default, but explicit threading avoids future drift.
- **Mahavishnu's `mcp__mahavishnu__list_adapters` (defined at `mahavishnu/mcp/server_core.py:1225` inside `_register_tools()` which is at line 313, called from `FastMCPServer.__init__` at line 143)** is the reference shape for runtime facts. Returns the legacy `{adapters: {name: {enabled, health, type, features}}, count, available_names}` envelope.
- **No other component has an equivalent tool.** Asymmetry confirmed 2026-09-26 via MCP tool listings.
- **Auth posture:** `~/.oneiric/settings.yaml` has `auth.enabled: false`; loopback trusted per `feedback-bodai-localhost-no-auth` memory. Decorators threaded with `allow_anonymous=not auth_enabled` after the 2026-09-26 auth fix.
- **Per-tool feed deferral comment at `server.py:359-364`** says "Per-tool HealthFeedState aggregation is DEFERRED to a follow-up." Phase 1.6 will partially roll this back for the new tool — update the comment in the same change (R4).
- **Crackerjack boot path is HIGH RISK (R2).** `crackerjack/cli/` is fragmented; the plan must verify Crackerjack's MCP server is in the boot path before Phase 3 wires it. If it is not, Phase 3 is N/A for Crackerjack.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-RCR-001
    title: "oneiric_report_runtime tool persists sanitized runtime facts per adapter"
  - id: REQ-RCR-002
    title: "oneiric_get_adapter_health response merges {registry, runtime, health} additively"
  - id: REQ-RCR-003
    title: "Server-side secret sanitization (denylist + URL userinfo parsing); value replaced with '<redacted>', key recorded in runtime_facts.redacted_secrets"
  - id: REQ-RCR-004
    title: "Each non-Oneiric Bodai component pushes its adapter runtime facts on boot"
  - id: REQ-RCR-005
    title: "Old registry entries without runtime_facts continue to load (backcompat JSON)"
  - id: REQ-RCR-006
    title: "Registry file mode 0600; registry root dir mode 0700 (chmod in _save and __init__)"
  - id: REQ-RCR-007
    title: "oneiric_report_runtime requires auth even on loopback (write tools are NOT loopback-trusted)"
  - id: REQ-RCR-008
    title: "Caller-identity audit log per oneiric_report_runtime call (PID, component, payload sha256)"
  - id: REQ-RCR-009
    title: "AdapterRecord.to_dict() AND _save() BOTH thread runtime_facts (non-symmetric serialization fix)"
  - id: REQ-RCR-010
    title: "runtime_facts payload uses namespaced schema {config, capabilities, redacted_secrets, health_reserved}"
  - id: REQ-RCR-011
    title: "HealthFeedState('runtime_registry') feed wired into _resolve_feeds AND aggregate_health"
  - id: REQ-RCR-012
    title: "audit_orphans.py clean; tests/integration/test_<tool>_e2e.py for every new tool (wiring discipline)"
```

## 5. Implementation Phases

### Phase 0: Multi-Agent Plan Review *(gate)*

**Goal:** Sign-off on v2.
**Tasks:** Reviewers confirm the 17 fixes (see `## Review Notes`) are correctly captured. ≥4 of 5 reviewers mark `[x]`.
**Exit criteria:** Plan status bumped `draft → active`; `## Review Notes` populated.

#### Integration Contract
- **Triggered from:** User approval.
- **Returns to / updates:** This file — frontmatter `status: active`; `## Review Notes` populated.
- **Demonstrable by:** `grep -E '^- \[(x| )\] reviewer:' docs/plans/2026-09-26-oneiric-runtime-config-registry.md` shows ≥4 `[x]` of 5.
- **Rollback signal:** ≥2 reviewers raise blocking objections → status stays `draft`.
- **Observability added:** None (planning artifact).

---

### Phase 1: Oneiric Foundation — Data Model, Sanitization, Tool, Health, Auth, Audit

**Goal:** Extend `OneiricAdapterRegistry` in place with sanitized `runtime_facts`, add the new tool with auth + audit + chmod, wire the new health feed into the aggregator, update the contract info literal. NO sibling file; NO new tool-registration function.

**Tasks (each ends with a passing test cycle):**

- **Task 1.1 (R5 sanitize first, R4 promote to 1.1):** Add `_SECRET_KEY_NAMES` denylist + `_sanitize_runtime_facts()` helper in `oneiric/mcp/adapter_registry.py`. Covers key-name match (case-insensitive) + `<x>_token`/`<x>_secret`/`<x>_key` suffixes + URL userinfo parsing (`urllib.parse.urlparse` → if `username` or `password`, scrub). Replace value with `"<redacted>"`; record original key in `runtime_facts.redacted_secrets`. Add unit test covering both flat and nested dicts.

- **Task 1.2:** Add `RuntimeFacts` Pydantic model in `oneiric/mcp/models.py`: `config: dict[str, Any]`, `capabilities: dict[str, Any] = {}`, `redacted_secrets: list[str] = []`, `health_reserved: None = None` (documented as reserved for future Phase). Add `runtime_facts: RuntimeFacts | None = None` field to `AdapterRecord` (`oneiric/mcp/adapter_registry.py:55`). Thread through `to_dict()` (line 116) — explicitly call `runtime_facts.model_dump()` if non-None, else `None`. Default for legacy entries: `None`.

- **Task 1.3 (R4 non-symmetric serialization BLOCKER):** Edit `_save()` (line 197-220) to include `runtime_facts` in the serialized dict — currently `to_dict()` and `_save()` are not mirror images (schema_version is dropped). Add an explicit dict literal mapping, mirroring `to_dict()`.

- **Task 1.4:** Add `set_runtime_facts_async(domain, key, provider, runtime_facts: dict) -> None` method to `OneiricAdapterRegistry`. Pipeline: `runtime_facts = _sanitize_runtime_facts(runtime_facts)` → look up record by (domain, key, provider) → if not found, create new record (or raise — pick: raise `KeyError`, the caller must `store_adapter` first) → set `record.runtime_facts = RuntimeFacts(**runtime_facts)` → `_save()`.

- **Task 1.5 (R5 chmod BLOCKER):** Edit `OneiricAdapterRegistry.__init__` (line 151-156) to `os.chmod(self._root, 0o700)` if `_root` was just created (check via `exist_ok=True` semantics — use a `if not self._root.exists():` guard). Edit `_save()` (line 197-220) to `os.chmod(self._path, 0o600)` immediately after `tmp.replace(self._path)`. Add unit test asserting both file and dir modes.

- **Task 1.6 (R5 auth + R5 audit + R3 wire-shape + R3 contract_info):** In `oneiric/mcp/server.py`, extend `_register_adapter_tools()` (line 344) with:
  1. New tool `oneiric_report_runtime(domain, key, provider, runtime_facts: dict, caller_component: str) -> dict` decorated with `@mcp.tool()` + `@require_auth(permission=Permission.WRITE, service_name=auth_config.service_name, allow_anonymous=False)` — note `allow_anonymous=False` per R5 (write tools are NOT loopback-trusted). Body: call `_sanitize_runtime_facts()`, then `registry.set_runtime_facts_async(...)`, then emit structured audit log line `runtime-audit caller_pid=<pid> caller_component=<str> domain=<d> key=<k> provider=<p> fact_count=<n> payload_sha256=<hex12>` via `oneiric.mcp.runtime_registry.audit` logger.
  2. Extend `oneiric_get_adapter_health` (line 524-538) to return `{success, registry: rec.to_dict(), runtime: rec.runtime_facts.model_dump() if rec.runtime_facts else None, health: {…unchanged factory-import probe…}}`. Additive — `health` key preserved per R3.
  3. Update `oneiric_get_contract_info` (line 404-440) `tool_groups.adapter_registry` literal to include `"report_runtime"`.

- **Task 1.7 (R3 wiring discipline + R3 health feed aggregator):** Edit `oneiric/mcp/server.py::_resolve_feeds` (line 88-93) to append `"runtime_registry"` to the tuple. Edit `scripts/launch_mcp.py::_build_warm_feeds` (line 143) to append `"runtime_registry"` to the pre-warm loop. Update the per-tool feed deferral comment at `server.py:359-364` to note Phase 1.6 rolled it back for runtime tools only.

- **Task 1.8 (R3 wiring discipline test path):** Create `tests/integration/test_oneiric_report_runtime_e2e.py` — spins up `build_mcp_server(...)`, calls `oneiric_store_adapter` to seed, calls `oneiric_report_runtime` with `runtime_facts={"api_key": "sk-abc", "api_url": "http://x"}` (secret-shaped key + URL), calls `oneiric_get_adapter_health`, asserts: (a) `runtime.config["api_key"] == "<redacted>"`, (b) `runtime.redacted_secrets == ["api_key"]`, (c) `runtime_registry` feed shows `entities_count == 1`, `cycles_total >= 1`. Required by `mcp-backend-wiring-discipline.md` §4.

**Exit criteria:**
- All 8 tasks green; `tests/mcp/test_server.py` still passes (auth-fix invariants preserved); new integration test green.
- `python scripts/audit_orphans.py` reports zero new symbols with zero callers.
- `cd /Users/les/Projects/oneiric && uv run crackerjack run -p patch` clean.
- `launchctl unload && launchctl load` cycle clean; `/health` returns 200 with `runtime_registry` route present.

#### Integration Contract (Phase 1)
- **Triggered from:** Any non-Oneiric component's boot path (Phase 2+) calling `oneiric_report_runtime(domain, key, provider, runtime_facts, caller_component)`. Reachable directly via the MCP tool.
- **Returns to / updates:** `~/.oneiric/adapter_registry.json` (mode `0600`) — append/update the matching (domain, key, provider) entry's `runtime_facts` field after server-side sanitization. Audit log line emitted per call.
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/oneiric && uv run pytest tests/integration/test_oneiric_report_runtime_e2e.py -v
  cd /Users/les/Projects/oneiric && uv run python scripts/audit_orphans.py
  cd /Users/les/Projects/oneiric && uv run crackerjack run -p patch
  launchctl unload ~/Library/LaunchAgents/com.mcp.oneiric.plist && launchctl load ~/Library/LaunchAgents/com.mcp.oneiric.plist
  curl -fsS http://127.0.0.1:8681/health | jq '.routes.runtime_registry'
  ```
- **Rollback signal:** `HealthFeedState("runtime_registry").errors_total > 0` for 60s OR `/health` returns 503 with `runtime_registry.status: "unhealthy"`. Mitigation: revert the merge commit; registry file reverts to pre-extended shape (backcompat JSON per REQ-RCR-005).
- **Observability added:** `HealthFeedState("runtime_registry")` feed (cycles_total, entities_count, errors_total, last_updated_timestamp); structured audit log per call; chmod + sanitization logged via `oneiric.mcp.runtime_registry.audit` logger.

---

### Phase 2: Mahavishnu Wires Up Push on Boot + Reconfigure (v3 corrected)

**Goal:** Mahavishnu contributes its 4 adapter runtime facts (prefect, llamaindex, agno, worker) on boot AND on subsequent adapter-reconfigure events. **Same builder used by both boot push and the existing inline `list_adapters` tool** (R2 single-source-of-truth).

**v3 corrections** (verified 2026-10-12 against `mahavishnu/mcp/server_core.py` and `oneiric/runtime/watchers.py`):
- `list_adapters` tool is defined at `mahavishnu/mcp/server_core.py:1225` (an `async def list_adapters() -> dict[str, Any]` inside `_register_tools()` at line 313, called from `FastMCPServer.__init__` at line 143). The previously-referenced line range 1037-1084 contains unrelated tool decorators.
- `SettingsWatcher.on_change()` **does not exist** in this codebase. The actual reconfigure trigger is `oneiric.runtime.watchers.SelectionWatcher` (`/Users/les/Projects/oneiric/oneiric/runtime/watchers.py:29`, `poll_interval: float = 5.0`).
- `_register_tools()` is called from `FastMCPServer.__init__` at line 143 (not line 109 as the v2 plan stated). `FastMCPServer.start()` lives at line 1473.
- **Wire contract preservation rule** (added v3): the existing `list_adapters` MCP tool returns `{adapters: {name: {enabled, health, type, features}}, count, available_names}` per `mahavishnu/mcp/server_core.py:1225` docstring. Every existing caller (e.g. `get_capability_result`, dashboards) depends on this shape. `RuntimeFactsBuilder.build_all()` MUST preserve this shape for the `list_adapters` path. The Oneiric envelope `{success, registry, runtime, health}` is constructed INSIDE the Oneiric push path (`report_runtime_facts`) and never leaks to `list_adapters`.

**Tasks:**
- **Task 2.1 (R2 BLOCKING, v3 corrected):** Move the body of the inline `list_adapters` tool (`mahavishnu/mcp/server_core.py:1225`, inside `_register_tools` which is defined at `mahavishnu/mcp/server_core.py:313`) into `mahavishnu/core/runtime_facts.py:RuntimeFactsBuilder.build_all()`. The inline tool becomes a one-line `return RuntimeFactsBuilder(self.app).build_all()`. `build_all()` MUST return the legacy `{adapters: {name: {enabled, health, type, features}}, count, available_names}` shape exactly as the v2 inline body did — not the Oneiric envelope. The Oneiric envelope is constructed separately inside `report_runtime_facts` (Task 2.2). Boot push (Task 2.2) calls `build_all()` to source the per-adapter facts and then shapes them for Oneiric.
- **Task 2.2 (R1 reconfigure trigger, v3 corrected):** Add `async def report_runtime_facts(self) -> None` to `MahavishnuApp`. Two trigger paths:
  - **Boot path:** call from `mahavishnu/mcp/server_core.py::FastMCPServer.start()` (line 1473) after the server begins serving. Alternative boot trigger: call from `__init__` at line 143 right after `_register_tools()` returns. Either is acceptable.
  - **Reconfigure path:** subscribe to `oneiric.runtime.watchers.SelectionWatcher` (NOT `SettingsWatcher.on_change()` — that API does not exist). Mahavishnu does NOT import oneiric internals; it polls the Oneiric MCP HTTP endpoint `http://127.0.0.1:8681/mcp` via httpx (per the documented public-surface contract) on a configurable interval, OR instantiates `oneiric.runtime.watchers.SelectionWatcher` only if the plan opts into direct coupling. **Default:** httpx POST loop, because the public-surface contract forbids direct oneiric imports from Mahavishnu.
  - Explicit hook enumeration (R1): `settings.yaml` reload in Oneiric → `SelectionWatcher.tick` → Oneiric's adapter_registry.json updated → Mahavishnu polls `/mcp` → sees the change → `report_runtime_facts()` pushes new facts.
- **Task 2.3 (v3 corrected):** E2E test `tests/integration/test_mahavishnu_pushes_runtime_to_oneiric.py`. Constraints:
  - Test 1 `test_mahavishnu_boot_pushes_runtime_to_oneiric`: spawn `MahavishnuApp`, wait for boot, query `oneiric_get_adapter_health` for each of 4 adapters, assert non-null `runtime` blocks with expected fields.
  - Test 2 `test_mahavishnu_list_adapters_preserves_legacy_wire_shape`: spin up `MahavishnuApp` and call `list_adapters()` MCP tool, assert the response has the exact legacy keys `adapters`, `count`, `available_names` and that `adapters[*]` has the legacy sub-keys `enabled`, `health`, `type`, `features`. This pins the wire-contract preservation rule.
  - Test 3 `test_mahavishnu_reconfigure_pushes_runtime_to_oneiric`: drive the Oneiric reconfigure tick (POST a synthetic change to Oneiric's MCP endpoint, or directly mutate the registry on disk); poll the Oneiric `runtime` block until one within 30s; the assertion compares `cycles_total` (a monotonic counter that Oneiric DOES set), not `generated_at_unix` (which the runtime_facts_builder does NOT set). Earlier draft used `generated_at_unix` — that comparison defaulted to 0==0, a no-op. v3 mandates `cycles_total`.
  - All three tests skip cleanly when Oneiric MCP HTTP endpoint is unreachable.
- **Task 2.4 (R5 circuit breaker, v3 line-precise):** Wrap the `oneiric_report_runtime` call in a circuit breaker. Use the existing `CircuitBreaker` (`mahavishnu/core/resilience.py:212`, async `call(func, *args, **kwargs)` API at line 282, raises `CircuitBreakerOpenError` on open state — MahavishnuError subclass with `ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE`). The breaker instance lives at `mahavishnu/core/app.py:273` per the v3 audit; reuse it. Push failure MUST NOT block boot — wrap the per-adapter call in `try/except Exception` so `CircuitBreakerOpenError` and any other exception are caught and logged, never raised to the caller.

**Exit criteria:**
- Mahavishnu boot + reconfigure complete without regression.
- E2E test green for all three tests (boot push, list_adapters shape preservation, reconfigure push).
- `grep -rn "RuntimeFactsBuilder" mahavishnu/` shows exactly two callers (`list_adapters` inline tool + `report_runtime_facts` boot hook). No third code path constructs the shape.
- `audit_orphans.py` reports zero new symbols with zero callers.
- `grep -rn "from oneiric\|import oneiric" mahavishnu/core/runtime_facts.py mahavishnu/core/app.py` returns zero direct-import hits (per the public-surface contract).

#### Integration Contract (Phase 2, v3 corrected)
- **Triggered from:** (a) `MahavishnuApp.startup()` completion + (b) `oneiric.runtime.watchers.SelectionWatcher` tick observed by Mahavishnu via httpx POST poll loop. Reconfigure side uses the public Oneiric MCP HTTP endpoint, NOT direct oneiric imports. Circuit-breaker-wrapped per Task 2.4.
- **Returns to / updates:** Oneiric registry (`~/.oneiric/adapter_registry.json`) — 4 entries updated with sanitized runtime facts blocks. `list_adapters` MCP tool continues to return the legacy wire shape.
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/test_mahavishnu_pushes_runtime_to_oneiric.py -v
  cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch
  # Manual: start Mahavishnu, query Oneiric, verify runtime blocks present; flip adapters.prefect: false, verify Oneiric reflects within 30s.
  ```
- **Rollback signal:** Circuit breaker opens (5+ consecutive push failures in 60s) OR `runtime-audit` log shows `status=fail` for ≥3 consecutive pushes.
- **Observability added:** Structured log line `runtime-push component=mahavishnu adapter=<key> status=ok|fail` per push; OTel span `mahavishnu.runtime.push` around the call (parent: `mahavishnu.startup`).

---

### Phase 3: Akosha, Crackerjack, Session-Buddy Wire Up Push

**Goal:** Three remaining Bodai MCP components push their runtime facts on boot + reconfigure.

**Tasks:**
- **Task 3.1 (R2 per-component boot enumeration):**
  - **Akosha:** Insert `await oneiric_report_runtime(...)` inside `akosha/cli.py:build_server` closure (line 449-452), AFTER `create_app(mode=mode_instance)` returns, BEFORE `mcp_common.server.launch` consumes the closure. Enumerate adapters per Akosha mode (lite, standard).
  - **Session-Buddy:** Insert `await oneiric_report_runtime(...)` inside `session_buddy/cli/base.py:start_server_handler` (line 116), before `asyncio.run()`.
  - **Crackerjack (R2 HIGH RISK):** **PREREQUISITE — verify Crackerjack's MCP server is in the boot path.** Read `/Users/les/Projects/crackerjack/cli/` to identify canonical boot surface. If no MCP server is in the boot path, Phase 3 is N/A for Crackerjack — document the decision and skip.
- **Task 3.2 (R4 concurrency preflight):** Add `tests/integration/test_three_component_parallel_boot.py` — spin up a temp-rooted `OneiricAdapterRegistry`, fire `set_runtime_facts_async` from 3 concurrent tasks simulating Akosha/Crackerjack/Session-Buddy boot, assert no `JSONDecodeError` and no lost writes.
- **Task 3.3:** Per-component `runtime_facts.py` builder + boot hook + e2e test (per R2 §5 — one snippet per component).

**Exit criteria:**
- All applicable components push on boot without breaking existing tools.
- Concurrency preflight green (no JSONDecodeError under 3-component parallel push).
- Per-component e2e tests green.
- `audit_orphans.py` clean per component.

#### Integration Contract (Phase 3)
- **Triggered from:** Each component's startup completion (insertion points enumerated in Task 3.1).
- **Returns to / updates:** Oneiric registry — N entries per component.
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/akosha && uv run pytest tests/integration/test_akosha_pushes_runtime.py -v
  cd /Users/les/Projects/session-buddy && uv run pytest tests/integration/test_session_buddy_pushes_runtime.py -v
  cd /Users/les/Projects/crackerjack && uv run pytest tests/integration/test_three_component_parallel_boot.py -v  # if applicable
  ```
- **Rollback signal:** Per-component — circuit breaker opens OR 3+ consecutive push failures.
- **Observability added:** Same pattern as Phase 2.

---

## 6. Required Code Changes

### Phase 1 (Oneiric — extend in place)

- [ ] `oneiric/mcp/adapter_registry.py` — add `_SECRET_KEY_NAMES` denylist + `_sanitize_runtime_facts()` helper (Task 1.1)
- [ ] `oneiric/mcp/adapter_registry.py::AdapterRecord` — add `runtime_facts: RuntimeFacts | None = None` field (Task 1.2)
- [ ] `oneiric/mcp/adapter_registry.py::AdapterRecord.to_dict()` — thread `runtime_facts` (Task 1.2)
- [ ] `oneiric/mcp/adapter_registry.py::OneiricAdapterRegistry._save()` — add `runtime_facts` to serialized dict + `os.chmod(self._path, 0o600)` (Tasks 1.3, 1.5)
- [ ] `oneiric/mcp/adapter_registry.py::OneiricAdapterRegistry.__init__` — `os.chmod(self._root, 0o700)` on create (Task 1.5)
- [ ] `oneiric/mcp/adapter_registry.py::OneiricAdapterRegistry.set_runtime_facts_async()` — new method (Task 1.4)
- [ ] `oneiric/mcp/models.py` — add `RuntimeFacts` Pydantic model with namespaced schema (Task 1.2)
- [ ] `oneiric/mcp/server.py::_register_adapter_tools` — add `oneiric_report_runtime` tool (Task 1.6)
- [ ] `oneiric/mcp/server.py::_register_adapter_tools` — extend `oneiric_get_adapter_health` response shape (Task 1.6)
- [ ] `oneiric/mcp/server.py::oneiric_get_contract_info` — append `"report_runtime"` to `tool_groups.adapter_registry` literal (Task 1.6)
- [ ] `oneiric/mcp/server.py::_resolve_feeds` — append `"runtime_registry"` to feed tuple (Task 1.7)
- [ ] `oneiric/mcp/server.py:359-364` — update per-tool feed deferral comment (Task 1.7)
- [ ] `scripts/launch_mcp.py::_build_warm_feeds` — append `"runtime_registry"` to pre-warm loop (Task 1.7)
- [ ] `tests/integration/test_oneiric_report_runtime_e2e.py` (new file) — wiring-discipline e2e test (Task 1.8)

### Phase 2 (Mahavishnu)

- [ ] `mahavishnu/core/runtime_facts.py` (new file) — `RuntimeFactsBuilder.build_all()` extracting inline `list_adapters` body (Task 2.1)
- [ ] `mahavishnu/core/app.py::MahavishnuApp.report_runtime_facts()` — new async method + circuit breaker wrap (Tasks 2.2, 2.4)
- [ ] `mahavishnu/mcp/server_core.py::list_adapters` — replace inline body with `RuntimeFactsBuilder(self.app).build_all()` call (Task 2.1)
- [ ] `mahavishnu/mcp/server_core.py::FastMCPServer.start()` — call `report_runtime_facts()` after `_register_tools()` (Task 2.2)
- [ ] Wire Oneiric reconfigure trigger (via httpx POST poll loop on `oneiric.runtime.watchers.SelectionWatcher` ticks) → `report_runtime_facts()` (Task 2.2). Default transport: httpx loop on `http://127.0.0.1:8681/mcp` JSON-RPC; fallback only if the user explicitly approves direct oneiric import.
- [ ] `tests/integration/test_mahavishnu_pushes_runtime_to_oneiric.py` (new file) — boot + reconfigure assertions (Task 2.3)

### Phase 3 (Akosha, Crackerjack, Session-Buddy)

- [ ] `akosha/cli.py:build_server` — insert `oneiric_report_runtime` calls (Task 3.1)
- [ ] `akosha/core/runtime_facts.py` (new file) — adapter enumeration per mode (Task 3.1)
- [ ] `session_buddy/cli/base.py:start_server_handler` — insert `oneiric_report_runtime` calls (Task 3.1)
- [ ] `session_buddy/core/runtime_facts.py` (new file) — adapter enumeration (Task 3.1)
- [ ] `crackerjack/cli/` — verify MCP server boot path (Task 3.1 PREREQUISITE)
- [x] `tests/integration/test_three_component_parallel_boot.py` (new file) — concurrency preflight (Task 3.2) [oneiric ccc5525, 2026-10-12]
- [ ] Per-component e2e test files (Task 3.3)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `cd /Users/les/Projects/oneiric && uv run pytest tests/integration/test_oneiric_report_runtime_e2e.py -v` | All tests pass | CI logs |
| `cd /Users/les/Projects/oneiric && uv run pytest tests/mcp/test_server.py tests/mcp/test_auth_integration.py -v` | All tests pass (auth-fix invariants preserved) | CI logs |
| `cd /Users/les/Projects/oneiric && uv run python scripts/audit_orphans.py` | Zero new symbols with zero callers | stdout |
| `cd /Users/les/Projects/oneiric && uv run crackerjack run -p patch` | All quality gates pass | Crackerjack log |
| `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_orphans.py` | Zero new symbols with zero callers | stdout |
| `cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch` | All quality gates pass | Crackerjack log |
| `launchctl unload ~/Library/LaunchAgents/com.mcp.oneiric.plist && launchctl load ~/Library/LaunchAgents/com.mcp.oneiric.plist` | Server restarts clean | `/Users/les/.local/state/mcp/logs/oneiric.log` |
| `curl -fsS http://127.0.0.1:8681/health \| jq '.routes.runtime_registry'` | Returns 200 with runtime_registry route | curl output |
| `mcp__oneiric__oneiric_get_adapter_health(domain="adapter", key="prefect", provider="mahavishnu")` (after Phase 2) | Returns `{success, registry, runtime, health}` | Session transcript |
| `stat -f '%Lp' ~/.oneiric/adapter_registry.json` | `600` | shell output |
| `stat -f '%Lp' ~/.oneiric/` | `700` | shell output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Server-side sanitization catches too few key patterns (false negatives) | Medium | Denylist includes suffix variants (`*_key`, `*_token`, `*_secret`); URL userinfo parsed via `urllib.parse`; e2e test includes nested-dict case. |
| Sanitization drops legitimate data | Low | Denylist is key-name based; only well-known secret patterns trigger. False-positive risk is low because secret-shaped keys in runtime_facts are by definition suspicious. |
| `oneiric_report_runtime` requires auth — break loopback-friendly push | Low | Components push via direct tool call from same machine; auth required for security posture. Loopback bypass applies to READ tools only. |
| Oneiric down at component boot | Medium | Circuit breaker; push failure logged but doesn't block boot. Components remain operable. |
| JSON read-modify-write bottleneck under multi-component boot | Medium | Phase 1 ships JSON for both catalog and runtime facts (per R4 storage trade-off); future phases may move runtime to Dhara (deferred). Per-component batched push minimizes lock-acquisition count. |
| Crackerjack has no MCP server in boot path | Medium | Phase 3 prerequisite explicitly verifies; if absent, Phase 3 is N/A for Crackerjack — document and skip. |
| Reconfigure staleness if poll loop misses a tick | Low | httpx POST loop on `oneiric.runtime.watchers.SelectionWatcher` ticks; e2e test pins the reconfigure path within 30s. |
| Inter-process registry race | Low | Document as known limitation (single-process deployment). Dhara-backed multi-process is Non-Goal #4. |
| Old entries with `runtime_facts` missing | Low | REQ-RCR-005 + JSON shape is naturally additive. `_load()` default is `None`. |

## 9. Decision Rule

The plan is "done enough" when:
- Phase 1 implemented + tested + audit_orphans clean + crackerjack clean + reload-clean + verified end-to-end via `mcp__oneiric__oneiric_get_adapter_health` with sanitization assertion (secrets never reach disk).
- Mahavishnu (Phase 2) implemented + tested + e2e-clean for BOTH boot AND reconfigure paths.
- Applicable components from Phase 3 implemented + tested + concurrency preflight clean.
- `oneiric_get_adapter_health` returns non-null runtime blocks for every Bodai adapter.
- Zero secrets persisted to disk (verified by disk-stat or test fixture).

**Scope pressure cut:** if forced, drop Phase 3 to a follow-up plan and ship Phase 1+2 alone. Phase 1 is the foundation; without it the cross-component value is zero.

---

## Phase 2 v3 Revision Log (post-correction 2026-10-12)

A workflow execution on 2026-10-12 produced merge-blocking code:
- The plan's reference to `mahavishnu/mcp/server_core.py:1037-1084` was wrong; those lines contain unrelated tool decorators. The actual `list_adapters` tool is at line 1225.
- The plan's reference to `SettingsWatcher.on_change()` referenced an API that does not exist in the codebase.
- The implementation that shipped against those wrong premises reformatted `list_adapters` to return the Oneiric envelope (`{success, registry, runtime, health}`), breaking the legacy `{adapters, count, available_names}` wire contract that downstream consumers (`get_capability_result`, dashboards) depend on.
- The implementation also added a `runtime_facts_bridge.py` that imported `oneiric.core.config.LayerSettings` and `oneiric.runtime.watchers.SelectionWatcher` directly, violating the documented public-surface contract.

v3 corrections (above, in Phase 2) address all four. The corrected wire-contract preservation rule keeps `list_adapters` returning the legacy envelope; `RuntimeFactsBuilder.build_all()` is the single source of truth for both the `list_adapters` path (legacy shape) and the `report_runtime_facts` Oneiric push path (Oneiric envelope, constructed inside the push). The reconfigure trigger uses the public Oneiric MCP HTTP endpoint via httpx POST, not direct oneiric imports.

A re-execution after this revision should:
1. Overwrite `mahavishnu/core/runtime_facts.py`, `mahavishnu/core/runtime_facts_bridge.py` (delete this if no longer needed), `tests/integration/test_mahavishnu_pushes_runtime_to_oneiric.py` with the corrected implementation.
2. Revert `mahavishnu/mcp/server_core.py::list_adapters` to the legacy wire shape (preserving the existing return dict).
3. Revert `mahavishnu/core/app.py` direct-import additions; use httpx POST instead.

Reviewers from Phase 0 sign-off are NOT re-validating this v3 revision automatically — treat the wire-contract preservation rule (line 170) and the public-surface contract (line 190 exit criteria) as the new merge gates.

---

## Review Notes (Phase 0)

Five reviewers dispatched in parallel; sign-offs populate as `[x]`.

- [x] reviewer-1: `feature-dev:code-architect` — 2026-09-26 — **Approved with revisions** (namespaced schema, reconfigure trigger, Integration Contract gaps; all captured in v2 §4.5, Phase 1 Task 1.2/1.6, Phase 2 Task 2.2)
- [x] reviewer-2: `feature-dev:code-explorer` — 2026-09-26 — **Approved with revisions** (extend existing registry; single source of truth; audit_orphans; explicit decorator; Crackerjack boot path HIGH RISK; all captured in v2 §6, §7, §8, Phase 1 Task 1.6, Phase 3 Task 3.1)
- [x] reviewer-3: `mcp-integration-expert` — 2026-09-26 — **Approved with revisions** (test path; `_resolve_feeds` wiring; wire-shape change; explicit decorator; `to_dict()` extension; `get_contract_info` literal update; tool profile note; HealthFeedState race; inter-process race; all captured in v2 §4.5 REQ-RCR-011, Phase 1 Tasks 1.6/1.7/1.8, §8 Risks)
- [x] reviewer-4: `oneiric-specialist` — 2026-09-26 — **Approved with revisions** (`_save()` non-symmetric serialization BLOCKER; sanitize at Phase 1.1; URL userinfo secrets; per-tool feed deferral comment; phase 3 concurrency preflight; update `get_contract_info` literal; JSON storage trade-off documented; all captured in v2 Phase 1 Tasks 1.1/1.3/1.7, Phase 3 Task 3.2, §8 Risks)
- [x] reviewer-5: `general-purpose` (security lens) — 2026-09-26 — **Required hardening before Phase 1 ships** (REQ-RCR-003 rewrite as enforcement; chmod 0600; require auth on `oneiric_report_runtime`; caller-identity audit; URL userinfo secret handling; all captured in v2 §4.5 REQ-RCR-003/006/007/008, Phase 1 Tasks 1.1/1.5/1.6)

**Verdict:** 5/5 sign-offs with revisions incorporated. Plan status bumps `draft → active` upon user approval.
