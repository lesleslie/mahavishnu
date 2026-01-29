# mcp-common

Shared infrastructure package for Session Buddy and Mahavishnu projects.

## Overview

This package contains shared components that are used by both Session Buddy and Mahavishnu:

- Code graph analysis tools
- Shared messaging types
- MCP contracts
- Common utilities

## Installation

```bash
uv pip install -e .
```

## Development

```bash
# Run tests
pytest mcp_common/tests/

# Format code
ruff format mcp_common/

# Lint code
ruff check mcp_common/
```
