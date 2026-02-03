"""MCP tool authorization decorators with RBAC and audit logging.

This module provides authorization decorators for FastMCP tools to ensure
that code query tools are properly authenticated and access is logged for security auditing.

Key Features:
- @require_mcp_auth decorator for FastMCP tools
- RBAC integration with Permission system
- Comprehensive audit logging
- Pydantic SecretStr for credential handling
"""

import logging
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from pydantic import SecretStr

# Import from parent modules to avoid circular import
from ..core.auth import AuthenticationError
from ..core.permissions import Permission, RBACManager

logger = logging.getLogger(__name__)


# =============================================================================
# AUDIT LOGGING
# =============================================================================

class AuditLogger:
    """Audit logger for security events."""

    def __init__(self, log_path: Path | str = "data/audit.log"):
        """Initialize audit logger.

        Args:
            log_path: Path to audit log file
        """
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: str,
        user_id: str | None,
        tool_name: str,
        params: dict[str, Any],
        result: str = "success",
        error: str | None = None,
    ) -> None:
        """Log security event.

        Args:
            event_type: Type of event (e.g., "tool_access", "auth_failure")
            user_id: User identifier (None if unauthenticated)
            tool_name: Name of the tool being accessed
            params: Tool parameters (sensitive values will be redacted)
            result: Result of the operation ("success", "failure", "denied")
            error: Error message if operation failed
        """
        timestamp = datetime.now(tz=UTC).isoformat()

        # Redact sensitive parameters
        safe_params = self._redact_secrets(params)

        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "user_id": user_id,
            "tool_name": tool_name,
            "params": safe_params,
            "result": result,
            "error": error,
        }

        # Write to audit log
        try:
            with open(self.log_path, "a") as f:
                import json

                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

        # Also log to standard logger for immediate visibility
        log_message = (
            f"[{timestamp}] {event_type}: user={user_id}, tool={tool_name}, "
            f"result={result}"
        )

        if error:
            log_message += f", error={error}"

        if result == "denied":
            logger.warning(log_message)
        elif result == "failure":
            logger.error(log_message)
        else:
            logger.info(log_message)

    @staticmethod
    def _redact_secrets(params: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive parameter values.

        Args:
            params: Original parameters

        Returns:
            Parameters with sensitive values redacted
        """
        redacted = {}

        sensitive_keys = {
            "password", "token", "key", "secret", "credential",
            "api_key", "apikey", "auth_token", "access_token",
            "ssh_key", "private_key", "passphrase",
        }

        for key, value in params.items():
            key_lower = key.lower()

            # Check if this is a sensitive key
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, SecretStr):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = AuditLogger._redact_secrets(value)
            elif isinstance(value, list):
                redacted[key] = [
                    AuditLogger._redact_secrets(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                redacted[key] = value

        return redacted


# Global audit logger instance
_audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance."""
    return _audit_logger


# =============================================================================
# MCP AUTHORIZATION DECORATOR
# =============================================================================

def require_mcp_auth(
    rbac_manager: RBACManager | None = None,
    required_permission: Permission | None = None,
    require_repo_param: str | None = None,
) -> Callable:
    """Decorator to require authentication and authorization for MCP tools.

    This decorator checks:
    1. Authentication: User is authenticated (user_id provided)
    2. Authorization: User has required permission for the repo
    3. Audit logging: All access attempts are logged

    Args:
        rbac_manager: RBAC manager for authorization checks (None = auth only)
        required_permission: Required permission (None = no permission check)
        require_repo_param: Parameter name containing repo path (for RBAC checks)

    Returns:
        Decorator function

    Example:
        ```python
        @server.tool()
        @require_mcp_auth(
            rbac_manager=rbac,
            required_permission=Permission.READ_REPO,
            require_repo_param="project_path"
        )
        async def get_function_context(project_path: str, function_name: str) -> dict:
            # Tool implementation
            pass
        ```
    """
    audit_logger = get_audit_logger()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Extract authentication context from kwargs
            # FastMCP tools pass parameters as kwargs
            user_id = kwargs.get("user_id")
            auth_method = kwargs.get("auth_method", "unknown")

            # Check authentication
            if not user_id:
                audit_logger.log(
                    event_type="auth_failure",
                    user_id=None,
                    tool_name=func.__name__,
                    params=kwargs,
                    result="denied",
                    error="No user_id provided",
                )

                return {
                    "status": "error",
                    "error": "Authentication required: user_id parameter missing",
                    "error_code": "AUTH_REQUIRED",
                }

            # Check authorization if RBAC manager provided
            if rbac_manager and required_permission:
                repo_path = None

                # Extract repo path from parameters
                if require_repo_param:
                    repo_path = kwargs.get(require_repo_param)
                elif "project_path" in kwargs:
                    repo_path = kwargs.get("project_path")
                elif "repo_path" in kwargs:
                    repo_path = kwargs.get("repo_path")

                if not repo_path:
                    audit_logger.log(
                        event_type="auth_failure",
                        user_id=user_id,
                        tool_name=func.__name__,
                        params=kwargs,
                        result="denied",
                        error="No repo path provided for authorization check",
                    )

                    return {
                        "status": "error",
                        "error": f"Authorization failed: Cannot determine repo path for {required_permission.value} check",
                        "error_code": "AUTH_NO_REPO",
                    }

                # Check permission
                try:
                    has_permission = await rbac_manager.check_permission(
                        user_id=user_id,
                        repo=repo_path,
                        permission=required_permission,
                    )

                    if not has_permission:
                        audit_logger.log(
                            event_type="auth_denied",
                            user_id=user_id,
                            tool_name=func.__name__,
                            params=kwargs,
                            result="denied",
                            error=f"User lacks {required_permission.value} permission for repo",
                        )

                        return {
                            "status": "error",
                            "error": f"Authorization denied: {required_permission.value} permission required for {repo_path}",
                            "error_code": "AUTH_DENIED",
                        }

                except Exception as e:
                    audit_logger.log(
                        event_type="auth_failure",
                        user_id=user_id,
                        tool_name=func.__name__,
                        params=kwargs,
                        result="failure",
                        error=f"Authorization check failed: {e}",
                    )

                    logger.error(f"Authorization error: {e}")

                    return {
                        "status": "error",
                        "error": "Authorization check failed",
                        "error_code": "AUTH_ERROR",
                    }

            # Authentication and authorization successful
            audit_logger.log(
                event_type="tool_access",
                user_id=user_id,
                tool_name=func.__name__,
                params=kwargs,
                result="success",
            )

            # Call the original function
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                # Log execution error
                audit_logger.log(
                    event_type="tool_execution_error",
                    user_id=user_id,
                    tool_name=func.__name__,
                    params=kwargs,
                    result="failure",
                    error=str(e),
                )
                raise

        return wrapper

    return decorator


# =============================================================================
# AUTHENTICATION CONTEXT EXTRACTORS
# =============================================================================

async def extract_auth_from_request(request: dict[str, Any]) -> dict[str, Any]:
    """Extract authentication context from MCP request.

    Args:
        request: MCP request dictionary

    Returns:
        Authentication context with user_id and auth_method

    Raises:
        AuthenticationError: If authentication fails
    """
    # Try to get user_id from various sources
    user_id = None
    auth_method = None

    # Check for direct user_id parameter
    if "user_id" in request:
        user_id = request["user_id"]
        auth_method = "direct"

    # Check for Authorization header (if available in request context)
    elif "headers" in request and isinstance(request["headers"], dict):
        headers = request["headers"]
        auth_header = headers.get("Authorization") or headers.get("authorization")

        if auth_header and auth_header.startswith("Bearer "):
            # This would need JWT validation in production
            token = auth_header[7:]  # Remove "Bearer " prefix
            # For now, extract user_id from token (simplified)
            # In production, use JWTManager.verify_token()
            user_id = token  # Simplified for development
            auth_method = "bearer_token"

    # Check for API key
    elif "api_key" in request:
        api_key = request["api_key"]
        # Validate API key against database
        # For now, simplified validation
        if api_key and api_key.startswith("mhv_"):
            user_id = api_key[4:]  # Extract user from API key
            auth_method = "api_key"

    if not user_id:
        raise AuthenticationError(
            message="Could not extract user_id from request",
            details={"available_keys": list(request.keys())},
        )

    return {
        "user_id": user_id,
        "method": auth_method,
    }


# =============================================================================
# CREDENTIAL MANAGEMENT
# =============================================================================

class CredentialManager:
    """Manager for secure credential handling."""

    @staticmethod
    def redact_from_dict(data: dict[str, Any], sensitive_keys: list[str] | None = None) -> dict[str, Any]:
        """Redact sensitive values from dictionary.

        Args:
            data: Dictionary with potentially sensitive values
            sensitive_keys: List of keys to redact (None = use default list)

        Returns:
            Dictionary with sensitive values redacted
        """
        if sensitive_keys is None:
            sensitive_keys = [
                "password", "token", "key", "secret", "credential",
                "api_key", "apikey", "auth_token", "access_token",
                "ssh_key", "private_key", "passphrase", "jwt_secret",
            ]

        redacted = {}

        for key, value in data.items():
            key_lower = key.lower()

            # Check if this is a sensitive key
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                if isinstance(value, str):
                    # Show first 4 characters for debugging
                    preview = value[:4] if len(value) > 4 else value
                    redacted[key] = f"{preview}***"
                elif isinstance(value, SecretStr):
                    # SecretStr already protects the value
                    redacted[key] = "***"
                else:
                    redacted[key] = "***"
            else:
                redacted[key] = value

        return redacted

    @staticmethod
    def validate_secret_str(value: str, min_length: int = 32) -> SecretStr:
        """Validate and wrap a secret value.

        Args:
            value: Secret value to validate
            min_length: Minimum length requirement

        Returns:
            SecretStr wrapped value

        Raises:
            ValueError: If secret is too short
        """
        if len(value) < min_length:
            raise ValueError(
                f"Secret too short: {len(value)} characters (minimum {min_length})"
            )

        return SecretStr(value)
