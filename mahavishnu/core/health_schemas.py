"""Compatibility wrapper for health check schemas.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.core.health`` instead.

    To migrate, change imports from::

        from mahavishnu.core.health_schemas import HealthStatus, HealthResponse

    To::

        from mahavishnu.core.health import HealthStatus, HealthResponse

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "mahavishnu.core.health_schemas is a compatibility wrapper. "
    "Import from mahavishnu.core.health instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from mahavishnu.core.health import (  # noqa: F401
    DependencyStatus,
    HealthCheckResult,
    HealthResponse,
    HealthStatus,
    ReadyResponse,
    WaitResult,
)

__all__ = [
    "HealthStatus",
    "DependencyStatus",
    "HealthResponse",
    "ReadyResponse",
    "HealthCheckResult",
    "WaitResult",
]
