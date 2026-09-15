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
| `kv_time_series` | `dhara_put` | TBD | Session-Buddy or Oneiric | **Deferred to Phase 6.** Three options: (a) move to Session-Buddy as `session_buddy_kv_put`, (b) wrap as Oneiric cache adapter, (c) drop. Recommend (b). |
| `kv_time_series` | `dhara_get` | TBD | same as above | |
| `kv_time_series` | `dhara_list_prefix` | TBD | same as above | |
| `kv_time_series` | `dhara_record_time_series` | TBD | same as above | |
| `kv_time_series` | `dhara_query_time_series` | TBD | same as above | |
| `kv_time_series` | `dhara_aggregate_patterns` | TBD | same as above | Note: this overlaps with `akosha` `aggregate_patterns`; consolidate as part of Phase 6. |
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
| `otel_traces` | `dhara_query_local_traces` | `akosha_query_local_traces` | Akosha | Dep moves from Dhara to Akosha (`akosha>=0.17.1`). |
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

After decomposition, Dhara's pyproject.toml drops these dependencies:

```diff
 dependencies = [
-    "fastmcp>=3.4.0,<5",
-    "mcp-common>=0.26.0,<0.27.0",
-    "uvicorn>=0.48.0",
-    "ipython>=9.14.0",
-    "rich>=15.0.0",
-    "cryptography>=50.0.0",
-    "schedule>=1.2.2",
-    "zstandard>=0.25.0",
-    "aiosqlite>=0.22.1",
+    # Engine-only dependencies; MCP-specific deps removed.
 ]
```

`cryptography` is needed only by the signer_feed (Phase 1.5 → Crackerjack). `aiosqlite` may stay if the engine's async path uses it (verify; see §4.5).

The `[project.entry-points."bodai.apps"]` block for `dhara.cli:app` remains — Dhara is still a Bodai app, just not an MCP server.

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

The restored Oneiric MCP server follows the pattern already established by the other 4 Bodai MCP servers:

```python
# oneiric/mcp/server_core.py
from __future__ import annotations

from mcp_common.auth import AuthConfig, require_auth, Permission
from oneiric.core.cli import MCPServerBase, MCPServerCLIFactory
from oneiric.adapters.bootstrap import builtin_adapter_metadata


class OneiricMCPServer(MCPServerBase):
    def get_app(self):
        # FastMCP app with 7 tools, auth via mcp_common.auth.middleware
        # ...
        pass


def make_app() -> OneiricMCPServer:
    config = OneiricMCPConfig.from_env()
    return OneiricMCPServer(config)
```

CLI subcommands via `MCPServerCLIFactory`:

```
$ oneiric mcp start      # Start the MCP server
$ oneiric mcp stop       # Graceful stop
$ oneiric mcp status     # Liveness
$ oneiric mcp health     # Per-feed health (per .claude/decisions/mcp-backend-wiring-discipline.md)
$ oneiric mcp restart    # Restart
$ oneiric mcp config     # Show resolved config
```

The `mcp_health.py` runtime module (`oneiric/runtime/mcp_health.py`) already provides the per-feed aggregator. The 7 tools each become a feed with `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total` per the wire-up contract.

### 4.7 ADR cross-references

- **ADR 013 (active)** — currently documents Option B ("keep both surfaces"). Phase 1 of this spec adopts Option C (remove Mahavishnu's `adapter_list` / `adapter_metadata`). ADR 013 amendment lands in the same commit as Phase 1.
- **ADR 017 (proposed)** — Oneiric as the shared persistence substrate. The Oneiric MCP server IS the ADR-013 "canonical surface" for adapter state queries, now owned by Oneiric per ADR-017's "owned by Oneiric" framing.
- **Active plan `2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Phase 4** (Dhara re-architecture) — the storage/lock changes still apply (fcntl locks → Oneiric adapter, FileStorage → Oneiric storage adapter, cloud primary, async path). But the "Dhara still has an MCP server" assumption in Phase 4 needs amendment: Phase 4's deliverable is now "Dhara engine uses Oneiric substrate; MCP surface moved to other components." Phase 11 (Harness-agnostic enablement) needs to redirect Qwen/Claude Code validation from `mcp__dhara__*` tools to `mcp__oneiric__*` + `mcp__mahavishnu__*` + `mcp__crackerjack__*` + `mcp__akosha__*` tools.

## 5. Phased Delivery Plan

Phase ordering matters because the migrations cascade and each phase leaves the test suite green.

### Phase 1 — Restore Oneiric MCP server

**Goal:** `mcp__oneiric__*` tools exist; Mahavishnu and agents migrate to calling them.

**Tasks:**

1. Create `oneiric/mcp/server_core.py` extending `MCPServerBase` from `oneiric/core/cli.py`.
2. Port the 7 `adapter_registry` tool implementations from `dhara/mcp/adapter_tools.py` (1,301 LOC) into `oneiric/mcp/tools/adapter_registry.py`.
3. Wire auth via `mcp_common.auth.middleware` (NOT Dhara's auth fork).
4. Wire tool profile gating via `mcp_common.tools.dispatch`.
5. Add health aggregator using existing `oneiric/runtime/mcp_health.py`.
6. Extend `MCPServerCLIFactory` to register `oneiric mcp start|stop|status|health|restart|config` subcommands.
7. Add `tests/integration/test_<tool>_e2e.py` for each of the 7 tools (per wire-up contract).
8. Add `tests/integration/test_oneiric_mcp_health.py` asserting 503-on-degraded per `.claude/decisions/mcp-backend-wiring-discipline.md`.
9. Update `.claude/agents/oneiric-specialist.md` to use `mcp__oneiric__*` names.
10. Update `.claude/agents/database-operations-specialist.md` + `architecture-council.md` cross-references.

**Deprecations (in this phase):**

- `mcp__dhara__list_adapters` → `mcp__oneiric__list_adapters`
- `mcp__dhara__get_adapter` → `mcp__oneiric__get_adapter`
- `mcp__dhara__list_adapter_versions` → `mcp__oneiric__list_adapter_versions`
- `mcp__dhara__validate_adapter` → `mcp__oneiric__validate_adapter`
- `mcp__dhara__get_adapter_health` → `mcp__oneiric__get_adapter_health`
- `mcp__dhara__store_adapter` → `mcp__oneiric__store_adapter`
- `mcp__dhara__get_contract_info` → `mcp__oneiric__get_contract_info`

**ADR amendments:** ADR-013 moves from Option B to Option C. Amendment lands in the same commit as the Oneiric MCP server code.

**Mahavishnu changes:**

- Remove `mcp__mahavishnu__adapter_list` and `mcp__mahavishnu__adapter_metadata` (Option C of ADR-013).
- Remove the corresponding entries from `mahavishnu/mcp/tool_versions.py` `TOOL_VERSIONS` (lines 151-152).
- Add both to `DEPRECATED_TOOLS` in the same file.
- Update `_check_adapter_metadata_contract` in `mahavishnu/core/compatibility.py` to point at Oneiric.
- Update tests in `tests/unit/test_compatibility.py`, `tests/unit/test_main_cli.py`.
- Internal callers that hit `HybridAdapterRegistry.list_adapters` / `get_metadata` directly (CLI, compatibility checks) continue to work because those are in-process calls, not MCP calls.

**Integration contract (per wire-up contract):**

- **Triggered from:** `oneiric mcp start` (or via launchd plist / systemd unit); agents call `mcp__oneiric__*` via MCP protocol.
- **Returns to / updates:** The Oneiric adapter registry store (backed by Dhara's `AsyncAdapterRegistry` for now; future: Oneiric's own persistence layer per ADR-017).
- **Demonstrable by:** `pytest tests/integration/test_<tool>_e2e.py` (7 files, one per tool) + `oneiric mcp health` returning 200 with 7 healthy feeds.
- **Rollback signal:** 503 on `/health`, or 0 `entities_count` on any feed after startup.
- **Observability added:** OTel span `oneiric.mcp.tool.<name>` with attribute `tool.name`, `tool.duration_ms`.

### Phase 2 — Auth consolidation

**Goal:** Every Bodai MCP server uses `mcp_common.auth.*`. Dhara's auth fork is deleted (Dhara has no MCP server after Phase 1, but verify nothing imports `dhara.mcp.auth`).

**Tasks:**

1. Verify `mcp_common.auth.*` exports cover all of Dhara's auth usage:
   - `JWT_ALGORITHM` ✓ (in `core.py`)
   - `create_service_token` ✓
   - `verify_token` ✓
   - `@require_auth` ✓ (`decorator.py`)
   - Audience/issuer verification ✓ (`identity.py`, `permissions.py`)
   - Audit logging ✓ (`audit.py`)
   - ASGI middleware ✓ (`middleware.py`, `error_middleware.py`)
2. Delete `dhara/mcp/auth.py`, `dhara/mcp/fastmcp_auth.py`, `dhara/mcp/middleware.py` (1,325 LOC).
3. Update any remaining `dhara.mcp.auth.*` imports (likely none after Phase 1).
4. Update `.claude/decisions/mcp-backend-wiring-discipline.md` cross-reference if it cited Dhara's auth.
5. Update `2026-04-27-bodai-auth-standardization-design.md` from `status: complete` to `status: complete` (no change) but mark Dhara's row in the "per-service status" table as Done.

**Integration contract:**

- **Triggered from:** Import time (every Bodai MCP server that imports `mcp_common.auth`).
- **Returns to / updates:** The auth config from `ONEIRIC_*` env vars.
- **Demonstrable by:** Existing test suite passes; `grep -r "from dhara.mcp.auth"` returns nothing.
- **Rollback signal:** Test failures on auth-protected tool calls.
- **Observability added:** Existing `mcp_common.auth.audit.AuditLogger` events.

### Phase 3 — Move ecosystem_state → Mahavishnu

**Goal:** `mcp__mahavishnu__*` includes 5 new service/event tools. Dhara drops the implementation.

**Tasks:**

1. Port `dhara/mcp/ecosystem_state.py` (232 LOC) to `mahavishnu/mcp/tools/ecosystem_state.py`.
2. Port the `AsyncEcosystemStateStore` to `mahavishnu/core/ecosystem_state_store.py`.
3. Wire tool profile gating (`ecosystem_state` group; STANDARD + FULL profiles).
4. Add 5 e2e tests in `tests/integration/test_<tool>_e2e.py`.
5. Add health aggregator entry for the new feed.
6. Update `.claude/agents/mahavishnu-specialist.md` to reference the new tools.

**Deprecations:**

- `mcp__dhara__upsert_service` → `mcp__mahavishnu__upsert_service`
- `mcp__dhara__get_service` → `mcp__mahavishnu__get_service`
- `mcp__dhara__list_services` → `mcp__mahavishnu__list_services`
- `mcp__dhara__record_event` → `mcp__mahavishnu__record_event`
- `mcp__dhara__list_events` → `mcp__mahavishnu__list_events`

**Integration contract:**

- **Triggered from:** `mahavishnu mcp start`; agents call `mcp__mahavishnu__*` via MCP protocol.
- **Returns to / updates:** Mahavishnu's ecosystem_state store (replaces Dhara's `AsyncEcosystemStateStore`).
- **Demonstrable by:** 5 new e2e tests + `mahavishnu mcp health` returning 200 with healthy ecosystem_state feed.
- **Rollback signal:** 503 or 0 entities_count on ecosystem_state feed.
- **Observability added:** OTel span `mahavishnu.mcp.tool.ecosystem_state.<name>`.

### Phase 4 — Move agent_registry + skill_registry + signer_feed → Crackerjack

**Goal:** Phase 1.5 of the active ACP plan, but routed through Crackerjack not Dhara.

**Tasks:**

1. Port `dhara/mcp/tools/agent_registry.py` (426 LOC) to `crackerjack/mcp/tools/agent_registry.py`.
2. Port `dhara/mcp/agent_schema.py` (223 LOC) to `crackerjack/mcp/schemas/agent.py`.
3. Port `dhara/mcp/tools/skill_registry.py` (353 LOC) to `crackerjack/mcp/tools/skill_registry.py`.
4. Port `dhara/mcp/skill_schema.py` (173 LOC) to `crackerjack/mcp/schemas/skill.py`.
5. Port `dhara/mcp/signer_feed.py` (254 LOC) to `crackerjack/mcp/signer.py` (private; not exposed as a tool).
6. Move `dhara/skills_signer/` (if it exists) to `crackerjack/skills_signer/`.
7. Wire auth (RBAC: WRITE permission required for registration; READ for listing).
8. Add 4 e2e tests in `tests/integration/test_<tool>_e2e.py`.
9. Add health aggregator entry.

**Deprecations:**

- `mcp__dhara__list_agents` → `mcp__crackerjack__list_agents`
- `mcp__dhara__get_agent` → `mcp__crackerjack__get_agent`
- `mcp__dhara__list_skills` → `mcp__crackerjack__list_skills`
- `mcp__dhara__get_skill` → `mcp__crackerjack__get_skill`

**Integration contract:**

- **Triggered from:** `crackerjack mcp start`; agents call `mcp__crackerjack__*` via MCP protocol.
- **Returns to / updates:** Crackerjack's signed-content registry (ed25519-signed via the moved signer_feed).
- **Demonstrable by:** 4 e2e tests + Crackerjack `mcp health` returning 200 with healthy agents + skills feeds.
- **Rollback signal:** Failed signature verification on retrieved agent/skill metadata.
- **Observability added:** OTel span `crackerjack.mcp.tool.<agents|skills>.<name>` + `crackerjack.signer.sign` events.

### Phase 5 — Move otel_traces → Akosha

**Goal:** Akosha owns OTel trace queries; Dhara drops the tool + the `akosha>=0.17.1` dep.

**Tasks:**

1. Port `dhara/mcp/tools/otel_traces.py` (190 LOC) to `akosha/mcp/tools/query_local_traces.py`.
2. Move the `akosha` dep group from Dhara to Akosha (or remove from Dhara since the only Akosha dep was for this tool).
3. Add e2e test in `tests/integration/test_query_local_traces_e2e.py`.
4. Update `.claude/agents/akosha-specialist.md` and `architecture-council.md` cross-references.

**Deprecations:**

- `mcp__dhara__query_local_traces` → `mcp__akosha__query_local_traces`

**Integration contract:**

- **Triggered from:** `akosha mcp start`; agents call `mcp__akosha__*` via MCP protocol.
- **Returns to / updates:** Akosha's HotStore (DuckDB file conforming to the Akosha/Mahavishnu HotStore schema).
- **Demonstrable by:** e2e test + `akosha mcp health` returning 200.
- **Rollback signal:** Empty results when traces are expected.
- **Observability added:** OTel span `akosha.mcp.tool.query_local_traces`.

### Phase 6 — Decide kv_time_series and sql_proxy fate

**Goal:** Two remaining tool groups resolved.

**Decision matrix:**

| Tool group | Recommended action | Why |
|------------|--------------------|-----|
| `kv_time_series` (6 tools) | **Move to Session-Buddy as memory primitives.** | Session-Buddy is the memory MCP (49 tools). Generic KV + time-series are exactly the memory surface. Session-Buddy's `store_reflection` already uses a similar shape. |
| `kv_time_series.dhara_aggregate_patterns` | **Drop; consolidate into `mcp__akosha__aggregate_patterns`.** | Akosha already has `aggregate_patterns`; the Dhara tool is a duplicate. |
| `sql_proxy` (2 tools) | **Drop.** | The active plan's Phase 6 already strips similar tools as "off-the-shelf or deleted." DuckDB SQL is reachable through Akosha's trace query tool (which already uses the same DuckDB-backed schema). |

**If `kv_time_series` cannot move to Session-Buddy cleanly, fallback:** Drop and document as "no replacement; use Session-Buddy's existing memory primitives directly."

**Tasks (if moving kv_time_series):**

1. Port `dhara/mcp/kv_timeseries.py` (443 LOC) to `session-buddy/mcp/tools/kv_timeseries.py`.
2. Add 6 e2e tests.
3. Update Session-Buddy tool profile to include `kv_time_series` group.

**Tasks (if dropping sql_proxy):**

1. Mark `mcp__dhara__sql_query` and `mcp__dhara__sql_execute` as `DEPRECATED_TOOLS` with no replacement; remove in Phase 8.
2. Document the removal in `docs/MCP_TOOLS_SPECIFICATION.md`.

### Phase 7 — Move substrate_routes → Oneiric HTTP API

**Goal:** The HTTP routes (settings/context/progress) move to Oneiric alongside the new MCP server.

**Tasks:**

1. Port `dhara/mcp/substrate_routes.py` (531 LOC) to `oneiric/http/routes/substrate.py`.
2. Register with Oneiric's HTTP server (if it has one) or with a new `oneiric http` subcommand via `MCPServerCLIFactory` analog.
3. Update `.claude/decisions/mcp-backend-wiring-discipline.md` if it referenced these routes as Dhara's.

**Integration contract:**

- **Triggered from:** `oneiric http start` (new subcommand).
- **Returns to / updates:** Oneiric's HTTP API surface.
- **Demonstrable by:** `curl http://localhost:<port>/substrate/settings` returns 200.
- **Rollback signal:** 5xx on substrate routes.
- **Observability added:** OTel span `oneiric.http.route.<name>`.

### Phase 8 — Retire Dhara MCP server

**Goal:** Delete `dhara/mcp/` entirely. Slim pyproject.toml. Cut Dhara v1.0.0.

**Tasks:**

1. Delete `dhara/mcp/` directory (every file).
2. Delete `dhara/mcp/tools/` directory.
3. Delete `dhara/skills_signer/` if any (after Phase 4 moves it).
4. Update `dhara/__init__.py` to drop MCP imports.
5. Update `dhara/cli.py` to remove `dhara mcp` subcommands.
6. Slim `dhara/pyproject.toml` per §4.4.
7. Update `dhara/CLAUDE.md` to remove MCP server section.
8. Update `dhara/CHANGELOG.md`: fix the stale "MIT License" line at the bottom (it's wrong; pyproject.toml says BSD-3-Clause).
9. Bump `dhara/pyproject.toml` version `0.20.1` → `1.0.0`.
10. Add `dhara.egg-info/SOURCES.txt` to the slim build (verify hatchling config still works).
11. Run `crackerjack run -p major` (user-controlled publish step).
12. Add `dhara` to the `Bodai apps` registry as `engine` (was `mcp_server`).
13. Update `BODAI_REPO_REGISTRY.md` if it listed Dhara as an MCP server.

**Tests to update:**

- Delete `dhara/tests/integration/test_<mcp-tool>_e2e.py` files.
- Update `dhara/tests/unit/test_wiring.py` (golden fixture for `tests/fixtures/{minimal,standard,full}/tool_names.json`).
- Update `dhara/tests/unit/test_profiles.py` for the slimmed profile list.

**Integration contract:**

- **Triggered from:** `pip install dhara` (no MCP surface; library + CLI only).
- **Returns to / updates:** Dhara 1.0.0 on PyPI.
- **Demonstrable by:** `python -c "import dhara; print(dhara.__version__)"` prints `1.0.0`.
- **Rollback signal:** None (this is a release, not a runtime feature).
- **Observability added:** PyPI download count + import-time version check.

### Phase 9 — Update active plan and Phase 11

**Goal:** The active serverless-readiness plan and its Phase 11 (Harness-agnostic enablement) reflect the new component topology.

**Tasks:**

1. Amend `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`:
   - Phase 4 (Dhara re-architecture): update description to "Dhara engine uses Oneiric substrate; MCP surface moved to other components per `2026-09-14-dhara-mcp-decomposition-design.md`."
   - Phase 11 (Harness-agnostic enablement): redirect Qwen Code / Claude Code validation tests from `mcp__dhara__*` to `mcp__oneiric__*` + `mcp__mahavishnu__*` + `mcp__crackerjack__*` + `mcp__akosha__*`.
2. Update `docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md` precondition plan: any REQs that touched Dhara MCP tools now touch the new homes.
3. Update cross-references in `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` (Option C amendment), `docs/adr/017-oneiric-shared-persistence-substrate.md` (clarify that Oneiric now has an MCP server).

## 6. Risks & Mitigations

### R1 — Internal callers break when `mcp__dhara__*` tools move

**Risk:** Code in Mahavishnu, agents, or external repos that calls `mcp__dhara__list_adapters` etc. fails after Phase 1.

**Mitigation:** Per `.claude/decisions/wire-up-contract.md`, every `DEPRECATED_TOOLS` entry needs a `replacement` field pointing at the new tool. Add a thin pass-through in `dhara/mcp/server_core.py` that proxies deprecated tools to the new homes — OR document the deprecation in `docs/MCP_TOOLS_SPECIFICATION.md` with a hard-cutover date. **Decision: hard cutover; document in the spec, send notification, no proxy.** Proxying adds load on a server we're deleting.

### R2 — Phase 4 (Crackerjack skill signing) requires Crackerjack to grow

**Risk:** Crackerjack's surface area grows by ~1,800 LOC (tools + signer + schemas). The Crackerjack maintainer may not want this scope.

**Mitigation:** Phase 1.5 of the active ACP plan already routes skill distribution through Crackerjack. This spec just delivers what was already designed. If Crackerjack's maintainer objects, defer Phase 4 and leave `mcp__dhara__list_skills` etc. in place longer (delays Phase 8 retirement).

### R3 — Auth migration reveals gaps in `mcp_common.auth.*`

**Risk:** If Dhara's auth has Dhara-specific features (e.g. custom audience claim, custom permission level), `mcp_common.auth.*` doesn't cover them.

**Mitigation:** Phase 2 begins with a `grep` audit. If gaps found, file a follow-up spec for `mcp_common.auth` extension. Don't ship Phase 2 partially; either mcp-common covers it or Phase 2 splits.

### R4 — Bodai app registry / launchd plists still reference `mcp_server` role for Dhara

**Risk:** Dhara's launchd plist on the operator's machine (if any) tries to start `dhara mcp` and fails after Phase 8.

**Mitigation:** Phase 8 includes updating `BODAI_REPO_REGISTRY.md` and any launchd plists. Document the breaking change in the spec's "What Changes for Operators" section.

### R5 — External consumers (outside Bodai ecosystem) of `mcp__dhara__*` tools

**Risk:** Unknown number of consumers use `mcp__dhara__*` directly.

**Mitigation:** **Search all Bodai components for `mcp__dhara__*` references before Phase 1.** If found, update them. Document the move in `CHANGELOG.md` and notify via whatever channel is established for breaking MCP changes.

## 7. Open Questions

1. **Should we keep Dhara's `dhara/skills_signer/` directory after Phase 4 moves the signing logic to Crackerjack?** Or is the directory fully subsumed by Crackerjack? **Decision needed before Phase 4.**
2. **Should `dhara/mcp/substrate_routes.py` settings/context/progress storage live in Dhara (engine) or Oneiric (registry)?** Affects which component owns the data. **Decision needed before Phase 7.**
3. **What port does the Oneiric MCP server use?** Per `BODAI_REPO_REGISTRY.md`, Bodai components have canonical ports. Akosha=8682, Dhara=8683 (was), Mahavishnu=8680, Crackerjack=8676, Session-Buddy=8678. If Oneiric takes 8683, the existing Dhara plist must be retired; if a different port, agents need updating. **Decision needed before Phase 1.**
4. **Does `dhara/mcp/__main__.py` get deleted, or kept as a no-op stub for one release cycle?** Likely delete; confirm.

## 8. What Changes for Operators

| What | Before | After |
|------|--------|-------|
| `pip install dhara` | Library + MCP server + CLI | Library + CLI (engine only) |
| `dhara db start|client|pack` | Works | Works (unchanged) |
| `dhara mcp start|stop|status|health|restart` | Works | **Dropped** |
| `mcp__dhara__list_adapters` | Works | **Replaced by `mcp__oneiric__list_adapters`** |
| `mcp__dhara__upsert_service` | Works | **Replaced by `mcp__mahavishnu__upsert_service`** |
| `mcp__dhara__list_agents` | Works | **Replaced by `mcp__crackerjack__list_agents`** |
| `mcp__dhara__list_skills` | Works | **Replaced by `mcp__crackerjack__list_skills`** |
| `mcp__dhara__query_local_traces` | Works | **Replaced by `mcp__akosha__query_local_traces`** |
| `mcp__dhara__put/get/list_prefix/record_time_series/query_time_series` | Works | **Replaced by `mcp__session_buddy__*` (Phase 6 decision pending)** |
| `mcp__dhara__sql_query/sql_execute` | Works | **Dropped** |
| `mcp__mahavishnu__adapter_list/adapter_metadata` | Works | **Removed (ADR-013 Option C)** |
| `from dhara.mcp.auth import ...` | Works | **Replaced by `from mcp_common.auth import ...`** |
| `from dhara import Connection, Persistent` | Works | Works (unchanged) |
| `dhara` version | 0.20.1 | **1.0.0** (after Phase 8) |

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
