"""Core application module for Mahavishnu with Oneiric integration.

This module provides the main application class that manages configuration,
repository loading and adapter initialization using Oneiric patterns.
"""

from __future__ import annotations

import asyncio
from asyncio import Semaphore
import logging
from time import time_ns
from typing import TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class _NoOpBudgetStore:
    """No-op :class:`BudgetStore` used when MCP is not configured.

    Listed here (rather than imported) so the watchdog module does
    not have to know about app-private types.
    """

    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def put(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> Any:
        return None

    async def list_keys(self, prefix: str) -> list[str]:
        return []

    async def try_acquire_lease(
        self,
        lease_key: str,
        holder: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        return True

    async def release_lease(self, lease_key: str, holder: str) -> None:
        return None


def _log_budget_watchdog_done(task: asyncio.Task) -> None:
    """Log the outcome of a budget-watchdog asyncio task (mostly for shutdown)."""
    try:
        exc = task.exception()
    except (
        asyncio.CancelledError,
        Exception,  # noqa: BLE001  # background task — broad catch is the documented contract
    ):
        exc = None
    if exc is not None:
        logger.warning("budget.watchdog exited with error: %s", exc)
    else:
        logger.debug("budget.watchdog exited cleanly")


from .bootstrap import init_health_endpoint as _init_health_endpoint_helper
from .bootstrap import init_learning_pipeline as _init_learning_pipeline_helper
from .bootstrap import init_memory_aggregator as _init_memory_aggregator_helper
from .bootstrap import init_observability as _init_observability_helper
from .bootstrap import init_pool_manager as _init_pool_manager_helper
from .bootstrap import init_terminal_manager as _init_terminal_manager_helper
from .bootstrap import initialize_runtime_services as _initialize_runtime_services_helper
from .bootstrap import load_config as _load_config_helper
from .bootstrap import load_repos as _load_repos_helper
from .bootstrap import recover_approvals_from_mcp as _recover_approvals_from_mcp_helper
from .bootstrap import (
    recover_workflow_state_from_mcp as _recover_workflow_state_from_mcp_helper,
)
from .bootstrap import resolve_mcp_url as _resolve_mcp_url_helper
from .circuit_breaker import CircuitBreaker
from .control_surface import (
    get_correlation_status as _get_correlation_status,
)
from .control_surface import (
    get_event_activity as _get_event_activity,
)
from .control_surface import (
    get_fix_trace as _get_fix_trace,
)
from .control_surface import (
    get_recovered_routing_decisions as _get_recovered_routing_decisions,
)
from .control_surface import (
    get_recovery_summary as _get_recovery_summary,
)
from .control_surface import (
    list_pending_approvals as _list_pending_approvals,
)
from .control_surface import (
    record_event_activity as _record_event_activity,
)
from .control_surface import (
    record_fix_trace as _record_fix_trace,
)
from .control_surface import (
    request_approval as _request_approval,
)
from .control_surface import (
    respond_to_approval as _respond_to_approval,
)
from .dependency_waiter import wait_for_dependencies as _wait_for_dependencies_helper
from .errors import AdapterError
from .lifecycle import initialize_worktree_coordinator as _initialize_worktree_coordinator_helper
from .lifecycle import start_learning_pipeline as _start_learning_pipeline_helper
from .lifecycle import start_poller as _start_poller_helper
from .lifecycle import stop_learning_pipeline as _stop_learning_pipeline_helper
from .lifecycle import stop_poller as _stop_poller_helper
from .repo_nicknames import get_repo_nicknames
from .repository_surface import (
    check_user_repo_permission as _check_user_repo_permission_helper,
)
from .repository_surface import get_active_workflows as _get_active_workflows_helper
from .repository_surface import get_all_nicknames as _get_all_nicknames_helper
from .repository_surface import get_all_repo_paths as _get_all_repo_paths_helper
from .repository_surface import get_all_repos as _get_all_repos_helper
from .repository_surface import get_repos as _get_repos_helper
from .repository_surface import get_repos_by_role as _get_repos_by_role_helper
from .repository_surface import get_role_by_name as _get_role_by_name_helper
from .repository_surface import get_roles as _get_roles_helper
from .repository_surface import is_healthy as _is_healthy_helper
from .repository_surface import persist_workflow_end as _persist_workflow_end_helper
from .repository_surface import persist_workflow_start as _persist_workflow_start_helper
from .repository_surface import (
    update_workflow_runtime_gauges as _update_workflow_runtime_gauges_helper,
)
from .routing import RoutingStrategy
from .workflow_execution import (
    check_dependency_health as _check_dependency_health_helper,
)
from .workflow_execution import (
    create_session_checkpoint as _create_session_checkpoint_helper,
)
from .workflow_execution import (
    execute_parallel_workflow as _execute_parallel_workflow_helper,
)
from .workflow_execution import (
    execute_workflow_parallel as _execute_workflow_parallel_helper,
)
from .workflow_execution import (
    execute_workflow_with_fallback as _execute_workflow_with_fallback_helper,
)
from .workflow_execution import (
    execute_workflow_with_routing as _execute_workflow_with_routing_helper,
)
from .workflow_execution import (
    finalize_workflow_execution as _finalize_workflow_execution_helper,
)
from .workflow_execution import (
    handle_workflow_execution_error as _handle_workflow_execution_error_helper,
)
from .workflow_execution import (
    initialize_workflow_state as _initialize_workflow_state_helper,
)
from .workflow_execution import prepare_execution as _prepare_execution_helper
from .workflow_execution import process_single_repo as _process_single_repo_helper
from .workflow_execution import (
    validate_pre_execution_qc as _validate_pre_execution_qc_helper,
)

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager
    from .adapters.base import OrchestratorAdapter
    from .config import MahavishnuSettings

try:
    from ..terminal.manager import TerminalManager
except ImportError:  # pragma: no cover - optional runtime dependency
    TerminalManager = None  # ty: ignore[invalid-assignment]


class MahavishnuApp:
    """Main application class for Mahavishnu orchestrator.

    This class provides:
    - Configuration loading from Oneiric-compatible sources
    - Repository manifest loading from ecosystem.yaml (falls back to repos.yaml)
    - Adapter initialization and management
    - Type-safe operations throughout
    - Concurrency control for workflow execution

    Example:
        >>> from mahavishnu.core import MahavishnuApp
        >>> app = MahavishnuApp()
        >>> repos = app.get_repos(tag="backend")
        >>> result = app.execute_workflow(
        ...     task={"type": "code_sweep"},
        ...     adapter_name="langgraph",
        ...     repos=repos,
        ... )
    """

    # Runtime attributes set by _initialize_runtime_services / lifecycle helpers
    terminal_manager: Any
    session_buddy: Any
    workflow_state_manager: Any
    rbac_manager: Any
    worktree_coordinator: Any
    pool_manager: Any
    approval_manager: Any
    coordination_manager: Any
    error_recovery_manager: Any
    monitoring_service: Any
    opensearch_integration: Any
    budget_watchdog_task: asyncio.Task | None
    budget_watchdog_stop: asyncio.Event | None
    budget_watchdog_store: Any
    budget_watchdog_metrics: Any
    runtime_facts_lock: asyncio.Lock
    runtime_facts_watcher: asyncio.Task | None

    @classmethod
    def load(cls) -> MahavishnuApp:
        """Load Mahavishnu application with default configuration.

        This is a convenience classmethod that creates a new instance
        with configuration loaded from Oneiric-compatible sources.

        Returns:
            Initialized MahavishnuApp instance

        Raises:
            ConfigurationError: If configuration loading fails
        """
        return cls()

    def __init__(self, config: MahavishnuSettings | None = None) -> None:
        """Initialize Mahavishnu application.

        Args:
            config: Optional configuration. If not provided, loads from
                    Oneiric-compatible sources (YAML + environment).

        Raises:
            ConfigurationError: If configuration loading fails
        """
        self.config = config or self._load_config()
        self.adapters: dict[str, OrchestratorAdapter] = {}
        self.mcp_url = self._resolve_mcp_url()
        self._load_repos()
        self._initialize_adapters()

        # Round-5 review fix (m3): per-instance fallback timestamp for
        # ``core.health.merge_driver_health()``. Previously this was a
        # module-global in ``mahavishnu.core.health`` — two ``MahavishnuApp``
        # instances in the same process (CLI test + server daemon,
        # ``unittest.TestCase`` fixtures with shared state, etc.) would
        # stomp each other's fallback history. Stamp reads/writes go
        # through ``_resolve_degraded_since`` / ``_assign_degraded_since``
        # which transparently fall back to the module-global when this
        # attribute is missing (preserves CLI / script callers).
        self._degraded_since: datetime | None = None

        # Set application context for dependency injection
        self._set_app_context()

        # Initialize concurrency control
        self.semaphore = Semaphore(self.config.max_concurrent_workflows)

        self.active_workflows: set[str] = set()
        self.workflow_queue: asyncio.Queue = asyncio.Queue()

        # In-flight dedup lock for ``report_runtime_facts``. Concurrent
        # pushes are dropped immediately so a reconfigure tick that
        # arrives while a boot push is still in flight never overlaps.
        self.runtime_facts_lock = asyncio.Lock()
        self.runtime_facts_watcher = None

        # Initialize production features
        self.circuit_breaker = CircuitBreaker(
            threshold=self.config.resilience.circuit_breaker_threshold,
            timeout=int(self.config.resilience.retry_base_delay * 10),  # Convert to int
        )

        # Initialize observability and health endpoint
        self.observability = self._init_observability()
        self._health_endpoint = self._init_health_endpoint()

        # Initialize remaining runtime services
        self._initialize_runtime_services()

    async def start_poller(self) -> None:
        """Start Session-Buddy poller if configured.

        This method should be called after the async event loop is running.
        It's safe to call multiple times (idempotent).

        Example:
            >>> app = MahavishnuApp()
            >>> await app.start_poller()  # Start polling
        """
        await _start_poller_helper(self)

    async def start_runtime_facts_watcher(self) -> None:
        """Phase 2 / Task 2.2 — install the Oneiric reconfigure trigger.

        Uses an httpx POST poll loop (NOT Oneiric's ``SelectionWatcher``)
        to detect layer-change ticks on the Oneiric MCP endpoint. On
        each change, invokes :meth:`report_runtime_facts` which uses
        ``self.runtime_facts_lock`` for in-flight de-dup (a push already
        in flight causes the next call to be dropped).

        The poll loop:
        - Probes Oneiric reachability (5 s timeout); does NOT block boot
          if the endpoint is unreachable.
        - Polls every 5.0 seconds (default; matches the deleted
          ``RUNTIME_FACTS_WATCHER_INTERVAL_SECONDS`` constant).
        - Uses ``httpx.AsyncClient`` — no ``oneiric.*`` imports.
        - Detects layer-change via ``cycles_total`` comparison (falls
          back to response-text hash when the field is unavailable).
        - On change, awaits ``self.report_runtime_facts()`` which is
          gated by the in-flight dedup lock.

        PUBLIC-SURFACE CONTRACT (v3 critical): this module does NOT
        import anything from ``oneiric.*`` internals. The httpx POST
        loop is the only allowed mechanism.
        """
        import os

        import httpx

        logger = logging.getLogger("mahavishnu.app.runtime_facts_watcher")
        poll_interval_seconds = 5.0
        watcher_name = "runtime-facts-watcher"

        oneiric_url = os.environ.get(self.ONEIRIC_ENV_VAR, self.ONEIRIC_MCP_URL)

        async def _poll_loop() -> None:
            """Background poll loop: detect layer-change ticks on Oneiric.

            Each tick POSTs ``tools/call oneiric_get_health`` to the
            Oneiric MCP endpoint and compares ``cycles_total`` against
            the previous tick. On change, awaits
            ``self.report_runtime_facts()`` which uses the in-flight
            lock to drop a tick if a previous push is still running.
            """
            last_signature: int | None = None
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    while True:
                        signature: int | None = None
                        try:
                            response = await client.post(
                                oneiric_url,
                                json={
                                    "jsonrpc": "2.0",
                                    "id": "mahavishnu-poll",
                                    "method": "tools/call",
                                    "params": {
                                        "name": "oneiric_get_health",
                                        "arguments": {},
                                    },
                                },
                            )
                            response.raise_for_status()
                            data = response.json()
                            # Prefer cycles_total as the change indicator;
                            # fall back to response-text hash when the JSON
                            # shape is unexpected.
                            if isinstance(data, dict) and "result" in data:
                                result = data["result"]
                                if isinstance(result, dict) and "cycles_total" in result:
                                    signature = int(result["cycles_total"])
                                else:
                                    signature = hash(response.text)
                            else:
                                signature = hash(response.text)
                        except Exception:  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                            # On any failure, fall through to push so we
                            # still attempt to refresh the Oneiric view.
                            signature = None

                        if signature != last_signature:
                            last_signature = signature
                            try:
                                await self.report_runtime_facts()
                            except (
                                Exception
                            ):  # background task — broad catch is the documented contract
                                logger.exception("runtime-facts reconfigure push failed")

                        await asyncio.sleep(poll_interval_seconds)
            except asyncio.CancelledError:
                logger.debug("runtime-facts poll loop cancelled")
                raise
            except Exception:  # background task — broad catch is the documented contract
                logger.exception("runtime-facts poll loop crashed; reconfigure hook disabled")

        # Probe Oneiric reachability first (do NOT block boot if unreachable)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                probe = await client.post(
                    oneiric_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": "mahavishnu-probe",
                        "method": "tools/call",
                        "params": {
                            "name": "oneiric_get_health",
                            "arguments": {},
                        },
                    },
                )
                probe.raise_for_status()
        except Exception as exc:  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(
                "runtime-facts watcher probe failed; reconfigure hook disabled: %s",
                exc,
            )
            self.runtime_facts_watcher = None
            return

        # Start the poll loop as a background task
        self.runtime_facts_watcher = asyncio.create_task(
            _poll_loop(),
            name=watcher_name,
        )
        logger.info(
            "runtime-facts-watcher component=mahavishnu status=ok name=%s poll_interval=%.1f",
            watcher_name,
            poll_interval_seconds,
        )

    async def wait_for_dependencies(self) -> bool:
        """Wait for all configured dependencies to become healthy.

        Uses exponential backoff for retries. Required dependencies will
        block startup if unavailable. Optional dependencies will be skipped
        after a few failed attempts.

        This method should be called after app initialization but before
        starting to accept work.

        Returns:
            True if all required dependencies are healthy, False otherwise

        Example:
            >>> app = MahavishnuApp()
            >>> if not await app.wait_for_dependencies():
            ...     raise RuntimeError("Required dependencies unavailable")
        """
        return await _wait_for_dependencies_helper(self)

    @property
    def health_endpoint(self):
        """Get the health endpoint for this service.

        Returns the HealthEndpoint instance for exposing /health and /ready
        endpoints. Returns None if health check is disabled.

        Returns:
            HealthEndpoint instance or None
        """
        return self._health_endpoint

    async def stop_poller(self) -> None:
        """Stop Session-Buddy poller and clear transitional metrics state.

        This method should be called before shutting down the application.
        It's safe to call multiple times (idempotent).

        Example:
            >>> await app.stop_poller()  # Stop polling
        """
        await _stop_poller_helper(self)

    async def start_budget_watchdog(self) -> None:
        """Start the Phase 3 budget watchdog as an asyncio background task.

        Idempotent — calling twice is a no-op so the lifespan context
        can call this on every cold-start. The watchdog polls once a
        minute (60s) against MCP and enforces per-run budget shapes
        declared via the ``budget_enforce`` MCP tool.

        Failures during startup are logged and swallowed — the
        watchdog is allowed to be unhealthy without blocking the
        rest of the app.
        """
        if getattr(self, "budget_watchdog_task", None) is not None:
            return

        # Lazy imports keep the ``mahavishnu.core`` module thin and let
        # test code substitute the watchdog + store symbols.
        from .budget_watchdog import (
            MCPBudgetStore,
            WatchdogConfig,
            WatchdogMetrics,
            run_watchdog,
        )

        store: Any = None
        mcp_client = getattr(self, "_mcp_client", None) or getattr(self, "mcp_client", None)
        if mcp_client is not None and hasattr(mcp_client, "call_tool"):
            try:
                store = MCPBudgetStore(mcp_client)
            except Exception as exc:  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(
                    "budget.watchdog: failed to build MCPBudgetStore: %s",
                    exc,
                )
                store = None

        async def _noop_usage_source(_workflow_id: str) -> None:
            """Default usage source — explicit no-op.

            The real implementation reads the worker manager for the
            latest tokens/turns and computes wallclock from
            ``record.started_at``. With no worker registered yet, the
            implicit ``None`` return lets the watchdog skip cycles cleanly.
            """

        stop_event = asyncio.Event()
        metrics = WatchdogMetrics()
        config = WatchdogConfig(
            holder=f"mahavishni-{uuid.uuid4().hex[:8]}",
        )
        task = asyncio.create_task(
            run_watchdog(
                config=config,
                store=store if store is not None else _NoOpBudgetStore(),
                usage_source=_noop_usage_source,
                metrics=metrics,
                stop_event=stop_event,
            ),
            name="budget-watchdog",
        )
        # Quiet CancelledError on shutdown — re-raised through the task
        # result in the supervisor.
        task.add_done_callback(_log_budget_watchdog_done)

        self.budget_watchdog_task = task
        self.budget_watchdog_stop = stop_event
        self.budget_watchdog_metrics = metrics
        self.budget_watchdog_store = store
        logger.info("budget.watchdog.started")

    async def stop_budget_watchdog(self) -> None:
        """Stop the budget watchdog and await its task to drain.

        Cancels the underlying task and waits for it to exit; safe to
        call when the watchdog was never started (no-op).
        """
        task: asyncio.Task | None = getattr(self, "budget_watchdog_task", None)
        stop_event: asyncio.Event | None = getattr(self, "budget_watchdog_stop", None)
        if task is None or stop_event is None:
            return
        stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            logger.warning("budget.watchdog: task did not exit in time; cancelling")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("budget.watchdog: shutdown acknowledged")
            except Exception as exc:  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning("budget.watchdog: shutdown error: %s", exc)
        except asyncio.CancelledError:
            logger.debug("budget.watchdog: stop cancelled before drain")
        except Exception as exc:  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning("budget.watchdog: unexpected shutdown error: %s", exc)
        self.budget_watchdog_task = None
        self.budget_watchdog_stop = None

    async def start_change_point_tick_loop(self) -> Any:
        """Start the change-point detector tick loop from an async path.

        R3-C1 (round-3 review): the bootstrap was calling
        ``manager.start_change_point_tick_loop`` from a sync path
        where ``asyncio.get_running_loop()`` raises ``RuntimeError``,
        so the tick loop never started. This async method is the
        authoritative call site — start it from ``app.start()``
        or any other async lifecycle hook.

        2026-10-24: ``ObservabilityManager.start_change_point_tick_loop``
        is now synchronous and returns the ``asyncio.Task`` it created.
        It used to be ``async def``, and this call site did not
        ``await`` it — so the "task" stored in
        ``self._change_point_tick_task`` was a *coroutine object*. The
        tick loop therefore never started, the coroutine was collected
        unawaited (a RuntimeWarning on every CLI run), and the stop
        path called ``coroutine.cancel()``, which does not exist.
        Calling a synchronous method removes that failure mode.

        Returns the asyncio.Task; callers should retain it for
        cancellation via ``stop_change_point_tick_loop``.
        """
        if not hasattr(self, "observability") or self.observability is None:
            raise RuntimeError(
                "ObservabilityManager not initialized; call init_observability first."
            )

        # R3-C2: pass a real metric_source that reads pool queue depths
        # from PoolManager (proxy: worker counts until real queue depth
        # signal lands).
        def _pool_depths() -> dict[str, float]:
            manager = getattr(self, "pool_manager", None)
            if manager is None:
                return {}
            return manager.get_pool_queue_depths()

        self._change_point_tick_task = self.observability.start_change_point_tick_loop(
            metric_source=_pool_depths,
        )
        return self._change_point_tick_task

    async def stop_change_point_tick_loop(self) -> None:
        """Cancel the change-point tick loop task."""
        if not hasattr(self, "observability") or self.observability is None:
            return
        await self.observability.stop_change_point_tick_loop(
            task=getattr(self, "_change_point_tick_task", None),
        )
        self._change_point_tick_task = None

    async def start_learning_pipeline(self) -> None:
        """Start the learning pipeline if configured.

        This method should be called after the async event loop is running.
        It's safe to call multiple times (idempotent).

        Example:
            >>> app = MahavishnuApp()
            >>> await app.start_learning_pipeline()
        """
        await _start_learning_pipeline_helper(self)

    async def stop_learning_pipeline(self) -> None:
        """Stop the learning pipeline gracefully.

        This method should be called before shutting down the application.
        It's safe to call multiple times (idempotent).

        Example:
            >>> await app.stop_learning_pipeline()
        """
        await _stop_learning_pipeline_helper(self)

    async def initialize_worktree_coordinator(self) -> None:
        """Initialize WorktreeCoordinator after async event loop is running.

        This method should be called after the async event loop is running.
        It's safe to call multiple times (idempotent).

        Example:
            >>> app = MahavishnuApp()
            >>> await app.initialize_worktree_coordinator()
        """
        await _initialize_worktree_coordinator_helper(self)

    def _init_terminal_manager(self) -> TerminalManager | None:
        return _init_terminal_manager_helper(self)  # type: ignore[no-any-return]

    def _initialize_runtime_services(self):
        return _initialize_runtime_services_helper(self)

    def _init_observability(self):
        return _init_observability_helper(self)

    def _init_health_endpoint(self):
        return _init_health_endpoint_helper(self)

    def _init_pool_manager(self):
        return _init_pool_manager_helper(self)

    def _init_memory_aggregator(self):
        return _init_memory_aggregator_helper(self)

    def _init_learning_pipeline(self):
        return _init_learning_pipeline_helper(self)

    def _load_config(self) -> MahavishnuSettings:
        return _load_config_helper()

    def _load_repos(self) -> None:
        _load_repos_helper(self)

    def _initialize_adapters(self) -> None:
        from .bootstrap import initialize_adapters as _initialize_adapters_helper

        _initialize_adapters_helper(self)

    def _set_app_context(self) -> None:
        from .bootstrap import set_app_context as _set_app_context_helper

        _set_app_context_helper(self)

    def _resolve_mcp_url(self) -> str:
        return _resolve_mcp_url_helper(self.config)

    async def _recover_workflow_state_from_mcp(self) -> None:
        await _recover_workflow_state_from_mcp_helper(self)

    async def _recover_approvals_from_mcp(self) -> None:
        await _recover_approvals_from_mcp_helper(self)

    async def get_recovery_summary(self) -> dict[str, Any]:
        return await _get_recovery_summary(self)

    async def get_recovered_routing_decisions(
        self,
        task_class: str | None = None,
    ) -> list[dict[str, Any]]:
        return await _get_recovered_routing_decisions(self, task_class=task_class)

    def record_event_activity(self, envelope: Any) -> None:
        _record_event_activity(self, envelope)

    def get_event_activity(self, limit: int = 25) -> list[dict[str, Any]]:
        return _get_event_activity(self, limit=limit)

    def record_fix_trace(
        self,
        correlation_id: str,
        stage: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _record_fix_trace(self, correlation_id, stage, message, metadata)

    def get_fix_trace(
        self,
        correlation_id: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        return _get_fix_trace(self, correlation_id=correlation_id, limit=limit)

    def get_correlation_status(self, correlation_id: str | None = None) -> dict[str, Any]:
        return _get_correlation_status(self, correlation_id=correlation_id)

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        return _list_pending_approvals(self)

    def request_approval(
        self,
        approval_type: str,
        context: dict[str, Any],
        options: list[Any] | None = None,
        timeout_minutes: int | None = None,
    ) -> dict[str, Any]:
        return _request_approval(
            self,
            approval_type=approval_type,
            context=context,
            options=options,
            timeout_minutes=timeout_minutes,
        )

    def respond_to_approval(
        self,
        request_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        return _respond_to_approval(
            self,
            request_id=request_id,
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

    def _persist_workflow_start(
        self, execution_id: str, workflow_name: str, metadata: dict
    ) -> None:
        """Fire-and-forget: record workflow start in MCP."""
        _persist_workflow_start_helper(self, execution_id, workflow_name, metadata)

    def _persist_workflow_end(
        self, execution_id: str, workflow_name: str, status: str, error: str | None = None
    ) -> None:
        """Fire-and-forget: record workflow completion/failure in MCP."""
        _persist_workflow_end_helper(self, execution_id, workflow_name, status, error)

    def get_repos(
        self, tag: str | None = None, role: str | None = None, user_id: str | None = None
    ) -> list[str]:
        """Get repository paths based on tag, role, or return all.

        Args:
            tag: Optional tag to filter repositories
            role: Optional role to filter repositories
            user_id: Optional user ID for permission checking

        Returns:
            List of repository paths

        Raises:
            ValidationError: If tag or role is invalid
        """
        return _get_repos_helper(self, tag=tag, role=role, user_id=user_id)

    def _check_user_repo_permission(self, user_id: str, repo_path: str) -> bool:
        """Check if user has read permission for repository.

        Handles both sync and async contexts safely. When called from an async
        context, uses the running event loop. When called from sync context,
        creates a new event loop.
        """
        return _check_user_repo_permission_helper(self, user_id, repo_path)

    def get_all_repos(self) -> list[dict[str, Any]]:
        """Get all repositories with full metadata.

        Returns:
            List of repository dictionaries with path, tags, description
        """
        return _get_all_repos_helper(self)

    def get_all_repo_paths(self) -> list[str]:
        """Get all repository paths.

        Returns:
            List of all repository paths
        """
        return _get_all_repo_paths_helper(self)

    def get_roles(self) -> list[dict[str, Any]]:
        """Get all available roles.

        Returns:
            List of role definitions with name, description, tags, duties, capabilities
        """
        return _get_roles_helper(self)

    def get_role_by_name(self, role_name: str) -> dict[str, Any] | None:
        """Get a specific role by name.

        Args:
            role_name: Name of the role to retrieve

        Returns:
            Role definition if found, None otherwise
        """
        return _get_role_by_name_helper(self, role_name)

    def get_repos_by_role(self, role_name: str) -> list[dict[str, Any]]:
        """Get all repositories with a specific role.

        Args:
            role_name: Name of the role to filter by

        Returns:
            List of repository dictionaries with matching role

        Raises:
            ValidationError: If role_name is not found in role taxonomy
        """
        return _get_repos_by_role_helper(self, role_name)

    @staticmethod
    def get_repo_nicknames(repo: dict[str, Any]) -> list[str]:
        """Return normalized nickname aliases for a repository config."""
        return get_repo_nicknames(repo)

    def get_all_nicknames(self) -> dict[str, str]:
        """Get all repository nicknames.

        Returns:
            Dictionary mapping nickname to full repository name
        """
        return _get_all_nicknames_helper(self)

    async def is_healthy(self) -> bool:
        """Check if application is healthy.

        Returns:
            True if application is healthy (all adapters accessible)
        """
        return await _is_healthy_helper(self)

    async def get_active_workflows(self) -> list[str]:
        """Get list of active workflow IDs.

        Queries the workflow state manager for workflows that are currently
        in RUNNING status and returns their IDs.

        Returns:
            List of active workflow IDs
        """
        return await _get_active_workflows_helper(self)

    async def get_metrics(self) -> dict[str, Any]:
        """Return a snapshot of key system metrics for monitoring dashboards."""
        pool_manager = getattr(self, "pool_manager", None)
        worker_manager = getattr(self, "_worker_manager", None)
        adapter_health = "healthy" if await self.is_healthy() else "degraded"
        pools_active = len(getattr(pool_manager, "_pools", {})) if pool_manager else 0
        workers_running = len(getattr(worker_manager, "_workers", {})) if worker_manager else 0
        return {
            "workflows_active": len(self.active_workflows),
            "workflows_completed": 0,
            "pools_active": pools_active,
            "workers_running": workers_running,
            "adapter_health": adapter_health,
        }

    def _update_workflow_runtime_gauges(self) -> None:
        """Update shared Prometheus gauges for workflow runtime state."""
        _update_workflow_runtime_gauges_helper(self)

    async def execute_workflow(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow using specified adapter.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)
            user_id: Optional user ID for permission checking

        Returns:
            Workflow execution result

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
        # Validate adapter and prepare for execution
        adapter, validated_repos = await self._prepare_execution(adapter_name, task, repos, user_id)

        # Execute with adapter using parallel processing
        try:
            # Add observability if enabled
            if self.observability:
                workflow_counter = self.observability.create_workflow_counter()
                if workflow_counter:
                    workflow_counter.add(
                        1, {"adapter": adapter_name, "task_type": task.get("type", "unknown")}
                    )

            result = await adapter.execute(task, validated_repos)
            return result
        except Exception as e:  # background task — broad catch is the documented contract
            # Record error in observability if enabled
            if self.observability:
                error_counter = self.observability.create_error_counter()
                if error_counter:
                    error_counter.add(1, {"adapter": adapter_name, "error_type": type(e).__name__})

            # Log error to OpenSearch
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_{task.get('type', 'default')}_single"
            await self.opensearch_integration.log_error(
                workflow_id=workflow_id, error_msg=str(e), adapter=adapter_name
            )

            raise AdapterError(
                message=f"Adapter execution failed: {e}",
                details={
                    "adapter": adapter_name,
                    "task": task,
                    "repos_count": len(validated_repos),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e

    async def _prepare_execution(
        self, adapter_name: str, task: dict[str, Any], repos: list[str] | None, user_id: str | None
    ) -> tuple[OrchestratorAdapter, list[str]]:
        """Helper method to validate adapter and prepare for execution."""
        return await _prepare_execution_helper(self, adapter_name, task, repos, user_id)

    async def _check_dependency_health(self) -> None:
        """Check health of QC and Session-Buddy before execution.

        QC is a blocking dependency: unhealthy + enabled raises ExternalServiceError.
        Session-Buddy is non-blocking: unhealthy logs a warning and degrades silently.
        """
        await _check_dependency_health_helper(self)

    # ========================================================================
    # REFACTORED: execute_workflow_parallel helper methods
    # ========================================================================

    async def _initialize_workflow_state(
        self,
        task: dict[str, Any],
        adapter_name: str,
        validated_repos: list[str],
    ) -> str:
        """Initialize workflow state, logging, and observability.

        Args:
            task: Task specification
            adapter_name: Name of adapter being used
            validated_repos: List of validated repository paths

        Returns:
            workflow_id: Unique workflow identifier
        """
        return await _initialize_workflow_state_helper(self, task, adapter_name, validated_repos)

    async def _validate_pre_execution_qc(
        self, workflow_id: str, validated_repos: list[str]
    ) -> None:
        """Validate pre-execution quality control checks.

        Args:
            workflow_id: Workflow identifier
            validated_repos: List of validated repository paths

        Raises:
            ValidationError: If QC check fails
        """
        await _validate_pre_execution_qc_helper(self, workflow_id, validated_repos)

    async def _create_session_checkpoint(
        self, task: dict[str, Any], adapter_name: str, validated_repos: list[str]
    ) -> str | None:
        """Create session checkpoint if enabled.

        Args:
            task: Task specification
            adapter_name: Name of adapter being used
            validated_repos: List of validated repository paths

        Returns:
            checkpoint_id: Checkpoint ID if created, None otherwise
        """
        return await _create_session_checkpoint_helper(self, task, adapter_name, validated_repos)

    async def _process_single_repo(
        self,
        adapter: OrchestratorAdapter,
        task: dict[str, Any],
        adapter_name: str,
        workflow_id: str,
        repo_path: str,
        total_repos: int,
        semaphore: Semaphore,
        progress_callback=None,
    ) -> Any:
        """Process a single repository with circuit breaker and observability.

        Args:
            adapter: Orchestrator adapter instance
            task: Task specification
            adapter_name: Name of adapter being used
            workflow_id: Workflow identifier
            repo_path: Repository path to process
            total_repos: Total number of repos (for progress tracking)
            semaphore: Semaphore for concurrency control
            progress_callback: Optional progress callback

        Returns:
            Result from adapter execution

        Raises:
            Exception: If execution fails (propagated for error handling)
        """
        return await _process_single_repo_helper(
            self,
            adapter=adapter,
            task=task,
            adapter_name=adapter_name,
            workflow_id=workflow_id,
            repo_path=repo_path,
            total_repos=total_repos,
            semaphore=semaphore,
            progress_callback=progress_callback,
        )

    async def _execute_parallel_workflow(
        self,
        adapter: OrchestratorAdapter,
        task: dict[str, Any],
        adapter_name: str,
        workflow_id: str,
        validated_repos: list[str],
        progress_callback=None,
    ) -> tuple[float, list[Any], list[dict[str, Any]]]:
        """Execute workflow across repos in parallel with observability.

        Args:
            adapter: Orchestrator adapter instance
            task: Task specification
            adapter_name: Name of adapter being used
            workflow_id: Workflow identifier
            validated_repos: List of validated repository paths
            progress_callback: Optional progress callback

        Returns:
            Tuple of (execution_time, successful_results, errors)
        """
        return await _execute_parallel_workflow_helper(
            self,
            adapter=adapter,
            task=task,
            adapter_name=adapter_name,
            workflow_id=workflow_id,
            validated_repos=validated_repos,
            progress_callback=progress_callback,
        )

    async def _finalize_workflow_execution(
        self,
        workflow_id: str,
        adapter_name: str,
        task: dict[str, Any],
        validated_repos: list[str],
        execution_time: float,
        successful_results: list[Any],
        errors: list[dict[str, Any]],
        checkpoint_id: str | None,
    ) -> dict[str, Any]:
        """Finalize workflow execution with logging and checkpoint updates.

        Args:
            workflow_id: Workflow identifier
            adapter_name: Name of adapter being used
            task: Task specification
            validated_repos: List of validated repository paths
            execution_time: Total execution time in seconds
            successful_results: List of successful results
            errors: List of error dictionaries
            checkpoint_id: Optional checkpoint ID for session management

        Returns:
            Final workflow summary dictionary
        """
        return await _finalize_workflow_execution_helper(
            self,
            workflow_id=workflow_id,
            adapter_name=adapter_name,
            task=task,
            validated_repos=validated_repos,
            execution_time=execution_time,
            successful_results=successful_results,
            errors=errors,
            checkpoint_id=checkpoint_id,
        )

    async def _handle_workflow_execution_error(
        self,
        workflow_id: str,
        adapter_name: str,
        task: dict[str, Any],
        validated_repos: list[str],
        error: Exception,
        checkpoint_id: str | None,
    ) -> None:
        """Handle workflow execution error with logging and state updates.

        Args:
            workflow_id: Workflow identifier
            adapter_name: Name of adapter being used
            task: Task specification
            validated_repos: List of validated repository paths
            error: The exception that occurred
            checkpoint_id: Optional checkpoint ID for session management

        Raises:
            AdapterError: Always raises with detailed error information
        """
        await _handle_workflow_execution_error_helper(
            self,
            workflow_id=workflow_id,
            adapter_name=adapter_name,
            task=task,
            validated_repos=validated_repos,
            error=error,
            checkpoint_id=checkpoint_id,
        )

    # ========================================================================
    # REFACTORED: execute_workflow_parallel (main orchestrator)
    # ========================================================================

    async def execute_workflow_parallel(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        progress_callback=None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow in parallel across repositories with progress reporting.

        .. note:: **Golden Path**: Prefer ``mahavishnu workflow sweep`` (CLI) or
           ``trigger_workflow`` MCP tool over calling this method directly.
           See ``docs/reports/golden-paths-guide.md`` for canonical pathways.

        This refactored method orchestrates workflow execution through focused helper methods,
        following the Single Responsibility Principle for improved maintainability.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)
            progress_callback: Optional callback function to report progress
            user_id: Optional user ID for permission checking

        Returns:
            Workflow execution result with timing and performance metrics

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
        # ty: ignore[invalid-return-type] — helper may return None when caller
        # substitutes a swallowing error handler (matches existing
        # ``# type: ignore[no-any-return]`` at workflow_execution.py:536).
        return await _execute_workflow_parallel_helper(
            self,
            task=task,
            adapter_name=adapter_name,
            repos=repos,
            progress_callback=progress_callback,
            user_id=user_id,
        )

    async def execute_workflow_with_fallback(
        self,
        task: dict[str, Any],
        repos: list[str],
        adapter_preference: list[str] | None = None,
        routing_strategy: RoutingStrategy = RoutingStrategy.BALANCED,
        enable_cost_tracking: bool = False,
    ) -> dict[str, Any]:
        """Execute workflow with fallback chain.

        Uses the TaskRouter to generate a fallback chain of adapters and tries
        each one in order until one succeeds or all fail.

        Args:
            task: Task definition with 'type' and 'params' keys
            repos: Repository paths to execute on
            adapter_preference: Preferred adapters in order (optional)
            routing_strategy: Routing strategy for adapter selection
            enable_cost_tracking: Track execution costs (optional)

        Returns:
            Result dictionary with:
                - success: Whether execution succeeded
                - adapter_used: The adapter that succeeded (or None)
                - fallback_chain: List of tried adapters
                - repo_results: Results from successful execution
                - errors: List of (adapter, error) tuples if all failed

        Example:
            >>> result = await app.execute_workflow_with_fallback(
            ...     task={"type": "code_sweep", "params": {}},
            ...     repos=["org/repo1", "org/repo2"],
            ...     adapter_preference=["agno", "prefect"],
            ... )
            >>> if result["success"]:
            ...     print(f"Used adapter: {result['adapter_used']}")
        """
        return await _execute_workflow_with_fallback_helper(
            self,
            task=task,
            repos=repos,
            adapter_preference=adapter_preference,
            routing_strategy=routing_strategy,
            enable_cost_tracking=enable_cost_tracking,
        )

    async def execute_workflow_with_routing(
        self,
        task: dict[str, Any],
        repos: list[str],
        routing_strategy: str = "balanced",
        enable_fallback: bool = True,
    ) -> dict[str, Any]:
        """Execute workflow with adaptive routing.

        Uses the TaskRouter to select the optimal adapter based on the
        routing strategy. Optionally enables fallback chain execution.

        Args:
            task: Task definition with 'type' and 'params' keys
            repos: Repository paths to execute on
            routing_strategy: Strategy name ("cost", "latency", "success_rate", "balanced")
            enable_fallback: Enable fallback chain if primary adapter fails

        Returns:
            Execution result dictionary with:
                - success: Whether execution succeeded
                - adapter_used: The adapter that was used
                - repo_results: Results from execution
                - fallback_chain: List of adapters tried (if fallback enabled)

        Example:
            >>> result = await app.execute_workflow_with_routing(
            ...     task={"type": "rag_query", "params": {"query": "API docs"}},
            ...     repos=["org/docs"],
            ...     routing_strategy="latency",
            ...     enable_fallback=True,
            ... )
        """
        return await _execute_workflow_with_routing_helper(
            self,
            task=task,
            repos=repos,
            routing_strategy=routing_strategy,
            enable_fallback=enable_fallback,
        )

    # Phase 2 / Task 2.3 — push per-adapter runtime facts to Oneiric.
    ONEIRIC_MCP_URL = "http://127.0.0.1:8681/mcp"
    ONEIRIC_ENV_VAR = "MAHAVISHNU__ONBOARDING__ONEIRIC_URL"
    ONEIRIC_TIMEOUT_ENV_VAR = "MAHAVISHNU__ONBOARDING__ONEIRIC_TIMEOUT_SECONDS"
    DEFAULT_PUSH_TIMEOUT_SECONDS = 5.0

    async def report_runtime_facts(self) -> None:
        """Push each registered adapter's runtime facts to Oneiric via JSON-RPC.

        For each entry in ``self.adapters`` (engine adapters registered by
        :meth:`_initialize_adapters`), build the per-adapter runtime block
        via :class:`RuntimeFactsBuilder` (legacy wire shape), translate it
        into the Oneiric envelope (constructed HERE, not in the builder),
        and POST it to the Oneiric MCP endpoint at
        ``MAHAVISHNU__ONBOARDING__ONEIRIC_URL`` (default
        ``http://127.0.0.1:8681/mcp``).

        In-flight de-dup: ``self.runtime_facts_lock`` is acquired before
        the push loop. If a previous push is still running when this
        method is called (e.g. a reconfigure tick from
        :meth:`start_runtime_facts_watcher`'s poll loop arrives during
        a boot push), the new call returns immediately without
        overlapping. This is implemented as a single inline
        ``asyncio.Lock`` on the app instance.

        Each push is wrapped in ``self.circuit_breaker.call`` so a flaky
        Oneiric instance trips the breaker per-adapter (one bad adapter
        does not starve the others). Push failure MUST NOT block boot —
        every ``except`` branch logs and continues, leaving
        ``self.adapters`` (canonical) untouched.

        Structured log line:
        ``runtime-push component=mahavishnu adapter=<key> status=ok|fail``.
        """
        import os
        import uuid

        import httpx

        from .runtime_facts import RuntimeFactsBuilder

        logger = logging.getLogger("mahavishnu.app.report_runtime_facts")

        # In-flight de-dup: drop the call if a push is already running.
        if self.runtime_facts_lock.locked():
            logger.debug("runtime-facts: push already in flight, dropping concurrent call")
            return
        async with self.runtime_facts_lock:
            oneiric_url = os.environ.get(self.ONEIRIC_ENV_VAR, self.ONEIRIC_MCP_URL)
            try:
                timeout_seconds = float(
                    os.environ.get(
                        self.ONEIRIC_TIMEOUT_ENV_VAR,
                        str(self.DEFAULT_PUSH_TIMEOUT_SECONDS),
                    )
                )
            except ValueError:
                timeout_seconds = self.DEFAULT_PUSH_TIMEOUT_SECONDS

            builder = RuntimeFactsBuilder(self)
            legacy_facts = builder.build_all()

            runtime_meta: dict[str, Any] = {
                "generated_at_unix": time_ns() // 1_000_000_000,
                "caller_component": "mahavishnu",
                "phase": "plan1-phase2-task2",
            }

            async def _push(
                key: str,
                provider: str,
                legacy_entry: dict[str, Any],
                runtime_meta: dict[str, Any],
            ) -> str:
                """Single ``oneiric_report_runtime`` round-trip; raises on failure.

                The Oneiric envelope (``success / registry / runtime``) is
                constructed HERE, not in the builder, so the MCP
                ``list_adapters`` payload stays binary-compatible with the
                pre-Phase-2 wire shape.
                """
                runtime_facts: dict[str, Any] = {
                    "enabled": legacy_entry.get("enabled", True),
                    "features": legacy_entry.get("features", []),
                    "type": legacy_entry.get("type", "engine"),
                    "metadata": dict(runtime_meta),
                    "source": "mahavishnu.adapters",
                }
                envelope: dict[str, Any] = {
                    "success": True,
                    "registry": {
                        "adapters": [
                            {
                                "key": key,
                                "provider": provider,
                                "domain": "engine",
                                "enabled": legacy_entry.get("enabled", True),
                                "features": legacy_entry.get("features", []),
                                "type": legacy_entry.get("type", "engine"),
                            }
                        ],
                        "domain": "engine",
                    },
                    "runtime": runtime_meta,
                }
                payload = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": "oneiric_report_runtime",
                        "arguments": {
                            "domain": "engine",
                            "key": key,
                            "provider": provider,
                            "runtime_facts": runtime_facts,
                            "caller_component": "mahavishnu",
                            "envelope": envelope,
                        },
                    },
                }
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(oneiric_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                if isinstance(data, dict) and "error" in data:
                    raise RuntimeError(f"oneiric rpc error: {data['error']}")
                return "ok"

            legacy_adapters = legacy_facts.get("adapters") or {}
            for key, legacy_entry in legacy_adapters.items():
                provider = key  # adapter name = provider in this registry
                try:
                    await self.circuit_breaker.call(
                        _push, key, provider, legacy_entry, runtime_meta
                    )
                    logger.info(
                        "runtime-push component=mahavishnu adapter=%s status=ok",
                        key,
                    )
                except Exception:  # background task — broad catch is the documented contract
                    logger.exception(
                        "runtime-push component=mahavishnu adapter=%s status=fail",
                        key,
                    )
                    continue

            self._last_runtime_facts_push_unix = time_ns() // 1_000_000_000
