"""Lifecycle helpers for the MCP server."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

from .bootstrap import register_profile_tools as _register_profile_tools_helper
from .sweepers.task_orphan_sweeper import TaskOrphanSweeper
from .tools.profiles import PROFILE_REGISTRATIONS, get_active_profile

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger(__name__)


def get_session_buddy_client() -> Any:
    """Return the session-buddy client to bind to the task-orphan sweeper.

    Inline fallback for the v1.1 task-system wire-up (Task 10): the
    full session-buddy client wiring is out of scope here, so the
    sweeper's ``_recover_orphan`` body sees ``None`` and logs
    "no session_buddy client; skipping" — the stream loop stays alive
    but no tasks are re-linked. A follow-up wires the real client.
    """
    return None


async def start_change_point_tick_loop(server: Any) -> None:
    """Start the change-point detector tick loop on the server's app.

    This is the ONLY place the loop is started in production. It used
    to be started opportunistically from ``MahavishnuApp.__init__``
    (``bootstrap.init_observability``), which is a sync path with no
    matching teardown — and the call site never ``await``ed the
    manager's then-``async def`` method, so the loop never ran at all
    and the detector was silently dead.

    Starting it here pairs it with :func:`stop_change_point_tick_loop`,
    so the task is cancelled rather than orphaned when the loop closes.
    """
    try:
        app = getattr(server, "app", None)
        if app is None:
            logger.warning("change-point tick loop NOT started: server has no app")
            return
        await app.start_change_point_tick_loop()
        logger.info("change-point tick loop started")
    except Exception as exc:  # background task init — keep server alive on any failure  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.error(f"Failed to start change-point tick loop: {exc}")
        # Don't crash — drift detection is a degradable subsystem.


async def stop_change_point_tick_loop(server: Any) -> None:
    """Cancel the change-point tick loop task on shutdown."""
    app = getattr(server, "app", None)
    if app is None:
        return
    try:
        await app.stop_change_point_tick_loop()
        logger.info("change-point tick loop stopped")
    except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.warning(f"Error stopping change-point tick loop: {exc}")


def build_post_start_lifespan(server: Any) -> Any:
    """Return a FastMCP lifespan that runs all post-listener init.

    Why this exists (2026-10-04 refactor; see
    ``docs/specs/2026-10-04-mcp-lifespan-plan-index-init.md``):

    The previous ``start_server`` ran three init steps *before*
    ``run_http_async``: signer feed, plan_index rebuild, sweeper spawn.
    The plan_index rebuild uses ``MCPKvClient`` which connects via
    HTTP to the MCP server's own KV endpoints — a server that isn't
    bound until ``run_http_async`` runs. The previous
    ``_RunAsyncAdapter`` wrapper bypassed ``start_server`` entirely,
    so the broken code path was never exercised in production. The
    bypass hid a real bug, not just a wire-up contract.

    The lifespan runs after uvicorn has bound the listener (FastMCP's
    HTTP app lifespan, in ``fastmcp/server/http.py:667``, enters
    ``server._lifespan_manager()`` which fires the user-configured
    ``_lifespan``). All three post-init steps move here so the
    ``MCPKvClient`` can reach a live server.

    Returns the lifespan callable ready to assign to
    ``server.server._lifespan`` before calling ``run_http_async``.
    """

    @asynccontextmanager
    async def _lifespan(fastmcp: Any) -> AsyncGenerator[dict[str, Any]]:
        # ── startup (after uvicorn binds, before accepting) ──
        # signer feed (pure data, no HTTP dep)
        from .signer_feed import init_signer_feed_state

        try:
            init_signer_feed_state()
        except Exception as exc:  # MCP server init — degrading gracefully is the documented contract  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to initialize skills_signer feed state: {exc}")
            # Don't crash the server — /health reports skills_signer
            # as degraded with the error message.

        # sweeper spawn (Redis subscribe is fast; the run_forever()
        # body is the long-running part. Kept sync so the sweeper's
        # first health probe is live before the server starts serving.)
        sweeper_task: asyncio.Task | None = None
        try:
            sweeper = TaskOrphanSweeper(
                session_buddy_client=get_session_buddy_client(),
            )
            await sweeper.init()
            sweeper_task = asyncio.create_task(sweeper.run_forever(), name="task_orphan_sweeper")
            server._task_orphan_sweeper = sweeper
            server._task_orphan_sweeper_task = sweeper_task
            logger.info("task_orphan_sweeper started (stream=bodai:events)")
        except Exception as exc:  # background task init — keep server alive on any failure  # MCP tool error handler — broad catch is the documented contract  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to start task_orphan_sweeper: {exc}")
            # Don't crash — /health reports task_orphan_sweeper
            # degraded with the prior "not started" error message.

        # plan_index rebuild (needs MCP server's own KV endpoints —
        # scheduled as a BACKGROUND TASK rather than awaited here).
        # Why: when the lifespan runs, uvicorn has bound the listener
        # but the accept loop hasn't started yet (it starts after the
        # lifespan yields). An awaited HTTP call from inside the
        # lifespan would sit in the OS TCP backlog and time out.
        # Scheduling the work as a background task defers it until
        # the event loop is free to process both the server's request
        # handling and the client's response handling. The first
        # /health check after startup may briefly see plan_index as
        # ``warming_up``; the feed flips to ``ok`` once the background
        # task completes (typically < 5s).
        async def _init_plan_index() -> None:
            from pathlib import Path

            from ..core.bootstrap import resolve_mcp_url
            from ..core.state_backends.mcp_kv import MCPKvClient, MCPKvConfig
            from ..plan_index.cron import PeriodicTaskRunner
            from ..plan_index.store import PlanIndexStore

            try:
                mcp_url = resolve_mcp_url(server.app.config)
                kv_backend = MCPKvClient(
                    base_url=mcp_url,
                    config=MCPKvConfig(enabled=True),
                )
                server._plan_index_mcp_kv = kv_backend
                store = PlanIndexStore(kv_backend)
                # ``Path.cwd()`` is the mahavishnu repo root when
                # launched via the launchd plist (``WorkingDirectory``
                # is set), so ``discover_records`` finds the real
                # ``docs/plans/*.md``. Falls back to ``None`` (zero-
                # record cycle that still flips ``is_ok``) when cwd
                # isn't the repo.
                repo_root = Path.cwd() if Path("docs/plans").is_dir() else None
                runner = PeriodicTaskRunner(store=store, repo_root=repo_root)
                outcome = await runner.force_run()
                runner.start()  # schedule the periodic loop for subsequent cycles
                server._plan_index_runner = runner
                logger.info(
                    f"plan_index cycle complete: success={outcome.success} "
                    f"errors={outcome.errors} entities={outcome.entities_count} "
                    f"(repo_root={repo_root or '<none — empty cycle>'})"
                )
            except Exception as exc:  # plan_index background init — degradable subsystem per contract  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.error(f"Failed to start plan_index subsystem: {exc}")
                # Don't crash — /health reports plan_index degraded.

        plan_index_task = asyncio.create_task(_init_plan_index(), name="plan_index_init")
        server._plan_index_init_task = plan_index_task

        # change-point detector tick loop.
        #
        # This is the ONLY place the loop is started, and it is paired
        # with the shutdown half below so the task is cancelled rather
        # than orphaned when the event loop closes.
        await start_change_point_tick_loop(server)

        # ── yield: server runs here ──
        yield {}

        # ── shutdown (on SIGTERM) ──
        # Mirror stop_server's teardown semantics (lifespan replaces
        # stop_server for these three subsystems).
        if sweeper_task is not None:
            sweeper_task.cancel()
            try:
                await sweeper_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Error awaiting task_orphan_sweeper task: {exc}")
        sweeper = getattr(server, "_task_orphan_sweeper", None)
        if sweeper is not None:
            try:
                await sweeper.cleanup()
                logger.info("task_orphan_sweeper stopped")
            except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Error stopping task_orphan_sweeper: {exc}")

        # plan_index init task (may have completed by now or may still
        # be running; cancel and wait for cleanup)
        plan_index_init_task = getattr(server, "_plan_index_init_task", None)
        if plan_index_init_task is not None and not plan_index_init_task.done():
            plan_index_init_task.cancel()
            try:
                await plan_index_init_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Error cancelling plan_index_init task: {exc}")

        runner = getattr(server, "_plan_index_runner", None)
        if runner is not None:
            try:
                await runner.stop()
                logger.info("plan_index runner stopped")
            except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Error stopping plan_index runner: {exc}")

        # change-point tick loop — cancel it so the task does not outlive
        # the event loop.
        await stop_change_point_tick_loop(server)

        from .signer_feed import reset_signer_feed_state

        try:
            reset_signer_feed_state()
        except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Error resetting signer_feed_state: {exc}")

    return _lifespan


async def start_server(
    server: Any,
    host: str = "127.0.0.1",
    port: int = 3000,
    *,
    uvicorn_config: dict[str, Any] | None = None,
) -> None:
    """Start the MCP server with the active tool profile.

    Post-listener init (signer feed, plan_index rebuild, sweeper spawn)
    moved to the FastMCP lifespan returned by
    :func:`build_post_start_lifespan` so it runs after uvicorn binds
    the listener. The lifespan is assigned to ``server.server._lifespan``
    here, before ``run_http_async``, so FastMCP's HTTP app lifespan
    (in ``fastmcp/server/http.py:667``) enters the user lifespan via
    ``server._lifespan_manager()`` after the listener is up.

    Args:
        server: The :class:`FastMCPServer` wrapper to start.
        host: Bind host for the HTTP listener.
        port: Bind port for the HTTP listener.
        uvicorn_config: Optional dict passed verbatim to FastMCP's
            ``run_http_async(uvicorn_config=...)``. When ``None`` the
            historical default ``{"timeout_graceful_shutdown": 30}``
            applies — keeps the pre-launcher contract identical for
            ``mahavishnu mcp start`` and test callers that don't pass
            one. The launchd-driven ``scripts/launch_mcp.py`` path
            threads the launcher's config through so REQ-007 wins.
    """
    server._active_profile = get_active_profile()
    methods_to_call = PROFILE_REGISTRATIONS[server._active_profile]
    methods_set = set(methods_to_call)

    # Re-assert the process log level. ``FastMCPServer.__init__`` imports
    # crackerjack (whose module-level ``structlog.configure(...)`` pins
    # structlog at WARNING), and that import happens AFTER
    # ``MahavishnuApp.__init__`` restored the level. This is the last
    # point before the server starts serving, so it is the right place
    # to re-assert. See ``mahavishnu.core.bootstrap.configure_logging``.
    from ..core.bootstrap import configure_logging as _configure_logging_helper

    _configure_logging_helper(getattr(server.app, "config", None))

    logger.info(
        f"Starting Mahavishnu MCP server with tool profile: "
        f"{server._active_profile.value} ({len(methods_to_call)} registration groups scheduled)"
    )

    # Wire managers that ``initialize_runtime_services`` sets up for the
    # CLI/start path but NOT for the ``mahavishnu mcp start`` path.
    # Per Plan v3 Phase 1m (Agent A's diagnostic): this defensive block
    # MUST run BEFORE ``_register_profile_tools_helper`` so that
    # ``_register_pool_block`` sees ``pool_manager`` already populated.
    # Otherwise it short-circuits with "Pool manager not initialized,
    # skipping pool tools" and 19 pool + worker tools are missing from
    # the MCP surface. ``logger.exception`` (not ``logger.error``) per
    # Plan v3 Phase 1m — surfaces hard failures via full traceback for
    # the operator instead of silently continuing.
    if getattr(server.app, "pool_manager", None) is None and getattr(
        server.app.config, "pools_enabled", True
    ):
        try:
            from ..core.bootstrap import init_pool_manager

            server.app.pool_manager = init_pool_manager(server.app)
        except Exception:  # MCP start — surface traceback, server stays up
            logger.exception("Failed to initialize pool manager during mcp start — see traceback")

    if getattr(server.app, "memory_aggregator", None) is None and getattr(
        server.app.config, "memory_aggregation_enabled", False
    ):
        try:
            from ..core.bootstrap import init_memory_aggregator

            server.app.memory_aggregator = init_memory_aggregator(server.app)
        except Exception:  # MCP start — surface traceback, server stays up
            logger.exception(
                "Failed to initialize memory aggregator during mcp start — see traceback"
            )

    await _register_profile_tools_helper(server, methods_set)
    server._update_registered_tool_metrics()

    # Register the post-listener lifespan on the inner FastMCP before
    # ``run_http_async`` binds the listener. FastMCP's HTTP app
    # lifespan (in ``fastmcp/server/http.py:667``) enters
    # ``server._lifespan_manager()`` which fires this callable after
    # the listener is up — breaking the pre-refactor circular dep
    # where plan_index init's ``MCPKvClient`` tried to reach a server
    # that wasn't bound yet.
    server.server._lifespan = build_post_start_lifespan(server)

    # Override FastMCP's hardcoded 2s graceful-shutdown timeout so
    # lifespan teardown can run cleanup (hooks, health snapshots, etc.)
    # without being cancelled mid-shutdown. Caller-supplied
    # ``uvicorn_config`` (e.g. from the launcher's
    # ``timeout_graceful_shutdown`` kwarg) wins; the 30s literal is
    # the historical fallback for ``mahavishnu mcp start`` and tests
    # that don't pass one.
    effective_uvicorn_config = (
        uvicorn_config if uvicorn_config is not None else {"timeout_graceful_shutdown": 30}
    )
    await server.server.run_http_async(
        host=host,
        port=port,
        uvicorn_config=effective_uvicorn_config,
    )


async def stop_server(server: Any) -> None:
    """Stop the MCP server and cleanup resources."""
    # Task 10 — cancel the task-orphan sweeper loop and tear down the
    # Redis adapter. Mirrors the plan_index runner cleanup below:
    # the task attribute may be absent (init raised, or test
    # constructed the server by hand), so each step is guarded.
    sweeper_task = getattr(server, "_task_orphan_sweeper_task", None)
    if sweeper_task is not None:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Error awaiting task_orphan_sweeper task: {exc}")
    sweeper = getattr(server, "_task_orphan_sweeper", None)
    if sweeper is not None:
        try:
            await sweeper.cleanup()
            logger.info("task_orphan_sweeper stopped")
        except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Error stopping task_orphan_sweeper: {exc}")

    # Phase 3 — stop the plan_index rebuild loop so the periodic task
    # closes cleanly. Mirrors the signer reset pattern below. Skipped
    # silently when the runner was never started (e.g. init raised).
    runner = getattr(server, "_plan_index_runner", None)
    if runner is not None:
        try:
            await runner.stop()
            logger.info("plan_index runner stopped")
        except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Error stopping plan_index runner: {exc}")

    # Phase 1.5 — clear the skills_signer feed state singleton so
    # the next start() gets a fresh module-level state (and so a
    # test calling stop_server → start_server sees a clean slate).
    from .signer_feed import reset_signer_feed_state

    reset_signer_feed_state()

    if hasattr(server, "mcp_client") and hasattr(server.mcp_client, "_client"):
        try:
            await server.mcp_client._client.stop()
            logger.info("Stopped embedded MCP client")
        except Exception as exc:  # teardown — non-fatal, just log  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Error stopping embedded MCP client: {exc}")


async def register_worktree_tools(server: Any) -> None:
    """Register worktree management tools."""
    if not server.app.worktree_coordinator:
        logger.info("WorktreeCoordinator not initialized, skipping tool registration")
        return

    from ..mcp.tools.worktree_tools import register_worktree_tools

    register_worktree_tools(server.server, server.app)
    logger.info("Registered 1 worktree management tool with MCP server")
