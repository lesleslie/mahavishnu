---
title: mcp-common Authentication Primitives — Design Spec
date: 2026-09-06
last_reviewed: 2026-09-06
status: draft
role: implementation
topic: mcp-common-auth-primitives
author: brainstormed 2026-09-06
blocks_on:
  - mcp-common repo (foundation library; this spec designs modules there)
  - MCPServerSettings surface (AuthConfig integrates into `MCPServerSettings` at `mcp_common/cli/settings.py:15`)
blocks:
  - ADR 0016 v3 v4+ deferred items (this spec closes the "mcp-common authentication primitives" item)
  - Flowscape v1 remote-host scapy-mcp (this spec unblocks that path)
supersedes: null
related:
  - ../../adr/0016-scapy-mcp-integration.md (scapy-mcp client-mode enrichment posture)
  - ../../legal/gdpr-posture.md (Article 32 monitoring requires AuthHealth surface)
  - ../../../.claude/decisions/mcp-backend-wiring-discipline.md (wiring discipline §3 mandates feed observability shape)
target_repo: mcp-common
scope_note: |
  Single-phase design — no Phase 1/Phase 2 split, no backward-compat kwarg bridge. The package
  has zero production consumers today, so a clean break is cheaper than a migration release.
  Phased graduation (internal vs. public API surface) is kept: the package remains deep-import
  only until usage anchors the API commitment.
spec_location_note: |
  This spec lives in mahavishnu/docs/superpowers/specs/ rather than mcp-common/docs/superpowers/specs/
  because the work has cross-repo coordination implications (this spec unblocks remote-host
  scapy-mcp, a sibling MCP server; the auth surface changes the public API contract of every
  Bodai MCP server that opts in). The implementation lands in mcp-common; the spec lives with
  the orchestrator that owns the cross-repo dependency graph.
---

# mcp-common Authentication Primitives — Design Spec

## Context

`mcp_common/auth/` already exists as an 8-module package with substantive primitives:
`Permission` enum + `Role` definitions, JWT create/verify with issuer/audience/permission
claims, `AuthConfig` with env-var secret loading and placeholder rejection,
`AuthAuditEvent` + `AuditLogger` with pluggable sinks, and `@require_auth` decorator with
permission-level enforcement. The package is **unused in production** — `@require_auth` has
no callers in scapy-mcp, archive-org-mcp, medium-mcp, or mahavishnu.

What's missing is real integration: token transport is convention-only (`__auth_token__`
kwarg), no FastMCP middleware exists, no settings integration, no `/health` observability
surface, no identity-provider abstraction for human/IdP authentication.

The wiring discipline (`.claude/decisions/mcp-backend-wiring-discipline.md` §3) requires
every Bodai MCP server to surface feed observability on `/health`. Without an `AuthHealth`
surface, the auth layer is "alive but unverifiable" — exactly the failure mode the policy
was written to prevent.

ADR 0016 v3 deferred "mcp-common authentication primitives" to v4+. The remote-host
scapy-mcp scenario (called by Claude Code from another machine) cannot land until the
auth surface supports human/IdP authentication, not just inter-service JWT.

This spec designs the auth surface as a single coherent body of work. No Phase 1 / Phase 2
split, no backward-compat bridge: the package has zero production users today, so a clean
break is cheaper than a migration release.

## Goals

- **Build `BearerTokenMiddleware`** that reads `Authorization: Bearer <token>` from the
  ASGI scope and stores a `Principal` on a request-scoped `Context`.
- **Define `IdentityProvider` Protocol** with `verify_token` and `health` methods.
- **Implement `JWTIdentityProvider`** by extracting the existing `verify_token` core
  (the existing inter-service JWT path stays).
- **Implement `AnthropicIdentityProvider` (5a)** for **JWKS verification of
  Anthropic-issued access tokens**. The OAuth authorization-code flow, PKCE
  `code_verifier` generation, refresh-token rotation, and `offline_access` scope
  are **deferred to Task 5b (follow-up spec)**.
- **Add `Principal` model** with `issuer`, `subject`, `permissions`, `expires_at`,
  `raw_claims`, and `has_permission()`.
- **Extend `@require_auth`** with `allow_anonymous` and `audit_logger` parameters.
  Read Principal from Context. No kwarg transport — clean break. The previous
  `integrate_with_readyz` parameter is **dropped** (was accepted but never
  consulted — shipping a parameter that lies to callers is worse than no parameter).
- **Replace `KNOWN_SERVICES` frozenset** with per-server `trusted_issuers` declaration
  in `AuthConfig` (default-deny semantics: empty list rejects ALL issuers; a startup
  check `validate_auth_config()` fails loud if `enabled=True` with empty `trusted_issuers`).
- **Integrate `AuthConfig` into `MCPServerSettings`** so auth is part of the standard
  settings surface. (Note: this spec's earlier draft said `OneiricMCPConfig`; the
  actual class is `MCPServerSettings` at `mcp_common/cli/settings.py:15`. The
  `OneiricMCPConfig` was an early working title that never landed.)
- **Define `AuthHealth` model** with the wiring-discipline §3 four signals
  (`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`).
- **Aggregate `AuthHealth` into `/health`** via the existing
  `register_http_health_route` helper (extend `extra_components` shape). The `/health`
  route **keeps 200-only**; the `status: "degraded"` field in the body signals
  degraded state. The 503 semantic is reserved for `/readyz` (future work).
- **Add JWKS rotation logic** to providers that need it (Anthropic). Cached-fallback
  semantics on rotation failure.
- **Add `seed_principal(principal)` context-var injection helper** for tests and
  internal hops.
- **Wire sibling servers** (scapy-mcp, archive-org-mcp, medium-mcp) to construct
  `BearerTokenMiddleware` in their lifespan and surface auth state in `/health`.
- **Update `gdpr-posture.md` §10** with the auth section.
- **Re-review ADR 0016 v3** against the new posture; close the "mcp-common auth primitives"
  deferred item. **Requires a parallel reviewer (architecture-council or
  mcp-integration-expert) before the status bump lands.**

## Non-Goals

- Full OAuth/OIDC provider catalog (Anthropic concrete only in this spec; future IdPs add
  incrementally via the Protocol).
- Multi-tenant within a single MCP server process (each request is single-principal).
- Token refresh inside middleware (refresh happens in the IdP, not in middleware).
- mTLS / cert-based auth (deferred to v2).
- Dynamic Client Registration (DCR) and FAPI profile (out of scope).
- Federated identity / SAML / OIDC discovery outside what Anthropic OAuth uses.
- Backward-compat kwarg transport for `@require_auth` — clean break.
- Public-API graduation in this spec (the package remains deep-imports only; graduation
  happens after usage anchors the contract).
- **OAuth authorization-code flow, PKCE, refresh tokens, and `offline_access` scope**
  (deferred to Task 5b follow-up spec; the current spec is JWKS-verification only).

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One decorator: `@require_auth`** with `allow_anonymous` and `audit_logger` parameters (the previous `integrate_with_readyz` parameter is dropped — was accepted but never consulted) | Smallest API surface change; no alias; consistent with existing convention |
| 2 | **Trust on declaration** — per-server `trusted_issuers` list (default-deny); no central allow-list | New Bodai services self-declare; no mcp-common edits per server; aligns with OAuth/OIDC RP semantics |
| 3 | **FastMCP middleware, headers via `get_http_headers()` → Context** for token transport | OAuth/OIDC uses HTTP `Authorization` header; `MiddlewareContext.scope` doesn't exist; `get_http_headers()` is the FastMCP-native path |
| 4 | **Provider-agnostic Protocol + Anthropic concrete** | Future IdPs drop in as Protocol implementations; minimal viable surface for remote-host unblock |
| 5 | **Anthropic 5a: JWKS verification only**. 5b (PKCE + refresh tokens + `offline_access` scope) deferred to follow-up spec | Standard for long-lived MCP server sessions; matches Anthropic's documented OAuth flow; honest scope-bounding |
| 6 | **Phased graduation** — keep package internal (deep imports only) until usage anchors API commitment | Avoids premature public-API lock-in; defers the contract decision until we have real callers |
| 7 | **No backward-compat bridge** — clean break; `@require_auth` reads from Context only | Package has zero production users; bridge is overhead with no benefit; tests migrate simultaneously with the new shape |
| 8 | **Middleware 401 short-circuit by default**; tools opt out via `@require_auth(allow_anonymous=True)`; missing Principal raises `AuthenticationRequiredError` (401, not 403) | Default-deny security posture; 401 vs 403 distinction matters for OAuth client retry behavior |
| 9 | **Spec lives in mahavishnu**, not mcp-common | Cross-repo coordination implications; orchestrator owns the dependency graph |
| 10 | **`AuthConfig` reads env vars + YAML via `MCPServerSettings`**; `mcp_common.security.api_keys` stays separate | API-key validation is a different concern (external-provider keys); JWT/auth is the new block |

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                  HTTP request inbound to MCP server                    │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     BearerTokenMiddleware                              │
│                                                                        │
│  1. Skip if Principal already on Context (test/internal hop)          │
│  2. Read "Authorization: Bearer <token>" from ASGI scope               │
│  3. Pick IdentityProvider by issuer hint or default_provider          │
│  4. provider.verify_token(token) → Principal                          │
│  5. Stash Principal on request-scoped Context                         │
│  6. 401 if verification fails (or pass through if any tool opts out)   │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          FastMCP tool dispatch                         │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       @require_auth(permission=...)                   │
│                                                                        │
│  1. Read Principal from Context                                       │
│  2. Check Principal.has_permission(permission)                        │
│  3. If anonymous path: short-circuit per allow_anonymous               │
│  4. If denied: raise InsufficientPermissionError                      │
│  5. Emit AuthAuditEvent                                                │
│  6. Tool body executes                                                 │
└────────────────────────────────────────────────────────────────────────┘
```

```
┌────────────────────────────────────────────────────────────────────────┐
│                          /health GET request                          │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│              register_http_health_route (existing mcp-common)         │
│                                                                        │
│  Returns: { status, service, version, components: [...] }              │
│                                                                        │
│  components includes AuthHealth                                        │
│            { provider_states, verifications_total, errors_total,       │
│              last_successful_verification_at, cycles_total }           │
└────────────────────────────────────────────────────────────────────────┘
```

## Components in detail

### `Principal` model

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp_common.auth.permissions import Permission


@dataclass(frozen=True)
class Principal:
    issuer: str                          # "mahavishnu", "anthropic", ...
    subject: str                         # unique within issuer
    permissions: frozenset[Permission]
    expires_at: datetime
    raw_claims: dict[str, Any]           # full JWT/OIDC payload

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
```

### `BearerTokenMiddleware`

```python
from __future__ import annotations

from typing import Any

from fastmcp.server.dependencies import get_http_headers  # B1 fix
from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_common.auth.exceptions import AuthError  # B2 fix
from mcp_common.auth.context import (
    _clear_principal,
    _current_principal,
    seed_principal,
)


# MCP methods that bypass auth (handshake + lifecycle).
# M-R2-2 fix: `notifications/progress` is server→client per the MCP spec and
# never reaches middleware as an inbound message, so it is intentionally
# excluded from the bypass set. The bypass covers the MCP handshake
# (`initialize` + client→server `notifications/initialized`), the `ping`
# keepalive, and client→server `notifications/cancelled`.
_AUTH_BYPASS_METHODS = frozenset({
    "initialize",
    "notifications/initialized",
    "ping",
    "notifications/cancelled",
})


class BearerTokenMiddleware(Middleware):
    def __init__(
        self,
        *,
        auth_config: AuthConfig,
        providers: dict[str, IdentityProvider],
    ) -> None:
        self._config = auth_config
        self._providers = providers
        # I-4 fix: counter store. Middleware increments on every verification.
        # Sibling servers wire this to the same AuthHealth surface.
        self._verifications_total = 0
        self._errors_total = 0

    async def on_request(
        self,
        context: MiddlewareContext,
        call_next: Any,
    ) -> Any:
        # I-1 fix: skip auth on MCP handshake and notifications
        if context.method in _AUTH_BYPASS_METHODS:
            return await call_next(context)

        # Idempotency: test injection or internal hop already set a Principal
        if (existing := _current_principal()) is not None:
            return await call_next(context)

        # B1 fix: read headers via FastMCP's get_http_headers() (NOT
        # MiddlewareContext.scope — that attribute does not exist per
        # FastMCP source verification at middleware.py:47-61).
        try:
            headers = get_http_headers() or {}
        except Exception:
            # get_http_headers() raises in non-HTTP transports (stdio).
            # In that case, Bearer auth is meaningless — pass through.
            return await call_next(context)

        # 2. Read Authorization header from headers
        token = _extract_bearer_token(headers)
        if token is None:
            return await call_next(context)

        # 3. Determine provider by issuer hint or default_provider
        provider = self._select_provider(token)

        # 4. Verify token. B4 fix: catch AuthError only; programming errors
        # propagate. B2 fix: raise AuthError (not HTTPException).
        try:
            principal = await provider.verify_token(
                token, expected_audience=self._config.service_name
            )
        except AuthError:
            self._errors_total += 1
            raise  # error_handling middleware translates to JSON-RPC -32001

        self._verifications_total += 1

        # 5. Stash Principal on context
        token_handle = seed_principal(principal)
        # M-R2-4 spec note: BearerTokenMiddleware also calls
        # `fastmcp_context.set_state("principal", principal)` for FastMCP-native
        # consumers. contextvars remains the source of truth for @require_auth;
        # set_state is a parallel surface for any FastMCP tool that reads the
        # FastMCP Context object directly. Both must be reset in `finally`
        # (token_handle.var.reset + fmcp_ctx.reset_state(token)).
        try:
            return await call_next(context)
        finally:
            token_handle.var.reset(token_handle)


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    """Extract "Authorization: Bearer <token>" from a headers dict.

    B1 fix: takes a dict[str, str] (from get_http_headers()), not a MiddlewareContext.
    Reject tokens longer than 8192 bytes to prevent memory exhaustion via huge
    Authorization headers.
    """
    ...


def _select_provider(token: str) -> IdentityProvider:
    """Pick the provider by issuer hint in the JWT header (kid) or default."""
    ...
```

### `IdentityProvider` Protocol

```python
from __future__ import annotations

from typing import Protocol


class IdentityProvider(Protocol):
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

### `AuthConfig` (re-shaped)

```python
from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class AuthConfig(BaseModel):
    enabled: bool = True
    secret: SecretStr | None = None         # for JWT provider
    service_name: str                       # expected audience

    trusted_issuers: list[str] = Field(default_factory=list)
    identity_providers: dict[str, IdentityProviderConfig] = Field(default_factory=dict)
    default_provider: str | None = None
    allow_anonymous_paths: list[str] = Field(
        default_factory=lambda: ["/health", "/readyz"]
    )

    model_config = {"arbitrary_types_allowed": True}
```

### `@require_auth` (extended)

```python
def require_auth(
    permission: Permission = Permission.READ,
    *,
    allow_anonymous: bool = False,
    audit_logger: AuditLogger | None = None,
) -> Callable:
    """Decorator: enforce permission on the calling tool.

    Reads Principal from request-scoped Context.
    No kwarg transport — clean break with prior convention.

    Error semantics (B10 fix):
    - No Principal + allow_anonymous=False → AuthenticationRequiredError (401)
    - No Principal + allow_anonymous=True → proceed
    - Principal lacks permission → InsufficientPermissionError (403)

    B10 fix: emits AuthAuditEvent (not a new AuditEvent class). The
    existing AuthAuditEvent fields are timestamp, service, caller_service,
    caller_id, action, result, reason. We map our concerns onto these.

    I-2 fix: integrate_with_readyz parameter dropped. The /readyz aggregation
    semantics are deferred to a follow-up spec when there's an actual
    aggregation point.
    """
    ...
```

### `AuthHealth`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class ProviderHealth:
    name: str
    state: Literal["healthy", "degraded", "dead"]
    last_check_at: datetime | None = None
    last_error: str | None = None


@dataclass
class AuthHealth:
    providers: dict[str, ProviderHealth]
    verifications_total: int
    errors_total: int
    last_successful_verification_at: datetime | None
    last_updated_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cycles_total: int

    def as_components(self) -> list[dict[str, Any]]:
        """Render for /health envelope's components[] array."""
        ...
```

The shape mirrors wiring-discipline §3: `entities_count` (verifications served),
`last_updated_timestamp`, `errors_total`, `cycles_total`.

## Data Flow

### Inbound request

1. HTTP request hits the FastMCP ASGI app.
2. `BearerTokenMiddleware.on_request` runs first.
3. Middleware reads `Authorization: Bearer <token>` from ASGI scope; if absent, passes through
   (per-tool `allow_anonymous` decides).
4. Middleware selects the `IdentityProvider` by issuer hint or default provider.
5. `provider.verify_token(token, expected_audience=self._config.service_name)` returns a
   `Principal` or raises an `AuthError` subclass.
6. On success: Principal is set on the request-scoped Context; `call_next` proceeds.
7. FastMCP dispatches to the tool. The tool's `@require_auth(permission=...)` reads Principal
   from Context and checks `has_permission(permission)`.
8. Tool body executes.
9. `BearerTokenMiddleware` clears the Context (in `finally`).
10. Audit event is emitted to `AuditLogger`.

### `/health` aggregation

1. HTTP `GET /health` hits `register_http_health_route`.
2. Each `IdentityProvider.health()` is called (in parallel via `asyncio.gather`).
3. `AuthHealth.as_components()` is appended to the `components` array.
4. Server returns **200** + `{"status": "ok"|"degraded", "service": ..., "version": ..., "components": [...]}`.
5. If any provider reports `state != "healthy"`, `status` is `"degraded"` (B3 + I-7 fix: route stays 200; the 503 semantic is reserved for `/readyz`).

## Error Handling

| Failure | Behavior | Status |
|---|---|---|
| Missing `Authorization` header | Pass through; per-tool `allow_anonymous` decides | 200 or 401 |
| Malformed token (not a JWT, wrong format) | `TokenInvalidError` | 401 |
| Expired token | `TokenExpiredError` | 401 + `WWW-Authenticate: Bearer error="invalid_token"` |
| Wrong audience | `AudienceMismatchError` | 401 |
| Unknown issuer (not in `trusted_issuers`, B6 default-deny) | `UnknownIssuerError` | 401 |
| IdP unreachable | `ProviderUnavailableError` | 503 + `Retry-After` |
| JWKS rotation failure | Cached JWKS continues; alarm via `AuthHealth` | 200 with degraded component |
| Missing `AuthConfig` when `enabled=True` | Startup failure (B6: `validate_auth_config()` fails loud) | n/a (fail-loud) |
| Trusted-issuers empty + `enabled=True` | Startup failure (B6 default-deny) | n/a (fail-loud) |
| Tool called without Principal, `allow_anonymous=False` | `AuthenticationRequiredError` (B10 fix) | 401 |
| Tool called with Principal, lacks permission | `InsufficientPermissionError` | 403 |
| Test injection (via `seed_principal`) | Middleware skips verification | 200 |
| MCP handshake (`initialize`, `notifications/initialized`, `ping`) | Bypass auth (I-1 fix) | n/a |

## Implementation

This is a single-phase implementation. No Phase 1 / Phase 2 split; all work lands together.

### Tasks

1. **Add `Principal` model** to `mcp_common/auth/principal.py`.
2. **Add `IdentityProvider` Protocol** to `mcp_common/auth/provider.py`.
3. **Extract `JWTIdentityProvider`** from `mcp_common/auth/core.py`. B5 fix: `jwt.decode`
   pins `algorithms=["HS256"]` and requires `exp`/`iat`/`iss`/`aud` claims. B9 fix:
   rename `TokenPayload.raw` to `raw_claims`.
4. **Add `AnthropicIdentityProvider` (5a)** to `mcp_common/auth/providers/anthropic.py`.
   B7 fix: `_extract_permissions` returns `[]` on empty scope (default-deny). I-3 fix:
   enforce `trusted_issuers`. PKCE + refresh tokens + `offline_access` are deferred
   to Task 5b (follow-up spec).
5. **Add `BearerTokenMiddleware`** to `mcp_common/auth/middleware.py`. B1 fix: uses
   `get_http_headers()` from `fastmcp.server.dependencies` (NOT `MiddlewareContext.scope`).
   B2 fix: raises `AuthError` (not `HTTPException`). B4 fix: catches `AuthError` only.
   I-1 fix: skips MCP handshake methods.
6. **Add `seed_principal(principal)` and `_current_principal()` helpers** to
   `mcp_common/auth/context.py`.
7. **Extend `@require_auth`** with `allow_anonymous` and `audit_logger` parameters.
   I-2 fix: `integrate_with_readyz` parameter dropped. B10 fix: uses `AuthAuditEvent`
   fields. B10 fix: distinguishes `AuthenticationRequiredError` (401) from
   `InsufficientPermissionError` (403).
8. **Replace `KNOWN_SERVICES`** with per-server `trusted_issuers` check. B6 fix:
   default-deny semantics. `validate_auth_config()` startup helper fails loud.
9. **Integrate `AuthConfig` into `MCPServerSettings`** as a typed field. B8 fix:
   the integration is split into 8a (Pydantic conversion, BEFORE Task 6) + 8b
   (new fields, AFTER). Update `mcp_common/cli/settings.py` to support `auth` block
   in YAML.
10. **Define `AuthHealth` and `ProviderHealth`** in `mcp_common/auth/health.py`. I-4
    fix: include counter store references so `verifications_total` and
    `errors_total` actually increment.
11. **Extend `register_http_health_route`** to include `AuthHealth` components via
    a `auth_health_provider: Callable[[], AuthHealth | None]` parameter. B3 fix:
    `is_degraded` is recomputed per request (not captured at registration). I-7
    fix: route stays 200; `status: "degraded"` in body.
12. **Add JWKS rotation logic** to providers that need it (Anthropic). Cached-fallback
    semantics on rotation failure.
13. **Wire sibling servers** (scapy-mcp, archive-org-mcp, medium-mcp) to construct
    `BearerTokenMiddleware` in their lifespan. Each gets one integration test that asserts
    the middleware is constructed and `/health` envelope includes auth state.
14. **Write the internal auth doc** at `mcp_common/docs/auth-design.md` (rationale,
    examples, migration notes from the old package shape).
15. **Update `gdpr-posture.md` §10** with the auth section.
16. **Re-review ADR 0016 v3** against the new posture; close the "mcp-common auth primitives"
    deferred item.

### Test additions

- `tests/auth/test_principal.py` — Principal.has_permission edge cases
- `tests/auth/test_provider.py` — IdentityProvider Protocol conformance for both concretes
- `tests/auth/test_providers/test_jwt.py` — JWTIdentityProvider with various claims
- `tests/auth/test_providers/test_anthropic.py` — AnthropicIdentityProvider with mocked
  Anthropic OAuth endpoints (no live calls in CI; sandbox-only task)
- `tests/auth/test_middleware.py` — BearerTokenMiddleware with mock providers
- `tests/auth/test_context.py` — seed_principal / _current_principal lifecycle
- `tests/auth/test_trusted_issuers.py` — replaces test_identity.py for the new shape
- `tests/auth/test_health.py` — AuthHealth aggregation, /health envelope shape
- `tests/auth/test_jwks_rotation.py` — rotation success and fallback
- **Migration**: existing `tests/auth/test_decorator.py` cases that used `__auth_token__=`
  get rewritten to `seed_principal(...)` simultaneously with this implementation (no
  deprecation window).
- Smoke tests in CI: spin up scapy-mcp with mock IdP, hit `/health`, assert auth
  component appears with expected shape.

### Phased graduation (kept)

- The `mcp_common/auth/` package is **not** re-exported from `__init__.py`. Consumers
  (scapy-mcp, archive-org-mcp, medium-mcp, mahavishnu) use deep imports from
  `mcp_common.auth.*`. This is the "internal API" state.
- Graduation to public API (re-export from `__init__.py`, settings field, etc.) happens
  in a future spec, after the auth surface has been used by at least one sibling server
  in production for a release cycle.

## Testing Strategy

### Unit (per package)

- Each `IdentityProvider` implementation in isolation.
- Mock IdP responses (use `respx` for Anthropic OAuth endpoints).
- `Principal.has_permission` edge cases.
- `@require_auth` decorator with various Context states.
- 90% branch coverage required (matches mcp-common standard).

### Integration

- Middleware + real FastMCP app + mock IdP.
- Assert 401 / 200 / permission-denied paths.
- Assert `seed_principal` skips verification.

### Contract

- Extend `assert_baseline_surface` to verify auth providers appear in `/health` envelope.

### Smoke

- Spin up server with mock IdP, hit `/health`, assert `AuthHealth` shape.
- Run in CI for scapy-mcp, archive-org-mcp, medium-mcp.

### Sibling server adoption

- scapy-mcp: integration test constructs `BearerTokenMiddleware` in lifespan.
- archive-org-mcp: same.
- medium-mcp: same.
- Each test asserts the middleware is constructed and `/health` envelope includes auth state.

## Cross-references

- `docs/adr/0016-scapy-mcp-integration.md` — this spec closes the v4+ deferred item
  "mcp-common authentication primitives"; unblocks remote-host scapy-mcp.
- `docs/legal/gdpr-posture.md` §10 — `AuthHealth` surface satisfies Article 32 monitoring
  requirements for any production deployment.
- `.claude/decisions/mcp-backend-wiring-discipline.md` §3 — feed observability shape
  (`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`) is the
  model `AuthHealth` implements.
- `mcp_common/auth/exceptions.py` — existing exception hierarchy is reused; new addition
  `ProviderUnavailableError` for IdP reachability failures. New addition
  `AuthenticationRequiredError` for the 401 case (no Principal + `allow_anonymous=False`).
- `mcp_common/cli/settings.py` — `MCPServerSettings` integration point (the
  `OneiricMCPConfig` referenced in earlier drafts was an early working title
  that never landed; the actual class is `MCPServerSettings`).

## Open Questions

None at the architectural level. Implementation-plan concerns (not design
decisions) include: exact JWKS cache TTL, exact PKCE code-verifier generation
strategy (deferred to Task 5b follow-up spec), and Oneiric settings integration
deferred until `MCPServerSettings` is migrated into Oneiric.

## Spec amendments (post 2026-09-07 multi-agent review)

This spec was reviewed by 7 subagents (5 domain-relevant + 2 orthogonal). The
review report is at `docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives-multi-agent-review.md`.
The following amendments were applied based on the review's 12 distinct BLOCKERs
and 22 distinct cross-cutting IMPORTANTs:

| ID | Change | Source |
|---|---|---|
| B1 | `BearerTokenMiddleware` uses `get_http_headers()` from `fastmcp.server.dependencies` (not `MiddlewareContext.scope` — that attribute doesn't exist) | mcp-integration-expert |
| B2 | Middleware raises `AuthError` (not `HTTPException`); sibling's `error_handling` middleware translates to JSON-RPC `-32001` with `WWW-Authenticate: Bearer` data | mcp-integration-expert |
| B3 | `is_degraded` recomputed per request via `auth_health_provider` callable (not captured at registration) | python-pro, architecture, mcp-integration, audit (4 reviewers) |
| B4 | Middleware catches `AuthError` only (no bare `except Exception`) | python-pro, auth cross-cutting |
| B5 | `jwt.decode` pins `algorithms=["HS256"]`; required claims `exp`/`iat`/`iss`/`aud` | api-security |
| B6 | `trusted_issuers` default-deny; `validate_auth_config()` startup check fails loud | api-security, auth |
| B7 | `_extract_permissions` returns `[]` on empty scope; exact-match scope checking (no substring `in`) | api-security, architecture |
| B8 | Task 8 split into 8a (Pydantic, BEFORE Task 6) + 8b (new fields, AFTER) | architecture |
| B9 | `TokenPayload.raw` renamed to `raw_claims`; no `hasattr` guard | architecture, api-security |
| B10 | `@require_auth` uses `AuthAuditEvent` fields (not a new `AuditEvent`); distinguishes `AuthenticationRequiredError` (401) from `InsufficientPermissionError` (403) | architecture, auth |
| B11 | Task 5 split into 5a (JWKS verification only) + 5b (OAuth flow, follow-up spec) | auth, documentation |
| B12 | Integration Contract blocks added for all 4 phases in the implementation plan | audit |
| I-1 | `BearerTokenMiddleware` skips `context.method in {"initialize", "notifications/initialized", "ping", "notifications/cancelled"}` (`notifications/progress` removed per M-R2-2 — server→client per MCP spec, never reaches middleware as inbound) | mcp-integration |
| I-2 | `integrate_with_readyz` parameter dropped from `@require_auth` | auth, audit, mcp-integration (3 reviewers) |
| I-3 | `AnthropicIdentityProvider.verify_token` enforces `trusted_issuers` (mirror JWT) | audit, auth |
| I-4 | `BearerTokenMiddleware` carries `_verifications_total` and `_errors_total` counter properties; sibling servers wire these to `AuthHealth.from_providers(...)` | audit |
| I-5 | Task 14 sibling integration tests use concrete assertions (401 on unauthenticated; tool body runs on valid token) — not the registration-illusion pattern | audit, architecture |
| I-7 | `/health` keeps 200-only; `status: "degraded"` in body. 503 reserved for `/readyz` (future work) | mcp-integration, audit |
| I-8 | HS256 limitation noted; JWKS support is a future enhancement | auth |
| I-9 | Embedded `auth-design.md` example guards `auth_config.secret` before `.get_secret_value()` | documentation |
| I-10 | Task 16 requires parallel reviewer (architecture-council or mcp-integration-expert) before ADR status bump | audit |
| I-1 (drift) | `OneiricMCPConfig` → `MCPServerSettings` throughout (the spec's earlier draft used `OneiricMCPConfig`; the actual class is `MCPServerSettings` at `mcp_common/cli/settings.py:15`) | audit, documentation |

**Spec-side amendments applied in this commit:**

- Goals list updated for B1, B6, B7, B8, B10, B11, I-2, I-7, I-10.
- Non-Goals list gained the explicit "OAuth flow, PKCE, refresh tokens, `offline_access`" exclusion (deferred to 5b).
- Design Decisions table updated for #1, #2, #3, #5, #8, #10.
- BearerTokenMiddleware code block updated for B1, B2, B4, I-1, I-4.
- `@require_auth` code block updated for I-2, B10.
- Data Flow → `/health` aggregation updated for B3, I-7.
- Error Handling table updated for B6, B10.
- Tasks list updated for B1, B2, B3, B4, B5, B6, B7, B8, B9, B10, B11, I-1, I-2, I-3, I-4, I-7.
- Cross-references updated for `AuthenticationRequiredError` and `MCPServerSettings`.

The plan (`docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives.md`) was
revised simultaneously (commit `682bbb7f`); spec and plan now agree.
