# Security Checklist for Mahavishnu

This checklist ensures security best practices are followed during development and deployment of Mahavishnu.

## Pre-Commit Security Checks

- [ ] All API keys and secrets are stored in environment variables, not in code/config files
- [ ] Sensitive configuration files (config.yaml, oneiric.yaml) are added to .gitignore
- [ ] Path validation is implemented to prevent directory traversal attacks
- [ ] Input validation is performed on all user inputs
- [ ] JWT authentication is properly implemented when enabled
- [ ] Secrets are validated for minimum entropy/length requirements

## Configuration Security

- [ ] JWT secrets are at least 32 characters long
- [ ] Authentication is configurable via environment variables
- [ ] Default configurations do not include sensitive information
- [ ] Configuration loading follows the principle of least privilege

## Runtime Security

- [ ] File operations validate paths to prevent directory traversal
- [ ] External resources are accessed securely (HTTPS/TLS where applicable)
- [ ] Error messages do not leak sensitive system information
- [ ] Proper isolation between different workflow executions

## Deployment Security

- [ ] Container images are scanned for vulnerabilities
- [ ] Dependencies are regularly updated and scanned for known vulnerabilities
- [ ] Network access is restricted to necessary ports/services only
- [ ] Secrets management is handled by the platform (Kubernetes secrets, AWS Secrets Manager, etc.)

## Monitoring and Logging

- [ ] Authentication failures are logged for security monitoring
- [ ] Access patterns are monitored for anomalies
- [ ] Audit logs are maintained for compliance purposes
- [ ] Sensitive information is not logged in plaintext

## Incident Response

- [ ] Procedures are defined for rotating compromised secrets
- [ ] Contact information is available for security incidents
- [ ] Rollback procedures are documented and tested
- [ ] Security patches are applied promptly

---

## Task Orchestration Security (Phase 0)

### Webhook Authentication (`mahavishnu/core/webhook_auth.py`)

- [x] HMAC-SHA256 signature validation with constant-time comparison
- [x] Replay attack prevention via webhook_id + timestamp tracking
- [x] Configurable max age for webhook timestamps (default 5 minutes)
- [x] Timestamp validation prevents future timestamps (clock skew detection)
- [x] Database fail-open for availability during outages
- [x] Comprehensive error categorization (signature_mismatch, expired, replay_attack, etc.)

**Test Coverage:** 24 tests in `tests/security/test_webhooks.py`

### Input Sanitization (`mahavishnu/core/task_models.py`)

- [x] Pydantic v2 models for all task inputs
- [x] Null byte removal (prevents null byte injection)
- [x] Control character removal (except newline, tab)
- [x] Length validation on all text fields
- [x] Repository name whitelist pattern (alphanumeric, dash, underscore)
- [x] FTS query sanitization with dangerous pattern detection
- [x] Deadline validation (must be future date)
- [x] Tag validation (pattern, length, deduplication)

**Dangerous Patterns Blocked:**
- SQL comments: `--`, `/*`, `*/`
- SQL statement separator: `;`
- Extended stored procedures: `xp_`
- Function calls: `exec(`, `execute(`

**Test Coverage:** 25 tests in `tests/security/test_validation.py`

### Audit Logging (`mahavishnu/core/task_audit.py`)

- [x] 14 task lifecycle events logged
- [x] Sensitive field redaction (description, metadata, deadline, tags)
- [x] Sensitive key pattern detection (api_key, password, secret, token, credential)
- [x] Deep recursive redaction for nested structures
- [x] User attribution for all operations
- [x] UTC timestamps for consistency
- [x] Structured logging for forensic analysis

**Events Logged:**
- task_created, task_updated, task_deleted
- task_assigned, task_started, task_completed, task_cancelled
- task_blocked, task_unblocked
- quality_gate_passed, quality_gate_failed
- task_access_denied, task_validation_failure

**Test Coverage:** 25 tests in `tests/security/test_task_audit.py`

### Security Test Suite (`tests/security/`)

- [x] SQL injection tests (`test_sql_injection.py`) - 29 tests
- [x] Path traversal tests (`test_path_traversal.py`) - 29 tests
- [x] XSS prevention tests (`test_xss_prevention.py`) - 29 tests
- [x] Authorization bypass tests (`test_auth_bypass.py`) - 23 tests
- [x] Webhook security tests (`test_webhooks.py`) - 24 tests
- [x] Input validation tests (`test_validation.py`) - 25 tests
- [x] Audit logging tests (`test_task_audit.py`) - 25 tests

**Total:** 193 security tests

### Security Documentation

- [x] Security runbook (`docs/runbooks/security.md`)
- [x] Updated SECURITY_CHECKLIST.md with Task Orchestration components

---

## Security Test Commands

```bash
# Run all security tests
pytest tests/security/ -v --no-cov

# Run specific test categories
pytest tests/security/test_sql_injection.py -v
pytest tests/security/test_path_traversal.py -v
pytest tests/security/test_webhooks.py -v
pytest tests/security/test_validation.py -v
pytest tests/security/test_task_audit.py -v

# Run with coverage
pytest tests/security/ --cov=mahavishnu.core --cov-report=html
```

## Security-Related Environment Variables

| Variable | Purpose | Minimum Length |
|----------|---------|----------------|
| `MAHAVISHNU_AUTH_SECRET` | JWT signing secret | 32 characters |
| `MAHAVISHNU_WEBHOOK_SECRET` | Webhook signature secret | 16 characters |

## Related Documentation

- [Security Runbook](runbooks/security.md) - Incident response procedures
- [Phase 0 Action Plan](../PHASE_0_ACTION_PLAN.md) - Implementation details
- [Master Plan v3](../TASK_ORCHESTRATION_MASTER_PLAN_V3.md) - Architecture overview
