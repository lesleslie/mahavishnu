# Production Integration Tests

This directory contains production-ready integration tests for WebSocket deployment across the 7-service Bodhisattva ecosystem.

## Test Categories

### 1. Authentication Tests (`TestJWTAuthentication`)
- Valid token authentication
- Expired token rejection
- Invalid token rejection
- Permission-based access control
- Token refresh functionality

### 2. TLS/WSS Tests (`TestTLSConnections`)
- WSS connections with valid certificates
- Certificate validation
- TLS cipher suite verification
- Certificate expiry checking

### 3. Service Lifecycle Tests (`TestServiceLifecycle`)
- Service start/stop
- Graceful shutdown
- Multiple concurrent connections
- Connection tracking

### 4. Cross-Service Communication Tests (`TestCrossServiceCommunication`)
- Service-to-service authenticated communication
- Cross-service subscriptions
- Permission-based routing

### 5. Graceful Degradation Tests (`TestGracefulDegradation`)
- Connection failure handling
- Server restart scenarios
- Partial connection failures
- Service recovery

### 6. Performance Tests (`TestPerformance`)
- 100+ concurrent connections
- Broadcast performance
- Message throughput
- Latency under load

### 7. Upgrade Scenarios (`TestUpgradeScenarios`)
- Clean deployment
- Data preservation across restarts
- Migration testing

## Running Tests

### Quick Start
```bash
# Run all production tests (except slow)
pytest tests/production/ -v -m "production"

# Run with coverage
pytest tests/production/ -v -m "production" --cov=mahavishnu --cov-report=html
```

### Specific Test Categories
```bash
# Authentication tests only
pytest tests/production/test_websocket_deployment.py::TestJWTAuthentication -v

# TLS tests only
pytest tests/production/test_websocket_deployment.py::TestTLSConnections -v

# Performance tests (slow)
pytest tests/production/test_websocket_deployment.py::TestPerformance -v --runslow
```

### With Docker
```bash
# Build test container
docker build -t websocket-tests -f Dockerfile.test .

# Run tests
docker run --rm websocket-tests pytest tests/production/ -v
```

## Test Requirements

```bash
# Install dependencies
pip install pytest pytest-asyncio pytest-cov pytest-timeout
pip install websockets cryptography aiohttp
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TEST_JWT_SECRET` | JWT secret for authentication tests | Auto-generated |
| `TEST_CERT_PATH` | Path to TLS certificate file | Auto-generated |
| `TEST_KEY_PATH` | Path to TLS private key file | Auto-generated |

## CI/CD Integration

Tests are automatically run on:
- Push to `main` or `develop` branches
- Pull requests targeting `main` or `develop`
- Manual trigger via workflow_dispatch

### Manual Workflow Trigger
```bash
# Trigger via GitHub CLI
gh workflow run websocket-production-tests.yml \
  -f run_slow_tests=true
```

## Test Markers

- `@pytest.mark.production`: Production readiness tests
- `@pytest.mark.slow`: Performance/load tests (require --runslow)
- `@pytest.mark.asyncio`: Async test (auto-applied)

## Success Criteria

All tests must pass:
- 100% of non-slow tests pass
- >= 95% of slow tests pass
- No security vulnerabilities detected
- Coverage >= 90%

## Troubleshooting

### Port already in use
```bash
# Kill existing WebSocket processes
lsof -ti:8690 | xargs kill -9
```

### Certificate errors
```bash
# Regenerate test certificates
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /tmp/key.pem \
  -out /tmp/cert.pem \
  -days 1 \
  -subj "/CN=localhost"
```

### Timeout errors
```bash
# Increase timeout
pytest tests/production/ -v --timeout=600
```

## Contributing

When adding new tests:
1. Use appropriate test markers (`@pytest.mark.production`)
2. Follow async/await patterns
3. Clean up resources in fixtures
4. Add docstrings explaining test scenarios
5. Update this README with new test categories

## References

- [WebSocket Deployment Guide](/docs/WEBSOCKET_DEPLOYMENT.md)
- [MCP Tools Specification](/docs/MCP_TOOLS_SPECIFICATION.md)
- [Production Deployment Guide](/docs/PRODUCTION_DEPLOYMENT_GUIDE.md)
