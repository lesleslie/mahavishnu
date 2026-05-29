"""Unit tests for JWT authentication."""

from unittest.mock import patch

import jwt
import pytest

from mahavishnu.core.auth import JWTAuth, TokenPayload, get_auth_from_config
from mahavishnu.core.config import MahavishnuSettings


def test_jwt_auth_creation():
    """Test JWTAuth creation with valid secret."""
    secret = "x" * 32  # 32-character secret
    auth = JWTAuth(secret=secret)

    assert auth.secret == secret
    assert auth.algorithm == "HS256"
    assert auth.expire_minutes == 60


def test_jwt_auth_creation_short_secret():
    """Test JWTAuth creation fails with short secret."""
    short_secret = "short"

    with pytest.raises(ValueError) as exc_info:
        JWTAuth(secret=short_secret)

    assert "JWT secret must be at least 32 characters long" in str(exc_info.value)


def test_token_payload_missing_attribute_raises():
    payload = TokenPayload({"user_id": "u1"})

    with pytest.raises(AttributeError, match="missing"):
        _ = payload.missing


def test_create_and_verify_token():
    """Test creating and verifying a JWT token."""
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=1)  # 1 minute expiry

    # Create a token using the current API
    token = auth.create_token(user_id="test_user", scopes=["admin"])

    # Verify the token
    decoded_data = auth.verify_token(token)

    assert decoded_data["sub"] == "test_user"
    assert "admin" in decoded_data["scopes"]


def test_create_access_token_uses_claims_and_extra_claims():
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=1)

    token = auth.create_access_token(
        {"sub": "test_user", "scopes": ["read"], "team": "platform"},
        role="admin",
    )

    decoded_data = auth.verify_token(token)
    assert decoded_data["sub"] == "test_user"
    assert decoded_data["scopes"] == ["read"]
    assert decoded_data["team"] == "platform"
    assert decoded_data["role"] == "admin"


def test_create_access_token_requires_user_identifier():
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=1)

    with pytest.raises(ValueError, match="sub' or 'user_id"):
        auth.create_access_token({"scope": "read"})


def test_expired_token():
    """Test that expired tokens are rejected."""
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=0.01)  # Expire in 0.01 minutes (0.6 seconds)

    # Create a token using the current API
    token = auth.create_token(user_id="test_user")

    # Wait for token to expire
    import time

    time.sleep(1)

    # Verification should fail
    with pytest.raises(Exception) as exc_info:
        auth.verify_token(token)

    assert "expired" in str(exc_info.value).lower()


def test_invalid_token():
    """Test that invalid tokens are rejected."""
    secret = "x" * 32
    auth = JWTAuth(secret=secret)

    # Try to verify an invalid token
    with pytest.raises(Exception):
        auth.verify_token("invalid.token.string")


def test_verify_token_decode_error():
    """Test that jwt.DecodeError is caught and wrapped as AuthenticationError."""
    from mahavishnu.core.errors import AuthenticationError

    secret = "x" * 32
    auth = JWTAuth(secret=secret)

    with patch("jwt.decode", side_effect=jwt.exceptions.DecodeError("bad token")):
        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token("any.token.here")
    assert "decode" in exc_info.value.message.lower()


def test_verify_token_generic_exception_wrapped():
    from mahavishnu.core.errors import AuthenticationError

    secret = "x" * 32
    auth = JWTAuth(secret=secret)

    with patch("jwt.decode", side_effect=Exception("boom")):
        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token("any.token.here")

    assert "authentication error" in exc_info.value.message.lower()
    assert exc_info.value.details["error"] == "boom"


def test_get_auth_from_config():
    """Test getting auth handler from configuration."""
    # Test with auth disabled
    config = MahavishnuSettings(auth={"enabled": False})
    auth = get_auth_from_config(config)
    assert auth is None

    # Test with auth enabled and valid secret
    secret = "x" * 32
    config = MahavishnuSettings(auth={"enabled": True, "secret": secret})
    auth = get_auth_from_config(config)
    assert auth is not None
