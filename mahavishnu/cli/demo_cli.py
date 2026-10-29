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
import inspect
import json
import os
from pathlib import Path
import shutil
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

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

    2026-10-19: rewritten to use ``flow.from_source(...).deploy()``
    with a ``GitRepository`` storage, instead of the historical
    ``client.create_flow_run(flow=fn, work_pool_name=...)`` ad-hoc
    pattern. The historical path silently failed against Prefect 3.x
    process worker pools — the worker subprocess couldn't import
    the in-memory flow object (no source path serialized), so the
    run sat PENDING until the demo's 120s poll timeout.

    Why ``GitRepository``: Prefect 3.x requires *image OR remote
    storage* when deploying via a process work pool (per the
    ``Either an image or remote storage location must be provided``
    guard). Local filesystems don't satisfy the "remote" predicate.
    Prefect Core's own ``prefect.runner.storage.GitRepository``
    provides that remote storage, so the demo can persist the
    source location to the worker's subprocess via a real remote
    (the project's ``lesleslie/mahavishnu`` GitHub remote, branch
    ``main``). The worker subprocess clones, imports the module
    by entrypoint path, and runs the flow.

    Trade-off: the demo now requires the worker subprocess to be
    able to reach ``github.com:443``. In environments without that
    connectivity, fall back to building a docker image on the
    configured pool's worker hardware and passing ``image`` to
    ``adeploy``.
    """
    import importlib

    from prefect.client.orchestration import get_client
    from prefect.deployments import run_deployment
    from prefect.flow_runs import wait_for_flow_run
    from prefect.runner.storage import GitRepository

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
    flow_name = flow_func.name

    parameters = {
        "repos": list(repos),
        "task_spec": {"id": f"demo-{int(time.time())}", "type": "default"},
        **(extra_parameters or {}),
    }

    # Deploy first (idempotent by deployment name + storage fetch).
    # Pref Core's ``GitRepository`` is used here (not ``prefect_github.
    # repository.GitHubRepository``) because Pref Core's variant gives
    # a deterministic destination name ``<repo>-<branch>`` (e.g.
    # ``mahavishnu-main``) whereas the GitHubRepository block's
    # default resolves to ``github-repository-None``, which makes
    # the worker subprocess' ``__set_sys_path`` write an unreadable
    # directory into the module name.
    #
    # KNOWN LIMITATION (2026-10-19): the worker subprocess still fails
    # the import with ``ModuleNotFoundError: No module named
    # '<tmpdir>/<repo>-<branch>/<module>'``. Root cause: Prefect 3.x's
    # worker executor uses ``os.getcwd()`` as the import sys.path
    # root (see ``prefect/utilities/importtools.py::load_module``)
    # rather than the storage's pulled destination, and never
    # ``os.chdir(destination)`` before invoking the entrypoint. The
    # destination IS on sys.path (the load_module helper inserts it),
    # but Python's import machinery is receiving a path-prefixed
    # module name in the error path suggesting the prefix got
    # concatenated somewhere in the executor. Resolving this requires
    # either (a) a worker-level ``chdir`` step in the deployment's
    # ``pull_steps`` chain, (b) a Prefect upstream fix to make the
    # executor ``os.chdir(destination)`` before entrypoint load, or
    # (c) pinning the work pool's ``working_dir`` template variable
    # so ``storage._storage_base_path`` resolves to the clone dir on
    # the executor's first call. The current demo exercises the path
    # to the failure surface so subsequent readers see the exact
    # blocker; operators handling it from the running side should
    # verify the executor's CWD matches the storage's
    # ``destination`` path before granting the demo \"passes\" status.
    storage = GitRepository(
        url="https://github.com/lesleslie/mahavishnu.git",
        branch="main",
    )

    src_with_flow = await flow_func.afrom_source(
        source=storage,
        entrypoint=f"{module_dotted}:{attr_name}",
    )
    deployment_id = await src_with_flow.adeploy(
        name="mahavishnu-demo-flow",
        work_pool_name=work_pool,
        tags=["mahavishnu", "demo"],
    )

    # Submit a run against the persisted deployment. The worker
    # subprocess pulls the source from the GitRepository and
    # imports the entrypoint module from the cloned tree.
    #
    # ``run_deployment`` is wrapped in Prefect's ``async_dispatch``
    # decorator: inside a running event loop it returns the
    # ``arun_deployment`` coroutine, and in a sync context it returns
    # an already-resolved ``FlowRun``. This helper is async, so the
    # coroutine branch is what fires at runtime — but await only when
    # the value is genuinely awaitable, because awaiting a resolved
    # ``FlowRun`` would raise ``TypeError``.
    deployment_run = run_deployment(
        name=f"{flow_name}/mahavishnu-demo-flow",
        parameters=parameters,
        timeout=prefect_cfg.timeout_seconds,
    )
    if inspect.isawaitable(deployment_run):
        flow_run = await deployment_run
    else:
        flow_run = deployment_run

    # ``prefect.flow_runs.wait_for_flow_run`` requires a ``UUID``.
    # ``FlowRun.id`` is already a ``UUID`` at runtime; the explicit
    # conversion keeps the contract honest for any string-shaped id
    # and turns a malformed id into a readable failure instead of a
    # raw ``ValueError`` from inside Prefect.
    raw_flow_run_id = getattr(flow_run, "id", None)
    if raw_flow_run_id is None:
        raise ValueError("Prefect run_deployment returned a flow run without an id")
    try:
        flow_run_id = UUID(str(raw_flow_run_id))
    except ValueError as exc:
        raise ValueError(f"Prefect returned a non-UUID flow run id: {raw_flow_run_id!r}") from exc

    async with get_client():
        polled_run = await wait_for_flow_run(flow_run_id, timeout=prefect_cfg.timeout_seconds)
        state = polled_run.state
        is_completed = bool(state and state.is_completed())
        results = state.result() if is_completed else []
        if results is None:
            results = []

    return {
        "flow_run_id": str(flow_run_id),
        "deployment_id": str(deployment_id),
        "flow_run_url": f"http://{prefect_cfg.api_url.replace('http://', '').rstrip('/api')}/flows/flow-run/{flow_run_id}",
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
      endpoint; this is the canonical local provider).
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
    read from settings (the canonical local provider is llama.cpp's
    OpenAI-compat server).
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
# pydantic_ai demo (full implementation — replaces 2026-10-16 stub)
# ============================================================================


DEFAULT_PYDANTIC_AI_PRECONDITION_TIMEOUT = 5.0

# Provider → env-var mapping (mirrors `_check_agno_preconditions`).
# ``None`` means the provider is local and needs no API key.
_PYDANTIC_AI_PROVIDER_KEY_ENV: dict[str, str | None] = {
    "minimax": "MINIMAX_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "llama_server": None,
}


def _check_pydantic_ai_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    import_probe: Callable[[str], Any] | None = None,
    env_getter: Callable[[str], str | None] | None = None,
    http_probe: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_PYDANTIC_AI_PRECONDITION_TIMEOUT,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``pydantic_ai`` importable (the minimal public surface the
      adapter actually uses; lives in the ``[ai]`` optional group).
    - ``settings.integrations.pydantic_ai_enabled`` is True (the
      feature flag the engine dispatch checks before constructing
      the adapter).
    - At least one provider is reachable — either the local
      ``llama_server`` (no key required) or one of the cloud
      providers (``MINIMAX_API_KEY`` / ``ANTHROPIC_API_KEY`` /
      ``OPENAI_API_KEY``). The adapter's own
      ``PydanticAISettings.primary_model`` defaults to None, so a
      demo without a key surfaces as a noisy "no model configured"
      failure rather than a clean run.
    - Settings are loadable (rejects malformed Oneiric config).
    """
    settings_getter = settings_getter or _default_settings_getter
    import_probe = import_probe or _default_import_probe
    env_getter = env_getter or os.getenv
    http_probe = http_probe or httpx.get

    failures: list[str] = []
    if import_probe("pydantic_ai") is None:
        failures.append(
            "pydantic-ai not installed (.venv/bin/python -c 'import pydantic_ai' "
            "fails; run 'uv sync --group ai')"
        )

    try:
        settings = settings_getter()
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(f"could not load settings: {exc}")
        return failures

    enabled = bool(getattr(getattr(settings, "integrations", None), "pydantic_ai_enabled", False))
    if not enabled:
        failures.append(
            "settings.integrations.pydantic_ai_enabled is False "
            "(set MAHAVISHNU_INTEGRATIONS__PYDANTIC_AI_ENABLED=true)"
        )

    # At least one provider must be reachable. Local llama_server wins
    # if it's up; otherwise we need a cloud API key.
    llama_url = getattr(settings, "llama_server_url", None) or "http://localhost:8081"
    llama_reachable = False
    try:
        resp = http_probe(llama_url.rstrip("/") + "/v1/models", timeout=timeout)
        llama_reachable = resp.status_code == 200
    except (  # CLI entry point — HTTP probe failure surfaces as "not reachable"
        Exception  # noqa: BLE001, RUF100
    ):
        llama_reachable = False

    cloud_keys = {
        env_name
        for env_name in (
            "MINIMAX_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
        )
        if env_getter(env_name)
    }

    if not llama_reachable and not cloud_keys:
        # The mapping carries ``None`` for key-less local providers
        # (``llama_server``). The three cloud providers below always
        # map to a real env-var name, so dropping the ``None`` entries
        # keeps the rendered hint identical.
        provider_key_envs = sorted(
            env_name
            for env_name in (
                _PYDANTIC_AI_PROVIDER_KEY_ENV[p] for p in ("anthropic", "minimax", "openai")
            )
            if env_name is not None
        )
        failures.append(
            f"no LLM provider reachable. Start llama_server at {llama_url} "
            f"(with --embeddings) or set one of: "
            f"{', '.join(provider_key_envs)}"
        )

    return failures


async def _run_pydantic_ai_demo(
    *,
    repos: Sequence[str],
    prompt: str,
    keep: bool = False,
) -> dict[str, object]:
    """Drive the Pydantic-AI engine end-to-end against one or more repos.

    Uses ``PydanticAIAdapter.execute`` with a single ``"agent"`` task
    carrying the user's prompt as ``task.prompt``.

    The adapter's ``PydanticAISettings`` defaults to
    ``primary_model=None, fallback_models=[]``, which trips the
    ``MHV-001 No models configured`` guard at execute time — so the
    demo must inject a ``ModelConfig`` based on the detected provider
    and set the SDK env vars pydantic-ai reads on its own
    (``OPENAI_API_KEY``/``OPENAI_BASE_URL`` for ``llama_server``;
    ``ANTHROPIC_API_KEY``/``OPENAI_API_KEY``/``MINIMAX_API_KEY`` are
    the user's responsibility for cloud providers).

    On the exception path ``adapter.shutdown()`` is best-effort called
    before re-raising, mirroring the ``_run_tmux_demo`` reap-on-error
    pattern.
    """
    from mahavishnu.adapters.ai.pydantic_ai_adapter import (
        PydanticAIAdapter,
        PydanticAISettings,
    )

    model_config, env_overrides = _resolve_demo_pydantic_ai_model_config()
    # pydantic-ai's SDK reads these env vars directly. Set them only
    # if the user hasn't already exported a value (setdefault semantics).
    for key, value in env_overrides.items():
        os.environ.setdefault(key, value)

    task = {
        "id": f"demo-pydantic-ai-{int(time.time())}",
        "type": "agent",
        "prompt": prompt,
        # pydantic-ai 2.57.0's Agent constructor iterates over
        # ``system_prompt`` internally and fails on None. The adapter
        # passes ``task["system_prompt"]`` straight through without
        # defaulting, so the demo has to provide one. A future adapter
        # fix could default to "" when the task omits it.
        "system_prompt": "You are a helpful assistant. Be concise.",
    }

    adapter = PydanticAIAdapter(
        settings=PydanticAISettings(primary_model=model_config),
        # pydantic-ai's Agent requires a non-None output_type; ``str``
        # is the simplest shape and yields plain text the demo can
        # print. A future demo could parameterize a Pydantic model
        # here to show the structured-output story.
        #
        # The ``ty: ignore`` is a genuine false positive: the
        # adapter's ``OutputT`` TypeVar is bound to ``BaseModel``, but
        # the value is forwarded verbatim to pydantic-ai's
        # ``Agent(output_type=...)``, whose ``OutputSpec`` accepts
        # ``type[str]`` (verified against pydantic-ai 2.63.0). The
        # adapter's own bound is over-tight for this call site.
        output_type=str,  # ty: ignore[invalid-argument-type]
    )
    try:
        await adapter.initialize()
    except Exception:  # cleanup is best-effort on init failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_pydantic_ai_shutdown(adapter)
        raise

    try:
        result = await adapter.execute(task=task, repos=list(repos))
    except Exception:  # cleanup is best-effort on execute failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_pydantic_ai_shutdown(adapter)
        raise

    if not keep:
        await adapter.shutdown()

    return {
        "status": result.get("status"),
        "execution_id": result.get("execution_id"),
        "model_used": result.get("model_used"),
        "latency_ms": result.get("latency_ms"),
        "output": result.get("output"),
        "error": result.get("error"),
        "repos": list(repos),
    }


def _resolve_demo_pydantic_ai_model_config() -> tuple[Any, dict[str, str]]:
    """Return ``(ModelConfig, env_overrides)`` for the detected provider.

    Walks the same provider order as ``_resolve_demo_pydantic_ai_model``:
    local ``llama_server`` first (no key), then cloud providers in
    ``minimax → anthropic → openai`` order. Returns the env-var
    overrides the caller should set so pydantic-ai's SDK can find
    them (``OPENAI_API_KEY``/``OPENAI_BASE_URL`` for llama_server;
    cloud providers rely on whatever the user already exported).
    """
    from mahavishnu.adapters.ai.pydantic_ai_adapter import ModelConfig, PydanticAIAdapterError

    settings = _default_settings_getter()
    llama_url = getattr(settings, "llama_server_url", None) or "http://localhost:8081"
    try:
        resp = httpx.get(llama_url.rstrip("/") + "/v1/models", timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data") or []
            if models and isinstance(models, list):
                first = models[0]
                model_id = first.get("id") if isinstance(first, dict) else None
                if model_id:
                    return (
                        ModelConfig(
                            provider="llama_server",
                            model_name=model_id,
                            base_url=llama_url,
                        ),
                        # pydantic-ai's OpenAI provider reads these env
                        # vars directly; llama_server doesn't check the
                        # key but the SDK still requires it set.
                        {
                            "OPENAI_API_KEY": "no-auth",
                            "OPENAI_BASE_URL": llama_url.rstrip("/") + "/v1",
                        },
                    )
    except Exception as _exc:  # CLI entry point — llama_server probe failure is non-fatal, fall through to cloud providers  # noqa: BLE001, S110, RUF100
        pass

    if os.getenv("MINIMAX_API_KEY"):
        # minimax uses an OpenAI-compatible endpoint but pydantic-ai
        # doesn't have a first-class "minimax" provider, so route via
        # the OpenAI provider with a custom base_url.
        return (
            ModelConfig(
                provider="openai",
                model_name="MiniMax-M3",
                base_url="https://api.minimax.io/v1",
                api_key=os.getenv("MINIMAX_API_KEY"),
            ),
            {},
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        return (
            ModelConfig(
                provider="anthropic",
                model_name="claude-sonnet-4-5",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
            ),
            {},
        )
    if os.getenv("OPENAI_API_KEY"):
        return (
            ModelConfig(
                provider="openai",
                model_name="gpt-4o-mini",
                api_key=os.getenv("OPENAI_API_KEY"),
            ),
            {},
        )
    raise PydanticAIAdapterError(
        "No LLM provider available — set MINIMAX/ANTHROPIC/OPENAI_API_KEY or start llama_server",
    )


async def _best_effort_pydantic_ai_shutdown(adapter: Any) -> None:
    """Best-effort shutdown — called from the exception path."""
    try:
        await adapter.shutdown()
    except Exception as exc:  # CLI entry point — shutdown errors must never mask the original failure  # noqa: BLE001, RUF100
        typer.echo(f"[warning] adapter shutdown failed: {exc}", err=True)


@demo_app.command("pydantic_ai")
def demo_pydantic_ai(
    repos: list[str] = typer.Option(
        [],
        "--repos",
        help="Repos to pass to PydanticAIAdapter.execute. Defaults to the Mahavishnu repo itself.",
    ),
    prompt: str = typer.Option(
        "describe the project architecture in one paragraph",
        "--prompt",
        "-p",
        help="Prompt passed to the Pydantic-AI agent as task.prompt.",
    ),
    keep: bool = typer.Option(
        False,
        "--keep",
        help="Leave the adapter initialized after the demo (mainly for debugging).",
    ),
    timeout: int = typer.Option(
        600,
        "--timeout",
        help="Max seconds to wait for PydanticAIAdapter.execute. "
        "Local 8B Q4_K_M models on CPU need 2-5 min for first token.",
    ),
) -> None:
    """Run the Pydantic-AI engine end-to-end against the configured LLM.

    Constructs ``PydanticAIAdapter`` with a ``PydanticAISettings`` whose
    ``primary_model`` is built by ``_resolve_demo_pydantic_ai_model_config``
    (local llama_server preferred, then ``minimax → anthropic → openai``),
    calls ``adapter.execute(task, repos)``, prints the trimmed result,
    and shuts down. The SDK env vars pydantic-ai reads on its own
    (``OPENAI_API_KEY``/``OPENAI_BASE_URL`` for the local server) are
    set by the runner before the adapter initializes.
    """
    failures = _check_pydantic_ai_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    effective_repos: list[str] = list(repos) or [str(Path(__file__).resolve().parents[3])]
    # Resolve the model once for display (re-resolved inside the runner
    # to build the actual ModelConfig). Cheap, single HTTP probe.
    model_config_preview, _ = _resolve_demo_pydantic_ai_model_config()
    typer.echo(f"Model:    {model_config_preview.safe_string()}")
    typer.echo(f"Prompt:   {prompt}")
    typer.echo(f"Repos:    {effective_repos}")

    async def _run_with_timeout() -> dict[str, object]:
        return await _run_pydantic_ai_demo(
            repos=effective_repos,
            prompt=prompt,
            keep=keep,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(
            f"Timed out after {timeout}s waiting for PydanticAIAdapter.execute",
            err=True,
        )
        raise typer.Exit(code=2) from None

    typer.echo("\nPydantic-AI demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# crow terminal adapter demo (full implementation — replaces 2026-10-16 stub)
# ============================================================================


DEFAULT_CROW_DEMO_CMD = "echo '[ack] from mahavishnu demo crow' && pwd"
DEFAULT_CROW_ACK_CMD = "echo '[ack-2] crow-mcp PTY is alive'"
DEFAULT_CROW_PRECONDITION_TIMEOUT = 3.0


def _parse_sse_or_json(body: str) -> dict[str, object]:
    """Parse an MCP streamable-HTTP response into a JSON-RPC envelope.

    The streamable-HTTP transport returns SSE-formatted bodies
    (per the MCP 2025-03-26 spec)::

        event: message
        data: {"jsonrpc":"2.0","id":1,"result":{...}}

    Some servers may also respond with plain JSON. Accept either
    shape and return the first JSON ``data:`` payload found, or
    ``{}`` for an empty body (e.g. the 202 Accepted response from
    ``notifications/initialized``).
    """
    body = body.strip()
    if not body:
        return {}
    # Plain JSON shortcut (some MCP servers return it).
    if body.startswith("{"):
        import json as _json

        result = _json.loads(body)
        return result if isinstance(result, dict) else {"_": result}
    # SSE: events are separated by a blank line; collect ``data:``
    # lines from the first event with a JSON payload.
    import json as _json

    for event in body.split("\n\n"):
        data_lines: list[str] = []
        for line in event.splitlines():
            if line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :])
        if not data_lines:
            continue
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        try:
            parsed = _json.loads(payload)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


class _CrowMCPClient:
    """Minimal MCP client for crow-mcp's streamable-http transport.

    Implements the only method ``CrowTerminalAdapter`` calls:
    ``async call_tool(name, params)``. Returns the raw MCP
    ``CallToolResult`` envelope (a dict shaped like
    ``{"content": [{"type": "text", "text": "..."}], "isError": false}``)
    so the adapter's ``_extract_output`` helper sees exactly what the
    MCP SDK's ``CallToolResult`` would look like — no per-tool
    reshaping needed.

    The MCP streamable-HTTP transport requires an ``initialize``
    handshake first that establishes a ``Mcp-Session-Id`` header
    used on every subsequent request. Without it, crow-mcp returns
    ``-32600 Missing session ID`` (verified 2026-10-16). The
    handshake is two POSTs:

    1. ``initialize`` → server returns ``Mcp-Session-Id`` response
       header (and a 200 body with ``serverInfo``/``capabilities``).
    2. ``notifications/initialized`` → server returns 202 Accepted
       with empty body; we just need to wait for the status.

    A full MCP client (session lifecycle, notifications, capability
    negotiation, SSE streaming) is overkill for a demo that just
    runs one shell command per call.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._request_id = 0
        self._session_id: str | None = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Drive the MCP ``initialize`` handshake on first call."""
        if self._initialized:
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # 1. initialize request — server returns Mcp-Session-Id header.
            self._request_id += 1
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mahavishnu-demo", "version": "0.36.0"},
                },
            }
            init_resp = await client.post(
                self._base_url,
                json=init_payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            if init_resp.status_code != 200:
                raise RuntimeError(
                    f"crow-mcp initialize HTTP {init_resp.status_code}: {init_resp.text[:200]}"
                )
            # Header name is server-defined; case-insensitive lookup covers both.
            session_id = init_resp.headers.get("Mcp-Session-Id") or init_resp.headers.get(
                "mcp-session-id"
            )
            if not session_id:
                raise RuntimeError(
                    "crow-mcp did not return Mcp-Session-Id on initialize "
                    f"(headers: {dict(init_resp.headers)})"
                )
            self._session_id = session_id

            # 2. notifications/initialized — JSON-RPC notification (no id,
            # no response expected). Server returns 202 Accepted.
            self._request_id += 1
            notif_payload: dict[str, object] = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            notif_resp = await client.post(
                self._base_url,
                json=notif_payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": self._session_id,
                },
            )
            if notif_resp.status_code not in (200, 202):
                raise RuntimeError(
                    f"crow-mcp notifications/initialized HTTP "
                    f"{notif_resp.status_code}: {notif_resp.text[:200]}"
                )
        self._initialized = True

    async def call_tool(self, name: str, params: dict[str, object]) -> dict[str, object]:
        await self._ensure_initialized()
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": params},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": self._session_id or "",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._base_url, json=payload, headers=headers)
        # crow-mcp returns 200 for both success and tool errors; the
        # JSON-RPC ``error`` field carries the failure detail.
        if resp.status_code != 200:
            raise RuntimeError(f"crow-mcp HTTP {resp.status_code}: {resp.text[:200]}")
        body = _parse_sse_or_json(resp.text)
        if "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                raise RuntimeError(
                    f"crow-mcp JSON-RPC error {err.get('code')}: {err.get('message')}"
                )
            raise RuntimeError(f"crow-mcp JSON-RPC error {err}")
        # Return the raw ``result`` envelope (the MCP ``CallToolResult``
        # shape). The adapter's ``_extract_output`` reads ``content[0].text``
        # from this directly — no client-side reshaping needed.
        result = body.get("result")
        return result if isinstance(result, dict) else {}


def _check_crow_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    http_probe: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_CROW_PRECONDITION_TIMEOUT,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``settings.terminal.crow_enabled`` is True (the feature flag
      the manager dispatches on).
    - ``http://{crow_http_host}:{crow_http_port}/mcp`` is reachable.
      A 200/400/405/415 to a POST is acceptable — the path exists
      and the server is up; an MCP ``initialize`` handshake isn't
      required for reachability.
    - Settings are loadable.
    """
    settings_getter = settings_getter or _default_settings_getter
    http_probe = http_probe or httpx.post

    failures: list[str] = []
    try:
        settings = settings_getter()
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(f"could not load settings: {exc}")
        return failures

    try:
        terminal = settings.terminal  # type: ignore[attr-defined]
    except AttributeError as exc:
        failures.append(f"settings.terminal not configured: {exc}")
        return failures

    if not bool(getattr(terminal, "crow_enabled", False)):
        failures.append(
            "settings.terminal.crow_enabled is False (set MAHAVISHNU_TERMINAL__CROW_ENABLED=true)"
        )

    host = getattr(terminal, "crow_http_host", "localhost")
    port = int(getattr(terminal, "crow_http_port", 8693))
    use_tls = bool(getattr(terminal, "crow_use_tls", False))
    scheme = "https" if use_tls else "http"
    url = f"{scheme}://{host}:{port}/mcp"
    # POST to /mcp with the wrong content-type; any non-5xx confirms
    # the path exists. 400/415 are expected; 200/404/405 also fine.
    try:
        resp = http_probe(url, content=b"probe", timeout=timeout)
        if resp.status_code >= 500:
            failures.append(
                f"crow-mcp returned HTTP {resp.status_code} at {url} "
                "(is the server running? start with: "
                "`crow-mcp --transport streamable-http --host 127.0.0.1 "
                "--port 8693 &`)"
            )
    except Exception as exc:  # CLI entry point — HTTP probe failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(
            f"crow-mcp unreachable at {url}: {exc}. "
            "Start it with: `crow-mcp --transport streamable-http "
            "--host 127.0.0.1 --port 8693 &`"
        )

    return failures


async def _run_crow_demo(
    *,
    command: str,
    ack_command: str,
    keep: bool = False,
) -> dict[str, object]:
    """Drive the crow terminal adapter end-to-end against a live crow-mcp.

    Constructs a ``CrowTerminalAdapter`` directly with a minimal
    ``_CrowMCPClient`` (httpx-based JSON-RPC wrapper), launches one
    session running *command*, captures initial output, sends an ACK
    command, captures the post-ACK output, and (unless ``--keep``)
    closes the session. On the exception path the session is best-
    effort closed, mirroring the ``_run_tmux_demo`` reap-on-error
    pattern at ``_run_tmux_demo:174-178``.
    """
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    settings = _default_settings_getter()
    host = getattr(settings.terminal, "crow_http_host", "localhost")
    port = int(getattr(settings.terminal, "crow_http_port", 8693))
    use_tls = bool(getattr(settings.terminal, "crow_use_tls", False))
    scheme = "https" if use_tls else "http"
    url = f"{scheme}://{host}:{port}/mcp"
    timeout = float(getattr(settings.terminal, "crow_timeout_seconds", 10))

    mcp_client = _CrowMCPClient(base_url=url, timeout=timeout)
    adapter = CrowTerminalAdapter(mcp_client=mcp_client)

    session_id = await adapter.launch_session(command=command)
    session_ids = [session_id]
    try:
        typer.echo(f"\n[session {session_id}] launched with: {command!r}")
        initial = await adapter.capture_output(session_id)
        typer.echo(f"\n--- initial output ---\n{initial}")
        typer.echo(f"\n--- sending ACK: {ack_command!r} ---")
        await adapter.send_command(session_id, ack_command)
        post_ack = await adapter.capture_output(session_id)
        typer.echo(f"\n--- post-ACK output ---\n{post_ack}")
    except (
        Exception
    ):  # cleanup is best-effort on failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_crow_close(adapter, session_ids)
        raise

    if keep:
        typer.echo(
            f"\n--keep set: left session {session_id} running. "
            "Close manually or re-run without --keep."
        )
        return {
            "adapter": "crow",
            "endpoint": url,
            "session_id": session_id,
            "command": command,
            "ack_command": ack_command,
            "initial_output": initial,
            "post_ack_output": post_ack,
            "kept": True,
        }

    await adapter.close_session(session_id)
    return {
        "adapter": "crow",
        "endpoint": url,
        "session_id": session_id,
        "command": command,
        "ack_command": ack_command,
        "initial_output": initial,
        "post_ack_output": post_ack,
        "kept": False,
    }


async def _best_effort_crow_close(adapter: Any, session_ids: list[str]) -> None:
    """Best-effort session close — called from the exception path."""
    for sid in session_ids:
        try:
            await adapter.close_session(sid)
        except Exception as exc:  # CLI entry point — cleanup errors must never mask the original failure  # noqa: BLE001, RUF100
            typer.echo(f"[warning] crow close_session({sid}) failed: {exc}", err=True)


@demo_app.command("crow")
def demo_crow(
    cmd: str | None = typer.Option(
        None,
        "--cmd",
        "-c",
        help="Command to run inside the crow-mcp PTY session.",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave the crow-mcp session open after the demo."
    ),
    timeout: int = typer.Option(
        60, "--timeout", help="Max seconds for the whole crow demo (preconditions + run)."
    ),
) -> None:
    """Run the crow terminal adapter end-to-end against a live crow-mcp.

    Probes ``settings.terminal.crow_*`` for host/port, launches one
    session running ``--cmd`` (default ``echo + pwd``), captures
    output, sends an ACK, captures again, then closes the session
    (unless ``--keep``). Start crow-mcp first:

        crow-mcp --transport streamable-http --host 127.0.0.1 --port 8693 &

    Settings required: ``terminal.crow_enabled=true`` and
    ``terminal.crow_http_port=8693`` (the default).
    """
    failures = _check_crow_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    settings = _default_settings_getter()
    host = getattr(settings.terminal, "crow_http_host", "localhost")
    port = int(getattr(settings.terminal, "crow_http_port", 8693))
    use_tls = bool(getattr(settings.terminal, "crow_use_tls", False))
    scheme = "https" if use_tls else "http"
    url = f"{scheme}://{host}:{port}/mcp"
    typer.echo(f"crow-mcp endpoint: {url}")

    command = cmd if cmd is not None else DEFAULT_CROW_DEMO_CMD

    async def _run_with_timeout() -> dict[str, object]:
        return await _run_crow_demo(
            command=command,
            ack_command=DEFAULT_CROW_ACK_CMD,
            keep=keep,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s running the crow demo", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nCrow demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# hatchet demo (full implementation — replaces 2026-10-17 stub)
# ============================================================================


DEFAULT_HATCHET_PRECONDITION_TIMEOUT = 3.0


def _check_hatchet_preconditions(
    *,
    settings_getter: Callable[[], Any] | None = None,
    import_probe: Callable[[str], Any | None] | None = None,
    env_getter: Callable[[str], str | None] | None = None,
    timeout: float = DEFAULT_HATCHET_PRECONDITION_TIMEOUT,
) -> list[str]:
    """Return human-readable failures (empty list = pass).

    Probes (each injectable for tests):

    - ``hatchet_sdk`` importable (lives in the optional ``[hatchet]``
      group at pyproject.toml:203; pulled in transitively via the
      ``dev`` group).
    - ``settings.adapters.hatchet_enabled`` is True (the master
      switch at ``settings/mahavishnu.yaml:31``).
    - ``settings.hatchet`` exposed (top-level ``HatchetConfig`` field
      at ``core/config.py:3279``).
    - ``settings.hatchet.server_url`` is non-empty.
    - ``HATCHET_CLIENT_TOKEN`` env var set (the SDK raises
      ``RuntimeError`` at ``initialize()`` without it).
    - Settings are loadable (rejects malformed Oneiric config).
    """
    settings_getter = settings_getter or _default_settings_getter
    import_probe = import_probe or _default_import_probe
    env_getter = env_getter or os.getenv

    failures: list[str] = []
    if import_probe("hatchet_sdk") is None:
        failures.append(
            "hatchet-sdk not installed (.venv/bin/python -c 'import hatchet_sdk' "
            "fails; run 'uv sync --group hatchet' — pulled in transitively via dev)"
        )

    try:
        settings = settings_getter()
    except Exception as exc:  # CLI entry point — settings load failure surfaces as a precondition failure  # noqa: BLE001, RUF100
        failures.append(f"could not load settings: {exc}")
        return failures

    enabled = bool(getattr(getattr(settings, "adapters", None), "hatchet_enabled", False))
    if not enabled:
        failures.append(
            "settings.adapters.hatchet_enabled is False "
            "(set MAHAVISHNU_ADAPTERS__HATCHET_ENABLED=true)"
        )

    try:
        hatchet_cfg = settings.hatchet  # type: ignore[attr-defined]
    except AttributeError as exc:
        failures.append(f"settings.hatchet not configured: {exc}")
        return failures

    if not getattr(hatchet_cfg, "server_url", None):
        failures.append(
            "settings.hatchet.server_url is empty "
            "(set MAHAVISHNU_HATCHET__SERVER_URL, e.g. 'localhost:7077')"
        )

    if not env_getter("HATCHET_CLIENT_TOKEN"):
        failures.append(
            "HATCHET_CLIENT_TOKEN env var unset — the Hatchet SDK raises "
            "RuntimeError at initialize() without it"
        )

    return failures


async def _run_hatchet_demo(
    *,
    repos: Sequence[str],
    prompt: str,
    workflow_name: str,
    keep: bool = False,
) -> dict[str, object]:
    """Drive the Hatchet engine end-to-end against one or more repositories.

    Constructs ``HatchetAdapterImpl`` directly, calls
    ``adapter.initialize()`` (which validates ``HATCHET_CLIENT_TOKEN``
    and opens the gRPC channel), ``adapter.execute(task, repos)`` to
    dispatch the workflow run, prints the trimmed result, and calls
    ``adapter.cleanup()``. On the exception path ``adapter.cleanup()``
    is best-effort called before re-raising, mirroring the
    ``_run_tmux_demo`` reap-on-error pattern at ``_run_tmux_demo:174-178``.
    """
    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    settings = _default_settings_getter()
    task = {
        "id": f"demo-hatchet-{int(time.time())}",
        "prompt": prompt,
        "workflow_name": workflow_name,
    }

    adapter = HatchetAdapterImpl(config=settings.hatchet)
    try:
        await adapter.initialize()
    except Exception:  # cleanup is best-effort on init failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_hatchet_cleanup(adapter)
        raise

    try:
        result = await adapter.execute(task=task, repos=list(repos))
    except Exception:  # cleanup is best-effort on execute failure — never mask the original error  # noqa: BLE001, RUF100
        await _best_effort_hatchet_cleanup(adapter)
        raise

    if not keep:
        await adapter.cleanup()

    return {
        "status": result.get("status"),
        "adapter": result.get("adapter"),
        "workflow": result.get("workflow"),
        "run_id": result.get("run_id"),
        "output": result.get("output"),
        "error": result.get("error"),
        "repos": list(repos),
    }


async def _best_effort_hatchet_cleanup(adapter: Any) -> None:
    """Best-effort cleanup — called from the exception path."""
    try:
        await adapter.cleanup()
    except Exception as exc:  # CLI entry point — cleanup errors must never mask the original failure  # noqa: BLE001, RUF100
        typer.echo(f"[warning] adapter cleanup failed: {exc}", err=True)


@demo_app.command("hatchet")
def demo_hatchet(
    repos: list[str] = typer.Option(
        [],
        "--repos",
        help="Repos to pass to HatchetAdapterImpl.execute. Defaults to the Mahavishnu repo itself.",
    ),
    prompt: str = typer.Option(
        "describe the project architecture in one paragraph",
        "--prompt",
        "-p",
        help="Prompt passed as the workflow input (Hatchet workflow 'input.prompt').",
    ),
    workflow_name: str = typer.Option(
        "agent-loop",
        "--workflow-name",
        "-w",
        help="Hatchet workflow to dispatch (default 'agent-loop').",
    ),
    keep: bool = typer.Option(
        False,
        "--keep",
        help="Leave the HatchetAdapter initialized after the demo (mainly for debugging).",
    ),
    timeout: int = typer.Option(
        180,
        "--timeout",
        help="Max seconds to wait for HatchetAdapterImpl.execute.",
    ),
) -> None:
    """Run the Hatchet engine end-to-end against the live Hatchet server.

    Constructs ``HatchetAdapterImpl`` directly, calls
    ``adapter.initialize()`` (validates ``HATCHET_CLIENT_TOKEN`` and
    opens the gRPC channel) → ``adapter.execute(task, repos)`` to
    dispatch the workflow run, prints the trimmed result, and
    cleans up. The server URL, namespace, and per-task timeout come
    from ``settings.hatchet`` (top-level ``HatchetConfig`` field at
    ``core/config.py:3279``); the master switch is
    ``adapters.hatchet_enabled``. Hatchet is the alternative durable-
    flow engine surfaced via the
    ``engine:durable-flow-alternative`` capability in
    ``HatchetAdapterImpl.provides``.
    """
    failures = _check_hatchet_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    settings = _default_settings_getter()
    effective_repos: list[str] = list(repos) or [str(Path(__file__).resolve().parents[3])]
    typer.echo(f"Hatchet server: {settings.hatchet.server_url}")
    typer.echo(f"Namespace:     {settings.hatchet.namespace}")
    typer.echo(f"Workflow:      {workflow_name}")
    typer.echo(f"Prompt:        {prompt}")
    typer.echo(f"Repos:         {effective_repos}")

    async def _run_with_timeout() -> dict[str, object]:
        return await _run_hatchet_demo(
            repos=effective_repos,
            prompt=prompt,
            workflow_name=workflow_name,
            keep=keep,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run_with_timeout(), timeout=timeout))
    except TimeoutError:
        typer.echo(
            f"Timed out after {timeout}s waiting for HatchetAdapterImpl.execute",
            err=True,
        )
        raise typer.Exit(code=2) from None

    typer.echo("\nHatchet demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# Pool demos (PR #2 — live implementations of all 4 pool types)
# ============================================================================
#
# Each sub-command drives one ``BasePool`` subclass end-to-end: build a
# ``PoolConfig``, call ``start()``, dispatch a single task via
# ``execute_task()``, optionally ``stop()`` (honors ``--keep``). The
# preconditions function is the CLI-friendly surface for "is this
# substrate even reachable from my shell?" — empty list = pass.
#
# Anti-revert pattern (sibling of the engine demos above): the stub
# registration loop at the bottom of this file MUST NOT include any
# of these names. ``tests/unit/cli/test_cli_wireup_invariants.py`` pins
# the live-implementation property for each one.


DEFAULT_POOL_DEMO_COMMAND = "echo hello from {pool_type} pool"
DEFAULT_SESSION_BUDDY_URL = "http://localhost:8678/mcp"
DEFAULT_RUNPOD_PROBE_TIMEOUT_S = 5.0
DEFAULT_PI_RUNTIME_PROBE_TIMEOUT_S = 5.0


# ----------------------------------------------------------------------------
# pool-mahavishnu — in-process WorkerManager + tmux substrate
# ----------------------------------------------------------------------------


def _check_pool_mahavishnu_preconditions(
    *,
    pool_name: str = "demo-mahavishnu",
    tmux_which: Callable[[str], str | None] | None = None,
    claude_which: Callable[[str], str | None] | None = None,
    exists: Callable[[Path], bool] | None = None,
    home: Path | None = None,
    require_claude: bool = True,
) -> list[str]:
    """Check that tmux is installed (and claude by default).

    Also checks the Shepherd workspace at the pool's resolved writable
    root (per ``_expected_shepherd_workspace_path``). Without an
    initialized workspace (``<workspace>/.vcscore``), ``pool.start()``
    fails fail-closed with ``MHV-312`` — we surface that here so the
    operator gets a clear "run sp init first" message instead of a
    traceback.

    Probes (all injectable for tests):

    - ``tmux`` / ``claude`` binaries on PATH.
    - Shepherd workspace marker via the ``exists`` callable.
    - Home directory via the ``home`` ``Path`` (so tests don't depend
      on ``Path.home()`` returning the real home).
    """
    tmux_lookup = tmux_which or shutil.which
    claude_lookup = claude_which or shutil.which
    failures: list[str] = []
    if not tmux_lookup("tmux"):
        failures.append("tmux binary not on PATH")
    if require_claude and not claude_lookup("claude"):
        failures.append(
            "claude binary not on PATH (required for default worker; "
            "the pool itself is fine — the demo's default task uses claude)"
        )
    workspace = _expected_shepherd_workspace_path(pool_name, home=home)
    failures.extend(_check_shepherd_workspace(workspace, exists=exists))
    return failures


async def _run_pool_mahavishnu_demo(
    *,
    pool_name: str,
    min_workers: int,
    max_workers: int,
    command: str,
    keep: bool,
) -> dict[str, object]:
    """Drive ``MahavishnuPool`` end-to-end: start, dispatch, reap (unless ``--keep``).

    The dispatch carries a ``command``, not a ``prompt``. ``shepherd_backend``
    accepts exactly one of ``task_ref`` or ``command`` and rejects a task with
    neither; a ``prompt`` is the only bodyless form the legacy WorkerManager
    understood, and it no longer has a backend. The command is validated and
    sanitised by the backend's exec guard before it runs, so it must be a
    shell command the workspace is willing to execute.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
    from mahavishnu.terminal.adapters import _build_tmux_adapter
    from mahavishnu.terminal.manager import TerminalManager

    config = PoolConfig(
        name=pool_name,
        pool_type="mahavishnu",
        min_workers=min_workers,
        max_workers=max_workers,
    )
    pool = MahavishnuPool(
        config=config,
        terminal_manager=TerminalManager(adapter=_build_tmux_adapter()),
    )
    pool_id = await pool.start()
    try:
        result = await pool.execute_task({"command": command})
    finally:
        if not keep:
            await pool.stop()
    return {
        "pool_id": pool_id,
        "pool_type": "mahavishnu",
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


def _truncate(value: object, *, max_chars: int) -> object:
    """Return ``value`` unchanged unless it is a string over ``max_chars``.

    Pools can return large output blobs (vision, embeddings); the demo
    only needs enough context to confirm the substrate fired.
    """
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"… (+{len(value) - max_chars} chars)"
    return value


def _expected_shepherd_workspace_path(
    pool_name: str,
    *,
    home: Path | None = None,
) -> Path:
    """Return the Shepherd workspace path MahavishnuPool will spawn into.

    Mirrors the first-priority candidate in
    ``mahavishnu.pools.mahavishnu_pool.MahavishnuPool.__init__`` (the
    candidates list prefers ``~/.local/state/mahavishnu/worktrees/<pool_name>/workspace``
    before the XDG-data and /tmp fallbacks). The demo doesn't set a
    custom ``writable_root`` on its ``PoolConfig``, so this is the
    path the pool will try first — and the one whose Shepherd init
    state the precondition should check.

    Raises ``ValueError`` if ``pool_name`` contains path separators
    or ``..`` segments: the operator-facing demos accept the name via
    ``--name`` (a free-form Typer option), and a name like
    ``"../../tmp/evil"`` would resolve the precondition's gate to a
    different location than the pool's runtime ``Path.resolve()`` call
    (``sibling-path-gate-parity``). Rejecting here keeps gate and
    runtime on the same path.
    """
    if not pool_name or pool_name != pool_name.strip():
        raise ValueError(f"invalid pool_name {pool_name!r}: must be non-empty and stripped")
    if ".." in Path(pool_name).parts or Path(pool_name).is_absolute():
        raise ValueError(f"invalid pool_name {pool_name!r}: must not contain '..' or be absolute")
    if any(sep in pool_name for sep in (os.sep, "/", "\\")):
        raise ValueError(f"invalid pool_name {pool_name!r}: must not contain path separators")
    base = home or Path.home()
    return base / ".local" / "state" / "mahavishnu" / "worktrees" / pool_name / "workspace"


def _check_shepherd_workspace(
    workspace: Path,
    *,
    exists: Callable[[Path], bool] | None = None,
) -> list[str]:
    """Return ``[failure]`` if the Shepherd workspace isn't initialized; ``[]`` if ready.

    A Shepherd workspace is ready when ``<workspace>/.vcscore`` exists.
    Per ``shepherd_dialect.workspace_control.workspace.discover`` (line 843
    of the upstream ``workspace.py``), the missing-marker path raises
    ``WorkspaceControlError("not a Shepherd workspace. Run `sp init` first.")``,
    which surfaces as ``MHV-312`` at the pool's ``start()`` call.

    **Gate/runtime parity**: the probe resolves ``workspace`` the same
    way ``MahavishnuPool.__init__`` does (``Path.resolve()``), so a
    path containing symlinks or ``..`` segments is checked at the
    *same* location the pool will spawn into — without this, a
    literal-path gate can disagree with the resolved path the pool
    actually uses, and the precondition would either false-positive
    (warn when the real workspace IS ready) or false-negative
    (pass when it isn't). The ``exists`` probe is injectable for
    tests; the resolution step always uses the real ``Path.resolve``.
    """
    resolved = workspace.resolve()
    exists_check = exists or Path.exists
    marker = resolved / ".vcscore"
    if not exists_check(marker):
        message = (
            f"Shepherd workspace not initialized at {resolved} "
            f"(missing .vcscore marker). Run `sp init {resolved}` to "
            f"initialize it before invoking this demo."
        )
        return [message]
    return []


@demo_app.command("pool-mahavishnu")
def demo_pool_mahavishnu(
    pool_name: str = typer.Option(
        "demo-mahavishnu",
        "--name",
        help="Pool name (informational; used in the pool_id).",
    ),
    min_workers: int = typer.Option(1, "--min", min=1, help="Minimum workers."),
    max_workers: int = typer.Option(2, "--max", min=1, help="Maximum workers."),
    command: str = typer.Option(
        DEFAULT_POOL_DEMO_COMMAND.format(pool_type="mahavishnu"),
        "--command",
        help="Shell command run by one MahavishnuPool worker.",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave the pool running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(60, "--timeout", help="Max seconds for start + execute + stop."),
) -> None:
    """Run the in-process MahavishnuPool (WorkerManager + tmux) end-to-end.

    Exercises the local substrate: spawns a ``PoolConfig(pool_type=
    "mahavishnu", min_workers, max_workers)``, dispatches one command, and
    reaps on success. Use ``--keep`` to leave the pool up for follow-up
    ``mahavishnu pool execute`` calls.

    The dispatched task is a ``command``, not a prompt: ``shepherd_backend``
    requires exactly one of ``task_ref`` or ``command`` and has no backend
    for a free-form prompt.
    """
    failures = _check_pool_mahavishnu_preconditions(pool_name=pool_name)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Pool: {pool_name} (type=mahavishnu, {min_workers}..{max_workers} workers)")
    typer.echo(f"Command: {command}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_pool_mahavishnu_demo(
                    pool_name=pool_name,
                    min_workers=min_workers,
                    max_workers=max_workers,
                    command=command,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nMahavishnuPool demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# pool-session-buddy — MCP-delegated substrate
# ----------------------------------------------------------------------------


def _check_pool_session_buddy_preconditions(
    *,
    url: str,
    http_probe: Callable[[str, float], bool] | None = None,
    probe_timeout_s: float = DEFAULT_RUNPOD_PROBE_TIMEOUT_S,
) -> list[str]:
    """Verify the Session-Buddy MCP server is reachable at ``url``.

    Probes with a short-timeout HTTP GET on the MCP endpoint. A bare
    TCP-connect is insufficient — many Session-Buddy installs accept
    the TCP handshake but 5xx the first MCP frame.
    """
    probe = http_probe or _default_http_probe
    failures: list[str] = []
    if not url:
        failures.append(
            "Session-Buddy URL is empty (pass --url or set MAHAVISHNU_SESSION_BUDDY__POOL_URL)"
        )
        return failures
    if not url.startswith(("http://", "https://")):
        failures.append(f"Session-Buddy URL must be http(s); got {url!r}")
        return failures
    if not probe(url, probe_timeout_s):
        failures.append(
            f"Session-Buddy MCP server not reachable at {url} within {probe_timeout_s}s. "
            f"Start it with `mahavishnu mcp start --adapter session-buddy` or "
            f"`uv run session-buddy`."
        )
    return failures


def _default_http_probe(url: str, timeout_s: float) -> bool:
    """HEAD-equivalent GET probe with a tight timeout (synchronous)."""
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(url, headers={"Accept": "text/event-stream"})
        return response.status_code < 500
    except Exception:  # CLI entry point — probe failures must yield a precondition failure, not crash the demo  # CLI entry point — broad catch is the documented contract  # noqa: BLE001, RUF100
        return False


async def _run_pool_session_buddy_demo(
    *,
    pool_name: str,
    url: str,
    prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Drive ``SessionBuddyPool`` end-to-end against the live MCP server."""
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

    config = PoolConfig(
        name=pool_name,
        pool_type="session-buddy",
        # Session-Buddy manages a fixed 3 workers; the config min/max
        # are advisory. Pass ``session_buddy_url=url`` to the pool ctor.
    )
    pool = SessionBuddyPool(config=config, session_buddy_url=url)
    pool_id = await pool.start()
    try:
        result = await pool.execute_task({"prompt": prompt})
    finally:
        if not keep:
            await pool.stop()
    return {
        "pool_id": pool_id,
        "pool_type": "session-buddy",
        "session_buddy_url": url,
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


@demo_app.command("pool-session-buddy")
def demo_pool_session_buddy(
    pool_name: str = typer.Option(
        "demo-session-buddy",
        "--name",
        help="Pool name (informational; used in the pool_id).",
    ),
    url: str = typer.Option(
        DEFAULT_SESSION_BUDDY_URL,
        "--url",
        "-u",
        help="Session-Buddy MCP server URL (defaults to http://localhost:8678/mcp).",
    ),
    prompt: str = typer.Option(
        DEFAULT_POOL_DEMO_COMMAND.format(pool_type="session-buddy"),
        "--prompt",
        "-p",
        help="Prompt dispatched to one Session-Buddy worker.",
    ),
    keep: bool = typer.Option(False, "--keep", help="Leave the pool running after the demo."),
    timeout: int = typer.Option(
        60, "--timeout", help="Max seconds for probe + start + execute + stop."
    ),
    probe_timeout_s: float = typer.Option(
        DEFAULT_RUNPOD_PROBE_TIMEOUT_S,
        "--probe-timeout",
        help="Seconds to wait on the Session-Buddy HTTP probe.",
    ),
) -> None:
    """Run the Session-Buddy delegated pool end-to-end against the live MCP server.

    The SessionBuddyPool owns 3 workers per server (fixed by the upstream
    substrate); the demo confirms the MCP round-trip works. Pass
    ``--keep`` to leave the pool up — useful for follow-up
    ``mahavishnu pool execute pool_<id>`` calls.
    """
    failures = _check_pool_session_buddy_preconditions(url=url, probe_timeout_s=probe_timeout_s)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Pool: {pool_name} (type=session-buddy, server={url})")
    typer.echo(f"Prompt: {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_pool_session_buddy_demo(
                    pool_name=pool_name,
                    url=url,
                    prompt=prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nSessionBuddyPool demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# pool-runpod — runpod SDK 2.0 serverless client (post-migration substrate)
# ----------------------------------------------------------------------------


def _check_pool_runpod_preconditions(
    *,
    endpoint_id: str,
    env_getter: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Verify ``RUNPOD_API_KEY`` is set and ``endpoint_id`` is non-empty.

    SDK 2.0 reads ``RUNPOD_API_KEY`` natively (per the post-2026-10-17
    migration — see ``docs/decisions/2026-10-17-runpod-flash-to-sdk-2.md``).
    The legacy ``api_key`` config field is no longer required; the
    endpoint_id IS required (points at a pre-configured serverless
    endpoint — handler logic lives in the RunPod console, not here).
    """
    env_getter = env_getter or os.getenv
    failures: list[str] = []
    if not env_getter("RUNPOD_API_KEY"):
        failures.append(
            "RUNPOD_API_KEY env var is unset. Set it in your shell "
            "(export RUNPOD_API_KEY=...) before invoking this demo."
        )
    if not endpoint_id:
        failures.append(
            "RunPod endpoint_id is empty. Pass --endpoint-id <id> or set "
            "RUNPOD_ENDPOINT_ID in the environment."
        )
    return failures


async def _run_pool_runpod_demo(
    *,
    pool_name: str,
    endpoint_id: str,
    prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Drive ``RunPodPool`` end-to-end against the named serverless endpoint.

    Uses the SDK 2.0 thin client (``runpod.Endpoint(id)``) — no worker
    registration, no decorator. Pool's ``execute_task`` wraps
    ``endpoint.run(payload) → req.output()`` in ``asyncio.to_thread``,
    so the orchestrator's event loop stays unblocked during the
    30-60s cold start and 2-3s warm call.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.runpod_pool import RunPodPool

    config = PoolConfig(
        name=pool_name,
        pool_type="runpod",
        extra_config={"endpoint_id": endpoint_id},
    )
    pool = RunPodPool(config=config)
    pool_id = await pool.start()
    try:
        result = await pool.execute_task({"prompt": prompt})
    finally:
        if not keep:
            await pool.stop()
    return {
        "pool_id": pool_id,
        "pool_type": "runpod",
        "endpoint_id": endpoint_id,
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


# ----------------------------------------------------------------------------
# pool-runpod-public — RunPod Public Endpoints REST substrate
# ----------------------------------------------------------------------------


def _check_pool_runpod_public_preconditions(
    *,
    endpoint_id: str,
    env_getter: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Verify ``RUNPOD_API_KEY`` is set and ``endpoint_id`` is a non-empty id.

    Sister to ``_check_pool_runpod_preconditions`` but points at a
    Public Endpoint id (``moonshot-kimi``, ``granite-4-0-h-small``,
    etc.) rather than an operator-deployed serverless endpoint.
    Auth is the same (``RUNPOD_API_KEY``). The body shape varies per
    public endpoint — moonshot-kimi expects ``messages``, granite-4-
    0-h-small expects ``prompt`` — so the demo passes the payload
    through verbatim and the operator picks the right key for the
    target endpoint.
    """
    env_getter = env_getter or os.getenv
    failures: list[str] = []
    if not env_getter("RUNPOD_API_KEY"):
        failures.append(
            "RUNPOD_API_KEY env var is unset. Set it in your shell "
            "(export RUNPOD_API_KEY=...) before invoking this demo."
        )
    if not endpoint_id:
        failures.append(
            "RunPod public endpoint_id is empty. Pass --endpoint-id <id> or set "
            "RUNPOD_PUBLIC_ENDPOINT_ID in the environment."
        )
    return failures


async def _run_pool_runpod_public_demo(
    *,
    pool_name: str,
    endpoint_id: str,
    prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Drive ``RunPodPublicEndpointPool`` end-to-end against the public endpoint.

    Wraps POST ``/v2/{endpoint_id}/runsync`` with ``{"input": payload}``
    in ``asyncio.to_thread`` so the orchestrator's event loop stays
    unblocked. The handler contract is endpoint-specific; the demo
    passes the prompt through as the ``prompt`` field by default but
    accepts any nested shape via the same input dict.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.runpod_public_pool import RunPodPublicEndpointPool

    config = PoolConfig(
        name=pool_name,
        pool_type="runpod_public",
        extra_config={"endpoint_id": endpoint_id},
    )
    pool = RunPodPublicEndpointPool(config=config)
    pool_id = await pool.start()
    try:
        result = await pool.execute_task({"prompt": prompt})
    finally:
        if not keep:
            await pool.stop()
    return {
        "pool_id": pool_id,
        "pool_type": "runpod_public",
        "endpoint_id": endpoint_id,
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


@demo_app.command("pool-runpod-public")
def demo_pool_runpod_public(
    pool_name: str = typer.Option(
        "demo-runpod-public",
        "--name",
        help="Pool name (informational; used in the pool_id).",
    ),
    endpoint_id: str = typer.Option(
        os.getenv("RUNPOD_PUBLIC_ENDPOINT_ID", ""),
        "--endpoint-id",
        "-e",
        help="RunPod Public Endpoint id (e.g. moonshot-kimi, granite-4-0-h-small; "
        "or set RUNPOD_PUBLIC_ENDPOINT_ID).",
    ),
    prompt: str = typer.Option(
        DEFAULT_POOL_DEMO_COMMAND.format(pool_type="runpod_public"),
        "--prompt",
        "-p",
        help="Prompt dispatched to the public endpoint.",
    ),
    keep: bool = typer.Option(False, "--keep", help="Leave the pool running after the demo."),
    timeout: int = typer.Option(
        120,
        "--timeout",
        help="Max seconds for start + execute + stop. Public endpoints "
        "cold-start on first call (typically 1-5s).",
    ),
) -> None:
    """Run the RunPodPublicEndpointPool end-to-end against a Public Endpoint.

    Sister substrate to ``pool-runpod``: this demo exercises the REST
    surface (``POST /v2/{id}/runsync``) instead of the ``runpod`` SDK.
    Suitable for first-party public endpoints whose handler contract
    does not match the SDK body shape (Moonshot Kimi, IBM Granite,
    etc.).
    """
    failures = _check_pool_runpod_public_preconditions(endpoint_id=endpoint_id)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Pool: {pool_name} (type=runpod_public, endpoint_id={endpoint_id})")
    typer.echo(f"Prompt: {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_pool_runpod_public_demo(
                    pool_name=pool_name,
                    endpoint_id=endpoint_id,
                    prompt=prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nRunPodPublicEndpointPool demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


@demo_app.command("pool-runpod")
def demo_pool_runpod(
    pool_name: str = typer.Option(
        "demo-runpod",
        "--name",
        help="Pool name (informational; used in the pool_id).",
    ),
    endpoint_id: str = typer.Option(
        os.getenv("RUNPOD_ENDPOINT_ID", ""),
        "--endpoint-id",
        "-e",
        help="RunPod serverless endpoint id (or set RUNPOD_ENDPOINT_ID).",
    ),
    prompt: str = typer.Option(
        DEFAULT_POOL_DEMO_COMMAND.format(pool_type="runpod"),
        "--prompt",
        "-p",
        help="Prompt dispatched to the RunPod serverless endpoint.",
    ),
    keep: bool = typer.Option(False, "--keep", help="Leave the pool running after the demo."),
    timeout: int = typer.Option(
        120,
        "--timeout",
        help="Max seconds for start + execute + stop. Cold start can be 30-60s.",
    ),
) -> None:
    """Run the RunPodPool (SDK 2.0) end-to-end against a serverless endpoint.

    The endpoint is operator-managed (RunPod console or
    ``runpod.serverless.start({...})`` in a dedicated handler repo).
    This demo verifies the client-side substrate — that
    ``runpod.Endpoint(id).run(payload)`` round-trips and the pool's
    ``execute_task`` correctly surfaces the terminal state.
    """
    failures = _check_pool_runpod_preconditions(endpoint_id=endpoint_id)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        typer.echo(
            "\nHint: see docs/decisions/2026-10-17-runpod-flash-to-sdk-2.md "
            "for the migration context.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Pool: {pool_name} (type=runpod, endpoint_id={endpoint_id})")
    typer.echo(f"Prompt: {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_pool_runpod_demo(
                    pool_name=pool_name,
                    endpoint_id=endpoint_id,
                    prompt=prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s (cold start can be 30-60s)", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nRunPodPool demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# pool-pi — single npx @earendil-works/pi-coding-agent subprocess
# ----------------------------------------------------------------------------


def _check_pool_pi_preconditions(
    *,
    npx_which: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Check that ``npx`` is on PATH and at least one LLM credential is set.

    The pi-coding-agent subprocess inherits the operator's
    LLM credentials via the PiPool's ``env_allowlist`` (see
    ``mahavishnu/pools/pi_pool.py``). The allowlist is opt-in: if
    the operator hasn't exported an LLM credential, the subprocess
    starts but every prompt returns an upstream auth error.

    We fail fast here with a clear operator-setup hint, including
    the Bifrost path (the post-bifrost-plan canonical upstream).
    """
    which = npx_which or shutil.which
    failures: list[str] = []
    if not which("npx"):
        failures.append(
            "npx binary not on PATH (PiPool spawns npx @earendil-works/pi-coding-agent). "
            "Install Node.js 18+ and ensure npx is reachable."
        )

    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not (has_openai or has_anthropic):
        bifrost_hint = (
            "  Tip: to route through the local Bifrost gateway, also export:\n"
            "    export OPENAI_BASE_URL=http://127.0.0.1:8471/v1\n"
            "  (oneiric 0.32.1's default URL; the gateway serves the\n"
            "  OpenAI-compatible endpoint at /v1/chat/completions.)\n"
            "  See docs/llm-routing.md for the full setup."
        )
        failures.append(
            "no LLM credentials exported — the pi-coding-agent subprocess "
            "inherits the parent's env but needs an LLM upstream to generate text. "
            "Export at least one of:\n"
            "  export OPENAI_API_KEY=...      # any OpenAI-compatible key\n"
            "  export ANTHROPIC_API_KEY=...   # for Anthropic\n" + bifrost_hint
        )

    return failures


async def _run_pool_pi_demo(
    *,
    pool_name: str,
    prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Drive ``PiPool`` end-to-end against the per-task pi-coding-agent CLI.

    PiPool has a fixed worker count of 1 (``scale(n>1)`` raises). The
    demo runs a one-shot ``npx @earendil-works/pi-coding-agent <prompt>``
    invocation per task, captures stdout, and reaps.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.pi_pool import PiPool

    config = PoolConfig(
        name=pool_name,
        pool_type="pi",
        min_workers=1,
        max_workers=1,  # PiPool rejects max_workers > 1 at construction
    )
    pool = PiPool(config=config)
    pool_id = await pool.start()
    try:
        result = await pool.execute_task({"prompt": prompt})
    finally:
        if not keep:
            await pool.stop()
    return {
        "pool_id": pool_id,
        "pool_type": "pi",
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


@demo_app.command("pool-pi")
def demo_pool_pi(
    pool_name: str = typer.Option(
        "demo-pi",
        "--name",
        help="Pool name (informational; used in the pool_id).",
    ),
    prompt: str = typer.Option(
        DEFAULT_POOL_DEMO_COMMAND.format(pool_type="pi"),
        "--prompt",
        "-p",
        help="Prompt dispatched to a fresh pi-coding-agent subprocess.",
    ),
    keep: bool = typer.Option(False, "--keep", help="Leave the pool running after the demo."),
    timeout: int = typer.Option(60, "--timeout", help="Max seconds for start + execute + stop."),
) -> None:
    """Run the PiPool end-to-end (one-shot npx pi-coding-agent CLI).

    The Pi substrate is model-agnostic — the prompt is forwarded to the
    configured upstream (Bifrost routing). For multi-process capacity,
    spawn additional PiPool instances (PiPool has a fixed worker count
    of 1 per pool).
    """
    failures = _check_pool_pi_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Pool: {pool_name} (type=pi, single subprocess)")
    typer.echo(f"Prompt: {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_pool_pi_demo(
                    pool_name=pool_name,
                    prompt=prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nPiPool demo result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# Workflow demos (PR #3 — cross-substrate compositions of pools, workers,
# and terminal adapters)
# ============================================================================
#
# Each demo exercises a different *combination* of substrates — unlike the
# single-substrate demos above, these narrate the handoff between two or
# more components. Three flavors, one demo each:
#
# 1. ``workflow-pool-worker-terminal``  (Operator E2E) — pool + worker +
#    terminal adapter triple. Narrative output with stage labels.
# 2. ``workflow-multi-pool-handoff``     (CI smoke)     — two pools in
#    sequence (source -> target). Compact ✓/✗ per stage, fast (<10s).
# 3. ``workflow-adapter-swap``           (Doc reference) — same task run
#    through two terminal adapters back-to-back. Verbose, side-by-side.
#
# Anti-revert pattern (sibling of the pool demos above): the stub
# registration loop at the bottom of this file MUST NOT include any
# of these names. ``tests/unit/cli/test_cli_wireup_invariants.py`` pins
# the live-implementation property for each one via unique flags in
# ``--help``.


DEFAULT_WORKFLOW_DEMO_PROMPT = "echo hello from workflow demo ({stage})"
DEFAULT_WORKFLOW_ADAPTER = "tmux"
DEFAULT_WORKFLOW_ADAPTER_B = "mock"
DEFAULT_WORKFLOW_SOURCE_POOL = "session-buddy"
DEFAULT_WORKFLOW_TARGET_POOL = "mahavishnu"


def _emit_workflow_stage(stage: int, total: int, message: str) -> None:
    """Print a single ``[stage N/M] message`` line to stdout.

    Used by the workflow demos to narrate each handoff. Goes to stdout
    (not stderr) so it appears interleaved with the eventual JSON result
    for operator E2E demos.
    """
    typer.echo(f"[stage {stage}/{total}] {message}")


def _build_terminal_adapter(name: str) -> Any:
    """Construct a TerminalAdapter by registered name.

    Supports ``mock`` and ``tmux`` for direct construction. ``crow`` is
    intentionally NOT supported here because the crow adapter needs an
    MCP client that only ``TerminalManager.create`` knows how to build
    (with config + crow_enabled flag + crow_http_endpoint); the demo
    surface is too thin to pass that through cleanly. Operators who
    want crow should use the standalone ``mahavishnu demo crow`` command.
    """
    from mahavishnu.terminal.adapters import _build_mock_adapter, _build_tmux_adapter

    if name == "mock":
        return _build_mock_adapter()
    if name == "tmux":
        return _build_tmux_adapter()
    raise ValueError(
        f"unsupported terminal adapter for workflow demo: {name!r}. "
        f"Supported: 'mock', 'tmux'. For crow, use `mahavishnu demo crow`."
    )


# ----------------------------------------------------------------------------
# workflow-pool-worker-terminal — Operator E2E triple composition
# ----------------------------------------------------------------------------


def _check_workflow_pool_worker_terminal_preconditions(
    *,
    adapter: str,
    pool_name: str = "demo-workflow-pwt",
    tmux_which: Callable[[str], str | None] | None = None,
    exists: Callable[[Path], bool] | None = None,
    home: Path | None = None,
) -> list[str]:
    """Verify the pool substrate and terminal adapter are present.

    Probes (injectable for tests):

    - ``adapter == 'tmux'`` requires the tmux binary on PATH.
    - ``adapter == 'mock'`` has no shell-binary prereq (always passes).
    - Shepherd workspace marker at the pool's resolved writable root
      (per ``_expected_shepherd_workspace_path``); without an
      initialized ``<workspace>/.vcscore``, ``pool.start()`` fails
      fail-closed with ``MHV-312`` — surfaced here so the operator
      sees a clear "run sp init first" message instead of a traceback.
    """
    tmux_lookup = tmux_which or shutil.which
    failures: list[str] = []
    if adapter not in ("mock", "tmux"):
        failures.append(f"unsupported adapter: {adapter!r}. Supported: 'mock', 'tmux'.")
    if adapter == "tmux" and not tmux_lookup("tmux"):
        failures.append("tmux binary not on PATH (required for the tmux terminal adapter)")
    workspace = _expected_shepherd_workspace_path(pool_name, home=home)
    failures.extend(_check_shepherd_workspace(workspace, exists=exists))
    return failures


async def _run_workflow_pool_worker_terminal_demo(
    *,
    prompt: str,
    adapter: str,
    keep: bool,
) -> dict[str, object]:
    """Drive pool + worker + terminal adapter end-to-end (3 stages).

    Composition:

    - MahavishnuPool wraps a WorkerManager (the 'worker' substrate).
    - WorkerManager attaches to a TerminalAdapter (the 'terminal' substrate).
    - The pool is the orchestrator that holds both.

    The demo narrates each handoff as a stage so an operator can see the
    pool -> worker -> terminal fan-out in a single trace.
    """
    # NOTE: ``MahavishnuPool`` is NOT in ``mahavishnu.pools``'s lazy
    # importer table (only ``RunPodPool`` is re-exported). Import from
    # the concrete module to avoid an ImportError at runtime.
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
    from mahavishnu.terminal.manager import TerminalManager

    total_stages = 3
    _emit_workflow_stage(1, total_stages, f"initializing pool + {adapter} terminal adapter")
    pool_config = PoolConfig(
        name="demo-workflow-pwt",
        pool_type="mahavishnu",
        min_workers=1,
        max_workers=1,
    )
    terminal_adapter = _build_terminal_adapter(adapter)
    terminal_manager = TerminalManager(adapter=terminal_adapter)
    pool = MahavishnuPool(config=pool_config, terminal_manager=terminal_manager)
    pool_id = await pool.start()
    _emit_workflow_stage(2, total_stages, f"pool {pool_id} started; dispatching task")
    try:
        result = await pool.execute_task({"prompt": prompt})
    finally:
        if not keep:
            await pool.stop()
            _emit_workflow_stage(3, total_stages, "pool + worker + adapter stopped")
    return {
        "workflow": "pool-worker-terminal",
        "pool_id": pool_id,
        "pool_type": "mahavishnu",
        "adapter": adapter,
        "worker_id": result.get("worker_id"),
        "status": result.get("status"),
        "duration": result.get("duration"),
        "output_preview": _truncate(result.get("output"), max_chars=200),
    }


@demo_app.command("workflow-pool-worker-terminal")
def demo_workflow_pool_worker_terminal(
    prompt: str = typer.Option(
        DEFAULT_WORKFLOW_DEMO_PROMPT.format(stage="pool-worker-terminal"),
        "--prompt",
        "-p",
        help="Prompt dispatched through the pool+worker+terminal chain.",
    ),
    adapter: str = typer.Option(
        DEFAULT_WORKFLOW_ADAPTER,
        "--adapter",
        "-a",
        help="Terminal adapter to wire into the pool's TerminalManager (mock|tmux).",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave the pool running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(60, "--timeout", help="Max seconds for the 3-stage handoff."),
) -> None:
    """Run a pool + worker + terminal adapter end-to-end with stage narration.

    Operator-facing E2E demo. Composes three substrates in a single trace:

    1. ``MahavishnuPool`` (orchestrator, scales min..max workers)
    2. ``WorkerManager`` (the 'worker'; the pool's internal substrate)
    3. ``TerminalAdapter`` (mock or tmux; controls how workers attach)

    Output is a stage-narrated trace followed by a structured result JSON.
    Use ``--adapter mock`` for a fast in-process run (no tmux overhead).
    """
    failures = _check_workflow_pool_worker_terminal_preconditions(adapter=adapter)
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Workflow: pool + worker + {adapter} terminal adapter")
    typer.echo(f"Prompt:   {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_workflow_pool_worker_terminal_demo(
                    prompt=prompt,
                    adapter=adapter,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nWorkflow result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# workflow-multi-pool-handoff — CI smoke: two pools in sequence
# ----------------------------------------------------------------------------


def _check_workflow_multi_pool_handoff_preconditions(
    *,
    source_pool: str,
    target_pool: str,
    http_probe: Callable[[str, float], bool] | None = None,
    probe_timeout_s: float = DEFAULT_RUNPOD_PROBE_TIMEOUT_S,
    tmux_which: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Verify both pool substrates are reachable.

    - source_pool='session-buddy'  -> HTTP probe the configured URL.
    - source_pool='mahavishnu'      -> require tmux binary (default backend).
    - source_pool='pi'              -> require npx (PiPool substrate).
    - target_pool follows the same matrix; 'mahavishnu' defaults require tmux.
    """
    tmux_lookup = tmux_which or shutil.which
    probe = http_probe or _default_http_probe
    failures: list[str] = []

    def _check_pool_substrate(label: str, pool: str) -> None:
        if pool == "session-buddy":
            if not probe(DEFAULT_SESSION_BUDDY_URL, probe_timeout_s):
                failures.append(
                    f"{label} pool 'session-buddy' not reachable at "
                    f"{DEFAULT_SESSION_BUDDY_URL} within {probe_timeout_s}s"
                )
        elif pool == "mahavishnu":
            if not tmux_lookup("tmux"):
                failures.append(f"{label} pool 'mahavishnu' requires tmux binary (not on PATH)")
        elif pool == "pi":
            if not shutil.which("npx"):
                failures.append(f"{label} pool 'pi' requires npx binary (not on PATH)")
        else:
            failures.append(
                f"{label} pool {pool!r} is not supported in this demo. "
                f"Supported: 'session-buddy', 'mahavishnu', 'pi'."
            )

    _check_pool_substrate("source", source_pool)
    _check_pool_substrate("target", target_pool)
    return failures


async def _run_workflow_multi_pool_handoff_demo(
    *,
    source_pool: str,
    target_pool: str,
    prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Dispatch to source pool, then hand the result to target pool.

    Compact step output (one line per step) — designed for CI smoke,
    not operator E2E. The follow-up prompt to the target pool echoes
    the source result so the handoff is observable in the output.
    """

    source_pool_obj = await _spawn_pool_by_type(source_pool, name="demo-mh-src")
    target_pool_obj = await _spawn_pool_by_type(target_pool, name="demo-mh-tgt")
    try:
        # Start both pools so workers are registered before execute_task().
        # Without this, self._workers is empty when execute_task checks
        # availability, and the pool raises "No workers available in
        # pool" before any task is actually dispatched.
        await source_pool_obj.start()
        await target_pool_obj.start()
        typer.echo(f"  ✓ source pool ({source_pool}) started: {source_pool_obj.pool_id}")
        source_result = await source_pool_obj.execute_task({"prompt": prompt})
        typer.echo(f"  ✓ source task complete: status={source_result.get('status')}")
        followup = f"echo 'received from {source_pool}: ' \"{source_result.get('output', '')}\""
        target_result = await target_pool_obj.execute_task({"prompt": followup})
        typer.echo(
            f"  ✓ target pool ({target_pool}) task complete: status={target_result.get('status')}"
        )
    finally:
        if not keep:
            await source_pool_obj.stop()
            await target_pool_obj.stop()
            typer.echo("  ✓ both pools stopped")
    return {
        "workflow": "multi-pool-handoff",
        "source": {
            "pool_type": source_pool,
            "pool_id": source_pool_obj.pool_id,
            "status": source_result.get("status"),
            "duration": source_result.get("duration"),
        },
        "target": {
            "pool_type": target_pool,
            "pool_id": target_pool_obj.pool_id,
            "status": target_result.get("status"),
            "duration": target_result.get("duration"),
        },
    }


async def _spawn_pool_by_type(pool_type: str, *, name: str) -> Any:
    """Construct a BasePool by string name (helper for workflow demos).

    Returns the constructed pool object. Caller is responsible for
    ``start()``, ``execute_task()``, and ``stop()`` (or use the
    pool-mahavishnu / pool-session-buddy / pool-pi demo helpers).
    """
    from mahavishnu.pools import PoolConfig

    if pool_type == "session-buddy":
        from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

        return SessionBuddyPool(
            config=PoolConfig(name=name, pool_type="session-buddy"),
            session_buddy_url=DEFAULT_SESSION_BUDDY_URL,
        )
    if pool_type == "mahavishnu":
        from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
        from mahavishnu.terminal.adapters import _build_tmux_adapter
        from mahavishnu.terminal.manager import TerminalManager

        return MahavishnuPool(
            config=PoolConfig(name=name, pool_type="mahavishnu", min_workers=1, max_workers=1),
            terminal_manager=TerminalManager(adapter=_build_tmux_adapter()),
        )
    if pool_type == "pi":
        from mahavishnu.pools.pi_pool import PiPool

        return PiPool(config=PoolConfig(name=name, pool_type="pi", min_workers=1, max_workers=1))
    raise ValueError(f"unsupported pool_type for workflow demo: {pool_type!r}")


@demo_app.command("workflow-multi-pool-handoff")
def demo_workflow_multi_pool_handoff(
    source_pool: str = typer.Option(
        DEFAULT_WORKFLOW_SOURCE_POOL,
        "--source-pool",
        help="Source pool type (session-buddy|mahavishnu|pi).",
    ),
    target_pool: str = typer.Option(
        DEFAULT_WORKFLOW_TARGET_POOL,
        "--target-pool",
        help="Target pool type (session-buddy|mahavishnu|pi).",
    ),
    prompt: str = typer.Option(
        "echo 'hello from source pool'",
        "--prompt",
        "-p",
        help="Prompt dispatched to the source pool first.",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave both pools running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(
        30, "--timeout", help="Max seconds for the 2-pool handoff (target <10s)."
    ),
) -> None:
    """Run a 2-pool handoff (source -> target) with compact step output.

    CI smoke flavor. Designed to be fast and exit-code-shaped: each step
    prints ``✓`` on success, the final result is a structured JSON
    payload. Use this in CI to confirm the pool-handoff path is not
    regressed (e.g. after a refactor of ``BasePool.execute_task``).

    For the operator-facing E2E (Prefect -> pool -> worker -> terminal),
    use ``mahavishnu demo workflow-pool-worker-terminal`` instead.
    """
    failures = _check_workflow_multi_pool_handoff_preconditions(
        source_pool=source_pool,
        target_pool=target_pool,
    )
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Workflow: {source_pool} -> {target_pool} pool handoff")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_workflow_multi_pool_handoff_demo(
                    source_pool=source_pool,
                    target_pool=target_pool,
                    prompt=prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nWorkflow result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# workflow-adapter-swap — Doc reference: same task, two terminal adapters
# ----------------------------------------------------------------------------


def _check_workflow_adapter_swap_preconditions(
    *,
    adapter_a: str,
    adapter_b: str,
    pool_name_a: str = "demo-aswap-adapter_a",
    pool_name_b: str = "demo-aswap-adapter_b",
    tmux_which: Callable[[str], str | None] | None = None,
    exists: Callable[[Path], bool] | None = None,
    home: Path | None = None,
) -> list[str]:
    """Verify both terminal adapters are usable.

    Probes (injectable for tests):

    - ``adapter_a == 'tmux'`` or ``adapter_b == 'tmux'`` requires the tmux binary.
    - ``adapter == 'mock'`` always passes.
    - Same-name + same-name is rejected (swap is meaningless).
    - Shepherd workspace markers at the resolved writable roots for
      each pool. Without an initialized ``<workspace>/.vcscore``,
      each ``pool.start()`` fails fail-closed with ``MHV-312`` —
      surfaced here so the operator sees a clear "run sp init first"
      message instead of two stack traces.
    """
    tmux_lookup = tmux_which or shutil.which
    failures: list[str] = []
    for label, name in (("adapter-a", adapter_a), ("adapter-b", adapter_b)):
        if name not in ("mock", "tmux"):
            failures.append(f"{label}={name!r} is not supported. Supported: 'mock', 'tmux'.")
    if (adapter_a == "tmux" or adapter_b == "tmux") and not tmux_lookup("tmux"):
        failures.append("tmux binary not on PATH (required when either adapter is 'tmux')")
    if adapter_a == adapter_b:
        failures.append(
            f"adapter-a and adapter-b are both {adapter_a!r} — "
            f"swap requires two different adapters."
        )
    for pool_name in (pool_name_a, pool_name_b):
        workspace = _expected_shepherd_workspace_path(pool_name, home=home)
        failures.extend(_check_shepherd_workspace(workspace, exists=exists))
    return failures


async def _run_workflow_adapter_swap_demo(
    *,
    prompt: str,
    adapter_a: str,
    adapter_b: str,
    keep: bool,
) -> dict[str, object]:
    """Run the same prompt through adapter-a then adapter-b; compare.

    The pool is constructed with adapter-a, dispatches the task, stops;
    then re-constructed with adapter-b for the second run. Output is
    side-by-side: each run's status, duration, and output preview are
    returned under their own key so an operator can compare behavior.
    """
    # NOTE: ``MahavishnuPool`` is NOT re-exported by ``mahavishnu.pools``
    # (only ``RunPodPool`` is). Import from the concrete module to
    # avoid an ImportError at runtime.
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
    from mahavishnu.terminal.manager import TerminalManager

    runs: dict[str, dict[str, object]] = {}
    for label, adapter_name in (("adapter_a", adapter_a), ("adapter_b", adapter_b)):
        typer.echo(f"  → running with {label}={adapter_name}")
        terminal_adapter = _build_terminal_adapter(adapter_name)
        terminal_manager = TerminalManager(adapter=terminal_adapter)
        pool = MahavishnuPool(
            config=PoolConfig(
                name=f"demo-aswap-{label}",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=1,
            ),
            terminal_manager=terminal_manager,
        )
        pool_id = await pool.start()
        try:
            result = await pool.execute_task({"prompt": prompt})
        finally:
            if not keep:
                await pool.stop()
        runs[label] = {
            "adapter": adapter_name,
            "pool_id": pool_id,
            "status": result.get("status"),
            "duration": result.get("duration"),
            "output_preview": _truncate(result.get("output"), max_chars=200),
        }
    return {
        "workflow": "adapter-swap",
        "prompt": prompt,
        **runs,
    }


@demo_app.command("workflow-adapter-swap")
def demo_workflow_adapter_swap(
    adapter_a: str = typer.Option(
        DEFAULT_WORKFLOW_ADAPTER,
        "--adapter-a",
        help="First terminal adapter (mock|tmux).",
    ),
    adapter_b: str = typer.Option(
        DEFAULT_WORKFLOW_ADAPTER_B,
        "--adapter-b",
        help="Second terminal adapter (mock|tmux).",
    ),
    prompt: str = typer.Option(
        "echo 'adapter swap: same prompt, different terminal adapters'",
        "--prompt",
        "-p",
        help="Same prompt dispatched through both adapters for comparison.",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave both pools running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(
        90, "--timeout", help="Max seconds for both runs (2 * pool start + execute + stop)."
    ),
) -> None:
    """Run the same task with two terminal adapters back-to-back.

    Doc-reference flavor. Demonstrates that the same MahavishnuPool
    substrate can be wired with different terminal adapters without
    changing the dispatch path — useful when writing guides that
    compare adapter behavior, or when debugging a regression that's
    specific to one adapter.

    Returns a side-by-side JSON payload with per-adapter status,
    duration, and output preview.
    """
    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a=adapter_a,
        adapter_b=adapter_b,
    )
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Workflow: adapter swap ({adapter_a} vs {adapter_b})")
    typer.echo(f"Prompt:   {prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_workflow_adapter_swap_demo(
                    prompt=prompt,
                    adapter_a=adapter_a,
                    adapter_b=adapter_b,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nWorkflow result (side-by-side):")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# workflow-pi-cascade — CI smoke: single PiPool, 2-turn cascade
# ----------------------------------------------------------------------------


def _check_workflow_pi_cascade_preconditions(
    *,
    npx_which: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Verify the PiPool substrate can spawn its npx subprocess.

    PiPool is the only pool in the demo set that does NOT use
    Shepherd — it spawns ``npx @earendil-works/pi-coding-agent``
    as a one-shot CLI invocation. So no Shepherd workspace check
    is needed (the pool doesn't resolve a ``writable_root``), and
    ``npx`` is the only binary prerequisite.
    """
    which = npx_which or shutil.which
    failures: list[str] = []
    if not which("npx"):
        failures.append(
            "npx binary not on PATH (PiPool spawns npx @earendil-works/"
            "pi-coding-agent). Install Node.js 18+ and ensure npx is reachable."
        )
    return failures


async def _run_workflow_pi_cascade_demo(
    *,
    prompt: str,
    followup: str,
    keep: bool,
) -> dict[str, object]:
    """Run a single PiPool through a 2-turn cascade: turn 1's result feeds turn 2.

    PiPool has a fixed ``max_workers=1`` (rejects ``scale(n>1)``), so a
    "cascade" here means "two sequential dispatches, each a fresh
    subprocess" — turn 1's output is folded into turn 2's prompt as
    context. This showcases PiPool's multi-turn agent capability,
    which is its real-world use case (the other pool demos all do
    single-dispatch).

    CI-smoke flavor: compact ✓/✗ per stage, no Shepherd prerequisite,
    runnable in any dev shell with ``npx`` installed.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.pi_pool import PiPool

    pool = PiPool(
        config=PoolConfig(
            name="demo-pi-cascade",
            pool_type="pi",
            min_workers=1,
            max_workers=1,
        )
    )
    pool_id = await pool.start()
    try:
        typer.echo(f"  ✓ pi pool started: {pool_id}")
        turn1_result = await pool.execute_task({"prompt": prompt})
        typer.echo(f"  ✓ turn 1 complete: status={turn1_result.get('status')}")
        cascade_prompt = (
            f"received from previous turn: {turn1_result.get('output', '')}\n\n{followup}"
        )
        turn2_result = await pool.execute_task({"prompt": cascade_prompt})
        typer.echo(f"  ✓ turn 2 complete: status={turn2_result.get('status')}")
    finally:
        if not keep:
            await pool.stop()
            typer.echo("  ✓ pi pool stopped")
    return {
        "workflow": "pi-cascade",
        "pool_id": pool_id,
        "pool_type": "pi",
        "turns": [
            {
                "prompt": prompt,
                "status": turn1_result.get("status"),
                "duration": turn1_result.get("duration"),
                "output_preview": _truncate(turn1_result.get("output"), max_chars=200),
            },
            {
                "prompt": cascade_prompt,
                "status": turn2_result.get("status"),
                "duration": turn2_result.get("duration"),
                "output_preview": _truncate(turn2_result.get("output"), max_chars=200),
            },
        ],
    }


@demo_app.command("workflow-pi-cascade")
def demo_workflow_pi_cascade(
    prompt: str = typer.Option(
        "what is 2+2?",
        "--prompt",
        "-p",
        help="First-turn prompt dispatched to PiPool.",
    ),
    followup: str = typer.Option(
        "explain the previous answer in one sentence.",
        "--followup",
        help="Second-turn prompt. Turn-1 result is prepended as context.",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave the pi pool running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(60, "--timeout", help="Max seconds for both turns + start + stop."),
) -> None:
    """Run a single PiPool through a 2-turn cascade (turn 1's result feeds turn 2).

    CI-smoke flavor. Distinct from the existing 3 workflow demos in
    shape: it uses a single pool, but exercises PiPool's
    multi-turn-agent capability (the only pool in the demo set that
    supports it). The cascade is a sequential pair of dispatches
    against the same long-lived subprocess — turn 1's output is
    folded into turn 2's prompt as context.

    Runnable in any dev shell with ``npx`` on PATH (no Shepherd
    workspace prerequisite — PiPool doesn't use one).
    """
    failures = _check_workflow_pi_cascade_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Workflow: pi cascade (2 turns on the same pool)")
    typer.echo(f"Turn 1:  {prompt}")
    typer.echo(f"Turn 2:  {followup}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_workflow_pi_cascade_demo(
                    prompt=prompt,
                    followup=followup,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nWorkflow result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------
# workflow-pi-then-local — Doc reference: PiPool → MahavishnuPool handoff
# ----------------------------------------------------------------------------


def _check_workflow_pi_then_local_preconditions(
    *,
    npx_which: Callable[[str], str | None] | None = None,
    exists: Callable[[Path], bool] | None = None,
    home: Path | None = None,
    pool_name_local: str = "demo-pi-then-local-local",
) -> list[str]:
    """Verify PiPool's npx substrate AND the local pool's Shepherd workspace.

    - PiPool half: npx on PATH (the only binary prereq for the
      ``npx @earendil-works/pi-coding-agent`` CLI invocation).
    - MahavishnuPool half: Shepherd workspace at
      ``~/.local/state/mahavishnu/worktrees/<pool_name_local>/workspace``
      must be initialized (``.vcscore`` marker present). Without it,
      the local pool's ``start()`` fails fail-closed with ``MHV-312``.

    Probes (all injectable for tests).
    """
    which = npx_which or shutil.which
    failures: list[str] = []
    if not which("npx"):
        failures.append("npx binary not on PATH (PiPool half; install Node.js 18+).")
    workspace = _expected_shepherd_workspace_path(pool_name_local, home=home)
    failures.extend(_check_shepherd_workspace(workspace, exists=exists))
    return failures


async def _run_workflow_pi_then_local_demo(
    *,
    pi_prompt: str,
    local_prompt: str,
    keep: bool,
) -> dict[str, object]:
    """Run PiPool, then hand the result to MahavishnuPool for follow-up.

    Two-pool handoff (PiPool → MahavishnuPool), each pool playing
    to its strengths: PiPool's model-agnostic single-subprocess
    agent generates something, then a local Shepherd-backed
    pool executes the follow-up. The PiPool's output is folded
    into the local pool's prompt as context.

    Demo-recipe flavor (paired with ``docs/cookbook/workflows.md``).
    Requires the Shepherd workspace to be initialized for the local
    pool — the precondition surfaces that with an ``sp init`` hint
    so the operator gets a clear path forward.
    """
    from mahavishnu.pools import PoolConfig
    from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
    from mahavishnu.pools.pi_pool import PiPool
    from mahavishnu.terminal.adapters import _build_tmux_adapter
    from mahavishnu.terminal.manager import TerminalManager

    pi_pool = PiPool(
        config=PoolConfig(
            name="demo-pi-then-local-pi",
            pool_type="pi",
            min_workers=1,
            max_workers=1,
        )
    )
    pi_pool_id = await pi_pool.start()
    try:
        typer.echo(f"  ✓ pi pool started: {pi_pool_id}")
        pi_result = await pi_pool.execute_task({"prompt": pi_prompt})
        typer.echo(f"  ✓ pi task complete: status={pi_result.get('status')}")
    finally:
        if not keep:
            await pi_pool.stop()
    typer.echo("  → starting local pool with pi output as context")
    local_pool = MahavishnuPool(
        config=PoolConfig(
            name="demo-pi-then-local-local",
            pool_type="mahavishnu",
            min_workers=1,
            max_workers=1,
        ),
        terminal_manager=TerminalManager(adapter=_build_tmux_adapter()),
    )
    local_pool_id = await local_pool.start()
    try:
        followup_prompt = (
            f"received from pi pool: {pi_result.get('output', '')}\n\ntask: {local_prompt}"
        )
        local_result = await local_pool.execute_task({"prompt": followup_prompt})
        typer.echo(f"  ✓ local task complete: status={local_result.get('status')}")
    finally:
        if not keep:
            await local_pool.stop()
            typer.echo("  ✓ both pools stopped")
    return {
        "workflow": "pi-then-local",
        "pi": {
            "pool_type": "pi",
            "pool_id": pi_pool_id,
            "status": pi_result.get("status"),
            "duration": pi_result.get("duration"),
            "output_preview": _truncate(pi_result.get("output"), max_chars=200),
        },
        "local": {
            "pool_type": "mahavishnu",
            "pool_id": local_pool_id,
            "status": local_result.get("status"),
            "duration": local_result.get("duration"),
            "output_preview": _truncate(local_result.get("output"), max_chars=200),
        },
    }


@demo_app.command("workflow-pi-then-local")
def demo_workflow_pi_then_local(
    pi_prompt: str = typer.Option(
        "write a hello-world function in Python",
        "--pi-prompt",
        help="Prompt dispatched to PiPool first (the 'generate' step).",
    ),
    local_prompt: str = typer.Option(
        "test it and report the result",
        "--local-prompt",
        help="Prompt dispatched to the local pool (the 'execute' step).",
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Leave both pools running after the demo (for debugging)."
    ),
    timeout: int = typer.Option(90, "--timeout", help="Max seconds for the 2-pool handoff."),
) -> None:
    """Run PiPool, then hand the result to MahavishnuPool for follow-up.

    Doc-reference flavor. Showcases a real cross-pool handoff where
    each pool plays to its strength: PiPool's model-agnostic single
    subprocess generates something, then a Shepherd-backed local
    pool executes the follow-up. The PiPool's output is folded
    into the local pool's prompt as context.

    Paired with ``docs/cookbook/workflows.md`` recipe 1.

    Prerequisites: ``npx`` on PATH AND a Shepherd workspace at
    ``~/.local/state/mahavishnu/worktrees/demo-pi-then-local-local/workspace``
    (run ``sp init`` there first if the precondition surfaces it).
    """
    failures = _check_workflow_pi_then_local_preconditions()
    if failures:
        typer.echo("Precondition failure(s):", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Workflow: pi pool -> local pool handoff")
    typer.echo(f"Pi prompt:    {pi_prompt}")
    typer.echo(f"Local prompt: {local_prompt}")

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_workflow_pi_then_local_demo(
                    pi_prompt=pi_prompt,
                    local_prompt=local_prompt,
                    keep=keep,
                ),
                timeout=timeout,
            )
        )
    except TimeoutError:
        typer.echo(f"Timed out after {timeout}s", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\nWorkflow result:")
    typer.echo(json.dumps(result, indent=2, default=str))


# ============================================================================
# Stubs — 1 mock terminal adapter remains (agno + llamaindex + pydantic_ai
# + crow + hatchet promoted to live implementations above; 4 pool demos
# promoted to live in PR #2: pool-mahavishnu, pool-session-buddy,
# pool-runpod, pool-pi; 5 workflow demos promoted to live across PR #3
# and PR #4: workflow-pool-worker-terminal, workflow-multi-pool-handoff,
# workflow-adapter-swap, workflow-pi-cascade, workflow-pi-then-local)
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


# Register the 1 remaining stub. Live implementations land in follow-up PRs.
for _stub_name in ("mock",):
    _cmd = _stub_command(_stub_name)
    demo_app.command(_stub_name)(_cmd)
del _stub_name, _cmd  # hygiene


__all__ = ["demo_app"]
