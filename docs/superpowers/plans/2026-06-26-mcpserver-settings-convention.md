# MCP Server Settings Convention — `OneiricMCPConfig` + `mcp-common`

**Status:** Drafted 2026-06-26, post-fleet audit
**Owner:** TBD
**Trigger:** 2026-06-26 fleet audit (`*-mcp` repos) revealed a real convention exists in 7 of 15 repos but 8 are lighter; spline-mcp is the lone outlier that uses neither oneiric-config nor mcp-common-config.

## Goal

Establish `OneiricMCPConfig` (from `oneiric.core.config`) as the canonical settings class for every `*-mcp` server in the Bodai ecosystem, with `mcp-common` as the FastMCP surface. After this plan ships, every `*-mcp` repo imports settings from a single place and uses the same layered config (YAML + env) pattern.

## Architecture

### The convention, formalized

Every `*-mcp` server should:

1. **Pin `oneiric>=0.13.3` (or current stable) and `mcp-common>=0.16.4`** in `[project].dependencies`
2. **Import settings from `oneiric.core.config`** via `OneiricMCPConfig` (or a subclass)
3. **Use `from mcp_common.fastmcp import FastMCP`** for the FastMCP surface (per Plan 7 Phase 1)
4. **Use `from mcp_common.server import StandardServer`** for the server lifecycle wrapper
5. **Use `from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware`** for OTel tracing

### Example bootstrap

```python
from __future__ import annotations

from fastmcp import FastMCP
from oneiric.core.config import OneiricMCPConfig
from mcp_common.server import StandardServer, StandardServerSettings


class SplineSettings(OneiricMCPConfig):
    """Spline-specific config layers on top of oneiric's MCP config base."""

    default_framework: str = "react"
    websocket_enabled: bool = False
    n8n_enabled: bool = False
    cache_dir: str = "~/.cache/spline-mcp"


def create_app() -> FastMCP:
    settings = SplineSettings.load("spline-mcp")  # oneiric-config — YAML + env layered
    server = StandardServer(
        name="spline-mcp",
        description="Spline MCP server",
        settings=StandardServerSettings.load("spline-mcp"),  # mcp-common
    )
    server.attach_otel_middleware()
    register_all_tools(server)
    return server.app  # underlying FastMCP instance
```

This replaces the per-repo ad-hoc `BaseSettings(env_prefix="...")` pattern.

## Why this convention

- **Secret resolution** — `OneiricMCPConfig` integrates with `oneiric.core.config`'s `SecretsProviderProtocol`, giving every server Doppler/Vault support for free
- **Layered config** — YAML (committed defaults) + local.yaml (gitignored overrides) + env vars, in load order
- **Lifecycle integration** — `oneiric.core.lifecycle.LifecycleManager` hooks for graceful shutdown
- **Reuse** — every `*-mcp` server's config-time concerns (cache dirs, secrets, telemetry, health checks) come from one place
- **Consistency** — new `*-mcp` repos can be scaffolded from a template instead of copy-pasting the `BaseSettings` boilerplate

## Per-repo migration template

For each repo not currently on the convention:

```python
# OLD (config.py):
from pydantic_settings import BaseSettings, SettingsConfigDict

class SplineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPLINE_", env_file=(".env",))
    server_name: str = "spline-mcp"
    default_framework: str = "react"
    # ... 30 fields

# NEW (config.py):
from oneiric.core.config import OneiricMCPConfig

class SplineSettings(OneiricMCPConfig):
    """Spline-specific config layers on top of oneiric."""
    default_framework: str = "react"
    # ... only spline-specific fields
    # env_prefix + YAML loading comes from OneiricMCPConfig
```

```python
# OLD (server.py):
from fastmcp import FastMCP
def create_app() -> FastMCP:
    settings = get_settings()
    app = FastMCP(name=APP_NAME, version=APP_VERSION)
    register_tool_groups(app)
    return app

# NEW (server.py):
from mcp_common.fastmcp import FastMCP
from mcp_common.server import StandardServer
from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware
def create_app() -> FastMCP:
    server = StandardServer(name=APP_NAME, description=APP_DESCRIPTION)
    server.attach_otel_middleware()
    register_tool_groups(server.app)
    return server.app
```

## Current state (verified 2026-06-26)

| Repo | oneiric setting? | mcp-common? | Camp |
|---|---|---|---|
| excalidraw-mcp | ✅ | ✅ | Oneiric-native |
| mailgun-mcp | ✅ | ✅ | Oneiric-native |
| opera-cloud-mcp | ✅ | ✅ | Oneiric-native |
| raindropio-mcp | ✅ | ✅ | Oneiric-native |
| unifi-mcp | ✅ | ✅ | Oneiric-native |
| langsmith-mcp | ✅ | ✅ | Oneiric-native |
| penpot-api-mcp | ✅ | ✅ | Oneiric-native |
| css-mcp | ❌ | ✅ (thin) | Light |
| graphics-mcp | ❌ | ✅ (thin) | Light |
| neo4j-mcp | ❌ | ✅ (thin) | Light |
| porkbun-dns-mcp | ❌ | ✅ (thin) | Light |
| porkbun-domain-mcp | ❌ | ✅ (thin) | Light |
| synxis-crs-mcp | ❌ | ✅ (thin) | Light |
| synxis-pms-mcp | ❌ | ✅ (thin) | Light |
| **spline-mcp** | ❌ | ❌ | **Outlier** |

## Phases

### Phase 1 — Convention plan + showcase (1 day)

- This document (DONE)
- spline-mcp migration as the showcase (1 day subagent, see Task A below)

### Phase 2 — Plan 7 Phase 1 (mcp-common foundation) lands `OneiricMCPConfig` re-export

- mcp-common pins `oneiric>=0.13.3` (or current stable) as a direct dep
- `mcp_common.config` re-exports `OneiricMCPConfig` from `oneiric.core.config`
- `mcp_common.fastmcp` re-export module (per Plan 7) includes `OneiricMCPConfig` so consumers have a single canonical import path
- Backward compat: `MCPBaseSettings` (current mcp-common base) stays as a deprecated shim, with a warning when used
- CI guard: `tests/unit/test_settings_convention.py` asserts every `*-mcp` repo's `pyproject.toml` declares the convention

### Phase 3 — Light-camp repos migrate (parallel)

7 light-camp repos (`css-mcp`, `graphics-mcp`, `neo4j-mcp`, `porkbun-dns-mcp`, `porkbun-domain-mcp`, `synxis-crs-mcp`, `synxis-pms-mcp`).

Each is ~4 hours of mechanical work: swap base class, update env_prefix logic, update tests, verify FastMCP server still boots.

Dispatch 7 subagents in parallel.

### Phase 4 — Oneiric-camp repos verify + extend (1 day)

7 already-on-Oneiric repos verify they match the convention exactly:
- OneiricMCPConfig via `mcp_common.fastmcp` re-export (not direct `oneiric.core.config`)
- `StandardServer` lifecycle (not raw `FastMCP`)
- OTel middleware attached

Per-repo: read existing config, identify gaps, fix.

### Phase 5 — CI guard + lint (1 day)

- `scripts/ci/check_settings_convention.py` runs in mcp-common CI: greps every `*-mcp` repo's `pyproject.toml` and `config.py`, asserts the pattern
- Crackerjack-style pre-commit gate for `*-mcp` repos that catches regressions

## Acceptance criteria

1. Every `*-mcp` repo imports `OneiricMCPConfig` from `mcp_common.fastmcp` (or directly from `oneiric.core.config` if it's the heavy-camp pattern)
2. No `from pydantic_settings import BaseSettings` (or equivalent) survives in any `*-mcp` `config.py`
3. Every `*-mcp` server uses `StandardServer` (or equivalent mcp-common lifecycle)
4. CI guard catches future regressions
5. All existing tests pass after migration

## Open questions

1. **Should `MCPBaseSettings` be deprecated or removed?** Recommend deprecation + 1-version warning, then removal in mcp-common 0.18+.
2. **Should the convention also apply to Bodai core repos** (mahavishnu, akosha, dhara, session-buddy, crackerjack, oneiric)? Most of them have their own custom settings — out of scope for this plan, but worth a follow-up.
3. **Should mcp-common's `StandardServerSettings` inherit from `OneiricMCPConfig`?** Currently it inherits from `MCPBaseSettings`. If yes, the `Settings.load("server-name")` calls would route through oneiric's loader instead of mcp-common's. Verify backward compat before merging.

## Execution mode

Recommended: `superpowers:subagent-driven-development`. Order:
1. (Task A) spline-mcp showcase migration (~1 day)
2. (Task B) Plan 7 Phase 1 (mcp-common foundation) — BLOCKING for Task C
3. (Task C) Light-camp migrations (7 parallel subagents)
4. (Task D) Oneiric-camp verification (7 subagents, parallel)
5. (Task E) CI guard + docs

Total: ~5 days.