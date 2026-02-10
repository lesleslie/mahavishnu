# Phase 2 Test Quick Reference Guide

Quick commands for running Phase 2 CLI and MCP tools tests.

## Test Files Created

1. **`tests/unit/test_mcp/test_pool_tools.py`** (50+ tests)
   - Pool spawn, list, execute, route, scale, health, close
   - Swarm coordination tools
   - Pool monitoring and memory search

2. **`tests/unit/test_mcp/test_session_buddy_tools.py`** (50+ tests)
   - Code graph indexing
   - Function context retrieval
   - Related code finding
   - Documentation indexing and search
   - Project messaging

3. **`tests/unit/test_cli/test_mcp_commands.py`** (24+ tests)
   - MCP start/status/health/stop commands
   - Terminal management integration
   - Authentication modes

## Running Tests

### Run All Phase 2 Tests
```bash
# Run all new Phase 2 tests
pytest tests/unit/test_mcp/test_pool_tools.py \
       tests/unit/test_mcp/test_session_buddy_tools.py \
       tests/unit/test_cli/test_mcp_commands.py \
       -v

# Expected: 124+ tests passing
```

### Run Individual Test Files

#### Pool Tools Tests
```bash
# Run with verbose output
pytest tests/unit/test_mcp/test_pool_tools.py -v

# Run with coverage
pytest tests/unit/test_mcp/test_pool_tools.py \
    --cov=mahavishnu/mcp/tools/pool_tools \
    --cov-report=term-missing \
    --cov-report=html

# Run specific test class
pytest tests/unit/test_mcp/test_pool_tools.py::TestPoolSpawnTool -v

# Run specific test
pytest tests/unit/test_mcp/test_pool_tools.py::TestPoolSpawnTool::test_pool_spawn_mahavishnu -v
```

#### Session Buddy Tools Tests
```bash
# Run with verbose output
pytest tests/unit/test_mcp/test_session_buddy_tools.py -v

# Run with coverage
pytest tests/unit/test_mcp/test_session_buddy_tools.py \
    --cov=mahavishnu/mcp/tools/session_buddy_tools \
    --cov-report=term-missing \
    --cov-report=html

# Run specific test category
pytest tests/unit/test_mcp/test_session_buddy_tools.py::TestIndexCodeGraph -v
```

#### MCP CLI Commands Tests
```bash
# Run with verbose output
pytest tests/unit/test_cli/test_mcp_commands.py -v

# Run with coverage
pytest tests/unit/test_cli/test_mcp_commands.py \
    --cov=mahavishnu/cli \
    --cov-report=term-missing \
    --cov-report=html

# Run specific test class
pytest tests/unit/test_cli/test_mcp_commands.py::TestMCPStartCommands -v
```

### Run by Test Category

#### Pool Spawn Tests
```bash
pytest tests/unit/test_mcp/test_pool_tools.py::TestPoolSpawnTool -v
```

#### Pool Execute Tests
```bash
pytest tests/unit/test_mcp/test_pool_tools.py::TestPoolExecuteTool -v
```

#### Swarm Coordination Tests
```bash
pytest tests/unit/test_mcp/test_pool_tools.py::TestSwarmTools -v
```

#### Code Graph Tests
```bash
pytest tests/unit/test_mcp/test_session_buddy_tools.py::TestIndexCodeGraph -v
```

#### Documentation Search Tests
```bash
pytest tests/unit/test_mcp/test_session_buddy_tools.py::TestSearchDocumentation -v
```

#### MCP Start Tests
```bash
pytest tests/unit/test_cli/test_mcp_commands.py::TestMCPStartCommands -v
```

### Run with Markers

```bash
# Run all unit tests
pytest tests/unit/ -m unit -v

# Run all MCP tests
pytest tests/unit/ -m mcp -v

# Run all async tests
pytest tests/unit/ -k "async" -v
```

## Coverage Commands

### Check Coverage for New Tests
```bash
# Pool tools coverage
pytest tests/unit/test_mcp/test_pool_tools.py \
    --cov=mahavishnu/mcp/tools/pool_tools \
    --cov-report=term-missing \
    --cov-fail-under=75

# Session Buddy tools coverage
pytest tests/unit/test_mcp/test_session_buddy_tools.py \
    --cov=mahavishnu/mcp/tools/session_buddy_tools \
    --cov-report=term-missing \
    --cov-fail-under=70

# MCP CLI coverage
pytest tests/unit/test_cli/test_mcp_commands.py \
    --cov=mahavishnu/cli \
    --cov-report=term-missing \
    --cov-fail-under=70
```

### Generate HTML Coverage Reports
```bash
# Generate HTML report for all Phase 2 tests
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py \
    --cov=mahavishnu \
    --cov-report=html \
    --cov-context=test

# Open the report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Generate XML Coverage Report (for CI/CD)
```bash
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py \
    --cov=mahavishnu \
    --cov-report=xml \
    --cov-report=term
```

## Debugging Failed Tests

### Run with Detailed Output
```bash
# Show full output (including print statements)
pytest tests/unit/test_mcp/test_pool_tools.py -v -s

# Show local variables on failure
pytest tests/unit/test_mcp/test_pool_tools.py -v -l

# Show extra tracebacks
pytest tests/unit/test_mcp/test_pool_tools.py -v --tb=long
```

### Run Specific Failed Test
```bash
# Run last failed tests
pytest tests/unit/test_mcp/test_pool_tools.py --lf -v

# Run first failed test and stop
pytest tests/unit/test_mcp/test_pool_tools.py -x -v
```

### Debug with pdb
```bash
# Drop into debugger on failure
pytest tests/unit/test_mcp/test_pool_tools.py -v --pdb

# Drop into debugger on error
pytest tests/unit/test_mcp/test_pool_tools.py -v --pdb --trace
```

## Parallel Execution

### Run Tests in Parallel
```bash
# Auto-detect CPU count and run in parallel
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py -n auto

# Specify number of workers
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py -n 4

# Distribute tests by file (load balancing)
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py -n auto --dist loadfile
```

## Performance Testing

### Measure Test Execution Time
```bash
# Show slowest tests
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py --durations=10

# Profile tests
pytest tests/unit/test_mcp/ tests/unit/test_cli/test_mcp_commands.py --profile
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Phase 2 Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run Phase 2 tests
        run: |
          pytest tests/unit/test_mcp/ \
                 tests/unit/test_cli/test_mcp_commands.py \
                 --cov=mahavishnu \
                 --cov-report=xml \
                 --cov-fail-under=60
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
```

## Test Coverage Goals

| Module | Target | Status |
|--------|--------|--------|
| Pool Tools | 75% | ✅ Target set |
| Session Buddy Tools | 70% | ✅ Target set |
| MCP CLI Commands | 70% | ✅ Target set |
| Overall Project | 60% | ✅ Threshold configured |

## Common Issues & Solutions

### Import Errors
```bash
# Ensure package is installed in editable mode
pip install -e ".[dev]"

# Verify imports
python -c "from mahavishnu.mcp.tools.pool_tools import register_pool_tools"
```

### Async Test Errors
```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio>=1.3.0

# Verify asyncio mode
pytest --co -q  # Should show asyncio_mode = auto
```

### Coverage Not Detected
```bash
# Remove stale coverage data
coverage erase

# Re-run tests
pytest tests/unit/test_mcp/test_pool_tools.py --cov=mahavishnu/mcp/tools/pool_tools
```

## Summary

- **Total new tests**: 124+
- **Test files**: 3
- **Lines of test code**: 3,400+
- **Coverage targets**: 70-75%
- **Execution time**: ~2-3 minutes (parallel)

## Next Steps

1. Run all Phase 2 tests to verify they pass
2. Check coverage meets targets
3. Review any failing tests
4. Proceed to Phase 3 (Configuration & Production Validation)

---

**For detailed documentation, see**: `PHASE2_CLI_MCP_TESTS_COMPLETE.md`
