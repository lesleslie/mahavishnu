"""LlamaIndex adapter for RAG orchestration.

Re-exports from the full implementation in engines module.
This module provides backward compatibility for imports from the
adapters.rag location while delegating to the complete implementation.

Usage:
    from mahavishnu.adapters.rag.llamaindex_adapter import (
        LlamaIndexAdapter,
        LlamaIndexIngestionError,
        LlamaIndexQueryError,
        LlamaIndexIndexNotFoundError,
        LlamaIndexEmbeddingError,
    )

Or directly from engines:
    from mahavishnu.engines.llamaindex_adapter import LlamaIndexAdapter
"""

from mahavishnu.engines.llamaindex_adapter import (
    LlamaIndexAdapter,
    LlamaIndexEmbeddingError,
    LlamaIndexIndexNotFoundError,
    LlamaIndexIngestionError,
    LlamaIndexQueryError,
)

__all__ = [
    "LlamaIndexAdapter",
    "LlamaIndexIngestionError",
    "LlamaIndexQueryError",
    "LlamaIndexIndexNotFoundError",
    "LlamaIndexEmbeddingError",
]
