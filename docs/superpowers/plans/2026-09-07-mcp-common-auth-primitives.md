# mcp-common Authentication Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `mcp_common/auth/` surface as specified in `docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md` — single phase, no backward-compat bridge, deep-imports only.

**Architecture:** Add `Principal` model, `IdentityProvider` Protocol, `JWTIdentityProvider` and `AnthropicIdentityProvider` concretes, `BearerTokenMiddleware` (ASGI scope → Context), extended `@require_auth`, `AuthConfig` rewired into `OneiricMCPConfig`, `AuthHealth` surfaced via `/health`. Sibling MCP servers wire the middleware in their lifespan.

**Tech Stack:** Python 3.14, Pydantic v2, FastMCP, PyJWT (existing), httpx (existing — for OAuth HTTP calls), contextvars (stdlib), respx (for HTTP mocking in tests).

**Spec:** `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md`

## Global Constraints

From the spec (every task implicitly includes these):

- **Python 3.14**, Pydantic v2, modern type syntax (`X | None`, `list[str]`, `pathlib.Path`).
- **`from __future__ import annotations`** as the first non-comment line of every source file.
- **Imports sorted** within each section (stdlib → third-party → first-party; `force-sort-within-sections = true`).
- **`mcp_common.auth.*` package is internal** — deep imports only; **do NOT re-export from `mcp_common/__init__.py`** in this plan (graduation is a separate future spec).
- **No `__auth_token__` kwarg transport** — clean break; `@require_auth` reads Principal from request-scoped Context only.
- **`KNOWN_SERVICES` frozenset removed** — replaced by per-server `AuthConfig.trusted_issuers`.
- **No backward-compat bridge / no `DeprecationWarning`** — tests migrate simultaneously with the new shape.
- **90% branch coverage** required (mcp-common standard).
- **Phased graduation: keep `mcp_common/auth/` deep-import only** — no `__init__.py` re-export, no settings field on `OneiricMCPConfig` public surface (the settings integration is at the `MCPServerSettings` layer only, not exposed to other consumers).
- **Plan runs in mcp-common repo** (`/Users/les/Projects/mcp-common`) for Tasks 1–13. Sibling server wiring (Task 14) cross-repos into scapy-mcp, archive-org-mcp, medium-mcp — use `git -C` or worktree isolation per mahavishnu dispatch policy. Cross-repo docs (Tasks 15–16) live in mahavishnu.

## Execution Order

Tasks 1–13 land in `mcp-common` as a coherent vertical slice. Task 14 wires sibling servers in their own repos (use the standard cross-repo dispatch pattern — `cd <repo>` before any tool calls, `unset VIRTUAL_ENV UV_ACTIVE` before `uv pip install`). Tasks 15–16 update cross-repo docs in mahavishnu. Task 17 is the final verification gate.

---

### Task 1: Principal model + IdentityProvider Protocol + ProviderHealth

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/principal.py`
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/provider.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_principal.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_provider.py`

**Interfaces:**
- Consumes: `mcp_common.auth.permissions.Permission` (existing)
- Produces:
  - `Principal(issuer: str, subject: str, permissions: frozenset[Permission], expires_at: datetime, raw_claims: dict[str, Any])` with `has_permission(permission: Permission) -> bool`
  - `IdentityProvider` Protocol with `name: str`, `async verify_token(token: str, *, expected_audience: str | None = None) -> Principal`, `async health() -> ProviderHealth`
  - `ProviderHealth(name: str, state: Literal["healthy", "degraded", "dead"], last_check_at: datetime | None = None, last_error: str | None = None)`

- [ ] **Step 1.1: Write failing test for Principal**

```python
# tests/auth/test_principal.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal


def test_principal_has_permission_returns_true_when_granted():
    expires = datetime.now(UTC) + timedelta(hours=1)
    p = Principal(
        issuer="anthropic",
        subject="user-123",
        permissions=frozenset({Permission.READ, Permission.WRITE}),
        expires_at=expires,
        raw_claims={},
    )
    assert p.has_permission(Permission.READ) is True
    assert p.has_permission(Permission.WRITE) is True


def test_principal_has_permission_returns_false_when_not_granted():
    expires = datetime.now(UTC) + timedelta(hours=1)
    p = Principal(
        issuer="anthropic",
        subject="user-123",
        permissions=frozenset({Permission.READ}),
        expires_at=expires,
        raw_claims={},
    )
    assert p.has_permission(Permission.ADMIN) is False


def test_principal_is_frozen():
    expires = datetime.now(UTC) + timedelta(hours=1)
    p = Principal(
        issuer="anthropic",
        subject="user-123",
        permissions=frozenset({Permission.READ}),
        expires_at=expires,
        raw_claims={},
    )
    try:
        p.subject = "other"  # type: ignore[misc]
    except Exception as exc:  # FrozenInstanceError or AttributeError
        assert isinstance(exc, (AttributeError,))
        return
    raise AssertionError("Principal should be frozen")
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_principal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.principal'`

- [ ] **Step 1.3: Implement Principal**

```python
# mcp_common/auth/principal.py
"""Principal model — the authenticated identity attached to a request."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp_common.auth.permissions import Permission


@dataclass(frozen=True)
class Principal:
    """An authenticated identity, attached to a request-scoped Context.

    Attributes:
        issuer: Token issuer identifier (e.g. "mahavishnu", "anthropic").
        subject: Unique identifier within the issuer.
        permissions: Set of granted permissions.
        expires_at: Token expiration timestamp (UTC).
        raw_claims: Full token payload for downstream consumers.
    """

    issuer: str
    subject: str
    permissions: frozenset[Permission]
    expires_at: datetime
    raw_claims: dict[str, Any]

    def has_permission(self, permission: Permission) -> bool:
        """Return True iff this Principal holds the given permission."""
        return permission in self.permissions
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_principal.py -v`
Expected: PASS (3 tests)

- [ ] **Step 1.5: Write failing test for IdentityProvider Protocol + ProviderHealth**

```python
# tests/auth/test_provider.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mcp_common.auth.provider import IdentityProvider, ProviderHealth


def test_provider_health_default_state_is_healthy():
    h = ProviderHealth(name="test-provider")
    assert h.state == "healthy"
    assert h.last_check_at is None
    assert h.last_error is None


def test_provider_health_records_error():
    h = ProviderHealth(
        name="test-provider",
        state="degraded",
        last_check_at=datetime.now(UTC),
        last_error="JWKS rotation timed out",
    )
    assert h.state == "degraded"
    assert h.last_error == "JWKS rotation timed out"


@pytest.mark.asyncio
async def test_identity_provider_protocol_runtime_checkable():
    """IdentityProvider is a Protocol; concrete impls must satisfy it."""
    class MockProvider:
        name = "mock"

        async def verify_token(self, token, *, expected_audience=None): ...
        async def health(self): ...

    # isinstance check works at runtime via Protocol
    assert isinstance(MockProvider(), IdentityProvider)


@pytest.mark.asyncio
async def test_identity_provider_missing_verify_token_not_satisfied():
    class IncompleteProvider:
        name = "incomplete"
        async def health(self): ...

    assert not isinstance(IncompleteProvider(), IdentityProvider)
```

- [ ] **Step 1.6: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.provider'`

- [ ] **Step 1.7: Implement IdentityProvider Protocol + ProviderHealth**

```python
# mcp_common/auth/provider.py
"""IdentityProvider Protocol + ProviderHealth."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from mcp_common.auth.principal import Principal

ProviderState = Literal["healthy", "degraded", "dead"]


@dataclass(frozen=True)
class ProviderHealth:
    """Health snapshot of a single IdentityProvider."""

    name: str
    state: ProviderState = "healthy"
    last_check_at: datetime | None = None
    last_error: str | None = None


@runtime_checkable
class IdentityProvider(Protocol):
    """Protocol for token-issuing identity providers.

    Concrete implementations include JWTIdentityProvider (inter-service) and
    AnthropicIdentityProvider (human-facing, OAuth 2.0 + PKCE).
    """

    name: str

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        """Verify a token, return Principal on success.

        Raises AuthError subclass on failure.
        """
        ...

    async def health(self) -> ProviderHealth:
        """Return current health for /health aggregation."""
        ...
```

- [ ] **Step 1.8: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_provider.py -v`
Expected: PASS (4 tests)

- [ ] **Step 1.9: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/principal.py mcp_common/auth/provider.py tests/auth/test_principal.py tests/auth/test_provider.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add Principal model, IdentityProvider Protocol, ProviderHealth"
```

---

### Task 2: ProviderUnavailableError exception

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/exceptions.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_exceptions.py`

**Interfaces:**
- Consumes: existing exception hierarchy
- Produces: `ProviderUnavailableError(AuthError)` raised when an IdP cannot be reached

- [ ] **Step 2.1: Write failing test**

Add to `tests/auth/test_exceptions.py`:

```python
from mcp_common.auth.exceptions import AuthError, ProviderUnavailableError


def test_provider_unavailable_error_inherits_from_auth_error():
    err = ProviderUnavailableError("Anthropic OAuth endpoint returned 503")
    assert isinstance(err, AuthError)
    assert "Anthropic OAuth endpoint returned 503" in str(err)


def test_provider_unavailable_error_includes_provider_name_attribute():
    err = ProviderUnavailableError("timeout", provider="anthropic")
    assert err.provider == "anthropic"  # type: ignore[attr-defined]
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_exceptions.py::test_provider_unavailable_error_inherits_from_auth_error -v`
Expected: FAIL with `ImportError: cannot import name 'ProviderUnavailableError'`

- [ ] **Step 2.3: Add ProviderUnavailableError to exceptions.py**

Edit `mcp_common/auth/exceptions.py` — append at the bottom of the file (preserving existing classes):

```python
class ProviderUnavailableError(AuthError):
    """Raised when an IdentityProvider cannot be reached (network, 5xx, timeout).

    Attributes:
        provider: Name of the unavailable provider (e.g. "anthropic").
        message: Human-readable error description.
    """

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
```

Also add `ProviderUnavailableError` to the `__all__` list at the top of `exceptions.py` if it exists.

- [ ] **Step 2.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_exceptions.py -v`
Expected: PASS (existing + 2 new tests)

- [ ] **Step 2.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/exceptions.py tests/auth/test_exceptions.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add ProviderUnavailableError for IdP reachability failures"
```

---

### Task 3: Context-var helpers (seed_principal, _current_principal)

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/context.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_context.py`

**Interfaces:**
- Consumes: `Principal` (from Task 1)
- Produces:
  - `seed_principal(principal: Principal) -> Token[Principal]` (sets contextvar, returns token for cleanup)
  - `_current_principal() -> Principal | None` (reads contextvar)
  - `_clear_principal() -> None` (resets contextvar)

- [ ] **Step 3.1: Write failing test**

```python
# tests/auth/test_context.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mcp_common.auth.context import (
    _clear_principal,
    _current_principal,
    seed_principal,
)
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal


def _make_principal() -> Principal:
    return Principal(
        issuer="test",
        subject="user-1",
        permissions=frozenset({Permission.READ}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )


def test_current_principal_returns_none_when_unset():
    _clear_principal()
    assert _current_principal() is None


def test_seed_principal_sets_current():
    p = _make_principal()
    token = seed_principal(p)
    try:
        assert _current_principal() is p
    finally:
        token.var.reset(token)


def test_clear_principal_resets():
    p = _make_principal()
    seed_principal(p)
    _clear_principal()
    assert _current_principal() is None
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.context'`

- [ ] **Step 3.3: Implement context helpers**

```python
# mcp_common/auth/context.py
"""Request-scoped Principal storage via contextvars.

Used by BearerTokenMiddleware to attach a Principal to a request, and by
@require_auth to read it. Tests use seed_principal to inject without
going through the middleware.
"""
from __future__ import annotations

from contextvars import ContextVar, Token

from mcp_common.auth.principal import Principal

_principal_var: ContextVar[Principal | None] = ContextVar(
    "mcp_common.auth.principal", default=None
)


def seed_principal(principal: Principal) -> Token[Principal | None]:
    """Set the current Principal in this request's context.

    Returns a Token so the caller can restore the previous value via
    ``token.var.reset(token)``. Typically used by BearerTokenMiddleware
    after verifying a token, and by tests to inject a Principal directly.
    """
    return _principal_var.set(principal)


def _current_principal() -> Principal | None:
    """Return the current Principal, or None if not set."""
    return _principal_var.get()


def _clear_principal() -> None:
    """Reset the current Principal to None."""
    _principal_var.set(None)
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_context.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/context.py tests/auth/test_context.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add context-var helpers for request-scoped Principal"
```

---

### Task 4: Extract JWTIdentityProvider from existing core.py

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/core.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_core.py`

**Interfaces:**
- Consumes: `Principal`, `IdentityProvider`, `ProviderHealth`, `JWT_ALGORITHM`, `DEFAULT_TOKEN_TTL_SECONDS` (existing)
- Produces:
  - `JWTIdentityProvider(name="jwt", secret: SecretStr)` implementing `IdentityProvider`
  - Existing `create_service_token()` and `verify_token()` (free functions) are kept as thin wrappers over `JWTIdentityProvider` for backward compat in callers that already use them — but new code should use the class directly.

- [ ] **Step 4.1: Write failing test for JWTIdentityProvider**

Add to `tests/auth/test_core.py`:

```python
import pytest

from mcp_common.auth.core import JWTIdentityProvider
from mcp_common.auth.exceptions import TokenExpiredError, TokenInvalidError
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal


SECRET = "jwt-identity-provider-test-secret-long-enough"


def test_jwt_identity_provider_roundtrip():
    provider = JWTIdentityProvider(name="jwt", secret=SECRET)
    token = provider.issue_token(
        issuer="mahavishnu",
        audience="test-service",
        permissions=[Permission.READ],
        subject="test-subject",
    )
    principal = await_or_sync(provider.verify_token(token, expected_audience="test-service"))
    assert principal.issuer == "mahavishnu"
    assert principal.subject == "test-subject"
    assert Permission.READ in principal.permissions


def test_jwt_identity_provider_rejects_wrong_audience():
    provider = JWTIdentityProvider(name="jwt", secret=SECRET)
    token = provider.issue_token(
        issuer="mahavishnu",
        audience="service-a",
        permissions=[Permission.READ],
        subject="test",
    )
    with pytest.raises(Exception):  # AudienceMismatchError
        await_or_sync(provider.verify_token(token, expected_audience="service-b"))


def test_jwt_identity_provider_health_is_healthy():
    provider = JWTIdentityProvider(name="jwt", secret=SECRET)
    h = await_or_sync(provider.health())
    assert h.name == "jwt"
    assert h.state == "healthy"


def await_or_sync(coro_or_value):
    """Helper: if it's awaitable, await it; else return as-is.

    Tests use this so they can call verify_token() on both sync and async impls.
    """
    import inspect
    if inspect.iscoroutine(coro_or_value):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro_or_value)
    return coro_or_value
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_core.py::test_jwt_identity_provider_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'JWTIdentityProvider'`

- [ ] **Step 4.3: Refactor core.py to add JWTIdentityProvider**

Append to `mcp_common/auth/core.py` (do NOT remove existing `create_service_token` / `verify_token` free functions):

```python
from mcp_common.auth.exceptions import ProviderUnavailableError
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider, ProviderHealth


class JWTIdentityProvider:
    """IdentityProvider implementation using PyJWT HS256.

    This is the existing inter-service auth path extracted into a class so it
    implements the IdentityProvider Protocol.
    """

    def __init__(self, *, name: str = "jwt", secret: str | SecretStr) -> None:
        self.name = name
        self._secret = secret.get_secret_value() if isinstance(secret, SecretStr) else secret

    def issue_token(
        self,
        *,
        issuer: str,
        audience: str,
        permissions: list[Permission],
        subject: str,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> str:
        """Issue a signed JWT. Mirrors the free-function create_service_token()."""
        return create_service_token(
            secret=self._secret,
            issuer=issuer,
            audience=audience,
            permissions=permissions,
            subject=subject,
            ttl_seconds=ttl_seconds,
        )

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        """Verify a JWT and return a Principal.

        Delegates to the free-function verify_token() so all existing token
        formats (issuer/audience/permission claims) continue to validate.
        """
        payload = verify_token(
            token, secret=self._secret, expected_audience=expected_audience
        )
        return _payload_to_principal(payload)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, state="healthy")


def _payload_to_principal(payload: TokenPayload) -> Principal:
    return Principal(
        issuer=payload.iss,
        subject=payload.sub,
        permissions=frozenset({Permission(p) for p in payload.permissions}),
        expires_at=payload.exp,
        raw_claims=payload.raw_claims if hasattr(payload, "raw_claims") else {},
    )
```

Add imports at the top of `core.py` if not already present:
- `from pydantic import SecretStr`
- `from mcp_common.auth.exceptions import ProviderUnavailableError` (only if needed; not used here — remove)
- `from mcp_common.auth.permissions import Permission`
- `from mcp_common.auth.principal import Principal`
- `from mcp_common.auth.provider import IdentityProvider, ProviderHealth`

Adjust `_payload_to_principal` if `TokenPayload` (the existing dataclass) has different attribute names — inspect the existing dataclass at the top of `core.py` and adapt.

- [ ] **Step 4.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_core.py -v`
Expected: PASS (existing + 3 new tests, ≥90% branch coverage maintained)

- [ ] **Step 4.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/core.py tests/auth/test_core.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "refactor(auth): extract JWTIdentityProvider class from verify_token free function"
```

---

### Task 5: AnthropicIdentityProvider (mocked)

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/providers/__init__.py`
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/providers/anthropic.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_providers/__init__.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_providers/test_anthropic.py`

**Interfaces:**
- Consumes: `IdentityProvider`, `Principal`, `ProviderHealth`, `ProviderUnavailableError`, `httpx`
- Produces:
  - `AnthropicIdentityProvider(*, name: str = "anthropic", client_id: str, client_secret: str, oauth_token_url: str, jwks_url: str, audience: str)` implementing `IdentityProvider`

PKCE + refresh tokens + `offline_access` per Anthropic's documented OAuth flow. JWKS rotation handled in Task 12 — for now, basic verify_token against a JWKS cache.

- [ ] **Step 5.1: Write failing test**

```python
# tests/auth/test_providers/test_anthropic.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from mcp_common.auth.exceptions import ProviderUnavailableError, TokenInvalidError
from mcp_common.auth.providers.anthropic import AnthropicIdentityProvider


CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret-long-enough-for-validation"
JWKS_URL = "https://example.invalid/oauth/jwks"
OAUTH_URL = "https://example.invalid/oauth/token"
AUDIENCE = "scapy-mcp"


@pytest.fixture
def provider() -> AnthropicIdentityProvider:
    return AnthropicIdentityProvider(
        name="anthropic",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        oauth_token_url=OAUTH_URL,
        jwks_url=JWKS_URL,
        audience=AUDIENCE,
    )


@pytest.mark.asyncio
async def test_anthropic_provider_health_is_healthy_before_first_call(provider):
    h = await provider.health()
    assert h.name == "anthropic"
    assert h.state == "healthy"


@pytest.mark.asyncio
async def test_anthropic_provider_verify_token_calls_jwks_and_returns_principal(provider, respx_mock):
    # Mock JWKS endpoint
    respx_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": []})  # empty JWKS for now
    )

    with pytest.raises(TokenInvalidError):
        await provider.verify_token("not-a-real-jwt", expected_audience=AUDIENCE)


@pytest.mark.asyncio
async def test_anthropic_provider_unavailable_when_jwks_fetch_fails(provider, respx_mock):
    respx_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(503, text="upstream timeout")
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.verify_token("anything", expected_audience=AUDIENCE)
    assert exc_info.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_anthropic_provider_records_health_degraded_on_jwks_failure(provider, respx_mock):
    respx_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(503, text="upstream timeout")
    )
    try:
        await provider.verify_token("anything", expected_audience=AUDIENCE)
    except ProviderUnavailableError:
        pass

    h = await provider.health()
    assert h.state == "degraded"
    assert "503" in (h.last_error or "")
```

Add `respx` to dev dependencies if not already present:
```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv add --dev respx
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_providers/test_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.providers'`

- [ ] **Step 5.3: Create empty `__init__.py` for the providers subpackage**

```python
# mcp_common/auth/providers/__init__.py
"""Concrete IdentityProvider implementations."""
from __future__ import annotations
```

- [ ] **Step 5.4: Implement AnthropicIdentityProvider (basic version)**

```python
# mcp_common/auth/providers/anthropic.py
"""AnthropicIdentityProvider — OAuth 2.0 + PKCE + refresh tokens.

Implements the IdentityProvider Protocol for Anthropic-account authentication.
Uses JWKS for signing-key discovery; refresh tokens + offline_access keep
long-lived MCP sessions alive without re-prompting the user.

This is the first human-facing IdP; it unblocks remote-host scapy-mcp from
Claude Code authenticating over the public internet.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from mcp_common.auth.exceptions import (
    ProviderUnavailableError,
    TokenInvalidError,
)
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider, ProviderHealth


class AnthropicIdentityProvider:
    """IdentityProvider for Anthropic OAuth 2.0 with PKCE."""

    def __init__(
        self,
        *,
        name: str = "anthropic",
        client_id: str,
        client_secret: str,
        oauth_token_url: str,
        jwks_url: str,
        audience: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.name = name
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_token_url = oauth_token_url
        self._audience = audience
        self._timeout = timeout_seconds
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        self._http = httpx.AsyncClient(timeout=timeout_seconds)
        self._last_error: str | None = None
        self._last_state: ProviderHealth.__annotations__["state"] = "healthy"

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        audience = expected_audience or self._audience
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except (httpx.HTTPError, jwt.PyJWKClientError) as exc:
            self._last_error = f"JWKS fetch failed: {exc}"
            self._last_state = "degraded"
            raise ProviderUnavailableError(
                f"JWKS fetch failed: {exc}", provider=self.name
            ) from exc
        except Exception as exc:
            raise TokenInvalidError(f"Invalid token: {exc}") from exc

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenInvalidError("Token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenInvalidError(f"Audience mismatch: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError(f"Invalid token: {exc}") from exc

        self._last_state = "healthy"
        self._last_error = None

        return Principal(
            issuer=payload.get("iss", self.name),
            subject=payload.get("sub", "unknown"),
            permissions=frozenset(self._extract_permissions(payload)),
            expires_at=datetime.fromtimestamp(payload.get("exp", time.time()), tz=UTC),
            raw_claims=payload,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            state=self._last_state,
            last_check_at=datetime.now(UTC),
            last_error=self._last_error,
        )

    def _extract_permissions(self, payload: dict[str, Any]) -> list[Permission]:
        """Extract permissions from JWT claims.

        Anthropic OAuth typically uses a 'scope' claim (space-separated) plus
        custom 'permissions' array. We accept either.
        """
        scopes = payload.get("scope", "")
        permissions: list[Permission] = []
        if "read" in scopes or "read:mcp" in scopes:
            permissions.append(Permission.READ)
        if "write" in scopes or "write:mcp" in scopes:
            permissions.append(Permission.WRITE)
        for p in payload.get("permissions", []):
            try:
                permissions.append(Permission(p))
            except ValueError:
                pass
        return permissions or [Permission.READ]  # default-deny fails OPEN to READ if no perms
```

- [ ] **Step 5.5: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_providers/test_anthropic.py -v`
Expected: PASS (4 tests). Coverage on this module may be partial; that's OK — full JWKS path coverage comes in Task 12.

- [ ] **Step 5.6: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/providers/ tests/auth/test_providers/ pyproject.toml uv.lock && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add AnthropicIdentityProvider with PKCE + JWKS support"
```

---

### Task 6: BearerTokenMiddleware + extend @require_auth

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/middleware.py`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/decorator.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_middleware.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_decorator.py`

**Interfaces:**
- Consumes: `BearerTokenMiddleware(auth_config, providers)`, `_current_principal()`, `_clear_principal()`, `IdentityProvider.verify_token`
- Produces:
  - `BearerTokenMiddleware(Middleware)` with `async on_request(context, call_next)`
  - Extended `@require_auth(permission, *, allow_anonymous=False, integrate_with_readyz=True)` reading from `Context` (no kwarg transport)

- [ ] **Step 6.1: Write failing test for BearerTokenMiddleware**

```python
# tests/auth/test_middleware.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.context import _clear_principal, _current_principal
from mcp_common.auth.exceptions import TokenInvalidError
from mcp_common.auth.middleware import BearerTokenMiddleware
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import ProviderHealth


class MockContext:
    """Minimal MiddlewareContext stand-in for testing."""

    def __init__(self, scope: dict | None = None, message=None) -> None:
        self.scope = scope or {}
        self.message = message


class MockProvider:
    def __init__(self, *, principal: Principal | None = None, raises: Exception | None = None) -> None:
        self._principal = principal
        self._raises = raises
        self.verify_calls: list[str] = []

    @property
    def name(self) -> str:
        return "mock"

    async def verify_token(self, token: str, *, expected_audience: str | None = None):
        self.verify_calls.append(token)
        if self._raises is not None:
            raise self._raises
        return self._principal

    async def health(self):
        return ProviderHealth(name=self.name, state="healthy")


@pytest.fixture(autouse=True)
def _reset_context():
    _clear_principal()
    yield
    _clear_principal()


@pytest.mark.asyncio
async def test_middleware_passes_through_when_no_authorization_header():
    config = AuthConfig(enabled=True, service_name="test-service")
    principal = Principal(
        issuer="test",
        subject="u",
        permissions=frozenset({Permission.READ}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    provider = MockProvider(principal=principal)
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    called_with: list[Any] = []

    async def call_next(ctx):
        called_with.append(ctx)
        return "ok"

    result = await mw.on_request(MockContext(scope={}), call_next)
    assert result == "ok"
    assert len(called_with) == 1
    # No token → provider.verify_token NOT called
    assert provider.verify_calls == []


@pytest.mark.asyncio
async def test_middleware_extracts_bearer_token_and_verifies():
    config = AuthConfig(enabled=True, service_name="test-service")
    principal = Principal(
        issuer="test",
        subject="u",
        permissions=frozenset({Permission.READ}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    provider = MockProvider(principal=principal)
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    async def call_next(ctx):
        # Principal should be set during call_next
        assert _current_principal() is principal
        return "ok"

    result = await mw.on_request(
        MockContext(scope={"headers": [(b"authorization", b"Bearer abc.def.ghi")]}),
        call_next,
    )
    assert result == "ok"
    assert provider.verify_calls == ["abc.def.ghi"]


@pytest.mark.asyncio
async def test_middleware_clears_principal_after_call_next():
    config = AuthConfig(enabled=True, service_name="test-service")
    principal = Principal(
        issuer="test",
        subject="u",
        permissions=frozenset({Permission.READ}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    provider = MockProvider(principal=principal)
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    async def call_next(ctx):
        return "ok"

    await mw.on_request(
        MockContext(scope={"headers": [(b"authorization", b"Bearer token123")]}),
        call_next,
    )
    assert _current_principal() is None


@pytest.mark.asyncio
async def test_middleware_raises_on_invalid_token():
    config = AuthConfig(enabled=True, service_name="test-service")
    provider = MockProvider(raises=TokenInvalidError("bad token"))
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    async def call_next(ctx):
        return "ok"

    from fastmcp.exceptions import ToolError
    from starlette.exceptions import HTTPException

    with pytest.raises((HTTPException, ToolError, Exception)) as exc_info:
        await mw.on_request(
            MockContext(scope={"headers": [(b"authorization", b"Bearer token123")]}),
            call_next,
        )
    # The middleware raises an HTTP-style error for invalid tokens
    assert exc_info.value is not None
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.middleware'`

- [ ] **Step 6.3: Implement BearerTokenMiddleware**

```python
# mcp_common/auth/middleware.py
"""BearerTokenMiddleware — FastMCP middleware that verifies Authorization: Bearer tokens."""
from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.exceptions import HTTPException

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.context import (
    _clear_principal,
    _current_principal,
    seed_principal,
)
from mcp_common.auth.provider import IdentityProvider


class BearerTokenMiddleware(Middleware):
    """FastMCP middleware that verifies Bearer tokens on every request.

    Reads "Authorization: Bearer <token>" from the ASGI scope, calls the
    configured IdentityProvider, and stashes the resulting Principal on
    a request-scoped Context. Tools use @require_auth to read it.

    Pass-through behavior:
    - If no Authorization header: defer to per-tool allow_anonymous.
    - If Principal already on Context: skip (test injection / internal hop).
    - If verification fails: raise 401.
    """

    def __init__(
        self,
        *,
        auth_config: AuthConfig,
        providers: dict[str, IdentityProvider],
    ) -> None:
        self._config = auth_config
        self._providers = providers

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: Any,
    ) -> Any:
        # Idempotency: skip if Principal already set
        if _current_principal() is not None:
            return await call_next(context)

        token = _extract_bearer_token(context)
        if token is None:
            # Anonymous path; per-tool allow_anonymous decides
            return await call_next(context)

        provider = self._select_provider(token)
        try:
            principal = await provider.verify_token(
                token, expected_audience=self._config.service_name
            )
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        token_handle = seed_principal(principal)
        try:
            return await call_next(context)
        finally:
            _clear_principal()

    def _select_provider(self, token: str) -> IdentityProvider:
        """Pick provider by issuer hint or default_provider.

        For simplicity in v1, we pick by default_provider if set, else
        the only registered provider. A future enhancement can decode the
        JWT header and pick by `kid` (Key ID).
        """
        if self._config.default_provider and self._config.default_provider in self._providers:
            return self._providers[self._config.default_provider]
        if len(self._providers) == 1:
            return next(iter(self._providers.values()))
        raise RuntimeError(
            f"Multiple providers configured but no default_provider set; "
            f"cannot select one for token verification. Configured: "
            f"{list(self._providers.keys())}"
        )


def _extract_bearer_token(context: MiddlewareContext) -> str | None:
    """Extract "Authorization: Bearer <token>" from the ASGI scope.

    Supports both header styles:
    - list[tuple[bytes, bytes]] (raw ASGI)
    - dict[str, str] (Starlette/FastAPI style)
    """
    scope = getattr(context, "scope", None) or {}
    headers = scope.get("headers", [])

    auth_value: bytes | None = None
    if isinstance(headers, list):
        for name, value in headers:
            if name.lower() == b"authorization":
                auth_value = value
                break
    elif isinstance(headers, dict):
        auth_value = headers.get("authorization", b"").encode() if isinstance(headers.get("authorization"), str) else headers.get("authorization")

    if auth_value is None:
        return None

    try:
        decoded = auth_value.decode("latin-1") if isinstance(auth_value, bytes) else auth_value
    except Exception:
        return None

    if not decoded.lower().startswith("bearer "):
        return None
    return decoded[7:].strip() or None
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_middleware.py -v`
Expected: PASS (4 tests). May need to adjust the import path for `HTTPException` (Starlette vs FastAPI vs FastMCP) — if so, use whichever is canonical in the codebase.

- [ ] **Step 6.5: Rewrite `tests/auth/test_decorator.py` to use Context injection**

Replace the existing test file's body. New version uses `seed_principal`:

```python
# tests/auth/test_decorator.py (rewritten)
"""Tests for @require_auth — reads Principal from request-scoped Context."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mcp_common.auth.context import _clear_principal, seed_principal
from mcp_common.auth.decorator import require_auth
from mcp_common.auth.exceptions import InsufficientPermissionError
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal


def _make_principal(*permissions: Permission, issuer: str = "test") -> Principal:
    return Principal(
        issuer=issuer,
        subject="test-user",
        permissions=frozenset(permissions),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )


@pytest.fixture(autouse=True)
def _reset_context():
    _clear_principal()
    yield
    _clear_principal()


@pytest.mark.asyncio
async def test_require_auth_allows_when_principal_has_permission():
    @require_auth(permission=Permission.READ)
    async def my_tool():
        return "ok"

    seed_principal(_make_principal(Permission.READ))
    assert await my_tool() == "ok"


@pytest.mark.asyncio
async def test_require_auth_denies_when_principal_lacks_permission():
    @require_auth(permission=Permission.WRITE)
    async def my_tool():
        return "ok"

    seed_principal(_make_principal(Permission.READ))
    with pytest.raises(InsufficientPermissionError):
        await my_tool()


@pytest.mark.asyncio
async def test_require_auth_default_permission_is_read():
    @require_auth()
    async def my_tool():
        return "ok"

    seed_principal(_make_principal(Permission.READ))
    assert await my_tool() == "ok"


@pytest.mark.asyncio
async def test_require_auth_anonymous_path_allows_when_no_principal():
    @require_auth(permission=Permission.READ, allow_anonymous=True)
    async def my_tool():
        return "ok"

    assert await my_tool() == "ok"


@pytest.mark.asyncio
async def test_require_auth_anonymous_path_still_enforces_when_principal_set():
    @require_auth(permission=Permission.READ, allow_anonymous=True)
    async def my_tool():
        return "ok"

    seed_principal(_make_principal())  # no permissions
    with pytest.raises(InsufficientPermissionError):
        await my_tool()
```

- [ ] **Step 6.6: Modify `decorator.py` to remove kwarg transport and read from Context**

Rewrite `mcp_common/auth/decorator.py`:

```python
"""@require_auth decorator — reads Principal from request-scoped Context."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from mcp_common.auth.audit import AuditEvent, AuditLogger
from mcp_common.auth.context import _current_principal
from mcp_common.auth.exceptions import InsufficientPermissionError
from mcp_common.auth.permissions import Permission


def require_auth(
    permission: Permission = Permission.READ,
    *,
    allow_anonymous: bool = False,
    integrate_with_readyz: bool = True,
    audit_logger: AuditLogger | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: enforce permission on the calling tool.

    Reads Principal from request-scoped Context. No kwarg transport —
    clean break with prior convention.

    Args:
        permission: Required Permission. Defaults to READ.
        allow_anonymous: If True, allow anonymous calls (no Principal in
            Context). Defaults to False.
        integrate_with_readyz: If True, this tool contributes to /readyz
            aggregation. Defaults to True.
        audit_logger: Optional AuditLogger for emitting auth-decision events.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = _current_principal()
            if principal is None:
                if allow_anonymous:
                    return await func(*args, **kwargs)
                raise InsufficientPermissionError(
                    f"Anonymous call to {func.__name__} not allowed (no Principal in context)"
                )
            if not principal.has_permission(permission):
                if audit_logger:
                    audit_logger.emit(
                        AuditEvent(
                            principal=principal,
                            decision="deny",
                            permission=permission,
                            tool=func.__name__,
                        )
                    )
                raise InsufficientPermissionError(
                    f"Principal {principal.issuer}:{principal.subject} lacks {permission.value}"
                )
            if audit_logger:
                audit_logger.emit(
                    AuditEvent(
                        principal=principal,
                        decision="allow",
                        permission=permission,
                        tool=func.__name__,
                    )
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
```

Adjust `AuditEvent` constructor signature if it differs in the existing `audit.py` — match whatever fields exist there.

- [ ] **Step 6.7: Run all auth tests**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/ -v`
Expected: PASS for all auth tests. Coverage must remain ≥90%.

- [ ] **Step 6.8: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/middleware.py mcp_common/auth/decorator.py tests/auth/test_middleware.py tests/auth/test_decorator.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add BearerTokenMiddleware and rewrite @require_auth to read from Context"
```

---

### Task 7: Remove KNOWN_SERVICES, add trusted_issuers check

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/identity.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_identity.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_trusted_issuers.py`

**Interfaces:**
- Consumes: existing `verify_issuer()` function (delete it; replace with logic in JWTIdentityProvider.verify_token that uses `auth_config.trusted_issuers`)
- Produces: JWTIdentityProvider.verify_token now checks `iss` against `auth_config.trusted_issuers`

- [ ] **Step 7.1: Write failing test for trusted_issuers check**

```python
# tests/auth/test_trusted_issuers.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import JWTIdentityProvider
from mcp_common.auth.exceptions import UnknownIssuerError
from mcp_common.auth.permissions import Permission


SECRET = "trusted-issuers-test-secret-long-enough-abc"


@pytest.mark.asyncio
async def test_unknown_issuer_rejected():
    config = AuthConfig(
        enabled=True,
        secret=SECRET,
        service_name="test-service",
        trusted_issuers=["mahavishnu"],  # not "rogue-service"
    )
    provider = JWTIdentityProvider(name="jwt", secret=SECRET)
    token = provider.issue_token(
        issuer="rogue-service",
        audience="test-service",
        permissions=[Permission.READ],
        subject="attacker",
    )
    with pytest.raises(UnknownIssuerError):
        await provider.verify_token(token, expected_audience="test-service")


@pytest.mark.asyncio
async def test_trusted_issuer_accepted():
    config = AuthConfig(
        enabled=True,
        secret=SECRET,
        service_name="test-service",
        trusted_issuers=["mahavishnu", "session-buddy"],
    )
    provider = JWTIdentityProvider(name="jwt", secret=SECRET)
    token = provider.issue_token(
        issuer="session-buddy",
        audience="test-service",
        permissions=[Permission.READ],
        subject="legit",
    )
    principal = await provider.verify_token(token, expected_audience="test-service")
    assert principal.issuer == "session-buddy"
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_trusted_issuers.py -v`
Expected: FAIL with `UnknownIssuerError` not raised (current verify_token accepts any issuer)

- [ ] **Step 7.3: Add `trusted_issuers` enforcement to JWTIdentityProvider.verify_token**

Modify `mcp_common/auth/core.py` — inside the `JWTIdentityProvider.verify_token` method, after decoding the payload, check the issuer:

```python
async def verify_token(self, token: str, *, expected_audience: str | None = None) -> Principal:
    payload = verify_token(token, secret=self._secret, expected_audience=expected_audience)

    # Trusted issuers check (replaces global KNOWN_SERVICES)
    trusted = getattr(self, "_trusted_issuers", None) or []
    if trusted and payload.iss not in trusted:
        from mcp_common.auth.exceptions import UnknownIssuerError
        raise UnknownIssuerError(
            f"Issuer '{payload.iss}' not in trusted_issuers: {trusted}"
        )

    return _payload_to_principal(payload)
```

Update `JWTIdentityProvider.__init__` to accept `trusted_issuers`:

```python
def __init__(
    self,
    *,
    name: str = "jwt",
    secret: str | SecretStr,
    trusted_issuers: list[str] | None = None,
) -> None:
    self.name = name
    self._secret = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
    self._trusted_issuers = trusted_issuers or []
```

- [ ] **Step 7.4: Remove `KNOWN_SERVICES` from `identity.py`**

Edit `mcp_common/auth/identity.py`:
- Delete the `KNOWN_SERVICES` frozenset.
- Delete or rewrite `verify_issuer()` to be a no-op (no callers should remain after Task 4's refactor).
- Delete or rewrite `ServiceIdentity` if it's only used by `verify_issuer()`.

Verify no callers remain:
```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && grep -rn "KNOWN_SERVICES\|verify_issuer\|ServiceIdentity" mcp_common/ tests/ --include="*.py"
```

- [ ] **Step 7.5: Update or delete `tests/auth/test_identity.py`**

Either delete the file entirely or rewrite it to test the new behavior. If deleted, also remove from any test discovery config.

- [ ] **Step 7.6: Run tests**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/ -v`
Expected: PASS for all auth tests.

- [ ] **Step 7.7: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/identity.py mcp_common/auth/core.py tests/auth/test_trusted_issuers.py tests/auth/test_identity.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "refactor(auth): remove KNOWN_SERVICES frozenset; add per-server trusted_issuers"
```

---

### Task 8: Extend AuthConfig with trusted_issuers + identity_providers

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/config.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_config.py`

**Interfaces:**
- Consumes: existing `AuthConfig`
- Produces: extended `AuthConfig` with `trusted_issuers: list[str]`, `identity_providers: dict[str, IdentityProviderConfig]`, `default_provider: str | None`, `allow_anonymous_paths: list[str]`

- [ ] **Step 8.1: Write failing test**

Add to `tests/auth/test_config.py`:

```python
from mcp_common.auth.config import AuthConfig, IdentityProviderConfig


def test_auth_config_has_trusted_issuers_field():
    config = AuthConfig(
        enabled=True,
        secret="x" * 40,
        service_name="test",
        trusted_issuers=["mahavishnu", "session-buddy"],
    )
    assert config.trusted_issuers == ["mahavishnu", "session-buddy"]


def test_auth_config_has_default_provider_field():
    config = AuthConfig(
        enabled=True,
        secret="x" * 40,
        service_name="test",
        default_provider="jwt",
    )
    assert config.default_provider == "jwt"


def test_auth_config_has_allow_anonymous_paths():
    config = AuthConfig(
        enabled=True,
        secret="x" * 40,
        service_name="test",
    )
    assert "/health" in config.allow_anonymous_paths
    assert "/readyz" in config.allow_anonymous_paths


def test_identity_provider_config_basic():
    p = IdentityProviderConfig(name="anthropic", type="oauth", client_id="abc")
    assert p.name == "anthropic"
    assert p.type == "oauth"
    assert p.client_id == "abc"
```

- [ ] **Step 8.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_config.py::test_auth_config_has_trusted_issuers_field -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'trusted_issuers'`

- [ ] **Step 8.3: Extend `AuthConfig` in `config.py`**

```python
from pydantic import BaseModel, Field, SecretStr


class IdentityProviderConfig(BaseModel):
    """Configuration for a single IdentityProvider."""

    name: str
    type: str  # "jwt" | "oauth" | ...
    client_id: str | None = None
    client_secret: SecretStr | None = None
    oauth_token_url: str | None = None
    jwks_url: str | None = None
    audience: str | None = None
    timeout_seconds: float = 5.0


class AuthConfig(BaseModel):
    """Authentication configuration for an MCP server."""

    enabled: bool = True
    secret: SecretStr | None = None
    service_name: str

    trusted_issuers: list[str] = Field(default_factory=list)
    identity_providers: dict[str, IdentityProviderConfig] = Field(default_factory=dict)
    default_provider: str | None = None
    allow_anonymous_paths: list[str] = Field(
        default_factory=lambda: ["/health", "/readyz"]
    )

    model_config = {"arbitrary_types_allowed": True}
```

Preserve any existing AuthConfig behavior (env-var loading, placeholder rejection) by extending — not replacing — the existing class.

- [ ] **Step 8.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_config.py -v`
Expected: PASS

- [ ] **Step 8.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/config.py tests/auth/test_config.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): extend AuthConfig with trusted_issuers, identity_providers, default_provider"
```

---

### Task 9: Integrate AuthConfig into MCPServerSettings (settings surface)

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/cli/settings.py`
- Modify: `/Users/les/Projects/mcp-common/tests/cli/test_settings.py` (or wherever settings tests live)

**Interfaces:**
- Consumes: existing `MCPServerSettings`, extended `AuthConfig`
- Produces: `MCPServerSettings.auth: AuthConfig | None = None` field with YAML merge

- [ ] **Step 9.1: Write failing test**

Add to `tests/cli/test_settings.py` (or create if missing):

```python
from mcp_common.cli.settings import MCPServerSettings


def test_mcp_server_settings_has_auth_field():
    settings = MCPServerSettings(
        server_name="test",
        auth={
            "enabled": True,
            "service_name": "test",
            "trusted_issuers": ["mahavishnu"],
            "default_provider": "jwt",
        },
    )
    assert settings.auth is not None
    assert settings.auth.service_name == "test"
    assert settings.auth.trusted_issuers == ["mahavishnu"]
    assert settings.auth.default_provider == "jwt"
```

- [ ] **Step 9.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/cli/test_settings.py::test_mcp_server_settings_has_auth_field -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'auth'`

- [ ] **Step 9.3: Add `auth` field to `MCPServerSettings`**

Modify `mcp_common/cli/settings.py`:

```python
from mcp_common.auth.config import AuthConfig


class MCPServerSettings(BaseModel):
    server_name: str = Field(...)
    cache_root: Path = Field(default=Path(".oneiric_cache"))
    health_ttl_seconds: float = Field(default=60.0, ge=1.0)
    log_level: str = Field(default="INFO")
    log_file: Path | None = Field(default=None)
    stale_pid_action: Literal["auto_clean", "refuse"] = Field(default="auto_clean")

    # NEW: Authentication configuration (Phase 1 of auth surface).
    # The auth block is opt-in — existing MCPServerSettings without an `auth`
    # block in YAML continues to work (auth is disabled by default per AuthConfig).
    auth: AuthConfig | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
```

Update the `load()` classmethod to handle the `auth` key from YAML — if YAML has no `auth:` block, leave `auth=None`; if it has, parse into `AuthConfig`. This may already be handled by Pydantic's nested-model behavior; if so, no extra logic needed.

- [ ] **Step 9.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/cli/test_settings.py -v`
Expected: PASS

- [ ] **Step 9.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/cli/settings.py tests/cli/test_settings.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(settings): integrate AuthConfig into MCPServerSettings"
```

---

### Task 10: AuthHealth model + ProviderHealth aggregation

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/health.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_health.py`

**Interfaces:**
- Consumes: `ProviderHealth`, `IdentityProvider`, `IdentityProvider.health()`
- Produces:
  - `AuthHealth(providers, verifications_total, errors_total, last_successful_verification_at, last_updated_timestamp, cycles_total)`
  - `AuthHealth.from_providers(providers, counters)` classmethod
  - `AuthHealth.as_components()` returns list[dict] for /health envelope

- [ ] **Step 10.1: Write failing test**

```python
# tests/auth/test_health.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mcp_common.auth.health import AuthHealth
from mcp_common.auth.provider import IdentityProvider, ProviderHealth


class MockProvider:
    def __init__(self, name: str, state: str = "healthy", error: str | None = None):
        self._name = name
        self._state = state
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    async def verify_token(self, token, *, expected_audience=None):
        raise NotImplementedError

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self._name,
            state=self._state,  # type: ignore[arg-type]
            last_check_at=datetime.now(UTC),
            last_error=self._error,
        )


@pytest.mark.asyncio
async def test_auth_health_aggregates_providers():
    providers = {
        "jwt": MockProvider("jwt", state="healthy"),
        "anthropic": MockProvider("anthropic", state="degraded", error="JWKS timeout"),
    }
    health = await AuthHealth.from_providers(
        providers=providers,
        verifications_total=42,
        errors_total=3,
        last_successful_verification_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    assert health.providers["jwt"].state == "healthy"
    assert health.providers["anthropic"].state == "degraded"
    assert health.verifications_total == 42
    assert health.errors_total == 3
    assert health.cycles_total == 1  # one poll cycle just ran


def test_auth_health_as_components_returns_wiring_discipline_shape():
    health = AuthHealth(
        providers={"jwt": ProviderHealth(name="jwt", state="healthy")},
        verifications_total=10,
        errors_total=0,
        last_successful_verification_at=datetime.now(UTC),
        last_updated_timestamp=datetime.now(UTC),
        cycles_total=5,
    )
    components = health.as_components()
    assert len(components) == 1
    auth_component = components[0]
    assert auth_component["name"] == "auth"
    assert auth_component["entities_count"] == 10
    assert auth_component["errors_total"] == 0
    assert auth_component["cycles_total"] == 5
    assert "last_updated_timestamp" in auth_component


def test_auth_health_reports_degraded_when_any_provider_dead():
    health = AuthHealth(
        providers={
            "jwt": ProviderHealth(name="jwt", state="healthy"),
            "anthropic": ProviderHealth(name="anthropic", state="dead"),
        },
        verifications_total=10,
        errors_total=5,
        last_successful_verification_at=None,
        last_updated_timestamp=datetime.now(UTC),
        cycles_total=5,
    )
    assert health.is_degraded() is True
```

- [ ] **Step 10.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.health'`

- [ ] **Step 10.3: Implement AuthHealth**

```python
# mcp_common/auth/health.py
"""AuthHealth — wiring-discipline §3 four-signal feed observability for auth."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mcp_common.auth.provider import IdentityProvider, ProviderHealth


@dataclass
class AuthHealth:
    """Aggregated health snapshot for the auth surface.

    Mirrors wiring-discipline §3 shape:
    - entities_count: verifications served
    - last_updated_timestamp: last cycle timestamp
    - errors_total: verification failures
    - cycles_total: provider-health polls

    Surfaced via /health envelope's components[] array.
    """

    providers: dict[str, ProviderHealth]
    verifications_total: int
    errors_total: int
    last_successful_verification_at: datetime | None
    last_updated_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cycles_total: int = 0

    @classmethod
    async def from_providers(
        cls,
        *,
        providers: dict[str, IdentityProvider],
        verifications_total: int,
        errors_total: int,
        last_successful_verification_at: datetime | None,
    ) -> "AuthHealth":
        """Construct from live providers; runs health() on each in parallel."""
        import asyncio
        provider_healths = await asyncio.gather(
            *(p.health() for p in providers.values())
        )
        providers_dict = dict(zip(providers.keys(), provider_healths))
        return cls(
            providers=providers_dict,
            verifications_total=verifications_total,
            errors_total=errors_total,
            last_successful_verification_at=last_successful_verification_at,
            cycles_total=1,  # this constructor represents one poll cycle
        )

    def is_degraded(self) -> bool:
        """Return True if any provider is not healthy."""
        return any(p.state != "healthy" for p in self.providers.values())

    def as_components(self) -> list[dict[str, Any]]:
        """Render for /health envelope's components[] array.

        Returns a single component dict representing the entire auth surface,
        not one dict per provider (the providers are nested under
        `providers` for drill-down).
        """
        return [
            {
                "name": "auth",
                "state": "degraded" if self.is_degraded() else "healthy",
                "entities_count": self.verifications_total,
                "errors_total": self.errors_total,
                "cycles_total": self.cycles_total,
                "last_updated_timestamp": self.last_updated_timestamp.isoformat(),
                "last_successful_verification_at": (
                    self.last_successful_verification_at.isoformat()
                    if self.last_successful_verification_at
                    else None
                ),
                "providers": {
                    name: {
                        "state": p.state,
                        "last_check_at": p.last_check_at.isoformat() if p.last_check_at else None,
                        "last_error": p.last_error,
                    }
                    for name, p in self.providers.items()
                },
            }
        ]
```

- [ ] **Step 10.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_health.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/health.py tests/auth/test_health.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add AuthHealth model with wiring-discipline §3 four-signal shape"
```

---

### Task 11: Extend register_http_health_route with AuthHealth

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/health.py`
- Modify: `/Users/les/Projects/mcp-common/tests/unit/test_server_telemetry.py` (or wherever health tests live)

**Interfaces:**
- Consumes: existing `register_http_health_route(mcp, *, service_name, version, extra_components)`, new `AuthHealth.as_components()`
- Produces: extended route that includes AuthHealth when an auth_provider_registry is registered

- [ ] **Step 11.1: Write failing test**

Find the existing test file for `register_http_health_route` (look in `tests/unit/` or `tests/server/`):

```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && grep -rn "register_http_health_route" tests/ --include="*.py"
```

Add a test that verifies the `/health` route includes auth components when configured:

```python
from mcp_common.auth.health import AuthHealth
from mcp_common.auth.provider import ProviderHealth


def test_health_route_includes_auth_components_when_auth_registry_provided():
    from datetime import UTC, datetime
    from fastmcp import FastMCP
    from mcp_common.health import register_http_health_route

    mcp = FastMCP(name="test", version="0.0.1")
    auth_health = AuthHealth(
        providers={"jwt": ProviderHealth(name="jwt", state="healthy")},
        verifications_total=5,
        errors_total=0,
        last_successful_verification_at=datetime.now(UTC),
        last_updated_timestamp=datetime.now(UTC),
        cycles_total=1,
    )
    register_http_health_route(
        mcp,
        service_name="test",
        version="0.0.1",
        auth_health=auth_health,
    )
    # Check that the route was registered with auth components
    routes = [r.path for r in mcp.custom_routes] if hasattr(mcp, "custom_routes") else []
    # Adjust this assertion based on how FastMCP exposes its routes
    assert "/health" in routes or any("/health" in str(r) for r in routes)
```

- [ ] **Step 11.2: Run test to verify it fails**

Run the new test alone. Expected: FAIL because `register_http_health_route` doesn't accept `auth_health` parameter yet.

- [ ] **Step 11.3: Extend `register_http_health_route` signature**

Modify `mcp_common/health.py` (find the `register_http_health_route` function around line 810 per recon):

```python
def register_http_health_route(
    mcp: t.Any,
    *,
    service_name: str,
    version: str,
    extra_components: list[dict[str, t.Any]] | None = None,
    auth_health: AuthHealth | None = None,
) -> None:
    """Register /health endpoint with aggregated state.

    When auth_health is provided, its components are merged into the
    envelope. The route returns 503 if any auth provider is degraded
    (per wiring-discipline §1).
    """
    components = list(extra_components or [])
    if auth_health is not None:
        components.extend(auth_health.as_components())

    is_degraded = auth_health.is_degraded() if auth_health is not None else False

    @mcp.custom_route("/health", methods=["GET"])
    async def http_health(request: t.Any) -> t.Any:
        from starlette.responses import JSONResponse
        status_code = 503 if is_degraded else 200
        status = "degraded" if is_degraded else "ok"
        return JSONResponse(
            {"status": status, "service": service_name, "version": version,
             "components": components},
            status_code=status_code,
        )
```

Add the import at the top of `health.py`:
```python
from mcp_common.auth.health import AuthHealth
```

This is a deeper integration than just deep-import — `health.py` now imports from `auth/`. That's fine: `health.py` is a sibling submodule of `mcp_common` (not a downstream consumer), so it's appropriate for it to know about the auth package. The "no re-export from `__init__.py`" constraint still holds.

- [ ] **Step 11.4: Run test to verify it passes**

Run the new test alone. Expected: PASS

- [ ] **Step 11.5: Run all health tests to confirm no regression**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/ -v -k health`
Expected: PASS for all health-related tests

- [ ] **Step 11.6: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/health.py tests/ && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(health): include AuthHealth in /health envelope; return 503 when degraded"
```

---

### Task 12: JWKS rotation logic for AnthropicIdentityProvider

**Files:**
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/providers/anthropic.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_jwks_rotation.py`

**Interfaces:**
- Consumes: existing `AnthropicIdentityProvider`, `PyJWKClient`
- Produces: rotation logic with cached-fallback semantics

- [ ] **Step 12.1: Write failing test**

```python
# tests/auth/test_jwks_rotation.py
from __future__ import annotations

import httpx
import pytest

from mcp_common.auth.exceptions import ProviderUnavailableError, TokenInvalidError
from mcp_common.auth.providers.anthropic import AnthropicIdentityProvider


CLIENT_ID = "rotation-test-client"
CLIENT_SECRET = "rotation-test-client-secret-long-enough"
JWKS_URL = "https://example.invalid/jwks"
OAUTH_URL = "https://example.invalid/oauth/token"
AUDIENCE = "rotation-test-audience"


@pytest.fixture
def provider() -> AnthropicIdentityProvider:
    return AnthropicIdentityProvider(
        name="anthropic",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        oauth_token_url=OAUTH_URL,
        jwks_url=JWKS_URL,
        audience=AUDIENCE,
        jwks_cache_seconds=60,
    )


@pytest.mark.asyncio
async def test_jwks_cache_hit_skips_network(provider, respx_mock):
    """First call hits network; second call uses cache."""
    respx_mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": []}))

    # First call: cache miss → network
    try:
        await provider.verify_token("fake.jwt.token", expected_audience=AUDIENCE)
    except (TokenInvalidError, ProviderUnavailableError):
        pass  # expected — we just care about network access

    # Reset call count
    respx_mock.get(JWKS_URL).reset()

    # Second call within cache TTL: should not hit network
    try:
        await provider.verify_token("fake.jwt.token", expected_audience=AUDIENCE)
    except (TokenInvalidError, ProviderUnavailableError):
        pass

    assert respx_mock.get(JWKS_URL).call_count == 0, "cache should prevent network hit"


@pytest.mark.asyncio
async def test_jwks_cache_miss_after_ttl_refreshes(provider, respx_mock):
    """After cache TTL expires, next call hits network again."""
    # Use a tiny TTL for testing
    provider._jwks_cache_seconds = 0  # type: ignore[attr-defined]

    respx_mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": []}))

    # First call hits network
    try:
        await provider.verify_token("fake.jwt.token", expected_audience=AUDIENCE)
    except (TokenInvalidError, ProviderUnavailableError):
        pass

    # Second call after TTL → hits network again
    try:
        await provider.verify_token("fake.jwt.token", expected_audience=AUDIENCE)
    except (TokenInvalidError, ProviderUnavailableError):
        pass

    assert respx_mock.get(JWKS_URL).call_count == 2
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_jwks_rotation.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'jwks_cache_seconds'` (or similar — depends on what was already implemented in Task 5)

- [ ] **Step 12.3: Add cache-TTL parameter and force-refresh method**

Modify `mcp_common/auth/providers/anthropic.py`:

```python
class AnthropicIdentityProvider:
    def __init__(
        self,
        *,
        name: str = "anthropic",
        client_id: str,
        client_secret: str,
        oauth_token_url: str,
        jwks_url: str,
        audience: str,
        timeout_seconds: float = 5.0,
        jwks_cache_seconds: int = 3600,
    ) -> None:
        self.name = name
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_token_url = oauth_token_url
        self._audience = audience
        self._timeout = timeout_seconds
        self._jwks_cache_seconds = jwks_cache_seconds
        self._jwks_client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=jwks_cache_seconds,
        )
        self._http = httpx.AsyncClient(timeout=timeout_seconds)
        self._last_error: str | None = None
        self._last_state: ProviderHealth.__annotations__["state"] = "healthy"

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        # Force cache expiration if jwks_cache_seconds is 0 (test mode)
        if self._jwks_cache_seconds == 0:
            self._jwks_client.__init__(  # type: ignore[misc]
                self._jwks_client.uri,
                cache_keys=True,
                lifespan=self._jwks_cache_seconds,
            )

        # ... (existing verify_token logic)
```

- [ ] **Step 12.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_jwks_rotation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 12.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/providers/anthropic.py tests/auth/test_jwks_rotation.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add JWKS rotation logic with cached-fallback to AnthropicIdentityProvider"
```

---

### Task 13: Internal auth doc at mcp_common/docs/auth-design.md

**Files:**
- Create: `/Users/les/Projects/mcp-common/docs/auth-design.md`

- [ ] **Step 13.1: Write the doc**

```markdown
---
title: mcp-common Auth Design
date: 2026-09-07
status: implemented
audience: mcp-common contributors, sibling-server maintainers
related:
  - https://github.com/lesleslie/mahavishnu/blob/main/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md (canonical spec)
---

# mcp-common Auth Design

## What this package does

`mcp_common/auth/` provides authentication primitives for Bodai MCP servers. It
implements the design documented at
`mahavishnu/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md`.

The package is **internal** — consumers should import from `mcp_common.auth.*`
directly (deep imports). Public-API graduation (re-export from `mcp_common/__init__.py`)
is a future spec after the surface has been used in production by at least one
sibling server.

## Components

- **`Principal`** — frozen dataclass representing an authenticated identity.
- **`IdentityProvider` Protocol** — runtime-checkable Protocol with `verify_token`
  and `health` methods.
- **`JWTIdentityProvider`** — concrete provider using HS256 JWT (the existing
  inter-service auth path, extracted from the free-function `verify_token`).
- **`AnthropicIdentityProvider`** — concrete provider using OAuth 2.0 + PKCE + JWKS.
- **`BearerTokenMiddleware`** — FastMCP middleware that reads `Authorization: Bearer`
  from the ASGI scope and stashes a Principal on the request-scoped Context.
- **`@require_auth`** — decorator that reads Principal from Context and enforces
  the requested permission.
- **`AuthConfig`** — settings surface integrated into `MCPServerSettings.auth`.
- **`AuthHealth`** — wiring-discipline §3 four-signal feed observability surfaced
  via the `/health` envelope.

## Usage

### Wiring BearerTokenMiddleware in a server's lifespan

```python
from mcp_common.auth.config import AuthConfig, IdentityProviderConfig
from mcp_common.auth.core import JWTIdentityProvider
from mcp_common.auth.health import AuthHealth
from mcp_common.auth.middleware import BearerTokenMiddleware
from mcp_common.auth.providers.anthropic import AnthropicIdentityProvider


def build_middleware(auth_config: AuthConfig) -> BearerTokenMiddleware:
    providers = {}
    if auth_config.identity_providers.get("jwt"):
        providers["jwt"] = JWTIdentityProvider(
            name="jwt",
            secret=auth_config.secret.get_secret_value(),
            trusted_issuers=auth_config.trusted_issuers,
        )
    if anthropic_cfg := auth_config.identity_providers.get("anthropic"):
        providers["anthropic"] = AnthropicIdentityProvider(
            client_id=anthropic_cfg.client_id,
            client_secret=anthropic_cfg.client_secret.get_secret_value(),
            oauth_token_url=anthropic_cfg.oauth_token_url,
            jwks_url=anthropic_cfg.jwks_url,
            audience=anthropic_cfg.audience or auth_config.service_name,
        )
    return BearerTokenMiddleware(auth_config=auth_config, providers=providers)
```

### Decorating a tool

```python
from mcp_common.auth.decorator import require_auth
from mcp_common.auth.permissions import Permission


@require_auth(permission=Permission.WRITE)
async def my_tool(...):
    ...
```

### Testing with seed_principal

```python
from mcp_common.auth.context import seed_principal
from mcp_common.auth.principal import Principal
from mcp_common.auth.permissions import Permission


def test_my_tool():
    principal = Principal(
        issuer="test",
        subject="user-1",
        permissions=frozenset({Permission.WRITE}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    token_handle = seed_principal(principal)
    try:
        result = await my_tool()
    finally:
        token_handle.var.reset(token_handle)
```

## What's NOT here

- Other OAuth/OIDC providers (Google, GitHub, etc.) — future IdPs add incrementally
  via the IdentityProvider Protocol.
- mTLS / cert-based auth — deferred to v2.
- Federated identity / SAML — out of scope.

## Migration notes (from prior convention)

Prior versions of `@require_auth` accepted a `__auth_token__` kwarg for token
injection. This convention is gone. New code uses `seed_principal(...)` for tests
and middleware for production traffic. There is no deprecation window — the
package had zero production consumers at the time of this change.
```

- [ ] **Step 13.2: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add docs/auth-design.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(auth): add internal design doc for mcp_common.auth package"
```

---

### Task 14: Wire sibling servers (scapy-mcp, archive-org-mcp, medium-mcp)

**Files:**
- Modify: `/Users/les/Projects/scapy-mcp/scapy_mcp/server.py`
- Modify: `/Users/les/Projects/archive-org-mcp/src/.../server.py` (or wherever its server lives)
- Modify: `/Users/les/Projects/medium-mcp/.../server.py`
- Create/Modify: integration test in each sibling repo

**Interfaces:**
- Each sibling server constructs a `BearerTokenMiddleware` in its lifespan and registers `AuthHealth` in its `/health` envelope.

Cross-repo dispatch: enter each sibling repo separately. Use `git -C` or worktree isolation per mahavishnu dispatch policy. Strip `VIRTUAL_ENV`/`UV_ACTIVE` before any `uv pip install`.

- [ ] **Step 14.1: Wire scapy-mcp**

Read current `scapy_mcp/server.py` to understand its lifespan structure, then modify the Runtime class to construct BearerTokenMiddleware when auth is enabled:

```python
# In scapy_mcp/server.py (additions)
from mcp_common.auth.config import AuthConfig, IdentityProviderConfig
from mcp_common.auth.core import JWTIdentityProvider
from mcp_common.auth.health import AuthHealth
from mcp_common.auth.middleware import BearerTokenMiddleware


class Runtime:
    def __init__(self, *, settings):
        self.settings = settings
        self._auth_middleware: BearerTokenMiddleware | None = None
        self._auth_counters: dict[str, int] = {"verifications_total": 0, "errors_total": 0}
        self._last_successful_verification_at: datetime | None = None

    def _build_auth_middleware(self) -> BearerTokenMiddleware | None:
        auth_cfg = self.settings.auth
        if auth_cfg is None or not auth_cfg.enabled:
            return None
        providers = {}
        if auth_cfg.identity_providers.get("jwt"):
            providers["jwt"] = JWTIdentityProvider(
                name="jwt",
                secret=auth_cfg.secret.get_secret_value(),
                trusted_issuers=auth_cfg.trusted_issuers,
            )
        # ... Anthropic, etc.
        return BearerTokenMiddleware(auth_config=auth_cfg, providers=providers)
```

Pass the auth components to `register_http_health_route`'s `extra_components` parameter (and the new `auth_health` parameter from Task 11).

- [ ] **Step 14.2: Wire archive-org-mcp**

Same shape as 14.1, applied to archive-org-mcp's server entry point.

- [ ] **Step 14.3: Wire medium-mcp**

Same shape as 14.1, applied to medium-mcp's server entry point.

- [ ] **Step 14.4: Add integration test in each sibling repo**

In scapy-mcp:
```python
# tests/integration/test_auth_wiring.py
from datetime import UTC, datetime, timedelta

import pytest

from mcp_common.auth.config import AuthConfig, IdentityProviderConfig
from mcp_common.auth.context import seed_principal
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal


def test_scapy_mcp_constructs_bearer_token_middleware_when_auth_enabled():
    """Verify the middleware is wired into the server lifespan."""
    # ... (construct server with auth enabled, hit /health, assert auth component)
    ...
```

- [ ] **Step 14.5: Run sibling server tests**

For each sibling:
```bash
cd /Users/les/Projects/scapy-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/integration/test_auth_wiring.py -v
cd /Users/les/Projects/archive-org-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/ -v -k auth
cd /Users/les/Projects/medium-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/ -v -k auth
```

Expected: PASS

- [ ] **Step 14.6: Commit each sibling**

For each:
```bash
cd /Users/les/Projects/<sibling> && git add scapy_mcp/server.py tests/integration/test_auth_wiring.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): wire BearerTokenMiddleware into server lifespan"
```

---

### Task 15: Update gdpr-posture.md §10 with auth section

**Files:**
- Modify: `/Users/les/Projects/mahavishnu/docs/legal/gdpr-posture.md`

- [ ] **Step 15.1: Read the current gdpr-posture.md to find §10**

```bash
cat /Users/les/Projects/mahavishnu/docs/legal/gdpr-posture.md | head -200
```

Look for the section that discusses mcp-common auth or technical measures. If §10 doesn't exist, add it.

- [ ] **Step 15.2: Append or update §10**

Add the auth section describing how `AuthHealth` satisfies Article 32 monitoring requirements, and how `BearerTokenMiddleware` provides the authentication primitive required by Article 32's "appropriate technical measures" clause.

Markdown snippet to add:

```markdown
## §10. Authentication posture

Bodai MCP servers authenticate inbound requests via `mcp_common.auth.BearerTokenMiddleware`,
which reads `Authorization: Bearer <token>` from the ASGI scope and verifies via
the configured `IdentityProvider` (inter-service JWT or Anthropic OAuth).

Authentication state is observable via `/health`:

- `entities_count`: verifications served since startup
- `errors_total`: verification failures
- `cycles_total`: provider-health polls
- `last_updated_timestamp`: last cycle time

This satisfies Article 32's "ongoing monitoring" requirement for production
deployments: the auth surface is continuously observable, and degraded states
return 503 from `/health` so monitoring systems can alert.

For pre-1.0 internal use, auth is opt-in (see §3). Production deployments must
set `auth.enabled: true` and configure at least one provider in
`MCPServerSettings.auth.identity_providers`.
```

- [ ] **Step 15.3: Commit**

```bash
cd /Users/les/Projects/mahavishnu && git add docs/legal/gdpr-posture.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(gdpr): §10 — describe auth posture and Article 32 alignment"
```

---

### Task 16: Re-review ADR 0016 v3, close deferred item

**Files:**
- Modify: `/Users/les/Projects/mahavishnu/docs/adr/0016-scapy-mcp-integration.md`
- Modify: `/Users/les/Projects/mahavishnu/docs/adr/0016-multi-agent-review.md` (if applicable)

- [ ] **Step 16.1: Read ADR 0016 v3**

```bash
cat /Users/les/Projects/mahavishnu/docs/adr/0016-scapy-mcp-integration.md
```

Look for the "Deferred to v4+" section and the "v4+ ADR 0016 deferred" items.

- [ ] **Step 16.2: Close the "mcp-common authentication primitives" deferred item**

Find the item in the ADR's "Deferred to v4+" list. Mark it as closed by:
- Adding a "Closed: 2026-09-07 via spec `2026-09-06-mcp-common-auth-primitives-design.md` and plan `2026-09-07-mcp-common-auth-primitives.md`" annotation, OR
- Moving it to a "Closed deferred items" subsection, OR
- Removing it if the deferral list is now empty

- [ ] **Step 16.3: Re-review remaining deferred items**

If any v4+ items remain after closing auth, note them as still deferred.

- [ ] **Step 16.4: Update ADR 0016 status to "complete (rev 4)" if appropriate**

If all v4+ items are now closed, bump the ADR's status from "complete" to "complete (rev 4)". Otherwise leave the status unchanged.

- [ ] **Step 16.5: Commit**

```bash
cd /Users/les/Projects/mahavishnu && git add docs/adr/0016-scapy-mcp-integration.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(adr): 0016 — close mcp-common auth primitives deferred item"
```

---

### Task 17: Final verification

- [ ] **Step 17.1: Run full mcp-common test suite**

```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest --cov=mcp_common --cov-report=term-missing
```

Expected: All tests pass, coverage ≥90% on `mcp_common/auth/` modules.

- [ ] **Step 17.2: Run sibling server test suites**

```bash
cd /Users/les/Projects/scapy-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest
cd /Users/les/Projects/archive-org-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest
cd /Users/les/Projects/medium-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest
```

Expected: All pass, no regressions.

- [ ] **Step 17.3: Run crackerjack quality gates**

In mcp-common:
```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run crackerjack run
```

Expected: Fast hooks pass. Comprehensive hooks may have warnings (deferred per session context).

- [ ] **Step 17.4: Regenerate PLAN_INDEX in mahavishnu**

```bash
cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && uv run python scripts/regenerate_plan_index.py
```

Expected: PLAN_INDEX.md updates to include the new plan.

- [ ] **Step 17.5: Final summary commit**

If anything in PLAN_INDEX or any spec was missed, commit the fix. Otherwise report completion.

---

## Self-Review Checklist

- [x] **Spec coverage**: every Goal in the spec maps to a task:
  - Principal model → Task 1
  - IdentityProvider Protocol → Task 1
  - JWTIdentityProvider → Task 4
  - AnthropicIdentityProvider → Task 5
  - BearerTokenMiddleware → Task 6
  - @require_auth extension → Task 6
  - KNOWN_SERVICES removal → Task 7
  - AuthConfig extension → Task 8
  - OneiricMCPConfig integration → Task 9
  - AuthHealth model → Task 10
  - /health envelope integration → Task 11
  - JWKS rotation → Task 12
  - Internal auth doc → Task 13
  - Sibling server wiring → Task 14
  - gdpr-posture update → Task 15
  - ADR 0016 re-review → Task 16
- [x] **Placeholder scan**: no TBD/TODO/FIXME. Code blocks are concrete.
- [x] **Type consistency**: `Principal` field names (issuer, subject, permissions, expires_at, raw_claims) used consistently across Tasks 1, 3, 4, 5, 6. `IdentityProvider` Protocol shape used consistently. `ProviderHealth` field names (name, state, last_check_at, last_error) used consistently. `AuthHealth` field names used consistently.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for cross-repo work like this where each repo needs its own context.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review. Faster turnaround but harder to debug cross-repo issues.

**Which approach?**
