"""Mahavishnu data ingesters for various telemetry sources.

This module provides ingesters for converting external telemetry data
into Mahavishnu's internal storage format (Akosha HotStore).

Available ingesters:
    - OtelIngester: OpenTelemetry trace ingestion with semantic search
    - ContentIngester: Ingest blogs, webpages, and books into knowledge ecosystem

Example:
    >>> from mahavishnu.ingesters import OtelIngester, ContentIngester
    >>>
    >>> # OTel traces
    >>> otel = OtelIngester()
    >>> await otel.initialize()
    >>> await otel.ingest_trace(trace_data)
    >>> results = await otel.search_traces("error handling")
    >>> await otel.close()
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
from mahavishnu.ingesters.otel_ingester import OtelIngester, create_otel_ingester
from mahavishnu.ingesters.quality_evaluator import (
    QualityEvaluator,
    EvaluationReport,
    MetricScore,
    QualityMetric,
    create_quality_evaluator,
)

__all__ = [
    "OtelIngester",
    "create_otel_ingester",
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
