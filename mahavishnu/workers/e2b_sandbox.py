"""E2B cloud sandbox worker — tier-2 isolation via Firecracker microVMs.

Executes tasks in hosted E2B sandboxes (https://e2b.dev). Each worker maps
to one sandbox session: ``start()`` creates the microVM (~150ms warm),
``execute()`` runs guarded commands inside it, ``stop()`` kills it.

This is the fallback tier when the local Apple ``container`` runtime is
unsupported (Intel Macs, Linux hosts) — see
``WorkerManager._create_isolated_worker``.

Requires the optional ``e2b`` dependency (``uv sync --group sandbox``) and
the ``E2B_API_KEY`` environment variable (read by the SDK).
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from . import _exec_guard
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Optional dependency — imported only for static analysis. The runtime
    # `else` branch below handles the install / no-install cases.
    from e2b import AsyncSandbox
else:
    try:
        from e2b import AsyncSandbox
    except ImportError:
        AsyncSandbox = None  # type: ignore[misc]

_DEFAULT_TIMEOUT_SECONDS = 300


class E2BSandboxWorker(BaseWorker):
    """Worker that executes tasks in an E2B Firecracker sandbox.

    Mirrors the AppleContainerWorker lifecycle contract so callers are
    agnostic to which isolation tier served the task.

    Args:
        template: E2B sandbox template name (default "base")
        timeout: Sandbox keep-alive in seconds (SDK kills it after this)
        api_key: Optional explicit API key; when None the SDK reads
            ``E2B_API_KEY`` from the environment
        session_buddy_client: Session-Buddy MCP client for result storage
    """

    def __init__(
        self,
        template: str = "base",
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        api_key: str | None = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(worker_type="e2b-sandbox")
        self.template = template
        self.timeout = timeout
        self._api_key = api_key
        self.session_buddy_client = session_buddy_client
        self._sandbox: Any = None
        self.sandbox_id: str | None = None
        self._running = False

    async def start(self, *, prompt: str | None = None) -> str:
        """Create the sandbox and return its ID.

        Raises:
            RuntimeError: If the ``e2b`` SDK is not installed or sandbox
                creation fails.
        """
        if AsyncSandbox is None:
            raise RuntimeError(
                "E2BSandboxWorker requires 'e2b'. Install with: uv sync --group sandbox"
            )
        self._status = WorkerStatus.STARTING
        create_kwargs: dict[str, Any] = {
            "template": self.template,
            "timeout": self.timeout,
        }
        if self._api_key is not None:
            create_kwargs["api_key"] = self._api_key
        try:
            self._sandbox = await AsyncSandbox.create(**create_kwargs)
        except Exception as e:
            self._status = WorkerStatus.FAILED
            logger.exception("Failed to create E2B sandbox (template=%s)", self.template)
            raise RuntimeError(f"E2B sandbox failed to start: {e}") from e

        self.sandbox_id = getattr(self._sandbox, "sandbox_id", None) or "e2b-sandbox"
        self._running = True
        self._status = WorkerStatus.RUNNING
        logger.info(
            "Started e2b-sandbox worker: %s (template=%s, timeout=%ss)",
            self.sandbox_id,
            self.template,
            self.timeout,
        )
        return self.sandbox_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task command inside the sandbox.

        Args:
            task: Task specification with a "command" key

        Returns:
            WorkerResult with execution status, output, and metadata

        Raises:
            RuntimeError: If the worker was not started
            ValueError: If the command is missing or fails validation
        """
        if self._sandbox is None or not self.sandbox_id:
            raise RuntimeError("E2B sandbox not started")
        command = task.get("command")
        if not command:
            raise ValueError("Task must specify 'command'")
        _exec_guard.validate_command(command)

        start_time = time.time()
        safe_command = _exec_guard.sanitize_command(command)
        exit_code, output, error_output = await self._run_in_sandbox(f"echo {safe_command} | sh")
        duration = time.time() - start_time
        result = self._build_result(command, exit_code, output, error_output, duration)
        await self._store_result(result, command)
        return result

    async def _run_in_sandbox(self, shell_command: str) -> tuple[int, str, str]:
        """Run a shell command, normalizing the SDK's raise-on-nonzero behavior.

        The e2b SDK raises ``CommandExitException`` (carrying exit_code,
        stdout, stderr) for non-zero exits; transport errors raise other
        exception types. Both are folded into (exit_code, stdout, stderr)
        so callers get uniform WorkerResult mapping.
        """
        try:
            execution = await self._sandbox.commands.run(shell_command)
        except Exception as exc:
            exit_code = getattr(exc, "exit_code", None)
            if not isinstance(exit_code, int):
                # Transport-level failure, not a command failure
                logger.exception("e2b-sandbox exec transport error for %s", self.sandbox_id)
                return -1, "", str(exc)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or str(exc)
            return exit_code, stdout, stderr
        exit_code = getattr(execution, "exit_code", 0) or 0
        stdout = getattr(execution, "stdout", "") or ""
        stderr = getattr(execution, "stderr", "") or ""
        return exit_code, stdout, stderr

    def _result_metadata(self, command: str) -> dict[str, Any]:
        return {
            "runtime": "e2b",
            "template": self.template,
            "command": command,
        }

    def _build_result(
        self,
        command: str,
        exit_code: int,
        output: str,
        error_output: str,
        duration: float,
    ) -> WorkerResult:
        """Map a sandbox exec result onto a WorkerResult and update status."""
        worker_id = self.sandbox_id or "unknown"
        if exit_code == 0:
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
            error=error_output or f"Command failed with exit code {exit_code}",
            exit_code=exit_code,
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
                        "runtime": "e2b",
                        "template": self.template,
                        "timestamp": time.time(),
                    },
                },
            )
        except Exception:
            logger.exception("Failed to store e2b-sandbox result in Session-Buddy")

    async def stop(self) -> None:
        """Kill the sandbox.

        Raises:
            RuntimeError: If the sandbox kill call fails.
        """
        if self._sandbox is None:
            return
        try:
            await self._sandbox.kill()
            self._status = WorkerStatus.COMPLETED
            logger.info("Stopped e2b-sandbox worker: %s", self.sandbox_id)
        except Exception as exc:
            logger.exception("Failed to kill e2b sandbox %s", self.sandbox_id)
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Failed to stop E2B sandbox: {exc}") from exc
        finally:
            self._running = False
            self._sandbox = None
            self.sandbox_id = None

    async def status(self) -> WorkerStatus:
        """Get sandbox status via the SDK's is_running probe when available.

        Returns:
            Current WorkerStatus
        """
        if self._sandbox is None or not self.sandbox_id:
            return WorkerStatus.PENDING
        if not self._running:
            return WorkerStatus.COMPLETED
        checker = getattr(self._sandbox, "is_running", None)
        if checker is None:
            return WorkerStatus.RUNNING
        try:
            probe = checker()
            running = await probe if inspect.isawaitable(probe) else probe
        except Exception:
            logger.exception("e2b-sandbox status probe failed for %s", self.sandbox_id)
            self._running = False
            return WorkerStatus.FAILED
        if running:
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
            "sandbox_id": self.sandbox_id,
            "runtime": "e2b",
            "template": self.template,
            "running": self._running,
        }
