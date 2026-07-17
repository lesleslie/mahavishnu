---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on:
  - ext:dhara-http-api-surface
topic: observability
---

# Live Observe (Presence Over Gate) v1.0 — Design

**Status:** **DEFERRED** — blocked on Dhara HTTP API surface for `/workflows/<id>/progress-snapshots` (NOT blocked on in-process SQL `execute()` / `query()`; uses HTTP CRUD instead). Substrate reuse with Spec #8 (adapter-runtime-observability); Spec #9 integration for per-tenant access control on workflow queries.  <!-- legacy status: DEFERRED — see YAML frontmatter -->
**Phase:** 3 (Adjacent)
**Source:** `Building a Production Agent Harness` — "presence in the loop, not approval at the gate." The article's pattern was streaming updates; in our serverless context, this reframes to queryable progress (operator polls when curious; server stays stateless).

**Pivot from original spec name `live-observe-presence-over-gate`:** The original framing assumed long-lived streaming connections. Serverless constraints (Cloud Run instances are ephemeral) rule out persistent SSE/WebSocket for workflows of any length. The semantic shift: "presence" = *queryable progress* — the operator can ask "what is this workflow doing right now?" at any time and get a structured answer.

______________________________________________________________________

## Overview

This spec defines **queryable progress** for in-flight workflows. Two Dhara tables back the design:

- `workflow_progress_snapshots` — periodic state of a workflow (current iteration, current hypothesis, confidence, last event). One row per snapshot.
- `workflow_events` — append-only log of significant state changes (started, iteration_completed, hypothesis_changed, completed, failed). One row per event.

Workers emit snapshots alongside Spec #1 reports (no extra round-trip). Operators query the latest snapshot via CLI or MCP. A `mahavishnu workflow watch` command polls client-side; no server-side streaming.

**Architectural property:** Operators get near-real-time visibility (5-30s polling cadence is configurable) without the server holding connection state. Works on Cloud Run; survives instance replacement.

______________________________________________________________________

## Goals

- **G1.** Operator can ask "what is workflow X doing right now?" at any time and get a structured answer.
- **G2.** Operator can see fleet view: list all running workflows with current iteration + confidence + status.
- **G3.** Operator can poll (with diff-printing) a single workflow to see events as they happen.
- **G4.** Serverless-native: stateless MCP server, all state in Dhara.
- **G5.** Substrate reuse with Spec #8: same Dhara storage pattern, same query API shape.

## Non-Goals

- **N1.** Persistent SSE/WebSocket streaming. Serverless constraint rules this out.
- **N2.** Real-time push (latency < 1s). Polling cadence is 5-30s by default; tighter cadence is possible but not real-time.
- **N3.** Auto-suggested actions based on workflow state. v1.0 read-only.
- **N4.** Web dashboard. v2.0 candidate; v1.0 CLI only.

______________________________________________________________________

## Architecture & Data Flow

```
Cloud Run MCP server instance:
  ┌──────────────────────────────────────────────────────────────┐
  │  Workflow running (Spec #1-3 pipeline emits IterationReports)│
  │                                                                │
  │  On every iteration completion:                                │
  │    1. publish_iteration_report(report, source, correlation_id) │
  │         (Spec #1 — unchanged)                                  │
  │    2. write_progress_snapshot(workflow_id, snapshot)           │
  │         (this spec — new)                                       │
  │    3. record_workflow_event(workflow_id, event_type, payload)   │
  │         (this spec — new)                                       │
  └──────────────────────────────────────────────────────────────┘

Operator (on demand):
  ┌──────────────────────────────────────────────────────────────┐
  │  $ mahavishnu workflow status <id>          (single workflow)  │
  │  $ mahavishnu workflow list --status running  (fleet view)     │
  │  $ mahavishnu workflow watch <id> --poll 5  (client polling)  │
  │                                                                │
  │  All three query Dhara. No server-side streaming.             │
  └──────────────────────────────────────────────────────────────┘
```

______________________________________________________________________

## Storage Schema (Dhara)

### `workflow_progress_snapshots`

```sql
CREATE TABLE IF NOT EXISTS workflow_progress_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    iteration_index INTEGER,
    iteration_budget INTEGER,
    status TEXT NOT NULL,                 -- running | completed | blocked | failed | stalled
    current_hypothesis TEXT,
    confidence INTEGER,                  -- 0-100
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
```

### `workflow_events`

```sql
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

**Snapshots vs events distinction:**

- **Snapshots**: periodic state. Query "current state" is `SELECT * FROM snapshots WHERE workflow_id = ? ORDER BY snapshot_at DESC LIMIT 1`. Cheap.
- **Events**: facts. Query "what happened" is `SELECT * FROM events WHERE workflow_id = ? AND timestamp > ?`. Used for diff printing in `workflow watch`.

______________________________________________________________________

## Python API

```python
# mahavishnu/core/workflow_progress.py

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


DharaClient = httpx.AsyncClient(
    base_url=os.environ.get("MAHAVISHNU_DHARA_URL", "http://localhost:8683"),
    timeout=httpx.Timeout(5.0),
)


async def write_progress_snapshot(workflow_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
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

______________________________________________________________________

## CLI Commands

```python
# mahavishnu/cli/workflow_cli.py

import asyncio
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

______________________________________________________________________

## Worker Integration

Workers emit progress snapshots alongside Spec #1 reports:

```python
# In worker loop, after Spec #1's publish_iteration_report:
async def on_iteration_complete(report: dict, source: str, correlation_id: str) -> None:
    """Emit progress snapshot + workflow event (this spec)."""
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
```

______________________________________________________________________

## MCP Tools

```python
@mcp_tool
async def get_workflow_status_mcp(workflow_id: str) -> dict[str, Any]:
    """Return the latest progress snapshot for a workflow."""

@mcp_tool
async def list_workflows_mcp(status: str = "running") -> list[dict[str, Any]]:
    """Return latest snapshot per workflow matching status."""

@mcp_tool
async def record_workflow_event_mcp(
    workflow_id: str,
    event_type: str,
    *,
    iteration_index: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a workflow event."""
```

______________________________________________________________________

## Adoption & Migration

| Version | Adoption |
|---|---|
| **v1.0** | Dhara tables created. Workers emit snapshots at iteration completion (alongside Spec #1 reports). CLI shipped. `mahavishnu workflow status`, `list`, `watch` work. |
| **v1.1** | Per-tenant access control on workflow queries (Spec #9 integration). Snapshot cadence configurable per workflow type. |
| **v2.0** | Web dashboard for fleet view; webhook subscriptions for events. |

______________________________________________________________________

## Storage & Retrieval

**Dhara tables** — append-only. Snapshots are periodic state; events are facts.

**CLI** for query. `mahavishnu workflow watch <id>` polls (no server streaming).

**MCP tools** for query and write.

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Dhara HTTP timeout | `httpx.TimeoutException` | `get_workflow_status` returns None; CLI prints "no data." |
| Worker fails to write snapshot | Exception in `write_progress_snapshot` | Logged; iteration report still persists (Spec #1 succeeds). Snapshot is observational, not blocking. |
| Concurrent snapshot writes | Idempotent on snapshot_id (UUID) | Duplicate inserts rejected by primary key. |
| Workflow has no snapshots yet | Query returns None | CLI prints "no data"; operator waits or queries history (Spec #1). |

______________________________________________________________________

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | Snapshot write produces correct payload. Event write produces correct payload. |
| **L1 (file isolation)** | Real filesystem + mocked Dhara: full write/read round-trip. |
| **L2 (service isolation)** | Mocked Dhara: `get_workflow_status` returns latest snapshot. `list_workflow_events` filters by `since`. |
| **L3 (sandbox)** | Real Dhara: write snapshots + events, query latest, query events, list running. |
| **L4 (integration)** | End-to-end: worker emits snapshot + report; operator queries `mahavishnu workflow status`; CLI prints formatted output. |

**Coverage target:** `tests/unit/test_workflow_progress.py` ≥ 95% line coverage.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| Python API | `mahavishnu/core/workflow_progress.py` |
| Dhara migrations | `mahavishnu/core/dhara_migrations/workflow_progress.sql` |
| CLI | `mahavishnu/cli/workflow_cli.py` |
| MCP tools | `mahavishnu/mcp/tools/workflow_progress_tools.py` |
| Worker integration | (modify Spec #1 publisher) |
| L0/L1 tests | `tests/unit/test_workflow_progress.py` |
| L3 tests | `tests/integration/test_workflow_progress_dhara.py` |
| L4 tests | `tests/integration/test_workflow_progress_cli.py` |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Queryable progress (Option A) | Stateless; works on serverless; no connection management | SSE (Option B) — fragile on Cloud Run; reconnect logic; event buffering |
| Snapshots + events (two tables) | Snapshots are periodic state (cheap to query); events are facts (immutable log) | Single events table only — query "current state" requires MAX(timestamp) aggregation; wasteful |
| Workers emit snapshots alongside Spec #1 reports | Same publish path; minimal overhead | Separate worker emit code — duplication, drift risk |
| `mahavishnu workflow watch` polls on the client side | No server state; reconnects automatically; works across instance replacements | Server-side push — fragile on Cloud Run |
| Polling cadence default 5s (configurable) | Operator controls; can be tighter for fast workflows, looser for slow ones | Fixed cadence — wastes tokens for slow workflows, lags for fast ones |
| Substrate reuse with Spec #8 | Same Dhara pattern; same query API shape; same HTTP client | New custom substrate — duplication |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Snapshot cadence: emit on every iteration completion (current default), or also emit mid-iteration (e.g., every 60s while iterating)? v1.0 emits on iteration completion only.
- **OQ2.** Snapshot retention: how long to keep old snapshots. v1.0 never expires; v1.1 may add retention.
- **OQ3.** Per-tenant access: should `get_workflow_status` check tenant header? v1.0 no auth (Cloud Run IAM only); v1.1 may add.
- **OQ4.** Webhook subscriptions for events: v2.0 candidate. v1.0 poll-only.
- **OQ5.** Mid-iteration progress (e.g., "Claude is generating tool call X"): out of scope. v1.0 iteration-level only.

______________________________________________________________________

## Success Criteria

- **SC1.** Dhara tables (`workflow_progress_snapshots`, `workflow_events`) created and migration-applied.
- **SC2.** Workers emit snapshots at iteration completion (alongside Spec #1 reports) without extra round-trip.
- **SC3.** `mahavishnu workflow status <id>` returns latest snapshot.
- **SC4.** `mahavishnu workflow list --status running` returns fleet view.
- **SC5.** `mahavishnu workflow watch <id>` polls client-side; prints diffs on new events.
- **SC6.** MCP tools (`get_workflow_status_mcp`, `list_workflows_mcp`, `record_workflow_event_mcp`) shipped.
- **SC7.** L0–L4 tests green; ≥ 95% line coverage on new modules.
