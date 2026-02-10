# Test Configuration Strategy

## Overview

Mahavishnu uses a **layered test configuration strategy** that separates test environments from production, ensuring tests run reliably without requiring external services.

## Configuration Layers (Priority Order)

1. **Defaults** (Pydantic model defaults)
2. **`settings/test.yaml`** (committed, test-specific defaults)
3. **`settings/local.yaml`** (gitignored, local overrides)
4. **Environment Variables** (`MAHAVISHNU_*`)

## Test Environments

### Unit Tests (`tests/unit/`)

**Purpose:** Fast, isolated tests of individual components

**Configuration:**
- Uses `settings/test.yaml` (no external services)
- Authentication: **DISABLED**
- Adapters: **ALL DISABLED** (Prefect, LlamaIndex, Agno)
- Databases: **Mock/In-memory**
- Runtime: **~1-2 minutes**

**Run:**
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific unit test file
pytest tests/unit/test_health.py -v

# Run with coverage
pytest tests/unit/ --cov=mahavishnu --cov-report=html
```

### Integration Tests (`tests/integration/`)

**Purpose:** Test interactions between components and external services

**Configuration:**
- Requires external services (see below)
- Uses `settings/test.yaml` as base
- May require service-specific credentials
- Runtime: **~5-10 minutes**

**External Services Required:**

| Service | Purpose | Test Files | Environment Variables |
|---------|---------|------------|----------------------|
| **Prefect Server** | Workflow orchestration | `test_prefect_*.py` | `PREFECT_API_URL` |
| **Grafana** | Metrics/dashboard integration | `test_predictive_quality.py` | `GRAFANA_URL`, `GRAFANA_API_KEY` |
| **PostgreSQL + pgvector** | Vector storage for OTel traces | `test_*.py` (otel_storage tests) | `DATABASE_URL` |
| **OpenSearch** | Observability backend | `test_opensearch_integration.py` | `OPENSEARCH_URL` |
| **Redis** | Caching/session storage | `test_session_buddy_integration.py` | `REDIS_URL` |
| **Ollama** | Embedding model for RAG | `test_llamaindex_*.py` | `OLLAMA_BASE_URL` |
| **Oneiric MCP** | Config/resolver integration | `test_oneiric_*.py` | `ONEIRIC_MCP_URL` |
| **Session-Buddy** | Session tracking | `test_session_buddy_integration.py` | `SESSION_BUDDY_URL` |
| **Mahavishnu MCP** | MCP server tools | `test_mcp_tools_integration.py` | `MAHAVISHNU_MCP_URL` |
| **Crackerjack** | Quality control | `test_crackerjack_integration.py` | `CRACKERJACK_URL` |

**Run:**
```bash
# Run all integration tests (services must be available)
pytest tests/integration/ -v

# Run only tests that don't require external services
pytest tests/integration/ -v -m "not requires_network"

# Skip tests that require Grafana
pytest tests/integration/ -v -m "not requires_grafana"

# Run only Prefect integration tests
pytest tests/integration/ -v -m "prefect"
```

### Property Tests (`tests/property/`)

**Purpose:** Property-based testing with Hypothesis

**Configuration:**
- Uses `settings/test.yaml`
- Hypothesis strategies for config values
- Runtime: **~2-5 minutes**

**Run:**
```bash
# Run all property tests
pytest tests/property/ -v

# Run with custom Hypothesis settings
pytest tests/property/ -v --hypothesis-seed=0
```

### Performance Tests (`tests/performance/`)

**Purpose:** Benchmark and performance regression tests

**Configuration:**
- Uses `settings/test.yaml`
- May require larger datasets
- Runtime: **~10-20 minutes**

**Run:**
```bash
# Run performance tests
pytest tests/performance/ -v

# Run with pytest-benchmark
pytest tests/performance/ -v --benchmark-only
```

## External Services Setup Guide

### Quick Start: Docker Compose

For local development, use the provided `docker-compose.test.yml` to start all required services:

```bash
# Start all test services
docker-compose -f docker-compose.test.yml up -d

# Run integration tests
pytest tests/integration/ -v

# Stop services when done
docker-compose -f docker-compose.test.yml down
```

### Individual Service Setup

#### 1. Prefect Server

```bash
# Install Prefect
pip install prefect

# Start Prefect server
prefect server start

# Set environment variable
export PREFECT_API_URL="http://localhost:4200/api"
```

#### 2. PostgreSQL + pgvector

```bash
# Using Docker
docker run -d \
  --name mahavishnu-postgres \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=mahavishnu_test \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Set environment variable
export DATABASE_URL="postgresql://postgres:test@localhost:5432/mahavishnu_test"

# Enable pgvector extension
docker exec -it mahavishnu-postgres psql -U postgres -d mahavishnu_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### 3. Grafana

```bash
# Using Docker
docker run -d \
  --name mahavishnu-grafana \
  -p 3000:3000 \
  grafana/grafana:latest

# Access at http://localhost:3000
# Default credentials: admin/admin

# Set environment variables
export GRAFANA_URL="http://localhost:3000"
export GRAFANA_API_KEY="your-api-key"
```

#### 4. OpenSearch

```bash
# Using Docker
docker run -d \
  --name mahavishnu-opensearch \
  -p 9200:9200 \
  -p 9600:9600 \
  -e "discovery.type=single-node" \
  -e "DISABLE_SECURITY_PLUGIN=true" \
  opensearchproject/opensearch:latest

# Set environment variable
export OPENSEARCH_URL="http://localhost:9200"
```

#### 5. Redis

```bash
# Using Docker
docker run -d \
  --name mahavishnu-redis \
  -p 6379:6379 \
  redis:latest

# Set environment variable
export REDIS_URL="redis://localhost:6379"
```

#### 6. Ollama (for RAG/embeddings)

```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Start Ollama
ollama serve

# Pull embedding model
ollama pull nomic-embed-text

# Set environment variable (already set in test.yaml)
export OLLAMA_BASE_URL="http://localhost:11434"
```

#### 7. Oneiric MCP

```bash
# Install Oneiric
pip install oneiric

# Start Oneiric MCP server
oneiric mcp start

# Set environment variable (if not default)
export ONEIRIC_MCP_URL="http://localhost:8680/mcp"
```

#### 8. Session-Buddy

```bash
# Install Session-Buddy
pip install session-buddy

# Start Session-Buddy MCP server
session-buddy mcp start

# Set environment variable (if not default)
export SESSION_BUDDY_URL="http://localhost:8678/mcp"
```

#### 9. Mahavishnu MCP

```bash
# Start Mahavishnu MCP server
mahavishnu mcp start

# Set environment variable (if not default)
export MAHAVISHNU_MCP_URL="http://localhost:8680/mcp"
```

#### 10. Crackerjack

```bash
# Install Crackerjack
pip install crackerjack

# Start Crackerjack MCP server
crackerjack mcp start

# Set environment variable (if not default)
export CRACKERJACK_URL="http://localhost:8676/mcp"
```

## Test Markers

Tests are marked to allow selective running:

| Marker | Description | Usage |
|--------|-------------|-------|
| `unit` | Fast, isolated tests | `pytest -m unit` |
| `integration` | Slower, may use external services | `pytest -m integration` |
| `property` | Hypothesis property tests | `pytest -m property` |
| `performance` | Benchmark tests | `pytest -m performance` |
| `slow` | Marked as slow (skip with `-m 'not slow'`) | `pytest -m "not slow"` |
| `requires_network` | Requires network access | `pytest -m "not requires_network"` |
| `requires_auth` | Requires authentication | Use `mock_auth_secret` fixture |
| `requires_prefect` | Requires Prefect server | `pytest -m "not requires_prefect"` |
| `requires_grafana` | Requires Grafana instance | `pytest -m "not requires_grafana"` |
| `requires_postgres` | Requires PostgreSQL | `pytest -m "not requires_postgres"` |
| `requires_redis` | Requires Redis | `pytest -m "not requires_redis"` |
| `requires_opensearch` | Requires OpenSearch | `pytest -m "not requires_opensearch"` |
| `ci` | Tests that must pass in CI | `pytest -m ci` |

## CI/CD Configuration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run unit tests
        run: |
          pytest tests/unit/ -v --cov=mahavishnu --cov-report=xml

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: mahavishnu_test
        ports:
          - 5432:5432
      redis:
        image: redis:latest
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run integration tests
        run: |
          export DATABASE_URL="postgresql://postgres:test@localhost:5432/mahavishnu_test"
          export REDIS_URL="redis://localhost:6379"
          pytest tests/integration/ -v -m "not requires_grafana and not requires_prefect"
```

## Best Practices

### 1. Always Mock External Services in Unit Tests

```python
# GOOD: Mock external service
def test_unit_with_mock(mocker):
    mock_service = mocker.patch('mahavishnu.clients.external.Service')
    mock_service.return_value = MockResponse()
    result = function_under_test()
    assert result == expected

# BAD: Real external service in unit test
def test_unit_real_service():
    result = function_under_test()  # Makes real HTTP call
    assert result == expected
```

### 2. Use Fixtures for Common Test Setup

```python
@pytest.fixture
def mock_config(monkeypatch):
    """Provide mock configuration for tests."""
    monkeypatch.setenv("MAHAVISHNU_AUTH__ENABLED", "false")
    monkeypatch.setenv("MAHAVISHNU_ENV", "test")
    return {"auth": {"enabled": False}}
```

### 3. Mark Tests Appropriately

```python
@pytest.mark.integration
@pytest.mark.requires_postgres
def test_database_integration():
    """Integration test requiring PostgreSQL."""
    # Test code here
    pass
```

### 4. Use pytest-xdist for Parallel Execution

```bash
# Run tests in parallel (auto-detect CPU count)
pytest tests/ -n auto

# Run with specific number of workers
pytest tests/ -n 4
```

### 5. Separate Test Suites

```bash
# Run fast unit tests only (CI gate)
pytest tests/unit/ -v -m "not slow" --cov=mahavishnu --cov-fail-under=80

# Run full test suite locally
pytest tests/ -v

# Run integration tests only
pytest tests/integration/ -v
```

## Troubleshooting

### Tests Failing with Auth Errors

**Problem:** `AttributeError: 'MahavishnuApp' object has no attribute 'auth'`

**Solution:** The test environment is not being loaded. Check:
1. `settings/test.yaml` exists
2. `MAHAVISHNU_ENV=test` is set (done automatically in `tests/conftest.py`)
3. `auth.enabled: false` in test.yaml

### Integration Tests Failing with Connection Errors

**Problem:** Tests failing to connect to external services

**Solution:** Either:
1. Start the required service (see External Services Setup)
2. Skip tests requiring that service: `pytest -m "not requires_service_name"`

### Coverage Too Low

**Problem:** Coverage below 80% threshold

**Solution:** Add more unit tests for uncovered modules:
```bash
# Generate coverage report
pytest tests/unit/ --cov=mahavishnu --cov-report=html

# Open report
open htmlcov/index.html

# Identify modules needing tests
# Add tests for modules with < 80% coverage
```

### Tests Timing Out

**Problem:** Tests timing out after 5 minutes

**Solution:**
1. Increase timeout for specific tests:
   ```python
   @pytest.mark.timeout(600)  # 10 minutes
   def test_slow_operation():
       pass
   ```
2. Mark slow tests appropriately:
   ```python
   @pytest.mark.slow
   def test_heavy_computation():
       pass
   ```
3. Skip slow tests in CI: `pytest -m "not slow"`

## Summary

- **Unit tests:** Fast, isolated, no external services (use `settings/test.yaml`)
- **Integration tests:** Require external services (skip if not available)
- **Property tests:** Hypothesis-based, use `settings/test.yaml`
- **Performance tests:** Benchmarks, may require larger datasets

**Key Configuration Files:**
- `settings/test.yaml` - Test configuration (this file)
- `settings/mahavishnu.yaml` - Production configuration
- `settings/local.yaml` - Local overrides (gitignored)

**Environment Variables:**
- `MAHAVISHNU_ENV=test` - Auto-set by `tests/conftest.py`
- `MAHAVISHNU_AUTH__ENABLED=false` - Auto-set by `tests/conftest.py`
- Service-specific URLs for integration tests (see above)
