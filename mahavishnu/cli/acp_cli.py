"""CLI surface for the ACP server — ``mahavishnu acp serve``.

Per plan §Phase 2 Task 2. Registers a Typer sub-app on the main CLI
that exposes ``mahavishnu acp serve`` — the stdio JSON-RPC 2.0 dispatcher
described in :mod:`mahavishnu.acp.server`.

The :func:`serve_cmd` is intentionally thin: it acquires the bearer,
constructs the ``execute_fn`` (lazily using the Phase 1.5 factory
``build_execute_fn`` if available, otherwise a stub that echoes the
prompt back), and hands stdin/stdout to :class:`ACPServer`.

Real execute_fn wiring is Phase 1.5 work; the stub here lets the
CLI be smoke-tested end-to-end before that lands.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import typer

from mahavishnu.acp.server import ACPServer

logger = logging.getLogger("mahavishnu.acp.cli")

app = typer.Typer(help="ACP server (stdio JSON-RPC 2.0) commands.")


def _build_default_execute_fn() -> Any:
    """Construct the ``execute_fn`` passed to :class:`ACPServer`.

    Phase 1.5 plan: this delegates to ``build_execute_fn(settings)`` from
    ``mahavishnu.core.execute_fn_factory``. That factory doesn't exist
    yet — Phase 1.5 is a follow-on. Until then, return a stub that
    echoes the prompt back. The dispatcher's protocol behavior is
    fully exercised by this stub; only the actual prompt execution
    is a placeholder.
    """
    try:
        from mahavishnu.core.execute_fn_factory import (
            build_execute_fn,  # type: ignore[import-not-found]
        )

        return build_execute_fn()
    except ImportError:
        # Phase 1.5 hasn't landed yet. Return a stub that just echoes the
        # prompt — enough for the protocol smoke test in Phase 2's
        # exit criteria.
        async def _stub_execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "echo": payload.get("prompt"),
                "stub": True,
                "note": "Phase 1.5 execute_fn not yet wired; this is a stub.",
            }

        return _stub_execute_fn


def _build_stdin_stream() -> Any:
    """Build an :class:`asyncio.StreamReader` over ``sys.stdin``.

    Uses ``loop.connect_read_pipe`` per the asyncio stdio best practice.
    Returns the StreamReader; the actual pipe protocol is owned by
    :func:`serve` below.
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    return loop, reader, protocol


def _build_stdout_stream() -> Any:
    """Build an :class:`asyncio.StreamWriter` over ``sys.stdout``."""
    loop = asyncio.get_event_loop()
    transport, protocol = loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(transport, protocol, loop)
    return writer


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
    server = ACPServer(
        execute_fn=execute_fn,
        bearer_token=bearer_token,
        max_concurrent_sessions=max_concurrent_sessions,
        session_timeout_seconds=session_timeout_seconds,
    )

    async def _run() -> None:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        transport, write_proto = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(transport, write_proto, loop)
        await server.serve(reader, writer)

    try:
        asyncio.run(_run())
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


__all__ = ["app", "serve_cmd"]
