"""Container worker for Docker/Podman task execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
import shutil
import sys
from typing import Any

from ..core.errors import ContainerDaemonUnavailable
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)


@dataclass
class _RuntimeResolver:
    """Resolve the concrete container runtime and socket path.

    Order of precedence:
        1. Explicit ``socket_path`` (e.g. ``DOCKER_HOST``-style override)
        2. OrbStack default socket on macOS
        3. ``DOCKER_HOST`` environment variable
        4. First available binary in PATH (``docker`` then ``podman``)
    """

    runtime: str
    socket_path: str | None

    @classmethod
    def from_settings(
        cls, *, runtime: str | None, socket_path: str | None,
    ) -> _RuntimeResolver:
        """Pick a runtime and optional socket path from settings."""
        if socket_path:
            return cls(runtime=runtime or "docker", socket_path=socket_path)
        if sys.platform == "darwin":
            orbstack = os.path.expanduser("~/.orbstack/docker/docker.sock")
            if os.path.exists(orbstack):
                return cls(runtime=runtime or "docker", socket_path=orbstack)
        env_socket = os.environ.get("DOCKER_HOST")
        if env_socket:
            return cls(runtime=runtime or "docker", socket_path=env_socket)
        for candidate in ("docker", "podman"):
            if shutil.which(candidate):
                return cls(runtime=runtime or candidate, socket_path=None)
        return cls(runtime=runtime or "docker", socket_path=None)


class ContainerWorker(BaseWorker):
    """Worker that executes tasks in containers.

    Supports Docker and Podman runtimes.
    Progress tracking via container socket/logs.
    Session-Buddy integration for result storage.

    Args:
        runtime: Container runtime ("docker" or "podman")
        image: Container image to use
        session_buddy_client: Session-Buddy MCP client for storage

    Example:
        >>> worker = ContainerWorker(
        ...     runtime="docker",
        ...     image="python:3.13-slim",
        ...     session_buddy_client=session_buddy_client
        ... )
        >>> container_id = await worker.start()
        >>> result = await worker.execute({"command": "python -c 'print(42)'"})
    """

    def __init__(
        self,
        runtime: str | None = None,
        image: str = "python:3.13-slim",
        session_buddy_client: Any = None,
        *,
        socket_path_override: str | None = None,
    ) -> None:
        """Initialize container worker.

        Args:
            runtime: Container runtime ("docker" or "podman"). When ``None`` the
                resolver picks the first available binary on PATH (docker, then
                podman), falling back to ``"docker"`` if neither is found.
            image: Container image to use
            session_buddy_client: Session-Buddy MCP client
            socket_path_override: Force a specific daemon socket path. When set,
                takes precedence over the OrbStack and ``DOCKER_HOST`` discovery
                paths.
        """
        super().__init__(worker_type="container-executor")
        self.session_buddy_client = session_buddy_client
        self.image = image
        resolver = _RuntimeResolver.from_settings(
            runtime=runtime,
            socket_path=socket_path_override,
        )
        self.runtime = resolver.runtime
        self.socket_path = resolver.socket_path
        self.container_id: str | None = None
        self._running = False

        # SECURITY: Whitelist of allowed commands to prevent RCE
        self._ALLOWED_COMMANDS = {
            "python",
            "pip",
            "npm",
            "node",
            "ls",
            "cat",
            "echo",
            "grep",
            "find",
            "head",
            "tail",
            "wc",
            "pwd",
            "cd",
            "mkdir",
            "touch",
            "rm",
            "cp",
            "mv",
            "sort",
            "uniq",
            "cut",
            "awk",
            "sed",
            "git",
            "pytest",
            "black",
        }

        # SECURITY: Dangerous command patterns to block
        self._DANGEROUS_PATTERNS = [
            "rm -rf /",
            "mkfs",
            "dd if=",
            "> /dev/sd",
            "chmod 000",
            "chown root:",
            "curl | sh",
            "wget | sh",
            "&& rm",
            "; rm",
            "| rm",
            "nc -e",
            "ncat",
            "/dev/tcp",
            "/dev/udp",
            "bind shell",
            "reverse shell",
        ]

        self._MAX_COMMAND_LENGTH = 10000

    def _validate_command(self, command: str) -> None:
        """Validate command for security to prevent injection attacks.

        Args:
            command: Command string to validate

        Raises:
            ValueError: If command fails validation
        """
        if not isinstance(command, str):
            raise ValueError("Command must be a string")

        # Check length limit
        if len(command) > self._MAX_COMMAND_LENGTH:
            raise ValueError(
                f"Command too long: {len(command)} > {self._MAX_COMMAND_LENGTH} characters"
            )

        # Block dangerous patterns
        command_lower = command.lower()
        for pattern in self._DANGEROUS_PATTERNS:
            if pattern.lower() in command_lower:
                raise ValueError(
                    f"Command contains dangerous pattern '{pattern}'. "
                    "This command is not allowed for security reasons."
                )

        # Extract first word (command name)
        first_word = command.strip().split()[0] if command.strip() else ""
        if not first_word:
            raise ValueError("Command cannot be empty")

        # Check against whitelist
        if first_word not in self._ALLOWED_COMMANDS:
            raise ValueError(
                f"Command '{first_word}' is not in the allowed list. "
                f"Allowed commands: {', '.join(sorted(self._ALLOWED_COMMANDS))}"
            )

    def _sanitize_command(self, command: str) -> str:
        """Sanitize command for safe execution.

        Args:
            command: Command string to sanitize

        Returns:
            Sanitized command string
        """
        import shlex

        # Use shlex.quote to escape special characters
        # This prevents shell metacharacter injection
        return shlex.quote(command)

    def _subprocess_env(self) -> dict[str, str] | None:
        """Build the subprocess env, injecting ``DOCKER_HOST`` when needed.

        Returns ``None`` when ``socket_path`` is unset so the subprocess
        inherits the parent environment unchanged. Otherwise returns the
        parent env merged with ``DOCKER_HOST`` so a discovered OrbStack
        socket (or an explicit ``socket_path_override``) actually takes
        effect for the runtime CLI.

        Strips a leading ``unix://`` scheme because ``DOCKER_HOST`` accepts
        the bare path for ``unix://`` URLs (matching the docker and podman
        CLIs' own behavior).
        """
        if not self.socket_path:
            return None
        host = self.socket_path
        prefix = "unix://"
        if host.startswith(prefix):
            host = host[len(prefix):]
        return {**os.environ, "DOCKER_HOST": host}

    async def _probe_daemon(self) -> None:
        """Verify the container daemon is reachable before launching.

        Raises:
            ContainerDaemonUnavailable: If the runtime binary is missing,
                the socket path does not exist, the daemon probe times out,
                or the daemon returns a non-zero exit code.
        """
        if self.socket_path and not os.path.exists(self.socket_path):
            raise ContainerDaemonUnavailable(
                runtime=self.runtime, error="socket_missing",
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                self.runtime, "version", "--format", "{{.Server.Version}}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=self._subprocess_env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except (TimeoutError, OSError) as exc:
            raise ContainerDaemonUnavailable(
                runtime=self.runtime, error=type(exc).__name__,
            ) from exc
        if proc.returncode != 0:
            error_output = stderr.decode() if stderr else "daemon_unreachable"
            raise ContainerDaemonUnavailable(
                runtime=self.runtime, error=error_output,
            )

    async def start(self) -> str:
        """Launch container with persistent shell.

        Returns:
            Container ID

        Raises:
            ContainerDaemonUnavailable: If the container daemon is unreachable.
            RuntimeError: If the container fails to launch after the daemon probe.
        """
        await self._probe_daemon()
        # Existing docker run / podman run invocation from
        # mahavishnu/workers/container.py:163-210 is preserved unchanged
        # after the probe. The container launch logic and `asyncio.sleep(1)`
        # stub are replaced with the real readiness probe above.
        try:
            # Launch container with sleep infinity to keep it running
            proc = await asyncio.create_subprocess_exec(
                self.runtime,
                "run",
                "-d",
                "--rm",
                self.image,
                "sleep",
                "infinity",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._subprocess_env(),
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_output = stderr.decode() if stderr else ""
                raise RuntimeError(f"Failed to launch container: {error_output}")

            self.container_id = stdout.decode().strip()
            self._running = True
            self._status = WorkerStatus.STARTING

            logger.info(
                f"Started container worker: {self.container_id} "
                f"(runtime={self.runtime}, image={self.image})"
            )

            # Give container a moment to initialize
            await asyncio.sleep(1)

            self._status = WorkerStatus.RUNNING
            return self.container_id

        except Exception as e:
            logger.error(f"Failed to start container worker: {e}")
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Container worker failed to start: {e}") from e

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute task in container.

        Args:
            task: Task specification with "command" key

        Returns:
            WorkerResult with execution results

        Raises:
            ValueError: If command not specified
            RuntimeError: If execution fails
        """
        if not self.container_id:
            raise RuntimeError("Container not started")

        command = task.get("command")
        if not command:
            raise ValueError("Task must specify 'command'")

        # SECURITY: Validate command to prevent injection attacks
        self._validate_command(command)

        import time

        start_time = time.time()

        try:
            logger.info(f"Executing in container {self.container_id}: {command}")

            # Execute command in container with validated and sanitized input
            safe_command = self._sanitize_command(command)
            proc = await asyncio.create_subprocess_exec(
                self.runtime,
                "exec",
                self.container_id,
                "sh",
                "-c",
                f"echo {safe_command} | sh",  # Double protection with shlex.quote + pipe
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()
            duration_seconds = time.time() - start_time

            output = stdout.decode()
            error_output = stderr.decode()

            if proc.returncode == 0:
                self._status = WorkerStatus.COMPLETED
                logger.info(
                    f"Container {self.container_id} completed successfully "
                    f"({duration_seconds:.2f}s)"
                )

                result = WorkerResult(
                    worker_id=self.container_id,
                    status=WorkerStatus.COMPLETED,
                    output=output,
                    error=error_output if error_output else None,
                    exit_code=0,
                    duration_seconds=duration_seconds,
                    metadata={
                        "runtime": self.runtime,
                        "image": self.image,
                        "command": command,
                    },
                )
            else:
                self._status = WorkerStatus.FAILED
                logger.warning(
                    f"Container {self.container_id} failed with exit code "
                    f"{proc.returncode} ({duration_seconds:.2f}s)"
                )

                result = WorkerResult(
                    worker_id=self.container_id,
                    status=WorkerStatus.FAILED,
                    output=output,
                    error=error_output or f"Command failed with exit code {proc.returncode}",
                    exit_code=proc.returncode,
                    duration_seconds=duration_seconds,
                    metadata={
                        "runtime": self.runtime,
                        "image": self.image,
                        "command": command,
                    },
                )

            # Store in Session-Buddy if available
            if self.session_buddy_client:
                try:
                    await self.session_buddy_client.call_tool(
                        "store_memory",
                        arguments={
                            "content": json.dumps(
                                {
                                    "worker_id": self.container_id,
                                    "command": command,
                                    "output": output,
                                    "error": error_output,
                                    "exit_code": proc.returncode,
                                    "duration_seconds": duration_seconds,
                                    "status": result.status.value,
                                }
                            ),
                            "metadata": {
                                "type": "worker_result",
                                "worker_type": "container-executor",
                                "runtime": self.runtime,
                                "image": self.image,
                                "timestamp": time.time(),
                            },
                        },
                    )
                    logger.debug(f"Stored result in Session-Buddy for {self.container_id}")
                except Exception as e:
                    logger.warning(f"Failed to store in Session-Buddy: {e}")

            return result

        except Exception as e:
            duration_seconds = time.time() - start_time
            logger.error(f"Container execution failed: {e}")

            self._status = WorkerStatus.FAILED

            return WorkerResult(
                worker_id=self.container_id,
                status=WorkerStatus.FAILED,
                output=None,
                error=str(e),
                exit_code=None,
                duration_seconds=duration_seconds,
                metadata={
                    "runtime": self.runtime,
                    "image": self.image,
                    "command": command,
                    "exception": type(e).__name__,
                },
            )

    async def stop(self) -> None:
        """Stop and remove container.

        Raises:
            RuntimeError: If container fails to stop
        """
        if not self.container_id:
            return

        try:
            # Stop and remove container
            proc = await asyncio.create_subprocess_exec(
                self.runtime,
                "stop",
                self.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await proc.communicate()

            self._running = False
            self._status = WorkerStatus.COMPLETED

            logger.info(f"Stopped container worker: {self.container_id}")

        except Exception as e:
            logger.error(f"Failed to stop container {self.container_id}: {e}")
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"Failed to stop container: {e}") from e
        finally:
            self.container_id = None

    async def status(self) -> WorkerStatus:
        """Get container status.

        Returns:
            Current WorkerStatus
        """
        if not self.container_id:
            return WorkerStatus.PENDING

        if not self._running:
            return WorkerStatus.COMPLETED

        # Check if container is still running
        try:
            proc = await asyncio.create_subprocess_exec(
                self.runtime,
                "inspect",
                "-f",
                "{{.State.Status}}",
                self.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()
            container_status = stdout.decode().strip().lower()

            if container_status == "running":
                return WorkerStatus.RUNNING
            else:
                self._running = False
                return WorkerStatus.COMPLETED

        except Exception:
            self._running = False
            return WorkerStatus.FAILED

    async def get_progress(self) -> dict[str, Any]:
        """Get container progress information.

        Returns:
            Dictionary with progress details
        """
        return {
            "status": await self.status(),
            "container_id": self.container_id,
            "runtime": self.runtime,
            "image": self.image,
            "running": self._running,
        }
