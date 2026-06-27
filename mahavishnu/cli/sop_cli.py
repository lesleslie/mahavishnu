"""SOP evolution CLI (Spec #7).

Three subcommands:

- ``mahavishnu sop list --project PROJECT_ID`` — list SOPs and pending
  suggestions for a project.
- ``mahavishnu sop show --project PROJECT_ID --name SOP_NAME`` — show a
  single SOP's body and metadata.
- ``mahavishnu sop propose --project PROJECT_ID`` — run the
  EvolutionTrigger over the failure-mode catalog and persist resulting
  suggestions.

Substrate status (Phase 3): sql_blocked + http_blocked. The CLI uses the
``InMemorySOPPersister`` for the v0 build so the surface is exercisable
end-to-end. When Workstream C lands, the persister is swapped in via
configuration; the CLI surface does not change.
"""

from __future__ import annotations

import json

import typer

sop_app = typer.Typer(help="Project-scoped SOP evolution (Spec #7)")


def _persister():
    """Return the configured ``SOPPersister`` for this CLI session.

    Phase 3: returns ``InMemorySOPPersister``. Workstream C will swap in
    the Dhara-backed implementation behind a config flag.
    """
    # Local import keeps the CLI cheap when sop subcommands are not used.
    from mahavishnu.sop.persisters import InMemorySOPPersister

    return InMemorySOPPersister()


@sop_app.command("list")
def sop_list(
    project: str = typer.Option(..., "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit structured JSON output"
    ),
) -> None:
    """List SOPs and pending suggestions for a project."""
    persister = _persister()
    sops = persister.list_for_project(project)
    suggestions = persister.list_suggestions(project)
    failure_modes = persister.list_failure_modes(project)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "project_id": project,
                    "sops": [
                        {
                            "name": s.name,
                            "version": s.version,
                            "last_failure_id": s.last_failure_id,
                            "last_evolved_at": (
                                s.last_evolved_at.isoformat()
                                if s.last_evolved_at
                                else None
                            ),
                        }
                        for s in sops
                    ],
                    "pending_suggestions": [
                        {
                            "suggestion_id": sg.suggestion_id,
                            "sop_name": sg.sop_name,
                            "failure_mode_id": sg.failure_mode_id,
                            "status": sg.status,
                        }
                        for sg in suggestions
                        if sg.status == "pending"
                    ],
                    "failure_modes": [
                        {
                            "failure_mode_id": fm.failure_mode_id,
                            "fingerprint": fm.fingerprint,
                            "sop_name": fm.sop_name,
                            "occurrences": fm.occurrences,
                        }
                        for fm in failure_modes
                    ],
                },
                indent=2,
            )
        )
        return

    typer.echo(f"SOPs for project '{project}':")
    if not sops:
        typer.echo("  (none)")
    for s in sops:
        typer.echo(f"  - {s.name} (version={s.version})")

    pending = [sg for sg in suggestions if sg.status == "pending"]
    typer.echo(f"\nPending suggestions: {len(pending)}")
    for sg in pending:
        typer.echo(f"  - {sg.suggestion_id} → {sg.sop_name} (fm={sg.failure_mode_id})")

    typer.echo(f"\nFailure-mode catalog: {len(failure_modes)} entries")
    for fm in failure_modes:
        typer.echo(
            f"  - {fm.fingerprint} ({fm.sop_name}): {fm.occurrences} occurrences"
        )


@sop_app.command("show")
def sop_show(
    project: str = typer.Option(..., "--project", "-p", help="Project ID"),
    name: str = typer.Option(..., "--name", "-n", help="SOP name"),
) -> None:
    """Show a single SOP's body and metadata."""
    persister = _persister()
    sop = persister.get(project, name)
    if sop is None:
        typer.echo(f"ERROR: SOP '{name}' not found for project '{project}'")
        raise typer.Exit(code=1)

    typer.echo(f"SOP: {sop.name}")
    typer.echo(f"Project: {sop.project_id}")
    typer.echo(f"Version: {sop.version}")
    if sop.last_failure_id:
        typer.echo(f"Last failure ID: {sop.last_failure_id}")
    if sop.last_evolved_at:
        typer.echo(f"Last evolved at: {sop.last_evolved_at.isoformat()}")
    typer.echo("")
    typer.echo(sop.body)


@sop_app.command("propose")
def sop_propose(
    project: str = typer.Option(..., "--project", "-p", help="Project ID"),
    threshold: int = typer.Option(
        3, "--threshold", "-t", help="Occurrence threshold to trigger a proposal"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit structured JSON output"
    ),
) -> None:
    """Run the EvolutionTrigger over the project's failure-mode catalog."""
    from mahavishnu.sop.evolution import EvolutionTrigger

    persister = _persister()
    entries = persister.list_failure_modes(project)
    trigger = EvolutionTrigger(threshold=threshold)
    decisions = trigger.evaluate_batch(entries)

    proposed = []
    for decision in decisions:
        if decision.propose and decision.suggestion is not None:
            persister.save_suggestion(decision.suggestion)
            proposed.append(decision.suggestion)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "project_id": project,
                    "threshold": threshold,
                    "catalog_size": len(entries),
                    "proposed_count": len(proposed),
                    "proposed": [
                        {
                            "suggestion_id": sg.suggestion_id,
                            "sop_name": sg.sop_name,
                            "failure_mode_id": sg.failure_mode_id,
                            "rationale": sg.rationale,
                        }
                        for sg in proposed
                    ],
                },
                indent=2,
            )
        )
        return

    typer.echo(
        f"Evaluated {len(entries)} failure-mode entries for project '{project}' "
        f"(threshold={threshold})."
    )
    if not proposed:
        typer.echo("No new suggestions — no failure mode crossed the threshold.")
        return

    typer.echo(f"\nProposed {len(proposed)} new suggestion(s):")
    for sg in proposed:
        typer.echo(f"  - {sg.suggestion_id} → {sg.sop_name} (fm={sg.failure_mode_id})")
        typer.echo(f"    rationale: {sg.rationale}")


def add_sop_commands(app: typer.Typer) -> None:
    """Register the SOP sub-app on the root Typer app."""
    app.add_typer(sop_app, name="sop")