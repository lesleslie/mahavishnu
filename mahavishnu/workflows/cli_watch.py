"""CLI watch command for workflow progress snapshots — Spec #10.

Exposes a Typer sub-app that registers a ``watch`` subcommand. The watch
subcommand subscribes to a workflow's progress snapshots by polling the
in-process recorder; it stubs out cleanly when the substrate HTTP CRUD
call is unavailable (current Workstream C state:
``http_blocked (/workflows/<id>/progress-snapshots)``).

Architectural property (per spec):
- Client-side polling; no server-side streaming.
- The substrate persister is observational, not blocking — failure to
  reach Dhara does not stop the operator's local poll.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import typer

from mahavishnu.workflows.progress import (
    list_progress_snapshots,
    record_progress_snapshot,
)

logger = logging.getLogger(__name__)


watch_app = typer.Typer(help="Observe live workflow progress (Spec #10).")


@watch_app.command("watch")
def watch_cmd(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID to observe")],
    poll: Annotated[
        int,
        typer.Option(help="Poll interval in seconds for client-side polling"),
    ] = 5,
    once: Annotated[
        bool,
        typer.Option(help="Print the current snapshots once, then exit"),
    ] = False,
) -> None:
    """Subscribe to ``workflow_id`` progress snapshots.

    Client-side polling against the in-process recorder. Prints each new
    snapshot as it appears. Ctrl+C cleanly stops the loop.
    """
    asyncio.run(_watch(workflow_id=workflow_id, poll=poll, once=once))


@watch_app.command("emit")
def emit_cmd(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID")],
    step: Annotated[str, typer.Option(help="Step label")] = "manual",
    percent: Annotated[int, typer.Option(help="Percent 0-100")] = 0,
    message: Annotated[str, typer.Option(help="Status message")] = "",
) -> None:
    """Record a single progress snapshot for ``workflow_id``.

    Used by callers (workers, tests, scripts) that want to push a snapshot
    without going through the full substrate flow. Stub substrate persists
    no-op when the HTTP CRUD endpoint is blocked.
    """
    snap = asyncio.run(
        record_progress_snapshot(
            workflow_id=workflow_id,
            step=step,
            percent=percent,
            message=message,
        )
    )
    typer.echo(f"recorded snapshot: {snap.to_payload()}")


async def _watch(*, workflow_id: str, poll: int, once: bool) -> None:
    """Async body of the watch loop.

    Implementation note: this is a *stub* that the Workstream C substrate
    team will replace with a real subscription once the Dhara HTTP CRUD
    endpoint is unblocked. Until then, we poll the in-process recorder
    (which the same Python process owns) and print any new snapshots
    since the last seen timestamp.
    """
    seen_ts: set[str] = set()
    if once:
        snapshots = await list_progress_snapshots(workflow_id)
        for snap in snapshots:
            typer.echo(_format(snap))
        return

    typer.echo(f"watching {workflow_id!r} (poll={poll}s, Ctrl+C to stop)")
    try:
        while True:
            snapshots = await list_progress_snapshots(workflow_id)
            for snap in snapshots:
                key = snap.ts.isoformat()
                if key in seen_ts:
                    continue
                seen_ts.add(key)
                typer.echo(_format(snap))
            await asyncio.sleep(poll)
    except KeyboardInterrupt:
        typer.echo("stopped watching.")


def _format(snap) -> str:
    """Format a snapshot for CLI output."""
    return (
        f"[{snap.ts.isoformat()}] {snap.workflow_id} "
        f"{snap.step} {snap.percent:>3}% — {snap.message}"
    )


__all__ = ["watch_app", "watch_cmd", "emit_cmd"]
