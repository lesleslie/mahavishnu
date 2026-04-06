#!/usr/bin/env python3
"""CI check: validate all builtin event schemas and sample envelopes.

Returns exit code 0 on success, 1 on failure.
Designed to be run as a pre-commit hook or CI step.

Usage:
    python scripts/check-event-schemas.py
"""

from __future__ import annotations

import sys

from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.schema_registry import EventSchemaRegistry


def build_sample_envelopes() -> list[EventEnvelope]:
    """Build well-formed sample envelopes for every builtin schema."""
    return [
        EventEnvelope(
            event_type="code.graph.indexed",
            version="1.0.0",
            source="ci-check",
            payload={
                "repo_path": "/tmp/repo",
                "nodes_count": 42,
                "commit_hash": "abc123",
            },
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


def main() -> int:
    """Run all schema validation checks.

    Returns:
        0 if all checks pass, 1 otherwise.
    """
    registry = EventSchemaRegistry()
    schemas = registry.list_schemas()
    errors: list[str] = []

    # --- Check 1: all builtin schemas are well-formed (Pydantic already
    # validated them during construction, but verify they loaded) ---
    if not schemas:
        errors.append("No schemas registered — builtin loading may have failed")

    # --- Check 2: sample envelopes pass validation ---
    envelopes = build_sample_envelopes()
    event_types_covered = {e.event_type for e in envelopes}

    for envelope in envelopes:
        issues = registry.validate(envelope)
        if issues:
            for issue in issues:
                errors.append(f"{envelope.event_type} v{envelope.version}: {issue}")

    # --- Check 3: every registered schema has at least one sample envelope ---
    for schema in schemas:
        if schema.event_type not in event_types_covered:
            errors.append(f"No sample envelope for registered schema: {schema.event_type}")

    # --- Report ---
    if errors:
        print("❌ Event schema validation FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(f"\n{len(errors)} issue(s) found.", file=sys.stderr)
        return 1

    print(f"✅ All {len(schemas)} schemas and {len(envelopes)} envelopes passed validation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
