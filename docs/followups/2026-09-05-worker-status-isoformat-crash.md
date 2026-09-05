---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: worker-status-isoformat-crash
---

# `worker_status` isoformat crash on malformed `last_seen_at`

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/mcp/tools/worker_contract_tools.py:217-230`
(`last_activity.isoformat()` call moved into the same `try/except (AttributeError, TypeError, ValueError)`
block that guards the `record.last_seen_at - record.created_at` subtraction; both fallback to
zero / `None`); regression test at
`tests/unit/mcp/tools/test_worker_contract_tools.py::test_workflow_status_handles_malformed_non_datetime`
(feeds `last_seen_at="not-a-datetime"`, asserts both `uptime_seconds == 0` and
`last_activity_iso is None`).

## Trigger

Coverage fanout 2026-09-05 (Brief 1: `worker_contract_tools.py`) — subagent discovered
the `try/except AttributeError, TypeError, ValueError` block at lines 220-224 of the
old code only guarded the timestamp subtraction, **not** the subsequent
`last_activity.isoformat()` call on line 227. If a corrupted record has a non-None
non-datetime `last_seen_at`, the isoformat call raises `AttributeError` (or similar)
and bubbles up uncaught, crashing the MCP `worker_status` call.

## Action

1. File `Open` followup note (this file).
2. Collapse the uptime-computation and the isoformat call into one `try` block —
   same exception family, same best-effort semantics.
3. Add regression test that mocks a record with `last_seen_at="not-a-datetime"`
   and asserts the call returns gracefully (no raise).
4. Mark Resolved citing fix location + regression test name.
