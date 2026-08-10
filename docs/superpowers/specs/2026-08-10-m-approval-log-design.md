---
status: draft
date: 2026-08-10
topic: m-approval-log
entity: approval_log
owner_repo: mahavishnu
subscribes_to: dhara.schema.approval_log
---

# M-APPROVAL-LOG Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `approval_log` typed schema (from `dhara.schema`) into Mahavishnu's approval flow. Stop deleting approval history on resolve; persist as structured `approval_log` records. Both producer (validate-on-write at decision time) and consumer (read-back-and-validate via `list_approval_history`) sides wired.

**Architecture:** Producer module sits in `mahavishnu/core/approval/decision_writer.py`; imports `ApprovalLog` from `dhara.schema`, validates via `validate("approval_log", payload)`, persists to Dhara storage at `approval-history/{approval_id}/`. Consumer module extends `mahavishnu/cli/approval_cli.py::list_approval_history(approval_id, since, status)` (or equivalent MCP tool) to read back via `from_dict` and return validated structs.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, no new third-party deps.

## Integration Contract

- **Triggered from:** `mahavishnu.core.approval.record_decision(approval_id, decision, rationale, decided_by)` (existing function, modified to call decision_writer)
- **Returns to / updates:** `approval-history/{approval_id}/` Dhara key namespace (replaces the previous "delete on resolve" behavior with persistent log)
- **Demonstrable by:** pytest `tests/unit/approval/test_decision_writer.py::test_record_decision_emits_validated_struct` + smoke `pytest tests/integration/approval/test_list_history.py::test_list_returns_validated_records`
- **Rollback signal:** feature flag `APPROVAL_LOG_V1_ENABLED=False`; `record_decision` falls back to old delete-on-resolve behavior
- **Observability added:** counter `approval_log_recorded_total{decision}` (approved/denied/requested) + counter `approval_log_invalid_total{reason}` (validation_error, schema_drift)

## Tasks (Sketch)

1. Import `ApprovalLog` from `dhara.schema` + producer module `decision_writer.py` + tests (RED-first)
2. Extend consumer-side `list_approval_history` to return validated structs + tests (RED-first)
3. Wire producer into `record_decision`; remove old delete-on-resolve branch
4. Round-trip integration test
5. Crackerjack gate + completion report

## Open questions

None.