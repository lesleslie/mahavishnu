"""Flow registry for Prefect flow management.

This module provides an in-memory registry for tracking and managing Prefect flows.
The registry allows registration, retrieval, listing, and unregistration of flows.

Example:
    ```python
    from mahavishnu.engines.prefect_registry import FlowRegistry
    from prefect import flow

    @flow
    def my_flow():
        pass

    registry = FlowRegistry()
    flow_id = registry.register_flow(my_flow, "my-flow", tags=["etl", "production"])
    registered = registry.get_flow(flow_id)
    flows = registry.list_flows(tags=["etl"])
    registry.unregister_flow(flow_id)
    ```
"""

import logging
import uuid
from typing import Any, Callable

from prefect import Flow

logger = logging.getLogger(__name__)


class FlowRegistry:
    """In-memory registry for Prefect flow management.

    Provides a centralized location for tracking flows that can be
    deployed and executed through the PrefectAdapter.

    Attributes:
        _flows: Dictionary mapping flow IDs to flow metadata
        _flow_funcs: Dictionary mapping flow IDs to flow functions

    Example:
        ```python
        registry = FlowRegistry()

        # Register a flow
        @flow(name="my-etl-flow")
        def etl_flow():
            pass

        flow_id = registry.register_flow(
            etl_flow,
            name="my-etl-flow",
            tags=["etl", "production"],
        )

        # Retrieve the flow
        flow_func = registry.get_flow(flow_id)

        # List flows by tag
        etl_flows = registry.list_flows(tags=["etl"])

        # Unregister when done
        registry.unregister_flow(flow_id)
        ```
    """

    def __init__(self) -> None:
        """Initialize an empty flow registry."""
        self._flows: dict[str, dict[str, Any]] = {}
        self._flow_funcs: dict[str, Callable] = {}

    def register_flow(
        self,
        flow_func: Callable,
        name: str,
        tags: list[str] | None = None,
    ) -> str:
        """Register a flow function in the registry.

        Args:
            flow_func: The Prefect flow function (decorated with @flow)
            name: Human-readable name for the flow
            tags: Optional list of tags for categorization

        Returns:
            Unique flow ID string

        Raises:
            ValueError: If flow_func is not callable

        Example:
            ```python
            @flow(name="data-pipeline")
            def data_pipeline():
                pass

            flow_id = registry.register_flow(
                data_pipeline,
                name="data-pipeline",
                tags=["data", "pipeline"],
            )
            ```
        """
        if not callable(flow_func):
            raise ValueError("flow_func must be callable")

        flow_id = str(uuid.uuid4())
        flow_name = getattr(flow_func, "__name__", name)

        # Extract Prefect flow metadata if available
        prefect_name = getattr(flow_func, "name", None) or flow_name

        self._flows[flow_id] = {
            "id": flow_id,
            "name": name,
            "func_name": flow_name,
            "prefect_name": prefect_name,
            "tags": tags or [],
            "registered_at": __import__("datetime").datetime.now(
                tz=__import__("datetime").timezone.utc
            ),
        }
        self._flow_funcs[flow_id] = flow_func

        logger.info(
            "Registered flow in registry",
            extra={
                "flow_id": flow_id,
                "name": name,
                "prefect_name": prefect_name,
                "tags": tags or [],
            },
        )

        return flow_id

    def get_flow(self, flow_id: str) -> Flow | Callable | None:
        """Get a registered flow function by ID.

        Args:
            flow_id: The unique flow identifier returned from register_flow

        Returns:
            The flow function if found, None otherwise

        Example:
            ```python
            flow_func = registry.get_flow("abc-123")
            if flow_func:
                result = await flow_func()
            ```
        """
        return self._flow_funcs.get(flow_id)

    def list_flows(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """List registered flows, optionally filtered by tags.

        If tags are provided, only flows that have ALL specified tags
        are returned (AND logic).

        Args:
            tags: Optional list of tags to filter by (AND logic)

        Returns:
            List of flow metadata dictionaries, each containing:
                - id: Unique flow ID
                - name: Human-readable flow name
                - func_name: Function name
                - prefect_name: Prefect flow name
                - tags: List of tags
                - registered_at: Registration timestamp

        Example:
            ```python
            # List all flows
            all_flows = registry.list_flows()

            # List flows tagged with "production"
            prod_flows = registry.list_flows(tags=["production"])

            # List flows with both "etl" AND "production" tags
            prod_etl = registry.list_flows(tags=["etl", "production"])
            ```
        """
        flows = list(self._flows.values())

        if tags:
            # Filter by tags - flow must have ALL specified tags
            filtered = []
            for flow_meta in flows:
                flow_tags = set(flow_meta.get("tags", []))
                if all(tag in flow_tags for tag in tags):
                    filtered.append(flow_meta)
            flows = filtered

        return flows

    def unregister_flow(self, flow_id: str) -> bool:
        """Remove a flow from the registry.

        Args:
            flow_id: The unique flow identifier to remove

        Returns:
            True if the flow was removed, False if it wasn't found

        Example:
            ```python
            success = registry.unregister_flow("abc-123")
            if success:
                print("Flow removed from registry")
            ```
        """
        if flow_id in self._flows:
            flow_name = self._flows[flow_id].get("name", "unknown")
            del self._flows[flow_id]
            del self._flow_funcs[flow_id]

            logger.info(
                "Unregistered flow from registry",
                extra={"flow_id": flow_id, "name": flow_name},
            )

            return True

        logger.warning(
            "Attempted to unregister non-existent flow",
            extra={"flow_id": flow_id},
        )

        return False

    def get_flow_metadata(self, flow_id: str) -> dict[str, Any] | None:
        """Get metadata for a registered flow without the function.

        Args:
            flow_id: The unique flow identifier

        Returns:
            Flow metadata dictionary if found, None otherwise

        Example:
            ```python
            metadata = registry.get_flow_metadata("abc-123")
            if metadata:
                print(f"Flow name: {metadata['name']}")
                print(f"Tags: {metadata['tags']}")
            ```
        """
        return self._flows.get(flow_id)

    def clear(self) -> int:
        """Clear all flows from the registry.

        Returns:
            Number of flows that were removed

        Example:
            ```python
            count = registry.clear()
            print(f"Removed {count} flows from registry")
            ```
        """
        count = len(self._flows)
        self._flows.clear()
        self._flow_funcs.clear()

        logger.info(
            "Cleared flow registry",
            extra={"flows_removed": count},
        )

        return count

    def count(self) -> int:
        """Get the number of registered flows.

        Returns:
            Number of flows in the registry
        """
        return len(self._flows)

    def find_by_name(self, name: str) -> list[dict[str, Any]]:
        """Find flows by name (exact match).

        Args:
            name: Flow name to search for

        Returns:
            List of matching flow metadata dictionaries

        Example:
            ```python
            matches = registry.find_by_name("my-etl-flow")
            for flow in matches:
                print(f"Found: {flow['id']} - {flow['name']}")
            ```
        """
        return [f for f in self._flows.values() if f.get("name") == name]

    def find_by_prefect_name(self, prefect_name: str) -> list[dict[str, Any]]:
        """Find flows by Prefect flow name.

        Args:
            prefect_name: Prefect flow name to search for

        Returns:
            List of matching flow metadata dictionaries

        Example:
            ```python
            matches = registry.find_by_prefect_name("data-pipeline-flow")
            ```
        """
        return [f for f in self._flows.values() if f.get("prefect_name") == prefect_name]


# Global registry instance for convenience
_global_registry: FlowRegistry | None = None


def get_flow_registry() -> FlowRegistry:
    """Get the global flow registry instance.

    Creates the registry on first access (lazy initialization).

    Returns:
        The global FlowRegistry instance

    Example:
        ```python
        registry = get_flow_registry()
        flow_id = registry.register_flow(my_flow, "my-flow")
        ```
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = FlowRegistry()
    return _global_registry


def reset_flow_registry() -> None:
    """Reset the global flow registry.

    Useful for testing or when you need a fresh registry.

    Example:
        ```python
        reset_flow_registry()
        registry = get_flow_registry()
        assert registry.count() == 0
        ```
    """
    global _global_registry
    _global_registry = None


__all__ = [
    "FlowRegistry",
    "get_flow_registry",
    "reset_flow_registry",
]
