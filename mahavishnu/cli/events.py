"""Event schema CLI commands for Mahavishnu.

Provides commands for validating and exporting event schemas:
- validate: Validate all registered schemas against sample events
- export: Export all registered schemas as JSON (for CI artifacts)
"""

from __future__ import annotations

import json

import typer

from ..core.events.envelope import EventEnvelope
from ..core.events.schema_registry import EventSchemaRegistry

app = typer.Typer(help="Event schema validation and export commands")


def _build_sample_envelopes() -> list[EventEnvelope]:
    """Build sample event envelopes for each registered schema.

    Returns envelopes that should pass validation, covering every
    builtin event_type with the correct required fields and types.
    """
    return [
        EventEnvelope(
            event_type="code.graph.indexed",
            version="1.0.0",
            source="ci-check",
            payload={"repo_path": "/tmp/repo", "nodes_count": 42, "commit_hash": "abc123"},
        ),
        EventEnvelope(
            event_type="worker.started",
            version="1.0.0",
            source="ci-check",
            payload={"worker_id": "w-001", "worker_type": "terminal-qwen"},
        ),
        EventEnvelope(
            event_type="worker.stopped",
            version="1.0.0",
            source="ci-check",
            payload={"worker_id": "w-001", "exit_code": 0},
        ),
        EventEnvelope(
            event_type="worker.status_changed",
            version="1.0.0",
            source="ci-check",
            payload={"worker_id": "w-001", "status": "running"},
        ),
        EventEnvelope(
            event_type="worker.error",
            version="1.0.0",
            source="ci-check",
            payload={"worker_id": "w-001", "error": "something went wrong"},
        ),
        EventEnvelope(
            event_type="backup.started",
            version="1.0.0",
            source="ci-check",
            payload={"backup_type": "full"},
        ),
        EventEnvelope(
            event_type="backup.completed",
            version="1.0.0",
            source="ci-check",
            payload={"backup_id": "b-001"},
        ),
        EventEnvelope(
            event_type="backup.failed",
            version="1.0.0",
            source="ci-check",
            payload={"error": "disk full"},
        ),
        EventEnvelope(
            event_type="backup.restored",
            version="1.0.0",
            source="ci-check",
            payload={"backup_id": "b-001"},
        ),
        EventEnvelope(
            event_type="pool.spawned",
            version="1.0.0",
            source="ci-check",
            payload={"pool_id": "p-001", "pool_type": "mahavishnu"},
        ),
        EventEnvelope(
            event_type="pool.closed",
            version="1.0.0",
            source="ci-check",
            payload={"pool_id": "p-001"},
        ),
        EventEnvelope(
            event_type="pool.scaled",
            version="1.0.0",
            source="ci-check",
            payload={"pool_id": "p-001", "target_workers": 5},
        ),
        EventEnvelope(
            event_type="workflow.started",
            version="1.0.0",
            source="ci-check",
            payload={"workflow_id": "wf-001"},
        ),
        EventEnvelope(
            event_type="task.created",
            version="1.0.0",
            source="ci-check",
            payload={"task_id": "t-001"},
        ),
    ]


@app.command("validate")
def validate_schemas() -> None:
    """Validate all registered schemas against sample events.

    Checks that every builtin schema is well-formed and that a
    corresponding sample envelope passes validation. Exits with
    code 1 if any issues are found.
    """
    registry = EventSchemaRegistry()
    schemas = registry.list_schemas()

    typer.echo(f"📋 Checking {len(schemas)} registered schemas…\n")

    errors_found = 0

    for schema in schemas:
        key = f"{schema.event_type}:{schema.version}"
        typer.echo(f"  Schema: {key}")

        # Build a matching sample envelope
        sample = EventEnvelope(
            event_type=schema.event_type,
            version=schema.version,
            source="schema-validation",
            payload=_sample_payload_for(schema),
        )

        issues = registry.validate(sample)
        if issues:
            errors_found += 1
            for issue in issues:
                typer.echo(f"    ❌ {issue}", err=True)
        else:
            typer.echo("    ✅ valid")

    # Also validate the full set of pre-built envelopes
    typer.echo("\n📋 Validating sample envelopes…\n")
    envelopes = _build_sample_envelopes()

    for envelope in envelopes:
        issues = registry.validate(envelope)
        label = f"{envelope.event_type} v{envelope.version}"
        if issues:
            errors_found += 1
            for issue in issues:
                typer.echo(f"  ❌ {label}: {issue}", err=True)
        else:
            typer.echo(f"  ✅ {label}")

    typer.echo("")
    if errors_found:
        typer.echo(f"❌ {errors_found} issue(s) found", err=True)
        raise typer.Exit(code=1)
    else:
        typer.echo("✅ All schemas and envelopes passed validation")


@app.command("export")
def export_schemas() -> None:
    """Export all registered schemas as JSON to stdout.

    Output format: [{"event_type": "...", "version": "...",
    "required_fields": [...], "field_types": {...}, "description": "..."}]
    """
    registry = EventSchemaRegistry()
    schemas = registry.list_schemas()

    export_data = [
        {
            "event_type": s.event_type,
            "version": s.version,
            "required_fields": s.required_fields,
            "field_types": s.field_types,
            "description": s.description,
        }
        for s in schemas
    ]

    typer.echo(json.dumps(export_data, indent=2, sort_keys=True))


def _sample_payload_for(schema) -> dict:
    """Generate a minimal valid payload for a given EventSchema."""
    payload: dict = {}
    # Provide a string value for every required field
    for field_name in schema.required_fields:
        expected = schema.field_types.get(field_name, "str")
        if expected == "int":
            payload[field_name] = 0
        elif expected == "float":
            payload[field_name] = 0.0
        elif expected == "bool":
            payload[field_name] = True
        else:
            payload[field_name] = "sample"
    return payload


def add_events_commands(main_app: typer.Typer) -> None:
    """Add event schema commands to the main CLI app."""
    main_app.add_typer(app, name="events", help="Event schema validation and export")
