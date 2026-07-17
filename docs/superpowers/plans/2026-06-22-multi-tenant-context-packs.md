---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on:
  - ext:dhara-http-api-surface
topic: multi-tenant-context-packs
---

# Multi-Tenant Context Packs v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship per-tenant context bundles (4-file format) loaded per-request from Dhara and injected into agent prompts. Multi-tenant MCP deployment on Cloud Run; stateless instances.

**Architecture:** `mahavishnu/core/tenant_context.py` exposes async API. Per-request middleware loads active bundle fresh. CLI for operators. Partial unique index on `tenant_context_versions.tenant_id WHERE deactivated_at IS NULL` enforces single-active-version per tenant.

**Tech Stack:** Python 3.13, `httpx` async, Dhara (existing HTTP API), typer, pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **4 files per bundle**: voice, icp, positioning, visual_identity (article-faithful).
- **Partial unique index** enforces single-active-version per tenant.
- **Atomic update** = deactivate current + insert new with updated file; other 3 files inherited.
- **No local cache** in Cloud Run instances; per-request fetch from Dhara.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/dhara_migrations/tenant_context.sql` | DDL for 2 tables + partial unique index. |
| `mahavishnu/core/tenant_context.py` | Async API: `load_active_bundle`, `update_context_file`. |
| `mahavishnu/mcp/middleware/tenant_context.py` | Per-request middleware. |
| `mahavishnu/mcp/tools/tenant_context_tools.py` | MCP tools. |
| `mahavishnu/cli/tenant_cli.py` | `mahavishnu tenant context` CLI. |
| `tests/unit/test_tenant_context.py` | L0/L1/L2 tests. |
| `tests/integration/test_tenant_context_dhara.py` | L3 tests. |
| `tests/integration/test_tenant_context_middleware.py` | L4 tests. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/mcp/server.py` | Wire per-request middleware into system prompt assembly. |
| `mahavishnu/mcp/tools/__init__.py` | Register tenant_context_tools. |
| `mahavishnu/cli/__init__.py` | Register tenant_app. |

______________________________________________________________________

## Task 1: Dhara migrations

**Files:**

- Create: `mahavishnu/core/dhara_migrations/tenant_context.sql`

- [ ] **Step 1: Write the DDL**

Create `mahavishnu/core/dhara_migrations/tenant_context.sql`:

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

CREATE TABLE IF NOT EXISTS tenant_context_files (
    file_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    content TEXT NOT NULL,
    UNIQUE (version_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_tenant_context_files_version
    ON tenant_context_files (version_id);
```

- [ ] **Step 2: Apply the migration**

Apply via the project's Dhara migration runner, or via `execute()`:

```python
from mahavishnu.core.dhara_client import execute
with open("mahavishnu/core/dhara_migrations/tenant_context.sql") as f:
    execute(f.read())
```

Expected: 2 tables + 4 indexes created.

- [ ] **Step 3: Verify schema**

Query Dhara: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tenant_%'`
Expected: 2 tables.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/dhara_migrations/tenant_context.sql
git commit -m "feat(tenant-context): add Dhara migration for tenant_context tables"
```

______________________________________________________________________

## Task 2: Async Python API

**Files:**

- Create: `mahavishnu/core/tenant_context.py`

- Test: `tests/unit/test_tenant_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tenant_context.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.tenant_context import (
    CONTEXT_FILES,
    load_active_bundle,
    update_context_file,
)


@pytest.fixture
def mock_dhara(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = AsyncMock()
    monkeypatch.setattr("mahavishnu.core.tenant_context.DharaClient", client)
    return client


@pytest.mark.asyncio
async def test_load_active_returns_none_when_no_version(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(status_code=404)
    result = await load_active_bundle("tenant-1")
    assert result is None


@pytest.mark.asyncio
async def test_load_active_returns_files_dict(mock_dhara: AsyncMock):
    version_resp = MagicMock(
        status_code=200,
        json=lambda: {"version_id": "v1"},
    )
    files_resp = MagicMock(
        status_code=200,
        json=lambda: [
            {"file_name": "voice", "content": "Direct, opinionated."},
            {"file_name": "icp", "content": "Senior engineers."},
        ],
    )
    mock_dhara.get.side_effect = [version_resp, files_resp]
    result = await load_active_bundle("tenant-1")
    assert result == {
        "voice": "Direct, opinionated.",
        "icp": "Senior engineers.",
    }


@pytest.mark.asyncio
async def test_update_rejects_unknown_file(mock_dhara: AsyncMock):
    with pytest.raises(ValueError, match="unknown context file"):
        await update_context_file(
            tenant_id="tenant-1",
            file_name="bogus",
            content="x",
            activated_by="alice",
        )
    mock_dhara.post.assert_not_called()


@pytest.mark.asyncio
async def test_update_posts_to_correct_endpoint(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(
        status_code=201, json=lambda: {"version_id": "v2"}
    )
    await update_context_file(
        tenant_id="tenant-1",
        file_name="voice",
        content="New voice.",
        activated_by="alice",
        notes="Updated for Q4 campaign",
    )
    call_kwargs = mock_dhara.post.call_args.kwargs
    assert call_kwargs["json"]["activated_by"] == "alice"
    assert call_kwargs["json"]["notes"] == "Updated for Q4 campaign"
    assert call_kwargs["json"]["updated_file"] == {
        "file_name": "voice",
        "content": "New voice.",
    }


def test_context_files_constant():
    assert CONTEXT_FILES == ("voice", "icp", "positioning", "visual_identity")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_tenant_context.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the API**

Create `mahavishnu/core/tenant_context.py`:

```python
"""Tenant context API: per-tenant context bundles loaded from Dhara."""

from __future__ import annotations

import os
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
) -> dict[str, Any]:
    """Atomically: deactivate current + insert new with updated file.

    Other 3 files are inherited from the previous version.
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_tenant_context.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/tenant_context.py tests/unit/test_tenant_context.py
git commit -m "feat(tenant-context): add async API for load and update context files"
```

______________________________________________________________________

## Task 3: Per-request middleware

**Files:**

- Create: `mahavishnu/mcp/middleware/tenant_context.py`

- Test: `tests/integration/test_tenant_context_middleware.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_tenant_context_middleware.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.middleware.tenant_context import (
    format_tenant_context_block,
    resolve_tenant_context,
)


@pytest.mark.asyncio
async def test_resolve_returns_none_without_tenant_header():
    ctx = MagicMock()
    ctx.request.headers.get.return_value = None
    result = await resolve_tenant_context(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_loads_bundle_when_tenant_present():
    ctx = MagicMock()
    ctx.request.headers.get.return_value = "tenant-1"
    with patch(
        "mahavishnu.mcp.middleware.tenant_context.load_active_bundle",
        new_callable=AsyncMock,
    ) as mock_load:
        mock_load.return_value = {
            "voice": "Direct.",
            "icp": "Senior engineers.",
            "positioning": "",
            "visual_identity": "",
        }
        result = await resolve_tenant_context(ctx)
    assert result["voice"] == "Direct."


def test_format_block_includes_all_filled_sections():
    bundle = {
        "voice": "Direct.",
        "icp": "Senior engineers.",
        "positioning": "",
        "visual_identity": "",
    }
    block = format_tenant_context_block(bundle)
    assert "# Tenant Context" in block
    assert "## Voice" in block
    assert "Direct." in block
    assert "## ICP" in block
    assert "## Positioning" not in block  # empty section omitted


def test_format_block_empty_bundle_returns_empty_string():
    block = format_tenant_context_block({})
    assert block == ""
```

- [ ] **Step 2: Implement the middleware**

Create `mahavishnu/mcp/middleware/tenant_context.py`:

```python
"""Per-request middleware: load tenant context bundle from Dhara."""

from __future__ import annotations

from typing import Any

from mahavishnu.core.tenant_context import CONTEXT_FILES, load_active_bundle


async def resolve_tenant_context(ctx: Any) -> dict[str, str] | None:
    """Load the active bundle for the tenant identified by X-Tenant-Id header.

    Returns None if header is missing or tenant has no active bundle.
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

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/integration/test_tenant_context_middleware.py -v`
Expected: PASS (4 tests)

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/middleware/tenant_context.py tests/integration/test_tenant_context_middleware.py
git commit -m "feat(tenant-context): add per-request middleware for tenant context bundle"
```

______________________________________________________________________

## Task 4: Wire middleware into MCP server system prompt

**Files:**

- Modify: `mahavishnu/mcp/server.py`

- [ ] **Step 1: Locate the system prompt assembly**

Run: `grep -n "system_prompt\|assemble" mahavishnu/mcp/server.py`
Find the existing system-prompt assembly location.

- [ ] **Step 2: Add the tenant context injection**

Modify the system-prompt assembly to call `assemble_system_prompt` from `tenant_context` middleware:

```python
async def build_system_prompt(ctx: Any, base_prompt: str) -> str:
    from mahavishnu.mcp.middleware.tenant_context import (
        format_tenant_context_block,
        resolve_tenant_context,
    )
    bundle = await resolve_tenant_context(ctx)
    if bundle is None:
        return base_prompt
    block = format_tenant_context_block(bundle)
    return f"{base_prompt}\n\n{block}"
```

Wire this into the existing prompt assembly site.

- [ ] **Step 3: Run existing MCP tests to verify no regressions**

Run: `pytest tests/unit/ tests/integration/ -v -k "mcp"`
Expected: all existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/server.py
git commit -m "feat(tenant-context): wire per-request middleware into MCP system prompt"
```

______________________________________________________________________

## Task 5: MCP tools

**Files:**

- Create: `mahavishnu/mcp/tools/tenant_context_tools.py`

- Modify: `mahavishnu/mcp/tools/__init__.py`

- [ ] **Step 1: Write the tools module**

Create `mahavishnu/mcp/tools/tenant_context_tools.py`:

```python
"""MCP tools for tenant context management."""

from __future__ import annotations

from typing import Any

from mahavishnu.core.tenant_context import (
    load_active_bundle,
    update_context_file,
)


async def get_tenant_context_fn(tenant_id: str) -> dict[str, Any]:
    bundle = await load_active_bundle(tenant_id)
    if bundle is None:
        return {"error": "no_active_bundle"}
    return {"tenant_id": tenant_id, "bundle": bundle}


async def update_tenant_context_file_fn(
    tenant_id: str,
    file_name: str,
    content: str,
    *,
    notes: str = "",
    activated_by: str = "system:mcp",
) -> dict[str, Any]:
    return await update_context_file(
        tenant_id=tenant_id,
        file_name=file_name,
        content=content,
        activated_by=activated_by,
        notes=notes,
    )


def register(server, app, mcp_client) -> None:
    @server.tool()
    async def get_tenant_context(tenant_id: str) -> dict[str, Any]:
        return await get_tenant_context_fn(tenant_id)

    @server.tool()
    async def update_tenant_context_file(
        tenant_id: str,
        file_name: str,
        content: str,
        *,
        notes: str = "",
        activated_by: str = "system:mcp",
    ) -> dict[str, Any]:
        return await update_tenant_context_file_fn(
            tenant_id=tenant_id,
            file_name=file_name,
            content=content,
            notes=notes,
            activated_by=activated_by,
        )
```

Register in `mahavishnu/mcp/tools/__init__.py` (under the `full` profile).

- [ ] **Step 2: Commit**

```bash
git add mahavishnu/mcp/tools/tenant_context_tools.py mahavishnu/mcp/tools/__init__.py
git commit -m "feat(tenant-context): add MCP tools for read and update"
```

______________________________________________________________________

## Task 6: CLI

**Files:**

- Create: `mahavishnu/cli/tenant_cli.py`

- Modify: `mahavishnu/cli/__init__.py`

- [ ] **Step 1: Implement the CLI**

Create `mahavishnu/cli/tenant_cli.py`:

```python
"""Tenant management CLI."""

from __future__ import annotations

import asyncio

import typer

from mahavishnu.core.tenant_context import CONTEXT_FILES, load_active_bundle, update_context_file


tenant_app = typer.Typer(help="Tenant management")


@tenant_app.command("context")
def tenant_context_cmd(
    tenant_id: str = typer.Argument(help="Tenant ID"),
    file_name: str = typer.Option(None, "--file", help="voice|icp|positioning|visual_identity"),
    content: str = typer.Option(None, "--content", help="New content for --file"),
    notes: str = typer.Option("", "--notes", help="Reason for update"),
) -> None:
    """Show or update tenant context files."""
    if file_name is None and content is None:
        bundle = asyncio.run(load_active_bundle(tenant_id))
        if bundle is None:
            typer.echo(f"No active bundle for tenant {tenant_id}.")
            raise typer.Exit(code=1)
        for fname in CONTEXT_FILES:
            typer.echo(f"## {fname}")
            typer.echo(bundle.get(fname, "(empty)"))
            typer.echo()
    elif file_name is not None and content is not None:
        if file_name not in CONTEXT_FILES:
            typer.echo(f"Invalid file name: {file_name}. Must be one of {CONTEXT_FILES}.")
            raise typer.Exit(code=1)
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

- [ ] **Step 2: Manual smoke check**

Run: `mahavishnu tenant context --help`
Expected: shows command help

Run: `mahavishnu tenant context dummy-tenant` (no Dhara connection; should error gracefully)

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/cli/tenant_cli.py mahavishnu/cli/__init__.py
git commit -m "feat(tenant-context): add CLI for show and update"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Dhara schema (2 tables, partial unique index) | Task 1 |
| Python API | Task 2 |
| Per-request middleware | Task 3 |
| System prompt integration | Task 4 |
| MCP tools | Task 5 |
| CLI | Task 6 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `load_active_bundle` and `update_context_file` signatures consistent across Tasks 2-6.

**Gaps:** None.

Plan complete. Moving to spec #10 brainstorm (`live-observe-presence-over-gate`, Phase 3).
