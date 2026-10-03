"""Lifecycle helpers for the MCP server."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .bootstrap import register_profile_tools as _register_profile_tools_helper
from .sweepers.task_orphan_sweeper import TaskOrphanSweeper
from .tools.profiles import PROFILE_REGISTRATIONS, get_active_profile

logger = logging.getLogger(__name__)


def get_session_buddy_client() -> Any:
    """Return the session-buddy client to bind to the task-orphan sweeper.

    Inline fallback for the v1.1 task-system wire-up (Task 10): the
    full session-buddy client wiring is out of scope here, so the
    sweeper's ``_recover_orphan`` body sees ``None`` and logs
    "no session_buddy client; skipping" — the stream loop stays alive
    but no tasks are re-linked. A follow-up wires the real client.
    """
    return None


async def start_server(server: Any, host: str = "127.0.0.1", port: int = 3000) -> None:
    """Start the MCP server with the active tool profile."""
    server._active_profile = get_active_profile()
    methods_to_call = PROFILE_REGISTRATIONS[server._active_profile]
    methods_set = set(methods_to_call)

    logger.info(
        "Starting Mahavishnu MCP server with tool profile: %s (%d registration groups scheduled)",
        server._active_profile.value,
        len(methods_to_call),
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
        except Exception:
            logger.exception("Failed to initialize pool manager during mcp start — see traceback")

    if getattr(server.app, "memory_aggregator", None) is None and getattr(
        server.app.config, "memory_aggregation_enabled", False
    ):
        try:
            from ..core.bootstrap import init_memory_aggregator

            server.app.memory_aggregator = init_memory_aggregator(server.app)
        except Exception:
            logger.exception(
                "Failed to initialize memory aggregator during mcp start — see traceback"
            )

    await _register_profile_tools_helper(server, methods_set)
    server._update_registered_tool_metrics()

    # Phase 1.5 — initialize the skills_signer feed state BEFORE
    # ``run_http_async`` so the /health route (already registered in
    # register_health_endpoint during __init__) can see the populated
    # singleton. Per plan §10.3.2 option c: mahavishnu has no async
    # lifespan so this init runs after the tool profile is applied.
    # The launchd wrapper tolerates up to 120s of startup.
    from .signer_feed import init_signer_feed_state

    try:
        init_signer_feed_state()
    except Exception as exc:  # noqa: BLE001 - MCP boundary must preserve all operation failures
        logger.error("Failed to initialize skills_signer feed state: %s", exc)
        # Don't crash the server — the /health route will report
        # skills_signer as degraded with the error message.

    # Phase 3 — start the plan_index periodic rebuild loop BEFORE
    # ``run_http_async`` so the /health route can read populated feed
    # state. Mirrors the signer_init pattern: ``PeriodicTaskRunner``
    # exposes ``force_run()`` (async) and ``start()`` (schedules the
    # periodic loop). We await ``force_run()`` once synchronously so
    # the feed state is populated immediately — calling only
    # ``start()`` would defer the first cycle to a background task
    # that may not get scheduled before FastMCP's lifespan scope
    # reshuffles the event loop.
    #
    # The cron calls ``mcp.get/.put/.list_prefix`` via
    # ``PlanIndexStore`` — that interface (string KV) is implemented
    # by ``MCPKvClient``, which unwraps MCP's
    # ``{ok,key,value}`` wire envelope so ``cron_core`` can do
    # ``int(await store._mcp.get(KEY))`` and ``json.loads(...)``
    # against the raw stored string. ``MCPStateBackend`` (the
    # workflow/pool/approval substrate) returns the envelope dict
    # on purpose and would crash every cycle with
    # ``int() argument must be ... not 'dict'``.
    try:
        from pathlib import Path

        from ..core.bootstrap import resolve_mcp_url
        from ..core.state_backends.mcp_kv import MCPKvClient, MCPKvConfig
        from ..plan_index.cron import PeriodicTaskRunner
        from ..plan_index.store import PlanIndexStore

        mcp_url = resolve_mcp_url(server.app.config)
        kv_backend = MCPKvClient(
            base_url=mcp_url,
            config=MCPKvConfig(enabled=True),
        )
        server._plan_index_mcp_kv = kv_backend
        store = PlanIndexStore(kv_backend)
        # ``Path.cwd()`` is the mahavishnu repo root when launched via
        # the launchd plist (``WorkingDirectory`` is set), so
        # ``discover_records`` finds the real ``docs/plans/*.md``.
        # Falls back to ``None`` (zero-record cycle that still flips
        # ``is_ok``) when cwd isn't the repo.
        repo_root = Path.cwd() if Path("docs/plans").is_dir() else None
        runner = PeriodicTaskRunner(store=store, repo_root=repo_root)
        outcome = await runner.force_run()
        runner.start()  # schedule the periodic loop for subsequent cycles
        server._plan_index_runner = runner
        logger.info(
            "plan_index cycle complete: success=%d errors=%d entities=%d (repo_root=%s)",
            outcome.success,
            outcome.errors,
            outcome.entities_count,
            repo_root or "<none — empty cycle>",
        )
    except Exception as exc:  # noqa: BLE001 - MCP boundary
        logger.error("Failed to start plan_index subsystem: %s", exc)
        # Don't crash — /health will report plan_index degraded with
        # the prior "awaiting start()" error message.
        # Note: a previous version of this code synthesized a fake
        # feed-state here so /health flipped even when the live cycle
        # crashed. That hid the int(dict) wire-envelope bug; now that
        # ``MCPKvClient`` solves the seam, the live cycle should
        # succeed and a real failure is worth surfacing.

    # Task 10 — wire the v1.1 task-orphan sweeper into the MCP server
    # lifecycle. The sweeper consumes ``task.handoff_orphan`` events on
    # the ``bodai:events`` Redis Stream and re-links orphaned tasks via
    # session-buddy (Task 9). Started BEFORE ``run_http_async`` so the
    # /health route (registered in ``__init__``) can see populated
    # feed state. Failures are logged + swallowed so a Redis outage
    # at startup does not crash the server; ``/health`` flips to
    # ``degraded`` via the sweeper's ``_consecutive_read_failures``
    # signal. ``get_session_buddy_client()`` returns ``None`` for now
    # (Task 10 scope is the lifecycle seam, not the client wiring) —
    # the sweeper logs "no session_buddy client; skipping" and the
    # stream loop stays alive.
    try:
        sweeper = TaskOrphanSweeper(
            session_buddy_client=get_session_buddy_client(),
        )
        await sweeper.init()
        sweeper_task = asyncio.create_task(sweeper.run_forever(), name="task_orphan_sweeper")
        server._task_orphan_sweeper = sweeper
        server._task_orphan_sweeper_task = sweeper_task
        logger.info("task_orphan_sweeper started (stream=bodai:events)")
    except Exception as exc:  # noqa: BLE001 - MCP boundary
        logger.error("Failed to start task_orphan_sweeper: %s", exc)
        # Don't crash — /health will report task_orphan_sweeper degraded
        # with the prior "not started" error message.

    # Override FastMCP's hardcoded 2s graceful-shutdown timeout so
    # lifespan teardown can run cleanup (hooks, health snapshots, etc.)
    # without being cancelled mid-shutdown.
    await server.server.run_http_async(
        host=host,
        port=port,
        uvicorn_config={"timeout_graceful_shutdown": 30},
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
        except Exception as exc:  # noqa: BLE001 - MCP boundary
            logger.warning("Error awaiting task_orphan_sweeper task: %s", exc)
    sweeper = getattr(server, "_task_orphan_sweeper", None)
    if sweeper is not None:
        try:
            await sweeper.cleanup()
            logger.info("task_orphan_sweeper stopped")
        except Exception as exc:  # noqa: BLE001 - MCP boundary
            logger.warning("Error stopping task_orphan_sweeper: %s", exc)

    # Phase 3 — stop the plan_index rebuild loop so the periodic task
    # closes cleanly. Mirrors the signer reset pattern below. Skipped
    # silently when the runner was never started (e.g. init raised).
    runner = getattr(server, "_plan_index_runner", None)
    if runner is not None:
        try:
            await runner.stop()
            logger.info("plan_index runner stopped")
        except Exception as exc:  # noqa: BLE001 - MCP boundary
            logger.warning("Error stopping plan_index runner: %s", exc)

    # Phase 1.5 — clear the skills_signer feed state singleton so
    # the next start() gets a fresh module-level state (and so a
    # test calling stop_server → start_server sees a clean slate).
    from .signer_feed import reset_signer_feed_state

    reset_signer_feed_state()

    if hasattr(server, "mcp_client") and hasattr(server.mcp_client, "_client"):
        try:
            await server.mcp_client._client.stop()
            logger.info("Stopped embedded MCP client")
        except Exception as exc:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.warning("Error stopping embedded MCP client: %s", exc)


async def register_worktree_tools(server: Any) -> None:
    """Register worktree management tools."""
    if not server.app.worktree_coordinator:
        logger.info("WorktreeCoordinator not initialized, skipping tool registration")
        return

    from ..mcp.tools.worktree_tools import register_worktree_tools

    register_worktree_tools(server.server, server.app)
    logger.info("Registered 1 worktree management tool with MCP server")
