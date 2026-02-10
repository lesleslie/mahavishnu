# Disaster Recovery Quickstart Guide

This guide provides quick reference for common disaster recovery operations in Mahavishnu.

## Table of Contents

1. [Immediate Actions](#immediate-actions)
2. [Backup Operations](#backup-operations)
3. [Restore Operations](#restore-operations)
4. [Testing and Drills](#testing-and-drills)
5. [Monitoring and Status](#monitoring-and-status)
6. [Emergency Contacts](#emergency-contacts)

---

## Immediate Actions

### Emergency Checklist

If you're reading this during an emergency, follow these steps:

1. **ASSESS** - Determine the scope of the incident
   ```bash
   mahavishnu health check
   mahavishnu pool health
   ```

2. **DECLARE** - Declare disaster if needed
   - Notify on-call: #incidents Slack channel
   - Page: `pagerduty Mahavishnu-Production`

3. **RECOVER** - Follow the appropriate runbook below
   - Single server failure → [Runbook](docs/DISASTER_RECOVERY_PLAN.md#runbook-single-server-failure)
   - Region failure → [Runbook](docs/DISASTER_RECOVERY_PLAN.md#runbook-region-failure)
   - Database corruption → [Runbook](docs/DISASTER_RECOVERY_PLAN.md#runbook-database-corruption)

4. **VERIFY** - Confirm system is operational
   ```bash
   mahavishnu list-repos
   mahavishnu pool health
   ```

5. **DOCUMENT** - Log all actions and lessons learned

---

## Backup Operations

### Create Immediate Backup

```bash
# Create a full backup immediately
python scripts/backup_automation.py run-immediate --backup-type full

# Create an incremental backup
python scripts/backup_automation.py run-immediate --backup-type incremental

# Create an archival backup
python scripts/backup_automation.py run-immediate --backup-type archival
```

### Check Backup Status

```bash
# Show backup status and statistics
python scripts/backup_automation.py status

# Output includes:
# - Backup counts by type (incremental, full, archival)
# - Total storage used
# - Latest backup information
# - Retention policy details
```

### Validate Backup Integrity

```bash
# Validate all backups
python scripts/backup_automation.py validate-backups

# Validate specific backup
python scripts/backup_automation.py validate-backups --backup-id backup_20250205_020000

# Checks performed:
# - File integrity (SHA-256 checksums)
# - Archive format validation
# - Metadata verification
```

### Clean Up Old Backups

```bash
# Remove backups exceeding retention policy
python scripts/backup_automation.py cleanup-old

# Automatically enforces:
# - Daily incremental: 7 days
# - Weekly full: 4 weeks
# - Monthly archival: 12 months
```

---

## Restore Operations

### Run Restore Test

```bash
# Test restore from latest backup
python scripts/restore_test.py run-test

# Test restore from specific backup
python scripts/restore_test.py run-test --backup-id backup_20250205_020000

# Output includes:
# - Restore success/failure status
# - RTO (Recovery Time Objective)
# - RPO (Recovery Point Objective)
# - Integrity validation results
```

### Measure RTO/RPO

```bash
# Measure Recovery Time Objective
python scripts/restore_test.py measure-rto --backup-id backup_20250205_020000

# Target: < 15 minutes
# Actual: 10.5 minutes ✓

# Measure Recovery Point Objective
python scripts/restore_test.py measure-rpo

# Target: < 5 minutes data loss
# Actual: 2.3 minutes ✓
```

### Generate Restore Test Report

```bash
# Show last 10 test results
python scripts/restore_test.py report

# Show last 20 test results
python scripts/restore_test.py report --last 20

# Includes:
# - RTO/RPO metrics
# - Integrity check summary
# - Success rate statistics
# - Recent test details
```

### Restore from Backup (Production)

```bash
# List available backups
python scripts/backup_automation.py status

# Restore from specific backup (CAUTION: Production operation)
mahavishnu restore --backup-id backup_20250205_020000

# Verify restore
mahavishnu health check
mahavishnu list-repos
```

---

## Testing and Drills

### Run Disaster Recovery Drill

```bash
# List available scenarios
python scripts/disaster_recovery_drill.py list-scenarios

# Run specific scenario
python scripts/disaster_recovery_drill.py run-drill --scenario single_server_failure

# Available scenarios:
# - single_server_failure
# - region_failure
# - database_corruption
# - network_partition
# - data_deletion

# Dry run (validate without executing)
python scripts/disaster_recovery_drill.py run-drill --scenario single_server_failure --dry-run
```

### Generate Drill Report

```bash
# Summary report
python scripts/disaster_recovery_drill.py report

# Specific drill report
python scripts/disaster_recovery_drill.py report --drill-id drill_single_server_failure_20250205_100000

# Includes:
# - Drill execution summary
# - Steps completed
# - RTO/RPO achieved
# - Issues encountered
```

---

## Monitoring and Status

### System Health Check

```bash
# Overall system health
mahavishnu health check

# DR-specific health check
mahavishnu dr check

# Output includes:
# - Backup availability
# - Backup integrity status
# - Recent backup age
# - Overall DR health status
```

### Pool Health

```bash
# Check pool status
mahavishnu pool health

# Shows:
# - Active pools
# - Worker status
# - Pool performance metrics
```

### View Backup Metrics

```bash
# Via CLI
python scripts/backup_automation.py status

# Via monitoring dashboard (if configured)
# http://localhost:9090/graph?g0.expr=backup_success_rate
# http://localhost:9090/graph?g0.expr=backup_age_seconds
```

---

## Common Scenarios

### Scenario: Backup Failed

**Symptoms:**
- Alert: "Backup failed for [backup_type]"
- Backup status shows failed attempts

**Actions:**
```bash
# Check backup logs
journalctl -u mahavishnu-backup -n 100

# Check available disk space
df -h /opt/mahavishnu/backups

# Attempt manual backup
python scripts/backup_automation.py run-immediate --backup-type full

# If still failing, escalate to on-call
```

### Scenario: Restore Test Failed

**Symptoms:**
- Alert: "Restore test failed for [backup_id]"
- Test report shows integrity check failure

**Actions:**
```bash
# Check test details
python scripts/restore_test.py run-test --backup-id <backup_id>

# Validate backup integrity
python scripts/backup_automation.py validate-backups --backup-id <backup_id>

# If backup corrupted, try earlier backup
python scripts/restore_test.py run-test  # Uses latest valid backup
```

### Scenario: RTO/RPO Exceeded

**Symptoms:**
- Alert: "RTO exceeded: 20 minutes (target: < 15 min)"
- Alert: "RPO exceeded: 8 minutes (target: < 5 min)"

**Actions:**
```bash
# Check restore performance
python scripts/restore_test.py measure-rto --backup-id <backup_id>

# Identify bottleneck
# - Network latency?
# - Disk I/O?
# - Backup size?

# Optimize based on findings:
# - Use incremental backups for faster restores
# - Compress backups for faster transfer
# - Use local storage for faster access
```

---

## Scheduled Operations

### Automation Setup

**Cron Jobs (Recommended):**

```bash
# Daily incremental backup (2 AM UTC)
0 2 * * * /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type incremental

# Weekly full backup (Sunday 3 AM UTC)
0 3 * * 0 /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type full

# Monthly archival backup (1st of month 4 AM UTC)
0 4 1 * * /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type archival

# Weekly restore test (Saturday 5 AM UTC)
0 5 * * 6 /path/to/mahavishnu/scripts/restore_test.py run-test

# Weekly backup validation (Wednesday 6 AM UTC)
0 6 * * 3 /path/to/mahavishnu/scripts/backup_automation.py validate-backups
```

**Systemd Timers (Alternative):**

Create `/etc/systemd/system/mahavishnu-backup.service`:
```ini
[Unit]
Description=Mahavishnu Backup Service
After=network.target

[Service]
Type=oneshot
ExecStart=/path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type full
User=mahavishnu
Group=mahavishnu
```

Create `/etc/systemd/system/mahavishnu-backup.timer`:
```ini
[Unit]
Description=Mahavishnu Backup Timer
Requires=mahavishnu-backup.service

[Timer]
OnCalendar=Sun *-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable timer:
```bash
sudo systemctl enable mahavishnu-backup.timer
sudo systemctl start mahavishnu-backup.timer
```

---

## Configuration

### Backup Configuration

Edit `settings/mahavishnu.yaml`:

```yaml
backup:
  enabled: true
  directory: "./backups"

  schedules:
    daily_incremental:
      enabled: true
      time: "02:00"
      timezone: "UTC"
      retention_days: 7

    weekly_full:
      enabled: true
      day: "sunday"
      time: "03:00"
      timezone: "UTC"
      retention_weeks: 4

    monthly_archival:
      enabled: true
      day: 1
      time: "04:00"
      timezone: "UTC"
      retention_months: 12

  encryption:
    enabled: true
    algorithm: "AES-256-GCM"
    key_path: "/etc/mahavishnu/backup_key"

  validation:
    enabled: true
    checksum_algorithm: "sha256"
    verify_on_create: true
    verify_on_restore: true
```

### Disaster Recovery Configuration

```yaml
disaster_recovery:
  rto_target_minutes: 15
  rpo_target_minutes: 5

  automated_tests:
    enabled: true
    schedule: "weekly"
    day: "saturday"
    time: "05:00"

  drills:
    enabled: true
    frequency: "monthly"
    scenarios:
      - single_server_failure
      - region_failure
      - database_corruption
```

---

## Monitoring and Alerting

### Key Metrics to Monitor

**Backup Metrics:**
- `backup_success_rate` - Target: 99.9%
- `backup_age_seconds` - Latest backup age
- `backup_size_bytes` - Backup storage usage
- `backup_duration_seconds` - Backup creation time

**Restore Metrics:**
- `restore_test_success_rate` - Target: 100%
- `restore_rto_seconds` - Recovery time (target: < 900)
- `restore_rpo_seconds` - Data loss time (target: < 300)

**System Metrics:**
- `mahavishnu_health_status` - Overall health (1=healthy, 0=unhealthy)
- `mahavishnu_pool_status` - Pool health status

### Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Backup success rate | < 95% | < 90% |
| Backup age | > 26 hours | > 48 hours |
| Restore test success | < 100% | < 95% |
| RTO | > 12 min | > 20 min |
| RPO | > 4 min | > 10 min |

---

## Emergency Contacts

### On-Call Team

**Primary On-Call:**
- Slack: @mahavishnu-oncall
- PagerDuty: Mahavishnu-Production
- Phone: +1-555-0100

**Secondary On-Call:**
- Slack: @mahavishnu-oncall-backup
- Phone: +1-555-0101

**Escalation Path:**
1. Primary On-Call
2. Secondary On-Call
3. Engineering Manager: @eng-manager
4. DevOps Lead: @devops-lead
5. CTO: @cto

### Internal Channels

- **Incidents**: #mahavishnu-incidents
- **DR Updates**: #mahavishnu-dr
- **Status Page**: https://status.example.com

### External Contacts

- **Cloud Provider Support**: (check provider console)
- **Security Team**: security@example.com
- **Legal Team**: legal@example.com (for compliance)

---

## Quick Reference Commands

```bash
# === BACKUP OPERATIONS ===
python scripts/backup_automation.py run-immediate --backup-type full          # Create backup
python scripts/backup_automation.py status                                     # Check status
python scripts/backup_automation.py validate-backups                           # Validate backups
python scripts/backup_automation.py cleanup-old                                # Clean up old

# === RESTORE OPERATIONS ===
python scripts/restore_test.py run-test                                        # Run restore test
python scripts/restore_test.py measure-rto --backup-id <ID>                    # Measure RTO
python scripts/restore_test.py measure-rpo                                     # Measure RPO
python scripts/restore_test.py report --last 10                                # Test report

# === DR DRILLS ===
python scripts/disaster_recovery_drill.py list-scenarios                      # List scenarios
python scripts/disaster_recovery_drill.py run-drill --scenario <scenario>     # Run drill
python scripts/disaster_recovery_drill.py report                              # Drill report

# === SYSTEM HEALTH ===
mahavishnu health check                                                        # Overall health
mahavishnu pool health                                                         # Pool health
mahavishnu dr check                                                           # DR health
```

---

## Additional Resources

- [Full Disaster Recovery Plan](docs/DISASTER_RECOVERY_PLAN.md) - Comprehensive DR documentation
- [DR Implementation Guide](docs/DISASTER_RECOVERY_IMPLEMENTATION.md) - Technical implementation details
- [Production Deployment Guide](docs/PRODUCTION_DEPLOYMENT_GUIDE.md) - Production setup
- [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md) - All available tools

---

**Last Updated**: 2025-02-05
**Version**: 1.0

*For questions or issues, contact the DevOps team: devops@example.com*
