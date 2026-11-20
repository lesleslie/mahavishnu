---
status: active
role: canonical
kind: decision
date: 2026-11-14
last_reviewed: 2026-11-14
superseded_by:
topic: observability
---

# Hooks must pin structlog to stderr

**Date:** 2026-11-14

## Context

Claude Code treats a hook's stdout as a passthrough channel: JSON on stdout
is the hook's *response*, and anything else is injected into the user's
prompt. The jot hooks were writing a structlog line to stdout, which broke
the contract two ways:

- `jot-session-start` and `jot-post-tool-use` emit a JSON envelope on
  stdout. The log line took line 1, the envelope landed on line 2, and
  `json.loads` failed with `Extra data: line 2 column 1`.
- `jot-capture` is fire-and-forget and must stay silent. Its stdout was
  not empty at all.

The line came from `oneiric.adapters.queue.redis_streams`, whose
`queue-enqueue` event is emitted on every publish.

The cause is a default, not a bug in any one file. structlog's default
configuration writes to stdout through `PrintLoggerFactory`. Nothing in the
ecosystem sets a sink explicitly:

- `oneiric.core.logging.get_logger` is a thin `structlog.get_logger`
  wrapper -- it configures nothing.
- mahavishnu's `bootstrap.configure_logging` deliberately preserves "the
  console (non-JSON) renderer and the stdout sink", because operators read
  those lines in `~/.local/state/mcp/logs/mahavishnu.log`.

That is right for the MCP server and wrong for a hook. The server's stdout
is a log; the hook's stdout is a protocol channel.

## Decision rule

A hook pins the log sink to stderr before anything else can log.

`mahavishnu/hooks/logging_to_stderr.py` provides `pin_logging_to_stderr()`,
which calls `structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))`.
The factory is set explicitly rather than left to structlog's defaults, so
the destination does not depend on the structlog version.

Re-configuring later does not undo it: `bootstrap.configure_logging` passes
only `wrapper_class` and `cache_logger_on_first_use`, which leaves the
existing factory in place.

## Consequences

- The jot hooks emit their JSON envelope (or nothing) on stdout, and
  nothing else.
- The server keeps its stdout sink. No operator-visible log line moves.
- Any new hook must call `pin_logging_to_stderr()` before it imports
  anything that logs. The helper lives in `mahavishnu/hooks/`, so it is
  importable from a hook wrapper.

## Related

The same "default, not bug" shape shows up in the MCP server's
`/health` aggregation and in the `create_pool` failures -- both are
reported against a running gateway rather than a missing implementation.
