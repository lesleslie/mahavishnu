# Disaster Recovery Runbook

This runbook provides procedures for recovering from major incidents and disasters in the Mahavishnu Task Orchestration System.

## Table of Contents

1. [Disaster Severity Levels](#disaster-severity-levels)
2. [Immediate Response](#immediate-response)
3. [Database Recovery](#database-recovery)
4. [Service Recovery](#service-recovery)
5. [Data Validation](#data-validation)
6. [Post-Recovery Actions](#post-recovery-actions)

---

## Disaster Severity Levels

| Level | Description | Examples | RTO | RPO |
|-------|-------------|----------|-----|-----|
| **SEV1** | Complete service outage | Database loss, region failure | 1 hour | 1 hour |
| **SEV2** | Partial outage | Single AZ failure, degraded performance | 4 hours | 4 hours |
| **SEV3** | Minor impact | Single component failure | 24 hours | 24 hours |

**RTO**: Recovery Time Objective (how fast we must recover)
**RPO**: Recovery Point Objective (maximum data loss acceptable)

---

## Immediate Response

### Step 1: Assess the Situation (0-5 minutes)

```bash
# Check service health
curl -s https://mahavishnu.example.com/health/all | jq

# Check database connectivity
curl -s https://mahavishnu.example.com/health/db | jq

# Check recent alerts
curl -s "http://prometheus.example.com/api/v1/alerts" | jq '.data.alerts[] | select(.state=="firing")'

# Check error rates
curl -s "http://prometheus.example.com/api/v1/query?query=rate(mahavishnu_task_errors_total[5m])" | jq
```

### Step 2: Notify Stakeholders (5-10 minutes)

1. Page on-call engineer if not already alerted
2. Create incident channel: `#incident-YYYY-MM-DD`
3. Notify stakeholders based on severity:
   - **SEV1**: Exec team, all engineers
   - **SEV2**: Engineering manager, relevant team
   - **SEV3**: Relevant team only

### Step 3: Stop the Bleeding (10-30 minutes)

```bash
# If database is corrupt, stop writes
kubectl scale deployment mahavishnu --replicas=0 -n mahavishnu

# If specific endpoint is causing issues, block it
# (Implementation depends on load balancer/ingress)

# Enable maintenance mode
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: mahavishnu-maintenance
  namespace: mahavishnu
data:
  enabled: "true"
  message: "System under maintenance - please try again later"
EOF
```

---

## Database Recovery

### Scenario: Database Corruption

```bash
# 1. Stop application to prevent further corruption
kubectl scale deployment mahavishnu --replicas=0 -n mahavishnu

# 2. Assess corruption extent
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "SELECT COUNT(*) FROM tasks;"

# 3. If partial corruption, attempt repair
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "REINDEX DATABASE mahavishnu;"
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "VACUUM FULL ANALYZE;"

# 4. If complete corruption, restore from backup
# (See Backup Restoration below)
```

### Scenario: Database Server Failure

```bash
# 1. Verify backup exists
aws s3 ls s3://mahavishnu-backups/database/ | tail -5

# 2. Provision new database instance
# (Using Terraform or cloud console)

# 3. Restore from most recent backup
pg_restore -h $NEW_DB_HOST -U $DB_USER -d mahavishnu /backup/latest.dump

# 4. Update application configuration
kubectl set env deployment/mahavishnu \
  MAHAVISHNU_DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$NEW_DB_HOST/mahavishnu" \
  -n mahavishnu

# 5. Restart application
kubectl scale deployment mahavishnu --replicas=3 -n mahavishnu
```

### Backup Restoration Procedure

```bash
# List available backups
./scripts/list_backups.sh

# Restore from specific backup
./scripts/restore_backup.sh --backup-id backup-2026-02-18-0400

# Or manually:
aws s3 cp s3://mahavishnu-backups/database/backup-2026-02-18-0400.dump /tmp/
pg_restore -h $DB_HOST -U $DB_USER -d mahavishnu --clean /tmp/backup-2026-02-18-0400.dump
```

---

## Service Recovery

### Scenario: Complete Service Outage

```bash
# 1. Check pod status
kubectl get pods -n mahavishnu

# 2. Check pod logs for errors
kubectl logs -n mahavishnu -l app=mahavishnu --tail=100

# 3. Check events
kubectl get events -n mahavishnu --sort-by='.lastTimestamp'

# 4. If pods are crashlooping, check configuration
kubectl describe pod -n mahavishnu -l app=mahavishnu

# 5. Restart services
kubectl rollout restart deployment/mahavishnu -n mahavishnu

# 6. Monitor recovery
kubectl rollout status deployment/mahavishnu -n mahavishnu --timeout=300s
```

### Scenario: Configuration Error

```bash
# 1. Identify bad configuration
kubectl get configmap mahavishnu-config -n mahavishnu -o yaml

# 2. Rollback to previous ConfigMap version
kubectl rollout undo deployment/mahavishnu -n mahavishnu

# 3. Or manually fix configuration
kubectl edit configmap mahavishnu-config -n mahavishnu

# 4. Restart to pick up new config
kubectl rollout restart deployment/mahavishnu -n mahavishnu
```

### Scenario: Dependency Failure (Redis, External APIs)

```bash
# 1. Check dependency health
redis-cli -h $REDIS_HOST ping

# 2. If Redis is down, check if we can operate in degraded mode
kubectl set env deployment/mahavishnu \
  MAHAVISHNU_CACHE_ENABLED=false \
  -n mahavishnu

# 3. Restart to apply
kubectl rollout restart deployment/mahavishnu -n mahavishnu

# 4. When dependency is restored, re-enable
kubectl set env deployment/mahavishnu \
  MAHAVISHNU_CACHE_ENABLED=true \
  -n mahavishnu
kubectl rollout restart deployment/mahavishnu -n mahavishnu
```

---

## Data Validation

After recovery, validate data integrity:

### Database Integrity Checks

```bash
# Check row counts
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "
SELECT 
  'tasks' as table_name, COUNT(*) as count FROM tasks
UNION ALL
SELECT 'webhook_events', COUNT(*) FROM webhook_events
UNION ALL
SELECT 'audit_logs', COUNT(*) FROM audit_logs;
"

# Check for orphaned records
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "
SELECT COUNT(*) as orphaned_tasks FROM tasks t
WHERE t.repository_id NOT IN (SELECT id FROM repositories);
"

# Verify foreign key constraints
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "
SET CONSTRAINTS ALL IMMEDIATE;
"
```

### Data Hash Verification

```bash
# Generate data hash
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "
SELECT md5(string_agg(id::text || title || status, '' ORDER BY id)) as data_hash
FROM tasks;
"

# Compare with pre-incident hash (if available)
```

### Functional Validation

```bash
# Create test task
TEST_TASK=$(curl -s -X POST https://mahavishnu.example.com/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "DR Test", "repository": "test-repo"}')

# Verify task lifecycle
TASK_ID=$(echo $TEST_TASK | jq -r '.id')

curl -s -X PATCH "https://mahavishnu.example.com/api/tasks/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}'

curl -s "https://mahavishnu.example.com/api/tasks/$TASK_ID" | jq '.status'

# Cleanup
curl -s -X DELETE "https://mahavishnu.example.com/api/tasks/$TASK_ID"
```

---

## Post-Recovery Actions

### Step 1: Verify Full Service Restoration (0-30 minutes)

```bash
# Run full health check
curl -s https://mahavishnu.example.com/health/all | jq

# Check error rates return to normal
curl -s "http://prometheus.example.com/api/v1/query?query=rate(mahavishnu_task_errors_total[5m])" | jq

# Verify all endpoints
./scripts/smoke_test.sh production
```

### Step 2: Update Stakeholders (30-60 minutes)

1. Post recovery update in incident channel
2. Email stakeholders with recovery summary
3. Update status page

### Step 3: Document Incident (1-24 hours)

1. Create post-incident report
2. Document root cause
3. List remediation steps taken
4. Schedule post-mortem meeting

### Step 4: Post-Mortem (24-72 hours)

1. Conduct blameless post-mortem
2. Identify action items
3. Create tickets for improvements
4. Update runbooks based on learnings

---

## Monthly DR Test Schedule

### Testing Cadence

| Test Type | Frequency | Owner | Duration | Success Criteria |
|-----------|-----------|-------|----------|------------------|
| **Backup restoration** | Monthly (1st Tuesday) | SRE Team | 1 hour | Backup restores successfully, data intact |
| **Database failover** | Monthly (3rd Wednesday) | DBA/SRE | 30 min | Failover completes < 5 min, no data loss |
| **Service failover** | Quarterly | Platform Team | 2 hours | Traffic rerouted < 2 min, all health checks pass |
| **Full DR simulation** | Annually | All Teams | 4 hours | Complete recovery within RTO, RPO met |

### Monthly Backup Verification (1st Tuesday, 10am)

```bash
# Run backup verification script
./scripts/verify_backup.py --latest

# Expected output:
# ✅ Backup file exists
# ✅ Backup is readable
# ✅ Backup contains expected tables
# ✅ Backup can be restored to test database
# ✅ Data integrity check passed

# Test restoration procedure
./scripts/test_restore.sh --sandbox

# Verify critical tables
psql -h $TEST_DB_HOST -c "
SELECT
  (SELECT COUNT(*) FROM tasks) as tasks,
  (SELECT COUNT(*) FROM users) as users,
  (SELECT COUNT(*) FROM repositories) as repositories;
"
```

### Monthly Database Failover Test (3rd Wednesday, 2pm)

```bash
# 1. Pre-test checks
mahavishnu db health
mahavishnu db replication-status

# 2. Initiate controlled failover
mahavishnu db failover --to-replica --dry-run  # Test mode
mahavishnu db failover --to-replica            # Actual failover

# 3. Verify failover
mahavishnu db health
mahavishnu db replication-status

# 4. Verify application connectivity
curl -s https://mahavishnu.example.com/health/db

# 5. Failback (if applicable)
mahavishnu db failback --to-primary

# 6. Document results
# - Time to detect: ___ seconds
# - Time to failover: ___ seconds
# - Data loss (if any): ___ transactions
# - Issues encountered: ___
```

### Quarterly Service Failover Test

```markdown
## Pre-Test Checklist
- [ ] Notify stakeholders 48 hours in advance
- [ ] Schedule during low-traffic window
- [ ] Verify all runbooks are up to date
- [ ] Ensure on-call engineer is available

## Test Procedure

### Phase 1: Preparation (30 min)
1. Document current state (traffic, errors, latency)
2. Verify standby environment health
3. Prepare rollback procedure

### Phase 2: Failover (15 min)
1. Drain traffic from primary
2. Update DNS/load balancer to standby
3. Verify traffic flowing to standby

### Phase 3: Validation (30 min)
1. Run smoke tests
2. Verify monitoring dashboards
3. Test critical user journeys

### Phase 4: Failback (30 min)
1. Verify primary is healthy
2. Sync any missed data
3. Failback to primary
4. Verify traffic flow

### Phase 5: Cleanup (15 min)
1. Document results
2. Update runbooks if needed
3. Schedule retro if issues found
```

### Annual Full DR Simulation

**Scope**: Complete production recovery in isolated DR environment

```markdown
## Annual DR Simulation Checklist

### Week Before
- [ ] Create DR simulation ticket
- [ ] Assign participants and roles
- [ ] Prepare DR environment
- [ ] Brief all participants

### Day Of Simulation
1. **Announce simulation** (not surprise drill)
2. **Simulate disaster scenario**:
   - Primary region unavailable
   - Database corrupted
   - All services down

3. **Execute full DR procedure**:
   - Provision DR infrastructure
   - Restore from backups
   - Configure networking
   - Deploy applications
   - Verify data integrity
   - Run full test suite

4. **Measure against targets**:
   | Metric | Target | Actual |
   |--------|--------|--------|
   | Time to provision | < 30 min | ___ |
   | Time to restore data | < 20 min | ___ |
   | Time to deploy | < 10 min | ___ |
   | Total RTO | < 1 hour | ___ |
   | Data loss (RPO) | < 1 hour | ___ |

5. **Document findings**:
   - What worked well
   - What didn't work
   - Action items for improvement
```

### DR Test Results Template

```markdown
## DR Test Report - [DATE]

### Summary
- **Test Type**: [Backup/Failover/Full DR]
- **Duration**: [X hours Y minutes]
- **Result**: [PASS/FAIL/DEGRADED]

### Metrics
| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| RTO | 1 hour | ___ | ✅/❌ |
| RPO | 1 hour | ___ | ✅/❌ |
| Data integrity | 100% | ___% | ✅/❌ |

### Issues Found
1. [Issue description]
   - Impact: [High/Medium/Low]
   - Action item: [Ticket #]

### Recommendations
1. [Recommendation]

### Next Test
- **Scheduled**: [DATE]
- **Type**: [Test type]
```

---

## Emergency Contacts

| Role | Contact | Availability |
|------|---------|--------------|
| On-Call Engineer | @oncall | 24/7 |
| SRE Lead | @sre-lead | Business hours |
| DBA | @dba | Business hours |
| Incident Commander | @ic | During incidents |
