"""Unit tests for MCP tool authorization decorators."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.auth import (
    AuditLogger,
    CredentialManager,
    extract_auth_from_request,
    require_mcp_auth,
)
from mahavishnu.core.auth import AuthenticationError
from mahavishnu.core.permissions import Permission, RBACManager
from mahavishnu.core.config import MahavishnuSettings


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create temporary directory for test audit logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def audit_logger(temp_dir):
    """Create audit logger for testing."""
    return AuditLogger(log_path=temp_dir / "audit.log")


@pytest.fixture
def rbac_manager():
    """Create RBAC manager for testing."""
    # Mock config
    mock_config = MagicMock(spec=MahavishnuSettings)
    mock_auth = MagicMock()
    mock_auth.secret = "test_secret_key_32_characters_long_"
    mock_auth.algorithm = "HS256"
    mock_auth.expire_minutes = 60
    mock_config.auth = mock_auth

    manager = RBACManager(mock_config)

    # Create test users
    asyncio.run(manager.create_user("admin_user", ["admin"]))
    asyncio.run(manager.create_user("dev_user", ["developer"], allowed_repos=["/safe/repo"]))
    asyncio.run(manager.create_user("viewer_user", ["viewer"], allowed_repos=["/safe/repo"]))

    return manager


# =============================================================================
# AUDIT LOGGING TESTS
# =============================================================================


def test_audit_logger_log_success(audit_logger, temp_dir):
    """Test successful audit logging."""
    audit_logger.log(
        event_type="tool_access",
        user_id="test_user",
        tool_name="test_tool",
        params={"param1": "value1", "param2": "value2"},
        result="success",
    )

    # Verify log file created
    assert audit_logger.log_path.exists()

    # Read and verify log entry
    with open(audit_logger.log_path, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["event_type"] == "tool_access"
    assert log_entry["user_id"] == "test_user"
    assert log_entry["tool_name"] == "test_tool"
    assert log_entry["result"] == "success"
    assert log_entry["params"]["param1"] == "value1"


def test_audit_logger_redact_secrets(audit_logger, temp_dir):
    """Test that sensitive parameters are redacted."""
    audit_logger.log(
        event_type="tool_access",
        user_id="test_user",
        tool_name="test_tool",
        params={
            "param1": "value1",
            "password": "secret123",
            "api_key": "key_abc123",
            "normal_param": "normal_value",
        },
        result="success",
    )

    # Read log entry
    with open(audit_logger.log_path, "r") as f:
        log_entry = json.loads(f.readline())

    # Verify redaction
    assert log_entry["params"]["param1"] == "value1"
    assert log_entry["params"]["password"] == "***REDACTED***"
    assert log_entry["params"]["api_key"] == "***REDACTED***"
    assert log_entry["params"]["normal_param"] == "normal_value"


def test_audit_logger_log_denied(audit_logger, temp_dir):
    """Test denied access logging."""
    audit_logger.log(
        event_type="auth_denied",
        user_id="unauthorized_user",
        tool_name="test_tool",
        params={"repo": "/protected/repo"},
        result="denied",
        error="User lacks permission",
    )

    # Read log entry
    with open(audit_logger.log_path, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["result"] == "denied"
    assert log_entry["error"] == "User lacks permission"


# =============================================================================
# AUTHORIZATION DECORATOR TESTS
# =============================================================================


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
async def test_require_mcp_auth_with_permission_granted(rbac_manager):
    """Test successful authorization with permission."""
    decorator = require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )

    @decorator
    async def test_function(project_path: str, user_id: str | None = None) -> dict:
        return {"status": "success", "result": "processed"}

    # Call with authorized user
    result = await test_function(
        project_path="/safe/repo",
        user_id="dev_user",  # Has access to /safe/repo
    )

    assert result["status"] == "success"
    assert result["result"] == "processed"


@pytest.mark.asyncio
async def test_require_mcp_auth_with_permission_denied(rbac_manager):
    """Test authorization denied when user lacks permission."""
    decorator = require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )

    @decorator
    async def test_function(project_path: str, user_id: str | None = None) -> dict:
        return {"status": "success", "result": "processed"}

    # Call with unauthorized user
    result = await test_function(
        project_path="/unauthorized/repo",
        user_id="viewer_user",  # Only has access to /safe/repo
    )

    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_DENIED"
    assert "permission required" in result["error"]


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


@pytest.mark.asyncio
async def test_require_mcp_auth_logs_to_audit_file(rbac_manager, temp_dir):
    """Test that decorator logs to audit file."""
    audit_logger = AuditLogger(log_path=temp_dir / "audit.log")

    decorator = require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )

    @decorator
    async def test_function(project_path: str, user_id: str | None = None) -> dict:
        return {"status": "success", "result": "processed"}

    # Patch the global audit logger
    with patch("mahavishnu.mcp.auth.get_audit_logger", return_value=audit_logger):
        result = await test_function(
            project_path="/safe/repo",
            user_id="dev_user",
        )

    assert result["status"] == "success"

    # Verify audit log
    with open(audit_logger.log_path, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["event_type"] == "tool_access"
    assert log_entry["user_id"] == "dev_user"
    assert log_entry["tool_name"] == "test_function"
    assert log_entry["result"] == "success"


@pytest.mark.asyncio
async def test_require_mcp_auth_logs_denied_access(rbac_manager, temp_dir):
    """Test that denied access is logged to audit file."""
    audit_logger = AuditLogger(log_path=temp_dir / "audit.log")

    decorator = require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )

    @decorator
    async def test_function(project_path: str, user_id: str | None = None) -> dict:
        return {"status": "success", "result": "processed"}

    # Patch the global audit logger
    with patch("mahavishnu.mcp.auth.get_audit_logger", return_value=audit_logger):
        result = await test_function(
            project_path="/unauthorized/repo",
            user_id="viewer_user",
        )

    assert result["status"] == "error"

    # Verify audit log shows denied access
    with open(audit_logger.log_path, "r") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["event_type"] == "auth_denied"
    assert log_entry["result"] == "denied"
    assert log_entry["error"] is not None


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
    assert redacted["password"] == "sec***"  # First 4 chars shown
    assert redacted["api_key"] == "key_***"
    assert redacted["normal_field"] == "normal_value"
    assert redacted["ssh_key"] == "ssh-***"


def test_credential_manager_custom_sensitive_keys():
    """Test custom sensitive keys."""
    data = {
        "custom_secret": "value123",
        "public_field": "public_value",
    }

    redacted = CredentialManager.redact_from_dict(
        data, sensitive_keys=["custom_secret"]
    )

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
    request = {
        "headers": {"Authorization": "Bearer test_user_token"}
    }

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
