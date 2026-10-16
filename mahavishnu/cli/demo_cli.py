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
import os
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
        except Exception as exc:  # CLI entry point — reap failures must never break the calling exception path  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
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
    except (
        Exception
    ):  # CLI entry point — demo flow must reap orphan panes on any failure before re-raising
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
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure, not a stack trace  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
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
    except Exception as exc:  # CLI entry point — HTTP probe failure surfaces as a precondition failure, not a stack trace  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
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
# agno demo (full implementation — replaces 2026-10-15 stub)
# ============================================================================


DEFAULT_AGNO_PRECONDITION_TIMEOUT = 5.0


def _check_agno_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    import_probe: Callable[[str], Any] | None = None,
    env_getter: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``agno`` Python SDK importable.
    - For non-llama_server providers, the configured ``api_key_env`` is set
      in the environment (or ``None`` falls back to the provider default).
    - Settings are loadable (rejects malformed Oneiric config).
    """
    settings_getter = settings_getter or _default_settings_getter
    import_probe = import_probe or _default_import_probe
    env_getter = env_getter or os.getenv

    failures: list[str] = []
    if import_probe("agno") is None:
        failures.append(
            "agno SDK not installed (.venv/bin/python -c 'import agno' fails; "
            "run uv pip install -e .[agno] or 'uv sync --group agno')"
        )

    try:
        settings = settings_getter()
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
        failures.append(f"could not load settings: {exc}")
        return failures

    try:
        agno_llm = settings.agno.llm  # type: ignore[attr-defined]
    except AttributeError as exc:
        failures.append(f"settings.agno.llm not configured: {exc}")
        return failures

    # Provider-aware API-key check (llama_server runs locally with no key).
    from mahavishnu.core.config import LLMProvider

    provider_value = agno_llm.provider
    provider = (
        provider_value
        if isinstance(provider_value, LLMProvider)
        else LLMProvider(provider_value)
        if isinstance(provider_value, str)
        else None
    )
    provider_default_env = (
        {
            LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.MINIMAX: "MINIMAX_API_KEY",
            LLMProvider.LLAMA_SERVER: None,  # no API key required
        }.get(provider)
        if provider is not None
        else None
    )

    env_var = agno_llm.api_key_env or provider_default_env
    if env_var and not env_getter(env_var):
        failures.append(
            f"LLM API key not set. {env_var} is unset (or set "
            f"MAHAVISHNU_AGNO__LLM__API_KEY_ENV to a populated env var)"
        )

    return failures


def _default_import_probe(module_name: str) -> Any | None:
    """Lazy-import probe (injectable for tests)."""
    try:
        return __import__(module_name)
    except ImportError:
        return None


async def _run_agno_demo(
    *,
    repos: Sequence[str],
    task_type: str,
    params: dict[str, object] | None = None,
    keep: bool = False,
) -> dict[str, object]:
    """Drive the Agno engine end-to-end against one or more repositories.

    Constructs ``AgnoAdapter`` directly, initializes it, calls
    ``adapter.execute(task, repos)``, and shuts down cleanly. Uses
    ``AgnoAdapter.execute`` rather than ``run_team`` so the single-task
    path is exercised; for multi-agent team orchestration use
    ``mahavishnu team {create,run}``.

    On the exception path, ``adapter.shutdown()`` is best-effort called
    before re-raising — mirrors the ``_run_tmux_demo`` reap-on-error
    pattern at ``_run_tmux_demo:174-178``.
    """
    settings = _default_settings_getter()
    from mahavishnu.engines.agno_adapter_impl import AgnoAdapter

    task = {
        "id": f"demo-agno-{int(time.time())}",
        "type": task_type,
        "params": dict(params or {}),
    }

    adapter = AgnoAdapter(config=settings)
    try:
        await adapter.initialize()
    except Exception:  # shutdown is best-effort on init failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_agno_shutdown(adapter)
        raise

    try:
        result = await adapter.execute(task=task, repos=list(repos))
    except Exception:  # shutdown is best-effort on execute failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_agno_shutdown(adapter)
        raise

    if not keep:
        await adapter.shutdown()

    return {
        "status": result.get("status"),
        "engine": result.get("engine"),
        "engine_version": result.get("engine_version"),
        "task_type": task_type,
        "repos": list(repos),
        "repos_processed": result.get("repos_processed"),
        "success_count": result.get("success_count"),
        "failure_count": result.get("failure_count"),
        "first_result": (result.get("results") or [None])[0],
    }


async def _best_effort_agno_shutdown(adapter: Any) -> None:
    """Best-effort shutdown — called from the exception path."""
    try:
        await adapter.shutdown()
    except Exception as exc:  # CLI entry point — shutdown errors must never mask the original failure  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
        typer.echo(f"[warning] adapter shutdown failed: {exc}", err=True)


@demo_app.command("agno")
def demo_agno(
    repos: list[str] = typer.Option(
        [],
        "--repos",
        help="Repos to pass to AgnoAdapter.execute. Defaults to the Mahavishnu repo itself.",
    ),
    task_type: str = typer.Option(
        "default",
        "--task-type",
        "-t",
        help="Agno task type (e.g. code_sweep, quality_check, default).",
    ),
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Optional focus hint passed through as task.params.focus.",
    ),
    keep: bool = typer.Option(
        False,
        "--keep",
        help="Leave the AgnoAdapter initialized after the demo (rarely useful; mainly for debugging).",
    ),
    timeout: int = typer.Option(
        120, "--timeout", help="Max seconds to wait for AgnoAdapter.execute."
    ),
) -> None:
    """Run the Agno engine end-to-end against the live LLM provider.

    Constructs ``AgnoAdapter`` directly, calls ``adapter.execute(task,
    repos)``, prints the trimmed result, and shuts down. The LLM
    provider and API key env var are read from
    ``settings.agno.llm.{provider,api_key_env}`` (see
    ``settings/mahavishnu.yaml`` under ``agno:``).
    """
    failures = _check_agno_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    settings = _default_settings_getter()
    effective_repos: list[str] = list(repos) or [str(Path(__file__).resolve().parents[3])]
    params: dict[str, object] = {}
    if prompt:
        params["focus"] = prompt

    typer.echo(f"LLM provider: {settings.agno.llm.provider.value}")
    typer.echo(f"LLM model:    {settings.agno.llm.model_id}")
    typer.echo(f"Task type:    {task_type}")
    typer.echo(f"Repos:        {effective_repos}")

    async def _run_with_timeout() -> dict[str, object]:
        return await _run_agno_demo(
            repos=effective_repos,
            task_type=task_type,
            params=params,
            keep=keep,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s waiting for AgnoAdapter.execute", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nAgno demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# llamaindex demo (full implementation — replaces 2026-10-16 stub)
# ============================================================================


DEFAULT_LLAMAINDEX_PRECONDITION_TIMEOUT = 5.0


def _check_llamaindex_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    import_probe: Callable[[str], Any] | None = None,
    http_probe: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_LLAMAINDEX_PRECONDITION_TIMEOUT,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``llama_index.core`` importable (the minimal public surface the
      adapter actually uses; the full extras live in the ``[llamaindex]``
      optional group).
    - ``llama_server_url`` is set and reachable (the embed/llm
      endpoint; after the ollama drop this is the canonical local
      provider).
    - Settings are loadable (rejects malformed Oneiric config).
    """
    settings_getter = settings_getter or _default_settings_getter
    import_probe = import_probe or _default_import_probe
    http_probe = http_probe or httpx.get

    failures: list[str] = []
    if import_probe("llama_index.core") is None:
        failures.append(
            "llama-index not installed (.venv/bin/python -c 'import llama_index.core' "
            "fails; run uv pip install -e .[llamaindex])"
        )

    try:
        settings = settings_getter()
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(f"could not load settings: {exc}")
        return failures

    # The adapter's config exposes llama_server_url. Reject explicit
    # un-set; oneiric settings may not have it populated.
    llama_url = getattr(settings, "llama_server_url", None) or "http://localhost:8081"
    try:
        resp = http_probe(llama_url.rstrip("/") + "/v1/models", timeout=timeout)
        if resp.status_code != 200:
            failures.append(
                f"llama_server returned HTTP {resp.status_code} at "
                f"{llama_url}/v1/models (is the server running?)"
            )
    except Exception as exc:  # CLI entry point — HTTP probe failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(
            f"llama_server unreachable at {llama_url}/v1/models: {exc}. "
            "Start the llama.cpp server with `--embedding` enabled."
        )

    return failures


async def _run_llamaindex_demo(
    *,
    repos: Sequence[str],
    task_type: str,
    query: str,
    keep: bool = False,
) -> dict[str, object]:
    """Drive the LlamaIndex engine end-to-end against one or more repos.

    Uses ``LlamaIndexAdapter.execute`` with task types ``ingest`` /
    ``query`` / ``ingest_and_query`` — the same wire as the production
    path. ``query`` is the default; ``ingest_and_query`` exercises the
    full ingest-then-retrieve path. On the exception path
    ``adapter.cleanup()`` is best-effort called before re-raising,
    mirroring the ``_run_tmux_demo`` reap-on-error pattern at
    ``_run_tmux_demo:174-178``.
    """
    settings = _default_settings_getter()
    from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter

    task = {
        "id": f"demo-llamaindex-{int(time.time())}",
        "type": task_type,
        "params": {"query": query} if task_type in {"query", "ingest_and_query"} else {},
    }

    adapter = LlamaIndexAdapter(config=settings)
    try:
        await adapter.initialize()
    except Exception:  # cleanup is best-effort on init failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_llamaindex_cleanup(adapter)
        raise

    try:
        result = await adapter.execute(task=task, repos=list(repos))
    except Exception:  # cleanup is best-effort on execute failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_llamaindex_cleanup(adapter)
        raise

    if not keep:
        await adapter.cleanup()

    return {
        "status": result.get("status"),
        "engine": result.get("engine"),
        "execution_id": result.get("execution_id"),
        "task_type": task_type,
        "query": query,
        "repos": list(repos),
        "repos_processed": result.get("repos_processed"),
        "success_count": result.get("success_count"),
        "failure_count": result.get("failure_count"),
        "first_result": (result.get("results") or [None])[0],
    }


async def _best_effort_llamaindex_cleanup(adapter: Any) -> None:
    """Best-effort cleanup — called from the exception path."""
    try:
        await adapter.cleanup()
    except Exception as exc:  # CLI entry point — cleanup errors must never mask the original failure  # noqa: BLE001, RUF100
        typer.echo(f"[warning] adapter cleanup failed: {exc}", err=True)


@demo_app.command("llamaindex")
def demo_llamaindex(
    repos: list[str] = typer.Option(
        [],
        "--repos",
        help="Repos to pass to LlamaIndexAdapter.execute. Defaults to the Mahavishnu repo itself.",
    ),
    task_type: str = typer.Option(
        "query",
        "--task-type",
        "-t",
        help="LlamaIndex task type (ingest, query, or ingest_and_query).",
    ),
    query: str = typer.Option(
        "summarize the project structure",
        "--query",
        "-q",
        help="Focus query passed to the retrieval step (used for 'query' and 'ingest_and_query').",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave the adapter initialized after the demo (mainly for debugging)."
    ),
    timeout: int = typer.Option(
        120, "--timeout", help="Max seconds to wait for LlamaIndexAdapter.execute."
    ),
) -> None:
    """Run the LlamaIndex engine end-to-end against the live llama_server.

    Constructs ``LlamaIndexAdapter`` directly, calls
    ``adapter.execute(task, repos)``, prints the trimmed result, and
    cleans up. The llama_server URL and the embed/llm model names are
    read from settings (post-ollama drop the canonical local provider
    is llama.cpp's OpenAI-compat server, not a separate Ollama process).
    """
    if task_type not in {"ingest", "query", "ingest_and_query"}:
        typer.echo(
            f"Invalid --task-type {task_type!r}; must be ingest, query, or ingest_and_query",
            err=True,
        )
        raise typer.Exit(code=2)

    failures = _check_llamaindex_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    settings = _default_settings_getter()
    effective_repos: list[str] = list(repos) or [str(Path(__file__).resolve().parents[3])]
    llama_url = getattr(settings, "llama_server_url", None) or "http://localhost:8081"
    typer.echo(f"llama_server URL: {llama_url}")
    typer.echo(f"Task type:        {task_type}")
    typer.echo(f"Query:            {query}")
    typer.echo(f"Repos:            {effective_repos}")

    async def _run_with_timeout() -> dict[str, object]:
        return await _run_llamaindex_demo(
            repos=effective_repos,
            task_type=task_type,
            query=query,
            keep=keep,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(
            f"Timed out after {timeout}s waiting for LlamaIndexAdapter.execute",
            err=True,
        )
        raise typer.Exit(code=2) from None

    typer.echo("\nLlamaIndex demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# Stubs — 5 engines/terminals (agno + llamaindex promoted to live
# implementations above)
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


# Register the 5 stubs. Live implementations land in follow-up PRs.
for _stub_name in ("hatchet", "pydantic_ai", "crow", "goose", "mock"):
    _cmd = _stub_command(_stub_name)
    demo_app.command(_stub_name)(_cmd)
del _stub_name, _cmd  # hygiene


__all__ = ["demo_app"]
