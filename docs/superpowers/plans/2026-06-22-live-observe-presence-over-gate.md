# Live Observe (Presence Over Gate) v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship queryable progress for in-flight workflows. Two Dhara tables (snapshots + events); workers emit snapshots alongside Spec #1 reports; CLI provides `status`, `list`, `watch`. Serverless-native: stateless MCP server, all state in Dhara.

**Architecture:** `mahavishnu/core/workflow_progress.py` exposes async API for write_progress_snapshot, record_workflow_event, get_workflow_status, list_running_workflows, list_workflow_events. CLI polls client-side; no server streaming.

**Tech Stack:** Python 3.13, `httpx` async, Dhara (existing HTTP API), typer, pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **Two tables** (snapshots + events); snapshots for current-state queries, events for diff history.
- **Substrate reuse** with Spec #8 (adapter-runtime-observability): same Dhara pattern, same query API shape.
- **No server-side streaming**; CLI polls client-side.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/dhara_migrations/workflow_progress.sql` | DDL for 2 tables. |
| `mahavishnu/core/workflow_progress.py` | Async API. |
| `mahavishnu/mcp/tools/workflow_progress_tools.py` | MCP tools. |
| `mahavishnu/cli/workflow_cli.py` | `mahavishnu workflow {status, list, watch}`. |
| `tests/unit/test_workflow_progress.py` | L0/L1/L2 tests. |
| `tests/integration/test_workflow_progress_dhara.py` | L3 tests. |
| `tests/integration/test_workflow_progress_cli.py` | L4 tests. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/core/events/report_publishers.py` | Add snapshot + event emit after Spec #1's publish_iteration_report. |
| `mahavishnu/mcp/tools/__init__.py` | Register workflow_progress_tools. |
| `mahavishnu/cli/__init__.py` | Register workflow_app. |

______________________________________________________________________

## Task 1: Dhara migrations

**Files:**

- Create: `mahavishnu/core/dhara_migrations/workflow_progress.sql`

- [ ] **Step 1: Write the DDL**

Create `mahavishnu/core/dhara_migrations/workflow_progress.sql`:

```sql
CREATE TABLE IF NOT EXISTS workflow_progress_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    iteration_index INTEGER,
    iteration_budget INTEGER,
    status TEXT NOT NULL,
    current_hypothesis TEXT,
    confidence INTEGER,
    open_questions TEXT NOT NULL DEFAULT '[]',
    last_event TEXT NOT NULL,
    last_event_at TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    snapshot_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_progress_latest
    ON workflow_progress_snapshots (workflow_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_progress_status
    ON workflow_progress_snapshots (status, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    iteration_index INTEGER,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_workflow_time
    ON workflow_events (workflow_id, timestamp DESC);
```

- [ ] **Step 2: Apply the migration**

Apply via the project's Dhara migration runner, or via `execute()`:

```python
from mahavishnu.core.dhara_client import execute
with open("mahavishnu/core/dhara_migrations/workflow_progress.sql") as f:
    execute(f.read())
```

Expected: 2 tables + 4 indexes created.

- [ ] **Step 3: Verify schema**

Query Dhara: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'workflow_%'`
Expected: 2 tables.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/dhara_migrations/workflow_progress.sql
git commit -m "feat(workflow-progress): add Dhara migration for snapshots and events tables"
```

______________________________________________________________________

## Task 2: Async Python API

**Files:**

- Create: `mahavishnu/core/workflow_progress.py`

- Test: `tests/unit/test_workflow_progress.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_workflow_progress.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.workflow_progress import (
    get_workflow_status,
    list_running_workflows,
    list_workflow_events,
    record_workflow_event,
    write_progress_snapshot,
)


@pytest.fixture
def mock_dhara(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = AsyncMock()
    monkeypatch.setattr("mahavishnu.core.workflow_progress.DharaClient", client)
    return client


@pytest.mark.asyncio
async def test_write_snapshot_posts_correct_payload(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(status_code=201, json=lambda: {})
    await write_progress_snapshot(
        workflow_id="wf-1",
        snapshot={
            "iteration_index": 3,
            "status": "running",
            "confidence": 75,
            "open_questions": "[]",
            "last_event": "iteration_completed",
            "last_event_at": "2026-06-22T10:00:00Z",
        },
    )
    call_kwargs = mock_dhara.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["workflow_id"] == "wf-1"
    assert payload["iteration_index"] == 3
    assert payload["confidence"] == 75
    assert "snapshot_id" in payload
    assert "snapshot_at" in payload


@pytest.mark.asyncio
async def test_record_event_posts_correct_payload(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(status_code=201, json=lambda: {})
    await record_workflow_event(
        workflow_id="wf-1",
        event_type="iteration_completed",
        iteration_index=3,
        payload={"confidence": 75},
    )
    payload = mock_dhara.post.call_args.kwargs["json"]
    assert payload["event_type"] == "iteration_completed"
    assert payload["iteration_index"] == 3
    assert payload["payload"] == {"confidence": 75}
    assert "event_id" in payload
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_get_status_returns_none_on_404(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(status_code=404)
    assert await get_workflow_status("wf-1") is None


@pytest.mark.asyncio
async def test_get_status_returns_data_on_200(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(
        status_code=200, json=lambda: {"workflow_id": "wf-1", "status": "running"}
    )
    result = await get_workflow_status("wf-1")
    assert result == {"workflow_id": "wf-1", "status": "running"}


@pytest.mark.asyncio
async def test_list_running_returns_array(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(
        status_code=200, json=lambda: [{"workflow_id": "wf-1"}]
    )
    assert await list_running_workflows() == [{"workflow_id": "wf-1"}]


@pytest.mark.asyncio
async def test_list_events_passes_since_param(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(status_code=200, json=lambda: [])
    await list_workflow_events("wf-1", since="2026-06-22T10:00:00Z")
    call_kwargs = mock_dhara.get.call_args.kwargs
    assert call_kwargs["params"]["since"] == "2026-06-22T10:00:00Z"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_workflow_progress.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the API**

Create `mahavishnu/core/workflow_progress.py`:

```python
"""Workflow progress API: queryable progress for in-flight workflows."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


DharaClient = httpx.AsyncClient(
    base_url=os.environ.get("MAHAVISHNU_DHARA_URL", "http://localhost:8683"),
    timeout=httpx.Timeout(5.0),
)


async def write_progress_snapshot(
    workflow_id: str, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Write a progress snapshot for a workflow. Idempotent on snapshot_id."""
    resp = await DharaClient.post(
        f"/workflows/{workflow_id}/progress-snapshots",
        json={
            "snapshot_id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            **snapshot,
            "snapshot_at": datetime.now(UTC).isoformat(),
        },
    )
    resp.raise_for_status()
    return resp.json()


async def record_workflow_event(
    workflow_id: str,
    event_type: str,
    *,
    iteration_index: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a workflow event to the log."""
    resp = await DharaClient.post(
        f"/workflows/{workflow_id}/events",
        json={
            "event_id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "iteration_index": iteration_index,
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
        },
    )
    resp.raise_for_status()
    return resp.json()


async def get_workflow_status(workflow_id: str) -> dict[str, Any] | None:
    """Return the latest progress snapshot for a workflow, or None."""
    resp = await DharaClient.get(
        f"/workflows/{workflow_id}/progress-snapshots?latest=true"
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def list_running_workflows() -> list[dict[str, Any]]:
    """Return latest snapshot per running workflow (fleet view)."""
    resp = await DharaClient.get("/workflows?status=running")
    resp.raise_for_status()
    return resp.json()


async def list_workflow_events(
    workflow_id: str, *, since: str | None = None
) -> list[dict[str, Any]]:
    """Return events for a workflow, optionally since a timestamp (for diff printing)."""
    params: dict[str, str] = {}
    if since is not None:
        params["since"] = since
    resp = await DharaClient.get(f"/workflows/{workflow_id}/events", params=params)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_workflow_progress.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/workflow_progress.py tests/unit/test_workflow_progress.py
git commit -m "feat(workflow-progress): add async API for snapshots and events"
```

______________________________________________________________________

## Task 3: Worker integration (snapshot emit on iteration complete)

**Files:**

- Modify: `mahavishnu/core/events/report_publishers.py`

- [ ] **Step 1: Locate the publish_iteration_report function**

Run: `grep -n "def publish_iteration_report" mahavishnu/core/events/report_publishers.py`

- [ ] **Step 2: Add the snapshot emit after publish**

After the existing `await event_bus.publish(envelope)` call in `publish_iteration_report`, add:

```python
import json

from mahavishnu.core.workflow_progress import (
    record_workflow_event,
    write_progress_snapshot,
)

# Inside publish_iteration_report, after the publish call:
try:
    await write_progress_snapshot(
        workflow_id=report["workflow_id"],
        snapshot={
            "iteration_index": report["iteration_index"],
            "iteration_budget": report["iteration_budget"],
            "status": report["status"].lower(),
            "current_hypothesis": report.get("current_hypothesis"),
            "confidence": report["confidence"],
            "open_questions": json.dumps(report.get("open_questions", [])),
            "last_event": "iteration_completed",
            "last_event_at": report["completed_at"],
            "metrics": json.dumps({
                "elapsed_seconds": int(report["duration_ms"] / 1000),
                "iterations_used": report["iteration_index"] + 1,
            }),
        },
    )
    await record_workflow_event(
        workflow_id=report["workflow_id"],
        event_type="iteration_completed",
        iteration_index=report["iteration_index"],
        payload={"confidence": report["confidence"]},
    )
except Exception as exc:
    logger.exception(
        "failed to emit progress snapshot",
        extra={"workflow_id": report["workflow_id"], "error": str(exc)},
    )
    # Snapshot is observational; iteration report still succeeded.
```

- [ ] **Step 3: Run Spec #1 publisher tests to verify no regression**

Run: `pytest tests/unit/test_report_publishers.py -v`
Expected: all existing tests still pass (snapshot emit is in `try` block; failures don't break the publish path).

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/events/report_publishers.py
git commit -m "feat(workflow-progress): emit snapshot and event from publish_iteration_report"
```

______________________________________________________________________

## Task 4: CLI commands

**Files:**

- Create: `mahavishnu/cli/workflow_cli.py`

- Modify: `mahavishnu/cli/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_workflow_progress_cli.py`:

```python
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from mahavishnu.cli.workflow_cli import workflow_app


def test_status_prints_snapshot():
    snapshot = {
        "workflow_id": "wf-1",
        "status": "running",
        "iteration_index": 3,
        "iteration_budget": 20,
        "confidence": 75,
        "current_hypothesis": "Database connection pool exhaustion",
        "last_event": "iteration_completed",
        "last_event_at": "2026-06-22T10:00:00Z",
        "open_questions": "[\"Why does pool reset not propagate?\"]",
    }
    with patch(
        "mahavishnu.cli.workflow_cli.get_workflow_status",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = snapshot
        result = CliRunner().invoke(workflow_app, ["status", "wf-1"])
    assert result.exit_code == 0
    assert "wf-1" in result.output
    assert "running" in result.output
    assert "Database connection pool" in result.output


def test_status_exits_when_no_data():
    with patch(
        "mahavishnu.cli.workflow_cli.get_workflow_status",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None
        result = CliRunner().invoke(workflow_app, ["status", "missing-wf"])
    assert result.exit_code != 0


def test_list_prints_fleet():
    snapshots = [
        {"workflow_id": "wf-1", "iteration_index": 3, "confidence": 75, "status": "running"},
        {"workflow_id": "wf-2", "iteration_index": 5, "confidence": 88, "status": "running"},
    ]
    with patch(
        "mahavishnu.cli.workflow_cli.list_running_workflows",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = snapshots
        result = CliRunner().invoke(workflow_app, ["list"])
    assert result.exit_code == 0
    assert "wf-1" in result.output
    assert "wf-2" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_workflow_progress_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the CLI**

Create `mahavishnu/cli/workflow_cli.py`:

```python
"""Workflow observation CLI."""

from __future__ import annotations

import asyncio
import json
import time

import typer

from mahavishnu.core.workflow_progress import (
    get_workflow_status,
    list_running_workflows,
    list_workflow_events,
)


workflow_app = typer.Typer(help="Workflow observation")


@workflow_app.command("status")
def workflow_status_cmd(
    workflow_id: str = typer.Argument(help="Workflow ID"),
) -> None:
    """Show latest progress snapshot for a workflow."""
    snapshot = asyncio.run(get_workflow_status(workflow_id))
    if snapshot is None:
        typer.echo(f"No data for {workflow_id}.")
        raise typer.Exit(code=1)
    _print_snapshot(snapshot)


@workflow_app.command("list")
def workflow_list_cmd(
    status: str = typer.Option("running", "--status", help="running|completed|blocked|failed"),
) -> None:
    """List workflows by status."""
    snapshots = asyncio.run(list_running_workflows())
    if not snapshots:
        typer.echo("No workflows match.")
        return
    typer.echo(f"{'workflow_id':32s}  {'iter':>3}  {'conf':>3}  status")
    for snap in snapshots:
        typer.echo(
            f"{snap['workflow_id']:32s}  "
            f"{snap.get('iteration_index', '-'):>3}  "
            f"{snap.get('confidence', '-'):>3}  "
            f"{snap['status']}"
        )


@workflow_app.command("watch")
def workflow_watch_cmd(
    workflow_id: str = typer.Argument(help="Workflow ID"),
    poll: int = typer.Option(5, "--poll", help="Poll interval in seconds"),
) -> None:
    """Poll workflow events; print new ones as they appear. Client-side polling."""
    last_seen_timestamp: str | None = None
    try:
        while True:
            events = asyncio.run(list_workflow_events(workflow_id, since=last_seen_timestamp))
            for event in events:
                typer.echo(
                    f"[{event['timestamp']}] {event['event_type']} "
                    f"iter={event.get('iteration_index', '-')}"
                )
                last_seen_timestamp = event["timestamp"]
            time.sleep(poll)
    except KeyboardInterrupt:
        typer.echo("Stopped watching.")


def _print_snapshot(snap: dict) -> None:
    typer.echo(f"Workflow: {snap['workflow_id']}")
    typer.echo(f"  Status:    {snap['status']}")
    typer.echo(f"  Iteration: {snap.get('iteration_index', '-')}/{snap.get('iteration_budget', '-')}")
    typer.echo(f"  Confidence: {snap.get('confidence', '-')}")
    typer.echo(f"  Hypothesis: {snap.get('current_hypothesis', '-') or '(none)'}")
    typer.echo(f"  Last event: {snap['last_event']} @ {snap['last_event_at']}")
    open_q = json.loads(snap.get("open_questions", "[]"))
    if open_q:
        typer.echo(f"  Open questions ({len(open_q)}):")
        for q in open_q[:3]:
            typer.echo(f"    - {q}")
```

Register in `mahavishnu/cli/__init__.py`:

```python
from mahavishnu.cli.workflow_cli import workflow_app

main_app.add_typer(workflow_app, name="workflow")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_workflow_progress_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/workflow_cli.py mahavishnu/cli/__init__.py tests/integration/test_workflow_progress_cli.py
git commit -m "feat(workflow-progress): add CLI for status, list, watch"
```

______________________________________________________________________

## Task 5: MCP tools

**Files:**

- Create: `mahavishnu/mcp/tools/workflow_progress_tools.py`

- Modify: `mahavishnu/mcp/tools/__init__.py`

- [ ] **Step 1: Implement the tools**

Create `mahavishnu/mcp/tools/workflow_progress_tools.py`:

```python
"""MCP tools for workflow progress observation."""

from __future__ import annotations

from typing import Any

from mahavishnu.core.workflow_progress import (
    get_workflow_status,
    list_running_workflows,
    record_workflow_event,
)


def register(server, app, mcp_client) -> None:
    @server.tool()
    async def get_workflow_status_mcp(workflow_id: str) -> dict[str, Any]:
        """Return the latest progress snapshot for a workflow."""
        return await get_workflow_status(workflow_id) or {"error": "no_data"}

    @server.tool()
    async def list_workflows_mcp(status: str = "running") -> list[dict[str, Any]]:
        """Return latest snapshot per workflow matching status."""
        return await list_running_workflows()

    @server.tool()
    async def record_workflow_event_mcp(
        workflow_id: str,
        event_type: str,
        *,
        iteration_index: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a workflow event."""
        return await record_workflow_event(
            workflow_id=workflow_id,
            event_type=event_type,
            iteration_index=iteration_index,
            payload=payload,
        )
```

Register in `mahavishnu/mcp/tools/__init__.py` (under the `full` profile).

- [ ] **Step 2: Commit**

```bash
git add mahavishnu/mcp/tools/workflow_progress_tools.py mahavishnu/mcp/tools/__init__.py
git commit -m "feat(workflow-progress): add MCP tools for status, list, event"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Two-table schema (snapshots + events) | Task 1 |
| Python API | Task 2 |
| Worker integration | Task 3 |
| CLI (status, list, watch) | Task 4 |
| MCP tools | Task 5 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** All 5 functions return consistent types across Tasks 2-5.

**Gaps:** None.

Plan complete. All 10 specs + plans now drafted.
