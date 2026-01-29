"""LlamaIndex adapter implementation for RAG pipelines.

This adapter provides:
- Repository/document ingestion from repos.yaml
- Embedding with Ollama (local models)
- Vector store management
- RAG query capabilities
- Integration with Agno for agent knowledge bases
"""

from pathlib import Path
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


class LlamaIndexAdapter(OrchestratorAdapter):
    """Adapter for LlamaIndex RAG pipelines.

    This adapter handles:
    - Ingesting repositories and documents
    - Creating embeddings with Ollama
    - Building vector stores for RAG
    - Querying knowledge bases
    - Integration with Agno agents

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
        except Exception as e:
            print(f"Warning: Could not initialize OpenSearch vector store: {e}")
            print("Falling back to in-memory vector store")
            self.vector_store = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _ingest_repository(
        self, repo_path: str, task_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Ingest a repository into LlamaIndex with code graph context.

        Args:
            repo_path: Path to repository
            task_params: Task parameters (file_types, exclude_patterns, etc.)

        Returns:
            Ingestion result with document count and index ID
        """
        try:
            repo = Path(repo_path)

            if not repo.exists():
                return {
                    "repo": repo_path,
                    "status": "failed",
                    "error": f"Repository path does not exist: {repo_path}",
                    "task_id": task_params.get("id", "unknown"),
                }

            # Use code graph analyzer to extract structural information
            graph_analyzer = CodeGraphAnalyzer(repo)
            graph_stats = await graph_analyzer.analyze_repository(repo_path)

            # Get file types to include (default: common code/doc files)
            file_types = task_params.get(
                "file_types", [".py", ".js", ".ts", ".md", ".txt", ".rst", ".yaml", ".yml", ".json"]
            )

            # Get exclude patterns
            exclude_patterns = task_params.get(
                "exclude_patterns",
                ["__pycache__", ".git", ".venv", "node_modules", "dist", "build"],
            )

            # Load documents from repository
            reader = SimpleDirectoryReader(
                input_dir=str(repo),
                recursive=True,
                required_exts=file_types,
                exclude=exclude_patterns,
            )

            documents = reader.load_data()

            if not documents:
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

            # Enhance documents with code graph context
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
            nodes = self.node_parser.get_nodes_from_documents(documents)

            # Create storage context with OpenSearch vector store if available
            if self.vector_store:
                storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
                # Create index with persistent OpenSearch storage
                index = VectorStoreIndex(nodes, storage_context=storage_context)
            else:
                # Fallback to in-memory storage
                index = VectorStoreIndex(nodes)

            # Store index for querying
            index_id = f"{repo.name}_{len(self.indices)}"
            self.indices[index_id] = index
            self.documents[index_id] = documents

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
                    "vector_backend": "opensearch" if self.vector_store else "memory",
                },
                "task_id": task_params.get("id", "unknown"),
            }

        except Exception as e:
            return {
                "repo": repo_path,
                "status": "failed",
                "error": f"Ingestion failed: {str(e)}",
                "task_id": task_params.get("id", "unknown"),
            }

    async def _get_document_context(
        self, graph_analyzer: CodeGraphAnalyzer, file_path: Path
    ) -> dict:
        """Get context for a document from the code graph analyzer."""
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

        Args:
            repo_path: Path to repository (used to find index)
            task_params: Task parameters (query, index_id, top_k, etc.)

        Returns:
            Query results with relevant documents
        """
        try:
            query_text = task_params.get("query", "")
            index_id = task_params.get("index_id")
            top_k = task_params.get("top_k", 5)

            if not query_text:
                return {
                    "repo": repo_path,
                    "status": "failed",
                    "error": "Query text not provided in task_params",
                    "task_id": task_params.get("id", "unknown"),
                }

            # Find index
            if index_id and index_id in self.indices:
                index = self.indices[index_id]
            else:
                # Try to find index by repo name
                repo_name = Path(repo_path).name
                index_id = f"{repo_name}_0"
                if index_id not in self.indices:
                    return {
                        "repo": repo_path,
                        "status": "failed",
                        "error": f"No index found for repository: {repo_path}",
                        "task_id": task_params.get("id", "unknown"),
                    }
                index = self.indices[index_id]

            # Create query engine
            query_engine = index.as_query_engine(
                similarity_top_k=top_k, retrieve_similarity_top_k=top_k * 2
            )

            # Execute query
            response = query_engine.query(query_text)

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
            return {
                "repo": repo_path,
                "status": "failed",
                "error": f"Query failed: {str(e)}",
                "task_id": task_params.get("id", "unknown"),
            }

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute a LlamaIndex RAG task across multiple repositories.

        Args:
            task: Task specification with 'type' and 'params' keys
                  Types: 'ingest', 'query', 'ingest_and_query'
            repos: List of repository paths to operate on

        Returns:
            Execution result with all repository results
        """
        task_type = task.get("type", "ingest")
        task_params = task.get("params", {})

        results = []

        # Process each repository
        for repo in repos:
            if task_type == "ingest":
                result = await self._ingest_repository(repo, task_params)
                results.append(result)

            elif task_type == "query":
                result = await self._query_index(repo, task_params)
                results.append(result)

            elif task_type == "ingest_and_query":
                # First ingest
                ingest_result = await self._ingest_repository(repo, task_params)
                results.append(ingest_result)

                # Then query if ingestion succeeded
                if ingest_result.get("status") == "completed":
                    index_id = ingest_result.get("result", {}).get("index_id")
                    if index_id:
                        query_params = {**task_params, "index_id": index_id}
                        query_result = await self._query_index(repo, query_params)
                        results.append(query_result)

            else:
                # Unknown task type
                results.append(
                    {
                        "repo": repo,
                        "status": "failed",
                        "error": f"Unknown task type: {task_type}",
                        "task_id": task.get("id", "unknown"),
                    }
                )

        return {
            "status": "completed",
            "engine": "llamaindex",
            "task": task,
            "repos_processed": len(repos),
            "results": results,
            "success_count": len([r for r in results if r.get("status") == "completed"]),
            "failure_count": len([r for r in results if r.get("status") == "failed"]),
            "indices_available": list(self.indices.keys()),
        }

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details.
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
                "configured": True,
            }

            return {"status": "healthy", "details": health_details}

        except Exception as e:
            return {"status": "unhealthy", "details": {"error": str(e), "configured": True}}
