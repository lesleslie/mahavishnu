# Test Coverage Improvement Plan

## Current State
- **Overall Coverage**: 38.13%
- **Target Coverage**: 80%+
- **Critical Modules**: 20 modules at 0% coverage
- **Medium Coverage**: 15 modules between 20-60%

## Priority Areas

### Phase 1: Critical Infrastructure (0% Coverage)
These modules are foundational and need immediate coverage:

1. **mahavishnu/__main__.py** - Entry point
   - Test CLI argument parsing
   - Test main execution flow
   - Test error handling

2. **mahavishnu/mcp/server.py** - MCP server core
   - Test FastMCP server initialization
   - Test tool registration
   - Test request handling

3. **mahavishnu/terminal/pool.py** - Terminal management
   - Test pool spawning/closing
   - Test session management
   - Test error conditions

4. **Core Repository Modules** ( mahavishnu/core/repositories/ )
   - Test base repository operations
   - Test document storage/retrieval
   - Test embedding operations
   - Test task/run tracking

5. **Adapter Modules** ( mahavishnu/adapters/ )
   - Test adapter initialization
   - Test method delegations
   - Test error handling

### Phase 2: High-Impact Medium Coverage (50-60%)
Focus on modules with existing tests but gaps:

1. **mahavishnu/websocket/server.py** (59.48%)
   - Add tests for WebSocket connections
   - Test broadcasting functionality
   - Test rate limiting integration

2. **mahavishnu/automation/** modules (55-59%)
   - Test automation backends
   - Test security features
   - Test manager operations

3. **mahavishnu/core/worktree_providers/**
   - Test worktree management
   - Test Git integration
   - Test error scenarios

### Phase 3: Integration and Edge Cases
1. **Error handling paths**
2. **Configuration validation**
3. **Performance-critical paths**

## Test Strategy

### Unit Tests (60% of effort)
- Focus on individual components
- Mock external dependencies
- Test happy path and error cases

### Integration Tests (30% of effort)
- Test component interactions
- Use test containers where needed
- Test data flow between modules

### Property-Based Tests (10% of effort)
- Use Hypothesis for complex data structures
- Test edge cases and boundary conditions

## Implementation Plan

### Week 1: Foundation
- [ ] Add tests for __main__.py
- [ ] Add tests for MCP server core
- [ ] Add tests for terminal pool
- [ ] Add tests for repository modules

### Week 2: Adapters and Core
- [ ] Complete adapter module tests
- [ ] Test core configuration modules
- [ ] Add tests for worktree providers

### Week 3: Advanced Features
- [ ] Improve WebSocket tests
- [ ] Test automation modules
- [ ] Add integration tests

### Week 4: Quality and Validation
- [ ] Property-based tests
- [ ] Performance tests
- [ ] Coverage validation

## Testing Best Practices

1. **Arrange-Act-Assert Pattern**
   - Clear test structure
   - Each test has one purpose

2. **Mock External Dependencies**
   - Use unittest.mock
   - Avoid actual network calls in unit tests

3. **Test Data Management**
   - Use factory_boy for complex objects
   - Avoid hardcoded test data

4. **Clear Naming Convention**
   - `test_[feature]_[scenario]`
   - Describe what behavior is being tested

5. **Assertion Quality**
   - Assert on outcomes, not implementation
   - Use specific assertions
   - Include helpful failure messages

## Tools and Frameworks

- **pytest**: Primary testing framework
- **pytest-mock**: Mocking utilities
- **pytest-cov**: Coverage reporting
- **hypothesis**: Property-based testing
- **factory_boy**: Test data factories
- **freezegun**: Time-related testing
- **responses**: HTTP mocking