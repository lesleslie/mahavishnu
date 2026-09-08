"""Pi coding-agent pool — third pool type for Mahavishnu.

Implements ``BasePool`` against a single persistent
``npx @earendil-works/pi-coding-agent --rpc`` subprocess. JSON-RPC 2.0
communication uses Content-Length framing (LSP convention; NOT NDJSON)
via :class:`mahavishnu.core.json_rpc_stdio.JSONRPCStdioClient`.

Each pool manages exactly ONE subprocess. ``scale(n>1)`` raises
``NotImplementedError`` to match ``SessionBuddyPool.scale`` — see
``docs/plans/2026-09-07-pi-pool-backend.md`` (reverses the original
"WARN-round-down" decision per multi-agent review consensus).

Security primitives (non-negotiable, see plan §D1.6):

* ``env_allowlist`` — minimal allowlist of env keys forwarded to the
  subprocess. Sensitive parent env keys (``MAHAVISHNU_*``, ``MINIMAX_*``,
  ``ZAI_*``, ``DHARA_*``, ``AKOSHA_*``, ``SESSION_BUDDY_*``) are NEVER
  copied. Implementation lives in
  :class:`mahavishnu.core.json_rpc_stdio.JSONRPCStdioClient`.
* ``npx_command`` — start of command must be in
  ``{npx, /usr/bin/env, /usr/local/bin/npx}``; command must include
  ``--rpc`` and reference ``@earendil-works/pi-coding-agent``. Enforced
  by :class:`mahavishnu.core.config.PiPoolSettings._npx_command_allowlist`.

Observability:

* OTel-style metrics: ``mahavishnu.pi.tasks.executed{status}``,
  ``mahavishnu.pi.task.duration``, ``mahavishnu.pi.heartbeat.missed_total``
* Health-check dict carries ``rpc_latency_ms``, ``last_ping_at``,
  ``version``, ``startup_self_test`` block.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any, ClassVar
import uuid

from oneiric.core.logging import get_logger

from mahavishnu.core.errors import (
    PiProtocolError,
    PiRPCTimeout,
    PiUnavailable,
)
from mahavishnu.core.json_rpc_stdio import JSONRPCStdioClient

from . import pi_observability
from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


# Methods on the Pi RPC that we treat as "execute a task".
# The Pi coding-agent's --rpc protocol is documented as Pi-Coding-Agent
# RPC. The contract used here is intentionally minimal — "execute" wraps
# the prompt in a generic "complete" method so a future schema upgrade
# does not require changing PiPool.
_PI_EXECUTE_METHOD = "complete"


def _format_worker_id(pool_id: str) -> str:
    """Return the canonical worker id string for this pool."""
    return f"{pool_id}:pi-{uuid.uuid4().hex[:8]}"


def _map_rpc_error_to_pool_error(exc: Exception, *, method: str) -> dict[str, Any]:
    """Translate an RPC exception to a pool-friendly error result.

    Centralised so :meth:`PiPool.execute_task` can keep its branch count
    within the complexity budget (≤15 branches; see plan §D1.8).

    Req: REQ-PI-007
    """  # req: REQ-PI-007
    if isinstance(exc, PiRPCTimeout):
        return {
            "status": "timeout",
            "error": f"Pi RPC timeout: {exc.message}",
        }
    if isinstance(exc, PiProtocolError):
        return {
            "status": "failed",
            "error": f"Pi protocol error: {exc.message}",
        }
    # JSON-RPC error returned by the peer.
    message = str(exc)
    return {
        "status": "failed",
        "error": f"Pi RPC {method} failed: {message}",
    }


class PiPool(BasePool):
    """Pool backed by a single ``npx pi-coding-agent --rpc`` subprocess.

    Req: REQ-PI-002, REQ-PI-004, REQ-PI-005, REQ-PI-006, REQ-PI-007
    """  # req: REQ-PI-002, REQ-PI-004, REQ-PI-005, REQ-PI-006, REQ-PI-007

    pool_type: ClassVar[str] = "pi"

    def __init__(
        self,
        config: PoolConfig,
        *,
        runtime_probe: Callable[[], tuple[bool, str]] | None = None,
        rpc_factory: Callable[..., JSONRPCStdioClient] | None = None,
        env_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        """Initialise PiPool. Does NOT spawn the subprocess — call ``start()``.

        Args:
            config: Pool configuration.
            runtime_probe: Optional ``(ok, message)`` callable used by
                ``start()`` to gate pool creation on an external signal
                (e.g. ``npx`` --version probe).
            rpc_factory: Optional factory callable used to construct the
                :class:`JSONRPCStdioClient`. Defaults to the class itself.
                Tests use this seam to inject doubled pipes.
            env_allowlist: Subprocess env allowlist. Defaults to the
                ``PiPoolSettings.env_allowlist`` default.
        """
        super().__init__(config)
        # PiPool has a fixed worker count (1). Reject configs that claim otherwise
        # at construction time so the operator gets a clear error instead of a
        # pool that silently manages 1 worker.
        if config.max_workers > 1:
            raise ValueError(
                f"PiPool has a fixed worker count of 1; "
                f"config.max_workers={config.max_workers} is not allowed. "
                f"Spawn additional PiPool instances for more capacity."
            )
        self._runtime_probe = runtime_probe
        self._rpc_factory = rpc_factory or self._default_rpc_factory
        self._env_allowlist: tuple[str, ...] = env_allowlist or (
            "PATH",
            "HOME",
            "LANG",
            "NODE_PATH",
            "NODE_ENV",
            "TMPDIR",
        )
        self._client: JSONRPCStdioClient | None = None
        self._startup_version: str | None = None
        self._startup_self_test_at: float | None = None
        self._last_ping_ms: float | None = None
        self._last_ping_at: float | None = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._tasks_timed_out = 0
        self._task_durations: list[float] = []
        self._heartbeats_missed = 0

    # -- BasePool lifecycle --------------------------------------------------

    async def start(self) -> str:
        """Spawn the subprocess and run the startup self-test.

        Returns:
            pool_id: Unique pool identifier.

        Raises:
            PiUnavailable: When ``npx`` is missing or ``--rpc`` unsupported.
            PiProtocolError: When the subprocess fails to spawn.

        Req: REQ-PI-005
        """  # req: REQ-PI-005
        self._status = PoolStatus.INITIALIZING
        self._gate_on_runtime_probe()
        npx_command = self._resolve_npx_command()
        await self._spawn_and_start_client(npx_command)
        self._record_successful_start(npx_command)
        return self.pool_id

    def _gate_on_runtime_probe(self) -> None:
        """Apply the external runtime probe (no-op if not configured)."""
        if self._runtime_probe is None:
            return
        ok, message = self._runtime_probe()
        if ok:
            return
        self._status = PoolStatus.FAILED
        raise PiUnavailable(
            f"runtime probe failed: {message}",
            install_hint="npm i -g npx && npx -y @earendil-works/pi-coding-agent",
        )

    async def _spawn_and_start_client(self, npx_command: tuple[str, ...]) -> None:
        """Construct the JSON-RPC client and run start(); map spawn failures.

        Maps PiProtocolError / FileNotFoundError / OSError to PiUnavailable
        with actionable ``install_hint`` so operators can resolve the most
        common causes (missing npx, filesystem permissions, RPC handshake
        rejection). Extracted from ``start()`` to keep that method under the
        ≤15-branch complexity budget per CLAUDE.md.

        Req: REQ-PI-005
        """  # req: REQ-PI-005
        try:
            self._client = self._rpc_factory(
                command=npx_command,
                env=self._env_allowlist,
                logger=logger,
            )
            self._startup_version = await self._client.start()
        except PiProtocolError as e:
            self._status = PoolStatus.FAILED
            raise PiUnavailable(
                f"failed to start Pi subprocess: {e.message}",
                install_hint="npm i -g npx && npx -y @earendil-works/pi-coding-agent",
            ) from e
        except FileNotFoundError as e:
            self._status = PoolStatus.FAILED
            raise PiUnavailable(
                "`npx` binary not found on PATH",
                install_hint="install Node.js (https://nodejs.org) which bundles npx",
            ) from e
        except OSError as e:
            self._status = PoolStatus.FAILED
            raise PiUnavailable(
                f"failed to spawn Pi subprocess: {e}",
                install_hint="check PATH and filesystem permissions",
            ) from e

    def _record_successful_start(self, npx_command: tuple[str, ...]) -> None:
        """Mark pool RUNNING, register the worker, emit spawn log."""
        self._startup_self_test_at = time.monotonic()
        self._status = PoolStatus.RUNNING
        worker_id = _format_worker_id(self.pool_id)
        self._workers[worker_id] = {
            "kind": "pi",
            "version": self._startup_version,
            "command": list(npx_command),
        }
        logger.info(
            "pool.pi.spawned pool_id=%s version=%s startup_self_test_version=%s",
            self.pool_id,
            self._startup_version,
            self._startup_version,
        )

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a task to the Pi subprocess via JSON-RPC.

        Args:
            task: Task dict. Recognised keys: ``prompt`` (required),
                ``timeout`` (optional, seconds).

        Returns:
            Execution result dict with the BasePool contract shape:
            ``{pool_id, worker_id, status, output, error, duration}``.
        """
        if self._client is None or not self._client.is_started:
            return {
                "pool_id": self.pool_id,
                "worker_id": _format_worker_id(self.pool_id),
                "status": "failed",
                "output": None,
                "error": "PiPool not started",
                "duration": 0.0,
            }
        prompt = task.get("prompt")
        if not prompt:
            self._tasks_failed += 1
            return {
                "pool_id": self.pool_id,
                "worker_id": _format_worker_id(self.pool_id),
                "status": "failed",
                "output": None,
                "error": "task missing 'prompt' field",
                "duration": 0.0,
            }
        timeout = float(task.get("timeout") or getattr(self._client, "_request_timeout", 30.0))
        worker_id = _format_worker_id(self.pool_id)
        start_time = time.monotonic()
        try:
            result = await self._client.request(
                _PI_EXECUTE_METHOD,
                {"prompt": prompt, "model": task.get("model")},
                timeout=timeout,
            )
            duration = time.monotonic() - start_time
            self._tasks_completed += 1
            self._task_durations.append(duration)
            pi_observability.record_task_completed(duration)
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "completed",
                "output": result,
                "error": None,
                "duration": duration,
            }
        except (PiRPCTimeout, PiProtocolError, Exception) as exc:  # noqa: BLE001
            duration = time.monotonic() - start_time
            self._task_durations.append(duration)
            mapped = _map_rpc_error_to_pool_error(exc, method=_PI_EXECUTE_METHOD)
            timed_out = mapped["status"] == "timeout"
            if timed_out:
                self._tasks_timed_out += 1
            else:
                self._tasks_failed += 1
            pi_observability.record_task_failed(duration, timed_out=timed_out)
            if self._client.watchdog_failed:
                self._heartbeats_missed += 1
                self._status = PoolStatus.FAILED
                pi_observability.record_heartbeat_missed()
            logger.warning(
                "pool.pi.task_failed pool_id=%s worker_id=%s status=%s error=%s",
                self.pool_id,
                worker_id,
                mapped["status"],
                mapped["error"],
            )
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": mapped["status"],
                "output": None,
                "error": mapped["error"],
                "duration": duration,
            }

    async def execute_batch(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Run tasks concurrently via ``asyncio.gather``.

        Args:
            tasks: List of task dicts.

        Returns:
            Dict mapping ``str(task_id or index) -> result``.
        """
        if not tasks:
            return {}
        results = await asyncio.gather(
            *(self.execute_task(t) for t in tasks),
            return_exceptions=False,
        )
        out: dict[str, dict[str, Any]] = {}
        for idx, res in enumerate(results):
            task_id = str(tasks[idx].get("task_id") or idx)
            out[task_id] = res
        return out

    async def scale(self, target_worker_count: int) -> None:
        """PiPool has a fixed worker count (1).

        Args:
            target_worker_count: Desired worker count. Must be 1.

        Raises:
            ValueError: When ``target_worker_count < 1`` (zero or negative).
            NotImplementedError: When ``target_worker_count > 1`` (matches
                ``SessionBuddyPool.scale`` semantics per multi-agent review).

        Req: REQ-PI-004
        """  # req: REQ-PI-004
        if target_worker_count < 1:
            raise ValueError(
                f"target_worker_count must be >= 1 (got {target_worker_count}); "
                f"PiPool has a fixed worker count of 1 — use spawn for 0 / "
                f"shutdown the pool to drop below 1."
            )
        if target_worker_count > 1:
            raise NotImplementedError(
                "PiPool has fixed worker count (1). Spawn additional pools for more capacity."
            )
        # target == 1 is a no-op: the canonical single subprocess is already running.

    async def health_check(self) -> dict[str, Any]:
        """Return the canonical PiPool health snapshot.

        Req: REQ-PI-006
        """  # req: REQ-PI-006
        client = self._client
        if client is None:
            return {
                "pool_id": self.pool_id,
                "pool_type": "pi",
                "status": "unhealthy",
                "workers_active": 0,
                "worker_health": {
                    "rpc_latency_ms": None,
                    "last_ping_at": None,
                    "version": None,
                    "startup_self_test": {
                        "passed": False,
                        "version": None,
                        "checked_at": None,
                    },
                },
            }
        # Best-effort ping (coarse write latency). Skipped if the client is
        # already in failed state to avoid log spam.
        if not client.watchdog_failed and not client.is_stopped:
            try:
                self._last_ping_ms = await client.ping()
                self._last_ping_at = time.monotonic()
            except (PiRPCTimeout, PiProtocolError, OSError) as e:
                logger.debug("pi pool ping failed: %s", e)
        pool_status = "healthy"
        if client.watchdog_failed or self._status == PoolStatus.FAILED:
            pool_status = "unhealthy"
        elif client.protocol_errors > 0:
            pool_status = "degraded"
        return {
            "pool_id": self.pool_id,
            "pool_type": "pi",
            "status": pool_status,
            "workers_active": 0 if pool_status == "unhealthy" else 1,
            "worker_health": {
                "rpc_latency_ms": self._last_ping_ms,
                "last_ping_at": self._last_ping_at,
                "version": client.startup_version,
                "startup_self_test": {
                    "passed": self._startup_version is not None,
                    "version": self._startup_version,
                    "checked_at": self._startup_self_test_at,
                },
            },
        }

    async def get_metrics(self) -> PoolMetrics:
        """Aggregate pool-level metrics.

        OTel counters ``mahavishnu.pi.tasks.executed{status}``,
        ``mahavishnu.pi.task.duration``, and
        ``mahavishnu.pi.heartbeat.missed_total`` are emitted
        incrementally at the mutation sites in :meth:`execute_task` and
        :meth:`JSONRPCStdioClient._watchdog_loop`; see
        :mod:`mahavishnu.pools.pi_observability` for the wire-up.
        Dashboards pulling those counter names will populate
        immediately on the next task, not on each ``get_metrics()``
        scrape.
        """
        status = self._status
        active_workers = 1 if status == PoolStatus.RUNNING else 0
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )
        return PoolMetrics(
            pool_id=self.pool_id,
            status=status,
            active_workers=active_workers,
            total_workers=1,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed + self._tasks_timed_out,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Return per-task memory items for cross-session storage.

        Empty list — Pi tasks are stateless; no per-pool memory to collect.
        """
        return []

    async def stop(self) -> None:
        """Stop the pool: cancel pending requests, then SIGTERM subprocess."""
        # STOPPING is treated as RUNNING until the subprocess terminates.
        # We reuse the RUNNING status to avoid expanding the PoolStatus enum
        # (which is imported from mahavishnu.core.status and may not have a
        # STOPPING member in every code path).
        self._status = PoolStatus.STOPPED
        if self._client is not None:
            try:
                await self._client.stop()
            except Exception as e:  # pragma: no cover - defensive  # noqa: BLE001
                logger.warning("error stopping pi client: %s", e)
            self._client = None
        self._status = PoolStatus.STOPPED
        logger.info("pool.pi.stopped pool_id=%s", self.pool_id)

    # -- Internal helpers ----------------------------------------------------

    def _default_rpc_factory(
        self,
        *,
        command: tuple[str, ...],
        env: tuple[str, ...],
        logger: Any,
    ) -> JSONRPCStdioClient:
        """Default factory — wires the env allowlist + heartbeat callback."""
        env_map = {k: os.environ[k] for k in env if k in os.environ}
        return JSONRPCStdioClient(
            command=command,
            env=env_map,
            logger=logger,
            on_heartbeat_missed=pi_observability.record_heartbeat_missed,
        )

    def _resolve_npx_command(self) -> tuple[str, ...]:
        """Resolve the npx command from PoolConfig.extra_config or env.

        Order:
        1. ``config.extra_config["npx_command"]`` if present.
        2. ``MAHAVISHNU_PI_POOL__NPX_COMMAND`` (comma-separated) if set.
        3. The default ``("npx", "-y", "@earendil-works/pi-coding-agent", "--rpc")``.
        """
        from mahavishnu.core.config import PiPoolSettings

        cmd = self.config.extra_config.get("npx_command") if self.config.extra_config else None
        if cmd is not None:
            return tuple(cmd)
        env_value = os.environ.get("MAHAVISHNU_PI_POOL__NPX_COMMAND")
        if env_value:
            return tuple(part.strip() for part in env_value.split(",") if part.strip())
        return PiPoolSettings().npx_command


def _build_pi_pool(
    config: PoolConfig,
    *,
    runtime_probe: Callable[[], tuple[bool, str]] | None = None,
    rpc_factory: Callable[..., JSONRPCStdioClient] | None = None,
    env_allowlist: tuple[str, ...] | None = None,
    **_unused: Any,
) -> PiPool:
    """Factory used by the pool registry.

    Accepts ``runtime_probe``, ``rpc_factory``, and ``env_allowlist`` as
    kwargs so tests can inject seams without editing this function.
    """
    return PiPool(
        config=config,
        runtime_probe=runtime_probe,
        rpc_factory=rpc_factory,
        env_allowlist=env_allowlist,
    )


from ._registry import register_pool_type

# Register at module import. The canonical name is "pi" (no underscore form
# needed; "pi" is the only canonical spelling).
register_pool_type("pi", _build_pi_pool)


__all__ = ["PiPool", "_build_pi_pool"]
