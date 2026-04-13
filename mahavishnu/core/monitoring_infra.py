"""Compatibility wrapper for monitoring infrastructure.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.core.monitoring`` instead.

    To migrate, change imports from::

        from mahavishnu.core.monitoring_infra import MetricsExporter, AlertManager

    To::

        from mahavishnu.core.monitoring import MetricsExporter, AlertManager

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "mahavishnu.core.monitoring_infra is a compatibility wrapper. "
    "Import from mahavishnu.core.monitoring instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from mahavishnu.core.monitoring import (  # noqa: F401
    Alert,
    AlertManager as _CanonicalAlertManager,
    AlertRule,
    AlertSeverity,
    ComponentHealthChecker as HealthChecker,
    ComponentHealthResult as HealthCheckResult,
    DashboardConfig,
    DashboardPanel,
    Metric,
    MetricType,
    MetricsExporter,
)
from mahavishnu.core.status import HealthStatus  # noqa: F401


class AlertManager(_CanonicalAlertManager):
    """Compatibility wrapper providing synchronous get_active_alerts.

    .. deprecated:: 0.4.0
        Use ``mahavishnu.core.monitoring.AlertManager`` and call
        ``get_active_alerts_sync()`` for synchronous access.
    """

    def __init__(self) -> None:
        super().__init__(app=None)

    def get_active_alerts(self) -> list[Alert]:
        """Synchronous version for backward compatibility."""
        return self.get_active_alerts_sync()


__all__ = [
    "MetricsExporter",
    "AlertManager",
    "AlertRule",
    "Alert",
    "AlertSeverity",
    "HealthChecker",
    "HealthStatus",
    "HealthCheckResult",
    "Metric",
    "MetricType",
    "DashboardConfig",
    "DashboardPanel",
]
