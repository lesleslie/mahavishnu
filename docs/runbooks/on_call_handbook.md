# On-Call Handbook

This handbook provides guidance for on-call engineers supporting the Mahavishnu Task Orchestration System.

## Table of Contents

1. [On-Call Overview](#on-call-overview)
2. [Rotation Schedule](#rotation-schedule)
3. [Escalation Paths](#escalation-paths)
4. [Common Alerts and Responses](#common-alerts-and-responses)
5. [Handoff Procedures](#handoff-procedures)
6. [On-Call Best Practices](#on-call-best-practices)

---

## On-Call Overview

### Responsibilities

As an on-call engineer for Mahavishnu, you are responsible for:

1. **Monitoring**: Responding to alerts within SLA
2. **Incident Response**: Triaging and resolving incidents
3. **Communication**: Keeping stakeholders informed
4. **Documentation**: Recording actions and learnings

### Expected Response Times

| Severity | Initial Response | Update Frequency |
|----------|------------------|------------------|
| **P0 - Critical** | 5 minutes | Every 15 minutes |
| **P1 - High** | 15 minutes | Every 30 minutes |
| **P2 - Medium** | 1 hour | Every 2 hours |
| **P3 - Low** | 4 hours | Daily |

### On-Call Tools

| Tool | Purpose | Access |
|------|---------|--------|
| PagerDuty | Alert management | pagerduty.example.com |
| Grafana | Dashboards | grafana.example.com |
| Prometheus | Metrics | prometheus.example.com |
| Kubectl | Kubernetes management | CLI |
| Incident Channel | Communication | Slack #incident-* |

---

## Rotation Schedule

### Primary and Shadow Rotation

```
Week of        Primary        Shadow
2026-02-16     @alice         @bob
2026-02-23     @charlie       @alice
2026-03-02     @bob           @charlie
2026-03-09     @diana         @bob
```

### Schedule Rules

1. **Primary**: First responder to all alerts
2. **Shadow**: Backup for primary, learning role
3. **Rotation**: Weekly, starting Monday 00:00 UTC
4. **Handoff**: Sunday 23:00 UTC (1 hour before transition)

### Time Zone Considerations

- Schedule is in UTC
- Primary and shadow should be in different time zones when possible
- If both are unavailable, escalate to secondary on-call

---

## Escalation Paths

### Escalation Levels

```
T0: Primary On-Call (5 min response)
  └─> T1: Secondary On-Call (15 min response)
       └─> T2: Team Lead (30 min response)
            └─> T3: Engineering Manager (1 hour response)
                 └─> T4: VP Engineering (Critical only)
```

### When to Escalate

1. **Immediate**: If you cannot access systems
2. **15 minutes**: If you cannot diagnose the issue
3. **30 minutes**: If issue is not resolved
4. **1 hour**: If business impact is significant

### Escalation Contacts

| Level | Role | Contact |
|-------|------|---------|
| T0 | Primary On-Call | @oncall-primary |
| T1 | Secondary On-Call | @oncall-secondary |
| T2 | Team Lead | @team-lead |
| T3 | Engineering Manager | @eng-manager |
| T4 | VP Engineering | @vp-eng |

---

## Common Alerts and Responses

### Alert: High Error Rate

**Alert Name**: `HighErrorRate`

**Threshold**: Error rate > 5% for 5 minutes

**Response**:
```bash
# 1. Check error details
curl -s "http://prometheus.example.com/api/v1/query?query=rate(mahavishnu_task_errors_total[5m])" | jq

# 2. Check recent deployment
kubectl rollout history deployment/mahavishnu -n mahavishnu

# 3. Check application logs
kubectl logs -n mahavishnu -l app=mahavishnu --tail=200 | grep ERROR

# 4. If recent deployment, consider rollback
kubectl rollout undo deployment/mahavishnu -n mahavishnu
```

### Alert: Database Connection Pool Exhausted

**Alert Name**: `DatabasePoolExhausted`

**Threshold**: Active connections > 90% of max

**Response**:
```bash
# 1. Check current connections
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "SELECT COUNT(*) FROM pg_stat_activity;"

# 2. Check for long-running queries
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "
SELECT pid, query, state, now() - pg_stat_activity.query_start AS duration
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes';
"

# 3. Kill long-running queries if needed
psql -h $DB_HOST -U $DB_USER -d mahavishnu -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE duration > interval '10 minutes';"

# 4. Restart application to reset connections
kubectl rollout restart deployment/mahavishnu -n mahavishnu
```

### Alert: Webhook Verification Failures

**Alert Name**: `HighWebhookFailureRate`

**Threshold**: Failure rate > 10% for 5 minutes

**Response**:
```bash
# 1. Check failure types
curl -s "http://prometheus.example.com/api/v1/query?query=sum by (result) (rate(mahavishnu_webhook_operations_total{result!=\"success\"}[5m]))" | jq

# 2. Check webhook logs
kubectl logs -n mahavishnu -l app=mahavishnu --tail=200 | grep -i webhook

# 3. If signature failures, verify webhook secret
# Check if secret was rotated without updating external services

# 4. If replay attacks, check for duplicate webhook sources
grep "replay_attack" /var/log/mahavishnu/audit.log | tail -20
```

### Alert: Memory Usage High

**Alert Name**: `HighMemoryUsage`

**Threshold**: Memory > 85% for 10 minutes

**Response**:
```bash
# 1. Check pod memory
kubectl top pods -n mahavishnu

# 2. Check for memory leaks in logs
kubectl logs -n mahavishnu -l app=mahavishnu --tail=200 | grep -i "out of memory\|memory"

# 3. Restart pods to clear memory
kubectl rollout restart deployment/mahavishnu -n mahavishnu

# 4. If persistent, increase memory limits
kubectl set resources deployment/mahavishnu \
  --limits=memory=2Gi \
  -n mahavishnu
```

### Alert: Task Queue Backed Up

**Alert Name**: `TaskQueueBackup`

**Threshold**: Pending tasks > 100 for 15 minutes

**Response**:
```bash
# 1. Check task distribution
curl -s "http://prometheus.example.com/api/v1/query?query=mahavishnu_active_tasks" | jq

# 2. Check for blocked tasks
curl -s "https://mahavishnu.example.com/api/tasks?status=blocked" | jq 'length'

# 3. Check worker health
kubectl get pods -n mahavishnu -l role=worker

# 4. Scale workers if needed
kubectl scale deployment mahavishnu-worker --replicas=5 -n mahavishnu
```

---

## Handoff Procedures

### Outgoing Handoff

Before your shift ends, complete these tasks:

1. **Document Open Issues**:
   - Create tickets for unresolved issues
   - Update incident tickets with current status

2. **Prepare Handoff Notes**:
   ```
   ## On-Call Handoff: YYYY-MM-DD

   ### Summary
   - Total alerts: X
   - Incidents: Y
   - Current issues: Z

   ### Open Items
   - [ ] Issue 1: Description, current status, next steps
   - [ ] Issue 2: Description, current status, next steps

   ### Watch Items
   - Item to monitor: Why it's important

   ### System Status
   - Overall health: Green/Yellow/Red
   - Recent changes: Any deployments or config changes
   - Upcoming maintenance: Any scheduled changes
   ```

3. **Sync with Incoming On-Call**:
   - Schedule 15-minute sync call
   - Walk through open items
   - Answer questions

### Incoming Handoff

When starting your shift:

1. **Review Handoff Notes**: Read through previous on-call's notes
2. **Check System Health**: Verify all systems are operational
3. **Review Open Incidents**: Understand current issues
4. **Verify Access**: Ensure you have access to all systems
5. **Update Status**: Mark yourself as on-call in team channels

---

## On-Call Best Practices

### Do's

1. **Acknowledge alerts quickly** - Even if you need time to investigate
2. **Communicate early and often** - Keep stakeholders informed
3. **Document everything** - Future you will thank present you
4. **Ask for help** - Escalate if unsure
5. **Take breaks** - Avoid burnout during extended incidents

### Don'ts

1. **Don't ignore alerts** - They don't go away
2. **Don't make changes without rollback plan** - Always have an escape route
3. **Don't work alone on P0s** - Get help immediately
4. **Don't skip handoff** - Incoming on-call needs context
5. **Don't blame** - Focus on resolution, not fault

### Managing On-Call Burden

1. **Limit shift length**: Maximum 1 week primary
2. **Comp time**: Take time off after difficult shifts
3. **Automate**: Convert manual responses to runbooks/scripts
4. **Improve alerting**: Tune noisy alerts during business hours
5. **Post-mortems**: Address systemic issues to reduce alerts

---

## Quick Reference

### Key Dashboards

| Dashboard | URL |
|-----------|-----|
| SLO Overview | grafana.example.com/d/task-orchestration-slo |
| Operational Health | grafana.example.com/d/task-orchestration-operational |
| Kubernetes Overview | grafana.example.com/d/kubernetes |

### Key Commands

```bash
# Check pod status
kubectl get pods -n mahavishnu

# View recent logs
kubectl logs -n mahavishnu -l app=mahavishnu --tail=100

# Restart deployment
kubectl rollout restart deployment/mahavishnu -n mahavishnu

# Rollback deployment
kubectl rollout undo deployment/mahavishnu -n mahavishnu

# Scale deployment
kubectl scale deployment mahavishnu --replicas=5 -n mahavishnu

# Check resource usage
kubectl top pods -n mahavishnu

# Execute into pod
kubectl exec -it -n mahavishnu deployment/mahavishnu -- /bin/bash
```

### Useful Queries

```promql
# Error rate
rate(mahavishnu_task_errors_total[5m])

# Active tasks by status
sum by (status) (mahavishnu_active_tasks)

# P99 task duration
histogram_quantile(0.99, rate(mahavishnu_task_duration_seconds_bucket[5m]))

# Webhook success rate
sum(rate(mahavishnu_webhook_operations_total{result="success"}[5m])) 
/ 
sum(rate(mahavishnu_webhook_operations_total[5m]))
```
