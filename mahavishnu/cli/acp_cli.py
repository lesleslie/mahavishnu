"""CLI surface for the ACP server — ``mahavishnu acp serve``.

Per plan §Phase 2 Task 2. Registers a Typer sub-app on the main CLI
that exposes ``mahavishnu acp serve`` — the stdio JSON-RPC 2.0 dispatcher
described in :mod:`mahavishnu.acp.server`.

The :func:`serve_cmd` is intentionally thin: it acquires the bearer,
constructs the ``execute_fn`` (lazily using the Phase 1.5 factory
``build_execute_fn`` if available, otherwise a stub that echoes the
prompt back), and hands stdin/stdout to the dispatcher via the
module-level :func:`mahavishnu.acp.server.serve`.

Real execute_fn wiring is Phase 1.5 work; the stub here lets the
CLI be smoke-tested end-to-end before that lands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import typer

from mahavishnu.acp.server import serve
from mahavishnu.core.execute_fn_factory import build_execute_fn

logger = logging.getLogger("mahavishnu.acp.cli")

app = typer.Typer(help="ACP server (stdio JSON-RPC 2.0) commands.")


class _ACPSettings:
    """Minimal settings object passed to ``build_execute_fn``.

    The full ``ACPSettings`` is a follow-on; for now we pass a stub
    with just the fields the factory reads (``component_name`` and
    ``execute_fn_timeout_seconds``).
    """

    component_name: str = "acp"
    execute_fn_timeout_seconds: float = 600.0


def _build_default_execute_fn() -> Any:
    """Construct the ``execute_fn`` passed to the dispatcher.

    Phase 1.5 unified this with the A2A path: both protocols now
    import ``build_execute_fn`` from ``mahavishnu.core.execute_fn_factory``
    and call it with their protocol-specific settings. When the full
    ``MahavishnuApp.execute`` refactor lands, the factory wires the
    app; until then, the factory falls back to a stub ``WorkerResult``
    echo.
    """
    return build_execute_fn(_ACPSettings())


@app.command("serve")
def serve_cmd(
    bearer_token: str | None = typer.Option(
        None,
        "--bearer-token",
        envvar="MAHAVISHNU_ACP_BEARER_TOKEN",
        help=(
            "Explicit bearer token. If omitted, reads MAHAVISHNU_ACP_BEARER_TOKEN "
            "or MAHAVISHNU_ACP_BEARER_TOKEN_FILE from the environment."
        ),
    ),
    max_concurrent_sessions: int = typer.Option(
        16,
        "--max-concurrent-sessions",
        help="Maximum concurrent ACP sessions before -32004 rejection.",
    ),
    session_timeout_seconds: float = typer.Option(
        600.0,
        "--session-timeout",
        help="execute_fn timeout in seconds (asyncio.wait_for cap).",
    ),
) -> None:
    """Start the ACP server on stdio (JSON-RPC 2.0).

    Reads JSON-RPC requests from stdin, writes responses to stdout,
    logs structured events to stderr. The server refuses to start
    unless a bearer token is configured — see the auth module for the
    env-var and file conventions.
    """
    execute_fn = _build_default_execute_fn()
    try:
        asyncio.run(
            serve(
                execute_fn=execute_fn,
                bearer_token=bearer_token,
                max_concurrent_sessions=max_concurrent_sessions,
                session_timeout_seconds=session_timeout_seconds,
            )
        )
    except RuntimeError as exc:
        # The dispatcher refuses to start without a bearer; surface
        # the error cleanly with a non-zero exit code.
        typer.echo(f"acp: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl-C.
        logger.info("acp.cli.serve_interrupted")
        typer.echo("acp: interrupted", err=True)
        raise typer.Exit(code=130) from None


__all__ = ["app", "serve", "serve_cmd"]
