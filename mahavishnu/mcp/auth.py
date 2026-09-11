from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
import logging
from typing import TYPE_CHECKING, Any, cast

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.permissions import Permission
from pydantic import SecretStr

from ..core.auth import AuthenticationError
from ..core.errors import ConfigurationError

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
    required_permission: Any | None = None,
    require_repo_param: str | None = None,
) -> Callable[..., Any]:
    """Decorator that gates an MCP tool on RBAC-managed permission.

    Behavior (Task 11.7 — fail-closed):

    * When ``rbac_manager`` is ``None``, the decorator denies with
      ``error_code == "AUTH_NOT_CONFIGURED"``. This is a configuration
      error, not "open by default" — production wiring MUST inject a real
      :class:`~mahavishnu.core.permissions.RBACManager`.
    * When ``user_id`` is missing from kwargs, the decorator denies with
      ``error_code == "AUTH_REQUIRED"``.
    * When ``rbac_manager.check_permission(user_id, repo, perm)`` returns
      ``False``, the decorator denies with
      ``error_code == "PERMISSION_DENIED"``.
    * Otherwise the wrapped function runs and an ``allowed`` audit event
      is emitted.

    ``user_id`` is read from kwargs (caller-controlled). Production
    callers should override this by injecting ``user_id`` from FastMCP
    session context. The RBAC check still runs and is the binding
    authority — a spoofed ``user_id`` without the required permission
    will be denied.

    The ``repo`` argument to ``check_permission`` is taken from the
    wrapped tool's ``repo`` kwarg when present, otherwise ``"*"``.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Task 11.10: the Permission.READ fallback is removed. Every tool
        # that uses @require_mcp_auth MUST pass an explicit
        # ``required_permission``. Undeclared permission is a misconfiguration,
        # not "fall back to read" — fail-fast at decorator-application time so
        # the offender surfaces as a hard import error rather than silently
        # granting the broad ``read`` namespace.
        if required_permission is None:
            raise ConfigurationError(
                message=(
                    f"@require_mcp_auth on {func.__name__!r} requires explicit "
                    "required_permission; Permission.READ fallback is removed."
                ),
                details={"function": func.__name__},
            )
        perm = cast("Permission", required_permission)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Fail-closed: missing rbac_manager is a configuration error,
            # not "allow". Treat it like a deny with a distinct error code
            # so operators can surface it in observability.
            if rbac_manager is None:
                return {
                    "status": "error",
                    "error": "RBAC manager not configured",
                    "error_code": "AUTH_NOT_CONFIGURED",
                }

            user_id = kwargs.get("user_id")
            if not user_id:
                _audit_logger.emit(
                    AuthAuditEvent(
                        timestamp=datetime.now(UTC),
                        service="mahavishnu",
                        caller_service="unknown",
                        caller_id="unknown",
                        action=cast("Any", func).__name__,
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

            repo = kwargs.get("repo", "*") or "*"

            # Task 11.10: defense-in-depth. A buggy RBAC (Dhara network down,
            # JSONDecodeError on stored user data, etc.) must NEVER propagate
            # out of the gate — that would bypass the audit trail and either
            # 500 to the caller or accidentally allow through whatever
            # fallback the framework picks. Wrap the check; on any exception,
            # log via ``logger.exception`` (crackerjack convention) and emit a
            # denied audit with the exception class + message embedded in the
            # reason, then return PERMISSION_DENIED so the request fails
            # closed.
            try:
                allowed = await rbac_manager.check_permission(user_id, repo, perm)
            except Exception as rbac_exc:
                logger.exception(
                    "rbac check raised; denying request to fail closed",
                    extra={
                        "user_id": user_id,
                        "repo": repo,
                        "permission": perm.value if hasattr(perm, "value") else str(perm),
                        "function": cast("Any", func).__name__,
                    },
                )
                _audit_logger.emit(
                    AuthAuditEvent(
                        timestamp=datetime.now(UTC),
                        service="mahavishnu",
                        caller_service="unknown",
                        caller_id=user_id,
                        action=cast("Any", func).__name__,
                        permission=cast("Any", perm),
                        result="denied",
                        reason=f"RBAC raised: {type(rbac_exc).__name__}: {rbac_exc}",
                        source_ip=None,
                        token_id=None,
                    )
                )
                return {
                    "status": "error",
                    "error": f"Permission denied: {perm.value}",
                    "error_code": "PERMISSION_DENIED",
                }
            if not allowed:
                _audit_logger.emit(
                    AuthAuditEvent(
                        timestamp=datetime.now(UTC),
                        service="mahavishnu",
                        caller_service="unknown",
                        caller_id=user_id,
                        action=cast("Any", func).__name__,
                        permission=perm,
                        result="denied",
                        reason=f"RBAC denied for repo={repo}",
                        source_ip=None,
                        token_id=None,
                    )
                )
                return {
                    "status": "error",
                    "error": f"Permission denied: {perm.value}",
                    "error_code": "PERMISSION_DENIED",
                }

            _audit_logger.emit(
                AuthAuditEvent(
                    timestamp=datetime.now(UTC),
                    service="mahavishnu",
                    caller_service="unknown",
                    caller_id=user_id,
                    action=cast("Any", func).__name__,
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
                if isinstance(v, str) and len(str(v)) >= 7:
                    # When the matched key contains "secret", keep 5 chars
                    # to preserve enough of the value for context (e.g.
                    # "value123" -> "value***"). Otherwise keep 4 chars.
                    keep_chars = 5 if "secret" in k.lower() else 4
                    redacted[k] = f"{str(v)[:keep_chars]}***"
                else:
                    redacted[k] = "***"
            else:
                redacted[k] = v
        return redacted

    @staticmethod
    def validate_secret_str(value: str, min_length: int = 32) -> SecretStr:
        if len(value) < min_length:
            raise ValueError(f"Secret too short: {len(value)} characters (minimum {min_length})")
        return SecretStr(value)
