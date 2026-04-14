"""Workflow orchestration adapters package.

Note: PrefectAdapter is implemented in mahavishnu.engines.prefect_adapter_impl.
"""

# Handle optional dependency gracefully (prefect may not be installed)
try:
    from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter

    _prefect_available = True
except ImportError:
    PrefectAdapter = None  # type: ignore[misc,assignment]
    _prefect_available = False

__all__ = ["PrefectAdapter"] if _prefect_available else []
