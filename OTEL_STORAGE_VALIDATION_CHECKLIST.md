# OTel Storage Setup Validation Checklist

## Configuration Files

- [x] `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml` - Updated with `otel_storage` section
- [x] `/Users/les/Projects/mahavishnu/mahavishnu/core/config.py` - Added 12 OTel storage fields
- [x] `/Users/les/Projects/mahavishnu/pyproject.toml` - Added 3 new dependencies

## Documentation Files

- [x] `/Users/les/Projects/mahavishnu/docs/ONEIRIC_OTEL_STORAGE.md` - Comprehensive documentation (17KB)
- [x] `/Users/les/Projects/mahavishnu/docs/OTEL_STORAGE_QUICKSTART.md` - Quick start guide (6.5KB)
- [x] `/Users/les/Projects/mahavishnu/OTEL_STORAGE_SETUP_PLAN.md` - Implementation plan (6.2KB)
- [x] `/Users/les/Projects/mahavishnu/OTEL_STORAGE_SETUP_SUMMARY.md` - Summary document (8.6KB)

## Scripts and Examples

- [x] `/Users/les/Projects/mahavishnu/scripts/setup_otel_storage.sh` - Database setup script (executable)
- [x] `/Users/les/Projects/mahavishnu/examples/otel_storage_example.py` - Usage examples (10KB)

## Pre-Setup Validation

### Prerequisites Check

- [ ] PostgreSQL 14+ installed
- [ ] pgvector extension installed
- [ ] Python 3.13+ installed
- [ ] Mahavishnu repository accessible

### Dependency Verification

Run these commands to verify prerequisites:

```bash
# Check PostgreSQL
psql --version
# Should output: psql (PostgreSQL) 14.x or higher

# Check pgvector
psql -U postgres -c "SELECT * FROM pg_available_extensions WHERE extname = 'vector'"
# Should return: vector | ... | ...

# Check Python
python --version
# Should output: Python 3.13.x

# Check Mahavishnu config
python -c "from mahavishnu.core.config import MahavishnuSettings; print('OK')"
# Should output: OK
```

## Setup Validation

### Step 1: Database Setup

- [ ] PostgreSQL running at configured host:port
- [ ] Database `otel_traces` created
- [ ] User `otel_user` created with password
- [ ] pgvector extension enabled in database
- [ ] Traces table created with vector column
- [ ] Indexes created (including IVFFlat vector index)

**Validation Commands:**

```bash
# Test connection
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT 1"

# Check extensions
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT extname FROM pg_extension WHERE extname = 'vector'"

# Check tables
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "\dt traces"

# Check indexes
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "\di"
```

### Step 2: Configuration

- [ ] `otel_storage.enabled: true` in settings
- [ ] Connection string correct and accessible
- [ ] Embedding dimension matches model
- [ ] Environment variables set (if using)

**Validation Commands:**

```bash
# Check configuration
python -c "
from mahavishnu.core.config import MahavishnuSettings
s = MahavishnuSettings()
print(f'Enabled: {s.otel_storage_enabled}')
print(f'Connection: {s.otel_storage_connection_string[:30]}...')
print(f'Model: {s.otel_storage_embedding_model}')
print(f'Dimensions: {s.otel_storage_embedding_dimension}')
"
```

### Step 3: Dependencies

- [ ] asyncpg installed
- [ ] pgvector Python package installed
- [ ] sentence-transformers installed
- [ ] All dependencies up to date

**Validation Commands:**

```bash
# Check dependencies
pip list | grep -E "(asyncpg|pgvector|sentence-transformers)"
# Should show all three packages

# Or using uv
uv pip list | grep -E "(asyncpg|pgvector|sentence-transformers)"
```

### Step 4: Adapter Initialization

- [ ] OTelStorageAdapter can be instantiated
- [ ] Connection pool created successfully
- [ ] Health check returns healthy status

**Validation Commands:**

```bash
python -c "
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings
import asyncio

async def test():
    s = MahavishnuSettings()
    settings = OTelStorageSettings(
        connection_string=s.otel_storage_connection_string
    )
    adapter = OTelStorageAdapter(settings)
    health = await adapter.health_check()
    print(f'Healthy: {health[\"healthy\"]}')
    if health['healthy']:
        print('✓ Adapter initialization successful')
    else:
        print(f'✗ Error: {health.get(\"error\")}')
        exit(1)

asyncio.run(test())
"
```

### Step 5: Trace Storage

- [ ] Can store single trace
- [ ] Can store batch of traces
- [ ] Traces appear in database
- [ ] Embeddings generated correctly

**Validation Commands:**

```bash
# Run example storage operations
python -c "
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings
from datetime import datetime, timezone
import asyncio

async def test():
    s = MahavishnuSettings()
    settings = OTelStorageSettings(
        connection_string=s.otel_storage_connection_string
    )
    adapter = OTelStorageAdapter(settings)

    # Store test trace
    await adapter.store_trace(
        trace_id='test-trace-001',
        span_id='test-span-001',
        name='test.operation',
        kind='INTERNAL',
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        status='OK',
        attributes={},
        events=[],
        links=[],
        summary='Test trace for validation'
    )

    # Verify trace exists
    trace = await adapter.get_trace('test-trace-001')
    if trace:
        print('✓ Trace storage successful')
        print(f'  Trace ID: {trace[\"trace_id\"]}')
        print(f'  Name: {trace[\"name\"]}')
    else:
        print('✗ Trace not found after storage')
        exit(1)

asyncio.run(test())
"

# Verify in database
psql "postgresql://postgres:password@localhost:5432/otel_traces" -c "SELECT trace_id, name, summary FROM traces WHERE trace_id = 'test-trace-001'"
```

### Step 6: Semantic Search

- [ ] Can search traces by natural language
- [ ] Results ranked by similarity
- [ ] Similarity scores computed correctly
- [ ] Filtered search works

**Validation Commands:**

```bash
python -c "
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observailability import OTelStorageAdapter, OTelStorageSettings
import asyncio

async def test():
    s = MahavishnuSettings()
    settings = OTelStorageSettings(
        connection_string=s.otel_storage_connection_string,
        similarity_threshold=0.70
    )
    adapter = OTelStorageAdapter(settings)

    # Search for traces
    results = await adapter.search_traces(
        query='test operation validation',
        limit=5
    )

    if results:
        print(f'✓ Semantic search successful')
        print(f'  Found {len(results)} results')
        for i, r in enumerate(results[:3], 1):
            print(f'  {i}. {r[\"name\"]} (similarity: {r[\"similarity\"]:.3f})')
    else:
        print('⚠ No search results (may be expected if database is empty)')

asyncio.run(test())
"
```

### Step 7: Error Handling

- [ ] Invalid connection string raises error
- [ ] Database failures handled gracefully
- [ ] Retry mechanism works
- [ ] Circuit breaker activates

**Validation Commands:**

```bash
# Test invalid connection
python -c "
from oneiric.adapters.observability import OTelStorageSettings
from mahavishnu.core.config import MahavishnuSettings

try:
    # This should fail validation
    settings = OTelStorageSettings(
        connection_string='invalid://connection-string'
    )
    print('✗ Validation should have failed')
    exit(1)
except ValueError as e:
    print('✓ Connection string validation works')
    print(f'  Error: {e}')
"
```

### Step 8: Performance

- [ ] Batch operations faster than single inserts
- [ ] Vector index improves search speed
- [ ] Connection pool reduces overhead
- [ ] Cache improves repeated queries

**Performance Test:**

```bash
python -c "
import time
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings
from datetime import datetime, timezone
import asyncio

async def test():
    s = MahavishnuSettings()
    settings = OTelStorageSettings(
        connection_string=s.otel_storage_connection_string,
        batch_size=100
    )
    adapter = OTelStorageAdapter(settings)

    # Test batch insert performance
    traces = []
    for i in range(100):
        traces.append({
            'trace_id': f'perf-test-{i:04d}',
            'span_id': f'span-{i:04d}',
            'name': f'performance.test.{i}',
            'kind': 'INTERNAL',
            'start_time': datetime.now(timezone.utc),
            'end_time': datetime.now(timezone.utc),
            'status': 'OK',
            'attributes': {'index': i},
            'events': [],
            'links': [],
            'summary': f'Performance test trace {i}'
        })

    start = time.time()
    await adapter.batch_store(traces)
    await adapter.flush()
    duration = time.time() - start

    print(f'✓ Batch insert performance')
    print(f'  Inserted 100 traces in {duration:.2f}s')
    print(f'  Average: {duration/100*1000:.2f}ms per trace')

asyncio.run(test())
"
```

## Post-Setup Validation

### Production Readiness

- [ ] SSL/TLS enabled for database connections
- [ ] Strong passwords configured
- [ ] Connection pooling tuned
- [ ] Backup strategy implemented
- [ ] Monitoring configured
- [ ] Alert thresholds set
- [ ] Documentation reviewed
- [ ] Team trained

### Documentation Review

- [ ] Read full documentation: `docs/ONEIRIC_OTEL_STORAGE.md`
- [ ] Reviewed quick start: `docs/OTEL_STORAGE_QUICKSTART.md`
- [ ] Understood configuration options
- [ ] Reviewed troubleshooting section
- [ ] Understood performance implications

## Success Criteria

All of the following must pass:

1. ✓ Configuration files updated correctly
1. ✓ Documentation complete and accurate
1. ✓ Database schema created successfully
1. ✓ Adapter initializes without errors
1. ✓ Can store and retrieve traces
1. ✓ Semantic search returns relevant results
1. ✓ Error handling works correctly
1. ✓ Performance meets requirements

## Troubleshooting

If any validation step fails:

1. Check PostgreSQL is running: `pg_isready`
1. Verify pgvector extension: `SELECT * FROM pg_extension WHERE extname = 'vector'`
1. Check connection string format: Must start with `postgresql://`
1. Review logs: Check database logs and application logs
1. Consult full documentation: `docs/ONEIRIC_OTEL_STORAGE.md`
1. Review troubleshooting section in docs

## Next Steps After Validation

Once all validation steps pass:

1. Enable in production configuration
1. Set up monitoring and alerts
1. Configure backup strategy
1. Train team on usage
1. Integrate with OpenTelemetry SDK
1. Set up data retention policies
1. Document custom configurations
1. Plan for scaling

## Support

For issues or questions:

- Full documentation: `docs/ONEIRIC_OTEL_STORAGE.md`
- Quick start: `docs/OTEL_STORAGE_QUICKSTART.md`
- Example code: `examples/otel_storage_example.py`
- Setup script: `scripts/setup_otel_storage.sh`
