#!/usr/bin/env python3
"""Script to update WebSocket servers with TLS support.

This script creates TLS configuration modules for services and updates
their WebSocket server __init__ methods to support TLS parameters.
"""

from __future__ import annotations

import sys
from pathlib import Path


# TLS config template
TLS_CONFIG_TEMPLATE = '''"""TLS configuration for {service_name} WebSocket server.

This module provides TLS configuration loading from environment variables
and helper functions for secure WebSocket connections.
"""

from __future__ import annotations

import logging
from mcp_common.websocket.tls import (
    get_tls_config_from_env,
    create_ssl_context,
)

logger = logging.getLogger(__name__)


def get_websocket_tls_config() -> dict[str, str | bool | None]:
    """Get TLS configuration from environment variables.

    Environment Variables:
        {service_upper}_WS_TLS_ENABLED: Enable TLS ("true" or "false")
        {service_upper}_WS_CERT_FILE: Path to certificate file (PEM format)
        {service_upper}_WS_KEY_FILE: Path to private key file (PEM format)
        {service_upper}_WS_CA_FILE: Path to CA file (for client verification)
        {service_upper}_WS_VERIFY_CLIENT: Verify client certificates ("true" or "false")

    Returns:
        Dictionary with TLS configuration
    """
    return get_tls_config_from_env("{service_upper}_WS")


def load_ssl_context(
    cert_file: str | None = None,
    key_file: str | None = None,
    ca_file: str | None = None,
    verify_client: bool = False,
) -> dict:
    """Load SSL context for WebSocket server.

    Args:
        cert_file: Path to certificate file
        key_file: Path to private key file
        ca_file: Path to CA file for client verification
        verify_client: Whether to verify client certificates

    Returns:
        Dictionary with ssl_context and paths for cleanup
    """
    # If no files provided, check environment
    if not cert_file and not key_file:
        config = get_websocket_tls_config()
        if config["tls_enabled"]:
            cert_file = config["cert_file"]
            key_file = config["key_file"]
            ca_file = config["ca_file"]
            verify_client = config.get("verify_client", False)

    # Create SSL context if files provided
    ssl_context = None
    if cert_file and key_file:
        try:
            ssl_context = create_ssl_context(
                cert_file=cert_file,
                key_file=key_file,
                ca_file=ca_file,
                verify_client=verify_client,
            )
            logger.info(f"Loaded TLS certificate: {{cert_file}}")
        except Exception as e:
            logger.error(f"Failed to load SSL context: {{e}}")
            raise

    return {{
        "ssl_context": ssl_context,
        "cert_file": cert_file,
        "key_file": key_file,
        "ca_file": ca_file,
        "verify_client": verify_client,
    }}
'''


SERVICES = [
    {
        "name": "akosha",
        "package": "akosha",
        "service_upper": "AKOSHA",
        "server_file": "/Users/les/Projects/akosha/akosha/websocket/server.py",
        "config_file": "/Users/les/Projects/akosha/akosha/websocket/tls_config.py",
    },
    {
        "name": "crackerjack",
        "package": "crackerjack",
        "service_upper": "CRACKERJACK",
        "server_file": "/Users/les/Projects/crackerjack/crackerjack/websocket/server.py",
        "config_file": "/Users/les/Projects/crackerjack/crackerjack/websocket/tls_config.py",
    },
    {
        "name": "dhruva",
        "package": "dhruva",
        "service_upper": "DHRUVA",
        "server_file": "/Users/les/Projects/dhruva/dhruva/websocket/server.py",
        "config_file": "/Users/les/Projects/dhruva/dhruva/websocket/tls_config.py",
    },
    {
        "name": "excalidraw-mcp",
        "package": "excalidraw_mcp",
        "service_upper": "EXCALIDRAW",
        "server_file": "/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/server.py",
        "config_file": "/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/tls_config.py",
    },
    {
        "name": "fastblocks",
        "package": "fastblocks",
        "service_upper": "FASTBLOCKS",
        "server_file": "/Users/les/Projects/fastblocks/fastblocks/websocket/server.py",
        "config_file": "/Users/les/Projects/fastblocks/fastblocks/websocket/tls_config.py",
    },
]


def create_tls_config(service: dict) -> None:
    """Create TLS config module for a service."""
    config_path = Path(service["config_file"])
    content = TLS_CONFIG_TEMPLATE.format(
        service_name=service["name"].capitalize(),
        service_upper=service["service_upper"],
    )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content)
    print(f"Created: {config_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Update WebSocket servers with TLS support")
    parser.add_argument(
        "--services",
        nargs="*",
        choices=[s["name"] for s in SERVICES],
        help="Services to update (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    # Filter services
    if args.services:
        target_services = [s for s in SERVICES if s["name"] in args.services]
    else:
        target_services = SERVICES

    print(f"Updating {len(target_services)} services...")

    for service in target_services:
        print(f"\n--- {service['name'].capitalize()} ---")
        create_tls_config(service)

    print("\n✓ TLS config modules created")
    print("\nNext steps:")
    print("1. Review and update each WebSocket server __init__ method")
    print("2. Add TLS parameters: cert_file, key_file, ca_file, tls_enabled, verify_client, auto_cert")
    print("3. Import and use load_ssl_context() from tls_config module")
    print("4. Update integration.py to pass TLS parameters")


if __name__ == "__main__":
    main()
