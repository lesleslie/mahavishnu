# Operational Runbooks for Mahavishnu

**Version:** 1.0.0
**Last Updated:** 2025-02-05
**Target Audience:** Production Operations Teams, SREs, DevOps Engineers

## Table of Contents

1. [Incident Response Runbook](#1-incident-response-runbook)
2. [Deployment Runbook](#2-deployment-runbook)
3. [Backup/Restore Runbook](#3-backuprestore-runbook)
4. [Monitoring and Alerting Runbook](#4-monitoring-and-alerting-runbook)
5. [Common Operational Procedures](#5-common-operational-procedures)
6. [Health Check Procedures](#6-health-check-procedures)
7. [Performance Tuning Guide](#7-performance-tuning-guide)
8. [Security Runbook](#8-security-runbook)

---

## 1. Incident Response Runbook

### Purpose

Provides structured procedures for responding to production incidents affecting Mahavishnu orchestration platform.

### Prerequisites

- Access to production infrastructure (Docker/Kubernetes)
- SSH access to servers (if applicable)
- Access to monitoring dashboards (Grafana, Prometheus)
- Access to logs (aggregated logging system)
- Admin permissions on Mahavishnu CLI
- Communication channels (Slack, PagerDuty, etc.)

### Alert Levels and Severity

| Severity | Name | Response Time | Description |
|----------|------|---------------|-------------|
| **P1** | Critical | 15 minutes | Complete service outage, data loss, security breach |
| **P2** | High | 1 hour | Major functionality broken, significant performance degradation |
| **P3** | Medium | 4 hours | Partial functionality loss, minor performance issues |
| **P4** | Low | 1 business day | Cosmetic issues, documentation errors |

### Initial Triage Checklist (Time: 0-5 minutes)

**Step 1: Acknowledge the Alert**
- [ ] Acknowledge alert in monitoring system
- [ ] Post in incident response channel (e.g., \`#incidents\`)
- [ ] Set severity level based on impact

**Step 2: Gather Initial Information**
\`\`\`bash
# Check service status
mahavishnu mcp status

# Check health endpoints
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/health/components

# Check recent logs (last 100 lines)
journalctl -u mahavishnu -n 100 --no-pager

# Check resource usage
top -b -n 1 | head -20
df -h
free -m
\`\`\`

**Step 3: Assess Impact**
- [ ] Number of users affected
- [ ] Geographic scope of impact
- [ ] Business impact (revenue, operations, etc.)
- [ ] Downstream services affected

**Step 4: Declare Incident Severity**
- [ ] Assign severity (P1-P4)
- [ ] Notify stakeholders based on severity
- [ ] Create incident ticket/postmortem document

### Common Incident Scenarios

#### Scenario 1: High Error Rate Spike

**Symptoms:**
- Error rate > 5% in monitoring dashboards
- HTTP 5xx responses increasing
- Application logs showing exceptions

**Triage Steps:**
\`\`\`bash
# Check error rate in Prometheus (last 5 minutes)
curl 'http://localhost:9090/api/v1/query?query=rate(mahavishnu_errors_total[5m])'

# Check recent error logs
journalctl -u mahavishnu --since "5 minutes ago" | grep -i error

# Check component health
curl http://localhost:8080/health/components | jq '.components'
\`\`\`

**Response Procedures:**

**If Circuit Breaker is Open:**
\`\`\`bash
# Wait for circuit breaker to cool down (typically 60 seconds)
curl http://localhost:8080/health/components | jq '.components.circuit_breaker_main'

# If errors persist, restart affected adapter
mahavishnu adapter restart llamaindex
\`\`\`

**If Database Connection Failed:**
\`\`\`bash
# Check database connectivity
psql -h localhost -U mahavishnu -c "SELECT 1;"

# Restart database connection
mahavishnu ecosystem restart-database
\`\`\`

**Verification Steps:**
\`\`\`bash
# Check error rate has returned to normal (< 0.1%)
curl 'http://localhost:9090/api/v1/query?query=rate(mahavishnu_errors_total[5m])'

# Run health checks
curl http://localhost:8080/health
curl http://localhost:8080/ready
\`\`\`

---

#### Scenario 2: Performance Degradation

**Symptoms:**
- Response time P95 > 5 seconds (baseline: < 1 second)
- CPU usage > 80%
- Memory usage > 85%
- Disk I/O at 100%

**Response Procedures:**

**If Worker Pool Exhausted:**
\`\`\`bash
# Scale up pool (add 5 workers)
mahavishnu pool scale <pool_id> --target +5

# Or spawn new pool
mahavishnu pool spawn --type mahavishnu --name emergency --min 5 --max 10
\`\`\`

**If Memory Exhausted:**
\`\`\`bash
# Restart service if memory > 90%
sudo systemctl restart mahavishnu

# Or scale up deployment (Kubernetes)
kubectl scale deployment mahavishnu --replicas=4
\`\`\`

---

#### Scenario 3: Complete Service Outage

**Symptoms:**
- All health checks failing
- MCP server not responding
- No metrics in Prometheus

**Response Procedures:**

**If Service Crashed:**
\`\`\`bash
# Restart service
sudo systemctl restart mahavishnu

# Monitor startup
sudo journalctl -u mahavishnu -f --no-pager
\`\`\`

**Rollback Procedure:**
\`\`\`bash
# If nothing works, rollback to previous deployment
cd /opt/mahavishnu
git log --oneline -10
git checkout <previous_commit_hash>
sudo systemctl restart mahavishnu
\`\`\`

---

### Escalation Paths

**P1 - Critical:**
1. Page on-call engineer immediately
2. Page engineering manager after 15 minutes
3. Page CTO after 30 minutes if unresolved
4. Create incident bridge call

**P2 - High:**
1. Page on-call engineer
2. Notify engineering manager via Slack
3. Schedule postmortem meeting

**P3 - Medium:**
1. Create ticket in issue tracker
2. Assign to appropriate team
3. Target resolution: 1 business day

**P4 - Low:**
1. Create backlog item
2. Address in next sprint

---

## 2. Deployment Runbook

### Purpose

Provides procedures for deploying Mahavishnu to production with minimal downtime and risk.

### Pre-Deployment Checklist

- [ ] All tests passing (unit, integration, e2e)
- [ ] Code reviewed and approved
- [ ] No critical security vulnerabilities
- [ ] Performance benchmarks meet baseline
- [ ] Environment variables configured
- [ ] Database migrations prepared
- [ ] Backup created before deployment
- [ ] Rollback plan documented

**Run Production Validation:**
\`\`\`bash
mahavishnu validate-production
\`\`\`

### Deployment Strategies

#### Strategy 1: Blue-Green Deployment (Recommended)

**Procedure:**

**Step 1: Deploy to Green Environment**
\`\`\`bash
kubectl apply -f k8s/ -n mahavishnu-green
kubectl wait --for=condition=ready pod -l app=mahavishnu -n mahavishnu-green --timeout=300s
\`\`\`

**Step 2: Health Check Green Environment**
\`\`\`bash
kubectl port-forward -n mahavishnu-green svc/mahavishnu 8080:8080
curl http://localhost:8080/health
curl http://localhost:8080/ready
\`\`\`

**Step 3: Switch Traffic to Green**
\`\`\`bash
kubectl patch svc mahavishnu -n mahavishnu-prod -p '{"spec":{"selector":{"version":"green"}}}'
\`\`\`

**Rollback Procedure:**
\`\`\`bash
kubectl patch svc mahavishnu -n mahavishnu-prod -p '{"spec":{"selector":{"version":"blue"}}}'
kubectl scale deployment mahavishnu -n mahavishnu-green --replicas=0
\`\`\`

---

#### Strategy 2: Rolling Deployment (Kubernetes)

**Procedure:**
\`\`\`bash
# Create backup
mahavishnu backup create --type full

# Update deployment
kubectl set image deployment/mahavishnu mahavishnu=<registry>/mahavishnu:<new_tag> -n mahavishnu-prod

# Watch rollout
kubectl rollout status deployment/mahavishnu -n mahavishnu-prod
\`\`\`

**Rollback:**
\`\`\`bash
kubectl rollout undo deployment/mahavishnu -n mahavishnu-prod
\`\`\`

---

#### Strategy 3: Canary Deployment

**Procedure:**
\`\`\`bash
# Deploy canary (5% traffic)
kubectl apply -f k8s/canary-deployment.yaml -n mahavishnu-prod

# Monitor for 30-60 minutes
# Gradually increase to 25%, 50%, 100%
\`\`\`

---

### Post-Deployment Verification

\`\`\`bash
# Health checks
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/health/components

# Smoke tests
mahavishnu test --smoke

# Metrics verification
curl 'http://localhost:9090/api/v1/query?query=rate(mahavishnu_errors_total[5m])'
\`\`\`

---

## 3. Backup/Restore Runbook

### Purpose

Procedures for creating, managing, and restoring backups.

### Creating Backups

\`\`\`bash
# Manual full backup
mahavishnu backup create --type full

# Automated daily backup (cron)
0 2 * * * /usr/local/bin/mahavishnu backup create --type full >> /var/log/mahavishnu-backup.log 2>&1
\`\`\`

### Listing Backups

\`\`\`bash
mahavishnu backup list
\`\`\`

### Restore Procedures

#### Full System Restore

\`\`\`bash
# Download backup
aws s3 cp s3://mahavishnu-backups/backup_20250205_103000.tar.gz /opt/mahavishnu/backups/

# Restore backup
mahavishnu backup restore backup_20250205_103000

# Restart service
sudo systemctl restart mahavishnu

# Verify restore
curl http://localhost:8080/health
\`\`\`

#### Disaster Recovery

\`\`\`bash
# Run disaster recovery check
mahavishnu dr check

# Initiate disaster recovery
mahavishnu dr recover --backup backup_20250205_103000
\`\`\`

---

## 4. Monitoring and Alerting Runbook

### Key Metrics to Monitor

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|-----------------|
| \`up\` | Gauge | Service is up | < 1 for 1 minute |
| \`mahavishnu_request_duration_seconds\` | Histogram | Request latency | P95 > 1s for 5 minutes |
| \`mahavishnu_errors_total\` | Counter | Total errors | Rate > 5% for 5 minutes |
| \`mahavishnu_active_workflows\` | Gauge | Running workflows | > 100 for 10 minutes |

### Alert Configuration

Sample Prometheus alert rules in \`alerts/mahavishnu.yml\`:

\`\`\`yaml
groups:
  - name: mahavishnu_alerts
    interval: 30s
    rules:
      - alert: MahavishnuServiceDown
        expr: up{job="mahavishnu"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Mahavishnu service is down"
\`\`\`

### Dashboard Setup

\`\`\`bash
# Import Grafana dashboard
grafana-cli import-dashboard mahavishnu-dashboard.json

# Or create via UI
# 1. Open Grafana
# 2. Go to Dashboards -> Import
# 3. Upload dashboard JSON
\`\`\`

---

## 5. Common Operational Procedures

### Starting/Stopping Services

**Systemd:**
\`\`\`bash
sudo systemctl start mahavishnu
sudo systemctl stop mahavishnu
sudo systemctl restart mahavishnu
\`\`\`

**Docker:**
\`\`\`bash
docker start mahavishnu
docker stop mahavishnu
docker restart mahavishnu
\`\`\`

**Kubernetes:**
\`\`\`bash
kubectl scale deployment mahavishnu --replicas=3
kubectl scale deployment mahavishnu --replicas=0
\`\`\`

### Pool Management

\`\`\`bash
# List pools
mahavishnu pool list

# Spawn new pool
mahavishnu pool spawn --type mahavishnu --name prod --min 3 --max 10

# Scale pool
mahavishnu pool scale <pool_id> --target 10

# Close pool
mahavishnu pool close <pool_id>
\`\`\`

### Configuration Updates

\`\`\`bash
# Edit configuration
vim /opt/mahavishnu/settings/mahavishnu.yaml

# Validate configuration
mahavishnu config validate

# Reload configuration
mahavishnu config reload

# Or restart service
sudo systemctl restart mahavishnu
\`\`\`

---

## 6. Health Check Procedures

### Running Health Checks

\`\`\`bash
# Liveness check
curl http://localhost:8080/health

# Readiness check
curl http://localhost:8080/ready

# Component health
curl http://localhost:8080/health/components
\`\`\`

### Interpreting Results

| Status | Description | Action |
|--------|-------------|--------|
| **healthy** | Component fully operational | No action needed |
| **degraded** | Reduced capacity | Monitor closely |
| **unhealthy** | Failing | Immediate action required |

### Kubernetes Probes

\`\`\`yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
\`\`\`

---

## 7. Performance Tuning Guide

### Cache Optimization

\`\`\`yaml
# settings/mahavishnu.yaml
cache:
  enabled: true
  backend: "redis"
  ttl: 3600
  max_size: 1000
\`\`\`

### Worker Pool Sizing

\`\`\`bash
# Determine optimal workers
optimal_workers = (target_cpu_utilization * total_cpu) / avg_task_cpu_time

# Example: (0.70 * 8) / 2 = 2.8 workers per CPU core
\`\`\`

### Memory Management

\`\`\`bash
# Set memory limits (systemd)
# /etc/systemd/system/mahavishnu.service
[Service]
MemoryLimit=4G
MemoryMax=4G
\`\`\`

---

## 8. Security Runbook

### Security Incident Response

\`\`\`bash
# 1. Identify incident
journalctl -u mahavishnu --since "1 hour ago" | grep -i "failed\|unauthorized"

# 2. Contain incident
sudo systemctl stop mahavishnu
sudo iptables -A INPUT -s <suspicious_ip> -j DROP

# 3. Assess impact
grep -r "SELECT\|COPY" /var/log/postgresql/ | tail -100

# 4. Eradicate threat
mahavishnu security rotate-secrets

# 5. Recover
mahavishnu backup restore <backup_id>
\`\`\`

### Access Control

\`\`\`bash
# List users
mahavishnu auth list-users

# Create user
mahavishnu auth create-user --username john.doe --role operator

# Rotate secrets
mahavishnu security rotate-jwt-secret
\`\`\`

### Vulnerability Scanning

\`\`\`bash
# Run Bandit
bandit -r mahavishnu/

# Run Safety
safety check

# Run Trivy
trivy image mahavishnu:latest
\`\`\`

---

## Appendix

### Quick Reference Commands

\`\`\`bash
# Health Checks
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Service Management
sudo systemctl restart mahavishnu

# Logs
journalctl -u mahavishnu -f

# Backup
mahavishnu backup create --type full

# Pool Management
mahavishnu pool list
mahavishnu pool spawn --type mahavishnu --name prod --min 3 --max 10

# Production Validation
mahavishnu validate-production
\`\`\`

### Related Documentation

- [Architecture Decision Records](/docs/adr/)
- [Production Readiness Report](/docs/PRODUCTION_READINESS_REPORT.md)
- [Security Audit Report](/docs/SECURITY_AUDIT_REPORT.md)
- [API Documentation](/docs/API.md)

---

**End of Operational Runbooks**
