"""CLI surface for the ACP server — ``mahavishnu acp serve``.

Per plan §Phase 2 Task 2. Registers a Typer sub-app on the main CLI
that exposes ``mahavishnu acp serve`` — the stdio JSON-RPC 2.0 dispatcher
described in :mod:`mahavishnu.acp.server`.

The :func:`serve_cmd` is intentionally thin: it acquires the bearer,
constructs the ``execute_fn`` (using the Phase 1.5 factory
``build_execute_fn``), and hands stdin/stdout to the dispatcher via
the module-level :func:`mahavishnu.acp.server.serve`.

The factory wires either:

- **A real ``MahavishnuApp``** (default) — the dispatcher delegates
  ``session/prompt`` payloads to ``app.execute_workflow(...)`` via a
  small adapter shim. Construction adds ~2-3 s of Oneiric config load
  + adapter initialization, paid once at CLI startup.
- **The echo stub** — set ``MAHAVISHNU_ACP_STUB_EXECUTE_FN=1`` to
  fall back to the stub. Useful for fast unit tests that don't want
  the Oneiric / adapter boot cost, or when an operator needs to
  validate the dispatcher without a configured app.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import typer

from mahavishnu.acp.server import serve
from mahavishnu.core.config import ACPSettings
from mahavishnu.core.execute_fn_factory import build_execute_fn

logger = logging.getLogger("mahavishnu.acp.cli")

app = typer.Typer(help="ACP server (stdio JSON-RPC 2.0) commands.")


_DEFAULT_ADAPTER_NAME = "langgraph"


class _MahavishnuAppAdapter:
    """Bridge ``MahavishnuApp.execute_workflow`` to the factory's single-arg contract.

    The factory expects ``execute(payload: dict) -> Awaitable[Any]``;
    ``MahavishnuApp`` exposes the workflow-shaped API
    ``execute_workflow(task, adapter_name, repos, user_id)``. This shim
    translates ACP ``session/prompt`` payloads into the workflow shape.

    The adapter name is fixed at construction time — the ACP CLI is
    a single-protocol entry point and does not implement dynamic
    adapter routing. Operators wanting per-prompt adapter selection
    should use the full ``mahavishnu`` CLI surface.
    """

    def __init__(self, app: Any, *, adapter_name: str = _DEFAULT_ADAPTER_NAME) -> None:
        self._app = app
        self._adapter_name = adapter_name

    async def execute(self, payload: dict[str, Any]) -> Any:
        prompt = payload.get("prompt", "")
        return await self._app.execute_workflow(
            task={"type": "code_sweep", "prompt": prompt},
            adapter_name=self._adapter_name,
            repos=None,
            user_id=payload.get("user_id"),
        )


def _build_default_execute_fn() -> Any:
    """Construct the ``execute_fn`` passed to the dispatcher.

    Behavior:

    1. If ``MAHAVISHNU_ACP_STUB_EXECUTE_FN=1`` is set, build the echo
       stub via the factory. No ``MahavishnuApp`` is constructed — fast
       startup, suitable for protocol-level tests.
    2. Otherwise, construct a real ``MahavishnuApp`` and attach it via
       ``ACPSettings(app=shim)``. The factory's app-wired branch picks
       up ``settings.app`` and routes through ``shim.execute(payload)``.

    The CLI builds a standalone ``ACPSettings()`` instance — it does
    not need the top-level ``MahavishnuSettings.acp`` wiring because
    the ACP CLI is self-contained by design.

    Raises:
        RuntimeError: If ``MahavishnuApp`` construction fails (e.g.,
            Oneiric config load, missing dependencies). The original
            exception is chained via ``raise ... from``.
    """
    if os.getenv("MAHAVISHNU_ACP_STUB_EXECUTE_FN"):
        logger.info("acp.cli.stub_execute_fn_enabled")
        return build_execute_fn(ACPSettings())

    try:
        from mahavishnu.core.app import MahavishnuApp
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            f"failed to import MahavishnuApp for ACP CLI: {exc}. "
            "Set MAHAVISHNU_ACP_STUB_EXECUTE_FN=1 to fall back to the echo stub."
        ) from exc

    try:
        app_instance = MahavishnuApp()
    except Exception as exc:
        raise RuntimeError(
            f"failed to construct MahavishnuApp for ACP CLI: {exc}. "
            "Set MAHAVISHNU_ACP_STUB_EXECUTE_FN=1 to fall back to the echo stub."
        ) from exc

    shim = _MahavishnuAppAdapter(app_instance)
    return build_execute_fn(ACPSettings(app=shim))


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
