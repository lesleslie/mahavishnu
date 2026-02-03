# Adapter Test Suite Documentation

## Overview

This test suite provides comprehensive coverage for all three Mahavishnu orchestration adapters:

- **AgnoAdapter**: Agent-based orchestration with LLM integration (Claude, GPT, Ollama)
- **PrefectAdapter**: Flow-based orchestration with workflow management
- **LlamaIndexAdapter**: RAG pipelines with vector embeddings and OpenTelemetry instrumentation

## Test Coverage Summary

### AgnoAdapter Tests (`test_agno_adapter.py`)

**Total Tests**: 40+

#### Initialization Tests (3 tests)

- Adapter initialization with configuration
- Adapter initialization with defaults
- Configuration validation

#### LLM Configuration Tests (4 tests)

- Ollama LLM configuration
- Anthropic LLM with API key validation
- OpenAI LLM with API key validation
- Unsupported provider error handling

#### Agent Creation Tests (2 tests)

- Agent creation for code sweep
- Mock agent fallback when Agno unavailable

#### Code Graph Integration Tests (3 tests)

- File reading tool functionality
- File reading error handling
- Code search tool functionality

#### Execution Tests - Code Sweep (3 tests)

- Single repository code sweep
- Multiple repository code sweep
- Analysis details inclusion

#### Execution Tests - Quality Check (1 test)

- Quality check execution

#### Execution Tests - Default Operations (1 test)

- Unknown/ default operation handling

#### Error Handling Tests (2 tests)

- Individual repo failure handling
- Exception handling in repo processing

#### Retry Logic Tests (1 test)

- Transient failure retry with tenacity

#### Timeout Tests (1 test)

- Task timeout handling

#### Health Check Tests (3 tests)

- Healthy status check
- Health check includes details
- Health check error handling

#### Agent Response Tests (3 tests)

- Code quality response generation
- Quality check response generation
- Default response generation

#### Integration Tests (2 tests)

- Full execution workflow
- Concurrent execution across multiple repos

#### Edge Case Tests (3 tests)

- Empty repository list
- Missing task ID
- Missing task type

### PrefectAdapter Tests (`test_prefect_adapter.py`)

**Total Tests**: 35+

#### Initialization Tests (2 tests)

- Adapter initialization with config
- Adapter initialization with None config

#### Task Processing Tests (5 tests)

- Code sweep processing
- Complexity analysis
- Quality check processing
- Default operation handling
- Error handling in processing

#### Flow Tests (3 tests)

- Single repository flow
- Multiple repository flow
- Concurrent execution

#### Adapter Execute Tests (5 tests)

- Code sweep execution
- Multiple repository execution
- Partial failure handling
- Flow failure handling
- Exception handling

#### Retry Logic Tests (1 test)

- Transient failure retry

#### Health Check Tests (3 tests)

- Healthy status check
- Prefect-specific details
- Exception handling

#### Flow Run Tracking Tests (2 tests)

- Flow run ID tracking
- Flow run URL generation

#### Edge Case Tests (2 tests)

- Empty repository list
- Missing task ID

#### Integration Tests (1 test)

- Full Prefect workflow

### LlamaIndexAdapter Tests (`test_llamaindex_adapter.py`)

**Total Tests**: 40+

#### Initialization Tests (3 tests)

- Adapter initialization with config
- Initialization fails when LlamaIndex unavailable
- Initialization with telemetry enabled

#### OpenTelemetry Tests (2 tests)

- Fallback instrumentation
- Query text truncation

#### Document Ingestion Tests (5 tests)

- Successful repository ingestion
- Nonexistent path handling
- No documents found handling
- Code graph enrichment
- Custom file type filtering

#### Query Tests (4 tests)

- Successful index query
- Missing query text error
- Index not found error
- Auto-discovery of index by repo name

#### Execute Tests (5 tests)

- Ingest task execution
- Query task execution
- Ingest and query combined task
- Unknown task type handling
- Multiple repository execution

#### Document Context Tests (1 test)

- Context extraction from code graph

#### Health Check Tests (4 tests)

- Healthy status check
- Index information in health
- Telemetry status in health
- Exception handling

#### Retry Logic Tests (1 test)

- Transient failure retry

#### Edge Case Tests (2 tests)

- Empty repository list
- Missing task ID

#### Integration Tests (1 test)

- Full RAG workflow

## Running the Tests

### Run All Adapter Tests

```bash
pytest tests/unit/test_adapters/ -v
```

### Run Specific Adapter Tests

```bash
# Agno adapter only
pytest tests/unit/test_adapters/test_agno_adapter.py -v

# Prefect adapter only
pytest tests/unit/test_adapters/test_prefect_adapter.py -v

# LlamaIndex adapter only
pytest tests/unit/test_adapters/test_llamaindex_adapter.py -v
```

### Run with Coverage

```bash
pytest tests/unit/test_adapters/ \
  --cov=mahavishnu.engines.agno_adapter \
  --cov=mahavishnu.engines.prefect_adapter \
  --cov=mahavishnu.engines.llamaindex_adapter \
  --cov-report=html \
  --cov-report=term
```

### Run Specific Test Categories

```bash
# Run only initialization tests
pytest tests/unit/test_adapters/ -k "initialization" -v

# Run only execution tests
pytest tests/unit/test_adapters/ -k "execute" -v

# Run only error handling tests
pytest tests/unit/test_adapters/ -k "error" -v

# Run only health check tests
pytest tests/unit/test_adapters/ -k "health" -v

# Run only integration tests
pytest tests/unit/test_adapters/ -k "integration" -v

# Run only edge case tests
pytest tests/unit/test_adapters/ -k "edge" -v
```

## Test Organization

### Test Structure

Each test file follows a consistent structure:

1. **Imports and Fixtures**: All necessary imports and shared test fixtures
1. **Initialization Tests**: Verify proper adapter setup
1. **Core Functionality Tests**: Test main execution paths
1. **Error Handling Tests**: Verify graceful error handling
1. **Retry Logic Tests**: Test tenacity-based retry mechanisms
1. **Health Check Tests**: Verify health endpoint functionality
1. **Integration Tests**: End-to-end workflow tests
1. **Edge Case Tests**: Boundary conditions and unusual inputs

### Test Naming Convention

Tests follow the pattern: `test_<feature>_<scenario>_<expected_outcome>`

Examples:

- `test_agno_adapter_initialization`: Verify adapter can be initialized
- `test_execute_code_sweep_single_repo`: Test code sweep on one repository
- `test_get_health_healthy`: Verify health check returns healthy status
- `test_process_repository_error_handling`: Test error handling in processing

## Fixtures

### Common Fixtures

- `mock_config`: Basic configuration object
- `mock_config_anthropic`: Config for Anthropic LLM
- `mock_config_openai`: Config for OpenAI LLM
- `mock_config_with_telemetry`: Config with OpenTelemetry enabled
- `sample_repo_path`: Temporary repository with test files
- `mock_code_graph_analyzer`: Mocked code graph analyzer
- `mock_qc_checker`: Mocked quality control checker
- `mock_documents`: Mocked LlamaIndex documents
- `mock_vector_store_index`: Mocked vector store index

### Fixture Usage

Fixtures are defined per-test-file to provide:

- Isolated test environments
- Realistic mock data
- Reusable test components
- Proper cleanup

## Coverage Goals

The target coverage for adapter tests is **100%** of all execution paths:

### AgnoAdapter Coverage Targets

- [x] Agent creation (real and mock)
- [x] LLM configuration (all 3 providers)
- [x] Code sweep execution
- [x] Quality check execution
- [x] Repository processing with code graph
- [x] Error handling and retries
- [x] Health checks
- [x] Timeout scenarios

### PrefectAdapter Coverage Targets

- [x] Flow creation and execution
- [x] Task processing (code_sweep, quality_check)
- [x] Code graph analysis integration
- [x] Quality control integration
- [x] Error handling and retries
- [x] Flow run tracking
- [x] Health checks
- [x] Concurrent processing

### LlamaIndexAdapter Coverage Targets

- [x] Document ingestion
- [x] Code graph enrichment
- [x] Vector store creation (OpenSearch + memory)
- [x] RAG query execution
- [x] Node parsing and chunking
- [x] OpenTelemetry instrumentation
- [x] Error handling and retries
- [x] Health checks

## Mocking Strategy

### External Dependencies

Tests use extensive mocking to avoid external dependencies:

1. **LlamaIndex**: Mocked when unavailable to allow test execution
1. **Prefect**: Mocked client and flow execution
1. **Code Graph Analyzer**: Mocked for realistic analysis results
1. **Quality Control**: Mocked for QC checks
1. **LLM Providers**: Mocked to avoid API calls

### Mock Implementation

```python
# Example: Mocking code graph analyzer
@pytest.fixture
def mock_code_graph_analyzer():
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(return_value={
        "functions_indexed": 5,
        "total_nodes": 10,
        # ... more data
    })
    return analyzer
```

## Async Test Execution

All adapter methods are async, so tests use:

```python
@pytest.mark.asyncio
async def test_async_functionality():
    result = await adapter.execute(...)
    assert result["status"] == "completed"
```

## Known Limitations

1. **LlamaIndex Tests**: Require mocking of LlamaIndex imports if package not installed
1. **Prefect Tests**: Mock Prefect client doesn't test actual Prefect server integration
1. **Agno Tests**: Use mock agent when Agno package unavailable
1. **Integration Tests**: Limited to mock-based integration, not end-to-end with real services

## Future Enhancements

1. **End-to-End Tests**: Add tests that run against real services (Ollama, Prefect server)
1. **Performance Tests**: Add benchmarks for concurrent processing
1. **Property-Based Tests**: Add Hypothesis tests for input validation
1. **Contract Tests**: Verify adapter interface compliance
1. **Stress Tests**: Test behavior with large repositories and many concurrent operations

## Contributing

When adding new adapter features:

1. Add corresponding tests in the appropriate test file
1. Maintain the established test structure
1. Update this README with new test descriptions
1. Ensure 100% coverage of new code paths
1. Add integration tests for complex workflows

## Test Execution CI/CD

These tests are configured to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run adapter tests
  run: |
    pytest tests/unit/test_adapters/ \
      --cov=mahavishnu.engines \
      --cov-fail-under=90 \
      --junitxml=adapter-test-results.xml
```
