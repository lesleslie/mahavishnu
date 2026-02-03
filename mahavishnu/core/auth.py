"""Authentication module for Mahavishnu supporting both JWT and subscription tokens."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

UTC = UTC
from functools import wraps

from fastapi import HTTPException, Request, status
import jwt
from pydantic import BaseModel

from ..core.errors import AuthenticationError
from .subscription_auth import MultiAuthHandler


class TokenData(BaseModel):
    """Token data model."""

    username: str
    exp: int


class JWTAuth:
    """JWT Authentication handler."""

    def __init__(self, secret: str, algorithm: str = "HS256", expire_minutes: int = 60):
        """
        Initialize JWT Auth handler.

        Args:
            secret: JWT secret key (should be at least 32 characters)
            algorithm: JWT algorithm to use (default HS256)
            expire_minutes: Token expiration time in minutes
        """
        if len(secret) < 32:
            raise ValueError("JWT secret must be at least 32 characters long")

        self.secret = secret
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    def create_access_token(self, data: dict) -> str:
        """
        Create access token with expiration.

        Args:
            data: Data to encode in the token

        Returns:
            Encoded JWT token
        """
        to_encode = data.copy()
        expire = datetime.now(tz=UTC) + timedelta(minutes=self.expire_minutes)
        to_encode.update({"exp": int(expire.timestamp())})  # Convert datetime to integer timestamp
        encoded_jwt = jwt.encode(to_encode, self.secret, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> TokenData:
        """
        Verify and decode JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Decoded token data

        Raises:
            AuthenticationError: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            token_data = self._validate_payload(payload)
            self._check_token_expiry(token_data)
            return token_data
        except jwt.exceptions.InvalidSignatureError as e:
            raise AuthenticationError(
                message="Invalid token signature", details={"error": "Invalid signature"}
            ) from e
        except jwt.exceptions.DecodeError as e:
            raise AuthenticationError(
                message="Could not decode token", details={"error": "Decode error"}
            ) from e
        except Exception as e:
            raise AuthenticationError(
                message=f"Authentication error: {e}", details={"error": str(e)}
            ) from e

    def _validate_payload(self, payload: dict) -> TokenData:
        """Validate the JWT payload and extract token data."""
        username: str | None = payload.get("sub")
        exp: int | None = payload.get("exp")

        if username is None:
            raise AuthenticationError(
                message="Could not validate credentials",
                details={"error": "Username not found in token"},
            )

        if exp is None:
            raise AuthenticationError(
                message="Could not validate credentials",
                details={"error": "Expiration not found in token"},
            )

        return TokenData(username=username, exp=exp)

    def _check_token_expiry(self, token_data: TokenData) -> None:
        """Check if the token has expired."""
        if datetime.now(tz=UTC).timestamp() > token_data.exp:
            raise AuthenticationError(
                message="Token has expired", details={"error": "Expired token"}
            )


def get_auth_from_config(config: Any) -> MultiAuthHandler:
    """
    Create MultiAuthHandler instance from configuration.

    Args:
        config: MahavishnuSettings configuration

    Returns:
        MultiAuthHandler instance configured according to settings
    """
    return MultiAuthHandler(config)


def require_auth(auth_handler: Any) -> Callable:
    """
    Decorator to require authentication for functions using MultiAuthHandler.

    Args:
        auth_handler: MultiAuthHandler instance or None

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if not auth_handler:
                # If auth is disabled, allow access
                return await func(*args, **kwargs)

            # Extract token from request
            request: Request | None = kwargs.get("request") or (
                args[0] if args and isinstance(args[0], Request) else None
            )

            if not request:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Request object required for authentication",
                )

            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authorization header missing or invalid format",
                )

            try:
                auth_result = auth_handler.authenticate_request(auth_header)

                # Add user info to request state for use in route handlers
                request.state.user = auth_result.get("user")
                request.state.auth_method = auth_result.get("method")
                request.state.scopes = auth_result.get("scopes", [])

                return await func(*args, **kwargs)
            except AuthenticationError as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message
                ) from e

        return wrapper

    return decorator
