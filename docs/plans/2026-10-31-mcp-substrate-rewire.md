---
status: active
role: canonical
kind: plan
date: 2026-10-31
last_reviewed: 2026-10-31
superseded_by: null
topic: mcp-substrate-rewire
title: "Rewire the MCP substrate from the decommissioned service to the live owners"
---

# Rewire the MCP substrate from the decommissioned service to the live owners

## 1. Outcome

Mahavishnu's substrate calls reach live servers again. Concretely: the
durable-state and KV paths write to and read from a server that exposes
those tools, and the analytics paths either read a metric that a live
component actually writes or report plainly that no writer exists.

Success signal: with the fleet up, `mahavishnu_kv_put` / `mahavishnu_kv_get`
are listed by the live server's `tools/list`, a `workflow/v1/...` write is
readable back, and `grep -rn "8683" mahavishnu/` returns only the
historical mentions this plan retires.

## 2. Goals

1. Remove every default and fallback that points at the decommissioned
   service's port.
2. Make mahavishnu's own KV tools reachable at every tool profile tier.
3. Point the durable-state backend at the tools that actually exist.
4. Route the one analytics metric that has a live writer to the component
   that writes it, and make the metrics with no writer say so.

## 3. Non-Goals

1. Building a new metrics writer. `git_velocity`, `repository_health` and
   `improvement-records` have no writer anywhere in the fleet; this plan
   makes that visible rather than inventing a producer.
2. Registering Crackerjack's `get_repository_health_dashboard` as an MCP
   tool. It is a module-level function today, not a registered tool.
3. Changing the `mcp_state` feature semantics (degraded-boot mode, the
   inline circuit breaker, fire-and-forget writes).
4. Moving `ttl` enforcement into the KV store. The KV tools accept `ttl`
   and treat it as a no-op; this plan does not add eviction.
5. **The `mcp_calltime` substrate family — see § 4.6.** It is the same
   retired-service aftermath but a different mechanism, with a wider blast
   radius. Fixing it properly needs its own plan.

### 4.6 A second, larger instance of the same defect (found during this work)

`mahavishnu/core/_mcp_substrate_compat.py` resolves the substrate lazily
with `importlib.import_module("mcp")` and then reads `mcp.<name>`. That
resolved the **retired storage service's client package**, which is where
`put` / `get` / `list` / `delete` / `query_time_series` came from. After
the service was removed, the name `mcp` resolves to the **MCP Python
SDK** — which has none of those attributes.

Verified in-process:

```
mcp_calltime('put')              -> None
mcp_calltime('get')              -> None
mcp_calltime('list')             -> None
mcp_calltime('delete')           -> None
mcp_calltime('query_time_series')-> None
```

So **every** call site of that family silently no-ops — the substrate
gate sees `None` and takes the "substrate not bound" branch. The
affected sites:

| Module | Sites |
|---|---|
| `mahavishnu/core/ecosystem_state.py` | 8 — the service registry and the event log |
| `mahavishnu/core/workflow/outcome_writer.py` | 1 — workflow outcomes |
| `mahavishnu/core/approval/decision_writer.py` | 1 — approval decisions |
| `mahavishnu/mcp/tools/workflow_tools.py` | 1 — reading workflow results |
| `mahavishnu/cli/approval_cli.py` | 1 — listing approvals |
| `mahavishnu/webhooks/receiver.py` | 1 — webhook persistence |
| `mahavishnu/webhooks/replay.py` | 1 — webhook replay |

This plan does **not** fix it. Doing so properly means giving the
substrate a sync `put` / async `get` / `list` surface with the retired
service's call contract (the callers mix both — `put` is called
synchronously, `get` is awaited), moving the process-local store so the
in-process callers and the MCP tools share one implementation, and
rewiring all fourteen sites. That is a separate plan with its own
integration contract.

## 4. Current Findings

### 4.1 The port default and the API it speaks are both gone

`mahavishnu/core/bootstrap.py:889` `resolve_mcp_url()` returns the literal
`http://localhost:8683/mcp` whenever `config.health.dependencies` has no
`"mcp"` key. `settings/mahavishnu.yaml` defines `session_buddy`, `akosha`
and others under `health.dependencies` but **no `mcp` key**, so the literal
is what every caller gets.

Nothing listens on 8683 (`curl http://localhost:8683/health` → connection
refused; 8678/8680/8681/8682 all answer 200).

Worse, the literal is not merely a stale port. The tools it reaches for
were the decommissioned service's API:

| Call site | Tool it calls | Live provider? |
|---|---|---|
| `mahavishnu/core/mcp_adapter.py:90` | `put` | none |
| `mahavishnu/core/mcp_adapter.py:119` | `query_time_series` | none |
| `mahavishnu/core/mcp_adapter.py:136` | `aggregate_patterns` | none |
| `mahavishnu/core/state_backends/mcp.py:181` | `put` | none |
| `mahavishnu/core/state_backends/mcp.py:316` | `get` | none |
| `mahavishnu/core/state_backends/mcp.py:331` | `delete` | none |

Verified against the live servers' `tools/list`: Oneiric (8681) exposes 18
`oneiric_*` tools, Mahavishnu (8680) exposes 157, Crackerjack (8676)
exposes 53, Akosha (8682) exposes 39 — **none exposes a bare `put`, `get`,
`delete`, `query_time_series` or `aggregate_patterns`**.

### 4.2 The re-homing was already designed; only the wiring is missing

`mahavishnu/mcp/tools/kv_tools.py` documents the intended end state:
the four KV tools live on **mahavishnu's own MCP server**, backed by a
process-local thread-safe dict, and "`MCPStateBackend` / `MCPKvClient`
(which are self-calls)". `mahavishnu/core/state_backends/mcp_kv.py` is
the client that already speaks the new tool names
(`mahavishnu_kv_get` / `_put` / `_list` / `_delete`).

But:

1. `_register_kv_tools` is in `REGISTRATION_MAP` (`profiles.py:213`) and
   **not** in `MAHAVISHNU_MANDATORY_GROUPS` (`profiles.py:298`, 9
   entries). The adjacent comment says "Always-on because the plan_index
   cron runs at every profile" — the code does not match the comment. The
   live server's `tools/list` confirms it: no `mahavishnu_kv_*` tool is
   exposed.
2. `MCPKvClient` is constructed with `resolve_mcp_url(...)`
   (`mahavishnu/mcp/lifecycle.py:160`), i.e. with the dead 8683. So even
   the client that speaks the right tool names points at nothing.

So the plan_index lock store — the reason the KV tools exist — is dead
twice over: the tools are not registered, and the client cannot reach
them.

### 4.3 Three more dead-port fallbacks

`mahavishnu/mcp/tools/self_improvement_tools.py` hardcodes
`"http://localhost:8683"` as the fallback for `settings.mcp_url` at
lines 477, 529 and 617 — three sites that never consult the configured
URL.

### 4.4 The analytics metrics have no writer at all

The first survey suggested `fix-failures` still had a writer. A deeper
check showed otherwise:

| Metric | Writer | Reader | Disposition |
|---|---|---|---|
| `fix-failures` | **none** — `crackerjack/crackerjack/services/failure_recorder.py:138` calls `akosha.analyze_changepoints(metric_name="fix-failures")`, which is a *reader*, and Akosha **removed that tool on 2026-09-26** (`akosha/akosha/mcp/tools/akosha_tools.py:59`, `:946`). The call therefore raises and is swallowed. | `self_improvement_tools.py:534` | report "no writer" |
| `improvement-records` | **none** | `self_improvement_tools.py:622` | report "no writer" |
| `git_velocity` | **none** | `git_analytics.py:69` | report "no writer" |
| `repository_health` | **none** | `git_analytics.py:136` | report "no writer" |
| `aggregate_patterns` | **none** | `git_analytics.py:225`, `self_improvement_tools.py:481` | report "no writer" |

No live server exposes a metric-writing tool either: Akosha's
`tools/list` carries `add_eval_metric` but not `add_metric`, and the
metrics that were written went through the retired service's own
`record_time_series`.

So there is **no metric series in the fleet with both a writer and a
reader**. The analytics half cannot be "re-pointed" — there is nothing
to point at. The honest treatment is to say so: a query raises
`NoAnalyticsWriterError` naming the series, instead of returning an
empty list that reads as "the series exists but has no data yet".

Restoring the analytics features is a separate piece of work: it needs a
writer (a component that records git velocity, repository health and
failure series) before a reader is meaningful.

### 4.5 The self-call target is already configured

`config.tools.mcp_server_url` defaults to `http://localhost:8680/mcp` —
mahavishnu's own MCP server, and the one that answers on this host.
`settings/mahavishnu.yaml:141` already sets `akosha_url:
"http://localhost:8682/mcp"` for the analytics provider.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-SUB-001
    title: "Substrate URL resolves to mahavishnu's own MCP server"
  - id: REQ-SUB-002
    title: "KV tools are registered at every tool profile tier"
  - id: REQ-SUB-003
    title: "Durable state reads and writes through the live KV tools"
  - id: REQ-SUB-004
    title: "No default or fallback points at the decommissioned port"
  - id: REQ-SUB-005
    title: "Analytics with no writer report the absence of a source"
```

## 5. Implementation Phases

### Phase 1: The substrate self-call

**Goal:** every substrate call reaches a server that exposes the tools it
calls.

**Tasks:**
1. `resolve_mcp_url()` returns `config.tools.mcp_server_url` instead of
   the 8683 literal, keeping the `health.dependencies["mcp"]` override.
   (REQ-SUB-001)
2. Add `_register_kv_tools` to `MAHAVISHNU_MANDATORY_GROUPS`.
   (REQ-SUB-002)
3. `MCPStateBackend` calls `mahavishnu_kv_put` / `_get` / `_delete` /
   `_list`, JSON-encoding dict values on write and decoding them on read
   so `recover_*` still receives dicts. (REQ-SUB-003)
4. `oneiric_client._default_mcp_base_url` resolves to mahavishnu's own
   server; `self_improvement_tools`' three literal fallbacks are removed.
   (REQ-SUB-004)

**Exit criteria:** the live server's `tools/list` includes the four
`mahavishnu_kv_*` tools; a write/read round-trip through
`MCPStateBackend` returns the original dict; `grep -rn 8683
mahavishnu/mahavishnu/` returns nothing outside archive material.

#### Integration Contract

- **Triggered from:** `MahavishnuApp._resolve_mcp_url()`
  (`mahavishnu/core/app.py:714`) during app construction;
  `mahavishnu/mcp/lifecycle.py:160` for the plan_index KV client;
  `_init_mcp_state` (`mahavishnu/core/bootstrap.py:710`) for the durable
  state backend.
- **Returns to / updates:** the process-local KV store in
  `mahavishnu/mcp/tools/kv_tools.py` (`_kv_store`), keyed
  `workflow/v1/{id}`, `pool/v1/{id}`, `routing/v1/{class}/{ts}`,
  `approval/v1/{id}`, `plan-index/...`.
- **Demonstrable by:** `pytest tests/unit/test_mcp_kv_client.py
  tests/unit/test_state_backends.py` green, plus a live
  `tools/list` on 8680 showing `mahavishnu_kv_get`.
- **Rollback signal:** the state backend's circuit breaker opens
  (3 consecutive failures) or `/health` reports the substrate feed
  degraded.
- **Observability added:** the state backend's existing
  "MCP state backend recovered" / failure debug logs now describe a
  reachable endpoint.

### Phase 2: The analytics paths

**Goal:** analytics either read a live writer's data or say that no
writer exists.

**Tasks:**
1. `fix-failures`, `improvement-records`, `git_velocity`,
   `repository_health` and `aggregate_patterns` raise
   `NoAnalyticsWriterError` naming the series, rather than returning an
   empty list that reads as "no data". (REQ-SUB-005)

**Exit criteria:** the affected tool tests assert the new error
shapes; no analytics call site references a bare time-series tool name.

#### Integration Contract

- **Triggered from:** `mahavishnu/mcp/tools/self_improvement_tools.py`
  (pattern listing, fix-failure count, improvement status) and
  `mahavishnu/mcp/tools/git_analytics.py` (velocity dashboard,
  repository health).
- **Returns to / updates:** the tool result dictionaries returned to the
  MCP caller — no durable state is written.
- **Demonstrable by:** `pytest tests/unit/test_self_improvement_tools.py
  tests/unit/test_git_analytics.py` green.
- **Rollback signal:** the tools report an explicit error instead of
  partial data; callers already handle the error envelope.
- **Observability added:** the "no writer" result names the metric and
  the component that would need to write it.

## 6. Verification

1. `git grep -n "8683" -- mahavishnu/mahavishnu/` → no live-code hits.
2. Live `tools/list` on 8680 includes `mahavishnu_kv_get/put/list/delete`.
3. `pytest tests/unit/test_mcp_kv_client.py tests/unit/test_state_backends.py
   tests/unit/test_self_improvement_tools.py` → green.
4. `python scripts/audit_orphans.py` → no new orphans.
5. `crackerjack run -v -f` → gate passes.

## 7. Risks

- **Self-call over HTTP.** The state backend now calls mahavishnu's own
  MCP server over HTTP from inside that server. This is the design the
  KV tools already document and `plan_index` already uses
  (`lifecycle.py:161`), so it is not a new pattern — but it does mean the
  substrate depends on the server's own listener being bound. The
  lifespan already defers the plan_index init to a background task for
  exactly this reason; the durable-state backend has the same constraint
  and its degraded-boot mode covers it.
- **Auth on the self-call.** `mahavishnu_kv_*` require
  `READ/WRITE_ECOSYSTEM_STATE`. The existing `MCPKvClient` path already
  authenticates; `MCPStateBackend` must use the same credential.
- **Encoding change.** `MCPStateBackend` values become JSON strings on
  the wire. Any other reader of the same keys would need the same decode.

## 8. Status

Phase 1 and Phase 2 are implemented in the commit that ships this plan.
