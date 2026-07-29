"""MCP tools for worker orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from ...workers.contract.state import WorkerLifecycleState
from ...workers.registry import WORKER_REGISTRY, WorkerCategory

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

    from ...workers.contract.manager import DurableWorkerManager
    from ...workers.contract.tmux_adapter import CapturedOutput
    from ...workers.manager import WorkerManager


# Module-level references set by ``register_worker_tools``. The pattern
# mirrors ``worker_contract_tools.py``: module-level tool functions read
# from these globals so tests can monkeypatch without going through the
# FastMCP app.
_durable_manager: DurableWorkerManager | None = None
_worker_manager: WorkerManager | None = None


# Categories that must go through the durable-worker contract per the
# durable-local-workers plan. Container/Gateway/Application workers
# continue to use the legacy ``WorkerManager.spawn_workers`` path.
_DURABLE_CATEGORIES: frozenset[WorkerCategory] = frozenset(
    {WorkerCategory.SHELL, WorkerCategory.AI_ASSISTANT, WorkerCategory.REMOTE}
)


class _DurableCloseResult(TypedDict):
    """Return shape of ``worker_close`` on the durable-manager path."""

    closed: bool
    exit_code: int | None


class _LegacyCloseResult(TypedDict):
    """Return shape of ``worker_close`` on the legacy fallback path.

    ``error`` is populated only when the underlying ``close_worker``
    raises; the success branch intentionally omits it.
    """

    success: bool
    worker_id: str
    error: NotRequired[str]


async def worker_spawn(
    worker_type: str = "terminal-claude",
    count: int = 1,
) -> dict:
    """Spawn worker instances for task execution.

    Shell-based worker types (``SHELL``, ``AI_ASSISTANT``, ``REMOTE``)
    are routed through the durable-worker contract
    (``_durable_manager.spawn``) so they get tmux-backed lifecycle
    tracking. Non-shell workers (container, gateway, application)
    continue to use the legacy ``WorkerManager.spawn_workers`` path.
    When the durable manager is not configured, shell workers fall back
    to the legacy path so existing callers stay green.
    """
    if count < 1 or count > 50:
        raise ValueError("count must be between 1 and 50")

    config = WORKER_REGISTRY.get(worker_type)
    if (
        config is not None
        and config.category in _DURABLE_CATEGORIES
        and _durable_manager is not None
    ):
        results = [
            _durable_manager.spawn(
                worker_type=worker_type,
                backend="claude_tui",
                command=[worker_type],
            )
            for _ in range(count)
        ]
        return {"worker_ids": [r.worker_id for r in results]}

    if _worker_manager is None:
        raise RuntimeError("worker_manager not configured")

    worker_ids = await _worker_manager.spawn_workers(
        worker_type=worker_type,
        count=count,
    )
    return {"worker_ids": worker_ids}


async def worker_monitor(
    worker_ids: list[str] | None = None,
    interval: float = 1.0,
) -> dict[str, str | None]:
    """Monitor worker status using durable records or the legacy manager.

    When a durable manager is configured, this performs a one-shot status
    lookup for each requested worker and returns its authoritative state as a
    flat ``{worker_id: state}`` mapping. Missing durable workers map to
    ``None``. Without a durable manager, the legacy manager's polling behavior
    and interval validation are preserved.
    """
    if _durable_manager is not None:
        out: dict[str, str | None] = {}
        for wid in worker_ids or []:
            record = _durable_manager.status(wid)
            out[wid] = record.state if record is not None else None
        return out

    if interval < 0.1 or interval > 10.0:
        raise ValueError("interval must be between 0.1 and 10.0")

    if _worker_manager is None:
        raise RuntimeError("worker_manager not configured")

    statuses = await _worker_manager.monitor_workers(worker_ids, interval)
    return {wid: status.value for wid, status in statuses.items()}


async def worker_collect_results(
    worker_ids: list[str] | None = None,
    *,
    since_offset: int = 0,
) -> dict:
    """Collect results from completed workers.

    Wire shape differs by configuration. This is an intentional breaking
    change relative to the legacy flat-dict shape (``{wid: {...}}``):

    * **Durable-manager path** — when ``_durable_manager`` is configured,
      returns an envelope ``{"workers": {wid: {text, next_offset,
      truncated, pane_alive}}}`` so callers can page pane output via
      ``since_offset`` (F1, F20). An empty ``worker_ids`` returns
      ``{"workers": {}}`` without calling ``capture_output``.
    * **Legacy path** — when ``_durable_manager`` is not configured,
      returns the original flat ``{wid: {status, output, error,
      exit_code, duration_seconds, metadata}}`` mapping so existing
      callers stay green.
    """
    if _durable_manager is not None:
        workers_out: dict[str, dict[str, object]] = {}
        for wid in worker_ids or []:
            captured: CapturedOutput = _durable_manager.capture_output(
                wid, since_offset=since_offset
            )
            workers_out[wid] = {
                "text": captured.text,
                "next_offset": captured.next_offset,
                "truncated": captured.truncated,
                "pane_alive": captured.pane_alive,
            }
        return {"workers": workers_out}

    if _worker_manager is None:
        raise RuntimeError("worker_manager not configured")

    results = await _worker_manager.collect_results(worker_ids)

    return {
        wid: {
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "metadata": result.metadata or {},
        }
        for wid, result in results.items()
    }


async def worker_close(
    worker_id: str,
    force: bool = False,
) -> _DurableCloseResult | _LegacyCloseResult:
    """Close a worker using two-phase graceful shutdown.

    Soft (default): SIGTERM with 5 s grace window; if the pane is still
    alive after the grace window the controller escalates to SIGKILL
    automatically. ``force=True`` skips the soft phase and sends SIGKILL
    immediately.

    Returns ``{"closed": bool, "exit_code": int | None}`` on the
    durable path. Returns ``{"success": bool, "worker_id": str, "error": str}``
    on the legacy fallback path.
    """
    if _durable_manager is not None:
        cancelled = _durable_manager.cancel(
            worker_id,
            signal="SIGKILL" if force else "soft",
            grace_ms=0 if force else 5_000,
        )
        record = _durable_manager.status(worker_id)
        return {
            "closed": cancelled,
            "exit_code": getattr(record, "last_exit_code", None),
        }
    # Legacy fallback (unchanged shape)
    try:
        await _worker_manager.close_worker(worker_id)
        return {"success": True, "worker_id": worker_id}
    except Exception as e:
        return {"success": False, "worker_id": worker_id, "error": str(e)}


async def worker_close_all() -> dict:
    """Cancel every in-flight durable worker.

    Wire-format note (durable path): returns ``{"closed": [wid, ...]}`` —
    this is a deliberate break from the legacy ``{"closed_count": int}``
    shape so callers can address the closed workers individually. The
    legacy fallback preserves the original ``{"closed_count": int}`` shape
    so existing callers stay green.
    """
    if _durable_manager is not None:
        closed: list[str] = []
        for record in _durable_manager.store.list_all():
            # Cancel only in-flight states; skip terminal ones.
            if record.state in {WorkerLifecycleState.RUNNING, WorkerLifecycleState.READY}:
                _durable_manager.cancel(record.worker_id, signal="soft", grace_ms=5_000)
                closed.append(record.worker_id)
        return {"closed": closed}
    # Legacy fallback (preserves original shape)
    workers_list = await _worker_manager.list_workers()
    worker_ids = [w["worker_id"] for w in workers_list]
    for wid in worker_ids:
        await _worker_manager.close_worker(wid)
    return {"closed_count": len(worker_ids)}


async def worker_health() -> dict:
    """Aggregate durable-record counts by lifecycle state.

    Durable path returns ``{"total": int, "counts": {state: int}}`` with
    every ``WorkerLifecycleState`` value present in ``counts`` (zero
    default). Legacy fallback returns whatever
    ``worker_manager.health_check()`` returns.
    """
    if _durable_manager is not None:
        records = list(_durable_manager.store.list_all())
        counts: dict[str, int] = {state.value: 0 for state in WorkerLifecycleState}
        for record in records:
            counts[record.state] = counts.get(record.state, 0) + 1
        return {"total": len(records), "counts": counts}
    return await _worker_manager.health_check()


def register_worker_tools(
    mcp: FastMCP,
    worker_manager: WorkerManager,
    durable_manager: DurableWorkerManager | None = None,
) -> None:
    """Register worker orchestration tools with MCP server.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP server instance
        worker_manager: WorkerManager instance for backend operations
        durable_manager: Optional DurableWorkerManager for shell worker
            routing. When ``None`` (default), shell workers fall back to
            the legacy ``WorkerManager.spawn_workers`` path.
    """
    global _durable_manager, _worker_manager
    _durable_manager = durable_manager
    _worker_manager = worker_manager

    mcp.tool()(worker_spawn)
    mcp.tool()(worker_monitor)
    mcp.tool()(worker_collect_results)
    mcp.tool()(worker_close)
    mcp.tool()(worker_close_all)
    mcp.tool()(worker_health)

    @mcp.tool()
    async def worker_execute(
        worker_id: str,
        prompt: str,
        timeout: int = 300,
    ) -> dict:
        """Execute task on specific worker.

        Returns the full structured result without silent truncation;
        callers that need a summary should pass the result through
        their own formatter.
        """
        if timeout < 30 or timeout > 3600:
            raise ValueError("timeout must be between 30 and 3600")

        task = {
            "prompt": prompt,
            "timeout": timeout,
        }

        result = await worker_manager.execute_task(worker_id, task)

        return {
            "worker_id": result.worker_id,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "metadata": result.metadata or {},
        }

    @mcp.tool()
    async def worker_execute_batch(
        worker_ids: list[str],
        prompts: list[str],
        timeout: int = 300,
    ) -> list[dict]:
        """Execute tasks on multiple workers concurrently.

        Returns a list of structured results, one per input, in the
        same order as the input worker_ids / prompts.
        """
        if len(worker_ids) != len(prompts):
            raise ValueError("worker_ids and prompts must have same length")

        tasks = [{"prompt": prompt, "timeout": timeout} for prompt in prompts]

        results = await worker_manager.execute_batch(worker_ids, tasks)

        out: list[dict] = []
        for wid, result in results.items():
            out.append(
                {
                    "worker_id": wid,
                    "status": result.status.value,
                    "output": result.output,
                    "error": result.error,
                    "exit_code": result.exit_code,
                    "duration_seconds": result.duration_seconds,
                    "metadata": result.metadata or {},
                }
            )
        return out

    @mcp.tool()
    async def worker_list(
        state: str | None = None,
        worker_id: str | None = None,
    ) -> list[dict]:
        """List workers, optionally filtered by state and/or worker_id.

        When the durable worker manager is configured, the tool reads
        from ``_durable_manager.store.list_all()`` and applies the
        optional ``state`` and ``worker_id`` filters, projecting each
        surviving record to ``{"worker_id": ..., "state": ...}``. When
        the durable manager is absent, the tool falls back to
        ``worker_manager.list_workers()`` so existing callers stay
        green; the legacy path does not apply the new filters.

        Args:
            state: Optional ``WorkerLifecycleState`` value to filter by
                (e.g. ``"ready"``, ``"running"``). Only honored on the
                durable-manager path.
            worker_id: Optional worker id to filter by. Only honored on
                the durable-manager path.
        """
        if _durable_manager is None:
            return await worker_manager.list_workers()
        records = list(_durable_manager.store.list_all())
        # DurableWorkerRecord uses ``use_enum_values=True``, so ``r.state``
        # is already the enum's string value (e.g. "ready"); no .value access.
        if state is not None:
            records = [r for r in records if r.state == state]
        if worker_id is not None:
            records = [r for r in records if r.worker_id == worker_id]
        return [{"worker_id": r.worker_id, "state": r.state} for r in records]
