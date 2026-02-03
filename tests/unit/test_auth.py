"""Unit tests for JWT authentication."""

import pytest

from mahavishnu.core.auth import JWTAuth, get_auth_from_config
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


def test_create_and_verify_token():
    """Test creating and verifying a JWT token."""
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=1)  # 1 minute expiry

    # Create a token
    data = {"sub": "test_user", "role": "admin"}
    token = auth.create_access_token(data)

    # Verify the token
    decoded_data = auth.verify_token(token)

    assert decoded_data.username == "test_user"


def test_expired_token():
    """Test that expired tokens are rejected."""
    secret = "x" * 32
    auth = JWTAuth(secret=secret, expire_minutes=0.01)  # Expire in 0.01 minutes (0.6 seconds)

    # Create a token
    data = {"sub": "test_user", "role": "admin"}
    token = auth.create_access_token(data)

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


def test_get_auth_from_config():
    """Test getting JWTAuth from configuration."""
    # Test with auth disabled
    config = MahavishnuSettings(auth={"enabled": False})
    auth = get_auth_from_config(config)
    assert auth is None

    # Test with auth enabled but no secret
    config = MahavishnuSettings(auth={"enabled": True, "secret": None})
    auth = get_auth_from_config(config)
    assert auth is None

    # Test with auth enabled and valid secret
    secret = "x" * 32
    config = MahavishnuSettings(auth={"enabled": True, "secret": secret})
    auth = get_auth_from_config(config)
    assert auth is not None
    assert auth.secret == secret
