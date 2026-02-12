"""Base adapter interface for orchestrator engines."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class AdapterType(str, Enum):
    """Enumeration of adapter types."""

    PREFECT = "prefect"
    AGNO = "agno"
    LLAMAINDEX = "llamaindex"


class AdapterCapabilities:
    """Adapter capabilities flags."""

    def __init__(
        self,
        can_deploy_flows: bool = False,
        can_monitor_execution: bool = False,
        can_cancel_workflows: bool = False,
        can_sync_state: bool = False,
        supports_batch_execution: bool = False,
        has_cloud_ui: bool = False,
        supports_multi_agent: bool = False,
    ):
        self.can_deploy_flows = can_deploy_flows
        self.can_monitor_execution = can_monitor_execution
        self.can_cancel_workflows = can_cancel_workflows
        self.can_sync_state = can_sync_state
        self.supports_batch_execution = supports_batch_execution
        self.has_cloud_ui = has_cloud_ui
        self.supports_multi_agent = supports_multi_agent


class OrchestratorAdapter(ABC):
    """Base class for orchestrator adapters."""

    @property
    @abstractmethod
    def adapter_type(self) -> AdapterType:
        """Return adapter type enum."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return adapter name."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities."""
        pass

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
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy') and optional
            adapter-specific health details.
        """
        pass


__all__ = [
    "OrchestratorAdapter",
    "AdapterType",
    "AdapterCapabilities",
]
