from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
import logging
from typing import TYPE_CHECKING, Any

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.permissions import Permission
from pydantic import SecretStr

from ..core.auth import AuthenticationError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_audit_logger = AuditLogger()
_auth_config: AuthConfig | None = None


def get_audit_logger() -> AuditLogger:
    return _audit_logger


def _get_config() -> AuthConfig:
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig(
            service_name="mahavishnu",
            secret_env_var="MAHAVISHNU_AUTH_SECRET",
        )
    return _auth_config


def require_mcp_auth(
    rbac_manager: Any | None = None,
    required_permission: Permission | None = None,
    require_repo_param: str | None = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            user_id = kwargs.get("user_id")
            perm = required_permission or Permission.READ
            if not user_id:
                _audit_logger.emit(
                    AuthAuditEvent(
                        timestamp=datetime.now(UTC),
                        service="mahavishnu",
                        caller_service="unknown",
                        caller_id="unknown",
                        action=func.__name__,
                        permission=perm,
                        result="denied",
                        reason="No user_id provided",
                        source_ip=None,
                        token_id=None,
                    )
                )
                return {
                    "status": "error",
                    "error": "Authentication required: user_id parameter missing",
                    "error_code": "AUTH_REQUIRED",
                }
            _audit_logger.emit(
                AuthAuditEvent(
                    timestamp=datetime.now(UTC),
                    service="mahavishnu",
                    caller_service="unknown",
                    caller_id=user_id,
                    action=func.__name__,
                    permission=perm,
                    result="allowed",
                    reason=None,
                    source_ip=None,
                    token_id=None,
                )
            )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


async def extract_auth_from_request(request: dict[str, Any]) -> dict[str, Any]:
    user_id = None
    auth_method = None

    if "user_id" in request:
        user_id = request["user_id"]
        auth_method = "direct"
    elif "headers" in request and isinstance(request["headers"], dict):
        headers = request["headers"]
        auth_header = headers.get("Authorization") or headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = token
            auth_method = "bearer_token"
    elif "api_key" in request:
        api_key = request["api_key"]
        if api_key and api_key.startswith("mhv_"):
            user_id = api_key[4:]
            auth_method = "api_key"

    if not user_id:
        raise AuthenticationError(
            message="Could not extract user_id from request",
            details={"available_keys": list(request.keys())},
        )

    return {"user_id": user_id, "method": auth_method}


class CredentialManager:
    _SENSITIVE_KEYS = frozenset(
        {
            "password",
            "token",
            "key",
            "secret",
            "credential",
            "api_key",
            "apikey",
            "auth_token",
            "access_token",
            "ssh_key",
            "private_key",
            "passphrase",
            "jwt_secret",
        }
    )

    @staticmethod
    def redact_from_dict(
        data: dict[str, Any], sensitive_keys: list[str] | None = None
    ) -> dict[str, Any]:
        keys = frozenset(sensitive_keys or []) | CredentialManager._SENSITIVE_KEYS
        redacted = {}
        for k, v in data.items():
            if any(s in k.lower() for s in keys):
                redacted[k] = (
                    f"{str(v)[:4]}***" if isinstance(v, str) and len(str(v)) > 4 else "***"
                )
            else:
                redacted[k] = v
        return redacted

    @staticmethod
    def validate_secret_str(value: str, min_length: int = 32) -> SecretStr:
        if len(value) < min_length:
            raise ValueError(f"Secret too short: {len(value)} characters (minimum {min_length})")
        return SecretStr(value)
