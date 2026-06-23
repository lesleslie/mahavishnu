# Multi-Tenant Context Packs v1.0 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 3 (Adjacent)
**Source:** `Rebuilt Hermes / MAOS` Part 3 — "The Identity Layer — Multi-Client Without Multiple Installs." Per-client context bundles (voice, ICP, positioning, visual-identity) loaded at runtime and injected into agent prompts.

**Pivot from spec #9 original framing:** Original was about "multi-client" in a single-org sense. Reframed as multi-tenant MCP deployment: each tenant (operator/customer) of a shared Bodai MCP server gets its own context bundle.

---

## Overview

This spec defines **per-tenant context bundles** for multi-tenant MCP deployments. Each tenant has 4 markdown files (`voice.md`, `icp.md`, `positioning.md`, `visual-identity.md`) loaded per-request from Dhara and injected into agent prompts.

**Architectural property:** Tenant context is *per-request*, fetched fresh from Dhara. Cloud Run instances stay stateless. Bundle updates are atomic version activations; old bundles are preserved in history for forensic recall.

**Shared skills** (`commands/`, `agents/`) are tenant-agnostic. Only the context bundle changes between tenants.

---

## Goals

- **G1.** Multi-tenant MCP deployment: one Bodai instance, many tenants, each with distinct voice/audience/positioning.
- **G2.** Per-request context loading: tenant context is fetched fresh on every request.
- **G3.** Versioned immutable history: "What was tenant X's voice when this MR was generated?" is answerable via Dhara query.
- **G4.** 4-file bundle format (article-faithful): each file answers one question.
- **G5.** Atomic version activation: single-active-version per tenant, enforced at DB level.

## Non-Goals

- **N1.** Cache layer for high-traffic tenants. v1.0 every-request hit; v1.1 may add TTL cache.
- **N2.** Bundle inheritance (parent org → sub-tenant). v1.0 flat.
- **N3.** Multi-region context replication. v1.0 single Dhara region; v2.0 may extend.
- **N4.** Bulk tenant onboarding. v1.0 one-at-a-time via CLI; v2.0 may add import/export.

---

## Architecture & Data Flow

```
MCP server (Cloud Run instance, stateless):
  ┌──────────────────────────────────────────────────────────────┐
  │  Request arrives with X-Tenant-Id header                     │
  │    tenant_id = request.headers["X-Tenant-Id"]               │
  │    bundle = await load_active_bundle(tenant_id)  # Dhara    │
  │                                                                │
  │    Inject into agent prompt:                                   │
  │      System prompt block:                                       │
  │        ---                                                     │
  │        # Tenant Context                                         │
  │        ## Voice                                                │
  │        <bundle.voice>                                          │
  │        ## ICP                                                  │
  │        <bundle.icp>                                            │
  │        ## Positioning                                          │
  │        <bundle.positioning>                                    │
  │        ## Visual Identity                                      │
  │        <bundle.visual_identity>                                │
  │        ---                                                     │
  │                                                                │
  │    Agent runs with tenant context;                              │
  │    Output respects tenant's voice, ICP, positioning.            │
  └──────────────────────────────────────────────────────────────┘

Dhara (persistent):
  ┌──────────────────────────────────────────────────────────────┐
  │  Tables:                                                       │
  │    tenant_context_versions (append-only; partial unique idx)   │
  │    tenant_context_files (per-version, 4 rows per version)     │
  └──────────────────────────────────────────────────────────────┘

Operator workflow:
  mahavishnu tenant context update <tenant_id> --file voice --content <md>
    → New context version; old deactivated; new active.
```

---

## Storage Schema (Dhara)

### `tenant_context_versions`

```sql
CREATE TABLE IF NOT EXISTS tenant_context_versions (
    version_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    activated_at TEXT NOT NULL,
    deactivated_at TEXT,
    activated_by TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_context_one_active
    ON tenant_context_versions (tenant_id)
    WHERE deactivated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tenant_context_versions_tenant_time
    ON tenant_context_versions (tenant_id, activated_at DESC);
```

### `tenant_context_files`

```sql
CREATE TABLE IF NOT EXISTS tenant_context_files (
    file_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    file_name TEXT NOT NULL,            -- "voice" | "icp" | "positioning" | "visual_identity"
    content TEXT NOT NULL,
    UNIQUE (version_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_tenant_context_files_version
    ON tenant_context_files (version_id);
```

---

## Python API

```python
# mahavishnu/core/tenant_context.py

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


DharaClient = httpx.AsyncClient(
    base_url=os.environ.get("MAHAVISHNU_DHARA_URL", "http://localhost:8683"),
    timeout=httpx.Timeout(5.0),
)

CONTEXT_FILES = ("voice", "icp", "positioning", "visual_identity")


async def load_active_bundle(tenant_id: str) -> dict[str, str] | None:
    """Load the active bundle for a tenant. Returns {file_name: content} or None."""
    version_resp = await DharaClient.get(f"/tenants/{tenant_id}/active-context-version")
    if version_resp.status_code == 404:
        return None
    version_resp.raise_for_status()
    version = version_resp.json()

    files_resp = await DharaClient.get(
        f"/tenants/{tenant_id}/context-versions/{version['version_id']}/files"
    )
    files_resp.raise_for_status()
    files = files_resp.json()
    return {f["file_name"]: f["content"] for f in files}


async def update_context_file(
    tenant_id: str,
    file_name: str,
    content: str,
    *,
    activated_by: str,
    notes: str = "",
) -> dict:
    """Atomically: deactivate current version + insert new with updated file.

    Other 3 files are inherited from the previous version (unchanged unless
    explicitly provided in this call).
    """
    if file_name not in CONTEXT_FILES:
        raise ValueError(
            f"unknown context file: {file_name!r}; expected one of {CONTEXT_FILES}"
        )

    resp = await DharaClient.post(
        f"/tenants/{tenant_id}/context-versions",
        json={
            "activated_by": activated_by,
            "notes": notes,
            "updated_file": {"file_name": file_name, "content": content},
        },
    )
    resp.raise_for_status()
    return resp.json()
```

---

## Per-Request Middleware

```python
# mahavishnu/mcp/middleware/tenant_context.py

from fastmcp import Context

from mahavishnu.core.tenant_context import load_active_bundle, CONTEXT_FILES


async def resolve_tenant_context(ctx: Context) -> dict[str, str] | None:
    """Per-request middleware: load tenant context bundle from Dhara.

    Called by the agent's prompt assembly. If X-Tenant-Id header is missing
    or tenant has no active bundle, returns None.
    """
    tenant_id = ctx.request.headers.get("X-Tenant-Id")
    if not tenant_id:
        return None
    return await load_active_bundle(tenant_id)


def format_tenant_context_block(bundle: dict[str, str]) -> str:
    """Format the tenant context as a system-prompt block."""
    sections: list[str] = []
    for file_name in CONTEXT_FILES:
        content = bundle.get(file_name, "")
        if content:
            title = file_name.replace("_", " ").title()
            sections.append(f"## {title}\n{content}")
    if not sections:
        return ""
    return "# Tenant Context\n\n" + "\n\n".join(sections)
```

### Prompt Assembly

The agent's system prompt is constructed per-request:

```python
async def assemble_system_prompt(ctx: Context, base_prompt: str) -> str:
    """Inject tenant context block into the base system prompt."""
    bundle = await resolve_tenant_context(ctx)
    if bundle is None:
        return base_prompt
    block = format_tenant_context_block(bundle)
    return f"{base_prompt}\n\n{block}"
```

---

## MCP Tools

```python
@mcp_tool
async def get_tenant_context(tenant_id: str) -> dict:
    """Return the active tenant context bundle (all 4 files)."""

@mcp_tool
async def update_tenant_context_file(
    tenant_id: str,
    file_name: str,
    content: str,
    *,
    notes: str = "",
    activated_by: str = "system:mcp",
) -> dict:
    """Update one file in the tenant context. Creates a new version."""
```

---

## CLI Commands

```python
# mahavishnu/cli/tenant_cli.py

import typer

from mahavishnu.core.tenant_context import load_active_bundle, update_context_file


tenant_app = typer.Typer(help="Tenant management")


@tenant_app.command("context")
def tenant_context_cmd(
    tenant_id: str = typer.Argument(help="Tenant ID"),
    file_name: str = typer.Option(None, "--file", help="voice|icp|positioning|visual_identity"),
    content: str = typer.Option(None, "--content", help="New content for --file"),
    notes: str = typer.Option("", "--notes", help="Reason for update"),
):
    """Show or update tenant context files."""
    if file_name is None and content is None:
        # Show all 4 files.
        bundle = asyncio.run(load_active_bundle(tenant_id))
        if bundle is None:
            typer.echo(f"No active bundle for tenant {tenant_id}.")
            raise typer.Exit(code=1)
        for fname in ("voice", "icp", "positioning", "visual_identity"):
            typer.echo(f"## {fname}")
            typer.echo(bundle.get(fname, "(empty)"))
            typer.echo()
    elif file_name is not None and content is not None:
        # Update.
        asyncio.run(update_context_file(
            tenant_id=tenant_id,
            file_name=file_name,
            content=content,
            activated_by="system:cli",
            notes=notes,
        ))
        typer.echo(f"Updated {file_name} for tenant {tenant_id}.")
    else:
        typer.echo("Provide both --file and --content to update, or neither to show.")
        raise typer.Exit(code=1)
```

Register in `mahavishnu/cli/__init__.py`:

```python
from mahavishnu.cli.tenant_cli import tenant_app

main_app.add_typer(tenant_app, name="tenant")
```

---

## Adoption & Migration

| Version | Adoption |
|---|---|
| **v1.0** | Dhara tables created. Per-request tenant resolution middleware shipped. 4-file bundle format. CLI and MCP tools for read/update. Tenants created on first request. |
| **v1.1** | Per-tenant in-memory cache with TTL. Reduced Dhara load for high-traffic tenants. |
| **v2.0** | Multi-region context replication; bulk tenant onboarding via import/export. |

---

## Storage & Retrieval

**Dhara tables** — append-only. Versions form an immutable history per tenant.

**Per-request middleware** loads the active bundle fresh. No local caching in v1.0.

**MCP tools** for query/update. CLI for operator convenience.

---

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Missing X-Tenant-Id header | `ctx.request.headers.get` returns None | `resolve_tenant_context` returns None; caller decides fallback (no context, or default tenant). |
| Tenant has no active bundle | Dhara returns 404 | Returns None; caller decides fallback. |
| Invalid file_name | `file_name not in CONTEXT_FILES` | Raises `ValueError`. |
| Dhara HTTP timeout | `httpx.TimeoutException` | Returns None; logs error. Caller retries on next request. |
| Concurrent context update | Dhara's partial unique index rejects second active version | Second call retries with exponential backoff; if persistent, surfaces 409 to operator. |

---

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | `load_active_bundle` returns correct shape; missing fields default to empty string. `update_context_file` validates file_name. |
| **L1 (file isolation)** | Real filesystem + mocked Dhara: bundle serialized correctly. |
| **L2 (service isolation)** | Mocked Dhara client: `load_active_bundle` returns mocked bundle; `update_context_file` posts correct payload. |
| **L3 (sandbox)** | Real Dhara: full bundle lifecycle. Insert v1 → activate v2 (atomic) → both versions exist; v1 deactivated. |
| **L4 (integration)** | MCP server test: request with X-Tenant-Id → middleware loads bundle → system prompt contains tenant context. |

**Coverage target:** `tests/unit/test_tenant_context.py` ≥ 95% line coverage.

---

## Implementation Module Paths

| Component | Path |
|---|---|
| Python API | `mahavishnu/core/tenant_context.py` |
| Dhara migrations | `mahavishnu/core/dhara_migrations/tenant_context.sql` |
| MCP middleware | `mahavishnu/mcp/middleware/tenant_context.py` |
| MCP tools | `mahavishnu/mcp/tools/tenant_context_tools.py` |
| CLI | `mahavishnu/cli/tenant_cli.py` |
| L0/L1/L2 tests | `tests/unit/test_tenant_context.py` |
| L3 tests | `tests/integration/test_tenant_context_dhara.py` |
| L4 tests | `tests/integration/test_tenant_context_middleware.py` |

---

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| 4-file bundle (article-faithful) | Clean separation of concerns; each file answers one question | Single file — harder to evolve individual dimensions |
| Versioned immutable history | Forensic recall: "what was tenant X's voice when this MR was generated?" | Single mutable — unanswerable for past times |
| Dhara storage | ACID; HTTP API works for serverless | Local filesystem — lost on cold start |
| Per-request middleware load | Stateless; consistent with Cloud Run model | Cache at startup — stale on updates |
| Other 3 files inherited on single-file update | Operators edit one dimension at a time | All 4 files required per update — high friction |
| Partial unique index on active version | DB-enforced single-active-version; no race conditions | App-level enforcement — possible inconsistency |
| HTTP header tenant identification | Standard HTTP mechanism; easy to debug | Auth-token-based — couples to auth scheme |

---

## Open Questions / Future Work

- **OQ1.** Tenant identification: HTTP header `X-Tenant-Id` (assumed) vs auth token claims vs API key. v1.0 header; v1.1 may add token-based.
- **OQ2.** Per-tenant caching: TTL cache in request handler. v1.0 no cache; v1.1 may add.
- **OQ3.** Default tenant: if `X-Tenant-Id` is missing, use a default. v1.0 strict (None); v1.1 may add fallback.
- **OQ4.** Bundle inheritance: can a tenant inherit from a parent (org → sub-tenant)? v1.0 flat; v1.1 may add.
- **OQ5.** Bundle schema migration: when `CONTEXT_FILES` gains a 5th file, existing tenants need migration. v1.0 doesn't address; v1.1 may add migration tooling.

---

## Success Criteria

- **SC1.** Dhara tables (`tenant_context_versions`, `tenant_context_files`) created and migration-applied.
- **SC2.** Partial unique index enforces single-active-version per tenant.
- **SC3.** Per-request middleware loads bundle from Dhara; system prompt contains formatted tenant context block.
- **SC4.** CLI `mahavishnu tenant context` shows and updates bundles.
- **SC5.** MCP tools (`get_tenant_context`, `update_tenant_context_file`) shipped.
- **SC6.** Update of one file atomically creates new version; old version preserved in history.
- **SC7.** L0–L4 tests green; ≥ 95% line coverage on new modules.
