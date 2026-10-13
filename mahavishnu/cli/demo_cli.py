"""``mahavishnu demo <engine|adapter>`` — first-class demo commands.

Re-creates the precedent set by commit ``55630b45`` (Oct 9 2026, since
reverted in an untraceable merge). Each sub-command runs an opinionated
one-line scenario so operators can see the substrate in action without
ad-hoc scripts.

**Wire-up contract (anti-revert)** — three markers all must move together:

1. This docstring references ``mahavishnu/_main_cli.py`` ``=== DEMO
   SUB-COMMANDS ===`` block.
2. ``mahavishnu/_main_cli.py`` carries the matching ``=== DEMO
   SUB-COMMANDS ===`` comment + ``from .cli.demo_cli import demo_app;
   app.add_typer(demo_app, name="demo")`` wiring.
3. ``tests/unit/cli/test_cli_wireup_invariants.py::test_demo_subcommands_wired``
   asserts the ``demo`` Typer group is registered in
   ``mahavishnu._main_cli.app.registered_groups``.

If any marker is missing, the demo commands are silently reverted. A
failing CI is the load-bearing signal — do not remove any of the three.

**Implementation notes:**

- Module-level Typer (``demo_app``) per the Pattern A convention used by
  ``executions_cli``, ``jot_cli``, ``board_cli``, and ``acp_cli``.
- Each sub-command is a Typer callback that reads config via
  ``get_settings().prefect`` (NOT bare ``PrefectConfig()`` — only the
  former honours ``MAHAVISHNU_PREFECT__*`` env vars).
- Prefect demo uses ``prefect.flow_runs.wait_for_flow_run`` (the
  top-level function), not ``client.wait_for_flow_run`` (which doesn't
  exist on ``PrefectClient`` in 3.x — see
  ``mahavishnu/engines/prefect_adapter_impl.py`` for the fix).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import time
from typing import TYPE_CHECKING, Any

import httpx2 as httpx
import typer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


# Module-level Typer app. ``_main_cli.py`` wires it as ``mahavishnu demo ...``.
demo_app = typer.Typer(
    help=(
        "First-class demo commands for workflow engines and terminal adapters. "
        "Each subcommand runs an opinionated one-line scenario so operators "
        "can see the substrate in action without the 8-step ad-hoc flow "
        "from the 2026-10-09 demo."
    ),
    invoke_without_command=True,
)


# ============================================================================
# Shared: tmux demo (rebuilt from commit 55630b45)
# ============================================================================


# Default demo command — banner with PID + timestamp, then sleep so the pane
# stays alive for the capture/ACK step. Mirrors the 2026-10-09 manual flow.
DEFAULT_TMUX_DEMO_CMD = (
    'bash -c \'echo "[worker $$] alive at $(date +%T)"; '
    'echo "[worker $$] tmux session pane running claude_tui equivalent"; '
    "sleep 120'"
)
ACK_COMMAND = "echo '[ack] from mahavishnu demo tmux'"
DEFAULT_SOCKET_DIR = Path("~/.mahavishnu/tmux").expanduser()


def _check_tmux_preconditions(
    *,
    tmux_which: Callable[[str], str | None] | None = None,
    claude_which: Callable[[str], str | None] | None = None,
    socket_dir: Path | None = None,
    require_claude: bool = True,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (injectable for tests):

    - ``tmux`` binary on PATH.
    - ``claude`` binary on PATH (only when ``require_claude``).
    - Socket dir ``socket_dir`` (default ``~/.mahavishnu/tmux``) is writable.
    """
    tmux_which = tmux_which or shutil.which
    claude_which = claude_which or shutil.which
    socket_dir = socket_dir or DEFAULT_SOCKET_DIR
    failures: list[str] = []
    if not tmux_which("tmux"):
        failures.append("tmux binary not on PATH")
    if require_claude and not claude_which("claude"):
        failures.append(
            "claude binary not on PATH (required for default demo command; "
            "pass --cmd '<other>' to skip)"
        )
    try:
        socket_dir.mkdir(parents=True, exist_ok=True)
        probe = socket_dir / ".mahavishnu-demo-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        failures.append(f"socket dir not writable: {socket_dir} ({exc})")
    return failures


def _build_terminal_manager():  # type: ignore[no-untyped-def]
    from mahavishnu.core.app import MahavishnuApp
    from mahavishnu.terminal.manager import TerminalManager

    async def _build() -> TerminalManager:
        maha_app = MahavishnuApp()
        return await TerminalManager.create(maha_app.config, mcp_client=None)

    return asyncio.run(_build())


async def _best_effort_reap(adapter, session_ids: list[str]) -> None:
    """Best-effort cleanup — called from the exception path of the demo."""
    typer.echo(f"\n--- cleanup reap on failure ({len(session_ids)} pane(s)) ---")
    for sid in session_ids:
        try:
            await adapter.close_session(sid)
        except Exception as exc:
            typer.echo(f"  reap failed for {sid}: {exc}")


async def _reap(adapter, session_ids: list[str]) -> None:
    typer.echo(f"\n--- reaping {len(session_ids)} worker(s) ---")
    for sid in session_ids:
        await adapter.close_session(sid)
    typer.echo("Done.")


async def _run_tmux_demo(
    *,
    command: str,
    workers: int,
    keep: bool,
    terminal_manager,
    ack_command: str = ACK_COMMAND,
) -> None:
    """Spawn N panes, capture, send ACK, optionally reap.

    Restructured to avoid B012: ``return``-in-``finally``. The cleanup
    path lives in a dedicated ``_best_effort_reap`` coroutine.
    """
    adapter = terminal_manager.adapter
    session_ids = await adapter.launch_sessions(command, count=workers)
    typer.echo(f"Spawned {len(session_ids)} worker(s):")
    for sid in session_ids:
        typer.echo(f"  - {sid}")

    try:
        typer.echo("\n--- initial pane capture ---")
        for sid in session_ids:
            output = await adapter.capture_output(sid)
            typer.echo(f"[{sid}]\n{output}")
        typer.echo(f"\n--- sending ACK: {ack_command!r} ---")
        for sid in session_ids:
            await adapter.send_command(sid, ack_command)
        typer.echo("\n--- post-ACK pane capture ---")
        for sid in session_ids:
            output = await adapter.capture_output(sid)
            typer.echo(f"[{sid}]\n{output}")
    except Exception:
        await _best_effort_reap(adapter, session_ids)
        raise

    # Success path.
    if keep:
        typer.echo(
            f"\n--keep set: left {len(session_ids)} worker(s) running. "
            "Reap with `mahavishnu pool reap --all --yes`."
        )
        return
    await _reap(adapter, session_ids)


@demo_app.command("tmux")
def demo_tmux(
    workers: int = typer.Option(
        3, "--workers", "-n", min=1, max=50, help="Number of tmux workers to spawn."
    ),
    cmd: str | None = typer.Option(None, "--cmd", "-c", help="Command to run inside each pane."),
    keep: bool = typer.Option(False, "--keep", help="Leave workers up after the demo."),
) -> None:
    """Spawn N tmux workers, capture panes, ACK, then reap (unless --keep).

    Reconstruction of the 55630b45 demo, switched to Pattern A (module-level
    Typer) per current CLI convention.
    """
    command = cmd if cmd is not None else DEFAULT_TMUX_DEMO_CMD
    require_claude = cmd is None
    failures = _check_tmux_preconditions(require_claude=require_claude)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)
    terminal_manager = _build_terminal_manager()
    asyncio.run(
        _run_tmux_demo(
            command=command,
            workers=workers,
            keep=keep,
            terminal_manager=terminal_manager,
        )
    )


# ============================================================================
# prefect demo (full implementation)
# ============================================================================


# Default probe target for the Prefect server (where the REST API lives).
# ``api_url`` from settings is the base; the health endpoint is at /api/health.
PREFECT_HEALTH_PATH = "/api/health"
# Hard floor on the probe timeout. Default 5s; settings.adapters.prefect may
# have a different value, but the demo needs a snappy fallback.
DEFAULT_PRECONDITION_TIMEOUT = 5.0


def _check_prefect_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    api_url_override: str | None = None,
    http_probe: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    timeout: float = DEFAULT_PRECONDITION_TIMEOUT,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``prefect`` binary on PATH (Python SDK callable).
    - ``PREFECT_API_URL`` reachable: ``GET ${url}/api/health`` → 200 ``true``.
    - ``settings.prefect.work_pool`` set (or default ``"default"``).
    """
    which = which or shutil.which
    http_probe = http_probe or httpx.get
    settings_getter = settings_getter or _default_settings_getter

    failures: list[str] = []
    if not which("prefect"):
        failures.append(
            "prefect binary not on PATH (.venv/bin/prefect; run uv pip install -e .[prefect])"
        )

    try:
        settings = settings_getter()
    except Exception as exc:
        failures.append(f"could not load settings: {exc}")
        return failures

    prefect_cfg = settings.prefect  # type: ignore[attr-defined]
    api_url = (api_url_override or str(prefect_cfg.api_url)).rstrip("/")
    if not api_url.endswith("/api"):
        api_url = api_url + "/api"
    health_url = api_url + "/health"

    try:
        resp = http_probe(health_url, timeout=timeout)
        if resp.status_code != 200:
            failures.append(f"Prefect server returned HTTP {resp.status_code} at {health_url}")
    except Exception as exc:
        failures.append(f"Prefect server unreachable at {health_url}: {exc}")

    work_pool = getattr(prefect_cfg, "work_pool", None)
    if not work_pool:
        failures.append("prefect.work_pool is unset (set MAHAVISHNU_PREFECT__WORK_POOL)")
    return failures


def _default_settings_getter() -> Any:
    # Lazy import so the precondition helper does not trigger Oneiric loader
    # at module-import time (which would break CLI test isolation).
    from mahavishnu.core.config import get_settings

    return get_settings()


async def _run_prefect_demo(
    *,
    repos: Sequence[str],
    keep: bool,
    flow_dotted: str,
    extra_parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """Drive the Prefect engine end-to-end. Returns a structured result dict.

    Uses the canonical ``prefect.flow_runs.wait_for_flow_run`` (NOT the
    dead ``client.wait_for_flow_run`` method) to block on completion.
    Threads ``prefect.work_pool`` from settings into ``create_flow_run``
    so the demo routes flow runs to the operator's intended pool on
    multi-tenant servers.
    """
    import importlib

    from prefect.client.orchestration import get_client
    from prefect.flow_runs import wait_for_flow_run

    module_dotted, _, attr_name = flow_dotted.partition(":")
    if not module_dotted or not attr_name:
        raise ValueError(f"--flow must be 'pkg.module:func' shape, got {flow_dotted!r}")
    flow_module = importlib.import_module(module_dotted)
    flow_func = getattr(flow_module, attr_name, None)
    if flow_func is None:
        raise ValueError(f"--flow resolves to {module_dotted!r} but no {attr_name!r} attribute")

    settings = _default_settings_getter()
    prefect_cfg = settings.prefect  # type: ignore[attr-defined]
    work_pool = prefect_cfg.work_pool
    parameters = {
        "repos": list(repos),
        "task_spec": {"id": f"demo-{int(time.time())}", "type": "default"},
        **(extra_parameters or {}),
    }

    async with get_client() as client:
        flow_run = await client.create_flow_run(
            flow=flow_func,
            parameters=parameters,
            name="mahavishnu-demo-prefect",
            work_pool_name=work_pool,
        )
        polled_run = await wait_for_flow_run(flow_run.id, timeout=prefect_cfg.timeout_seconds)
        state = polled_run.state
        is_completed = bool(state and state.is_completed())
        results = state.result() if is_completed else []
        if results is None:
            results = []

    return {
        "flow_run_id": str(flow_run.id),
        "flow_run_url": f"http://{prefect_cfg.api_url.replace('http://', '').rstrip('/api')}/flows/flow-run/{flow_run.id}",
        "state": state.type if state else "UNKNOWN",
        "state_name": state.name if state else "Unknown",
        "repos_processed": len(repos),
        "results_count": len(results),
    }


@demo_app.command("prefect")
def demo_prefect(
    repos: list[str] = typer.Option(
        [],
        "--repos",
        help="Repos to pass to the flow. Defaults to the Mahavishnu repo itself.",
    ),
    flow_dotted: str = typer.Option(
        "mahavishnu.engines.prefect_adapter_impl:process_repositories_flow",
        "--flow",
        help="Dotted path 'pkg.module:func' to a @flow-decorated function.",
    ),
    keep: bool = typer.Option(False, "--keep", help="Leave any deployment running."),
    timeout: int = typer.Option(120, "--timeout", help="Max seconds to wait for the flow run."),
) -> None:
    """Run a Prefect flow end-to-end against the live API server.

    Resolves ``MAHAVISHNU_PREFECT__*`` env vars via ``get_settings()``; honors
    the configured ``work_pool``; polls to completion via
    ``prefect.flow_runs.wait_for_flow_run``. Prints the run URL so the
    operator can tail it in the Prefect UI.
    """
    failures = _check_prefect_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        typer.echo(
            "\nHint: start a Prefect server with "
            "`prefect server start --background --port 4200`, then re-run.",
            err=True,
        )
        raise typer.Exit(code=1)
    effective_repos = list(repos) or [str(Path(__file__).resolve().parents[3])]
    typer.echo(f"Dispatching to work_pool: {_default_settings_getter().prefect.work_pool}")
    typer.echo(f"Flow: {flow_dotted}")
    typer.echo(f"Repos: {effective_repos}")

    async def _run_with_timeout() -> dict[str, object]:
        # Patch timeout onto the helper scope via an asyncio.wait_for.
        # The helper blocks on wait_for_flow_run which respects
        # prefect_cfg.timeout_seconds by default; we leave that in place.
        return await _run_prefect_demo(
            repos=effective_repos,
            keep=keep,
            flow_dotted=flow_dotted,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s waiting for the flow run", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nFlow run result:")
    typer.echo(json.dumps(result, indent=2, default=str))
    typer.echo(f"\nView: {result['flow_run_url']}")


# ============================================================================
# Stubs — 7 engines/terminals as discovery surface per user decision
# ============================================================================


def _emit_stub_notice(name: str, why: bool, implementation_cost: str) -> None:
    if why:
        typer.echo(f"[{name}] implementation cost: {implementation_cost}")
        typer.echo("Plan: /Users/les/.claude/plans/dazzling-waddling-ullman.md")
        raise typer.Exit(code=0)
    typer.echo(
        "not implemented — see docs/plans/2026-10-11-prefect-adapter-bug-fixes-demo-cli-launchd.md"
    )
    raise typer.Exit(code=0)


_STUB_COSTS = {
    "agno": "~80 LOC: AgnoAdapter.execute + 2 pinned tests",
    "llamaindex": "~60 LOC: LlamaIndexAdapter.retrieve + 1 ingestion pinning test",
    "hatchet": "~70 LOC: HatchetEngine adaptation (alternative durable flow)",
    "pydantic_ai": "~50 LOC: PydanticAIAdapter agent shell",
    "crow": "~40 LOC: TerminalManager adapter bridge to crow-mcp",
    "goose": "~40 LOC: TerminalManager adapter bridge to goose serve",
    "mock": "~25 LOC: in-process adapter (already exists; CLI surface only)",
}


def _stub_command(name: str) -> Callable[[bool], None]:
    """Build a Typer callback factory for ``name``.

    Each callback exposes ``--why-stub`` which prints the implementation
    cost (per the user's decision: stubs are discovery surface, not
    silent failure modes).
    """

    def callback(
        why_stub: bool = typer.Option(
            False, "--why-stub", help="Print implementation cost and exit."
        ),
    ) -> None:
        _emit_stub_notice(name, why=why_stub, implementation_cost=_STUB_COSTS[name])

    return callback


# Register the 7 stubs. Live implementations land in follow-up PRs.
for _stub_name in ("agno", "llamaindex", "hatchet", "pydantic_ai", "crow", "goose", "mock"):
    _cmd = _stub_command(_stub_name)
    demo_app.command(_stub_name)(_cmd)
del _stub_name, _cmd  # hygiene


__all__ = ["demo_app"]
