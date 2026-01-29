# LangGraph Adapter

The LangGraph adapter provides integration with LangGraph for AI agent workflows.

## Overview

LangGraph is ideal for creating complex AI agent workflows with state management and human-in-the-loop capabilities.

## Configuration

```yaml
langgraph:
  enabled: true
  llm_provider: "openai"
  llm_model: "gpt-4o"
  llm_temperature: 0.1
  llm_timeout: 30
```

## Usage

```bash
mahavishnu sweep --tag agent --adapter langgraph
```

## Features

- Stateful agent workflows
- Human-in-the-loop interactions
- Multi-agent coordination
- Production-ready for complex AI workflows

## Best Practices

- Use for complex multi-agent systems
- Leverage state management for conversations
- Implement proper error handling
- Monitor token usage for cost control
