# Property-Based Testing Quick Start Guide

## Overview

This guide provides quick reference for running and maintaining the 116+ property-based tests implemented with Hypothesis for the Mahavishnu project.

## Prerequisites

Hypothesis is already installed in the development environment:

```bash
# Verify installation
pip show hypothesis

# Should show: hypothesis>=6.148.13
```

## Running Tests

### Basic Commands

```bash
# Run all property tests
pytest tests/property/ -v

# Run specific test file
pytest tests/property/test_validators_properties.py -v

# Run specific test class
pytest tests/property/test_validators_properties.py::TestDirectoryTraversalPrevention -v

# Run specific test
pytest tests/property/test_validators_properties.py::TestDirectoryTraversalPrevention::test_rejects_dot_dot_sequences -v
```

### With Coverage

```bash
# Run with HTML coverage report
pytest tests/property/ --cov=mahavishnu --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Parallel Execution

```bash
# Run all tests in parallel (faster)
pytest tests/property/ -n auto

# Run with specific number of workers
pytest tests/property/ -n 4

# Run tests in parallel with coverage
pytest tests/property/ -n auto --cov=mahavishnu --cov-report=html
```

### Hypothesis-Specific Options

```bash
# Increase examples for more thorough testing (default: 100)
pytest tests/property/ -v --hypothesis-max-examples=200

# Set random seed for reproducibility
pytest tests/property/ -v --hypothesis-seed=12345

# Show Hypothesis output (useful for debugging)
pytest tests/property/ -v -s

# Generate examples (don't run tests)
pytest tests/property/ --hypothesis-generate-seeds=10
```

### Timeouts and Performance

```bash
# Set timeout for individual tests (10 minutes)
pytest tests/property/ --timeout=600

# Show slowest tests
pytest tests/property/ --durations=10

# Profile test execution
pytest tests/property/ --profile
```

## Test Files

| File | Tests | Description |
|------|-------|-------------|
| `test_config_properties.py` | 20+ | Configuration validation |
| `test_validators_properties.py` | 30 | Security validation |
| `test_learning_models_properties.py` | 25 | Data model invariants |
| `test_database_properties.py` | 19 | Database operations |
| `test_database_tools_properties.py` | 22 | Database tools |

## Understanding Test Output

### Passing Test

```
test_validators_properties.py::TestDirectoryTraversalPrevention::test_rejects_dot_dot_sequences PASSED
```

### Failing Test (Example)

```
Falsifying example:
test_validators_properties.py::TestDirectoryTraversalPrevention::test_rejects_dot_dot_sequences

state = <Hypothesis state>
input = '../../../etc/passwd'

# Hypothesis found this input breaks the test
```

### What To Do When Test Fails

1. **Copy the failing example** from the output
1. **Create a regression test** with that example
1. **Fix the bug** in the code
1. **Verify the fix** with both tests
1. **Run full suite** to ensure no regressions

## Common Issues

### Issue: Tests Are Slow

**Solution:** Run in parallel or reduce examples

```bash
# Parallel execution
pytest tests/property/ -n auto

# Reduce examples for faster testing
pytest tests/property/ --hypothesis-max-examples=50
```

### Issue: Test Times Out

**Solution:** Increase timeout or reduce test complexity

```bash
# Increase timeout to 10 minutes
pytest tests/property/ --timeout=600

# Or skip slow tests
pytest tests/property/ -m "not slow"
```

### Issue: Flaky Test

**Solution:** Use Hypothesis seed for reproducibility

```bash
# Run with fixed seed
pytest tests/property/ --hypothesis-seed=12345

# Report the seed in bug report
```

### Issue: Database Tests Fail

**Solution:** Ensure DuckDB is installed

```bash
# Check DuckDB installation
python -c "import duckdb; print(duckdb.__version__)"

# Reinstall if needed
pip install duckdb
```

## Writing New Property Tests

### Template

```python
from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

@given(st.text(min_size=1, max_size=100))
@settings(max_examples=100)
def test_property(input_data):
    """
    Test that property holds for all inputs.

    Property: [Describe what must always be true]
    """
    # Arrange
    # Act
    result = function_under_test(input_data)

    # Assert
    assert invariant_holds(result)
```

### Common Strategies

```python
# Text generation
st.text(min_size=1, max_size=100, alphabet='abc')

# Integers in range
st.integers(min_value=0, max_value=100)

# Floats in range
st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Lists
st.lists(st.integers(), min_size=0, max_size=10)

# One of a set
st.sampled_from(['a', 'b', 'c'])

# Dictionaries
st.dictionaries(st.text(), st.integers())

# Pydantic models
from hypothesis.extra import pydantic as st_pydantic
st_pydantic.from_type(MyModel)
```

## Best Practices

1. **Start Small:** Begin with simple properties
1. **Use assume():** Filter invalid inputs early
1. **Set Deadlines:** Use `@settings(deadline=None)` for slow tests
1. **Document Invariants:** Explain what property is being tested
1. **Independent Tests:** Each test should verify one property
1. **Reproducible Seeds:** Use seeds for debugging failures

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Property Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run property tests
        run: |
          pytest tests/property/ -v -n auto --cov=mahavishnu
```

### GitLab CI Example

```yaml
property-tests:
  script:
    - pip install -e ".[dev]"
    - pytest tests/property/ -v -n auto --cov=mahavishnu
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

## Resources

- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [Property-Based Testing with Python](https://www.youtube.com/watch?v=qaQ0NcjH3qU)
- [Testing with Hypothesis](https://hypothesis.works/articles/the-purpose-of-hypothesis/)
- [Strategies for Complex Data](https://hypothesis.readthedocs.io/en/latest/data.html)

## Getting Help

### Debugging Failed Tests

```python
# Add this to see what Hypothesis is trying
@given(st.text())
@settings(max_examples=100, verbosity=Verbosity.verbose)
def test_with_verbose_output(text):
    # ...
```

### Contact

- Test Automation Agent: Run `/test-automator` command
- Review Implementation Plan: `tests/property/IMPLEMENTATION_PLAN.md`
- Full Summary: `tests/property/PROPERTY_TEST_SUMMARY.md`

## Summary

- **116+ tests** across 5 modules
- **50-200 examples** per test (configurable)
- **5,800-23,200+ total test cases**
- **5-10 minute execution** (parallelized)
- **Ready to run** immediately

Start testing now with:

```bash
pytest tests/property/ -v
```
