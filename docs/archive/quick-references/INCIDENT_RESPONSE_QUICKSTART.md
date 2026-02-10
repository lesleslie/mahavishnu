# Incident Response Quickstart

Get started with auto-incident response in 10 minutes.

## 10-Minute Setup

### Step 1: Enable Incident Response (1 minute)

```bash
# Add to settings/mahavishnu.yaml
incident_response:
  enabled: true
  auto_remediation: true
  notifications:
    slack:
      webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    pagerduty:
      api_key: "your_pagerduty_api_key"
```

### Step 2: Start Incident Manager (1 minute)

```bash
# Start the incident management system
mahavishnu incidents start

# Check status
mahavishnu incidents status
```

### Step 3: Submit Test Events (2 minutes)

```python
from mahavishnu.patterns.incident_response import (
    IncidentManager,
    IncidentEvent,
    IncidentSeverity,
)
from datetime import UTC, datetime

# Create manager
manager = IncidentManager(config)
await manager.start()

# Submit test events
for i in range(10):
    event = IncidentEvent(
        event_id=f"test_{i}",
        timestamp=datetime.now(tz=UTC),
        event_type="error",
        source="api",
        severity=IncidentSeverity.HIGH,
        message=f"Test error {i}",
    )
    await manager.submit_event(event)
```

### Step 4: View Detected Incidents (1 minute)

```bash
# List incidents
mahavishnu incidents list

# View details
mahavishnu incidents get <incident_id>
```

### Step 5: Test Auto-Remediation (3 minutes)

```bash
# View recommended actions
mahavishnu incidents mitigate <incident_id> --list-actions

# Execute safe action
mahavishnu incidents mitigate <incident_id> --action clear_cache
```

### Step 6: View Dashboard (2 minutes)

```bash
# Start dashboard
mahavishnu incidents dashboard --port 8080

# Open browser
open http://localhost:8080
```

---

## 15 Common Incident Scenarios

### Scenario 1: API Error Burst

**Detection**: 10+ errors within 5 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "api_error", "message": "POST /api/users returned 500"},
    {"type": "api_error", "message": "GET /api/orders timeout"}
  ]
}
```

**Auto-Remediation**:
1. Clear application cache
2. Scale up resources
3. Restart service (if approved)

**Manual Steps** (if auto-remediation fails):
```bash
# Check API logs
mahavishnu logs tail api --since 5m

# Restart API service
mahavishnu service restart api

# Check health
mahavishnu health check api
```

---

### Scenario 2: Service Down

**Detection**: 5+ service unavailable events within 1 minute

**Symptoms**:
```json
{
  "events": [
    {"type": "service_down", "source": "auth_service"}
  ]
}
```

**Auto-Remediation**:
1. Attempt service restart (requires approval)
2. Rollback deployment (if critical)

**Manual Steps**:
```bash
# Check service status
mahavishnu service status auth_service

# View service logs
mahavishnu logs tail auth_service

# Restart service
mahavishnu service restart auth_service

# Rollback if needed
mahavishnu deployment rollback --service auth_service
```

---

### Scenario 3: Memory Exhaustion

**Detection**: 3+ high memory events within 2 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "memory_high", "message": "Memory at 95%"}
  ]
}
```

**Auto-Remediation**:
1. Scale up resources
2. Kill zombie processes

**Manual Steps**:
```bash
# Check memory usage
mahavishnu metrics memory --detail

# Kill zombie processes
mahavishnu processes kill-zombies

# Scale up workers
mahavishnu workers scale --count 10
```

---

### Scenario 4: Database Connection Failures

**Detection**: Service down with database source

**Symptoms**:
```json
{
  "events": [
    {"type": "database_error", "message": "Connection pool exhausted"}
  ]
}
```

**Auto-Remediation**:
1. Scale up (if connection pool issue)
2. Notifications only (manual intervention required)

**Manual Steps**:
```bash
# Check database status
mahavishnu database status

# Check connection pool
mahavishnu database pool-stats

# Restart database if needed
mahavishnu database restart
```

---

### Scenario 5: Cache Failure

**Detection**: Error burst with cache-related errors

**Symptoms**:
```json
{
  "events": [
    {"type": "cache_error", "message": "Redis connection refused"}
  ]
}
```

**Auto-Remediation**:
1. Clear cache
2. Notifications (if persistent)

**Manual Steps**:
```bash
# Check cache status
mahavishnu cache status

# Clear cache
mahavishnu cache clear --all

# Restart cache service
mahavishnu service restart redis
```

---

### Scenario 6: Performance Degradation

**Detection**: 10+ slow request events within 5 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "slow_request", "message": "Request took 5.2s"}
  ]
}
```

**Auto-Remediation**:
1. Scale up resources
2. Clear cache

**Manual Steps**:
```bash
# Check performance metrics
mahavishnu metrics performance

# View slow queries
mahavishnu database slow-queries

# Scale up
mahavishnu workers scale --count 5
```

---

### Scenario 7: Disk Space Low

**Detection**: 3+ low disk space events within 5 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "disk_low", "message": "Disk at 92%"}
  ]
}
```

**Auto-Remediation**: Notifications only

**Manual Steps**:
```bash
# Check disk usage
mahavishn metrics disk

# Clear old logs
mahavishnu logs clear --older-than 7d

# Clear cache
mahavishnu cache clear --all

# Add storage (manual)
```

---

### Scenario 8: Workflow Failure Spike

**Detection**: 8+ workflow failures within 5 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "workflow_failed", "message": "ETL pipeline failed"}
  ]
}
```

**Auto-Remediation**:
1. Clear cache
2. Restart workflow engine (if approved)

**Manual Steps**:
```bash
# Check workflow status
mahavishnu workflows status

# View failed workflows
mahavishnu workflows list --status failed

# Retry failed workflows
mahavishnu workflows retry --failed-since 10m
```

---

### Scenario 9: Quality Drop

**Detection**: 5+ quality check failures within 10 minutes

**Symptoms**:
```json
{
  "events": [
    {"type": "quality_failed", "message": "Coverage dropped to 72%"}
  ]
}
```

**Auto-Remediation**: Notifications only

**Manual Steps**:
```bash
# Run quality checks
mahavishnu quality check

# View quality report
mahavishnu quality report

# Fix issues (manual)
```

---

### Scenario 10: Network Partition

**Detection**: Service down with network errors

**Symptoms**:
```json
{
  "events": [
    {"type": "network_error", "message": "Connection refused"}
  ]
}
```

**Auto-Remediation**: Critical notifications only

**Manual Steps**:
```bash
# Check network status
mahavishnu network status

# Test connectivity
mahavishnu network test --target database

# Restart networking (manual)
```

---

### Scenario 11: Zombie Processes

**Detection**: Resource leak events

**Symptoms**:
```json
{
  "events": [
    {"type": "resource_leak", "message": "High process count"}
  ]
}
```

**Auto-Remediation**:
1. Kill zombie processes

**Manual Steps**:
```bash
# List zombie processes
mahavishnu processes list --zombies

# Kill zombies
mahavishnu processes kill-zombies
```

---

### Scenario 12: Rate Limiting

**Detection**: Error burst with rate limit errors

**Symptoms**:
```json
{
  "events": [
    {"type": "rate_limit", "message": "Rate limit exceeded"}
  ]
}
```

**Auto-Remediation**: Notifications with recommendations

**Manual Steps**:
```bash
# Check rate limit status
mahavishnu api rate-limit --status

# Implement backoff (code change)
# Increase quota (manual)
```

---

### Scenario 13: SSL Certificate Expiry

**Detection**: Service down with SSL errors

**Symptoms**:
```json
{
  "events": [
    {"type": "ssl_error", "message": "Certificate expired"}
  ]
}
```

**Auto-Remediation**: Critical notifications

**Manual Steps**:
```bash
# Check certificates
mahavishnu security check-certs

# Renew certificates
mahavishnu security renew-cert --service api
```

---

### Scenario 14: Deadlock Detected

**Detection**: Deadlock events

**Symptoms**:
```json
{
  "events": [
    {"type": "deadlock", "message": "Database deadlock detected"}
  ]
}
```

**Auto-Remediation**: High severity notifications

**Manual Steps**:
```bash
# Check database locks
mahavishnu database locks

# Kill blocking transactions
mahavishnu database kill-transaction --id <txn_id>
```

---

### Scenario 15: Security Breach

**Detection**: Security events (manual or automated)

**Symptoms**:
```json
{
  "events": [
    {"type": "security_breach", "message": "Unauthorized access detected"}
  ]
}
```

**Auto-Remediation**: Emergency paging, no auto-actions

**Manual Steps**:
```bash
# Lock down systems
mahavishnu security lockdown

# Preserve evidence
mahavishnu security preserve-evidence

# Notify security team (manual)
```

---

## CLI Command Reference

### Core Commands

```bash
# List incidents
mahavishnu incidents list
mahavishnu incidents list --status active
mahavishnu incidents list --severity critical

# Get incident details
mahavishnu incidents get <incident_id>
mahavishnu incidents get <incident_id> --timeline
mahavishnu incidents get <incident_id> --full

# Create incident manually
mahavishnu incidents create \
  --type error_burst \
  --severity high \
  --title "API Issues"

# Update incident
mahavishnu incidents update <incident_id> --status investigating
mahavishnu incidents update <incident_id> --assigned-to john.doe

# Assign incident
mahavishnu incidents assign <incident_id> john.doe

# Acknowledge incident
mahavishnu incidents acknowledge <incident_id>

# Mitigate (run remediation)
mahavishnu incidents mitigate <incident_id> --list-actions
mahavishnu incidents mitigate <incident_id> --action scale_up
mahavishnu incidents mitigate <incident_id> --action restart_service --approved-by john.doe

# Resolve incident
mahavishnu incidents resolve <incident_id> --notes "Fixed by scaling up"

# Close incident
mahavishnu incidents close <incident_id>

# View timeline
mahavishnu incidents timeline <incident_id>

# View post-mortem
mahavishnu incidents postmortem <incident_id>

# Statistics
mahavishnu incidents stats
mahavishnu incidents stats --by-severity

# Watch (live updates)
mahavishnu incidents watch

# Start dashboard
mahavishnu incidents dashboard --port 8080
```

### Detection Rules Commands

```bash
# List rules
mahavishnu incidents rules list

# Show rule
mahavishnu incidents rules show error_burst

# Enable/disable
mahavishnu incidents rules enable error_burst
mahavishnu incidents rules disable error_burst

# Update rule
mahavishnu incidents rules update error_burst --threshold 15
mahavishnu incidents rules update error_burst --time-window 600

# Create custom rule
mahavishnu incidents rules create \
  --id custom_rule \
  --name "Custom Rule" \
  --type performance_degradation \
  --severity high \
  --threshold 10
```

### Testing Commands

```bash
# Test rule
mahavishnu incidents test-rule error_burst

# Simulate incident
mahavishnu incidents simulate --type error_burst --severity high
```

---

## Dashboard Quick Reference

### Dashboard URL

```
http://localhost:8080
```

### Dashboard Sections

| Section | Description |
|---------|-------------|
| Overview | System health, active incidents, stats |
| Active Incidents | List of currently active incidents |
| Timeline | Recent incident activity |
| Metrics | Incident statistics and trends |
| Components | Component health status |

### Dashboard Actions

- **View Incident**: Click incident ID
- **Acknowledge**: Click "Acknowledge" button
- **Assign**: Click "Assign" button
- **Mitigate**: Click "Mitigate" button, select action
- **Resolve**: Click "Resolve" button, add notes
- **Export**: Click "Export" button for data export

### Dashboard Filters

```
# Filter by severity
?severity=critical

# Filter by status
?status=active

# Filter by component
?component=api

# Filter by time range
?since=1h
```

---

## Troubleshooting Guide

### Problem: No incidents detected

**Check**:
```bash
# Verify incident manager is running
mahavishnu incidents status

# Check if rules are enabled
mahavishnu incidents rules list --enabled

# Verify events are being submitted
mahavishnu incidents events list --last 10
```

**Solution**:
- Ensure incident manager is started
- Enable detection rules
- Verify event submission is working

---

### Problem: Too many false positives

**Solution**:
```bash
# Adjust thresholds
mahavishnu incidents rules update error_burst --threshold 15

# Increase time window
mahavishnu incidents rules update error_burst --time-window 600

# Require consecutive events
mahavishnu incidents rules update error_burst --require-consecutive
```

---

### Problem: Auto-remediation not working

**Check**:
```bash
# Verify auto-remediation is enabled
mahavishnu incidents config get auto_remediation

# Check remediation history
mahavishnu incidents history --remediation
```

**Solution**:
- Enable auto-remediation in config
- Verify actions are marked as safe
- Check action execution logs

---

### Problem: Notifications not sent

**Check**:
```bash
# Verify notification config
mahavishnu incidents config get notifications

# Test notification
mahavishnu incidents notify test --channel slack
```

**Solution**:
- Verify webhook URLs and API keys
- Test notification endpoints
- Check notification logs

---

### Problem: High MTTD/MTTR

**Solution**:
```bash
# Reduce detection interval
mahavishnu incidents rules update error_burst --check-interval 30

# Enable more auto-remediation
mahavishnu incidents config set auto_remediation=true

# Review and tune rules regularly
mahavishnu incidents rules review
```

---

## Configuration Quick Reference

### Basic Config

```yaml
# settings/mahavishnu.yaml
incident_response:
  enabled: true
  auto_remediation: true
  auto_resolution: false  # Requires manual approval

  # Detection settings
  detection:
    check_interval_seconds: 60
    event_retention_seconds: 3600
    max_events: 10000

  # Remediation settings
  remediation:
    safe_actions_only: true
    require_approval_for:
      - restart_service
      - rollback
    approval_timeout_seconds: 300

  # Notification settings
  notifications:
    slack:
      enabled: true
      webhook_url: "${SLACK_WEBHOOK_URL}"
      notify_on_severity:
        - critical
        - high
        - medium

    pagerduty:
      enabled: true
      api_key: "${PAGERDUTY_API_KEY}"
      service_key: "${PAGERDUTY_SERVICE_KEY}"
      notify_on_severity:
        - critical

    email:
      enabled: false
      smtp_server: "smtp.example.com"
      smtp_port: 587
      from_address: "incidents@example.com"

  # Dashboard settings
  dashboard:
    enabled: true
    port: 8080
    refresh_interval_seconds: 30

  # Retention settings
  retention:
    resolved_incidents_days: 90
    event_history_days: 7
    postmortems_days: 365
```

### Environment Variables

```bash
# Incident response
export MAHAVISHNU_INCIDENT_ENABLED=true
export MAHAVISHNU_INCIDENT_AUTO_REMEDIATION=true

# Notifications
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export PAGERDUTY_API_KEY="your_api_key"
export PAGERDUTY_SERVICE_KEY="your_service_key"

# Database (for incident storage)
export INCIDENT_DATABASE_URL="sqlite:///incidents.db"
```

---

## Best Practices (Quick Checklist)

### Detection
- [ ] Set thresholds based on baseline metrics
- [ ] Use multiple detection methods
- [ ] Review rules quarterly
- [ ] Test rules with simulated incidents

### Response
- [ ] Prioritize safety over speed
- [ ] Communicate early and often
- [ ] Document all actions
- [ ] Use auto-remediation for safe actions only

### Prevention
- [ ] Conduct blameless post-mortems
- [ ] Implement preventive measures
- [ ] Share findings across teams
- [ ] Improve observability

### Monitoring
- [ ] Set up dashboards for key metrics
- [ ] Configure appropriate alerts
- [ ] Monitor MTTD and MTTR
- [ ] Track auto-resolution rate

---

## Next Steps

1. **Configure**: Set up detection rules and thresholds
2. **Integrate**: Connect with existing monitoring
3. **Test**: Simulate incidents to verify response
4. **Train**: Educate team on response procedures
5. **Review**: Regularly review and tune the system
6. **Improve**: Continuously learn from incidents

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────┐
│            INCIDENT RESPONSE QUICK REFERENCE         │
├─────────────────────────────────────────────────────┤
│                                                     │
│  SEVERITY LEVELS:                                   │
│    LOW      → Log only                             │
│    MEDIUM   → Slack + log                          │
│    HIGH     → Slack + log + immediate response      │
│    CRITICAL → PagerDuty + Slack + log + emergency  │
│                                                     │
│  RESPONSE STAGES:                                   │
│    Assess → Contain → Investigate → Remediate →     │
│    Recover → Post-Mortem                            │
│                                                     │
│  COMMON COMMANDS:                                   │
│    mahavishnu incidents list                        │
│    mahavishnu incidents get <id>                    │
│    mahavishnu incidents mitigate <id> --action X    │
│    mahavishnu incidents resolve <id>                │
│    mahavishnu incidents dashboard                   │
│                                                     │
│  AUTO-REMEDIATION:                                  │
│    ✓ Scale up resources                             │
│    ✓ Clear cache                                    │
│    ✓ Kill zombie processes                          │
│    ✗ Restart service (requires approval)            │
│    ✗ Rollback (requires approval)                   │
│                                                     │
│  KEY METRICS:                                       │
│    MTTD: Mean Time To Detect                        │
│    MTTR: Mean Time To Resolve                       │
│    Target: MTTD < 5min, MTTR < 60min                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

For detailed documentation, see [AUTO_INCIDENT_RESPONSE.md](AUTO_INCIDENT_RESPONSE.md).
