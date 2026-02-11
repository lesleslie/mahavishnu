"""TLS configuration for Mahavishnu WebSocket server.

This module provides TLS configuration loading from environment variables
and helper functions for secure WebSocket connections.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp_common.websocket.tls import (
    get_tls_config_from_env,
    create_ssl_context,
)

logger = logging.getLogger(__name__)


def get_websocket_tls_config() -> dict[str, str | bool | None]:
    """Get TLS configuration from environment variables.

    Environment Variables:
        MAHAVISHNU_WS_TLS_ENABLED: Enable TLS ("true" or "false")
        MAHAVISHNU_WS_CERT_FILE: Path to certificate file (PEM format)
        MAHAVISHNU_WS_KEY_FILE: Path to private key file (PEM format)
        MAHAVISHNU_WS_CA_FILE: Path to CA file (for client verification)
        MAHAVISHNU_WS_VERIFY_CLIENT: Verify client certificates ("true" or "false")

    Returns:
        Dictionary with TLS configuration

    Example:
        >>> config = get_websocket_tls_config()
        >>> print(config)
        {'tls_enabled': True, 'cert_file': '/path/to/cert.pem', ...}
    """
    return get_tls_config_from_env("MAHAVISHNU_WS")


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

    Example:
        >>> result = load_ssl_context(
        ...     cert_file="/path/to/cert.pem",
        ...     key_file="/path/to/key.pem"
        ... )
        >>> ssl_context = result["ssl_context"]
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
            logger.info(f"Loaded TLS certificate: {cert_file}")
        except Exception as e:
            logger.error(f"Failed to load SSL context: {e}")
            raise

    return {
        "ssl_context": ssl_context,
        "cert_file": cert_file,
        "key_file": key_file,
        "ca_file": ca_file,
        "verify_client": verify_client,
    }


def get_tls_cli_options() -> dict[str, Any]:
    """Get TLS-related CLI option defaults from environment.

    Returns:
        Dictionary with default values for TLS CLI options

    Example:
        >>> defaults = get_tls_cli_options()
        >>> typer.Option(default=defaults["tls_enabled"])
    """
    config = get_websocket_tls_config()

    return {
        "tls_enabled": config["tls_enabled"],
        "cert_file": config["cert_file"],
        "key_file": config["key_file"],
        "ca_file": config["ca_file"],
        "verify_client": config.get("verify_client", False),
    }
