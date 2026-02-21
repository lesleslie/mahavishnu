"""Prefect adapter for Mahavishnu orchestration - DEPRECATED.

.. deprecated:: 0.3.0
    This module is deprecated. Use the complete implementation at
    ``mahavishnu.engines.prefect_adapter`` instead, which includes:
    - Full Prefect SDK integration with get_client()
    - Deployment CRUD operations
    - Schedule management (cron, interval, rrule)
    - Flow registry integration
    - Comprehensive error mapping

    To migrate, change imports from:
        from mahavishnu.adapters.workflow.prefect_adapter import PrefectAdapter
    To:
        from mahavishnu.engines.prefect_adapter import PrefectAdapter

    Note: The new adapter uses PrefectConfig for initialization.
    If you were using keyword arguments like api_url, api_key, etc.,
    create a PrefectConfig object instead:

        # Old (deprecated):
        adapter = PrefectAdapter(api_url="http://localhost:4200", api_key="...")

        # New (recommended):
        from mahavishnu.core.config import PrefectConfig
        config = PrefectConfig(api_url="http://localhost:4200", api_key="...")
        adapter = PrefectAdapter(config)

This module re-exports from the engines implementation for backward compatibility.
"""

from __future__ import annotations

import warnings

# Emit deprecation warning at import time
warnings.warn(
    "mahavishnu.adapters.workflow.prefect_adapter is deprecated. "
    "Use mahavishnu.engines.prefect_adapter instead, which has complete "
    "Prefect SDK integration including deployments, schedules, and flow registry. "
    "See module docstring for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the engines implementation for backward compatibility
# Handle optional dependency gracefully (prefect may not be installed)
try:
    from mahavishnu.engines.prefect_adapter import (  # noqa: E402
        PrefectAdapter,
        process_repository,
        process_repositories_flow,
    )
    _prefect_available = True
except ImportError:
    PrefectAdapter = None  # type: ignore[misc,assignment]
    process_repository = None  # type: ignore[misc,assignment]
    process_repositories_flow = None  # type: ignore[misc,assignment]
    _prefect_available = False

__all__ = [
    "PrefectAdapter",
    "process_repository",
    "process_repositories_flow",
]
