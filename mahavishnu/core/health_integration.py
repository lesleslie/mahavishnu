"""Health integration module for adapter monitoring.

Wires adapter health to StatisticalRouter, alerts, and Grafana (Phase 3).

Components:
- AdapterHealthMonitor: Collects health from all adapters periodically
- Updates Prometheus metrics for observability
- Persists health state to Dhruva/SQLite
- Broadcasts health changes via WebSocket
- Triggers alerts on adapter degradation

Integration Points:
- HybridAdapterRegistry: Source of adapter health data
- RoutingMetrics: Prometheus metrics for health status
- RoutingAlertManager: Alert generation on health changes
- WebSocket: Real-time health change broadcasts
- StatisticalRouter: Updates preference order based on health
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.adapters.base import OrchestratorAdapter
    from mahavishnu.core.routing_alerts import RoutingAlertManager
    from mahavishnu.core.routing_metrics import RoutingMetrics

logger = logging.getLogger(__name__)


@dataclass
class HealthIntegrationConfig:
    """Configuration for health monitoring integration.

    Attributes:
        check_interval_seconds: Interval between health checks (default: 60s)
        unhealthy_threshold: Consecutive failures before marking unhealthy (default: 3)
        recovery_threshold: Consecutive successes before marking healthy (default: 1)
        broadcast_changes: Whether to broadcast health changes via WebSocket (default: True)
        persist_to_storage: Whether to persist health to Dhruva/SQLite (default: True)
        update_router_preferences: Whether to update StatisticalRouter on health changes (default: True)
    """

    check_interval_seconds: int = 60
    unhealthy_threshold: int = 3
    recovery_threshold: int = 1
    broadcast_changes: bool = True
    persist_to_storage: bool = True
    update_router_preferences: bool = True


@dataclass
class AdapterHealthState:
    """Tracks health state for a single adapter.

    Attributes:
        adapter_name: Name of the adapter
        current_health: Latest health check result
        consecutive_failures: Count of consecutive failed health checks
        consecutive_successes: Count of consecutive successful health checks
        is_healthy: Current healthy status (based on thresholds)
        last_check_time: When the last health check occurred
        last_state_change: When the health state last changed
        failure_history: Recent failure reasons (bounded list)
    """

    adapter_name: str
    current_health: dict[str, Any] = field(default_factory=dict[str, Any])
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    is_healthy: bool = True
    last_check_time: datetime | None = None
    last_state_change: datetime | None = None
    failure_history: list[str] = field(default_factory=list[str])

    def update(self, health: dict[str, Any], config: HealthIntegrationConfig) -> bool:
        """Update health state with new health check result.

        Args:
            health: Health check result from adapter
            config: Health integration configuration

        Returns:
            True if state changed (healthy <-> unhealthy)
        """
        self.current_health = health
        self.last_check_time = datetime.now(UTC)

        status = health.get("status", "unknown")
        state_changed = False

        if status == "healthy":
            self.consecutive_failures = 0
            self.consecutive_successes += 1

            # Check for recovery
            if not self.is_healthy and self.consecutive_successes >= config.recovery_threshold:
                self.is_healthy = True
                self.last_state_change = datetime.now(UTC)
                state_changed = True
                logger.info(f"Adapter {self.adapter_name} recovered to healthy state")

        elif status in ("unhealthy", "degraded"):
            self.consecutive_successes = 0
            self.consecutive_failures += 1

            # Record failure reason
            if error := health.get("error"):
                self.failure_history.append(f"{datetime.now(UTC).isoformat()}: {error}")
                # Keep only last 10 failures
                self.failure_history = self.failure_history[-10:]

            # Check for unhealthy threshold
            if self.is_healthy and self.consecutive_failures >= config.unhealthy_threshold:
                self.is_healthy = False
                self.last_state_change = datetime.now(UTC)
                state_changed = True
                logger.warning(
                    f"Adapter {self.adapter_name} marked unhealthy after "
                    f"{self.consecutive_failures} consecutive failures"
                )
        else:
            # Unknown status - log warning but don't change state
            logger.warning(f"Adapter {self.adapter_name} returned unknown status: {status}")

        return state_changed

    def to_dict(self) -> dict[str, Any]:
        """Convert health state to dictionary."""
        return {
            "adapter_name": self.adapter_name,
            "is_healthy": self.is_healthy,
            "current_status": self.current_health.get("status", "unknown"),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
            "last_state_change": self.last_state_change.isoformat()
            if self.last_state_change
            else None,
            "failure_count": len(self.failure_history),
            "details": self.current_health,
        }


class AdapterHealthMonitor:
    """Monitors adapter health and integrates with routing infrastructure.

    Collects health from all adapters periodically and:
    - Updates Prometheus metrics for observability
    - Persists health to Dhruva/SQLite for historical analysis
    - Broadcasts health changes via WebSocket for real-time updates
    - Triggers alerts on adapter degradation
    - Updates StatisticalRouter preference order

    Attributes:
        registry: Adapter registry for health checks
        metrics: Prometheus routing metrics
        websocket_server: WebSocket server for broadcasts
        alert_manager: Alert manager for health alerts
        config: Health monitoring configuration
        health_states: Current health states for all adapters
    """

    def __init__(
        self,
        registry: dict[str, OrchestratorAdapter] | Any,
        metrics: RoutingMetrics | None = None,
        websocket_server: Any | None = None,
        alert_manager: RoutingAlertManager | None = None,
        config: HealthIntegrationConfig | None = None,
    ) -> None:
        """Initialize health monitor.

        Args:
            registry: Adapter registry (dict of adapters or object with adapters attribute)
            metrics: Optional RoutingMetrics for Prometheus tracking
            websocket_server: Optional WebSocket server for broadcasts
            alert_manager: Optional alert manager for health alerts
            config: Optional health monitoring configuration
        """
        self.registry = registry
        self.metrics = metrics
        self.websocket_server = websocket_server
        self.alert_manager = alert_manager
        self.config = config or HealthIntegrationConfig()

        # Health state tracking
        self.health_states: dict[str, AdapterHealthState] = {}

        # Background task management
        self._monitor_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

        # Initialize Prometheus health metrics if available
        self._health_gauge: Any = None
        self._health_check_counter: Any = None
        self._health_state_counter: Any = None

        if self.metrics is not None:
            self._initialize_prometheus_metrics()

        logger.info(
            f"AdapterHealthMonitor initialized: interval={self.config.check_interval_seconds}s, "
            f"unhealthy_threshold={self.config.unhealthy_threshold}, "
            f"recovery_threshold={self.config.recovery_threshold}"
        )

    def _initialize_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics for health monitoring."""
        try:
            from prometheus_client import Counter, Gauge

            # Adapter health status gauge (1=healthy, 0=unhealthy, 0.5=degraded)
            self._health_gauge = Gauge(
                "mahavishnu_adapter_health_status",
                "Adapter health status (1=healthy, 0=unhealthy, 0.5=degraded)",
                ["server", "adapter"],
            )

            # Health check counter
            self._health_check_counter = Counter(
                "mahavishnu_health_checks_total",
                "Total health checks performed",
                ["server", "adapter", "status"],
            )

            # Health state change counter
            self._health_state_counter = Counter(
                "mahavishnu_health_state_changes_total",
                "Total health state changes",
                ["server", "adapter", "from_state", "to_state"],
            )

            logger.debug("Initialized Prometheus health metrics")
        except ImportError:
            logger.warning("prometheus_client not available, health metrics disabled")
        except ValueError as e:
            # Metrics may already be registered
            logger.debug(f"Prometheus health metrics already registered: {e}")

    def _get_adapters(self) -> dict[str, OrchestratorAdapter]:
        """Get adapters from registry.

        Returns:
            Dictionary mapping adapter names to adapter instances
        """
        if hasattr(self.registry, "adapters"):
            # HybridAdapterRegistry or similar
            return self.registry.adapters  # type: ignore[no-any-return]
        elif isinstance(self.registry, dict):
            # Direct dictionary of adapters
            return self.registry
        else:
            logger.warning(f"Unknown registry type: {type(self.registry)}")
            return {}

    async def check_all_health(self) -> dict[str, dict[str, Any]]:
        """Check health of all registered adapters.

        Returns:
            Dictionary mapping adapter names to health results
        """
        adapters = self._get_adapters()
        results: dict[str, dict[str, Any]] = {}

        for adapter_name in adapters:
            try:
                health = await self.check_adapter_health(adapter_name)
                results[adapter_name] = health
            except Exception as e:
                logger.error(f"Failed to check health for {adapter_name}: {e}")
                results[adapter_name] = {
                    "status": "error",
                    "error": str(e),
                    "adapter": adapter_name,
                }

        return results

    async def check_adapter_health(self, adapter_name: str) -> dict[str, Any]:
        """Check health of a single adapter.

        Args:
            adapter_name: Name of the adapter to check

        Returns:
            Health check result dictionary
        """
        adapters = self._get_adapters()
        adapter = adapters.get(adapter_name)

        if not adapter:
            return {
                "status": "not_configured",
                "error": f"Adapter {adapter_name} not found in registry",
                "adapter": adapter_name,
            }

        try:
            # Call adapter's get_health method
            if hasattr(adapter, "get_health"):
                health = await adapter.get_health()
            else:
                # Fallback: assume healthy if no health check method
                health = {
                    "status": "healthy",
                    "message": "No health check method available",
                }

            # Ensure adapter name is in result
            health["adapter"] = adapter_name
            health["timestamp"] = datetime.now(UTC).isoformat()

            # Get or create health state
            if adapter_name not in self.health_states:
                self.health_states[adapter_name] = AdapterHealthState(adapter_name=adapter_name)

            state = self.health_states[adapter_name]
            old_is_healthy = state.is_healthy

            # Update state and check for changes
            state_changed = state.update(health, self.config)

            # Update Prometheus metrics
            self._update_prometheus_metrics(adapter_name, health, state)

            # Handle state changes
            if state_changed:
                await self._handle_health_state_change(adapter_name, old_is_healthy, state)

            # Record health check in counter
            if self._health_check_counter:
                status = health.get("status", "unknown")
                self._health_check_counter.labels(
                    server="mahavishnu",
                    adapter=adapter_name,
                    status=status,
                ).inc()

            return health

        except Exception as e:
            logger.error(f"Health check failed for {adapter_name}: {e}")

            error_health: dict[str, Any] = {
                "status": "error",
                "error": str(e),
                "adapter": adapter_name,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            # Update state with error
            if adapter_name not in self.health_states:
                self.health_states[adapter_name] = AdapterHealthState(adapter_name=adapter_name)

            state = self.health_states[adapter_name]
            old_is_healthy = state.is_healthy
            state_changed = state.update(error_health, self.config)

            # Update Prometheus metrics
            self._update_prometheus_metrics(adapter_name, error_health, state)

            if state_changed:
                await self._handle_health_state_change(adapter_name, old_is_healthy, state)

            return error_health

    async def _handle_health_state_change(
        self,
        adapter_name: str,
        old_is_healthy: bool,
        new_state: AdapterHealthState,
    ) -> None:
        """Handle health state changes.

        Args:
            adapter_name: Name of the adapter with state change
            old_is_healthy: Previous healthy state
            new_state: New health state
        """
        from_state = "healthy" if old_is_healthy else "unhealthy"
        to_state = "healthy" if new_state.is_healthy else "unhealthy"

        logger.info(f"Adapter {adapter_name} health state changed: {from_state} -> {to_state}")

        # Record state change in Prometheus
        if self._health_state_counter:
            self._health_state_counter.labels(
                server="mahavishnu",
                adapter=adapter_name,
                from_state=from_state,
                to_state=to_state,
            ).inc()

        # Broadcast via WebSocket
        if self.config.broadcast_changes and self.websocket_server:
            await self._broadcast_health_change(adapter_name, new_state)

        # Trigger alert
        if self.alert_manager and not new_state.is_healthy:
            await self._trigger_health_alert(adapter_name, new_state)

        # Update StatisticalRouter preferences
        if self.config.update_router_preferences:
            await self._update_router_preferences(adapter_name, new_state)

        # Persist to storage
        if self.config.persist_to_storage:
            await self._persist_health_state(adapter_name, new_state)

    def _update_prometheus_metrics(
        self,
        adapter_name: str,
        health: dict[str, Any],
        state: AdapterHealthState,  # noqa: ARG002
    ) -> None:
        """Update Prometheus metrics for adapter health.

        Args:
            adapter_name: Name of the adapter
            health: Health check result
            state: Current health state (unused, for future extensions)
        """
        if not self._health_gauge:
            return

        status = health.get("status", "unknown")

        # Map status to numeric value
        if status == "healthy":
            value = 1.0
        elif status == "degraded":
            value = 0.5
        else:
            value = 0.0

        try:
            self._health_gauge.labels(
                server="mahavishnu",
                adapter=adapter_name,
            ).set(value)
        except Exception as e:
            logger.debug(f"Failed to update health gauge for {adapter_name}: {e}")

    async def _broadcast_health_change(
        self,
        adapter_name: str,
        state: AdapterHealthState,
    ) -> None:
        """Broadcast health change via WebSocket.

        Args:
            adapter_name: Name of the adapter with state change
            state: New health state
        """
        if not self.websocket_server:
            return

        try:
            # Check if websocket server has broadcast method
            if hasattr(self.websocket_server, "broadcast_to_room"):
                from mcp_common.websocket import WebSocketProtocol

                event = WebSocketProtocol.create_event(
                    "adapter.health_changed",
                    {
                        "adapter": adapter_name,
                        "is_healthy": state.is_healthy,
                        "status": state.current_health.get("status", "unknown"),
                        "consecutive_failures": state.consecutive_failures,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "details": state.current_health,
                    },
                    room="global",
                )
                await self.websocket_server.broadcast_to_room("global", event)
                logger.debug(f"Broadcast health change for {adapter_name}")
        except Exception as e:
            logger.warning(f"Failed to broadcast health change: {e}")

    async def _trigger_health_alert(
        self,
        adapter_name: str,
        state: AdapterHealthState,
    ) -> None:
        """Trigger alert for adapter health degradation.

        Args:
            adapter_name: Name of the degraded adapter
            state: Current health state
        """
        if not self.alert_manager:
            return

        try:
            from mahavishnu.core.routing_alerts import Alert, AlertSeverity, AlertType

            # Create alert for unhealthy adapter
            alert = Alert(
                alert_type=AlertType.ADAPTER_DEGRADATION,
                severity=AlertSeverity.CRITICAL
                if state.consecutive_failures >= 5
                else AlertSeverity.WARNING,
                message=(
                    f"Adapter {adapter_name} is unhealthy: "
                    f"{state.consecutive_failures} consecutive failures. "
                    f"Last error: {state.current_health.get('error', 'unknown')}"
                ),
                current_value=float(state.consecutive_failures),
                threshold_value=float(self.config.unhealthy_threshold),
                metadata={
                    "adapter": adapter_name,
                    "consecutive_failures": state.consecutive_failures,
                    "failure_history": state.failure_history[-5:],  # Last 5 failures
                },
            )

            # Send alert through all handlers
            for handler in self.alert_manager.handlers:
                try:
                    await handler.send_alert(alert)
                except Exception as e:
                    logger.error(f"Alert handler {handler.__class__.__name__} failed: {e}")

            logger.info(f"Triggered health alert for {adapter_name}")
        except Exception as e:
            logger.error(f"Failed to trigger health alert: {e}")

    async def _update_router_preferences(
        self,
        adapter_name: str,
        state: AdapterHealthState,
    ) -> None:
        """Update StatisticalRouter preferences based on health.

        Args:
            adapter_name: Name of the adapter
            state: Current health state
        """
        try:
            from mahavishnu.core.statistical_router import get_statistical_router

            router = get_statistical_router()

            if not state.is_healthy:
                # Clear cached preferences to force recalculation
                # This will deprioritize unhealthy adapters
                router._preferences.clear()  # noqa: SLF001
                logger.info(f"Cleared StatisticalRouter cache due to {adapter_name} health change")
        except Exception as e:
            logger.debug(f"Failed to update router preferences: {e}")

    async def _persist_health_state(
        self,
        adapter_name: str,
        state: AdapterHealthState,
    ) -> None:
        """Persist health state to storage (Dhruva/SQLite).

        Args:
            adapter_name: Name of the adapter
            state: Current health state
        """
        try:
            # Try to use Dhruva client if available
            from mahavishnu.core.oneiric_client import get_dhruva_client

            client = get_dhruva_client()
            if client:
                key = f"health:adapter:{adapter_name}"
                await client.put(key, state.to_dict(), ttl=86400 * 7)  # 7 days TTL
                logger.debug(f"Persisted health state for {adapter_name} to Dhruva")
        except ImportError:
            # Fallback to local SQLite if available
            try:
                # Use local health.db for persistence
                conn = sqlite3.connect("health.db")
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS adapter_health (
                        adapter_name TEXT PRIMARY KEY,
                        health_data TEXT,
                        updated_at TEXT
                    )
                """)

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO adapter_health (adapter_name, health_data, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (adapter_name, json.dumps(state.to_dict()), datetime.now(UTC).isoformat()),
                )

                conn.commit()
                conn.close()
                logger.debug(f"Persisted health state for {adapter_name} to SQLite")
            except Exception as e:
                logger.debug(f"Failed to persist health state to SQLite: {e}")
        except Exception as e:
            logger.debug(f"Failed to persist health state: {e}")

    async def start_periodic_checks(self, interval: int | None = None) -> None:
        """Start background health monitoring.

        Args:
            interval: Optional override for check interval (seconds)
        """
        if self._monitor_task is not None:
            logger.warning("Health monitor already running")
            return

        check_interval = interval or self.config.check_interval_seconds
        self._shutdown_event.clear()

        async def _monitor_loop() -> None:
            """Background health check loop."""
            logger.info(f"Starting health monitoring (interval: {check_interval}s)")

            while not self._shutdown_event.is_set():
                try:
                    await self.check_all_health()
                    await asyncio.sleep(check_interval)
                except asyncio.CancelledError:
                    logger.info("Health monitor loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Health monitor error: {e}", exc_info=True)
                    await asyncio.sleep(check_interval)

        self._monitor_task = asyncio.create_task(_monitor_loop())
        logger.info("Health monitor started")

    async def stop_periodic_checks(self) -> None:
        """Stop background health monitoring."""
        logger.info("Stopping health monitor...")

        self._shutdown_event.set()

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task

        self._monitor_task = None
        logger.info("Health monitor stopped")

    def get_health_summary(self) -> dict[str, Any]:
        """Get summary of all adapter health states.

        Returns:
            Dictionary with health summary for all adapters
        """
        adapters = self._get_adapters()
        total = len(adapters)
        healthy = sum(1 for s in self.health_states.values() if s.is_healthy)
        unhealthy = total - healthy

        return {
            "total_adapters": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "health_percentage": (healthy / total * 100) if total > 0 else 100.0,
            "adapters": {name: state.to_dict() for name, state in self.health_states.items()},
            "monitor_running": self._monitor_task is not None and not self._monitor_task.done(),
            "config": {
                "check_interval_seconds": self.config.check_interval_seconds,
                "unhealthy_threshold": self.config.unhealthy_threshold,
                "recovery_threshold": self.config.recovery_threshold,
            },
        }

    def get_adapter_health(self, adapter_name: str) -> dict[str, Any] | None:
        """Get health state for a specific adapter.

        Args:
            adapter_name: Name of the adapter

        Returns:
            Health state dictionary or None if not found
        """
        state = self.health_states.get(adapter_name)
        return state.to_dict() if state else None


# Singleton instance
_health_monitor: AdapterHealthMonitor | None = None


def get_health_monitor() -> AdapterHealthMonitor:
    """Get or create global health monitor singleton.

    Returns:
        Global AdapterHealthMonitor instance

    Raises:
        RuntimeError: If health monitor not initialized
    """
    global _health_monitor
    if _health_monitor is None:
        raise RuntimeError(
            "Health monitor not initialized. Call initialize_health_monitor() first."
        )
    return _health_monitor


async def initialize_health_monitor(
    registry: dict[str, OrchestratorAdapter] | Any,
    metrics: RoutingMetrics | None = None,
    websocket_server: Any | None = None,
    alert_manager: RoutingAlertManager | None = None,
    config: HealthIntegrationConfig | None = None,
    auto_start: bool = True,
) -> AdapterHealthMonitor:
    """Initialize and optionally start global health monitor.

    Args:
        registry: Adapter registry (dict of adapters or object with adapters attribute)
        metrics: Optional Prometheus routing metrics
        websocket_server: Optional WebSocket server for broadcasts
        alert_manager: Optional alert manager
        config: Optional health monitoring configuration
        auto_start: Whether to automatically start monitoring (default: True)

    Returns:
        Initialized AdapterHealthMonitor instance
    """
    global _health_monitor

    _health_monitor = AdapterHealthMonitor(
        registry=registry,
        metrics=metrics,
        websocket_server=websocket_server,
        alert_manager=alert_manager,
        config=config,
    )

    if auto_start:
        await _health_monitor.start_periodic_checks()

    return _health_monitor


__all__ = [
    "AdapterHealthMonitor",
    "AdapterHealthState",
    "HealthIntegrationConfig",
    "get_health_monitor",
    "initialize_health_monitor",
]
