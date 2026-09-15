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

**Why we don't use `MCPServerCLIFactory` directly:** the existing factory's `_start_server()` calls `server.startup()` then enters a `time.sleep(1)` loop, which never binds a port and never calls a transport. The factory is a thin wrapper that assumes the subclass implements `run_http_async()`. The fix is to have Oneiric's `MCPServerCLIFactory` subclass override `_start_server` to invoke `server.run_http_async()` (not the parent class's broken implementation). Phase 1 task 1.5 includes this override.

**Port choice:** Phase 1 claims port **8683** (Dhara's old port). See §7 Open Question #3 for resolution. The Dhara launchd plist on operator machines must be retired as part of Phase 8 (R4 mitigation).

CLI subcommands (provided by `MCPServerCLIFactory` after the `_start_server` override):

```
$ oneiric mcp start      # calls run_http_async() — binds 8683
$ oneiric mcp stop       # graceful shutdown
$ oneiric mcp status     # liveness probe
$ oneiric mcp health     # per-feed aggregator (returns 503 if any feed degraded)
$ oneiric mcp restart    # stop + start
$ oneiric mcp config     # show resolved config
```

The `oneiric/runtime/mcp_health.py` runtime module provides the per-feed aggregator primitives (`HealthMonitor`, `ComponentHealth`, `HealthStatus`); Phase 1 task 5 wires it into the new server.

**Per-tool feed commitment:** Each of the 7 adapter_registry tools registers a `ComponentHealth` feed exposing `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` per `.claude/decisions/mcp-backend-wiring-discipline.md`. The aggregator increments these counters on every tool invocation.

**Tool profile gating (Phase 1):** Wire via `mcp_common.tools.dispatch.apply_tool_profile(profile_env_var="ONEIRIC_TOOL_PROFILE")` with explicit group definitions:

| Profile | Groups exposed |
|---------|----------------|
| `MINIMAL` | `MANDATORY` + `HEALTH` (only `list_adapters` for discovery) |
| `STANDARD` | `MINIMAL` + `get_adapter` + `list_adapter_versions` + `validate_adapter` + `get_adapter_health` (read-only introspection) |
| `FULL` | `STANDARD` + `store_adapter` + `get_contract_info` (mutation + introspection) |

This mirrors the convention used by other Bodai MCP servers (Dhara's profile definition at `dhara/mcp/profiles.py:122-138` is the reference pattern).

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

1. Create `oneiric/mcp/server_core.py` with `OneiricMCPServer` class following Dhara's `run_http_async` pattern (NOT the broken `MCPServerCLIFactory._start_server()` loop — see §4.6 for the pattern).
2. Override `MCPServerCLIFactory._start_server` in a Oneiric-specific subclass to invoke `server.run_http_async()`.
3. Port the 7 `adapter_registry` tool implementations from `dhara/mcp/adapter_tools.py` (1,301 LOC) into `oneiric/mcp/tools/adapter_registry.py`.
4. Wire auth via `mcp_common.auth.middleware` (NOT Dhara's auth fork — Dhara's auth goes away with the server in Phase 8).
5. Wire tool profile gating via `mcp_common.tools.dispatch.apply_tool_profile` with explicit `ONEIRIC_TOOL_PROFILE` semantics per §4.6.
6. Wire per-feed health aggregator: each of the 7 tools registers a `ComponentHealth` feed exposing `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`. Use `oneiric/runtime/mcp_health.py` primitives. `/health` endpoint returns 503 if any feed is degraded.
7. Add `tests/integration/test_<tool>_e2e.py` for each of the 7 tools (per wire-up contract).
8. Add `tests/integration/test_oneiric_mcp_health.py` asserting (a) `/health` returns 200 with 7 healthy feeds on warm startup, (b) returns 503 when any feed is degraded.
9. Update `mahavishnu/tests/fixtures/full/tool_names.json` to remove the strings `"adapter_list"` and `"adapter_metadata"` (Mahavishnu's parallel fixture — currently has these as golden-fixture strings).
10. Update `.claude/agents/oneiric-specialist.md` to use `mcp__oneiric__*` names.
11. Update `.claude/agents/database-operations-specialist.md` + `architecture-council.md` cross-references.
12. Update `docs/superpowers/plans/2026-04-26-agent-skill-modernization.md` (lines 275, 685, 1079, 1088) to replace `mcp__dhara__*` with `mcp__oneiric__*` / `mcp__mahavishnu__*` / `mcp__crackerjack__*` / `mcp__akosha__*` per the §4.2 destination table.
13. Update `mahavishnu/core/skill_mcp_validator.py:62` to call `mcp__oneiric__get_adapter` instead of `mcp__dhara__get_adapter`.
14. **Retire Oneiric's `dhara_pusher` adapter** (R6): delete `oneiric/adapters/dhara_pusher.py` (entire file), `tests/test_dhara_pusher_coverage.py` (entire file), remove 6 occurrences in `tests/unit/adapters/test_tracked_settings.py`, remove 4 occurrences in `QUICKSTART.md`, remove `dhara_pusher` entry points from `pyproject.toml` if any. After Phase 1, Oneiric owns its own registry — pushing to a separate Dhara MCP is incoherent.

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

### Phase 4 — Move agent_registry + skill_registry + signer_feed → Crackerjack

**Goal:** Phase 1.5 of the active ACP plan, but routed through Crackerjack not Dhara. LOC breakdown: agent_registry (426) + agent_schema (223) + skill_registry (353) + skill_schema (173) + signer_feed (254) = **1,429 LOC** of code moved (plus ~400 LOC of tests + scaffolding = ~1,830 LOC total — the previous ~1,800 estimate in §R2 was in this range).

**Pre-flight gate (resolves OQ #1):** `dhara/skills_signer/` exists at `/Users/les/Projects/dhara/dhara/skills_signer/` per `ls dhara/` listing. Move it to Crackerjack in this phase. After move, **delete** the Dhara-side directory (subsumed by Crackerjack's copy — no dual-location reason).

**Tasks:**

1. Port `dhara/mcp/tools/agent_registry.py` (426 LOC) to `crackerjack/mcp/tools/agent_registry.py`.
2. Port `dhara/mcp/agent_schema.py` (223 LOC) to `crackerjack/mcp/schemas/agent.py`.
3. Port `dhara/mcp/tools/skill_registry.py` (353 LOC) to `crackerjack/mcp/tools/skill_registry.py`.
4. Port `dhara/mcp/skill_schema.py` (173 LOC) to `crackerjack/mcp/schemas/skill.py`.
5. Port `dhara/mcp/signer_feed.py` (254 LOC) to `crackerjack/mcp/signer.py` (private; not exposed as a tool).
6. Move `dhara/skills_signer/` to `crackerjack/skills_signer/`. **Delete the Dhara-side directory after move.**
7. Wire auth (RBAC: WRITE permission required for registration; READ for listing).
8. Update `crackerjack/mcp/profiles.py`: set `CRACKERJACK_MANDATORY_GROUPS = {REG_KEY_AGENT_REGISTRY, REG_KEY_SKILL_REGISTRY, REG_KEY_HEALTH}` per the picker-parity logic that Dhara documented in `dhara/mcp/profiles.py:215-228`. Without this, `CRACKERJACK_TOOL_PROFILE=minimal` would not expose `list_agents` / `list_skills`, breaking the picker surface inside Mahavishnu and other consumers.
9. Add 4 e2e tests in `tests/integration/test_<tool>_e2e.py`.
10. Wire per-feed health aggregator: each tool registers a `ComponentHealth` feed exposing `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`.

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
3. **Resolve per-component DuckDB routing** (resolves akosha-specialist HIGH #2). Add `OtelTracesConfig` (or extend Akosha's existing config) with a per-component endpoint map: `akosha://component_endpoint/{system_id}` → DuckDB file path. Components publish their own config; Akosha's tool resolves the path via the map before opening HotStore. This restores the cross-component polling behavior Dhara's tool had. Initial entries: `mahavishnu → /Users/les/.local/share/mahavishnu/traces.duckdb`, `akosha → /Users/les/.local/share/akosha/traces.duckdb`, `crackerjack → /Users/les/.local/share/crackerjack/traces.duckdb`, `session_buddy → /Users/les/.local/share/session-buddy/traces.duckdb`, `dhara → /Users/les/.local/share/dhara/traces.duckdb` (if Dhara still emits traces post-Phase-8).
4. **Remove `akosha>=0.17.1` from Dhara's `[dependency-groups].otel-traces`** — Dhara no longer needs it after the port. Verified: the only `import akosha` in Dhara runtime code is `dhara/mcp/tools/otel_traces.py:99` (`from akosha.storage import HotStore`); other matches are docstrings. Do NOT move the dep group to Akosha (Akosha already depends on its own storage in-tree — adding a self-referential group creates circular install hazard).
5. Add e2e test in `tests/integration/test_query_local_traces_fitness_e2e.py` — assert the fitness analyzer can poll all 5 components and compute fitness signals correctly.
6. Update `.claude/agents/akosha-specialist.md` and `architecture-council.md` cross-references.

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

**Pre-flight gate (resolves OQ #2):** substrate_routes' storage layer lives in Oneiric's registry (not Dhara's). The HTTP routes read/write Oneiric's own state. Rationale: Oneiric is the persistence substrate per ADR-017; substrate state is Oneiric's responsibility. **Confirmed 2026-09-14.** No double-storage between Dhara and Oneiric.

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

**Goal:** Delete `dhara/mcp/` entirely. Slim pyproject.toml. Cut Dhara v1.0.0.

**Tasks:**

1. Delete `dhara/mcp/` directory (every file: `__init__.py`, `__main__.py`, `adapter_lookup.py`, `adapter_tools.py`, `agent_schema.py`, `auth.py`, `ecosystem_state.py`, `fastmcp_auth.py`, `kv_timeseries.py`, `middleware.py`, `profiles.py`, `server.py`, `server_core.py`, `signer_feed.py`, `skill_schema.py`, `substrate_routes.py`, `tools/`).
2. Delete `dhara/skills_signer/` (moved to Crackerjack in Phase 4).
3. Verify `aiosqlite` usage: if only used by `dhara/mcp/`, drop from `pyproject.toml`. If used by engine code (likely, since `AsyncFileStorage` wraps `AsyncSqliteStorage`), keep it. Decision recorded in pyproject comments.
4. Update `dhara/__init__.py` to drop MCP imports.
5. Update `dhara/cli.py` to remove `dhara mcp` subcommands (`dhara mcp start|stop|status|health|restart`).
6. Slim `dhara/pyproject.toml` per §4.4 (10 deps dropped; `oneiric` preserved).
7. Update `dhara/CLAUDE.md` to remove MCP server section.
8. Update `dhara/CHANGELOG.md`: fix the stale "MIT License" line at the bottom (it's wrong; pyproject.toml says BSD-3-Clause).
9. **Grep Dhara docs for MCP references:** `grep -rn "dhara mcp\|mcp__dhara__\|dhara.*MCP.*server" /Users/les/Projects/dhara/` — update `DHARA_MODES_QUICK_REFERENCE.md`, `QUICKSTART.md`, `README.md`, and any other docs that reference the MCP server.
10. Update `dhara/tests/unit/test_wiring.py` (golden fixture for `tests/fixtures/{minimal,standard,full}/tool_names.json`) — delete or empty out since Dhara no longer has tool profiles.
11. Update `dhara/tests/unit/test_profiles.py` for the slimmed profile list (or delete entirely).
12. Delete `dhara/tests/integration/test_<mcp-tool>_e2e.py` files (no longer applicable).
13. Verify exit criteria: `python scripts/audit_orphans.py --days 14` reports zero new orphans in Dhara (after the MCP-related symbols are deleted). If the audit flags recently-removed MCP symbols as "orphans" within the lookback window, document the exemption.
14. Update `BODAI_REPO_REGISTRY.md` — Dhara's role tag shifts from `mcp_server` to `engine`.
15. **User-controlled publish step:** user runs `crackerjack run -p major` to bump Dhara's version to 1.0.0 and publish to PyPI. Per `feedback-mcp-common-version-bump-is-user` memory: the agent never bumps Bodai versions; the user does.

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

**Goal:** The active serverless-readiness plan and its Phase 11 (Harness-agnostic enablement) reflect the new component topology.

**Tasks:**

1. Amend `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`:
   - Phase 4 (Dhara re-architecture): update description to "Dhara engine uses Oneiric substrate; MCP surface moved to other components per `2026-09-14-dhara-mcp-decomposition-design.md`."
   - Phase 11 (Harness-agnostic enablement): redirect Qwen Code / Claude Code validation tests from `mcp__dhara__*` to the new homes per the explicit tool-name table below.
2. Update `docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md` precondition plan: any REQs that touched Dhara MCP tools now touch the new homes.
3. Update cross-references in `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` (Option C amendment — overturning the 2026-09-14 amendment, see §4.7), `docs/adr/017-oneiric-shared-persistence-substrate.md` (clarify that Oneiric now has an MCP server).
4. **If the Phase 1 commit did not include the ADR-013 reversal amendment, apply it now** (covers edge case where Phase 1 shipped without the amendment; Phase 9 is the safety net).

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

**Risk:** Unknown number of consumers use `mcp__dhara__*` directly outside the Bodai ecosystem.

**Mitigation:** Phase 1 task #0 enumerates within the Bodai ecosystem (86 hits, all in tracked files). External consumers are not enumerable from this repo. Document the move in `CHANGELOG.md` and notify via whatever channel is established for breaking MCP changes. Hard cutover means external consumers break immediately — this is acceptable per user decision.

### R6 — Oneiric's `dhara_pusher` adapter and hardcoded Dhara 8683 references

**Risk:** Oneiric has 4+ hardcoded references to Dhara on port 8683:
- `oneiric/QUICKSTART.md` (lines 119, 150)
- `oneiric/adapters/dhara_pusher.py` (lines 55, 214, 253, 263) — defaults to `http://127.0.0.1:8683`
- `oneiric/tests/test_dhara_pusher_coverage.py` (lines 43, 99)
- `oneiric/tests/unit/adapters/test_tracked_settings.py` (6 occurrences)

The `dhara_pusher.py` adapter is the most consequential: its purpose is to push adapter metadata *to* Dhara. After Phase 1, the destination changes (Oneiric owns its own registry).

**Mitigation:** Phase 1 task 14 retires `dhara_pusher.py` entirely (deletes the file, the tests, the QUICKSTART references, the entry points). No retargeting. The "push to a separate Dhara MCP" pattern is incoherent once Oneiric owns its own registry.

### R7 — Phase 11 harness-portability name uniqueness re-verification

**Risk:** Phase 11's REQ-HARNESS-TEST-MATRIX-QWEN validates Qwen Code's 197-tool Bodai MCP surface for name uniqueness (Qwen truncates names >63 chars). If Phase 11 ships during the same window as this spec's earlier phases, the harness's tool-name table will see *both* `mcp__dhara__list_adapters` (still present pre-Phase-8) and `mcp__oneiric__list_adapters` (just added) — two surfaces for the same concept, contradicting the Phase 11 uniqueness claim.

**Mitigation:** Phase 11's name-uniqueness checklist must re-verify *after* Dhara MCP is fully retired (post-Phase-8), not at Phase 11 ship time. Phase 9 of this spec updates Phase 11's redirect table.

## 7. Open Questions

All resolved 2026-09-14:

1. **Dhara's `dhara/skills_signer/` directory fate.** **Resolved: move to Crackerjack in Phase 4, then delete Dhara's copy.** Subsumed by Crackerjack's copy; no dual-location reason. Phase 4 task 6 implements this.

2. **`dhara/mcp/substrate_routes.py` storage location.** **Resolved: Oneiric owns the storage** (per ADR-017 framing). Oneiric is the persistence substrate; substrate state is Oneiric's responsibility. No double-storage between Dhara and Oneiric. Phase 7 implements this.

3. **Oneiric MCP server port.** **Resolved: 8683** (Dhara's old port, reclaimed). Per `BODAI_REPO_REGISTRY.md` port conventions: Akosha=8682, Mahavishnu=8680, Crackerjack=8676, Session-Buddy=8678. 8683 was Dhara's port; reclaiming it preserves operator muscle memory. The Dhara plist on operator machines is retired as part of Phase 8 (R4 mitigation).

4. **`dhara/mcp/__main__.py` fate.** **Resolved: delete in Phase 8.** No stub release cycle. Hard cutover per user decision. The directory `dhara/mcp/` is deleted whole; no per-file ceremony.

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
