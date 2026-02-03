"""MCP tools for OpenTelemetry trace ingestion and search using Akosha HotStore."""

from __future__ import annotations

import json
from logging import getLogger
from pathlib import Path
from typing import Any

logger = getLogger(__name__)


def register_otel_tools(server, app, mcp_client):
    """Register OTel trace management tools with the MCP server.

    Uses Akosha HotStore (DuckDB) for zero-dependency storage with semantic search.
    No Docker, PostgreSQL, or pgvector required.

    Args:
        server: FastMCP server instance
        app: MahavishnuApp instance
        mcp_client: MCP client wrapper
    """

    @server.tool()
    async def ingest_otel_traces(
        log_files: list[str] | None = None,
        trace_data: list[dict] | None = None,
        system_id: str = "unknown",
    ) -> dict[str, Any]:
        """Ingest OpenTelemetry traces from log files or direct trace data.

        Uses Akosha HotStore (DuckDB with HNSW vector index) for storage.
        Traces are automatically embedded for semantic search.

        Args:
            log_files: Optional list of log file paths to ingest (JSON format)
            trace_data: Optional list of trace dictionaries to ingest directly
            system_id: System identifier (claude, qwen, or custom name)

        Returns:
            Dictionary with ingestion summary:
                - status: success or error
                - traces_ingested: Number of traces successfully ingested
                - files_processed: Number of log files processed
                - errors: List of per-file/per-trace errors
                - system_id: System identifier for ingested traces
                - storage_backend: Always "duckdb_hotstore"

        Example:
            result = await mcp.call_tool("ingest_otel_traces", {
                "log_files": ["/path/to/claude_session.json"],
                "system_id": "claude"
            })
        """
        try:
            # Import native OTel ingester (uses Akosha HotStore)
            from mahavishnu.ingesters import OtelIngester

            # Validate inputs - either log_files or trace_data must be provided
            if not log_files and not trace_data:
                return {
                    "status": "error",
                    "error": "Either log_files or trace_data must be provided",
                    "traces_ingested": 0,
                    "files_processed": 0,
                    "errors": ["No input data provided"],
                    "system_id": system_id,
                    "storage_backend": "duckdb_hotstore",
                }

            # Initialize ingester with app config
            ingester = OtelIngester(
                hot_store_path=app.config.otel_ingester.hot_store_path,
                embedding_model=app.config.otel_ingester.embedding_model,
                cache_size=app.config.otel_ingester.cache_size,
            )
            await ingester.initialize()

            traces_ingested = 0
            errors = []
            files_processed = 0

            # Process log files if provided
            if log_files:
                for log_file in log_files:
                    try:
                        file_path = Path(log_file)
                        if not file_path.exists():
                            errors.append(f"File not found: {log_file}")
                            continue

                        # Read and parse JSON log file
                        with file_path.open("r") as f:
                            file_data = json.load(f)

                        # Handle different file formats
                        if isinstance(file_data, list):
                            traces = file_data
                        elif isinstance(file_data, dict):
                            # Extract traces from dict format
                            traces = file_data.get("traces", file_data.get("data", []))
                        else:
                            errors.append(f"Invalid format in {log_file}")
                            continue

                        # Add system_id to each trace if not present
                        for trace in traces:
                            if isinstance(trace, dict):
                                trace.setdefault("system_id", system_id)

                        # Batch ingest traces from file
                        await ingester.ingest_batch(traces)
                        traces_ingested += len(traces)
                        files_processed += 1
                        logger.info(f"Ingested {len(traces)} traces from {log_file}")

                    except Exception as e:
                        error_msg = f"Failed to process {log_file}: {str(e)}"
                        logger.error(error_msg)
                        errors.append(error_msg)

            # Process direct trace data if provided
            if trace_data:
                try:
                    # Add system_id to each trace if not present
                    for trace in trace_data:
                        if isinstance(trace, dict):
                            trace.setdefault("system_id", system_id)

                    await ingester.ingest_batch(trace_data)
                    traces_ingested += len(trace_data)
                    logger.info(f"Ingested {len(trace_data)} direct traces")
                except Exception as e:
                    error_msg = f"Failed to process direct traces: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            await ingester.close()

            return {
                "status": "success" if traces_ingested > 0 else "warning",
                "traces_ingested": traces_ingested,
                "files_processed": files_processed,
                "errors": errors,
                "system_id": system_id,
                "storage_backend": "duckdb_hotstore",
            }

        except ImportError as e:
            return {
                "status": "error",
                "error": f"OtelIngester not available: {str(e)}",
                "traces_ingested": 0,
                "files_processed": 0,
                "errors": [str(e)],
                "system_id": system_id,
                "storage_backend": "none",
            }
        except Exception as e:
            logger.exception("Unexpected error during trace ingestion")
            return {
                "status": "error",
                "error": f"Unexpected error: {str(e)}",
                "traces_ingested": 0,
                "files_processed": 0,
                "errors": [str(e)],
                "system_id": system_id,
                "storage_backend": "duckdb_hotstore",
            }

    @server.tool()
    async def search_otel_traces(
        query: str,
        system_id: str | None = None,
        limit: int = 10,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over OTel traces using vector embeddings.

        Finds traces similar to the natural language query using DuckDB HNSW index.

        Args:
            query: Natural language search query (e.g., "RAG pipeline timeout")
            system_id: Optional system filter (claude, qwen, or custom)
            limit: Maximum number of results to return (default: 10)
            threshold: Optional minimum similarity score (0.0-1.0). If not specified,
                       uses app config default (0.7)

        Returns:
            List of matching traces with metadata:
                - conversation_id: Trace ID
                - system_id: System identifier
                - content: Trace summary/content
                - timestamp: Trace timestamp
                - similarity: Semantic similarity score (0.0-1.0)
                - metadata: Full trace metadata

        Example:
            results = await mcp.call_tool("search_otel_traces", {
                "query": "RAG pipeline failed with timeout",
                "system_id": "claude",
                "limit": 5,
                "threshold": 0.75
            })
        """
        try:
            from mahavishnu.ingesters import OtelIngester

            # Initialize ingester
            ingester = OtelIngester(
                hot_store_path=app.config.otel_ingester.hot_store_path,
                embedding_model=app.config.otel_ingester.embedding_model,
                similarity_threshold=threshold or app.config.otel_ingester.similarity_threshold,
            )
            await ingester.initialize()

            # Perform semantic search
            results = await ingester.search_traces(
                query=query,
                system_id=system_id,
                limit=limit,
            )

            await ingester.close()

            logger.info(f"Found {len(results)} traces for query: {query}")
            return results

        except ImportError:
            logger.error("OtelIngester not available for search")
            return []
        except Exception as e:
            logger.exception(f"Error during trace search: {e}")
            return []

    @server.tool()
    async def get_otel_trace(
        trace_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a specific OTel trace by ID.

        Args:
            trace_id: Unique trace identifier (conversation_id in HotStore)

        Returns:
            Trace dictionary with full details if found:
                - conversation_id: Trace ID
                - system_id: System identifier
                - content: Trace content
                - timestamp: Trace timestamp
                - metadata: Full trace metadata
            Returns None if trace not found.

        Example:
            trace = await mcp.call_tool("get_otel_trace", {
                "trace_id": "abc123-def456"
            })
        """
        try:
            from mahavishnu.ingesters import OtelIngester

            # Initialize ingester
            ingester = OtelIngester(
                hot_store_path=app.config.otel_ingester.hot_store_path,
            )
            await ingester.initialize()

            # Retrieve trace by ID
            trace = await ingester.get_trace_by_id(trace_id)

            await ingester.close()

            if trace:
                logger.info(f"Retrieved trace: {trace_id}")
            else:
                logger.warning(f"Trace not found: {trace_id}")

            return trace

        except ImportError:
            logger.error("OtelIngester not available for trace retrieval")
            return None
        except Exception as e:
            logger.exception(f"Error retrieving trace {trace_id}: {e}")
            return None

    @server.tool()
    async def otel_ingester_stats() -> dict[str, Any]:
        """Get statistics about the OTel trace ingester.

        Returns:
            Dictionary with ingester statistics:
                - total_traces: Total number of traces stored
                - traces_by_system: Breakdown by system_id (claude, qwen, etc.)
                - storage_backend: Always "duckdb_hotstore"
                - hot_store_path: Path to HotStore database file
                - embedding_model: Model used for embeddings
                - cache_size: Embedding cache size
                - status: health status (healthy/error)

        Example:
            stats = await mcp.call_tool("otel_ingester_stats", {})
        """
        try:
            from mahavishnu.ingesters import OtelIngester
            from akosha.storage import HotStore

            # Initialize HotStore to query statistics
            hot_store = HotStore(database_path=app.config.otel_ingester.hot_store_path)
            await hot_store.initialize()

            # Query total traces (basic implementation)
            # Note: DuckDB doesn't expose count directly without SQL query
            stats = {
                "storage_backend": "duckdb_hotstore",
                "hot_store_path": app.config.otel_ingester.hot_store_path,
                "embedding_model": app.config.otel_ingester.embedding_model,
                "cache_size": app.config.otel_ingester.cache_size,
                "similarity_threshold": app.config.otel_ingester.similarity_threshold,
                "status": "healthy",
                # Would need to add SQL query to HotStore for exact counts
                "total_traces": "unknown",
                "traces_by_system": {},
            }

            await hot_store.close()

            logger.info("Retrieved OTel ingester statistics")
            return stats

        except ImportError:
            return {
                "storage_backend": "none",
                "status": "error",
                "error": "OtelIngester or HotStore not available",
            }
        except Exception as e:
            logger.exception(f"Error getting ingester stats: {e}")
            return {
                "storage_backend": "duckdb_hotstore",
                "status": "error",
                "error": str(e),
            }

    logger.info("Registered 4 OTel trace tools (Akosha HotStore backend)")
