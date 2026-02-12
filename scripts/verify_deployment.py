#!/usr/bin/env python3
"""Mahavishnu WebSocket deployment verification script.

This script performs comprehensive checks to verify that the WebSocket server
is correctly deployed and configured for production use.

Usage:
    python scripts/verify_deployment.py [--host HOST] [--port PORT] [--metrics-port PORT]

Example:
    python scripts/verify_deployment.py --host localhost --port 8686
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_success(message: str) -> None:
    """Print success message."""
    print(f"{GREEN}✓{RESET} {message}")


def print_error(message: str) -> None:
    """Print error message."""
    print(f"{RED}✗{RESET} {message}")


def print_warning(message: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}⚠{RESET} {message}")


def print_info(message: str) -> None:
    """Print info message."""
    print(f"{BLUE}ℹ{RESET} {message}")


def print_header(message: str) -> None:
    """Print section header."""
    print(f"\n{BOLD}{message}{RESET}")
    print("=" * len(message))


class DeploymentVerifier:
    """Verify WebSocket deployment configuration."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8686,
        metrics_port: int = 9090,
        use_tls: bool = False,
    ):
        """Initialize verifier.

        Args:
            host: WebSocket server host
            port: WebSocket server port
            metrics_port: Prometheus metrics port
            use_tls: Use WSS (TLS) instead of WS
        """
        self.host = host
        self.port = port
        self.metrics_port = metrics_port
        self.use_tls = use_tls
        self.results = []
        self.ws_url = f"{'wss' if use_tls else 'ws'}://{host}:{port}"
        self.http_url = f"{'https' if use_tls else 'http'}://{host}:{port}"
        self.metrics_url = f"http://{host}:{metrics_port}"

    def record_result(self, check: str, passed: bool, message: str) -> None:
        """Record test result.

        Args:
            check: Name of check
            passed: Whether check passed
            message: Result message
        """
        self.results.append({
            "check": check,
            "passed": passed,
            "message": message,
        })

    async def check_health_endpoint(self) -> bool:
        """Check health endpoint is accessible."""
        print_header("1. Health Endpoint Check")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.http_url}/health")

                if response.status_code == 200:
                    data = response.json()
                    print_success(f"Health endpoint returned 200 OK")

                    if "status" in data:
                        print_success(f"Server status: {data['status']}")
                    else:
                        print_warning("No 'status' field in response")

                    if "checks" in data:
                        for check_name, check_status in data["checks"].items():
                            status_icon = "✓" if check_status == "passing" else "✗"
                            print(f"  {status_icon} {check_name}: {check_status}")

                    if "metrics" in data:
                        print_info(f"Active connections: {data['metrics'].get('active_connections', 'N/A')}")

                    self.record_result("health_endpoint", True, "Health endpoint accessible")
                    return True
                else:
                    print_error(f"Health endpoint returned {response.status_code}")
                    self.record_result("health_endpoint", False, f"HTTP {response.status_code}")
                    return False

        except httpx.ConnectError as e:
            print_error(f"Connection failed: {e}")
            self.record_result("health_endpoint", False, str(e))
            return False
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            self.record_result("health_endpoint", False, str(e))
            return False

    async def check_metrics_endpoint(self) -> bool:
        """Check Prometheus metrics endpoint."""
        print_header("2. Metrics Endpoint Check")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.metrics_url}/metrics")

                if response.status_code == 200:
                    metrics_text = response.text

                    # Check for required metrics
                    required_metrics = [
                        "websocket_connections_total",
                        "websocket_connections_active",
                        "websocket_messages_total",
                    ]

                    all_present = True
                    for metric in required_metrics:
                        if metric in metrics_text:
                            print_success(f"Metric found: {metric}")
                        else:
                            print_error(f"Metric missing: {metric}")
                            all_present = False

                    if all_present:
                        self.record_result("metrics_endpoint", True, "All required metrics present")
                        return True
                    else:
                        self.record_result("metrics_endpoint", False, "Some metrics missing")
                        return False
                else:
                    print_error(f"Metrics endpoint returned {response.status_code}")
                    self.record_result("metrics_endpoint", False, f"HTTP {response.status_code}")
                    return False

        except Exception as e:
            print_error(f"Metrics check failed: {e}")
            self.record_result("metrics_endpoint", False, str(e))
            return False

    async def check_websocket_connection(self) -> bool:
        """Check WebSocket connection can be established."""
        print_header("3. WebSocket Connection Check")

        try:
            # Configure SSL context for WSS
            ssl_context = None
            if self.use_tls:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(self.ws_url, ssl=ssl_context, close_timeout=5) as ws:
                print_success(f"Connected to {self.ws_url}")

                # Receive welcome message
                try:
                    welcome_msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    welcome_data = json.loads(welcome_msg)
                    print_success(f"Received welcome message: {welcome_data.get('event', 'unknown')}")
                except asyncio.TimeoutError:
                    print_warning("No welcome message received")

                self.record_result("websocket_connection", True, "WebSocket connection successful")
                return True

        except websockets.exceptions.InvalidStatusCode as e:
            print_error(f"Invalid status code: {e}")
            self.record_result("websocket_connection", False, str(e))
            return False
        except Exception as e:
            print_error(f"WebSocket connection failed: {e}")
            self.record_result("websocket_connection", False, str(e))
            return False

    async def check_tls_configuration(self) -> bool:
        """Check TLS configuration (if enabled)."""
        print_header("4. TLS Configuration Check")

        if not self.use_tls:
            print_info("TLS not enabled, skipping TLS checks")
            return True

        try:
            # Get certificate
            import socket

            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            with socket.create_connection((self.host, self.port)) as sock:
                with context.wrap_socket(sock, server_hostname=self.host) as ssock:
                    cert = ssock.getpeercert()
                    print_success("TLS certificate retrieved")

                    # Check expiration
                    if 'notAfter' in cert:
                        print_info(f"Certificate expires: {cert['notAfter']}")

                    # Check protocol version
                    version = ssock.version()
                    print_success(f"TLS version: {version}")

                    if version in ['TLSv1.2', 'TLSv1.3']:
                        self.record_result("tls_configuration", True, f"TLS {version}")
                        return True
                    else:
                        print_error(f"Insecure TLS version: {version}")
                        self.record_result("tls_configuration", False, f"Insecure version: {version}")
                        return False

        except Exception as e:
            print_error(f"TLS check failed: {e}")
            self.record_result("tls_configuration", False, str(e))
            return False

    def check_environment_variables(self) -> bool:
        """Check required environment variables."""
        print_header("5. Environment Variables Check")

        required_vars = [
            "MAHAVISHNU_TLS_ENABLED",
            "MAHAVISHNU_AUTH_ENABLED",
            "MAHAVISHNU_JWT_SECRET",
        ]

        optional_vars = [
            "MAHAVISHNU_CERT_FILE",
            "MAHAVISHNU_KEY_FILE",
            "MAHAVISHNU_METRICS_ENABLED",
            "MAHAVISHNU_REDIS_HOST",
        ]

        all_present = True

        for var in required_vars:
            value = os.getenv(var)
            if value:
                # Hide sensitive values
                display_value = "***" if "SECRET" in var or "PASSWORD" in var else value
                print_success(f"{var}={display_value}")
            else:
                print_error(f"{var} not set")
                all_present = False

        for var in optional_vars:
            if os.getenv(var):
                print_info(f"{var} is set")

        if all_present:
            self.record_result("environment_variables", True, "All required vars present")
            return True
        else:
            self.record_result("environment_variables", False, "Some required vars missing")
            return False

    def check_file_permissions(self) -> bool:
        """Check file permissions for certificates and keys."""
        print_header("6. File Permissions Check")

        cert_file = os.getenv("MAHAVISHNU_CERT_FILE")
        key_file = os.getenv("MAHAVISHNU_KEY_FILE")

        if not cert_file or not key_file:
            print_info("Certificate paths not set, skipping permission check")
            return True

        all_correct = True

        # Check certificate file
        if Path(cert_file).exists():
            stat_info = os.stat(cert_file)
            mode = oct(stat_info.st_mode & 0o777)
            print_info(f"Certificate file: {cert_file} (mode {mode})")
            print_success("Certificate file exists")
        else:
            print_error(f"Certificate file not found: {cert_file}")
            all_correct = False

        # Check key file
        if Path(key_file).exists():
            stat_info = os.stat(key_file)
            mode = oct(stat_info.st_mode & 0o777)
            print_info(f"Key file: {key_file} (mode {mode})")

            # Key file should be 600 or 400
            if mode in ('0o600', '0o400'):
                print_success("Key file permissions are secure")
            else:
                print_warning(f"Key file should be 0600 or 0400, currently {mode}")
        else:
            print_error(f"Key file not found: {key_file}")
            all_correct = False

        if all_correct:
            self.record_result("file_permissions", True, "Files accessible")
        else:
            self.record_result("file_permissions", False, "Some files missing")

        return all_correct

    def check_certificate_validity(self) -> bool:
        """Check certificate validity and expiration."""
        print_header("7. Certificate Validity Check")

        cert_file = os.getenv("MAHAVISHNU_CERT_FILE")

        if not cert_file:
            print_info("Certificate file not set, skipping validity check")
            return True

        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend

            with open(cert_file, "rb") as f:
                cert_data = f.read()
                cert = x509.load_pem_x509_certificate(cert_data, default_backend())

            # Check expiration
            now = time.time()
            not_after = cert.not_valid_after.timestamp()

            if now > not_after:
                print_error("Certificate has expired")
                self.record_result("certificate_validity", False, "Certificate expired")
                return False

            days_remaining = (not_after - now) / 86400

            if days_remaining < 30:
                print_warning(f"Certificate expires in {days_remaining:.0f} days")
                self.record_result("certificate_validity", False, f"Expires in {days_remaining:.0f} days")
                return False
            else:
                print_success(f"Certificate valid for {days_remaining:.0f} more days")
                print_info(f"Valid from: {cert.not_valid_before.isoformat()}")
                print_info(f"Valid until: {cert.not_valid_after.isoformat()}")
                self.record_result("certificate_validity", True, f"{days_remaining:.0f} days remaining")
                return True

        except Exception as e:
            print_error(f"Certificate validation failed: {e}")
            self.record_result("certificate_validity", False, str(e))
            return False

    async def check_redis_connection(self) -> bool:
        """Check Redis connection (if configured)."""
        print_header("8. Redis Connection Check")

        redis_host = os.getenv("MAHAVISHNU_REDIS_HOST")
        redis_port = int(os.getenv("MAHAVISHNU_REDIS_PORT", "6379"))

        if not redis_host:
            print_info("Redis not configured, skipping Redis check")
            return True

        try:
            import redis.asyncio as aioredis

            client = await aioredis.from_url(f"redis://{redis_host}:{redis_port}")
            await client.ping()
            await client.close()

            print_success(f"Connected to Redis at {redis_host}:{redis_port}")
            self.record_result("redis_connection", True, "Redis accessible")
            return True

        except Exception as e:
            print_error(f"Redis connection failed: {e}")
            self.record_result("redis_connection", False, str(e))
            return False

    def print_summary(self) -> None:
        """Print test summary."""
        print_header("Test Summary")

        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        percentage = (passed / total * 100) if total > 0 else 0

        print(f"\nTotal tests: {total}")
        print(f"{GREEN}Passed: {passed}{RESET}")
        print(f"{RED}Failed: {total - passed}{RESET}")
        print(f"Success rate: {percentage:.0f}%")

        print("\nDetailed Results:")
        print("-" * 60)

        for result in self.results:
            icon = f"{GREEN}✓{RESET}" if result["passed"] else f"{RED}✗{RESET}"
            print(f"{icon} {result['check']}: {result['message']}")

        print("-" * 60)

        # Return exit code
        if percentage >= 80:
            print(f"\n{GREEN}{BOLD}Deployment verification PASSED{RESET}")
            sys.exit(0)
        else:
            print(f"\n{RED}{BOLD}Deployment verification FAILED{RESET}")
            sys.exit(1)

    async def run_all_checks(self) -> None:
        """Run all verification checks."""
        print(f"\n{BOLD}Mahavishnu WebSocket Deployment Verification{RESET}")
        print(f"Target: {self.ws_url}")

        # Run all checks
        await self.check_health_endpoint()
        await self.check_metrics_endpoint()
        await self.check_websocket_connection()
        await self.check_tls_configuration()
        self.check_environment_variables()
        self.check_file_permissions()
        self.check_certificate_validity()
        await self.check_redis_connection()

        # Print summary
        self.print_summary()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Verify Mahavishnu WebSocket deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="WebSocket server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8686,
        help="WebSocket server port (default: 8686)",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9090,
        help="Prometheus metrics port (default: 9090)",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        help="Use WSS (TLS) instead of WS",
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="Skip environment variable checks",
    )

    args = parser.parse_args()

    verifier = DeploymentVerifier(
        host=args.host,
        port=args.port,
        metrics_port=args.metrics_port,
        use_tls=args.tls,
    )

    asyncio.run(verifier.run_all_checks())


if __name__ == "__main__":
    main()
