"""LlamaIndex adapter for RAG orchestration.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.engines.llamaindex_adapter`` instead.

    To migrate, change imports from::

        from mahavishnu.adapters.rag.llamaindex_adapter import LlamaIndexAdapter

    To::

        from mahavishnu.engines.llamaindex_adapter import LlamaIndexAdapter

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "mahavishnu.adapters.rag.llamaindex_adapter is deprecated. "
    "Import from mahavishnu.engines.llamaindex_adapter instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

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
