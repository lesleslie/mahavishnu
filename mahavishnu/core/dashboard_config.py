"""Compatibility wrapper for dashboard configuration models.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.core.monitoring`` instead.

    To migrate, change imports from::

        from mahavishnu.core.dashboard_config import DashboardConfig, DashboardPanel

    To::

        from mahavishnu.core.monitoring import DashboardConfig, DashboardPanel

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "mahavishnu.core.dashboard_config is a compatibility wrapper. "
    "Import from mahavishnu.core.monitoring instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from mahavishnu.core.monitoring import DashboardConfig, DashboardPanel  # noqa: F401

__all__ = ["DashboardConfig", "DashboardPanel"]
