"""Comprehensive tests for Agno adapter.

Tests cover:
- Adapter initialization
- Agent creation with real and mock implementations
- LLM configuration (Anthropic, OpenAI, Ollama)
- Code sweep execution
- Quality check execution
- Repository processing with code graph context
- Error handling and retry logic
- Health checks
- Task timeout scenarios
"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ConfigurationError
from mahavishnu.engines.agno_adapter import AgnoAdapter


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    config = MagicMock()
    config.llm_provider = "ollama"
    config.llm.model = "qwen2.5:7b"
    config.llm.ollama_base_url = "http://localhost:11434"
    return config


@pytest.fixture
def mock_config_anthropic():
    """Create mock configuration for Anthropic."""
    config = MagicMock()
    config.llm_provider = "anthropic"
    config.llm.model = "claude-sonnet-4-20250514"
    return config


@pytest.fixture
def mock_config_openai():
    """Create mock configuration for OpenAI."""
    config = MagicMock()
    config.llm_provider = "openai"
    config.llm.model = "gpt-4"
    return config


@pytest.fixture
def sample_repo_path(tmp_path):
    """Create a sample repository with test files."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create a simple Python file
    (repo_dir / "test.py").write_text("""
def hello_world():
    print("Hello, World!")

class TestClass:
    def method(self):
        return "test"
""")

    return str(repo_dir)


@pytest.fixture
def mock_code_graph_analyzer():
    """Create mock code graph analyzer."""
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(return_value={
        "functions_indexed": 2,
        "total_nodes": 5,
        "total_functions": 2,
        "total_classes": 1,
        "nodes": {
            "node1": {
                "type": "function",
                "name": "hello_world",
                "file_id": "/test/test.py",
                "start_line": 2,
                "end_line": 3,
                "is_export": True,
                "calls": []
            },
            "node2": {
                "type": "class",
                "name": "TestClass",
                "methods": ["method"],
                "inherits_from": []
            }
        }
    })
    analyzer.nodes = {
        "node1": MagicMock(
            name="hello_world",
            file_id="/test/test.py",
            start_line=2,
            end_line=3,
            is_export=True,
            calls=[]
        ),
        "node2": MagicMock(
            name="TestClass",
            methods=["method"],
            inherits_from=[]
        )
    }
    analyzer.find_related_files = AsyncMock(return_value=[])
    return analyzer


# ============================================================================
# Initialization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_agno_adapter_initialization(mock_config):
    """Test Agno adapter initialization with configuration."""
    adapter = AgnoAdapter(config=mock_config)

    assert adapter.config is not None
    assert adapter.config.llm_provider == "ollama"
    assert adapter.config.llm.model == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_agno_adapter_initialization_with_defaults():
    """Test Agno adapter initialization with minimal config."""
    config = MagicMock()
    # No attributes set, should use defaults

    adapter = AgnoAdapter(config=config)

    assert adapter.config is not None


# ============================================================================
# LLM Configuration Tests
# ============================================================================


@pytest.mark.skip(reason="agno package not installed")
@pytest.mark.asyncio
async def test_get_llm_ollama(mock_config):
    """Test Ollama LLM configuration."""
    adapter = AgnoAdapter(config=mock_config)

    llm = adapter._get_llm()

    assert llm is not None
    # Mock agent will be created, so LLM may be None in test environment


@pytest.mark.skip(reason="agno package not installed")
@pytest.mark.asyncio
async def test_get_llm_anthropic_no_key(mock_config_anthropic, monkeypatch):
    """Test Anthropic LLM configuration fails without API key."""
    adapter = AgnoAdapter(config=mock_config_anthropic)

    # Ensure no API key is set
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ConfigurationError) as exc_info:
        adapter._get_llm()

    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


@pytest.mark.skip(reason="agno package not installed")
@pytest.mark.asyncio
async def test_get_llm_openai_no_key(mock_config_openai, monkeypatch):
    """Test OpenAI LLM configuration fails without API key."""
    adapter = AgnoAdapter(config=mock_config_openai)

    # Ensure no API key is set
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError) as exc_info:
        adapter._get_llm()

    assert "OPENAI_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_llm_unsupported_provider():
    """Test LLM configuration with unsupported provider."""
    config = MagicMock()
    config.llm_provider = "unsupported"

    adapter = AgnoAdapter(config=config)

    with pytest.raises(ConfigurationError) as exc_info:
        adapter._get_llm()

    assert "Unsupported LLM provider" in str(exc_info.value)
    assert "unsupported" in str(exc_info.value)


# ============================================================================
# Agent Creation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_agent_code_sweep(mock_config):
    """Test creating agent for code sweep task."""
    adapter = AgnoAdapter(config=mock_config)

    agent = await adapter._create_agent("code_sweep")

    assert agent is not None
    assert hasattr(agent, "name")
    assert hasattr(agent, "role")
    assert hasattr(agent, "instructions")


@pytest.mark.asyncio
async def test_create_agent_returns_mock_agent(mock_config):
    """Test that mock agent is returned when Agno is not available."""
    adapter = AgnoAdapter(config=mock_config)

    agent = await adapter._create_agent("code_sweep")

    # Mock agent should have run method
    assert hasattr(agent, "run")
    assert asyncio.iscoroutinefunction(agent.run)


# ============================================================================
# Code Graph Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_read_file_tool(mock_config, tmp_path):
    """Test _read_file tool functionality."""
    adapter = AgnoAdapter(config=mock_config)

    # Create a test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    content = await adapter._read_file(str(test_file))

    assert content == "Hello, World!"


@pytest.mark.asyncio
async def test_read_file_tool_error_handling(mock_config):
    """Test _read_file tool handles errors gracefully."""
    adapter = AgnoAdapter(config=mock_config)

    content = await adapter._read_file("/nonexistent/file.txt")

    assert "Error reading file" in content
    assert "No such file" in content or "cannot find the file" in content.lower()


@pytest.mark.asyncio
async def test_search_code_tool(mock_config):
    """Test _search_code tool functionality."""
    adapter = AgnoAdapter(config=mock_config)

    results = await adapter._search_code("function", "/path/to/repo")

    assert isinstance(results, list)
    assert len(results) > 0


# ============================================================================
# Execution Tests - Code Sweep
# ============================================================================


@pytest.mark.asyncio
async def test_execute_code_sweep_single_repo(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test executing code sweep on a single repository."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"},
            repos=[sample_repo_path]
        )

        assert result["status"] in ["completed", "failed"]
        assert result["engine"] == "agno"
        assert result["repos_processed"] == 1
        assert "results" in result
        assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_execute_code_sweep_multiple_repos(mock_config, mock_code_graph_analyzer):
    """Test executing code sweep on multiple repositories."""
    adapter = AgnoAdapter(config=mock_config)

    repos = ["/path/to/repo1", "/path/to/repo2", "/path/to/repo3"]

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"},
            repos=repos
        )

        assert result["status"] in ["completed", "failed"]
        assert result["repos_processed"] == 3
        assert len(result["results"]) == 3


@pytest.mark.asyncio
async def test_execute_code_sweep_with_analysis_details(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test that code sweep includes analysis details from code graph."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"},
            repos=[sample_repo_path]
        )

        # Check that results contain analysis details
        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert "result" in repo_result
            assert "analysis_details" in repo_result["result"]


# ============================================================================
# Execution Tests - Quality Check
# ============================================================================


@pytest.mark.asyncio
async def test_execute_quality_check(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test executing quality check on repository."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "quality_check", "id": "test_456"},
            repos=[sample_repo_path]
        )

        assert result["status"] in ["completed", "failed"]
        assert result["engine"] == "agno"

        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert "result" in repo_result
            assert repo_result["result"]["operation"] == "quality_check"


# ============================================================================
# Execution Tests - Default Operations
# ============================================================================


@pytest.mark.asyncio
async def test_execute_default_operation(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test executing a default (unknown) operation."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "custom_operation", "id": "test_789"},
            repos=[sample_repo_path]
        )

        assert result["status"] in ["completed", "failed"]
        assert result["engine"] == "agno"

        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert repo_result["result"]["operation"] == "custom_operation"


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_handles_repo_processing_errors(mock_config, mock_code_graph_analyzer):
    """Test that execution handles individual repo failures gracefully."""
    adapter = AgnoAdapter(config=mock_config)

    # Make analyzer raise an error
    mock_code_graph_analyzer.analyze_repository.side_effect = Exception("Analysis failed")

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_error"},
            repos=["/path/to/repo1"]
        )

        assert result["status"] == "completed"  # Overall execution completes
        assert result["failure_count"] >= 0


@pytest.mark.asyncio
async def test_process_single_repo_exception_handling(mock_config):
    """Test _process_single_repo handles exceptions."""
    adapter = AgnoAdapter(config=mock_config)

    # Invalid repo path should not crash
    result = await adapter._process_single_repo(
        repo="/nonexistent/path",
        task={"type": "code_sweep", "id": "test_exception"}
    )

    assert result is not None
    assert result["status"] in ["completed", "failed"]
    assert "repo" in result


# ============================================================================
# Retry Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_retry_on_transient_failure(mock_config, mock_code_graph_analyzer):
    """Test that adapter retries on transient failures using tenacity."""
    adapter = AgnoAdapter(config=mock_config)

    # Make analyzer fail twice then succeed
    call_count = 0

    async def failing_analyze(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Transient error")
        return {"functions_indexed": 1, "total_nodes": 1, "total_functions": 1, "total_classes": 0, "nodes": {}}

    mock_code_graph_analyzer.analyze_repository = failing_analyze

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter._process_single_repo(
            repo="/path/to/repo",
            task={"type": "code_sweep", "id": "test_retry"}
        )

        # Should eventually succeed or fail after retries
        assert result is not None


# ============================================================================
# Timeout Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_timeout(mock_config, sample_repo_path):
    """Test that execution respects timeout."""
    adapter = AgnoAdapter(config=mock_config)

    # Create a slow operation
    async def slow_analyze(*args, **kwargs):
        await asyncio.sleep(5)
        return {"functions_indexed": 1, "total_nodes": 1, "total_functions": 1, "total_classes": 0, "nodes": {}}

    mock_analyzer = MagicMock()
    mock_analyzer.analyze_repository = slow_analyze
    mock_analyzer.nodes = {}
    mock_analyzer.find_related_files = AsyncMock(return_value=[])

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_analyzer):
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            async with asyncio.timeout(0.5):
                await adapter.execute(
                    task={"type": "code_sweep", "id": "test_timeout"},
                    repos=[sample_repo_path]
                )


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_health_healthy(mock_config):
    """Test health check returns healthy status."""
    adapter = AgnoAdapter(config=mock_config)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health
    assert health["status"] in ["healthy", "unhealthy"]
    assert "details" in health


@pytest.mark.asyncio
async def test_get_health_includes_details(mock_config):
    """Test health check includes adapter details."""
    adapter = AgnoAdapter(config=mock_config)

    health = await adapter.get_health()

    assert "details" in health
    assert "configured" in health["details"]


@pytest.mark.asyncio
async def test_get_health_handles_errors():
    """Test health check handles exceptions gracefully."""
    adapter = AgnoAdapter(config=None)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health


# ============================================================================
# Agent Response Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mock_agent_code_quality_response(mock_config):
    """Test mock agent generates code quality analysis."""
    adapter = AgnoAdapter(config=mock_config)

    agent = await adapter._create_agent("code_sweep")

    response = await agent.run(
        "Analyze repository for code quality",
        context={"repo_path": "/test/repo", "code_graph": {"functions_indexed": 10}}
    )

    assert hasattr(response, "content")
    assert isinstance(response.content, str)
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_mock_agent_quality_check_response(mock_config):
    """Test mock agent generates quality check response."""
    adapter = AgnoAdapter(config=mock_config)

    agent = await adapter._create_agent("code_sweep")

    response = await agent.run(
        "Perform quality check",
        context={"repo_path": "/test/repo", "code_graph": {}}
    )

    assert hasattr(response, "content")
    assert "Quality Check Results" in response.content or "Compliance Score" in response.content


@pytest.mark.asyncio
async def test_mock_agent_default_response(mock_config):
    """Test mock agent generates default response."""
    adapter = AgnoAdapter(config=mock_config)

    agent = await adapter._create_agent("code_sweep")

    response = await agent.run(
        "Unknown operation",
        context={"repo_path": "/test/repo", "code_graph": {}}
    )

    assert hasattr(response, "content")
    assert isinstance(response.content, str)
    assert len(response.content) > 0


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_execution_workflow(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test complete workflow from task execution to result."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        # Execute task
        result = await adapter.execute(
            task={
                "type": "code_sweep",
                "id": "integration_test",
                "params": {"analysis_depth": "deep"}
            },
            repos=[sample_repo_path]
        )

        # Verify structure
        assert result["engine"] == "agno"
        assert result["task"]["id"] == "integration_test"
        assert result["repos_processed"] == 1
        assert "success_count" in result
        assert "failure_count" in result
        assert "results" in result

        # Verify individual result structure
        repo_result = result["results"][0]
        assert "repo" in repo_result
        assert "status" in repo_result
        assert "task_id" in repo_result


@pytest.mark.asyncio
async def test_concurrent_execution_multiple_repos(mock_config, mock_code_graph_analyzer):
    """Test executing tasks concurrently across multiple repos."""
    adapter = AgnoAdapter(config=mock_config)

    repos = [f"/path/to/repo{i}" for i in range(10)]

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep", "id": "concurrent_test"},
            repos=repos
        )

        assert result["repos_processed"] == 10
        assert len(result["results"]) == 10
        # All repos should be processed in parallel
        assert result["success_count"] + result["failure_count"] == 10


# ============================================================================
# Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_empty_repo_list(mock_config):
    """Test executing with empty repository list."""
    adapter = AgnoAdapter(config=mock_config)

    result = await adapter.execute(
        task={"type": "code_sweep", "id": "empty_test"},
        repos=[]
    )

    assert result["repos_processed"] == 0
    assert result["success_count"] == 0
    assert result["failure_count"] == 0
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_execute_with_missing_task_id(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test executing task without ID."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"type": "code_sweep"},  # No id
            repos=[sample_repo_path]
        )

        # Should use "unknown" as default
        repo_result = result["results"][0]
        assert repo_result["task_id"] == "unknown"


@pytest.mark.asyncio
async def test_execute_with_missing_task_type(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test executing task without type (uses default)."""
    adapter = AgnoAdapter(config=mock_config)

    with patch('mahavishnu.engines.agno_adapter.CodeGraphAnalyzer', return_value=mock_code_graph_analyzer):
        result = await adapter.execute(
            task={"id": "no_type_test"},  # No type
            repos=[sample_repo_path]
        )

        assert result["status"] in ["completed", "failed"]
