"""Mahavishnu orchestration adapters package.

Provides adapters for different workflow orchestration engines:
- Prefect: Workflow orchestration with Prefect Cloud
- Agno: Multi-agent AI task execution
- Pydantic-AI: Type-safe agent orchestration with structured outputs
- LlamaIndex: RAG pipeline orchestration
- Pgvector: Production vector storage with HNSW indexing

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
from mahavishnu.adapters.ai.pydantic_ai_adapter import (
    AgentResult,
    AgentStatus,
    FallbackStrategy,
    MCPToolConfig,
    ModelConfig,
    PydanticAIAdapter,
    PydanticAISettings,
)
from mahavishnu.adapters.pgvector_adapter import (
    HNSWConfig,
    IVFFlatConfig,
    IndexType,
    PgvectorAdapter,
    PgvectorSettings,
)
from mahavishnu.adapters.rag.llamaindex_adapter import LlamaIndexAdapter

__all__ = [
    "AgentResult",
    "AgentStatus",
    "AgnoAdapter",
    "FallbackStrategy",
    "HNSWConfig",
    "IVFFlatConfig",
    "IndexType",
    "LlamaIndexAdapter",
    "MCPToolConfig",
    "ModelConfig",
    "PgvectorAdapter",
    "PgvectorSettings",
    "PydanticAIAdapter",
    "PydanticAISettings",
]

# Only add PrefectAdapter if available
if _prefect_available:
    __all__.append("PrefectAdapter")
