# Test Coverage Improvement Plan

## Current Coverage Baseline

Based on the coverage report, here's the current state for core modules:

| Module | Coverage | Missing Lines | Priority |
|--------|----------|---------------|----------|
| `mahavishnu/core/validators.py` | 57.28% | 44 lines | HIGH |
| `mahavishnu/core/auth.py` | 32.88% | 49 lines | HIGH |
| `mahavishnu/core/permissions.py` | 34.92% | 82 lines | HIGH |
| `mahavishnu/core/backup_recovery.py` | 0.00% | 279 lines | CRITICAL |
| `mahavishnu/core/booster.py` | 0.00% | 155 lines | MEDIUM |
| `mahavishnu/core/defaults.py` | 0.00% | 65 lines | LOW |
| `mahavishnu/pools/mahavishnu_pool.py` | 17.14% | 87 lines | HIGH |
| `mahavishnu/pools/manager.py` | 87.75% | 25 lines | LOW |
| `mahavishnu/core/ecosystem.py` | 41.99% | 105 lines | MEDIUM |
| `mahavishnu/core/model_router.py` | 32.54% | 114 lines | MEDIUM |

**Overall Core Coverage: 39.91%**

## Target Coverage Goals

- **Core modules**: 80%+ coverage (from 40%)
- **Critical security modules**: 90%+ coverage (validators, auth, permissions)
- **Zero-coverage modules**: 70%+ minimum coverage

## Implementation Strategy

### Phase 1: Critical Security Tests (HIGH PRIORITY)
1. **validators.py** - Add comprehensive path validation tests
2. **auth.py** - Add JWT authentication flow tests
3. **permissions.py** - Add RBAC tests

### Phase 2: Zero-Coverage Modules (CRITICAL)
1. **backup_recovery.py** - Add backup/restore workflow tests
2. **booster.py** - Add performance booster tests
3. **defaults.py** - Add defaults loading tests

### Phase 3: Pool Enhancement (HIGH PRIORITY)
1. **mahavishnu_pool.py** - Add pool lifecycle tests
2. **manager.py** - Add missing coverage for edge cases

### Phase 4: Additional Core Modules (MEDIUM)
1. **ecosystem.py** - Add ecosystem management tests
2. **model_router.py** - Add routing telemetry tests

## Test Types to Add

### 1. Unit Tests
- Edge cases (empty inputs, None values, boundary conditions)
- Error handling (exceptions, validation failures)
- Security scenarios (path traversal, injection attempts)
- State transitions (initialization, shutdown, error recovery)

### 2. Integration Tests
- End-to-end workflows (backup creation → restore)
- Multi-component interactions (auth → permissions → operations)
- Error propagation across boundaries

### 3. Property-Based Tests
- Use Hypothesis for property testing
- Test invariants (e.g., validated paths never escape base dirs)
- Test properties (e.g., backup always contains checksum)

## Success Criteria

- ✅ Core modules coverage: 80%+
- ✅ Security modules coverage: 90%+
- ✅ All new tests passing
- ✅ No regressions in existing tests
- ✅ Property-based tests for critical functions

## Testing Infrastructure

### Fixtures to Create
```python
# tests/fixtures.py
- mock_app() - Mock MahavishnuApp instance
- mock_config() - Mock configuration
- temp_directory() - Temporary directory for file tests
- mock_terminal_manager() - Mock terminal manager
- mock_worker_manager() - Mock worker manager
```

### Test Utilities
```python
# tests/utils.py
- assert_path_security() - Assert path validation security
- assert_backup_integrity() - Assert backup file integrity
- assert_auth_validity() - Assert JWT token validity
```

## Execution Plan

1. **Week 1**: Phase 1 (Security tests)
2. **Week 2**: Phase 2 (Zero-coverage modules)
3. **Week 3**: Phase 3 (Pool enhancement)
4. **Week 4**: Phase 4 (Additional modules) + Property-based tests

## Tracking

Track progress with coverage reports after each phase:

```bash
pytest tests/unit/test_core/ --cov=mahavishnu/core --cov-report=term-missing
```
