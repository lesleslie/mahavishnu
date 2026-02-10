# CI/CD Guide for Mahavishnu

This document provides comprehensive guidance on the Continuous Integration and Continuous Deployment (CI/CD) pipelines for the Mahavishnu project.

## Overview

Mahavishnu uses GitHub Actions for CI/CD automation with four primary workflows:

1. **Phase 6 Tests** (`test-phase6.yml`) - Comprehensive testing suite
2. **Build Documentation** (`build-docs.yml`) - Documentation generation and validation
3. **Security Scan** (`security-scan.yml`) - Security vulnerability scanning
4. **Performance Benchmark** (`benchmark.yml`) - Performance regression detection

## Quick Start

### Triggering Workflows

Workflows are automatically triggered on:
- **Push** to `main` or `develop` branches
- **Pull Requests** to `main` or `develop` branches
- **Manual trigger** via workflow dispatch
- **Scheduled runs** (security scans: daily, benchmarks: weekly)

### Manual Workflow Dispatch

You can manually trigger workflows from the GitHub Actions tab:

1. Navigate to **Actions** tab
2. Select the workflow you want to run
3. Click **Run workflow**
4. Select branch and parameters
5. Click **Run workflow**

## Workflows

### 1. Phase 6 Tests (`test-phase6.yml`)

Comprehensive testing suite for Phase 6 deliverables including adapters, E2E framework, and examples.

#### Jobs

**Unit Tests** (matrix: 5 adapters × 3 Python versions)
- Tests individual components in isolation
- Runs on Python 3.11, 3.12, 3.13
- Coverage reporting to Codecov
- Adapters: core, prefect, agno, langgraph, llamaindex

**Integration Tests** (matrix: 4 test suites)
- Tests cross-component interactions
- Suites: adapters, mcp-server, pool-management, phase3-advanced

**Adapter Tests** (matrix: 3 adapters)
- Adapter-specific functionality tests
- Prefect, Agno, LangGraph

**CLI Tests**
- CLI command validation
- Help command testing
- Basic operations testing

**Example Validation** (matrix: 4 categories)
- Syntax validation
- Documentation coverage
- Runner functionality
- Categories: quickstart, workflows, integrations, phase3-advanced

**E2E Framework Tests** (manual trigger only)
- End-to-end workflow validation
- Cross-integration testing
- Triggered manually or with `[e2e]` in commit message

#### Running Locally

```bash
# Unit tests
pytest tests/unit/ -m "unit" --cov=mahavishnu

# Integration tests
pytest tests/integration/ -m "integration"

# Adapter tests
pytest tests/unit/test_adapters/test_prefect*.py -v

# E2E tests
pytest tests/integration/ -m "e2e" --timeout=600
```

#### Test Markers

- `unit` - Fast, isolated unit tests
- `integration` - Integration tests (slower, may use external services)
- `e2e` - End-to-end tests (slowest, full workflow)
- `property` - Property-based tests using Hypothesis
- `ci` - Tests that must pass in CI
- `prefect` - Tests for Prefect adapter
- `agno` - Tests for Agno adapter
- `langgraph` - Tests for LangGraph adapter
- `llamaindex` - Tests for LlamaIndex adapter
- `mcp` - Tests for MCP server functionality

### 2. Build Documentation (`build-docs.yml`)

Documentation generation and validation for all project documentation and examples.

#### Jobs

**Build Documentation**
- Validates markdown links
- Checks README examples
- Builds API documentation with pydocstyle
- Generates documentation coverage with interrogate

**Validate Examples** (matrix: 4 categories)
- Syntax validation for all example files
- Documentation coverage check
- Example runner testing

**Documentation Coverage**
- Interrogate coverage analysis
- Coverage badge generation
- HTML report generation

**Deploy Documentation** (main branch only)
- Creates deployment tags
- Generates deployment summary

#### Running Locally

```bash
# Check markdown links
pip install markdown-link-check
find docs -name "*.md" -exec markdown-link-check {} \;

# Check docstring coverage
pip install interrogate
interrogate mahavishnu/ --fail-under=80

# Validate example syntax
for file in examples/**/*.py; do
    python -m py_compile "$file"
done

# Test example runner
cd examples
python runner.py --list-examples
```

### 3. Security Scan (`security-scan.yml`)

Comprehensive security scanning including dependency vulnerabilities, code security issues, and secret detection.

#### Jobs

**Dependency Vulnerability Scan**
- Safety check for known vulnerabilities
- JSON report generation
- Daily scheduled runs

**Bandit Security Scan**
- Python code security linting
- Common security issues detection
- JSON report generation

**Secret Detection**
- TruffleHog secret scanning
- Verified secrets only
- Credential detection

**Code Quality Checks**
- Ruff linter (replaces black/flake8/isort)
- Ruff formatter check
- JSON report generation

**Type Checking**
- mypy static type checking
- HTML report generation
- Type coverage analysis

**Complexity Analysis**
- Complexipy complexity checking
- Max complexity: 15
- Cyclomatic complexity validation

#### Running Locally

```bash
# Dependency vulnerability scan
safety check

# Bandit security scan
bandit -r mahavishnu/ --exclude tests/

# Ruff linting
ruff check mahavishnu/

# Ruff formatting
ruff format --check mahavishnu/

# Type checking
mypy mahavishnu/

# Complexity check
complexipy --max_complexity 15 mahavishnu/
```

#### Fixing Issues

```bash
# Auto-fix Ruff issues
ruff check mahavishnu/ --fix

# Auto-format with Ruff
ruff format mahavishnu/

# Install missing dependencies
safety check --fix
```

### 4. Performance Benchmark (`benchmark.yml`)

Performance regression detection and benchmarking for all major components.

#### Jobs

**Performance Benchmarks**
- Adapter benchmarks (pytest-benchmark)
- Cache benchmarks
- Pool benchmarks
- JSON report generation

**Load Testing**
- Concurrent operation testing
- Operations per second measurement
- 100 concurrent operations test

**Memory Profiling**
- Memory usage analysis
- Profile generation
- Leak detection

**Integration Health Checks** (matrix: 4 integrations)
- MCP server health
- Pool management health
- Coordination health
- Repository messaging health

**Performance Regression Detection** (PR only)
- Compares PR benchmarks with baseline
- Detects performance regressions
- Alerts on significant changes

#### Running Locally

```bash
# Install pytest-benchmark
pip install pytest-benchmark

# Run benchmarks
pytest tests/unit/test_adapters/ -k "benchmark" --benchmark-only

# Run load test
python -c "
import asyncio
import time
from mahavishnu.core.app import MahavishnuApp

async def load_test():
    app = MahavishnuApp()
    await app.initialize()

    start = time.time()
    tasks = [app.list_repos() for _ in range(100)]
    await asyncio.gather(*tasks)
    duration = time.time() - start

    print(f'100 concurrent operations: {duration:.2f}s')
    print(f'Operations per second: {100/duration:.2f}')

asyncio.run(load_test())
"

# Memory profiling
pip install memory-profiler
python -m memory_profiler examples/quickstart/*.py
```

## Status Badges

Add these badges to your README.md:

```markdown
[![Phase 6 Tests](https://github.com/yourusername/mahavishnu/actions/workflows/test-phase6.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/test-phase6.yml)
[![Build Documentation](https://github.com/yourusername/mahavishnu/actions/workflows/build-docs.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/build-docs.yml)
[![Security Scan](https://github.com/yourusername/mahavishnu/actions/workflows/security-scan.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/security-scan.yml)
[![Performance Benchmark](https://github.com/yourusername/mahavishnu/actions/workflows/benchmark.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/benchmark.yml)
```

## Configuration

### Environment Variables

Workflows use these environment variables:

- `PYTHON_VERSION` - Python version to use (default: '3.13')
- `CI` - Set to 'true' in CI environment
- `CODECOV_TOKEN` - Codecov token for coverage reporting (optional)

### Secrets

Configure these secrets in GitHub repository settings:

- `CODECOV_TOKEN` - Codecov upload token (optional)
- `SLACK_WEBHOOK` - Slack webhook for notifications (optional)

### Caching

Workflows use pip and uv caching for faster runs:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: ${{ env.PYTHON_VERSION }}
    cache: 'pip'
```

## Troubleshooting

### Common Issues

**1. Tests failing in CI but passing locally**

```bash
# Ensure you're using same Python version
python --version  # Should match PYTHON_VERSION in workflow

# Run with same pytest configuration
pytest tests/unit/ -m "unit" --cov=mahavishnu --cov-report=xml

# Check for environment-specific issues
pytest tests/unit/ -m "unit" --tb=long
```

**2. Security scan failures**

```bash
# Run locally to see full report
bandit -r mahavishnu/ --exclude tests/

# Check specific issues
safety check --json

# Fix automatically
ruff check mahavishnu/ --fix
```

**3. Build failures**

```bash
# Check dependencies
uv pip install -e ".[dev,prefect,agno]"

# Validate syntax
python -m py_compile mahavishnu/**/*.py

# Check imports
python -c "from mahavishnu.core.app import MahavishnuApp"
```

### Debug Mode

Enable debug logging in workflows:

```yaml
env:
  DEBUG: "true"
  VERBOSE: "true"
```

### Artifact Downloads

Download workflow artifacts for debugging:

1. Go to workflow run
2. Scroll to **Artifacts** section
3. Download artifact (retention: 7-30 days depending on type)

## Best Practices

### Writing CI-Friendly Tests

1. **Use markers appropriately**

```python
import pytest

@pytest.mark.unit
def test_adapter_initialization():
    """Fast unit test"""
    pass

@pytest.mark.integration
@pytest.mark.prefect
def test_prefect_workflow():
    """Integration test for Prefect adapter"""
    pass

@pytest.mark.slow
@pytest.mark.e2e
def test_full_orchestration_workflow():
    """End-to-end test (marked as slow)"""
    pass
```

2. **Avoid external dependencies in unit tests**

```python
# Good: Mock external dependencies
@pytest.mark.unit
def test_adapter_with_mock(mocker):
    mock_client = mocker.patch('mahavishnu.core.adapters.prefect.PrefectClient')
    # Test logic

# Bad: Real external dependency
@pytest.mark.unit
def test_adapter_with_real_client():
    client = PrefectClient()  # Requires running Prefect server
    # Test logic
```

3. **Use appropriate timeouts**

```python
@pytest.mark.timeout(30)  # 30 seconds
def test_slow_operation():
    pass

@pytest.mark.unit
@pytest.mark.timeout(5)  # 5 seconds for unit tests
def test_fast_operation():
    pass
```

### Performance Optimization

1. **Use matrix strategies wisely** - Don't test every combination
2. **Cache dependencies** - Use pip and uv caching
3. **Run tests in parallel** - Use pytest-xdist: `pytest -n auto`
4. **Fail fast selectively** - Use `fail-fast: false` for matrix jobs

### Security Best Practices

1. **Don't use untrusted input** - See security reminder below
2. **Pin dependencies** - Use exact versions for critical deps
3. **Scan regularly** - Daily security scans catch issues early
4. **Review dependency updates** - Don't auto-merge PRs

## Security Reminder

When editing GitHub Actions workflows:

1. **Never use untrusted input** directly in run: commands
2. **Use environment variables** instead of `${{ github.event.* }}` expressions
3. **Review the security guide**: https://github.blog/security/vulnerability-research/how-to-catch-github-actions-workflow-injections-before-attackers-do/

**Example of UNSAFE pattern to avoid:**
```yaml
run: echo "${{ github.event.issue.title }}"
```

**Example of SAFE pattern:**
```yaml
env:
  TITLE: ${{ github.event.issue.title }}
run: echo "$TITLE"
```

## Monitoring and Notifications

### Workflow Status

Check workflow status at:
- Actions tab: https://github.com/yourusername/mahavishnu/actions
- README badges: Real-time status
- Commit checks: Green checkmark = passing

### Notifications

Set up notifications in GitHub:
1. Settings → Notifications
2. Configure email/Slack/webhook notifications
3. Subscribe to workflow failure notifications

## Continuous Deployment

### Staging Deployment

Manual trigger required:

```yaml
on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        type: choice
        options:
          - staging
          - production
```

### Production Deployment

Requires approval:

```yaml
environment:
  name: production
  url: https://mahavishnu.example.com
```

## Related Documentation

- [Getting Started Guide](GETTING_STARTED.md)
- [Testing Guide](TESTING_GUIDE.md)
- [Security Checklist](../SECURITY_CHECKLIST.md)
- [Production Deployment Guide](PRODUCTION_DEPLOYMENT_GUIDE.md)

## Support

For CI/CD issues:
1. Check workflow logs in Actions tab
2. Review this guide
3. Open an issue with workflow run link
4. Tag with `ci/cd` label

______________________________________________________________________

**Last Updated**: 2026-02-05
**Maintained By**: Mahavishnu DevOps Team
