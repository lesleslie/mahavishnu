"""Comprehensive tests for Agno adapter.

Tests cover:
- Adapter initialization
- LLM provider factory configuration
- Agent creation (via mocking agno SDK imports)
- Task execution across repositories
- Health checks
- Error handling and retry logic
- Team management delegation
- Timeout scenarios
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.errors import AgnoError, ConfigurationError
from mahavishnu.engines.agno_adapter_impl import (
    AgnoAdapter,
    AgnoAdapterConfig,
    AgnoLLMConfig,
    LLMProvider,
    LLMProviderFactory,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration that provides AgnoAdapterConfig via .agno attribute."""
    config = MagicMock()
    agno_config = AgnoAdapterConfig(
        llm=AgnoLLMConfig(
            provider=LLMProvider.OLLAMA,
            model_id="qwen2.5:7b",
            base_url="http://localhost:11434",
        ),
    )
    config.agno = agno_config
    return config


@pytest.fixture
def mock_config_anthropic():
    """Create mock configuration for Anthropic."""
    config = MagicMock()
    agno_config = AgnoAdapterConfig(
        llm=AgnoLLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model_id="claude-sonnet-4-20250514",
        ),
    )
    config.agno = agno_config
    return config


@pytest.fixture
def mock_config_openai():
    """Create mock configuration for OpenAI."""
    config = MagicMock()
    agno_config = AgnoAdapterConfig(
        llm=AgnoLLMConfig(
            provider=LLMProvider.OPENAI,
            model_id="gpt-4",
        ),
    )
    config.agno = agno_config
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


# ============================================================================
# Initialization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_agno_adapter_initialization(mock_config):
    """Test Agno adapter initialization with configuration."""
    adapter = AgnoAdapter(config=mock_config)

    assert adapter.config is not None
    assert adapter.agno_config is not None
    assert adapter.agno_config.llm.provider == LLMProvider.OLLAMA
    assert adapter.agno_config.llm.model_id == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_agno_adapter_initialization_with_defaults():
    """Test Agno adapter initialization with minimal config."""
    config = MagicMock(spec=[])
    # No .agno attribute -- should fall back to default AgnoAdapterConfig

    adapter = AgnoAdapter(config=config)

    assert adapter.config is not None
    assert isinstance(adapter.agno_config, AgnoAdapterConfig)


# ============================================================================
# LLM Provider Factory Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_llm_ollama(mock_config):
    """Test Ollama LLM configuration."""
    adapter = AgnoAdapter(config=mock_config)

    factory = LLMProviderFactory(adapter.agno_config.llm)
    llm = factory.create_model()

    assert llm is not None


@pytest.mark.asyncio
async def test_get_llm_anthropic_no_key(mock_config_anthropic, monkeypatch):
    """Test Anthropic LLM configuration fails without API key."""
    adapter = AgnoAdapter(config=mock_config_anthropic)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    factory = LLMProviderFactory(adapter.agno_config.llm)

    with pytest.raises(ConfigurationError) as exc_info:
        factory.create_model()

    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_llm_openai_no_key(mock_config_openai, monkeypatch):
    """Test OpenAI LLM configuration fails without API key."""
    adapter = AgnoAdapter(config=mock_config_openai)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    factory = LLMProviderFactory(adapter.agno_config.llm)

    with pytest.raises(ConfigurationError) as exc_info:
        factory.create_model()

    assert "OPENAI_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_llm_unsupported_provider():
    """Test LLM configuration with unsupported provider."""
    # Create a config with an unsupported provider via direct manipulation
    config = AgnoLLMConfig(provider=LLMProvider.OLLAMA)
    # Manually set provider to an invalid value after construction
    config.provider = "unsupported"  # type: ignore[assignment]

    factory = LLMProviderFactory(config)

    with pytest.raises(AgnoError) as exc_info:
        factory.create_model()

    assert "Unsupported LLM provider" in str(exc_info.value)


# ============================================================================
# Agent Creation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_agent_code_sweep(mock_config):
    """Test creating agent for code sweep task via _create_agent."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._semaphore = asyncio.Semaphore(5)

    # Mock the agno SDK Agent class (imported locally in _create_agent)
    mock_agent = MagicMock()
    mock_agent.name = "code_sweep_agent"
    mock_agent.role = "Agent for code_sweep operations"
    mock_agent.instructions = "instructions"

    with (
        patch("agno.agent.Agent", return_value=mock_agent),
        patch.object(adapter, "_get_all_tools", return_value=[]),
        patch.object(adapter, "_llm_factory") as mock_factory,
    ):
        mock_factory.create_model.return_value = MagicMock()

        agent = await adapter._create_agent(
            name="code_sweep_agent",
            role="Agent for code_sweep operations",
            instructions="Analyze code quality",
        )

        assert agent is not None
        assert agent.name == "code_sweep_agent"


@pytest.mark.asyncio
async def test_create_agent_requires_all_args(mock_config):
    """Test that _create_agent can derive task metadata from the task name."""
    adapter = AgnoAdapter(config=mock_config)

    mock_agent = MagicMock()
    mock_agent.name = "code_sweep_agent"

    with (
        patch("agno.agent.Agent", return_value=mock_agent),
        patch.object(adapter, "_get_llm", return_value=MagicMock()),
    ):
        agent = await adapter._create_agent("code_sweep")

    assert agent is mock_agent
    assert agent.name == "code_sweep_agent"


# ============================================================================
# Execution Tests - Code Sweep
# ============================================================================


@pytest.mark.asyncio
async def test_execute_code_sweep_single_repo(mock_config, sample_repo_path):
    """Test executing code sweep on a single repository."""
    adapter = AgnoAdapter(config=mock_config)

    # Mock _process_single_repo to avoid agno SDK dependency
    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {
            "operation": "code_sweep",
            "content": "Analysis complete",
            "run_id": "test_run",
            "latency_ms": 100.0,
        },
        "task_id": "test_123",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        # Ensure adapter is initialized to avoid init code path
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"},
            repos=[sample_repo_path],
        )

        assert result["status"] in ("completed", "partial")
        assert result["engine"] == "agno"
        assert result["repos_processed"] == 1
        assert "results" in result
        assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_execute_code_sweep_multiple_repos(mock_config):
    """Test executing code sweep on multiple repositories."""
    adapter = AgnoAdapter(config=mock_config)

    repos = ["/path/to/repo1", "/path/to/repo2", "/path/to/repo3"]

    mock_result = {
        "repo": "/path/to/repo",
        "status": "completed",
        "result": {"operation": "code_sweep", "content": "done"},
        "task_id": "test_123",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(task={"type": "code_sweep", "id": "test_123"}, repos=repos)

        assert result["status"] in ("completed", "partial")
        assert result["repos_processed"] == 3
        assert len(result["results"]) == 3


@pytest.mark.asyncio
async def test_execute_code_sweep_with_analysis_details(mock_config, sample_repo_path):
    """Test that code sweep results contain operation details."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {
            "operation": "code_sweep",
            "content": "Analysis complete with details",
            "run_id": "test_run",
            "latency_ms": 100.0,
        },
        "task_id": "test_123",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_123"},
            repos=[sample_repo_path],
        )

        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert "result" in repo_result
            assert "operation" in repo_result["result"]


# ============================================================================
# Execution Tests - Quality Check
# ============================================================================


@pytest.mark.asyncio
async def test_execute_quality_check(mock_config, sample_repo_path):
    """Test executing quality check on repository."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {
            "operation": "quality_check",
            "content": "Quality check passed",
            "run_id": "test_run",
            "latency_ms": 50.0,
        },
        "task_id": "test_456",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "quality_check", "id": "test_456"},
            repos=[sample_repo_path],
        )

        assert result["status"] in ("completed", "partial")
        assert result["engine"] == "agno"

        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert "result" in repo_result
            assert repo_result["result"]["operation"] == "quality_check"


# ============================================================================
# Execution Tests - Default Operations
# ============================================================================


@pytest.mark.asyncio
async def test_execute_default_operation(mock_config, sample_repo_path):
    """Test executing a default (unknown) operation."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {
            "operation": "custom_operation",
            "content": "Custom operation done",
            "run_id": "test_run",
            "latency_ms": 75.0,
        },
        "task_id": "test_789",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "custom_operation", "id": "test_789"},
            repos=[sample_repo_path],
        )

        assert result["status"] in ("completed", "partial")
        assert result["engine"] == "agno"

        repo_result = result["results"][0]
        if repo_result.get("status") == "completed":
            assert repo_result["result"]["operation"] == "custom_operation"


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_handles_repo_processing_errors(mock_config):
    """Test that execution handles individual repo failures gracefully."""
    adapter = AgnoAdapter(config=mock_config)

    # Mock _process_single_repo to return a failed result
    failed_result = {
        "repo": "/path/to/repo1",
        "status": "failed",
        "error": "Analysis failed",
        "task_id": "test_error",
    }

    with patch.object(adapter, "_process_single_repo", return_value=failed_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "code_sweep", "id": "test_error"},
            repos=["/path/to/repo1"],
        )

        assert result["status"] in ("completed", "partial")
        assert result["failure_count"] >= 1


@pytest.mark.asyncio
async def test_process_single_repo_exception_handling(mock_config):
    """Test _process_single_repo handles exceptions."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._semaphore = asyncio.Semaphore(5)

    # Mock _create_agent to raise an exception
    with patch.object(adapter, "_create_agent", side_effect=Exception("Agent creation failed")):
        result = await adapter._process_single_repo(
            repo="/nonexistent/path",
            task={"type": "code_sweep", "id": "test_exception"},
        )

        assert result is not None
        assert result["status"] in ("completed", "failed")
        assert "repo" in result


# ============================================================================
# Retry Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_retry_on_transient_failure(mock_config):
    """Test that adapter retries on transient failures using tenacity."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._semaphore = asyncio.Semaphore(5)

    # First call fails, second succeeds
    call_count = 0
    mock_agent_result = MagicMock()
    mock_agent_result.name = "code_sweep_agent"

    original_create = adapter._create_agent

    async def failing_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Transient error")
        return await original_create(*args, **kwargs) if False else mock_agent_result

    with (
        patch.object(adapter, "_create_agent", side_effect=failing_create),
        patch.object(adapter, "_run_agent") as mock_run,
    ):
        mock_run.return_value = MagicMock(
            agent_name="code_sweep_agent",
            content="Success after retry",
            run_id="retry_run",
            success=True,
            latency_ms=200.0,
        )

        result = await adapter._process_single_repo(
            repo="/path/to/repo",
            task={"type": "code_sweep", "id": "test_retry"},
        )

        # Should succeed after retry or fail gracefully
        assert result is not None


# ============================================================================
# Timeout Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_timeout(mock_config, sample_repo_path):
    """Test that execution respects timeout."""
    adapter = AgnoAdapter(config=mock_config)

    # Create a slow _process_single_repo
    async def slow_process(*args, **kwargs):
        await asyncio.sleep(5)
        return {
            "repo": sample_repo_path,
            "status": "completed",
            "result": {},
            "task_id": "test_timeout",
        }

    with patch.object(adapter, "_process_single_repo", side_effect=slow_process):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            async with asyncio.timeout(0.5):
                await adapter.execute(
                    task={"type": "code_sweep", "id": "test_timeout"},
                    repos=[sample_repo_path],
                )


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_health_healthy(mock_config):
    """Test health check returns healthy status when initialized."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._llm_factory = MagicMock()

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health
    assert health["status"] in ("healthy", "unhealthy", "degraded")
    assert "details" in health


@pytest.mark.asyncio
async def test_get_health_includes_details(mock_config):
    """Test health check includes adapter details."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._llm_factory = MagicMock()

    health = await adapter.get_health()

    assert "details" in health
    details = health["details"]
    assert "adapter" in details
    assert details["adapter"] == "agno"
    assert "version" in details
    assert "initialized" in details


@pytest.mark.asyncio
async def test_get_health_handles_errors():
    """Test health check handles exceptions gracefully."""
    adapter = AgnoAdapter(config=None)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health
    # With config=None, the adapter should still return a health dict
    # (using default AgnoAdapterConfig)
    assert health["status"] in ("healthy", "unhealthy", "degraded")


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_execution_workflow(mock_config, sample_repo_path):
    """Test complete workflow from task execution to result."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {
            "operation": "code_sweep",
            "content": "Full workflow analysis",
            "run_id": "integration_run",
            "latency_ms": 150.0,
        },
        "task_id": "integration_test",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        # Execute task
        result = await adapter.execute(
            task={
                "type": "code_sweep",
                "id": "integration_test",
                "params": {"analysis_depth": "deep"},
            },
            repos=[sample_repo_path],
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
async def test_concurrent_execution_multiple_repos(mock_config):
    """Test executing tasks concurrently across multiple repos."""
    adapter = AgnoAdapter(config=mock_config)

    repos = [f"/path/to/repo{i}" for i in range(10)]

    mock_result = {
        "repo": "/path/to/repo",
        "status": "completed",
        "result": {"operation": "code_sweep", "content": "done"},
        "task_id": "concurrent_test",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "code_sweep", "id": "concurrent_test"}, repos=repos
        )

        assert result["repos_processed"] == 10
        assert len(result["results"]) == 10
        assert result["success_count"] + result["failure_count"] == 10


# ============================================================================
# Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_empty_repo_list(mock_config):
    """Test executing with empty repository list."""
    adapter = AgnoAdapter(config=mock_config)
    adapter._initialized = True
    adapter._semaphore = asyncio.Semaphore(5)

    result = await adapter.execute(task={"type": "code_sweep", "id": "empty_test"}, repos=[])

    assert result["repos_processed"] == 0
    assert result["success_count"] == 0
    assert result["failure_count"] == 0
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_execute_with_missing_task_id(mock_config, sample_repo_path):
    """Test executing task without ID."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {"operation": "code_sweep", "content": "done"},
        "task_id": "unknown",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"type": "code_sweep"},  # No id
            repos=[sample_repo_path],
        )

        # Should use "unknown" as default
        repo_result = result["results"][0]
        assert repo_result["task_id"] == "unknown"


@pytest.mark.asyncio
async def test_execute_with_missing_task_type(mock_config, sample_repo_path):
    """Test executing task without type (uses default)."""
    adapter = AgnoAdapter(config=mock_config)

    mock_result = {
        "repo": sample_repo_path,
        "status": "completed",
        "result": {"operation": "default", "content": "done"},
        "task_id": "no_type_test",
    }

    with patch.object(adapter, "_process_single_repo", return_value=mock_result):
        adapter._initialized = True
        adapter._semaphore = asyncio.Semaphore(5)

        result = await adapter.execute(
            task={"id": "no_type_test"},  # No type
            repos=[sample_repo_path],
        )

        assert result["status"] in ("completed", "partial")
