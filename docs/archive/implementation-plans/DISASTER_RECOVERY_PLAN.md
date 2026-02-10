# Mahavishnu Disaster Recovery Plan

**Version**: 1.0
**Last Updated**: 2025-02-05
**Owner**: DevOps Team
**Review Frequency**: Quarterly

## Executive Summary

This document outlines the comprehensive disaster recovery (DR) plan for Mahavishnu, including procedures for backup, restoration, failover, and recovery from various disaster scenarios. The plan is designed to achieve:

- **RTO (Recovery Time Objective)**: < 15 minutes for full system recovery
- **RPO (Recovery Point Objective)**: < 5 minutes data loss
- **Backup Success Rate**: 99.9%
- **Restore Test Success Rate**: 100%

## Table of Contents

1. [Scope and Objectives](#scope-and-objectives)
2. [Backup Strategy](#backup-strategy)
3. [Disaster Scenarios](#disaster-scenarios)
4. [Recovery Procedures](#recovery-procedures)
5. [Testing and Validation](#testing-and-validation)
6. [Communication Plan](#communication-plan)
7. [Roles and Responsibilities](#roles-and-responsibilities)
8. [Appendices](#appendices)

---

## Scope and Objectives

### Scope

This DR plan covers:

- Mahavishnu orchestration platform
- Configuration data (YAML files, settings)
- Workflow state and metadata
- Integration with ecosystem components (Session-Buddy, Akosha, etc.)
- MCP server configuration and state
- Backup and restore automation

### Exclusions

Out of scope:

- User application data (managed by respective applications)
- External service dependencies (GitLab, cloud providers)
- Network infrastructure (routers, switches)
- Physical hardware failures

### Objectives

**Primary Objectives:**
1. Minimize downtime during disasters
2. Prevent data loss
3. Ensure business continuity
4. Maintain service availability

**Recovery Objectives:**
- **RTO**: < 15 minutes (critical systems), < 1 hour (non-critical)
- **RPO**: < 5 minutes (critical data), < 1 hour (non-critical)

---

## Backup Strategy

### Backup Types

#### 1. Daily Incremental Backups

**Schedule**: 2:00 AM UTC daily
**Retention**: 7 days
**Content**: Changes since last backup
**Target RPO**: 5 minutes

**Execution:**
```bash
# Run immediate incremental backup
python scripts/backup_automation.py run-immediate --backup-type incremental

# Schedule automated daily backups (via cron/systemd)
0 2 * * * /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type incremental
```

#### 2. Weekly Full Backups

**Schedule**: 3:00 AM UTC on Sundays
**Retention**: 4 weeks
**Content**: Complete system backup
**Target RTO**: 15 minutes

**Execution:**
```bash
# Run immediate full backup
python scripts/backup_automation.py run-immediate --backup-type full

# Weekly schedule (cron)
0 3 * * 0 /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type full
```

#### 3. Monthly Archival Backups

**Schedule**: 4:00 AM UTC on 1st of month
**Retention**: 12 months
**Content**: Compressed long-term archive
**Purpose**: Compliance and long-term retention

**Execution:**
```bash
# Run immediate archival backup
python scripts/backup_automation.py run-immediate --backup-type archival

# Monthly schedule (cron)
0 4 1 * * /path/to/mahavishnu/scripts/backup_automation.py run-immediate --backup-type archival
```

### Backup Locations

**Primary Storage:**
- Local: `/opt/mahavishnu/backups/`
- Access: Immediate, low-latency

**Secondary Storage (Optional):**
- AWS S3: `s3://mahavishnu-backups/`
- Azure Blob: `mahavishnu-backups` container
- Purpose: Geo-redundancy, disaster recovery

### Backup Encryption

All backups are encrypted using AES-256-GCM:

```yaml
# Configuration (settings/mahavishnu.yaml)
backup:
  encryption:
    enabled: true
    algorithm: "AES-256-GCM"
    key_path: "/etc/mahavishnu/backup_key"
```

**Key Management:**
- Encryption keys stored in secure vault (e.g., HashiCorp Vault)
- Keys rotated quarterly
- Never store keys with backups

### Backup Validation

**Automated Validation:**
```bash
# Validate all backups
python scripts/backup_automation.py validate-backups

# Validate specific backup
python scripts/backup_automation.py validate-backups --backup-id backup_20250205_020000
```

**Validation Checks:**
- File integrity (SHA-256 checksums)
- Archive format validation
- Metadata verification
- Random sample restore tests

### Backup Retention

| Backup Type | Retention Period | Cleanup Schedule |
|-------------|------------------|------------------|
| Incremental | 7 days | Daily (after new backup) |
| Full | 4 weeks | Weekly (after new backup) |
| Archival | 12 months | Monthly (after new backup) |

**Manual Cleanup:**
```bash
python scripts/backup_automation.py cleanup-old
```

---

## Disaster Scenarios

### Scenario 1: Single Server Failure

**Severity**: Medium
**Frequency**: Low
**RTO**: < 5 minutes (auto-failover)
**RPO**: < 1 minute (replicated state)

**Detection:**
- Heartbeat monitoring failures
- Health check failures
- Service unavailability

**Impact:**
- Temporary service interruption
- Potential in-flight workflow failures
- Minimal data loss (replicated state)

**Recovery Strategy:**
1. Automatic failover to hot standby
2. Service restart on standby server
3. Traffic redirection via load balancer
4. Primary server investigation and repair

**Runbook:** [Single Server Failure Runbook](#runbook-single-server-failure)

---

### Scenario 2: Entire Region Failure

**Severity**: Critical
**Frequency**: Very Low
**RTO**: < 15 minutes (manual failover)
**RPO**: < 5 minutes (async replication)

**Detection:**
- Multi-region health check failures
- Network unreachability
- Cloud provider outage notifications

**Impact:**
- Complete service interruption in region
- Potential data loss since last replication
- Extended downtime during failover

**Recovery Strategy:**
1. Verify primary region failure
2. Activate DR region infrastructure
3. DNS failover to DR region
4. Restore from replicated backups
5. Verify service functionality

**Runbook:** [Region Failure Runbook](#runbook-region-failure)

---

### Scenario 3: Database Corruption

**Severity**: Critical
**Frequency**: Low
**RTO**: < 30 minutes (restore + replay)
**RPO**: < 5 minutes (transaction logs)

**Detection:**
- Checksum validation failures
- Database consistency check failures
- Application error reports

**Impact:**
- Data integrity issues
- Potential data loss
- Service interruption during recovery

**Recovery Strategy:**
1. Identify corruption scope
2. Stop database writes
3. Restore from latest valid backup
4. Replay transaction logs
5. Verify data integrity
6. Resume operations

**Runbook:** [Database Corruption Runbook](#runbook-database-corruption)

---

### Scenario 4: Network Partition

**Severity**: Medium to High
**Frequency**: Low
**RTO**: Variable (depends on partition duration)
**RPO**: < 1 minute (eventual consistency)

**Detection:**
- Network monitoring alerts
- Quorum failures
- Split-brain detection

**Impact:**
- Degraded service availability
- Potential data inconsistency
- Message queue delays

**Recovery Strategy:**
1. Detect partition boundaries
2. Activate degraded mode operation
3. Monitor queue depth
4. Resync on partition resolution
5. Verify consistency

**Runbook:** [Network Partition Runbook](#runbook-network-partition)

---

### Scenario 5: Malicious Data Deletion

**Severity**: Critical
**Frequency**: Very Low
**RTO**: < 30 minutes (restore)
**RPO**: < 5 minutes (before deletion)

**Detection:**
- Anomaly detection alerts
- Audit log analysis
- User reports

**Impact:**
- Data loss
- Service disruption
- Security investigation required

**Recovery Strategy:**
1. Stop ongoing deletion
2. Identify deletion scope and timeline
3. Restore from pre-incident backup
4. Verify restored data
5. Investigate root cause
6. Implement additional safeguards

**Runbook:** [Data Deletion Runbook](#runbook-data-deletion)

---

## Recovery Procedures

### General Recovery Process

**Pre-Recovery Checklist:**
- [ ] Confirm disaster scope and impact
- [ ] Identify latest valid backup
- [ ] Notify stakeholders
- [ ] Prepare recovery environment
- [ ] Document recovery timeline

**Recovery Steps:**
1. Assess disaster scope
2. Identify recovery strategy
3. Execute recovery procedure
4. Validate system functionality
5. Monitor for issues
6. Document lessons learned

### Runbook: Single Server Failure

**Objective**: Restore service within 5 minutes via automatic failover

**Prerequisites:**
- Hot standby server configured and operational
- Load balancer configured for failover
- Replicated state sync active

**Steps:**

1. **Verify Failure (1 minute)**
   ```bash
   # Check server health
   mahavishnu health check
   curl -f http://primary-server:8678/health || echo "Primary failed"
   ```

2. **Automatic Failover (2 minutes)**
   ```bash
   # Load balancer should automatically detect failure
   # and redirect traffic to standby server

   # Manual verification
   curl -f http://standby-server:8678/health
   ```

3. **Verify Service (1 minute)**
   ```bash
   # Test critical functionality
   mahavishnu list-repos
   mahavishnu pool health
   ```

4. **Investigate Primary (Ongoing)**
   ```bash
   # Check logs
   journalctl -u mahavishnu -n 100

   # System diagnostics
   top, df -h, netstat -tulpn
   ```

5. **Restore Primary (When ready)**
   ```bash
   # Sync from standby
   mahavishnu sync --from standby-server

   # Switch traffic back
   # (via load balancer UI or API)
   ```

**Success Criteria:**
- Service accessible within 5 minutes
- All critical endpoints responding
- Data consistency verified

**Rollback:**
If failover fails:
1. Verify standby server health
2. Check network connectivity
3. Review error logs
4. Escalate to next tier support

---

### Runbook: Region Failure

**Objective**: Restore service in DR region within 15 minutes

**Prerequisites:**
- DR region infrastructure provisioned
- DNS failover configured
- Replicated backups available

**Steps:**

1. **Verify Failure (2 minutes)**
   ```bash
   # Check primary region health
   # Multiple monitoring endpoints
   # Cloud provider status page

   # Confirm region-wide failure
   ```

2. **Activate DR Region (3 minutes)**
   ```bash
   # Start DR region services
   mahavishnu mcp start --region dr-region

   # Verify health
   mahavishnu health check --region dr-region
   ```

3. **Restore from Backup (5 minutes)**
   ```bash
   # Find latest backup
   python scripts/backup_automation.py status

   # Restore backup
   mahavishnu restore --backup-id backup_20250205_030000
   ```

4. **DNS Failover (2 minutes)**
   ```bash
   # Update DNS records
   # Point to DR region load balancer

   # Verify propagation
   dig mahavishnu.example.com
   ```

5. **Validate Service (3 minutes)**
   ```bash
   # End-to-end smoke tests
   mahavishnu list-repos
   mahavishnu pool health
   # Run critical workflows
   ```

**Success Criteria:**
- Service accessible via DNS within 15 minutes
- All data restored from backup
- Critical workflows operational

**Rollback:**
If DR region activation fails:
1. Verify DR region infrastructure
2. Check backup availability
3. Attempt alternative recovery method
4. Escalate to management

---

### Runbook: Database Corruption

**Objective**: Restore database integrity within 30 minutes

**Prerequisites:**
- Valid database backup available
- Transaction logs accessible
- Point-in-time recovery configured

**Steps:**

1. **Detect Corruption (2 minutes)**
   ```bash
   # Run consistency checks
   mahavishnu db check

   # Identify corruption scope
   mahavishnu db validate
   ```

2. **Stop Writes (1 minute)**
   ```bash
   # Stop Mahavishnu service
   mahavishnu mcp stop

   # Prevent new writes
   ```

3. **Restore Backup (10 minutes)**
   ```bash
   # Find latest valid backup
   python scripts/backup_automation.py status

   # Restore database
   mahavishnu db restore --backup-id backup_20250205_030000
   ```

4. **Replay Logs (10 minutes)**
   ```bash
   # Replay transaction logs
   mahavishnu db replay-logs --until "2025-02-05 14:30:00"
   ```

5. **Verify Integrity (5 minutes)**
   ```bash
   # Run consistency checks
   mahavishnu db check

   # Validate data
   mahavishnu db validate
   ```

6. **Resume Service (2 minutes)**
   ```bash
   # Start Mahavishnu
   mahavishnu mcp start

   # Verify functionality
   ```

**Success Criteria:**
- Database consistent after recovery
- No data corruption detected
- Service operational

**Rollback:**
If recovery fails:
1. Try earlier backup
2. Contact database specialists
3. Consider full database rebuild

---

### Runbook: Network Partition

**Objective**: Maintain degraded service during partition

**Prerequisites:**
- Partition detection enabled
- Degraded mode operation configured
- Message queue persistence enabled

**Steps:**

1. **Detect Partition (1 minute)**
   ```bash
   # Check network connectivity
   ping -c 3 other-components

   # Check quorum
   mahavishnu cluster status
   ```

2. **Activate Degraded Mode (2 minutes)**
   ```bash
   # Enable degraded operation
   mahavishnu cluster degraded-mode enable

   # Monitor queue depth
   mahavishnu queue status
   ```

3. **Monitor System (Ongoing)**
   ```bash
   # Watch for queue overflow
   watch mahavishnu queue status

   # Monitor degraded metrics
   mahavishnu metrics --degraded
   ```

4. **Resolution - Resync (Variable)**
   ```bash
   # When partition resolves
   mahavishnu cluster resync

   # Verify consistency
   mahavishnu cluster verify
   ```

5. **Exit Degraded Mode (2 minutes)**
   ```bash
   # Exit degraded mode
   mahavishnu cluster degraded-mode disable

   # Verify normal operation
   ```

**Success Criteria:**
- No message loss during partition
- System remains partially available
- Successful resync after resolution

**Rollback:**
If degraded mode fails:
1. Stop all writes
2. Wait for partition resolution
3. Manual reconciliation required

---

### Runbook: Data Deletion

**Objective**: Restore deleted data within 30 minutes

**Prerequisites:**
- Pre-incident backup available
- Audit logs enabled
- Backup testing current

**Steps:**

1. **Stop Deletion (1 minute)**
   ```bash
   # Revoke access if malicious
   mahavishnu auth revoke --user <username>

   # Stop service if needed
   mahavishnu mcp stop
   ```

2. **Assess Damage (5 minutes)**
   ```bash
   # Check audit logs
   mahavishnu audit logs --since "1 hour ago"

   # Identify deleted items
   mahavishnu list --deleted
   ```

3. **Select Backup (2 minutes)**
   ```bash
   # Find pre-incident backup
   python scripts/backup_automation.py status

   # Verify backup integrity
   python scripts/backup_automation.py validate-backups --backup-id backup_20250205_020000
   ```

4. **Restore Backup (10 minutes)**
   ```bash
   # Restore to staging environment
   mahavishnu restore --backup-id backup_20250205_020000 --environment staging

   # Verify restored data
   mahavishnu verify --environment staging
   ```

5. **Production Restore (5 minutes)**
   ```bash
   # Stop production
   mahavishnu mcp stop

   # Swap with staging
   mahavishnu promote --from staging

   # Start production
   mahavishnu mcp start
   ```

6. **Investigate (Ongoing)**
   ```bash
   # Analyze root cause
   mahavishnu audit investigate

   # Implement safeguards
   # (e.g., additional confirmation prompts)
   ```

**Success Criteria:**
- Deleted data restored
- Root cause identified
- Safeguards implemented

**Rollback:**
If restore fails:
1. Try earlier backup
2. Escalate to security team
3. Consider forensic investigation

---

## Testing and Validation

### Automated Restore Testing

**Schedule**: Weekly (Saturday 5:00 AM UTC)

**Execution:**
```bash
# Run automated restore test
python scripts/restore_test.py run-test

# Test specific backup
python scripts/restore_test.py run-test --backup-id backup_20250205_020000
```

**Test Coverage:**
- Backup integrity validation
- Restore to staging environment
- Data verification
- RTO/RPO measurement
- Test result reporting

**Success Criteria:**
- 100% test execution rate
- 100% test success rate
- RTO < 15 minutes
- RPO < 5 minutes

### Disaster Recovery Drills

**Schedule**: Monthly

**Scenarios:**
- Single server failure
- Region failure
- Database corruption
- Network partition
- Data deletion

**Execution:**
```bash
# Run specific drill
python scripts/disaster_recovery_drill.py run-drill --scenario single_server_failure

# List available scenarios
python scripts/disaster_recovery_drill.py list-scenarios

# Generate drill report
python scripts/disaster_recovery_drill.py report
```

**Drill Report Contents:**
- Scenario executed
- Steps completed
- RTO/RPO achieved
- Issues encountered
- Lessons learned
- Improvement recommendations

### Backup Validation

**Daily:**
- Checksum verification
- File integrity checks
- Backup completion monitoring

**Weekly:**
- Random sample restore tests
- Archive format validation
- Metadata verification

**Monthly:**
- Full restore drill
- RTO/RPO measurement
- Documentation review

---

## Communication Plan

### Alert Levels

**Level 1 - Informational:**
- Scheduled maintenance
- Routine backup completions
- DR drill notifications
- Audience: Internal team

**Level 2 - Warning:**
- Backup failures
- Degraded performance
- Minor service issues
- Audience: Internal team + stakeholders

**Level 3 - Critical:**
- Service outages
- Data loss incidents
- Security breaches
- Audience: All stakeholders + users

### Communication Channels

**Internal:**
- Slack: #mahavishnu-incidents
- Email: devops@example.com
- PagerDuty: On-call rotations

**External:**
- Status page: status.example.com
- Email: users@example.com
- Twitter: @mahavishnu_status

### Incident Communication Timeline

**T+0 (Incident Detection):**
- Alert on-call engineer
- Post to #incidents channel
- Start incident log

**T+15 minutes:**
- Initial assessment
- Determine severity level
- Notify stakeholders (if Level 2+)

**T+30 minutes:**
- Update status page (if user-facing)
- Provide recovery ETA
- Establish communication cadence

**T+Recovery:**
- Confirm service restoration
- Post-incident review scheduled
- Close incident

**T+24 hours:**
- Post-incident report published
- Improvement actions identified
- Stakeholders updated

---

## Roles and Responsibilities

### Disaster Recovery Team

**Incident Commander:**
- Declares disasters
- Coordinates recovery efforts
- Makes critical decisions
- Communicates with stakeholders

**Backup Administrator:**
- Manages backup schedules
- Monitors backup health
- Executes restore procedures
- Validates backup integrity

**System Administrator:**
- Manages infrastructure
- Executes failover procedures
- Restores services
- Monitors system health

**Database Administrator:**
- Manages database backups
- Executes database recovery
- Validates data integrity
- Optimizes recovery procedures

**Security Officer:**
- Investigates security incidents
- Validates access controls
- Implements safeguards
- Conducts post-incident analysis

**Communications Lead:**
- Manages internal communications
- Updates status pages
- Notifies external stakeholders
- Handles press inquiries (if needed)

### On-Call Rotations

**Primary On-Call:**
- 24/7 availability
- First responder to alerts
- Incident commander initiation
- Technical execution

**Secondary On-Call:**
- Backup for primary
- Supports complex incidents
- Knowledge transfer

**Escalation Path:**
1. Primary On-Call
2. Secondary On-Call
3. Engineering Manager
4. CTO
5. CEO (critical incidents only)

---

## Appendices

### Appendix A: Backup Configuration

**Example Configuration:**
```yaml
# settings/mahavishnu.yaml
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

  monitoring:
    enabled: true
    alert_on_failure: true
    alert_channels: ["email", "slack"]

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
      - network_partition
      - data_deletion
```

### Appendix B: Contact Information

**Internal Contacts:**
- DevOps Team: devops@example.com
- Engineering Manager: eng-manager@example.com
- CTO: cto@example.com
- Security Team: security@example.com

**External Contacts:**
- Cloud Provider Support: (varies by provider)
- Data Center: (varies by facility)
- Backup Vendor: (if applicable)

### Appendix C: System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Mahavishnu DR Architecture                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │   Primary Site   │         │    DR Site       │          │
│  │                  │         │                  │          │
│  │ ┌──────────────┐ │         │ ┌──────────────┐ │          │
│  │ │ Mahavishnu   │ │         │ │ Mahavishnu   │ │          │
│  │ │   Primary    │ │         │ │   Standby    │ │          │
│  │ └──────┬───────┘ │         │ └──────┬───────┘ │          │
│  │        │         │         │        │         │          │
│  │        │ Backup  │         │        │ Restore  │          │
│  │        ▼         │         │        ▼         │          │
│  │ ┌──────────────┐ │    ┌─────────────────┐    │          │
│  │ │   Local      │ │    │   Replicated   │    │          │
│  │ │  Storage     │ │────│    Backups     │    │          │
│  │ └──────────────┘ │    │  (S3/Azure/GCS)│    │          │
│  └──────────────────┘    └─────────────────┘    └──────────────────┘
│         │                              │
│         │     Async Replication        │
│         └──────────────────────────────┘
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │             Monitoring & Alerting                       │ │
│  │  - Health Checks  - Metrics  - Logging  - Alerts      │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Appendix D: Monitoring Metrics

**Backup Metrics:**
- Backup success rate (target: 99.9%)
- Backup creation time
- Backup size
- Backup age (latest backup)

**Restore Metrics:**
- Restore test success rate (target: 100%)
- RTO achieved (target: < 15 minutes)
- RPO achieved (target: < 5 minutes)
- Restore time by backup size

**System Metrics:**
- Service availability
- Response time
- Error rate
- Queue depth (if applicable)

### Appendix E: Change Log

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2025-02-05 | Initial DR plan creation | DevOps Team |

### Appendix F: Related Documents

- [Disaster Recovery Implementation Guide](DISASTER_RECOVERY_IMPLEMENTATION.md)
- [Backup Automation Script](../scripts/backup_automation.py)
- [Restore Test Script](../scripts/restore_test.py)
- [DR Drill Script](../scripts/disaster_recovery_drill.py)
- [Production Deployment Guide](PRODUCTION_DEPLOYMENT_GUIDE.md)

---

**Document Control:**

- **Next Review Date**: 2025-05-05
- **Approved By**: DevOps Lead
- **Distribution**: DevOps Team, Engineering Management, Security Team

---

*This document is a living document and should be updated as the system evolves. Ensure all contact information and procedures are kept current.*
