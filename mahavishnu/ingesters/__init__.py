"""Mahavishnu data ingesters for various telemetry sources.

This module provides ingesters for converting external telemetry data
into Mahavishnu's internal storage format (Akosha HotStore).

Available ingesters:
    - OtelIngester: OpenTelemetry trace ingestion with semantic search

Example:
    >>> from mahavishnu.ingesters import OtelIngester
    >>> ingester = OtelIngester()
    >>> await ingester.initialize()
    >>> await ingester.ingest_trace(trace_data)
    >>> results = await ingester.search_traces("error handling")
    >>> await ingester.close()
"""

from mahavishnu.ingesters.otel_ingester import OtelIngester, create_otel_ingester

__all__ = ["OtelIngester", "create_otel_ingester"]
