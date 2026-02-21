"""Workflow orchestration adapters package.

Note: PrefectAdapter has moved to mahavishnu.engines.prefect_adapter.
The import from this module is deprecated but maintained for backward compatibility.
"""

# Import from engines module with deprecation warning
# The deprecation warning is emitted by the workflow/prefect_adapter module
# Handle optional dependency gracefully (prefect may not be installed)
try:
    from mahavishnu.adapters.workflow.prefect_adapter import PrefectAdapter
    _prefect_available = True
except ImportError:
    PrefectAdapter = None  # type: ignore[misc,assignment]
    _prefect_available = False

__all__ = ["PrefectAdapter"] if _prefect_available else []
