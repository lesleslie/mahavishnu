---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: terminal-send-regex-mismatch
---

# `SessionID` regex rejects legitimate adapter IDs (e.g. macOS Terminal dots)

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:20-26`
(`SessionID` regex widened from `r"^[a-zA-Z0-9_-]+$"` to `r"^[a-zA-Z0-9._-]+$"` to accept
`.` in IDs); regression test at
`tests/unit/mcp/tools/test_terminal_tools.py::TestTerminalSend::test_session_id_with_dots_accepted`
(parametrized over `"session.with.dot"`, `"sess.1.2.3"`, `"a.b.c.d.e"` — all now pass
through to `manager.send_command`).

## Trigger

Coverage fanout 2026-09-05 (Brief 2: `terminal_tools.py`) — subagent flagged the
`SessionID = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+$")]`
constraint as potentially over-restrictive. macOS Terminal sessions backed by
`com.apple.Terminal` emit IDs containing dots; the previous regex rejected
those IDs at the MCP boundary even though the underlying adapter accepted them.

(Note: the subagent's original framing described a "regex vs Annotated
mismatch" — but `terminal_send` has only one validator, the Annotated constraint.
There was no internal duplicate regex check. The actual fix is to widen the
single Annotated constraint, not reconcile two validators.)

## Action

1. File `Open` followup note (this file).
2. Widen the regex pattern to include `.`.
3. Update `test_invalid_session_id_rejected` parametrize list to remove the
   `session.with.dot` case (now valid).
4. Add positive `test_session_id_with_dots_accepted` parametrized test.
5. Mark Resolved citing fix location + regression test name.
