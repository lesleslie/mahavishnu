---
status: draft
role: implementation
topic: dhara-mcp-decomposition
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on:
  - docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md
  - docs/adr/017-oneiric-shared-persistence-substrate.md
related:
  - docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md
  - docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md
  - docs/plans/2026-07-26-mahavishnu-acp-server.md
  - docs/superpowers/specs/2026-04-27-bodai-auth-standardization-design.md
  - docs/superpowers/specs/2026-05-24-dhara-serverless-design.md
---

# Dhara MCP Decomposition — Design Specification

**Status:** Draft — pending user review
**Date:** 2026-09-14
**Author:** Claude Code + les

## 1. Problem

The Dhara package ships two unrelated products bundled in one repo:

1. **The Durus object database engine** (`dhara/core/`, `dhara/storage/`, `dhara/serialize/`, `dhara/collections/`, `dhara/server/`, `dhara/_persistent.c`) — a modernized continuation of CNRI's Durus, BSD-3-licensed, designed as a standalone library.

2. **The Bodai MCP catalog server** (`dhara/mcp/` — 7,580 LOC across 8 tool groups + auth + middleware + substrate routes) — a FastMCP surface that Bodai's other components consume for adapter state queries, KV/time-series, ecosystem events, agent/skill catalogs, OTel trace queries, and SQL proxy.

Bundling these obscures both products and creates three concrete problems:

- **Footprint.** Dhara's MCP server adds 7,580 LOC of MCP-specific code, plus ~10 dependencies (FastMCP, mcp-common, uvicorn, ipython, rich, cryptography, msgspec, schedule, zstandard, aiosqlite) to a package whose actual engine doesn't need any of them.
- **Identity confusion.** The Durus engine is a general-purpose persistent-object library that anyone could use outside Bodai. The MCP server is Bodai-specific. A new contributor reading the Dhara `CLAUDE.md` sees "modern persistent object system" in the project overview, then `dhara/mcp/` with `dhara_store_adapter`, `dhara_upsert_service`, and `dhara_list_agents` tools — and reasonably wonders which product is which.
- **Auth/middleware duplication.** Every Bodai MCP server has its own auth implementation. mcp-common already ships `mcp_common.auth.*` (1,570 LOC, 14 files) with JWT, RBAC, middleware, audit, identity, and ASGI integration. Dhara's `dhara/mcp/auth.py` (786 LOC) + `dhara/mcp/fastmcp_auth.py` (99 LOC) + `dhara/mcp/middleware.py` (440 LOC) reimplement this. The active plan's Phase 4 + Phase 6 + the active spec `2026-04-27-bodai-auth-standardization-design.md` already converged on mcp-common as the canonical auth surface; Dhara is the only consumer still on its fork.

This design addresses all three by **decomposing the MCP surface into the components where each tool group naturally belongs**, restoring the **Oneiric MCP server** (the original Bodai design, briefly consolidated into Dhara), and retiring Dhara as a Bodai component. **The Durus engine stays in Dhara.**

## 2. Goals

1. **Dhara becomes a pure library.** Engine code (Durus) survives; MCP code is deleted. Dhara's CLI keeps `dhara db start|client|pack` for the engine; drops `dhara mcp start|stop|status|health`. Pyproject slims to engine-only deps.
2. **Oneiric MCP server is restored.** `oneiric/mcp/server_core.py` ships with the 7 `adapter_registry` tools (`store_adapter`, `get_contract_info`, `get_adapter`, `list_adapters`, `list_adapter_versions`, `validate_adapter`, `get_adapter_health`). This restores the original Bodai design and is ADR-013's "Option C — canonical surface lives where adapters live."
3. **All 7,580 LOC of Dhara MCP code finds a new home.** No orphan code. Each tool group moves to a Bodai component where the domain naturally lives.
4. **Auth consolidation completes.** Every Bodai MCP server uses `mcp_common.auth.*`. Dhara's auth fork is deleted. The `2026-04-27-bodai-auth-standardization-design.md` spec's pending migrations for Dhara close out.
5. **No breaking changes to the Durus engine.** Existing users of `from dhara import Connection, Persistent, PersistentDict` continue to work unchanged. `dhara.connection`, `dhara.persistent_dict`, etc. legacy aliases still resolve.
6. **Dhara v1.0.0 signal.** With the MCP server gone and the engine proven standalone, Dhara's version stamp moves to 1.0.0 to signal "production-ready standalone library."

## 3. Non-Goals

- **Extracting the Durus engine into a separate package** (e.g. `durus-ng`). The engine stays in Dhara; the name Dhara was chosen as a play on Durus to preserve the lineage.
- **Removing the C extension** (`dhara/_persistent.c`). The C extension is the engine's hot path. Pure-Python fallback on PyPy remains.
- **Changes to `dhara.connection` / `dhara.persistent_dict` legacy aliases.** These stay.
- **Multi-region or horizontal scaling of Dhara's storage server.** Out of scope (covered by `2026-05-24-dhara-serverless-design.md`).
- **Replacing the Durus pickle format.** The object-graph serialization stays.
- **Per-tool granular permissions beyond mcp-common's existing RBAC** (READ/WRITE/DELETE/ADMIN). Out of scope.
- **OAuth / mTLS / cert-based auth.** Out of scope; covered by future auth enhancement plans.

## 4. Architecture

### 4.1 Component mapping

| Component | Before | After | Tools gained |
|-----------|--------|-------|--------------|
| **Dhara** | Engine + 7,580 LOC MCP server | Engine only | — (loses all `mcp__dhara__*` tools) |
| **Oneiric** | Library + 54 adapters | Library + 54 adapters + MCP server | 7 (adapter_registry) |
| **Akosha** | Seer/intelligence (32 tools) | Seer + trace query | 1 (`query_local_traces`) |
| **Mahavishnu** | Orchestrator (141 tools) | Orchestrator + ecosystem state | 5 (ecosystem_state group) |
| **Crackerjack** | Inspector (47 tools) | Inspector + signed content registry | 5 (skill_registry + agent_registry + signer_feed) |
| **mcp-common** | Auth, dispatch, profiles | Unchanged surface; absorbed Dhara's auth fork | — (now sole auth source) |
| **Session-Buddy** | Memory MCP (49 tools) | Unchanged | — (Phase 6 may absorb `kv_time_series`; deferred) |

### 4.2 Tool-by-tool destination

| Dhara group (current) | Tool name (current) | New tool name | New home | Notes |
|-----------------------|---------------------|---------------|----------|-------|
| `kv_time_series` | `dhara_put` | (Oneiric cache adapter, no MCP tool) | Oneiric | Wrapped as `oneiric.adapters.cache.persistent_kv.put` (Phase 6). |
| `kv_time_series` | `dhara_get` | (Oneiric cache adapter, no MCP tool) | Oneiric | Wrapped as `oneiric.adapters.cache.persistent_kv.get` (Phase 6). |
| `kv_time_series` | `dhara_list_prefix` | (Oneiric cache adapter, no MCP tool) | Oneiric | Wrapped as `oneiric.adapters.cache.persistent_kv.list_prefix` (Phase 6). |
| `kv_time_series` | `dhara_record_time_series` | (Oneiric cache adapter, no MCP tool) | Oneiric | Wrapped as `oneiric.adapters.cache.persistent_kv.record_time_series` (Phase 6). |
| `kv_time_series` | `dhara_query_time_series` | (Oneiric cache adapter, no MCP tool) | Oneiric | Wrapped as `oneiric.adapters.cache.persistent_kv.query_time_series` (Phase 6). |
| `kv_time_series` | `dhara_aggregate_patterns` | (deleted) | — | Dropped along with other kv_time_series tools (Phase 6). **Correction:** the spec's earlier draft noted an overlap with `akosha_aggregate_patterns`; that claim was incorrect (no such tool exists in Akosha). The tool is deleted with no replacement; consumers needing aggregate-patterns queries use the Oneiric cache adapter directly via the resolver, not via MCP. |
| `adapter_registry` | `dhara_store_adapter` | `oneiric_store_adapter` | Oneiric | |
| `adapter_registry` | `dhara_get_contract_info` | `oneiric_get_contract_info` | Oneiric | |
| `adapter_registry` | `dhara_get_adapter` | `oneiric_get_adapter` | Oneiric | |
| `adapter_registry` | `dhara_list_adapters` | `oneiric_list_adapters` | Oneiric | |
| `adapter_registry` | `dhara_list_adapter_versions` | `oneiric_list_adapter_versions` | Oneiric | |
| `adapter_registry` | `dhara_validate_adapter` | `oneiric_validate_adapter` | Oneiric | |
| `adapter_registry` | `dhara_get_adapter_health` | `oneiric_get_adapter_health` | Oneiric | |
| `ecosystem_state` | `dhara_upsert_service` | `mahavishnu_upsert_service` | Mahavishnu | |
| `ecosystem_state` | `dhara_get_service` | `mahavishnu_get_service` | Mahavishnu | |
| `ecosystem_state` | `dhara_list_services` | `mahavishnu_list_services` | Mahavishnu | |
| `ecosystem_state` | `dhara_record_event` | `mahavishnu_record_event` | Mahavishnu | |
| `ecosystem_state` | `dhara_list_events` | `mahavishnu_list_events` | Mahavishnu | |
| `sql_proxy` | `dhara_sql_execute` | — (drop) | — | **Phase 6: drop.** The active plan's Phase 6 already strips 22 of 32 Akosha tools; sql_proxy fits the same "off-the-shelf or deleted" pattern. |
| `sql_proxy` | `dhara_sql_query` | — (drop) | — | Same. |
| `agent_registry` | `dhara_list_agents` | `crackerjack_list_agents` | Crackerjack | Phase 1.5 of the active ACP plan routes through Crackerjack. |
| `agent_registry` | `dhara_get_agent` | `crackerjack_get_agent` | Crackerjack | |
| `skill_registry` | `dhara_list_skills` | `crackerjack_list_skills` | Crackerjack | |
| `skill_registry` | `dhara_get_skill` | `crackerjack_get_skill` | Crackerjack | |
| `otel_traces` | `dhara_query_local_traces` | `akosha_query_local_traces_fitness` | Akosha | Drop Akosha's existing general-purpose `akosha_query_local_traces` (Phase 5). Dhara's `akosha>=0.17.1` dep is removed (not moved — circular install hazard). |
| `signer_feed` | (cross-cutting) | — | Crackerjack (private) | ed25519 signer, shared by `agent_registry` + `skill_registry`. |
| `substrate_routes` (HTTP) | (settings/context/progress) | — | Oneiric HTTP API | Move to Oneiric, exposed alongside the new MCP server. |
| `auth.py` + `fastmcp_auth.py` + `middleware.py` | — | — | mcp-common (already there) | **Delete Dhara's forks.** |
| `server_core.py` (DharaMCPServer) | — | — | Oneiric (new `oneiric/mcp/server_core.py`) | Restore Oneiric MCP server. |
| `profiles.py` (Dhara-specific tool profile) | — | — | Each consumer | Each new home has its own profile. |

### 4.3 Auth consolidation

Every Bodai MCP server's auth module collapses to ~20 lines: re-export from `mcp_common.auth.*` with a thin service-specific adapter. The pattern is established by `2026-04-27-bodai-auth-standardization-design.md` §5.2.

```python
# After migration — Dhara no longer has an auth.py at all (no MCP server).
# Akosha's auth.py after migration:
from mcp_common.auth import (
    AuthConfig,
    require_auth,
    Permission,
    create_service_token,
    verify_token,
    # ...
)
# Plus Akosha-specific identity claims if any (none currently).
```

This completes the 5-way auth fork consolidation. The `2026-04-27-bodai-auth-standardization-design.md` spec's "Phase 2 engine surface expansion" unblocker closes.

### 4.4 Dhara pyproject.toml slim-down

After decomposition, Dhara's pyproject.toml drops these 10 dependencies. `oneiric` is preserved (it's the configuration substrate — every Bodai component uses Oneiric for config).

```diff
 dependencies = [
+    "oneiric>=0.20",  # PRESERVED — configuration substrate, used by engine's config loader
-    "fastmcp>=3.4.0,<5",        # MCP-server-only
-    "mcp-common>=0.26.0,<0.27.0",  # MCP-server-only
-    "uvicorn>=0.48.0",         # MCP-server-only (ASGI host for FastMCP)
-    "ipython>=9.14.0",         # MCP-server-only (admin shell)
-    "rich>=15.0.0",            # MCP-server-only (pretty tables)
-    "cryptography>=50.0.0",    # signer_feed (moves to Crackerjack Phase 4)
-    "schedule>=1.2.2",         # MCP-server-only (background tasks)
-    "zstandard>=0.25.0",       # MCP-server-only (compression)
-    "aiosqlite>=0.22.1",       # VERIFY: only used by MCP layer? (see Phase 8 task 2)
+    # Engine-only deps below this line; verify aiosqlite is MCP-only before removing
 ]
```

**Verification gate (Phase 8 task 2):** Confirm `aiosqlite` is used only by `dhara/mcp/` (MCP server), not by `dhara/core/`, `dhara/storage/`, `dhara/collections/` (engine). If engine uses it, keep it. The active plan's Phase 4 (`REQ-DHARA-STORAGE`) uses async storage backends that may pull `aiosqlite` — verify case-by-case.

The `[project.entry-points."bodai.apps"]` block for `dhara.cli:app` remains — Dhara is still a Bodai app, just not an MCP server. The role tag may shift from `mcp_server` to `engine` in `BODAI_REPO_REGISTRY.md` (Phase 8 task 13).

### 4.5 What stays in Dhara (the engine surface)

After decomposition, `dhara/` contains:

```
dhara/
├── __init__.py             # Public API: Connection, Persistent, PersistentDict, PersistentList, PersistentSet, BTree, BNode
├── __main__.py             # CLI entry
├── _persistent.c           # C extension (hot path)
├── audit/                  # Engine audit hooks
├── backup/                 # Backup/restore
├── cli.py                  # CLI: dhara db start|client|pack (NO dhara mcp)
├── collections/            # PersistentDict, PersistentList, PersistentSet, BTree, BNode
├── config/                 # Oneiric config integration
├── core/                   # Connection, Persistent, PersistentBase
├── error.py                # Error hierarchy
├── events/                 # Engine events
├── lock/                   # Lock backends (in_memory, sql, postgres, protocol, routes)
├── logging/                # Structured logging
├── migrations/             # Engine migrations
├── modes/                  # Operational modes (lite, standard, base)
├── monitoring/             # Engine monitoring
├── schema/                 # Schema versioning
├── security/               # Engine security (oneiric_secrets)
├── serialize/              # msgspec, msgpack, fallback
├── server/                 # StorageServer (TCP / Unix domain socket)
└── shell/                  # Admin shell
```

`dhara/mcp/`, `dhara/mcp/tools/`, `dhara/mcp/skills_signer/` (if any) — **all deleted**.

`dhara/skills_signer/` is a recent addition (Phase 1.5 of the active ACP plan). It belongs with the new `crackerjack_list_skills` + `crackerjack_get_skill` tools in Crackerjack. **Move to Crackerjack in Phase 4** (not "delete"), so the signing infrastructure lives where the consumer is.

### 4.6 Oneiric MCP server shape

The restored Oneiric MCP server follows the pattern already established by Dhara's MCP server (the only working precedent in the Bodai ecosystem). **Note:** `oneiric/core/cli.py:MCPServerCLIFactory._start_server()` is currently broken — it calls `asyncio.run(server.startup())` then enters a `time.sleep(1)` loop without ever calling a transport. **The spec does NOT use this factory as-is.** The Oneiric server follows Dhara's proven pattern instead:

```python
# oneiric/mcp/server_core.py
from __future__ import annotations

import asyncio
from fastmcp import FastMCP
from mcp_common.auth.middleware import AuthMiddleware
from mcp_common.auth import require_auth, Permission
from oneiric.adapters.bootstrap import builtin_adapter_metadata, register_builtin_adapters
from oneiric.runtime.mcp_health import HealthMonitor, ComponentHealth, HealthStatus


class OneiricMCPServer:
    def __init__(self, config):
        self.config = config
        self.server = FastMCP(name="Oneiric Registry", version=__version__)
        self._register_tools()
        self._register_health_route()

    def _register_tools(self):
        # 7 adapter_registry tools ported from dhara/mcp/adapter_tools.py
        # Each uses @server.tool(name="...", auth=require_auth(Permission.READ/WRITE))
        # ...

    def _register_health_route(self):
        # /health endpoint backed by HealthMonitor aggregating 7 tool feeds
        # Returns 503 if any feed reports degraded (per mcp-backend-wiring-discipline.md)
        # Each feed exposes: feed.entities_count, feed.last_updated_timestamp,
        #                    feed.errors_total, feed.cycles_total
        # ...

    async def run_http_async(self, host: str = "127.0.0.1", port: int = 8683):
        """Bind and serve HTTP. This is what `oneiric mcp start` invokes."""
        await self._init_async_state()
        await self.server.run_http_async(
            host=host,
            port=port,
            uvicorn_config={"timeout_graceful_shutdown": 30},
        )

    async def stop(self):
        # Graceful shutdown of uvicorn server
        # ...


async def run_server(config=None):
    """Entry point for `oneiric mcp start`."""
    config = config or OneiricMCPConfig.from_env()
    server = OneiricMCPServer(config)
    await server.run_http_async(
        host=config.host,
        port=config.port,
    )
```

**Why we don't use `MCPServerCLIFactory` directly:** `grep -rn "MCPServerCLIFactory" oneiric/` returns zero call sites and zero subclasses. The factory is dead code (the second-pass oneiric-specialist review flagged this). The actual Oneiric CLI uses `OneiricCLI(OneiricCLIBase)` with `app.add_typer(manifest_app, name="manifest")` / `secrets_app` / `event_app` / `workflow_app` (per `oneiric/cli/__init__.py:271-278`). The new MCP server uses this **Typer sub-app pattern** instead: Phase 1 task 2 adds `app.add_typer(mcp_app, name="mcp")` to `oneiric/cli/__init__.py:271-278` (where `mcp_app` is a `typer.Typer(help="Oneiric MCP server lifecycle.")` defined in `oneiric/mcp/server_core.py`). The unused `MCPServerCLIFactory` (lines 31-162 of `oneiric/core/cli.py`) is left as historical artifact; cleanup is deferred to a follow-up refactor.

**Port choice:** Oneiric claims port **8683** (Dhara's old port, reclaimed). The default `OneiricMCPConfig.http_port` is **8000** today (per `oneiric/core/config.py:231-233`). Phase 1 task 1.5 creates `oneiric/settings/oneiric.yaml` with `mcp: { http_port: 8683, http_host: 127.0.0.1 }` override. The override is required — `oneiric/settings/` currently contains only `lavinmq.yaml`; there is no project-local config file. The Dhara launchd plist on operator machines is retired as part of Phase 8 (R4 mitigation).

CLI subcommands (provided by the new Typer sub-app):

```
$ oneiric mcp start      # calls run_server() — binds 8683 (or whatever settings/oneiric.yaml configures)
$ oneiric mcp stop       # graceful shutdown
$ oneiric mcp status     # liveness probe
$ oneiric mcp health     # per-feed aggregator (returns 503 if any feed degraded)
$ oneiric mcp restart    # stop + start
$ oneiric mcp config     # show resolved config
```

The `oneiric/runtime/mcp_health.py` runtime module provides the base primitives (`HealthStatus`, `ComponentHealth`, `HealthMonitor.create_health_response`) but **lacks the per-feed counter primitives the spec requires**. Phase 1 task 6 extends `HealthMonitor` with:
- `record_invocation(name: str, errored: bool) -> None` — increments `cycles_total`, optionally `errors_total`, sets `last_updated_timestamp`
- `set_entities_count(name: str, n: int) -> None` — updates entity count
- `get_feed(name: str) -> ComponentHealth | None` — per-feed lookup (currently not exposed)

Without these primitives, Phase 1 task 8's e2e test ("/health returns 200 with 7 healthy feeds on warm startup") cannot construct feeds with non-zero `cycles_total` and read per-feed signals.

**Per-tool feed commitment:** Each of the 7 adapter_registry tools registers a `ComponentHealth` feed exposing `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` per `.claude/decisions/mcp-backend-wiring-discipline.md`. The aggregator increments these counters on every tool invocation.

**Tool profile gating (Phase 1):** Wire via `mcp_common.tools.dispatch.apply_tool_profile(profile_env_var="ONEIRIC_TOOL_PROFILE")` with explicit group definitions:

| Profile | Groups exposed |
|---------|----------------|
| `MINIMAL` | `MANDATORY` + `HEALTH` (only `list_adapters` for discovery) |
| `STANDARD` | `MINIMAL` + `get_adapter` + `list_adapter_versions` + `validate_adapter` + `get_adapter_health` (read-only introspection) |
| `FULL` | `STANDARD` + `store_adapter` + `get_contract_info` (mutation + introspection) |

This mirrors the convention used by other Bodai MCP servers (Dhara's profile definition at `dhara/mcp/profiles.py:122-138` is the reference pattern).

### 4.8 Observability commitment (cross-phase)

The spec's per-feed observability commitment is tightened across four axes that the second-pass observability-incident-lead review flagged.

**Per-tool OTel span wrapping.** `oneiric/core/observability.py:87-101` defines `observed_span()` as an explicit context manager — **NOT auto-instrumented**. Every Phase that adds MCP tools must wrap each tool body in `with observed_span("<server>.mcp.tool.<name>", component="<server>.mcp", attributes={"tool.name": ..., "tool.duration_ms": ...}):`. Phase 1 task 7 commits to wrapping each of the 7 adapter_registry tools; Phases 3, 4, 5, 7 commit similarly. A new `mcp_common.tools.observed_tool_span` decorator is the preferred path (avoids per-tool wrapping repetition); Phase 1 task 7 implements the decorator if not already present.

**HealthStatus threshold semantics.** `oneiric/runtime/mcp_health.py:13-18` defines 5 states. The spec commits to the following threshold contract (every Phase applies this):

| Status | Condition |
|--------|-----------|
| `STARTING` | Feed initialized, `cycles_total == 0`. |
| `HEALTHY` | `cycles_total > 0` AND `errors_total == 0` AND `last_updated_timestamp` within `5 × polling_interval` of now. |
| `DEGRADED` | `errors_total > 0` AND `last_updated_timestamp` within `5 × polling_interval` of now, OR `last_updated_timestamp` is older than `5 × polling_interval`. |
| `UNHEALTHY` | `entities_count == 0` after warmup (cycles_total > some-warmup-threshold, e.g. 10), OR N consecutive `DEGRADED` cycles (N=5 by default), OR per-component-DuckDB-file-missing (Phase 5 endpoint check). |
| `SHUTTING_DOWN` | Feed explicitly marked for shutdown. |

`HealthMonitor._determine_overall_status` (oneiric/runtime/mcp_health.py:107-116) maps any `UNHEALTHY` component to overall `UNHEALTHY`, any `DEGRADED` to overall `DEGRADED`, otherwise `HEALTHY`. The overall status drives the `/health` HTTP response: `HEALTHY` → 200, `DEGRADED` → 200 (operational but imperfect), `UNHEALTHY` → 503.

**Alert routing (HIGH).** 503 responses from `/health` emit a structured OTel log event at `ERROR` level with attributes `server.name`, `feed.name`, `feed.status`, `feed.errors_total`, `last_updated_timestamp`. **Grafana Alertmanager rules are provisioned to page the Bodai on-call channel on sustained 503 (≥2 minutes) from any Bodai MCP server.** This is committed by Phase 8 task 16 (cross-component provisioning): add Grafana Alertmanager rules at `monitoring/grafana/alertmanager-rules.yaml` covering all 4 Bodai MCP servers (Oneiric:8683, Mahavishnu:8680, Akosha:8682, Crackerjack:8676). Phase 8 demonstrates the wiring with `amtool check-config monitoring/grafana/alertmanager-rules.yaml`.

**Audit logging scope.** `mcp_common/auth/audit.py:18-45` defines `AuthAuditEvent` as **auth-only** (token verification, RBAC checks, denial events). It does NOT capture MCP tool invocations. Phase 1 task 4 commits to extending `mcp_common.auth.audit.AuditLogger` with a `tool_invocation` event shape (fields: `tool.name`, `caller_id`, `arguments` redacted per auth-standards spec, `timestamp`, **`outcome` (success|failure|blocked), `caller_session_id`** for OTel/hook-bus correlation, `error_class` when failure). Wire tools emit `tool_invocation` audit events on every invocation; read-only tools emit them at `INFO` level, write tools (`store_adapter`, `validate_adapter`) emit at `WARN` level. Phase 2 closes out the audit story alongside the auth consolidation.

**Audit cross-correlation.** `caller_session_id` joins audit records to (a) the OTel trace span for the same call (via `session_id` field), (b) the `hook_bridge_feed` canonical envelope's `session_id` (Phase 12), and (c) the Session-Buddy session log. Without these three fields, audit becomes a write-only ledger; with them, audit is an investigation surface for incident response. Per `.claude/decisions/mcp-backend-wiring-discipline.md`, audit records are a mandatory wire-up substrate for incident playbooks. Phase 2 closes out the audit story alongside the auth consolidation.

**Bus publish error tracking.** Phase 12's `bodai_hook_bridge._publish()` is **not fire-and-forget** in the silent-no-op sense — failure modes (Redis Streams unreachable, adapter missing) **increment `hook_bridge_feed.errors_total`** before swallowing. The feed exposes `feed.entities_count`, `feed.cycles_total`, `feed.errors_total`, AND `feed.publish_failures_total` — the latter is a sub-counter of `errors_total` reserved for publish-side failures. Silent no-op is a wiring-discipline violation per `mcp-backend-wiring-discipline.md` ("a process being alive is not the same as a process being functional"). The bridge remains non-blocking on the hot path; tracking failures is observational, not blocking.

**Bus subscriber per-feed signals.** Subscriber-side loops (`mahavishnu/bus_subscribers/jot_drainer.py` and any other async consumer introduced by Phase 12+) own their own `ComponentHealth` feed exposing `feed.entities_count` (number of envelopes drained), `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`. The publish-side `hook_bridge_feed` does NOT count subscriber activity. Without subscriber-side feeds, a dead consumer fills the bus silently — same wiring-discipline failure mode the publish-side fix above addresses.

**Canonical `polling_interval`.** The §4.8 threshold contract's "5 × polling_interval" is anchored to a single canonical value: **`polling_interval = 60 seconds`** (configurable per-component, but the default and the contract reference are 60s). Each component's `OtelTracesConfig.component_endpoints` polling loop MUST default to 60s; per-component overrides are allowed but the threshold semantics (`HEALTHY`/`DEGRADED`/`UNHEALTHY` boundaries) assume 60s unless the override is also documented in the spec.

**Cross-MCP correlation playbook.** Phase 1 changes 4 MCP servers simultaneously. Incident responders need:
- A `docs/runbooks/bodai-mcp-incident.md` runbook listing the 4 `mcp` servers' `/health` URLs, the dependency graph, and trace-context propagation rules. Phase 8 task 17 creates this runbook.
- An aggregate "ecosystem health" surface. Phase 8 task 18 adds `mahavishnu mcp ecosystem health` (Typer sub-command) that fans out to all 4 `/health` endpoints and returns an aggregate response.
- OTel trace propagation across MCP server boundaries. Phase 1 task 7 includes trace-context propagation in `mcp_common.auth.middleware` (cross-server traceparent header forwarding).

### 4.9 Migration guide commitment

Phase 8 task 20 creates a top-level `dhara/MIGRATION.md` (not a buried spec section) with:
1. **Old-name → new-name mapping table** for all 21 tools (lift from §4.2 and §8 of this spec).
2. **Hard-cutover date and commit boundary** (commit hash for the Phase 8 deletion).
3. **Notification channels** (resolves R5 / H HIGH):
   - **Email**: `mailto:nas-dhara@arctrix.com` (already on Dhara's `CHANGELOG.md:871`).
   - **GitHub Discussions**: pinned issue at `https://github.com/lesleslie/dhara/discussions` (or similar — pin a discussion with the migration guide).
   - **PyPI long-description**: Dhara's `pyproject.toml` `readme = "README.md"`; ensure the README's first 200 chars lead with "BREAKING: 21 mcp__dhara__* tools removed in v1.0.0; see https://github.com/lesleslie/dhara/blob/v1.0.0/MIGRATION.md".
   - **PyPI classifier**: add `Development Status :: 7 - Inactive` is wrong (Dhara is active); instead add `Topic :: Software Development :: Libraries :: Python Modules` and a project URL pointing at the migration guide.
4. **Per-consumer migration instructions** — for each of the 21 tools, link the new tool's path, the import change, and a one-line code snippet showing old → new.

Phase 9 task 3 (`docs/MCP_TOOLS_SPECIFICATION.md`) adds a top-of-file breadcrumb: "**Notice: 21 `mcp__dhara__*` tools removed in v1.0.0; see [MIGRATION.md](https://github.com/lesleslie/dhara/blob/v1.0.0/MIGRATION.md).**"

### 4.10 Historical Dhara state retention

Per second-pass data-retention review (MEDIUM #4), each Dhara substrate has a documented fate:

| Substrate | Phase home | Historical fate |
|----------|------------|-----------------|
| `AsyncAdapterRegistry` (Dhara's adapter catalog) | Phase 1: Oneiric | **Migrate on first startup.** One-shot read-and-write task: load existing adapter records from Dhara's on-disk file, write to Oneiric's adapter catalog store. Demonstrable by `oneiric mcp health.adapter_registry.entities_count > 0` on a pre-0.20.1 install. |
| `AsyncKVTimeSeriesStore` | Phase 6: Oneiric cache adapter | **Decision needed.** Two options: (a) ship a `dhara migrate kv-timeseries` CLI that bulk-writes historical records to the Oneiric cache adapter; (b) document data as orphaned with a release note. **Default (per user): migrate.** Phase 8 task 19 implements the CLI. |
| `AsyncEcosystemStateStore` (service registry + event log) | Phase 3: Mahavishnu | **Migrate on first startup.** One-shot read-and-write task: load existing service/event records from Dhara's on-disk file, write to Mahavishnu's ecosystem_state store. Demonstrable by `mahavishnu mcp health.ecosystem_state.entities_count > 0` on a pre-0.20.1 install. |
| `dhara_query_local_traces` DuckDB file | Phase 5: Akosha | **No migration needed.** The DuckDB file is read through `OtelTracesConfig.component_endpoints` (Phase 5 task 3). Historical traces are read unchanged. Phase 8 documents the no-op. |

**§4.10.1 Migration observability commitment (added 2026-09-15, multi-agent review).** Each historical-Dhara migration operation emits an OTel span and an audit event so that "fresh install" and "silent migration failure" are distinguishable in operator dashboards.

- **OTel span**: name = `bodai.migration.<substrate>` (e.g. `bodai.migration.adapter_registry`, `bodai.migration.ecosystem_state`, `bodai.migration.kv_timeseries`); attributes include `substrate` (string), `source_path` (string), `records_read` (int), `records_written` (int), `outcome` (`success`|`partial`|`failure`), `error_class` (when failure).
- **Audit event**: `mcp.migration.<substrate>` event_type with the same field set; `INFO` on success, `WARN` on partial / failure. Emitted via `mcp_common.auth.audit.AuditLogger.migration_event(...)` extending the same shape as `tool_invocation`.
- **Health-feed surface**: each migration's target feed carries a `migration_completed_at` timestamp field on `ComponentHealth`. Operators can correlate `entities_count > 0` + `migration_completed_at is None` (fresh install) against `entities_count > 0` + `migration_completed_at not None` (migrated) against `entities_count == 0` + `migration_completed_at not None and outcome == 'failure'` (silent-failure mode). Demonstrable by `oneiric mcp health.adapter_registry.migration_completed_at is not None` on a pre-0.20.1 install after Phase 1.

The hard cutover stance (per spec Phase 12a task 5 + §4.13.4) extends here: migrations are atomic from the operator's perspective — either `migration_completed_at` is set with outcome `success`/`partial`, or it's not set (and the operator inspects OTel + audit logs for the failure). KV-time-series remains the asymmetric case (explicit CLI rather than auto-migrate); its audit event lands when the operator runs `dhara migrate kv-timeseries`.

### 4.11 Wrapper consolidation principle (Layer 1)

Per the third-pass topology analysis (`docs/adr/017-oneiric-shared-persistence-substrate.md` already establishes the persistence substrate; this spec extends the same substrate principle to the **MCP-tool wrapper layer**):

The four Bodai application components (Mahavishnu, AkoSHA, Session-Buddy, Crackerjack) independently ship the same thin wrappers over shared infrastructure:

| Wrapper | Count today | Shared underlying service |
|---|---|---|
| PyCharm/IDE wrappers (`search_code_patterns`, `find_usages`, `get_ide_diagnostics`, `get_symbol_info`, `pycharm_health`) | 5 tools × 4 components = **20 duplicate slots** | `pycharm` MCP |
| `discover_tools` | 4 copies | Each component's own tool inventory |
| `list_*_skills` / `list_*_agents` / `get_*_skill` / `get_*_agent` | 4 tools × 4 components = **16 duplicate slots** | Canonical Dhara substrate (per Phase 4 / mcp-common.canonical_schemas) |
| Health probes (`get_liveness`, `get_readiness`, `health_check_service`, `health_check_all`, `wait_for_dependency`) | 5 tools × 4 components = **20 duplicate slots** | `mcp_common.health` |
| `query_local_traces` | 3 copies (Mahavishnu, AkoSHA, Crackerjack) | Per-component DuckDB files |

Each component **declares its own copy** of these wrappers, all routing to the same underlying service. This is the natural shape of an MCP server exposing a canonical surface — but it costs 60+ duplicate tool slots, four launchd processes, four mcp-common instantiations, four auth secret env vars, and four `name=` overrides for picker visibility.

**The consolidation opportunity lives in `mcp-common`, not in component absorption.** Components keep their distinct business responsibilities (orchestration / intelligence / session / quality); the *wrappers over shared infrastructure* move to `mcp-common`.

**Layer 1 commitment:** The Phase 1.5 wrapper consolidation phase (added to §5) extracts these wrappers into `mcp-common` modules. Each component mounts them under a local-namespace prefix (e.g., `mcp__mahavishnu__pycharm_*`) via `mcp_common.tools.dispatch` registration. After Layer 1 ships, each component's MCP surface drops from 30-200 tools down to just its domain tools.

**What Layer 1 does NOT do:** It does not fold components together, does not consolidate the storage layers (still per-component DuckDB / SQLite / Dhara), does not change the four-process architecture. Layer 1 is wrapper-extraction only.

**Pre-flight gate:** the wrapper extraction must use the existing `mcp-common` modules where they exist (`mcp_common.health`, `mcp_common.auth`). New wrappers (`mcp-common.ide.pycharm_tools`, `mcp-common.discovery`, `mcp-common.catalog`, `mcp-common.traces`) live alongside existing modules. Phase 1.5 task 0 enumerates each wrapper's current call sites across all four components before extraction.

### 4.12 Postgres consolidation principle

The Postgres / pgvector analysis from the topology review surfaces three distinct layers of "consolidation" — only one of which requires component-level changes:

**Layer 2 — pgvector adapter (Oneiric owns it).** Already consolidated per ADR 017 (`oneiric/adapters/vector/pgvector.py:49`). AkoSHA wraps it as `PgvectorHotStore` (HotStore collection contract on a specific collection); Mahavishnu wraps it as `PgvectorAdapter` (HNSW-extended driver). These wrappers are at different abstraction layers and add genuinely different behavior. **Do not merge the wrappers** — folding them would lose the HotStore collection contract and the HNSW driver config separately. **Verdict: nothing to do.**

**Layer 3 — Postgres server co-tenancy.** A deployment-config decision the repos do not make. Each component has its own DSN site (`akosha/settings/akosha.yaml:95`, `mahavishnu/settings/mahavishnu.yaml:144`, `mahavishnu/core/database.py:59-84`, `mahavishnu/core/config.py:789`). Co-tenancy on one Postgres server is feasible (different schema namespaces, no collisions) but nothing in the code assumes it. **Verdict: deployment decision, not a spec decision.**

**Dormant-code hygiene (the real work).** Both Mahavishnu and AkoSHA have full pgvector code paths that are wired in code but disabled in committed config:

| Component | Dormant signal | Decision |
|---|---|---|
| AkoSHA | `hot_store.pg_url: ""` (`akosha/settings/akosha.yaml:95`); `akosha_query_local_traces` integration test gated on `AKOSHA_TEST_PGVECTOR_URL` (header docstring notes Oneiric upstream bug `WITH (lists := 100)` rejected by Postgres 18 blocking the suite) | Phase 10 commits-or-deletes: pick one |
| Mahavishnu | `otel_storage.enabled=false` (`mahavishnu/settings/mahavishnu.yaml:59`); `persistence.postgres_url=""` (`mahavishnu/settings/mahavishnu.yaml:144`) | Phase 10 commits-or-deletes: pick one |
| Oneiric | `OTelStorageSettings.connection_string` default `"postgresql://postgres: postgres@localhost: 5432/otel"` has spaces around the colon; Mahavishnu's stricter validator (`mahavishnu/core/config.py:880-916`) would reject it | Phase 10 fixes the default and makes Oneiric's `OTelStorageSettings` the canonical model Mahavishnu imports |

**Cross-component Postgres coupling.** `mahavishnu/ingesters/otel_ingester.py:41` does `from akosha.storage import HotStore` — a direct cross-component Python import ADR 017 §Implementation evidence lines 147-148 cite as Phase-5 work to be removed. The replacement path is **Oneiric adapter access** (not AkoSHA's storage). The dependency arrow flips: Mahavishnu → Oneiric, never Mahavishnu → AkoSHA. Phase 5 task 4 implements this flip.

**Mahavishnu dual-write migration debt.** `mahavishnu/settings/mahavishnu.yaml:140` shows `persistence.write_mode: "dual"` — Mahavishnu writes to BOTH Dhara (legacy) AND Postgres simultaneously. Dual-write is a migration state, not a steady state. Phase 5 commits a single-source decision: either Dhara OR Postgres, delete the other write path. **Without this, the spec's "decompose Dhara's MCP" goal is undermined** — Dhara's substrate role is not cleanly retired while Mahavishnu keeps dual-writing.

### 4.13 Hook coordination via Oneiric event bus — added 2026-09-14

The four hook channels (`mahavishnu/.git/hooks/`, `mahavishnu/.claude/hooks/`, `~/.claude/hooks/`, plus Qwen/Codex bridges) currently run local action logic and emit events to an in-house JSON-file queue (`~/.mahavishnu/bodai-event-queue.json`). Phase 12 introduces a one-canonical-handler / four-bridge pattern; the bus arm reduces friction for cross-component subscribers.

**§4.13.1 Design principle.**

- **Canonical handler**: a single Python module owns all hook logic. The seven project-scoped Claude hooks (`mahavishnu/.claude/hooks/*.py`) have per-file bodies today; the bridge refactor moves them into `mahavishnu/bodai_hook_bridge.py` as named functions.
- **Per-harness bridges**: each hook location gets a ≤20-line bridge that reads harness-specific JSON, normalizes to a canonical envelope, and invokes the canonical handler. Bridges are the only harness-specific code; the canonical handler is harness-agnostic.
- **Sync-blocking preservation**: `PreToolUse`, `SubagentStop`, `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, and other events whose exit code blocks the harness stay sync. The bus publish (where it fires) is post-decision, fire-and-forget — the blocking semantics never depend on a bus round-trip.
- **Bus choice**: `oneiric.adapters.queue.redis_streams` (per the brainstorming session 2026-09-14; aligned with the active serverless-readiness plan Phase 8 WAL substrate).
- **Multi-harness support**: Claude Code today; Qwen Code added in Phase 12b; Codex bridge deferred to when Codex ships a stable hook surface.
- **Handler home**: `mahavishnu/bodai_hook_bridge.py`, project-local (matches the existing `_hook_io.py` module location and keeps project-context knowledge in the same repo).

**§4.13.2 Canonical envelope schema.**

The bridge normalizes the harness-specific stdin JSON to a single canonical envelope. Qwen's docs state "compatibility with light field remapping"; the schema below is the superset both harnesses can normalize into.

| Field | Claude Code | Qwen Code | Canonical envelope |
|---|---|---|---|
| `event` | `hook_event_name` | `hook_event_name` | pass-through (literal event name) |
| `harness` | (set by bridge) | (set by bridge) | literal — bridge sets "claude", "qwen", "git", "codex" |
| `session_id` | stdin | stdin | pass-through (str) |
| `cwd` | stdin | stdin | pass-through (str) |
| `tool_name` | display name (e.g. `WriteFile`) | runtime id (e.g. `write_file`) | store both; canonical uses runtime id (Qwen convention) |
| `tool_input` | object | object | pass-through |
| `tool_use_id` | `toolu_xxx` | `toolu_xxx` | pass-through |
| `tool_call_id` | (absent) | `call_xxx` (optional) | optional canonical field |
| `permission_mode` | `default \| plan \| acceptEdits \| auto \| dontAsk \| bypassPermissions` | `default \| plan \| auto_edit \| auto \| yolo` | store both raw enums; canonical writer picks per project |
| `agent_id`, `agent_type` | subagent fields | subagent fields | pass-through |
| `effort` | `{ level: low\|medium\|high\|xhigh\|max }` | (absent) | optional canonical field, Claude-only |
| `timestamp` | (absent) | present | always set (ISO 8601) |

Tools subscribing to the bus read the canonical envelope; harness-specific schema divergences stay at the bridge layer.

**§4.13.3 Sync-blocking events (no bus-arm blocking dependency).**

These events' *observation* may still publish to the bus (post-decision), but their *blocking semantics* never depend on a bus round-trip:

| Event | Reason |
|---|---|
| `PreToolUse` | Exit 2 blocks the tool call; sync execution required |
| `UserPromptSubmit` | Can block the prompt; sync required |
| `Stop` | Can block the model from stopping; sync required |
| `SubagentStop` | Can block subagent return; sync required |
| `UserPromptExpansion` | Can block expansion; sync required |

**§4.13.4 Migration path.**

`~/.mahavishnu/bodai-event-queue.json` (current) → `oneiric.adapters.queue.redis_streams` (target). **Hard cutover in Phase 12a task 5** — all in-process Bodai producers either publish to the bus or are retired; the JSON-file path is deleted. No dual-write migration state (Phase 5 R11 cautionary tale: `persistence.write_mode: "dual"` is precisely the kind of debt this design rule rejects).

**§4.13.5 Multi-harness compatibility.**

Each new harness adds a ≤20-line bridge file at the harness-specific hook location:

```python
#!/usr/bin/env python3
# /Users/les/hooks/qwen/PostToolUse (10-15 lines)
import sys, json, os
sys.path.insert(0, os.environ["QWEN_PROJECT_DIR"])
from bodai_hook_bridge import handle
handle(event_name=os.environ["QWEN_HOOK_EVENT_NAME"], harness="qwen", payload=json.load(sys.stdin))
```

Adding Codex hooks (or any future harness) is ~15 lines per event. The canonical handler is one Python module.

### 4.7 ADR cross-references

- **ADR 013 (active) — REVERSAL.** ADR-013's existing 2026-09-14 amendment (lines 169-199) explicitly states "**Option C (remove Mahavishnu's surface) is not chosen by this amendment.**" This spec **overturns** that amendment and adopts Option C (remove `mcp__mahavishnu__adapter_list` and `mcp__mahavishnu__adapter_metadata`). The rationale for reversal: Oneiric regaining an MCP server (Phase 1 of this spec) removes the original justification for the B-framing. With Oneiric's MCP server as the canonical surface per ADR-013's own "if Option C is later adopted" branch (lines 141-152), keeping Mahavishnu's adapter tools creates duplication, not boundary clarity. The amended ADR-013 must record this reversal explicitly with date and rationale; this spec is the contract for that amendment.

- **ADR 017 (proposed)** — Oneiric as the shared persistence substrate. The Oneiric MCP server (Phase 1 of this spec) IS the ADR-013 "canonical surface" for adapter state queries, now owned by Oneiric per ADR-017's "owned by Oneiric" framing. ADR-017 needs a minor amendment noting that Oneiric now ships an MCP server alongside its 54 built-in adapters.

- **Active plan `2026-09-14-bodai-serverless-readiness-and-component-substitution.md` — REQ REDIRECTS.** Phase 4 of the active plan has 5 named REQs that need explicit redirect after Phase 1 of this spec lands. Without this enumeration, the two plans silently conflict on the same Dhara files:

  | Active plan REQ | Target file (in active plan) | New target (post-Phase-1) | Rationale |
  |-----------------|-------------------------------|--------------------------|-----------|
  | `REQ-DHARA-LOCKS` | `dhara/dhara/lock/__init__.py` | unchanged | Lock impl is engine code; stays in Dhara |
  | `REQ-DHARA-STORAGE` | `dhara/dhara/mcp/server_core.py:141-148` | `oneiric/mcp/server_core.py` | The hardcoded `FileStorage` instantiation lives in the MCP server code; after Phase 1 this code is in Oneiric |
  | `REQ-DHARA-CACHE` | `dhara/dhara/core/connection.py` | unchanged | Cache is engine code; stays in Dhara |
  | `REQ-DHARA-CLOUD` | `dhara/dhara/storage/postgres.py` | unchanged | Cloud primary storage is engine code; stays in Dhara |
  | `REQ-DHARA-ASYNC` | `dhara/dhara/core/connection.py` | unchanged | Async path is engine code; stays in Dhara |

  Phase 9 of this spec updates the active plan to reflect these redirects. Only `REQ-DHARA-STORAGE` migrates target; the rest are unchanged because they touch engine code that this spec does not move.

- **Active plan Phase 11 (Harness-agnostic enablement) — REDIRECT.** Phase 11 currently validates Qwen Code / Claude Code against `mcp__dhara__*` tools. After Phase 8 of this spec, those tools are gone. Phase 9 of this spec updates Phase 11's test matrix with an explicit tool-name mapping (see §5 Phase 9 below).

## 5. Phased Delivery Plan

Phase ordering matters because the migrations cascade and each phase leaves the test suite green.

### Phase 1 — Restore Oneiric MCP server

**Goal:** `mcp__oneiric__*` tools exist; Mahavishnu and agents migrate to calling them. Hard cutover — no deprecation window, no `DEPRECATED_TOOLS` entries (user decision 2026-09-14).

**Pre-flight gate (Phase 1 task #0):** Enumerate every `mcp__dhara__*` reference across the Bodai ecosystem. The 86 hits found by `grep -rn "mcp__dhara__" /Users/les/Projects/` span:
- `.claude/agents/oneiric-specialist.md:17` (1 hit)
- `.claude/worktrees/agent-*/docs/adr/013-...md` (5 hits in worktree copies — non-canonical, ignored)
- `mahavishnu/.claude/decisions/test-matrix-review-followups.md` (archival, fine)
- `mahavishnu/core/skill_mcp_validator.py:62` (1 hit)
- `docs/superpowers/plans/2026-04-26-agent-skill-modernization.md` (4 hits at lines 275, 685, 1079, 1088)
- All other matches are registration code in Dhara, McP-server definitions, or Dhara CHANGELOG entries — not consumers.

**Tasks:**

0. **Enumerate all 86 `mcp__dhara__*` call sites** (verified via grep across `/Users/les/Projects/`). Each consumer updated in the same commit as the tool's deletion. See R5 enumeration: 86 hits span `.claude/agents/oneiric-specialist.md:17`, `.claude/worktrees/agent-*/docs/adr/013-...md` (5 worktree copies — non-canonical, ignored), `mahavishnu/.claude/decisions/test-matrix-review-followups.md` (archival, fine), `mahavishnu/core/skill_mcp_validator.py:62`, `docs/superpowers/plans/2026-04-26-agent-skill-modernization.md` (4 hits at lines 275, 685, 1079, 1088). All other matches are registration code in Dhara, McP-server definitions, or Dhara CHANGELOG entries — not consumers.

1. Create `oneiric/mcp/server_core.py` with `OneiricMCPServer` class following Dhara's `run_http_async` pattern (NOT the broken `MCPServerCLIFactory._start_server()` loop — see §4.6 for the pattern).

1.5. **Create `oneiric/settings/oneiric.yaml`** with `mcp: { http_port: 8683, http_host: 127.0.0.1 }` override. The default `OneiricMCPConfig.http_port` is 8000; without this override Phase 1 would bind the wrong port. Verify by `oneiric config show mcp` after the file lands.

2. **Wire the Typer sub-app pattern** (oneiric MEDIUM #1 — MCPServerCLIFactory is dead code): in `oneiric/cli/__init__.py:271-278`, add `app.add_typer(mcp_app, name="mcp")` where `mcp_app` is a `typer.Typer` defined in `oneiric/mcp/server_core.py` registering `start|stop|status|health|restart|config` commands that invoke `OneiricMCPServer.run_http_async()`. The unused `MCPServerCLIFactory` (lines 31-162 of `oneiric/core/cli.py`) is left as historical artifact; cleanup deferred to a follow-up refactor.

3. Port the 7 `adapter_registry` tool implementations from `dhara/mcp/adapter_tools.py` (1,301 LOC) into `oneiric/mcp/tools/adapter_registry.py`. Each tool body wraps work in `with observed_span("oneiric.mcp.tool.<name>", component="oneiric.mcp", attributes={"tool.name": ..., "tool.duration_ms": ...}):` per §4.8. **Without this wrapping, OTel spans do not exist at runtime** (observability HIGH #1).

4. Wire auth via `mcp_common.auth.middleware` (NOT Dhara's auth fork — Dhara's auth goes away with the server in Phase 8). Also extend `mcp_common.auth.audit.AuditLogger` with `tool_invocation` events (`tool.name`, `caller_id`, `arguments` redacted) per §4.8. Wire write tools (`store_adapter`, `validate_adapter`) to emit `WARN`-level events; read-only tools emit `INFO`.

5. Wire tool profile gating via `mcp_common.tools.dispatch.apply_tool_profile` with explicit `ONEIRIC_TOOL_PROFILE` semantics per §4.6.

6. **Extend `HealthMonitor`** with `record_invocation(name, errored)`, `set_entities_count(name, n)`, `get_feed(name)`, per §4.8 (oneiric HIGH #3 — primitives don't exist yet). Wire each of the 7 tools to register a `ComponentHealth` feed and call `health_monitor.record_invocation(name, errored=...)` after each tool invocation. `/health` endpoint returns 503 if any feed's status is `UNHEALTHY` per the §4.8 threshold contract.

7. **Migrate historical `AsyncAdapterRegistry` data** on first Oneiric startup (per §4.10). One-shot read-and-write from Dhara's on-disk file to Oneiric's adapter catalog store. Demonstrable by `oneiric mcp health.adapter_registry.entities_count > 0` on a pre-0.20.1 install.

8. Add `tests/integration/test_<tool>_e2e.py` for each of the 7 tools (per wire-up contract). Each test asserts the tool emits an OTel span and updates the per-feed counters.

9. Add `tests/integration/test_oneiric_mcp_health.py` asserting (a) `/health` returns 200 with 7 healthy feeds on warm startup, (b) returns 503 when any feed reports `UNHEALTHY` per the §4.8 threshold contract, (c) each feed's `entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total` are exposed per `.claude/decisions/mcp-backend-wiring-discipline.md`.

10. Update `mahavishnu/tests/fixtures/full/tool_names.json` to remove the strings `"adapter_list"` and `"adapter_metadata"` (Mahavishnu's parallel fixture — currently has these as golden-fixture strings).

11. Update `.claude/agents/oneiric-specialist.md` to use `mcp__oneiric__*` names.

12. Update `.claude/agents/database-operations-specialist.md` + `architecture-council.md` cross-references.

13. Update `docs/superpowers/plans/2026-04-26-agent-skill-modernization.md` (lines 275, 685, 1079, 1088) to replace `mcp__dhara__*` with `mcp__oneiric__*` / `mcp__mahavishnu__*` / `mcp__crackerjack__*` / `mcp__akosha__*` per the §4.2 destination table.

14. Update `mahavishnu/core/skill_mcp_validator.py:62` to call `mcp__oneiric__get_adapter` instead of `mcp__dhara__get_adapter`.

15. **Update Mahavishnu settings port references** (oneiric MEDIUM #4): in `mahavishnu/settings/mahavishnu.yaml`, update line 304-307 (`oneiric_mcp.base_url: "http://localhost:8683/mcp"` — section title and docstring comment) and line 365-370 (`health.dependencies.dhara: { port: 8683, required: false }` — repurpose to point at Oneiric's new MCP server since Dhara the engine is still a runtime dependency). Verify by `grep -n "8683" settings/mahavishnu.yaml` after the edit returns only the Oneiric references.

16. **Retire Oneiric's `dhara_pusher` adapter** (R6): delete `oneiric/adapters/dhara_pusher.py` (entire file), `tests/test_dhara_pusher_coverage.py` (entire file), remove 6 occurrences in `tests/unit/adapters/test_tracked_settings.py`, remove 4 occurrences in `QUICKSTART.md`, remove `dhara_pusher` entry points from `pyproject.toml` if any. After Phase 1, Oneiric owns its own registry — pushing to a separate Dhara MCP is incoherent.

17. **Add OTel trace-context propagation** to `mcp_common.auth.middleware` for cross-MCP-server trace continuity. Phase 1 task 7 commits this; Phase 8 task 17 documents the propagation rules in `docs/runbooks/bodai-mcp-incident.md`.

**ADR amendments (same commit as Phase 1):**

- **ADR-013**: amendment overturning the 2026-09-14 Option B→"not chosen" decision. Rationale: Oneiric regaining an MCP server removes the original justification for the B-framing. Record reversal with date + rationale per ADR conventions.
- **ADR-017**: minor amendment noting Oneiric now ships an MCP server alongside its 54 built-in adapters.

**Mahavishnu changes (hard cutover in same commit):**

- **Delete** `mcp__mahavishnu__adapter_list` and `mcp__mahavishnu__adapter_metadata` (Option C of ADR-013). Remove from `mahavishnu/mcp/tool_versions.py:TOOL_VERSIONS` (lines 151-152). **Do NOT add to `DEPRECATED_TOOLS`** — the tools are gone, not deprecated (user decision: no deprecation window).
- Update `_check_adapter_metadata_contract` in `mahavishnu/core/compatibility.py:200-222` — the check validates `AdapterMetadata` shape (not the MCP tool itself), so the check stays. Only its description text updates to mention "this checks the shape used by `mcp__oneiric__*`."
- Update `mahavishnu/core/adapter_registry.py:495` docstring: replace "call the dedicated `adapter_list` MCP tool" with "call `mcp__oneiric__list_adapters` via the Oneiric MCP server."
- Tests: narrow scope to actual MCP-tool-affected tests only:
  - Delete `tests/unit/test_mcp_adapter_registry_tools.py:85-289` (the MCP-tool-specific tests)
  - Delete `tests/unit/test_mcp_tool_versions.py:58` (the tool-version entry for the deleted tools)
  - **Do NOT modify** `tests/unit/test_main_cli.py:465,488,497` — these test `_async_adapter_list` which is a local-registry call, not the MCP tool
  - **Do NOT modify** `tests/unit/test_workflow_cli.py:65,78` — same reason
- Internal callers that hit `HybridAdapterRegistry.list_adapters` / `get_metadata` directly (CLI, compatibility checks, agents) continue to work because those are in-process calls, not MCP calls.

**Integration contract (per wire-up contract):**

- **Triggered from:** `oneiric mcp start` (or via launchd plist / systemd unit); agents call `mcp__oneiric__*` via MCP protocol.
- **Returns to / updates:** The Oneiric adapter registry store (backed by Dhara's `AsyncAdapterRegistry` for now; future: Oneiric's own persistence layer per ADR-017).
- **Demonstrable by:** `pytest tests/integration/test_<tool>_e2e.py` (7 files, one per tool) returns exit 0; `oneiric mcp health` returns 200 with 7 healthy feeds; `python scripts/audit_orphans.py --days 14` reports zero new orphans from the Oneiric MCP surface.
- **Rollback signal:** 503 on `/health`, or 0 `entities_count` on any feed after startup, or any e2e test failure.
- **Observability added:** OTel span `oneiric.mcp.tool.<name>` with attribute `tool.name`, `tool.duration_ms`. Per-feed signals at `/health`: `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` for each of the 7 tools (per `.claude/decisions/mcp-backend-wiring-discipline.md`).

### Phase 1.5 — Wrapper consolidation → mcp-common (Layer 1)

**Goal:** Extract duplicated infrastructure wrappers from the four Bodai MCP servers (Mahavishnu, AkoSHA, Session-Buddy, Crackerjack) into `mcp-common` modules per §4.11. Each component mounts the consolidated wrappers under a local-namespace prefix; component-specific tools remain in their own component. **Hard cutover per component** (each wrapper consolidated in its own commit when its tests pass).

**Pre-flight gate (Phase 1.5 task #0):** Enumerate every wrapper call site across all four components for each of the five wrapper categories in §4.11. Verified counts at Phase 1.5 start:
- **PyCharm wrappers**: 5 tools × 4 components = 20 call sites (`akosha/mcp/tools/pycharm*.py`, `mahavishnu/mcp/tools/pycharm*.py`, `session-buddy/mcp/tools/pycharm*.py`, `crackerjack/mcp/tools/pycharm*.py`)
- **`discover_tools`**: 4 implementations (`akosha/mcp/tools/__init__.py`, `mahavishnu/mcp/tools/ecosystem_tools.py`, `session-buddy/mcp/server.py`, `crackerjack/mcp/tools/discovery_tools.py`)
- **`list_*_skills` / `list_*_agents` / `get_*_skill` / `get_*_agent`**: 16 implementations across `akosha/mcp/tools/skill_*.py` + `akosha/mcp/tools/agent_*.py`, etc.
- **Health probes**: 20 implementations (5 tools × 4 components)
- **`query_local_traces`**: 3 implementations (Mahavishnu, AkoSHA, Crackerjack)

**Tasks (per wrapper category — one commit per category):**

1. **PyCharm wrappers → `mcp_common.ide.pycharm_tools`**. Extract `pycharm_search_code_patterns`, `pycharm_find_usages`, `pycharm_get_ide_diagnostics`, `pycharm_get_symbol_info`, `pycharm_health` into a single `mcp_common.ide.pycharm_tools` module. Each component's MCP server registers them via `mcp_common.tools.dispatch.register_local_namespace(component="mahavishnu"|"akosha"|"session_buddy"|"crackerjack", tools=[...])` so the picker still sees `mcp__<component>__pycharm_*`. **Demonstrable by:** each component's `mcp/__main__.py` imports the consolidated module and registers it under the local namespace prefix; existing agent prompts (`.claude/agents/akosha-specialist.md`, etc.) continue to work unchanged because the tool names are stable. **Rollback signal:** any e2e test fails, or `pycharm_health` returns non-200 in any component.

2. **`discover_tools` → `mcp_common.discovery`**. Extract the 4 `discover_tools` implementations into a single `mcp_common.discovery.discover_tools(component=...)` factory. Each component calls `mcp_common.discovery.mount(server)` to wire it locally. The Akosha-only `akosha_list_ecosystem_skills` (which fans out to all 4 servers) stays in AkoSHA — it's the federation aggregator, not a per-component wrapper. **Demonstrable by:** `mcp__mahavishnu__discover_tools` (and 3 siblings) return non-empty `loaded_tools` lists after a fresh component restart. **Rollback signal:** any discover call returns an empty list when tools exist, or federation aggregator misses any component.

3. **`list_*_skills` / `list_*_agents` → `mcp-common.canonical_schemas` + `mcp_common.catalog`**. The current sed-replicated `agent_schema.py` / `skill_schema.py` (canonical in AkoSHA, sed-copied to the other 3) moves to `mcp-common.canonical_schemas`. The 16 tool implementations (4 sets of 4) collapse to a single `mcp_common.catalog.register(server)` that exposes `list_skills`, `get_skill`, `list_agents`, `get_agent` under the local namespace. **Demonstrable by:** `mcp__mahavishnu__list_skills` (and 3 siblings) return the same canonical catalog; deleting AkoSHA's canonical schema files (`akosha/mcp/agent_schema.py`, `akosha/mcp/skill_schema.py`) leaves the other three components still functional because they import from `mcp-common.canonical_schemas`. **Rollback signal:** any catalog query fails signature verification, or any component reports empty `list_agents` after a populated install. Phase 10 commits to this fix as part of the sed-replication cleanup.

4. **Health probes → `mcp_common.health_tools`**. The 20 implementations (5 tools × 4 components) collapse to a single `mcp_common.health_tools.mount(server)` registration. Each component's `mcp/auth.py` and `mcp/tools/health*.py` files shrink to mount-time imports. **Demonstrable by:** `mcp__<component>__get_liveness` (and 4 siblings × 4 components = 16 total) return consistent envelope shapes; `/health` HTTP endpoint returns 200 / 503 per §4.8 threshold contract. **Rollback signal:** any component's `/health` returns the wrong status code, or a probe returns non-canonical envelope.

5. **`query_local_traces` → `mcp_common.traces.endpoint_resolver`**. The 3 implementations (Mahavishnu, AkoSHA, Crackerjack) collapse to a single `mcp_common.traces.query_local_traces(component_endpoints=...)` factory. Per-component DuckDB paths become env-var-driven (`MAHAVISHNU_TRACES_PATH`, `AKOSHA_TRACES_PATH`, `CRACKERJACK_TRACES_PATH`, `SESSION_BUDDY_TRACES_PATH`, `DHARA_TRACES_PATH` if Dhara still emits traces post-Phase-8). **This replaces the hard-coded paths in Phase 5 task 3** (see §5 Phase 5 update below). Demonstrable by: each component's `query_local_traces` reads from its env-var-resolved path; the AkoSHA-side `OtelTracesConfig.component_endpoints` map becomes a default that operators can override. **Rollback signal:** `entities_count == 0` after warmup, or endpoint-resolver raises on any path lookup.

**Mahavishnu / AkoSHA / Session-Buddy / Crackerjack changes (in each wrapper-category commit):**
- Delete the local wrapper file(s); replace with `from mcp_common.<module> import ...; mount(server)`.
- Update test fixtures (`tests/fixtures/{minimal,standard,full}/tool_names.json`) to reflect the new registration source.
- Update `.claude/decisions/mcp-backend-wiring-discipline.md` to cite `mcp-common` as the canonical home.

**Integration contract:**
- **Triggered from:** each component's `mcp/server_core.py` startup calls the consolidated `mount(server)` helper before registering component-specific tools.
- **Returns to / updates:** the consolidated `mcp-common` modules own the canonical wrapper implementations; components own only their domain tools.
- **Demonstrable by:** each wrapper-category commit (5 commits total) passes `pytest` in all four affected components; picker shows `mcp__<component>__<wrapper>_<verb>` for every existing prompt reference.
- **Rollback signal:** any e2e test fails, or the consolidated module raises on `mount(server)`, or any cross-component call breaks.
- **Observability added:** each wrapper tracks invocation count via the existing `HealthMonitor.record_invocation` from Phase 1 task 6; per-feed signals at `mcp-common.health_tools` surface aggregated across all mounted wrappers.

### Phase 2 — Auth consolidation

**Goal:** Complete the auth consolidation by closing out Dhara's row in `2026-04-27-bodai-auth-standardization-design.md`. **Critical correction:** Dhara's auth is **file-based `TokenAuth`** (SHA-256 hashed tokens with per-token `Role` mapping and rate limits — see `dhara/mcp/auth.py:252-436`), NOT JWT. There is no JWT migration. Phase 2 is essentially a no-op for code change because Dhara's auth goes away with the server in Phase 8.

**Why this is a no-op:**

- Phase 1 builds the Oneiric MCP server using `mcp_common.auth.middleware` directly (not Dhara's auth fork).
- Phase 8 deletes `dhara/mcp/auth.py`, `dhara/mcp/fastmcp_auth.py`, `dhara/mcp/middleware.py` (1,325 LOC) along with `dhara/mcp/`.
- No Dhara consumer of `dhara.mcp.auth.*` survives Phase 8 (Dhara has no MCP server, no callers).

**Tasks (documentation only — no code change in Phase 2 itself):**

1. Update `docs/superpowers/specs/2026-04-27-bodai-auth-standardization-design.md` — mark Dhara's row in the "per-service status" table as Done (no separate code migration was needed; the spec's pre-existing mcp_common adoption covered all four remaining services).
2. Update `.claude/decisions/mcp-backend-wiring-discipline.md` if it cited Dhara's auth (verify).
3. Verify by grep: `grep -r "from dhara.mcp.auth" /Users/les/Projects/` returns nothing (already enforced by Phase 1 + Phase 8 deletion, but record the verification step).

**Phase 8 owns the actual deletion** (not Phase 2). Phase 2 just closes the audit trail on the auth-standardization spec.

**Integration contract:**

- **Triggered from:** None (documentation update only; no runtime feature).
- **Returns to / updates:** `2026-04-27-bodai-auth-standardization-design.md` § per-service status table.
- **Demonstrable by:** `grep -rn "dhara" docs/superpowers/specs/2026-04-27-bodai-auth-standardization-design.md` returns no references to "in-progress" or "pending Dhara migration"; the spec's §5.2 per-service adapter section explicitly lists Dhara as N/A (no MCP server post-Phase-1).
- **Rollback signal:** None (no runtime change).
- **Observability added:** None (no runtime change).

### Phase 3 — Move ecosystem_state → Mahavishnu

**Goal:** `mcp__mahavishnu__ecosystem_*` includes 5 new service/event tools. Dhara drops the implementation. Tools use the `ecosystem_*` prefix to cluster with existing `ecosystem_status`, `ecosystem_capabilities`, `ecosystem_routing_readiness` (control-plane convention: cross-component ecosystem state).

**Pre-flight gate:** Confirm no internal caller of `mcp__dhara__upsert_service` / `get_service` / `list_services` / `record_event` / `list_events` outside Dhara. (Grep result from Phase 1 task #0 — none found outside Dhara's own mcp/.)

**Tasks:**

1. Port `dhara/mcp/ecosystem_state.py` (232 LOC) to `mahavishnu/mcp/tools/ecosystem_state.py`. Rename functions:
   - `dhara_upsert_service` → `ecosystem_upsert_service`
   - `dhara_get_service` → `ecosystem_get_service`
   - `dhara_list_services` → `ecosystem_list_services`
   - `dhara_record_event` → `ecosystem_record_event`
   - `dhara_list_events` → `ecosystem_list_events`
2. Port the `AsyncEcosystemStateStore` to `mahavishnu/core/ecosystem_state_store.py`.
3. Register tools with `@server.tool(name="ecosystem_upsert_service")` etc. — explicit names matching the cluster convention.
4. Wire tool profile gating (`ecosystem_state` group; STANDARD + FULL profiles; `mandatory_groups` includes `ecosystem_state` per picker-parity logic — see Dhara's `dhara/mcp/profiles.py:215-228` for the pattern).
5. Add 5 e2e tests in `tests/integration/test_ecosystem_<tool>_e2e.py`.
6. Wire per-feed health aggregator: `ecosystem_state` feed exposes `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`. Counter increments on each tool invocation.
7. Update `.claude/agents/mahavishnu-specialist.md` to reference the new tools under the `/ecosystem/*` cluster.
8. Update `.claude/agents/architecture-council.md` cross-references.

**Hard cutover (no deprecation window, no `DEPRECATED_TOOLS` entries):**

- `mcp__dhara__upsert_service` → `mcp__mahavishnu__ecosystem_upsert_service`
- `mcp__dhara__get_service` → `mcp__mahavishnu__ecosystem_get_service`
- `mcp__dhara__list_services` → `mcp__mahavishnu__ecosystem_list_services`
- `mcp__dhara__record_event` → `mcp__mahavishnu__ecosystem_record_event`
- `mcp__dhara__list_events` → `mcp__mahavishnu__ecosystem_list_events`

**Integration contract:**

- **Triggered from:** `mahavishnu mcp start`; agents call `mcp__mahavishnu__ecosystem_*` via MCP protocol.
- **Returns to / updates:** Mahavishnu's ecosystem_state store (replaces Dhara's `AsyncEcosystemStateStore`).
- **Demonstrable by:** `pytest tests/integration/test_ecosystem_<tool>_e2e.py` returns exit 0; `mahavishnu mcp health` returns 200 with healthy `ecosystem_state` feed; `python scripts/audit_orphans.py --days 14` reports zero new orphans from the ecosystem_state surface.
- **Rollback signal:** 503 or 0 entities_count on ecosystem_state feed, or any e2e test failure.
- **Observability added:** OTel span `mahavishnu.mcp.tool.ecosystem_state.<name>`. Per-feed signals: `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` exposed at `mahavishnu mcp health.ecosystem_state`.

### Phase 4 — Move agent_registry + skill_registry → Crackerjack; signer_feed → mcp-common

**Goal:** Phase 1.5 of the active ACP plan, with split routing per the topology review. The agent/skill catalogs (which are Crackerjack's domain — federation-wide catalogs are quality-tooling's natural neighbor) move to Crackerjack. The signer infrastructure (a cryptographic primitive used by both catalogs) moves to `mcp-common` as cross-cutting infra. LOC breakdown: agent_registry (426) + agent_schema (223) + skill_registry (353) + skill_schema (173) = **1,175 LOC** → Crackerjack; signer_feed (254) + `dhara/skills_signer/` → `mcp-common` (254 LOC + package).

**Pre-flight gate (resolves OQ #1 + OQ-6):** `dhara/skills_signer/` exists at `/Users/les/Projects/dhara/dhara/skills_signer/`. Move it to `mcp-common` (not Crackerjack) — signer is cross-cutting infra, not a quality-tooling concern. After move, **delete** the Dhara-side directory. The canonical `agent_schema.py` / `skill_schema.py` files (currently sed-replicated across 4 components) move to `mcp-common.canonical_schemas` (this is the Phase 10 commit referenced from Phase 1.5 task 3; Phase 4 ships the Crackerjack-side import from the canonical home).

**Tasks:**

1. Port `dhara/mcp/tools/agent_registry.py` (426 LOC) to `crackerjack/mcp/tools/agent_registry.py`. **Imports `agent_schema` from `mcp-common.canonical_schemas`** (not from a local copy).
2. Port `dhara/mcp/agent_schema.py` (223 LOC) to `mcp-common/mcp_common/canonical_schemas/agent.py` (the canonical home referenced by Phase 1.5 task 3).
3. Port `dhara/mcp/tools/skill_registry.py` (353 LOC) to `crackerjack/mcp/tools/skill_registry.py`. **Imports `skill_schema` from `mcp-common.canonical_schemas`**.
4. Port `dhara/mcp/skill_schema.py` (173 LOC) to `mcp-common/mcp_common/canonical_schemas/skill.py`.
5. **Port `dhara/mcp/signer_feed.py` (254 LOC) to `mcp-common/mcp_common/signing/skills_signer.py`** (cross-cutting crypto primitive, not a Crackerjack-domain concern). **Not exposed as an MCP tool**; consumed by the agent/skill catalogs as a library import. The ed25519 signing is the same primitive Phase 1.5 of the active ACP plan ships through `oneiric.actions.security.SecuritySignatureAction`; Phase 4 consolidates around `mcp-common`'s canonical home.
6. Move `dhara/skills_signer/` package to `mcp-common/mcp_common/signing/dhara_skills_signer/` (rename optional; preserving the original namespace avoids breaking the import paths the active ACP plan Phase 1.5 already shipped). **Delete the Dhara-side directory after move.**
7. Wire auth (RBAC: WRITE permission required for registration; READ for listing).
8. Update `crackerjack/mcp/profiles.py`: set `CRACKERJACK_MANDATORY_GROUPS = {REG_KEY_AGENT_REGISTRY, REG_KEY_SKILL_REGISTRY, REG_KEY_HEALTH}` per the picker-parity logic that Dhara documented in `dhara/mcp/profiles.py:215-228`. Without this, `CRACKERJACK_TOOL_PROFILE=minimal` would not expose `list_agents` / `list_skills`, breaking the picker surface inside Mahavishnu and other consumers.
9. Add 4 e2e tests in `tests/integration/test_<tool>_e2e.py`.
10. Wire per-feed health aggregator: each tool registers a `ComponentHealth` feed exposing `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`.

**Phase 10 cross-reference:** Tasks 2 and 4 ship the canonical schema files to `mcp-common.canonical_schemas`; Phase 10 task 2 then **deletes the sed-replicated copies** in AkoSHA / Session-Buddy / Mahavishnu and forces those components to import from the canonical home. Phase 4 + Phase 10 together eliminate the DRY violation documented at `akosha/mcp/agent_schema.py` (the "canonical source" comment) and the 3 sed-replicated siblings.

**Why signer_feed moves to mcp-common, not Crackerjack:** The ed25519 signer is shared infrastructure between `agent_registry` and `skill_registry`. Both catalogs move to Crackerjack, but the signer does not — keeping it in mcp-common means any future catalog (e.g. a workflow catalog, a memory-catalog) can sign its entries without depending on Crackerjack. Cryptographic primitives belong in the cross-cutting infra layer, not in any single application component.

**Hard cutover:**

- `mcp__dhara__list_agents` → `mcp__crackerjack__list_agents`
- `mcp__dhara__get_agent` → `mcp__crackerjack__get_agent`
- `mcp__dhara__list_skills` → `mcp__crackerjack__list_skills`
- `mcp__dhara__get_skill` → `mcp__crackerjack__get_skill`

**Naming note:** Crackerjack already ships its own skill mechanism for skill-managed packaging (`crackerjack-compliant-code`, etc.). The ported Bodai-wide agent/skill catalog lives under the same tool prefix. Document the two namespaces in Phase 4 acceptance criteria: "Crackerjack's own skill management" vs "the federation-wide agent/skill catalog."

**Integration contract:**

- **Triggered from:** `crackerjack mcp start`; agents call `mcp__crackerjack__*` via MCP protocol.
- **Returns to / updates:** Crackerjack's signed-content registry (ed25519-signed via the moved signer_feed).
- **Demonstrable by:** `pytest tests/integration/test_<tool>_e2e.py` returns exit 0; `crackerjack mcp health` returns 200 with healthy agents + skills feeds; `python scripts/audit_orphans.py --days 14` reports zero new orphans from the agent/skill surface.
- **Rollback signal:** Failed signature verification on retrieved agent/skill metadata, or any e2e test failure.
- **Observability added:** OTel span `crackerjack.mcp.tool.<agents|skills>.<name>` + `crackerjack.signer.sign` events. Per-feed signals: `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` exposed at `crackerjack mcp health.<agents|skills>`.

### Phase 5 — Move otel_traces → Akosha (single tool, fitness-shaped)

**Goal:** Akosha owns OTel trace queries; Dhara drops the tool + the `akosha>=0.17.1` dep. **Single tool, not two** (user decision 2026-09-14 — pick one name). Pick **`akosha_query_local_traces_fitness`**: drop Akosha's existing `akosha_query_local_traces` (general-purpose, raw conversation rows) and port Dhara's fitness-shaped tool. Reasons: the `_fitness` suffix makes the contract explicit, the Dhara tool is the only documented consumer's actual need (Akosha's fitness analyzer polls cross-component traces for fitness signal computation), and hard cutover means no backward-compat baggage. If a general-purpose raw-trace query is ever needed, ship it later under a different name (e.g. `akosha_query_traces_raw`).

**Pre-flight gate (resolves HIGH findings from review):**

- **Signature/scope decision.** Dhara's tool and Akosha's existing tool have different signatures (Dhara: `task_class: str` required, `time_range_minutes: int`, `system_id: str | None`, returns fitness-shaped tuples `outcome`/`duration_ms`/`selector`/`component_name`. Akosha: `system_id: str` required, `start_time`/`end_time` RFC3339, returns raw conversation rows `conversation_id`/`content`/`metadata`). They are NOT byte-clones despite Dhara's docstring claiming so. **Hard cutover to the fitness-shaped signature**; the fitness analyzer is the documented consumer; raw-row queries are not.

**Tasks:**

1. **Drop Akosha's existing `akosha_query_local_traces`** (`akosha/mcp/tools/otel_tools.py:30-78`). Delete the tool registration. Update `akosha/mcp/tool_versions.py:TOOL_VERSIONS` to remove the entry.
2. **Port Dhara's `dhara_query_local_traces`** (`dhara/mcp/tools/otel_traces.py:52-187`) to `akosha/mcp/tools/query_local_traces_fitness.py`. Rename to `akosha_query_local_traces_fitness`. Preserve the fitness-shaped signature: `task_class: str`, `time_range_minutes: int = 60`, `system_id: str | None = None`, `limit: int = 100`. Preserve the cross-component polling pattern (opens HotStore against a config-supplied DuckDB file).
3. **Resolve per-component DuckDB routing** (resolves akosha-specialist HIGH #2). Use **`mcp_common.traces.endpoint_resolver`** (the Phase 1.5 wrapper consolidation lands this helper at `mcp-common/mcp_common/traces/endpoint_resolver.py`). Per-component DuckDB paths are env-var-driven, not hardcoded: `MAHAVISHNU_TRACES_PATH` (default `/Users/les/.local/share/mahavishnu/traces.duckdb`), `AKOSHA_TRACES_PATH`, `CRACKERJACK_TRACES_PATH`, `SESSION_BUDDY_TRACES_PATH`, `DHARA_TRACES_PATH` (only set if Dhara still emits traces post-Phase-8). AkoSHA's `OtelTracesConfig.component_endpoints` becomes a **default override layer** that operators can configure when env-vars are insufficient (e.g. for multi-region trace sources). **Demonstrable by:** `akosha mcp health.query_local_traces_fitness` returns 200 with `entities_count > 0` even when one component's DuckDB file is moved (env-var follows it). **Rollback signal:** endpoint_resolver raises on missing path, or `entities_count == 0` after warmup.
4. **Remove `akosha>=0.17.1` from Dhara's `[dependency-groups].otel-traces`** — Dhara no longer needs it after the port. Verified: the only `import akosha` in Dhara runtime code is `dhara/mcp/tools/otel_traces.py:99` (`from akosha.storage import HotStore`); other matches are docstrings. Do NOT move the dep group to Akosha (Akosha already depends on its own storage in-tree — adding a self-referential group creates circular install hazard).
5. Add e2e test in `tests/integration/test_query_local_traces_fitness_e2e.py` — assert the fitness analyzer can poll all 5 components and compute fitness signals correctly. The e2e test verifies (a) all 5 component DuckDB files exist at startup (proactive check), (b) each file is readable, (c) the fitness analyzer returns fitness-shaped tuples with non-empty `entities_count`.
6. Update `.claude/agents/akosha-specialist.md` and `architecture-council.md` cross-references.
7. **Add `traces_endpoints_health` feed** (observability MEDIUM #5 — proactive, not reactive). Each of the 5 component DuckDB files is a separate feed with `feed.entities_count = number_of_reachable_endpoints`. The feed transitions `HEALTHY` → `UNHEALTHY` if any endpoint file is missing or unreadable. Per §4.8 threshold contract: `UNHEALTHY` if `entities_count < 5` after warmup. Rollback signal becomes proactive: "503 or `entities_count < 5` on `traces_endpoints` feed at `/health`, or any e2e test failure." Each tool body wraps work in `with observed_span("akosha.mcp.tool.query_local_traces_fitness", attributes={"tool.name": ..., "tool.duration_ms": ...}):`.
8. **Replace Mahavishnu's `from akosha.storage import HotStore`** (resolves §4.12 cross-component Postgres coupling + ADR 017 §Implementation evidence line 147). The direct import at `mahavishnu/ingesters/otel_ingester.py:41` is the worst cross-component Python import in the Bodai tree (AkoSHA → Dhara was OK; Mahavishnu → AkoSHA is not). **Replacement path:** `from oneiric.adapters.vector.pgvector import PgvectorAdapter` (or the DuckDB-in-Oneiric equivalent) for the pgvector path; **never** `from akosha.storage import HotStore`. The dependency arrow flips: Mahavishnu → Oneiric, never Mahavishnu → AkoSHA. **Demonstrable by:** `grep -rn "from akosha" mahavishnu/` returns 0 matches after Phase 5 commits; the OTel ingester continues to read/write trace data via the Oneiric adapter; the e2e test from Phase 5 task 5 passes with the new adapter path. **Rollback signal:** trace ingestion returns 0 records, or `pytest mahavishnu/tests/integration/test_otel_ingester_e2e.py` fails.
9. **Resolve Mahavishnu's `persistence.write_mode: "dual"`** (resolves §4.12 dual-write migration debt + ADR 017 substrate ownership). Mahavishnu currently writes to BOTH Dhara (legacy) AND Postgres (`mahavishnu/settings/mahavishnu.yaml:140`). Dual-write is a migration state, not a steady state. **Phase 5 commits a single-source decision:**
   - **Option A (Dhara only):** keep Dhara as the substrate; delete Mahavishnu's Postgres write path; remove `mahavishnu/migrations/` Postgres DDL files. Simpler, but loses the serverless-readiness substrate framing in the active plan's Phase 5.
   - **Option B (Postgres only):** migrate the substrate to Oneiric's `PostgresDatabaseAdapter`; delete Mahavishnu's Dhara write path. Aligns with the active plan's substrate framing.
   - **Default (per ADR 017 substrate ownership): Option B.** Dhara's MCP server is being retired in Phase 8; Dhara the engine stays (Dhara-as-engine is the user's choice per `dhara` 2026-09-14 decision). Phase 5 picks Option B: substrate lives on Oneiric's `PostgresDatabaseAdapter`; Mahavishnu's `write_mode: "dual"` setting is removed; `persistence.postgres_url` becomes the canonical substrate URL (operator-configurable). **Demonstrable by:** `mahavishnu mcp health.persistence.entities_count > 0` after a single write (proves Postgres is the substrate); `grep -rn "write_mode.*dual" mahavishnu/` returns 0 matches; the Dhara-as-engine connection (`dhara db start --port 8685`) continues to work for operators who use it for non-Mahavishnu state (the engine stays). **Rollback signal:** Postgres write fails on the operator's deployment, or a Dhara-engine consumer of Mahavishnu state reports missing data. Phase 5 documents the Option A fallback path in `docs/ops/persistence-modes.md` for operators who cannot migrate to Postgres immediately.

**Hard cutover:**

- `mcp__dhara__query_local_traces` → `mcp__akosha__query_local_traces_fitness`
- `mcp__akosha__query_local_traces` (existing) → **deleted** (not replaced; if raw-row queries are needed later, ship a separate tool)

**Integration contract:**

- **Triggered from:** `akosha mcp start`; agents call `mcp__akosha__query_local_traces_fitness` via MCP protocol.
- **Returns to / updates:** Per-component DuckDB HotStore files (resolved via `OtelTracesConfig.component_endpoints`).
- **Demonstrable by:** `pytest tests/integration/test_query_local_traces_fitness_e2e.py` returns exit 0; `akosha mcp health` returns 200; `python scripts/audit_orphans.py --days 14` reports zero new orphans from the otel_traces surface.
- **Rollback signal:** Empty results when traces are expected, or any e2e test failure, or per-component DuckDB file not found (missing endpoint config).
- **Observability added:** OTel span `akosha.mcp.tool.query_local_traces_fitness`. Per-feed signals: `feed.entities_count` (total fitness-shaped rows returned), `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` exposed at `akosha mcp health.query_local_traces_fitness`.

### Phase 6 — Decide kv_time_series and sql_proxy fate

**Goal:** Two remaining tool groups resolved. **Hard cutover (no deprecation window).**

**Pre-flight gate:** Both decisions must be ratified by user before Phase 8 retires Dhara's MCP server. If unratified by Phase 8, the spec defaults are: drop `sql_proxy`, wrap `kv_time_series` as Oneiric cache adapter (no MCP tool).

**Decision matrix (defaults ratified 2026-09-14):**

| Tool group | Default action | Why |
|------------|----------------|-----|
| `kv_time_series` (6 tools: `put`, `get`, `list_prefix`, `record_time_series`, `query_time_series`, `aggregate_patterns`) | **Wrap as Oneiric cache adapter** (no MCP tool). The adapter becomes `oneiric.adapters.cache.persistent_kv` and is consumed by Bodai components via the Oneiric resolver, not via MCP. | Akosha's HotStore is a query substrate (not a generic KV). Session-Buddy's `store_reflection` is memory/reflective (not generic KV). Wrapping as a Oneiric adapter keeps each component's surface tight. Consumers that need generic KV access the adapter directly via Oneiric's resolver; no MCP tool needed. |
| `sql_proxy` (2 tools: `dhara_sql_query`, `dhara_sql_execute`) | **Drop.** | The active plan's Phase 6 already strips similar tools as "off-the-shelf or deleted." DuckDB SQL is reachable through Akosha's trace query tool (which already uses the same DuckDB-backed schema) and through other Bodai surfaces. **Note:** My earlier draft of this spec claimed "AkoSHA already has `aggregate_patterns`" — that claim is false (verified by grep: no such tool exists in `akosha/mcp/tools/`). The decision to drop `sql_proxy` stands on its own merits, not on the (incorrect) duplication rationale. |

**Tasks:**

1. **Wrap `kv_time_series` as Oneiric cache adapter:** port `dhara/mcp/kv_timeseries.py` (443 LOC) to `oneiric/adapters/cache/persistent_kv.py`. Register with `AdapterMetadata(category="cache", provider="persistent_kv", ...)`. Add entry-point to Oneiric's resolver. **Delete** the Dhara `dhara/mcp/kv_timeseries.py` file (no MCP tool to leave behind).
2. **Drop `sql_proxy`:** delete `dhara/mcp/tools/sql_proxy.py`. No replacement. Document the removal in `docs/MCP_TOOLS_SPECIFICATION.md` with rationale.
3. **Drop `dhara_aggregate_patterns`** along with the other kv_time_series tools (no MCP destination; the Oneiric cache adapter doesn't expose aggregate_patterns as an MCP tool — only via the resolver).
4. Add integration tests:
   - `oneiric/tests/integration/test_persistent_kv_adapter_e2e.py` — assert `oneiric.adapters.cache.persistent_kv.put/get/list_prefix` work end-to-end via the resolver.
   - No replacement test for `sql_proxy` (deletion, not migration).
5. Update `oneiric/adapters/bootstrap.py` to include the new adapter (Phase 6 commits both the adapter and the bootstrap registration).

**Integration contract (for the cache adapter; sql_proxy deletion has no contract):**

- **Triggered from:** Bodai components import `oneiric.adapters.cache.persistent_kv` directly or resolve via `OneiricSettings.cache.provider`.
- **Returns to / updates:** The persistent KV store (backed by Oneiric's storage layer per ADR-017).
- **Demonstrable by:** `pytest oneiric/tests/integration/test_persistent_kv_adapter_e2e.py` returns exit 0; manual test via REPL: `from oneiric.adapters.cache.persistent_kv import PersistentKV; kv = PersistentKV(); kv.put("test", b"hello"); assert kv.get("test") == b"hello"`.
- **Rollback signal:** Any e2e test failure or get-after-put returning `None`.
- **Observability added:** OTel span `oneiric.cache.persistent_kv.<verb>` with `verb`, `key`, `duration_ms`. Per-feed signals at the Oneiric cache layer.

### Phase 7 — Move substrate_routes → Oneiric HTTP API

**Goal:** The HTTP routes (settings/context/progress) move to Oneiric alongside the new MCP server.

**Pre-flight gate (resolves OQ #2, with re-evaluation point tracked in OQ #5):** substrate_routes' storage layer lives in Oneiric's registry (not Dhara's). The HTTP routes read/write Oneiric's own state. Rationale: Oneiric is the persistence substrate per ADR-017; substrate state is Oneiric's responsibility. **Confirmed 2026-09-14.** No double-storage between Dhara and Oneiric. **Re-evaluation point:** OQ #5 tracks whether the HTTP gateway should live on Mahavishnu instead (Phase 11 gateway-pattern evaluation will revisit this).

**Tasks:**

1. Port `dhara/mcp/substrate_routes.py` (531 LOC) to `oneiric/http/routes/substrate.py`.
2. Register with Oneiric's HTTP server. Add `oneiric http start|stop|status` subcommand (analog to `oneiric mcp start|stop|status`).
3. Update `.claude/decisions/mcp-backend-wiring-discipline.md` if it referenced these routes as Dhara's.
4. Add per-route health aggregator: each HTTP route registers a `ComponentHealth` feed with `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`. `/health` returns 503 if any route is degraded.
5. Add integration test: `pytest oneiric/tests/integration/test_substrate_routes_e2e.py` — `curl http://localhost:<port>/substrate/settings` returns 200 with non-empty payload; same for `/substrate/context` and `/substrate/progress`.

**Hard cutover:**

- Dhara's `substrate_routes.py` deleted with Phase 8.
- Any external caller of the old Dhara HTTP API (`http://localhost:8683/substrate/*`) is broken. **Mitigation:** document the URL change in `docs/MCP_TOOLS_SPECIFICATION.md`; no backward compat.

**Integration contract:**

- **Triggered from:** `oneiric http start` (new subcommand); agents / scripts call via HTTP.
- **Returns to / updates:** Oneiric's substrate state (settings/context/progress); backed by Oneiric's persistence layer per ADR-017.
- **Demonstrable by:** `pytest oneiric/tests/integration/test_substrate_routes_e2e.py` returns exit 0; `curl http://localhost:<port>/substrate/settings` returns 200 with non-empty payload; `oneiric http health` returns 200 with 3 healthy feeds.
- **Rollback signal:** 5xx on substrate routes, or 0 entities_count on any feed, or any e2e test failure.
- **Observability added:** OTel span `oneiric.http.route.<name>` with attribute `route.name`, `route.duration_ms`. Per-feed signals at `oneiric http health.<route>`.

### Phase 8 — Retire Dhara MCP server

**Goal:** Delete `dhara/mcp/` entirely. Slim pyproject.toml. Cut Dhara v1.0.0. Provision alerting + migration guide + runbook + ecosystem health.

**Tasks:**

1. Delete `dhara/mcp/` directory (every file: `__init__.py`, `__main__.py`, `adapter_lookup.py`, `adapter_tools.py`, `agent_schema.py`, `auth.py`, `ecosystem_state.py`, `fastmcp_auth.py`, `kv_timeseries.py`, `middleware.py`, `profiles.py`, `server.py`, `server_core.py`, `signer_feed.py`, `skill_schema.py`, `substrate_routes.py`, `tools/`). **Explicit documentation for files not in §4.2's destination table** (resolves Agent B's "odd" finding):
   - **`adapter_lookup.py`** — internal lookup helper under `adapter_tools.py:adapter_lookup`; subsumed by Oneiric's `oneiric/mcp/tools/adapter_registry.py` port (Phase 1 task 3). Not exposed as an MCP tool; deletion-with-directory is correct.
   - **`server.py`** — alternative CLI entry point or ASGI host variant; distinct from `server_core.py` (which becomes Oneiric's `oneiric/mcp/server_core.py`). Phase 1 explicitly does NOT use this factory path (see §4.6 for the verified pattern). Deletion-with-directory is correct.
2. Delete `dhara/skills_signer/` (moved to Crackerjack in Phase 4).
3. Verify `aiosqlite` usage: if only used by `dhara/mcp/`, drop from `pyproject.toml`. If used by engine code (likely, since `AsyncFileStorage` wraps `AsyncSqliteStorage`), keep it. Decision recorded in pyproject comments.
4. Update `dhara/__init__.py` to drop MCP imports.
5. Update `dhara/cli.py` to remove `dhara mcp` subcommands (`dhara mcp start|stop|status|health|restart`).
6. Slim `dhara/pyproject.toml` per §4.4 (10 deps dropped; `oneiric` preserved).
7. **Surgical removal in `dhara/CLAUDE.md`** (data-retention MEDIUM #5 — the spec previously said "remove MCP server section" but the file has MCP references across 7+ sites, not one section): line 100 (`dhara mcp stop` example), line 145 (directory tree `├── mcp/`), lines 470-485 (dedicated MCP server section), line 620 (Bodai MCP server /health rule), plus any other `mcp\|MCP` occurrences. Verify by `grep -n "mcp\|MCP" /Users/les/Projects/dhara/CLAUDE.md` returning 0 occurrences after the cutover (or only references to upstream MCP servers like Bodai's `mcp-common`). The directory tree snippet also drops `├── mcp/` and updates the "engine + CLI" surface count.
8. Update `dhara/CHANGELOG.md` (data-retention HIGH #1 + MEDIUM #7):
   - Fix the stale "MIT License" line at the bottom (line 875 — wrong; pyproject.toml says BSD-3-Clause).
   - **Consolidate both `[Unreleased]` sections** (lines 172 and 676) into the canonical one above `0.19.0`. The second block covers `BodaiCLIBase` → `OneiricCLIBase` rename, `__missing__` support, PyPy compatibility — all of which shipped in 0.18.0 and 0.17.2.
   - **Add a NEW `[Unreleased]` entry** that records the decomposition: "MCP server retired; 21 tools removed; Dhara becomes engine-only library; v1.0.0 signal."
   - **Add contextual annotation to the 0.20.0 entry** (which added `Phase 1.5 ed25519 skills_signer infrastructure`): "**Superseded by v1.0.0 (2026-09-14):** This entry's MCP surface was retired one day after release; ed25519 signer moved to Crackerjack (see `2026-09-14-dhara-mcp-decomposition-design.md` Phase 4)."
9. **Grep Dhara docs for MCP references:** `grep -rn "dhara mcp\|mcp__dhara__\|dhara.*MCP.*server" /Users/les/Projects/dhara/` — update `DHARA_MODES_QUICK_REFERENCE.md`, `QUICKSTART.md`, `README.md`, and any other docs that reference the MCP server.
10. Update `dhara/tests/unit/test_wiring.py` (golden fixture for `tests/fixtures/{minimal,standard,full}/tool_names.json`) — delete or empty out since Dhara no longer has tool profiles.
11. Update `dhara/tests/unit/test_profiles.py` for the slimmed profile list (or delete entirely).
12. Delete `dhara/tests/integration/test_<mcp-tool>_e2e.py` files (no longer applicable).
13. Verify exit criteria: `python scripts/audit_orphans.py --days 14` reports zero new orphans in Dhara (after the MCP-related symbols are deleted). If the audit flags recently-removed MCP symbols as "orphans" within the lookback window, document the exemption.
14. Update `BODAI_REPO_REGISTRY.md` — Dhara's role tag shifts from `mcp_server` to `engine`.
15. **User-controlled publish step:** user runs `crackerjack run -p major` to bump Dhara's version to 1.0.0 and publish to PyPI. Per `feedback-mcp-common-version-bump-is-user` memory: the agent never bumps Bodai versions; the user does.
16. **Provision Grafana Alertmanager rules** (observability HIGH #2 / alert routing): create `monitoring/grafana/alertmanager-rules.yaml` with rules covering all 4 Bodai MCP servers. Each rule: alert when `/health` returns 503 sustained for ≥2 minutes; page the Bodai on-call channel. Verify with `amtool check-config monitoring/grafana/alertmanager-rules.yaml`. Commit alongside the Phase 8 retirement.
17. **Create `docs/runbooks/bodai-mcp-incident.md`** (observability MEDIUM #4): list all 4 `mcp` servers' `/health` URLs (Oneiric:8683, Mahavishnu:8680, Akosha:8682, Crackerjack:8676), the dependency graph (which tool calls which), trace-context propagation rules per §4.8, and incident-response runbook per failure mode.
18. **Add `mahavishnu mcp ecosystem health`** Typer sub-command (observability MEDIUM #4): fans out to all 4 `/health` endpoints, returns aggregate response, surface-level aggregate status. Demonstrable by `mahavishnu mcp ecosystem health` returning a structured response with per-server status and aggregate.
19. **Implement `dhara migrate kv-timeseries`** CLI (data-retention MEDIUM #4 / §4.10): bulk-write historical KV/time-series records from Dhara's on-disk file to the Oneiric cache adapter `oneiric.adapters.cache.persistent_kv`. Run once during Dhara uninstall, before upgrading to v1.0.0. Documents the migration in `dhara/MIGRATION.md` "Before upgrading" section.
20. **Create `dhara/MIGRATION.md`** (data-retention HIGH #2 / §4.9): top-level migration guide with old-name → new-name mapping table, hard-cutover date, notification channels (email `nas-dhara@arctrix.com`, GitHub Discussions pinned issue, PyPI long-description lead), per-consumer migration instructions.
21. **Update `docs/MCP_TOOLS_SPECIFICATION.md`** (data-retention HIGH #2): add a top-of-file breadcrumb pointing to `dhara/MIGRATION.md`, and a new section 28 "Migration Guide — Hard Cutover 2026-09-14" with the old-name → new-name mapping (or directly lift from §4.2 + §8 of this spec).

**Tests to update (post-deletion):**

- Delete `dhara/tests/integration/test_<mcp-tool>_e2e.py` files.
- Update `dhara/tests/unit/test_wiring.py` (golden fixture).
- Update `dhara/tests/unit/test_profiles.py` for the slimmed profile list.

**Integration contract:**

- **Triggered from:** `pip install dhara` (no MCP surface; library + CLI only). User runs `crackerjack run -p major` to publish.
- **Returns to / updates:** Dhara 1.0.0 on PyPI; alert routing live; MIGRATION.md published; runbook live.
- **Demonstrable by:** `python -c "import dhara; print(dhara.__version__)"` prints `1.0.0`; `dhara db start --port 8685` works; `dhara db client --port 8685` connects; `python scripts/audit_orphans.py --days 14` reports zero orphans; `grep -rn "dhara mcp\|mcp__dhara__" /Users/les/Projects/` returns no references outside `docs/plans/` historical records; `amtool check-config monitoring/grafana/alertmanager-rules.yaml` returns OK; `mahavishnu mcp ecosystem health` returns aggregate response.
- **Rollback signal:** None (this is a release, not a runtime feature).
- **Observability added:** Alertmanager rules live; MIGRATION.md published; runbook live. Per-feed observability for all 4 Bodai MCP servers feeds the alertmanager.

**Tests to update (post-deletion):**

- Delete `dhara/tests/integration/test_<mcp-tool>_e2e.py` files.
- Update `dhara/tests/unit/test_wiring.py` (golden fixture).
- Update `dhara/tests/unit/test_profiles.py` for the slimmed profile list.

**Integration contract:**

- **Triggered from:** `pip install dhara` (no MCP surface; library + CLI only).
- **Returns to / updates:** Dhara 1.0.0 on PyPI.
- **Demonstrable by:** `python -c "import dhara; print(dhara.__version__)"` prints `1.0.0`; `dhara db start --port 8685` works; `dhara db client --port 8685` connects; `python scripts/audit_orphans.py --days 14` reports zero orphans; `grep -rn "dhara mcp\|mcp__dhara__" /Users/les/Projects/` returns no references outside `docs/plans/` historical records.
- **Rollback signal:** None (this is a release, not a runtime feature).
- **Observability added:** PyPI download count + import-time version check.

### Phase 9 — Update active plan and Phase 11

**Goal:** The active serverless-readiness plan and its Phase 11 (Harness-agnostic enablement) reflect the new component topology. External migration guide is published.

**Tasks:**

1. **Update `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`** (data-retention MEDIUM #6 — both the description text and the REQ table need updating):
   - **Phase 4 description** (line 566): add "MCP surface moved per `2026-09-14-dhara-mcp-decomposition-design.md`" alongside the existing goal sentence.
   - **Phase 4 REQ citations** in §4.5 (lines 467-472): REQ-DHARA-STORAGE's "Target file" column should read `oneiric/mcp/server_core.py:141-148` (per the decomposition spec's table 4.7), not `dhara/dhara/mcp/server_core.py:141-148`.
   - **Phase 11** (Harness-agnostic enablement): redirect Qwen Code / Claude Code validation tests from `mcp__dhara__*` to the new homes per the explicit tool-name table below.
2. **Update `docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md` precondition plan:** add `2026-09-14-dhara-mcp-decomposition-design.md` to the precondition plan's `related:` frontmatter. **Note:** the precondition plan has no Dhara MCP REQs to update (its 14 REQs are all text edits / governance fixes, none touch Dhara MCP code paths) — the previous draft's task 2 was a no-op.
3. Update cross-references in `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` (Option C amendment — overturning the 2026-09-14 amendment, see §4.7), `docs/adr/017-oneiric-shared-persistence-substrate.md` (clarify that Oneiric now has an MCP server).
4. **If the Phase 1 commit did not include the ADR-013 reversal amendment, apply it now** (covers edge case where Phase 1 shipped without the amendment; Phase 9 is the safety net).
5. **Pin a GitHub Discussions thread** at `https://github.com/lesleslie/dhara/discussions` with the migration guide and a "subscribe for breaking-change notifications" callout. Update `dhara/CHANGELOG.md` v1.0.0 entry with the discussion URL.
6. **Email notification** to `nas-dhara@arctrix.com` subscribers (per Dhara's existing contact pattern, line 871): "Dhara v1.0.0 released; 21 `mcp__dhara__*` tools removed; see MIGRATION.md." The user controls this email (not agent-driven) per `feedback-bodai-push-is-user-controlled`.

**Phase 11 explicit tool-name redirect table.** Phase 11's REQ-HARNESS-TEST-MATRIX-QWEN (and Claude Code equivalent) currently validates against `mcp__dhara__*` tools. After Phase 8, those tools are gone. The redirect:

| Was (pre-Phase-8) | Now (post-Phase-8) | Test surface |
|-------------------|---------------------|--------------|
| `mcp__dhara__list_adapters` | `mcp__oneiric__list_adapters` | Oneiric adapter discovery |
| `mcp__dhara__get_adapter` | `mcp__oneiric__get_adapter` | Oneiric adapter lookup |
| `mcp__dhara__store_adapter` | `mcp__oneiric__store_adapter` | Oneiric adapter registration |
| `mcp__dhara__upsert_service` | `mcp__mahavishnu__ecosystem_upsert_service` | Mahavishnu ecosystem service registration |
| `mcp__dhara__list_services` | `mcp__mahavishnu__ecosystem_list_services` | Mahavishnu ecosystem service listing |
| `mcp__dhara__record_event` | `mcp__mahavishnu__ecosystem_record_event` | Mahavishnu ecosystem event log |
| `mcp__dhara__list_agents` | `mcp__crackerjack__list_agents` | Crackerjack agent catalog |
| `mcp__dhara__list_skills` | `mcp__crackerjack__list_skills` | Crackerjack skill catalog |
| `mcp__dhara__query_local_traces` | `mcp__akosha__query_local_traces_fitness` | Akosha trace query (fitness-shaped) |
| `mcp__dhara__sql_query` / `dhara_sql_execute` | **deleted** (no replacement) | — |
| `mcp__dhara__put` / `dhara_get` / `dhara_list_prefix` / `dhara_record_time_series` / `dhara_query_time_series` / `dhara_aggregate_patterns` | **deleted as MCP tools** (replaced by Oneiric cache adapter `oneiric.adapters.cache.persistent_kv`, not exposed as MCP tool) | Oneiric resolver, not MCP |

**Phase 11 name-uniqueness re-verification.** Per §6 R7 (Phase 11 harness-portability checklist must re-verify name uniqueness *after* Dhara MCP is fully retired, not at Phase 11 ship time). The 197-tool Bodai MCP surface must be re-validated for Qwen Code's 63-char name truncation constraint once Dhara's tools are gone.

### Phase 10 — Postgres consolidation hygiene

**Goal:** Resolve dormant pgvector code paths in AkoSHA and Mahavishnu, fix Oneiric's invalid OTel default URL, and complete the sed-replication cleanup of `agent_schema.py` / `skill_schema.py` per §4.12. **Both pgvector decisions must land in the same release** — two components carrying dormant pgvector code paths is technical debt that blocks ADR 017's "Oneiric is the substrate" promise.

**Pre-flight gate (resolves OQ #6):** The canonical `agent_schema.py` / `skill_schema.py` files now live in `mcp-common.canonical_schemas` (Phase 4 tasks 2 and 4 ship them there). Phase 10 task 2 then **deletes the sed-replicated copies** in AkoSHA / Session-Buddy / Mahavishnu and forces those components to import from the canonical home. Pre-flight: `grep -rn "agent_schema\|skill_schema" /Users/les/Projects/{mahavishnu,akosha,session-buddy}/` returns only `mcp-common` import paths (no local schema files).

**Tasks:**

1. **AkoSHA pgvector path — commit or delete.** Two options:
   - **Option A (commit):** add `AKOSHA__STORAGE__HOT__PG_URL` to `akosha/.envrc.example` (a real local Postgres DSN the operator can override); fix the Oneiric upstream bug (`WITH (lists := 100)` rejected by Postgres 18) so `akosha/tests/integration/test_pgvector_hot_store_e2e.py` actually runs; commit a CI workflow that spins up Postgres 16 + 17 + 18 to verify all three. Production-grade option; honors the adapter-layer investment.
   - **Option B (delete):** delete `akosha/storage/pgvector_hot_store.py` (241 LOC) + `akosha/tests/integration/test_pgvector_hot_store_e2e.py` + `akosha/tests/unit/test_main_start_hot_store_wiring.py`; remove `pgvector` from `akosha/settings/akosha.yaml:96-99`; remove any `pg_url` references from `akosha/akosha/config.py:84-89`. Reduces AkoSHA's surface to its actual production backend (DuckDB).
   - **Default: Option B (delete).** Rationale: AkoSHA has shipped pgvector support since 0.17.x with no production adoption; the dormant code path is technical debt, not a feature. ADR 017 explicitly rejected "mandate Postgres for everything" (lines 122-128). Deletion aligns with the substrate framing. **Demonstrable by:** `grep -rn "pgvector\|pg_url" akosha/` returns 0 matches after the commit; AkoSHA's e2e test suite passes on DuckDB-only.
2. **Mahavishnu pgvector path — commit or delete.** Two options:
   - **Option A (commit):** wire `MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING` to a real Postgres URL in `mahavishnu/settings/local.yaml`; fix the Oneiric OTel default URL (task 3 below) so Mahavishnu's stricter validator accepts it; commit `mahavishnu/migrations/` Postgres DDL as the canonical Mahavishnu schema.
   - **Option B (delete):** delete `mahavishnu/adapters/pgvector_adapter.py` (685 LOC) + `mahavishnu/tests/unit/test_adapters_pgvector_adapter.py` + `mahavishnu/examples/otel_pgvector_test.py`; remove `mahavishnu/migrations/` directory (Postgres DDL); remove `OTelStorageConfig` from `mahavishnu/core/config.py:782-918`; remove `OTelIngesterConfig.storage_type` from `mahavishnu/core/config.py:943-995`; simplify `OTelIngester._initialize_pgvector` to `OtelIngester._initialize_duckdb_only` (`mahavishnu/ingesters/otel_ingester.py:611-636`); remove pgvector branch from `_ingest_trace_pgvector` (`mahavishnu/ingesters/otel_ingester.py:754`).
   - **Default: Option A (commit) — but ONLY if Phase 5 task 9 also commits to Postgres-only persistence** (Option B in Phase 5 task 9). Rationale: keeping pgvector code paths live while committing Postgres-only persistence is incoherent; if we choose Postgres as the substrate, the OTel traces should live there too. **If Phase 5 task 9 chose Option A (Dhara only):** Mahavishnu's pgvector path goes the same way (Option B / delete).
3. **Fix Oneiric's invalid OTel default URL.** `oneiric/adapters/observability/settings.py:7-52` defaults `OTelStorageSettings.connection_string` to `"postgresql://postgres: postgres@localhost: 5432/otel"` — **spaces around the colon** that Mahavishnu's validator (`mahavishnu/core/config.py:880-916`) would reject. Two options:
   - **Option A (fix the default):** change the default to `"postgresql://postgres:postgres@localhost:5432/otel"` (no spaces).
   - **Option B (make Oneiric's `OTelStorageSettings` the canonical model Mahavishnu imports):** Mahavishnu imports `from oneiric.adapters.observability.settings import OTelStorageSettings` instead of redefining the field in `mahavishnu/core/config.py:782-918`. Validator is moved into Oneiric.
   - **Default: Option B (canonical import).** Aligns with ADR 017's "Oneiric owns the substrate" framing; removes the duplicated config model.
4. **Delete sed-replicated `agent_schema.py` / `skill_schema.py`** in AkoSHA / Session-Buddy / Mahavishnu. Files to delete:
   - `akosha/mcp/agent_schema.py`, `akosha/mcp/skill_schema.py` (the canonical source — these are the files that AkoSHA owns today; deletion moves the canonical home to `mcp-common`)
   - `mahavishnu/mcp/agent_schema.py`, `mahavishnu/mcp/skill_schema.py` (sed-replicated copies)
   - `session-buddy/mcp/agent_schema.py`, `session-buddy/mcp/skill_schema.py` (sed-replicated copies)
   - `crackerjack/mcp/agent_schema.py`, `crackerjack/mcp/skill_schema.py` (sed-replicated copies — Phase 4 ships the import-from-canonical-home change)
   - All consumers update to `from mcp_common.canonical_schemas.agent import ...` and `from mcp_common.canonical_schemas.skill import ...`. **Demonstrable by:** `grep -rn "agent_schema\|skill_schema" /Users/les/Projects/{mahavishnu,akosha,session-buddy,crackerjack}/` returns only `mcp_common.canonical_schemas` import paths; each component's `list_agents` / `list_skills` / `get_agent` / `get_skill` tool continues to work (verified by Phase 1.5 task 3 e2e tests).
5. Add e2e tests in `mcp-common/tests/integration/test_canonical_schemas_e2e.py` — assert the canonical schemas are importable from all four components and produce identical `AdapterMetadata` / `SkillMetadata` shapes for the same input. Demonstrable by the e2e suite passing on the four components' test matrix.

**Integration contract:**
- **Triggered from:** AkoSHA / Mahavishnu's CI run + Phase 5 task 9's substrate decision.
- **Returns to / updates:** AkoSHA and Mahavishnu's pgvector paths are either live (with real Postgres URLs) or deleted; Oneiric's OTel default is fixed; the four sed-replicated schema files are gone.
- **Demonstrable by:** `grep -rn "pgvector" /Users/les/Projects/{mahavishnu,akosha}/` returns 0 matches (Option B) OR a real CI workflow runs the pgvector e2e suite (Option A); `grep -rn "agent_schema\|skill_schema" /Users/les/Projects/{mahavishnu,akosha,session-buddy,crackerjack}/` returns only `mcp_common` import paths.
- **Rollback signal:** e2e test fails, OR AkoSHA / Mahavishnu reports `entities_count == 0` after pgvector is committed live.
- **Observability added:** the canonical-schemas e2e test surfaces schema-shape stability across components.

### Phase 11 — Gateway pattern evaluation (post-Phase-10)

**Goal:** After Phase 10 lands, evaluate whether to mount the four component libraries (Mahavishnu, AkoSHA, Crackerjack, Oneiric) under a single Mahavishnu MCP gateway process. **This is an evaluation, not a commitment.** The decision lives in a follow-up spec if the operator chooses to proceed.

**Pre-flight gate:** Phase 10 must have shipped. Phase 1.5 wrapper consolidation must have shipped (so each component's surface is already mostly shared infrastructure, leaving only domain tools). Phase 5 task 9 substrate decision must be in (single-source persistence). Without these preconditions, Phase 11's evaluation cannot make a clean call.

**Tasks:**

1. **Document the gateway trade-offs** in `docs/adr/018-gateway-pattern-evaluation.md`. Three options:
   - **Option A (status quo — four processes):** keep current architecture. Preserves independent release cadence for each component; per-component failure isolation. Costs: 4 launchd plists, 4 health endpoints, 4 mcp-common instantiations, 4 auth secret env vars.
   - **Option B (gateway — one process, four libraries):** Mahavishnu becomes the only MCP server process; AkoSHA / Crackerjack / Oneiric expose their tools via `mcp_common.tools.dispatch.register_remote_tools(server, namespace="akosha"|"crackerjack"|"oneiric", tools=[...])` — a generalization of the Phase 1.5 `register_local_namespace` primitive. Single auth surface, single `/health`, single set of launchd plists. Costs: single point of failure, coordinated release for cross-component API changes, larger Mahavishnu binary.
   - **Option C (hybrid — gateway for read-only, direct for stateful):** Mahavishnu gateways read-only wrapper tools (the Phase 1.5 consolidated wrappers); stateful domain tools stay in their own process. Splits the operational complexity cleanly: gateway handles the cross-cutting infra, components handle the stateful work.
2. **Estimate the cost of each option** with concrete metrics: launchd plist count, /health endpoint count, auth secret env vars, OTel span propagation overhead, cross-component MCP call latency, operator muscle-memory disruption.
3. **Recommend one option** based on the Phase 10 substrate outcomes (whether Postgres is the substrate or Dhara-as-engine is).
4. **If Option B or C is recommended:** write a follow-up spec (`docs/superpowers/specs/2026-XX-XX-gateway-pattern-implementation.md`) describing the migration. The follow-up spec gets its own reviews and its own implementation plan.

**Integration contract:**
- **Triggered from:** ADR 018's option recommendation.
- **Returns to / updates:** either "do nothing" (Option A) or a follow-up spec for Option B/C.
- **Demonstrable by:** ADR 018 lands with a concrete option recommendation + metrics.
- **Rollback signal:** none (evaluation, not a runtime feature).

### Phase 12 — Hook bus coordination — added 2026-09-14

**Goal:** The existing JSON-file hook queue (`~/.mahavishnu/bodai-event-queue.json`) is the in-house event surface. Phase 12 introduces a canonical handler with per-harness bridges and re-platforms to `oneiric.adapters.queue.redis_streams`. **Hard cutover** — no dual-write state. **Post-event hooks only** get bus arms; sync-blocking events (`PreToolUse`, `SubagentStop`, `UserPromptSubmit`, `Stop`, `UserPromptExpansion`) stay sync per spec §4.13.3.

**Demonstrable by:** `pytest tests/integration/test_hook_bridge_e2e.py` returns exit 0; `oneiric mcp health.hook_bridge_feed.entities_count > 0` after one Claude session; `grep -rn "bodai-event-queue" mahavishnu/` returns 0 hits.

**Triggered from:** Claude Code runs the bridge wrapper; git invokes the bash wrapper; pre-existing `mahavishnu/events`-style modules emit to the bus.

**Returns to / updates:** `oneiric.adapters.queue.redis_streams` channel `bodai.hooks.*` (subject: `event_name`; body: canonical envelope per spec §4.13.2).

**Rollback signal:** subscribed consumers (jot drainer, observability) show empty queue after warmup; existing Claude-specific behavior (worktree isolation, license-guard) doesn't fire.

**Observability added:** per-feed `hook_bridge_feed.entities_count`, `.cycles_total`, `.errors_total`. New OTel spans per hook event.

#### Phase 12a — Claude hook bridge + git-hook wrappers + JSON-queue hard cutover

0. **Pre-flight gate** — `ls -la mahavishnu/.claude/hooks/*.py | grep -v __pycache__` should list 7 files: `_hook_io.py`, `bodai-activity-post-tool-use.py`, `bodai-activity-subscriber.py`, `jot-capture.py`, `jot-post-tool-use.py`, `jot-session-start.py`, `worktree-session-isolation.py`. The 4 active git hooks are `mahavishnu/.git/hooks/{pre-commit, post-commit, post-merge, post-rewrite}`.
1. **Create `mahavishnu/bodai_hook_bridge.py`** — canonical handler. Each existing Claude hook's body becomes a named function (`handle_post_tool_use`, `handle_session_start`, `handle_pre_tool_use`, etc.). `read_stdin()` re-exports the existing `_hook_io.HookPayload` shape. Each handler runs the existing logic AND publishes a normalized event to `oneiric.adapters.queue.redis_streams` (fire-and-forget). Sync-blocking events skip the post-event publish step per §4.13.3; the canonical handler still runs.
2. **Replace `mahavishnu/.claude/hooks/*.py` with bridge wrappers** — each file becomes:
   ```python
   #!/usr/bin/env python3
   import sys, json, os
   sys.path.insert(0, os.environ["CLAUDE_PROJECT_DIR"])
   from bodai_hook_bridge import handle
   payload = json.load(sys.stdin) or {}
   event = payload.get("hook_event_name", "?")
   handle(event_name=event, harness="claude", payload=payload)
   ```
   The legacy Python logic moves into `bodai_hook_bridge.py` named functions; the bridge file becomes a thin dispatcher. Per `claude-code-hook-commands-use-claude-project-dir` memory, hooks anchor with `$CLAUDE_PROJECT_DIR` so this works in sibling repos.
3. **Add `mahavishnu git-hook <event>` Typer sub-command** — git hook entry. Event handlers `post_commit`, `post_merge`, `post_rewrite`, `pre_commit` re-implement the existing 378-662-byte action lines from `.git/hooks/<event>` (which are not version-controlled — git hooks live per-clone) and publish to the bus. The git hook script shrinks to:
   ```bash
   #!/bin/bash
   exec mahavishnu git-hook post-commit "$@"
   ```
4. **Update `.git/hooks/<event>` shell scripts** to call the new Typer sub-command (per the local git checkout — operator commit).
5. **Hard-cutover the JSON-file queue** — `bodai-activity-subscriber.py` rewrites to consume Redis Streams only; the JSON-file write path is deleted. Other producers that wrote to the queue (e.g. `mahavishnu/jot/drain.py`, `mahavishnu/mcp/tools/jot_tools.py` consumers) publish directly to the bus instead. Verify: `grep -rn "bodai-event-queue\|bodai-event-queue\.json" mahavishnu/` returns 0 hits after Phase 12a commits.
6. **Add `tests/integration/test_hook_bridge_e2e.py`** — asserts:
   - `BodaiHookBridge.handle("PostToolUse", harness="claude", payload={...})` invokes the canonical handler.
   - Publish reaches `oneiric.adapters.queue.redis_streams` channel `bodai.hooks.post-tool-use`.
   - `mahavishnu git-hook post-commit` runs the legacy crackerjack action AND publishes to the bus.
   - The JSON-file queue is no longer written.
   - `PreToolUse` returns exit 2 unchanged (sync-blocking preserved).
7. **Commit** — same-commit guard: producers and consumers flip together.

#### Phase 12b — Qwen Code bridge + Codex bridge (deferred)

1. **Inventory Qwen events with no Claude equivalent** — `PostToolUseFailure`, `SessionDelete`, `MessageDisplay`, `StopFailure`, `SubagentStart`, `PreCompact`, `PostCompact`, `PermissionRequest`, `PermissionDenied`, `TodoCreated`, `TodoCompleted`. Each gets a canonical handler function in `mahavishnu/bodai_hook_bridge.py`.
2. **Create `~/.qwen/hooks/<event>` bridge files** — 10-line scripts that normalize Qwen's JSON to the canonical envelope and invoke the canonical handler. Both Claude and Qwen field semantics per spec §4.13.2.
3. **Update `~/.qwen/settings.json`** to register bridges for each event.
4. **Add `tests/integration/test_qwen_hook_bridge_e2e.py`** — asserts the Qwen bridge normalizes correctly.
5. **Codex bridge deferred to when Codex ships hooks** — no-op until Codex docs land; same ~15-line-per-event pattern.

## 6. Risks & Mitigations

### R1 — Hard cutover breaks internal callers of `mcp__dhara__*` tools

**Risk:** Code in Mahavishnu, agents, or external repos that calls `mcp__dhara__*` tools fails immediately at the commit boundary. No deprecation window by user decision 2026-09-14.

**Mitigation:** Phase 1 task #0 enumerates every `mcp__dhara__*` reference across the Bodai ecosystem (86 hits found by grep). Each consumer is updated in the same commit as the tool's deletion. External consumers (outside Bodai) are documented in `docs/MCP_TOOLS_SPECIFICATION.md` migration guide (§6). 86 hits is a tractable number; verified grep scope at Phase 1 start.

### R2 — Phase 4 (Crackerjack skill signing) requires Crackerjack to grow

**Risk:** Crackerjack's surface area grows by ~1,830 LOC (1,429 LOC code + ~400 LOC tests/scaffolding). The Crackerjack maintainer may not want this scope.

**Mitigation:** Phase 1.5 of the active ACP plan already routes skill distribution through Crackerjack. This spec just delivers what was already designed. If Crackerjack's maintainer objects, defer Phase 4 and leave `mcp__dhara__list_skills` etc. in place longer (delays Phase 8 retirement).

### R3 — Phase 2 auth audit reveals Dhara-specific auth behavior

**Risk:** If Dhara's `TokenAuth` (file-based SHA-256 with roles) has Dhara-specific semantics that some Bodai consumer relies on, Phase 1's new Oneiric MCP server (using `mcp_common.auth`) might not match.

**Mitigation:** Phase 1 builds the Oneiric server with `mcp_common.auth.middleware` from day one. **Dhara's auth goes away with the server in Phase 8** — there is no consumer of `dhara.mcp.auth.*` that survives the deletion. If Phase 1's e2e tests fail because of missing auth semantics, the failure surfaces immediately and gets fixed before Phase 8 retires Dhara.

### R4 — Bodai app registry / launchd plists still reference `mcp_server` role for Dhara

**Risk:** Dhara's launchd plist on the operator's machine (if any) tries to start `dhara mcp` and fails after Phase 8.

**Mitigation:** Phase 8 includes updating `BODAI_REPO_REGISTRY.md` and any launchd plists. Document the breaking change in the spec's "What Changes for Operators" section. Oneiric MCP server takes port 8683 (Dhara's old port) — the Dhara launchd plist must be retired entirely.

### R5 — External consumers (outside Bodai ecosystem) of `mcp__dhara__*` tools

**Risk:** Unknown number of consumers use `mcp__dhara__*` directly outside the Bodai ecosystem. Hard cutover (user decision 2026-09-14) means external consumers break immediately at the commit boundary.

**Mitigation (specific channels, not hand-waved):**
1. **`dhara/MIGRATION.md`** (top-level, not buried in spec) — created in Phase 8 task 20. Contains the old-name → new-name mapping table, hard-cutover date, and per-consumer migration instructions.
2. **CHANGELOG header callout** — Dhara's `CHANGELOG.md` v1.0.0 entry leads with "BREAKING: 21 `mcp__dhara__*` tools removed; see https://github.com/lesleslie/dhara/blob/v1.0.0/MIGRATION.md".
3. **PyPI long-description** — Dhara's README first 200 chars lead with the migration link (above-the-fold on PyPI).
4. **GitHub Discussions pinned issue** — pinned at `https://github.com/lesleslie/dhara/discussions` (Phase 9 task 5).
5. **Email** to `nas-dhara@arctrix.com` subscribers (Phase 9 task 6, user-controlled).

### R6 — Oneiric's `dhara_pusher` adapter and hardcoded Dhara 8683 references

**Risk:** Oneiric has 4+ hardcoded references to Dhara on port 8683:
- `oneiric/QUICKSTART.md` (lines 119, 150)
- `oneiric/adapters/dhara_pusher.py` (lines 55, 214, 253, 263) — defaults to `http://127.0.0.1:8683`
- `oneiric/tests/test_dhara_pusher_coverage.py` (lines 43, 99)
- `oneiric/tests/unit/adapters/test_tracked_settings.py` (6 occurrences)

The `dhara_pusher.py` adapter is the most consequential: its purpose is to push adapter metadata *to* Dhara. After Phase 1, the destination changes (Oneiric owns its own registry).

**Mitigation:** Phase 1 task 16 retires `dhara_pusher.py` entirely (deletes the file, the tests, the QUICKSTART references, the entry points). No retargeting. The "push to a separate Dhara MCP" pattern is incoherent once Oneiric owns its own registry.

### R7 — Phase 11 harness-portability name uniqueness re-verification

**Risk:** Phase 11's REQ-HARNESS-TEST-MATRIX-QWEN validates Qwen Code's 197-tool Bodai MCP surface for name uniqueness (Qwen truncates names >63 chars). If Phase 11 ships during the same window as this spec's earlier phases, the harness's tool-name table will see *both* `mcp__dhara__list_adapters` (still present pre-Phase-8) and `mcp__oneiric__list_adapters` (just added) — two surfaces for the same concept, contradicting the Phase 11 uniqueness claim.

**Mitigation:** Phase 11's name-uniqueness checklist must re-verify *after* Dhara MCP is fully retired (post-Phase-8), not at Phase 11 ship time. Phase 9 of this spec updates Phase 11's redirect table.

### R8 — Audit-trail gaps in Dhara's CHANGELOG and CLAUDE.md (data-retention HIGH #1 + MEDIUM #5)

**Risk:** Dhara's `CHANGELOG.md` has TWO `[Unreleased]` sections (lines 172 and 676) with overlapping content; `dhara/CLAUDE.md` has MCP references across 7+ sites (lines 100, 145, 470-485, 620, plus others). Phase 8 task 7 originally said "remove MCP server section" but the file has MCP references spread across the document, not in a single section. Future contributors grepping for `skills_signer` or `mcp_server` will land on entries that no longer reflect the post-Phase-8 state.

**Mitigation:**
- Phase 8 task 7 surgical-removal grep across `dhara/CLAUDE.md` (verify `grep -n "mcp\|MCP"` returns 0 after cutover).
- Phase 8 task 8 CHANGELOG consolidation: merge both `[Unreleased]` blocks; add new v1.0.0 entry recording the decomposition; add contextual annotation to the 0.20.0 entry explaining that the MCP surface shipped and retired within 24 hours.
- Phase 9 task 5 pins a GitHub Discussions thread for long-term migration support.

### R9 — Oneiric MCP server primitives that don't yet exist

**Risk:** The spec cites `HealthMonitor.record_invocation`, `set_entities_count`, `get_feed`, and per-feed `ComponentHealth` lookup as ready-to-use primitives. They are not implemented in `oneiric/runtime/mcp_health.py` today. Phase 1 cannot ship without them. Without these primitives, Phase 1 task 8's e2e test ("/health returns 200 with 7 healthy feeds on warm startup") cannot construct feeds with non-zero `cycles_total` and read per-feed signals.

**Mitigation:** Phase 1 task 6 explicitly extends `HealthMonitor` with the primitives. The extension is small (~50 LOC) but is a precondition for the e2e test passing. Without it, Phase 1 is broken at runtime despite looking correct on paper.

### R10 — Dormant pgvector code paths (AkoSHA + Mahavishnu)

**Risk:** Both AkoSHA and Mahavishnu ship full pgvector code paths that are wired in code but disabled in committed config:
- AkoSHA: `hot_store.pg_url: ""` (`akosha/settings/akosha.yaml:95`); `akosha/tests/integration/test_pgvector_hot_store_e2e.py` gated on `AKOSHA_TEST_PGVECTOR_URL` (header docstring notes Oneiric upstream bug `WITH (lists := 100)` rejected by Postgres 18 blocking the suite).
- Mahavishnu: `otel_storage.enabled=false` (`mahavishnu/settings/mahavishnu.yaml:59`); `persistence.postgres_url=""` (`mahavishnu/settings/mahavishnu.yaml:144`).

Carrying dormant pgvector code paths ages badly: the upstream APIs (asyncpg, pgvector extension versions, Oneiric adapter changes) drift; the integration test never runs; the CI never catches the rot. Two components with dormant pgvector also block ADR 017's "Oneiric is the substrate" framing — the substrate is shared, but each component re-implements its own pgvector layer.

**Mitigation:** Phase 10 commits-or-deletes both pgvector paths in the same release. The decisions are coupled to Phase 5 task 9's substrate choice: if Phase 5 picks Option B (Postgres-only substrate), Mahavishnu keeps pgvector live (commit Option A in Phase 10); if Phase 5 picks Option A (Dhara-only substrate), Mahavishnu deletes pgvector (delete Option B in Phase 10). AkoSHA's decision defaults to delete (no production adoption since 0.17.x; ADR 017 explicitly rejected mandate-Postgres). Phase 10's e2e tests + integration tests catch the rot before it ships.

### R11 — Mahavishnu dual-write mode (`persistence.write_mode: "dual"`)

**Risk:** `mahavishnu/settings/mahavishnu.yaml:140` shows `persistence.write_mode: "dual"` — Mahavishnu writes to BOTH Dhara (legacy) AND Postgres simultaneously. Dual-write is a migration state, not a steady state. **Without Phase 5 task 9 committing a single-source decision, the spec's "decompose Dhara's MCP" goal is undermined** — Dhara's substrate role is not cleanly retired while Mahavishnu keeps dual-writing to it. Operators who read the spec and try to retire Dhara-as-substrate will find Mahavishnu still writing there.

**Mitigation:** Phase 5 task 9 commits to single-source persistence (default Option B = Postgres-only, per ADR 017 substrate ownership). Phase 5 removes `write_mode: "dual"` from `mahavishnu/settings/mahavishnu.yaml:140`; Phase 5 documents the Option A (Dhara-only) fallback path in `docs/ops/persistence-modes.md` for operators who cannot migrate to Postgres immediately. Phase 5's e2e tests + the Dhara-as-engine connection (`dhara db start --port 8685`) demonstrate that the engine stays available for non-Mahavishnu consumers.

### R12 — Hook migration hard-cutover breaks in-process subscribers (added 2026-09-14)

**Risk:** Phase 12a hard-cuts from `~/.mahavishnu/bodai-event-queue.json` to `oneiric.adapters.queue.redis_streams`. Any in-process Bodai code still writing to (or reading from) the JSON file breaks immediately at the commit boundary. Examples: `mahavishnu/jot/drain.py` may write envelopes; `mahavishnu/mcp/tools/jot_tools.py` consumers may read them; external subscribers may be on the file path.

**Mitigation:** Phase 12a task 5 enumerates every producer and reader in `mahavishnu/` before the cutover (mirrors Phase 1 task #0's enumeration discipline). Each one updates in the same commit as the file's deletion. External consumers documented in `docs/runbooks/hook-migration.md`. The hard-cutover stance matches the spec's user-2026-09-14 decision (no deprecation window); the alternative — dual-write — is rejected per Phase 5 R11 cautionary tale.

## 7. Open Questions

All resolved 2026-09-14, plus OQ #5 / OQ #6 added 2026-09-14 from the topology review:

1. **Dhara's `dhara/skills_signer/` directory fate.** **Resolved: move to `mcp-common` in Phase 4, then delete Dhara's copy.** The ed25519 signer is a cryptographic primitive shared by both agent/skill catalogs; cross-cutting infra lives in `mcp-common`, not in any single application component. Phase 4 task 5 + task 6 implement this.

2. **`dhara/mcp/substrate_routes.py` storage location.** **Resolved: Oneiric owns the storage** (per ADR-017 framing). Oneiric is the persistence substrate; substrate state is Oneiric's responsibility. No double-storage between Dhara and Oneiric. Phase 7 implements this. **Re-evaluation point:** OQ #5 below tracks whether the HTTP gateway should live on Mahavishnu instead (Phase 11 gateway-pattern evaluation).

3. **Oneiric MCP server port.** **Resolved: 8683** (Dhara's old port, reclaimed). Per `BODAI_REPO_REGISTRY.md` port conventions: Akosha=8682, Mahavishnu=8680, Crackerjack=8676, Session-Buddy=8678. 8683 was Dhara's port; reclaiming it preserves operator muscle memory. The Dhara plist on operator machines is retired as part of Phase 8 (R4 mitigation).

4. **`dhara/mcp/__main__.py` fate.** **Resolved: delete in Phase 8.** No stub release cycle. Hard cutover per user decision. The directory `dhara/mcp/` is deleted whole; no per-file ceremony.

5. **`substrate_routes` HTTP gateway location — Oneiric vs Mahavishnu.** **Resolved for Phase 7: Oneiric owns the HTTP gateway** (per OQ #2). **Re-evaluation point for Phase 11:** Phase 11's gateway-pattern evaluation (newly added) revisits whether the HTTP gateway should live on Mahavishnu instead of Oneiric. If Mahavishnu becomes the gateway for read-only wrappers (Phase 11 Option C), it may make sense to also move the substrate routes there for operational consistency. Decision deferred to Phase 11 ADR-018.

6. **`agent_schema.py` / `skill_schema.py` canonical location.** **Resolved: `mcp-common.canonical_schemas`.** AkoSHA's `agent_schema.py` and `skill_schema.py` are currently marked "canonical source" in their docstrings (per `akosha/mcp/agent_schema.py`'s comment); the other three components sed-replicate. This DRY violation is fixed by Phase 4 tasks 2 + 4 (move canonical files to `mcp-common`) and Phase 10 task 2 (delete the sed-replicated copies in AkoSHA / Session-Buddy / Mahavishnu, with Crackerjack following Phase 4's import-from-canonical-home change).

7. **Hook-channel migration scope (added 2026-09-14).** **Resolved: bridge pattern, project-local canonical handler, hard cutover from JSON-file queue to Redis Streams.** Per the brainstorming-session-2026-09-14 answers (Q4): handler lives at `mahavishnu/bodai_hook_bridge.py`. The bridge pattern (≤20-line JSON normalizer per harness) absorbs harness-specific schema differences — Claude Code's ~30 events vs Qwen Code's ~19; divergent `permission_mode` enums; Claude-only `effort` field per spec §4.13.2. Multi-harness compatibility is bounded to ~15 lines per new harness. Phase 12a ships the Claude bridge + git-hook wrappers; Phase 12b adds Qwen and (eventually) Codex.

## 8. What Changes for Operators

| What | Before | After |
|------|--------|-------|
| `pip install dhara` | Library + MCP server + CLI | Library + CLI (engine only) |
| `dhara db start\|client\|pack` | Works | Works (unchanged) |
| `dhara mcp start\|stop\|status\|health\|restart` | Works | **Dropped** |
| `oneiric mcp start\|stop\|status\|health\|restart` | Did not exist | **New** — binds port 8683 (Dhara's old port) |
| `mcp__dhara__list_adapters` | Works | **Replaced by `mcp__oneiric__list_adapters`** |
| `mcp__dhara__get_adapter` | Works | **Replaced by `mcp__oneiric__get_adapter`** |
| `mcp__dhara__list_adapter_versions` | Works | **Replaced by `mcp__oneiric__list_adapter_versions`** |
| `mcp__dhara__validate_adapter` | Works | **Replaced by `mcp__oneiric__validate_adapter`** |
| `mcp__dhara__get_adapter_health` | Works | **Replaced by `mcp__oneiric__get_adapter_health`** |
| `mcp__dhara__store_adapter` | Works | **Replaced by `mcp__oneiric__store_adapter`** |
| `mcp__dhara__get_contract_info` | Works | **Replaced by `mcp__oneiric__get_contract_info`** |
| `mcp__dhara__upsert_service` | Works | **Replaced by `mcp__mahavishnu__ecosystem_upsert_service`** |
| `mcp__dhara__get_service` | Works | **Replaced by `mcp__mahavishnu__ecosystem_get_service`** |
| `mcp__dhara__list_services` | Works | **Replaced by `mcp__mahavishnu__ecosystem_list_services`** |
| `mcp__dhara__record_event` | Works | **Replaced by `mcp__mahavishnu__ecosystem_record_event`** |
| `mcp__dhara__list_events` | Works | **Replaced by `mcp__mahavishnu__ecosystem_list_events`** |
| `mcp__dhara__list_agents` | Works | **Replaced by `mcp__crackerjack__list_agents`** |
| `mcp__dhara__get_agent` | Works | **Replaced by `mcp__crackerjack__get_agent`** |
| `mcp__dhara__list_skills` | Works | **Replaced by `mcp__crackerjack__list_skills`** |
| `mcp__dhara__get_skill` | Works | **Replaced by `mcp__crackerjack__get_skill`** |
| `mcp__dhara__query_local_traces` | Works | **Replaced by `mcp__akosha__query_local_traces_fitness`** |
| `mcp__akosha__query_local_traces` | Works (general-purpose) | **Dropped** (replaced by `_fitness` variant) |
| `mcp__dhara__put/get/list_prefix/record_time_series/query_time_series/aggregate_patterns` | Works | **Dropped as MCP tools** (replaced by Oneiric cache adapter `oneiric.adapters.cache.persistent_kv`, not exposed via MCP) |
| `mcp__dhara__sql_query/sql_execute` | Works | **Dropped** (no replacement) |
| `mcp__mahavishnu__adapter_list/adapter_metadata` | Works | **Removed (ADR-013 Option C)** |
| `from dhara.mcp.auth import ...` | Works (file-based TokenAuth) | **Deleted with Dhara server** (Phase 8); new code uses `from mcp_common.auth import ...` |
| `oneiric/adapters/dhara_pusher.py` | Pushes to Dhara MCP | **Deleted (Phase 1 task 14)** |
| `from dhara import Connection, Persistent, PersistentDict, PersistentList, BTree` | Works | Works (unchanged) |
| Dhara launchd plist (if any) | Runs `dhara mcp start` | **Retired (Phase 8)** — replace with Oneiric MCP launchd plist on port 8683 |
| Dhara role in `BODAI_REPO_REGISTRY.md` | `mcp_server` | **`engine`** (Phase 8 task 14) |
| `dhara` version | 0.20.1 | **1.0.0** (after Phase 8; user bumps via `crackerjack run -p major`) |

## 9. References

- `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` — to be amended (Option B → Option C).
- `docs/adr/017-oneiric-shared-persistence-substrate.md` — to be amended (Oneiric now has an MCP server).
- `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` — to be amended (Phase 4 description, Phase 11 redirect).
- `docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md` — precondition plan; cross-references need updating.
- `docs/plans/2026-07-26-mahavishnu-acp-server.md` — Phase 1.5 (skill distribution) routes through Crackerjack per Phase 4 of this spec.
- `docs/superpowers/specs/2026-04-27-bodai-auth-standardization-design.md` — Phase 2 of this spec completes Dhara's row.
- `docs/superpowers/specs/2026-05-24-dhara-serverless-design.md` — Phase 4 of the active plan (Dhara re-architecture) still applies; this spec decomposes the MCP surface.
- `docs/ZODB_COMPARISON.md` (in Dhara repo) — documents Dhara's lineage from Durus; informs "Dhara stays the engine" decision.
- `dhara/NOTICE` — CNRI/Durus attribution preserved under BSD-3-Clause.
- `.claude/decisions/wire-up-contract.md` — Integration Contract pattern used in every phase.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — per-feed health aggregator pattern for new MCP servers.
- `oneiric/core/cli.py` — `MCPServerBase` + `MCPServerCLIFactory` primitives used to build the Oneiric MCP server.
- `oneiric/runtime/mcp_health.py` — health infrastructure reused.
- `mcp_common/auth/*` — 14 files, 1,570 LOC; canonical auth surface.
