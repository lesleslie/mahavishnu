# OTel Storage Quick Start Guide

## 5-Minute Setup

### 1. Install PostgreSQL + pgvector (Docker - Recommended)

```bash
docker run -d \
  --name postgres-otel \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=otel_traces \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 2. Run Setup Script

```bash
cd /Users/les/Projects/mahavishnu
./scripts/setup_otel_storage.sh
```

### 3. Enable OTel Storage

Edit `settings/mahavishnu.yaml`:

```yaml
otel_storage:
  enabled: true
  connection_string: "postgresql://postgres:password@localhost:5432/otel_traces"
```

### 4. Update Dependencies

```bash
cd /Users/les/Projects/mahavishnu
uv sync
```

### 5. Test

```bash
python examples/otel_storage_example.py
```

## Configuration Cheat Sheet

### Minimal Configuration

```yaml
otel_storage:
  enabled: true
  connection_string: "postgresql://user:pass@localhost:5432/db"
```

### Production Configuration

```yaml
otel_storage:
  enabled: true
  connection_string: "postgresql://otel_user:secure_password@db.example.com:5432/otel_traces"
  embedding_model: "all-mpnet-base-v2"  # Higher accuracy
  embedding_dimension: 768
  cache_size: 5000
  similarity_threshold: 0.90
  batch_size: 200
  batch_interval_seconds: 10
  max_retries: 5
  circuit_breaker_threshold: 10
```

### Environment Variables

```bash
# Quick enable
export MAHAVISHNU_OTEL_STORAGE__ENABLED=true

# Connection string
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://user:pass@host:5432/db"

# Performance tuning
export MAHAVISHNU_OTEL_STORAGE__BATCH_SIZE=200
export MAHAVISHNU_OTEL_STORAGE__CACHE_SIZE=5000
```

## Common Commands

### Check Database Connection

```bash
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT 1"
```

### Verify pgvector Extension

```bash
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT * FROM pg_extension WHERE extname = 'vector'"
```

### Count Traces

```bash
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT COUNT(*) FROM traces"
```

### Check Index Status

```bash
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "\d traces"
```

## Troubleshooting

### "psql: command not found"

Install PostgreSQL client:

```bash
brew install postgresql   # macOS
sudo apt install postgresql-client  # Ubuntu
```

### "type 'vector' does not exist"

Install pgvector:

```bash
git clone https://github.com/pgvector/pgvector.git
cd pgvector && make && sudo make install
```

Then enable in database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### "vector must have 384 dimensions"

Match embedding dimension to model:

```yaml
otel_storage:
  embedding_model: "all-MiniLM-L6-v2"  # 384 dims
  embedding_dimension: 384  # Must match!
```

### "connection refused"

Check PostgreSQL is running:

```bash
pg_isready -h localhost -p 5432
```

### Docker troubleshooting

```bash
# Check container logs
docker logs postgres-otel

# Restart container
docker restart postgres-otel

# Remove and recreate
docker rm -f postgres-otel
docker run -d --name postgres-otel -p 5432:5432 pgvector/pgvector:pg16
```

## Performance Tuning

### High Throughput (Millions of traces)

```yaml
otel_storage:
  batch_size: 500
  batch_interval_seconds: 15
  cache_size: 10000
```

```sql
-- Recreate index with more lists
DROP INDEX idx_traces_embedding;
CREATE INDEX idx_traces_embedding ON traces USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 1000);
```

### Low Latency (Real-time search)

```yaml
otel_storage:
  batch_size: 50
  batch_interval_seconds: 1
  cache_size: 2000
```

### Memory Optimization

```yaml
otel_storage:
  cache_size: 500  # Reduce memory usage
  batch_size: 50   # Smaller batches
```

## Testing

### Unit Tests

```bash
pytest tests/unit/test_otel_storage.py -v
```

### Integration Tests

```bash
pytest tests/integration/test_otel_storage.py -v -m integration
```

### Manual Test

```python
python -c "
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings
import asyncio

async def test():
    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string
    )
    adapter = OTelStorageAdapter(otel_settings)
    health = await adapter.health_check()
    print(f'Healthy: {health[\"healthy\"]}')

asyncio.run(test())
"
```

## Migration from Other Systems

### From Jaeger

1. Export traces from Jaeger API
1. Convert to OTel format
1. Import using `adapter.batch_store()`

### From Tempo

1. Query Tempo API
1. Convert trace format
1. Import using `adapter.store_trace()`

## Monitoring

### Key Metrics

- Database connection pool size
- Average query time
- Trace storage rate
- Search latency
- Cache hit rate

### Health Checks

```python
health = await adapter.health_check()
print(f"Healthy: {health['healthy']}")
print(f"Total traces: {health['total_traces']}")
print(f"Cache size: {health['cache_size']}")
```

### Statistics

```python
stats = await adapter.get_statistics()
print(f"Total traces: {stats['total_traces']}")
print(f"Average duration: {stats['avg_duration_ms']}ms")
```

## Security Best Practices

1. **Use environment variables** for sensitive credentials
1. **Restrict network access** to PostgreSQL
1. **Use SSL connections** in production
1. **Regular backups** with pg_dump
1. **Rotate credentials** periodically
1. **Monitor access logs** for suspicious activity

## Backup and Recovery

### Backup

```bash
pg_dump "postgresql://postgres:password@localhost:5432/otel_traces" > otel_backup.sql
```

### Restore

```bash
psql "postgresql://postgres:password@localhost:5432/otel_traces" < otel_backup.sql
```

## Next Steps

1. Read full documentation: `docs/ONEIRIC_OTEL_STORAGE.md`
1. Review implementation plan: `OTEL_STORAGE_SETUP_PLAN.md`
1. Run examples: `examples/otel_storage_example.py`
1. Configure OpenTelemetry SDK integration
1. Set up monitoring and alerts
1. Implement backup strategy

## Support

- Full documentation: `docs/ONEIRIC_OTEL_STORAGE.md`
- Troubleshooting section in docs
- Example code: `examples/otel_storage_example.py`
- Setup script: `scripts/setup_otel_storage.sh`

## Quick Reference

| Task | Command |
|------|---------|
| Install | `./scripts/setup_otel_storage.sh` |
| Enable | Edit `settings/mahavishnu.yaml` |
| Test | `python examples/otel_storage_example.py` |
| Health check | `adapter.health_check()` |
| Search | `adapter.search_traces("query")` |
| Store | `adapter.store_trace(...)` |
| Backup | `pg_dump ... > backup.sql` |
| Restore | `psql ... < backup.sql` |
