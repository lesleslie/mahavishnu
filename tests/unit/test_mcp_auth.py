"""Unit tests for MCP tool authorization decorators."""

from mcp_common.auth.audit import AuditLogger
import pytest

from mahavishnu.core.auth import AuthenticationError
from mahavishnu.mcp.auth import (
    CredentialManager,
    extract_auth_from_request,
    get_audit_logger,
    require_mcp_auth,
)

# =============================================================================
# AUDIT LOGGING TESTS
# =============================================================================


def test_get_audit_logger_returns_logger():
    """Test that get_audit_logger returns an AuditLogger instance."""
    al = get_audit_logger()
    assert isinstance(al, AuditLogger)


# =============================================================================
# AUTHORIZATION DECORATOR TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_require_mcp_auth_passes_with_user_id():
    """Test that decorator passes with user_id provided."""
    decorator = require_mcp_auth()

    @decorator
    async def test_function(user_id: str | None = None) -> str:
        return f"hello {user_id}"

    result = await test_function(user_id="alice")
    assert "alice" in result


@pytest.mark.asyncio
async def test_require_mcp_auth_no_user_id():
    """Test that decorator denies access without user_id."""
    decorator = require_mcp_auth()

    @decorator
    async def test_function(param1: str) -> dict:
        return {"status": "success", "result": param1}

    # Call without user_id
    result = await test_function(param1="test")

    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_REQUIRED"
    assert "user_id parameter missing" in result["error"]


@pytest.mark.asyncio
async def test_require_mcp_auth_auth_only_no_rbac():
    """Test authentication-only mode (no RBAC)."""
    decorator = require_mcp_auth(rbac_manager=None)

    @decorator
    async def test_function(param1: str, user_id: str | None = None) -> dict:
        return {"status": "success", "result": param1}

    # Call with user_id (no permission check)
    result = await test_function(param1="test", user_id="test_user")

    assert result["status"] == "success"
    assert result["result"] == "test"


# =============================================================================
# CREDENTIAL MANAGEMENT TESTS
# =============================================================================


def test_credential_manager_redact_from_dict():
    """Test credential redaction from dictionary."""
    data = {
        "username": "testuser",
        "password": "secret123",
        "api_key": "key_abc123",
        "normal_field": "normal_value",
        "ssh_key": "ssh-rsa AAAA...",
    }

    redacted = CredentialManager.redact_from_dict(data)

    assert redacted["username"] == "testuser"
    assert redacted["password"] == "secr***"
    assert redacted["api_key"] == "key_***"
    assert redacted["normal_field"] == "normal_value"
    assert redacted["ssh_key"] == "ssh-***"


def test_credential_manager_custom_sensitive_keys():
    """Test custom sensitive keys."""
    data = {
        "custom_secret": "value123",
        "public_field": "public_value",
    }

    redacted = CredentialManager.redact_from_dict(data, sensitive_keys=["custom_secret"])

    assert redacted["custom_secret"] == "value***"
    assert redacted["public_field"] == "public_value"


def test_credential_manager_validate_secret_str():
    """Test SecretStr validation."""
    # Valid secret
    secret = CredentialManager.validate_secret_str("a" * 32)
    assert secret.get_secret_value() == "a" * 32

    # Secret too short
    with pytest.raises(ValueError, match="too short"):
        CredentialManager.validate_secret_str("short")


def test_credential_manager_validate_secret_str_custom_min_length():
    """Test SecretStr validation with custom minimum."""
    # Valid secret (50 chars)
    secret = CredentialManager.validate_secret_str("a" * 50, min_length=50)
    assert secret.get_secret_value() == "a" * 50

    # Secret too short
    with pytest.raises(ValueError, match="too short"):
        CredentialManager.validate_secret_str("a" * 30, min_length=50)


# =============================================================================
# AUTHENTICATION EXTRACTION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_extract_auth_from_request_direct_user_id():
    """Test extracting user_id from direct parameter."""
    request = {"user_id": "test_user", "other_param": "value"}

    auth_context = await extract_auth_from_request(request)

    assert auth_context["user_id"] == "test_user"
    assert auth_context["method"] == "direct"


@pytest.mark.asyncio
async def test_extract_auth_from_request_bearer_token():
    """Test extracting user_id from bearer token."""
    request = {"headers": {"Authorization": "Bearer test_user_token"}}

    auth_context = await extract_auth_from_request(request)

    assert auth_context["user_id"] == "test_user_token"
    assert auth_context["method"] == "bearer_token"


@pytest.mark.asyncio
async def test_extract_auth_from_request_api_key():
    """Test extracting user_id from API key."""
    request = {"api_key": "mhv_test_user"}

    auth_context = await extract_auth_from_request(request)

    assert auth_context["user_id"] == "test_user"
    assert auth_context["method"] == "api_key"


@pytest.mark.asyncio
async def test_extract_auth_from_request_no_auth():
    """Test failure when no authentication provided."""
    request = {"other_param": "value"}

    with pytest.raises(AuthenticationError, match="Could not extract user_id"):
        await extract_auth_from_request(request)
