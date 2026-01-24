# Adapters

Mahavishnu supports multiple orchestration engines through adapters. Each adapter provides a unified interface to different workflow engines.

## Available Adapters

- [LangGraph](langgraph.md): For AI agent workflows with state management
- [Prefect](prefect.md): For general workflow orchestration
- [Agno](agno.md): For experimental AI agent runtime

## Adapter Selection

Choose the right adapter for your use case:

- **LangGraph**: Best for AI agent workflows with complex state management
- **Prefect**: Best for general workflow orchestration and ETL pipelines
- **Agno**: For evaluating next-generation agent runtimes (experimental)

## Configuration

Enable adapters in your configuration:

```yaml
adapters:
  langgraph: true
  prefect: true
  agno: false  # Experimental
```

## Performance Considerations

Each adapter has different performance characteristics:

- **LangGraph**: Higher overhead for complex state management
- **Prefect**: Optimized for general workflows
- **Agno**: Experimental with evolving performance profile