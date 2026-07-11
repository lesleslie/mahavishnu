"""Shared terminal-worker execution protocol.

Defines the structural contract that all terminal-based workers must satisfy.
Both GenericShellWorker and any compatibility shims conform to this protocol.
"""

from typing import Any, Protocol, TypedDict, TypeGuard

from .base import WorkerResult, WorkerStatus


class ProgressSnapshot(TypedDict):
    """Typed shape returned by TerminalWorkerProtocol.get_progress().

    All keys are always present; optional fields carry their zero/None values
    rather than being absent.
    """

    status: str
    session_id: str | None
    output_preview: str
    duration_seconds: float
    worker_type: str
    worker_name: str
    category: str


class TerminalWorkerProtocol(Protocol):
    """Structural protocol for terminal-based workers.

    Formalises the shared execution contract covering launcher abstractions,
    completion detection, and lifecycle management.  Any class that implements
    these members satisfies the protocol without explicit inheritance.

    Contract guarantees:
    - ``start()`` returns a session identifier and transitions the worker to RUNNING.
      After ``start()`` returns, ``session_id`` is guaranteed to be a non-None str.
      Callers must not write to ``session_id`` directly.
    - ``execute()`` delivers a prompt, waits for completion, and returns a result.
    - ``stop()`` closes the underlying terminal session and is safe to call twice.
    - ``status()`` reflects the current lifecycle state by querying the terminal.
    - ``get_progress()`` returns a ``ProgressSnapshot`` for monitoring dashboards.
    - ``health_check()`` returns a health dict delegating to ``status()`` by default.

    Runtime conformance:
    Use ``is_terminal_worker()`` for accurate runtime checks — it verifies attribute
    names *and* that ``worker_type`` is actually a ``str``.  Avoid relying on
    ``isinstance()`` alone, which only checks that method names exist.
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

    async def get_progress(self) -> ProgressSnapshot:
        """Return a typed progress snapshot for monitoring."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Return health status; delegates to status() by default."""
        ...


def is_terminal_worker(obj: object) -> TypeGuard[TerminalWorkerProtocol]:
    """Return True when *obj* structurally satisfies TerminalWorkerProtocol.

    More accurate than ``isinstance(obj, TerminalWorkerProtocol)`` because it
    also verifies that ``worker_type`` is a ``str`` — a check that the Protocol's
    ``@runtime_checkable`` decorator cannot perform.
    """
    return (
        hasattr(obj, "worker_type")
        and isinstance(obj.worker_type, str)
        and hasattr(obj, "session_id")
        and hasattr(obj, "start")
        and hasattr(obj, "execute")
        and hasattr(obj, "stop")
        and hasattr(obj, "status")
        and hasattr(obj, "get_progress")
        and hasattr(obj, "health_check")
    )


__all__ = ["ProgressSnapshot", "TerminalWorkerProtocol", "is_terminal_worker"]
