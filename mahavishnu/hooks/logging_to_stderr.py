"""Route structlog output to stderr for Claude Code hook processes.

Claude Code treats a hook's stdout as a passthrough channel: JSON on
stdout is the hook's response, and anything else is injected into the
user's prompt. A log line on stdout therefore breaks the hook contract
two ways -- it corrupts the JSON envelope (the log takes line 1 and the
envelope lands on line 2, so ``json.loads`` reports "Extra data"), and
for a capture hook that must stay silent it is plain pollution.

structlog's *default* configuration writes to stdout through
``PrintLoggerFactory``. Nothing in the ecosystem sets a sink
explicitly: ``oneiric.core.logging.get_logger`` is a thin
``structlog.get_logger`` wrapper, and mahavishnu's
``bootstrap.configure_logging`` deliberately preserves "the console
(non-JSON) renderer and the stdout sink" because operators read those
lines in ``~/.local/state/mcp/logs/mahavishnu.log``. That is right for
the MCP server and wrong for a hook.

So a hook pins the sink to stderr before anything else logs. The
``logger_factory`` is set explicitly rather than left to structlog's
defaults, so the destination does not depend on the structlog version.
Re-configuring later does not undo it: ``bootstrap.configure_logging``
passes only ``wrapper_class`` and ``cache_logger_on_first_use``, which
leaves the existing factory in place.
"""

from __future__ import annotations

import sys


def pin_logging_to_stderr() -> None:
    """Point structlog's logger factory at stderr."""
    import structlog

    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
