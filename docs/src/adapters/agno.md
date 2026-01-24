# Agno Adapter

The Agno adapter provides integration with Agno for experimental AI agent runtime.

## Overview

Agno is an experimental multi-agent system with AgentOS runtime. This adapter is in evaluation phase.

## Configuration

```yaml
agno:
  enabled: false  # Experimental
  runtime: "local"
  agent_os_enabled: true
  timeout: 300
```

## Usage

```bash
mahavishnu sweep --tag agent --adapter agno
```

## Features

- Fast execution
- Minimalist design
- Python-first approach
- Multi-agent system support

## Best Practices

- Use for evaluating next-gen agent runtimes
- Monitor experimental features carefully
- Expect breaking changes in future versions
- Consider for proof-of-concept projects