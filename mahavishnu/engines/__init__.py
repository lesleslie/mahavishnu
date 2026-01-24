"""Engines module for Mahavishnu orchestrator."""
# Adapters are imported individually by the app when needed to avoid dependency issues

from .prefect_adapter import PrefectAdapter
from .agno_adapter import AgnoAdapter
from .llamaindex_adapter import LlamaIndexAdapter

__all__ = [
    "PrefectAdapter",       # Stub implementation (143 lines)
    "AgnoAdapter",          # Stub implementation (116 lines)
    "LlamaIndexAdapter",    # Fully implemented (348 lines)
]