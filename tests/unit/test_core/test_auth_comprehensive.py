"""Comprehensive tests for authentication module.

This module provides extensive test coverage for:
- JWT token creation and verification
- Token expiration handling
- Invalid token signature handling
- Token data validation
- Multi-auth handler integration
- Authentication decorators
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException, Request, status

from mahavishnu.core.auth import (
    JWTAuth,
    TokenData,
    get_auth_from_config,
    require_auth,
)
from mahavishnu.core.errors import AuthenticationError


class TestJWTAuth:
    """Test suite for JWTAuth class."""

    def test_init_with_valid_secret(self):
        """Test initialization with valid secret."""
        auth = JWTAuth(secret="a" * 32)  # 32 characters minimum
        assert auth.secret == "a" * 32
        assert auth.algorithm == "HS256"
        assert auth.expire_minutes == 60

    def test_init_with_custom_algorithm(self):
        """Test initialization with custom algorithm."""
        auth = JWTAuth(secret="a" * 32, algorithm="HS512")
        assert auth.algorithm == "HS512"

    def test_init_with_custom_expiration(self):
        """Test initialization with custom expiration."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=120)
        assert auth.expire_minutes == 120

    def test_init_rejects_short_secret(self):
        """Test that short secrets are rejected."""
        with pytest.raises(ValueError) as exc_info:
            JWTAuth(secret="short")

        assert "at least 32 characters" in str(exc_info.value).lower()

    def test_create_access_token_with_username(self):
        """Test token creation with username."""
        auth = JWTAuth(secret="a" * 32)
        data = {"sub": "testuser"}

        token = auth.create_access_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_includes_expiration(self):
        """Test that token includes expiration."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=60)
        data = {"sub": "testuser"}

        token = auth.create_access_token(data)

        # Decode to verify expiration
        payload = jwt.decode(token, auth.secret, algorithms=[auth.algorithm])
        assert "exp" in payload

    def test_create_access_token_with_custom_data(self):
        """Test token creation with custom data."""
        auth = JWTAuth(secret="a" * 32)
        data = {"sub": "testuser", "role": "admin", "scopes": ["read", "write"]}

        token = auth.create_access_token(data)

        # Verify custom data is preserved
        payload = jwt.decode(token, auth.secret, algorithms=[auth.algorithm])
        assert payload["sub"] == "testuser"
        assert payload["role"] == "admin"
        assert payload["scopes"] == ["read", "write"]

    def test_verify_token_valid(self):
        """Test verification of valid token."""
        auth = JWTAuth(secret="a" * 32)
        data = {"sub": "testuser"}

        token = auth.create_access_token(data)
        token_data = auth.verify_token(token)

        assert isinstance(token_data, TokenData)
        assert token_data.username == "testuser"
        assert isinstance(token_data.exp, int)

    def test_verify_token_invalid_signature(self):
        """Test verification fails with invalid signature."""
        auth1 = JWTAuth(secret="a" * 32)
        auth2 = JWTAuth(secret="b" * 32)

        data = {"sub": "testuser"}
        token = auth1.create_access_token(data)

        # Try to verify with different secret
        with pytest.raises(AuthenticationError) as exc_info:
            auth2.verify_token(token)

        assert "invalid token signature" in exc_info.value.message.lower()

    def test_verify_token_malformed(self):
        """Test verification fails with malformed token."""
        auth = JWTAuth(secret="a" * 32)

        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token("not.a.valid.token")

        assert "could not decode" in exc_info.value.message.lower() or "authentication error" in exc_info.value.message.lower()

    def test_verify_token_missing_username(self):
        """Test verification fails when username is missing."""
        auth = JWTAuth(secret="a" * 32)

        # Create token without 'sub' field
        token = jwt.encode({"exp": 9999999999}, auth.secret, algorithm=auth.algorithm)

        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token(token)

        assert "could not validate credentials" in exc_info.value.message.lower()

    def test_verify_token_missing_expiration(self):
        """Test verification fails when expiration is missing."""
        auth = JWTAuth(secret="a" * 32)

        # Create token without 'exp' field
        token = jwt.encode({"sub": "testuser"}, auth.secret, algorithm=auth.algorithm)

        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token(token)

        assert "could not validate credentials" in exc_info.value.message.lower()

    def test_verify_token_expired(self):
        """Test verification fails for expired token."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=1)

        # Create token that's already expired
        data = {"sub": "testuser", "exp": int((datetime.now(tz=UTC) - timedelta(minutes=2)).timestamp())}
        token = jwt.encode(data, auth.secret, algorithm=auth.algorithm)

        with pytest.raises(AuthenticationError) as exc_info:
            auth.verify_token(token)

        assert "token has expired" in exc_info.value.message.lower()

    def test_verify_token_expiration_future(self):
        """Test verification succeeds for non-expired token."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=60)

        data = {"sub": "testuser"}
        token = auth.create_access_token(data)

        # Should not raise exception
        token_data = auth.verify_token(token)
        assert token_data.username == "testuser"

    def test_verify_token_expiration_near_boundary(self):
        """Test verification near expiration boundary."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=1)

        # Create token that expires in 30 seconds
        exp_time = int((datetime.now(tz=UTC) + timedelta(seconds=30)).timestamp())
        data = {"sub": "testuser", "exp": exp_time}
        token = jwt.encode(data, auth.secret, algorithm=auth.algorithm)

        # Should still be valid
        token_data = auth.verify_token(token)
        assert token_data.username == "testuser"


class TestTokenData:
    """Test suite for TokenData model."""

    def test_token_data_creation(self):
        """Test TokenData model creation."""
        token_data = TokenData(username="testuser", exp=1234567890)
        assert token_data.username == "testuser"
        assert token_data.exp == 1234567890

    def test_token_data_with_future_expiration(self):
        """Test TokenData with future expiration."""
        future_exp = int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp())
        token_data = TokenData(username="testuser", exp=future_exp)
        assert token_data.exp > datetime.now(tz=UTC).timestamp()


class TestRequireAuth:
    """Test suite for require_auth decorator."""

    @pytest.mark.asyncio
    async def test_require_auth_with_no_handler(self):
        """Test decorator allows access when auth is disabled."""
        auth_handler = None

        @require_auth(auth_handler)
        async def protected_function():
            return "success"

        result = await protected_function()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_auth_with_valid_token(self):
        """Test decorator allows access with valid token."""
        from unittest.mock import MagicMock, AsyncMock

        # Create mock auth handler
        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(return_value={
            "user": "testuser",
            "method": "jwt",
            "scopes": ["read", "write"]
        })

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return request.state.user

        # Create mock request with valid authorization header
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer valid_token"}
        request.state = MagicMock()

        result = await protected_function(request)
        assert result == "testuser"

    @pytest.mark.asyncio
    async def test_require_auth_without_request_object(self):
        """Test decorator fails when no request object is provided."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(return_value={
            "user": "testuser",
            "method": "jwt"
        })

        @require_auth(auth_handler)
        async def protected_function():
            return "success"

        # No request provided
        with pytest.raises(HTTPException) as exc_info:
            await protected_function()

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_require_auth_with_missing_authorization_header(self):
        """Test decorator fails when Authorization header is missing."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(return_value={
            "user": "testuser",
            "method": "jwt"
        })

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return "success"

        # Create mock request without authorization header
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await protected_function(request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "authorization header" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_require_auth_with_invalid_auth_header_format(self):
        """Test decorator fails with invalid authorization header format."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return "success"

        # Create mock request with malformed authorization header
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "InvalidFormat token"}
        request.state = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await protected_function(request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_require_auth_with_authentication_error(self):
        """Test decorator fails when authentication raises error."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(side_effect=AuthenticationError(
            message="Invalid credentials",
            details={"error": "Token expired"}
        ))

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return "success"

        # Create mock request with authorization header
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer invalid_token"}
        request.state = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await protected_function(request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "invalid credentials" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_require_auth_sets_request_state(self):
        """Test decorator sets request state with auth info."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(return_value={
            "user": "testuser",
            "method": "jwt",
            "scopes": ["read", "write", "admin"]
        })

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return {
                "user": request.state.user,
                "method": request.state.auth_method,
                "scopes": request.state.scopes
            }

        # Create mock request
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer valid_token"}
        request.state = MagicMock()

        result = await protected_function(request)
        assert result["user"] == "testuser"
        assert result["method"] == "jwt"
        assert result["scopes"] == ["read", "write", "admin"]

    @pytest.mark.asyncio
    async def test_require_auth_with_empty_scopes(self):
        """Test decorator handles empty scopes."""
        from unittest.mock import MagicMock

        auth_handler = MagicMock()
        auth_handler.authenticate_request = MagicMock(return_value={
            "user": "testuser",
            "method": "jwt",
            "scopes": []
        })

        @require_auth(auth_handler)
        async def protected_function(request: Request):
            return request.state.scopes

        # Create mock request
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer valid_token"}
        request.state = MagicMock()

        result = await protected_function(request)
        assert result == []


class TestGetAuthFromConfig:
    """Test suite for get_auth_from_config function."""

    def test_get_auth_from_config_creates_handler(self):
        """Test that MultiAuthHandler is created from config."""
        from unittest.mock import MagicMock

        mock_config = MagicMock()

        result = get_auth_from_config(mock_config)

        # Should return a MultiAuthHandler instance
        assert result is not None
        # Verify it's configured with the provided config
        assert result.config == mock_config


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_jwt_with_very_long_secret(self):
        """Test JWT with very long secret."""
        long_secret = "x" * 1000
        auth = JWTAuth(secret=long_secret)
        assert auth.secret == long_secret

    def test_jwt_with_minimum_length_secret(self):
        """Test JWT with exactly 32 character secret."""
        secret = "a" * 32
        auth = JWTAuth(secret=secret)
        assert auth.secret == secret

    def test_jwt_with_very_short_expiration(self):
        """Test JWT with very short expiration time."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=1)
        data = {"sub": "testuser"}

        token = auth.create_access_token(data)
        token_data = auth.verify_token(token)

        assert token_data.username == "testuser"

    def test_jwt_with_very_long_expiration(self):
        """Test JWT with very long expiration time."""
        auth = JWTAuth(secret="a" * 32, expire_minutes=10080)  # 1 week
        data = {"sub": "testuser"}

        token = auth.create_access_token(data)
        token_data = auth.verify_token(token)

        assert token_data.username == "testuser"

    def test_token_with_unicode_username(self):
        """Test token creation with Unicode username."""
        auth = JWTAuth(secret="a" * 32)
        data = {"sub": "用户名"}

        token = auth.create_access_token(data)
        token_data = auth.verify_token(token)

        assert token_data.username == "用户名"

    def test_token_with_special_characters(self):
        """Test token creation with special characters in data."""
        auth = JWTAuth(secret="a" * 32)
        data = {"sub": "user@example.com", "roles": ["admin&user", "read/write"]}

        token = auth.create_access_token(data)

        # Should not raise exception
        payload = jwt.decode(token, auth.secret, algorithms=[auth.algorithm])
        assert payload["sub"] == "user@example.com"

    def test_verify_token_with_empty_string(self):
        """Test verification fails with empty string."""
        auth = JWTAuth(secret="a" * 32)

        with pytest.raises(AuthenticationError):
            auth.verify_token("")

    def test_verify_token_with_none(self):
        """Test verification fails with None."""
        auth = JWTAuth(secret="a" * 32)

        with pytest.raises((AuthenticationError, AttributeError)):
            auth.verify_token(None)  # type: ignore
