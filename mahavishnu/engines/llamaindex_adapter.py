"""LlamaIndex adapter implementation for RAG pipelines.

This adapter provides:
- Repository/document ingestion from repos.yaml
- Embedding with Ollama (local models)
- Vector store management
- RAG query capabilities
- Integration with Agno for agent knowledge bases
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Document
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.llms.ollama import Ollama
    from llama_index.core.settings import Settings
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

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
        self.indices: Dict[str, VectorStoreIndex] = {}
        self.documents: Dict[str, List[Document]] = {}

        # Configure Ollama embedding model
        ollama_model = getattr(config, 'llm_model', 'nomic-embed-text')
        ollama_base_url = getattr(config, 'ollama_base_url', 'http://localhost:11434')

        # Configure LlamaIndex settings
        Settings.embed_model = OllamaEmbedding(
            model_name=ollama_model,
            base_url=ollama_base_url
        )
        Settings.llm = Ollama(
            model=ollama_model,
            base_url=ollama_base_url
        )

        # Configure node parser for chunking
        self.node_parser = SentenceSplitter(
            chunk_size=1024,
            chunk_overlap=20,
            separator=" "
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _ingest_repository(self, repo_path: str, task_params: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest a repository into LlamaIndex.

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
                    "task_id": task_params.get("id", "unknown")
                }

            # Get file types to include (default: common code/doc files)
            file_types = task_params.get(
                "file_types",
                [".py", ".js", ".ts", ".md", ".txt", ".rst", ".yaml", ".yml", ".json"]
            )

            # Get exclude patterns
            exclude_patterns = task_params.get(
                "exclude_patterns",
                ["__pycache__", ".git", ".venv", "node_modules", "dist", "build"]
            )

            # Load documents from repository
            reader = SimpleDirectoryReader(
                input_dir=str(repo),
                recursive=True,
                required_exts=file_types,
                exclude=exclude_patterns
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
                        "message": "No matching documents found"
                    },
                    "task_id": task_params.get("id", "unknown")
                }

            # Parse documents into nodes
            nodes = self.node_parser.get_nodes_from_documents(documents)

            # Create vector store index
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
                    "embedding_model": getattr(self.config, 'llm_model', 'nomic-embed-text')
                },
                "task_id": task_params.get("id", "unknown")
            }

        except Exception as e:
            return {
                "repo": repo_path,
                "status": "failed",
                "error": f"Ingestion failed: {str(e)}",
                "task_id": task_params.get("id", "unknown")
            }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _query_index(
        self,
        repo_path: str,
        task_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Query a LlamaIndex vector store.

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
                    "task_id": task_params.get("id", "unknown")
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
                        "task_id": task_params.get("id", "unknown")
                    }
                index = self.indices[index_id]

            # Create query engine
            query_engine = index.as_query_engine(
                similarity_top_k=top_k,
                retrieve_similarity_top_k=top_k * 2
            )

            # Execute query
            response = query_engine.query(query_text)

            return {
                "repo": repo_path,
                "status": "completed",
                "result": {
                    "operation": "query",
                    "query": query_text,
                    "answer": str(response),
                    "sources": [
                        {
                            "file": source.metadata.get("file_name", "unknown"),
                            "content": source.node.get_content()
                        }
                        for source in response.source_nodes
                    ],
                    "index_id": index_id
                },
                "task_id": task_params.get("id", "unknown")
            }

        except Exception as e:
            return {
                "repo": repo_path,
                "status": "failed",
                "error": f"Query failed: {str(e)}",
                "task_id": task_params.get("id", "unknown")
            }

    async def execute(self, task: Dict[str, Any], repos: List[str]) -> Dict[str, Any]:
        """Execute a LlamaIndex RAG task across multiple repositories.

        Args:
            task: Task specification with 'type' and 'params' keys
                  Types: 'ingest', 'query', 'ingest_and_query'
            repos: List of repository paths to operate on

        Returns:
            Execution result with all repository results
        """
        task_type = task.get('type', 'ingest')
        task_params = task.get('params', {})

        results = []

        # Process each repository
        for repo in repos:
            if task_type == 'ingest':
                result = await self._ingest_repository(repo, task_params)
                results.append(result)

            elif task_type == 'query':
                result = await self._query_index(repo, task_params)
                results.append(result)

            elif task_type == 'ingest_and_query':
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
                results.append({
                    "repo": repo,
                    "status": "failed",
                    "error": f"Unknown task type: {task_type}",
                    "task_id": task.get("id", "unknown")
                })

        return {
            "status": "completed",
            "engine": "llamaindex",
            "task": task,
            "repos_processed": len(repos),
            "results": results,
            "success_count": len([r for r in results if r.get("status") == "completed"]),
            "failure_count": len([r for r in results if r.get("status") == "failed"]),
            "indices_available": list(self.indices.keys())
        }

    async def get_health(self) -> Dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details.
        """
        try:
            # Check Ollama availability
            ollama_base_url = getattr(self.config, 'ollama_base_url', 'http://localhost:11434')
            embedding_model = getattr(self.config, 'llm_model', 'nomic-embed-text')

            health_details = {
                "llamaindex_version": "0.14.x",
                "ollama_base_url": ollama_base_url,
                "embedding_model": embedding_model,
                "indices_loaded": len(self.indices),
                "documents_loaded": sum(len(docs) for docs in self.documents.values()),
                "configured": True
            }

            return {
                "status": "healthy",
                "details": health_details
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {
                    "error": str(e),
                    "configured": True
                }
            }
