---
status: draft
date: 2026-08-10
topic: m-webhook-durable
entity: webhook_ingress
owner_repo: mahavishnu
subscribes_to: dhara.schema.webhook_ingress
---

# M-WEBHOOK-DURABLE Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `webhook_ingress` typed schema (from `dhara.schema`) into Mahavishnu's webhook receiver. Close the durable-ingress gap (P0-3/P0-4/P0-5 in `docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md`): webhook endpoints accept work but never enqueue; an MCP restart loses accepted requests. Both producer (validate-on-write on webhook arrival) and consumer (read-back-and-validate via replay MCP tool) sides wired.

**Architecture:** Producer module sits in `mahavishnu/webhooks/receiver.py`; imports `WebhookIngress` from `dhara.schema`, validates via `validate("webhook_ingress", payload)` from `SCHEMA_REGISTRY`, persists via `dhara.put` (which triggers D-AUDIT subscriber for `audit_record` emission per the Layer 0 substrate pattern). Consumer module sits in `mahavishnu/mcp_tools/webhook_tools.py` as a new `webhook_replay(webhook_id)` MCP tool; reads back via `from_dict` and returns validated struct.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, no new third-party deps.

## Integration Contract

- **Triggered from:** webhook HTTP POST handler in `mahavishnu/webhooks/receiver.py` (modified to call schema-validated persistence)
- **Returns to / updates:** `webhook-ingress/{webhook_id}/` Dhara key namespace (durable; survives MCP restart)
- **Demonstrable by:** pytest `tests/unit/webhooks/test_receiver.py::test_post_emits_validated_struct` + smoke `pytest tests/integration/test_webhook_replay.py::test_replay_returns_validated_records`
- **Rollback signal:** feature flag `WEBHOOK_DURABLE_V1_ENABLED=False`; receiver falls back to in-memory only (re-introducing the durability gap but unblocking rollback)
- **Observability added:** counter `webhook_ingress_recorded_total{source}` (per webhook source) + counter `webhook_ingress_invalid_total{reason}` (validation_error, schema_drift)

## Tasks (Sketch)

1. Import `WebhookIngress` from `dhara.schema` + producer module receiver + tests (RED-first)
2. Consumer-side MCP tool `webhook_replay` + tests (RED-first)
3. Wire producer into webhook HTTP handler; replace in-memory queue with `dhara.put`
4. Round-trip integration test (durable across process restart)
5. Crackerjack gate + completion report

## Open questions

None.