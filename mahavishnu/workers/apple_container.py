"""Apple ``container`` worker — one microVM per task on Apple silicon.

Uses Apple's open-source ``container`` CLI (https://github.com/apple/container),
which runs each Linux container inside its own lightweight VM on the
Virtualization framework. Unlike the Docker/OrbStack path in
``container.py``, every task gets a dedicated guest kernel.

Host requirements (hard, per Apple's docs): Apple silicon Mac, macOS 26+.
On any other host :class:`AppleContainerUnsupported` is raised so callers
can skip to the next isolation tier (e.g. a cloud sandbox pool) instead of
failing the task.

UNVERIFIED-ON-HARDWARE: this module was authored on an Intel Mac. All CLI
invocations flow through :func:`_run_cli`; the exact flags to re-verify on
Apple silicon are listed in docs/feature-tracking/apple-container-worker.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import shutil
import sys
import time
from typing import Any

from ..core.errors import AppleContainerUnsupported, ContainerDaemonUnavailable
from . import _exec_guard
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)

_CLI = "container"
_PROBE_TIMEOUT = 5.0


def is_apple_container_supported() -> bool:
    """True when this host can run the Apple ``container`` runtime.

    Requires macOS on Apple silicon (arm64) with the ``container`` binary
    on PATH. Intel Macs and non-macOS hosts always return False — Apple
    ships the runtime as Apple-silicon-only.
    """
    if sys.platform != "darwin":
        return False
    if platform.machine() != "arm64":
        return False
    return shutil.which(_CLI) is not None


def unsupported_reason() -> str:
    """Human-readable reason the current host cannot run Apple ``container``."""
    if sys.platform != "darwin":
        return f"host platform is {sys.platform!r}, requires macOS"
    if platform.machine() != "arm64":
        return f"host architecture is {platform.machine()!r}, requires Apple silicon (arm64)"
    return "the 'container' binary is not on PATH (install from github.com/apple/container)"


async def _run_cli(*argv: str, timeout: float | None = None) -> tuple[int, str, str]:
    """Run the ``container`` CLI and return (returncode, stdout, stderr).

    Single seam for all runtime interaction — tests fake this function, and
    any flag corrections discovered on real hardware land here or in the
    callers, never in scattered subprocess calls.
    """
    proc = await asyncio.create_subprocess_exec(
        _CLI,
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if timeout is not None:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    else:
        stdout, stderr = await proc.communicate()
    returncode = proc.returncode if proc.returncode is not None else -1
    return returncode, stdout.decode(), stderr.decode()


class AppleContainerWorker(BaseWorker):
    """Worker that executes tasks in per-task Apple ``container`` microVMs.

    Mirrors the ``ContainerWorker`` lifecycle contract (start / execute /
    stop / status / get_progress) so pool routing and MCP tools above it
    are unaffected by the runtime swap.

    Args:
        image: OCI image to run (auto-pulled by the CLI on first use)
        session_buddy_client: Session-Buddy MCP client for result storage
        cpus: Optional CPU limit passed as ``--cpus``
        memory: Optional memory limit passed as ``--memory`` (e.g. "4g")

    Raises:
        AppleContainerUnsupported: On construction when the host is not an
            Apple silicon Mac with the runtime installed. Catch this to
            fall through to the next isolation tier.
    """

    def __init__(
        self,
        image: str = "python:3.13-slim",
        session_buddy_client: Any = None,
        *,
        cpus: int | None = None,
        memory: str | None = None,
    ) -> None:
        if not is_apple_container_supported():
            raise AppleContainerUnsupported(reason=unsupported_reason())
        super().__init__(worker_type="apple-container")
        self.image = image
        self.session_buddy_client = session_buddy_client
        self.cpus = cpus
        self.memory = memory
        self.container_id: str | None = None
        self._running = False

    async def _probe_runtime(self) -> None:
        """Verify the runtime's system services respond before launching.

        Raises:
            ContainerDaemonUnavailable: If the probe times out, the binary
                cannot be executed, or the services report failure.
        """
        try:
            returncode, _stdout, stderr = await _run_cli(
                "system", "status", timeout=_PROBE_TIMEOUT
            )
        except (TimeoutError, OSError) as exc:
            raise ContainerDaemonUnavailable(
                runtime="apple-container",
                error=type(exc).__name__,
            ) from exc
        if returncode != 0:
            raise ContainerDaemonUnavailable(
                runtime="apple-container",
                error=stderr or "system_services_unavailable",
            )

    def _run_argv(self) -> list[str]:
        """Build the ``container run`` argv for a persistent task microVM."""
        argv = ["run", "--detach", "--rm"]
        if self.cpus is not None:
            argv.extend(["--cpus", str(self.cpus)])
        if self.memory is not None:
            argv.extend(["--memory", self.memory])
        argv.extend([self.image, "sleep", "infinity"])
        return argv

    async def start(self, *, prompt: str | None = None) -> str:
        """Launch a microVM with a persistent shell and return its ID.

        Raises:
            ContainerDaemonUnavailable: If the runtime probe fails.
            RuntimeError: If the microVM fails to launch after the probe.
        """
        await self._probe_runtime()
        self._status = WorkerStatus.STARTING
        returncode, stdout, stderr = await _run_cli(*self._run_argv())
        if returncode != 0:
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Failed to launch Apple container: {stderr}")

        self.container_id = stdout.strip()
        self._running = True
        self._status = WorkerStatus.RUNNING
        logger.info(
            "Started apple-container worker: %s (image=%s, cpus=%s, memory=%s)",
            self.container_id,
            self.image,
            self.cpus,
            self.memory,
        )
        return self.container_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task command inside the microVM.

        Args:
            task: Task specification with a "command" key

        Returns:
            WorkerResult with execution status, output, and metadata

        Raises:
            RuntimeError: If the worker was not started
            ValueError: If the command is missing or fails validation
        """
        if not self.container_id:
            raise RuntimeError("Apple container not started")
        command = task.get("command")
        if not command:
            raise ValueError("Task must specify 'command'")
        _exec_guard.validate_command(command)

        start_time = time.time()
        safe_command = _exec_guard.sanitize_command(command)
        try:
            returncode, output, error_output = await _run_cli(
                "exec",
                self.container_id,
                "sh",
                "-c",
                f"echo {safe_command} | sh",
            )
        except OSError as exc:
            logger.exception("apple-container exec failed for %s", self.container_id)
            self._status = WorkerStatus.FAILED
            return WorkerResult(
                worker_id=self.container_id,
                status=WorkerStatus.FAILED,
                output=None,
                error=str(exc),
                exit_code=None,
                duration_seconds=time.time() - start_time,
                metadata=self._result_metadata(command) | {"exception": type(exc).__name__},
            )

        duration = time.time() - start_time
        result = self._build_result(command, returncode, output, error_output, duration)
        await self._store_result(result, command)
        return result

    def _result_metadata(self, command: str) -> dict[str, Any]:
        return {
            "runtime": "apple-container",
            "image": self.image,
            "command": command,
        }

    def _build_result(
        self,
        command: str,
        returncode: int,
        output: str,
        error_output: str,
        duration: float,
    ) -> WorkerResult:
        """Map a CLI exec result onto a WorkerResult and update status."""
        worker_id = self.container_id or "unknown"
        if returncode == 0:
            self._status = WorkerStatus.COMPLETED
            return WorkerResult(
                worker_id=worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                error=error_output or None,
                exit_code=0,
                duration_seconds=duration,
                metadata=self._result_metadata(command),
            )
        self._status = WorkerStatus.FAILED
        return WorkerResult(
            worker_id=worker_id,
            status=WorkerStatus.FAILED,
            output=output,
            error=error_output or f"Command failed with exit code {returncode}",
            exit_code=returncode,
            duration_seconds=duration,
            metadata=self._result_metadata(command),
        )

    async def _store_result(self, result: WorkerResult, command: str) -> None:
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
                            "command": command,
                            "output": result.output,
                            "error": result.error,
                            "exit_code": result.exit_code,
                            "duration_seconds": result.duration_seconds,
                            "status": result.status.value,
                        }
                    ),
                    "metadata": {
                        "type": "worker_result",
                        "worker_type": self.worker_type,
                        "runtime": "apple-container",
                        "image": self.image,
                        "timestamp": time.time(),
                    },
                },
            )
        except Exception:
            logger.exception("Failed to store apple-container result in Session-Buddy")

    async def stop(self) -> None:
        """Stop the microVM (removed automatically via ``--rm``).

        Raises:
            RuntimeError: If the runtime CLI cannot be invoked to stop it.
        """
        if not self.container_id:
            return
        try:
            await _run_cli("stop", self.container_id)
            self._status = WorkerStatus.COMPLETED
            logger.info("Stopped apple-container worker: %s", self.container_id)
        except OSError as exc:
            logger.exception("Failed to stop apple-container %s", self.container_id)
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Failed to stop Apple container: {exc}") from exc
        finally:
            self._running = False
            self.container_id = None

    async def status(self) -> WorkerStatus:
        """Get microVM status via ``container inspect``.

        Returns:
            Current WorkerStatus
        """
        if not self.container_id:
            return WorkerStatus.PENDING
        if not self._running:
            return WorkerStatus.COMPLETED
        try:
            returncode, stdout, _stderr = await _run_cli("inspect", self.container_id)
        except OSError:
            self._running = False
            return WorkerStatus.FAILED
        if returncode != 0:
            self._running = False
            return WorkerStatus.FAILED
        if _inspect_reports_running(stdout):
            return WorkerStatus.RUNNING
        self._running = False
        return WorkerStatus.COMPLETED

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details
        """
        return {
            "status": await self.status(),
            "container_id": self.container_id,
            "runtime": "apple-container",
            "image": self.image,
            "running": self._running,
        }


def _inspect_reports_running(inspect_output: str) -> bool:
    """Parse ``container inspect`` JSON and report whether the VM is running.

    Apple's CLI emits JSON (a list of container objects). The exact schema
    should be re-verified on hardware; this parser tolerates both list and
    object forms and several plausible status key spellings.
    """
    try:
        data = json.loads(inspect_output)
    except (json.JSONDecodeError, TypeError):
        return False
    entry: dict[str, Any]
    if isinstance(data, list):
        if not data or not isinstance(data[0], dict):
            return False
        entry = data[0]
    elif isinstance(data, dict):
        entry = data
    else:
        return False
    raw = entry.get("status") or entry.get("state") or entry.get("Status")
    if isinstance(raw, dict):
        raw = raw.get("status") or raw.get("Status")
    return isinstance(raw, str) and raw.strip().lower() == "running"
