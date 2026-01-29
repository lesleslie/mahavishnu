"""Base adapter interface for orchestrator engines."""

from abc import ABC, abstractmethod
from typing import Any


class OrchestratorAdapter(ABC):
    """Base class for orchestrator adapters."""

    @abstractmethod
    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """
        Execute a task using the orchestrator engine asynchronously.

        Args:
            task: Task specification
            repos: List of repository paths to operate on

        Returns:
            Execution result
        """
        pass

    @abstractmethod
    async def get_health(self) -> dict[str, Any]:
        """
        Get adapter health status asynchronously.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and optional adapter-specific health details.
        """
        pass
