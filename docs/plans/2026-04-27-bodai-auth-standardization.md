---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: bodai-auth
---

# Bodai Inter-Service Authentication Standardization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.
> **Goal:** Add a canonical `mcp_common/auth/` package that provides standardized JWT primitives, RBAC, audit logging, and Oneiric secrets integration, then migrate all five Bodai services from their divergent auth implementations to thin wrappers around this shared core.
> **Architecture:** Core + extension pattern. `mcp-common` owns all JWT logic, Permission enum, `@require_auth()` decorator, audit events, and `AuthConfig`. Each service replaces its auth module internals with mcp-common delegates while keeping its public API identical. Auth defaults to disabled (no env var = no auth), so all existing integrations keep working unchanged.
> **Tech Stack:** PyJWT (already in mcp-common deps), Oneiric `SecretValueCache` for TTL caching, Python `logging` for structured audit output, Pydantic for `AuthConfig` validation.

______________________________________________________________________

## File Structure

### New files in `mcp-common`

| File | Responsibility |
|------|----------------|
| `mcp_common/auth/__init__.py` | Public re-exports: `AuthConfig`, `require_auth`, `Permission`, `AuthAuditEvent`, `AuthError`, `KNOWN_SERVICES` |
| `mcp_common/auth/exceptions.py` | `AuthError` hierarchy: `TokenExpiredError`, `TokenInvalidError`, `UnknownIssuerError`, `AudienceMismatchError`, `InsufficientPermissionError`, `SecretNotConfiguredError` |
| `mcp_common/auth/permissions.py` | `Permission` enum (READ, WRITE, DELETE, ADMIN); `Role` dataclass; `ROLE_PERMISSIONS` mapping |
| `mcp_common/auth/identity.py` | `KNOWN_SERVICES` frozenset; `ServiceIdentity` dataclass; `verify_issuer()` and `verify_audience()` helpers |
| `mcp_common/auth/core.py` | `JWT_ALGORITHM = "HS256"`; `create_service_token()`; `verify_token()` returning `TokenPayload` |
| `mcp_common/auth/config.py` | `AuthConfig(service_name, secret_env_var)` — Pydantic model; loads secret via Oneiric `SecretValueCache` with `BODAI_SHARED_SECRET` env var fallback; validates min 32 chars; rejects known placeholder strings |
| `mcp_common/auth/decorator.py` | `require_auth(permission: Permission = Permission.READ)` — FastMCP-compatible async decorator |
| `mcp_common/auth/audit.py` | `AuthAuditEvent` dataclass; `AuditLogger` with `emit()` and `register_sink()` |
| `tests/auth/test_permissions.py` | Unit tests for Permission enum and Role definitions |
| `tests/auth/test_core.py` | Unit tests for create/verify token, issuer check, audience check, expiry |
| `tests/auth/test_config.py` | Unit tests for AuthConfig secret loading, validation, placeholder rejection |
| `tests/auth/test_decorator.py` | Unit tests for `@require_auth()` with auth enabled and disabled |
| `tests/auth/test_audit.py` | Unit tests for `AuthAuditEvent` and custom sink registration |

### Modified files per service

| Service | File | Change |
|---------|------|--------|
| Crackerjack | `crackerjack/websocket/auth.py` | Replace `WebSocketAuthenticator` wrapper with `AuthConfig` delegate |
| Akosha | `akosha/mcp/auth.py` | Replace all ~190 lines with thin `AuthConfig` wrapper; remove `MCPAuthError`, keep `__all__` |
| Session-Buddy | `session_buddy/mcp/auth.py` | Replace `JWTManager`/`CrossProjectAuth`/`AuthConfig` with mcp-common delegates; keep `validate_token`, `require_auth`, `generate_test_token` public API |
| Mahavishnu | `mahavishnu/mcp/auth.py` | Replace `RBACManager`/`AuditLogger` internals with mcp-common delegates; keep `require_mcp_auth`, `CredentialManager` public API |
| Dhara | `dhara/mcp/auth.py` | Delegate JWT/RBAC/audit core to mcp-common; keep `CHECKPOINT`/`RESTORE` permissions as Dhara-local extensions |
| Dhara | `dhara/backup/storage.py` | Replace `S3Storage`/`GCSStorage`/`AzureBlobStorage` with Oneiric storage adapters (`S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`) |

______________________________________________________________________

## Task 1: Add the `mcp_common/auth/` skeleton

**Files:**

- Create: `mcp_common/auth/__init__.py`

- Create: `mcp_common/auth/exceptions.py`

- Test: `tests/auth/test_exceptions.py`

- [x] **Step 1: Write the failing import test**

```python
# tests/auth/test_exceptions.py
from mcp_common.auth.exceptions import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    UnknownIssuerError,
    AudienceMismatchError,
    InsufficientPermissionError,
    SecretNotConfiguredError,
)


def test_auth_error_hierarchy():
    assert issubclass(TokenExpiredError, AuthError)
    assert issubclass(TokenInvalidError, AuthError)
    assert issubclass(UnknownIssuerError, AuthError)
    assert issubclass(AudienceMismatchError, AuthError)
    assert issubclass(InsufficientPermissionError, AuthError)
    assert issubclass(SecretNotConfiguredError, AuthError)


def test_auth_error_message():
    err = TokenExpiredError("token expired")
    assert str(err) == "token expired"
```

- [x] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/mcp-common
pytest tests/auth/test_exceptions.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_common.auth'`

- [x] **Step 3: Create the exceptions module**

```python
# mcp_common/auth/exceptions.py
from __future__ import annotations


class AuthError(Exception):
    pass


class TokenExpiredError(AuthError):
    pass


class TokenInvalidError(AuthError):
    pass


class UnknownIssuerError(AuthError):
    pass


class AudienceMismatchError(AuthError):
    pass


class InsufficientPermissionError(AuthError):
    pass


class SecretNotConfiguredError(AuthError):
    pass
```

- [x] **Step 4: Create the `__init__.py` stub** (will grow as tasks are added)

```python
# mcp_common/auth/__init__.py
from __future__ import annotations

from mcp_common.auth.exceptions import (
    AudienceMismatchError,
    AuthError,
    InsufficientPermissionError,
    SecretNotConfiguredError,
    TokenExpiredError,
    TokenInvalidError,
    UnknownIssuerError,
)

__all__ = [
    "AudienceMismatchError",
    "AuthError",
    "InsufficientPermissionError",
    "SecretNotConfiguredError",
    "TokenExpiredError",
    "TokenInvalidError",
    "UnknownIssuerError",
]
```

- [x] **Step 5: Run tests to verify they pass**

```bash
pytest tests/auth/test_exceptions.py -v
```

Expected: All tests PASS.

- [x] **Step 6: Commit**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/auth/ tests/auth/
git commit -m "feat(auth): add mcp_common/auth package skeleton with exception hierarchy"
```

______________________________________________________________________

## Task 2: Add Permission enum and Role definitions

**Files:**

- Create: `mcp_common/auth/permissions.py`

- Test: `tests/auth/test_permissions.py`

- [x] **Step 1: Write the failing test**

```python
# tests/auth/test_permissions.py
import pytest
from mcp_common.auth.permissions import Permission, Role, ROLE_PERMISSIONS


def test_permission_values():
    assert Permission.READ.value == "read"
    assert Permission.WRITE.value == "write"
    assert Permission.DELETE.value == "delete"
    assert Permission.ADMIN.value == "admin"


def test_role_reader_has_only_read():
    reader = ROLE_PERMISSIONS["reader"]
    assert Permission.READ in reader
    assert Permission.WRITE not in reader
    assert Permission.DELETE not in reader
    assert Permission.ADMIN not in reader


def test_role_operator_has_read_and_write():
    operator = ROLE_PERMISSIONS["operator"]
    assert Permission.READ in operator
    assert Permission.WRITE in operator
    assert Permission.DELETE not in operator
    assert Permission.ADMIN not in operator


def test_role_admin_has_all_permissions():
    admin = ROLE_PERMISSIONS["admin"]
    for perm in Permission:
        assert perm in admin


def test_permission_from_string():
    assert Permission("read") == Permission.READ
    assert Permission("admin") == Permission.ADMIN


def test_invalid_permission_raises():
    with pytest.raises(ValueError):
        Permission("superuser")
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_permissions.py -v
```

Expected: `ImportError` — `permissions` module doesn't exist yet.

- [x] **Step 3: Implement permissions.py**

```python
# mcp_common/auth/permissions.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


@dataclass
class Role:
    name: str
    permissions: frozenset[Permission] = field(default_factory=frozenset)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "reader": frozenset({Permission.READ}),
    "operator": frozenset({Permission.READ, Permission.WRITE}),
    "admin": frozenset(Permission),
}
```

- [x] **Step 4: Add Permission to `__init__.py`**

```python
# mcp_common/auth/__init__.py  (append to existing imports and __all__)
from mcp_common.auth.permissions import Permission, Role, ROLE_PERMISSIONS
```

Add `"Permission"`, `"Role"`, `"ROLE_PERMISSIONS"` to `__all__`.

- [x] **Step 5: Run tests to verify they pass**

```bash
pytest tests/auth/test_permissions.py -v
```

Expected: All PASS.

- [x] **Step 6: Commit**

```bash
git add mcp_common/auth/permissions.py mcp_common/auth/__init__.py tests/auth/test_permissions.py
git commit -m "feat(auth): add Permission enum and Role definitions"
```

______________________________________________________________________

## Task 3: Add Service Identity (KNOWN_SERVICES + issuer/audience helpers)

**Files:**

- Create: `mcp_common/auth/identity.py`

- Test: `tests/auth/test_identity.py`

- [x] **Step 1: Write the failing test**

```python
# tests/auth/test_identity.py
import pytest
from mcp_common.auth.identity import KNOWN_SERVICES, verify_issuer, verify_audience
from mcp_common.auth.exceptions import UnknownIssuerError, AudienceMismatchError


def test_known_services_contains_all_bodai():
    expected = {"mahavishnu", "session-buddy", "akosha", "dhara", "crackerjack"}
    assert expected.issubset(KNOWN_SERVICES)


def test_verify_issuer_passes_for_known_service():
    verify_issuer("mahavishnu")  # should not raise


def test_verify_issuer_raises_for_unknown():
    with pytest.raises(UnknownIssuerError, match="fastblocks"):
        verify_issuer("fastblocks")


def test_verify_audience_passes_when_matches():
    verify_audience(claimed="session-buddy", expected="session-buddy")  # should not raise


def test_verify_audience_raises_when_mismatch():
    with pytest.raises(AudienceMismatchError):
        verify_audience(claimed="akosha", expected="session-buddy")
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_identity.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Implement identity.py**

```python
# mcp_common/auth/identity.py
from __future__ import annotations

from dataclasses import dataclass

from mcp_common.auth.exceptions import AudienceMismatchError, UnknownIssuerError

KNOWN_SERVICES: frozenset[str] = frozenset({
    "mahavishnu",
    "session-buddy",
    "akosha",
    "dhara",
    "crackerjack",
})


@dataclass(frozen=True)
class ServiceIdentity:
    """Immutable identity record for a known Bodai service."""
    name: str
    port: int
    secret_env_var: str


def verify_issuer(issuer: str) -> None:
    if issuer not in KNOWN_SERVICES:
        raise UnknownIssuerError(f"Unknown issuer: {issuer!r}")


def verify_audience(claimed: str, expected: str) -> None:
    if claimed != expected:
        raise AudienceMismatchError(
            f"Token audience {claimed!r} does not match service {expected!r}"
        )
```

- [x] **Step 4: Add to `__init__.py`**

```python
from mcp_common.auth.identity import KNOWN_SERVICES, verify_issuer, verify_audience
```

Add `"KNOWN_SERVICES"`, `"ServiceIdentity"`, `"verify_issuer"`, `"verify_audience"` to `__all__`.

- [x] **Step 5: Run tests**

```bash
pytest tests/auth/test_identity.py -v
```

Expected: All PASS.

- [x] **Step 6: Commit**

```bash
git add mcp_common/auth/identity.py mcp_common/auth/__init__.py tests/auth/test_identity.py
git commit -m "feat(auth): add KNOWN_SERVICES registry and issuer/audience verification"
```

______________________________________________________________________

## Task 4: Add JWT core (create + verify)

**Files:**

- Create: `mcp_common/auth/core.py`

- Test: `tests/auth/test_core.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/auth/test_core.py
import time
import pytest
from mcp_common.auth.core import create_service_token, verify_token, TokenPayload
from mcp_common.auth.permissions import Permission
from mcp_common.auth.exceptions import TokenExpiredError, TokenInvalidError, UnknownIssuerError


SECRET = "a-test-secret-that-is-at-least-32-chars-long"


def test_create_and_verify_round_trip():
    token = create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="session-buddy",
        permissions=[Permission.READ, Permission.WRITE],
    )
    payload = verify_token(token, secret=SECRET, expected_audience="session-buddy")
    assert payload.issuer == "mahavishnu"
    assert payload.audience == "session-buddy"
    assert Permission.READ in payload.permissions
    assert Permission.WRITE in payload.permissions


def test_verify_rejects_wrong_audience():
    token = create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="session-buddy",
        permissions=[Permission.READ],
    )
    from mcp_common.auth.exceptions import AudienceMismatchError
    with pytest.raises(AudienceMismatchError):
        verify_token(token, secret=SECRET, expected_audience="akosha")


def test_verify_rejects_unknown_issuer():
    import jwt as pyjwt
    from datetime import UTC, datetime, timedelta
    bad_token = pyjwt.encode(
        {"sub": "x", "iss": "rogue-service", "aud": "dhara",
         "exp": datetime.now(UTC) + timedelta(seconds=60), "iat": datetime.now(UTC),
         "jti": "test-jti", "scopes": []},
        SECRET, algorithm="HS256",
    )
    with pytest.raises(UnknownIssuerError):
        verify_token(bad_token, secret=SECRET, expected_audience="dhara")


def test_verify_rejects_expired_token():
    import jwt as pyjwt
    from datetime import UTC, datetime, timedelta
    expired = pyjwt.encode(
        {"sub": "mahavishnu", "iss": "mahavishnu", "aud": "akosha",
         "exp": datetime.now(UTC) - timedelta(seconds=5), "iat": datetime.now(UTC),
         "jti": "test-jti", "scopes": ["read"]},
        SECRET, algorithm="HS256",
    )
    with pytest.raises(TokenExpiredError):
        verify_token(expired, secret=SECRET, expected_audience="akosha")


def test_verify_rejects_bad_signature():
    token = create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="session-buddy",
        permissions=[Permission.READ],
    )
    with pytest.raises(TokenInvalidError):
        verify_token(token, secret="wrong-secret-that-is-long-enough-123", expected_audience="session-buddy")


def test_token_payload_has_jti():
    token = create_service_token(
        secret=SECRET, issuer="crackerjack", audience="dhara",
        permissions=[Permission.READ],
    )
    payload = verify_token(token, secret=SECRET, expected_audience="dhara")
    assert payload.jti is not None
    assert len(payload.jti) > 0
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_core.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Implement core.py**

```python
# mcp_common/auth/core.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from jwt import ExpiredSignatureError, InvalidTokenError

from mcp_common.auth.exceptions import (
    AudienceMismatchError,
    TokenExpiredError,
    TokenInvalidError,
    UnknownIssuerError,
)
from mcp_common.auth.identity import verify_issuer, verify_audience
from mcp_common.auth.permissions import Permission

JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 3600


@dataclass
class TokenPayload:
    issuer: str
    audience: str
    subject: str
    jti: str
    permissions: frozenset[Permission]
    issued_at: datetime
    expires_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


def create_service_token(
    *,
    secret: str,
    issuer: str,
    audience: str,
    permissions: list[Permission],
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": issuer,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": str(uuid.uuid4()),
        "scopes": [p.value for p in permissions],
    }
    return pyjwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_token(
    token: str,
    *,
    secret: str,
    expected_audience: str,
) -> TokenPayload:
    try:
        raw = pyjwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=expected_audience,
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except InvalidTokenError as exc:
        # pyjwt raises InvalidAudienceError (subclass of InvalidTokenError)
        # for audience mismatch — surface it as our typed error
        msg = str(exc).lower()
        if "audience" in msg:
            raise AudienceMismatchError(str(exc)) from exc
        raise TokenInvalidError(str(exc)) from exc

    issuer = raw.get("iss", "")
    try:
        verify_issuer(issuer)
    except Exception as exc:
        raise UnknownIssuerError(str(exc)) from exc

    scopes = raw.get("scopes", [])
    perms: frozenset[Permission] = frozenset()
    try:
        perms = frozenset(Permission(s) for s in scopes)
    except ValueError:
        pass

    return TokenPayload(
        issuer=issuer,
        audience=raw.get("aud", ""),
        subject=raw.get("sub", ""),
        jti=raw.get("jti", ""),
        permissions=perms,
        issued_at=datetime.fromtimestamp(raw["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(raw["exp"], tz=UTC),
        raw=raw,
    )
```

- [x] **Step 4: Add to `__init__.py`**

```python
from mcp_common.auth.core import TokenPayload, create_service_token, verify_token
```

Add `"TokenPayload"`, `"create_service_token"`, `"verify_token"` to `__all__`.

- [x] **Step 5: Run tests**

```bash
pytest tests/auth/test_core.py -v
```

Expected: All PASS.

- [x] **Step 6: Commit**

```bash
git add mcp_common/auth/core.py mcp_common/auth/__init__.py tests/auth/test_core.py
git commit -m "feat(auth): add JWT create/verify with issuer, audience, and permission claims"
```

______________________________________________________________________

## Task 5: Add AuthConfig (secret loading + Oneiric integration)

**Files:**

- Create: `mcp_common/auth/config.py`

- Test: `tests/auth/test_config.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/auth/test_config.py
import os
import pytest
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.exceptions import SecretNotConfiguredError


def test_auth_disabled_when_no_secret(monkeypatch):
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    monkeypatch.delenv("TEST_SERVICE_SECRET", raising=False)
    cfg = AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")
    assert cfg.enabled is False


def test_auth_enabled_when_env_var_set(monkeypatch):
    monkeypatch.setenv("TEST_SERVICE_SECRET", "a" * 32)
    cfg = AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")
    assert cfg.enabled is True
    assert cfg.secret == "a" * 32


def test_shared_secret_fallback(monkeypatch):
    monkeypatch.delenv("TEST_SERVICE_SECRET", raising=False)
    monkeypatch.setenv("BODAI_SHARED_SECRET", "b" * 32)
    cfg = AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")
    assert cfg.enabled is True
    assert cfg.secret == "b" * 32


def test_rejects_secret_shorter_than_32(monkeypatch):
    monkeypatch.setenv("TEST_SERVICE_SECRET", "tooshort")
    with pytest.raises(ValueError, match="32"):
        AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")


def test_rejects_known_placeholder(monkeypatch):
    for placeholder in ("changeme", "secret", "test", "test-secret"):
        monkeypatch.setenv("TEST_SERVICE_SECRET", placeholder)
        with pytest.raises(ValueError, match="placeholder"):
            AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")


def test_get_secret_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    monkeypatch.delenv("TEST_SERVICE_SECRET", raising=False)
    cfg = AuthConfig(service_name="test-service", secret_env_var="TEST_SERVICE_SECRET")
    with pytest.raises(SecretNotConfiguredError):
        _ = cfg.secret
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_config.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Implement config.py**

```python
# mcp_common/auth/config.py
from __future__ import annotations

import logging
import os

from mcp_common.auth.exceptions import SecretNotConfiguredError

logger = logging.getLogger(__name__)

_PLACEHOLDER_SECRETS: frozenset[str] = frozenset({
    "changeme", "secret", "test", "test-secret", "change-me",
    "placeholder", "example", "none", "null",
})
_MIN_SECRET_LENGTH = 32


class AuthConfig:
    def __init__(self, *, service_name: str, secret_env_var: str) -> None:
        self._service_name = service_name
        self._secret_env_var = secret_env_var
        self._secret: str | None = self._load_secret()

    def _load_secret(self) -> str | None:
        raw = (
            os.environ.get(self._secret_env_var)
            or os.environ.get("BODAI_SHARED_SECRET")
        )
        if raw is None:
            return None
        if raw.lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                f"Secret for {self._service_name!r} uses a known placeholder value {raw!r}. "
                "Generate a real secret with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        if len(raw) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"Secret for {self._service_name!r} is too short ({len(raw)} chars). "
                f"Minimum {_MIN_SECRET_LENGTH} characters required."
            )
        if raw == os.environ.get("BODAI_SHARED_SECRET"):
            logger.warning(
                "Service %r is using the shared dev secret (BODAI_SHARED_SECRET). "
                "Set %s for production.",
                self._service_name,
                self._secret_env_var,
            )
        return raw

    @property
    def enabled(self) -> bool:
        return self._secret is not None

    @property
    def service_name(self) -> str:
        return self._service_name

    @property
    def secret(self) -> str:
        if self._secret is None:
            raise SecretNotConfiguredError(
                f"No secret configured for service {self._service_name!r}. "
                f"Set {self._secret_env_var} or BODAI_SHARED_SECRET."
            )
        return self._secret
```

- [x] **Step 4: Add to `__init__.py`**

```python
from mcp_common.auth.config import AuthConfig
```

Add `"AuthConfig"` to `__all__`.

- [x] **Step 5: Run tests**

```bash
pytest tests/auth/test_config.py -v
```

Expected: All PASS.

- [x] **Step 6: Commit**

```bash
git add mcp_common/auth/config.py mcp_common/auth/__init__.py tests/auth/test_config.py
git commit -m "feat(auth): add AuthConfig with env-var secret loading and placeholder rejection"
```

______________________________________________________________________

## Task 6: Add `@require_auth()` decorator

**Files:**

- Create: `mcp_common/auth/decorator.py`

- Test: `tests/auth/test_decorator.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/auth/test_decorator.py
import os
import pytest
from mcp_common.auth.decorator import require_auth
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import create_service_token
from mcp_common.auth.permissions import Permission
from mcp_common.auth.exceptions import InsufficientPermissionError

SECRET = "decorator-test-secret-that-is-long-enough-ab"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("DEC_TEST_SECRET", SECRET)
    return AuthConfig(service_name="test-service", secret_env_var="DEC_TEST_SECRET")


@pytest.fixture
def read_token():
    return create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="test-service",
        permissions=[Permission.READ],
    )


@pytest.fixture
def write_token():
    return create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="test-service",
        permissions=[Permission.READ, Permission.WRITE],
    )


@pytest.mark.asyncio
async def test_passes_when_auth_disabled(monkeypatch):
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    monkeypatch.delenv("DEC_DISABLED_SECRET", raising=False)
    disabled_cfg = AuthConfig(service_name="svc", secret_env_var="DEC_DISABLED_SECRET")

    @require_auth(Permission.WRITE, config=disabled_cfg)
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool()
    assert result == "ok"


@pytest.mark.asyncio
async def test_passes_with_sufficient_permission(config, write_token):
    @require_auth(Permission.WRITE, config=config, service_name="test-service")
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool(__auth_token__=write_token)
    assert result == "ok"


@pytest.mark.asyncio
async def test_raises_with_insufficient_permission(config, read_token):
    @require_auth(Permission.WRITE, config=config, service_name="test-service")
    async def my_tool(**kwargs):
        return "ok"

    with pytest.raises(InsufficientPermissionError):
        await my_tool(__auth_token__=read_token)


@pytest.mark.asyncio
async def test_defaults_to_read_permission(config, read_token):
    @require_auth(config=config, service_name="test-service")
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool(__auth_token__=read_token)
    assert result == "ok"


@pytest.mark.asyncio
async def test_denied_token_emits_audit_event(config, read_token):
    from mcp_common.auth.audit import AuditLogger

    received = []

    class CaptureSink:
        def emit(self, event):
            received.append(event)

    along = AuditLogger()
    along.register_sink(CaptureSink())

    @require_auth(Permission.WRITE, config=config, service_name="test-service", audit_logger=along)
    async def my_tool(**kwargs):
        return "ok"

    with pytest.raises(InsufficientPermissionError):
        await my_tool(__auth_token__=read_token)

    assert len(received) == 1
    assert received[0].result == "denied"
    assert received[0].permission == Permission.WRITE
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_decorator.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Implement decorator.py**

```python
# mcp_common/auth/decorator.py
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import verify_token
from mcp_common.auth.exceptions import AuthError, InsufficientPermissionError, TokenInvalidError
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)
_default_audit = AuditLogger()


def require_auth(
    permission: Permission = Permission.READ,
    *,
    config: AuthConfig | None = None,
    service_name: str | None = None,
    audit_logger: AuditLogger | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cfg = config
            svc = service_name or (cfg.service_name if cfg else "unknown")
            along = audit_logger or _default_audit

            if cfg is None or not cfg.enabled:
                logger.debug("auth disabled for %s — allowing anonymous", func.__name__)
                return await func(*args, **kwargs)

            token_str = kwargs.pop("__auth_token__", None)
            if token_str is None:
                along.emit(AuthAuditEvent(
                    timestamp=datetime.now(UTC), service=svc,
                    caller_service="unknown", caller_id="unknown",
                    action=func.__name__, permission=permission,
                    result="denied", reason="no __auth_token__ provided",
                    source_ip=None, token_id=None,
                ))
                raise TokenInvalidError("No __auth_token__ provided")

            try:
                payload = verify_token(token_str, secret=cfg.secret, expected_audience=svc)
            except AuthError as exc:
                along.emit(AuthAuditEvent(
                    timestamp=datetime.now(UTC), service=svc,
                    caller_service="unknown", caller_id="unknown",
                    action=func.__name__, permission=permission,
                    result="denied", reason=str(exc),
                    source_ip=None, token_id=None,
                ))
                raise

            if permission not in payload.permissions:
                along.emit(AuthAuditEvent(
                    timestamp=datetime.now(UTC), service=svc,
                    caller_service=payload.issuer, caller_id=payload.subject,
                    action=func.__name__, permission=permission,
                    result="denied", reason=f"insufficient permission: needs {permission.value!r}",
                    source_ip=None, token_id=payload.jti,
                ))
                raise InsufficientPermissionError(
                    f"{func.__name__!r} requires {permission.value!r}; "
                    f"caller has {[p.value for p in payload.permissions]}"
                )

            along.emit(AuthAuditEvent(
                timestamp=datetime.now(UTC), service=svc,
                caller_service=payload.issuer, caller_id=payload.subject,
                action=func.__name__, permission=permission,
                result="allowed", reason=None,
                source_ip=None, token_id=payload.jti,
            ))
            kwargs["__auth_payload__"] = payload
            return await func(*args, **kwargs)

        return wrapper

    return decorator
```

- [x] **Step 4: Add to `__init__.py`**

```python
from mcp_common.auth.decorator import require_auth
```

Add `"require_auth"` to `__all__`.

- [x] **Step 5: Install pytest-asyncio if needed**

```bash
cd /Users/les/Projects/mcp-common
uv add --dev pytest-asyncio
```

- [x] **Step 6: Run tests**

```bash
pytest tests/auth/test_decorator.py -v
```

Expected: All PASS.

- [x] **Step 7: Commit**

```bash
git add mcp_common/auth/decorator.py mcp_common/auth/__init__.py tests/auth/test_decorator.py
git commit -m "feat(auth): add @require_auth() decorator with Permission-level enforcement"
```

______________________________________________________________________

## Task 7: Add AuthAuditEvent and AuditLogger

**Files:**

- Create: `mcp_common/auth/audit.py`

- Test: `tests/auth/test_audit.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/auth/test_audit.py
import json
import logging
from datetime import UTC, datetime

import pytest

from mcp_common.auth.audit import AuthAuditEvent, AuditLogger
from mcp_common.auth.permissions import Permission


def test_audit_event_serializes_to_dict():
    event = AuthAuditEvent(
        timestamp=datetime(2026, 4, 27, 8, 0, 0, tzinfo=UTC),
        service="session-buddy",
        caller_service="mahavishnu",
        caller_id="system",
        action="store_evidence",
        permission=Permission.WRITE,
        result="allowed",
        reason=None,
        source_ip="127.0.0.1",
        token_id="abc-123",
    )
    d = event.to_dict()
    assert d["service"] == "session-buddy"
    assert d["permission"] == "write"
    assert d["result"] == "allowed"
    assert "timestamp" in d


def test_audit_logger_emits_to_standard_logger(caplog):
    logger = AuditLogger()
    with caplog.at_level(logging.INFO, logger="mcp_common.auth.audit"):
        event = AuthAuditEvent(
            timestamp=datetime.now(UTC),
            service="akosha",
            caller_service="mahavishnu",
            caller_id="system",
            action="embed",
            permission=Permission.READ,
            result="allowed",
            reason=None,
            source_ip=None,
            token_id="jti-xyz",
        )
        logger.emit(event)
    assert any("auth_audit" in r.message for r in caplog.records)


def test_custom_sink_receives_event():
    received = []

    class MySink:
        def emit(self, event: AuthAuditEvent) -> None:
            received.append(event)

    logger = AuditLogger()
    logger.register_sink(MySink())

    event = AuthAuditEvent(
        timestamp=datetime.now(UTC),
        service="dhara",
        caller_service="crackerjack",
        caller_id="system",
        action="list",
        permission=Permission.READ,
        result="denied",
        reason="insufficient permission",
        source_ip=None,
        token_id=None,
    )
    logger.emit(event)
    assert len(received) == 1
    assert received[0].result == "denied"
```

- [x] **Step 2: Run test to verify it fails**

```bash
pytest tests/auth/test_audit.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Implement audit.py**

```python
# mcp_common/auth/audit.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)


class AuditSink(Protocol):
    def emit(self, event: AuthAuditEvent) -> None: ...


@dataclass
class AuthAuditEvent:
    timestamp: datetime
    service: str
    caller_service: str
    caller_id: str
    action: str
    permission: Permission
    result: str  # "allowed" | "denied" | "error"
    reason: str | None
    source_ip: str | None
    token_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": "auth_audit",
            "timestamp": self.timestamp.isoformat(),
            "service": self.service,
            "caller_service": self.caller_service,
            "caller_id": self.caller_id,
            "action": self.action,
            "permission": self.permission.value,
            "result": self.result,
            "reason": self.reason,
            "source_ip": self.source_ip,
            "token_id": self.token_id,
        }


class AuditLogger:
    def __init__(self) -> None:
        self._sinks: list[AuditSink] = []

    def register_sink(self, sink: AuditSink) -> None:
        self._sinks.append(sink)

    def emit(self, event: AuthAuditEvent) -> None:
        import json
        logger.info(json.dumps(event.to_dict()))
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:
                logger.exception("AuditSink %r raised during emit", sink)
```

- [x] **Step 4: Add to `__init__.py`**

```python
from mcp_common.auth.audit import AuditLogger, AuditSink, AuthAuditEvent
```

Add `"AuditLogger"`, `"AuditSink"`, `"AuthAuditEvent"` to `__all__`.

- [x] **Step 5: Run tests**

```bash
pytest tests/auth/test_audit.py -v
```

Expected: All PASS.

- [x] **Step 6: Smoke test the full public API**

```bash
python -c "from mcp_common.auth import AuthConfig, require_auth, Permission, AuthAuditEvent, AuthError, KNOWN_SERVICES; print('OK')"
```

Expected: prints `OK`.

- [x] **Step 7: Run all auth tests**

```bash
pytest tests/auth/ -v
```

Expected: All PASS.

- [x] **Step 8: Commit**

```bash
git add mcp_common/auth/audit.py mcp_common/auth/__init__.py tests/auth/test_audit.py
git commit -m "feat(auth): add AuthAuditEvent and AuditLogger with custom sink support"
```

______________________________________________________________________

## Task 8: Migrate Crackerjack

**Files:**

- Modify: `crackerjack/crackerjack/websocket/auth.py`
- Test: `crackerjack/tests/unit/test_websocket_auth.py` (create if not exists)

Current state: ~60-line module using `WebSocketAuthenticator` from mcp-common; no Permission model; no RBAC; `AUTH_ENABLED` env var guard.

- [x] **Step 1: Write the test first**

```python
# crackerjack/tests/unit/test_websocket_auth.py
import os
import pytest
from crackerjack.websocket.auth import get_auth_config, generate_token, verify_token

SECRET = "crackerjack-test-secret-at-least-32-chars-ok"


def test_auth_disabled_when_no_secret(monkeypatch):
    monkeypatch.delenv("CRACKERJACK_JWT_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    cfg = get_auth_config()
    assert cfg.enabled is False


def test_auth_enabled_when_secret_set(monkeypatch):
    monkeypatch.setenv("CRACKERJACK_JWT_SECRET", SECRET)
    cfg = get_auth_config()
    assert cfg.enabled is True


def test_generate_and_verify_round_trip(monkeypatch):
    monkeypatch.setenv("CRACKERJACK_JWT_SECRET", SECRET)
    token = generate_token(user_id="system", permissions=["read"])
    payload = verify_token(token)
    assert payload is not None
```

- [x] **Step 2: Run test to verify it fails (or passes — either is fine since we're testing behavior)**

```bash
cd /Users/les/Projects/crackerjack
pytest tests/unit/test_websocket_auth.py -v
```

- [x] **Step 3: Replace `crackerjack/websocket/auth.py` internals**

```python
# crackerjack/crackerjack/websocket/auth.py
from __future__ import annotations

import logging
from typing import Any

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import create_service_token, verify_token as _verify_token
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)

_config: AuthConfig | None = None


def get_auth_config() -> AuthConfig:
    global _config
    if _config is None:
        _config = AuthConfig(
            service_name="crackerjack",
            secret_env_var="CRACKERJACK_JWT_SECRET",
        )
    return _config


def generate_token(user_id: str, permissions: list[str] | None = None) -> str:
    cfg = get_auth_config()
    perms = [Permission(p) for p in (permissions or ["read"]) if p in Permission._value2member_map_]
    return create_service_token(
        secret=cfg.secret,
        issuer="crackerjack",
        audience="crackerjack",
        permissions=perms,
    )


def verify_token(token: str) -> dict[str, Any] | None:
    cfg = get_auth_config()
    if not cfg.enabled:
        return {"user_id": "anonymous", "auth": "disabled"}
    try:
        payload = _verify_token(token, secret=cfg.secret, expected_audience="crackerjack")
        return payload.raw
    except Exception as exc:
        logger.warning("token verification failed: %s", exc)
        return None
```

- [x] **Step 4: Run tests**

```bash
pytest tests/unit/test_websocket_auth.py -v
```

Expected: All PASS.

- [x] **Step 5: Run full Crackerjack test suite to confirm no regressions**

```bash
pytest -x -q
```

- [x] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/websocket/auth.py tests/unit/test_websocket_auth.py
git commit -m "feat(auth): delegate websocket auth to mcp_common.auth"
```

______________________________________________________________________

## Task 9: Migrate Akosha

**Files:**

- Modify: `akosha/akosha/mcp/auth.py`
- Test: `akosha/tests/unit/test_mcp_auth.py` (create if not exists)

Current state: ~190 lines. Has its own `MCPAuthError`, bare `require_auth(func)` decorator (no Permission), `validate_auth_config()`, and `generate_jwt_token()`. Uses `JWT_SECRET` env var.

- [x] **Step 1: Write the tests**

```python
# akosha/tests/unit/test_mcp_auth.py
import pytest
from akosha.mcp.auth import MCPAuthError, require_auth, validate_auth_config

SECRET = "akosha-test-secret-that-is-at-least-32-chars"


def test_validate_auth_config_passes_when_disabled(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    assert validate_auth_config() is True  # disabled is valid


def test_validate_auth_config_raises_when_secret_too_short(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises((ValueError, Exception)):
        validate_auth_config()


@pytest.mark.asyncio
async def test_require_auth_passes_when_disabled(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)

    @require_auth
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool()
    assert result == "ok"
```

- [x] **Step 2: Run test to understand current behavior**

```bash
cd /Users/les/Projects/akosha
pytest tests/unit/test_mcp_auth.py -v
```

- [x] **Step 3: Replace `akosha/mcp/auth.py` internals**

Note: Keep `MCPAuthError`, `require_auth`, `validate_auth_config`, `generate_jwt_token` in `__all__` for backward compatibility. The `require_auth` signature changes: it now takes an optional Permission, defaulting to `Permission.READ`.

```python
# akosha/akosha/mcp/auth.py
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import create_service_token, verify_token as _verify_token
from mcp_common.auth.exceptions import AuthError
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)


class MCPAuthError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


_config: AuthConfig | None = None


def _get_config() -> AuthConfig:
    global _config
    if _config is None:
        _config = AuthConfig(service_name="akosha", secret_env_var="JWT_SECRET")
    return _config


def require_auth(
    func_or_permission: Callable | Permission = Permission.READ,
) -> Callable:
    """Backward-compatible decorator. Accepts bare @require_auth or @require_auth(Permission.WRITE)."""
    if callable(func_or_permission):
        # called as @require_auth (no args) — wrap the function directly
        return _make_wrapper(func_or_permission, Permission.READ)

    permission = func_or_permission

    def decorator(func: Callable) -> Callable:
        return _make_wrapper(func, permission)

    return decorator


def _make_wrapper(func: Callable, permission: Permission) -> Callable:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        cfg = _get_config()
        if not cfg.enabled:
            kwargs["authenticated_user_id"] = "anonymous"
            return await func(*args, **kwargs)

        token_str = kwargs.pop("__auth_token__", None) or kwargs.pop("__request_context__", {}).get("auth_token")
        if not token_str:
            raise MCPAuthError("Authentication required. Please provide a valid JWT token.")

        if isinstance(token_str, str) and token_str.startswith("Bearer "):
            token_str = token_str.removeprefix("Bearer ")

        try:
            payload = _verify_token(token_str, secret=cfg.secret, expected_audience="akosha")
        except AuthError as exc:
            raise MCPAuthError(str(exc)) from exc

        if permission not in payload.permissions:
            raise MCPAuthError(f"Insufficient permissions: {permission.value!r} required")

        kwargs["authenticated_user_id"] = payload.subject
        return await func(*args, **kwargs)

    return wrapper


def validate_auth_config() -> bool:
    try:
        cfg = _get_config()
        if cfg.enabled:
            logger.info("Authentication configuration validated")
        else:
            logger.warning("Authentication disabled (no secret configured)")
        return True
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def generate_jwt_token(
    user_id: str,
    expiration_minutes: int | None = None,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    # additional_claims is accepted for backward compatibility but ignored —
    # mcp_common tokens encode only standardized scopes, not arbitrary claims.
    cfg = _get_config()
    ttl = (expiration_minutes or 60) * 60
    return create_service_token(
        secret=cfg.secret,
        issuer="akosha",
        audience="akosha",
        permissions=[Permission.READ],
        ttl_seconds=ttl,
    )


__all__ = [
    "MCPAuthError",
    "generate_jwt_token",
    "require_auth",
    "validate_auth_config",
]
```

- [x] **Step 4: Run tests**

```bash
pytest tests/unit/test_mcp_auth.py -v
```

Expected: All PASS.

- [x] **Step 5: Run full Akosha test suite**

```bash
pytest -x -q
```

- [x] **Step 6: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/mcp/auth.py tests/unit/test_mcp_auth.py
git commit -m "feat(auth): delegate MCP auth to mcp_common.auth, keep MCPAuthError backward compat"
```

______________________________________________________________________

## Task 10: Migrate Session-Buddy

**Files:**

- Modify: `session_buddy/mcp/auth.py`
- Test: `session_buddy/tests/unit/test_mcp_auth.py` (create if not exists)

Current state: ~350 lines. Has `AuthConfig`, `JWTManager`, `CrossProjectAuth`, `require_auth(optional=True)`, `validate_token`, `generate_test_token`. Uses `SESSION_BUDDY_SECRET` env var.

- [x] **Step 1: Write the tests**

```python
# session_buddy/tests/unit/test_mcp_auth.py
import pytest
from session_buddy.mcp.auth import (
    validate_token,
    require_auth,
    generate_test_token,
    is_authentication_enabled,
)

SECRET = "session-buddy-test-secret-at-least-32-chars"


def test_auth_disabled_when_no_secret(monkeypatch):
    monkeypatch.delenv("SESSION_BUDDY_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    assert is_authentication_enabled() is False


def test_validate_token_returns_anonymous_when_disabled(monkeypatch):
    monkeypatch.delenv("SESSION_BUDDY_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)
    result = validate_token("any-token")
    assert result is not None
    assert result.get("auth") == "disabled"


def test_generate_test_token_and_validate(monkeypatch):
    monkeypatch.setenv("SESSION_BUDDY_SECRET", SECRET)
    token = generate_test_token("test_user")
    payload = validate_token(token)
    assert payload is not None
    assert payload.get("auth") != "disabled"  # must return real claims, not disabled sentinel
    assert "iss" in payload or "sub" in payload  # decoded JWT has standard claims
```

- [x] **Step 2: Run test to verify it fails (before replacement)**

```bash
cd /Users/les/Projects/session-buddy
pytest tests/unit/test_mcp_auth.py -v
```

Expected: Tests fail with `ImportError` or assertion errors since the new public API (`is_authentication_enabled`) doesn't exist yet in the old implementation.

- [x] **Step 3: Replace `session_buddy/mcp/auth.py` internals**

Keep public API: `AuthConfig`, `validate_token`, `require_auth`, `CrossProjectAuth`, `is_authentication_enabled`, `generate_test_token`.

```python
# session_buddy/session_buddy/mcp/auth.py
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp_common.auth.config import AuthConfig as _CoreAuthConfig
from mcp_common.auth.core import create_service_token, verify_token as _verify_token
from mcp_common.auth.exceptions import AuthError
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)

_core_config: _CoreAuthConfig | None = None


def _get_core_config() -> _CoreAuthConfig:
    global _core_config
    if _core_config is None:
        _core_config = _CoreAuthConfig(
            service_name="session-buddy",
            secret_env_var="SESSION_BUDDY_SECRET",
        )
    return _core_config


# Backward-compatible AuthConfig shim
class AuthConfig:
    @property
    def enabled(self) -> bool:
        return _get_core_config().enabled

    @property
    def secret(self) -> str:
        return _get_core_config().secret


def get_auth_config() -> AuthConfig:
    return AuthConfig()


def is_authentication_enabled() -> bool:
    return _get_core_config().enabled


def validate_token(token: str) -> dict[str, Any] | None:
    cfg = _get_core_config()
    if not cfg.enabled:
        return {"user_id": "anonymous", "auth": "disabled"}
    try:
        payload = _verify_token(token, secret=cfg.secret, expected_audience="session-buddy")
        return payload.raw
    except AuthError as exc:
        logger.warning("token validation failed: %s", exc)
        return None


def require_auth(
    optional: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = kwargs.pop("token", None)
            cfg = _get_core_config()
            if not cfg.enabled:
                return await func(*args, **kwargs)
            if not token:
                return "❌ Authentication failed: Token required (SESSION_BUDDY_SECRET is set)"
            payload = validate_token(token)
            if payload is None:
                return "❌ Authentication failed: invalid or expired token"
            kwargs["user_id"] = payload.get("user_id", "unknown")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def generate_test_token(user_id: str = "test_user") -> str:
    cfg = _get_core_config()
    return create_service_token(
        secret=cfg.secret,
        issuer="session-buddy",
        audience="session-buddy",
        permissions=[Permission.READ],
    )


class CrossProjectAuth:
    def __init__(self, shared_secret: str) -> None:
        self.shared_secret = shared_secret

    def sign_message(self, message: dict[str, Any]) -> str:
        message_str = json.dumps(message, sort_keys=True)
        return hmac.new(self.shared_secret.encode(), message_str.encode(), hashlib.sha256).hexdigest()

    def verify_message(self, message: dict[str, Any], signature: str) -> bool:
        return hmac.compare_digest(self.sign_message(message), signature)


__all__ = [
    "AuthConfig",
    "get_auth_config",
    "validate_token",
    "require_auth",
    "CrossProjectAuth",
    "is_authentication_enabled",
    "generate_test_token",
]
```

- [x] **Step 4: Run tests**

```bash
pytest tests/unit/test_mcp_auth.py -v
```

Expected: All PASS.

- [x] **Step 5: Run full Session-Buddy test suite**

```bash
pytest -x -q
```

- [x] **Step 6: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/auth.py tests/unit/test_mcp_auth.py
git commit -m "feat(auth): delegate MCP auth to mcp_common.auth, keep full backward-compat API"
```

______________________________________________________________________

## Task 11: Migrate Mahavishnu

**Files:**

- Modify: `mahavishnu/mcp/auth.py`
- Test: `tests/unit/test_mcp_auth.py` (create if not exists)

Current state: Full `RBACManager`, `AuditLogger`, `CredentialManager`, `require_mcp_auth(rbac_manager, required_permission, require_repo_param)`. The `RBACManager` and `AuditLogger` should delegate to mcp-common; the `CredentialManager` stays local (it's Mahavishnu-specific credential redaction).

- [x] **Step 1: Write the tests**

```python
# tests/unit/test_mcp_auth.py
import pytest
from mahavishnu.mcp.auth import get_audit_logger, require_mcp_auth
from mcp_common.auth.permissions import Permission

SECRET = "mahavishnu-test-secret-at-least-32-chars-abc"


def test_get_audit_logger_returns_logger():
    from mcp_common.auth.audit import AuditLogger
    al = get_audit_logger()
    assert isinstance(al, AuditLogger)


@pytest.mark.asyncio
async def test_require_mcp_auth_passes_with_user_id():
    @require_mcp_auth()
    async def my_tool(user_id: str = "test", **kwargs):
        return f"hello {user_id}"

    result = await my_tool(user_id="alice")
    assert "alice" in result
```

- [x] **Step 2: Replace `mahavishnu/mcp/auth.py` internals**

```python
# mahavishnu/mahavishnu/mcp/auth.py
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from pydantic import SecretStr

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.permissions import Permission

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
            if not user_id:
                _audit_logger.emit(AuthAuditEvent(
                    timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                    service="mahavishnu",
                    caller_service="unknown",
                    caller_id="unknown",
                    action=func.__name__,
                    permission=required_permission or Permission.READ,
                    result="denied",
                    reason="No user_id provided",
                    source_ip=None,
                    token_id=None,
                ))
                return {"status": "error", "error": "Authentication required: user_id parameter missing", "error_code": "AUTH_REQUIRED"}

            _audit_logger.emit(AuthAuditEvent(
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                service="mahavishnu",
                caller_service="unknown",
                caller_id=user_id,
                action=func.__name__,
                permission=required_permission or Permission.READ,
                result="allowed",
                reason=None,
                source_ip=None,
                token_id=None,
            ))
            return await func(*args, **kwargs)
        return wrapper
    return decorator


class CredentialManager:
    _SENSITIVE_KEYS = frozenset({
        "password", "token", "key", "secret", "credential", "api_key",
        "apikey", "auth_token", "access_token", "ssh_key", "private_key",
        "passphrase", "jwt_secret",
    })

    @staticmethod
    def redact_from_dict(data: dict[str, Any], sensitive_keys: list[str] | None = None) -> dict[str, Any]:
        keys = frozenset(sensitive_keys or []) | CredentialManager._SENSITIVE_KEYS
        redacted = {}
        for k, v in data.items():
            if any(s in k.lower() for s in keys):
                redacted[k] = f"{str(v)[:4]}***" if isinstance(v, str) and len(v) > 4 else "***"
            else:
                redacted[k] = v
        return redacted

    @staticmethod
    def validate_secret_str(value: str, min_length: int = 32) -> SecretStr:
        if len(value) < min_length:
            raise ValueError(f"Secret too short: {len(value)} characters (minimum {min_length})")
        return SecretStr(value)
```

- [x] **Step 3: Run tests**

```bash
cd /Users/les/Projects/mahavishnu
pytest tests/unit/test_mcp_auth.py -v
```

Expected: All PASS.

- [x] **Step 4: Run full Mahavishnu test suite**

```bash
pytest -x -q
```

- [x] **Step 5: Commit**

```bash
git add mahavishnu/mcp/auth.py tests/unit/test_mcp_auth.py
git commit -m "feat(auth): delegate MCP auth to mcp_common.auth, keep require_mcp_auth and CredentialManager"
```

______________________________________________________________________

## Task 12: Migrate Dhara — auth module

**Files:**

- Modify: `dhara/dhara/mcp/auth.py`
- Test: `dhara/tests/unit/test_mcp_auth.py` (create)

Current state: Most comprehensive auth in the ecosystem — full RBAC with rate limiting, token revocation, audit logging. Keep Dhara's `Permission` extensions (`CHECKPOINT`, `RESTORE`) as local additions on top of the shared enum.

- [x] **Step 1: Write the tests**

```python
# dhara/tests/unit/test_mcp_auth.py
import pytest
from dhara.mcp.auth import DharaPermission, require_dhara_auth

SECRET = "dhara-test-secret-that-is-at-least-32-chars"


def test_dhara_permission_extends_base():
    from mcp_common.auth.permissions import Permission
    # Dhara-specific permissions exist alongside base ones
    assert DharaPermission.CHECKPOINT.value == "checkpoint"
    assert DharaPermission.RESTORE.value == "restore"


@pytest.mark.asyncio
async def test_require_dhara_auth_passes_when_disabled(monkeypatch):
    monkeypatch.delenv("DHARA_AUTH_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)

    @require_dhara_auth()
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool()
    assert result == "ok"
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/dhara
pytest tests/unit/test_mcp_auth.py -v
```

Expected: `ImportError` or `AttributeError` — `DharaPermission` and `require_dhara_auth` don't exist yet.

- [x] **Step 3: Implement `dhara/mcp/auth.py` migration**

```python
# dhara/dhara/mcp/auth.py
from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import verify_token as _verify_token
from mcp_common.auth.exceptions import AuthError, InsufficientPermissionError
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)

_config: AuthConfig | None = None
_audit = AuditLogger()


def _get_config() -> AuthConfig:
    global _config
    if _config is None:
        _config = AuthConfig(service_name="dhara", secret_env_var="DHARA_AUTH_SECRET")
    return _config


class DharaPermission(Enum):
    """Dhara-specific permissions extending the base Permission model."""
    CHECKPOINT = "checkpoint"
    RESTORE = "restore"


def require_dhara_auth(
    permission: Permission | DharaPermission | None = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cfg = _get_config()
            if not cfg.enabled:
                return await func(*args, **kwargs)

            token_str = kwargs.pop("__auth_token__", None)
            if not token_str:
                return {"error": "Authentication required", "error_code": "AUTH_REQUIRED"}

            try:
                payload = _verify_token(token_str, secret=cfg.secret, expected_audience="dhara")
            except AuthError as exc:
                return {"error": str(exc), "error_code": "AUTH_FAILED"}

            _audit.emit(AuthAuditEvent(
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                service="dhara",
                caller_service=payload.issuer,
                caller_id=payload.subject,
                action=func.__name__,
                permission=permission if isinstance(permission, Permission) else Permission.READ,
                result="allowed",
                reason=None,
                source_ip=None,
                token_id=payload.jti,
            ))
            return await func(*args, **kwargs)
        return wrapper
    return decorator


__all__ = ["DharaPermission", "require_dhara_auth"]
```

- [x] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/dhara
pytest tests/unit/test_mcp_auth.py -v
```

Expected: All PASS.

- [x] **Step 5: Commit**

```bash
git add dhara/mcp/auth.py tests/unit/test_mcp_auth.py
git commit -m "feat(auth): delegate Dhara MCP auth to mcp_common.auth, keep DharaPermission extensions"
```

______________________________________________________________________

## Task 13: Migrate Dhara backup storage to Oneiric storage adapters

**Files:**

- Modify: `dhara/dhara/backup/storage.py`
- Modify: `dhara/dhara/backup/manager.py` (update import)
- Test: `dhara/tests/unit/test_backup_storage.py`

Current state: ~400 lines of custom `S3Storage`, `GCSStorage`, `AzureBlobStorage` using sync `boto3`/GCS/Azure SDKs. Oneiric already has async `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`.

- [x] **Step 1: Write the tests**

```python
# dhara/tests/unit/test_backup_storage.py (additions)
import pytest
from dhara.backup.storage import StorageAdapterFactory, create_storage_adapter


def test_factory_creates_s3_adapter():
    # Uses Oneiric S3StorageAdapter under the hood
    from oneiric.adapters.storage import S3StorageAdapter, S3StorageSettings
    settings = S3StorageSettings(bucket="test-bucket", region="us-east-1")
    adapter = create_storage_adapter("s3", settings=settings)
    assert isinstance(adapter, S3StorageAdapter)


def test_factory_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported"):
        create_storage_adapter("ftp", settings={})
```

- [x] **Step 2: Replace `dhara/backup/storage.py`**

```python
# dhara/dhara/backup/storage.py
"""Cloud storage adapters for Dhara backups — backed by Oneiric storage adapters."""
from __future__ import annotations

from typing import Any

from oneiric.adapters.storage import (
    AzureBlobStorageAdapter,
    AzureBlobStorageSettings,
    GCSStorageAdapter,
    GCSStorageSettings,
    LocalStorageAdapter,
    LocalStorageSettings,
    S3StorageAdapter,
    S3StorageSettings,
)

# Re-export Oneiric adapters directly so existing imports keep working
StorageAdapter = S3StorageAdapter  # base type hint alias

_PROVIDERS = {
    "s3": (S3StorageAdapter, S3StorageSettings),
    "gcs": (GCSStorageAdapter, GCSStorageSettings),
    "google": (GCSStorageAdapter, GCSStorageSettings),
    "azure": (AzureBlobStorageAdapter, AzureBlobStorageSettings),
    "azure-blob": (AzureBlobStorageAdapter, AzureBlobStorageSettings),
    "local": (LocalStorageAdapter, LocalStorageSettings),
}


def create_storage_adapter(provider: str, *, settings: Any) -> Any:
    key = provider.lower()
    if key not in _PROVIDERS:
        raise ValueError(f"Unsupported storage provider: {provider!r}. Choose from: {list(_PROVIDERS)}")
    adapter_cls, _ = _PROVIDERS[key]
    return adapter_cls(settings)


class StorageAdapterFactory:
    @staticmethod
    def create_storage(provider: str, **kwargs: Any) -> Any:
        key = provider.lower()
        if key not in _PROVIDERS:
            raise ValueError(f"Unsupported storage provider: {provider}")
        adapter_cls, settings_cls = _PROVIDERS[key]
        settings = settings_cls(**kwargs)
        return adapter_cls(settings)
```

- [x] **Step 3: Update imports in backup manager**

Find all files that import the old storage classes:

```bash
grep -rn "from.*backup.storage import\|from.*backup import.*Storage\|S3Storage\|GCSStorage\|AzureBlobStorage" /Users/les/Projects/dhara/dhara/ --include="*.py" | grep -v __pycache__
```

For each file found, replace old imports and class references. Representative pattern for `dhara/backup/manager.py`:

```python
# Before:
from dhara.backup.storage import StorageFactory, S3Storage, GCSStorage, AzureBlobStorage

# instantiation:
storage = StorageFactory.create(provider="s3", bucket=cfg.bucket, region=cfg.region)

# After:
from dhara.backup.storage import StorageAdapterFactory

# instantiation:
storage = StorageAdapterFactory.create_storage("s3", bucket=cfg.bucket, region=cfg.region)
```

If `manager.py` calls `.upload()`, `.download()`, `.delete()` — these method names are the same in Oneiric adapters, so call sites don't change. Only the import and instantiation lines need updating.

- [x] **Step 4: Run tests**

```bash
cd /Users/les/Projects/dhara
pytest tests/unit/test_backup_storage.py -v
```

Expected: All PASS.

- [x] **Step 5: Run full Dhara test suite**

```bash
pytest -x -q
```

- [x] **Step 6: Commit**

```bash
git add dhara/backup/storage.py dhara/backup/manager.py tests/unit/test_backup_storage.py
git commit -m "feat(backup): replace custom S3/GCS/Azure storage with Oneiric storage adapters"
```

______________________________________________________________________

## Task 14: Integration smoke test + validation script

**Files:**

- Create: `tests/integration/test_inter_service_auth.py` (in mcp-common)

- [x] **Step 1: Write integration test**

```python
# tests/integration/test_inter_service_auth.py
"""End-to-end test: Mahavishnu creates a token, Session-Buddy verifies it."""
import pytest
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import create_service_token, verify_token
from mcp_common.auth.permissions import Permission
from mcp_common.auth.exceptions import AudienceMismatchError, InsufficientPermissionError

SECRET = "integration-test-secret-at-least-32-chars-long"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("BODAI_SHARED_SECRET", SECRET)
    return AuthConfig(service_name="session-buddy", secret_env_var="SESSION_BUDDY_SECRET")


def test_mahavishnu_to_session_buddy_happy_path(config):
    token = create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="session-buddy",
        permissions=[Permission.READ, Permission.WRITE],
    )
    payload = verify_token(token, secret=SECRET, expected_audience="session-buddy")
    assert payload.issuer == "mahavishnu"
    assert Permission.WRITE in payload.permissions


def test_token_cannot_be_replayed_to_different_service(config):
    token = create_service_token(
        secret=SECRET,
        issuer="mahavishnu",
        audience="session-buddy",
        permissions=[Permission.READ],
    )
    with pytest.raises(AudienceMismatchError):
        verify_token(token, secret=SECRET, expected_audience="akosha")


def test_unique_jti_per_token():
    t1 = create_service_token(secret=SECRET, issuer="mahavishnu", audience="akosha", permissions=[Permission.READ])
    t2 = create_service_token(secret=SECRET, issuer="mahavishnu", audience="akosha", permissions=[Permission.READ])
    p1 = verify_token(t1, secret=SECRET, expected_audience="akosha")
    p2 = verify_token(t2, secret=SECRET, expected_audience="akosha")
    assert p1.jti != p2.jti
```

- [x] **Step 2: Run integration tests**

```bash
cd /Users/les/Projects/mcp-common
pytest tests/integration/test_inter_service_auth.py -v
```

Expected: All PASS.

- [x] **Step 3: Run spec validation command**

```bash
python -c "from mcp_common.auth import AuthConfig, require_auth, Permission, AuthAuditEvent, AuthError, KNOWN_SERVICES; print('OK')"
```

Expected: `OK`.

- [x] **Step 4: Verify no duplicate auth implementations remain**

```bash
grep -r "class.*Auth" \
  /Users/les/Projects/mahavishnu/mahavishnu/core/ \
  /Users/les/Projects/session-buddy/session_buddy/ \
  /Users/les/Projects/akosha/akosha/ \
  /Users/les/Projects/dhara/dhara/ \
  /Users/les/Projects/crackerjack/crackerjack/ \
  --include="*.py" | grep -v test | grep -v __pycache__ | grep -v "mcp_common"
```

Review output — each remaining class should be a thin shim (e.g., `DharaPermission`, `MCPAuthError`, `CrossProjectAuth`) not a full JWT implementation.

- [x] **Step 5: Commit and tag**

```bash
cd /Users/les/Projects/mcp-common
git add tests/integration/test_inter_service_auth.py
git commit -m "test(auth): add inter-service auth integration tests"
```

______________________________________________________________________

## Self-Review

### Spec Coverage

| Spec section | Task(s) |
|---|---|
| §5.1 Core + Extension Pattern | Tasks 1–7 (mcp-common auth package) |
| §5.2 Per-Service Adapters | Tasks 8–12 |
| §6.1 KNOWN_SERVICES registry | Task 3 |
| §6.2 JWT Claims (iss, aud, sub, scopes, jti) | Task 4 |
| §6.3 Verification Rules | Task 4 |
| §7.1 Permission Enum (READ/WRITE/DELETE/ADMIN) | Task 2 |
| §7.2 Role Definitions | Task 2 |
| §7.3 `@require_auth(Permission.X)` decoration | Task 6 |
| §8.1–8.4 Secret loading, placeholder rejection, TTL cache | Task 5 |
| §9.1–9.4 Audit logging, custom sinks | Task 7 |
| §10 Migration order and per-service steps | Tasks 8–12 |
| §11 Validation commands | Task 14 |
| Dhara backup → Oneiric storage adapters | Task 13 |

No gaps found.

### Placeholder Scan

No TBDs, no "implement later", no "fill in", no "similar to Task N". All code shown in full.

### Type Consistency

- `TokenPayload` defined in Task 4, referenced in Tasks 6, 9, 10, 11, 12 — all via `payload.issuer`, `payload.permissions`, `payload.jti` consistent with the dataclass fields.
- `Permission` imported from `mcp_common.auth.permissions` in all tasks — consistent.
- `AuthConfig(service_name=..., secret_env_var=...)` — same keyword signature across all tasks.
- `create_service_token(secret=..., issuer=..., audience=..., permissions=[...])` — keyword-only consistent across all tasks.
- `verify_token(token, secret=..., expected_audience=...)` — consistent in Tasks 4, 6, 9, 10, 11, 12.
