"""MCP tools for OpenTelemetry trace ingestion and search using Akosha HotStore."""

from __future__ import annotations

import json
from logging import getLogger
from pathlib import Path
from typing import Any

logger = getLogger(__name__)


def register_otel_tools(server, app, mcp_client):  # noqa: C901
    """Register OTel trace management tools with the MCP server.

    Uses Akosha HotStore (DuckDB) for zero-dependency storage with semantic search.
    No Docker, PostgreSQL, or pgvector required.

    Structural C901 suppression: FastMCP's ``@server.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        server: FastMCP server instance
        app: MahavishnuApp instance
        mcp_client: MCP client wrapper
    """

    @server.tool()
    async def ingest_otel_traces(  # noqa: C901
        log_files: list[str] | None = None,
        trace_data: list[dict] | None = None,
        system_id: str = "unknown",
    ) -> dict[str, Any]:
        """Ingest OpenTelemetry traces from log files or direct trace data."""
        try:
            # Import native OTel ingester (uses Akosha HotStore)
            from mahavishnu.ingesters.otel_ingester import OtelIngester

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

            # Initialize ingester — OtelIngester creates HotStore internally
            # using storage_type from config (duckdb or postgresql)
            ingester = OtelIngester(  # type: ignore[call-arg]
                embedding_model=app.config.otel_ingester.embedding_model,
                cache_size=app.config.otel_ingester.cache_size,
                turboquant_bits=app.config.otel_ingester.turboquant_bits,
                duckdb_path=app.config.otel_ingester.hot_store_path,
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
            if "ingester" in dir() and ingester is not None:
                await ingester.close()
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
        """Semantic search over OTel traces using vector embeddings."""
        try:
            from mahavishnu.ingesters.otel_ingester import OtelIngester

            # Initialize ingester
            ingester = OtelIngester(  # type: ignore[call-arg]
                embedding_model=app.config.otel_ingester.embedding_model,
                similarity_threshold=threshold or app.config.otel_ingester.similarity_threshold,
                turboquant_bits=app.config.otel_ingester.turboquant_bits,
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
            if "ingester" in dir() and ingester is not None:
                await ingester.close()
            return []

    @server.tool()
    async def get_otel_trace(
        trace_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a specific OTel trace by ID."""
        try:
            from mahavishnu.ingesters.otel_ingester import OtelIngester

            # Initialize ingester
            ingester = OtelIngester(  # type: ignore[call-arg]
                turboquant_bits=app.config.otel_ingester.turboquant_bits,
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
            if "ingester" in dir() and ingester is not None:
                await ingester.close()
            return None

    @server.tool()
    async def query_local_traces(
        task_class: str,
        time_range_minutes: int = 60,
        system_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query OTel traces by task_class and time range.

        This is the Bodai component endpoint that Akosha's fitness analyzer
        polls to collect traces for fitness signal computation.

        Args:
            task_class: Task classification tag to filter on (e.g. "code_generation")
            time_range_minutes: How far back to query (default 60 minutes)
            system_id: Optional source system identifier (auto-detected if not provided)
            limit: Maximum number of traces to return (default 100)

        Returns:
            List of trace records with outcome, duration_ms, selector, component_name
        """
        # Input validation (C3)
        if not task_class or not isinstance(task_class, str):
            logger.error("query_local_traces: task_class must be a non-empty string")
            return []
        if (
            not isinstance(time_range_minutes, int)
            or time_range_minutes <= 0
            or time_range_minutes > 10080
        ):
            logger.error("query_local_traces: time_range_minutes must be 1-10080 (1 week max)")
            return []
        if not isinstance(limit, int) or limit <= 0 or limit > 1000:
            logger.error("query_local_traces: limit must be 1-1000")
            return []

        try:
            from datetime import UTC, datetime, timedelta

            from akosha.storage import HotStore

            # Calculate start_time from time_range_minutes
            end_time = datetime.now(UTC)
            start_time = end_time - timedelta(minutes=time_range_minutes)

            # Initialize HotStore
            hot_store = HotStore(database_path=app.config.otel_ingester.hot_store_path)
            await hot_store.initialize()

            try:
                # Use SQL WHERE filtering (query_traces) instead of zero-vector
                # semantic search — pushes task_class, time_range, and system_id
                # into the SQL WHERE clause for efficient attribute filtering (C2/H7)
                results = await hot_store.query_traces(
                    system_id=system_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    task_class=task_class,
                    limit=limit,
                )
            finally:
                # Always close hot_store, whether query succeeded or not (C1)
                await hot_store.close()

            # Normalize result format for fitness analyzer consumption
            # FitnessAnalyzer expects: outcome, duration_ms, selector, component_name
            normalized = []
            for r in results:
                # Parse metadata JSON (may be str or dict per HotStore schema)
                import json

                metadata_raw = r.get("metadata", "{}")
                if isinstance(metadata_raw, str):
                    try:
                        attrs = json.loads(metadata_raw).get("attributes", {})
                    except json.JSONDecodeError:
                        attrs = {}
                else:
                    attrs = (
                        metadata_raw.get("attributes", {}) if isinstance(metadata_raw, dict) else {}
                    )

                normalized.append(
                    {
                        "outcome": attrs.get("outcome", "unknown"),
                        "duration_ms": attrs.get("duration_ms", 0),
                        "selector": attrs.get("selector", "unknown"),
                        "component_name": system_id or r.get("system_id", "unknown"),
                        "task_class": task_class,
                        "timestamp": str(r.get("timestamp", "")),
                    }
                )

            logger.info(
                f"query_local_traces returned {len(normalized)} records for task_class={task_class}"
            )
            return normalized

        except ImportError:
            logger.error("HotStore not available for query_local_traces")
            return []
        except Exception as e:
            logger.exception(f"Error querying traces: {e}")
            return []

    @server.tool()
    async def otel_ingester_stats() -> dict[str, Any]:
        """Get statistics about the OTel trace ingester."""
        try:
            from akosha.storage import HotStore

            # Initialize HotStore to query statistics
            hot_store = HotStore(database_path=app.config.otel_ingester.hot_store_path)
            await hot_store.initialize()

            # Query total traces (basic implementation)
            # Note: DuckDB doesn't expose count directly without SQL query
            tq_bits = app.config.otel_ingester.turboquant_bits
            stats = {
                "storage_backend": "duckdb_hotstore",
                "hot_store_path": app.config.otel_ingester.hot_store_path,
                "embedding_model": app.config.otel_ingester.embedding_model,
                "cache_size": app.config.otel_ingester.cache_size,
                "similarity_threshold": app.config.otel_ingester.similarity_threshold,
                "turboquant_bits": tq_bits,
                "turboquant_compression": tq_bits is not None,
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

    logger.info("Registered 5 OTel trace tools (Akosha HotStore backend)")
