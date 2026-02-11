#!/usr/bin/env python3
"""WebSocket health check script for Mahavishnu ecosystem.

This script provides comprehensive health checking for all WebSocket servers
in the Mahavishnu ecosystem. It can be used by operators to verify server status,
measure latency, and output results in multiple formats.

Supported Servers:
    - session-buddy (8765) - Session management and context tracking
    - mahavishnu (8690) - Workflow orchestration and pool management
    - akosha (8692) - Knowledge graph and insights
    - crackerjack (8686) - Quality control and CI/CD
    - dhruva (8693) - Dependency management
    - excalidraw-mcp (3042) - Diagram collaboration
    - fastblocks (8684) - Application building and UI rendering

Usage:
    python scripts/check_websocket_health.py
    python scripts/check_websocket_health.py --servers mahavishnu,akosha
    python scripts/check_websocket_health.py --timeout 10
    python scripts/check_websocket_health.py --json
    python scripts/check_websocket_health.py --prometheus
    python scripts/check_websocket_health.py --verbose

Exit Codes:
    0: All servers healthy
    1: Some servers unhealthy (degraded)
    2: Critical failure (all servers down or configuration error)
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from typer import Option, Typer, Exit

# Type aliases for cleaner code
ServerConfig = dict[str, Any]
ServerName = str

app = Typer(
    name="websocket-health",
    add_completion=False,
    no_args_is_help=False,
    help="Health check script for WebSocket servers",
)


# =============================================================================
# Configuration
# =============================================================================

# Default server configurations
DEFAULT_SERVERS: dict[ServerName, ServerConfig] = {
    "session-buddy": {
        "host": "127.0.0.1",
        "port": 8765,
        "description": "Session management and context tracking",
    },
    "mahavishnu": {
        "host": "127.0.0.1",
        "port": 8690,
        "description": "Workflow orchestration and pool management",
    },
    "akosha": {
        "host": "127.0.0.1",
        "port": 8692,
        "description": "Knowledge graph and insights",
    },
    "crackerjack": {
        "host": "127.0.0.1",
        "port": 8686,
        "description": "Quality control and CI/CD",
    },
    "dhruva": {
        "host": "127.0.0.1",
        "port": 8693,
        "description": "Dependency management",
    },
    "excalidraw-mcp": {
        "host": "127.0.0.1",
        "port": 3042,
        "description": "Diagram collaboration",
    },
    "fastblocks": {
        "host": "127.0.0.1",
        "port": 8684,
        "description": "Application building and UI rendering",
    },
}

# Service dependencies for health impact analysis
SERVICE_DEPENDENCIES: dict[ServerName, list[ServerName]] = {
    "session-buddy": [],  # No dependencies
    "mahavishnu": ["session-buddy"],  # Depends on session management
    "akosha": ["mahavishnu"],  # Depends on orchestration for memory aggregation
    "crackerjack": [],  # Independent quality checks
    "dhruva": [],  # Independent dependency management
    "excalidraw-mcp": [],  # Independent diagram service
    "fastblocks": [],  # Independent app building
}


# =============================================================================
# Data Structures
# =============================================================================

class HealthStatus(str, Enum):
    """Health status enumeration.

    Attributes:
        HEALTHY: Server is responding normally
        DEGRADED: Server is up but performance is poor
        UNHEALTHY: Server is not responding
        UNKNOWN: Unable to determine status
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check for a single server.

    Attributes:
        name: Server name
        host: Server hostname/IP
        port: Server port
        status: Health status
        latency_ms: Connection latency in milliseconds (None if failed)
        error: Error message if status is not healthy
        check_time: ISO 8601 timestamp of the check
    """

    name: ServerName
    host: str
    port: int
    status: HealthStatus
    latency_ms: float | None = None
    error: str | None = None
    check_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary.

        Returns:
            Dictionary representation of the health check result
        """
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "check_time": self.check_time,
        }


@dataclass
class HealthCheckSummary:
    """Summary of health check results across all servers.

    Attributes:
        results: List of individual server health check results
        total_servers: Total number of servers checked
        healthy_count: Number of healthy servers
        degraded_count: Number of degraded servers
        unhealthy_count: Number of unhealthy servers
        timestamp: ISO 8601 timestamp of the check
    """

    results: list[HealthCheckResult]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def total_servers(self) -> int:
        """Get total number of servers checked."""
        return len(self.results)

    @property
    def healthy_count(self) -> int:
        """Get count of healthy servers."""
        return sum(1 for r in self.results if r.status == HealthStatus.HEALTHY)

    @property
    def degraded_count(self) -> int:
        """Get count of degraded servers."""
        return sum(1 for r in self.results if r.status == HealthStatus.DEGRADED)

    @property
    def unhealthy_count(self) -> int:
        """Get count of unhealthy servers."""
        return sum(1 for r in self.results if r.status == HealthStatus.UNHEALTHY)

    @property
    def exit_code(self) -> int:
        """Get appropriate exit code based on results.

        Returns:
            0 if all healthy, 1 if some degraded/unhealthy, 2 if critical
        """
        if self.healthy_count == self.total_servers:
            return 0
        if self.healthy_count > 0:
            return 1
        return 2

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to dictionary.

        Returns:
            Dictionary representation of the health check summary
        """
        return {
            "timestamp": self.timestamp,
            "servers": [r.to_dict() for r in self.results],
            "summary": {
                "total": self.total_servers,
                "healthy": self.healthy_count,
                "degraded": self.degraded_count,
                "unhealthy": self.unhealthy_count,
            },
        }


# =============================================================================
# Health Check Logic
# =============================================================================

async def check_websocket_server(
    name: ServerName,
    host: str,
    port: int,
    timeout: float = 5.0,
    advanced: bool = False,
) -> HealthCheckResult:
    """Check health of a WebSocket server.

    Performs basic TCP connection check and optionally advanced
    WebSocket protocol validation.

    Args:
        name: Server name
        host: Server hostname/IP
        port: Server port
        timeout: Connection timeout in seconds
        advanced: Whether to perform advanced WebSocket checks

    Returns:
        HealthCheckResult with status and latency information
    """
    start_time = time.time()
    error_msg: str | None = None
    status = HealthStatus.UNKNOWN
    latency_ms: float | None = None

    try:
        # Step 1: Basic TCP connection check
        sock_future = asyncio.get_event_loop().create_future()

        def connect_tcp():
            """Synchronous TCP connection for socket check."""
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                return result == 0
            except Exception as e:
                return False

        # Run TCP check in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        tcp_connected = await loop.run_in_executor(None, connect_tcp)

        if not tcp_connected:
            error_msg = "Connection refused"
            status = HealthStatus.UNHEALTHY
            return HealthCheckResult(
                name=name,
                host=host,
                port=port,
                status=status,
                latency_ms=None,
                error=error_msg,
            )

        # Measure TCP connection latency
        latency_ms = (time.time() - start_time) * 1000

        # Step 2: Advanced WebSocket check (if requested)
        if advanced:
            try:
                # Import websockets here for optional dependency
                import websockets

                ws_uri = f"ws://{host}:{port}"
                msg_count = 0

                async with websockets.connect(
                    ws_uri,
                    close_timeout=timeout,
                    ping_timeout=timeout,
                ) as websocket:
                    # Send a ping to verify WebSocket protocol
                    ping_msg = {
                        "type": "ping",
                        "id": f"health_check_{int(time.time())}",
                    }
                    await websocket.send(json.dumps(ping_msg))

                    # Wait for response (with timeout)
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=1.0,
                        )
                        msg_count += 1

                        # Parse response to verify it's valid JSON
                        try:
                            response_data = json.loads(response)
                            if response_data.get("type") in ("pong", "event", "response"):
                                status = HealthStatus.HEALTHY
                            else:
                                status = HealthStatus.DEGRADED
                                error_msg = "Unexpected response type"
                        except json.JSONDecodeError:
                            status = HealthStatus.DEGRADED
                            error_msg = "Invalid JSON response"

                    except asyncio.TimeoutError:
                        # Connected but no response to ping
                        status = HealthStatus.DEGRADED
                        error_msg = "No response to ping"

                # Recalculate latency including WebSocket handshake
                latency_ms = (time.time() - start_time) * 1000

            except ImportError:
                # websockets not available, fall back to TCP check
                status = HealthStatus.HEALTHY
            except Exception as e:
                # WebSocket protocol error but TCP connected
                status = HealthStatus.DEGRADED
                error_msg = str(e)
                latency_ms = (time.time() - start_time) * 1000
        else:
            # Basic TCP check passed
            status = HealthStatus.HEALTHY

        # Determine degraded status based on latency
        if status == HealthStatus.HEALTHY and latency_ms is not None:
            if latency_ms > 100:  # Degraded if latency > 100ms
                status = HealthStatus.DEGRADED
                error_msg = f"High latency: {latency_ms:.1f}ms"

    except socket.gaierror:
        error_msg = "DNS resolution failed"
        status = HealthStatus.UNHEALTHY
    except socket.timeout:
        error_msg = f"Connection timeout after {timeout}s"
        status = HealthStatus.UNHEALTHY
    except Exception as e:
        error_msg = str(e)
        status = HealthStatus.UNHEALTHY

    return HealthCheckResult(
        name=name,
        host=host,
        port=port,
        status=status,
        latency_ms=latency_ms,
        error=error_msg,
    )


async def check_all_servers(
    servers: dict[ServerName, ServerConfig],
    timeout: float = 5.0,
    advanced: bool = False,
) -> HealthCheckSummary:
    """Check health of all configured servers concurrently.

    Args:
        servers: Dictionary of server configurations
        timeout: Per-server timeout in seconds
        advanced: Whether to perform advanced WebSocket checks

    Returns:
        HealthCheckSummary with results for all servers
    """
    tasks = []
    for name, config in servers.items():
        task = check_websocket_server(
            name=name,
            host=config["host"],
            port=config["port"],
            timeout=timeout,
            advanced=advanced,
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    return HealthCheckSummary(results=results)


# =============================================================================
# Output Formatting
# =============================================================================

class OutputFormatter:
    """Format health check results for different output modes."""

    # ANSI color codes for terminal output
    COLOR_GREEN = "\033[32m"
    COLOR_YELLOW = "\033[33m"
    COLOR_RED = "\033[31m"
    COLOR_RESET = "\033[0m"

    @classmethod
    def format_console(
        cls,
        summary: HealthCheckSummary,
        verbose: bool = False,
    ) -> str:
        """Format results as human-readable console output.

        Args:
            summary: Health check summary
            verbose: Whether to show detailed output

        Returns:
            Formatted string for console display
        """
        lines = []

        # Header
        lines.append("=" * 60)
        lines.append("WebSocket Server Health Check")
        lines.append("=" * 60)
        lines.append("")

        # Server results
        for result in summary.results:
            # Determine symbol and color
            if result.status == HealthStatus.HEALTHY:
                symbol = "\u2713"  # Checkmark
                color = cls.COLOR_GREEN
                latency_str = f"{result.latency_ms:.0f}ms" if result.latency_ms else "N/A"
            elif result.status == HealthStatus.DEGRADED:
                symbol = "\u26A0"  # Warning sign
                color = cls.COLOR_YELLOW
                latency_str = f"{result.latency_ms:.0f}ms" if result.latency_ms else "N/A"
            else:
                symbol = "\u2717"  # X mark
                color = cls.COLOR_RED
                latency_str = "UNREACHABLE"

            # Format line with color
            line = (
                f"{color}{symbol} {result.name} ({result.host}:{result.port}) - "
                f"{latency_str}{cls.COLOR_RESET}"
            )
            lines.append(line)

            # Add error details in verbose mode
            if verbose and result.error:
                lines.append(f"    Error: {result.error}")

            # Show dependency impact in verbose mode
            if verbose and result.status != HealthStatus.HEALTHY:
                dependents = SERVICE_DEPENDENCIES.get(result.name, [])
                if dependents:
                    lines.append(f"    Affects: {', '.join(dependents)}")

        lines.append("")

        # Summary
        lines.append("-" * 60)
        if summary.healthy_count == summary.total_servers:
            lines.append(
                f"{cls.COLOR_GREEN}All {summary.total_servers} servers healthy{cls.COLOR_RESET}"
            )
        else:
            lines.append(
                f"Total: {summary.total_servers} | "
                f"{cls.COLOR_GREEN}Healthy: {summary.healthy_count}{cls.COLOR_RESET} | "
                f"{cls.COLOR_YELLOW}Degraded: {summary.degraded_count}{cls.COLOR_RESET} | "
                f"{cls.COLOR_RED}Unhealthy: {summary.unhealthy_count}{cls.COLOR_RESET}"
            )
        lines.append("=" * 60)

        return "\n".join(lines)

    @classmethod
    def format_json(cls, summary: HealthCheckSummary) -> str:
        """Format results as JSON.

        Args:
            summary: Health check summary

        Returns:
            JSON string representation
        """
        return json.dumps(summary.to_dict(), indent=2)

    @classmethod
    def format_prometheus(cls, summary: HealthCheckSummary) -> str:
        """Format results as Prometheus node_exporter text format.

        Args:
            summary: Health check summary

        Returns:
            Prometheus text format metrics
        """
        lines = []

        # HELP and TYPE for websocket_up metric
        lines.append("# HELP websocket_health Whether the WebSocket server is up (1=up, 0=down)")
        lines.append("# TYPE websocket_health gauge")
        for result in summary.results:
            status_value = 1 if result.status == HealthStatus.HEALTHY else 0
            lines.append(
                f'websocket_health{{name="{result.name}",host="{result.host}",port="{result.port}"}} {status_value}'
            )

        lines.append("")

        # HELP and TYPE for websocket_latency_ms metric
        lines.append("# HELP websocket_latency_ms WebSocket connection latency in milliseconds")
        lines.append("# TYPE websocket_latency_ms gauge")
        for result in summary.results:
            latency = result.latency_ms if result.latency_ms is not None else 0
            lines.append(
                f'websocket_latency_ms{{name="{result.name}",host="{result.host}",port="{result.port}"}} {latency:.2f}'
            )

        lines.append("")

        # HELP and TYPE for websocket_status_info metric
        lines.append("# HELP websocket_status_info WebSocket server status as info label")
        lines.append("# TYPE websocket_status_info gauge")
        for result in summary.results:
            status_value = 1 if result.status != HealthStatus.UNHEALTHY else 0
            lines.append(
                f'websocket_status_info{{name="{result.name}",status="{result.status.value}"}} {status_value}'
            )

        return "\n".join(lines)


# =============================================================================
# Configuration Loading
# =============================================================================

def load_config_from_yaml(config_path: Path | None = None) -> dict[ServerName, ServerConfig] | None:
    """Load server configurations from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Dictionary of server configurations or None if not found
    """
    if config_path is None:
        # Try default location
        config_path = Path("settings/mahavishnu.yaml")

    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        # Extract WebSocket server configurations if present
        servers_config = config_data.get("websocket_servers")
        if servers_config and isinstance(servers_config, dict):
            return servers_config

    except Exception as e:
        # Silently fall back to defaults on any error
        pass

    return None


# =============================================================================
# CLI Application
# =============================================================================

@app.command()
def main(
    servers: str = Option(
        None,
        "--servers",
        "-s",
        help="Comma-separated list of servers to check (default: all)",
        metavar="SERVERS",
    ),
    timeout: float = Option(
        5.0,
        "--timeout",
        "-t",
        help="Connection timeout in seconds",
        min=1.0,
        max=30.0,
    ),
    json_output: bool = Option(
        False,
        "--json",
        help="Output results as JSON",
    ),
    prometheus_output: bool = Option(
        False,
        "--prometheus",
        help="Output results in Prometheus text format",
    ),
    verbose: bool = Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed error messages and dependency impact",
    ),
    advanced: bool = Option(
        False,
        "--advanced",
        help="Perform advanced WebSocket protocol checks",
    ),
    config: str = Option(
        None,
        "--config",
        "-c",
        help="Path to YAML configuration file",
        metavar="PATH",
    ),
):
    """Check health of WebSocket servers.

    Exit codes:
        0: All servers healthy
        1: Some servers unhealthy (degraded)
        2: Critical failure (all servers down or configuration error)
    """
    # Load server configurations
    servers_config = DEFAULT_SERVERS.copy()
    if config:
        custom_config = load_config_from_yaml(Path(config))
        if custom_config:
            servers_config.update(custom_config)

    # Filter servers if --servers flag provided
    if servers:
        selected_servers = servers.split(",")
        servers_to_check = {
            name: servers_config[name]
            for name in selected_servers
            if name in servers_config
        }
        if not servers_to_check:
            print(f"Error: No valid servers found in '{servers}'", file=sys.stderr)
            print(f"Available servers: {', '.join(servers_config.keys())}", file=sys.stderr)
            raise Exit(code=2)
    else:
        servers_to_check = servers_config

    # Run health checks
    summary = asyncio.run(
        check_all_servers(
            servers=servers_to_check,
            timeout=timeout,
            advanced=advanced,
        )
    )

    # Format and output results
    if prometheus_output:
        output = OutputFormatter.format_prometheus(summary)
    elif json_output:
        output = OutputFormatter.format_json(summary)
    else:
        output = OutputFormatter.format_console(summary, verbose=verbose)

    print(output)

    # Exit with appropriate code
    raise Exit(code=summary.exit_code)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    app()
