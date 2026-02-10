# Property-Based Testing Implementation Plan

## Overview

This document outlines the implementation of comprehensive property-based tests using Hypothesis for the Mahavishnu project. Property-based testing will catch edge cases that traditional example-based tests might miss by testing invariants (properties that must always be true) rather than specific examples.

## Target Modules

Based on the analysis of the codebase, the following modules are prioritized for property-based testing:

### 1. Configuration System (`mahavishnu/core/config.py`)
- **Priority**: HIGH
- **Complexity**: High (20+ nested Pydantic models)
- **Current Coverage**: Good example-based tests exist
- **Properties to Test**:
  - Config round-trip serialization (dict -> model -> dict)
  - Type coercion and validation invariants
  - Boundary condition handling
  - Default value consistency
  - Nested config model preservation
  - Environment variable precedence

### 2. Path Validation (`mahavishnu/core/validators.py`)
- **Priority**: CRITICAL (Security)
- **Complexity**: Medium
- **Current Coverage**: Basic tests
- **Properties to Test**:
  - Path traversal prevention invariants
  - Absolute path resolution correctness
  - Symbolic link handling security
  - Base directory enforcement
  - TOCTOU race condition prevention

### 3. Learning Models (`mahavishnu/learning/models.py`)
- **Priority**: MEDIUM
- **Complexity**: Medium (Pydantic models with validation)
- **Current Coverage**: Basic tests
- **Properties to Test**:
  - ExecutionRecord field constraint invariants
  - Cost calculation accuracy
  - Embedding content generation consistency
  - Dictionary serialization round-trip
  - UUID handling

### 4. Learning Database (`mahavishnu/learning/database.py`)
- **Priority**: MEDIUM
- **Complexity**: High (SQL queries, async operations)
- **Current Coverage**: Limited
- **Properties to Test**:
  - Query result consistency
  - Batch insertion correctness
  - Connection pool behavior
  - SQL injection prevention
  - Data integrity constraints

### 5. Database Tools (`mahavishnu/mcp/tools/database_tools.py`)
- **Priority**: HIGH (Security)
- **Complexity**: Medium
- **Current Coverage**: Basic tests
- **Properties to Test**:
  - Time range validation whitelist
  - SQL injection prevention
  - Statistics calculation accuracy
  - Result aggregation consistency

## Implementation Strategy

### Phase 1: Infrastructure Setup (Completed)
- ✅ Hypothesis is already installed (version 6.148.13+)
- ✅ `hypothesis.strategies` available
- ✅ `hypothesis.extra.pydantic` available for Pydantic models
- ✅ Property test marker configured in pyproject.toml

### Phase 2: Create Property Test Structure
1. Create `tests/property/` directory
2. Add `__init__.py` with documentation
3. Create separate test files per module:
   - `test_config_properties.py`
   - `test_validators_properties.py`
   - `test_learning_models_properties.py`
   - `test_database_properties.py`
   - `test_database_tools_properties.py`

### Phase 3: Implement Property Tests

#### Config Properties (20+ tests)
```python
# Round-trip serialization
@given(st_pydantic.from_type(PoolConfig))
def test_pool_config_roundtrip(config):
    config_dict = config.model_dump()
    reconstructed = PoolConfig(**config_dict)
    assert reconstructed.model_dump() == config_dict

# Boundary validation
@given(st.floats(min_value=0.0, max_value=400.0))
def test_timeout_rejects_out_of_bounds(timeout):
    assume(not (1.0 <= timeout <= 300.0))
    with pytest.raises(ValidationError):
        CleanupTimeoutConfig(file_operations=timeout)
```

#### Validator Properties (15+ tests)
```python
# Path traversal prevention
@given(st.text())
def test_rejects_directory_traversal(path):
    assume(".." in path)
    with pytest.raises(PathValidationError):
        validate_path(path, allowed_base_dirs=["/safe"])

# Absolute path invariance
@given(st.from_regex(r'^/tmp/test_[a-z]{5,10}$'))
def test_absolute_path_consistency(path):
    result = validate_path(path)
    assert result.is_absolute()
```

#### Learning Model Properties (15+ tests)
```python
# Cost calculation invariants
@given(st.floats(min_value=0.0, max_value=10.0),
       st.floats(min_value=0.0, max_value=10.0))
def test_cost_error_non_negative(estimate, actual):
    record = ExecutionRecord(cost_estimate=estimate, actual_cost=actual, ...)
    error = record.calculate_prediction_error()
    assert error["cost_error_abs"] >= 0

# Round-trip serialization
@given(st_pydantic.from_type(ExecutionRecord))
def test_execution_record_roundtrip(record):
    data = record.to_dict()
    reconstructed = ExecutionRecord.from_dict(data)
    assert reconstructed.task_id == record.task_id
```

#### Database Properties (10+ tests)
```python
# Query result consistency
@given(st.lists(st_pydantic.from_type(ExecutionRecord), min_size=0, max_size=100))
async def test_batch_insertion_preserves_data(executions):
    db = LearningDatabase(":memory:")
    await db.initialize()
    count = await db.store_executions_batch(executions)
    assert count == len(executions)
```

#### Database Tools Properties (10+ tests)
```python
# Time range whitelist
@given(st.text(min_size=1, max_size=10))
def test_time_range_validation(time_range):
    assume(time_range not in ["1h", "24h", "7d", "30d", "90d"])
    with pytest.raises(ValueError):
        validate_time_range(time_range)
```

### Phase 4: Hypothesis Configuration

Add to `pyproject.toml`:
```toml
[tool.hypothesis]
# Generate diverse examples
max_examples = 100
# Allow complex test logic
deadline = None
# Health checks
suppress_health_check = [HealthCheck.too_slow]
# Database for failing examples
database = ".hypothesis/db"
```

### Phase 5: Regression Testing

When Hypothesis finds a bug:
1. Add the failing example to regression test suite
2. Fix the bug
3. Verify the fix with property test
4. Keep regression test for documentation

## Expected Outcomes

### Test Coverage Metrics
- **Total Property Tests**: 70+
- **Examples Generated per Test**: 100-1000
- **Total Test Cases**: 7,000-70,000
- **Execution Time**: 5-10 minutes (parallelized)

### Edge Cases Covered
1. Boundary values (min/max for all numeric fields)
2. Empty/None values for optional fields
3. Unicode and special characters in strings
4. Very long strings (length limits)
5. Invalid data types (type coercion)
6. Directory traversal attempts (security)
7. SQL injection attempts (security)
8. Concurrent operations (race conditions)
9. Resource exhaustion (memory, connections)
10. Invalid state transitions

### Bugs Expected to Find
Based on similar projects, property-based testing typically finds:
- **Boundary bugs**: 2-5 issues with min/max validation
- **Type coercion bugs**: 1-3 issues with automatic type conversion
- **Serialization bugs**: 1-2 issues with round-trip conversion
- **Security bugs**: 0-2 issues with input validation
- **Race conditions**: 0-1 issues with concurrent access

## Running Property-Based Tests

### Run all property tests
```bash
pytest -m property
```

### Run specific module
```bash
pytest tests/property/test_config_properties.py
```

### Run with verbose output
```bash
pytest -m property -v -s
```

### Run with coverage
```bash
pytest -m property --cov=mahavishnu/core/config
```

### Run in parallel (fast)
```bash
pytest -m property -n auto
```

## Maintenance

### Shrinking Failing Examples
When a test fails, Hypothesis will:
1. Display the minimal failing example
2. Save to `.hypothesis/db` for replay
3. Allow reproduction with `@reproduce_failure`

### Adding New Properties
When adding new features:
1. Identify invariants (properties that must always be true)
2. Create property test with appropriate strategies
3. Run with `--hypothesis-seed` for reproducibility
4. Add regression tests for bugs found

### Performance Optimization
- Use `@settings(max_examples=50)` for slow tests
- Use `assume()` to filter invalid examples early
- Use `@st.composite` for complex strategy generation
- Cache expensive operations in fixtures

## Success Criteria

1. ✅ 70+ property tests implemented
2. ✅ All tests passing with 100+ examples each
3. ✅ 0 flaky tests (reproducible results)
4. ✅ Execution time < 10 minutes
5. ✅ Coverage increased by 5-10%
6. ✅ At least 1 bug found and fixed
7. ✅ Documentation complete

## Next Steps

1. Create `tests/property/` directory structure
2. Implement `test_config_properties.py` (20 tests)
3. Implement `test_validators_properties.py` (15 tests)
4. Implement `test_learning_models_properties.py` (15 tests)
5. Implement `test_database_properties.py` (10 tests)
6. Implement `test_database_tools_properties.py` (10 tests)
7. Run full test suite and fix any bugs found
8. Document findings and create regression tests
9. Add to CI/CD pipeline
10. Train team on property-based testing

## Resources

- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [Property-Based Testing with Python](https://www.youtube.com/watch?v=qaQ0NcjH3qU)
- [Testing with Hypothesis](https://hypothesis.works/articles/the-purpose-of-hypothesis/)
- [Strategies for Complex Data](https://hypothesis.readthedocs.io/en/latest/data.html)
