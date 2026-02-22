# Disaster Recovery Runbook

## Overview

This runbook provides step-by-step procedures for recovering from various failure scenarios in the Mahavishnu RAG infrastructure.

## Recovery Time Objectives (RTO) and Recovery Point Objectives (RPO)

| Component | RTO | RPO | Backup Strategy |
|-----------|-----|-----|-----------------|
| PostgreSQL | 15 min | 5 min | Daily backups + WAL archiving |
| Redis | 5 min | 1 min | AOF + RDB snapshots |
| Application | 5 min | N/A | Container orchestration restart |
| Embeddings | 4 hours | 24 hours | Re-compute from source documents |

---

## Scenario 1: PostgreSQL Failure

### Symptoms
- Connection errors to database
- Vector search queries failing
- Application logs showing "connection refused"

### Diagnosis

```bash
# Check PostgreSQL container status
docker-compose ps postgres

# Check PostgreSQL logs
docker-compose logs postgres

# Check if PostgreSQL is accepting connections
docker exec mahavishnu-postgres pg_isready -U mahavishnu
```

### Recovery Steps

#### 1. Automatic Restart (if container crashed)
```bash
# Docker will auto-restart with restart: unless-stopped
docker-compose up -d postgres

# Wait for health check to pass
docker-compose logs -f postgres
```

#### 2. Restore from Backup (if data corrupted)

```bash
# Stop the application to prevent writes
docker-compose stop mahavishnu

# List available backups
ls -la backups/

# Restore from latest backup
docker-compose exec postgres pg_restore -U mahavishnu -d mahavishnu -c backups/latest.dump

# Restart application
docker-compose start mahavishnu
```

#### 3. Failover to Standby (if primary unrecoverable)

```bash
# Promote standby to primary
docker exec mahavishnu-postgres-standby pg_ctl promote

# Update application connection string to point to new primary
# Edit settings/mahavishnu.yaml: postgres_host: postgres-standby

# Restart application
docker-compose restart mahavishnu
```

### Verification

```bash
# Verify database connectivity
docker exec mahavishnu-postgres psql -U mahavishnu -c "SELECT 1"

# Verify pgvector extension
docker exec mahavishnu-postgres psql -U mahavishnu -c "SELECT * FROM pg_extension WHERE extname='vector'"

# Verify embedding count
docker exec mahavishnu-postgres psql -U mahavishnu -c "SELECT COUNT(*) FROM task_embeddings"
```

---

## Scenario 2: Redis Failure

### Symptoms
- Cache misses increasing dramatically
- L2 cache operations timing out
- Higher latency on repeated queries

### Diagnosis

```bash
# Check Redis container status
docker-compose ps redis

# Check Redis logs
docker-compose logs redis

# Test Redis connectivity
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) ping
```

### Recovery Steps

#### 1. Automatic Restart
```bash
# Redis will auto-restart
docker-compose up -d redis

# Verify it started
docker-compose ps redis
```

#### 2. Restore from AOF (if data corrupted)

```bash
# Stop Redis
docker-compose stop redis

# Check AOF file
docker exec mahavishnu-redis redis-check-aof /data/appendonly.aof

# If AOF is corrupted, fix it
docker exec mahavishnu-redis redis-check-aof --fix /data/appendonly.aof

# Start Redis
docker-compose start redis
```

#### 3. If Redis completely lost data

```bash
# L1 cache still works - system continues with degraded performance
# L2 cache will warm up naturally as queries come in

# Optional: Warm cache from PostgreSQL
docker exec mahavishnu-postgres psql -U mahavishnu -t -c "
  SELECT text FROM task_embeddings
  WHERE updated_at > NOW() - INTERVAL '7 days'
  LIMIT 1000
" | while read text; do
  # Trigger embedding generation to warm cache
  curl -X POST http://localhost:8680/api/embed -d "{\"text\": \"$text\"}"
done
```

### Verification

```bash
# Test Redis operations
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) SET test_key "test_value"
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) GET test_key
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) DEL test_key

# Check memory usage
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) INFO memory
```

---

## Scenario 3: Embedding Service Failure

### Symptoms
- "using_mock_embedding" warnings in logs
- Circuit breaker open alerts
- Degraded search quality

### Diagnosis

```bash
# Check circuit breaker status
curl http://localhost:9091/metrics | grep circuit_breaker

# Check embedding latency
curl http://localhost:9091/metrics | grep embedding_latency

# Check Akosha MCP health
curl http://localhost:8682/mcp/health
```

### Recovery Steps

#### 1. Circuit Breaker Recovery

```bash
# Wait for recovery timeout (default 60s)
# Circuit breaker will automatically enter HALF_OPEN state

# Or manually reset (development only)
curl -X POST http://localhost:8680/admin/circuit-breaker/reset
```

#### 2. Akosha MCP Recovery

```bash
# Check if Akosha is running
docker ps | grep akosha

# Restart Akosha if needed
cd /path/to/akosha && docker-compose restart akosha

# Verify health
curl http://localhost:8682/mcp/health
```

#### 3. Fallback Mode

If all embedding sources fail:
- System automatically falls back to mock embeddings
- Search functionality continues but with reduced quality
- Monitor for when sources recover

### Verification

```bash
# Check embedding source distribution
curl http://localhost:9091/metrics | grep embedding_source

# Test embedding generation
curl -X POST http://localhost:8680/api/embed -d '{"text": "test query"}'

# Should return non-mock source if recovered
```

---

## Scenario 4: Complete System Failure

### Symptoms
- All services down
- No response from any endpoint
- Infrastructure completely unavailable

### Recovery Steps

#### 1. Infrastructure Recovery

```bash
# Check Docker daemon
systemctl status docker

# Start Docker if stopped
systemctl start docker

# Pull latest images
docker-compose pull

# Start all services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Wait for health checks
docker-compose ps
```

#### 2. Verify All Services

```bash
# PostgreSQL
docker exec mahavishnu-postgres pg_isready -U mahavishnu

# Redis
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) ping

# Mahavishnu MCP
curl http://localhost:8680/mcp/health

# Akosha MCP
curl http://localhost:8682/mcp/health

# Prometheus metrics
curl http://localhost:9091/metrics
```

#### 3. Data Integrity Check

```bash
# Verify PostgreSQL data
docker exec mahavishnu-postgres psql -U mahavishnu -c "
  SELECT
    COUNT(*) as total_embeddings,
    COUNT(DISTINCT model_version) as model_versions,
    MAX(updated_at) as last_update
  FROM task_embeddings
"

# Verify Redis data
docker exec mahavishnu-redis redis-cli -a $(cat secrets/redis_password.txt) DBSIZE
```

---

## Scenario 5: Data Corruption

### Symptoms
- SQL errors in logs
- Missing or invalid embeddings
- Vector search returning unexpected results

### Diagnosis

```bash
# Check for corrupted embeddings
docker exec mahavishnu-postgres psql -U mahavishnu -c "
  SELECT task_id, array_length(embedding, 1) as dim
  FROM task_embeddings
  WHERE embedding IS NULL OR array_length(embedding, 1) != 384
  LIMIT 10
"

# Check for orphaned records
docker exec mahavishnu-postgres psql -U mahavishnu -c "
  SELECT COUNT(*) FROM task_embeddings e
  LEFT JOIN tasks t ON e.task_id = t.id
  WHERE t.id IS NULL
"
```

### Recovery Steps

#### 1. Fix Invalid Embeddings

```bash
# Delete invalid embeddings
docker exec mahavishnu-postgres psql -U mahavishnu -c "
  DELETE FROM task_embeddings
  WHERE embedding IS NULL OR array_length(embedding, 1) != 384
"

# Re-generate embeddings for affected tasks
# This would be done through the application's re-indexing API
curl -X POST http://localhost:8680/admin/reindex -d '{"batch_size": 100}'
```

#### 2. Restore from Backup

```bash
# If corruption is widespread, restore from backup
docker-compose stop mahavishnu

# Drop and recreate database
docker exec mahavishnu-postgres psql -U mahavishnu -c "DROP DATABASE mahavishnu"
docker exec mahavishnu-postgres psql -U mahavishnu -c "CREATE DATABASE mahavishnu"

# Restore from backup
cat backups/latest.sql | docker exec -i mahavishnu-postgres psql -U mahavishnu

docker-compose start mahavishnu
```

---

## Monitoring and Alerts

### Key Metrics to Monitor During Recovery

| Metric | Normal Range | Alert Threshold |
|--------|-------------|-----------------|
| `pg_stat_activity_count` | < 50 | > 180 (90% of max) |
| `redis_memory_used_bytes` | < 2GB | > 5.7GB (95% of max) |
| `embedding_latency_p95` | < 100ms | > 500ms |
| `cache_hit_ratio` | > 70% | < 50% |
| `vector_search_latency_p95` | < 20ms | > 100ms |
| `circuit_breaker_state` | 0 (closed) | 2 (open) |

### Post-Recovery Checklist

- [ ] All containers running and healthy
- [ ] PostgreSQL accepting connections
- [ ] Redis responding to commands
- [ ] Embedding service generating embeddings
- [ ] Vector search returning results
- [ ] Cache hit rate returning to normal
- [ ] No alerts firing in Prometheus
- [ ] Application logs showing normal operation
- [ ] End-to-end test query successful

---

## Contact Information

| Role | Contact | Escalation Time |
|------|---------|-----------------|
| On-Call Engineer | @oncall in Slack | Immediate |
| Platform Team | platform@example.com | 15 min |
| Database Admin | dba@example.com | 30 min |

---

**Last Updated:** 2026-02-22
**Next Review:** 2026-03-22
