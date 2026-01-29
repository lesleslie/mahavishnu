"""Subscription-based authentication module for Mahavishnu.

This module provides authentication mechanisms for services like Claude Code
that use subscription tokens, in addition to the existing JWT authentication.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import jwt
from pydantic import BaseModel

from .errors import AuthenticationError


class AuthMethod(str, Enum):
    """Enumeration of supported authentication methods."""

    JWT = "jwt"
    CLAUDE_SUBSCRIPTION = "claude_subscription"
    CODEX_SUBSCRIPTION = "codex_subscription"
    QWEN_FREE = "qwen_free"


class SubscriptionTokenData(BaseModel):
    """Subscription token data model."""

    user_id: str
    subscription_type: str
    exp: int  # Expiration timestamp as integer
    scopes: list[str] = []


class SubscriptionAuth:
    """Subscription-based authentication handler for services like Claude Code."""

    def __init__(self, secret: str, algorithm: str = "HS256", expire_minutes: int = 60):
        """
        Initialize subscription auth handler.

        Args:
            secret: Secret key for validating subscription tokens
            algorithm: JWT algorithm to use (default HS256)
            expire_minutes: Token expiration time in minutes
        """
        if len(secret) < 32:
            raise ValueError("Subscription auth secret must be at least 32 characters long")

        self.secret = secret
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    def create_subscription_token(
        self, user_id: str, subscription_type: str, scopes: list[str] = None
    ) -> str:
        """
        Create a subscription token for services like Claude Code.

        Args:
            user_id: Unique identifier for the user
            subscription_type: Type of subscription (e.g., 'claude_code')
            scopes: List of permissions/scopes for the token

        Returns:
            Encoded subscription token
        """
        if scopes is None:
            scopes = ["read", "execute"]

        to_encode = {
            "sub": user_id,  # Using 'sub' to match JWT standard
            "user_id": user_id,
            "subscription_type": subscription_type,
            "scopes": scopes,
        }

        expire = datetime.utcnow() + timedelta(minutes=self.expire_minutes)
        to_encode.update({"exp": int(expire.timestamp())})  # Convert datetime to integer timestamp

        encoded_jwt = jwt.encode(to_encode, self.secret, algorithm=self.algorithm)
        return encoded_jwt

    def verify_subscription_token(self, token: str) -> SubscriptionTokenData:
        """
        Verify and decode a subscription token.

        Args:
            token: Subscription token to verify

        Returns:
            Decoded token data

        Raises:
            AuthenticationError: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])

            user_id: str = payload.get("user_id")
            subscription_type: str = payload.get("subscription_type")

            if not user_id or not subscription_type:
                raise AuthenticationError(
                    message="Invalid subscription token: missing required fields",
                    details={"error": "user_id or subscription_type not found in token"},
                )

            token_data = SubscriptionTokenData(
                user_id=user_id,
                subscription_type=subscription_type,
                exp=payload.get("exp"),
                scopes=payload.get("scopes", []),
            )

            # Check if token is expired
            if datetime.utcnow().timestamp() > token_data.exp:
                raise AuthenticationError(
                    message="Subscription token has expired", details={"error": "Expired token"}
                )

            return token_data
        except jwt.exceptions.InvalidSignatureError as e:
            raise AuthenticationError(
                message="Invalid subscription token signature",
                details={"error": "Invalid signature"},
            ) from e
        except jwt.exceptions.DecodeError as e:
            raise AuthenticationError(
                message="Could not decode subscription token", details={"error": "Decode error"}
            ) from e
        except Exception as e:
            raise AuthenticationError(
                message=f"Subscription authentication error: {str(e)}", details={"error": str(e)}
            ) from e


class MultiAuthHandler:
    """Handles multiple authentication methods including JWT and subscription tokens."""

    def __init__(self, config):
        """
        Initialize multi-authentication handler.

        Args:
            config: MahavishnuSettings configuration object
        """
        self.config = config
        self.jwt_auth = None
        self.subscription_auth = None

        # Initialize JWT auth if enabled
        if config.auth_enabled and config.auth_secret:
            from .auth import JWTAuth

            self.jwt_auth = JWTAuth(
                secret=config.auth_secret,
                algorithm=config.auth_algorithm,
                expire_minutes=config.auth_expire_minutes,
            )

        # Initialize subscription auth if enabled
        if hasattr(config, "subscription_auth_enabled") and config.subscription_auth_enabled:
            subscription_secret = getattr(config, "subscription_auth_secret", None)
            if subscription_secret:
                self.subscription_auth = SubscriptionAuth(
                    secret=subscription_secret,
                    algorithm=getattr(config, "subscription_auth_algorithm", "HS256"),
                    expire_minutes=getattr(config, "subscription_auth_expire_minutes", 60),
                )

    def authenticate_request(self, auth_header: str) -> dict[str, Any]:
        """
        Authenticate a request using either JWT or subscription token.

        Args:
            auth_header: Authorization header value (e.g., "Bearer <token>")

        Returns:
            Dictionary with authentication result including user info and method used

        Raises:
            AuthenticationError: If authentication fails
        """
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthenticationError(
                message="Authorization header missing or invalid format",
                details={"error": "Expected 'Bearer <token>' format"},
            )

        token = auth_header[len("Bearer ") :]

        # Decode the token without verification to check its type
        try:
            decoded_payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.exceptions.DecodeError as e:
            raise AuthenticationError(
                message="Could not decode token", details={"error": "Invalid token format"}
            ) from e

        # Check if it's a subscription token by looking for subscription-specific claims
        is_subscription_token = "subscription_type" in decoded_payload

        if is_subscription_token and self.subscription_auth:
            # Try subscription token authentication
            try:
                token_data = self.subscription_auth.verify_subscription_token(token)

                # Determine the specific authentication method based on subscription type
                auth_method = AuthMethod.CLAUDE_SUBSCRIPTION
                if token_data.subscription_type == "codex":
                    auth_method = AuthMethod.CODEX_SUBSCRIPTION
                elif token_data.subscription_type == "claude_code":
                    auth_method = AuthMethod.CLAUDE_SUBSCRIPTION

                return {
                    "user": token_data.user_id,
                    "method": auth_method,
                    "subscription_type": token_data.subscription_type,
                    "scopes": token_data.scopes,
                    "authenticated": True,
                }
            except AuthenticationError as e:
                raise e  # Re-raise the specific error from subscription auth

        elif not is_subscription_token and self.jwt_auth:
            # Try JWT authentication
            try:
                token_data = self.jwt_auth.verify_token(token)
                return {
                    "user": token_data.username,
                    "method": AuthMethod.JWT,
                    "authenticated": True,
                    "scopes": ["read", "write", "execute"],  # Default scopes for JWT
                }
            except AuthenticationError as e:
                raise e  # Re-raise the specific error from JWT auth

        else:
            # Neither authentication method is appropriate for this token
            raise AuthenticationError(
                message="Authentication failed with all available methods",
                details={"error": "Invalid or expired token"},
            )

    def create_claude_subscription_token(self, user_id: str, scopes: list[str] = None) -> str:
        """
        Create a Claude Code subscription token.

        Args:
            user_id: Unique identifier for the user
            scopes: List of permissions for the token

        Returns:
            Encoded Claude Code subscription token
        """
        if not self.subscription_auth:
            raise AuthenticationError(
                message="Subscription authentication is not configured",
                details={"error": "subscription_auth not initialized"},
            )

        return self.subscription_auth.create_subscription_token(
            user_id=user_id, subscription_type="claude_code", scopes=scopes
        )

    def is_claude_subscribed(self) -> bool:
        """
        Check if Claude Code subscription authentication is available.

        Returns:
            True if Claude Code subscription auth is configured
        """
        return self.subscription_auth is not None

    def is_codex_subscribed(self) -> bool:
        """
        Check if Codex subscription authentication is available.

        Returns:
            True if Codex subscription auth is configured
        """
        return self.subscription_auth is not None

    def create_codex_subscription_token(self, user_id: str, scopes: list[str] = None) -> str:
        """
        Create a Codex subscription token.

        Args:
            user_id: Unique identifier for the user
            scopes: List of permissions for the token

        Returns:
            Encoded Codex subscription token
        """
        if not self.subscription_auth:
            raise AuthenticationError(
                message="Subscription authentication is not configured",
                details={"error": "subscription_auth not initialized"},
            )

        return self.subscription_auth.create_subscription_token(
            user_id=user_id, subscription_type="codex", scopes=scopes
        )

    def is_qwen_free(self) -> bool:
        """
        Check if Qwen is configured as a free service (no auth required).

        Returns:
            True if Qwen is configured as free service
        """
        # Qwen is free as mentioned by the user, so we could implement
        # special handling for it if needed
        return True  # Qwen is free as per user's specification
