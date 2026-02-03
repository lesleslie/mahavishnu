"""OpenTelemetry trace ingester using Akosha's HotStore (DuckDB).

This module provides a native OTel trace ingestion system that converts OpenTelemetry
trace data into Akosha HotRecord format for semantic search and storage in DuckDB.
No Docker, PostgreSQL, or pgvector required - pure Python + DuckDB.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# Optional import for sentence-transformers
try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    # Define as type alias for None when not available
    SentenceTransformer: type[Any] | None = None  # type: ignore[misc]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from akosha.models import HotRecord
    from akosha.storage import HotStore

from mahavishnu.core.errors import ValidationError


logger = logging.getLogger(__name__)


class OtelIngester:
    """OpenTelemetry trace ingester for Akosha HotStore.

    Converts OTel trace data into HotRecord format with semantic embeddings
    for efficient similarity search in DuckDB.

    Example:
        >>> from akosha.storage import HotStore
        >>> ingester = OtelIngester()
        >>> await ingester.initialize()
        >>> await ingester.ingest_trace(trace_data)
        >>> results = await ingester.search_traces("error handling")
        >>> await ingester.close()
    """

    def __init__(
        self,
        hot_store: HotStore | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        cache_size: int = 1000,
    ) -> None:
        """Initialize OTel ingester.

        Args:
            hot_store: Optional HotStore instance (creates own if None)
            embedding_model: Sentence transformer model name
            cache_size: Maximum embeddings to cache in memory

        Raises:
            ImportError: If sentence-transformers is not installed
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is required for OTel ingester. "
                "Install with: pip install sentence-transformers"
            )

        self._hot_store = hot_store
        self._embedding_model_name = embedding_model
        self._cache_size = cache_size
        self._model: SentenceTransformer | None = None
        self._embedding_cache: dict[str, list[float]] = {}

    async def initialize(self) -> None:
        """Initialize ingester and HotStore.

        Creates HotStore if not provided, loads embedding model,
        and initializes database schema.

        Raises:
            RuntimeError: If initialization fails
        """
        try:
            # Initialize HotStore
            if self._hot_store is None:
                from akosha.storage import HotStore

                self._hot_store = HotStore(database_path=":memory:")
                await self._hot_store.initialize()

            # Load embedding model (lazy load, not thread-safe)
            if self._model is None:
                logger.info(f"Loading sentence transformer model: {self._embedding_model_name}")
                self._model = SentenceTransformer(self._embedding_model_name)
                logger.info("Embedding model loaded successfully")

            logger.info("OTel ingester initialized")

        except Exception as e:
            logger.error(f"Failed to initialize OTel ingester: {e}")
            raise RuntimeError(f"OTel ingester initialization failed: {e}") from e

    async def ingest_trace(self, trace_data: dict[str, Any]) -> None:
        """Ingest a single OTel trace into HotStore.

        Args:
            trace_data: OpenTelemetry trace data dictionary

        Raises:
            ValidationError: If trace data is invalid
            RuntimeError: If HotStore is not initialized

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

        logger.info(
            f"Batch ingestion complete: {success_count} success, {error_count} errors"
        )

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
        if not self._hot_store:
            raise RuntimeError("HotStore not initialized. Call initialize() first.")

        if not self._model:
            raise RuntimeError("Embedding model not loaded. Call initialize() first.")

        try:
            # Generate query embedding
            query_embedding = self._model.encode(query, convert_to_numpy=True).tolist()

            # Search HotStore
            results = await self._hot_store.search_similar(
                query_embedding=query_embedding,
                system_id=system_id,
                limit=limit,
                threshold=threshold,
            )

            logger.info(f"Search for '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []

    async def get_trace_by_id(self, trace_id: str) -> dict[str, Any] | None:
        """Retrieve specific trace by ID.

        Args:
            trace_id: OpenTelemetry trace ID

        Returns:
            Trace data dictionary or None if not found
        """
        if not self._hot_store:
            raise RuntimeError("HotStore not initialized. Call initialize() first.")

        try:
            # Query HotStore by conversation_id (which maps to trace_id)
            # Note: HotStore doesn't have a direct get_by_id method,
            # so we use search with the trace_id as query
            results = await self._hot_store.search_similar(
                query_embedding=[0.0] * 384,  # Dummy embedding, will filter below
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

    async def close(self) -> None:
        """Close ingester and cleanup resources.

        Closes HotStore connection and clears embedding cache.
        """
        try:
            if self._hot_store:
                await self._hot_store.close()

            self._embedding_cache.clear()
            logger.info("OTel ingester closed")

        except Exception as e:
            logger.error(f"Error closing OTel ingester: {e}")

    async def _get_embedding(self, content: str) -> list[float]:
        """Generate embedding for content with caching.

        Args:
            content: Text content to embed

        Returns:
            Embedding vector (384 dimensions)
        """
        # Check cache
        if content in self._embedding_cache:
            return self._embedding_cache[content]

        if not self._model:
            raise RuntimeError("Embedding model not loaded")

        try:
            # Generate embedding
            embedding = self._model.encode(content, convert_to_numpy=True).tolist()

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
            return [0.0] * 384

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
) -> OtelIngester:
    """Create and initialize OTel ingester.

    Args:
        hot_store_path: DuckDB database path (":memory:" for in-memory)
        embedding_model: Sentence transformer model name
        cache_size: Maximum embeddings to cache in memory

    Returns:
        Initialized OtelIngester instance

    Example:
        >>> ingester = await create_otel_ingester()
        >>> await ingester.ingest_trace(trace_data)
        >>> await ingester.close()
    """
    from akosha.storage import HotStore

    hot_store = HotStore(database_path=hot_store_path)
    await hot_store.initialize()

    ingester = OtelIngester(
        hot_store=hot_store,
        embedding_model=embedding_model,
        cache_size=cache_size,
    )
    await ingester.initialize()

    return ingester
