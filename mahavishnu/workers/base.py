"""Base worker interface for task execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mahavishnu.core.status import WorkerStatus


@dataclass
class WorkerResult:
    """Result from worker execution.

    Attributes:
        worker_id: Unique identifier for the worker
        status: Final execution status
        output: Worker output (stdout, response, etc.)
        error: Error message if execution failed
        exit_code: Process exit code (if applicable)
        duration_seconds: Execution duration in seconds
        metadata: Additional worker-specific metadata
        timestamp: When the result was generated
    """

    worker_id: str
    status: WorkerStatus
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerResult":
        """Create WorkerResult from dictionary.

        Args:
            data: Dictionary with result data

        Returns:
            WorkerResult instance
        """
        # Convert status string back to enum
        status_str = data.get("status", "unknown")
        status = WorkerStatus(status_str) if isinstance(status_str, str) else data.get("status")

        return cls(
            worker_id=data["worker_id"],
            status=status,
            output=data.get("output"),
            error=data.get("error"),
            exit_code=data.get("exit_code"),
            duration_seconds=data.get("duration_seconds", 0.0),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary.

        Returns:
            Dictionary representation of the result
        """
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    def is_success(self) -> bool:
        """Check if worker execution was successful.

        Returns:
            True if worker completed successfully
        """
        return self.status == WorkerStatus.COMPLETED

    def has_output(self) -> bool:
        """Check if worker produced output.

        Returns:
            True if output exists and is non-empty
        """
        return bool(self.output)

    def get_summary(self) -> str:
        """Get brief summary of result.

        Returns:
            One-line summary string
        """
        status_emoji = {
            WorkerStatus.COMPLETED: "✅",
            WorkerStatus.FAILED: "❌",
            WorkerStatus.TIMEOUT: "⏱️",
            WorkerStatus.CANCELLED: "🚫",
            WorkerStatus.RUNNING: "🔄",
            WorkerStatus.PENDING: "⏳",
            WorkerStatus.STARTING: "🔄",
        }.get(self.status, "❓")

        output_preview = (
            (self.output[:50] + "...")
            if self.output and len(self.output) > 50
            else self.output or ""
        )

        if self.is_success():
            return f"{status_emoji} {self.worker_id}: {output_preview}"
        else:
            error_msg = self.error or "Unknown error"
            return f"{status_emoji} {self.worker_id}: {error_msg}"


class BaseWorker(ABC):
    """Base class for all worker types.

    All workers must implement these core lifecycle methods:
    - start(): Initialize the worker and return worker_id
    - execute(): Execute a task and return results
    - stop(): Gracefully terminate the worker
    - status(): Get current execution status
    - get_progress(): Get progress information
    """

    def __init__(self, worker_type: str) -> None:
        """Initialize worker.

        Args:
            worker_type: Type identifier for this worker
        """
        self.worker_type = worker_type
        self._status = WorkerStatus.PENDING

    @abstractmethod
    async def start(self) -> str:
        """Start the worker and return worker_id.

        Returns:
            Unique identifier for this worker instance

        Raises:
            RuntimeError: If worker fails to start
        """
        pass

    @abstractmethod
    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task and return results.

        Args:
            task: Task specification with worker-specific parameters

        Returns:
            WorkerResult with execution status, output, and metadata

        Raises:
            RuntimeError: If execution fails
            TimeoutError: If task execution times out
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the worker gracefully.

        Raises:
            RuntimeError: If worker fails to stop
        """
        pass

    @abstractmethod
    async def status(self) -> WorkerStatus:
        """Get current worker status.

        Returns:
            Current WorkerStatus
        """
        pass

    @abstractmethod
    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details including:
            - status: Current status
            - output_preview: Recent output (if available)
            - duration: Execution time in seconds
            - metadata: Worker-specific progress data
        """
        pass

    async def health_check(self) -> dict[str, Any]:
        """Check worker health and availability.

        Returns:
            Dictionary with health status:
            - healthy: bool
            - status: WorkerStatus
            - worker_type: str
            - details: Additional health details
        """
        try:
            current_status = await self.status()
            return {
                "healthy": current_status in (WorkerStatus.RUNNING, WorkerStatus.PENDING),
                "status": current_status.value,
                "worker_type": self.worker_type,
                "details": {},
            }
        except Exception as e:
            return {
                "healthy": False,
                "status": "unknown",
                "worker_type": self.worker_type,
                "details": {"error": str(e)},
            }
