"""Session-Buddy MCP polling integration for Mahavishnu.

This module provides an async polling service that collects session telemetry
from Session-Buddy via MCP protocol and converts it to OpenTelemetry metrics.

Example:
    >>> from mahavishnu.core import MahavishnuApp
    >>> app = MahavishnuApp()
    >>> poller = app.session_buddy_poller
    >>> # Poller runs automatically in background
    >>> status = await poller.get_status()
    >>> await poller.stop()
"""

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from ..core.config import MahavishnuSettings


@dataclass
class PollerStatus:
    """Status of the Session-Buddy poller."""

    running: bool
    poll_cycles: int
    errors: int
    last_poll_time: datetime | None
    last_error: str | None
    circuit_breaker_open: bool


class SessionBuddyPoller:
    """Async MCP poller for Session-Buddy session telemetry.

    This poller periodically calls Session-Buddy MCP tools to collect
    session metrics, workflow statistics, and performance data, then
    converts them to OpenTelemetry metrics and pushes them to Mahavishnu's
    OTel collector.

    Features:
    - Async HTTP-based MCP client
    - Configurable polling interval
    - Graceful degradation on errors
    - Circuit breaker pattern for fault tolerance
    - OTel metric conversion and recording
    - Type-safe configuration

    Attributes:
        config: Mahavishnu configuration
        endpoint: Session-Buddy MCP server URL
        interval: Polling interval in seconds
        logger: Logger instance
    """

    # MCP tools to poll on Session-Buddy
    MCP_TOOLS = [
        "get_activity_summary",
        "get_workflow_metrics",
        "get_session_analytics",
        "get_performance_metrics",
    ]

    def __init__(
        self,
        config: MahavishnuSettings,
        observability_manager: Any | None = None,
    ):
        """Initialize the Session-Buddy poller.

        Args:
            config: Mahavishnu configuration object
            observability_manager: Optional observability manager for OTel metrics
        """
        self.config = config
        self.observability = observability_manager
        self.logger = logging.getLogger(__name__)

        # Polling configuration
        self.enabled = getattr(config, "session_buddy_polling_enabled", False)
        self.endpoint = getattr(
            config, "session_buddy_polling_endpoint", "http://localhost:8678/mcp"
        )
        self.interval = getattr(config, "session_buddy_polling_interval_seconds", 30)
        self.timeout = getattr(config, "session_buddy_polling_timeout_seconds", 10)
        self.max_retries = getattr(config, "session_buddy_polling_max_retries", 3)
        self.retry_delay = getattr(config, "session_buddy_polling_retry_delay_seconds", 5)
        self.circuit_breaker_threshold = getattr(
            config, "session_buddy_polling_circuit_breaker_threshold", 5
        )
        self.metrics_to_collect = getattr(
            config, "session_buddy_polling_metrics_to_collect", self.MCP_TOOLS
        )

        # Polling state
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._poll_cycles = 0
        self._errors = 0
        self._consecutive_failures = 0
        self._last_poll_time: datetime | None = None
        self._last_error: str | None = None

        # Circuit breaker state
        self._circuit_breaker_open = False
        self._circuit_breaker_opened_at: datetime | None = None

        self.logger.info(
            f"SessionBuddyPoller initialized: "
            f"enabled={self.enabled}, endpoint={self.endpoint}, interval={self.interval}s"
        )

    async def start(self) -> None:
        """Start the polling loop.

        Creates an async task that polls Session-Buddy metrics
        at the configured interval. Only starts if polling is enabled
        in configuration.

        Raises:
            RuntimeError: If poller is already running
        """
        if not self.enabled:
            self.logger.info("Session-Buddy polling is disabled in configuration")
            return

        if self._running:
            self.logger.warning("Poller is already running")
            return

        self._running = True
        self._http_client = httpx.AsyncClient(timeout=self.timeout)

        # Start polling loop
        self._poll_task = asyncio.create_task(self._polling_loop())
        self.logger.info(f"SessionBuddyPoller started (interval={self.interval}s)")

    async def stop(self) -> None:
        """Stop the polling loop.

        Cancels the polling task and closes the HTTP client.
        Waits for the current poll cycle to complete if one is in progress.
        """
        if not self._running:
            return

        self.logger.info("Stopping SessionBuddyPoller...")
        self._running = False

        # Cancel polling task
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

        # Close HTTP client
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        self.logger.info("SessionBuddyPoller stopped")

    async def get_status(self) -> PollerStatus:
        """Get the current status of the poller.

        Returns:
            PollerStatus with current state
        """
        return PollerStatus(
            running=self._running,
            poll_cycles=self._poll_cycles,
            errors=self._errors,
            last_poll_time=self._last_poll_time,
            last_error=self._last_error,
            circuit_breaker_open=self._circuit_breaker_open,
        )

    async def _polling_loop(self) -> None:
        """Main polling loop.

        Polls Session-Buddy metrics at the configured interval.
        Handles errors gracefully and implements circuit breaker pattern.
        """
        try:
            while self._running:
                try:
                    # Check circuit breaker
                    if self._circuit_breaker_open:
                        await self._check_circuit_breaker()

                    # Poll metrics
                    if not self._circuit_breaker_open:
                        await self.poll_once()

                    # Wait for next interval
                    await asyncio.sleep(self.interval)

                except asyncio.CancelledError:
                    self.logger.info("Polling loop cancelled")
                    break
                except Exception as e:
                    self.logger.error(f"Error in polling loop: {e}", exc_info=True)
                    self._record_error(f"Polling loop error: {e}")
                    # Continue running despite errors
                    await asyncio.sleep(self.interval)

        finally:
            self.logger.info("Polling loop terminated")

    async def poll_once(self) -> dict[str, Any]:
        """Execute a single polling cycle.

        Calls all configured MCP tools on Session-Buddy and records
        the returned metrics to OpenTelemetry.

        Returns:
            Dictionary with poll results including metrics collected
            and any errors encountered
        """
        if not self._http_client:
            raise RuntimeError("Poller is not started (HTTP client not initialized)")

        self._poll_cycles += 1
        self._last_poll_time = datetime.now(UTC)

        self.logger.debug(f"Starting poll cycle #{self._poll_cycles}")

        results = {
            "poll_cycle": self._poll_cycles,
            "timestamp": self._last_poll_time.isoformat(),
            "metrics_collected": [],
            "errors": [],
        }

        # Poll each configured metric
        for tool_name in self.metrics_to_collect:
            if tool_name not in self.MCP_TOOLS:
                self.logger.warning(f"Unknown MCP tool: {tool_name}")
                continue

            try:
                # Call MCP tool
                metric_data = await self._call_mcp_tool(tool_name)

                # Convert to OTel format
                otel_metrics = self._convert_to_otel(tool_name, metric_data)

                # Record metrics
                await self._record_metrics(tool_name, otel_metrics)

                results["metrics_collected"].append(tool_name)

                # Reset consecutive failures on success
                self._consecutive_failures = 0

            except Exception as e:
                error_msg = f"Failed to poll {tool_name}: {e}"
                self.logger.warning(error_msg)
                results["errors"].append(error_msg)
                self._record_error(error_msg)

        # Check circuit breaker threshold
        if self._consecutive_failures >= self.circuit_breaker_threshold:
            await self._open_circuit_breaker()

        self.logger.debug(
            f"Poll cycle #{self._poll_cycles} completed: "
            f"{len(results['metrics_collected'])} metrics, "
            f"{len(results['errors'])} errors"
        )

        return results

    async def _call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a Session-Buddy MCP tool via HTTP.

        Args:
            tool_name: Name of the MCP tool to call
            arguments: Optional tool arguments

        Returns:
            Tool result dictionary

        Raises:
            httpx.HTTPError: If HTTP request fails
            ValueError: If response is invalid
        """
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        url = f"{self.endpoint}/tools/call"
        payload = {"name": tool_name, "arguments": arguments or {}}

        self.logger.debug(f"Calling MCP tool: {tool_name}")

        # Retry logic
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self._http_client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()

                # Validate response structure
                if not isinstance(result, dict):
                    raise ValueError(f"Invalid response type: {type(result)}")

                return result

            except httpx.HTTPError as e:
                last_error = e
                self.logger.warning(
                    f"HTTP error calling {tool_name} (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))  # Exponential backoff
                else:
                    raise

            except ValueError as e:
                last_error = e
                self.logger.error(f"Invalid response from {tool_name}: {e}")
                raise

        raise last_error or RuntimeError("Failed to call MCP tool")

    def _convert_to_otel(self, tool_name: str, metric_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert Session-Buddy metric data to OTel format.

        Args:
            tool_name: Name of the MCP tool that provided the data
            metric_data: Raw metric data from Session-Buddy

        Returns:
            List of OTel metric dictionaries with name, type, value, and attributes
        """
        otel_metrics = []

        # Extract result from MCP response
        data = metric_data.get("result", metric_data)
        if not isinstance(data, dict):
            self.logger.warning(f"Invalid metric data for {tool_name}: {type(data)}")
            return []

        # Convert based on tool type
        if tool_name == "get_activity_summary":
            otel_metrics.extend(self._convert_activity_summary(data))
        elif tool_name == "get_workflow_metrics":
            otel_metrics.extend(self._convert_workflow_metrics(data))
        elif tool_name == "get_session_analytics":
            otel_metrics.extend(self._convert_session_analytics(data))
        elif tool_name == "get_performance_metrics":
            otel_metrics.extend(self._convert_performance_metrics(data))
        else:
            self.logger.warning(f"Unknown tool type for OTel conversion: {tool_name}")

        return otel_metrics

    def _convert_activity_summary(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert activity summary to OTel metrics."""
        metrics = []

        # Active sessions gauge
        if "active_sessions" in data:
            metrics.append(
                {
                    "name": "session_buddy.sessions.active",
                    "type": "gauge",
                    "value": data["active_sessions"],
                    "attributes": {"source": "session_buddy"},
                }
            )

        # Total sessions counter
        if "total_sessions" in data:
            metrics.append(
                {
                    "name": "session_buddy.sessions.total",
                    "type": "counter",
                    "value": data["total_sessions"],
                    "attributes": {"source": "session_buddy"},
                }
            )

        return metrics

    def _convert_workflow_metrics(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert workflow metrics to OTel metrics."""
        metrics = []

        # Workflows completed counter
        if "workflows_completed" in data:
            metrics.append(
                {
                    "name": "session_buddy.workflows.completed",
                    "type": "counter",
                    "value": data["workflows_completed"],
                    "attributes": {"source": "session_buddy"},
                }
            )

        # Workflows failed counter
        if "workflows_failed" in data:
            metrics.append(
                {
                    "name": "session_buddy.workflows.failed",
                    "type": "counter",
                    "value": data["workflows_failed"],
                    "attributes": {"source": "session_buddy"},
                }
            )

        # Average duration histogram
        if "avg_duration" in data:
            metrics.append(
                {
                    "name": "session_buddy.workflow.duration",
                    "type": "histogram",
                    "value": data["avg_duration"],
                    "attributes": {"source": "session_buddy", "stat": "average"},
                }
            )

        return metrics

    def _convert_session_analytics(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert session analytics to OTel metrics."""
        metrics = []

        # Total checkpoints counter
        if "total_checkpoints" in data:
            metrics.append(
                {
                    "name": "session_buddy.checkpoints.total",
                    "type": "counter",
                    "value": data["total_checkpoints"],
                    "attributes": {"source": "session_buddy"},
                }
            )

        # Average checkpoint size histogram
        if "avg_checkpoint_size" in data:
            metrics.append(
                {
                    "name": "session_buddy.checkpoint.size",
                    "type": "histogram",
                    "value": data["avg_checkpoint_size"],
                    "attributes": {"source": "session_buddy", "stat": "average"},
                }
            )

        # Session duration histogram
        if "avg_session_duration" in data:
            metrics.append(
                {
                    "name": "session_buddy.session.duration",
                    "type": "histogram",
                    "value": data["avg_session_duration"],
                    "attributes": {"source": "session_buddy", "stat": "average"},
                }
            )

        return metrics

    def _convert_performance_metrics(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert performance metrics to OTel metrics."""
        metrics = []

        # CPU usage gauge
        if "cpu_usage" in data:
            metrics.append(
                {
                    "name": "session_buddy.performance.cpu_usage",
                    "type": "gauge",
                    "value": data["cpu_usage"],
                    "attributes": {"source": "session_buddy", "unit": "percent"},
                }
            )

        # Memory usage gauge
        if "memory_usage" in data:
            metrics.append(
                {
                    "name": "session_buddy.performance.memory_usage",
                    "type": "gauge",
                    "value": data["memory_usage"],
                    "attributes": {"source": "session_buddy", "unit": "mb"},
                }
            )

        # Response time histogram
        if "response_time" in data:
            metrics.append(
                {
                    "name": "session_buddy.performance.response_time",
                    "type": "histogram",
                    "value": data["response_time"],
                    "attributes": {"source": "session_buddy", "unit": "ms"},
                }
            )

        return metrics

    async def _record_metrics(self, tool_name: str, otel_metrics: list[dict[str, Any]]) -> None:
        """Record metrics to OpenTelemetry.

        Args:
            tool_name: Name of the tool that provided the metrics
            otel_metrics: List of OTel metric dictionaries
        """
        if not self.observability:
            self.logger.debug("No observability manager, skipping metric recording")
            return

        for metric in otel_metrics:
            try:
                metric_name = metric["name"]
                metric_type = metric["type"]
                value = metric["value"]
                attributes = metric.get("attributes", {})

                # Record based on metric type
                if metric_type == "counter":
                    # Create or get counter instrument
                    counter = self.observability.meter.create_counter(
                        metric_name, description=f"Session-Buddy metric: {metric_name}"
                    )
                    counter.add(value, attributes)

                elif metric_type == "gauge":
                    # Create or get gauge instrument (using up-down counter)
                    gauge = self.observability.meter.create_up_down_counter(
                        metric_name, description=f"Session-Buddy metric: {metric_name}"
                    )
                    gauge.add(value, attributes)

                elif metric_type == "histogram":
                    # Create or get histogram instrument
                    histogram = self.observability.meter.create_histogram(
                        metric_name, description=f"Session-Buddy metric: {metric_name}"
                    )
                    histogram.record(value, attributes)

                self.logger.debug(f"Recorded OTel metric: {metric_name} = {value}")

            except Exception as e:
                self.logger.warning(f"Failed to record metric {metric.get('name')}: {e}")

    def _record_error(self, error_message: str) -> None:
        """Record an error and update error counters.

        Args:
            error_message: Error message to record
        """
        self._errors += 1
        self._consecutive_failures += 1
        self._last_error = error_message

        # Record error metric
        if self.observability:
            try:
                error_counter = self.observability.meter.create_counter(
                    "session_buddy_poller.poll_errors",
                    description="Total polling errors",
                )
                error_counter.add(1, {"source": "session_buddy_poller"})
            except Exception:
                pass  # Don't fail if metric recording fails

    async def _open_circuit_breaker(self) -> None:
        """Open the circuit breaker to stop polling.

        Opens the circuit breaker when consecutive failures exceed threshold.
        """
        self._circuit_breaker_open = True
        self._circuit_breaker_opened_at = datetime.now(UTC)

        self.logger.error(
            f"Circuit breaker opened after {self._consecutive_failures} consecutive failures"
        )

    async def _check_circuit_breaker(self) -> None:
        """Check if circuit breaker should be closed.

        Attempts to close the circuit breaker after a cooldown period.
        """
        if not self._circuit_breaker_open:
            return

        # Wait for cooldown period (5 * interval)
        if self._circuit_breaker_opened_at:
            cooldown_end = self._circuit_breaker_opened_at.timestamp() + (self.interval * 5)
            if datetime.now(UTC).timestamp() < cooldown_end:
                return  # Still in cooldown

        # Attempt to close circuit breaker
        self.logger.info("Attempting to close circuit breaker...")
        self._circuit_breaker_open = False
        self._consecutive_failures = 0
        self._circuit_breaker_opened_at = None
