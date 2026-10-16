"""Pool reap CLI — clear durable-worker audit rows and stale sockets.

Worker sockets in ``~/.mahavishnu/tmux/`` and the audit JSON rows under
``~/.mahavishnu/worker-sessions/`` persist after ``close_session()`` by
design (reaped-state retains the audit trail). Operators running the
production stack for months saw those sockets pile up; the 2026-10-09 demo
surfaced 7 leftover sockets from August with no command to prune them.
This subcommand closes the gap without forcing a manual ``rm -rf``.

Default scope: only records in ``WorkerLifecycleState.REAPED``. Add
``--all`` to include still-active states (destructive — use after a
confirmed pool shutdown). ``--dry-run`` lists without deleting;
``--yes`` skips the confirmation prompt for scripted runs.

Wired into ``mahavishnu pool reap`` via ``add_reap_commands(pool_app)`` in
:meth:`mahavishnu._main_cli`.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger
import typer

if TYPE_CHECKING:
    from mahavishnu.workers.contract.store import WorkerRecordStore


logger = get_logger(__name__)


DEFAULT_WORKER_SESSIONS_DIR = pathlib.Path("~/.mahavishnu/worker-sessions").expanduser()


def _build_store() -> WorkerRecordStore:
    """Construct a :class:`WorkerRecordStore` against the canonical root.

    The root matches :func:`mahavishnu.terminal.adapters._resolve_record_store`
    and :func:`mahavishnu.mcp.bootstrap._build_worker_record_store` so the
    reap CLI deletes the same rows every other entry point reads.
    """
    from mahavishnu.workers.contract.store import WorkerRecordStore

    return WorkerRecordStore(DEFAULT_WORKER_SESSIONS_DIR)


def _select_targets(
    store: WorkerRecordStore,
    *,
    include_all: bool,
) -> list[tuple[str, str, str | None, str | None]]:
    """Return ``(worker_id, state, session_name, socket_path)`` rows.

    Default scope: records in ``WorkerLifecycleState.REAPED``. Setting
    ``include_all=True`` keeps every record regardless of state — used by
    ``--all`` to express "nuclear" cleanup. The state-string is a raw
    ``StrEnum.value`` so the table column reads as ``"reaped"`` (not
    ``WorkerLifecycleState.REAPED``).
    """
    rows: list[tuple[str, str, str | None, str | None]] = []
    from mahavishnu.workers.contract.state import WorkerLifecycleState

    for record in store.list_all():
        if not include_all and record.state != WorkerLifecycleState.REAPED:
            continue
        state_value = record.state.value if hasattr(record.state, "value") else str(record.state)
        session_name = record.tmux.session if record.tmux else None
        socket_path = record.tmux.socket if record.tmux else None
        rows.append(
            (
                record.worker_id,
                state_value,
                session_name,
                socket_path,
            ),
        )
    return rows


def _render_table(rows: list[tuple[str, str, str | None, str | None]]) -> str:
    """Render a two-column-style aligned table for ``typer.echo``.

    Treated as a single block so terminal width does not blow up when one
    row carries a long session name or an absolute socket path.
    """
    headers = ("WORKER_ID", "STATE", "SESSION_NAME", "SOCKET_PATH")
    widths = [
        max(
            len(headers[i]),
            *(len(row[i] or "<none>") for row in rows),
        )
        for i in range(4)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)

    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    for row in rows:
        lines.append(
            fmt.format(
                row[0],
                row[1],
                row[2] or "<none>",
                row[3] or "<none>",
            ),
        )
    return "\n".join(lines)


def add_reap_commands(pool_app: typer.Typer) -> None:
    """Register ``mahavishnu pool reap`` on the pool sub-app.

    Delayed attach keeps the module import graph acyclic: ``_main_cli``
    imports this module and calls this function after ``pool_app`` is
    constructed, so the reap sub-app never touches the root at module
    load time.
    """
    reap_app = typer.Typer(
        help=(
            "Clear durable-worker audit rows (and stale tmux sockets). "
            "Default scope is REAPED-state records only."
        ),
        invoke_without_command=True,
    )

    @reap_app.callback()
    def _reap_root(
        ctx: typer.Context,
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="List reaped workers without deleting any records.",
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Skip confirmation prompt (intended for scripts).",
        ),
        all_flag: bool = typer.Option(
            False,
            "--all",
            help="Include records in states other than REAPED (destructive).",
        ),
    ) -> None:
        """Reap durable-worker audit rows.

        Lists eligible records, prompts for confirmation (skippable with
        ``--yes``), and deletes each row from the underlying
        :class:`WorkerRecordStore`. Socket files in ``~/.mahavishnu/tmux/``
        are left untouched so an audit-style rollback path remains
        available even after cleanup.
        """
        if ctx.invoked_subcommand is not None:
            return

        store = _build_store()
        rows = _select_targets(store, include_all=all_flag)

        scope_label = "ALL" if all_flag else "REAPED"
        typer.echo(f"Reap target: {scope_label} state, {len(rows)} worker(s) eligible.")
        if not rows:
            typer.echo("Nothing to do.")
            raise typer.Exit(code=0)

        typer.echo(_render_table(rows))

        if dry_run:
            typer.echo("\n--dry-run set: no records deleted.")
            raise typer.Exit(code=0)

        if not yes:
            prompt = f"\nDelete {len(rows)} worker record(s) above? [y/N]"
            confirmed = typer.confirm(prompt, default=False)
            if not confirmed:
                typer.echo("Aborted; no records deleted.")
                raise typer.Exit(code=0)

        deleted: list[str] = []
        for worker_id, *_ in rows:
            store.delete(worker_id)
            deleted.append(worker_id)

        typer.echo(f"\nDeleted {len(deleted)} worker record(s):")
        for worker_id in deleted:
            typer.echo(f"  - {worker_id}")

    pool_app.add_typer(reap_app, name="reap")
