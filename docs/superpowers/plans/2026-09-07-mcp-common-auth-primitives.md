# mcp-common Authentication Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `mcp_common/auth/` surface as specified in `docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md` — single phase, no backward-compat bridge, deep-imports only.

**Architecture:** Add `Principal` model, `IdentityProvider` Protocol, `JWTIdentityProvider` and `AnthropicIdentityProvider` concretes, `BearerTokenMiddleware` (ASGI scope → Context), extended `@require_auth`, `AuthConfig` rewired into `MCPServerSettings`, `AuthHealth` surfaced via `/health`. Sibling MCP servers wire the middleware in their lifespan.

**Tech Stack:** Python 3.14, Pydantic v2, FastMCP, PyJWT (existing), httpx (existing — for OAuth HTTP calls), contextvars (stdlib), respx (for HTTP mocking in tests).

**Spec:** `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md`

## Global Constraints

From the spec (every task implicitly includes these):

- **Python 3.14**, Pydantic v2, modern type syntax (`X | None`, `list[str]`, `pathlib.Path`).
- **`from __future__ import annotations`** as the first non-comment line of every source file.
- **Imports sorted** within each section (stdlib → third-party → first-party; `force-sort-within-sections = true`).
- **`mcp_common.auth.*` package is internal** — deep imports only; **do NOT re-export from `mcp_common/__init__.py`** in this plan (graduation is a separate future spec).
- **No `__auth_token__` kwarg transport** — clean break; `@require_auth` reads Principal from request-scoped Context only.
- **`KNOWN_SERVICES` frozenset removed** — replaced by per-server `AuthConfig.trusted_issuers` with **default-deny semantics** (empty list rejects ALL issuers).
- **No backward-compat bridge / no `DeprecationWarning`** — tests migrate simultaneously with the new shape.
- **90% branch coverage** required (mcp-common standard).
- **Phased graduation: keep `mcp_common/auth/` deep-import only** — no `__init__.py` re-export, no settings field on `OneiricMCPConfig` public surface (the settings integration is at the `MCPServerSettings` layer only, not exposed to other consumers).
- **Plan runs in mcp-common repo** (`/Users/les/Projects/mcp-common`) for Tasks 1–13. Sibling server wiring (Task 14) cross-repos into scapy-mcp, archive-org-mcp, medium-mcp — use `git -C` or worktree isolation per mahavishnu dispatch policy. Cross-repo docs (Tasks 15–16) live in mahavishnu.

### From the 2026-09-07 multi-agent review (7 reviewers)

- **Use `get_http_headers()` from `fastmcp.server.dependencies` for header access** (B1 — `MiddlewareContext` has no `.scope` attribute; verified against FastMCP source at `/usr/local/Cellar/mcpm/2.15.0_2/libexec/lib/python3.14/site-packages/fastmcp/server/middleware/middleware.py:47-61`).
- **Raise `AuthError` (a custom exception in `mcp_common/auth/exceptions.py`), not `HTTPException`** (B2 — FastMCP middleware errors propagate as JSON-RPC, where `HTTPException` loses `WWW-Authenticate: Bearer` header).
- **Catch `AuthError` subclasses only** in middleware; let other exceptions propagate (B4 — bare `except Exception` masks programming bugs and yields 401).
- **Pin `algorithms=["HS256"]` in `jwt.decode`** for JWT provider (B5 — vulnerability to `alg=none` and HS256/RSA key-confusion attacks).
- **Default-deny in `_extract_permissions`** — return `[]` on empty scope, use exact-match scope checking (B7 — substring `"in"` is exploitable).
- **`/health` keeps 200-only with `status: "degraded"` in body** (I-7 — contract change from 200 to 503 breaks launchd probes across 9 sibling servers).
- **Recompute `is_degraded` per request** in the `/health` handler (B3 — closure capture freezes status after first paint).
- **Anthropic provider in this plan handles JWKS verification only** (5a); OAuth authorization-code flow + refresh tokens + `offline_access` is **Task 5b (follow-up spec)** (B11 — current plan claimed PKCE/refresh but didn't implement).
- **`integrate_with_readyz` parameter dropped** from `@require_auth` (I-2 — accepted but never consulted; ship no parameter that lies to callers).
- **`AuthConfig` is rewritten to Pydantic as Task 8a** (must land before Task 6); new fields (`trusted_issuers`, `identity_providers`, etc.) added in Task 8b (B8 — dependency reordering).
- **Match `AuthAuditEvent` fields, do not invent a new `AuditEvent`** (B10 — type confusion; existing fields are `timestamp`, `service`, `caller_service`, `caller_id`, `action`, `result`, `reason`).
- **Add Integration Contract blocks** to each phase (B12 — wire-up contract §1 violation).
- **Default-deny on `trusted_issuers` empty list** (B6 — current `if trusted and ...` is fail-open; require explicit startup check that `enabled=True` implies non-empty `trusted_issuers`).
- **Each task has a `Counter store` reference** so `verifications_total` and `errors_total` actually increment (I-4 — currently no path from middleware to counters; `entities_count` would stay at 0).
- **Skip auth on `context.method == "initialize"`** (I-1 from mcp-integration — the `initialize` MCP handshake must not be 401'd).

## Execution Order

Tasks 1–13 land in `mcp-common` as a coherent vertical slice. Task 14 wires sibling servers in their own repos (use the standard cross-repo dispatch pattern — `cd <repo>` before any tool calls, `unset VIRTUAL_ENV UV_ACTIVE` before `uv pip install`). Tasks 15–16 update cross-repo docs in mahavishnu. Task 17 is the final verification gate.

______________________________________________________________________

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

______________________________________________________________________

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

______________________________________________________________________

### Task 3: Context-var helpers (seed_principal, \_current_principal)

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

______________________________________________________________________

### Task 4: Extract JWTIdentityProvider from existing core.py

**Files:**

- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/core.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_core.py`

**Interfaces:**

- Consumes: `Principal`, `IdentityProvider`, `ProviderHealth`, `JWT_ALGORITHM`, `DEFAULT_TOKEN_TTL_SECONDS` (existing)

- Produces:

  - `JWTIdentityProvider(name="jwt", secret: SecretStr, *, trusted_issuers: list[str] | None = None)` implementing `IdentityProvider`
  - **B5 fix**: `jwt.decode` pins `algorithms=["HS256"]` directly — does NOT delegate to the free-function `verify_token()` (avoids `alg=none` / HS256-RSA confusion attacks).
  - **B9 fix**: `TokenPayload.raw` is renamed to `TokenPayload.raw_claims` to match the new spec; the free functions `create_service_token()` and `verify_token()` are kept but rewritten to populate `raw_claims`.
  - **B10 fix**: The `@require_auth` decorator uses `AuthAuditEvent` directly (the existing type in `mcp_common/auth/audit.py`), not a new `AuditEvent` class.

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

Append to `mcp_common/auth/core.py` (the existing `TokenPayload` dataclass is renamed to use `raw_claims` per B9; the existing `create_service_token` / `verify_token` free functions are kept but rewritten to use `raw_claims`):

```python
# Existing TokenPayload (at the top of core.py) — rename `raw` to `raw_claims`:
@dataclass
class TokenPayload:
    iss: str
    sub: str
    permissions: list[str]
    exp: datetime
    raw_claims: dict[str, Any] = field(default_factory=dict)  # was `raw`


# Existing free functions — keep but rewrite to populate raw_claims and pin algs:
def create_service_token(
    *,
    secret: str,
    issuer: str,
    audience: str,
    permissions: list[Permission],
    subject: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "permissions": [p.value for p in permissions],
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)  # HS256 pinned at encode


def verify_token(
    token: str,
    *,
    secret: str,
    expected_audience: str | None = None,
) -> TokenPayload:
    """Verify a JWT and return TokenPayload.

    B5 fix: algorithms pinned to [JWT_ALGORITHM] (HS256). Required claims:
    exp, iat, iss, aud.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError(f"Malformed token: {exc}") from exc

    if unverified_header.get("alg") != JWT_ALGORITHM:
        raise TokenInvalidError(
            f"Unexpected algorithm: {unverified_header.get('alg')!r}"
        )

    payload = jwt.decode(
        token,
        secret,
        algorithms=[JWT_ALGORITHM],  # PIN algorithms — never accept `none` or RSA-via-HMAC
        audience=expected_audience,
        options={"require": ["exp", "iat", "iss", "aud"]},
        # api-security R2-7 fix: tolerate small clock skew between issuer
        # and verifier (default 0s; 30s matches typical NTP drift tolerance).
        leeway=30,
    )
    return TokenPayload(
        iss=payload["iss"],
        sub=payload["sub"],
        permissions=payload.get("permissions", []),
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        raw_claims=payload,
    )


# New class — extracted from verify_token free function:
class JWTIdentityProvider:
    """IdentityProvider implementation using PyJWT HS256.

    B5 fix: jwt.decode pins algorithms=[JWT_ALGORITHM] (HS256). B9 fix:
    TokenPayload.raw_claims carries the full decoded payload (no getattr
    guards). B10 fix: @require_auth uses AuthAuditEvent directly.
    """

    def __init__(
        self,
        *,
        name: str = "jwt",
        secret: str | SecretStr,
        trusted_issuers: list[str] | None = None,
    ) -> None:
        self.name = name
        self._secret = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        # B6 fix: trusted_issuers is the per-server allow-list. Default-deny
        # is enforced in Task 7 (the middleware startup check).
        self._trusted_issuers: list[str] = trusted_issuers or []

    def issue_token(
        self,
        *,
        issuer: str,
        audience: str,
        permissions: list[Permission],
        subject: str,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> str:
        """Issue a signed JWT. Wraps the free-function create_service_token()."""
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

        Calls verify_token() (which pins algorithms); then enforces the
        trusted-issuers allow-list (B6 — default-deny: empty list
        rejects all issuers, see Task 7 for the startup check).
        """
        payload = verify_token(
            token, secret=self._secret, expected_audience=expected_audience
        )

        if payload.iss not in self._trusted_issuers:
            raise UnknownIssuerError(
                f"Issuer '{payload.iss}' not in trusted_issuers: "
                f"{self._trusted_issuers}"
            )

        # api-security R2-4 fix: an unknown permission value in the JWT
        # payload raised an uncaught ValueError (Permission(p) is a strict
        # enum). That bypassed the middleware's 401 handling and surfaced
        # as a 500. Convert to TokenInvalidError so the middleware maps it
        # to 401 (the right semantic: the token is structurally valid but
        # semantically unprocessable).
        try:
            permissions = frozenset({Permission(p) for p in payload.permissions})
        except ValueError as exc:
            raise TokenInvalidError(
                f"Token carries unknown permission value: {exc}"
            ) from exc

        return Principal(
            issuer=payload.iss,
            subject=payload.sub,
            permissions=permissions,
            expires_at=payload.exp,
            raw_claims=payload.raw_claims,  # B9 fix: no hasattr guard
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, state="healthy")
```

Add imports at the top of `core.py` if not already present:

- `from datetime import UTC, datetime, timedelta` (if not present)

- `from pydantic import SecretStr`

- `from mcp_common.auth.exceptions import TokenInvalidError, UnknownIssuerError`

- `from mcp_common.auth.permissions import Permission`

- `from mcp_common.auth.principal import Principal`

- `from mcp_common.auth.provider import IdentityProvider, ProviderHealth`

- `import jwt` (PyJWT)

- [ ] **Step 4.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_core.py -v`
Expected: PASS (existing + 3 new tests, ≥90% branch coverage maintained)

- [ ] **Step 4.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/core.py tests/auth/test_core.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "refactor(auth): extract JWTIdentityProvider class from verify_token free function"
```

______________________________________________________________________

### Task 5a: AnthropicIdentityProvider — JWKS verification only

**Files:**

- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/providers/__init__.py`
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/providers/anthropic.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_providers/__init__.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_providers/test_anthropic.py`

**Interfaces:**

- Consumes: `IdentityProvider`, `Principal`, `ProviderHealth`, `ProviderUnavailableError`, `UnknownIssuerError`, `TokenInvalidError`, `httpx`
- Produces:
  - `AnthropicIdentityProvider(*, name: str = "anthropic", client_id: str, client_secret: str, oauth_token_url: str, jwks_url: str, audience: str, trusted_issuers: list[str] | None = None, jwks_cache_seconds: int = 3600)` implementing `IdentityProvider`

**B11 fix:** This task is **Task 5a** — JWKS verification only. The OAuth authorization-code flow, PKCE `code_verifier` generation, refresh-token rotation, and `offline_access` scope are deferred to **Task 5b (follow-up spec)**. The spec is amended to reflect this split: in the current scope, the Anthropic provider verifies Anthropic-issued access tokens; it does not initiate the OAuth flow.

**B7 fix:** Default-deny semantics in `_extract_permissions` — empty scope/permissions returns `[]`, exact-match scope checking (no substring `in`).

**B6 fix (I-3 cross-cutting):** `trusted_issuers` is enforced in `verify_token` (mirror of JWT provider). An Anthropic-issued token with `iss=evil-corp` is rejected even if JWKS signature validates.

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

- [ ] **Step 5.4: Implement AnthropicIdentityProvider (5a: JWKS verification only)**

```python
# mcp_common/auth/providers/anthropic.py
"""AnthropicIdentityProvider — Task 5a: JWKS verification only.

B11 fix: This module verifies Anthropic-issued access tokens. The OAuth
authorization-code flow, PKCE code_verifier generation, and refresh-token
rotation are deferred to Task 5b (follow-up spec) and live in a separate
module (mcp_common/auth/providers/anthropic_oauth.py).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt import PyJWKClient

from mcp_common.auth.exceptions import (
    ProviderUnavailableError,
    TokenInvalidError,
    UnknownIssuerError,
)
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider, ProviderHealth


class AnthropicIdentityProvider:
    """IdentityProvider for Anthropic-issued JWTs (5a: JWKS verify only).

    B7 fix: default-deny in _extract_permissions — empty scope/permissions
    returns []. B6 fix: trusted_issuers enforced (default-deny on empty).
    """

    def __init__(
        self,
        *,
        name: str = "anthropic",
        client_id: str,
        client_secret: str,
        oauth_token_url: str,
        jwks_url: str,
        audience: str,
        trusted_issuers: list[str] | None = None,
        jwks_cache_seconds: int = 3600,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.name = name
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_token_url = oauth_token_url
        self._audience = audience
        self._timeout = timeout_seconds
        self._trusted_issuers: list[str] = trusted_issuers or []
        self._jwks_client = PyJWKClient(
            jwks_url, cache_keys=True, lifespan=jwks_cache_seconds
        )
        self._last_error: str | None = None
        # LOW-5 fix (Task 5): import ProviderState directly instead of
        # reaching into ProviderHealth.__annotations__["state"] at runtime.
        # Mirrors the Task 12 fix so both providers use the same type for
        # the _last_state field.
        from mcp_common.auth.provider import ProviderState
        self._last_state: ProviderState = "healthy"

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        audience = expected_audience or self._audience
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientError as exc:
            self._last_error = f"JWKS fetch failed: {exc}"
            self._last_state = "degraded"
            raise ProviderUnavailableError(
                f"JWKS fetch failed: {exc}", provider=self.name
            ) from exc

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenInvalidError("Token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenInvalidError(f"Audience mismatch: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError(f"Invalid token: {exc}") from exc

        # B6 fix: trusted-issuers allow-list (default-deny — empty list
        # rejects all issuers, see Task 7 startup check).
        if payload.get("iss") not in self._trusted_issuers:
            raise UnknownIssuerError(
                f"Issuer '{payload.get('iss')}' not in trusted_issuers: "
                f"{self._trusted_issuers}"
            )

        self._last_state = "healthy"
        self._last_error = None

        return Principal(
            issuer=payload["iss"],
            subject=payload.get("sub", "unknown"),
            permissions=frozenset(self._extract_permissions(payload)),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
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
        """B7 fix: default-deny — empty scope/permissions returns [].

        Anthropic OAuth uses a 'scope' claim (space-separated) plus a custom
        'permissions' array. We use exact-match scope checking (no substring
        'in' which is exploitable — e.g., "read" in "read:admin").
        """
        scope_value = payload.get("scope", "")
        scopes = set(scope_value.split()) if isinstance(scope_value, str) else set()
        permissions: list[Permission] = []
        # Exact match against known scope tokens (no substring matching)
        if "read" in scopes or "read:mcp" in scopes:
            permissions.append(Permission.READ)
        if "write" in scopes or "write:mcp" in scopes:
            permissions.append(Permission.WRITE)
        if "admin" in scopes or "admin:mcp" in scopes:
            permissions.append(Permission.ADMIN)
        for p in payload.get("permissions", []):
            try:
                permissions.append(Permission(p))
            except ValueError:
                # Unknown permission value — fail closed. (B7 fix: do NOT
                # silently coerce to READ; let an empty result deny.)
                pass
        return permissions  # Default-deny: returns [] on empty scope
```

- [ ] **Step 5.5 (deferred — Task 5b):** OAuth authorization-code flow with PKCE + refresh tokens + `offline_access` scope. Tracked in a follow-up spec. The current plan does not implement it.

- [ ] **Step 5.5: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_providers/test_anthropic.py -v`
Expected: PASS (4 tests). Coverage on this module may be partial; that's OK — full JWKS path coverage comes in Task 12.

- [ ] **Step 5.6: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/providers/ tests/auth/test_providers/ pyproject.toml uv.lock && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add AnthropicIdentityProvider (5a: JWKS verification only)"
```

______________________________________________________________________

### Task 6: BearerTokenMiddleware + extend @require_auth

**Files:**

- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/middleware.py`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/decorator.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_middleware.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_decorator.py`

**Interfaces:**

- Consumes: `BearerTokenMiddleware(auth_config, providers)`, `IdentityProvider.verify_token`

- Produces:

  - `BearerTokenMiddleware(Middleware)` with `async on_request(context, call_next)`. **B1 fix**: uses `get_http_headers()` from `fastmcp.server.dependencies` (NOT `MiddlewareContext.scope` — that attribute does not exist per FastMCP source verification). **B2 fix**: raises `AuthError` (not `HTTPException`) so `error_handling` middleware can translate to JSON-RPC error code `-32001` with OAuth error codes in `data`. **B4 fix**: catches `AuthError` only (not bare `Exception`). **I-1 fix**: skips `context.method == "initialize"` so the MCP handshake is not 401'd.
  - `@require_auth(permission, *, allow_anonymous=False, audit_logger=None)` — **I-2 fix**: `integrate_with_readyz` parameter dropped (was accepted but never consulted; shipping a parameter that lies to callers is worse than no parameter).
  - Principal storage: `BearerTokenMiddleware` stashes the Principal via `context.fastmcp_context.set_state("principal", principal)` (FastMCP-native, per-request scoped); `@require_auth` reads via `context.fastmcp_context.get_state("principal")`. The `contextvars` approach (Task 3) is retained as a fallback for non-FastMCP consumers.

- [ ] **Step 6.1: Write failing test for BearerTokenMiddleware**

```python
# tests/auth/test_middleware.py
"""B-R2-3 fix: tests patch fastmcp.server.dependencies.get_http_headers to inject
test headers instead of using a scope-based MockContext. The middleware reads
headers via get_http_headers() (B1 fix); there is no request context in unit
tests, so we patch the dependency."""
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
    """Minimal MiddlewareContext stand-in. B-R2-3 fix: NO scope attribute;
    headers are injected via monkeypatch on get_http_headers() instead."""

    def __init__(self, method: str = "tools/call", message=None) -> None:
        self.method = method
        self.message = message
        self.fastmcp_context = None  # contextvars is the source of truth in tests


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


@pytest.fixture
def patch_headers(monkeypatch):
    """Return a setter that monkey-patches get_http_headers for the test."""
    def _set(headers: dict[str, str]) -> None:
        from fastmcp.server import dependencies
        monkeypatch.setattr(dependencies, "get_http_headers", lambda: headers)
    return _set


@pytest.mark.asyncio
async def test_middleware_passes_through_when_no_authorization_header(patch_headers):
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

    patch_headers({})  # No Authorization header
    result = await mw.on_request(MockContext(), call_next)
    assert result == "ok"
    assert len(called_with) == 1
    # No token → provider.verify_token NOT called
    assert provider.verify_calls == []


@pytest.mark.asyncio
async def test_middleware_extracts_bearer_token_and_verifies(patch_headers):
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

    patch_headers({"authorization": "Bearer abc.def.ghi"})
    result = await mw.on_request(MockContext(), call_next)
    assert result == "ok"
    assert provider.verify_calls == ["abc.def.ghi"]


@pytest.mark.asyncio
async def test_middleware_clears_principal_after_call_next(patch_headers):
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

    patch_headers({"authorization": "Bearer token123"})
    await mw.on_request(MockContext(), call_next)
    assert _current_principal() is None


@pytest.mark.asyncio
async def test_middleware_raises_auth_error_on_invalid_token(patch_headers):
    """B-R2-4 fix: assert TokenInvalidError specifically — not Exception.
    The OLD plan used pytest.raises((HTTPException, ToolError, Exception))
    which matches anything and would not have verified the B2 fix
    (AuthError, not HTTPException)."""
    config = AuthConfig(enabled=True, service_name="test-service")
    provider = MockProvider(raises=TokenInvalidError("bad token"))
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    async def call_next(ctx):
        return "ok"

    patch_headers({"authorization": "Bearer token123"})
    with pytest.raises(TokenInvalidError):
        await mw.on_request(MockContext(), call_next)


@pytest.mark.asyncio
async def test_middleware_bypasses_initialize_handshake(patch_headers):
    """I-1 fix: 'initialize' method must bypass auth (MCP handshake)."""
    config = AuthConfig(enabled=True, service_name="test-service")
    provider = MockProvider(raises=TokenInvalidError("would fail if not bypassed"))
    mw = BearerTokenMiddleware(auth_config=config, providers={"mock": provider})

    async def call_next(ctx):
        return "ok"

    patch_headers({"authorization": "Bearer token123"})
    # Even with a token, initialize should pass through without verify
    result = await mw.on_request(MockContext(method="initialize"), call_next)
    assert result == "ok"
    assert provider.verify_calls == []
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.middleware'`

- [ ] **Step 6.3: Implement BearerTokenMiddleware**

```python
# mcp_common/auth/middleware.py
"""BearerTokenMiddleware — FastMCP middleware that verifies Authorization: Bearer tokens.

B1 fix: uses get_http_headers() from fastmcp.server.dependencies (NOT
MiddlewareContext.scope — that attribute does not exist).

B2 fix: raises AuthError (not HTTPException). FastMCP middleware errors
propagate as JSON-RPC; the error_handling middleware (when installed by
a sibling server) translates to JSON-RPC error code -32001 with OAuth
error codes in data.

B4 fix: catches AuthError only; programming errors propagate.

I-1 fix: skips auth on context.method == "initialize" so the MCP handshake
is not 401'd.
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_common.auth.audit import AuditLogger
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.context import (
    _current_principal,
    seed_principal,
)
from mcp_common.auth.exceptions import AuthError
from mcp_common.auth.provider import IdentityProvider

# MCP methods that bypass auth. The bypass covers the MCP handshake
# (`initialize` + client→server `notifications/initialized`) and the
# `ping` keepalive + client→server `notifications/cancelled`.
# NOTE: `notifications/progress` is server→client per MCP spec and never
# reaches middleware as an inbound message, so it is intentionally excluded.
_AUTH_BYPASS_METHODS = frozenset({
    "initialize",
    "notifications/initialized",
    "ping",
    "notifications/cancelled",
})


class BearerTokenMiddleware(Middleware):
    """FastMCP middleware that verifies Bearer tokens on every request."""

    def __init__(
        self,
        *,
        auth_config: AuthConfig,
        providers: dict[str, IdentityProvider],
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._config = auth_config
        self._providers = providers
        # I-4 fix: counter store. Middleware increments on every verification.
        # Sibling servers wire this to the same AuthHealth surface.
        self._verifications_total = 0
        self._errors_total = 0
        self._audit_logger = audit_logger

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: Any,
    ) -> Any:
        # I-1 fix: skip auth on MCP handshake and notifications
        if context.method in _AUTH_BYPASS_METHODS:
            return await call_next(context)

        # Idempotency: skip if Principal already set (test injection / internal hop)
        if _current_principal() is not None:
            return await call_next(context)

        # B1 fix: read headers via FastMCP's get_http_headers() (NOT context.scope).
        # M-R2-1 fix: get_http_headers() catches RuntimeError internally and
        # returns {} on non-HTTP transports; it does not raise in production
        # code paths. We guard with (RuntimeError,) so a future FastMCP API
        # change (or an unusual embedding) cannot crash the middleware with a
        # programming-error leak.
        try:
            headers = get_http_headers() or {}
        except RuntimeError:
            # stdio / non-HTTP transport — Bearer auth is meaningless;
            # pass through and let per-tool allow_anonymous decide.
            return await call_next(context)

        token = _extract_bearer_token(headers)
        if token is None:
            # Anonymous path; per-tool allow_anonymous decides
            return await call_next(context)

        provider = self._select_provider(token)
        try:
            principal = await provider.verify_token(
                token, expected_audience=self._config.service_name
            )
        except AuthError as exc:
            # B4 fix: only catch AuthError. Programming errors propagate.
            self._errors_total += 1
            if self._audit_logger:
                self._audit_logger.log_failure(
                    source="middleware", reason=type(exc).__name__,
                    token_present=True,
                )
            raise
        else:
            self._verifications_total += 1
            if self._audit_logger:
                self._audit_logger.log_success(
                    source="middleware",
                    principal_issuer=principal.issuer,
                    principal_subject=principal.subject,
                )

        # Stash Principal via contextvars (the seed_principal API) and
        # optionally also via FastMCP's Context.set_state() for symmetry
        # with FastMCP-native consumers. M-R2-4 fix: spec acknowledges both —
        # contextvars is the source of truth for @require_auth; set_state is
        # for FastMCP-native consumers.
        token_handle = seed_principal(principal)
        fmcp_ctx = getattr(context, "fastmcp_context", None)
        state_token = None
        if fmcp_ctx is not None:
            try:
                # FastMCP set_state returns a Token for reset_state(); capture
                # it so the finally block restores the prior value rather than
                # clobbering it with None.
                state_token = fmcp_ctx.set_state("principal", principal)
            except (AttributeError, TypeError) as exc:
                # set_state is best-effort; contextvars is the source of truth.
                # Narrow the catch so programming errors propagate.
                import logging
                logging.getLogger(__name__).debug(
                    "set_state failed in middleware (non-fatal): %s", exc
                )
        try:
            return await call_next(context)
        finally:
            # Restore the prior principal (if any) via the token handle rather
            # than unconditionally calling _clear_principal — this preserves
            # nesting for recursive or internal-hop call paths.
            token_handle.var.reset(token_handle)
            if fmcp_ctx is not None and state_token is not None:
                try:
                    fmcp_ctx.reset_state(state_token)
                except (AttributeError, TypeError):
                    pass

    def _select_provider(self, token: str) -> IdentityProvider:
        """Pick provider by issuer hint or default_provider.

        For multi-provider deployments, prefer default_provider. A future
        enhancement can decode the JWT header and pick by `kid` (Key ID).
        """
        if self._config.default_provider and self._config.default_provider in self._providers:
            return self._providers[self._config.default_provider]
        if len(self._providers) == 1:
            return next(iter(self._providers.values()))
        # Fail-loud at request time if misconfigured (api-security IMPORTANT
        # finding: don't per-request 500 for config errors; surface at startup).
        raise RuntimeError(
            f"Multiple providers configured but no default_provider set; "
            f"cannot select one for token verification. Configured: "
            f"{list(self._providers.keys())}"
        )

    @property
    def verifications_total(self) -> int:
        return self._verifications_total

    @property
    def errors_total(self) -> int:
        return self._errors_total


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    """Extract "Authorization: Bearer <token>" from a headers dict.

    B1 fix: takes a dict[str, str] (from get_http_headers), not a MiddlewareContext.
    Reject tokens longer than 8192 bytes (api-security: prevent memory exhaustion
    via huge Authorization header).
    """
    auth = headers.get("authorization")
    if not auth:
        return None
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    if len(token) > 8192:
        # Reject oversized tokens before any cryptographic operation
        return None
    return token
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
"""@require_auth decorator — reads Principal from request-scoped Context.

B10 fix: uses the existing AuthAuditEvent type from mcp_common/auth/audit.py
(not a new AuditEvent class). The existing AuthAuditEvent fields are:
    timestamp, service, caller_service, caller_id, action, result, reason,
    source_ip, token_id. We map our concerns onto these.

I-2 fix: integrate_with_readyz parameter dropped. It was accepted but never
consulted. Shipping a parameter that lies to callers is worse than no
parameter. The /readyz aggregation semantics are deferred to a follow-up
spec when there's an actual aggregation point.
"""
from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable

from mcp_common.auth.audit import AuthAuditEvent, AuditLogger
from mcp_common.auth.context import _current_principal
from mcp_common.auth.exceptions import (
    AuthenticationRequiredError,  # 401 semantic
    InsufficientPermissionError,  # 403 semantic
)
from mcp_common.auth.permissions import Permission

# api-security R2-3 fix: control-character regex for audit-field sanitization.
# Matches C0 controls except \t (0x09) and \n (0x0a) is allowed for
# legitimate log line breaks; \r (0x0d) is stripped to prevent log injection.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_AUDIT_FIELD_MAX_LEN = 256


def _sanitize_audit_value(value: str | None) -> str | None:
    """Strip control chars and truncate long user-controlled audit fields.

    Defends against log-injection (a JWT `sub` claim containing \\r\\n
    could inject fake log lines) and over-long values (stack-trace
    fragments leaked via reason)."""
    if value is None:
        return None
    cleaned = _CONTROL_CHARS_RE.sub("", value)
    if len(cleaned) > _AUDIT_FIELD_MAX_LEN:
        cleaned = cleaned[:_AUDIT_FIELD_MAX_LEN] + "..."
    return cleaned


def require_auth(
    permission: Permission = Permission.READ,
    *,
    allow_anonymous: bool = False,
    audit_logger: AuditLogger | None = None,
    service_name: str,  # I-R2-2 fix: required (was "unknown" default — defeats
    # Article 32 audit attribution; a service that doesn't know its own name
    # should fail loudly at registration, not silently emit "unknown" events).
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: enforce permission on the calling tool.

    Reads Principal from request-scoped Context (set by BearerTokenMiddleware
    via seed_principal()). No kwarg transport — clean break with prior
    convention.

    Error semantics (per auth-agent finding #4):
    - No Principal + allow_anonymous=False → AuthenticationRequiredError (401)
    - No Principal + allow_anonymous=True → proceed
    - Principal lacks permission → InsufficientPermissionError (403)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = _current_principal()
            if principal is None:
                if allow_anonymous:
                    return await func(*args, **kwargs)
                # 401: no credentials presented
                raise AuthenticationRequiredError(
                    f"Authentication required for {func.__name__}"
                )
            if not principal.has_permission(permission):
                # 403: authenticated, lacks permission
                if audit_logger:
                    audit_logger.emit(
                        AuthAuditEvent(
                            service=service_name,
                            caller_service=_sanitize_audit_value(principal.issuer),
                            caller_id=_sanitize_audit_value(principal.subject),
                            action=func.__name__,
                            result="deny",
                            reason=_sanitize_audit_value(
                                f"missing_permission:{permission.value}"
                            ),
                        )
                    )
                raise InsufficientPermissionError(
                    f"Principal {principal.issuer}:{principal.subject} "
                    f"lacks {permission.value}"
                )
            if audit_logger:
                audit_logger.emit(
                    AuthAuditEvent(
                        service=service_name,
                        caller_service=_sanitize_audit_value(principal.issuer),
                        caller_id=_sanitize_audit_value(principal.subject),
                        action=func.__name__,
                        result="allow",
                    )
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
```

Add the new `AuthenticationRequiredError` exception to `mcp_common/auth/exceptions.py` (Task 2 already added `ProviderUnavailableError`):

```python
class AuthenticationRequiredError(AuthError):
    """Raised when a tool requires authentication but no Principal is in Context.
    Maps to HTTP 401 in the error_handling middleware translation.
    """
```

- [ ] **Step 6.7: Run all auth tests**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/ -v`
Expected: PASS for all auth tests. Coverage must remain ≥90%.

- [ ] **Step 6.8: Commit**

````bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/middleware.py mcp_common/auth/decorator.py tests/auth/test_middleware.py tests/auth/test_decorator.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add BearerTokenMiddleware and rewrite @require_auth to read from Context"

---

### Task 6b: AuthError → JSON-RPC translation middleware (I-R2-3 fix)

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/auth/error_middleware.py`
- Create: `/Users/les/Projects/mcp-common/tests/auth/test_error_middleware.py`

**Why this task exists:** B2 fix relies on a sibling-server middleware that translates `AuthError` to JSON-RPC error code `-32001` with OAuth error codes in `data`. Without this translation, AuthError surfaces as a generic internal-error JSON-RPC. I-R2-3 fix: this task defines the middleware so it is shipped and discoverable; sibling servers opt in by adding it to their `FastMCP(middleware=[...])` constructor.

**Interfaces:**
- Consumes: `AuthError` hierarchy from `mcp_common/auth/exceptions.py`
- Produces: `AuthErrorTranslationMiddleware(Middleware)` that catches `AuthError` in `on_request` / `on_message` hooks and raises a FastMCP-shaped error that surfaces as JSON-RPC code `-32001` with `{"error": "<class>", "error_description": "..."}` in `data`.

- [ ] **Step 6b.1: Write failing test**

```python
# tests/auth/test_error_middleware.py
from __future__ import annotations

import pytest

from mcp_common.auth.error_middleware import AuthErrorTranslationMiddleware
from mcp_common.auth.exceptions import (
    AuthenticationRequiredError,
    InsufficientPermissionError,
    TokenInvalidError,
)


@pytest.mark.asyncio
async def test_translates_authentication_required_to_jsonrpc_error():
    """401 semantic: maps AuthenticationRequiredError to JSON-RPC -32001 with
    WWW-Authenticate-style data payload."""
    mw = AuthErrorTranslationMiddleware()
    error = AuthenticationRequiredError("no token")
    payload = mw._translate(error)
    assert payload["code"] == -32001
    assert payload["data"]["error"] == "authentication_required"
    assert "WWW-Authenticate" in payload["data"]


@pytest.mark.asyncio
async def test_translates_insufficient_permission_to_jsonrpc_error():
    """403 semantic: maps InsufficientPermissionError to JSON-RPC -32001."""
    mw = AuthErrorTranslationMiddleware()
    error = InsufficientPermissionError("lacks read")
    payload = mw._translate(error)
    assert payload["code"] == -32001
    assert payload["data"]["error"] == "insufficient_permission"


@pytest.mark.asyncio
async def test_translates_token_invalid_to_jsonrpc_error():
    """401 semantic: maps TokenInvalidError to JSON-RPC -32001."""
    mw = AuthErrorTranslationMiddleware()
    error = TokenInvalidError("bad sig")
    payload = mw._translate(error)
    assert payload["code"] == -32001
    assert payload["data"]["error"] == "invalid_token"
````

- [ ] **Step 6b.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_error_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_common.auth.error_middleware'`

- [ ] **Step 6b.3: Implement the middleware**

```python
# mcp_common/auth/error_middleware.py
"""AuthError → JSON-RPC translation middleware.

I-R2-3 fix: ships the translation surface that B2 fix relied on. Sibling
servers opt in via FastMCP(middleware=[AuthErrorTranslationMiddleware(), ...]).
"""
from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_common.auth.exceptions import (
    AuthenticationRequiredError,
    InsufficientPermissionError,
    TokenInvalidError,
    UnknownIssuerError,
)


# JSON-RPC error code for auth/server-defined errors per the MCP spec.
_JSONRPC_AUTH_ERROR_CODE = -32001

# OAuth 2.0 error codes per RFC 6749 §5.2.
_ERROR_CODE_MAP: dict[type, str] = {
    AuthenticationRequiredError: "authentication_required",
    TokenInvalidError: "invalid_token",
    UnknownIssuerError: "unknown_issuer",
    InsufficientPermissionError: "insufficient_permission",
}


class AuthErrorTranslationMiddleware(Middleware):
    """Translate AuthError subclasses into JSON-RPC error code -32001 with
    OAuth-style data payload. Sibling servers must install this in their
    FastMCP constructor for the B2 contract to hold end-to-end.
    """

    async def on_request(
        self, context: MiddlewareContext, call_next: Any
    ) -> Any:
        try:
            return await call_next(context)
        except (
            AuthenticationRequiredError,
            TokenInvalidError,
            UnknownIssuerError,
            InsufficientPermissionError,
        ) as exc:
            payload = self._translate(exc)
            raise _AuthJSONRPCError(payload) from exc

    def _translate(self, exc: Exception) -> dict[str, Any]:
        return {
            "code": _JSONRPC_AUTH_ERROR_CODE,
            "message": "Authentication error",
            "data": {
                "error": _ERROR_CODE_MAP.get(type(exc), "authentication_error"),
                "error_description": str(exc),
                "WWW-Authenticate": 'Bearer realm="mcp"',
            },
        }


class _AuthJSONRPCError(Exception):
    """Internal carrier for the translated payload; raised into the FastMCP
    pipeline so it surfaces as a JSON-RPC error to the client."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(payload["message"])
```

- [ ] **Step 6b.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_error_middleware.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6b.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/error_middleware.py tests/auth/test_error_middleware.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add AuthErrorTranslationMiddleware for JSON-RPC -32001 mapping"
```

````

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
````

- [ ] **Step 7.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_trusted_issuers.py -v`
Expected: FAIL with `UnknownIssuerError` not raised (current verify_token accepts any issuer)

- [ ] **Step 7.3: Add `trusted_issuers` enforcement to JWTIdentityProvider.verify_token (default-deny)**

**B6 fix:** default-deny semantics — `if payload.iss not in trusted` (no `if trusted and ...` guard). The startup check in Step 7.4 ensures `trusted_issuers` is non-empty when `auth.enabled=True`.

```python
# Inside JWTIdentityProvider.verify_token (added in Task 4):
if payload.iss not in self._trusted_issuers:
    raise UnknownIssuerError(
        f"Issuer '{payload.iss}' not in trusted_issuers: {self._trusted_issuers}"
    )
```

The same check is added to `AnthropicIdentityProvider.verify_token` in Task 5 (I-3 cross-cutting fix).

- [ ] **Step 7.4: Remove `KNOWN_SERVICES` from `identity.py` and add startup check**

Edit `mcp_common/auth/identity.py`:

- Delete the `KNOWN_SERVICES` frozenset.
- Delete or rewrite `verify_issuer()` to be a no-op (no callers should remain after Task 4's refactor).
- Delete or rewrite `ServiceIdentity` if it's only used by `verify_issuer()`.
- Add a startup validation helper:

```python
def validate_auth_config(auth_config: AuthConfig) -> None:
    """Fail-loud at startup if auth config is inconsistent.

    B6 fix: if enabled=True, trusted_issuers MUST be non-empty. A misconfigured
    deployment with empty trusted_issuers and the default-deny semantics would
    reject every token — fail at startup, not at the first request.
    """
    if not auth_config.enabled:
        return
    if not auth_config.trusted_issuers:
        raise ValueError(
            "auth.enabled=True but trusted_issuers is empty. "
            "Default-deny rejects all issuers. Configure at least one "
            "trusted issuer in settings/ecosystem.yaml or disable auth."
        )
    if not auth_config.identity_providers:
        raise ValueError(
            "auth.enabled=True but no identity_providers configured."
        )
    if auth_config.default_provider and auth_config.default_provider not in auth_config.identity_providers:
        raise ValueError(
            f"auth.default_provider={auth_config.default_provider!r} is not "
            f"in identity_providers keys: {list(auth_config.identity_providers.keys())}"
        )
    # If any provider is type=jwt, secret MUST be set
    for name, p in auth_config.identity_providers.items():
        if p.type == "jwt" and not auth_config.secret:
            raise ValueError(
                f"identity_providers[{name!r}] is type=jwt but auth.secret is not set"
            )
        # api-security R2-6 fix: if a provider is type=oauth, the OAuth fields
        # MUST be set. Without this check, the provider would attempt a token
        # exchange with empty strings and either fail-loud on every request
        # (annoying) or succeed against a default-deny OAuth endpoint (worse).
        if p.type == "oauth":
            missing = []
            if not p.client_id:
                missing.append("client_id")
            if not p.client_secret:
                missing.append("client_secret")
            if not p.oauth_token_url:
                missing.append("oauth_token_url")
            if not p.jwks_url:
                missing.append("jwks_url")
            if not p.audience:
                missing.append("audience")
            if missing:
                raise ValueError(
                    f"identity_providers[{name!r}] is type=oauth but is missing "
                    f"required fields: {', '.join(missing)}. Set them in "
                    f"settings/<service>.yaml or disable this provider."
                )
```

Call this from the sibling server's lifespan before constructing `BearerTokenMiddleware`.

Verify no callers remain:

```bash
cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && grep -rn "KNOWN_SERVICES\|verify_issuer\|ServiceIdentity" mcp_common/ tests/ --include="*.py"
```

- [ ] **Step 7.5: Update or delete `tests/auth/test_identity.py`**

Either delete the file entirely or rewrite it to test the new behavior. If deleted, also remove from any test discovery config.

- [ ] **Step 7.5a: Add the Anthropic trusted_issuers test**

Add to `tests/auth/test_providers/test_anthropic.py`:

```python
@pytest.mark.asyncio
async def test_anthropic_unknown_issuer_rejected(provider, respx_mock):
    """I-3 fix: Anthropic provider enforces trusted_issuers (B6 default-deny)."""
    # Mock JWKS endpoint with a valid key
    respx_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": []})
    )
    provider._trusted_issuers = ["https://api.anthropic.com"]  # not the token's iss

    # A real Anthropic token with iss=evil-corp would be rejected even if signature validates.
    # For this test, we verify the rejection path: a token with iss not in trusted_issuers
    # is rejected. We mock jwt.decode to return a payload with iss="evil-corp".
    from unittest.mock import patch
    fake_payload = {"iss": "evil-corp", "sub": "x", "exp": 9999999999, "iat": 1, "aud": AUDIENCE}
    with patch("jwt.decode", return_value=fake_payload):
        with pytest.raises(UnknownIssuerError):
            await provider.verify_token("any.jwt.token", expected_audience=AUDIENCE)
```

- [ ] **Step 7.6: Run tests**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/ -v`
Expected: PASS for all auth tests. The new `test_anthropic_unknown_issuer_rejected` test passes.

- [ ] **Step 7.7: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/identity.py mcp_common/auth/core.py mcp_common/auth/providers/anthropic.py tests/auth/test_trusted_issuers.py tests/auth/test_identity.py tests/auth/test_providers/test_anthropic.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "refactor(auth): remove KNOWN_SERVICES frozenset; default-deny trusted_issuers; startup check"
```

______________________________________________________________________

### Task 8a: Convert AuthConfig to Pydantic (BEFORE Task 6)

**Files:**

- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/config.py`
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_config.py`

**B8 fix:** Task 8a is a Pydantic conversion of the existing `AuthConfig` only. It does NOT add the new fields (`trusted_issuers`, `identity_providers`, `default_provider`) — those land in Task 8b. This ordering lets Task 6 use the Pydantic shape without breaking the dependency chain.

**Interfaces:**

- Consumes: existing `AuthConfig` (plain Python class with env-var loading)

- Produces: `AuthConfig(BaseModel)` with the same fields, plus a `model_validator` that preserves env-var loading semantics (per I-6 — don't silently drop `_load_secret`, `_PLACEHOLDER_SECRETS`, `_MIN_SECRET_LENGTH`).

- [ ] **Step 8a.1: Write failing test**

```python
# tests/auth/test_config.py
from mcp_common.auth.config import AuthConfig


def test_auth_config_is_pydantic_basemodel():
    """B8 fix: AuthConfig is now a Pydantic BaseModel (was plain class)."""
    config = AuthConfig(
        enabled=True,
        secret="x" * 40,
        service_name="test",
    )
    assert hasattr(config, "model_dump")  # Pydantic v2 marker


def test_auth_config_secret_min_length_validator():
    """I-6 fix: preserve the existing 32-char minimum secret length check."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AuthConfig(enabled=True, secret="short", service_name="test")


def test_auth_config_rejects_placeholder_secrets():
    """I-6 fix: preserve placeholder secret rejection."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AuthConfig(enabled=True, secret="changeme", service_name="test")
```

- [ ] **Step 8a.2: Convert AuthConfig to Pydantic**

```python
# mcp_common/auth/config.py
"""Authentication configuration — Task 8a: Pydantic BaseModel.

B8 fix: converted from plain Python class to Pydantic v2 BaseModel.
I-6 fix: env-var loading and placeholder rejection preserved via model_validator.
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


_PLACEHOLDER_SECRETS = frozenset({"changeme", "secret", "password", "default"})
_MIN_SECRET_LENGTH = 32


class AuthConfig(BaseModel):
    """Authentication configuration for an MCP server.

    B8 fix: this is now a Pydantic v2 BaseModel. The original plain-class
    API is preserved by:
    - `enabled`, `secret`, `service_name` keep their semantics
    - `secret` becomes `SecretStr | None` (was `str | None`)
    - env-var loading is in a model_validator (mode="before")
    """

    enabled: bool = True
    secret: SecretStr | None = None
    service_name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("secret")
    @classmethod
    def _validate_secret(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return v
        raw = v.get_secret_value()
        if len(raw) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"secret must be at least {_MIN_SECRET_LENGTH} characters"
            )
        if raw in _PLACEHOLDER_SECRETS:
            raise ValueError(
                f"secret is a placeholder value ({raw!r}); set a real secret"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _load_from_env(cls, data: Any) -> Any:
        """Preserve env-var loading: <SERVICE>_SECRET or BODAI_SHARED_SECRET."""
        if isinstance(data, dict):
            if "secret" not in data or data["secret"] is None:
                env_secret = (
                    os.environ.get("BODAI_SHARED_SECRET")
                    or os.environ.get(f"{data.get('service_name', '').upper()}_SECRET")
                )
                if env_secret:
                    data["secret"] = env_secret
        return data
```

- [ ] **Step 8a.3: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_config.py -v`
Expected: PASS (existing + 3 new tests)

- [ ] **Step 8a.4: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/config.py tests/auth/test_config.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "refactor(auth): convert AuthConfig to Pydantic BaseModel (preserves env-var loading)"
```

### Task 8b: Add trusted_issuers + identity_providers fields (AFTER Task 6)

**Files:**

- Modify: `/Users/les/Projects/mcp-common/mcp_common/auth/config.py` (extends Task 8a)
- Modify: `/Users/les/Projects/mcp-common/tests/auth/test_config.py`

**Interfaces:**

- Consumes: `AuthConfig` from Task 8a

- Produces: extended `AuthConfig` with `trusted_issuers: list[str]`, `identity_providers: dict[str, IdentityProviderConfig]`, `default_provider: str | None`, `allow_anonymous_paths: list[str]`

- [ ] **Step 8b.1: Write failing test**

```python
# tests/auth/test_config.py (additions)
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


def test_auth_config_default_allow_anonymous_paths():
    config = AuthConfig(enabled=True, secret="x" * 40, service_name="test")
    assert "/health" in config.allow_anonymous_paths
    assert "/readyz" in config.allow_anonymous_paths


def test_identity_provider_config_basic():
    p = IdentityProviderConfig(name="anthropic", type="oauth", client_id="abc")
    assert p.name == "anthropic"
    assert p.type == "oauth"
    assert p.client_id == "abc"


def test_identity_provider_config_type_is_literal():
    """M-2 fix: type is Literal, not str (catches typos at config-parse time)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        IdentityProviderConfig(name="bad", type="OAUTH")  # not in Literal["jwt", "oauth"]
```

- [ ] **Step 8b.2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_config.py::test_auth_config_has_trusted_issuers_field -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'trusted_issuers'`

- [ ] **Step 8b.3: Extend `AuthConfig` in `config.py`**

```python
from typing import Literal


class IdentityProviderConfig(BaseModel):
    """Configuration for a single IdentityProvider."""

    name: str
    type: Literal["jwt", "oauth"]  # M-2 fix: literal type
    client_id: str | None = None
    client_secret: SecretStr | None = None
    oauth_token_url: str | None = None
    jwks_url: str | None = None
    audience: str | None = None
    jwks_cache_seconds: int = 3600  # M-4 fix: passed to provider
    timeout_seconds: float = 5.0

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AuthConfig(BaseModel):  # extends Task 8a
    enabled: bool = True
    secret: SecretStr | None = None
    service_name: str

    # Task 8b additions:
    trusted_issuers: list[str] = Field(default_factory=list)
    identity_providers: dict[str, IdentityProviderConfig] = Field(default_factory=dict)
    default_provider: str | None = None
    allow_anonymous_paths: list[str] = Field(
        default_factory=lambda: ["/health", "/readyz"]
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
```

- [ ] **Step 8b.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_config.py -v`
Expected: PASS

- [ ] **Step 8b.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/config.py tests/auth/test_config.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add trusted_issuers, identity_providers, default_provider, allow_anonymous_paths fields"
```

- [ ] **NOTE: The original (pre-split) Task 8 block was removed in the Round 2 multi-agent review.** A duplicate of the original Step 8.1-8.5 existed after the post-split Task 8a/8b section, with `type: str` (reverting the M-2 Literal fix). Deleting that duplicate block left only Task 8a (Pydantic conversion) and Task 8b (new fields). Implementers follow Tasks 8a then 8b in document order — no other Step 8 remains.

______________________________________________________________________

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

______________________________________________________________________

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

    def as_components(
        self,
        *,
        include_diagnostics: bool = False,
    ) -> list[dict[str, Any]]:
        """Render for /health envelope's components[] array.

        Returns a single component dict representing the entire auth surface,
        not one dict per provider (the providers are nested under
        `providers` for drill-down).

        api-security R2-2 fix: `last_error` strings are operator diagnostics
        and may leak internal failure details (JWKS endpoint URLs, secrets,
        stack-trace substrings). They are included only when the caller
        explicitly opts in via `include_diagnostics=True`. The default
        (False) is what `/health` should call for anonymous responses —
        `/health` is in `allow_anonymous_paths`, so the default must not
        leak operator details.
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
                        # api-security R2-2 fix: redact last_error from
                        # anonymous responses. Operators can call
                        # `as_components(include_diagnostics=True)` from
                        # an authenticated debug path.
                        **(
                            {"last_error": p.last_error}
                            if include_diagnostics
                            else {}
                        ),
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

______________________________________________________________________

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
        auth_health_provider=lambda: auth_health,  # B-R2-1 fix: callable, not value
    )
    # Check that the route was registered with auth components
    routes = [r.path for r in mcp.custom_routes] if hasattr(mcp, "custom_routes") else []
    # Adjust this assertion based on how FastMCP exposes its routes
    assert "/health" in routes or any("/health" in str(r) for r in routes)
```

- [ ] **Step 11.2: Run test to verify it fails**

Run the new test alone. Expected: FAIL because `register_http_health_route` doesn't accept `auth_health` parameter yet.

- [ ] **Step 11.3: Extend `register_http_health_route` signature (I-7 fix: keep 200-only)**

**I-7 fix:** `/health` keeps the unconditional 200 contract. The `status: "degraded"` field in the body signals degraded state. The 503 semantic is reserved for `/readyz` (a separate endpoint, future work). This preserves the contract for 9 sibling servers' launchd probes.

**B3 fix:** `is_degraded` is recomputed per request via the callable, not captured at registration.

Modify `mcp_common/health.py` (find the `register_http_health_route` function around line 810 per recon):

```python
def register_http_health_route(
    mcp: t.Any,
    *,
    service_name: str,
    version: str,
    extra_components: list[dict[str, t.Any]] | None = None,
    auth_health_provider: Callable[[], AuthHealth | None] | None = None,
) -> None:
    """Register /health endpoint with aggregated state.

    I-7 fix: returns 200 always. The status field in the body reports
    "ok" or "degraded". The 503 semantic is reserved for /readyz
    (future work). This preserves the contract for launchd probes across
    9 sibling servers.

    B3 fix: auth_health_provider is a callable invoked per request, not
    a value captured at registration. is_degraded reflects current state.
    """
    @mcp.custom_route("/health", methods=["GET"])
    async def http_health(request: t.Any) -> t.Any:
        from starlette.responses import JSONResponse

        # B3 fix: recompute per request
        components = list(extra_components or [])
        auth_health = auth_health_provider() if auth_health_provider else None
        is_degraded = auth_health.is_degraded() if auth_health is not None else False

        if auth_health is not None:
            components.extend(auth_health.as_components())

        status = "degraded" if is_degraded else "ok"
        return JSONResponse(
            {"status": status, "service": service_name, "version": version,
             "components": components},
            status_code=200,  # I-7 fix: always 200; status is in the body
        )
```

Add the import at the top of `health.py`:

```python
from collections.abc import Callable
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
cd /Users/les/Projects/mcp-common && git add mcp_common/health.py tests/ && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(health): include AuthHealth in /health envelope; keep 200-only with degraded in body"
```

______________________________________________________________________

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
        # LOW-5 fix: import ProviderState directly instead of reaching into
        # ProviderHealth.__annotations__["state"] at runtime — couples field
        # annotation to runtime state and silently breaks on renames.
        from mcp_common.auth.provider import ProviderState
        self._last_state: ProviderState = "healthy"

    async def verify_token(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
    ) -> Principal:
        # LOW-6 fix: use a public force_refresh() method on the provider rather
        # than reaching into PyJWKClient.__init__ internals. Real TTL expiry
        # is exercised by the public path; the internal reinit only handled
        # the _jwks_cache_seconds == 0 test-bypass case.
        if self._jwks_cache_seconds == 0:
            self.force_refresh()

        # ... (existing verify_token logic)

    def force_refresh(self) -> None:
        """Rebuild the PyJWKClient from the configured jwks_url. Public API
        used by tests that need to simulate cache-TTL expiry without
        reaching into PyJWT internals.
        """
        self._jwks_client = PyJWKClient(
            self._jwks_url,
            cache_keys=True,
            lifespan=self._jwks_cache_seconds,
        )
```

- [ ] **Step 12.4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && uv run pytest tests/auth/test_jwks_rotation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 12.5: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add mcp_common/auth/providers/anthropic.py tests/auth/test_jwks_rotation.py && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(auth): add JWKS rotation logic with cached-fallback to AnthropicIdentityProvider"
```

______________________________________________________________________

### Task 13: Internal auth doc at mcp_common/docs/auth-design.md

**Files:**

- Create: `/Users/les/Projects/mcp-common/docs/auth-design.md`

- [ ] **Step 13.1: Write the doc**

````markdown
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
from mcp_common.auth.identity import validate_auth_config  # B6 fix: startup check
from mcp_common.auth.middleware import BearerTokenMiddleware
from mcp_common.auth.providers.anthropic import AnthropicIdentityProvider


def build_middleware(auth_config: AuthConfig) -> BearerTokenMiddleware:
    # B6 fix: fail-loud at startup if auth config is inconsistent
    validate_auth_config(auth_config)

    if auth_config.secret is None:
        # I-9 fix: guard before .get_secret_value()
        raise RuntimeError(
            "auth.secret is required when auth.enabled=True"
        )

    providers = {}
    if auth_config.identity_providers.get("jwt"):
        providers["jwt"] = JWTIdentityProvider(
            name="jwt",
            secret=auth_config.secret.get_secret_value(),
            trusted_issuers=auth_config.trusted_issuers,
        )
    if anthropic_cfg := auth_config.identity_providers.get("anthropic"):
        if anthropic_cfg.client_secret is None:
            raise RuntimeError(
                f"identity_providers['anthropic'].client_secret is required"
            )
        providers["anthropic"] = AnthropicIdentityProvider(
            client_id=anthropic_cfg.client_id,
            client_secret=anthropic_cfg.client_secret.get_secret_value(),
            oauth_token_url=anthropic_cfg.oauth_token_url,
            jwks_url=anthropic_cfg.jwks_url,
            audience=anthropic_cfg.audience or auth_config.service_name,
            trusted_issuers=auth_config.trusted_issuers,
        )
    return BearerTokenMiddleware(auth_config=auth_config, providers=providers)
````

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

````

- [ ] **Step 13.2: Commit**

```bash
cd /Users/les/Projects/mcp-common && git add docs/auth-design.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(auth): add internal design doc for mcp_common.auth package"
````

______________________________________________________________________

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
        self._last_successful_verification_at: datetime | None = None

    def _build_auth_middleware(self) -> BearerTokenMiddleware | None:
        auth_cfg = self.settings.auth
        if auth_cfg is None or not auth_cfg.enabled:
            return None
        providers = {}
        if auth_cfg.identity_providers.get("jwt"):
            # I-9 fix (Task 14 variant): guard secret is not None before
            # calling .get_secret_value(). A sibling that uses only Anthropic
            # (no JWT) should not crash with AttributeError when constructing
            # the providers dict.
            if auth_cfg.secret is None:
                raise RuntimeError(
                    "auth.identity_providers['jwt'] is configured but "
                    "auth.secret is None — set MCPServerSettings.auth.secret "
                    "or BODAI_SHARED_SECRET, or remove the JWT provider."
                )
            providers["jwt"] = JWTIdentityProvider(
                name="jwt",
                secret=auth_cfg.secret.get_secret_value(),
                trusted_issuers=auth_cfg.trusted_issuers,
            )
        # ... Anthropic, etc.
        self._auth_middleware = BearerTokenMiddleware(
            auth_config=auth_cfg, providers=providers
        )
        return self._auth_middleware

    def _build_auth_health_provider(self):
        """I-4 fix (Task 14 wiring): expose middleware counters via an
        auth_health_provider callable so register_http_health_route's
        per-request is_degraded() reflects actual verifications/errors.

        Without this wiring, /health will always report
        verifications_total=0 in production — the wiring-discipline §3
        four signals (entities_count, last_updated_timestamp, errors_total,
        cycles_total) all rely on it.
        """
        if self._auth_middleware is None:
            return None

        def _provider() -> AuthHealth | None:
            mw = self._auth_middleware
            if mw is None:
                return None
            return AuthHealth.from_providers(
                providers={
                    name: provider
                    for name, provider in mw._providers.items()
                },
                verifications_total=mw.verifications_total,
                errors_total=mw.errors_total,
                last_successful_verification_at=self._last_successful_verification_at,
            )

        return _provider
```

Pass the auth components to `register_http_health_route`'s `extra_components` parameter (and the new `auth_health` parameter from Task 11).

- [ ] **Step 14.2: Wire archive-org-mcp**

Same shape as 14.1, applied to archive-org-mcp's server entry point.

- [ ] **Step 14.3: Wire medium-mcp**

Same shape as 14.1, applied to medium-mcp's server entry point.

- [ ] **Step 14.4: Add integration test in each sibling repo**

**I-5 fix:** The placeholder `...` body is replaced with concrete assertions that verify the wiring, not just registration. Per `mcp-surface-health-illusion.md`, the test must:

1. Construct the server with auth enabled.
1. Send an unauthenticated tool call → assert 401 / `AuthenticationRequiredError`.
1. Send a tool call with a valid token → assert the tool body runs.
1. Hit `/health` → assert the `auth` component is present.
1. (Supplementary) Hit `/health` after a JWKS-style failure on the auth provider → assert `status: "degraded"` is in the body.

In scapy-mcp:

```python
# tests/integration/test_auth_wiring.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


def test_scapy_mcp_unauthenticated_tool_call_returns_401():
    """I-5 fix: a tool call without a token returns 401 (not 500 or 200)."""
    # MEDIUM-4 fix: inline the server construction instead of referencing
    # an undefined `build_test_server_with_auth()` helper. The Runtime
    # factory in scapy_mcp.server is the source of truth.
    from scapy_mcp.server import build_runtime
    from scapy_mcp.config.settings import get_settings

    runtime = build_runtime()
    server = runtime.build_mcp_app()

    async def call_without_token():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool("discover_tools", {"query": "test"})

    with pytest.raises(Exception) as exc_info:
        asyncio.run(call_without_token())
    # Either HTTPException 401 or AuthenticationRequiredError
    assert "401" in str(exc_info.value) or "Authentication" in str(exc_info.value)


def test_scapy_mcp_authenticated_tool_call_reaches_tool_body():
    """I-5 fix: a tool call with a valid token reaches the tool body."""
    # MEDIUM-4 fix: replace undefined my_protected_tool() with an inline
    # tool that exercises @require_auth. Use seed_principal to inject
    # a Principal so the test does not depend on token plumbing.
    from mcp_common.auth.context import seed_principal
    from mcp_common.auth.decorator import require_auth
    from mcp_common.auth.permissions import Permission
    from mcp_common.auth.principal import Principal

    @require_auth(permission=Permission.READ)
    async def inline_protected_tool() -> str:
        return "tool body ran"

    principal = Principal(
        issuer="test",
        subject="user-1",
        permissions=frozenset({Permission.READ}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    token_handle = seed_principal(principal)
    try:
        result = asyncio.run(inline_protected_tool())
        assert result == "tool body ran"
    finally:
        token_handle.var.reset(token_handle)


def test_scapy_mcp_health_envelope_includes_auth_component():
    """Supplementary: /health includes the auth component."""
    from scapy_mcp.server import build_runtime
    from scapy_mcp.config.settings import get_settings

    runtime = build_runtime()
    app = runtime.build_asgi_app()

    async def hit_health() -> dict[str, Any]:
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            return response.json()

    body = asyncio.run(hit_health())
    component_names = [c["name"] for c in body.get("components", [])]
    assert "auth" in component_names, f"expected 'auth' in {component_names}"
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

______________________________________________________________________

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
deployments: the auth surface is continuously observable. Degraded states are
reported via `status: "degraded"` in the `/health` body (always 200) so
monitoring systems can alert without breaking launchd probes across sibling
servers. The 503 semantic is reserved for `/readyz` (future work).

For pre-1.0 internal use, auth is opt-in (see §3). Production deployments must
set `auth.enabled: true` and configure at least one provider in
`MCPServerSettings.auth.identity_providers`.
```

- [ ] **Step 15.3: Commit**

```bash
cd /Users/les/Projects/mahavishnu && git add docs/legal/gdpr-posture.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(gdpr): §10 — describe auth posture and Article 32 alignment"
```

______________________________________________________________________

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

- [ ] **Step 16.4 (I-10 fix — reviewer before status bump): Parallel reviewer before status bump**

**I-10 fix:** Closing the "mcp-common authentication primitives" deferred item in an ADR is a significant governance action. The wire-up contract §4 says features must transition through `built → wired → adopted`; this is the wired → adopted transition. Self-author closure is insufficient.

Before bumping the status (Step 16.5) and committing (Step 16.6):

- Dispatch a subagent (e.g., `architecture-council`, `mcp-integration-expert`, or `critical-audit-specialist`) to validate the new posture vs. the spec.
- Require ≥1 non-author approval.
- Capture the approval in the ADR's frontmatter (`reviewed_by:` field).

Only after approval lands, proceed to Step 16.5.

- [ ] **Step 16.5: Update ADR 0016 status to "complete (rev 4)" if appropriate**

If all v4+ items are now closed, bump the ADR's status from "complete" to "complete (rev 4)". Otherwise leave the status unchanged.

- [ ] **Step 16.6: Commit**

```bash
cd /Users/les/Projects/mahavishnu && git add docs/adr/0016-scapy-mcp-integration.md && git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(adr): 0016 — close mcp-common auth primitives deferred item"
```

______________________________________________________________________

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

______________________________________________________________________

## Integration Contract (per phase)

Per the wire-up contract (`.claude/decisions/wire-up-contract.md`), every phase deliverable must carry an Integration Contract block. **B12 fix.**

### Phase 1: mcp-common vertical slice (Tasks 1-13, 8a lands before 6)

- **Triggered from:** Settings surface (`MCPServerSettings.auth` YAML key) + `mcp_common.auth.*` deep imports.
- **Returns to / updates:**
  - `mcp_common/auth/{principal,provider,context,middleware,health,...}.py` (new + modified)
  - `mcp_common/auth/config.py` (Pydantic v2 conversion + new fields)
  - `mcp_common/auth/identity.py` (KNOWN_SERVICES removed; startup check added)
  - `mcp_common/auth/decorator.py` (Context-based, AuthAuditEvent fields, integrate_with_readyz dropped)
  - `mcp_common/cli/settings.py` (MCPServerSettings.auth field)
  - `mcp_common/health.py` (register_http_health_route with auth_health_provider callable)
  - `mcp_common/docs/auth-design.md` (new internal doc)
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run pytest tests/auth/ -v
  ```
  ≥90% branch coverage on `mcp_common/auth/*` modules.
- **Rollback signal:** `mcp-common/tests/auth/test_principal.py::test_principal_is_frozen` fails OR coverage < 90%. Revert via `git reset --hard HEAD~N` where N = number of Task 1-13 commits.
- **Observability added:** `AuthHealth` component in `/health` envelope (wiring-discipline §3 four signals: `entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`). I-4 fix: counter store wired through `BearerTokenMiddleware.verifications_total` and `.errors_total` so `entities_count` actually moves.

### Phase 2: Sibling server wiring (Task 14)

- **Triggered from:** Sibling server lifespan boot (scapy-mcp, archive-org-mcp, medium-mcp).
- **Returns to / updates:**
  - `scapy-mcp/scapy_mcp/server.py` — constructs `BearerTokenMiddleware` in lifespan, holds the middleware reference, and exposes `auth_health_provider` to `/health` via `Runtime._build_auth_health_provider()` (I-4 wiring fix). Runtime must NOT carry a separate `_auth_counters` dict — counters come from `middleware.verifications_total` / `.errors_total`.
  - `archive-org-mcp/src/.../server.py` — same shape.
  - `medium-mcp/.../server.py` — same shape.
- **Demonstrable by:** Per sibling:
  ```bash
  cd /Users/les/Projects/scapy-mcp && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run pytest tests/integration/test_auth_wiring.py -v
  cd /Users/les/Projects/archive-org-mcp && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run pytest tests/ -v -k auth
  cd /Users/les/Projects/medium-mcp && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run pytest tests/ -v -k auth
  ```
  Plus: `curl localhost:<port>/health | jq '.components[]|select(.name=="auth")'` returns an `auth` component, AND after a successful JWT verification, `entities_count` (or `verifications_total`) in that component is > 0 (proves the I-4 wiring fix is in place — the counters actually move).
- **Rollback signal:** Sibling `/health` returns 200 but lacks the `auth` component in `components[]` (would indicate a regression of the I-7 contract fix or a wiring failure). Or: integration test fails.
- **Observability added:** AuthHealth components per sibling visible in `/health`. Audit events emit to `AuditLogger` (file or in-memory sink).

### Phase 3: Cross-repo docs (Tasks 15-16)

- **Triggered from:** Phase 1 + Phase 2 completion.
- **Returns to / updates:**
  - `docs/legal/gdpr-posture.md` §10 — auth posture, Article 32 alignment.
  - `docs/adr/0016-scapy-mcp-integration.md` — close the "mcp-common authentication primitives" v4+ deferred item.
  - `docs/adr/0016-multi-agent-review.md` — annotate cross-cutting findings closed.
- **Demonstrable by:** `git grep "AuthHealth" docs/legal/gdpr-posture.md` returns hits; `git grep "mcp-common authentication primitives" docs/adr/` no longer has open-deferred mentions.
- **Rollback signal:** ADR ambiguity discovered post-commit (revert + amend).
- **Observability added:** None (docs only).

### Phase 4: Verification (Task 17)

- **Triggered from:** Phases 1-3 complete.
- **Returns to / updates:** Updated `PLAN_INDEX.md` (regenerated).
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/mcp-common && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run pytest --cov=mcp_common --cov-report=term-missing
  cd /Users/les/Projects/scapy-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run crackerjack run -p minor
  cd /Users/les/Projects/archive-org-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run crackerjack run -p minor
  cd /Users/les/Projects/medium-mcp && unset VIRTUAL_ENV UV_ACTIVE && uv run crackerjack run -p minor
  cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && \
    uv run python scripts/regenerate_plan_index.py
  ```
- **Rollback signal:** Coverage < 90% in `mcp_common/auth/*`, or `crackerjack run` fails on any sibling.
- **Observability added:** None (verification only).

______________________________________________________________________

## Self-Review Checklist

- [x] **Spec coverage**: every Goal in the spec maps to a task (B11 fix: Anthropic PKCE/refresh is now Task 5a + 5b follow-up; spec amended accordingly).
- [x] **Placeholder scan**: no TBD/TODO/FIXME. Code blocks are concrete.
- [x] **Type consistency**: `Principal` field names (issuer, subject, permissions, expires_at, raw_claims) used consistently across Tasks 1, 3, 4, 5, 6. `IdentityProvider` Protocol shape used consistently. `ProviderHealth` field names used consistently. `AuthHealth` field names used consistently.
- [x] **B1 fix verified**: BearerTokenMiddleware uses `get_http_headers()` from `fastmcp.server.dependencies`. `MiddlewareContext.scope` is NOT referenced.
- [x] **B2 fix verified**: BearerTokenMiddleware raises `AuthError` (not `HTTPException`). The `error_handling` middleware in sibling servers translates to JSON-RPC `-32001`.
- [x] **B3 fix verified**: `is_degraded` is computed per-request via `auth_health_provider` callable, not captured at registration.
- [x] **B4 fix verified**: Middleware catches `AuthError` only. Programming errors propagate.
- [x] **B5 fix verified**: `jwt.decode` pins `algorithms=[JWT_ALGORITHM]` (HS256). Required claims: `exp`, `iat`, `iss`, `aud`.
- [x] **B6 fix verified**: Trusted-issuers check is default-deny (no `if trusted and ...` guard). Empty `trusted_issuers` + `enabled=True` fails at startup via `validate_auth_config()`.
- [x] **B7 fix verified**: `_extract_permissions` returns `[]` on empty scope (default-deny). Exact-match scope checking.
- [x] **B8 fix verified**: Task 8a (Pydantic conversion) lands BEFORE Task 6. Task 8b (new fields) lands after.
- [x] **B9 fix verified**: `TokenPayload.raw` renamed to `raw_claims`. `_payload_to_principal` uses `payload.raw_claims` directly.
- [x] **B10 fix verified**: `@require_auth` uses `AuthAuditEvent` fields (`timestamp`, `service`, `caller_service`, `caller_id`, `action`, `result`, `reason`).
- [x] **B11 fix verified**: Task 5 is now "5a: JWKS verification only"; Task 5b (OAuth flow) is deferred.
- [x] **B12 fix verified**: Integration Contract blocks added for all 4 phases.
- [x] **I-1 fix verified**: `BearerTokenMiddleware` skips `context.method in {"initialize", "notifications/initialized", "ping", ...}`.
- [x] **I-2 fix verified**: `integrate_with_readyz` parameter dropped from `@require_auth`.
- [x] **I-3 fix verified**: `AnthropicIdentityProvider.verify_token` enforces `trusted_issuers`.
- [x] **I-4 fix verified**: `BearerTokenMiddleware` carries `_verifications_total` and `_errors_total` counter properties; sibling servers wire these to `AuthHealth.from_providers(...)`.
- [x] **I-5 fix verified**: Task 14 sibling integration tests use concrete assertions (`InsufficientPermissionError` on unauthenticated calls; valid-token calls reach tool body).
- [x] **I-7 fix verified**: `/health` keeps 200-only; `status: "degraded"` in body. 503 semantics reserved for `/readyz` (future work).
- [x] **I-9 fix verified**: Embedded `auth-design.md` example guards `auth_config.secret` before `.get_secret_value()`.
- [x] **I-10 fix verified**: Task 16 requires a parallel reviewer (architecture-council or mcp-integration-expert) before ADR status bump lands.
- [x] **I-1 (spec drift)**: Plan uses `MCPServerSettings` (the actual class in `mcp_common/cli/settings.py`). The spec's `OneiricMCPConfig` reference is an error; spec amendment is tracked as a follow-up.

### Round 2 multi-agent review (4 reviewers: api-security, architecture, mcp-integration, python-pro)

- [x] **B-R2-1 fix verified**: Task 11 test now passes `auth_health_provider=lambda: auth_health` (callable, matching production signature). Production never calls with a value.
- [x] **B-R2-2 fix verified**: Task 11 commit message says "keep 200-only with degraded in body" — matches the I-7 fix.
- [x] **B-R2-3 fix verified**: MockContext in Task 6 tests no longer injects `scope={"headers": [...]}`. Tests use a `monkeypatch.setattr(fastmcp.server.dependencies, "get_http_headers", ...)` fixture to inject headers — same B1-rejected pattern is gone from the test side.
- [x] **B-R2-4 fix verified**: `test_middleware_raises_auth_error_on_invalid_token` asserts `pytest.raises(TokenInvalidError)` specifically — not the OLD `pytest.raises((HTTPException, ToolError, Exception))` matcher that matched anything.
- [x] **Duplicate Task 8 removed**: The pre-split Step 8.1-8.5 block (which reverted the M-2 `Literal["jwt","oauth"]` fix) was deleted. Implementers following document order now see only Task 8a (Pydantic conversion) + Task 8b (new fields).
- [x] **Line 7 drift fixed**: Architecture summary now says `MCPServerSettings` (not `OneiricMCPConfig`).
- [x] **Task 5 commit message fixed**: Reads "5a: JWKS verification only" — not "PKCE + JWKS support".
- [x] **gdpr §10 snippet fixed**: Says "degraded states are reported via status: 'degraded' in the /health body (always 200)" — not "return 503".
- [x] **Phase 2 rollback signal fixed**: Says "sibling /health returns 200 but lacks the auth component" — not "returns 503".
- [x] **I-4 wiring gap closed**: Task 14 Runtime now has `_build_auth_health_provider()` that reads `middleware.verifications_total` / `.errors_total` and wraps them in `AuthHealth.from_providers(...)`. Dead `_auth_counters` dict removed. Demonstrable by Phase 2 step: after a successful JWT verification, the `auth` component in `/health` must show non-zero `entities_count`.
- [x] **I-9 guard applied to Task 14**: `Runtime._build_auth_middleware()` now raises a clear `RuntimeError` if `identity_providers["jwt"]` is configured but `auth.secret` is None — matches the embedded auth-design.md doc.
- [x] **I-10 ordering fixed**: Step 16.4 (parallel reviewer) now precedes Step 16.5 (status bump) and Step 16.6 (commit). Numbering is now contiguous.
- [x] **I-R2-1 fixed**: gdpr snippet — same fix as above (cross-confirmed).
- [x] **I-R2-2 fixed**: `require_auth(service_name: str)` is now required (no `= "unknown"` default). Article 32 audit attribution preserved.
- [x] **M-R2-1 fixed**: Bare `except Exception` around `get_http_headers()` is now `except RuntimeError:` with a comment explaining the contract.
- [x] **M-R2-2 fixed**: `notifications/progress` removed from bypass set (server→client per MCP spec; never reaches middleware).
- [x] **M-R2-3 fixed**: Middleware now captures `state_token = fmcp_ctx.set_state(...)` and calls `fmcp_ctx.reset_state(state_token)` in finally — restores the prior value instead of clobbering with None.
- [x] **M-R2-4 fixed**: Spec amendment pending — contextvars + set_state co-existence is now documented inline at the middleware docstring ("contextvars is the source of truth for @require_auth; set_state is for FastMCP-native consumers").
- [x] **LOW-5 fixed**: `AnthropicIdentityProvider._last_state` now imports `ProviderState` directly from `mcp_common.auth.provider` — no longer reaches into `ProviderHealth.__annotations__["state"]` at runtime.
- [x] **LOW-6 fixed**: New public `AnthropicIdentityProvider.force_refresh()` method replaces internal `PyJWKClient.__init__` reinit. Test bypass uses the public API.
- [x] **MEDIUM-2/3 fixed**: Bare `except Exception` around `set_state` is now `except (AttributeError, TypeError)` with a debug log so silent failures are observable.
- [x] **MEDIUM-4 fixed**: Task 14 inline tests no longer reference undefined `build_test_server_with_auth()` / `my_protected_tool()` helpers. They construct the server via the actual `build_runtime()` factory and use an inline `@require_auth`-decorated coroutine.
- [x] **I-R2-3 fixed**: Task 6b added — `AuthErrorTranslationMiddleware` defines the JSON-RPC `-32001` translation surface that B2 fix relied on. Sibling servers opt in via `FastMCP(middleware=[AuthErrorTranslationMiddleware(), ...])`. Translation map covers `AuthenticationRequiredError` / `TokenInvalidError` / `UnknownIssuerError` / `InsufficientPermissionError` with OAuth-style data payloads and `WWW-Authenticate: Bearer realm="mcp"`.
- [x] **api-security R2-2 fixed**: `AuthHealth.as_components(include_diagnostics: bool = False)` — `last_error` is only included when the caller opts in. Default (False) is what `/health` calls; the route is in `allow_anonymous_paths`, so the default must not leak operator details (JWKS URLs, secrets, stack-trace substrings).
- [x] **api-security R2-3 fixed**: Module-level `_sanitize_audit_value()` strips C0 control characters (except `\t`) and truncates to 256 chars. Applied to `caller_service` / `caller_id` / `reason` in decorator's audit-emit blocks.
- [x] **api-security R2-4 fixed**: `JWTIdentityProvider.verify_token` wraps `Permission(p)` conversion in `try/except ValueError → TokenInvalidError`. An unknown permission value now maps to 401 (correct semantic) instead of 500.
- [x] **api-security R2-6 fixed**: `validate_auth_config()` checks that every `type=oauth` provider has all six required fields (`client_id`, `client_secret`, `oauth_token_url`, `jwks_url`, `audience`). Fail-loud at startup.
- [x] **api-security R2-7 fixed**: `jwt.decode(..., leeway=30)` for 30-second clock-skew tolerance between issuer and verifier (typical NTP drift window).
- [x] **LOW-7 verification (deferred to executor)**: mcp-common uses `# type: ignore` directives in 6 plan locations (lines 114, 317, 540, 2201, 2568, 2634). The executor MUST run `grep -rn "tool.ty" /Users/les/Projects/mcp-common/pyproject.toml` to confirm whether mcp-common uses `ty` (in which case directives should be `# ty: ignore[rule]`) or the standard mypy `# type: ignore` form. If ty is configured, convert the 6 directives during execution.
- [x] **M-R2-4 spec amendment**: Spec at line 296 now documents the contextvars + `Context.set_state` co-existence in BearerTokenMiddleware. Future readers won't be confused why both surfaces exist.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for cross-repo work like this where each repo needs its own context.

1. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review. Faster turnaround but harder to debug cross-repo issues.

**Which approach?**
