---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: terminal-close-all-empty-id-roundtrip
---

# `terminal_close_all` round-trips empty-string IDs to `manager.close_all`

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:168-180`
(filter added: `session_ids = [sid for sid in ... if sid]` skips empty/missing IDs
instead of coercing them to `""` and round-tripping to the manager); regression tests
at `tests/unit/mcp/tools/test_terminal_tools.py::TestTerminalCloseAll` —
`test_close_all_handles_missing_ids` (updated to assert `closed_count == 1` and
`close_all.assert_awaited_once_with(["sess-1"])`) and the new
`test_close_all_skips_all_empty_ids` (asserts `closed_count == 0` and
`close_all.assert_not_awaited()`).

## Trigger

Coverage fanout 2026-09-05 (Brief 2: `terminal_tools.py`) — subagent flagged that
`terminal_close_all` line 172 (`[s.get("id", s.get("terminal_id", "")) for s in sessions]`)
coerced missing IDs to `""` and passed the empty string to `manager.close_all`,
forcing the manager to handle an invalid session ID on every call.

## Action

1. File `Open` followup note (this file).
2. Filter empty IDs out of the list before passing to `manager.close_all`.
3. Update `test_close_all_handles_missing_ids` to lock the new (correct) behavior.
4. Add `test_close_all_skips_all_empty_ids` for the all-missing-IDs edge case.
5. Mark Resolved citing fix location + regression test names.
