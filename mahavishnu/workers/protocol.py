"""Shared terminal-worker execution protocol.

Defines the structural contract that all terminal-based workers must satisfy.
Both GenericShellWorker and any compatibility shims conform to this protocol.
"""

from typing import Any, Protocol, runtime_checkable

from .base import WorkerResult, WorkerStatus


@runtime_checkable
class TerminalWorkerProtocol(Protocol):
    """Structural protocol for terminal-based workers.

    Formalises the shared execution contract covering launcher abstractions,
    completion detection, and lifecycle management.  Any class that implements
    these members satisfies the protocol without explicit inheritance.

    Contract guarantees:
    - ``start()`` returns a session identifier and transitions the worker to RUNNING.
    - ``execute()`` delivers a prompt, waits for completion, and returns a result.
    - ``stop()`` closes the underlying terminal session.
    - ``status()`` reflects the current lifecycle state.
    - ``get_progress()`` returns a snapshot suitable for monitoring dashboards.
    """

    worker_type: str
    session_id: str | None

    async def start(self) -> str:
        """Launch the terminal session and return its session ID."""
        ...

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Deliver *task* to the worker and return the collected result."""
        ...

    async def stop(self) -> None:
        """Close the terminal session and release resources."""
        ...

    async def status(self) -> WorkerStatus:
        """Return the current lifecycle status of this worker."""
        ...

    async def get_progress(self) -> dict[str, Any]:
        """Return a progress snapshot for monitoring."""
        ...


__all__ = ["TerminalWorkerProtocol"]
