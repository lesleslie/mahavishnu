"""Pi coding-agent pool — third pool type for Mahavishnu.

Implements ``BasePool`` against one-shot ``npx @earendil-works/pi-coding-agent``
invocations. v1.3.0+ of the agent is a CLI tool — each prompt is a single
``npx ... <prompt>`` subprocess that prints the model response to stdout
and exits 0 (errors are also printed to stdout, not stderr, and may exit 0).

Each ``execute_task`` call spawns a fresh subprocess and reaps it; there
is no long-lived subprocess, no JSON-RPC handshake, and no Content-Length
framing. The pool therefore has **no startup self-test beyond a one-shot
``--version`` probe at ``start()`` time** (populates the health-check
``version`` field) and **no watchdog loop**. Per-task timeouts still
fire ``mahavishnu.pi.heartbeat.missed_total`` (the per-invocation
counter replaces the old persistent-subprocess watchdog).

Each pool manages exactly ONE logical worker. ``scale(n>1)`` raises
``NotImplementedError`` to match ``SessionBuddyPool.scale`` — see
``docs/plans/2026-09-07-pi-pool-backend.md`` (reverses the original
"WARN-round-down" decision per multi-agent review consensus).

Security primitives (non-negotiable, see plan §D1.6):

* ``env_allowlist`` — minimal allowlist of env keys forwarded to the
  subprocess. Sensitive parent env keys (``MAHAVISHNU_*``, ``MINIMAX_*``,
  ``ZAI_*``, ``DHARA_*``, ``AKOSHA_*``, ``SESSION_BUDDY_*``) are NEVER
  copied. The default allowlist includes the standard LLM credential
  env vars (``OPENAI_API_KEY``, ``OPENAI_BASE_URL``,
  ``ANTHROPIC_API_KEY``, ``ANTHROPIC_BASE_URL``) so the pi-coding-agent
  can actually call an upstream; the operator opts in by setting
  these in their shell. To route through Bifrost, set
  ``OPENAI_BASE_URL=http://127.0.0.1:8471/v1`` (the gateway serves
  the OpenAI-compatible endpoint at ``/v1/chat/completions`` per the
  oneiric 0.32.1 default). The runtime denylist is
  :data:`_FORBIDDEN_ENV_PREFIXES` (REQ-BIFROST-014).
* ``npx_command`` — start of command must be in
  ``{npx, /usr/bin/env, /usr/local/bin/npx}``; command must reference
  ``@earendil-works/pi-coding-agent``. Enforced by
  :class:`mahavishnu.core.config.PiPoolSettings._npx_command_allowlist`.

Observability:

* OTel-style metrics: ``mahavishnu.pi.tasks.executed{status}``,
  ``mahavishnu.pi.task.duration``, ``mahavishnu.pi.heartbeat.missed_total``
* Health-check dict carries ``rpc_latency_ms`` (last task duration in
  ms), ``last_ping_at`` (last task timestamp), ``version`` (from the
  ``--version`` probe), and ``startup_self_test`` block.

Testability: ``subprocess_runner`` parameter lets tests inject an
in-memory coroutine instead of spawning a real subprocess. The default
runner uses :func:`asyncio.create_subprocess_exec` with stdout/stderr
captured to ``PIPE``.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import TYPE_CHECKING, Any, ClassVar, Protocol
import uuid

from oneiric.core.logging import get_logger

from mahavishnu.core.errors import (
    PiProtocolError,
    PiRPCTimeout,
    PiUnavailable,
)

from . import pi_observability
from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


# Default keys always passed through to the subprocess, in addition to the
# caller-provided ``env_allowlist``. These are minimal POSIX keys required
# for ``npx`` to function (``PATH``) and for the Node runtime to honour
# locale expectations (``HOME``, ``LANG``, ``TMPDIR``). ``NODE_PATH`` and
# ``NODE_ENV`` are forward-declared for future Pi features; both default to
# empty in the subprocess.
_REQUIRED_PASSTHROUGH_KEYS: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "NODE_PATH",
    "NODE_ENV",
    "TMPDIR",
)


# Runtime denylist: env-var name prefixes that MUST NOT be forwarded to the
# subprocess, even if the caller's ``env_allowlist`` accidentally or
# maliciously includes them. This is the runtime counterpart to the
# PiPool allowlist — the model-level validator is the first line of
# defense; this denylist is the second.
#
# REQ-BIFROST-014 (bifrost plan §5 Phase 3): the denylist is the
# ACTUAL security boundary for the PiPool subprocess env forwarding.
# ``MAHAVISHNU_`` is the mahavishnu operator's own config;
# ``BIFROST_`` covers the bifrost gateway config (any env var
# controlling the oneiric router or the legacy local bifrost).
# Pinned by ``tests/unit/pools/test_pi_security.py``.
_FORBIDDEN_ENV_PREFIXES: tuple[str, ...] = (
    "MAHAVISHNU_",
    "MINIMAX_",
    "ZAI_",
    "DHARA_",
    "AKOSHA_",
    "SESSION_BUDDY_",
    "BIFROST_",  # covers MAHAVISHNU_BIFROST__*, ONEIRIC_BIFROST_*, BIFROST_ALLOW_REMOTE
    "ONEIRIC_",
)


# Per-invocation timeout when the task dict doesn't specify one.
_DEFAULT_TASK_TIMEOUT_SECONDS: float = 30.0

# Per-invocation timeout for the ``--version`` startup probe.
_STARTUP_PROBE_TIMEOUT_SECONDS: float = 10.0

# Stdout/stderr line prefixes that indicate the agent failed. The v1.x
# agent prints errors to stdout (not stderr) and may still exit 0, so
# the pool treats these prefixes as failure regardless of return code.
# The list is intentionally narrow — we only match the canonical
# error shapes; user-facing model output (which can legitimately start
# with any text) is never treated as a failure.
_ERROR_LINE_PREFIXES: tuple[str, ...] = (
    "Error:",
    "OpenAI API error",
    "Anthropic API error",
    "AuthenticationError:",
    "RateLimitError:",
)


class SubprocessRunner(Protocol):
    """Callable that spawns the agent subprocess and returns its result.

    Returned tuple: ``(returncode, stdout, stderr)``. Both ``stdout`` and
    ``stderr`` are decoded text (``str``). Implementations MUST enforce
    the ``timeout`` budget; on timeout they should raise
    :class:`asyncio.TimeoutError` (the pool maps this to
    :class:`PiRPCTimeout`).
    """

    async def __call__(
        self,
        *,
        argv: tuple[str, ...],
        env: dict[str, str],
        timeout: float,
    ) -> tuple[int, str, str]: ...


async def _default_subprocess_runner(
    *,
    argv: tuple[str, ...],
    env: dict[str, str],
    timeout: float,
) -> tuple[int, str, str]:
    """Default runner — spawn via ``asyncio.create_subprocess_exec``.

    Maps spawn-time errors (``FileNotFoundError``, ``PermissionError``,
    ``OSError``) to :class:`PiUnavailable` so the pool's public
    contract is uniform: any spawn failure surfaces as ``PiUnavailable``.
    Runtime timeouts raise :class:`asyncio.TimeoutError`; the pool
    catches and maps those to :class:`PiRPCTimeout`.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as e:
        raise PiUnavailable(
            "`npx` binary not found on PATH",
            install_hint="install Node.js (https://nodejs.org) which bundles npx",
        ) from e
    except PermissionError as e:
        raise PiUnavailable(
            f"subprocess executable not executable: {argv[0]!r}",
            install_hint="check filesystem permissions on the npx binary",
        ) from e
    except OSError as e:
        raise PiUnavailable(
            f"failed to spawn Pi subprocess: {e}",
            install_hint="check PATH and filesystem permissions",
        ) from e
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except TimeoutError:
            logger.warning("Pi subprocess did not exit after SIGKILL")
        raise
    return (
        proc.returncode if proc.returncode is not None else 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _format_worker_id(pool_id: str) -> str:
    """Return the canonical worker id string for this pool."""
    return f"{pool_id}:pi-{uuid.uuid4().hex[:8]}"


def _build_subprocess_env(env_allowlist: tuple[str, ...]) -> dict[str, str]:
    """Build the subprocess env from the explicit ``env_allowlist``.

    Starts from a minimal POSIX-required base (``PATH``, ``HOME``,
    ``LANG``, ``NODE_PATH``, ``NODE_ENV``, ``TMPDIR``) and overlays
    the explicit ``env_allowlist`` keys taken from ``os.environ``.
    Sensitive parent env vars (see :data:`_FORBIDDEN_ENV_PREFIXES`)
    are NEVER copied — a denylist match is logged at WARNING and the
    key is dropped, even if the caller's allowlist included it.
    """
    env: dict[str, str] = {}
    for key in _REQUIRED_PASSTHROUGH_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    for key in env_allowlist:
        if any(key.startswith(prefix) for prefix in _FORBIDDEN_ENV_PREFIXES):
            logger.warning("pi-pool refusing to forward sensitive env var: %s", key)
            continue
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _looks_like_error_output(stdout: str) -> str | None:
    """Return the first error line from ``stdout`` if any, else ``None``.

    The v1.x agent prints errors to stdout (not stderr) and may still
    exit 0, so we scan stdout for the canonical error prefixes. We
    return the first matching line so the caller can surface it in
    the pool's error field.
    """
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for prefix in _ERROR_LINE_PREFIXES:
            if stripped.startswith(prefix):
                return stripped
    return None


class PiPool(BasePool):
    """Pool backed by one-shot ``npx pi-coding-agent`` invocations.

    Req: REQ-PI-002, REQ-PI-004, REQ-PI-005, REQ-PI-006, REQ-PI-007
    """  # req: REQ-PI-002, REQ-PI-004, REQ-PI-005, REQ-PI-006, REQ-PI-007

    pool_type: ClassVar[str] = "pi"

    def __init__(
        self,
        config: PoolConfig,
        *,
        runtime_probe: Callable[[], tuple[bool, str]] | None = None,
        subprocess_runner: SubprocessRunner | None = None,
        env_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        """Initialise PiPool. Does NOT spawn a subprocess — call ``start()``.

        Args:
            config: Pool configuration.
            runtime_probe: Optional ``(ok, message)`` callable used by
                ``start()`` to gate pool creation on an external signal
                (e.g. ``npx`` --version probe). Default ``None``.
            subprocess_runner: Optional test seam — defaults to
                :func:`_default_subprocess_runner` which spawns via
                ``asyncio.create_subprocess_exec``. Tests use this seam
                to inject an in-memory coroutine that returns a
                canned ``(returncode, stdout, stderr)`` triple.
            env_allowlist: Subprocess env allowlist. Defaults to the
                10-key minimal allowlist documented in this module.
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
        self._subprocess_runner: SubprocessRunner = (
            subprocess_runner or _default_subprocess_runner
        )
        self._env_allowlist: tuple[str, ...] = env_allowlist or (
            # Minimal POSIX keys required for any subprocess.
            "PATH",
            "HOME",
            "LANG",
            "NODE_PATH",
            "NODE_ENV",
            "TMPDIR",
            # LLM credentials (the pi-coding-agent subprocess reads
            # these directly to call the upstream). The operator
            # sets them in their shell before spawning the pool;
            # the pool forwards them through the allowlist rather
            # than embedding them in the repo. To route through
            # Bifrost, set ``OPENAI_BASE_URL=http://127.0.0.1:8471/v1``
            # (the gateway serves the OpenAI-compatible endpoint at
            # ``/v1/chat/completions`` per the oneiric 0.32.1 default).
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
        )
        # Pool state — populated by start() (version probe) and
        # execute_task (last task telemetry). The pool is otherwise
        # stateless across calls; each execute_task is independent.
        self._startup_version: str | None = None
        self._startup_self_test_at: float | None = None
        self._last_task_ms: float | None = None
        self._last_task_at: float | None = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._tasks_timed_out = 0
        self._task_durations: list[float] = []
        self._heartbeats_missed = 0

    # -- BasePool lifecycle --------------------------------------------------

    async def start(self) -> str:
        """Run the startup ``--version`` probe; mark the pool RUNNING.

        The probe is a one-shot ``npx <pkg> --version`` invocation that
        returns the installed agent version. Failure to probe does not
        abort start() — the version field is set to ``None`` and the
        pool still serves tasks (the per-task subprocess is what
        matters; the version probe is purely informational).

        Returns:
            pool_id: Unique pool identifier.

        Raises:
            PiUnavailable: When the ``runtime_probe`` callable returns
                ``(False, message)`` (caller-supplied gate).

        Req: REQ-PI-005
        """  # req: REQ-PI-005
        self._status = PoolStatus.INITIALIZING
        self._gate_on_runtime_probe()
        version = await self._startup_version_probe()
        self._record_successful_start(version)
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

    async def _startup_version_probe(self) -> str | None:
        """Run ``npx <pkg> --version`` to populate the version field.

        Returns the version string on success, ``None`` on any
        failure (the probe is best-effort). Never raises — the pool
        must remain usable even if the agent binary is unavailable
        at start() time.
        """
        cmd = self._resolve_npx_command()
        argv = (*cmd, "--version")
        env = _build_subprocess_env(self._env_allowlist)
        try:
            _, stdout, _ = await self._subprocess_runner(
                argv=argv, env=env, timeout=_STARTUP_PROBE_TIMEOUT_SECONDS
            )
        except (PiUnavailable, OSError) as e:
            logger.debug("Pi --version probe failed: %s", e)
            return None
        version = stdout.strip().splitlines()[0] if stdout.strip() else None
        return version or None

    def _record_successful_start(self, version: str | None) -> None:
        """Mark pool RUNNING, register the worker, emit spawn log."""
        self._startup_version = version
        self._startup_self_test_at = time.monotonic()
        self._status = PoolStatus.RUNNING
        worker_id = _format_worker_id(self.pool_id)
        self._workers[worker_id] = {
            "kind": "pi",
            "version": version,
            "command": list(self._resolve_npx_command()),
        }
        logger.info(
            "pool.pi.spawned pool_id=%s version=%s startup_self_test_version=%s",
            self.pool_id,
            version,
            version,
        )

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a task to a fresh pi-coding-agent subprocess.

        Args:
            task: Task dict. Recognised keys: ``prompt`` (required),
                ``timeout`` (optional, seconds), ``model`` (optional,
                forwarded as ``--model`` argv), ``provider`` (optional,
                forwarded as ``--provider`` argv — currently a no-op
                for v1.x which auto-detects the provider from
                ``OPENAI_*`` / ``ANTHROPIC_*`` env vars).

        Returns:
            Execution result dict with the BasePool contract shape:
            ``{pool_id, worker_id, status, output, error, duration}``.
        """
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
        timeout = float(task.get("timeout") or _DEFAULT_TASK_TIMEOUT_SECONDS)
        argv = self._build_task_argv(prompt, task)
        env = _build_subprocess_env(self._env_allowlist)
        worker_id = _format_worker_id(self.pool_id)
        start_time = time.monotonic()
        try:
            returncode, stdout, stderr = await self._subprocess_runner(
                argv=argv, env=env, timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            duration = time.monotonic() - start_time
            self._tasks_timed_out += 1
            self._task_durations.append(duration)
            self._heartbeats_missed += 1
            pi_observability.record_task_failed(duration, timed_out=True)
            pi_observability.record_heartbeat_missed()
            logger.warning(
                "pool.pi.task_timeout pool_id=%s worker_id=%s timeout=%.1fs",
                self.pool_id,
                worker_id,
                timeout,
            )
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "timeout",
                "output": None,
                "error": f"Pi subprocess timeout after {timeout:.1f}s",
                "duration": duration,
            }
        except PiUnavailable as exc:
            duration = time.monotonic() - start_time
            self._tasks_failed += 1
            self._task_durations.append(duration)
            pi_observability.record_task_failed(duration, timed_out=False)
            logger.warning(
                "pool.pi.task_unavailable pool_id=%s worker_id=%s error=%s",
                self.pool_id,
                worker_id,
                exc,
            )
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": f"Pi subprocess unavailable: {exc.message}",
                "duration": duration,
            }
        duration = time.monotonic() - start_time
        error_line = _looks_like_error_output(stdout)
        if error_line is not None or returncode != 0:
            self._tasks_failed += 1
            self._task_durations.append(duration)
            pi_observability.record_task_failed(duration, timed_out=False)
            error = error_line or (
                f"Pi subprocess exited {returncode}: {stderr.strip() or '<no stderr>'}"
            )
            logger.warning(
                "pool.pi.task_failed pool_id=%s worker_id=%s returncode=%d error=%s",
                self.pool_id,
                worker_id,
                returncode,
                error,
            )
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": stdout if stdout else None,
                "error": error,
                "duration": duration,
            }
        # Success path.
        self._tasks_completed += 1
        self._task_durations.append(duration)
        self._last_task_ms = duration * 1000.0
        self._last_task_at = time.monotonic()
        pi_observability.record_task_completed(duration)
        return {
            "pool_id": self.pool_id,
            "worker_id": worker_id,
            "status": "completed",
            "output": stdout,
            "error": None,
            "duration": duration,
        }

    def _build_task_argv(self, prompt: str, task: dict[str, Any]) -> tuple[str, ...]:
        """Build the per-task subprocess argv.

        v1.x of the agent takes the prompt as a positional argument.
        Optional ``--provider`` and ``--model`` flags are appended
        when present in the task dict (v1.x's CLI surface; verified
        with ``npx @earendil-works/pi-coding-agent --help``).
        """
        argv: list[str] = list(self._resolve_npx_command())
        provider = task.get("provider")
        model = task.get("model")
        if provider:
            argv.extend(["--provider", str(provider)])
        if model:
            argv.extend(["--model", str(model)])
        argv.append(prompt)
        return tuple(argv)

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
        if self._status == PoolStatus.PENDING or self._status == PoolStatus.INITIALIZING:
            return {
                "pool_id": self.pool_id,
                "pool_type": "pi",
                "status": "initializing",
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
        if self._status == PoolStatus.FAILED:
            return {
                "pool_id": self.pool_id,
                "pool_type": "pi",
                "status": "unhealthy",
                "workers_active": 0,
                "worker_health": {
                    "rpc_latency_ms": self._last_task_ms,
                    "last_ping_at": self._last_task_at,
                    "version": self._startup_version,
                    "startup_self_test": {
                        "passed": self._startup_version is not None,
                        "version": self._startup_version,
                        "checked_at": self._startup_self_test_at,
                    },
                },
            }
        # Status is RUNNING / STOPPED — report per-task telemetry.
        return {
            "pool_id": self.pool_id,
            "pool_type": "pi",
            "status": "healthy" if self._status == PoolStatus.RUNNING else "stopped",
            "workers_active": 1 if self._status == PoolStatus.RUNNING else 0,
            "worker_health": {
                "rpc_latency_ms": self._last_task_ms,
                "last_ping_at": self._last_task_at,
                "version": self._startup_version,
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
        incrementally at the mutation sites in :meth:`execute_task`;
        see :mod:`mahavishnu.pools.pi_observability` for the wire-up.
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
        """Stop the pool.

        No subprocess to reap in the per-invocation model — the pool
        simply marks itself ``STOPPED``. Outstanding in-flight tasks
        complete independently (they are not owned by the pool).
        """
        self._status = PoolStatus.STOPPED
        logger.info("pool.pi.stopped pool_id=%s", self.pool_id)

    # -- Internal helpers ----------------------------------------------------

    def _resolve_npx_command(self) -> tuple[str, ...]:
        """Resolve the npx command from PoolConfig.extra_config or env.

        Order:
        1. ``config.extra_config["npx_command"]`` if present.
        2. ``MAHAVISHNU_PI_POOL__NPX_COMMAND`` (comma-separated) if set.
        3. The default ``("npx", "-y", "@earendil-works/pi-coding-agent")``.
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
    subprocess_runner: SubprocessRunner | None = None,
    env_allowlist: tuple[str, ...] | None = None,
    **_unused: Any,
) -> PiPool:
    """Factory used by the pool registry.

    Accepts ``runtime_probe``, ``subprocess_runner``, and
    ``env_allowlist`` as kwargs so tests can inject seams without
    editing this function.
    """
    return PiPool(
        config=config,
        runtime_probe=runtime_probe,
        subprocess_runner=subprocess_runner,
        env_allowlist=env_allowlist,
    )


from ._registry import register_pool_type

# Register at module import. The canonical name is "pi" (no underscore form
# needed; "pi" is the only canonical spelling).
register_pool_type("pi", _build_pi_pool)


__all__ = [
    "PiPool",
    "_FORBIDDEN_ENV_PREFIXES",
    "_build_pi_pool",
    "_build_subprocess_env",
    "_default_subprocess_runner",
    "_looks_like_error_output",
    "SubprocessRunner",
]
