"""LlamaIndex adapter implementation for RAG pipelines.

This adapter provides:
- Repository/document ingestion from ecosystem.yaml
- Embedding with Ollama (local models)
- Vector store management
- RAG query capabilities
- Integration with Agno for agent knowledge bases
- OpenTelemetry instrumentation for tracing and metrics
"""

from pathlib import Path
import time
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from llama_index.core import Document, SimpleDirectoryReader, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.settings import Settings
    from llama_index.core.storage.storage_context import StorageContext
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.llms.ollama import Ollama
    from llama_index.vector_stores.opensearch import OpensearchVectorStore

    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

# Import code graph analyzer
from mcp_common.code_graph import CodeGraphAnalyzer

from ..core.adapters.base import OrchestratorAdapter

# Try to import OpenTelemetry components
try:
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.resources import Resource

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

    # Define minimal fallback classes for graceful degradation
    class MockCounter:
        def add(self, amount: int, attributes: dict[str, str] = None):
            pass

    class MockHistogram:
        def record(self, amount: float, attributes: dict[str, str] = None):
            pass

    class MockTracer:
        def start_as_current_span(self, name: str, attributes: dict[str, str] = None):
            class MockSpan:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def set_attribute(self, key: str, value: str | int | float | bool):
                    pass

                def set_status(self, status):
                    pass

                def record_exception(self, exception):
                    pass

            return MockSpan()

    class MockMeter:
        def create_counter(self, name: str, **kwargs) -> MockCounter:
            return MockCounter()

        def create_histogram(self, name: str, **kwargs) -> MockHistogram:
            return MockHistogram()

    class MockTraceProvider:
        def get_tracer(self, name: str, version: str = None) -> MockTracer:
            return MockTracer()

    class MockMeterProvider:
        def get_meter(self, name: str, version: str = None) -> MockMeter:
            return MockMeter()


class LlamaIndexAdapter(OrchestratorAdapter):
    """Adapter for LlamaIndex RAG pipelines with OpenTelemetry instrumentation.

    This adapter handles:
    - Ingesting repositories and documents
    - Creating embeddings with Ollama
    - Building vector stores for RAG
    - Querying knowledge bases
    - Integration with Agno agents
    - Distributed tracing with OpenTelemetry
    - Metrics for operations and performance

    Example:
        >>> adapter = LlamaIndexAdapter(config)
        >>> result = await adapter.execute({
        ...     "type": "ingest",
        ...     "params": {"repo_path": "/path/to/repo"}
        ... }, [])
    """

    def __init__(self, config):
        """Initialize the LlamaIndex adapter with configuration.

        Args:
            config: Mahavishnu configuration object

        Raises:
            ImportError: If LlamaIndex dependencies are not available
        """
        if not LLAMAINDEX_AVAILABLE:
            raise ImportError(
                "LlamaIndex dependencies not available. "
                "Install with: pip install 'mahavishnu[llamaindex]'"
            )

        self.config = config
        self.indices: dict[str, VectorStoreIndex] = {}
        self.documents: dict[str, list[Document]] = {}

        # Configure Ollama embedding model
        ollama_model = getattr(config, "llm_model", "nomic-embed-text")
        ollama_base_url = getattr(config, "ollama_base_url", "http://localhost:11434")

        # Configure LlamaIndex settings
        Settings.embed_model = OllamaEmbedding(model_name=ollama_model, base_url=ollama_base_url)
        Settings.llm = Ollama(model=ollama_model, base_url=ollama_base_url)

        # Configure node parser for chunking
        self.node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=20, separator=" ")

        # Initialize OpenSearch vector store with security settings
        try:
            self.vector_store = OpensearchVectorStore(
                endpoint=getattr(config, "opensearch_endpoint", "https://localhost:9200"),
                index_name=getattr(config, "opensearch_index_name", "mahavishnu_code"),
                dim=1536,  # Standard for text-embedding-ada-002
                verify_certs=getattr(config, "opensearch_verify_certs", True),
                ca_certs=getattr(config, "opensearch_ca_certs", None),
                use_ssl=getattr(config, "opensearch_use_ssl", True),
                ssl_assert_hostname=getattr(config, "opensearch_ssl_assert_hostname", True),
                ssl_show_warn=getattr(config, "opensearch_ssl_show_warn", True),
            )
            self._vector_backend = "opensearch"
        except Exception as e:
            print(f"Warning: Could not initialize OpenSearch vector store: {e}")
            print("Falling back to in-memory vector store")
            self.vector_store = None
            self._vector_backend = "memory"

        # Initialize OpenTelemetry instrumentation
        self._init_otel_instrumentation()

    def _init_otel_instrumentation(self):
        """Initialize OpenTelemetry components for tracing and metrics.

        Uses fallback no-op implementations if OpenTelemetry is not available.
        """
        try:
            if OTEL_AVAILABLE and getattr(self.config, "metrics_enabled", False):
                # Create resource for this adapter
                Resource.create({"service.name": "mahavishnu-llamaindex"})

                # Get tracer and meter providers
                tracer_provider = trace.get_tracer_provider()
                meter_provider = metrics.get_meter_provider()

                self.tracer = tracer_provider.get_tracer("mahavishnu.llamaindex", "1.0.0")
                self.meter = meter_provider.get_meter("mahavishnu.llamaindex", "1.0.0")

                # Create metric instruments
                self.ingest_duration_histogram = self.meter.create_histogram(
                    "llamaindex.ingest.duration",
                    description="Duration of document ingestion operations in seconds",
                    unit="s",
                )

                self.query_duration_histogram = self.meter.create_histogram(
                    "llamaindex.query.duration",
                    description="Duration of query operations in seconds",
                    unit="s",
                )

                self.documents_counter = self.meter.create_counter(
                    "llamaindex.documents.count",
                    description="Number of documents ingested",
                )

                self.nodes_counter = self.meter.create_counter(
                    "llamaindex.nodes.count",
                    description="Number of nodes created from documents",
                )

                self.query_counter = self.meter.create_counter(
                    "llamaindex.queries.count",
                    description="Number of queries executed",
                )

                self.error_counter = self.meter.create_counter(
                    "llamaindex.errors.count",
                    description="Number of errors encountered",
                )

                self.index_counter = self.meter.create_counter(
                    "llamaindex.indexes.count",
                    description="Number of indexes created",
                )
            else:
                self._init_fallback_instrumentation()

        except Exception as e:
            print(f"Warning: Failed to initialize OpenTelemetry instrumentation: {e}")
            self._init_fallback_instrumentation()

    def _init_fallback_instrumentation(self):
        """Initialize fallback no-op instrumentation when OTel is unavailable."""
        self.tracer = MockTracer()
        self.meter = MockMeter()

        # Create fallback metric instruments
        self.ingest_duration_histogram = self.meter.create_histogram("llamaindex.ingest.duration")
        self.query_duration_histogram = self.meter.create_histogram("llamaindex.query.duration")
        self.documents_counter = self.meter.create_counter("llamaindex.documents.count")
        self.nodes_counter = self.meter.create_counter("llamaindex.nodes.count")
        self.query_counter = self.meter.create_counter("llamaindex.queries.count")
        self.error_counter = self.meter.create_counter("llamaindex.errors.count")
        self.index_counter = self.meter.create_counter("llamaindex.indexes.count")

    def _truncate_query(self, query: str, max_length: int = 100) -> str:
        """Truncate query text for span attributes to avoid excessive size.

        Args:
            query: Query text to truncate
            max_length: Maximum length for truncated query

        Returns:
            Truncated query with ellipsis if needed
        """
        if len(query) <= max_length:
            return query
        return query[:max_length] + "..."

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _ingest_repository(
        self, repo_path: str, task_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Ingest a repository into LlamaIndex with code graph context.

        This method is instrumented with OpenTelemetry tracing and metrics:
        - Span: 'llamaindex.ingest' with repo path and configuration attributes
        - Metric: ingest_duration_histogram (seconds)
        - Metric: documents_counter (total documents ingested)
        - Metric: nodes_counter (total nodes created)
        - Metric: error_counter (incremented on errors)

        Args:
            repo_path: Path to repository
            task_params: Task parameters (file_types, exclude_patterns, etc.)

        Returns:
            Ingestion result with document count and index ID
        """
        # Start span for ingestion operation
        with self.tracer.start_as_current_span(
            "llamaindex.ingest",
            attributes={
                "repo.path": repo_path,
                "repo.name": Path(repo_path).name,
                "llamaindex.operation": "ingest",
                "vector.backend": self._vector_backend,
            },
        ) as span:
            start_time = time.time()

            try:
                repo = Path(repo_path)

                if not repo.exists():
                    error_msg = f"Repository path does not exist: {repo_path}"
                    span.set_attribute("error.message", error_msg)
                    span.set_status("ERROR")
                    self.error_counter.add(
                        1,
                        attributes={
                            "operation": "ingest",
                            "error_type": "path_not_found",
                            "repo.path": repo_path,
                        },
                    )
                    return {
                        "repo": repo_path,
                        "status": "failed",
                        "error": error_msg,
                        "task_id": task_params.get("id", "unknown"),
                    }

                # Use code graph analyzer to extract structural information
                graph_analyzer = CodeGraphAnalyzer(repo)
                graph_stats = await graph_analyzer.analyze_repository(repo_path)

                # Add graph stats to span
                span.set_attribute("code_graph.nodes", graph_stats.get("total_nodes", 0))
                span.set_attribute("code_graph.functions", graph_stats.get("total_functions", 0))
                span.set_attribute("code_graph.classes", graph_stats.get("total_classes", 0))

                # Get file types to include (default: common code/doc files)
                file_types = task_params.get(
                    "file_types",
                    [".py", ".js", ".ts", ".md", ".txt", ".rst", ".yaml", ".yml", ".json"],
                )
                span.set_attribute("ingest.file_types", ",".join(file_types))

                # Get exclude patterns
                exclude_patterns = task_params.get(
                    "exclude_patterns",
                    ["__pycache__", ".git", ".venv", "node_modules", "dist", "build"],
                )
                span.set_attribute("ingest.exclude_patterns", ",".join(exclude_patterns))

                # Load documents from repository
                reader = SimpleDirectoryReader(
                    input_dir=str(repo),
                    recursive=True,
                    required_exts=file_types,
                    exclude=exclude_patterns,
                )

                documents = reader.load_data()

                if not documents:
                    span.set_attribute("ingest.documents_count", 0)
                    span.set_attribute("ingest.status", "no_documents")
                    return {
                        "repo": repo_path,
                        "status": "completed",
                        "result": {
                            "operation": "ingest",
                            "documents_ingested": 0,
                            "index_id": None,
                            "message": "No matching documents found",
                            "graph_stats": graph_stats,
                        },
                        "task_id": task_params.get("id", "unknown"),
                    }

                span.set_attribute("ingest.documents_count", len(documents))

                # Enhance documents with code graph context
                with self.tracer.start_as_current_span(
                    "llamaindex.enhance_documents", attributes={"doc.count": len(documents)}
                ):
                    for doc in documents:
                        file_path = Path(doc.metadata.get("file_path", ""))
                        if file_path.exists():
                            # Add code graph context to document metadata
                            file_functions = [
                                node
                                for node_id, node in graph_analyzer.nodes.items()
                                if hasattr(node, "file_id") and Path(node.file_id) == file_path
                            ]

                            # Get context for the document
                            context = await self._get_document_context(graph_analyzer, file_path)

                            doc.metadata.update(
                                {
                                    "code_graph": context,
                                    "functions": context.get("functions", []),
                                    "classes": context.get("classes", []),
                                    "functions_count": len(
                                        [n for n in file_functions if hasattr(n, "name")]
                                    ),
                                    "related_files": await graph_analyzer.find_related_files(
                                        str(file_path)
                                    ),
                                }
                            )

                # Parse documents into nodes
                with self.tracer.start_as_current_span("llamaindex.parse_nodes") as parse_span:
                    nodes = self.node_parser.get_nodes_from_documents(documents)
                    parse_span.set_attribute("nodes.count", len(nodes))

                # Create storage context with OpenSearch vector store if available
                with self.tracer.start_as_current_span(
                    "llamaindex.create_index", attributes={"vector.backend": self._vector_backend}
                ) as create_span:
                    if self.vector_store:
                        storage_context = StorageContext.from_defaults(
                            vector_store=self.vector_store
                        )
                        # Create index with persistent OpenSearch storage
                        index = VectorStoreIndex(nodes, storage_context=storage_context)
                    else:
                        # Fallback to in-memory storage
                        index = VectorStoreIndex(nodes)

                    create_span.set_attribute("index.nodes_count", len(nodes))

                # Store index for querying
                index_id = f"{repo.name}_{len(self.indices)}"
                self.indices[index_id] = index
                self.documents[index_id] = documents

                # Record metrics
                duration = time.time() - start_time
                self.ingest_duration_histogram.record(
                    duration,
                    attributes={
                        "repo.path": repo_path,
                        "repo.name": repo.name,
                        "vector.backend": self._vector_backend,
                    },
                )
                self.documents_counter.add(
                    len(documents), attributes={"repo.path": repo_path, "repo.name": repo.name}
                )
                self.nodes_counter.add(
                    len(nodes), attributes={"repo.path": repo_path, "repo.name": repo.name}
                )
                self.index_counter.add(
                    1,
                    attributes={
                        "repo.path": repo_path,
                        "repo.name": repo.name,
                        "vector.backend": self._vector_backend,
                    },
                )

                # Add completion attributes to span
                span.set_attribute("ingest.duration_seconds", duration)
                span.set_attribute("ingest.nodes_count", len(nodes))
                span.set_attribute("ingest.index_id", index_id)
                span.set_attribute("ingest.status", "success")

                return {
                    "repo": repo_path,
                    "status": "completed",
                    "result": {
                        "operation": "ingest",
                        "documents_ingested": len(documents),
                        "nodes_created": len(nodes),
                        "index_id": index_id,
                        "embedding_model": getattr(self.config, "llm_model", "nomic-embed-text"),
                        "graph_stats": graph_stats,
                        "vector_backend": self._vector_backend,
                    },
                    "task_id": task_params.get("id", "unknown"),
                }

            except Exception as e:
                error_msg = f"Ingestion failed: {e}"

                # Record error in span
                span.set_attribute("error.message", error_msg)
                span.set_attribute("error.type", type(e).__name__)
                span.set_status("ERROR")
                span.record_exception(e)

                # Record error metric
                self.error_counter.add(
                    1,
                    attributes={
                        "operation": "ingest",
                        "error_type": type(e).__name__,
                        "repo.path": repo_path,
                    },
                )

                return {
                    "repo": repo_path,
                    "status": "failed",
                    "error": error_msg,
                    "task_id": task_params.get("id", "unknown"),
                }

    async def _get_document_context(
        self, graph_analyzer: CodeGraphAnalyzer, file_path: Path
    ) -> dict:
        """Get context for a document from the code graph analyzer.

        Args:
            graph_analyzer: Code graph analyzer instance
            file_path: Path to the document file

        Returns:
            Dictionary with functions, classes, imports, and node counts
        """
        # Get all nodes associated with this file
        file_nodes = [
            node
            for node_id, node in graph_analyzer.nodes.items()
            if hasattr(node, "file_id") and Path(node.file_id) == file_path
        ]

        # Separate nodes by type
        functions = [
            {
                "name": node.name,
                "start_line": getattr(node, "start_line", 0),
                "end_line": getattr(node, "end_line", 0),
                "is_export": getattr(node, "is_export", False),
                "calls": getattr(node, "calls", []),
            }
            for node in file_nodes
            if hasattr(node, "start_line") and hasattr(node, "name")
        ]

        classes = [
            {
                "name": node.name,
                "methods": getattr(node, "methods", []),
                "inherits_from": getattr(node, "inherits_from", []),
            }
            for node in file_nodes
            if hasattr(node, "methods") and hasattr(node, "name")
        ]

        imports = [
            {
                "name": node.name,
                "imported_from": getattr(node, "imported_from", ""),
                "alias": getattr(node, "alias", None),
            }
            for node in file_nodes
            if hasattr(node, "imported_from")
        ]

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "total_nodes": len(file_nodes),
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _query_index(self, repo_path: str, task_params: dict[str, Any]) -> dict[str, Any]:
        """Query a LlamaIndex vector store with code graph context.

        This method is instrumented with OpenTelemetry tracing and metrics:
        - Span: 'llamaindex.query' with query text and result attributes
        - Metric: query_duration_histogram (seconds)
        - Metric: query_counter (total queries executed)
        - Metric: error_counter (incremented on errors)

        Args:
            repo_path: Path to repository (used to find index)
            task_params: Task parameters (query, index_id, top_k, etc.)

        Returns:
            Query results with relevant documents
        """
        query_text = task_params.get("query", "")
        index_id = task_params.get("index_id")
        top_k = task_params.get("top_k", 5)

        # Start span for query operation
        with self.tracer.start_as_current_span(
            "llamaindex.query",
            attributes={
                "repo.path": repo_path,
                "repo.name": Path(repo_path).name,
                "query.text": self._truncate_query(query_text),
                "query.top_k": top_k,
                "vector.backend": self._vector_backend,
            },
        ) as span:
            start_time = time.time()

            try:
                if not query_text:
                    error_msg = "Query text not provided in task_params"
                    span.set_attribute("error.message", error_msg)
                    span.set_status("ERROR")
                    self.error_counter.add(
                        1,
                        attributes={
                            "operation": "query",
                            "error_type": "missing_query",
                            "repo.path": repo_path,
                        },
                    )
                    return {
                        "repo": repo_path,
                        "status": "failed",
                        "error": error_msg,
                        "task_id": task_params.get("id", "unknown"),
                    }

                # Find index
                with self.tracer.start_as_current_span("llamaindex.find_index") as find_span:
                    if index_id and index_id in self.indices:
                        index = self.indices[index_id]
                        find_span.set_attribute("index.found", True)
                        find_span.set_attribute("index.id", index_id)
                    else:
                        # Try to find index by repo name
                        repo_name = Path(repo_path).name
                        index_id = f"{repo_name}_0"
                        if index_id not in self.indices:
                            error_msg = f"No index found for repository: {repo_path}"
                            find_span.set_attribute("index.found", False)
                            find_span.set_attribute("error.message", error_msg)
                            span.set_status("ERROR")
                            self.error_counter.add(
                                1,
                                attributes={
                                    "operation": "query",
                                    "error_type": "index_not_found",
                                    "repo.path": repo_path,
                                },
                            )
                            return {
                                "repo": repo_path,
                                "status": "failed",
                                "error": error_msg,
                                "task_id": task_params.get("id", "unknown"),
                            }
                        index = self.indices[index_id]
                        find_span.set_attribute("index.found", True)
                        find_span.set_attribute("index.id", index_id)

                # Create query engine
                query_engine = index.as_query_engine(
                    similarity_top_k=top_k, retrieve_similarity_top_k=top_k * 2
                )

                # Execute query
                with self.tracer.start_as_current_span("llamaindex.execute_query") as exec_span:
                    response = query_engine.query(query_text)
                    exec_span.set_attribute("response.sources_count", len(response.source_nodes))

                # Process sources with enhanced code graph context
                sources = []
                for source in response.source_nodes:
                    source_info = {
                        "file": source.metadata.get("file_name", "unknown"),
                        "content": source.node.get_content(),
                        "score": getattr(source, "score", None),  # Similarity score if available
                    }

                    # Add code graph context if available
                    if "code_graph" in source.metadata:
                        source_info["code_graph"] = source.metadata["code_graph"]

                    if "functions" in source.metadata:
                        source_info["functions"] = source.metadata["functions"]

                    if "classes" in source.metadata:
                        source_info["classes"] = source.metadata["classes"]

                    if "related_files" in source.metadata:
                        source_info["related_files"] = source.metadata["related_files"]

                    sources.append(source_info)

                # Record metrics
                duration = time.time() - start_time
                self.query_duration_histogram.record(
                    duration,
                    attributes={
                        "repo.path": repo_path,
                        "repo.name": Path(repo_path).name,
                        "vector.backend": self._vector_backend,
                        "query.top_k": top_k,
                    },
                )
                self.query_counter.add(
                    1,
                    attributes={
                        "repo.path": repo_path,
                        "repo.name": Path(repo_path).name,
                        "vector.backend": self._vector_backend,
                    },
                )

                # Add completion attributes to span
                span.set_attribute("query.duration_seconds", duration)
                span.set_attribute("query.sources_count", len(sources))
                span.set_attribute("query.status", "success")

                return {
                    "repo": repo_path,
                    "status": "completed",
                    "result": {
                        "operation": "query",
                        "query": query_text,
                        "answer": str(response),
                        "sources": sources,
                        "index_id": index_id,
                        "total_sources": len(sources),
                    },
                    "task_id": task_params.get("id", "unknown"),
                }

            except Exception as e:
                error_msg = f"Query failed: {e}"

                # Record error in span
                span.set_attribute("error.message", error_msg)
                span.set_attribute("error.type", type(e).__name__)
                span.set_status("ERROR")
                span.record_exception(e)

                # Record error metric
                self.error_counter.add(
                    1,
                    attributes={
                        "operation": "query",
                        "error_type": type(e).__name__,
                        "repo.path": repo_path,
                    },
                )

                return {
                    "repo": repo_path,
                    "status": "failed",
                    "error": error_msg,
                    "task_id": task_params.get("id", "unknown"),
                }

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute a LlamaIndex RAG task across multiple repositories.

        This method is instrumented with OpenTelemetry tracing:
        - Span: 'llamaindex.execute' with task type and repository count
        - Child spans for each repository operation
        - Metrics recorded in child operations

        Args:
            task: Task specification with 'type' and 'params' keys
                  Types: 'ingest', 'query', 'ingest_and_query'
            repos: List of repository paths to operate on

        Returns:
            Execution result with all repository results
        """
        task_type = task.get("type", "ingest")
        task_params = task.get("params", {})

        # Start top-level span for execute operation
        with self.tracer.start_as_current_span(
            "llamaindex.execute",
            attributes={
                "task.type": task_type,
                "task.id": task_params.get("id", "unknown"),
                "repos.count": len(repos),
                "llamaindex.operation": "execute",
            },
        ) as span:
            results = []
            success_count = 0
            failure_count = 0

            # Process each repository
            for repo in repos:
                if task_type == "ingest":
                    result = await self._ingest_repository(repo, task_params)
                    results.append(result)
                    if result.get("status") == "completed":
                        success_count += 1
                    else:
                        failure_count += 1

                elif task_type == "query":
                    result = await self._query_index(repo, task_params)
                    results.append(result)
                    if result.get("status") == "completed":
                        success_count += 1
                    else:
                        failure_count += 1

                elif task_type == "ingest_and_query":
                    # First ingest
                    ingest_result = await self._ingest_repository(repo, task_params)
                    results.append(ingest_result)

                    if ingest_result.get("status") == "completed":
                        success_count += 1
                        # Then query if ingestion succeeded
                        index_id = ingest_result.get("result", {}).get("index_id")
                        if index_id:
                            query_params = {**task_params, "index_id": index_id}
                            query_result = await self._query_index(repo, query_params)
                            results.append(query_result)
                            if query_result.get("status") == "completed":
                                success_count += 1
                            else:
                                failure_count += 1
                    else:
                        failure_count += 1

                else:
                    # Unknown task type
                    failure_count += 1
                    results.append(
                        {
                            "repo": repo,
                            "status": "failed",
                            "error": f"Unknown task type: {task_type}",
                            "task_id": task.get("id", "unknown"),
                        }
                    )

            # Add completion attributes to span
            span.set_attribute("execute.success_count", success_count)
            span.set_attribute("execute.failure_count", failure_count)
            span.set_attribute(
                "execute.status", "success" if failure_count == 0 else "partial_failure"
            )

            return {
                "status": "completed",
                "engine": "llamaindex",
                "task": task,
                "repos_processed": len(repos),
                "results": results,
                "success_count": success_count,
                "failure_count": failure_count,
                "indices_available": list(self.indices.keys()),
            }

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details including telemetry status.
        """
        try:
            # Check Ollama availability
            ollama_base_url = getattr(self.config, "ollama_base_url", "http://localhost:11434")
            embedding_model = getattr(self.config, "llm_model", "nomic-embed-text")

            health_details = {
                "llamaindex_version": "0.14.x",
                "ollama_base_url": ollama_base_url,
                "embedding_model": embedding_model,
                "indices_loaded": len(self.indices),
                "documents_loaded": sum(len(docs) for docs in self.documents.values()),
                "vector_backend": self._vector_backend,
                "configured": True,
                "telemetry_enabled": OTEL_AVAILABLE
                and getattr(self.config, "metrics_enabled", False),
                "opentelemetry_available": OTEL_AVAILABLE,
            }

            return {"status": "healthy", "details": health_details}

        except Exception as e:
            return {"status": "unhealthy", "details": {"error": str(e), "configured": True}}
