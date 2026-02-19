# Deployment Runbook

This runbook provides step-by-step procedures for deploying the Mahavishnu Task Orchestration System.

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Deployment Procedures](#deployment-procedures)
3. [Post-Deployment Verification](#post-deployment-verification)
4. [Rollback Procedures](#rollback-procedures)
5. [Common Issues](#common-issues)

---

## Pre-Deployment Checklist

### Code Quality Checks

```bash
# Run all quality checks
crackerjack run all

# Or individually:
ruff check mahavishnu/           # Lint
ruff format mahavishnu/          # Format
pyright mahavishnu/              # Type check
pytest tests/ --cov=mahavishnu   # Tests with coverage
```

### Security Checks

```bash
# Run security tests
pytest tests/security/ -v --no-cov

# Check for vulnerable dependencies
safety check
pip-audit

# Security linting
bandit -r mahavishnu/
```

### Configuration Verification

```bash
# Validate configuration
python -c "from mahavishnu.core.config import MahavishnuSettings; s = MahavishnuSettings(); print(s.model_dump())"

# Check environment variables are set
env | grep MAHAVISHNU_
```

### Database Readiness

```bash
# Verify database connection
python -c "
from mahavishnu.core.app import MahavishnuApp
import asyncio

async def check():
    app = MahavishnuApp()
    await app.initialize()
    print('Database connection: OK')
    await app.shutdown()

asyncio.run(check())
"
```

---

## Deployment Procedures

### Standard Deployment (Blue-Green)

#### Step 1: Prepare New Version

```bash
# Pull latest code
git pull origin main

# Install/update dependencies
uv sync

# Run migrations (if any)
alembic upgrade head
```

#### Step 2: Run Pre-Flight Checks

```bash
# Full test suite
pytest tests/ -v --cov=mahavishnu --cov-fail-under=80

# Security tests specifically
pytest tests/security/ -v
```

#### Step 3: Deploy to Staging

```bash
# Deploy to staging environment
./scripts/deploy.sh staging

# Verify staging is healthy
curl -s https://staging.mahavishnu.example.com/health | jq
```

#### Step 4: Deploy to Production

```bash
# Deploy to production (blue-green)
./scripts/deploy.sh production --strategy blue-green

# The script will:
# 1. Deploy to "green" environment
# 2. Run health checks
# 3. Switch traffic from "blue" to "green"
# 4. Keep "blue" running for quick rollback
```

#### Step 5: Verify Deployment

```bash
# Check application health
curl -s https://mahavishnu.example.com/health | jq

# Check Prometheus metrics
curl -s https://mahavishnu.example.com:9091/metrics | head -20

# Verify task operations work
curl -X POST https://mahavishnu.example.com/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Test task", "repository": "test-repo"}'
```

### Canary Deployment

For high-risk changes, use canary deployment:

```bash
# Deploy to 10% of traffic initially
./scripts/deploy.sh production --strategy canary --percent 10

# Monitor for 30 minutes
# If successful, increase to 50%
./scripts/deploy.sh production --strategy canary --percent 50

# Monitor for another 30 minutes
# If successful, complete rollout
./scripts/deploy.sh production --strategy canary --percent 100
```

### Rolling Deployment (Kubernetes)

```bash
# Update deployment
kubectl set image deployment/mahavishnu \
  mahavishnu=mahavishnu:v1.2.3 \
  --namespace mahavishnu

# Watch rollout status
kubectl rollout status deployment/mahavishnu \
  --namespace mahavishnu

# Check pod health
kubectl get pods -n mahavishnu -w
```

---

## Post-Deployment Verification

### Health Checks

```bash
# Application health
curl -s https://mahavishnu.example.com/health | jq

# MCP server health
curl -s https://mahavishnu.example.com:8680/mcp/health | jq

# Database connectivity
curl -s https://mahavishnu.example.com/health/db | jq

# All components
curl -s https://mahavishnu.example.com/health/all | jq
```

### Smoke Tests

```bash
# Create a test task
TASK_ID=$(curl -s -X POST https://mahavishnu.example.com/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Smoke test", "repository": "test-repo"}' | jq -r '.id')

# Verify task was created
curl -s "https://mahavishnu.example.com/api/tasks/$TASK_ID" | jq

# Update task
curl -s -X PATCH "https://mahavishnu.example.com/api/tasks/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress"}' | jq

# Delete test task
curl -s -X DELETE "https://mahavishnu.example.com/api/tasks/$TASK_ID"
```

### Monitoring Verification

```bash
# Check Grafana dashboards are receiving data
curl -s "http://grafana.example.com/api/dashboards/uid/task-orchestration-slo" | jq '.dashboard.title'

# Verify Prometheus is scraping metrics
curl -s "http://prometheus.example.com/api/v1/targets" | jq '.data.activeTargets[].health'

# Check for recent errors
curl -s "http://prometheus.example.com/api/v1/query?query=rate(mahavishnu_task_errors_total[5m])" | jq
```

---

## Rollback Procedures

### Quick Rollback (Blue-Green)

```bash
# Switch traffic back to "blue" environment
./scripts/rollback.sh production --quick

# Verify rollback
curl -s https://mahavishnu.example.com/health | jq
```

### Full Rollback (Kubernetes)

```bash
# View rollout history
kubectl rollout history deployment/mahavishnu --namespace mahavishnu

# Rollback to previous version
kubectl rollout undo deployment/mahavishnu --namespace mahavishnu

# Rollback to specific revision
kubectl rollout undo deployment/mahavishnu \
  --namespace mahavishnu \
  --to-revision=3

# Watch rollback status
kubectl rollout status deployment/mahavishnu --namespace mahavishnu
```

### Database Migration Rollback

```bash
# Check current migration version
alembic current

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123

# Full rollback to base
alembic downgrade base
```

### Rollback Triggers

#### Application-Level Triggers

Automatic rollback should be triggered if:

| Metric | Threshold | Window |
|--------|-----------|--------|
| Error rate | > 5% | 5 minutes |
| P99 latency | > 10s | 5 minutes |
| Health check failures | > 3 consecutive | 1 minute |
| Memory usage | > 90% | 5 minutes |

#### Database Migration-Specific Triggers

For migrations, additional triggers must be monitored:

| Metric | Threshold | Action |
|--------|-----------|--------|
| **Query performance regression** | > 2x baseline latency | Investigate, consider rollback |
| **Lock wait timeout** | > 30 seconds | Rollback immediately |
| **Deadlock rate** | > 0.1% of queries | Rollback immediately |
| **Connection pool exhaustion** | < 10% connections available | Scale or rollback |
| **Replication lag** | > 60 seconds | Pause migration, investigate |
| **Disk usage spike** | > 80% during migration | Pause migration |
| **Data validation failure** | Any mismatch | Rollback immediately |

#### Data Validation Triggers

After migration, validate data integrity:

```bash
# Row count validation
EXPECTED_ROWS=$(cat migration_metadata.json | jq '.pre_migration_row_count')
ACTUAL_ROWS=$(psql -c "SELECT COUNT(*) FROM tasks" -t)

if [ "$EXPECTED_ROWS" != "$ACTUAL_ROWS" ]; then
    echo "CRITICAL: Row count mismatch! Expected $EXPECTED_ROWS, got $ACTUAL_ROWS"
    # Trigger rollback
    alembic downgrade -1
    exit 1
fi

# Hash validation (critical tables)
pre_hash=$(cat migration_metadata.json | jq '.table_hashes.tasks')
post_hash=$(psql -c "SELECT md5(CAST((array_agg(t ORDER BY id)) AS text)) FROM tasks t" -t)

if [ "$pre_hash" != "$post_hash" ]; then
    echo "CRITICAL: Data hash mismatch! Data may be corrupted."
    # Trigger rollback
    alembic downgrade -1
    exit 1
fi

# Foreign key integrity
fk_check=$(psql -c "SELECT COUNT(*) FROM tasks t LEFT JOIN users u ON t.user_id = u.id WHERE u.id IS NULL AND t.user_id IS NOT NULL" -t)

if [ "$fk_check" != "0" ]; then
    echo "CRITICAL: Foreign key integrity violation! $fk_check orphaned records."
    # Trigger rollback
    alembic downgrade -1
    exit 1
fi
```

#### Manual Rollback Decision Tree

```
Is data integrity at risk?
├── YES → Rollback immediately, investigate after recovery
└── NO → Is performance degraded > 2x?
    ├── YES → Can it be fixed with hotfix?
    │   ├── YES → Deploy hotfix within 15 min
    │   └── NO → Rollback
    └── NO → Continue monitoring, document for postmortem
```

---

## Common Issues

### Issue: Database Migration Fails

**Symptoms:**
- Deployment fails during migration step
- Application won't start

**Resolution:**
```bash
# Check migration status
alembic current
alembic history

# If stuck, manually mark as complete (CAUTION)
alembic stamp head

# Or rollback the failed migration
alembic downgrade -1
```

### Issue: Health Check Failing After Deploy

**Symptoms:**
- `/health` endpoint returns 503
- Load balancer removes instance

**Troubleshooting:**
```bash
# Check application logs
kubectl logs -n mahavishnu deployment/mahavishnu --tail=100

# Check if database is accessible
python -c "
from mahavishnu.core.config import MahavishnuSettings
s = MahavishnuSettings()
print(f'Database URL: {s.database_url}')
"

# Check if MCP server is running
curl -s http://localhost:8680/mcp/health
```

### Issue: High Memory Usage After Deploy

**Symptoms:**
- OOM kills
- Slow response times

**Resolution:**
```bash
# Check memory usage
kubectl top pods -n mahavishnu

# Restart pods to clear memory
kubectl rollout restart deployment/mahavishnu -n mahavishnu

# If persistent, increase memory limits
kubectl edit deployment mahavishnu -n mahavishnu
# Update: resources.limits.memory: "1Gi"
```

### Issue: Webhook Signature Failures After Deploy

**Symptoms:**
- High `signature_mismatch` count in logs
- External integrations failing

**Resolution:**
```bash
# Check webhook secret configuration
env | grep MAHAVISHNU_WEBHOOK_SECRET

# Verify secret matches external service
# If rotated, update external service configuration

# Test webhook signature
python -c "
import hmac, hashlib
secret = 'your-webhook-secret'
payload = b'{\"test\": \"data\"}'
mac = hmac.new(secret.encode(), payload, hashlib.sha256)
print(f'Signature: sha256={mac.hexdigest()}')
"
```

---

## Deployment Windows

| Environment | Window | Approval Required |
|-------------|--------|-------------------|
| Staging | Any time | No |
| Production | Mon-Thu 10am-4pm | Yes (via PR) |
| Production (hotfix) | Any time | Yes (post-hoc review) |

## Contacts

| Role | Contact |
|------|---------|
| On-Call Engineer | @oncall |
| Release Manager | @release-manager |
| Platform Team | #platform-team |
