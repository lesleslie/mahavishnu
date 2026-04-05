"""Hybrid search module combining semantic (pgvector) and lexical (PostgreSQL full-text) search.

This module provides:
- HybridSearchEngine: Main search engine combining semantic and lexical search
- HybridSearchConfig: Configuration for search weights and thresholds
- HybridSearchResult: Search result model with combined scores

Usage:
    from mahavishnu.core.search import HybridSearchEngine, HybridSearchConfig

    config = HybridSearchConfig(semantic_weight=0.7, lexical_weight=0.3)
    engine = HybridSearchEngine(connection_pool, config=config)

    results = await engine.search(
        query="API implementation",
        repository="mahavishnu",
        limit=20
    )
"""

from mahavishnu.core.search.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)

__all__ = [
    "HybridSearchConfig",
    "HybridSearchEngine",
    "HybridSearchResult",
]
