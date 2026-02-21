"""WebSocket authentication configuration for Mahavishnu.

This module provides JWT authentication configuration for the Mahavishnu
WebSocket server, using environment variables for secure credential management.
"""

from __future__ import annotations

import os
import logging

from mcp_common.websocket.auth import WebSocketAuthenticator

logger = logging.getLogger(__name__)


# Get JWT secret from environment - REQUIRED in production
# No default for security - must be explicitly set
_DEFAULT_DEV_SECRET = "dev-secret-change-in-production"
JWT_SECRET = os.getenv("MAHAVISHNU_JWT_SECRET", _DEFAULT_DEV_SECRET)

# Get token expiry from environment (default: 1 hour)
TOKEN_EXPIRY = int(os.getenv("MAHAVISHNU_TOKEN_EXPIRY", "3600"))

# Check if authentication is enabled
# Default to True for security - explicitly set to "false" for development only
AUTH_ENABLED = os.getenv("MAHAVISHNU_AUTH_ENABLED", "true").lower() == "true"

# Warn if using insecure defaults
_INSECURE_CONFIG = JWT_SECRET == _DEFAULT_DEV_SECRET or not AUTH_ENABLED
if _INSECURE_CONFIG:
    logger.warning(
        "⚠️  SECURITY WARNING: WebSocket using insecure configuration! "
        "Set MAHAVISHNU_JWT_SECRET and MAHAVISHNU_AUTH_ENABLED=true for production."
    )


def get_authenticator() -> WebSocketAuthenticator | None:
    """Get configured WebSocket authenticator.

    Returns:
        WebSocketAuthenticator instance if JWT secret is configured,
        None for development mode
    """
    if not AUTH_ENABLED:
        logger.info("WebSocket authentication disabled (development mode)")
        return None

    if JWT_SECRET == "dev-secret-change-in-production":
        logger.warning(
            "Using default JWT secret - please set MAHAVISHNU_JWT_SECRET "
            "environment variable in production"
        )

    return WebSocketAuthenticator(
        secret=JWT_SECRET,
        algorithm="HS256",
        token_expiry=TOKEN_EXPIRY,
    )


def generate_token(user_id: str, permissions: list[str] | None = None) -> str:
    """Generate a JWT token for testing or development.

    Args:
        user_id: User identifier
        permissions: List of permissions (default: ["read"])

    Returns:
        JWT token string

    Example:
        >>> token = generate_token("user123", ["read", "write"])
        >>> print(f"Token: {token}")
    """
    authenticator = get_authenticator()
    if authenticator is None:
        # Development mode - create a temporary authenticator
        authenticator = WebSocketAuthenticator(
            secret=JWT_SECRET,
            algorithm="HS256",
            token_expiry=TOKEN_EXPIRY,
        )

    return authenticator.create_token({
        "user_id": user_id,
        "permissions": permissions or ["read"],
    })


def verify_token(token: str) -> dict[str, object] | None:
    """Verify a JWT token.

    Args:
        token: JWT token to verify

    Returns:
        Token payload if valid, None otherwise
    """
    authenticator = get_authenticator()
    if authenticator is None:
        # Development mode - create a temporary authenticator
        authenticator = WebSocketAuthenticator(
            secret=JWT_SECRET,
            algorithm="HS256",
            token_expiry=TOKEN_EXPIRY,
        )

    return authenticator.verify_token(token)
