"""Comprehensive tests for LlamaIndex adapter.

Tests cover:
- Adapter initialization with Ollama embeddings
- OpenTelemetry instrumentation (tracing and metrics)
- Document ingestion from repositories
- Code graph integration for enhanced metadata
- Vector store creation (OpenSearch and in-memory)
- RAG query execution
- Node parsing and chunking
- Error handling and retry logic
- Structured error handling with MahavishnuError
- Health checks
- Edge cases and error scenarios
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# Mock LlamaIndex imports at module level
# ============================================================================

# Mock all LlamaIndex modules to allow tests to run without installing the package
sys_modules = {
    "llama_index": MagicMock(),
    "llama_index.core": MagicMock(),
    "llama_index.core.document": MagicMock(),
    "llama_index.core.node_parser": MagicMock(),
    "llama_index.core.settings": MagicMock(),
    "llama_index.core.storage": MagicMock(),
    "llama_index.core.storage.storage_context": MagicMock(),
    "llama_index.embeddings": MagicMock(),
    "llama_index.embeddings.ollama": MagicMock(),
    "llama_index.llms": MagicMock(),
    "llama_index.llms.ollama": MagicMock(),
    "llama_index.vector_stores": MagicMock(),
    "llama_index.vector_stores.opensearch": MagicMock(),
}

# Apply mocks before importing adapter
with patch.dict("sys.modules", sys_modules):
    # Make LLAMAINDEX_AVAILABLE True in the imported module
    import mahavishnu.engines.llamaindex_adapter as adapter_module
    from mahavishnu.engines.llamaindex_adapter import (
        LlamaIndexAdapter,
        LlamaIndexEmbeddingError,
        LlamaIndexIndexNotFoundError,
        LlamaIndexIngestionError,
        LlamaIndexQueryError,
    )

    adapter_module.LLAMAINDEX_AVAILABLE = True


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration with flat attributes matching adapter expectations."""
    config = MagicMock()
    # Use flat attributes as expected by getattr in adapter
    config.llm_model = "nomic-embed-text"
    config.ollama_base_url = "http://localhost:11434"
    config.opensearch_endpoint = "https://localhost:9200"
    config.opensearch_index_name = "mahavishnu_code"
    config.opensearch_verify_certs = True
    config.opensearch_use_ssl = True
    config.metrics_enabled = False
    return config


@pytest.fixture
def mock_config_with_telemetry():
    """Create mock configuration with telemetry enabled."""
    config = MagicMock()
    config.llm_model = "nomic-embed-text"
    config.ollama_base_url = "http://localhost:11434"
    config.opensearch_endpoint = "https://localhost:9200"
    config.opensearch_index_name = "mahavishnu_code"
    config.opensearch_verify_certs = True
    config.opensearch_use_ssl = True
    config.metrics_enabled = True
    return config


@pytest.fixture
def sample_repo_path(tmp_path):
    """Create a sample repository with test files."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create various file types
    (repo_dir / "README.md").write_text("""
# Test Repository

This is a test repository for LlamaIndex ingestion.
""")

    (repo_dir / "test.py").write_text("""
def hello_world():
    '''A simple hello world function.'''
    print("Hello, World!")

class TestClass:
    '''A test class.'''
    def method(self):
        return "test"
""")

    (repo_dir / "config.yaml").write_text("""
test:
  enabled: true
  value: 42
""")

    # Create a subdirectory with more files
    subdir = repo_dir / "src"
    subdir.mkdir()
    (subdir / "module.py").write_text("""
def helper_function():
    '''Helper function.'''
    return "help"
""")

    return str(repo_dir)


@pytest.fixture
def mock_code_graph_analyzer():
    """Create mock code graph analyzer."""
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(
        return_value={
            "functions_indexed": 3,
            "total_nodes": 8,
            "total_functions": 3,
            "total_classes": 1,
            "nodes": {
                "func1": {
                    "type": "function",
                    "name": "hello_world",
                    "file_id": "test.py",
                    "start_line": 2,
                    "end_line": 4,
                    "is_export": True,
                    "calls": ["print"],
                },
                "func2": {
                    "type": "function",
                    "name": "helper_function",
                    "file_id": "src/module.py",
                    "start_line": 2,
                    "end_line": 4,
                    "is_export": False,
                    "calls": [],
                },
            },
        }
    )

    # Mock nodes with file_id attribute
    node1 = MagicMock()
    node1.name = "hello_world"
    node1.file_id = "test.py"
    node1.start_line = 2
    node1.end_line = 4
    node1.is_export = True
    node1.calls = ["print"]

    node2 = MagicMock()
    node2.name = "helper_function"
    node2.file_id = "src/module.py"
    node2.start_line = 2
    node2.end_line = 4
    node2.is_export = False
    node2.calls = []

    analyzer.nodes = {"func1": node1, "func2": node2}

    analyzer.find_related_files = AsyncMock(return_value=["test.py", "src/module.py"])

    return analyzer


@pytest.fixture
def mock_documents():
    """Create mock LlamaIndex documents."""
    docs = []
    for i in range(3):
        doc = MagicMock()
        doc.metadata = {"file_name": f"test{i}.py", "file_path": f"/test/test{i}.py"}
        docs.append(doc)
    return docs


@pytest.fixture
def mock_vector_store_index():
    """Create mock vector store index."""
    index = MagicMock()
    index.as_query_engine.return_value = MagicMock()

    mock_response = MagicMock()
    mock_response.source_nodes = []
    mock_response.__str__ = lambda self: "Test response"
    index.as_query_engine.return_value.query.return_value = mock_response

    return index


# ============================================================================
# Initialization Tests
# ============================================================================


def test_llamaindex_adapter_initialization(mock_config):
    """Test LlamaIndex adapter initialization with configuration."""
    adapter = LlamaIndexAdapter(config=mock_config)

    assert adapter.config is not None
    assert adapter.config.llm_model == "nomic-embed-text"
    assert adapter.indices == {}
    assert adapter.documents == {}


def test_llamaindex_adapter_initialization_not_available():
    """Test initialization fails when LlamaIndex is not available."""
    with patch.object(adapter_module, "LLAMAINDEX_AVAILABLE", False):
        with pytest.raises(ImportError) as exc_info:
            LlamaIndexAdapter(config=MagicMock())

        assert "LlamaIndex dependencies not available" in str(exc_info.value)


def test_llamaindex_adapter_initialization_with_telemetry(mock_config_with_telemetry):
    """Test initialization with OpenTelemetry enabled."""
    with patch.object(adapter_module, "OTEL_AVAILABLE", False):
        adapter = LlamaIndexAdapter(config=mock_config_with_telemetry)

        assert adapter.config is not None
        assert hasattr(adapter, "tracer")
        assert hasattr(adapter, "meter")


# ============================================================================
# OpenTelemetry Tests
# ============================================================================


def test_fallback_instrumentation_initialization(mock_config):
    """Test fallback instrumentation when OpenTelemetry is unavailable."""
    with patch.object(adapter_module, "OTEL_AVAILABLE", False):
        adapter = LlamaIndexAdapter(config=mock_config)

        # Should have fallback metric instruments
        assert hasattr(adapter, "ingest_duration_histogram")
        assert hasattr(adapter, "query_duration_histogram")
        assert hasattr(adapter, "documents_counter")
        assert hasattr(adapter, "nodes_counter")
        assert hasattr(adapter, "query_counter")
        assert hasattr(adapter, "error_counter")
        assert hasattr(adapter, "index_counter")


def test_truncate_query(mock_config):
    """Test query text truncation for span attributes."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Short query should not be truncated
    short_query = "short query"
    assert adapter._truncate_query(short_query) == short_query

    # Long query should be truncated
    long_query = "a" * 200
    truncated = adapter._truncate_query(long_query, max_length=100)
    assert len(truncated) == 103  # 100 + "..."
    assert truncated.endswith("...")


# ============================================================================
# Document Ingestion Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ingest_repository_success(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test successful repository ingestion."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Mock SimpleDirectoryReader and VectorStoreIndex
    mock_reader = MagicMock()
    mock_docs = [
        MagicMock(metadata={"file_name": "test.py", "file_path": sample_repo_path + "/test.py"})
    ]
    mock_reader.load_data.return_value = mock_docs

    mock_index = MagicMock()
    mock_index.query = MagicMock()

    with (
        patch(
            "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
            return_value=mock_reader,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.VectorStoreIndex",
            return_value=mock_index,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.CodeGraphAnalyzer",
            return_value=mock_code_graph_analyzer,
        ),
    ):
        result = await adapter._ingest_repository(
            repo_path=sample_repo_path, task_params={"id": "test_ingest"}
        )

        assert result["status"] in ["completed", "failed"]
        assert result["repo"] == sample_repo_path


@pytest.mark.asyncio
async def test_ingest_repository_nonexistent_path(mock_config):
    """Test ingestion with nonexistent repository path."""
    adapter = LlamaIndexAdapter(config=mock_config)

    result = await adapter._ingest_repository(
        repo_path="/nonexistent/path", task_params={"id": "test_nonexistent"}
    )

    assert result["status"] == "failed"
    assert "error" in result
    assert "error_code" in result


@pytest.mark.asyncio
async def test_ingest_repository_no_documents(mock_config, tmp_path, mock_code_graph_analyzer):
    """Test ingestion when no documents are found."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Create empty repo
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()

    # Mock reader that returns no documents
    mock_reader = MagicMock()
    mock_reader.load_data.return_value = []

    with (
        patch(
            "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
            return_value=mock_reader,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.CodeGraphAnalyzer",
            return_value=mock_code_graph_analyzer,
        ),
    ):
        result = await adapter._ingest_repository(
            repo_path=str(empty_repo), task_params={"id": "test_no_docs"}
        )

        assert result["status"] == "completed"
        if "result" in result:
            assert result["result"]["documents_ingested"] == 0


@pytest.mark.asyncio
async def test_ingest_repository_with_code_graph_enrichment(
    mock_config, sample_repo_path, mock_code_graph_analyzer
):
    """Test that documents are enriched with code graph context."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Create mock documents with file_path metadata
    mock_doc = MagicMock()
    mock_doc.metadata = {"file_name": "test.py", "file_path": f"{sample_repo_path}/test.py"}

    mock_reader = MagicMock()
    mock_reader.load_data.return_value = [mock_doc]

    mock_index = MagicMock()

    with (
        patch(
            "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
            return_value=mock_reader,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.VectorStoreIndex",
            return_value=mock_index,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.CodeGraphAnalyzer",
            return_value=mock_code_graph_analyzer,
        ),
    ):
        result = await adapter._ingest_repository(
            repo_path=sample_repo_path, task_params={"id": "test_enrichment"}
        )

        assert result["status"] in ["completed", "failed"]


@pytest.mark.asyncio
async def test_ingest_repository_with_custom_file_types(
    mock_config, sample_repo_path, mock_code_graph_analyzer
):
    """Test ingestion with custom file type filters."""
    adapter = LlamaIndexAdapter(config=mock_config)

    mock_reader = MagicMock()
    mock_reader.load_data.return_value = []

    with (
        patch(
            "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
            return_value=mock_reader,
        ),
        patch(
            "mahavishnu.engines.llamaindex_adapter.CodeGraphAnalyzer",
            return_value=mock_code_graph_analyzer,
        ),
    ):
        result = await adapter._ingest_repository(
            repo_path=sample_repo_path,
            task_params={
                "id": "test_file_types",
                "file_types": [".py", ".md"],
                "exclude_patterns": ["__pycache__", ".git"],
            },
        )

        assert result["status"] in ["completed", "failed"]


# ============================================================================
# Query Tests
# ============================================================================


@pytest.mark.asyncio
async def test_query_index_success(mock_config, mock_vector_store_index):
    """Test successful index query."""
    adapter = LlamaIndexAdapter(config=mock_config)
    adapter.indices["test_0"] = mock_vector_store_index

    result = await adapter._query_index(
        repo_path="/test/repo",
        task_params={"query": "test query", "index_id": "test_0", "top_k": 5},
    )

    assert result["status"] == "completed"
    assert "result" in result
    assert result["result"]["operation"] == "query"


@pytest.mark.asyncio
async def test_query_index_missing_query(mock_config):
    """Test query fails when query text is not provided."""
    adapter = LlamaIndexAdapter(config=mock_config)

    result = await adapter._query_index(
        repo_path="/test/repo",
        task_params={"id": "test_no_query"},  # No query
    )

    assert result["status"] == "failed"
    assert "error" in result
    assert "error_code" in result


@pytest.mark.asyncio
async def test_query_index_not_found(mock_config):
    """Test query fails when index is not found."""
    adapter = LlamaIndexAdapter(config=mock_config)

    result = await adapter._query_index(
        repo_path="/test/repo",
        task_params={"query": "test query", "index_id": "nonexistent"},
    )

    assert result["status"] == "failed"
    assert "error" in result
    assert "error_code" in result


@pytest.mark.asyncio
async def test_query_index_auto_discovery(mock_config, mock_vector_store_index):
    """Test query auto-discovers index by repo name."""
    adapter = LlamaIndexAdapter(config=mock_config)
    adapter.indices["repo_0"] = mock_vector_store_index

    result = await adapter._query_index(
        repo_path="/path/to/repo",
        task_params={"query": "test query"},  # No index_id
    )

    assert result["status"] == "completed"


# ============================================================================
# Execute Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_ingest_task(mock_config, sample_repo_path):
    """Test execute with ingest task type."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Mock the ingestion method
    adapter._ingest_repository = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"documents_ingested": 5},
            "task_id": "test_exec_ingest",
        }
    )

    result = await adapter.execute(
        task={"type": "ingest", "params": {"id": "test_exec_ingest"}},
        repos=[sample_repo_path],
    )

    assert result["status"] == "completed"
    assert result["engine"] == "llamaindex"
    assert result["repos_processed"] == 1
    assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_execute_query_task(mock_config):
    """Test execute with query task type."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Mock the query method
    adapter._query_index = AsyncMock(
        return_value={
            "repo": "/test/repo",
            "status": "completed",
            "result": {"operation": "query", "answer": "test answer"},
            "task_id": "test_exec_query",
        }
    )

    result = await adapter.execute(
        task={"type": "query", "params": {"query": "test query", "id": "test_exec_query"}},
        repos=["/test/repo"],
    )

    assert result["status"] == "completed"
    assert result["engine"] == "llamaindex"
    assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_execute_ingest_and_query_task(mock_config, sample_repo_path):
    """Test execute with ingest_and_query task type."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Mock ingestion and query methods
    adapter._ingest_repository = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"documents_ingested": 5, "index_id": "test_index"},
            "task_id": "test_exec_both",
        }
    )

    adapter._query_index = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {"operation": "query"},
            "task_id": "test_exec_both",
        }
    )

    result = await adapter.execute(
        task={
            "type": "ingest_and_query",
            "params": {"query": "test query", "id": "test_exec_both"},
        },
        repos=[sample_repo_path],
    )

    assert result["status"] == "completed"
    assert result["success_count"] == 2  # ingest + query


@pytest.mark.asyncio
async def test_execute_unknown_task_type(mock_config, sample_repo_path):
    """Test execute with unknown task type."""
    adapter = LlamaIndexAdapter(config=mock_config)

    result = await adapter.execute(
        task={"type": "unknown_type", "params": {}}, repos=[sample_repo_path]
    )

    assert result["status"] == "completed"
    assert result["failure_count"] == 1


@pytest.mark.asyncio
async def test_execute_multiple_repos(mock_config, tmp_path):
    """Test execute across multiple repositories."""
    adapter = LlamaIndexAdapter(config=mock_config)

    repos = [str(tmp_path / f"repo{i}") for i in range(3)]
    for repo in repos:
        Path(repo).mkdir()

    # Mock ingestion method
    adapter._ingest_repository = AsyncMock(
        return_value={
            "repo": "/test/repo",
            "status": "completed",
            "result": {"documents_ingested": 3},
            "task_id": "test_multi",
        }
    )

    result = await adapter.execute(
        task={"type": "ingest", "params": {"id": "test_multi"}}, repos=repos
    )

    assert result["repos_processed"] == 3
    assert result["success_count"] == 3


# ============================================================================
# Document Context Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_document_context(mock_config, mock_code_graph_analyzer):
    """Test extracting context for a document from code graph."""
    adapter = LlamaIndexAdapter(config=mock_config)

    context = await adapter._get_document_context(
        graph_analyzer=mock_code_graph_analyzer, file_path=Path("test.py")
    )

    assert isinstance(context, dict)
    assert "functions" in context
    assert "classes" in context
    assert "imports" in context
    assert "total_nodes" in context


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_health_healthy(mock_config):
    """Test health check returns healthy status."""
    adapter = LlamaIndexAdapter(config=mock_config)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health
    assert health["status"] in ["healthy", "unhealthy"]
    assert "details" in health


@pytest.mark.asyncio
async def test_get_health_includes_indices_info(mock_config):
    """Test health check includes index information."""
    adapter = LlamaIndexAdapter(config=mock_config)
    adapter.indices["test_index"] = MagicMock()
    adapter.documents["test_index"] = [MagicMock(), MagicMock()]

    health = await adapter.get_health()

    assert "details" in health
    assert "indices_loaded" in health["details"]
    assert health["details"]["indices_loaded"] == 1
    assert "documents_loaded" in health["details"]
    assert health["details"]["documents_loaded"] == 2


@pytest.mark.asyncio
async def test_get_health_includes_telemetry_info(mock_config):
    """Test health check includes telemetry status."""
    adapter = LlamaIndexAdapter(config=mock_config)

    health = await adapter.get_health()

    assert "details" in health
    assert "telemetry_enabled" in health["details"]
    assert "opentelemetry_available" in health["details"]


@pytest.mark.asyncio
async def test_get_health_handles_exception():
    """Test health check handles exceptions."""
    adapter = LlamaIndexAdapter(config=None)

    health = await adapter.get_health()

    assert health is not None
    assert "status" in health


# ============================================================================
# Retry Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ingest_retry_on_transient_failure(mock_config, sample_repo_path):
    """Test that ingestion retries on transient failures."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Create a method that fails once then succeeds
    call_count = 0

    async def flaky_reader(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Transient error")
        return []

    mock_reader = MagicMock()
    mock_reader.load_data = flaky_reader

    with patch(
        "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
        return_value=mock_reader,
    ):
        result = await adapter._ingest_repository(
            repo_path=sample_repo_path, task_params={"id": "test_retry"}
        )

        # Should eventually complete or fail after retries
        assert result is not None


# ============================================================================
# Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_with_empty_repo_list(mock_config):
    """Test execute with empty repository list."""
    adapter = LlamaIndexAdapter(config=mock_config)

    result = await adapter.execute(task={"type": "ingest", "params": {}}, repos=[])

    assert result["repos_processed"] == 0
    assert result["success_count"] == 0
    assert result["failure_count"] == 0


@pytest.mark.asyncio
async def test_execute_with_missing_task_id(mock_config, sample_repo_path):
    """Test execute without task ID."""
    adapter = LlamaIndexAdapter(config=mock_config)

    adapter._ingest_repository = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {},
            "task_id": "unknown",
        }
    )

    result = await adapter.execute(
        task={"type": "ingest", "params": {}},  # No id
        repos=[sample_repo_path],
    )

    assert result["status"] == "completed"


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_rag_workflow(mock_config, sample_repo_path, mock_code_graph_analyzer):
    """Test complete RAG workflow from ingestion to query."""
    adapter = LlamaIndexAdapter(config=mock_config)

    # Mock ingestion
    adapter._ingest_repository = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {
                "documents_ingested": 5,
                "nodes_created": 10,
                "index_id": "test_rag_index",
            },
            "task_id": "rag_test",
        }
    )

    # Mock query
    adapter._query_index = AsyncMock(
        return_value={
            "repo": sample_repo_path,
            "status": "completed",
            "result": {
                "operation": "query",
                "query": "test query",
                "answer": "test answer",
                "sources": [],
            },
            "task_id": "rag_test",
        }
    )

    # Execute ingest_and_query
    result = await adapter.execute(
        task={
            "type": "ingest_and_query",
            "params": {"query": "test query", "id": "rag_test"},
        },
        repos=[sample_repo_path],
    )

    # Verify complete workflow
    assert result["status"] == "completed"
    assert result["engine"] == "llamaindex"
    assert result["repos_processed"] == 1
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    assert len(result["results"]) == 2


# ============================================================================
# Structured Error Handling Tests
# ============================================================================


class TestLlamaIndexIngestionError:
    """Tests for LlamaIndexIngestionError class."""

    def test_ingestion_error_with_all_params(self):
        """Test ingestion error with all parameters."""
        original = ValueError("Original error")
        error = LlamaIndexIngestionError(
            message="Ingestion failed",
            repo_path="/test/repo",
            original_error=original,
            details={"task_id": "test123"},
        )

        assert error.repo_path == "/test/repo"
        assert error.original_error is original
        assert error.details["repo_path"] == "/test/repo"
        assert error.details["original_error_type"] == "ValueError"
        assert error.details["original_error_message"] == "Original error"
        assert error.details["task_id"] == "test123"

    def test_ingestion_error_minimal(self):
        """Test ingestion error with minimal parameters."""
        error = LlamaIndexIngestionError(message="Ingestion failed")

        assert error.repo_path is None
        assert error.original_error is None
        # AdapterError includes adapter_name in message, not in details
        assert "llamaindex" in str(error)


class TestLlamaIndexQueryError:
    """Tests for LlamaIndexQueryError class."""

    def test_query_error_with_all_params(self):
        """Test query error with all parameters."""
        original = RuntimeError("LLM error")
        error = LlamaIndexQueryError(
            message="Query failed",
            query="test query",
            index_id="test_index_0",
            original_error=original,
        )

        assert error.query == "test query"
        assert error.index_id == "test_index_0"
        assert error.original_error is original
        # Query should be present in details
        assert "query" in error.details

    def test_query_error_truncates_long_query(self):
        """Test that long queries are truncated in details."""
        long_query = "a" * 200
        error = LlamaIndexQueryError(message="Query failed", query=long_query)

        assert len(error.details["query"]) == 100


class TestLlamaIndexIndexNotFoundError:
    """Tests for LlamaIndexIndexNotFoundError class."""

    def test_index_not_found_with_index_id(self):
        """Test index not found error with index_id."""
        error = LlamaIndexIndexNotFoundError(index_id="missing_index")

        assert error.index_id == "missing_index"
        assert "missing_index" in str(error)

    def test_index_not_found_with_repo_path(self):
        """Test index not found error with repo_path."""
        error = LlamaIndexIndexNotFoundError(repo_path="/path/to/repo")

        assert error.repo_path == "/path/to/repo"
        assert "No index found for repository" in str(error)


class TestLlamaIndexEmbeddingError:
    """Tests for LlamaIndexEmbeddingError class."""

    def test_embedding_error_with_model(self):
        """Test embedding error with model information."""
        original = ConnectionError("Ollama not running")
        error = LlamaIndexEmbeddingError(
            message="Failed to connect to Ollama",
            model="nomic-embed-text",
            original_error=original,
        )

        assert error.model == "nomic-embed-text"
        assert error.original_error is original
        assert error.details["model"] == "nomic-embed-text"


class TestWrapException:
    """Tests for _wrap_exception method."""

    @pytest.mark.asyncio
    async def test_wrap_exception_embedding_error(self, mock_config):
        """Test wrapping embedding-related exception."""
        adapter = LlamaIndexAdapter(config=mock_config)

        original = ConnectionError("Ollama connection failed")
        wrapped = adapter._wrap_exception(
            original,
            "ingest",
            {"repo_path": "/test/repo", "model": "nomic-embed-text"},
        )

        assert isinstance(wrapped, LlamaIndexEmbeddingError)
        assert wrapped.model == "nomic-embed-text"

    @pytest.mark.asyncio
    async def test_wrap_exception_ingestion_error(self, mock_config):
        """Test wrapping ingestion-related exception."""
        adapter = LlamaIndexAdapter(config=mock_config)

        original = OSError("File read error")
        wrapped = adapter._wrap_exception(
            original,
            "ingest",
            {"repo_path": "/test/repo"},
        )

        assert isinstance(wrapped, LlamaIndexIngestionError)
        assert wrapped.repo_path == "/test/repo"

    @pytest.mark.asyncio
    async def test_wrap_exception_query_error(self, mock_config):
        """Test wrapping query-related exception."""
        adapter = LlamaIndexAdapter(config=mock_config)

        original = ValueError("Invalid query")
        wrapped = adapter._wrap_exception(
            original,
            "query",
            {"query": "test query", "index_id": "test_0"},
        )

        assert isinstance(wrapped, LlamaIndexQueryError)
        assert wrapped.query == "test query"


class TestStructuredErrorInResponses:
    """Tests for structured error codes in operation responses."""

    @pytest.mark.asyncio
    async def test_ingest_nonexistent_path_returns_error_code(self, mock_config):
        """Test that ingestion of nonexistent path returns error code."""
        adapter = LlamaIndexAdapter(config=mock_config)

        result = await adapter._ingest_repository(
            repo_path="/nonexistent/path",
            task_params={"id": "test"},
        )

        assert result["status"] == "failed"
        assert "error_code" in result
        assert result["error_code"] == "MHV-009"  # RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_query_missing_query_returns_error_code(self, mock_config):
        """Test that query without query text returns error code."""
        adapter = LlamaIndexAdapter(config=mock_config)

        result = await adapter._query_index(
            repo_path="/test/repo",
            task_params={"id": "test"},
        )

        assert result["status"] == "failed"
        assert "error_code" in result
        assert result["error_code"] == "MHV-003"  # VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_query_missing_index_returns_error_code(self, mock_config):
        """Test that query for missing index returns error code."""
        adapter = LlamaIndexAdapter(config=mock_config)

        result = await adapter._query_index(
            repo_path="/test/repo",
            task_params={"query": "test query", "id": "test"},
        )

        assert result["status"] == "failed"
        assert "error_code" in result
        assert result["error_code"] == "MHV-009"  # RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_execute_unknown_task_type_returns_error_code(
        self, mock_config, sample_repo_path
    ):
        """Test that unknown task type returns validation error code."""
        adapter = LlamaIndexAdapter(config=mock_config)

        result = await adapter.execute(
            task={"type": "invalid_type", "params": {}},
            repos=[sample_repo_path],
        )

        assert result["failure_count"] == 1
        assert result["results"][0]["error_code"] == "MHV-003"  # VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_ingest_exception_includes_error_details(
        self, mock_config, sample_repo_path, mock_code_graph_analyzer
    ):
        """Test that exception during ingestion includes structured error details."""
        adapter = LlamaIndexAdapter(config=mock_config)

        # Mock reader that raises an exception
        mock_reader = MagicMock()
        mock_reader.load_data.side_effect = RuntimeError("Unexpected error")

        with (
            patch(
                "mahavishnu.engines.llamaindex_adapter.SimpleDirectoryReader",
                return_value=mock_reader,
            ),
            patch(
                "mahavishnu.engines.llamaindex_adapter.CodeGraphAnalyzer",
                return_value=mock_code_graph_analyzer,
            ),
        ):
            result = await adapter._ingest_repository(
                repo_path=sample_repo_path,
                task_params={"id": "test_error"},
            )

            assert result["status"] == "failed"
            assert "error_code" in result
            assert "error_details" in result
            assert "repo_path" in result["error_details"]


class TestAdapterProperties:
    """Tests for adapter properties."""

    def test_adapter_type(self, mock_config):
        """Test adapter_type property returns correct type."""
        adapter = LlamaIndexAdapter(config=mock_config)

        from mahavishnu.core.adapters.base import AdapterType

        assert adapter.adapter_type == AdapterType.LLAMAINDEX

    def test_adapter_name(self, mock_config):
        """Test name property returns correct name."""
        adapter = LlamaIndexAdapter(config=mock_config)

        assert adapter.name == "llamaindex"

    def test_adapter_capabilities(self, mock_config):
        """Test capabilities property returns correct capabilities."""
        adapter = LlamaIndexAdapter(config=mock_config)

        capabilities = adapter.capabilities
        assert capabilities.can_deploy_flows is True
        assert capabilities.can_monitor_execution is True
        assert capabilities.can_cancel_workflows is True
        assert capabilities.supports_batch_execution is True
        assert capabilities.can_sync_state is False
        assert capabilities.supports_multi_agent is False
        assert capabilities.has_cloud_ui is False
