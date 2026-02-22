"""Mahavishnu data ingesters for various telemetry sources.

This module provides ingesters for converting external telemetry data
into Mahavishnu's internal storage format (Akosha HotStore or PostgreSQL + pgvector).

Available ingesters:
    - OtelIngester: OpenTelemetry trace ingestion with semantic search
        - DuckDB storage: Fast local development, in-memory
        - PostgreSQL + pgvector: Production persistence with HNSW indexing
    - ContentIngester: Ingest blogs, webpages, and books into knowledge ecosystem

Example:
    >>> from mahavishnu.ingesters import OtelIngester, ContentIngester, StorageType
    >>>
    >>> # OTel traces with DuckDB (development)
    >>> otel = OtelIngester(storage_type=StorageType.DUCKDB)
    >>> await otel.initialize()
    >>> await otel.ingest_trace(trace_data)
    >>> results = await otel.search_traces("error handling")
    >>> await otel.close()
    >>>
    >>> # OTel traces with PostgreSQL (production)
    >>> otel = OtelIngester(
    ...     storage_type=StorageType.POSTGRESQL,
    ...     pgvector_dsn="postgresql://user:pass@localhost/mahavishnu"
    ... )
    >>>
    >>> # Web content
    >>> content = ContentIngester()
    >>> await content.initialize()
    >>> result = await content.ingest_url("https://blog.example.com/post")
    >>> await content.close()
"""

from mahavishnu.ingesters.content_ingester import (
    ContentIngester,
    ContentType,
    IngestionResult,
    create_content_ingester,
)
from mahavishnu.ingesters.otel_ingester import (
    AkoshaEmbedder,
    EmbeddingBackend,
    OtelIngester,
    StorageType,
    create_otel_ingester,
)
from mahavishnu.ingesters.quality_evaluator import (
    QualityEvaluator,
    EvaluationReport,
    MetricScore,
    QualityMetric,
    create_quality_evaluator,
)

__all__ = [
    "AkoshaEmbedder",
    "OtelIngester",
    "create_otel_ingester",
    "StorageType",
    "EmbeddingBackend",
    "ContentIngester",
    "ContentType",
    "IngestionResult",
    "create_content_ingester",
    "QualityEvaluator",
    "EvaluationReport",
    "MetricScore",
    "QualityMetric",
    "create_quality_evaluator",
]
