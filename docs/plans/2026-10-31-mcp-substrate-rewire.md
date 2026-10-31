---
status: active
role: canonical
kind: plan
date: 2026-10-31
last_reviewed: 2026-10-31
superseded_by: null
topic: mcp-substrate-rewire
title: "Rewire the MCP substrate from the decommissioned service to the live owners"
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
  - id: REQ-SUB-006
    title: "The internal principal is granted only on a verified credential"
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
5. **The `mcp_calltime` substrate family — see § 4.7.** It is the same
   retired-service aftermath but a different mechanism, with a wider blast
   radius. Fixing it properly needs its own plan.

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

1. `MCPKvClient` is constructed with `resolve_mcp_url(...)`
   (`mahavishnu/mcp/lifecycle.py:160`), i.e. with the dead 8683. So even
   the client that speaks the right tool names points at nothing.
2. The KV tools were **not registered on the running server at all**.
   This turned out to be three independent layers of drift, only the
   last of which was the actual blocker:

   | Layer | Table | State before | Role |
   |---|---|---|---|
   | 1 | `REGISTRATION_MAP` (`profiles.py:213`) | present | the W0 helper's dispatch table |
   | 2 | `MAHAVISHNU_MANDATORY_GROUPS` (`profiles.py:298`) | **missing** | the W0 helper's always-on set |
   | 3 | `PROFILE_REGISTRATIONS` (`profiles.py:78-159`) | **missing** | which groups a profile registers |
   | 4 | `_OPTIONAL_TOOL_BLOCKS` (`mcp/bootstrap.py:868`) | **missing** | the dispatch table the *startup path* actually uses |

   Layers 1 and 2 belong to the W0 path (`_apply_tool_profile`), which
   `mahavishnu mcp start` does **not** take. The startup path is
   `lifecycle.py:283` → `register_profile_tools` → `_register_optional_tools`
   → `_OPTIONAL_TOOL_BLOCKS`, and that table had no KV entry at any
   tier. Fixing layers 2 and 3 alone changed nothing on the running
   server — the live `tools/list` still showed no `mahavishnu_kv_*` tool.

   The adjacent comment in `profiles.py` claimed the KV tools were
   "Always-on because the plan_index cron runs at every profile". The
   *intent* was right — the plan_index subsystem is started in the
   server lifespan at every profile (`lifecycle.py:151`, not
   profile-gated) — and the code simply never matched it.

So the plan_index lock store — the reason the KV tools exist — was dead
twice over: the tools were not registered, and the client pointed at a
dead port.

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

### 4.6 The self-call's identity must be a credential, not a name

The KV tools are gated by `@require_mcp_auth`. The gate resolves the
caller's identity from the **tool-call arguments** — `user_id` is a
declared parameter of every one of those tools — and the RBAC check then
answers "may this user id exercise this permission".

That combination means an identity expressed as a *name* is forgeable:
any client that can reach the server can put `user_id="<some user>"`
in the tool arguments and be that user. The `AuthContextMiddleware`
does not close this — it derives the same value from the same
arguments and stores it in Context state, and **no tool declares a
`ctx` parameter**, so the decorator's ctx-preference branch never
actually ran in production.

Registering a privileged service principal under a well-known name
turns that into a privilege escalation: `mahavishnu-internal` with the
`internal_service` role would be claimable by anyone who could spell it.

So the internal path must present a **verified credential**, and the
principal must be granted only on that basis:

* a random per-process token (`mahavishnu/mcp/internal_auth.py`),
  regenerated on every process start;
* sent by the client in the `Authorization` header (`MCPClient(...,
  internal=True)`);
* verified by the auth middleware with `hmac.compare_digest` before the
  principal is recorded;
* required by the gate before the principal is usable — a caller that
  supplies only the *name* is denied with `AUTH_INVALID_IDENTITY`.

The credential is only ever sent to mahavishnu's own server: `MCPClient`
also talks to Oneiric and Session-Buddy, so the token is opt-in per
call site rather than a default.

### 4.7 A second, larger instance of the same defect (found during this work)

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

### 4.8 Three more call sites spoke the retired API

Sweeping `call_tool(` for the retired tool names found three more
modules still asking for `get` / `put` / `list_keys` / `list_prefix` —
names no live server exposes:

| Module | Sites | Live? |
|---|---|---|
| `mahavishnu/core/envelopes.py` | 3 — write, read, list envelopes | yes — `get_capability_result_tool` (a registered MCP tool) and `emit_node_dispatch.py` |
| `mahavishnu/core/budget_watchdog.py` | 5 — records and the lease | latent — `app._mcp_client` is never set, so the watchdog always falls back to `_NoOpBudgetStore` |
| `mahavishnu/metrics_cli.py` | 1 — `mahavishnu metrics` key listing | yes — an operator-invoked CLI |

They were already broken before this plan: the substrate pointed at
8683, and the tool names they asked for belonged to the service on
that port. Re-pointing the URL without renaming the tools would have
left them calling tools that do not exist, so all three move to the
live `mahavishnu_kv_*` names.

`MCPClient` grows the string-shape helpers that make this a rename
rather than a rewrite: `kv_get`, `kv_list` (and the existing `put`),
each unwrapping the KV tools' `{"ok": ..., "value"/"items": ...}`
envelope.

The credential also had to be kept off the wire in one of these:
`metrics_cli` accepts a `--mcp-url` override, so the client now
refuses to attach the internal credential to a non-loopback URL
(`MCPClient(internal=True)` checks `is_loopback_url`).

## 4.9 Requirements

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
  - id: REQ-SUB-006
    title: "The internal principal is granted only on a verified credential"
```

## 5. Implementation Phases

### Phase 1: The substrate self-call

**Goal:** every substrate call reaches a server that exposes the tools it
calls.

**Tasks:**
1. `resolve_mcp_url()` returns `config.tools.mcp_server_url` instead of
   the 8683 literal, keeping the `health.dependencies["mcp"]` override.
   (REQ-SUB-001)
2. Register the KV group on **every** path that registers tool groups:
   `MAHAVISHNU_MANDATORY_GROUPS` (the W0 helper), `PROFILE_REGISTRATIONS`
   (MINIMAL, hence STANDARD and FULL), and `_OPTIONAL_TOOL_BLOCKS` (the
   dispatch table the startup path actually uses). The third is the one
   that was missing on the running server. (REQ-SUB-002)
3. `MCPStateBackend` calls `mahavishnu_kv_put` / `_get` / `_delete` /
   `_list`, JSON-encoding dict values on write and decoding them on read
   so `recover_*` still receives dicts. (REQ-SUB-003)
4. `oneiric_client._default_mcp_base_url` resolves to mahavishnu's own
   server; `self_improvement_tools`' three literal fallbacks are removed.
   (REQ-SUB-004)
5. The self-call presents a per-process credential rather than a
   principal name: `mahavishnu/mcp/internal_auth.py` issues the token,
   `MCPClient(..., internal=True)` sends it, the auth middleware
   verifies it, and the gate grants the internal principal only on that
   basis. (REQ-SUB-006)

**Exit criteria:** the live server's `tools/list` includes the four
`mahavishnu_kv_*` tools; the server's own plan_index cycle writes and
reads the lock store (auth audit: `result: allowed`); a write/read
round-trip through `MCPStateBackend` returns the original dict;
`grep -rn 8683 mahavishnu/mahavishnu/` returns nothing outside archive
material.

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

### Phase 3: The remaining retired-API call sites

**Goal:** no call site asks a live server for a tool that does not exist.

**Tasks:**
1. `MCPClient` gains `kv_get` / `kv_list`, unwrapping the KV tools'
   envelopes. (REQ-SUB-003)
2. `envelopes.py`, `budget_watchdog.py` and `metrics_cli.py` move from
   the bare `get` / `put` / `list_keys` / `list_prefix` names to the
   live `mahavishnu_kv_*` tools. (REQ-SUB-003)
3. `MCPClient(internal=True)` refuses to attach the internal credential
   to a non-loopback URL, so a `--mcp-url` override cannot leak it.
   (REQ-SUB-006)

**Exit criteria:** `grep -rn "call_tool(\"get\"\|call_tool(\"put\"\|call_tool(\"list_"` over
`mahavishnu/` returns nothing; the credential is absent from any
non-loopback request.

#### Integration Contract

- **Triggered from:** `get_capability_result_tool` (a registered MCP
  tool) and `emit_node_dispatch.py` for the envelope path;
  `mahavishnu metrics` for the CLI path; the budget watchdog's
  `MCPBudgetStore` once it is wired.
- **Returns to / updates:** the process-local KV store in
  `mahavishnu/mcp/tools/kv_tools.py` (`_kv_store`), keyed
  `envelopes/<trace_id>/<envelope_id>` and `mahavishni://budgets/...`.
- **Demonstrable by:** `pytest tests/unit/test_envelopes.py
  tests/unit/test_budget_watchdog_methods.py` → green; the CLI's key
  listing returns the stored records.
- **Rollback signal:** the envelope read path raises
  `RESOURCE_NOT_FOUND` where it used to return a value — visible as
  `get_capability_result` losing its results.
- **Observability added:** none new; the KV tools' auth audit already
  records every read and write with the caller's identity.

## 6. Verification

1. `git grep -n "8683" -- mahavishnu/mahavishnu/` → no live-code hits.
2. Live `tools/list` on 8680 includes `mahavishnu_kv_get/put/list/delete`
   (verified: 160 tools, up from 156).
3. The server's own plan_index cycle writes and reads the lock store —
   auth audit shows `caller_id: mahavishnu-internal`, `result: allowed`.
4. An external client that supplies `user_id="mahavishnu-internal"`
   without the credential is denied — auth audit shows `result: denied`,
   `reason: "Internal principal requires a verified credential"`.
5. `grep -rn 'call_tool("get"\|call_tool("put"\|call_tool("list_' -- mahavishnu/` → no
   retired tool names remain.
6. `pytest tests/unit/test_mcp_kv_client.py tests/unit/test_state_backends.py
   tests/unit/test_self_improvement_tools.py
   tests/unit/test_mcp_internal_auth.py tests/unit/test_envelopes.py` → green.
7. `python scripts/audit_orphans.py` → no new orphans.
8. `crackerjack run -v -f` → gate passes.

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
  `READ/WRITE_ECOSYSTEM_STATE`. The self-call presents the per-process
  credential from `internal_auth.py`; the gate refuses the principal
  without it, so a misconfigured call site degrades to a denial rather
  than an escalation.
- **The credential is a bearer secret on loopback.** It is generated per
  process and never leaves the machine, but it does travel over the
  server's own HTTP listener. A local attacker who can read loopback
  traffic could capture it — such an attacker could equally import the
  module. mTLS or a signed service JWT would be stronger, at the cost of
  a certificate/JWT pipeline this codebase does not have today.
- **Encoding change.** `MCPStateBackend` values become JSON strings on
  the wire. Any other reader of the same keys would need the same decode.

## 8. Status

Phase 1, Phase 2 and Phase 3 are implemented. Verified live on the running server
on 2026-10-31: the four KV tools are registered (160 tools total), the
server's own plan_index cycle uses them successfully, and an external
client claiming the internal principal's name is denied.
