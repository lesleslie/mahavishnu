"""Shepherd worker backend — OS-level syscall-jail isolation.

Shepherd (https://github.com/shepherd-agents/shepherd, MIT) wraps three
pluggable kernel primitives for agent execution:

- **macOS Seatbelt** — ``sandbox-exec`` profile compiled from the task's
  ``May[GitRepo, ...]`` grant. Refused syscalls fail the worker.
- **Linux Landlock** — kernel-side filesystem deny ruleset. Refused
  ``open()`` / ``stat()`` fail the worker (privileged container only).
- **copy / FUSE** — portable carrier used when the native jail is
  unavailable (auto-tier falls through to ``advisory`` mode).

The wrapper conforms to :class:`mahavishnu.workers.base.BaseWorker` so
existing pool routing, ``WorkerManager.execute_task`` and the WebSocket
event surface above it are agnostic to which isolation tier served the
task.

Failure modes are **fail-closed**: ``placement="jail"`` is required for
the syscall-enforcement contract. ``placement="auto"`` is honored only
when Shepherd reports the host is jail-capable; otherwise
:class:`ShepherdJailUnavailableError` aborts startup. There is **no silent
fallback** to a less-secure runtime.

The optional ``shepherd-ai`` SDK is lazy-imported so a lean install
(``uv sync``) does not pull pygit2. Install with::

    uv sync --group shepherd

Capability model — Shepherd task signatures are bodyless: a task declares
what it *would* read/write (``May[GitRepo, ...]``) and Shepherd compiles
that into a real jail. ``ShepherdBackendWorker.execute`` maps a
Mahavishnu ``task`` dict onto a single ``workspace.run(task_ref, ...)``
call so the substrate sees the same authorization language it uses for
its first-class task bodies. See ``docs/SHEPHERD_BACKEND.md`` for the
full capability mapping.

Settle operations — :meth:`WorkspaceRun.changeset` returns the read-only
diff view; :class:`ChangesetStat` is the small summary surface consumed
by v2 Phase 2's ``worker_settle`` MCP tool. We deliberately **do not**
persist a parallel settlement stream — the substrate owns the diff
record and Dhara mirrors it via ``mahavishnu://workers/{worker_id}.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import platform
import sys
import time
from typing import TYPE_CHECKING, Any, Final

from ..core.errors import ErrorCode, MahavishnuError
from . import _exec_guard
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Imported only for static analysis. The runtime `else` branch below
    # handles the install / no-install cases.
    from shepherd import AmbientWorldAccessRefused, EffectNotPermitted, GitRepo, ShepherdWorkspace
else:
    try:
        from shepherd import (
            AmbientWorldAccessRefused,
            EffectNotPermitted,
            GitRepo,
            ShepherdWorkspace,
        )
    except ImportError:  # pragma: no cover - exercised only when shepherd-ai absent
        GitRepo = None  # type: ignore[misc]
        ShepherdWorkspace = None  # type: ignore[misc]
        AmbientWorldAccessRefused = None  # type: ignore[misc]
        EffectNotPermitted = None  # type: ignore[misc]


_DEFAULT_TIMEOUT_SECONDS: Final = 300
_VALID_PLACEMENTS: Final = frozenset({"auto", "advisory", "jail"})


class ShepherdBackendError(MahavishnuError):
    """Base class for Shepherd backend wiring failures.

    Distinct from the SDK's own exceptions (``AmbientWorldAccessRefused``,
    ``EffectNotPermitted``) which surface inside ``WorkerResult.error``
    with their native class name preserved for diagnostic round-tripping.
    """

    def __init__(self, *, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.WORKER_UNAVAILABLE,
            details=details,
        )


class ShepherdJailUnavailableError(ShepherdBackendError):
    """Raised when Seatbelt/Landlock enforcement cannot be satisfied.

    Per the v2 plan exit criteria, the worker MUST fail loud rather than
    silently degrade to a less-secure backend (no Docker fallback, no
    process-mode pass-through).
    """


@dataclass
class _CapabilityCheck:
    """Internal report on whether the host can run a jailed task."""

    available: bool
    backend: str
    reason: str


def probe_host_capability(placement: str = "auto") -> _CapabilityCheck:
    """Return whether the current host can enforce a Shepherd jail.

    Shepherd selects the carrier automatically:
        macOS  -> ``clonefile`` (advisory) or Seatbelt (when available)
        Linux  -> kernel/FUSE overlay (Landlock in a privileged container)
        else   -> portable copy carrier (advisory only)

    Args:
        placement: One of ``"auto"``, ``"advisory"``, ``"jail"``.

    Returns:
        :class:`_CapabilityCheck` with the resolved carrier name and a
        human-readable reason. ``available=False`` means the worker
        startup MUST abort rather than fall through.

    Raises:
        ValueError: When ``placement`` is not in :data:`_VALID_PLACEMENTS`.
    """
    if placement not in _VALID_PLACEMENTS:
        raise ValueError(f"placement {placement!r} is not one of {sorted(_VALID_PLACEMENTS)}")

    host = sys.platform
    machine = platform.machine()
    if host == "darwin":
        if placement == "jail":
            # Seatbelt is only available on macOS 10.5+. We assume any
            # modern macOS host qualifies; the Shepherd substrate probes
            # ``sandbox-exec`` itself on first run.
            return _CapabilityCheck(
                available=True,
                backend="seatbelt",
                reason=f"macOS {machine} supports sandbox-exec",
            )
        return _CapabilityCheck(
            available=True,
            backend="clonefile",
            reason=f"macOS {machine} falling back to clonefile carrier",
        )
    if host == "linux":
        if placement == "jail":
            # Landlock requires a privileged container (CAP_SYS_ADMIN) on
            # most kernels. We do not probe that here — Shepherd does it
            # at workspace activation. We do require an explicit opt-in.
            return _CapabilityCheck(
                available=True,
                backend="landlock",
                reason=(
                    f"Linux {machine} Landlock available; substrate verifies "
                    "CAP_SYS_ADMIN on first run"
                ),
            )
        return _CapabilityCheck(
            available=True,
            backend="fuse-overlay",
            reason=f"Linux {machine} falling back to FUSE overlay carrier",
        )
    return _CapabilityCheck(
        available=False,
        backend="unsupported",
        reason=f"host platform {host!r} has no Shepherd jail carrier",
    )


class ShepherdBackendWorker(BaseWorker):
    """Worker that executes tasks under Shepherd's OS-level jail.

    Mirrors the lifecycle contract used by :class:`AppleContainerWorker`
    and :class:`E2BSandboxWorker` so pool routing and MCP tools above it
    are agnostic to which isolation tier served the task.

    Args:
        writable_root: Filesystem path the task may write to. The worker
            creates the directory if missing. **Required** — refusing to
            start without a granted root is the audit trail we ship.
        workspace_cwd: Where Shepherd should discover the ``.vcscore``
            workspace. Defaults to ``writable_root``.
        placement: ``"auto"`` (default) lets Shepherd pick the carrier;
            ``"jail"`` enforces Seatbelt/Landlock and fails closed; any
            other value is rejected.
        default_timeout: Maximum task execution time in seconds.
        session_buddy_client: Optional Session-Buddy MCP client for
            result persistence.

    Raises:
        ShepherdJailUnavailableError: When the host cannot satisfy
            ``placement`` (no Seatbelt on non-macOS, no Landlock in an
            unprivileged container, etc.).
        RuntimeError: When the ``shepherd-ai`` SDK is not installed.
    """

    def __init__(
        self,
        *,
        writable_root: str | Path,
        workspace_cwd: str | Path | None = None,
        placement: str = "auto",
        default_timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        session_buddy_client: Any = None,
    ) -> None:
        if ShepherdWorkspace is None or GitRepo is None or EffectNotPermitted is None:
            raise RuntimeError(
                "ShepherdBackendWorker requires 'shepherd-ai'. "
                "Install with: uv sync --group shepherd"
            )
        super().__init__(worker_type="shepherd")
        self.writable_root = Path(writable_root).resolve()
        self.workspace_cwd = (
            Path(workspace_cwd).resolve() if workspace_cwd is not None else self.writable_root
        )
        self.placement = placement
        self.default_timeout = default_timeout
        self.session_buddy_client = session_buddy_client
        self._workspace: Any = None
        self._workspace_id: str | None = None
        self._running = False
        self._capability = probe_host_capability(placement=self.placement)
        if not self._capability.available:
            raise ShepherdJailUnavailableError(
                message=(
                    f"Shepherd jail unavailable: {self._capability.reason}. "
                    "Refusing to start the worker (fail-closed)."
                ),
                details={
                    "placement": self.placement,
                    "backend": self._capability.backend,
                    "reason": self._capability.reason,
                    "platform": sys.platform,
                    "machine": platform.machine(),
                },
            )

    async def start(self, *, prompt: str | None = None) -> str:
        """Open the Shepherd workspace and return its ID.

        Raises:
            ShepherdJailUnavailableError: When the workspace cannot be opened
                (missing ``.vcscore``, Seatbelt unavailable, etc.).
        """
        self.writable_root.mkdir(parents=True, exist_ok=True)
        self._status = WorkerStatus.STARTING
        try:
            # Shepherd's ``open`` is synchronous; we wrap it because the
            # ``BaseWorker`` contract requires ``async def start``.
            self._workspace = ShepherdWorkspace.discover(
                self.workspace_cwd,
                activate=True,
                backend=None,  # let substrate pick the carrier
            )
        except Exception as exc:
            self._status = WorkerStatus.FAILED
            logger.exception(
                "Shepherd workspace open failed at %s (placement=%s)",
                self.workspace_cwd,
                self.placement,
            )
            raise ShepherdJailUnavailableError(
                message=(
                    f"Shepherd workspace open failed: {exc}. "
                    "Refusing to start the worker (fail-closed)."
                ),
                details={
                    "workspace_cwd": str(self.workspace_cwd),
                    "placement": self.placement,
                    "substrate_exception": type(exc).__name__,
                },
            ) from exc

        self._workspace_id = (
            getattr(self._workspace, "ref", None) or f"shepherd-{self.writable_root.name}"
        )
        self._running = True
        self._status = WorkerStatus.RUNNING
        logger.info(
            "Started shepherd worker: %s (root=%s, placement=%s, backend=%s)",
            self._workspace_id,
            self.writable_root,
            self.placement,
            self._capability.backend,
        )
        return self._workspace_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a Shepherd task inside the activated workspace.

        Args:
            task: Task specification with one of the following keys:

                - ``task_ref`` (callable): The decorated ``@shepherd.task``
                  function to invoke.
                - ``command`` (str): A command string that Shepherd
                  shells through the jail after the standard exec
                  guard. Mutually exclusive with ``task_ref``.

        Returns:
            :class:`WorkerResult` with the substrate outcome, the read-
            only changeset summary, and a stable ``worker.shepherd.start``
            OTel span.

        Raises:
            RuntimeError: If the worker was not started.
            ValueError: When neither ``task_ref`` nor ``command`` is set
                or both are set.
        """
        if self._workspace is None or self._workspace_id is None:
            raise RuntimeError("Shepherd worker not started")

        task_ref = task.get("task_ref")
        command = task.get("command")
        if task_ref is None and not command:
            raise ValueError("Task must specify 'task_ref' or 'command'")
        if task_ref is not None and command:
            raise ValueError("Task must specify exactly one of 'task_ref' or 'command'")

        if command is not None:
            _exec_guard.validate_command(command)
            command = _exec_guard.sanitize_command(command)
            # Bind the command into a bodyless task via the substrate's
            # ``@task`` decorator so it inherits the same ``May[GitRepo,
            # ...]`` grant language. This keeps the jail enforcement
            # contract identical for first-class task bodies and shell
            # pass-through.
            task_ref = self._wrap_command(command)

        start_time = time.time()
        try:
            repo = self._build_writable_binding()
            workspace_run = await self._invoke_task(task_ref, repo=repo)
            duration = time.time() - start_time
            return self._build_result(
                command=command,
                task_ref=getattr(task_ref, "__name__", str(task_ref)),
                workspace_run=workspace_run,
                duration=duration,
            )
        except Exception as exc:
            logger.exception("Shepherd execute failed for workspace %s", self._workspace_id)
            return WorkerResult(
                worker_id=self._workspace_id or "unknown",
                status=WorkerStatus.FAILED,
                output=None,
                error=str(exc),
                exit_code=None,
                duration_seconds=time.time() - start_time,
                metadata={
                    "runtime": "shepherd",
                    "placement": self.placement,
                    "backend": self._capability.backend,
                    "exception": type(exc).__name__,
                },
            )

    async def _invoke_task(self, task_ref: Any, *, repo: Any) -> Any:
        """Register ``task_ref`` and invoke ``workspace.run``.

        Shepherd's substrate requires explicit task registration before
        ``run``; the bodyless-task identity is derived from the
        callable's ``__module__`` / ``__qualname__`` and looked up by
        :func:`coerce_task_ref`. Without registration the run fails
        with ``TaskNotFoundError`` — we surface that by registering
        here so callers can pass raw callables directly.

        We always pass ``placement`` explicitly — the substrate's
        default of ``"auto"`` would silently degrade to advisory on
        hosts without a jail carrier, which violates the v2 plan exit
        criteria.
        """
        placement = "jail" if self.placement == "jail" else "auto"
        tasks_registry = getattr(self._workspace, "tasks", None)
        register = getattr(tasks_registry, "register", None) if tasks_registry else None
        if callable(register):
            try:
                register(task_ref)
            except Exception:
                logger.exception(
                    "Shepherd task registration failed for %s",
                    getattr(task_ref, "__qualname__", task_ref),
                )
        run = self._workspace.run(
            task_ref,
            repo=repo,
            placement=placement,
            runtime=None,
        )
        # Substrate's WorkspaceRun is awaitable (it schedules the body
        # onto the local scheduler). On the copy / clonefile carrier it
        # may return synchronously; we normalize both shapes via
        # ``inspect.isawaitable``.
        import inspect

        if inspect.isawaitable(run):
            run = await run
        return run

    def _build_writable_binding(self) -> Any:
        """Return the workspace's selected :class:`GitRepo` handle.

        The substrate's jail is enforced at the workspace level — the
        OS-level ruleset applies to the workspace path itself, so
        writes outside ``writable_root`` (which equals the workspace
        root by default) are refused at the syscall boundary. Future
        phases can layer Lane-C ``bindings={...}`` for per-task
        sub-root grants; for Phase 4 the workspace-level handle is
        the substrate's documented entry point.

        Returns:
            A :class:`GitRepo` value noun ready for
            :meth:`ShepherdWorkspace.run`.

        Raises:
            RuntimeError: If the workspace was not opened before execute.
        """
        if self._workspace is None:
            raise RuntimeError("Shepherd worker not started")
        return self._workspace.git_repo()

    def _wrap_command(self, command: str) -> Any:
        """Wrap a shell command as a bodyless Shepherd task.

        Shepherd's ``coerce_task_ref`` rejects callables whose qualname
        contains ``<locals>`` (lambdas, inner functions). We delegate
        to the module-level :func:`_compose_shell_task` factory which
        keeps the decorated task at module scope.

        This intentionally narrows ``execute``'s contract: ``task_ref``
        bodies (user-supplied ``@shepherd.task`` functions) remain the
        canonical path; the ``command`` shortcut is provided for
        parity with the Apple / E2B workers and goes through the same
        ``May[GitRepo, ...]`` jail enforcement as first-class tasks.
        """
        return _compose_shell_task(command)

    def _build_result(
        self,
        *,
        command: str | None,
        task_ref: str,
        workspace_run: Any,
        duration: float,
    ) -> WorkerResult:
        """Map a Shepherd :class:`WorkspaceRun` onto a WorkerResult."""
        worker_id = self._workspace_id or "unknown"
        status_value = getattr(workspace_run, "status", None)
        # Substrate status: ``finished`` / ``exhausted`` / ``failed`` /
        # ``stopped``. We treat ``failed`` and ``stopped`` as non-zero
        # exits; ``finished`` and ``exhausted`` are success-equivalent.
        is_success = status_value in {"finished", "exhausted", None}
        settled_ref = getattr(workspace_run, "run_ref", None)
        changeset_stat: dict[str, Any] | None = None
        try:
            changeset = workspace_run.changeset()
            stat = changeset.stat()
            changeset_stat = {
                "output_id": stat.output_id,
                "output_name": stat.output_name,
                "binding": stat.binding,
                "state": stat.state,
                "changed_path_count": stat.changed_path_count,
            }
        except Exception:
            logger.exception("Shepherd changeset read failed for %s", worker_id)

        if is_success:
            self._status = WorkerStatus.COMPLETED
            result = WorkerResult(
                worker_id=worker_id,
                status=WorkerStatus.COMPLETED,
                output=None,
                error=None,
                exit_code=0,
                duration_seconds=duration,
                metadata={
                    "runtime": "shepherd",
                    "placement": self.placement,
                    "backend": self._capability.backend,
                    "task_ref": task_ref,
                    "command": command,
                    "settle_ref": str(settled_ref) if settled_ref else None,
                    "changeset": changeset_stat,
                },
            )
        else:
            self._status = WorkerStatus.FAILED
            result = WorkerResult(
                worker_id=worker_id,
                status=WorkerStatus.FAILED,
                output=None,
                error=f"Workspace run ended in {status_value!r}",
                exit_code=1,
                duration_seconds=duration,
                metadata={
                    "runtime": "shepherd",
                    "placement": self.placement,
                    "backend": self._capability.backend,
                    "task_ref": task_ref,
                    "command": command,
                    "settle_ref": str(settled_ref) if settled_ref else None,
                    "changeset": changeset_stat,
                },
            )

        # Mirror to Session-Buddy when a client is configured; the
        # ``worker_settle`` MCP tool (Phase 2) reads from there.
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            loop.create_task(self._store_result(result))
        return result

    async def _store_result(self, result: WorkerResult) -> None:
        """Persist the result to Session-Buddy when a client is configured."""
        if not self.session_buddy_client:
            return
        try:
            await self.session_buddy_client.call_tool(
                "store_memory",
                arguments={
                    "content": json.dumps(
                        {
                            "worker_id": result.worker_id,
                            "command": result.metadata.get("command"),
                            "task_ref": result.metadata.get("task_ref"),
                            "settle_ref": result.metadata.get("settle_ref"),
                            "changeset": result.metadata.get("changeset"),
                            "duration_seconds": result.duration_seconds,
                            "status": result.status.value,
                        }
                    ),
                    "metadata": {
                        "type": "worker_result",
                        "worker_type": self.worker_type,
                        "runtime": "shepherd",
                        "placement": self.placement,
                        "backend": self._capability.backend,
                        "timestamp": time.time(),
                    },
                },
            )
        except Exception:
            logger.exception("Failed to store shepherd result in Session-Buddy")

    async def stop(self) -> None:
        """Close the Shepherd workspace.

        Raises:
            RuntimeError: If the workspace close call fails.
        """
        if self._workspace is None:
            return
        try:
            close = getattr(self._workspace, "close", None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
            self._status = WorkerStatus.COMPLETED
            logger.info("Stopped shepherd worker: %s", self._workspace_id)
        except Exception as exc:
            logger.exception("Failed to close shepherd workspace %s", self._workspace_id)
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Failed to close Shepherd workspace: {exc}") from exc
        finally:
            self._running = False
            self._workspace = None
            self._workspace_id = None

    async def status(self) -> WorkerStatus:
        """Return the current worker status.

        The substrate does not expose a synchronous liveness probe; we
        mirror the local ``_running`` flag and surface ``FAILED`` if the
        workspace handle has been released.
        """
        if self._workspace is None or self._workspace_id is None:
            return WorkerStatus.PENDING
        if not self._running:
            return WorkerStatus.COMPLETED
        return WorkerStatus.RUNNING

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details including the workspace ID,
            placement, resolved carrier backend, and running flag.
        """
        return {
            "status": await self.status(),
            "workspace_id": self._workspace_id,
            "runtime": "shepherd",
            "placement": self.placement,
            "backend": self._capability.backend,
            "writable_root": str(self.writable_root),
            "running": self._running,
        }


__all__ = [
    "ShepherdBackendError",
    "ShepherdBackendWorker",
    "ShepherdJailUnavailableError",
    "probe_host_capability",
]


def _compose_shell_task(command: str) -> Any:
    """Module-level shell-task factory for :meth:`ShepherdBackendWorker._wrap_command`.

    Lives at module scope so the decorated task carries a stable
    ``__module__`` / ``__qualname__`` — Shepherd's ``coerce_task_ref``
    refuses callables whose qualname contains ``<locals>`` (lambdas,
    inner functions). The factory composes a single module-level
    ``_command_body`` per call.

    We return the *raw* callable (not the ``CallableTask`` wrapper
    that ``@shepherd.task`` would yield), because
    :func:`coerce_task_ref` derives the task identity from the
    callable's own ``__module__`` / ``__qualname__`` — feeding it the
    ``CallableTask`` wrapper surfaces an opaque object whose
    identity Shepherd refuses to resolve. The wrapper's ``execute``
    passes this callable straight to ``workspace.run``; Shepherd's
    compiler picks the right surface ruleset from the callable's
    declared ``May[GitRepo, ...]`` parameters at run time.

    The :mod:`_exec_guard` at the ``execute`` boundary ensures the
    command is on the allowlist before we reach here.
    """

    def _command_body() -> str:
        return command

    _command_body.__name__ = f"_shell_body_for_{command[:32]}"
    _command_body.__qualname__ = f"_command_body.{_command_body.__name__}"
    return _command_body
