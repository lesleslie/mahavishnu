---
title: mcp-common Authentication Primitives — Design Spec
date: 2026-09-06
status: proposed
author: brainstormed 2026-09-06
blocks_on:
  - mcp-common repo (foundation library; this spec designs modules there)
  - Oneiric settings surface (AuthConfig integrates into OneiricMCPConfig)
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
- **Implement `AnthropicIdentityProvider`** using PKCE + refresh tokens + `offline_access`
  scope (the first human-facing IdP, unblocking remote-host scapy-mcp).
- **Add `Principal` model** with `issuer`, `subject`, `permissions`, `expires_at`,
  `raw_claims`, and `has_permission()`.
- **Extend `@require_auth`** with `allow_anonymous` and `integrate_with_readyz` parameters.
  Read Principal from Context. No kwarg transport — clean break.
- **Replace `KNOWN_SERVICES` frozenset** with per-server `trusted_issuers` declaration
  in `AuthConfig`.
- **Integrate `AuthConfig` into `OneiricMCPConfig`** so auth is part of the standard
  settings surface.
- **Define `AuthHealth` model** with the wiring-discipline §3 four signals
  (`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`).
- **Aggregate `AuthHealth` into `/health`** via the existing
  `register_http_health_route` helper (extend `extra_components` shape).
- **Add JWKS rotation logic** to providers that need it (Anthropic). Cached-fallback
  semantics on rotation failure.
- **Add `seed_principal(principal)` context-var injection helper** for tests and
  internal hops.
- **Wire sibling servers** (scapy-mcp, archive-org-mcp, medium-mcp) to construct
  `BearerTokenMiddleware` in their lifespan and surface auth state in `/health`.
- **Update `gdpr-posture.md` §10** with the auth section.
- **Re-review ADR 0016 v3** against the new posture; close the "mcp-common auth primitives"
  deferred item.

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

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One decorator: `@require_auth`** with `allow_anonymous` and `integrate_with_readyz` parameters | Smallest API surface change; no alias; consistent with existing convention |
| 2 | **Trust on declaration** — per-server `trusted_issuers` list; no central allow-list | New Bodai services self-declare; no mcp-common edits per server; aligns with OAuth/OIDC RP semantics |
| 3 | **FastMCP middleware, ASGI scope → Context** for token transport | OAuth/OIDC uses HTTP `Authorization` header; kwarg-only transport can't reach OAuth; centralizes the verification path |
| 4 | **Provider-agnostic Protocol + Anthropic concrete** | Future IdPs drop in as Protocol implementations; minimal viable surface for remote-host unblock |
| 5 | **PKCE + refresh tokens + `offline_access`** for Anthropic OAuth | Standard for long-lived MCP server sessions; matches Anthropic's documented OAuth flow |
| 6 | **Phased graduation** — keep package internal (deep imports only) until usage anchors API commitment | Avoids premature public-API lock-in; defers the contract decision until we have real callers |
| 7 | **No backward-compat bridge** — clean break; `@require_auth` reads from Context only | Package has zero production users; bridge is overhead with no benefit; tests migrate simultaneously with the new shape |
| 8 | **Middleware 401 short-circuit by default**; tools opt out via `@require_auth(allow_anonymous=True)` | Default-deny security posture; per-tool override for tools that must accept anonymous |
| 9 | **Spec lives in mahavishnu**, not mcp-common | Cross-repo coordination implications; orchestrator owns the dependency graph |
| 10 | **`AuthConfig` reads env vars + YAML via OneiricMCPConfig**; `mcp_common.security.api_keys` stays separate | API-key validation is a different concern (external-provider keys); JWT/auth is the new block |

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

from fastmcp.server.middleware import Middleware, MiddlewareContext


class BearerTokenMiddleware(Middleware):
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
        # 1. Idempotency: test injection or internal hop already set a Principal
        if (existing := _current_principal()) is not None:
            return await call_next(context)

        # 2. Read Authorization header from ASGI scope
        token = _extract_bearer_token(context)
        if token is None:
            # Anonymous path; defer to per-tool allow_anonymous
            return await call_next(context)

        # 3. Determine provider by issuer hint or default_provider
        provider = self._select_provider(token)

        # 4. Verify token
        principal = await provider.verify_token(token, expected_audience=self._config.service_name)

        # 5. Stash Principal on context
        _set_principal(principal)
        try:
            return await call_next(context)
        finally:
            _clear_principal()


def _extract_bearer_token(context: MiddlewareContext) -> str | None:
    """Extract "Authorization: Bearer <token>" from the ASGI scope."""
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
    integrate_with_readyz: bool = True,
) -> Callable:
    """Decorator: enforce permission on the calling tool.

    Reads Principal from request-scoped Context.
    No kwarg transport — clean break with prior convention.
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
4. Server returns 200 + `{"status": "ok", "service": ..., "version": ..., "components": [...]}`.
5. If any provider reports `state != "healthy"`, server returns 503 (per wiring discipline §1).

## Error Handling

| Failure | Behavior | Status |
|---|---|---|
| Missing `Authorization` header | Pass through; per-tool `allow_anonymous` decides | 200 or 401 |
| Malformed token (not a JWT, wrong format) | `TokenInvalidError` | 401 |
| Expired token | `TokenExpiredError` | 401 + `WWW-Authenticate: Bearer error="invalid_token"` |
| Wrong audience | `AudienceMismatchError` | 401 |
| Unknown issuer (not in `trusted_issuers`) | `UnknownIssuerError` | 401 |
| IdP unreachable | `ProviderUnavailableError` | 503 + `Retry-After` |
| JWKS rotation failure | Cached JWKS continues; alarm via `AuthHealth` | 200 with degraded component |
| Missing `AuthConfig` when `enabled=True` | Startup failure | n/a (fail-loud) |
| Permission denied at tool | `InsufficientPermissionError` | 403 |
| Test injection (via `seed_principal`) | Middleware skips verification | 200 |

## Implementation

This is a single-phase implementation. No Phase 1 / Phase 2 split; all work lands together.

### Tasks

1. **Add `Principal` model** to `mcp_common/auth/principal.py`.
2. **Add `IdentityProvider` Protocol** to `mcp_common/auth/provider.py`.
3. **Extract `JWTIdentityProvider`** from `mcp_common/auth/core.py` (rename existing
   `verify_token` to `JWTIdentityProvider.verify_token`).
4. **Add `AnthropicIdentityProvider`** to `mcp_common/auth/providers/anthropic.py`.
   Implements PKCE + refresh tokens + `offline_access` per Anthropic's documented OAuth flow.
5. **Add `BearerTokenMiddleware`** to `mcp_common/auth/middleware.py`. Use `contextvars` for
   request-scoped Principal storage.
6. **Add `seed_principal(principal)` and `_current_principal()` helpers** to
   `mcp_common/auth/context.py`.
7. **Extend `@require_auth`** with `allow_anonymous` and `integrate_with_readyz` parameters.
   Reads from Context. No kwarg transport.
8. **Replace `KNOWN_SERVICES`** with per-server `trusted_issuers` check.
9. **Integrate `AuthConfig` into `OneiricMCPConfig`** as a typed field. Update
   `mcp_common/cli/settings.py` to support `auth` block in YAML.
10. **Define `AuthHealth` and `ProviderHealth`** in `mcp_common/auth/health.py`.
11. **Extend `register_http_health_route`** to include `AuthHealth` components in the
    envelope (extend `extra_components` parameter shape).
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
  `ProviderUnavailableError` for IdP reachability failures.
- `mcp_common/cli/settings.py` — `OneiricMCPConfig` integration point.

## Open Questions

None. All architectural decisions resolved during the 2026-09-06 brainstorm.

The remaining details (e.g., exact JWKS cache TTL, Anthropic OAuth endpoint URLs, exact
PKCE code-verifier generation strategy) are implementation-plan concerns, not design
decisions.
