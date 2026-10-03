---
status: draft
role: implementation
date: 2026-08-10
last_reviewed: 2026-08-10
superseded_by: null
blocks_on: []
topic: m-workflow-outcome
entity: workflow_outcome
owner_repo: mahavishnu
subscribes_to: dhara.schema.workflow_outcome
---

# M-WORKFLOW-OUTCOME Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `workflow_outcome` typed schema (from `dhara.schema`) into the Mahavishnu workflow completion path. Both producer (validate-on-write at completion) and consumer (read-back-and-validate via MCP query tool) sides wired.

**Architecture:** Producer module sits in `mahavishnu/core/workflow/outcome_writer.py`; imports `WorkflowOutcome` from `dhara.schema`, validates via `validate("workflow_outcome", payload)` from `SCHEMA_REGISTRY`, persists to Dhara storage at `workflow-results/{workflow_id}/`. Consumer module sits in `mahavishnu/mcp/tools/workflow_tools.py` as a new `workflow_get_outcome(workflow_id)` MCP tool; reads via `from_dict("workflow_outcome", payload)` and returns the validated struct.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, no new third-party deps.

## Integration Contract

- **Triggered from:** `mahavishnu.core.workflow.run()` completion callback (existing function, modified to call outcome_writer)
- **Returns to / updates:** `workflow-results/{workflow_id}/` Dhara key namespace
- **Demonstrable by:** pytest `tests/unit/workflow/test_workflow_outcome_wiring.py::test_round_trip` + smoke `pytest tests/integration/test_workflow_outcome_query.py::test_query_returns_validated_struct`
- **Rollback signal:** feature flag `WORKFLOW_OUTCOME_V1_ENABLED=False` (set in `mahavishnu/settings/local.yaml`); outcome_writer is a no-op when disabled
- **Observability added:** counter `workflow_outcome_recorded_total{status}` + counter `workflow_outcome_invalid_total{reason}` (succeeded/failed/cancelled × validation_error/schema_drift)

## Tasks (Sketch)

1. Import `WorkflowOutcome` from `dhara.schema` + producer module `outcome_writer.py` + tests (RED-first)
2. Consumer-side MCP tool `workflow_get_outcome` + tests (RED-first)
3. Wire producer into `mahavishnu.core.workflow.run()` completion callback
4. Round-trip integration test
5. Crackerjack gate + completion report

## Open questions

None.
