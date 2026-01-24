# Adapters

Mahavishnu supports multiple orchestration engines through adapters. Each adapter provides a unified interface to different workflow engines.

**Current Status**: All adapters are stub/skeleton implementations. Actual orchestration logic is not yet implemented.

## Available Adapters

- [LlamaIndex](llamaindex.md): RAG pipelines for knowledge bases (Stub - 348 lines)
- [Prefect](prefect.md): General workflow orchestration (Stub - 143 lines)
- [Agno](agno.md): Experimental AI agent runtime (Stub - 116 lines)

## Adapter Selection

Choose the right adapter for your use case:

- **LlamaIndex**: Best for RAG (Retrieval-Augmented Generation) pipelines and semantic search
- **Prefect**: Best for general workflow orchestration and ETL pipelines
- **Agno**: For evaluating next-generation agent runtimes (experimental)

**Note**: All adapters currently return simulated results. Real orchestration functionality requires LLM integration and state management implementation.

## Configuration

Enable adapters in your configuration:

```yaml
adapters:
  llamaindex: true
  prefect: true
  agno: false  # Experimental
```

## Implementation Status

### LlamaIndex Adapter
- **Status**: Stub implementation (348 lines)
- **Missing**: LLM provider integration, document chunking, vector embeddings, semantic search

### Prefect Adapter
- **Status**: Stub implementation (143 lines)
- **Missing**: LLM integration, flow construction, state management, checkpointing

### Agno Adapter
- **Status**: Stub implementation (116 lines)
- **Missing**: Agent lifecycle, tool integration, multi-LLM routing

## Estimated Implementation Effort

- LlamaIndex: 2-3 weeks
- Prefect: 2 weeks
- Agno: 2-3 weeks

**Total**: 6-9 weeks for all three adapters

## Next Steps

1. Implement LLM provider integration (OpenAI, Anthropic, Gemini, Ollama)
2. Add actual workflow execution logic
3. Implement state management across repos
4. Add comprehensive error handling
5. Implement progress tracking and streaming

See [UNIFIED_IMPLEMENTATION_STATUS.md](../../UNIFIED_IMPLEMENTATION_STATUS.md) for detailed progress tracking.
