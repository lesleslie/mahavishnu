"""Authentication module for Mahavishnu.

This module provides JWT authentication and a factory function
to create authentication handlers from configuration.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from .errors import AuthenticationError
from .subscription_auth import MultiAuthHandler


class JWTAuth:
    """JWT-based authentication handler."""

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        expire_minutes: int = 60,
    ) -> None:
        """Initialize JWT auth handler.

        Args:
            secret: Secret key for signing tokens
            algorithm: JWT algorithm to use (default HS256)
            expire_minutes: Token expiration time in minutes
        """
        if len(secret) < 32:
            raise ValueError("JWT secret must be at least 32 characters long")

        self.secret = secret
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    def create_token(
        self,
        user_id: str,
        scopes: list[str] | None = None,
        **extra_claims: Any,
    ) -> str:
        """Create a JWT token for a user.

        Args:
            user_id: Unique identifier for the user
            scopes: List of permissions/scopes for the token
            **extra_claims: Additional claims to include in the token

        Returns:
            Encoded JWT token
        """
        if scopes is None:
            scopes = ["read", "execute"]

        to_encode = {
            "sub": user_id,
            "user_id": user_id,
            "scopes": scopes,
            **extra_claims,
        }

        expire = datetime.now(tz=UTC) + timedelta(minutes=self.expire_minutes)
        to_encode.update({"exp": int(expire.timestamp())})

        encoded_jwt = jwt.encode(to_encode, self.secret, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify and decode a JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Decoded token payload

        Raises:
            AuthenticationError: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except jwt.exceptions.InvalidSignatureError as e:
            raise AuthenticationError(
                message="Invalid token signature",
                details={"error": "Invalid signature"},
            ) from e
        except jwt.exceptions.ExpiredSignatureError as e:
            raise AuthenticationError(
                message="Token has expired",
                details={"error": "Expired token"},
            ) from e
        except jwt.exceptions.DecodeError as e:
            raise AuthenticationError(
                message="Could not decode token",
                details={"error": "Decode error"},
            ) from e
        except Exception as e:
            raise AuthenticationError(
                message=f"Authentication error: {e}",
                details={"error": str(e)},
            ) from e


def get_auth_from_config(config) -> MultiAuthHandler | None:
    """Create an authentication handler from configuration.

    Args:
        config: MahavishnuSettings configuration object

    Returns:
        MultiAuthHandler instance if auth is enabled, None otherwise
    """
    # Check if auth is enabled
    auth_config = getattr(config, "auth", None)
    if not auth_config or not getattr(auth_config, "enabled", False):
        return None

    return MultiAuthHandler(config)


# Re-export AuthenticationError for convenience
__all__ = ["JWTAuth", "get_auth_from_config", "AuthenticationError", "MultiAuthHandler"]
