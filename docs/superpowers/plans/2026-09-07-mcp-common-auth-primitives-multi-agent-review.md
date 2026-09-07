---
title: mcp-common Auth Primitives Plan — Multi-Agent Review
date: 2026-09-07
status: review-complete
reviewers:
  - python-pro
  - authentication-specialist
  - api-security-specialist
  - mcp-integration-expert
  - critical-audit-specialist
  - feature-dev:code-architect
  - documentation-specialist
subjects:
  - plan: /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives.md
  - spec: /Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md
---

# mcp-common Auth Primitives Plan — Multi-Agent Review

## Executive summary

**7 reviewers** (5 domain-relevant + 2 orthogonal) examined the plan against the spec. The plan is **architecturally sound but has multiple BLOCKER-level bugs that will surface on first integration run**, particularly in the FastMCP middleware layer.

| Severity | Total | Distinct (deduplicated) | Must-fix before implementation |
|---|---|---|---|
| **BLOCKER** | 18 raw findings across 7 reviewers | **12 distinct issues** | 12 |
| **IMPORTANT** | 48 raw findings | ~22 distinct issues | 5-7 (cross-cutting) |
| **MINOR** | 59 raw findings | ~30 distinct issues | 0 (post-implementation cleanup) |

**Critical observation:** the most consequential BLOCKERs are not minor — they will cause the auth middleware to silently do nothing (`MiddlewareContext.scope` doesn't exist) or raise the wrong error type for FastMCP clients. The plan cannot ship without fixing these.

**Recommend:** Plan revision is required before implementation. Estimated revision effort: 2-4 hours of focused editing + spec amendment for the OneiricMCPConfig terminology drift.

## Top BLOCKERs (deduplicated, ranked by severity)

### B1. `MiddlewareContext` has no `.scope` attribute — middleware silently does nothing
**Reviewers:** mcp-integration-expert (B1)
**Plan lines:** 1062, 1146-1176 (Step 6.3)
**Issue:** Verified against FastMCP source at `/usr/local/Cellar/mcpm/2.15.0_2/libexec/lib/python3.14/site-packages/fastmcp/server/middleware/middleware.py:47-61` — `MiddlewareContext` exposes only `message`, `fastmcp_context`, `source`, `type`, `method`, `timestamp`. No `.scope`. The plan's `getattr(context, "scope", None) or {}` returns `{}` on every call. **Every authenticated tool will hit `InsufficientPermissionError` on every call** because the middleware never extracts a token.
**Fix:** Replace with the canonical FastMCP pattern:
```python
from fastmcp.server.dependencies import get_http_headers
headers = get_http_headers() or {}
auth_value = headers.get("authorization", "")
```
Handle stdio transport (where `get_http_headers()` returns `None`) explicitly — Bearer auth is meaningless there.

### B2. `HTTPException` is the wrong error type for FastMCP middleware
**Reviewers:** mcp-integration-expert (B2)
**Plan lines:** 1063, 1116-1120
**Issue:** FastMCP middleware errors propagate as JSON-RPC errors over MCP transports. `HTTPException` raised inside a middleware will either crash uncaught or be mis-translated to a generic internal-error JSON-RPC response — losing the `WWW-Authenticate: Bearer` header that OAuth clients need to recover.
**Fix:** Raise a custom `AuthError` carrying an OAuth error code (`error="invalid_token"`, `error_description=...`). Let the existing `error_handling` middleware (if the sibling server installs it) translate to JSON-RPC error code `-32001` with the OAuth error in `data`.

### B3. `is_degraded` captured at registration time, not per request — `/health` returns stale status forever
**Reviewers:** python-pro (I3), feature-dev:code-architect (IMPORTANT), mcp-integration-expert (I6), critical-audit-specialist (I3) — **4 reviewers**
**Plan lines:** 1958-1998 (Task 11 Step 11.3)
**Issue:** `is_degraded = auth_health.is_degraded() if auth_health is not None else False` is computed once at registration, then captured by closure. JWKS rotation failure at 03:00 will never reach the response — `/health` will keep returning 200 with the cached `is_degraded=False`.
**Fix:** Pass `auth_health` (or a `Callable[[], AuthHealth | None]`) and call `is_degraded()` inside the closure body each invocation. Or recompute via `auth_health.is_degraded()` inside the closure (requires the AuthHealth to live in a mutable container).

### B4. `except Exception` in middleware swallows programming bugs and returns 401
**Reviewers:** python-pro (B1), authentication-specialist (cross-cutting note)
**Plan lines:** 1115-1120
**Issue:** Bare `except Exception` converts `AttributeError`, `TypeError`, etc. (e.g., the B1 scope bug) into a clean 401 response — masking real bugs and making the middleware impossible to debug.
**Fix:** Narrow to `except AuthError as exc:` and let everything else propagate. Log via `logger.exception(...)`.

### B5. Algorithm pinning not verified for JWT — vulnerable to `alg=none` and HS256/RSA confusion
**Reviewers:** api-security-specialist (B3)
**Plan lines:** 588-593 (Task 4 Step 4.3)
**Issue:** `JWTIdentityProvider.verify_token` delegates to the existing free-function `verify_token()` without verifying that the underlying call pins `algorithms=["HS256"]`. If the legacy function accepts any algorithm or omits the parameter (falling back to PyJWT defaults), the implementation is vulnerable to `alg=none` and HS256/RSA key-confusion attacks.
**Fix:** Inspect `mcp_common/auth/core.py` `verify_token()` as part of Step 4.3. If it does not pin `algorithms`, fix inline: `payload = jwt.decode(token, self._secret, algorithms=["HS256"], audience=audience, options={"require": ["exp", "iat", "iss", "aud"]})`. Add tests for `alg=none` rejection and HS256/RSA confusion.

### B6. `trusted_issuers` empty allowlist is fail-open
**Reviewers:** api-security-specialist (B4), authentication-specialist (m13)
**Plan lines:** 1441-1452 (Task 7 Step 7.3)
**Issue:** `if trusted and payload.iss not in trusted` — when `_trusted_issuers` is empty/None, ALL issuers are accepted. A misconfigured or empty `trusted_issuers` silently permits arbitrary issuers.
**Fix:** Default-deny: `if payload.iss not in trusted: raise UnknownIssuerError(...)` with no `if trusted` guard. Add a config-validation step that fails startup if `enabled=True` and `trusted_issuers=[]`. Same logic must apply to Anthropic provider (currently only enforced for JWT — auth-agent finding m13).

### B7. `_extract_permissions` defaults to `[Permission.READ]` on empty scope — fail-OPEN
**Reviewers:** api-security-specialist (B1), feature-dev:code-architect (MINOR)
**Plan lines:** ~867 (Task 5 Step 5.4)
**Issue:** A token with no scope claim gets READ access. Substring scope matching (`"read" in scopes`) is also wrong — `"read" in "read:admin"` grants admin tier via naive `in`.
**Fix:** Return `[]` on empty scope/permissions (default-deny). Split scopes on whitespace and use exact equality (`"read" in scopes_set`). If the token's `permissions` claim is present but contains no recognized values, raise `TokenInvalidError` (silent swallowing is a security issue).

### B8. AuthConfig reordering — Task 6 tests use new shape, Task 8 (Pydantic conversion) lands after
**Reviewers:** feature-dev:code-architect (BLOCKER)
**Plan lines:** Task 6 (line ~908) + Task 8 (line ~1561)
**Issue:** Task 6 middleware tests instantiate `AuthConfig(enabled=True, service_name="test-service")` in the new Pydantic shape, but the Pydantic rewrite lands in Task 8 — after Task 6. Task 6 will fail to import because the current `AuthConfig` is a plain Python class requiring `service_name` + `secret_env_var` positional kwargs.
**Fix:** Reorder so Task 8 runs before Task 6, OR split Task 8 into "8a: convert AuthConfig to Pydantic (no new fields)" + "8b: add trusted_issuers/identity_providers fields" and run 8a before Task 6.

### B9. `_payload_to_principal` field-name mismatch — `raw_claims` silently empty
**Reviewers:** feature-dev:code-architect (BLOCKER), api-security-specialist (m4)
**Plan lines:** 599 (Task 4 Step 4.3)
**Issue:** Reads `payload.raw_claims` but the existing `TokenPayload` field is named `raw` (per `mcp_common/auth/core.py:34`). The `hasattr(payload, "raw_claims")` guard always returns False, so `Principal.raw_claims` is silently `{}` for every JWT verification — audit logs and downstream consumers get empty data.
**Fix:** Rename `TokenPayload.raw` to `raw_claims` (the new spec uses `raw_claims`); remove the `hasattr` guard. Add a test asserting `principal.raw_claims == payload.raw_claims` after roundtrip.

### B10. `AuditEvent` vs `AuthAuditEvent` type confusion — runtime TypeError
**Reviewers:** feature-dev:code-architect (BLOCKER)
**Plan lines:** 1282 (Task 6 Step 6.6)
**Issue:** The new `@require_auth` references `AuditEvent(principal=..., decision=..., permission=..., tool=...)` but the existing audit type is `AuthAuditEvent` with entirely different fields (`timestamp`, `service`, `caller_service`, `caller_id`, `action`, `result`, `reason`). Type check fails; runtime would TypeError.
**Fix:** Either (a) keep `AuthAuditEvent` and map fields (`principal.issuer` → `caller_service`, `decision` → `result`, `tool` → `action`), or (b) add an `AuditEvent` dataclass to `audit.py` and document coexistence.

### B11. Anthropic provider spec claim ("PKCE + refresh + offline_access") not implemented
**Reviewers:** authentication-specialist (B1), documentation-specialist (IMPORTANT)
**Plan lines:** 633, 745-868 (Task 5)
**Issue:** Spec/plan claim PKCE + refresh tokens + `offline_access`, but the concrete implementation only exposes `verify_token` and `health`. No `exchange_authorization_code`, no `refresh_access_token`, no PKCE `code_verifier`. `client_secret` accepted but never used.
**Fix:** Split Task 5 into "5a: JWKS-only verification (verifies Anthropic-issued access tokens)" and "5b: OAuth authorization-code + refresh-token plumbing". Update the spec to match what 5a actually delivers; defer 5b to a follow-up spec.

### B12. Wire-up contract §1 violation — no Integration Contract blocks
**Reviewers:** critical-audit-specialist (B1)
**Plan lines:** All 17 tasks
**Issue:** `.claude/decisions/wire-up-contract.md` requires every phase deliverable to carry an Integration Contract block (Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added). The plan defines 4 implicit phases but none have these blocks.
**Fix:** Add explicit Integration Contract blocks to each phase. See the comprehensive-audit agent's report for suggested content.

## Cross-cutting IMPORTANT findings (deduplicated)

These were flagged by multiple reviewers or affect multiple tasks:

### I-1. Spec says `OneiricMCPConfig`, plan uses `MCPServerSettings` (terminology drift)
**Reviewers:** comprehensive-audit (I1), documentation (B1)
**Issue:** Spec repeatedly references `OneiricMCPConfig` (a class that may not exist in mcp-common — actual is `MCPServerSettings` at `cli/settings.py`). The plan uses `MCPServerSettings` in Task 9.
**Fix:** Decide: (a) integrate into `OneiricMCPConfig` per spec (requires Oneiric repo work), or (b) amend the spec to say `MCPServerSettings` is canonical, with a "spec deviation note" in Task 9.

### I-2. `integrate_with_readyz` parameter captured but never used
**Reviewers:** authentication-specialist (I3), comprehensive-audit (M1), mcp-integration-expert (I4) — **3 reviewers**
**Issue:** Parameter is documented, stored in closure, never read in `wrapper()`. Public-ish signature ships with dead code.
**Fix:** Either implement (`/readyz` aggregator that registers the tool), or remove from the public signature and file a follow-up. Don't ship a parameter that lies to callers.

### I-3. `trusted_issuers` only enforced for JWT, not Anthropic
**Reviewers:** comprehensive-audit (I2), authentication-specialist (m13)
**Issue:** Task 7 implements the check in `JWTIdentityProvider.verify_token` but `AnthropicIdentityProvider.verify_token` never consults `AuthConfig.trusted_issuers`. An Anthropic-issued token with `iss=evil-corp` would be accepted as long as the JWKS signature validates.
**Fix:** Add the issuer check to Anthropic provider; mirror JWT pattern; add test `test_anthropic_unknown_issuer_rejected`.

### I-4. Counters (verifications_total, errors_total) have no defined owner — `entities_count` stays at 0
**Reviewers:** comprehensive-audit (I4)
**Issue:** `AuthHealth` carries `verifications_total` and `errors_total`; Task 14.1 stores them on `Runtime` as `self._auth_counters`. But `BearerTokenMiddleware` has no reference to any counter store. No plan step shows middleware incrementing counters on success/failure. Wiring-discipline §3 `entities_count` can never move past zero in production.
**Fix:** Define an `AuthCounterStore` (or pass `runtime` to the middleware) and wire `BearerTokenMiddleware.on_request` to increment on every verification. Add a test asserting `entities_count` increments after 5 mocked token roundtrips.

### I-5. Task 14 sibling integration test body is a `...` placeholder (registration illusion)
**Reviewers:** comprehensive-audit (I5), feature-dev:code-architect (IMPORTANT)
**Issue:** Test body is `...` with a comment "construct server with auth enabled, hit /health, assert auth component". This is exactly the registration-illusion pattern that `mcp-surface-health-illusion.md` warned about — `/health` can include auth components without any middleware being constructed.
**Fix:** Replace with assertions that (a) invoke an unauthenticated tool call and assert 401, and (b) a request with a valid token reaches the tool body. Health-envelope check is supplementary, not primary.

### I-6. AuthConfig Pydantic rewrite drops env-var loading + placeholder rejection
**Reviewers:** feature-dev:code-architect (IMPORTANT)
**Issue:** Task 8 converts `AuthConfig` from plain class with `secret_env_var`, `_load_secret`, `_PLACEHOLDER_SECRETS`, `_MIN_SECRET_LENGTH` to a Pydantic `BaseModel`. The env-var-driven secret validation is silently dropped.
**Fix:** Preserve env-var loading in a Pydantic validator (`@field_validator("secret", mode="before")`) or document the breaking change with a sibling-server migration table.

### I-7. `register_http_health_route` contract change (200 → 503) breaks launchd probes
**Reviewers:** comprehensive-audit (IMPORTANT), mcp-integration-expert (I5)
**Issue:** The existing helper always returns 200. The plan introduces 503 when auth is degraded. css-mcp, mailgun-mcp, porkbun-domain-mcp, excalidraw-mcp, synxis-crs-mcp, neo4j-mcp, scapy-mcp, medium-mcp, opera-cloud-mcp all depend on the unconditional-200 contract. Launchd probes treat 503 as "server crashed" — alerts will fire on degraded auth, not just server down.
**Fix:** Either keep `/health` 200-only with `status: "degraded"` in body (consistent with existing `HealthCheckResult`), or introduce a separate `/readyz` for 503 semantics.

### I-8. `JWTIdentityProvider` uses HS256 with shared secret for cross-machine auth
**Reviewers:** authentication-specialist (I2)
**Issue:** Every sibling MCP server holds the same secret — compromise of one compromises all. No `kid`/JWKS, no per-service keypair, no key-rotation path. Cross-machine auth is the textbook asymmetric case (RS256/ES256 + JWKS).
**Fix:** Either split into `JWTIdentityProvider` (HS256, intra-process) and `JWKSIdentityProvider` (RS256/ES256, inter-service), or add `kid` field plus key-set support.

### I-9. `AuthConfig.secret.get_secret_value()` called on optional field — `AttributeError` at runtime
**Reviewers:** documentation (IMPORTANT), authentication-specialist (MINOR)
**Issue:** Embedded `auth-design.md` example calls `.get_secret_value()` on a field typed `str | None`.
**Fix:** Guard with `if auth_config.secret is None: raise RuntimeError(...)`, or change field type to `SecretStr | None` and keep the call.

### I-10. Single-author ADR re-review for closure of v4+ deferred item
**Reviewers:** comprehensive-audit (I6)
**Issue:** Task 16 has the executor author the ADR closure annotation themselves; no second reviewer. Wire-up contract §4 says features must transition through `built → wired → adopted`; this is the wired → adopted transition for an architectural decision.
**Fix:** Add a parallel subagent verification step (e.g., dispatch `mcp-integration-expert` or `architecture-council` to validate the new posture vs. the spec; require ≥1 non-author approval before bumping ADR status).

## Per-reviewer findings (indexed for traceability)

| Reviewer | BLOCKER | IMPORTANT | MINOR | Notable cross-cutting |
|---|---|---|---|---|
| python-pro | 2 | 8 | 12 | I-3 (`is_degraded` closure), I-2 (`integrate_with_readyz` indirectly) |
| authentication-specialist | 1 | 6 | 6 | B6 (trusted_issuers fail-open), B11 (Anthropic PKCE), I-2 (`integrate_with_readyz`), I-3 (trusted_issuers on Anthropic), B4 (cross-cutting on `except Exception`) |
| api-security-specialist | 4 | 9 | 12 | B5 (alg pinning), B6 (trusted_issuers), B7 (`_extract_permissions` fail-open) |
| mcp-integration-expert | 2 | 6 | 4 | **B1** (MiddlewareContext.scope), **B2** (HTTPException wrong), I-2 (`integrate_with_readyz`), I-7 (health contract) |
| critical-audit-specialist | 1 | 6 | 18 | B12 (wire-up contract), I-1 (OneiricMCPConfig), I-3 (trusted_issuers Anthropic), I-4 (counters), I-5 (placeholder test), I-7 (health contract), I-10 (single-author ADR) |
| feature-dev:code-architect | 4 | 7 | 2 | **B8** (AuthConfig reordering), **B9** (raw_claims mismatch), **B10** (AuditEvent confusion), B4 (`health.py` backwards dep) |
| documentation-specialist | 4 | 6 | 5 | I-1 (OneiricMCPConfig), I-9 (get_secret_value), B11 (Anthropic PKCE) |

## Recommended next actions

**1. Plan revision (2-4 hours, blocking implementation):**

a. **Fix B1 (MiddlewareContext) and B2 (HTTPException) — rewrite Task 6 around FastMCP's actual API.** Use `get_http_headers()` from `fastmcp.server.dependencies`; raise a custom `AuthError` carrying OAuth error codes instead of `HTTPException`.

b. **Fix B3 (`is_degraded` closure) — recompute per request.** Pass an `auth_health_callable` and call it inside the closure body each request.

c. **Fix B4 (bare except) — narrow to `AuthError`.** Use `logger.exception(...)`.

d. **Fix B5 (algorithm pinning) — verify and pin `algorithms=["HS256"]`.** Add alg=none and HS256/RSA confusion tests.

e. **Fix B6 (trusted_issuers fail-open) — default-deny semantics.** Apply to both JWT and Anthropic providers.

f. **Fix B7 (fail-open READ default) — return `[]` on empty scope.** Use exact-match scope checking.

g. **Fix B8 (AuthConfig reordering) — split Task 8 into 8a (Pydantic conversion) + 8b (new fields).** Move 8a before Task 6.

h. **Fix B9 (raw_claims field) — rename `TokenPayload.raw` → `raw_claims`.** Remove `hasattr` guard.

i. **Fix B10 (AuditEvent vs AuthAuditEvent) — pin field shape.** Match existing `AuthAuditEvent` or add new `AuditEvent` with explicit fields.

j. **Fix B11 (Anthropic PKCE/refresh) — split Task 5 into 5a (JWKS verify) + 5b (OAuth flow).** Update spec.

k. **Fix B12 (wire-up contract) — add Integration Contract blocks to each phase.**

l. **Fix I-1 (OneiricMCPConfig terminology drift) — reconcile spec vs plan.**

**2. Cross-cutting IMPORTANT fixes (recommended before implementation):**

- I-2 (`integrate_with_readyz`): drop or implement.
- I-3 (trusted_issuers Anthropic): add to Anthropic provider.
- I-4 (counters): define owner; wire middleware to increment.
- I-5 (Task 14 placeholder): replace `...` with concrete assertions.
- I-6 (AuthConfig rewrite): preserve env-var loading via validator.
- I-7 (`/health` contract): keep 200-only or introduce `/readyz`.
- I-8 (HS256 → asymmetric): document or add JWKS support.
- I-9 (get_secret_value on optional): guard.
- I-10 (single-author ADR): add parallel reviewer.

**3. Re-run a second round of multi-agent review after revision.** The 6-agent ADR 0016 pattern produced 25 BLOCKERs in round 1; this 7-agent round produced 12 distinct BLOCKERs and surfaced the most consequential bug (B1) only because mcp-integration-expert verified against the actual FastMCP source. Round 2 will catch the new bugs introduced by the revision.

## Out-of-scope items worth noting (not raised as findings)

- Tests for `Authorization` header smuggling and `alg=none` are added by api-security's BLOCKER fixes — no separate audit needed.
- httpx2 migration status (mcp-integration m4): verify mcp-common is on `httpx2` before implementing Task 5; if yes, `import httpx2 as httpx` per project memory `httpx-migration-sed-venv-contamination`.
- `MAHAVISHNU_TOOL_PROFILE` profile gating: auth surface is HTTP-only (middleware + `/health`), independent of tool profiles. Spec should note this.
- All 17 tasks have explicit commit messages — no findings on commit hygiene.

## Files referenced by reviewers

- `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-09-07-mcp-common-auth-primitives.md`
- `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-09-06-mcp-common-auth-primitives-design.md`
- `/Users/les/Projects/mcp-common/mcp_common/health.py:810` (existing `register_http_health_route`)
- `/Users/les/Projects/mcp-common/mcp_common/cli/settings.py:15` (`MCPServerSettings`)
- `/Users/les/Projects/mcp-common/mcp_common/auth/identity.py:7-15` (`KNOWN_SERVICES`)
- `/Users/les/Projects/mcp-common/mcp_common/auth/decorator.py` (`@require_auth`)
- `/usr/local/Cellar/mcpm/2.15.0_2/libexec/lib/python3.14/site-packages/fastmcp/server/middleware/middleware.py:47-61` (`MiddlewareContext` shape)
- `/usr/local/Cellar/mcpm/2.15.0_2/libexec/lib/python3.14/site-packages/fastmcp/server/dependencies.py:56` (`get_http_headers`)

## Status

Review complete. Plan needs revision before implementation. Estimated revision: 2-4 hours focused editing + spec amendment for the OneiricMCPConfig terminology drift. After revision, recommend a Round 2 multi-agent review (smaller, focused on the changes) before dispatching implementation subagents.
