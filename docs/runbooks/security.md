# Security Runbook

This runbook provides operational procedures for security-related incidents and tasks in the Mahavishnu Task Orchestration System.

## Table of Contents

1. [Security Incident Response](#security-incident-response)
2. [Webhook Security Operations](#webhook-security-operations)
3. [Input Validation Failures](#input-validation-failures)
4. [Audit Log Investigation](#audit-log-investigation)
5. [Access Control Issues](#access-control-issues)
6. [Security Maintenance Tasks](#security-maintenance-tasks)

---

## Security Incident Response

### Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| **P0 - Critical** | Active attack, data breach | 15 minutes | SQL injection success, auth bypass |
| **P1 - High** | Vulnerability exploited | 1 hour | Failed injection attempts (repeated) |
| **P2 - Medium** | Suspicious activity | 4 hours | Unusual access patterns |
| **P3 - Low** | Security hygiene issues | 24 hours | Missing headers, config drift |

### Incident Response Playbook

#### Step 1: Detect (0-5 minutes)
```bash
# Check recent authentication failures
grep "task_access_denied" /var/log/mahavishnu/audit.log | tail -50

# Check webhook authentication failures
grep "signature_mismatch\|replay_attack" /var/log/mahavishnu/webhook.log | tail -50

# Check validation failures
grep "task_validation_failure" /var/log/mahavishnu/audit.log | tail -50
```

#### Step 2: Contain (5-15 minutes)
```bash
# Block suspicious IP addresses (if applicable)
# Note: This would be done at the infrastructure level

# Disable affected webhook endpoints
# Update settings/local.yaml:
# webhooks:
#   enabled: false

# Rotate compromised secrets
export MAHAVISHNU_WEBHOOK_SECRET="$(openssl rand -hex 32)"
```

#### Step 3: Eradicate (15-60 minutes)
1. Identify attack vector from audit logs
2. Patch vulnerability if in application code
3. Update security rules/patterns if needed
4. Deploy fix

#### Step 4: Recover (1-4 hours)
1. Verify fix is deployed
2. Re-enable services
3. Monitor for recurrence
4. Update runbook if needed

#### Step 5: Post-Incident (24-48 hours)
1. Write incident report
2. Schedule post-mortem
3. Implement preventive measures
4. Update security tests

---

## Webhook Security Operations

### Monitoring Webhook Health

```bash
# Check webhook authentication statistics
curl -s http://localhost:8680/api/webhooks/stats | jq

# View recent webhook failures
curl -s http://localhost:8680/api/webhooks/failures?limit=20 | jq
```

### Webhook Statistics Explained

| Metric | Normal Range | Action Threshold |
|--------|--------------|------------------|
| `total_verified` | Increasing | - |
| `signature_failures` | < 1% of total | > 5% |
| `replay_attacks_blocked` | 0 | Any |
| `expired_webhooks_rejected` | < 0.1% | > 1% |

### Common Webhook Issues

#### Signature Mismatch

**Symptoms:**
- High `signature_failures` count
- 401 responses to webhook calls

**Troubleshooting:**
1. Verify webhook secret is correct
2. Check timestamp format (ISO 8601)
3. Ensure payload is not modified

```bash
# Test webhook signature locally
python -c "
from mahavishnu.core.webhook_auth import WebhookAuthenticator
import hmac, hashlib

secret = 'your-secret'
payload = b'{\"test\": \"data\"}'
timestamp = '2026-02-18T12:00:00Z'

mac = hmac.new(secret.encode(), payload, hashlib.sha256)
signature = f'sha256={mac.hexdigest()}'
print(f'Signature: {signature}')
"
```

#### Replay Attack Detection

**Symptoms:**
- `replay_attacks_blocked` > 0
- Same webhook_id seen multiple times

**Action:**
1. Identify source of duplicate webhooks
2. Check for network retry storms
3. Verify webhook client idempotency

### Cleaning Up Old Webhook Records

```bash
# Remove webhook records older than 30 days
curl -X POST http://localhost:8680/api/webhooks/cleanup?retention_days=30
```

---

## Input Validation Failures

### Validation Failure Categories

| Category | Examples | Log Pattern |
|----------|----------|-------------|
| **SQL Injection** | `--`, `/*`, `;`, `xp_` | `dangerous pattern` |
| **Path Traversal** | `../`, `./`, `\` | `invalid repository` |
| **Null Byte** | `\x00` in strings | Removed silently |
| **Length Violation** | Title > 200 chars | `too long` |

### Investigating Validation Failures

```bash
# Find recent validation failures
grep "task_validation_failure" /var/log/mahavishnu/audit.log | \
  jq -r '.details.validation_errors[]' | sort | uniq -c | sort -rn

# Most common attack patterns
grep "dangerous" /var/log/mahavishnu/audit.log | \
  jq -r '.details.submitted_data.query' | sort | uniq -c | sort -rn | head -20
```

### Adding New Dangerous Patterns

Edit `mahavishnu/core/task_models.py`:

```python
# In FTSSearchQuery.sanitize_query()
dangerous_patterns = [
    ("--", "SQL comment"),
    ("/*", "SQL comment start"),
    # Add new patterns here:
    ("xp_", "Extended stored procedure"),
    ("sp_", "Stored procedure prefix"),  # NEW
]
```

---

## Audit Log Investigation

### Audit Log Location

```
/var/log/mahavishnu/audit.log          # Main audit log
/var/log/mahavishnu/audit.json         # Structured JSON format
```

### Audit Event Types

| Event Type | Description | Use Case |
|------------|-------------|----------|
| `task_created` | New task created | Track creation patterns |
| `task_updated` | Task modified | Detect bulk changes |
| `task_deleted` | Task removed | Forensic analysis |
| `task_access_denied` | Authorization failure | Attack detection |
| `task_validation_failure` | Input rejected | Attack detection |
| `quality_gate_failed` | Quality check failed | Not security-related |

### Searching Audit Logs

```bash
# Find all actions by a user
grep "user_id.*user-123" /var/log/mahavishnu/audit.json | jq

# Find all denied accesses today
grep "task_access_denied" /var/log/mahavishnu/audit.json | \
  jq "select(.timestamp | startswith(\"$(date +%Y-%m-%d)\"))"

# Find potential data exfiltration (large exports)
grep "task.*list" /var/log/mahavishnu/audit.json | \
  jq "select(.details.result_count > 1000)"

# Count events by type
grep -o '"event_type": "[^"]*"' /var/log/mahavishnu/audit.json | \
  sort | uniq -c | sort -rn
```

### Sensitive Field Redaction

The following fields are automatically redacted in audit logs:

- `description` - Task details
- `metadata` - Arbitrary key-value data
- `deadline` - Business timing info
- `tags` - Sensitive categorization
- Keys containing: `api_key`, `password`, `secret`, `token`, `credential`

---

## Access Control Issues

### Common Access Issues

#### User Cannot Access Their Own Tasks

**Troubleshooting:**
1. Verify user_id in request matches task owner
2. Check task status (completed tasks may have different permissions)
3. Verify repository access permissions

#### Unauthorized Cross-Repository Access

**Prevention:**
- Always filter by repository in queries
- Verify user has access to repository before returning tasks

### Debugging Authorization

```bash
# Check user's recent access attempts
grep "user-123" /var/log/mahavishnu/audit.json | \
  jq "select(.event_type == \"task_access_denied\")"
```

---

## Security Maintenance Tasks

### Weekly Tasks

- [ ] Review authentication failure rates
- [ ] Check for new attack patterns in validation failures
- [ ] Verify webhook secret rotation schedule
- [ ] Update security test coverage if new patterns found

### Monthly Tasks

- [ ] Rotate webhook secrets
- [ ] Review and clean up old webhook records
- [ ] Audit user permissions and access patterns
- [ ] Run full security test suite: `pytest tests/security/ -v`
- [ ] Update dependencies: `safety check && pip-audit`

### Quarterly Tasks

- [ ] Security architecture review
- [ ] Penetration testing (internal or external)
- [ ] Update security documentation
- [ ] Review and update SLI/SLO targets for security

### Secret Rotation Schedule

| Secret | Rotation Frequency | Location |
|--------|-------------------|----------|
| `MAHAVISHNU_WEBHOOK_SECRET` | 90 days | Environment variable |
| `MAHAVISHNU_AUTH_SECRET` | 90 days | Environment variable |
| Database credentials | 90 days | Infrastructure |

### Running Security Tests

```bash
# Run all security tests
pytest tests/security/ -v --no-cov

# Run specific test category
pytest tests/security/test_sql_injection.py -v
pytest tests/security/test_path_traversal.py -v
pytest tests/security/test_webhooks.py -v

# Run with coverage
pytest tests/security/ --cov=mahavishnu.core --cov-report=html
```

---

## Emergency Contacts

| Role | Contact | Escalation Time |
|------|---------|-----------------|
| On-Call Engineer | @oncall | Immediate |
| Security Team | security@example.com | 15 minutes |
| Engineering Manager | @eng-manager | 30 minutes |

## Related Documentation

- [SECURITY_CHECKLIST.md](../../SECURITY_CHECKLIST.md) - Security implementation checklist
- [TASK_ORCHESTRATION_MASTER_PLAN_V3.md](../TASK_ORCHESTRATION_MASTER_PLAN_V3.md) - Master plan
- [PHASE_0_ACTION_PLAN.md](../PHASE_0_ACTION_PLAN.md) - Phase 0 implementation details
