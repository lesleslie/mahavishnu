"""Settle CLI — sync wrappers for non-asyncio contexts.

Wires the two sync variants in :mod:`mahavishnu.settle.persistence` into
a Typer sub-app so they become reachable from the ``mahavishnu`` CLI:

  - ``settle status <run_ref>`` — load and print a settle run record
    (:func:`mahavishnu.settle.persistence.load_record_sync`)
  - ``settle start <run_ref> --worker <id> --task <sig>`` — persist a new
    PROPOSED record (:func:`mahavishnu.settle.persistence.persist_initial`)

Wires 2 of the 3 Group A orphans from
``docs/feature-tracking/2026-09-06-orphan-sweep.md``. The third —
``merge_three_way_sync`` — stays orphaned: its current signature takes
raw ``base/ours/theirs`` strings and the only honest CLI command would
require a higher-level wrapper that loads the record and iterates
bindings. That wrapper is deferred until adjacent settle work lands.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from ..settle.persistence import load_record_sync, persist_initial
from ..settle.state_machine import SettleRunRecord, SettleState


def add_settle_commands(app: typer.Typer) -> None:
    """Register the ``settle`` subcommand group on *app*."""
    settle_app = typer.Typer(help="Settle run introspection and operations")
    app.add_typer(settle_app, name="settle")

    @settle_app.command("status")
    def status(run_ref: str = typer.Argument(..., help="Settle run reference")) -> None:
        """Show status of a settle run."""
        record = load_record_sync(run_ref)
        if record is None:
            typer.echo(f"settle run not found: {run_ref}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"run_ref: {record.run_ref}")
        typer.echo(f"state: {record.state}")
        typer.echo(f"worker_id: {record.worker_id}")
        typer.echo(f"task_signature: {record.task_signature}")

    @settle_app.command("start")
    def start(
        run_ref: str = typer.Argument(..., help="Settle run reference"),
        worker_id: str = typer.Option(..., "--worker", "-w", help="Worker ID"),
        task_signature: str = typer.Option(
            ..., "--task", "-t", help="Task signature for the run"
        ),
    ) -> None:
        """Persist a newly-created (state=PROPOSED) record for *run_ref*.

        Bindings are intentionally empty at this stage — they are filled in
        by the worker before any filesystem side-effect, per the contract
        documented on :func:`mahavishnu.settle.persistence.persist_initial`.
        """
        now = datetime.now(UTC)
        record = SettleRunRecord(
            run_ref=run_ref,
            worker_id=worker_id,
            task_signature=task_signature,
            bindings=(),
            state=SettleState.PROPOSED,
            created_at=now,
            updated_at=now,
        )
        record = persist_initial(record)
        typer.echo(f"created: {record.run_ref} state={record.state}")
