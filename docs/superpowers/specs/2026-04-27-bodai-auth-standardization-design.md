# Bodai Inter-Service Authentication Standardization

**Status:** Approved
**Date:** 2026-04-27
**Author:** Claude Code + les
**Unblocks:** Phase 2 engine surface expansion

## 1. Problem

Phase 2 of the Bodai master plan (engine surface expansion) has a hard blocker: no formal inter-service authentication architecture exists. All five ecosystem components have independently implemented JWT auth, but each uses its own env vars, its own `@require_auth()` decorator, and its own secret management. There is no mutual verification, no standardized RBAC, no audit logging, and no shared secret distribution.

The master plan states: "A separate security architecture document must exist before Phase 2 work begins."

## 2. Goals

1. Standardize inter-service authentication across all Bodai ecosystem components via a shared package in mcp-common
1. Add mutual service verification (issuer + audience claims) so a compromised service cannot impersonate another
1. Implement full RBAC across all services, based on Dhara's existing Permission model
1. Integrate secret management through Oneiric's adapter system (Infisical, AWS, GCP, Keyring, env, file)
1. Add structured audit logging for all authenticated MCP calls
1. Maintain full backward compatibility — auth defaults to disabled, existing env vars work, existing JWT tokens remain valid
1. Keep localhost development trivial — one env var, no ceremony

## 3. Non-Goals

- mTLS or certificate-based authentication (future enhancement)
- Secret rotation automation (future enhancement, Oneiric's `SecretKey.rotate()` provides the building blocks)
- User-facing authentication portals or OAuth flows
- Per-tool granular permissions beyond the four Permission levels (READ, WRITE, DELETE, ADMIN)
- Replacing unique service features: Mahavishnu's subscription auth, webhook auth, Dhara's mTLS

## 4. Threat Model

**External + mutual verification (Option 2).**

- Services protect against unauthorized external access to MCP ports
- Services verify callers are genuine ecosystem components (not impersonation)
- Services use audience claims to prevent token replay across services
- Auth defaults to disabled for local development
- Defense-in-depth features (mTLS, per-service cert rotation) are deferred to future phases

## 5. Architecture

### 5.1 Core + Extension Pattern

`mcp-common` provides canonical auth primitives. Each ecosystem service keeps a thin adapter (~10-20 lines) that wires core into its framework and adds unique features.

```
mcp_common/
  auth/
    __init__.py              # Public API re-exports
    core.py                  # JWT primitives, token create/verify
    permissions.py           # Permission enum, Role definitions
    identity.py              # Service identity, issuer claims, peer verification
    decorator.py             # @require_auth(permission) decorator
    audit.py                 # AuthAuditEvent schema, structured logging
    config.py                # AuthConfig, Oneiric integration, env var fallback
    exceptions.py            # AuthError hierarchy
```

### 5.2 Per-Service Adapters

Each service replaces its auth module internals with mcp-common delegates while keeping the public API identical:

```python
# session_buddy/mcp/auth.py (after migration — ~20 lines)
from mcp_common.auth import AuthConfig as CoreAuthConfig, require_auth

config = CoreAuthConfig(
    service_name="session-buddy",
    secret_env_var="SESSION_BUDDY_SECRET",
)

# Backward-compatible re-exports
validate_token = config.verify_token
```

### 5.3 Data Flow

```
Mahavishnu                    Session-Buddy
    |                              |
    |  POST /mcp/tools/call        |
    |  Authorization: Bearer <jwt> |
    |  ---------------------------> |
    |                              |  1. Verify JWT signature
    |                              |  2. Check iss in KNOWN_SERVICES
    |                              |  3. Check aud == "session-buddy"
    |                              |  4. Check Permission.WRITE
    |                              |  5. Emit audit event
    |                              |  6. Execute tool
    |  <-------------------------- |
    |       { result }             |
```

## 6. Service Identity and Mutual Verification

### 6.1 Known Services Registry

Defined in `mcp_common/auth/identity.py`:

```python
KNOWN_SERVICES: frozenset[str] = frozenset({
    "mahavishnu",
    "session-buddy",
    "akosha",
    "dhara",
    "crackerjack",
})
```

### 6.2 JWT Claims for Inter-Service Calls

| Claim | Value | Purpose |
|-------|-------|---------|
| `sub` | `"mahavishnu"` | Who is calling |
| `iss` | `"mahavishnu"` | Which service signed this token |
| `aud` | `"session-buddy"` | Intended recipient |
| `scopes` | `["read", "write"]` | Caller's permissions |
| `exp` | timestamp | Token expiry |
| `iat` | timestamp | When token was issued |
| `jti` | UUID | Token ID for audit traceability |

### 6.3 Verification Rules

1. **Signature check** — JWT must be signed with a trusted secret
1. **Issuer check** — `iss` must be in `KNOWN_SERVICES`
1. **Audience check** — `aud` must match the receiving service name
1. **Expiry check** — Standard JWT expiry

### 6.4 Dev Mode vs Production

| | Dev (localhost) | Production |
|--|----------------|------------|
| Secret source | `BODAI_SHARED_SECRET` env var | Per-service secrets via Oneiric adapter |
| Token signing | Any service signs with shared secret | Service signs with its own secret |
| Peer verification | Signature valid + issuer known | Signature valid against issuer's known secret |
| `aud` enforcement | Yes | Yes |

## 7. RBAC Model

### 7.1 Permission Enum

Defined in `mcp_common/auth/permissions.py`, based on Dhara's existing model:

```python
class Permission(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"
```

Dhara's `CHECKPOINT` and `RESTORE` permissions are service-specific and remain in Dhara's adapter as extensions.

### 7.2 Role Definitions

| Role | Permissions | Typical caller |
|------|------------|----------------|
| `reader` | READ | Monitoring, TUI, dashboards |
| `operator` | READ, WRITE | Mahavishnu orchestrating workflows |
| `admin` | READ, WRITE, DELETE, ADMIN | Human operators, deployment tools |

Roles are additive sets. `admin` includes all permissions. No negative permissions.

### 7.3 Tool Decoration

```python
@mcp.tool()
@require_auth(Permission.READ)
async def list_repos(limit: int = 50) -> list[dict]:
    ...

@mcp.tool()
@require_auth(Permission.WRITE)
async def store_evidence(evidence_id: str, text: str) -> dict:
    ...
```

The `@require_auth()` decorator with no arguments defaults to `Permission.READ`.

### 7.4 Default Service Roles

| Service | Mahavishnu's role | Human caller's role |
|---------|-------------------|---------------------|
| Session-Buddy | operator | reader |
| Akosha | operator | reader |
| Dhara | operator | reader |
| Crackerjack | reader | reader |

## 8. Secret Management

### 8.1 Oneiric Integration

Secrets are loaded through Oneiric's adapter system, not direct env var reads. Oneiric supports 6 providers: AWS Secrets Manager, GCP Secret Manager, Infisical, macOS Keyring, file-based, and environment variables.

```yaml
# settings/mahavishnu.yaml
secrets:
  adapter: infisical
  settings:
    environment: dev
    secret_path: /bodai/auth
```

### 8.2 Secret Loading Priority

```
1. Oneiric secrets adapter (Infisical, Vault, AWS, GCP, Keyring, file)
2. BODAI_SHARED_SECRET env var          -> dev fallback
3. {SERVICE}_SECRET env var              -> production fallback
4. No secret                            -> auth disabled
```

### 8.3 Service Secret Paths

Each service registers its auth secret under a known Oneiric path:

- `bodai/auth/mahavishnu`
- `bodai/auth/session-buddy`
- `bodai/auth/akosha`
- `bodai/auth/dhara`
- `bodai/auth/crackerjack`

### 8.4 Validation Rules

- Minimum 32 characters
- Reject known placeholders (`"changeme"`, `"secret"`, `"test"`) when auth is enabled
- Log a warning at startup when running with shared dev secret
- Oneiric's `SecretValueCache` provides TTL-based caching to avoid hammering the secret manager

## 9. Audit Logging

### 9.1 Audit Event Schema

Defined in `mcp_common/auth/audit.py`:

```python
@dataclass
class AuthAuditEvent:
    timestamp: datetime
    service: str
    caller_service: str
    caller_id: str
    action: str
    permission: Permission
    result: str                # "allowed" | "denied" | "error"
    reason: str | None
    source_ip: str | None
    token_id: str | None
```

### 9.2 What Gets Logged

| Event | Logged |
|-------|--------|
| Valid token, sufficient permissions | Yes (result: "allowed") |
| Valid token, insufficient permissions | Yes (result: "denied") |
| Invalid/expired token | Yes (result: "denied") |
| Unknown issuer | Yes (result: "denied") |
| Auth disabled, request received | No |

### 9.3 Output Format

Structured JSON to Python's `logging` module at `INFO` level:

```json
{
  "event": "auth_audit",
  "timestamp": "2026-04-27T08:15:00Z",
  "service": "session-buddy",
  "caller_service": "mahavishnu",
  "caller_id": "system",
  "action": "store_evidence",
  "permission": "write",
  "result": "allowed",
  "source_ip": "127.0.0.1"
}
```

### 9.4 Custom Sinks

Services can register custom audit sinks:

```python
class AuditSink(Protocol):
    def emit(self, event: AuthAuditEvent) -> None: ...

audit_logger.register_sink(my_database_sink)
```

## 10. Migration Strategy

### 10.1 Order

| Step | Service | Risk |
|------|---------|------|
| 1 | mcp-common (add `auth/` package) | None — new code |
| 2 | Crackerjack | Low — simplest auth |
| 3 | Akosha | Low — thin wrapper |
| 4 | Session-Buddy | Low — thin wrapper |
| 5 | Mahavishnu | Medium — most callers |
| 6 | Dhara | Medium — most complex, becomes reference |

### 10.2 Per-Service Migration Pattern

Each service follows 3 steps:

1. **Install and wire** — Replace auth module internals with mcp-common delegates, keep public API
1. **Update decorators** — Replace service-local `@require_auth()` with mcp-common version, add Permission levels
1. **Verify** — Run existing tests, confirm audit logs appear

### 10.3 Backward Compatibility

- `SESSION_BUDDY_SECRET`, `AKOSHA_JWT_SECRET`, etc. continue to work as env var fallbacks
- Auth defaults to disabled if no secret is configured
- Existing JWT tokens remain valid (same HS256 algorithm, same claims)
- `@require_auth()` with no arguments defaults to `Permission.READ`

### 10.4 What Stays Local

- Mahavishnu's `MultiAuthHandler` and subscription auth
- Mahavishnu's `WebhookAuthenticator`
- Dhara's mTLS support
- All WebSocket auth (already in mcp-common)

## 11. Validation

```bash
# After mcp-common auth package is added
python -c "from mcp_common.auth import AuthConfig, require_auth, Permission, AuthAuditEvent; print('OK')"

# After each service migration
pytest tests/unit/test_auth.py -v

# Integration test: verify inter-service auth works end-to-end
pytest tests/integration/test_inter_service_auth.py -v

# Verify no duplicate auth implementations remain
grep -r "class.*Auth" mahavishnu/core/ session-buddy/ akosha/ dhara/ crackerjack/ --include="*.py" | grep -v "test" | grep -v "__pycache__"
```

## 12. Future Enhancements

- Secret rotation automation via Oneiric's `SecretKey.rotate()`
- mTLS support for distributed deployments
- Per-tool granular permissions beyond the four Permission levels
- Audit log aggregation into a persistent store
- Token refresh flow for long-running sessions
