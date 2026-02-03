# Production Deployment Guide

**Version**: 1.0
**Date**: 2026-02-02
**Project**: Mahavishnu MCP Ecosystem
**Purpose**: Guide for deploying Mahavishnu MCP ecosystem to production

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Infrastructure Setup](#infrastructure-setup)
3. [Environment Configuration](#environment-configuration)
4. [Deployment Process](#deployment-process)
5. [Smoke Tests](#smoke-tests)
6. [Monitoring & Validation](#monitoring--validation)
7. [Rollback Procedures](#rollback-procedures)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Infrastructure Requirements

**Minimum Requirements**:
- CPU: 4 cores per MCP server
- RAM: 8GB per MCP server
- Disk: 50GB SSD per MCP server
- Network: 1 Gbps

**Recommended Requirements**:
- CPU: 8 cores per MCP server
- RAM: 16GB per MCP server
- Disk: 100GB SSD per MCP server
- Network: 10 Gbps

### External Dependencies

**Required Services**:
- PostgreSQL 14+ (for Session-Buddy, Akosha)
- OpenSearch 2.x (for log aggregation)
- Redis 7+ (for caching, optional)
- S3-compatible storage (for backups)

**Optional Services**:
- Prometheus (for metrics)
- Grafana (for dashboards)
- AlertManager (for alerting)

### Software Requirements

**On Deployment Machine**:
- Python 3.11+
- uv (latest)
- Docker 24+ (if using containers)
- kubectl (if using Kubernetes)
- Terraform 1.5+ (if using IaC)

---

## Infrastructure Setup

### Option A: Cloud Run (Recommended for simplicity)

#### 1. Create Google Cloud Project

```bash
# Set project
export PROJECT_ID="mahavishnu-production"
gcloud config set project $PROJECT_ID

# Enable APIs
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  sql.googleapis.com \
  opensearch.googleapis.com \
  storage.googleapis.com
```

#### 2. Deploy Mahavishnu MCP Server

```bash
# Build and deploy
gcloud run deploy mahavishnu-mcp \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 8Gi \
  --cpu 4 \
  --max-instances 10 \
  --min-instances 1 \
  --port 8680 \
  --set-env-vars MAHAVISHNU_AUTH_SECRET="${AUTH_SECRET}" \
  --set-env-vars MAHAVISHNU_ENV="production" \
  --set-env-vars OPENSEARCH_URL="${OPENSEARCH_URL}" \
  --set-env-vars POSTGRES_URL="${POSTGRES_URL}"
```

#### 3. Deploy Session-Buddy

```bash
cd ../session-buddy

gcloud run deploy session-buddy \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
  --port 8678 \
  --set-env-vars SESSION_ENCRYPTION_KEY="${ENCRYPTION_KEY}" \
  --set-env-vars POSTGRES_URL="${POSTGRES_URL}"
```

#### 4. Deploy Akosha

```bash
cd ../akosha

gcloud run deploy akosha \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 8Gi \
  --cpu 4 \
  --port 8682 \
  --set-env-vars AKOSHA_API_TOKEN="${AKOSHA_TOKEN}" \
  --set-env-vars POSTGRES_URL="${POSTGRES_URL}"
```

### Option B: Docker Compose (For on-premises)

#### 1. Create docker-compose.yml

```yaml
version: '3.8'

services:
  # PostgreSQL
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: mahavishnu
      POSTGRES_USER: mahavishnu
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  # OpenSearch
  opensearch:
    image: opensearchproject/opensearch:latest
    environment:
      - discovery.type=single-node
      - DISABLE_SECURITY_PLUGIN=true
    ports:
      - "9200:9200"
    volumes:
      - opensearch_data:/usr/share/opensearch/data

  # Mahavishnu
  mahavishnu:
    image: mahavishnu:latest
    depends_on:
      - postgres
      - opensearch
    environment:
      - MAHAVISHNU_AUTH_SECRET=${AUTH_SECRET}
      - MAHAVISHNU_ENV=production
      - POSTGRES_URL=postgresql://mahavishnu:${POSTGRES_PASSWORD}@postgres:5432/mahavishnu
      - OPENSEARCH_URL=http://opensearch:9200
    ports:
      - "8680:8680"

  # Session-Buddy
  session-buddy:
    image: session-buddy:latest
    depends_on:
      - postgres
    environment:
      - SESSION_ENCRYPTION_KEY=${ENCRYPTION_KEY}
      - POSTGRES_URL=postgresql://mahavishnu:${POSTGRES_PASSWORD}@postgres:5432/mahavishnu
    ports:
      - "8678:8678"

  # Akosha
  akosha:
    image: akosha:latest
    depends_on:
      - postgres
    environment:
      - AKOSHA_API_TOKEN=${AKOSHA_TOKEN}
      - POSTGRES_URL=postgresql://mahavishnu:${POSTGRES_PASSWORD}@postgres:5432/mahavishnu
    ports:
      - "8682:8682"

volumes:
  postgres_data:
  opensearch_data:
```

#### 2. Deploy

```bash
# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### Option C: Kubernetes (For large-scale deployments)

See `kubernetes/deployment.md` for detailed Kubernetes manifests and deployment procedures.

---

## Environment Configuration

### Required Environment Variables

#### Mahavishnu MCP Server

```bash
# Authentication (REQUIRED for production)
export MAHAVISHNU_AUTH_SECRET="$(openssl rand -base64 32)"

# Environment
export MAHAVISHNU_ENV="production"

# Database
export POSTGRES_URL="postgresql://user:pass@host:5432/dbname"

# OpenSearch
export OPENSEARCH_URL="https://opensearch-cluster:9200"
export OPENSEARCH_USER="admin"
export OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD}"

# Observability
export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317"
export OTEL_SERVICE_NAME="mahavishnu-mcp"

# Rate Limiting
export RATE_LIMIT_ENABLED="true"
export RATE_LIMIT_PER_MINUTE="60"
export RATE_LIMIT_PER_HOUR="1000"
```

#### Session-Buddy

```bash
# Encryption (REQUIRED)
export SESSION_ENCRYPTION_KEY="$(openssl rand -base64 32)"

# Database
export POSTGRES_URL="postgresql://user:pass@host:5432/dbname"

# Pool Configuration
export WORKER_COUNT="3"
export POOL_MIN_SIZE="2"
export POOL_MAX_SIZE="10"
```

#### Akosha

```bash
# Authentication (REQUIRED)
export AKOSHA_API_TOKEN="$(openssl rand -hex 32)"

# Database
export POSTGRES_URL="postgresql://user:pass@host:5432/dbname"

# Embeddings
export EMBEDDING_MODEL="text-embedding-3-small"
export EMBEDDING_DIMENSIONS="1536"
```

### Configuration Files

#### Production Settings

Create `settings/production.yaml`:

```yaml
server_name: "Mahavishnu Production Orchestrator"

# Adapters
adapters:
  llamaindex: true
  prefect: false
  agno: false

# Quality Control
qc:
  enabled: true
  min_score: 80

# Authentication
auth_enabled: true
auth_algorithm: "RS256"
auth_token_expiry: 3600

# Repositories
repos_path: "/etc/mahavishnu/repos.yaml"

# Concurrency
max_concurrent_workflows: 10

# Timeouts
timeout_per_repo: 300
startup_timeout: 60

# Retries
retry_max_attempts: 3
retry_initial_delay: 1.0
retry_backoff_multiplier: 2.0

# Observability
opensearch_enabled: true
opensearch_use_ssl: true
otel_enabled: true
```

---

## Deployment Process

### Pre-Deployment Checklist

Run the production readiness checker:

```bash
python -m mahavishnu.core.production_readiness_standalone
```

**Minimum Requirements**:
- ✅ Overall score ≥ 70/100
- ✅ Zero failed checks
- ✅ Security audit complete
- ✅ Backups tested
- ✅ Incident response runbook created

### Deployment Steps

#### 1. Backup Current State

```bash
# Create backup timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Backup databases
pg_dump $POSTGRES_URL > backups/mahavishnu_$TIMESTAMP.sql

# Backup configuration
tar -czf backups/config_$TIMESTAMP.tar.gz settings/

# Backup data (if applicable)
tar -czf backups/data_$TIMESTAMP.tar.gz data/
```

#### 2. Deploy New Version

**Cloud Run**:
```bash
gcloud run deploy mahavishnu-mcp \
  --source . \
  --platform managed \
  --region us-central1 \
  --no-traffic \
  --tag new-version
```

**Docker**:
```bash
# Pull new image
docker pull mahavishnu:latest

# Stop old container
docker stop mahavishu-old
docker rm mahavishu-old

# Rename current to old
docker rename mahavishnu mahavishnu-old

# Start new container
docker run -d \
  --name mahavishnu \
  --env-file .env.production \
  -p 8680:8680 \
  mahavishnu:latest
```

**Kubernetes**:
```bash
# Apply new deployment
kubectl apply -f kubernetes/mahavishnu-deployment.yaml

# Rollout status
kubectl rollout status deployment/mahavishnu-mcp
```

#### 3. Verify Deployment

```bash
# Check health endpoint
curl https://mahavishnu-mcp-xxxxx.a.run.app/health

# Check MCP server
curl https://mahavishnu-mcp-xxxxx.a.run.app/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

---

## Smoke Tests

### Health Check Tests

```bash
#!/bin/bash
# smoke_tests.sh

set -e

MAHAVISHNU_URL="${MAHAVISHNU_URL:-http://localhost:8680}"

echo "🔍 Running smoke tests..."

# Test 1: Health endpoint
echo "Test 1: Health endpoint"
curl -f $MAHAVISHNU_URL/health || exit 1
echo "✅ Health check passed"

# Test 2: MCP initialization
echo "Test 2: MCP initialization"
curl -f $MAHAVISHNU_URL/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' || exit 1
echo "✅ MCP initialization passed"

# Test 3: List repositories
echo "Test 3: List repositories"
curl -f $MAHAVISHNU_URL/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_repos","arguments":{}}}' || exit 1
echo "✅ Repository listing passed"

# Test 4: Rate limiting
echo "Test 4: Rate limiting"
for i in {1..5}; do
  curl -s $MAHAVISHNU_URL/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":'$i',"method":"tools/list"} > /dev/null
done
echo "✅ Rate limiting test passed"

echo "🎉 All smoke tests passed!"
```

### Integration Tests

```bash
# Run integration tests against production
pytest tests/integration/ \
  --base-url=$MAHAVISHNU_URL \
  -v \
  --tb=short
```

---

## Monitoring & Validation

### Immediate Monitoring (First 30 minutes)

**Check Metrics**:
```bash
# Request rate
curl http://prometheus:9090/api/v1/query?query=rate(mahavishnu_requests_total[5m])

# Error rate
curl http://prometheus:9090/api/v1/query?query=rate(mahavishnu_errors_total[5m])

# Latency
curl http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,mahavishnu_request_duration_seconds)
```

**Check Logs**:
```bash
# View recent errors
docker logs mahavishnu --since 30m | grep ERROR

# View OpenSearch logs
curl -X GET "$OPENSEARCH_URL/_search" -H 'Content-Type: application/json' -d'
{
  "query": {
    "bool": {
      "must": [
        {"range": {"@timestamp": {"gte": "now-30m"}}},
        {"match": {"level": "ERROR"}}
      ]
    }
  }
}'
```

### 24-Hour Monitoring

**Critical Metrics**:
- Uptime: Should be > 99.9%
- p95 latency: Should be < 1s
- p99 latency: Should be < 2s
- Error rate: Should be < 0.1%
- Memory usage: Should be < 80%
- CPU usage: Should be < 70%

**Alert Thresholds**:
- Error rate > 1%: P1 alert
- Latency > 2s (p95): P2 alert
- Memory > 90%: P2 alert
- CPU > 85%: P3 alert

---

## Rollback Procedures

### When to Rollback

**Immediate Rollback Triggers**:
- Error rate > 5%
- Critical security vulnerability detected
- Data corruption
- Complete service outage

**Consider Rollback**:
- Error rate > 1% for 10 minutes
- Latency degradation > 50%
- Memory leak detected

### Rollback Steps

**Cloud Run**:
```bash
# Rollback to previous version
gcloud run services update-traffic mahavishnu-mcp \
  --to-revisions=REVISION_PREVIOUS \
  --region us-central1
```

**Docker**:
```bash
# Stop new version
docker stop mahavishnu
docker rm mahavishnu

# Start old version
docker start mahavishnu-old
docker rename mahavishnu-old mahavishnu
```

**Kubernetes**:
```bash
# Rollback deployment
kubectl rollout undo deployment/mahavishnu-mcp

# Verify rollback
kubectl rollout status deployment/mahavishnu-mcp
```

### Post-Rollback Validation

```bash
# Run smoke tests
./smoke_tests.sh

# Check error rate
# (should drop to pre-deployment levels)

# Check logs for errors
# (should see normal operation logs)
```

---

## Troubleshooting

### Common Issues

#### 1. High Memory Usage

**Symptoms**: Memory > 90%, OOM kills

**Diagnosis**:
```bash
# Check memory usage
docker stats mahavishnu

# Check for memory leaks
curl http://localhost:8680/debug/memory
```

**Solutions**:
- Reduce `max_concurrent_workflows`
- Increase container memory limit
- Check for connection leaks
- Restart service (temporary fix)

#### 2. High Latency

**Symptoms**: p95 latency > 2s

**Diagnosis**:
```bash
# Check slow queries
curl http://prometheus:9090/api/v1/query?query=topk(10,mahavishnu_slow_queries)

# Check database performance
pg_stat_statements
```

**Solutions**:
- Add database indexes
- Enable query caching
- Increase worker pool size
- Optimize database queries

#### 3. Connection Errors

**Symptoms**: 5xx errors, connection refused

**Diagnosis**:
```bash
# Check service health
curl http://localhost:8680/health

# Check database connectivity
psql $POSTGRES_URL -c "SELECT 1"
```

**Solutions**:
- Verify database connection string
- Check firewall rules
- Increase connection pool size
- Verify DNS resolution

#### 4. Rate Limiting Issues

**Symptoms**: Legitimate requests blocked

**Diagnosis**:
```bash
# Check rate limit stats
curl http://localhost:8680/debug/rate_limits
```

**Solutions**:
- Increase rate limit thresholds
- Add IP exemptions for trusted sources
- Check for distributed rate limiting issues

### Emergency Contacts

**On-Call**: [PHONE NUMBER]
**Engineering Lead**: [EMAIL]
**Infrastructure Lead**: [EMAIL]

### Escalation Path

1. **P1 (Critical)**: Page on-call immediately
2. **P2 (High)**: Page on-call, create ticket
3. **P3 (Medium)**: Create ticket, address in next business day
4. **P4 (Low)**: Create ticket, address in next sprint

---

## Appendix

### Useful Commands

**View Logs**:
```bash
# Real-time logs
docker logs -f mahavishnu

# Last 100 lines
docker logs --tail 100 mahavishnu

# Logs with timestamps
docker logs -t mahavishnu
```

**Restart Services**:
```bash
# Graceful restart
docker exec mahavishnu kill -HUP 1

# Hard restart
docker restart mahavishnu
```

**Check Configuration**:
```bash
# View config
cat settings/mahavishnu.yaml

# Validate config
python -c "from mahavishnu.core.config import MahavishnuSettings; MahavishnuSettings()"
```

### Health Check Endpoint

`GET /health`

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "checks": {
    "database": "ok",
    "opensearch": "ok",
    "adapters": {
      "llamaindex": "healthy",
      "prefect": "disabled",
      "agno": "disabled"
    }
  }
}
```

---

**Last Updated**: 2026-02-02
**Next Review**: 2026-03-02
**Version**: 1.0
