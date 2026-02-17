# Disaster Recovery Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Target RTO**: 4 hours (Recovery Time Objective)
**Target RPO**: 24 hours (Recovery Point Objective)

______________________________________________________________________

## Table of Contents

1. [Overview](#overview)
1. [Roles and Responsibilities](#roles-and-responsibilities)
1. [Backup Strategy](#backup-strategy)
1. [Disaster Scenarios](#disaster-scenarios)
1. [Recovery Procedures](#recovery-procedures)
1. [Verification Steps](#verification-steps)
1. [Communication Plan](#communication-plan)
1. [Post-Incident Review](#post-incident-review)

______________________________________________________________________

## Overview

This runbook provides step-by-step procedures for recovering the MCP ecosystem from various disaster scenarios. It covers:

- **Recovery Time Objective (RTO)**: 4 hours - Maximum acceptable downtime
- **Recovery Point Objective (RPO)**: 24 hours - Maximum acceptable data loss

### Scope

This runbook covers recovery for:

- **Mahavishnu**: Orchestration server
- **Session-Buddy**: Session management
- **Akosha**: Memory aggregation
- **Crackerjack**: Quality control
- **All MCP tool servers**: Excalidraw, Mermaid, Mailgun, UniFi, RaindropIO

### Out of Scope

- Hardware failures (handled by cloud provider/IT)
- Network infrastructure (handled by network team)
- Security incidents (handled by security team)
- Application-level bugs (handled by development team)

______________________________________________________________________

## Roles and Responsibilities

### Primary On-Call Engineer

**Responsibilities**:

- Initial incident assessment
- Executing recovery procedures
- Coordinating with stakeholders
- Documenting recovery progress

**Contact**: `oncall@example.com`
**Pager**: +1-555-0123

### Secondary On-Call Engineer

**Responsibilities**:

- Support primary engineer
- Handle escalation if primary unavailable
- Review recovery procedures

**Contact**: `oncall-secondary@example.com`

### Engineering Manager

**Responsibilities**:

- Major incident decisions
- Stakeholder communication
- Resource allocation
- Post-incident review

**Contact**: `eng-manager@example.com`

### Database Administrator (if available)

**Responsibilities**:

- Database-specific recovery
- Data integrity verification
- Performance tuning after recovery

**Contact**: `dba@example.com`

______________________________________________________________________

## Backup Strategy

### Backup Retention Policy

| Tier | Retention | Purpose |
|------|-----------|---------|
| **Daily** | 30 days | Point-in-time recovery |
| **Weekly** | 12 weeks | Long-term recovery |
| **Monthly** | 6 months | Archive/compliance |

### Backup Schedule

- **Daily Full Backups**: 2:00 AM UTC
- **Weekly Full Backups**: Sunday 3:00 AM UTC
- **Automatic Cleanup**: After each backup

### Backup Locations

- **Primary**: `/Users/les/Projects/mahavishnu/backups/`
- **Offsite**: [To be configured - S3/GCS/Azure Blob]
- **Encryption**: AES-256 at rest

### Backup Components

Each backup includes:

1. **Database dumps** (Session-Buddy, Akosha)
1. **Configuration files** (YAML, environment, .mcp.json)
1. **Workflow states** (Mahavishnu)
1. **Metadata** (checksums, timestamps, file manifests)

______________________________________________________________________

## Disaster Scenarios

### Scenario 1: Single Server Failure

**Severity**: Medium
**Impact**: One MCP server unavailable
**Estimated Recovery Time**: 30-60 minutes

**Symptoms**:

- One MCP server unreachable
- Health checks failing for specific service
- API calls to one service timing out

**Recovery Procedure**:

1. [Verify failure](#step-1-verify-failure)
1. [Check server status](#step-2-check-server-status)
1. [Restart affected service](#step-3-restart-affected-service)
1. [Verify recovery](#step-4-verify-recovery)

### Scenario 2: Database Corruption

**Severity**: High
**Impact**: Data integrity compromised
**Estimated Recovery Time**: 1-2 hours

**Symptoms**:

- Database query errors
- "Database disk image is malformed"
- Application crashes on database access

**Recovery Procedure**:

1. [Stop all affected services](#step-1-stop-all-affected-services)
1. [Identify corruption scope](#step-2-identify-corruption-scope)
1. [Restore from last good backup](#step-3-restore-from-last-good-backup)
1. [Verify data integrity](#step-4-verify-data-integrity)
1. [Restart services](#step-5-restart-services)

### Scenario 3: Complete System Failure

**Severity**: Critical
**Impact**: All services unavailable
**Estimated Recovery Time**: 2-4 hours

**Symptoms**:

- All MCP servers down
- No services responding
- Infrastructure failure

**Recovery Procedure**:

1. [Assess infrastructure](#step-1-assess-infrastructure)
1. [Restore infrastructure](#step-2-restore-infrastructure)
1. [Restore databases](#step-3-restore-databases)
1. [Restore configurations](#step-4-restore-configurations)
1. [Restart all services](#step-5-restart-all-services)
1. [Verify system health](#step-6-verify-system-health)

### Scenario 4: Data Loss Event

**Severity**: Critical
**Impact**: Accidental deletion or data corruption
**Estimated Recovery Time**: 1-3 hours

**Symptoms**:

- Critical data missing
- User reports of lost data
- Database integrity errors

**Recovery Procedure**:

1. [Identify lost data scope](#step-1-identify-lost-data-scope)
1. [Stop all writes](#step-2-stop-all-writes)
1. [Select appropriate backup](#step-3-select-appropriate-backup)
1. [Restore lost data](#step-4-restore-lost-data)
1. [Verify restored data](#step-5-verify-restored-data)
1. [Resume normal operations](#step-6-resume-normal-operations)

______________________________________________________________________

## Recovery Procedures

### General Pre-Recovery Checklist

Before starting any recovery:

- [ ] Notify stakeholders of incident
- [ ] Create incident ticket (Linear/Jira)
- [ ] Assign incident severity
- [ ] Start incident timer
- [ ] Join incident bridge line (if applicable)
- [ ] Document all actions in runbook

### Scenario 1: Single Server Failure

#### Step 1: Verify Failure

**Objective**: Confirm which service is actually failing

```bash
# Check service health
curl http://localhost:8680/health  # Mahavishnu
curl http://localhost:8678/health  # Session-Buddy
curl http://localhost:8682/health  # Akosha
curl http://localhost:8676/health  # Crackerjack

# Check process status
ps aux | grep -E "mahavishnu|session-buddy|akosha|crackerjack"

# Check logs
tail -100 /var/log/mcp/*.log
```

**Expected Results**:

- Identify which service(s) are failing
- Confirm symptoms match scenario

**If verification fails**: Escalate to engineering manager

#### Step 2: Check Server Status

**Objective**: Determine root cause of failure

```bash
# Check resource usage
top -p $(pgrep -f mahavishnu)
df -h
free -m

# Check for port conflicts
lsof -i :8680

# Check error logs
journalctl -u mahavishnu -n 100 --no-pager
```

**Common Causes**:

- Out of memory
- Disk full
- Port already in use
- Configuration error
- Dependency failure

**Resolution**: Fix root cause before restarting

#### Step 3: Restart Affected Service

**Objective**: Restart the failed service

```bash
# Graceful shutdown
pkill -TERM -f "mahavishnu mcp"

# Wait for shutdown (10 seconds)
sleep 10

# Force kill if still running
pkill -KILL -f "mahavishnu mcp"

# Start service
cd /Users/les/Projects/mahavishnu
mahavishnu mcp start

# Verify startup
tail -f /var/log/mahavishnu/mcp.log
```

**Alternative: Using MCP tools**

```bash
# If Mahavishnu CLI is available
mahavishnu mcp restart
```

#### Step 4: Verify Recovery

**Objective**: Confirm service is healthy

```bash
# Health check
curl http://localhost:8680/health

# Test MCP tools
mahavishnu list-repos

# Check metrics
curl http://localhost:8680/metrics
```

**Success Criteria**:

- Health endpoint returns 200
- MCP tools respond correctly
- No errors in logs
- Metrics being collected

**If verification fails**: Return to Step 2 or escalate

______________________________________________________________________

### Scenario 2: Database Corruption

#### Step 1: Stop All Affected Services

**Objective**: Prevent further corruption

```bash
# Stop all services using the database
pkill -TERM -f "session-buddy"
pkill -TERM -f "akosha"
pkill -TERM -f "mahavishnu"

# Verify processes stopped
ps aux | grep -E "session-buddy|akosha"
```

**Critical**: Do NOT skip this step!

#### Step 2: Identify Corruption Scope

**Objective**: Determine which databases are affected

```bash
# Check database integrity
sqlite3 /path/to/session_buddy.db "PRAGMA integrity_check"
sqlite3 /path/to/akosha.db "PRAGMA integrity_check"

# Look for specific errors
sqlite3 /path/to/session_buddy.db ".schema"
```

**Expected Errors**:

- "database disk image is malformed"
- "missing indexes"
- "rowid missing"

**Document findings**: Take screenshots of errors

#### Step 3: Restore from Last Good Backup

**Objective**: Restore databases from backup

```bash
# List available backups
ls -lth /Users/les/Projects/mahavishnu/backups/

# Select most recent good backup
# (Check timestamps and verify before this incident)

# Extract backup
cd /tmp
tar -xzf /Users/les/Projects/mahavishnu/backups/backup_YYYYMMDD_HHMMSS.tar.gz

# Verify SQL dump files
ls -lh backup_*/session_buddy.sql
ls -lh backup_*/akosha.sql

# Stop services (if not already stopped)
# ... (see Step 1)

# Backup corrupted databases (just in case)
cp /path/to/session_buddy.db /path/to/session_buddy.db.corrupted
cp /path/to/akosha.db /path/to/akosha.db.corrupted

# Restore databases
sqlite3 /path/to/session_buddy.db < backup_*/session_buddy.sql
sqlite3 /path/to/akosha.db < backup_*/akosha.sql

# Verify restored databases
sqlite3 /path/to/session_buddy.db "PRAGMA integrity_check"
sqlite3 /path/to/akosha.db "PRAGMA integrity_check"
```

**If restore fails**: Try next older backup

#### Step 4: Verify Data Integrity

**Objective**: Confirm restored data is valid

```bash
# Check record counts
sqlite3 /path/to/session_buddy.db "SELECT COUNT(*) FROM sessions"
sqlite3 /path/to/akosha.db "SELECT COUNT(*) FROM memories"

# Sample data
sqlite3 /path/to/session_buddy.db "SELECT * FROM sessions LIMIT 5"

# Compare with expected counts
# (Document expected counts in runbook update)
```

**Success Criteria**:

- PRAGMA integrity_check returns "ok"
- Record counts are reasonable
- Sample data looks correct
- No application errors on read

#### Step 5: Restart Services

**Objective**: Start services with restored databases

```bash
# Start Session-Buddy
cd /Users/les/Projects/session-buddy
session-buddy mcp start

# Start Akosha
cd /Users/les/Projects/akosha
akosha mcp start

# Start Mahavishnu
cd /Users/les/Projects/mahavishnu
mahavishnu mcp start

# Verify all services
curl http://localhost:8678/health
curl http://localhost:8682/health
curl http://localhost:8680/health
```

**Monitor**: Watch logs for 5 minutes for any errors

______________________________________________________________________

### Scenario 3: Complete System Failure

#### Step 1: Assess Infrastructure

**Objective**: Determine if infrastructure is available

```bash
# Check system resources
df -h
free -h
uptime

# Check network
ping -c 3 google.com
netstat -tuln | grep LISTEN

# Check Docker (if using)
docker ps -a
docker stats

# Check processes
ps aux | grep -E "mahavishnu|session|akosha" | grep -v grep
```

**Document**: Take screenshots of system state

#### Step 2: Restore Infrastructure

**Objective**: Get basic infrastructure running

**If using Docker**:

```bash
# Check Docker daemon
sudo systemctl status docker

# Restart if needed
sudo systemctl restart docker

# Check required networks
docker network ls
docker network inspect mcp-network

# Create if missing
docker network create mcp-network
```

**If using systemd services**:

```bash
# Check service status
systemctl status mahavishnu.service
systemctl status session-buddy.service

# Restart services
sudo systemctl restart mahavishnu.service
sudo systemctl restart session-buddy.service
```

**If using manual processes**:

```bash
# Kill any orphaned processes
pkill -KILL -f "mcp|mahavishnu|session-buddy"
```

#### Step 3: Restore Databases

**Objective**: Restore all databases

[Follow Scenario 2, Steps 3-5 for each database]

**Priority Order**:

1. Session-Buddy (most critical)
1. Akosha (memory aggregation)
1. Other databases

#### Step 4: Restore Configurations

**Objective**: Restore configuration files

```bash
# Extract backup
cd /tmp
tar -xzf /Users/les/Projects/mahavishnu/backups/backup_YYYYMMDD_HHMMSS.tar.gz

# Verify backup contents
ls -lh backup_*/config/

# Restore configurations
cp -r backup_*/config/* /Users/les/Projects/mahavishnu/
cp -r backup_*/config/session-buddy/* /Users/les/Projects/session-buddy/
cp -r backup_*/config/akosha/* /Users/les/Projects/akosha/

# Verify configurations
cd /Users/les/Projects/mahavishnu
cat settings/mahavishnu.yaml
cat repos.yaml
```

**Critical**: Check for any environment-specific changes needed

#### Step 5: Restart All Services

**Objective**: Start all MCP servers in correct order

**Startup Order**:

1. **Session-Buddy** (foundational service)

   ```bash
   cd /Users/les/Projects/session-buddy
   session-buddy mcp start
   ```

1. **Akosha** (depends on Session-Buddy)

   ```bash
   cd /Users/les/Projects/akosha
   akosha mcp start
   ```

1. **Crackerjack** (quality control)

   ```bash
   cd /Users/les/Projects/crackerjack
   crackerjack mcp start
   ```

1. **Mahavishnu** (orchestration)

   ```bash
   cd /Users/les/Projects/mahavishnu
   mahavishnu mcp start
   ```

1. **Tool Servers** (can start in parallel)

   ```bash
   cd /Users/les/Projects/excalidraw-mcp
   excalidraw mcp start

   cd /Users/les/Projects/mermaid-mcp
   mermaid mcp start

   # ... etc
   ```

**Wait between each**: 10 seconds to ensure startup

#### Step 6: Verify System Health

**Objective**: Confirm full system recovery

```bash
# Health checks
for port in 8680 8678 8682 8676 3032 3033 3034 3038 3039; do
    echo "Checking port $port..."
    curl -s http://localhost:$port/health && echo "✓ OK" || echo "✗ FAIL"
done

# Test cross-service communication
mahavishnu list-repos

# Check logs
tail -100 /var/log/mahavishnu/*.log
tail -100 /var/log/session-buddy/*.log
```

**Success Criteria**:

- All health endpoints return 200
- Mahavishnu can list repositories
- No critical errors in logs
- Metrics being collected

______________________________________________________________________

### Scenario 4: Data Loss Event

#### Step 1: Identify Lost Data Scope

**Objective**: Understand what data was lost

**Questions to Answer**:

- When did the loss occur?
- What data was affected?
- Who reported the loss?
- What was the user doing when it happened?

**Actions**:

- Interview affected users
- Check application logs
- Check database logs
- Document timeline

#### Step 2: Stop All Writes

**Objective**: Prevent further data loss

```bash
# Stop all MCP servers
pkill -TERM -f "mahavishnu|session-buddy|akosha"

# Verify stopped
ps aux | grep -E "mahavishnu|session-buddy|akosha" | grep -v grep
```

**Critical**: Do NOT allow any writes until recovery complete

#### Step 3: Select Appropriate Backup

**Objective**: Find the right backup to restore

**Criteria**:

- Backup must be from **before** the data loss event
- Most recent backup before event preferred
- Verify backup integrity

```bash
# List backups with timestamps
ls -lth /Users/les/Projects/mahavishnu/backups/

# Read backup metadata
tar -xzf /Users/les/Projects/mahavishnu/backups/backup_YYYYMMDD_HHMMSS.tar.gz -O backup_*/metadata.json
cat backup_*/metadata.json | jq '.timestamp, .databases_backed_up'
```

**Document**: Which backup selected and why

#### Step 4: Restore Lost Data

**Objective**: Restore only the lost data

**Options**:

1. **Full restore**: Replace entire database
1. **Partial restore**: Restore specific tables/records
1. **Manual merge**: Combine current and backup data

**Full restore example**:

```bash
# Backup current database (pre-restore)
cp /path/to/database.db /path/to/database.db.pre-restore

# Restore from backup
sqlite3 /path/to/database.db < backup_*/database.sql
```

**Partial restore** (advanced):

```sql
-- Create temporary database
ATTACH '/tmp/backup.db' AS backup_db;

-- Copy specific tables
INSERT INTO main.sessions SELECT * FROM backup_db.sessions WHERE created_at > '2026-01-01';

-- Detach
DETACH backup_db;
```

#### Step 5: Verify Restored Data

**Objective**: Confirm lost data is recovered

**Verification Steps**:

1. Check record counts
1. Sample random records
1. Verify with affected users
1. Run data integrity checks

```bash
# Record counts
sqlite3 /path/to/database.db "SELECT COUNT(*) FROM lost_table"

# Sample records
sqlite3 /path/to/database.db "SELECT * FROM lost_table WHERE id IN (1, 100, 1000)"

# User verification
# (Contact affected users to confirm their data is back)
```

#### Step 6: Resume Normal Operations

**Objective**: Start services with recovered data

```bash
# Start services
cd /Users/les/Projects/session-buddy
session-buddy mcp start

cd /Users/les/Projects/mahavishnu
mahavishnu mcp start

# Monitor for issues
tail -f /var/log/session-buddy/*.log
```

**Extended Monitoring**: Watch logs for 1 hour

______________________________________________________________________

## Verification Steps

### Post-Recovery Checklist

After any recovery, verify:

**Health Checks**:

- [ ] All services running (`ps aux | grep mcp`)
- [ ] All health endpoints returning 200
- [ ] No critical errors in logs
- [ ] Metrics being collected

**Functional Checks**:

- [ ] Mahavishnu can list repositories
- [ ] Session-Buddy can store/retrieve sessions
- [ ] Akosha can search memories
- [ ] MCP tools responding correctly
- [ ] Cross-service communication working

**Data Integrity**:

- [ ] Database `PRAGMA integrity_check` returns "ok"
- [ ] Record counts reasonable
- [ ] Sample data looks correct
- [ ] No duplicate records
- [ ] No missing indexes

**Performance**:

- [ ] Response times acceptable (\<1s p95)
- [ ] No unusual resource consumption
- [ ] No errors in monitoring dashboard

### Rollback Procedure

If recovery fails or causes issues:

```bash
# Stop services
pkill -TERM -f "mahavishnu|session-buddy|akosha"

# Restore pre-recovery state
cp /path/to/database.db.pre-restore /path/to/database.db

# Restart services
# ... (follow startup order)
```

**Critical**: Always have rollback plan!

______________________________________________________________________

## Communication Plan

### Severity Levels

| Severity | Definition | Response Time | Notification |
|----------|------------|----------------|--------------|
| **P1 - Critical** | Complete system failure | 15 minutes | Page all |
| **P2 - High** | Major service degradation | 1 hour | Email + Slack |
| **P3 - Medium** | Single service down | 4 hours | Email |
| **P4 - Low** | Minor issues | Next business day | Ticket |

### Notification Templates

#### Initial Incident Notification

**To**: eng-manager@example.com, oncall@example.com
**Subject**: 🔴 INCIDENT: [Service Name] Down - Severity P1

**Body**:

```
Service: [Service Name]
Severity: P1 - Critical
Impact: [Brief description]
Started: [Timestamp]
Investigator: [Your name]
Next Update: [Time]

Actions taken:
- [x] Verified failure
- [ ] Investigating root cause
- [ ] Estimated recovery time

Bridge line: [If applicable]
Incident ticket: [Link]
```

#### Recovery Update

**To**: [Same as initial]
**Subject**: ✅ UPDATE: [Service Name] Recovery in Progress

**Body**:

```
Service: [Service Name]
Status: Recovery in progress
Started: [Timestamp]
Current Time: [Timestamp]
Duration: [Hours/minutes]

Recovery steps completed:
- [x] Restored databases
- [x] Restarted services
- [ ] Verifying health

Estimated time to full recovery: [Time]
```

#### Recovery Complete

**To**: [Same as initial]
**Subject**: ✅ RESOLVED: [Service Name] Recovered

**Body**:

```
Service: [Service Name]
Status: Fully recovered
Incident duration: [Time]
Data loss: [Yes/No - if yes, extent]

Root cause: [Summary]
Resolution: [Summary]

Post-incident review scheduled: [Date/Time]
Incident ticket: [Link]
```

### Stakeholder Communication

**Who to Notify**:

- **End users**: If user-facing service affected
- **Management**: If P1 or P2 severity
- **Dependent teams**: If your service is their dependency
- **Customers**: If production customer-facing system

**Channels**:

- Email (for formal notifications)
- Slack (for status updates)
- Status page (if available)
- SMS/Pager (for critical incidents)

______________________________________________________________________

## Post-Incident Review

### Review Timeline

**When**: Within 1 week of incident resolution
**Attendees**: On-call engineer, engineering manager, relevant team leads
**Duration**: 60 minutes

### Review Agenda

1. **Incident Timeline** (10 minutes)

   - What happened?
   - When did it happen?
   - How long did it last?

1. **Root Cause Analysis** (15 minutes)

   - Why did it happen?
   - Contributing factors
   - Could it have been prevented?

1. **Response Evaluation** (15 minutes)

   - What went well in the response?
   - What could have been better?
   - Were runbooks followed?

1. **Action Items** (20 minutes)

   - Preventive measures
   - Runbook improvements
   - Process changes
   - Follow-up tasks

### Review Output

**Document**:

- Incident timeline
- Root cause
- Impact assessment
- Lessons learned
- Action items with owners and due dates

**Share**:

- Postmortem document with engineering team
- Summary with management (if high severity)
- Runbook updates (if needed)

______________________________________________________________________

## Appendix

### Useful Commands

```bash
# System health
df -h                    # Disk space
free -h                  # Memory
uptime                   # Uptime
top                      # Processes

# Service status
ps aux | grep mcp       # Running services
systemctl status *      # Service status
journalctl -u * -n 100   # Service logs

# Database
sqlite3 db.db "PRAGMA integrity_check"
sqlite3 db.db ".schema"
sqlite3 db.db ".tables"
sqlite3 db.db "SELECT COUNT(*) FROM table"

# Network
curl http://localhost:8680/health
netstat -tuln | grep LISTEN
lsof -i :8680

# Backup operations
ls -lth /path/to/backups/
tar -tzf backup.tar.gz      # List contents
tar -xzf backup.tar.gz      # Extract
sha256sum file.tar.gz       # Checksum

# Logs
tail -f /var/log/service.log
grep ERROR /var/log/*.log
journalctl -u service -f
```

### Emergency Contacts

| Role | Name | Contact |
|------|------|---------|
| Primary On-Call | [Name] | +1-555-0123 |
| Secondary On-Call | [Name] | +1-555-0124 |
| Engineering Manager | [Name] | +1-555-0125 |
| Database Administrator | [Name] | +1-555-0126 |
| Security Team | [Name] | security@example.com |

### Backup Locations

| Environment | Path |
|------------|------|
| Production | `/Users/les/Projects/mahavishnu/backups/` |
| Offsite | [To be configured] |
| Archive | [To be configured] |

### Related Documentation

- [Backup System Implementation](monitoring/backup_system.py)
- [Monitoring Guide](monitoring/MONITORING_GUIDE.md)
- [Alerting Rules](monitoring/alerts.py)
- [Resilience Patterns](monitoring/resilience.py)

______________________________________________________________________

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-02 | 1.0 | Initial runbook creation | Claude Code |

______________________________________________________________________

**Next Review Date**: 2026-03-02
**Runbook Owner**: Engineering Team
**Approval**: Engineering Manager

______________________________________________________________________

**IMPORTANT**: This runbook must be kept up-to-date. Any changes to backup procedures, service architecture, or contact information must be reflected in this document within 1 week of the change.
