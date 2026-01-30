# Adapters

Mahavishnu provides three orchestration adapters through a unified interface.

**Current Status**: One fully implemented (LlamaIndex), two stub implementations (Prefect, Agno).

## Available Adapters

- [LlamaIndex](llamaindex.md): RAG pipelines for knowledge bases (Fully implemented - 348 lines)
- [Prefect](prefect.md): General workflow orchestration (Stub - 143 lines)
- [Agno](agno.md): AI agent runtime (Stub - 116 lines)

## Adapter Selection

Choose the right adapter for your use case:

- **LlamaIndex**: Best for RAG (Retrieval-Augmented Generation) pipelines and semantic search. Fully functional with Ollama embeddings.
- **Prefect**: Best for general workflow orchestration and ETL pipelines. Stub only - returns simulated results.
- **Agno**: For multi-agent workflows with memory and tools. Stub only - returns simulated results.

## Configuration

Enable adapters in your configuration:

```yaml
adapters:
  llamaindex: true  # Fully functional
  prefect: true     # Stub implementation
  agno: false       # Stub implementation (experimental)
```

## Implementation Status

### LlamaIndex Adapter

- **Status**: Fully implemented (348 lines)
- **Capabilities**: Real Ollama integration, vector embeddings, semantic search
- **Ready for production use**

### Prefect Adapter

- **Status**: Stub implementation (143 lines)
- **Missing**: LLM integration, flow construction, state management, checkpointing
- **Estimated**: 2 weeks to complete

### Agno Adapter

- **Status**: Stub implementation (116 lines)
- **Missing**: Agent lifecycle, tool integration, multi-LLM routing
- **Estimated**: 2-3 weeks to complete (waiting for Agno v2.0 stable release)

## Estimated Implementation Effort

- Prefect: 2 weeks
- Agno: 2-3 weeks
- LlamaIndex: Complete

**Total**: 4-5 weeks to have all three adapters functional

## Next Steps

1. Complete Prefect adapter with flow construction and state management
1. Complete Agno adapter with agent lifecycle and tool integration
1. Add comprehensive error handling to both adapters
1. Implement progress tracking and streaming
