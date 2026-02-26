"""OpenTelemetry trace ingester with dual storage support.

This module provides an OTel trace ingestion system with two storage backends:
1. DuckDB (via Akosha HotStore): Fast local development, in-memory
2. PostgreSQL + pgvector: Production persistence with HNSW indexing

Storage selection:
- Use DuckDB for: Development, testing, small datasets
- Use PostgreSQL for: Production, persistence, large datasets (>100K vectors)
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Feature detection for embedding backends
# Try sentence-transformers first (best quality), then fastembed (cross-platform)
try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer: type[Any] | None = None  # type: ignore[misc]

try:
    from fastembed import TextEmbedding

    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False
    TextEmbedding: type[Any] | None = None  # type: ignore[misc]

if TYPE_CHECKING:
    from akosha.storage import HotStore

from mahavishnu.core.errors import ValidationError

logger = logging.getLogger(__name__)


class EmbeddingBackend(StrEnum):
    """Available embedding backends for OTel trace search."""

    AKOSHA = "akosha"  # Central embedding service via MCP
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    FASTEMBED = "fastembed"
    TEXT_ONLY = "text_only"


class StorageType(StrEnum):
    """Available storage backends for OTel traces."""

    DUCKDB = "duckdb"  # Akosha HotStore (development, in-memory)
    POSTGRESQL = "postgresql"  # pgvector with HNSW (production)


@runtime_checkable
class EmbeddingModel(Protocol):
    """Protocol for embedding model backends."""

    def encode(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        ...

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        ...


class SentenceTransformersWrapper:
    """Wrapper for sentence-transformers model."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize sentence-transformers wrapper.

        Args:
            model_name: Model name to load
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE or SentenceTransformer is None:
            raise ImportError("sentence-transformers not available")
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        # all-MiniLM-L6-v2 has 384 dimensions
        self._dimension = 384

    def encode(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return self._model.encode(text, convert_to_numpy=True).tolist()

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension


class FastEmbedWrapper:
    """Wrapper for fastembed model."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        """Initialize fastembed wrapper.

        Args:
            model_name: Model name to load
        """
        if not FASTEMBED_AVAILABLE or TextEmbedding is None:
            raise ImportError("fastembed not available")
        self._model = TextEmbedding(model_name=model_name)
        self._model_name = model_name
        # BAAI/bge-small-en-v1.5 has 384 dimensions
        self._dimension = 384

    def encode(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        # fastembed returns a generator, get first result
        embeddings = list(self._model.embed([text]))
        return embeddings[0].tolist()

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension


class TextOnlyEmbedder:
    """Fallback embedder that returns zero vectors.

    Used when no embedding library is available. Semantic search will
    fall back to text-based matching in the HotStore.
    """

    def __init__(self, dimension: int = 384) -> None:
        """Initialize text-only embedder.

        Args:
            dimension: Embedding dimension (for compatibility)
        """
        self._dimension = dimension

    def encode(self, text: str) -> list[float]:
        """Return zero embedding.

        Args:
            text: Text (ignored)

        Returns:
            Zero vector of specified dimension
        """
        return [0.0] * self._dimension

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension


class AkoshaEmbedder:
    """Embedder that uses Akosha MCP for centralized embedding generation.

    Routes all embedding requests through the Akosha MCP server, providing:
    - Centralized embedding service for the entire ecosystem
    - Consistent embeddings across all components
    - Multi-provider fallback (ONNX -> mock) handled by Akosha
    """

    def __init__(
        self,
        akosha_url: str = "http://localhost:8682/mcp",
        timeout: float = 30.0,
        dimension: int = 384,
    ) -> None:
        """Initialize Akosha embedder.

        Args:
            akosha_url: Akosha MCP server URL
            timeout: Request timeout in seconds
            dimension: Expected embedding dimension (default 384 for all-MiniLM-L6-v2)
        """
        self._akosha_url = akosha_url
        self._timeout = timeout
        self._dimension = dimension
        self._client: Any = None  # httpx.AsyncClient, lazy loaded
        self._available: bool | None = None

    async def _get_client(self) -> Any:
        """Get or create HTTP client."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self._akosha_url,
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._client

    async def check_available(self) -> bool:
        """Check if Akosha MCP is available.

        Returns:
            True if Akosha embedding service is accessible
        """
        if self._available is not None:
            return self._available

        try:
            client = await self._get_client()
            # Try to generate a test embedding
            response = await client.post(
                "/tools/call",
                json={
                    "name": "generate_embedding",
                    "arguments": {"text": "test"},
                },
            )
            self._available = response.status_code == 200
            if self._available:
                logger.info("akosha_embedding_service_available")
            return self._available
        except Exception as e:
            logger.warning(f"akosha_embedding_service_unavailable: {e}")
            self._available = False
            return False

    def encode(self, text: str) -> list[float]:
        """Generate embedding for text (synchronous wrapper).

        Note: This is a synchronous wrapper for the async implementation.
        For batch operations, use encode_batch_async directly.

        Args:
            text: Text to embed

        Returns:
            Embedding vector, or zero vector on error
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, create a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._encode_async(text))
                return future.result()
        except RuntimeError:
            # No running loop, we can use asyncio.run
            return asyncio.run(self._encode_async(text))

    async def _encode_async(self, text: str) -> list[float]:
        """Generate embedding for text asynchronously.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/tools/call",
                json={
                    "name": "generate_embedding",
                    "arguments": {"text": text},
                },
            )
            response.raise_for_status()

            result = response.json()
            # Parse MCP response format
            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0]
                if content.get("type") == "text":
                    import json

                    data = json.loads(content["text"])
                    return data.get("embedding", [0.0] * self._dimension)

            logger.warning(f"unexpected_akosha_response: {result}")
            return [0.0] * self._dimension

        except Exception as e:
            logger.error(f"akosha_embedding_failed: {e}")
            return [0.0] * self._dimension

    async def encode_batch_async(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/tools/call",
                json={
                    "name": "generate_batch_embeddings",
                    "arguments": {"texts": texts},
                },
            )
            response.raise_for_status()

            result = response.json()
            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0]
                if content.get("type") == "text":
                    import json

                    data = json.loads(content["text"])
                    return data.get("embeddings", [[0.0] * self._dimension] * len(texts))

            return [[0.0] * self._dimension] * len(texts)

        except Exception as e:
            logger.error(f"akosha_batch_embedding_failed: {e}")
            return [[0.0] * self._dimension] * len(texts)

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def get_available_backends() -> list[EmbeddingBackend]:
    """Get list of available embedding backends.

    Returns:
        List of available backends in preference order
    """
    backends: list[EmbeddingBackend] = []
    # Akosha is preferred as centralized embedding service
    backends.append(EmbeddingBackend.AKOSHA)
    if SENTENCE_TRANSFORMERS_AVAILABLE:
        backends.append(EmbeddingBackend.SENTENCE_TRANSFORMERS)
    if FASTEMBED_AVAILABLE:
        backends.append(EmbeddingBackend.FASTEMBED)
    backends.append(EmbeddingBackend.TEXT_ONLY)  # Always available
    return backends


def get_default_backend() -> EmbeddingBackend:
    """Get the default embedding backend based on availability.

    Akosha is preferred as the centralized embedding service for the ecosystem.

    Returns:
        Best available backend
    """
    # Prefer Akosha as centralized embedding service
    return EmbeddingBackend.AKOSHA


class OtelIngester:
    """OpenTelemetry trace ingester with dual storage support.

    Converts OTel trace data into vector format with semantic embeddings
    for efficient similarity search.

    Storage Backends:
    - DuckDB (HotStore): Fast local development, in-memory
    - PostgreSQL + pgvector: Production persistence with HNSW indexing

    Embedding Backends:
    - akosha (default, centralized service via MCP)
    - sentence-transformers (best quality, requires PyTorch)
    - fastembed (cross-platform, uses ONNX Runtime)
    - text-only (fallback, no embeddings)

    Example:
        >>> # DuckDB (development) with Akosha embeddings
        >>> ingester = OtelIngester(storage_type="duckdb")
        >>> await ingester.initialize()
        >>> await ingester.ingest_trace(trace_data)
        >>> results = await ingester.search_traces("error handling")
        >>> await ingester.close()

        >>> # PostgreSQL (production)
        >>> ingester = OtelIngester(
        ...     storage_type="postgresql",
        ...     pgvector_dsn="postgresql://user:pass@localhost/mahavishnu"
        ... )
        >>> await ingester.initialize()
    """

    def __init__(
        self,
        hot_store: HotStore | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        cache_size: int = 1000,
        preferred_backend: EmbeddingBackend | str | None = None,
        storage_type: StorageType | str = StorageType.DUCKDB,
        pgvector_dsn: str | None = None,
        pgvector_collection: str = "otel_traces",
        akosha_url: str = "http://localhost:8682/mcp",
    ) -> None:
        """Initialize OTel ingester.

        Args:
            hot_store: Optional HotStore instance (creates own if None, DuckDB only)
            embedding_model: Embedding model name (backend-specific)
            cache_size: Maximum embeddings to cache in memory
            preferred_backend: Preferred embedding backend. If None, uses Akosha
                by default. Options: "akosha", "sentence_transformers", "fastembed", "text_only"
            storage_type: Storage backend type ("duckdb" or "postgresql")
            pgvector_dsn: PostgreSQL DSN for pgvector storage (required if storage_type="postgresql")
            pgvector_collection: Collection/table name for pgvector (default: "otel_traces")
            akosha_url: Akosha MCP server URL for centralized embeddings

        Raises:
            ImportError: If preferred_backend is unavailable
        """
        # Convert string to enum if needed
        if isinstance(storage_type, str):
            storage_type = StorageType(storage_type)

        self._storage_type = storage_type
        self._pgvector_dsn = pgvector_dsn
        self._pgvector_collection = pgvector_collection
        self._akosha_url = akosha_url  # Akosha MCP URL for centralized embeddings
        self._hot_store = hot_store  # Only used for DuckDB
        self._pgvector_adapter: Any = None  # PgvectorAdapter, lazy loaded

        self._embedding_model_name = embedding_model
        self._cache_size = cache_size
        self._embedding_cache: dict[str, list[float]] = {}

        # Determine embedding backend
        if preferred_backend is not None:
            # Convert string to enum if needed
            if isinstance(preferred_backend, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                preferred_backend = EmbeddingBackend(preferred_backend)
            self._backend = preferred_backend
        else:
            self._backend = get_default_backend()

        # Initialize embedding model lazily
        self._embedder: EmbeddingModel | None = None
        self._embedding_dimension = 384

        # Log configuration
        available = get_available_backends()
        logger.info(f"Available embedding backends: {[b.value for b in available]}")
        logger.info(f"Selected backend: {self._backend.value}")
        logger.info(f"Storage type: {self._storage_type.value}")

    @property
    def backend(self) -> EmbeddingBackend:
        """Get current embedding backend."""
        return self._backend

    @property
    def storage_type(self) -> StorageType:
        """Get current storage type."""
        return self._storage_type

    @property
    def embedding_dimension(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dimension

    def _create_embedder(self) -> EmbeddingModel:
        """Create embedding model based on selected backend.

        Returns:
            Embedding model instance

        Raises:
            ImportError: If selected backend is unavailable
        """
        if self._backend == EmbeddingBackend.AKOSHA:
            logger.info(f"Using Akosha centralized embedding service: {self._akosha_url}")
            return AkoshaEmbedder(akosha_url=self._akosha_url)

        elif self._backend == EmbeddingBackend.SENTENCE_TRANSFORMERS:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                raise ImportError(
                    "sentence-transformers is not available. "
                    "Install with: pip install sentence-transformers"
                )
            logger.info(f"Loading sentence-transformers model: {self._embedding_model_name}")
            return SentenceTransformersWrapper(self._embedding_model_name)

        elif self._backend == EmbeddingBackend.FASTEMBED:
            if not FASTEMBED_AVAILABLE:
                raise ImportError("fastembed is not available. Install with: pip install fastembed")
            # Map sentence-transformers model names to fastembed equivalents
            fastembed_model = self._map_to_fastembed_model(self._embedding_model_name)
            logger.info(f"Loading fastembed model: {fastembed_model}")
            return FastEmbedWrapper(fastembed_model)

        else:  # TEXT_ONLY
            logger.warning(
                "Using text-only mode. Semantic search will be degraded. "
                "Install sentence-transformers or fastembed for full functionality."
            )
            return TextOnlyEmbedder()

    def _map_to_fastembed_model(self, model_name: str) -> str:
        """Map sentence-transformers model names to fastembed equivalents.

        Args:
            model_name: Sentence-transformers model name

        Returns:
            Fastembed-compatible model name
        """
        # Common mappings
        model_map = {
            "all-MiniLM-L6-v2": "BAAI/bge-small-en-v1.5",
            "all-mpnet-base-v2": "BAAI/bge-base-en-v1.5",
            "paraphrase-MiniLM-L6-v2": "BAAI/bge-small-en-v1.5",
        }
        return model_map.get(model_name, "BAAI/bge-small-en-v1.5")

    async def initialize(self) -> None:
        """Initialize ingester and storage backend.

        Creates storage backend (HotStore or pgvector) if not provided,
        loads embedding model, and initializes database schema.

        Raises:
            RuntimeError: If initialization fails
            ValueError: If PostgreSQL storage is selected but no DSN provided
        """
        try:
            # Initialize storage backend
            if self._storage_type == StorageType.POSTGRESQL:
                await self._initialize_pgvector()
            else:
                await self._initialize_duckdb()

            # Initialize embedding model
            if self._embedder is None:
                try:
                    self._embedder = self._create_embedder()
                    self._embedding_dimension = self._embedder.dimension
                    logger.info(
                        f"Embedding model loaded successfully "
                        f"(backend={self._backend.value}, dim={self._embedding_dimension})"
                    )
                except ImportError as e:
                    # Try fallback backends
                    logger.warning(f"Failed to load {self._backend.value}: {e}")
                    self._embedder = self._try_fallback_backends()
                    if self._embedder is not None:
                        self._embedding_dimension = self._embedder.dimension
                        logger.info(f"Using fallback embedding backend: {self._backend.value}")

            logger.info(f"OTel ingester initialized (storage={self._storage_type.value})")

        except Exception as e:
            logger.error(f"Failed to initialize OTel ingester: {e}")
            raise RuntimeError(f"OTel ingester initialization failed: {e}") from e

    async def _initialize_duckdb(self) -> None:
        """Initialize DuckDB (HotStore) storage backend."""
        if self._hot_store is None:
            from akosha.storage import HotStore

            self._hot_store = HotStore(database_path=":memory:")
            await self._hot_store.initialize()
        logger.info("DuckDB (HotStore) storage initialized")

    async def _initialize_pgvector(self) -> None:
        """Initialize PostgreSQL + pgvector storage backend."""
        if not self._pgvector_dsn:
            raise ValueError(
                "pgvector_dsn is required when storage_type='postgresql'. "
                "Set the MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING environment variable."
            )

        from mahavishnu.adapters import HNSWConfig, PgvectorAdapter, PgvectorSettings

        settings = PgvectorSettings(
            dsn=self._pgvector_dsn,
            ensure_extension=True,
        )
        self._pgvector_adapter = PgvectorAdapter(settings)
        await self._pgvector_adapter.init()

        # Ensure collection exists with correct dimension
        await self._pgvector_adapter.create_collection(
            name=self._pgvector_collection,
            dimension=self._embedding_dimension,
            distance_metric="cosine",
        )
        logger.info(
            f"PostgreSQL + pgvector storage initialized (collection={self._pgvector_collection})"
        )

    def _try_fallback_backends(self) -> EmbeddingModel | None:
        """Try fallback embedding backends.

        Returns:
            Embedding model or None if all backends fail
        """
        # Try backends in order of preference (Akosha first for centralized service)
        for backend in [
            EmbeddingBackend.AKOSHA,
            EmbeddingBackend.SENTENCE_TRANSFORMERS,
            EmbeddingBackend.FASTEMBED,
            EmbeddingBackend.TEXT_ONLY,
        ]:
            if backend == self._backend:
                continue  # Skip already tried backend

            try:
                self._backend = backend
                embedder = self._create_embedder()
                logger.info(f"Successfully initialized fallback backend: {backend.value}")
                return embedder
            except (ImportError, Exception) as e:
                logger.debug(f"Fallback backend {backend.value} unavailable: {e}")
                continue

        # This should never happen since TEXT_ONLY always works
        logger.error("All embedding backends failed, using text-only")
        self._backend = EmbeddingBackend.TEXT_ONLY
        return TextOnlyEmbedder()

    async def ingest_trace(self, trace_data: dict[str, Any]) -> None:
        """Ingest a single OTel trace into storage backend.

        Args:
            trace_data: OpenTelemetry trace data dictionary

        Raises:
            ValidationError: If trace data is invalid
            RuntimeError: If storage backend is not initialized

        Trace Data Format:
            {
                "trace_id": "1234...",
                "spans": [
                    {
                        "name": "span_name",
                        "start_time": "2024-01-01T00:00:00Z",
                        "attributes": {"service.name": "claude", ...}
                    },
                    ...
                ]
            }
        """
        # Route to appropriate storage backend
        if self._storage_type == StorageType.POSTGRESQL:
            await self._ingest_trace_pgvector(trace_data)
        else:
            await self._ingest_trace_duckdb(trace_data)

    async def _ingest_trace_duckdb(self, trace_data: dict[str, Any]) -> None:
        """Ingest trace into DuckDB (HotStore)."""
        if not self._hot_store:
            raise RuntimeError("HotStore not initialized. Call initialize() first.")

        try:
            # Validate required fields
            trace_id = trace_data.get("trace_id")
            if not trace_id:
                raise ValidationError("trace_data missing required field: trace_id")

            spans = trace_data.get("spans", [])
            if not spans:
                logger.warning(f"Trace {trace_id} has no spans, skipping")
                return

            # Extract system_id from service.name attribute
            system_id = self._extract_system_id(spans)

            # Build content from span names
            content = self._build_content(spans)

            # Generate embedding (cached)
            embedding = await self._get_embedding(content)

            # Extract timestamp from first span
            timestamp = self._extract_timestamp(spans)

            # Store all attributes as metadata
            metadata = {
                "trace_id": trace_id,
                "span_count": len(spans),
                "attributes": self._extract_attributes(spans),
            }

            # Create HotRecord
            from akosha.models import HotRecord

            record = HotRecord(
                system_id=system_id,
                conversation_id=trace_id,
                content=content,
                embedding=embedding,
                timestamp=timestamp,
                metadata=metadata,
            )

            # Insert into HotStore
            await self._hot_store.insert(record)
            logger.debug(f"Ingested trace {trace_id} with {len(spans)} spans")

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Failed to ingest trace {trace_data.get('trace_id', 'unknown')}: {e}")
            # Don't fail - log and continue for other traces

    async def _ingest_trace_pgvector(self, trace_data: dict[str, Any]) -> None:
        """Ingest trace into PostgreSQL + pgvector."""
        if not self._pgvector_adapter:
            raise RuntimeError("pgvector adapter not initialized. Call initialize() first.")

        try:
            # Validate required fields
            trace_id = trace_data.get("trace_id")
            if not trace_id:
                raise ValidationError("trace_data missing required field: trace_id")

            spans = trace_data.get("spans", [])
            if not spans:
                logger.warning(f"Trace {trace_id} has no spans, skipping")
                return

            # Extract system_id from service.name attribute
            system_id = self._extract_system_id(spans)

            # Build content from span names
            content = self._build_content(spans)

            # Generate embedding (cached)
            embedding = await self._get_embedding(content)

            # Extract timestamp from first span
            timestamp = self._extract_timestamp(spans)

            # Store all attributes as metadata
            metadata = {
                "trace_id": trace_id,
                "system_id": system_id,
                "span_count": len(spans),
                "attributes": self._extract_attributes(spans),
                "content": content,
                "timestamp": timestamp.isoformat(),
            }

            # Insert into pgvector
            await self._pgvector_adapter.upsert(
                collection=self._pgvector_collection,
                documents=[
                    {
                        "id": trace_id,
                        "vector": embedding,
                        "metadata": metadata,
                    }
                ],
            )
            logger.debug(f"Ingested trace {trace_id} with {len(spans)} spans into pgvector")

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Failed to ingest trace {trace_data.get('trace_id', 'unknown')}: {e}")

    async def ingest_batch(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        """Ingest multiple OTel traces in batch.

        Args:
            traces: List of OTel trace data dictionaries

        Returns:
            Dictionary with ingestion statistics:
                {
                    "success_count": int,
                    "error_count": int,
                    "errors": list[str]
                }
        """
        success_count = 0
        error_count = 0
        errors: list[str] = []

        for trace in traces:
            try:
                await self.ingest_trace(trace)
                success_count += 1
            except Exception as e:
                error_count += 1
                error_msg = f"Trace {trace.get('trace_id', 'unknown')}: {e}"
                errors.append(error_msg)
                logger.warning(error_msg)

        logger.info(f"Batch ingestion complete: {success_count} success, {error_count} errors")

        return {
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors,
        }

    async def search_traces(
        self,
        query: str,
        limit: int = 10,
        system_id: str | None = None,
        threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search traces by semantic similarity.

        Args:
            query: Search query text
            limit: Maximum results to return
            system_id: Optional system filter (e.g., "claude", "qwen")
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            List of matching traces with similarity scores:
                [
                    {
                        "conversation_id": "...",
                        "content": "...",
                        "timestamp": "...",
                        "metadata": {...},
                        "similarity": 0.92
                    },
                    ...
                ]
        """
        if not self._embedder:
            raise RuntimeError("Embedding model not loaded. Call initialize() first.")

        try:
            # Generate query embedding
            query_embedding = self._embedder.encode(query)

            # Route to appropriate storage backend
            if self._storage_type == StorageType.POSTGRESQL:
                results = await self._search_pgvector(query_embedding, limit, system_id, threshold)
            else:
                results = await self._search_duckdb(query_embedding, limit, system_id, threshold)

            logger.info(f"Search for '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []

    async def _search_duckdb(
        self,
        query_embedding: list[float],
        limit: int,
        system_id: str | None,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Search DuckDB (HotStore) backend."""
        if not self._hot_store:
            raise RuntimeError("HotStore not initialized. Call initialize() first.")

        return await self._hot_store.search_similar(
            query_embedding=query_embedding,
            system_id=system_id,
            limit=limit,
            threshold=threshold,
        )

    async def _search_pgvector(
        self,
        query_embedding: list[float],
        limit: int,
        system_id: str | None,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Search PostgreSQL + pgvector backend."""
        if not self._pgvector_adapter:
            raise RuntimeError("pgvector adapter not initialized. Call initialize() first.")

        # Build filter expression
        filter_expr = None
        if system_id:
            filter_expr = {"system_id": system_id}

        # Search with HNSW index
        results = await self._pgvector_adapter.search(
            collection=self._pgvector_collection,
            query_vector=query_embedding,
            limit=limit,
            filter_expr=filter_expr,
            include_vectors=False,
        )

        # Filter by threshold and format results
        formatted = []
        for result in results:
            # Convert distance to similarity (cosine distance = 1 - similarity)
            similarity = 1 - result["score"]
            if similarity >= threshold:
                formatted.append(
                    {
                        "conversation_id": result["id"],
                        "content": result["metadata"].get("content", ""),
                        "timestamp": result["metadata"].get("timestamp", ""),
                        "metadata": result["metadata"],
                        "similarity": similarity,
                    }
                )

        return formatted

    async def get_trace_by_id(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieve specific trace by ID.

        Args:
            trace_id: OpenTelemetry trace ID

        Returns:
            Trace data dictionary or None if not found
        """
        if self._storage_type == StorageType.POSTGRESQL:
            return await self._get_trace_pgvector(trace_id)
        else:
            return await self._get_trace_duckdb(trace_id)

    async def _get_trace_duckdb(self, trace_id: str) -> dict[str, Any] | None:
        """Get trace from DuckDB backend."""
        if not self._hot_store:
            raise RuntimeError("HotStore not initialized. Call initialize() first.")

        try:
            # Query HotStore by conversation_id (which maps to trace_id)
            # Note: HotStore doesn't have a direct get_by_id method,
            # so we use search with the trace_id as query
            results = await self._hot_store.search_similar(
                query_embedding=[0.0] * self._embedding_dimension,  # Dummy embedding
                limit=1000,
                threshold=0.0,  # Get all results
            )

            # Filter by trace_id
            for result in results:
                if result.get("conversation_id") == trace_id:
                    logger.debug(f"Found trace {trace_id}")
                    return result

            logger.debug(f"Trace {trace_id} not found")
            return None

        except Exception as e:
            logger.error(f"Failed to get trace {trace_id}: {e}")
            return None

    async def _get_trace_pgvector(self, trace_id: str) -> dict[str, Any] | None:
        """Get trace from PostgreSQL + pgvector backend."""
        if not self._pgvector_adapter:
            raise RuntimeError("pgvector adapter not initialized. Call initialize() first.")

        try:
            results = await self._pgvector_adapter.get(
                collection=self._pgvector_collection,
                ids=[trace_id],
                include_vectors=False,
            )

            if results:
                result = results[0]
                return {
                    "conversation_id": result["id"],
                    "content": result["metadata"].get("content", ""),
                    "timestamp": result["metadata"].get("timestamp", ""),
                    "metadata": result["metadata"],
                }

            logger.debug(f"Trace {trace_id} not found")
            return None

        except Exception as e:
            logger.error(f"Failed to get trace {trace_id}: {e}")
            return None

    async def close(self) -> None:
        """Close ingester and cleanup resources.

        Closes storage backend connections and clears embedding cache.
        """
        try:
            if self._storage_type == StorageType.POSTGRESQL:
                if self._pgvector_adapter:
                    await self._pgvector_adapter.cleanup()
            else:
                if self._hot_store:
                    await self._hot_store.close()

            self._embedding_cache.clear()
            logger.info(f"OTel ingester closed (storage={self._storage_type.value})")

        except Exception as e:
            logger.error(f"Error closing OTel ingester: {e}")

    async def _get_embedding(self, content: str) -> list[float]:
        """Generate embedding for content with caching.

        Args:
            content: Text content to embed

        Returns:
            Embedding vector
        """
        # Check cache
        if content in self._embedding_cache:
            return self._embedding_cache[content]

        if not self._embedder:
            raise RuntimeError("Embedding model not loaded")

        try:
            # Generate embedding
            embedding = self._embedder.encode(content)

            # Update cache (with size limit)
            if len(self._embedding_cache) >= self._cache_size:
                # Remove oldest entry (FIFO)
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]

            self._embedding_cache[content] = embedding
            return embedding

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            # Return zero embedding on error
            return [0.0] * self._embedding_dimension

    def _extract_system_id(self, spans: list[dict[str, Any]]) -> str:
        """Extract system_id from span attributes.

        Args:
            spans: List of span dictionaries

        Returns:
            System ID (e.g., "claude", "qwen", "unknown")
        """
        for span in spans:
            attributes = span.get("attributes", {})
            service_name = attributes.get("service.name")
            if service_name:
                # Map common service names to system IDs
                if "claude" in service_name.lower():
                    return "claude"
                elif "qwen" in service_name.lower():
                    return "qwen"
                else:
                    return service_name

        return "unknown"

    def _build_content(self, spans: list[dict[str, Any]]) -> str:
        """Build searchable content from span names.

        Args:
            spans: List of span dictionaries

        Returns:
            Concatenated span names as searchable text
        """
        parts = []
        for span in spans:
            name = span.get("name", "")
            if name:
                parts.append(name)

        return " | ".join(parts) if parts else "Empty trace"

    def _extract_timestamp(self, spans: list[dict[str, Any]]) -> datetime:
        """Extract timestamp from first span.

        Args:
            spans: List of span dictionaries

        Returns:
            Datetime object (UTC)
        """
        if not spans:
            return datetime.now(UTC)

        first_span = spans[0]
        start_time = first_span.get("start_time")

        if start_time:
            try:
                # Parse ISO 8601 timestamp
                if isinstance(start_time, str):
                    # Handle various ISO 8601 formats
                    return datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                elif isinstance(start_time, int):
                    # Handle Unix timestamp (nanoseconds)
                    return datetime.fromtimestamp(start_time / 1_000_000_000, tz=UTC)
            except Exception as e:
                logger.warning(f"Failed to parse timestamp {start_time}: {e}")

        return datetime.now(UTC)

    def _extract_attributes(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract all attributes from spans.

        Args:
            spans: List of span dictionaries

        Returns:
            Dictionary of all attributes
        """
        all_attributes: dict[str, Any] = {}

        for span in spans:
            attributes = span.get("attributes", {})
            all_attributes.update(attributes)

        return all_attributes

    async def __aenter__(self) -> OtelIngester:
        """Async context manager entry.

        Returns:
            Initialized OtelIngester instance
        """
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit.

        Args:
            exc_type: Exception type if an exception was raised
            exc_val: Exception value if an exception was raised
            exc_tb: Exception traceback if an exception was raised
        """
        await self.close()


# Factory function for convenient instantiation
async def create_otel_ingester(
    hot_store_path: str = ":memory:",
    embedding_model: str = "all-MiniLM-L6-v2",
    cache_size: int = 1000,
    preferred_backend: EmbeddingBackend | str | None = None,
    storage_type: StorageType | str = StorageType.DUCKDB,
    pgvector_dsn: str | None = None,
    pgvector_collection: str = "otel_traces",
    akosha_url: str = "http://localhost:8682/mcp",
) -> OtelIngester:
    """Create and initialize OTel ingester.

    Args:
        hot_store_path: DuckDB database path (":memory:" for in-memory)
        embedding_model: Embedding model name
        cache_size: Maximum embeddings to cache in memory
        preferred_backend: Preferred embedding backend (uses Akosha by default)
        storage_type: Storage backend ("duckdb" or "postgresql")
        pgvector_dsn: PostgreSQL DSN (required if storage_type="postgresql")
        pgvector_collection: pgvector collection name (default: "otel_traces")
        akosha_url: Akosha MCP server URL for centralized embeddings

    Returns:
        Initialized OtelIngester instance

    Example:
        >>> # DuckDB (development)
        >>> ingester = await create_otel_ingester()
        >>> await ingester.ingest_trace(trace_data)
        >>> await ingester.close()

        >>> # PostgreSQL (production)
        >>> ingester = await create_otel_ingester(
        ...     storage_type="postgresql",
        ...     pgvector_dsn="postgresql://user:pass@localhost/mahavishnu"
        ... )
    """
    # Convert string to enum if needed
    if isinstance(storage_type, str):
        storage_type = StorageType(storage_type)

    ingester = OtelIngester(
        embedding_model=embedding_model,
        cache_size=cache_size,
        preferred_backend=preferred_backend,
        storage_type=storage_type,
        pgvector_dsn=pgvector_dsn,
        pgvector_collection=pgvector_collection,
        akosha_url=akosha_url,
    )

    # For DuckDB, create HotStore if path provided
    if storage_type == StorageType.DUCKDB and hot_store_path:
        from akosha.storage import HotStore

        hot_store = HotStore(database_path=hot_store_path)
        await hot_store.initialize()
        ingester._hot_store = hot_store  # noqa: SLF001

    await ingester.initialize()

    return ingester
