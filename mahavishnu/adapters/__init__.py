"""Mahavishnu orchestration adapters package.

Provides adapters for different workflow orchestration engines:
- Prefect: Workflow orchestration with Prefect Cloud
- Agno: Multi-agent AI task execution
- LlamaIndex: RAG pipeline orchestration

Each adapter implements the OrchestratorAdapter interface.

Note: PrefectAdapter is now imported from the engines module.
The adapters.workflow.prefect_adapter module is deprecated.
"""

# Import PrefectAdapter from engines module (preferred location)
try:
    from mahavishnu.engines.prefect_adapter import PrefectAdapter
    _prefect_available = True
except ImportError:
    PrefectAdapter = None  # type: ignore[misc,assignment]
    _prefect_available = False

from mahavishnu.adapters.ai.agno_adapter import AgnoAdapter
from mahavishnu.adapters.rag.llamaindex_adapter import LlamaIndexAdapter

__all__ = [
    "AgnoAdapter",
    "LlamaIndexAdapter",
]

# Only add PrefectAdapter if available
if _prefect_available:
    __all__.append("PrefectAdapter")
