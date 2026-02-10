# Property-Based Testing Quick Reference

## What is Property-Based Testing?

Traditional testing checks if specific inputs produce expected outputs:

```python
def test_pool_config():
    config = PoolConfig(min_workers=2, max_workers=5)
    assert config.min_workers == 2
    assert config.max_workers == 5
```

Property-based testing checks if **invariants** (properties that must ALWAYS be true) hold for THOUSANDS of randomly generated inputs:

```python
@given(st.integers(min_value=1, max_value=10),
       st.integers(min_value=10, max_value=100))
def test_min_workers_le_max_workers(min_workers, max_workers):
    """Property: min_workers should always be <= max_workers"""
    assume(min_workers <= max_workers)
    config = PoolConfig(min_workers=min_workers, max_workers=max_workers)
    assert config.min_workers <= config.max_workers
```

## Key Concepts

### 1. Properties (Invariants)

A property is something that must ALWAYS be true:

- ✅ Round-trip: `serialize(deserialize(x)) == x`
- ✅ Idempotence: `f(f(x)) == f(x)`
- ✅ Commutativity: `f(x, y) == f(y, x)`
- ✅ Boundary: `0 <= percentage <= 100`
- ✅ Security: `validate("../../../etc/passwd")` raises error

### 2. Strategies (Generators)

Hypothesis strategies generate test data:

```python
# Basic strategies
st.integers(min_value=0, max_value=100)
st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
st.text(min_size=1, max_size=50, alphabet="abc")
st.booleans()
st.sampled_from(["small", "medium", "large"])
st.lists(st.integers(), min_size=0, max_size=10)
st.dictionaries(st.text(), st.integers())

# Complex strategies
st_pydantic.from_type(PoolConfig)  # Auto-generate Pydantic models
st.from_regex(r'^[a-z]+$')  # Regex-based
st.builds(MyClass)  # Build objects
st.composite(...)  # Custom composite strategies

# Filtering
st.integers().filter(lambda x: x > 0)  # or use assume()
```

### 3. The @given Decorator

```python
from hypothesis import given, settings, assume

@given(st.integers(), st.integers())
def test_addition_commutative(a, b):
    """Test that a + b == b + a for all integers"""
    assert a + b == b + a

@given(st.text())
@settings(max_examples=100)  # Custom settings
def test_string_operations(s):
    assume(len(s) > 0)  # Filter invalid examples
    assert s == s[::-1][::-1]  # Reverse twice = original
```

## Common Patterns

### Pattern 1: Round-Trip Serialization

```python
@given(st_pydantic.from_type(PoolConfig))
def test_roundtrip_serialization(config):
    """Property: serialize -> deserialize preserves data"""
    # Serialize to dict
    data = config.model_dump()

    # Deserialize back
    reconstructed = PoolConfig(**data)

    # Should be identical
    assert reconstructed.model_dump() == data
```

### Pattern 2: Boundary Validation

```python
@given(st.floats(min_value=0.0, max_value=500.0))
def test_timeout_upper_bound(timeout):
    """Property: timeouts should reject values > 300.0"""
    assume(timeout > 300.0)  # Only test invalid values

    with pytest.raises(ValidationError):
        CleanupTimeoutConfig(file_operations=timeout)
```

### Pattern 3: Security Invariants

```python
@given(st.text())
def test_path_traversal_prevention(path):
    """Property: paths with '..' are always rejected"""
    assume(".." in path)  # Only test dangerous paths

    with pytest.raises(PathValidationError):
        validate_path(path, allowed_base_dirs=["/safe"])
```

### Pattern 4: Mathematical Properties

```python
@given(st.floats(min_value=0.0, max_value=100.0),
       st.floats(min_value=0.0, max_value=100.0))
def test_cost_error_non_negative(estimate, actual):
    """Property: cost error should always be non-negative"""
    error = abs(actual - estimate)
    assert error >= 0.0
```

### Pattern 5: Idempotence

```python
@given(st.text())
def test_sanitization_idempotent(filename):
    """Property: sanitizing twice should give same result"""
    result1 = sanitize_filename(filename)
    result2 = sanitize_filename(result1)
    assert result1 == result2
```

## Hypothesis Settings

### Common Settings

```python
from hypothesis import settings
from hypothesis.strategies import composite

# Increase examples for more testing
@settings(max_examples=1000)

# Disable deadline for slow tests
@settings(deadline=None)

# Suppress specific health checks
from hypothesis import HealthCheck
@settings(suppress_health_check=[HealthCheck.too_slow])

# Custom deadline (milliseconds)
@settings(deadline=500)  # 500ms timeout per test

# Print all examples (debugging)
from hypothesis import Verbosity
@settings(verbosity=Verbosity.verbose)

# Reproduce specific failure
from hypothesis import reproduce_failure
@reproduce_failure('6.148.13', b'AA...')
@given(st.text())
def test_specific_failure(text):
    assert len(text) <= 10
```

## Working with Pydantic Models

### Auto-Generate Models

```python
from hypothesis.extra import pydantic as st_pydantic

@given(st_pydantic.from_type(PoolConfig))
def test_pool_config_properties(config):
    """Hypothesis auto-generates valid PoolConfig instances"""
    assert isinstance(config, PoolConfig)
    assert 1 <= config.min_workers <= 10
    assert 1 <= config.max_workers <= 100
    assert config.min_workers <= config.max_workers
```

### Generate Partial Models

```python
from hypothesis.strategies import builds

@given(builds(PoolConfig, enabled=st.just(True)))
def test_partial_pool_config(config):
    """Generate PoolConfig with enabled=True always"""
    assert config.enabled is True
```

## Debugging Failures

### Shrinking

Hypothesis automatically shrinks failing examples to minimal cases:

```
Falsifying example:
test_addition(
    a=0,
    b=0,
)
Shrunk from original:
test_addition(
    a=999999,
    b=123456,
)
```

### Reproducing Failures

```python
# Hypothesis provides a decorator for exact reproduction
@reproduce_failure('6.148.13', b'AA...')
@given(st.text())
def test_reproduce(text):
    assert len(text) <= 2
```

### Verbosity Levels

```python
from hypothesis import Verbosity

@settings(verbosity=Verbosity.verbose)  # Print all examples
@given(st.integers())
def test_verbose(x):
    assert x >= 0
```

## Best Practices

### 1. Use `assume()` to Filter

```python
# BAD: Test slow for invalid inputs
@given(st.integers())
def test_positive_only(x):
    if x < 0:
        return
    assert x >= 0

# GOOD: Filter early
@given(st.integers())
def test_positive_only(x):
    assume(x >= 0)
    assert x >= 0
```

### 2. Test Invariants, Not Implementation

```python
# BAD: Tests specific implementation
@given(st.integers())
def test_sort_implementation(arr):
    result = sort(arr)
    assert result == sorted(arr)  # Just duplicates sorted()

# GOOD: Tests sorting invariants
@given(st.lists(st.integers()))
def test_sort_invariants(arr):
    result = sorted(arr)
    assert result == sorted(result)  # Idempotent
    assert result[0] <= result[-1] if result else True  # Min <= Max
```

### 3. Use Custom Strategies for Complex Data

```python
from hypothesis.strategies import composite

@composite
def valid_timeout(draw):
    """Generate valid timeout between 1.0 and 300.0"""
    return draw(st.floats(min_value=1.0, max_value=300.0, allow_nan=False))

@given(valid_timeout())
def test_timeout_bounds(timeout):
    """Test with valid timeout strategy"""
    config = CleanupTimeoutConfig(file_operations=timeout)
    assert 1.0 <= config.file_operations <= 300.0
```

### 4. Test Security Properties

```python
@given(st.text())
def test_sql_injection_prevention(query):
    """Property: SQL injection attempts should be rejected"""
    assume(any(pattern in query.lower() for pattern in ["drop", "delete", "truncate"]))
    with pytest.raises(ValueError):
        execute_query(query)
```

### 5. Test Round-Trip Consistency

```python
@given(st_pydantic.from_type(ExecutionRecord))
def test_serialization_roundtrip(record):
    """Property: serialize -> deserialize should preserve data"""
    # To dict
    data = record.to_dict()

    # From dict
    reconstructed = ExecutionRecord.from_dict(data)

    # All fields should match
    assert reconstructed.task_id == record.task_id
    assert reconstructed.timestamp == record.timestamp
    assert reconstructed.model_dump() == record.model_dump()
```

## Running Property Tests

### Basic Commands

```bash
# Run all property tests
pytest -m property

# Run specific file
pytest tests/property/test_config_properties.py

# Run with verbose output
pytest -m property -v -s

# Run specific test
pytest tests/property/test_config_properties.py::test_pool_config_roundtrip -v

# Run with coverage
pytest -m property --cov=mahavishnu/core/config

# Run in parallel (faster)
pytest -m property -n auto

# Run with Hypothesis settings
pytest -m property --hypothesis-seed=1234  # Reproducible random seed
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml
- name: Run property tests
  run: |
    pytest -m property -v --hypothesis-seed=1234
```

## Common Pitfalls

### 1. Too Many Assumptions

```python
# BAD: Filters out most examples
@given(st.integers())
def test_bad(x):
    assume(x > 0)
    assume(x < 10)
    assume(x % 2 == 0)
    assert x in [2, 4, 6, 8]

# GOOD: Use more specific strategy
@given(st.integers(min_value=1, max_value=9).filter(lambda x: x % 2 == 0))
def test_good(x):
    assert x in [2, 4, 6, 8]
```

### 2. Testing Implementation Details

```python
# BAD: Tests internal state
@given(st.integers())
def test_internal_state(x):
    obj = MyClass(x)
    assert obj._internal_value == x

# GOOD: Tests observable behavior
@given(st.integers())
def test_behavior(x):
    obj = MyClass(x)
    assert obj.get_value() == x
```

### 3. Ignoring Flaky Tests

```python
# BAD: Retry on failure
@given(st.integers())
def test_flaky(x):
    try:
        assert expensive_computation(x) > 0
    except:
        pass  # Ignore failures

# GOOD: Fix the test or the code
@given(st.integers())
@settings(deadline=None)  # Give enough time
def test_deterministic(x):
    result = expensive_computation(x)
    assert result > 0
```

## Resources

- [Hypothesis Docs](https://hypothesis.readthedocs.io/)
- [Quick Start Guide](https://hypothesis.readthedocs.io/en/latest/quickstart.html)
- [Strategies Reference](https://hypothesis.readthedocs.io/en/latest/data.html)
- [Pydantic Integration](https://hypothesis.readthedocs.io/en/latest/numpy.html#pydantic)
- [Stateful Testing](https://hypothesis.readthedocs.io/en/latest/stateful.html)

## Summary

Property-based testing with Hypothesis:

- ✅ Tests thousands of examples automatically
- ✅ Finds edge cases you'd never think of
- ✅ Provides shrinkable, reproducible failures
- ✅ Tests invariants, not just examples
- ✅ Catches security vulnerabilities
- ✅ Improves code quality significantly

**Key Takeaway**: Property-based testing tests WHAT the code should do (invariants), not HOW it does it (implementation details).
