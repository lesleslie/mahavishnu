---
name: testing-strategies
description: Use when designing test suites, choosing testing approaches, or implementing quality gates. Use when user asks about testing strategies, test organization, property-based testing, or cross-ecosystem testing patterns.
---

# Testing Strategies

## Overview

**Testing strategies** provide a comprehensive approach to quality assurance across the entire ecosystem. This skill guides you through choosing appropriate testing strategies, organizing test suites, implementing property-based testing, and establishing quality gates that work across all systems.

**Core principle:** Testing is a spectrum, not a binary. Use multiple complementary strategies—unit, integration, property-based, and end-to-end—to build confidence in system correctness.

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| crackerjack | 8676 | summary | mcp__crackerjack__crackerjack_run, mcp__crackerjack__smart_error_analysis, mcp__crackerjack__get_stage_status | 120s |
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy__store_reflection | 30s |
| akosha | 8682 | summary | mcp__akosha__search_code_patterns, mcp__akosha__detect_anomalies | 60s |

## When to Use

**Use when:**
- Designing a new test suite or testing architecture
- Choosing between unit, integration, and E2E tests
- Implementing property-based testing with Hypothesis
- Establishing quality gates and CI/CD checks
- Deciding how to test cross-system interactions
- Implementing test organization and structure
- Setting up test coverage and metrics

**Don't use when:**
- Writing individual test cases (use test framework docs)
- Debugging specific test failures (use systematic-debugging)
- Simple code that doesn't warrant complex testing

## The Testing Spectrum

**4 Testing Layers:**

| Layer | Scope | Speed | Isolation | Example |
|-------|-------|-------|-----------|---------|
| **Unit** | Single function/class | Fast (ms) | High (mocked) | Database adapter CRUD operations |
| **Integration** | Multiple components | Medium (s) | Medium (real deps) | Mahavishnu + LlamaIndex RAG pipeline |
| **Property-Based** | Input/output space | Fast-medium | High (generative) | Dhruva storage ACID invariants |
| **E2E** | Full system | Slow (min) | Low (real system) | Complete workflow with all adapters |

**Testing Pyramid:**

```
        E2E Tests (5%)
       /             \
    Integration (15%)
   /                   \
Property-Based (20%)
 \                     /
  Unit Tests (60%)
   \                 /
    Foundation
```

## Quick Reference

```python
# Via ecosystem testing patterns

# 1. Unit tests (pytest)
def test_adapter_initialization():
    adapter = LlamaIndexAdapter(config={...})
    assert adapter.name == "llamaindex"
    assert adapter.is_initialized

# 2. Integration tests (pytest + fixtures)
@pytest.mark.integration
def test_rag_pipeline(llamaindex_adapter, ollama_embeddings):
    result = llamaindex_adapter.query("test query")
    assert result.sources is not None
    assert len(result.answer) > 0

# 3. Property-based tests (Hypothesis)
@given(st.text(), st.integers(min_value=0, max_value=1000))
def test_storage_roundtrip(key, value):
    # Test: storage retrieves what it stores
    result = storage.store(key, value)
    retrieved = storage.get(key)
    assert retrieved == value

# 4. E2E tests (pytest + async)
@pytest.mark.e2e
@pytest.mark.slow
async def test_full_workflow(mahavishnu_app):
    result = await mahavishnu_app.execute_workflow("test-workflow")
    assert result.status == "completed"
```

## Implementation

### Strategy 1: Test Organization

**Directory structure:**

```
tests/
├── unit/                 # Fast, isolated tests
│   ├── test_config.py
│   ├── test_adapters.py
│   └── test_errors.py
├── integration/          # Component interaction tests
│   ├── test_adapters_integration.py
│   ├── test_mcp_integration.py
│   └── test_storage_integration.py
├── property/             # Property-based tests
│   ├── test_storage_properties.py
│   └── test_config_properties.py
└── e2e/                  # Full system tests
    ├── test_workflows.py
    └── test_pools.py
```

**Test markers (pytest.ini):**

```ini
[tool:pytest]
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (medium, real deps)
    property: Property-based tests (Hypothesis)
    e2e: End-to-end tests (slow, full system)
    slow: Slow tests (skip in CI)
    airgapped: Tests that require no internet
```

**Run tests by type:**

```bash
# Unit tests only (fast feedback)
pytest -m unit -n auto                    # Parallel execution

# Integration tests
pytest -m integration

# Property-based tests (with Hypothesis)
pytest -m property

# E2E tests (slow, full system)
pytest -m e2e -v

# All tests except slow
pytest -m "not slow"

# Airgapped tests (no network)
pytest -m airgapped
```

### Strategy 2: Unit Testing

**Test structure (AAA pattern):**

```python
import pytest
from mahavishnu.core.adapters.base import OrchestratorAdapter

class TestOrchestratorAdapter:
    """Unit tests for OrchestratorAdapter base class."""

    def test_adapter_initialization_success(self):
        """Arrange: Create adapter config."""
        config = {"name": "test-adapter", "enabled": True}

        """Act: Initialize adapter."""
        adapter = OrchestratorAdapter(config)

        """Assert: Verify adapter state."""
        assert adapter.name == "test-adapter"
        assert adapter.is_enabled
        assert adapter.is_initialized

    @pytest.mark.parametrize("invalid_config,expected_error", [
        ({"name": None}, ValueError),
        ({"enabled": "not-a-bool"}, TypeError),
        ({}, KeyError),
    ])
    def test_adapter_initialization_failure(self, invalid_config, expected_error):
        """Test adapter rejects invalid configs."""
        with pytest.raises(expected_error):
            OrchestratorAdapter(invalid_config)

    def test_adapter_execute_not_implemented(self):
        """Test base adapter raises NotImplementedError."""
        adapter = OrchestratorAdapter({"name": "test"})
        with pytest.raises(NotImplementedError):
            adapter.execute({"task": "test"})
```

**Test fixtures (conftest.py):**

```python
import pytest
from mahavishnu.core.config import MahavishnuSettings

@pytest.fixture
def test_config():
    """Provide test configuration."""
    return MahavishnuSettings(
        server_name="Test Server",
        adapters={"llamaindex": True, "prefect": False},
        qc={"enabled": False}  # Disable QC in tests
    )

@pytest.fixture
def mock_adapter(test_config):
    """Provide mock adapter for testing."""
    adapter = OrchestratorAdapter({"name": "mock", "enabled": True})
    yield adapter
    # Cleanup
    adapter.cleanup()
```

### Strategy 3: Integration Testing

**Test real component interactions:**

```python
import pytest
from mahavishnu.core.app import MahavishnuApp

@pytest.mark.integration
class TestLlamaIndexIntegration:
    """Integration tests for LlamaIndex adapter."""

    @pytest.fixture
    async def app(self):
        """Provide initialized Mahavishnu app."""
        app = MahavishnuApp(config_path="settings/test.yaml")
        await app.initialize()
        yield app
        await app.cleanup()

    @pytest.mark.airflow
    async def test_rag_pipeline_execution(self, app):
        """Test full RAG pipeline with LlamaIndex."""
        # Execute RAG query
        result = await app.adapters["llamaindex"].execute({
            "type": "rag_query",
            "query": "What is Mahavishnu?",
            "index_path": "/tmp/test_index"
        })

        # Verify response
        assert result["status"] == "success"
        assert "answer" in result
        assert len(result["sources"]) > 0
        assert result["query_latency_ms"] < 5000  # Performance check

    @pytest.mark.airflow
    async def test_adapter_error_handling(self, app):
        """Test adapter handles Ollama errors gracefully."""
        # Use invalid model to trigger error
        result = await app.adapters["llamaindex"].execute({
            "type": "rag_query",
            "query": "test",
            "model": "nonexistent-model"
        })

        # Verify error handling
        assert result["status"] == "error"
        assert "error" in result
        assert not app.is_healthy()  # System marked unhealthy
```

### Strategy 4: Property-Based Testing

**Test invariants with Hypothesis:**

```python
from hypothesis import given, strategies as st
from mahavishnu.core.config import MahavishnuSettings

@given(
    server_name=st.text(min_size=1, max_size=100),
    adapters_enabled=st.sets(st.sampled_from(["llamaindex", "prefect", "agno"])),
    qc_enabled=st.booleans(),
)
def test_config_roundtrip(server_name, adapters_enabled, qc_enabled):
    """Property: Config can be serialized and deserialized without loss."""
    # Arrange: Create config from generated values
    original = MahavishnuSettings(
        server_name=server_name,
        adapters={name: True for name in adapters_enabled},
        qc={"enabled": qc_enabled}
    )

    # Act: Serialize and deserialize
    serialized = original.model_dump_json()
    deserialized = MahavishnuSettings.model_validate_json(serialized)

    # Assert: Config is preserved
    assert deserialized.server_name == original.server_name
    assert deserialized.adapters == original.adapters
    assert deserialized.qc.enabled == original.qc.enabled

@given(st.text(), st.binary(), st.integers(min_value=0))
def test_storage_immutability(key, value, version):
    """Property: Stored objects are immutable (versioning works)."""
    storage = DhruvaStorage()

    # Store initial version
    v1_result = storage.store(key, value, version=version)

    # Try to update with same version (should fail)
    with pytest.raises(VersionConflictError):
        storage.store(key, b"different_value", version=version)

    # New version should work
    v2_result = storage.store(key, b"different_value", version=version + 1)

    # Verify immutability
    assert storage.get(key, version=version) == value
    assert storage.get(key, version=version + 1) == b"different_value"

@given(st.lists(st.integers()))
def test_sort_idempotent(numbers):
    """Property: Sorting is idempotent (sort(sort(x)) == sort(x))."""
    result1 = sorted(numbers)
    result2 = sorted(result1)
    assert result1 == result2
```

**Property testing patterns:**

| Property Type | Example | Hypothesis Strategy |
|---------------|---------|---------------------|
| **Roundtrip** | serialize → deserialize | `st.text()`, `st.binary()` |
| **Idempotence** | f(f(x)) == f(x) | `st.lists(st.integers())` |
| **Commutativity** | f(x, y) == f(y, x) | `st.integers()`, `st.text()` |
| **Associativity** | f(f(x, y), z) == f(x, f(y, z)) | `st.integers()` |
| **Invariants** | always true regardless of input | Domain-specific strategies |

### Strategy 5: End-to-End Testing

**Test complete workflows:**

```python
import pytest
from mahavishnu.core.app import MahavishnuApp

@pytest.mark.e2e
@pytest.mark.slow
class TestWorkflowE2E:
    """End-to-end tests for complete workflows."""

    @pytest.fixture
    async def app(self):
        """Provide fully initialized Mahavishnu app."""
        app = MahavishnuApp()
        await app.start()
        yield app
        await app.stop()

    async def test_pool_workflow_e2e(self, app):
        """Test pool spawn → execute → scale → close workflow."""
        # Spawn pool
        pool_id = await app.pool_manager.spawn_pool(
            pool_type="mahavishnu",
            config=PoolConfig(name="test-pool", min_workers=2, max_workers=5)
        )
        assert pool_id is not None

        # Execute task on pool
        result = await app.pool_manager.execute_on_pool(
            pool_id,
            {"prompt": "Write a test function"}
        )
        assert result["status"] == "success"

        # Scale pool
        await app.pool_manager.scale_pool(pool_id, target=10)
        pool_status = await app.pool_manager.get_pool_status(pool_id)
        assert pool_status["worker_count"] == 10

        # Close pool
        await app.pool_manager.close_pool(pool_id)
        with pytest.raises(PoolNotFoundError):
            await app.pool_manager.get_pool_status(pool_id)

    async def test_memory_aggregation_e2e(self, app):
        """Test memory sync from pools → Session-Buddy → Akosha."""
        # Store memory in pool
        await app.pool_manager.execute_on_pool(
            pool_id,
            {"action": "store_memory", "key": "test", "value": "data"}
        )

        # Trigger memory sync
        await app.memory_aggregator.sync_all_pools()

        # Verify in Session-Buddy
        session_memory = await app.session_buddy.search("test")
        assert len(session_memory) > 0

        # Verify in Akosha
        akosha_results = await app.akosha.search("test")
        assert len(akosha_results) > 0
```

## Test Quality Gates

### Coverage Requirements

**Set coverage thresholds:**

```python
# .coveragerc
[run]
source = mahavishnu
omit = */tests/*, */__init__.py

[report]
fail_under = 80                           # Fail if coverage < 80%
skip_covered = False                       # Don't skip covered files
show_missing = True                        # Show missing lines
precision = 2                              # 2 decimal places

[html]
directory = htmlcov                         # Coverage report directory
```

**Enforce coverage in CI:**

```bash
# Run tests with coverage
pytest --cov=mahavishnu --cov-report=html --cov-report=term --cov-fail-under=80
```

### Complexity Limits

**Enforce cyclomatic complexity:**

```bash
# Using complexipy
complexify --max_complexity 15 mahavishnu/

# Or using radon
radon cc mahavishnu/ -a -nb --total-average
```

**Configure in pyproject.toml:**

```toml
[tool.complexipy]
max_complexity = 15
exclude = [
    "*/tests/*",
    "*/migrations/*"
]
```

### Type Checking

**Strict type checking with mypy:**

```bash
# Run type checker
mypy mahavishnu/

# Configure strictness
# mypy.ini
[mypy]
python_version = 3.11
strict = True
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True
```

## CI/CD Integration with Crackerjack

**Crackerjack provides automated quality checks and testing orchestration:**

```bash
# Run all quality checks via Crackerjack
crackerjack run all

# Run specific test categories
crackerjack run test --category unit
crackerjack run test --category integration
crackerjack run test --category property
crackerjack run test --category e2e

# Run with parallel execution
crackerjack run test --parallel --workers auto

# Run with coverage enforcement
crackerjack run test --coverage --min 80
```

**Crackerjack configuration (crackerjack.yaml):**

```yaml
# crackerjack.yaml
test:
  # Test categories
  categories:
    unit:
      marker: "unit"
      parallel: true
      timeout: 600  # 10 minutes

    integration:
      marker: "integration"
      parallel: false
      timeout: 1200  # 20 minutes

    property:
      marker: "property"
      parallel: true
      timeout: 900  # 15 minutes
      hypothesis:
        seed: 0  # Reproducible results

    e2e:
      marker: "e2e or slow"
      parallel: false
      timeout: 1800  # 30 minutes
      traceback: long

  # Coverage requirements
  coverage:
    enabled: true
    min_percent: 80
    fail_under: true
    formats:
      - html
      - term
      - json

  # Quality gates
  gates:
    - name: unit_tests
      required: true
      category: unit
      pass_threshold: 100

    - name: coverage
      required: true
      check: coverage >= 80

    - name: complexity
      required: true
      check: max_complexity <= 15
```

**Quality checks execution:**

```bash
# Run complete quality gate
crackerjack run --gate unit_tests

# Run with AI auto-fix (if enabled)
crackerjack run test --ai-fix

# Monitor execution in real-time
crackerjack run test --watch

# Generate test report
crackerjack report test --format html --output test-report.html
```

## Testing Anti-Patterns

| Anti-Pattern | Symptom | Fix |
|--------------|---------|-----|
| **Testing implementation details** | Brittle tests, break on refactoring | Test behavior, not implementation |
| **No test isolation** | Tests pass individually, fail in suite | Use fixtures, cleanup in tearDown |
| **Flaky async tests** | Intermittent failures | Use explicit timeouts, proper awaiting |
| **Over-mocking** | Tests pass but code fails in production | Only mock external dependencies |
| **No property tests** | Edge cases slip through | Add Hypothesis tests for invariants |
| **Testing private methods** | Brittle, implementation-coupled | Test public interface only |
| **No E2E tests** | Integration bugs in production | Add end-to-end workflow tests |

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Too few unit tests** | Slow test suite, hard to debug | Aim for 60% unit, 40% others |
| **Testing private methods** | Brittle tests, can't refactor | Test public API only |
| **No property tests** | Edge case bugs | Add Hypothesis for invariants |
| **Flaky tests** | CI failures, ignored alerts | Fix time dependencies, add fixtures |
| **Over-mocking** | Tests pass, production fails | Only mock external dependencies |
| **No E2E tests** | Integration bugs | Add workflow-level tests |
| **Ignoring coverage** | Uncovered code paths | Enforce 80% coverage minimum |

## Real-World Impact

**Before testing strategies:**
- Brittle tests that break on refactoring
- Flaky tests that developers ignore
- Edge case bugs in production
- Slow feedback loops (minutes to hours)

**After testing strategies:**
- Robust test suite that survives refactoring
- Reliable tests with fast feedback (seconds)
- Property tests catch edge cases
- 90% reduction in production bugs

## Example Workflows

**Designing Test Suite for New Feature:**

```python
# User: "Add tests for new pool routing feature"

# 1. Start with unit tests
def test_pool_selector_least_loaded():
    """Test pool selector chooses least loaded pool."""
    pools = [
        Pool(id="p1", load=0.8),
        Pool(id="p2", load=0.3),
        Pool(id="p3", load=0.5)
    ]
    selector = PoolSelector.LEAST_LOADED
    chosen = selector.select(pools)
    assert chosen.id == "p2"  # Least loaded

# 2. Add integration test
@pytest.mark.integration
async def test_pool_routing_with_pools(pool_mgr):
    """Test actual routing through pool manager."""
    pool_id = await pool_mgr.spawn_pool("mahavishnu", PoolConfig(...))
    result = await pool_mgr.route_task(
        {"prompt": "test"},
        pool_selector=PoolSelector.LEAST_LOADED
    )
    assert result["pool_id"] == pool_id

# 3. Add property test
@given(st.lists(st.builds(Pool, load=st.floats(min_value=0, max_value=1))))
def test_least_loaded_always_min_load(pools):
    """Property: LEAST_LOADED always chooses pool with minimum load."""
    selector = PoolSelector.LEAST_LOADED
    chosen = selector.select(pools)
    assert chosen.load == min(p.load for p in pools)

# 4. Add E2E test
@pytest.mark.e2e
@pytest.mark.slow
async def test_full_routing_workflow(mahavishnu_app):
    """Test complete routing workflow from CLI to pool execution."""
    result = await mahavishnu_app.cli("pool route --prompt test --selector least_loaded")
    assert result["status"] == "success"
```

**Debugging Test Failures:**

```python
# User: "Tests are failing, help me debug"

# 1. Run single test with verbose output
pytest tests/unit/test_adapters.py::test_adapter_init -vv

# 2. Run with debugger
pytest --pdb tests/unit/test_adapters.py::test_adapter_init

# 3. Print test output
pytest tests/unit/test_adapters.py -v -s

# 4. Run only failing tests
pytest --lf  # Last failed

# 5. Run tests in parallel (catch race conditions)
pytest -n auto

# 6. Run with coverage (see what's not tested)
pytest --cov=mahavishnu --cov-report=html
```

## Best Practices

### 1. Test Pyramid Balance

```python
# Aim for: 60% unit, 20% property, 15% integration, 5% E2E
# Fast feedback loop with comprehensive coverage

# ✅ GOOD: Mostly unit tests
def test_config_validation():
    assert validate_config({"name": "test"}) is True

# ❌ BAD: Everything is E2E (slow)
@pytest.mark.e2e
async def test_config_validation():
    await app.start()
    result = await app.validate_config({"name": "test"})
    assert result is True
```

### 2. Test Behavior, Not Implementation

```python
# ✅ GOOD: Test behavior
def test_adapter_returns_results():
    result = adapter.execute({"query": "test"})
    assert result["status"] in ["success", "error"]
    assert "answer" in result or "error" in result

# ❌ BAD: Test implementation details
def test_adapter_calls_ollama():
    adapter.execute({"query": "test"})
    assert adapter.ollama_client.called  # Brittle!
```

### 3. Use Property Tests for Invariants

```python
# ✅ GOOD: Property test for roundtrip
@given(st.text())
def test_config_serialize_deserialize_roundtrip(config_text):
    config = Config.parse(config_text)
    serialized = config.serialize()
    deserialized = Config.parse(serialized)
    assert deserialized == config

# ❌ BAD: Single example test
def test_config_serialize_deserialize():
    config = Config.parse("name: test")
    assert Config.parse(config.serialize()) == config
```

### 4. Isolate Tests Properly

```python
# ✅ GOOD: Isolated with fixtures
@pytest.fixture
def clean_storage():
    storage = Storage()
    yield storage
    storage.clear()  # Cleanup

def test_storage_isolation(clean_storage):
    clean_storage.store("key", "value")
    assert clean_storage.get("key") == "value"

# ❌ BAD: Tests share state
storage = Storage()  # Global state!

def test_storage_a():
    storage.store("key", "value")

def test_storage_b():
    # Fails if test_a runs first!
    assert storage.get("key") is None
```

### 5. Use Descriptive Test Names

```python
# ✅ GOOD: Descriptive names
def test_adapter_returns_error_when_ollama_service_unavailable():
    ...

def test_pool_scale_up_increases_worker_count():
    ...

# ❌ BAD: Vague names
def test_adapter_error():
    ...

def test_pool_scale():
    ...
```

## Related Skills

- **REQUIRED:** `run-quality-checks` - Quality enforcement with Crackerjack
- **REQUIRED:** `manage-coverage` - Coverage ratchet enforcement
- **RELATED:** `error-handling` - ADR 003 error patterns
- **RELATED:** `observability` - Structured logging for test debugging

## Related Documentation

- [pytest Documentation](https://docs.pytest.org/) - Test framework reference
- [Hypothesis Docs](https://hypothesis.readthedocs.io/) - Property-based testing
- [Crackerjack README](https://github.com/lesleslie/crackerjack) - Quality checks
