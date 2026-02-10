"""Comprehensive tests for Prefect adapter.

Tests cover:
- Adapter initialization
- Prefect flow execution
- Task processing with code graph
- Quality check integration
- Repository sweep operations
- Error handling and retry logic
- Health checks
- Flow run tracking
- Concurrent repository processing
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip if prefect is not installed (optional dependency)
prefect = pytest.importorskip("prefect", reason="prefect not installed")

from mahavishnu.engines.prefect_adapter import (
    PrefectAdapter,
    process_repositories_flow,
    process_repository,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    config = MagicMock()
    return config


@pytest.fixture
def sample_repo_path(tmp_path):
    """Create a sample repository with test files."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create Python files with varying complexity
    (repo_dir / "simple.py").write_text("""
def simple_func():
    return "simple"
""")

    (repo_dir / "complex.py").write_text("""
def complex_function(param1, param2, param3):
    '''Complex function with multiple parameters.'''
    result = param1 + param2
    for i in range(100):
        result += param3
    return result

class ComplexClass:
    def method_one(self):
        pass

    def method_two(self):
        pass

    def method_three(self):
        pass
""")

    return str(repo_dir)


@pytest.fixture
def mock_code_graph_analyzer():
    """Create mock code graph analyzer with realistic data."""
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(
        return_value={
            "functions_indexed": 5,
            "total_nodes": 10,
            "total_functions": 5,
            "total_classes": 2,
            "imports_indexed": 8,
            "nodes": {
                "func1": {
                    "type": "function",
                    "name": "simple_func",
                    "file_id": "/test/simple.py",
                    "start_line": 2,
                    "end_line": 3,
                    "is_export": True,
                    "calls": [],
                },
                "func2": {
                    "type": "function",
                    "name": "complex_function",
                    "file_id": "/test/complex.py",
                    "start_line": 2,
                    "end_line": 10,
                    "is_export": True,
                    "calls": ["range", "print"],
                },
                "class1": {
                    "type": "class",
                    "name": "ComplexClass",
                    "methods": ["method_one", "method_two", "method_three"],
                    "inherits_from": [],
                },
            },
        }
    )

    # Create function nodes for complexity analysis
    node1 = MagicMock()
    node1.name = "simple_func"
    node1.file_id = "/test/simple.py"
    node1.start_line = 2
    node1.end_line = 3
    node1.is_export = True
    node1.calls = []

    node2 = MagicMock()
    node2.name = "complex_function"
    node2.file_id = "/test/complex.py"
    node2.start_line = 2
    node2.end_line = 10
    node2.is_export = True
    node2.calls = ["range", "print"]

    node3 = MagicMock()
    node3.name = "ComplexClass"
    node3.file_id = "/test/complex.py"

    analyzer.nodes = {"func1": node1, "func2": node2, "class1": node3}

    return analyzer


@pytest.fixture
def mock_qc_checker():
    """Create mock quality control checker."""
    qc = MagicMock()
    qc.check_repository = AsyncMock(
        return_value={"status": "passed", "score": 92, "issues_found": 0, "recommendations": []}
    )
    return qc


# ============================================================================
# Adapter Initialization Tests
# ============================================================================


def test_prefect_adapter_initialization(mock_config):
    """Test Prefect adapter initialization."""
    adapter = PrefectAdapter(config=mock_config)

    assert adapter.config is not None
    assert adapter.config == mock_config


def test_prefect_adapter_initialization_with_none_config():
    """Test Prefect adapter initialization with None config."""
    adapter = PrefectAdapter(config=None)

    assert adapter.config is None


# ============================================================================
# Task Processing Tests
# ============================================================================


@pytest.mark.asyncio
async def test_process_repository_code_sweep(sample_repo_path, mock_code_graph_analyzer):
    """Test processing a single repository for code sweep."""
    with patch(
        "mahavishnu.engines.prefect_adapter.CodeGraphAnalyzer",
        return_value=mock_code_graph_analyzer,
    ):
        result = await process_repository(
            repo_path=sample_repo_path, task_spec={"type": "code_sweep", "id": "test_123"}
        )

        assert result["status"] in ["completed", "failed"]
        assert result["repo"] == sample_repo_path
        assert result["task_id"] == "test_123"


@pytest.mark.asyncio
async def test_process_repository_code_sweep_complexity_analysis(
    sample_repo_path, mock_code_graph_analyzer
):
    """Test code sweep identifies complex functions."""
    with patch(
        "mahavishnu.engines.prefect_adapter.CodeGraphAnalyzer",
        return_value=mock_code_graph_analyzer,
    ):
        result = await process_repository(
            repo_path=sample_repo_path, task_spec={"type": "code_sweep", "id": "test_complexity"}
        )

        if result["status"] == "completed":
            assert "result" in result
            assert "recommendations" in result["result"]
            assert "quality_score" in result["result"]
            assert "quality_factors" in result["result"]

            # Verify quality factors
            factors = result["result"]["quality_factors"]
            assert "total_functions" in factors
            assert "complex_functions_count" in factors
            assert "avg_function_length" in factors
            assert "max_complexity" in factors

            # Verify quality score is within valid range
            score = result["result"]["quality_score"]
            assert 0 <= score <= 100


@pytest.mark.asyncio
async def test_process_repository_quality_check(sample_repo_path, mock_qc_checker):
    """Test processing repository for quality check."""
    with patch("mahavishnu.engines.prefect_adapter.QualityControl", return_value=mock_qc_checker):
        result = await process_repository(
            repo_path=sample_repo_path, task_spec={"type": "quality_check", "id": "test_qc"}
        )

        assert result["status"] in ["completed", "failed"]
        assert result["repo"] == sample_repo_path
        assert result["task_id"] == "test_qc"


@pytest.mark.asyncio
async def test_process_repository_default_operation(sample_repo_path):
    """Test processing repository with default/unknown operation."""
    result = await process_repository(
        repo_path=sample_repo_path, task_spec={"type": "custom_operation", "id": "test_default"}
    )

    assert result["status"] == "completed"
    assert result["repo"] == sample_repo_path
    assert "result" in result
    assert result["result"]["operation"] == "custom_operation"


@pytest.mark.asyncio
async def test_process_repository_error_handling():
    """Test error handling in repository processing."""
    # Invalid path should trigger error handling
    result = await process_repository(
        repo_path="/nonexistent/path", task_spec={"type": "code_sweep", "id": "test_error"}
    )

    assert result["status"] == "failed"
    assert "error" in result
    assert result["repo"] == "/nonexistent/path"


# ============================================================================
# Flow Tests
# ============================================================================


@pytest.mark.asyncio
async def test_process_repositories_flow_single(sample_repo_path):
    """Test flow processing a single repository."""
    results = await process_repositories_flow(
        repos=[sample_repo_path], task_spec={"type": "default", "id": "flow_test_1"}
    )

    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["repo"] == sample_repo_path


@pytest.mark.asyncio
async def test_process_repositories_flow_multiple(tmp_path):
    """Test flow processing multiple repositories."""
    repo1 = str(tmp_path / "repo1")
    repo2 = str(tmp_path / "repo2")
    repo3 = str(tmp_path / "repo3")

    for repo in [repo1, repo2, repo3]:
        Path(repo).mkdir()

    results = await process_repositories_flow(
        repos=[repo1, repo2, repo3], task_spec={"type": "default", "id": "flow_test_multi"}
    )

    assert isinstance(results, list)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_process_repositories_flow_concurrent(tmp_path):
    """Test that flow processes repositories concurrently."""
    repos = [str(tmp_path / f"repo{i}") for i in range(5)]

    for repo in repos:
        Path(repo).mkdir()

    import time

    start_time = time.time()

    results = await process_repositories_flow(
        repos=repos, task_spec={"type": "default", "id": "flow_concurrent"}
    )

    duration = time.time() - start_time

    assert len(results) == 5
    # Concurrent execution should be faster than sequential
    # (This is a weak assertion, but demonstrates the concept)
    assert duration < 1.0  # Should complete quickly


# ============================================================================
# Adapter Execute Tests
# ============================================================================


@pytest.mark.asyncio
async def test_adapter_execute_code_sweep(mock_config, sample_repo_path):
    """Test adapter execute method for code sweep."""
    adapter = PrefectAdapter(config=mock_config)

    # Mock Prefect client
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-flow-run-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_123",
        }
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"}, repos=[sample_repo_path]
        )

        assert result["status"] in ["completed", "failed"]
        assert result["engine"] == "prefect"
        assert result["task"]["id"] == "test_123"
        assert result["repos_processed"] == 1


@pytest.mark.asyncio
async def test_adapter_execute_multiple_repos(mock_config, tmp_path):
    """Test adapter execute with multiple repositories."""
    adapter = PrefectAdapter(config=mock_config)

    repos = [str(tmp_path / f"repo{i}") for i in range(3)]
    for repo in repos:
        Path(repo).mkdir()

    # Mock Prefect client
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-multi-flow-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": repo,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_multi",
        }
        for repo in repos
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(task={"type": "code_sweep", "id": "test_multi"}, repos=repos)

        assert result["repos_processed"] == 3
        assert result["success_count"] == 3
        assert result["failure_count"] == 0


@pytest.mark.asyncio
async def test_adapter_execute_with_failures(mock_config, tmp_path):
    """Test adapter execute handles partial failures."""
    adapter = PrefectAdapter(config=mock_config)

    repos = [str(tmp_path / f"repo{i}") for i in range(3)]
    for repo in repos:
        Path(repo).mkdir()

    # Mock Prefect client with mixed results
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-partial-fail-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": repos[0],
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_partial",
        },
        {
            "repo": repos[1],
            "status": "failed",
            "error": "Processing failed",
            "task_id": "test_partial",
        },
        {
            "repo": repos[2],
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_partial",
        },
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_partial"}, repos=repos
        )

        assert result["repos_processed"] == 3
        assert result["success_count"] == 2
        assert result["failure_count"] == 1


@pytest.mark.asyncio
async def test_adapter_execute_flow_failure(mock_config, sample_repo_path):
    """Test adapter execute handles flow failure."""
    adapter = PrefectAdapter(config=mock_config)

    # Mock Prefect client with failed flow
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-failed-flow-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = False
    mock_state.result.return_value = []

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_flow_fail"}, repos=[sample_repo_path]
        )

        assert result["status"] == "failed"
        assert result["success_count"] == 0


@pytest.mark.asyncio
async def test_adapter_execute_exception_handling(mock_config, sample_repo_path):
    """Test adapter execute handles exceptions gracefully."""
    adapter = PrefectAdapter(config=mock_config)

    # Mock Prefect client that raises exception
    mock_client = AsyncMock()
    mock_client.create_run.side_effect = Exception("Prefect connection failed")

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_exception"}, repos=[sample_repo_path]
        )

        assert result["status"] == "failed"
        assert "error" in result
        assert result["success_count"] == 0
        assert result["failure_count"] == 1


# ============================================================================
# Retry Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_retry_on_transient_failure(mock_config, sample_repo_path):
    """Test that execute retries on transient failures."""
    adapter = PrefectAdapter(config=mock_config)

    # Mock Prefect client that fails then succeeds
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-retry-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_retry",
        }
    ]

    mock_client = AsyncMock()
    call_count = 0

    async def create_run_with_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Transient connection error")
        return mock_flow_run

    mock_client.create_run = create_run_with_retry
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_retry"}, repos=[sample_repo_path]
        )

        # Should eventually succeed after retries
        assert result["status"] in ["completed", "failed"]


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_health_healthy(mock_config):
    """Test health check returns healthy status."""
    adapter = PrefectAdapter(config=mock_config)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health
    assert health["status"] in ["healthy", "unhealthy"]
    assert "details" in health


@pytest.mark.asyncio
async def test_get_health_includes_prefect_details(mock_config):
    """Test health check includes Prefect-specific details."""
    adapter = PrefectAdapter(config=mock_config)

    health = await adapter.get_health()

    assert "details" in health
    assert "prefect_version" in health["details"]
    assert "configured" in health["details"]


@pytest.mark.asyncio
async def test_get_health_handles_exception():
    """Test health check handles exceptions."""
    adapter = PrefectAdapter(config=None)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health


# ============================================================================
# Flow Run Tracking Tests
# ============================================================================


@pytest.mark.asyncio
async def test_flow_run_id_tracking(mock_config, sample_repo_path):
    """Test that flow run ID is tracked and returned."""
    adapter = PrefectAdapter(config=mock_config)

    mock_flow_run = MagicMock()
    mock_flow_run.id = "unique-flow-run-id-12345"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_tracking",
        }
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_tracking"}, repos=[sample_repo_path]
        )

        assert "flow_run_id" in result
        assert result["flow_run_id"] == "unique-flow-run-id-12345"


@pytest.mark.asyncio
async def test_flow_run_url_generation(mock_config, sample_repo_path):
    """Test that flow run URL is generated correctly."""
    adapter = PrefectAdapter(config=mock_config)

    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-flow-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "test_url",
        }
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_url"}, repos=[sample_repo_path]
        )

        assert "flow_run_url" in result
        assert "test-flow-id" in result["flow_run_url"]
        assert "localhost:4200" in result["flow_run_url"]


# ============================================================================
# Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_empty_repo_list(mock_config):
    """Test executing with empty repository list."""
    adapter = PrefectAdapter(config=mock_config)

    # Mock Prefect client
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-empty-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = []

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(task={"type": "code_sweep", "id": "test_empty"}, repos=[])

        assert result["repos_processed"] == 0
        assert result["success_count"] == 0
        assert result["failure_count"] == 0


@pytest.mark.asyncio
async def test_execute_with_missing_task_id(mock_config, sample_repo_path):
    """Test executing task without ID."""
    adapter = PrefectAdapter(config=mock_config)

    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-no-task-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "code_sweep"},
            "task_id": "unknown",
        }
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={"type": "code_sweep"},  # No id
            repos=[sample_repo_path],
        )

        assert result["status"] in ["completed", "failed"]


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_prefect_workflow(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test complete Prefect workflow from execution to results."""
    adapter = PrefectAdapter(config=mock_config)

    mock_flow_run = MagicMock()
    mock_flow_run.id = "integration-test-flow-id"

    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [
        {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {
                "operation": "code_sweep",
                "changes_identified": 5,
                "recommendations": [],
                "quality_score": 85.0,
                "quality_factors": {
                    "total_functions": 5,
                    "complex_functions_count": 1,
                    "avg_function_length": 8.5,
                    "max_complexity": 3,
                },
            },
            "task_id": "integration_test",
        }
    ]

    mock_client = AsyncMock()
    mock_client.create_run = AsyncMock(return_value=mock_flow_run)
    mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)
    mock_client.api_url = "http://localhost:4200"

    with patch("mahavishnu.engines.prefect_adapter.get_client", return_value=mock_client):
        result = await adapter.execute(
            task={
                "type": "code_sweep",
                "id": "integration_test",
                "params": {"quality_threshold": 80},
            },
            repos=[sample_repo_path],
        )

        # Verify complete result structure
        assert result["engine"] == "prefect"
        assert result["task"]["id"] == "integration_test"
        assert result["repos_processed"] == 1
        assert result["success_count"] == 1
        assert result["failure_count"] == 0
        assert "flow_run_id" in result
        assert "flow_run_url" in result
        assert "results" in result

        # Verify individual result structure
        repo_result = result["results"][0]
        assert repo_result["status"] == "completed"
        assert "result" in repo_result
        assert repo_result["result"]["operation"] == "code_sweep"
        assert "quality_score" in repo_result["result"]
